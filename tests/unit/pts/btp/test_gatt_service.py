"""GattService skeleton — registration + bound IutActions/tester accessors."""
from unittest.mock import MagicMock

from pybluehost.ble.gatt import (
    ATT_ERR_INSUFFICIENT_AUTHENTICATION,
    ATT_ERR_INSUFFICIENT_AUTHORIZATION,
    ATT_ERR_INSUFFICIENT_ENC_KEY_SIZE,
    PERM_READ_AUTHZ,
    PERM_READ_ENC,
)
from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.base import BtpServiceRegistry
from pybluehost.pts.btp.services.gatt import GattService


def test_gatt_service_id_matches_constant():
    assert GattService.SERVICE_ID == op.SERVICE_GATT


def test_gatt_service_registers_in_registry():
    reg = BtpServiceRegistry()
    actions = MagicMock()
    tester = MagicMock()
    svc = GattService(actions=actions, tester=tester)
    reg.register(svc)
    assert reg.get(op.SERVICE_GATT) is svc


def test_gatt_service_stores_actions_and_tester():
    actions = MagicMock()
    tester = MagicMock()
    svc = GattService(actions=actions, tester=tester)
    assert svc._actions is actions
    assert svc._tester is tester


def _le16(uuid_hex: str) -> bytes:
    """'AA40' -> little-endian 2-byte BTP uuid body."""
    raw = bytes.fromhex(uuid_hex)
    return raw[::-1]


async def test_gatt_server_db_built_via_btp_init_sequence():
    """Drive the auto-pts GATT/SR init_server BTP sequence and confirm the db
    is committed to the real GATTServer on START_SERVER.

    Regression for the empty-db bug: the IUT hosted no services, so every
    GATT/SR case failed discovery. Exercises ADD_SERVICE / ADD_CHARACTERISTIC /
    ADD_INCLUDED_SERVICE (0x05, newly added) / SET_VALUE / START_SERVER.
    """
    from pybluehost.ble.gatt import GATTServer
    from pybluehost.core.uuid import UUID16

    stack = MagicMock()
    stack.gatt_server = GATTServer()
    actions = MagicMock()
    actions._stack = stack
    svc = GattService(actions=actions, tester=MagicMock())

    async def add_svc(svc_type: int, uuid_hex: str):
        body = bytes([svc_type]) + bytes([2]) + _le16(uuid_hex)
        status, rsp = await svc.dispatch(
            opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=body)
        assert status == op.BTP_STATUS_SUCCESS
        return int.from_bytes(rsp, "little")

    async def add_char(svc_handle: int, props: int, perms: int, uuid_hex: str):
        body = (svc_handle.to_bytes(2, "little") + bytes([props, perms])
                + bytes([2]) + _le16(uuid_hex))
        status, rsp = await svc.dispatch(
            opcode=op.OP_GATT_ADD_CHARACTERISTIC, controller_index=0, data=body)
        assert status == op.BTP_STATUS_SUCCESS
        return int.from_bytes(rsp, "little")

    # SVND16_0 (secondary) with one read/write char (VND16_0).
    await add_svc(1, "AA40")
    await add_char(0, 0x02 | 0x08, 0x01 | 0x02, "AA50")
    # SVND16_1 (primary) that includes service handle 1, plus one char.
    await add_svc(0, "AA41")
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_ADD_INCLUDED_SERVICE, controller_index=0,
        data=(1).to_bytes(2, "little"))
    assert status == op.BTP_STATUS_SUCCESS, "ADD_INCLUDED_SERVICE must succeed"
    await add_char(0, 0x02 | 0x08, 0x01 | 0x02, "AA50")

    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_START_SERVER, controller_index=0, data=b"")
    assert status == op.BTP_STATUS_SUCCESS

    # Both primary services discoverable in the committed db.
    prim = stack.gatt_server.db.find_by_group_type(
        0x0001, 0xFFFF, UUID16(0x2800))
    assert len(prim) >= 1, "no primary service committed to GATTServer"


async def test_gatt_add_included_service_materialises_the_include_declaration():
    """ADD_INCLUDED_SERVICE must reach the on-air db as a 0x2802 attribute.

    GATT/SR/GAS/BV-02 (Database Hash): a client discovers secondary services
    only through Include declarations, so dropping the include hid the whole
    secondary service from PTS and its hash disagreed with ours.
    """
    from pybluehost.ble.gatt import GATTServer, UUID_INCLUDE
    from pybluehost.core.uuid import UUID16

    stack = MagicMock()
    stack.gatt_server = GATTServer()
    actions = MagicMock()
    actions._stack = stack
    svc = GattService(actions=actions, tester=MagicMock())

    async def add_svc(svc_type: int, uuid_hex: str) -> int:
        body = bytes([svc_type, 2]) + _le16(uuid_hex)
        _, rsp = await svc.dispatch(
            opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=body)
        return int.from_bytes(rsp, "little")

    async def add_char(props: int, perms: int, uuid_hex: str) -> int:
        body = ((0).to_bytes(2, "little") + bytes([props, perms, 2])
                + _le16(uuid_hex))
        _, rsp = await svc.dispatch(
            opcode=op.OP_GATT_ADD_CHARACTERISTIC, controller_index=0, data=body)
        return int.from_bytes(rsp, "little")

    secondary = await add_svc(1, "AA40")
    await add_char(0x02 | 0x08, 0x01 | 0x02, "AA50")
    primary = await add_svc(0, "AA41")
    status, inc_rsp = await svc.dispatch(
        opcode=op.OP_GATT_ADD_INCLUDED_SERVICE, controller_index=0,
        data=secondary.to_bytes(2, "little"))
    assert status == op.BTP_STATUS_SUCCESS
    await add_char(0x02 | 0x08, 0x01 | 0x02, "AA50")

    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_START_SERVER, controller_index=0, data=b"")
    assert status == op.BTP_STATUS_SUCCESS

    db = stack.gatt_server.db
    inc_handle = int.from_bytes(inc_rsp, "little")
    inc_attr = db.get(inc_handle)
    assert inc_attr is not None, "include declaration missing from the db"
    assert inc_attr.type_uuid.to_bytes() == UUID_INCLUDE.to_bytes()
    # Value = start_handle(2 LE) + end_handle(2 LE) + included service UUID.
    secondary_end = db.find_by_group_type(
        secondary, 0xFFFF, UUID16(0x2801))[0][1]
    assert inc_attr.value == (
        secondary.to_bytes(2, "little")
        + secondary_end.to_bytes(2, "little")
        + _le16("AA40")
    ), f"include value {inc_attr.value.hex()}"
    # Emitted between the service declaration and the first characteristic.
    assert inc_handle == primary + 1


async def test_gatt_add_included_service_unknown_target_fails():
    actions = MagicMock()
    svc = GattService(actions=actions, tester=MagicMock())
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_ADD_INCLUDED_SERVICE, controller_index=0,
        data=(0x1234).to_bytes(2, "little"))
    assert status == op.BTP_STATUS_FAILED


async def test_gatt_get_attributes_reads_committed_db():
    """GET_ATTRIBUTES (0x1c) must enumerate the committed GATTServer db so the
    auto-pts GATT/SR discovery WID handlers can verify exposed services."""
    from pybluehost.ble.gatt import GATTServer
    from pybluehost.core.uuid import UUID16

    stack = MagicMock()
    stack.gatt_server = GATTServer()
    actions = MagicMock()
    actions._stack = stack
    svc = GattService(actions=actions, tester=MagicMock())

    # Build one primary service (SVND16_1 'AA41') with one char, then start.
    body = bytes([0]) + bytes([2]) + _le16("AA41")
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=body)
    assert status == op.BTP_STATUS_SUCCESS
    char_body = ((0).to_bytes(2, "little") + bytes([0x0A, 0x03])
                 + bytes([2]) + _le16("AA50"))
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_ADD_CHARACTERISTIC, controller_index=0, data=char_body)
    assert status == op.BTP_STATUS_SUCCESS
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_START_SERVER, controller_index=0, data=b"")
    assert status == op.BTP_STATUS_SUCCESS

    # Query primary services (type 0x2800) across the full handle range.
    req = ((1).to_bytes(2, "little") + (0xFFFF).to_bytes(2, "little")
           + bytes([2]) + _le16("2800"))
    status, rsp = await svc.dispatch(
        opcode=op.OP_GATT_GET_ATTRIBUTES, controller_index=0, data=req)
    assert status == op.BTP_STATUS_SUCCESS
    count = rsp[0]
    # vendor service (committed first, lowest handle) + auto-hosted GAP (0x1800)
    # and GATT (0x1801) standard services = 3 primary services.
    assert count == 3, f"expected 3 primary services (vendor + GAP + GATT), got {count}"
    # Entry: handle(2 LE) + perm(1) + type_len(1) + type(2 LE). The attribute
    # *type* of a primary-service declaration is 0x2800; the service's own UUID
    # lives in its value (read back via GET_ATTRIBUTE_VALUE below). The vendor
    # service was committed first, so it holds the lowest handle.
    handle = int.from_bytes(rsp[1:3], "little")
    assert handle >= 1
    assert rsp[4] == 2                      # type_length = UUID16
    assert rsp[5:7] == _le16("2800")        # declaration type, LE on the wire

    # Step 2 of the WID-handler flow: read the declaration's value -> svc UUID.
    val_req = bytes([0]) + bytes(6) + handle.to_bytes(2, "little")
    status, rsp = await svc.dispatch(
        opcode=op.OP_GATT_GET_ATTRIBUTE_VALUE, controller_index=0, data=val_req)
    assert status == op.BTP_STATUS_SUCCESS
    assert rsp[0] == 0x00                   # ATT success
    val_len = int.from_bytes(rsp[1:3], "little")
    assert rsp[3:3 + val_len] == _le16("AA41")


# --- GET_ATTRIBUTE_VALUE must report the link-security gate (WID 112/113/121/122)

_PEER_DISPLAY = "94:53:FF:1E:6A:EE"
_CONN_HANDLE = 0x0005


def _peer_wire() -> bytes:
    """BDAddress display order -> the little-endian form auto-pts puts on BTP."""
    return bytes.fromhex(_PEER_DISPLAY.replace(":", ""))[::-1]


async def _server_with_char(perms: int, *, enc_key_size: int = 0):
    """Build a one-characteristic db and commit it; return (svc, stack, value_handle).

    Mirrors the auto-pts GATT/SR ``init_server`` sequence: ADD_SERVICE ->
    ADD_CHARACTERISTIC -> (SET_ENC_KEY_SIZE) -> START_SERVER.
    """
    from pybluehost.ble.gatt import GATTServer

    stack = MagicMock()
    stack.gatt_server = GATTServer()
    actions = MagicMock()
    actions._stack = stack
    svc = GattService(actions=actions, tester=MagicMock())

    body = bytes([0]) + bytes([2]) + _le16("AA41")
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=body)
    assert status == op.BTP_STATUS_SUCCESS
    char_body = ((0).to_bytes(2, "little") + bytes([0x0A, perms])
                 + bytes([2]) + _le16("AA50"))
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_ADD_CHARACTERISTIC, controller_index=0, data=char_body)
    assert status == op.BTP_STATUS_SUCCESS
    if enc_key_size:
        status, _ = await svc.dispatch(
            opcode=op.OP_GATT_SET_ENC_KEY_SIZE, controller_index=0,
            data=(0).to_bytes(2, "little") + bytes([enc_key_size]))
        assert status == op.BTP_STATUS_SUCCESS
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_START_SERVER, controller_index=0, data=b"")
    assert status == op.BTP_STATUS_SUCCESS

    # The value attribute of the characteristic is the one typed by its own UUID.
    req = ((1).to_bytes(2, "little") + (0xFFFF).to_bytes(2, "little")
           + bytes([2]) + _le16("AA50"))
    status, rsp = await svc.dispatch(
        opcode=op.OP_GATT_GET_ATTRIBUTES, controller_index=0, data=req)
    assert status == op.BTP_STATUS_SUCCESS
    assert rsp[0] == 1, f"expected exactly 1 value attribute, got {rsp[0]}"
    return svc, stack, int.from_bytes(rsp[1:3], "little")


async def _read_value(svc, handle: int):
    """GET_ATTRIBUTE_VALUE for `handle`, addressed by the peer's wire address."""
    return await svc.dispatch(
        opcode=op.OP_GATT_GET_ATTRIBUTE_VALUE, controller_index=0,
        data=bytes([0]) + _peer_wire() + handle.to_bytes(2, "little"))


async def test_get_attribute_value_reports_insufficient_authorization():
    """A read_authz characteristic must answer 0x08 — auto-pts WID 112/113 pick
    their target handle by matching exactly this ATT error code."""
    svc, stack, handle = await _server_with_char(PERM_READ_AUTHZ)

    status, rsp = await _read_value(svc, handle)

    assert status == op.BTP_STATUS_SUCCESS
    assert rsp[0] == ATT_ERR_INSUFFICIENT_AUTHORIZATION, (
        f"expected 0x08 for a read_authz characteristic, got 0x{rsp[0]:02X}")
    assert int.from_bytes(rsp[1:3], "little") == 0


async def test_get_attribute_value_defaults_to_unsecured_for_absent_peer():
    """GET_ATTRIBUTE_VALUE is a pure db query, so PTS calls it while the peer may
    not be connected; an absent peer gets the default (unsecured) link state."""
    svc, stack, handle = await _server_with_char(PERM_READ_AUTHZ)

    status, rsp = await _read_value(svc, handle)

    assert status == op.BTP_STATUS_SUCCESS
    assert rsp[0] == ATT_ERR_INSUFFICIENT_AUTHORIZATION


async def test_get_attribute_value_reports_key_size_error_on_short_encrypted_link():
    """WID 121/122 look for 0x0C, which needs an *encrypted* link whose key is
    shorter than the characteristic demands (auto-pts sets the demand with
    SET_ENC_KEY_SIZE)."""
    svc, stack, handle = await _server_with_char(PERM_READ_ENC, enc_key_size=15)
    stack.gatt_server.set_connection_security(
        _CONN_HANDLE, encrypted=True, authenticated=True, key_size=7)
    _attach_peer(svc, stack)

    status, rsp = await _read_value(svc, handle)

    assert status == op.BTP_STATUS_SUCCESS
    assert rsp[0] == ATT_ERR_INSUFFICIENT_ENC_KEY_SIZE, (
        f"expected 0x0C for a 7-byte key on an enc_key_size=15 char, "
        f"got 0x{rsp[0]:02X}")


async def test_get_attribute_value_returns_value_when_gate_is_satisfied():
    """A link that satisfies the security level gets the real value (0x00)."""
    svc, stack, handle = await _server_with_char(PERM_READ_ENC, enc_key_size=15)
    stack.gatt_server.set_connection_security(
        _CONN_HANDLE, encrypted=True, authenticated=True, key_size=16)
    _attach_peer(svc, stack)

    status, rsp = await _read_value(svc, handle)

    assert status == op.BTP_STATUS_SUCCESS
    assert rsp[0] == 0x00, f"expected the value, got ATT error 0x{rsp[0]:02X}"


async def test_get_attribute_value_reports_authentication_for_unpaired_enc_link():
    """An unpaired link is told to PAIR (0x05), not that encryption is missing —
    GAP Vol 3 Part C §10.3; see GATTServer._read_error."""
    svc, stack, handle = await _server_with_char(PERM_READ_ENC)
    stack.gatt_server.set_connection_security(
        _CONN_HANDLE, encrypted=False, authenticated=False, key_size=0)
    _attach_peer(svc, stack)

    status, rsp = await _read_value(svc, handle)

    assert status == op.BTP_STATUS_SUCCESS
    assert rsp[0] == ATT_ERR_INSUFFICIENT_AUTHENTICATION


def _attach_peer(svc, stack) -> None:
    """Register a live LE connection to _PEER_DISPLAY in the service's session."""
    from pybluehost.core.address import BDAddress
    from pybluehost.pts.actions import ConnInfo, IutSession

    svc._actions.status.return_value = IutSession(connections={
        _CONN_HANDLE: ConnInfo(
            handle=_CONN_HANDLE,
            peer=BDAddress.from_string(_PEER_DISPLAY),
            transport="le",
        ),
    })




async def test_start_server_triggers_service_changed_indication():
    """GAS/BV-06 WID 136: a mid-test START_SERVER (add service) must mark the
    database changed and indicate Service Changed so the Lower Tester gets the
    indication it is waiting for (the initial build is a no-op — no client)."""
    from pybluehost.ble.gatt import GATTServer
    from pybluehost.core.uuid import UUID16

    stack = MagicMock()
    server = GATTServer()
    stack.gatt_server = server
    actions = MagicMock()
    actions._stack = stack
    svc = GattService(actions=actions, tester=MagicMock())

    # Initial build (pre_conditions _init_server).
    body = bytes([0]) + bytes([2]) + _le16("AA41")
    await svc.dispatch(opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=body)
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_START_SERVER, controller_index=0, data=b"")
    assert status == op.BTP_STATUS_SUCCESS

    # A connected client subscribed to the Service Changed characteristic.
    indicated = []
    server.on_indication_sent(lambda h, v, c: indicated.append((h, v, c)) or True)
    sc_handle = server.find_characteristic_value_handle(UUID16(0x2A05))
    server._indications_enabled[0x0001] = {sc_handle}

    # Second START_SERVER (WID 136): must resend the Service Changed indication.
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_START_SERVER, controller_index=0, data=b"")
    assert status == op.BTP_STATUS_SUCCESS
    assert indicated, "START_SERVER must resend the Service Changed indication"
    assert indicated[0][0] == sc_handle


async def test_notify_multiple_parses_body_and_calls_server():
    """NOTIFY_MULTIPLE (0x21) resolves the peer handle and asks the GATT server
    to send the 0x23 notification with the requested handles."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    class _Peer:
        def to_hci(self):
            return b"\x11\x22\x33\x44\x55\x66"

    actions = MagicMock()
    actions.status.return_value = SimpleNamespace(connections={
        0x0001: SimpleNamespace(transport="le", peer=_Peer()),
    })
    server = MagicMock()
    server.notify_multiple = AsyncMock()
    actions._stack = SimpleNamespace(gatt_server=server)
    svc = GattService(actions=actions, tester=MagicMock())

    body = (bytes([0x00]) + b"\x11\x22\x33\x44\x55\x66"
            + (2).to_bytes(2, "little")
            + (0x0001).to_bytes(2, "little") + (0x0003).to_bytes(2, "little"))
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_NOTIFY_MULTIPLE, controller_index=0, data=body)

    assert status == op.BTP_STATUS_SUCCESS
    server.notify_multiple.assert_awaited_once_with(0x0001, [0x0001, 0x0003])


async def _server_with_notify_char():
    """Build one NOTIFY characteristic through the auto-pts BTP sequence.

    Returns ``(svc, server, value_handle)`` with the db committed (START_SERVER
    auto-adds the CCCD for a notify characteristic)."""
    from pybluehost.ble.gatt import GATTServer
    from pybluehost.core.uuid import UUID16

    stack = MagicMock()
    stack.gatt_server = GATTServer()
    actions = MagicMock()
    actions._stack = stack
    svc = GattService(actions=actions, tester=MagicMock())

    body = bytes([0]) + bytes([2]) + _le16("AA41")
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=body)
    assert status == op.BTP_STATUS_SUCCESS
    char_body = ((0).to_bytes(2, "little") + bytes([0x12, 0x01, 2])
                 + _le16("AA50"))
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_ADD_CHARACTERISTIC, controller_index=0, data=char_body)
    assert status == op.BTP_STATUS_SUCCESS
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_START_SERVER, controller_index=0, data=b"")
    assert status == op.BTP_STATUS_SUCCESS

    server = stack.gatt_server
    value_handle = server.find_characteristic_value_handle(UUID16(0xAA50))
    assert value_handle is not None
    return svc, server, value_handle


async def test_set_value_notifies_the_subscribed_connection():
    """GATT/SR/GAN/BV-01: SET_VALUE is the Upper Tester's only lever for making
    the server send a notification. auto-pts WID 92 has the Lower Tester
    subscribe, then sets the value and waits on the air for
    ATT_HANDLE_VALUE_NTF (0x1B) — storing it silently times the MMI out."""
    svc, server, value_handle = await _server_with_notify_char()
    server.enable_notifications(0x0001, value_handle)
    sent = []
    server.on_notification_sent(lambda h, v, c: sent.append((h, v, c)))

    value = bytes.fromhex("efcdab8967452301")
    body = (value_handle.to_bytes(2, "little")
            + len(value).to_bytes(2, "little") + value)
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_SET_VALUE, controller_index=0, data=body)

    assert status == op.BTP_STATUS_SUCCESS
    assert sent == [(value_handle, value, 0x0001)]
    assert server.db.read(value_handle) == value


async def test_set_value_zero_handle_notifies_the_last_attribute():
    """Handle 0 means "the attribute most recently added"; the notification must
    carry that attribute's real handle, not 0."""
    svc, server, value_handle = await _server_with_notify_char()
    server.enable_notifications(0x0001, value_handle)
    sent = []
    server.on_notification_sent(lambda h, v, c: sent.append((h, v, c)))

    value = b"\x01\x02"
    body = (0).to_bytes(2, "little") + len(value).to_bytes(2, "little") + value
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_SET_VALUE, controller_index=0, data=body)

    assert status == op.BTP_STATUS_SUCCESS
    assert sent == [(value_handle, value, 0x0001)]


async def test_set_value_resolves_handles_from_the_committed_db():
    """Handles drift between the BTP build map and the committed db.

    ``add_service`` auto-adds a CCCD for a notify/indicate characteristic that
    was declared without one, so a later characteristic's *real* value handle
    is higher than the dynamic map's. ``hdl_wid_98`` passes
    GET_ATTRIBUTE_VALUE's handle (read from ``server.db``) straight into
    SET_VALUE, so SET_VALUE must resolve there too — GATT/SR/GAI/BV-01 targets
    a high handle (0x003B) and used to get BTP_STATUS_FAILED.
    """
    from pybluehost.ble.gatt import GATTServer
    from pybluehost.core.uuid import UUID16

    stack = MagicMock()
    stack.gatt_server = GATTServer()
    actions = MagicMock()
    actions._stack = stack
    svc = GattService(actions=actions, tester=MagicMock())

    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_ADD_SERVICE, controller_index=0,
        data=bytes([0]) + bytes([2]) + _le16("AA41"))
    assert status == op.BTP_STATUS_SUCCESS

    # Notify characteristic WITHOUT an explicit CCC descriptor: the committed
    # db auto-adds one, the build map does not.
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_ADD_CHARACTERISTIC, controller_index=0,
        data=(0).to_bytes(2, "little") + bytes([0x10, 0x01, 2]) + _le16("AA50"))
    assert status == op.BTP_STATUS_SUCCESS

    status, dyn_handle = await svc.dispatch(
        opcode=op.OP_GATT_ADD_CHARACTERISTIC, controller_index=0,
        data=(0).to_bytes(2, "little") + bytes([0x02, 0x01, 2]) + _le16("AA51"))
    assert status == op.BTP_STATUS_SUCCESS

    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_START_SERVER, controller_index=0, data=b"")
    assert status == op.BTP_STATUS_SUCCESS

    server = stack.gatt_server
    real_handle = server.find_characteristic_value_handle(UUID16(0xAA51))
    assert real_handle == int.from_bytes(dyn_handle, "little") + 1

    value = b"\xef\xcd"
    body = (real_handle.to_bytes(2, "little")
            + len(value).to_bytes(2, "little") + value)
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_SET_VALUE, controller_index=0, data=body)

    assert status == op.BTP_STATUS_SUCCESS
    assert server.db.read(real_handle) == value
