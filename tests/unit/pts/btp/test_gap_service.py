"""GapService skeleton — registration + bound IutActions/tester accessors."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.base import BtpServiceRegistry
from pybluehost.pts.btp.services.gap import GapService


class _FakeActions:
    """Records calls to async IutActions methods."""
    local_address: bytes = bytes(6)

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def advertise(self, *, adv_type=None, data=None, scan_rsp=None,
                        own_addr_type=None, filter_policy=0x00):
        self.calls.append(("advertise", {
            "adv_type": adv_type, "data": data, "scan_rsp": scan_rsp,
            "own_addr_type": own_addr_type, "filter_policy": filter_policy,
        }))

    async def stop_advertising(self):
        self.calls.append(("stop_advertising", {}))

    def set_bondable(self, enabled: bool):
        self.calls.append(("set_bondable", {"enabled": enabled}))

    def set_mitm(self, enabled: bool):
        self.calls.append(("set_mitm", {"enabled": enabled}))

    async def padv_configure(self, *, include_tx_power, interval_min, interval_max):
        self.calls.append(("padv_configure", {
            "include_tx_power": include_tx_power,
            "interval_min": interval_min, "interval_max": interval_max,
        }))

    async def padv_start(self):
        self.calls.append(("padv_start", {}))

    async def padv_stop(self):
        self.calls.append(("padv_stop", {}))

    async def padv_set_data(self, data):
        self.calls.append(("padv_set_data", {"data": data}))

    async def padv_create_sync(self, *, adv_sid, skip, sync_timeout, flags,
                               address_type, address):
        self.calls.append(("padv_create_sync", {
            "adv_sid": adv_sid, "skip": skip, "sync_timeout": sync_timeout,
            "flags": flags, "address_type": address_type, "address": address,
        }))

    async def padv_sync_transfer_set_info(self, *, address_type, address, service_data):
        self.calls.append(("padv_sync_transfer_set_info", {
            "address_type": address_type, "address": address,
            "service_data": service_data,
        }))

    async def padv_sync_transfer_start(self):
        self.calls.append(("padv_sync_transfer_start", {}))

    async def padv_sync_transfer_recv(self, *, skip, sync_timeout, flags,
                                      address_type, address):
        self.calls.append(("padv_sync_transfer_recv", {
            "skip": skip, "sync_timeout": sync_timeout, "flags": flags,
            "address_type": address_type, "address": address,
        }))


def test_gap_service_id_matches_constant():
    assert GapService.SERVICE_ID == op.SERVICE_GAP


def test_gap_service_registers_in_registry():
    reg = BtpServiceRegistry()
    actions = MagicMock()
    tester = MagicMock()
    svc = GapService(actions=actions, tester=tester)
    reg.register(svc)
    assert reg.get(op.SERVICE_GAP) is svc


def test_gap_service_stores_actions_and_tester():
    actions = MagicMock()
    tester = MagicMock()
    svc = GapService(actions=actions, tester=tester)
    assert svc._actions is actions
    assert svc._tester is tester


# ---------------------------------------------------------------------------
# T2: Read Controller Index List / Info / Reset
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_controller_index_list_returns_single_index_0():
    """PyBlueHost is single-controller; the list contains just index 0."""
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    status, data = await svc.dispatch(
        opcode=op.OP_GAP_READ_CONTROLLER_INDEX_LIST,
        controller_index=op.CONTROLLER_INDEX_NONE, data=b"",
    )
    assert status == op.BTP_STATUS_SUCCESS
    # Format: [num_controllers (u8), controller_indices...]
    assert data == bytes([1, 0])


@pytest.mark.asyncio
async def test_read_controller_info_returns_address_and_settings():
    """Layout (auto-pts): 6 BD_ADDR + 4 supported_settings + 4 current_settings
    + 3 class_of_device + 249 name + 11 short_name = 277 bytes."""
    actions = _FakeActions()
    actions.local_address = bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06])
    svc = GapService(actions=actions, tester=MagicMock())
    status, data = await svc.dispatch(
        opcode=op.OP_GAP_READ_CONTROLLER_INFO,
        controller_index=0, data=b"",
    )
    assert status == op.BTP_STATUS_SUCCESS
    # Sanity: minimum length, address bytes at expected offset.
    assert len(data) >= 14
    assert data[:6] == bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06])
    # supported_settings is u32 LE at offset 6.
    supported = int.from_bytes(data[6:10], "little")
    assert supported != 0    # we set some bits


@pytest.mark.asyncio
async def test_reset_clears_current_settings():
    """GAP RESET opcode (0x04) returns SUCCESS and zeroes per-session state."""
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    svc._current_settings = 0xDEAD
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_RESET, controller_index=0, data=b"",
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert svc._current_settings == 0


# ---------------------------------------------------------------------------
# T3: Set Powered / Connectable / Fast Connectable / Discoverable / Bondable
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("opcode,bit", [
    (op.OP_GAP_SET_POWERED, 0),
    (op.OP_GAP_SET_CONNECTABLE, 1),
    (op.OP_GAP_SET_FAST_CONNECTABLE, 2),
    (op.OP_GAP_SET_DISCOVERABLE, 3),
    (op.OP_GAP_SET_BONDABLE, 4),
])
@pytest.mark.asyncio
async def test_set_flag_updates_current_settings_bit(opcode, bit):
    from unittest.mock import MagicMock
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    status, data = await svc.dispatch(opcode=opcode, controller_index=0,
                                       data=bytes([1]))
    assert status == op.BTP_STATUS_SUCCESS
    current = int.from_bytes(data, "little")
    assert (current >> bit) & 1


@pytest.mark.asyncio
async def test_set_powered_off_clears_bit():
    from unittest.mock import MagicMock
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    await svc.dispatch(opcode=op.OP_GAP_SET_POWERED, controller_index=0, data=bytes([1]))
    _, data = await svc.dispatch(opcode=op.OP_GAP_SET_POWERED, controller_index=0, data=bytes([0]))
    current = int.from_bytes(data, "little")
    assert not (current & 0x01)


@pytest.mark.asyncio
async def test_set_command_rejects_empty_data():
    from unittest.mock import MagicMock
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    status, _ = await svc.dispatch(opcode=op.OP_GAP_SET_POWERED,
                                    controller_index=0, data=b"")
    assert status == op.BTP_STATUS_FAILED


# ---------------------------------------------------------------------------
# T4: Start / Stop Advertising
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_advertising_decodes_body_and_calls_actions():
    """Body layout: adv_len(1), scan_len(1), adv_data, scan_rsp, duration(4), own_addr_type(1).

    AD structs arrive in BTP wire format ``{type, len, data}`` (type first) and
    must be re-serialised to on-air ``[len][type][data]`` for the controller.
    """
    from unittest.mock import MagicMock
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())
    # BTP-format adv_data: flags(type01,len1,0xFF) + complete-name(type09,"Test")
    adv_data = bytes([0x01, 0x01, 0xFF]) + bytes([0x09, 0x04]) + b"Test"
    # BTP-format scan_rsp: short-name(type08,"Hi")
    scan_rsp = bytes([0x08, 0x02]) + b"Hi"
    body = (
        bytes([len(adv_data), len(scan_rsp)])
        + adv_data + scan_rsp
        + (0).to_bytes(4, "little")
        + bytes([op.GAP_ADDR_TYPE_PUBLIC])
    )
    status, data = await svc.dispatch(
        opcode=op.OP_GAP_START_ADVERTISING, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    # Response = updated current_settings; ADVERTISING is bit 10 (auto-pts defs).
    settings = int.from_bytes(data, "little")
    assert settings & (1 << 10)
    assert actions.calls[0][0] == "advertise"
    # No set_connectable/set_discoverable -> non-discoverable + non-connectable.
    # Flags struct overridden 0xFF -> 0x04 (BR/EDR-not-supported); re-serialised to
    # on-air [len][type][data]: flags "02 01 04" + name "05 09 'Test'".
    assert actions.calls[0][1].get("data") == bytes.fromhex("020104") + bytes([0x05, 0x09]) + b"Test"
    # scan_rsp re-serialised to on-air format: "03 08 'Hi'".
    assert actions.calls[0][1].get("scan_rsp") == bytes([0x03, 0x08]) + b"Hi"
    # non-connectable + has scan_rsp -> scannable ADV_SCAN_IND (0x02); no
    # accept list programmed -> advertising filter policy 0x00.
    assert actions.calls[0][1].get("adv_type") == 0x02
    assert actions.calls[0][1].get("filter_policy") == 0x00


@pytest.mark.asyncio
async def test_stop_advertising_clears_bit_and_calls_actions():
    from unittest.mock import MagicMock
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())
    svc._current_settings |= (1 << 10)       # pretend advertising is on (bit 10)
    status, data = await svc.dispatch(
        opcode=op.OP_GAP_STOP_ADVERTISING, controller_index=0, data=b"",
    )
    assert status == op.BTP_STATUS_SUCCESS
    settings = int.from_bytes(data, "little")
    assert not (settings & (1 << 10))
    assert any(c[0] == "stop_advertising" for c in actions.calls)


@pytest.mark.asyncio
async def test_start_advertising_truncated_body_fails():
    from unittest.mock import MagicMock
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    # Body says adv_len=10, scan_len=0, but only 3 bytes of adv_data provided.
    body = bytes([10, 0]) + b"\x01\x02\x03"
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_START_ADVERTISING, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


# ---------------------------------------------------------------------------
# T5: Start / Stop Discovery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_discovery_calls_actions_scan():
    from unittest.mock import MagicMock
    actions = _FakeActions()

    async def fake_scan(*, active=False, on_result=None):
        actions.calls.append(("scan", {"active": active, "on_result": on_result}))

    actions.scan = fake_scan
    svc = GapService(actions=actions, tester=MagicMock())
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_START_DISCOVERY, controller_index=0,
        data=bytes([0x01]),       # LE only
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert any(c[0] == "scan" for c in actions.calls)


# ---------------------------------------------------------------------------
# T6: Connect / Disconnect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_decodes_addr_and_calls_actions():
    from unittest.mock import MagicMock
    actions = _FakeActions()

    async def fake_connect(peer, *, le=True, filter_policy=0x00):
        actions.calls.append(("connect", {"peer_bytes": getattr(peer, "bytes", None)
                                          or getattr(peer, "address", None), "le": le}))
        return 0x000C

    actions.connect = fake_connect
    svc = GapService(actions=actions, tester=MagicMock())
    addr = bytes.fromhex("AABBCCDDEEFF")
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + addr
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_CONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert any(c[0] == "connect" for c in actions.calls)


@pytest.mark.asyncio
async def test_connect_rejects_wrong_length():
    from unittest.mock import MagicMock
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_CONNECT, controller_index=0, data=b"\x00\x01\x02",
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_connect_all_zero_addr_uses_filter_accept_list():
    """ACEP: connect to 00:00:00:00:00:00 must resolve to the accept-list entry."""
    from unittest.mock import MagicMock
    actions = _FakeActions()
    captured = {}

    async def fake_connect(peer, *, le=True, filter_policy=0x00):
        captured["address"] = getattr(peer, "address", None)
        captured["filter_policy"] = filter_policy
        return 0x000C

    actions.connect = fake_connect
    svc = GapService(actions=actions, tester=MagicMock())
    # PTS pushes its address via SET_FILTER_ACCEPT_LIST (wire = little-endian).
    pts_wire = bytes.fromhex("ee6a1eff5394")  # -> display 94:53:FF:1E:6A:EE
    fal_body = bytes([1, op.GAP_ADDR_TYPE_PUBLIC]) + pts_wire
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_SET_FILTER_ACCEPT_LIST, controller_index=0, data=fal_body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    # Connect to the all-zero address = use filter accept list.
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_CONNECT, controller_index=0,
        data=bytes([op.GAP_ADDR_TYPE_PUBLIC]) + bytes(6),
    )
    assert status == op.BTP_STATUS_SUCCESS
    # The stored entry is still the nominal peer (for session bookkeeping), but
    # the *controller* must do the matching: Initiator_Filter_Policy 0x01.
    assert bytes(captured["address"]) == bytes.fromhex("9453ff1e6aee")
    assert captured["filter_policy"] == 0x01


@pytest.mark.asyncio
async def test_connect_all_zero_addr_without_filter_list_stays_zero():
    """With no accept list, an all-zero connect is passed through unchanged."""
    from unittest.mock import MagicMock
    actions = _FakeActions()
    captured = {}

    async def fake_connect(peer, *, le=True, filter_policy=0x00):
        captured["address"] = getattr(peer, "address", None)
        captured["filter_policy"] = filter_policy
        return 0x000C

    actions.connect = fake_connect
    svc = GapService(actions=actions, tester=MagicMock())
    await svc.dispatch(
        opcode=op.OP_GAP_CONNECT, controller_index=0,
        data=bytes([op.GAP_ADDR_TYPE_PUBLIC]) + bytes(6),
    )
    assert bytes(captured["address"]) == bytes(6)
    assert captured["filter_policy"] == 0x00


@pytest.mark.asyncio
async def test_zero_addr_connect_with_privacy_prepares_rpa_and_initiates_from_it():
    """GAP/CONN/ACEP BV-03/04: with privacy on, the auto-connection flow must
    first program the LT identity into the resolving list and an RPA of our
    own (the Pass verdict checks the initiator address IS a resolvable
    private address), then connect with Initiator_Filter_Policy 0x01 and
    Own_Address_Type 0x01 (random)."""
    from unittest.mock import MagicMock

    actions = _FakeActions()
    captured = {}

    async def fake_prepare(peer_str: str):
        captured["prepared_peer"] = peer_str

    async def fake_connect(peer, *, le=True, filter_policy=0x00,
                           own_address_type=None):
        captured["address"] = getattr(peer, "address", None)
        captured["filter_policy"] = filter_policy
        captured["own_address_type"] = own_address_type
        return 0x000C

    actions.prepare_auto_connection = fake_prepare
    actions.connect = fake_connect
    svc = GapService(actions=actions, tester=MagicMock())
    pts_wire = bytes.fromhex("ee6a1eff5394")
    fal_body = bytes([1, op.GAP_ADDR_TYPE_PUBLIC]) + pts_wire
    await svc.dispatch(
        opcode=op.OP_GAP_SET_FILTER_ACCEPT_LIST, controller_index=0, data=fal_body,
    )
    # The per-case registration turns privacy on before WID 400 runs.
    await svc.dispatch(
        opcode=op.OP_GAP_SET_PRIVACY, controller_index=0, data=bytes([0x01]),
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_CONNECT, controller_index=0,
        data=bytes([op.GAP_ADDR_TYPE_PUBLIC]) + bytes(6),
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert captured["prepared_peer"] == "94:53:ff:1e:6a:ee"
    assert captured["filter_policy"] == 0x01
    # 0x01 = use the host-programmed RPA (minted from the PIXIT IRK the LT
    # resolves against). 0x02 was tried: the AX201 falls back to the identity
    # address with an all-zero resolving-list Local_IRK (LT saw peer_rpa=0)
    # and the LT drops the link.
    assert captured["own_address_type"] == 0x01


@pytest.mark.asyncio
async def test_direct_connect_with_privacy_initiates_from_the_programmed_rpa():
    """GAP/PRIV/CONN/BV-11: General Connection Establishment must use an RPA
    for InitA as well as resolving the LT's RPA. With privacy enabled, a normal
    (non-accept-list) connect therefore needs Own_Address_Type 0x01; leaving the
    default public address makes the LT silently ignore every CONNECT_IND."""
    from unittest.mock import MagicMock

    actions = _FakeActions()
    captured = {}

    async def fake_connect(peer, *, le=True, filter_policy=0x00,
                           own_address_type=None):
        captured["filter_policy"] = filter_policy
        captured["own_address_type"] = own_address_type
        return 0x000C

    actions.connect = fake_connect
    svc = GapService(actions=actions, tester=MagicMock())
    await svc.dispatch(
        opcode=op.OP_GAP_SET_PRIVACY, controller_index=0, data=b"\x01",
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_CONNECT, controller_index=0,
        data=bytes([op.GAP_ADDR_TYPE_PUBLIC]) + bytes.fromhex("eb8dd5539efc"),
    )

    assert status == op.BTP_STATUS_SUCCESS
    assert captured["filter_policy"] == 0x00
    assert captured["own_address_type"] == 0x01


@pytest.mark.asyncio
async def test_zero_addr_connect_without_privacy_skips_rpa_preparation():
    """GAP/CONN/ACEP BV-01/02 (public identity): the flow must not program a
    private address — today's plain filter-policy connect stays untouched."""
    from unittest.mock import MagicMock

    actions = _FakeActions()
    captured = {}
    prepared = []

    async def fake_prepare(peer):
        prepared.append(peer)

    async def fake_connect(peer, *, le=True, filter_policy=0x00):
        captured["filter_policy"] = filter_policy
        return 0x000C

    actions.prepare_auto_connection = fake_prepare
    actions.connect = fake_connect
    svc = GapService(actions=actions, tester=MagicMock())
    pts_wire = bytes.fromhex("ee6a1eff5394")
    await svc.dispatch(
        opcode=op.OP_GAP_SET_FILTER_ACCEPT_LIST, controller_index=0,
        data=bytes([1, op.GAP_ADDR_TYPE_PUBLIC]) + pts_wire,
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_CONNECT, controller_index=0,
        data=bytes([op.GAP_ADDR_TYPE_PUBLIC]) + bytes(6),
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert prepared == []
    assert captured["filter_policy"] == 0x01


@pytest.mark.asyncio
async def test_disconnect_decodes_addr_and_calls_actions():
    from unittest.mock import MagicMock
    from dataclasses import dataclass

    @dataclass
    class _FakePeer:
        address: bytes

        @property
        def bytes(self): return self.address

    @dataclass
    class _FakeConnInfo:
        handle: int
        peer: _FakePeer
        transport: str = "le"
        gatt_client: object = None

    @dataclass
    class _FakeSession:
        connections: dict
        last_handle: int | None = None

    addr_bytes = bytes.fromhex("AABBCCDDEEFF")
    session = _FakeSession(connections={
        0x000C: _FakeConnInfo(handle=0x000C, peer=_FakePeer(address=addr_bytes))
    })
    actions = _FakeActions()
    actions.status = lambda: session

    async def fake_disconnect(handle=None):
        actions.calls.append(("disconnect", {"handle": handle}))

    actions.disconnect = fake_disconnect
    svc = GapService(actions=actions, tester=MagicMock())
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + addr_bytes
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_DISCONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert any(c[0] == "disconnect" and c[1]["handle"] == 0x000C for c in actions.calls)


@pytest.mark.asyncio
async def test_disconnect_matches_a_peer_that_connected_under_its_rpa():
    """GAP/PRIV/CONN/BV-10: auto-pts disconnects the LT by identity, but with
    privacy on the session peer is the LT's resolvable private address."""
    from dataclasses import dataclass
    from unittest.mock import MagicMock

    from pybluehost.core.address import AddressType, BDAddress

    @dataclass
    class _FakeConnInfo:
        handle: int
        peer: BDAddress
        transport: str = "le"
        gatt_client: object = None

    @dataclass
    class _FakeSession:
        connections: dict
        last_handle: int | None = None

    identity = BDAddress.from_string("FC:9E:53:D5:8D:EB")
    rpa = BDAddress.from_hci(bytes.fromhex("1b08e8eb696b"), type=AddressType.RANDOM)
    session = _FakeSession(connections={
        0x0800: _FakeConnInfo(handle=0x0800, peer=rpa),
    })
    actions = _FakeActions()
    actions.status = lambda: session
    looked_up = []

    async def fake_peer_identity(peer):
        looked_up.append(peer)
        return identity

    async def fake_disconnect(handle=None):
        actions.calls.append(("disconnect", {"handle": handle}))

    actions.peer_identity = fake_peer_identity
    actions.disconnect = fake_disconnect
    svc = GapService(actions=actions, tester=MagicMock())
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + identity.to_hci()
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_DISCONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert looked_up == [rpa]
    assert any(c[0] == "disconnect" and c[1]["handle"] == 0x0800 for c in actions.calls)


@pytest.mark.asyncio
async def test_disconnect_over_rpa_without_a_bond_still_fails():
    from dataclasses import dataclass
    from unittest.mock import MagicMock

    from pybluehost.core.address import AddressType, BDAddress

    @dataclass
    class _FakeConnInfo:
        handle: int
        peer: BDAddress
        transport: str = "le"
        gatt_client: object = None

    @dataclass
    class _FakeSession:
        connections: dict
        last_handle: int | None = None

    identity = BDAddress.from_string("FC:9E:53:D5:8D:EB")
    rpa = BDAddress.from_hci(bytes.fromhex("1b08e8eb696b"), type=AddressType.RANDOM)
    other = BDAddress.from_string("11:22:33:44:55:66")
    session = _FakeSession(connections={
        0x0800: _FakeConnInfo(handle=0x0800, peer=rpa),
        0x0801: _FakeConnInfo(handle=0x0801, peer=other),
    })
    actions = _FakeActions()
    actions.status = lambda: session

    async def no_bond(peer):
        return None

    async def fake_disconnect(handle=None):
        actions.calls.append(("disconnect", {"handle": handle}))

    actions.peer_identity = no_bond
    actions.disconnect = fake_disconnect
    svc = GapService(actions=actions, tester=MagicMock())
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + identity.to_hci()
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_DISCONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED
    assert not any(c[0] == "disconnect" for c in actions.calls)


@pytest.mark.asyncio
async def test_disconnect_uses_the_only_connection_when_the_peer_is_unresolvable():
    """Hardware capture of GAP/PRIV/CONN/BV-10: the LT's phase-3 connection
    carried an RPA that resolves against neither the IRK it distributed at
    pairing nor ours, so the identity-keyed disconnect matched nothing and the
    case sat until TSPX_time_guard. With a single link the target is
    unambiguous."""
    from dataclasses import dataclass
    from unittest.mock import MagicMock

    from pybluehost.core.address import AddressType, BDAddress

    @dataclass
    class _FakeConnInfo:
        handle: int
        peer: BDAddress
        transport: str = "le"
        gatt_client: object = None

    @dataclass
    class _FakeSession:
        connections: dict
        last_handle: int | None = None

    identity = BDAddress.from_string("FC:9E:53:D5:8D:EB")
    rpa = BDAddress.from_hci(bytes.fromhex("a70d381a044e"), type=AddressType.RANDOM)
    session = _FakeSession(connections={
        0x0800: _FakeConnInfo(handle=0x0800, peer=rpa),
    })
    actions = _FakeActions()
    actions.status = lambda: session

    async def no_bond(peer):
        return None

    async def fake_disconnect(handle=None):
        actions.calls.append(("disconnect", {"handle": handle}))

    actions.peer_identity = no_bond
    actions.disconnect = fake_disconnect
    svc = GapService(actions=actions, tester=MagicMock())
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + identity.to_hci()
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_DISCONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert any(c[0] == "disconnect" and c[1]["handle"] == 0x0800 for c in actions.calls)


@pytest.mark.asyncio
async def test_disconnect_tolerates_actions_without_peer_identity():
    """Older/fake action facades without the helper keep the old behaviour."""
    from dataclasses import dataclass
    from unittest.mock import MagicMock

    from pybluehost.core.address import AddressType, BDAddress

    @dataclass
    class _FakeConnInfo:
        handle: int
        peer: BDAddress
        transport: str = "le"
        gatt_client: object = None

    @dataclass
    class _FakeSession:
        connections: dict
        last_handle: int | None = None

    identity = BDAddress.from_string("FC:9E:53:D5:8D:EB")
    rpa = BDAddress.from_hci(bytes.fromhex("1b08e8eb696b"), type=AddressType.RANDOM)
    other = BDAddress.from_string("11:22:33:44:55:66")
    session = _FakeSession(connections={
        0x0800: _FakeConnInfo(handle=0x0800, peer=rpa),
        0x0801: _FakeConnInfo(handle=0x0801, peer=other),
    })
    actions = _FakeActions()
    actions.status = lambda: session
    svc = GapService(actions=actions, tester=MagicMock())
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + identity.to_hci()
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_DISCONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


# ---------------------------------------------------------------------------
# T7: Set IO Cap / Pair / Unpair / Passkey
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_io_cap_calls_actions():
    from unittest.mock import MagicMock
    actions = _FakeActions()
    captured = {}

    def fake_set_io_cap(cap: str) -> None:
        captured["cap"] = cap
        actions.calls.append(("set_io_cap", {"cap": cap}))

    actions.set_io_cap = fake_set_io_cap
    svc = GapService(actions=actions, tester=MagicMock())
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_SET_IO_CAP, controller_index=0,
        data=bytes([op.GAP_IO_CAP_DISPLAY_YESNO]),
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert captured["cap"] == "DisplayYesNo"


@pytest.mark.asyncio
async def test_set_io_cap_unknown_value_fails():
    from unittest.mock import MagicMock
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_SET_IO_CAP, controller_index=0,
        data=bytes([0xFF]),
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_pair_resolves_addr_to_handle_and_calls_actions():
    from unittest.mock import MagicMock
    from dataclasses import dataclass

    @dataclass
    class _FakePeer:
        address: bytes
        @property
        def bytes(self): return self.address

    @dataclass
    class _FakeConnInfo:
        handle: int
        peer: _FakePeer
        transport: str = "le"
        gatt_client: object = None

    @dataclass
    class _FakeSession:
        connections: dict
        last_handle: int | None = None

    addr_bytes = bytes.fromhex("112233445566")
    session = _FakeSession(connections={
        0x0010: _FakeConnInfo(handle=0x0010, peer=_FakePeer(address=addr_bytes))
    })
    actions = _FakeActions()
    actions.status = lambda: session

    async def fake_pair(handle=None, *, io_cap=None, mitm=False):
        actions.calls.append(("pair", {"handle": handle}))

    actions.pair = fake_pair
    tester = MagicMock()
    tester.emit_event = AsyncMock()
    svc = GapService(actions=actions, tester=tester)
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + addr_bytes
    # PAIR responds once pairing is *initiated* (upstream 0x11 contract); the pair
    # itself runs as a background task. Yield so the spawned task executes.
    status, _ = await svc.dispatch(opcode=op.OP_GAP_PAIR, controller_index=0, data=body)
    assert status == op.BTP_STATUS_SUCCESS
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert any(c[0] == "pair" and c[1]["handle"] == 0x0010 for c in actions.calls)


@pytest.mark.asyncio
async def test_pair_unknown_peer_fails():
    from unittest.mock import MagicMock
    from dataclasses import dataclass

    @dataclass
    class _FakeSession:
        connections: dict
        last_handle: int | None = None

    actions = _FakeActions()
    actions.status = lambda: _FakeSession(connections={})
    svc = GapService(actions=actions, tester=MagicMock())
    body = bytes([op.GAP_ADDR_TYPE_PUBLIC]) + bytes.fromhex("000000000000")
    status, _ = await svc.dispatch(opcode=op.OP_GAP_PAIR, controller_index=0, data=body)
    assert status == op.BTP_STATUS_FAILED


def _make_connected_svc(actions, *, pair_impl):
    """Build a GapService with one LE connection (handle 0x10) wired to ``actions``."""
    from dataclasses import dataclass

    @dataclass
    class _FakePeer:
        address: bytes

        @property
        def bytes(self):
            return self.address

    @dataclass
    class _FakeConnInfo:
        handle: int
        peer: _FakePeer
        transport: str = "le"
        gatt_client: object = None

    @dataclass
    class _FakeSession:
        connections: dict
        last_handle: int | None = None

    addr_bytes = bytes.fromhex("112233445566")
    session = _FakeSession(connections={
        0x0010: _FakeConnInfo(handle=0x0010, peer=_FakePeer(address=addr_bytes))
    })
    actions.status = lambda: session
    actions.pair = pair_impl
    return addr_bytes


@pytest.mark.asyncio
async def test_pair_responds_immediately_without_waiting_for_completion():
    """PAIR returns SUCCESS once pairing is initiated, not after it completes.

    Regression for the CEN passkey deadlock: blocking the response until pairing
    finished froze auto-pts's main thread in gap_pair(), so the passkey-entry MMI
    (WID 104) could never be serviced.
    """
    from unittest.mock import MagicMock

    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_pair(handle=None, *, io_cap=None, mitm=False):
        started.set()
        await release.wait()  # pairing "in progress" until released

    actions = _FakeActions()
    addr_bytes = _make_connected_svc(actions, pair_impl=blocking_pair)
    tester = MagicMock()
    tester.emit_event = AsyncMock()
    svc = GapService(actions=actions, tester=tester)
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + addr_bytes
    # dispatch must return even though the pair coroutine is still blocked.
    status, _ = await asyncio.wait_for(
        svc.dispatch(opcode=op.OP_GAP_PAIR, controller_index=0, data=body), timeout=1.0
    )
    assert status == op.BTP_STATUS_SUCCESS
    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_pair_async_failure_emits_pairing_failed_event():
    """A pairing that fails after initiation surfaces as PAIRING_FAILED, not an error rsp."""
    from unittest.mock import MagicMock

    async def failing_pair(handle=None, *, io_cap=None, mitm=False):
        raise RuntimeError("pairing rejected")

    actions = _FakeActions()
    addr_bytes = _make_connected_svc(actions, pair_impl=failing_pair)
    tester = MagicMock()
    tester.emit_event = AsyncMock()
    svc = GapService(actions=actions, tester=tester)
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + addr_bytes
    status, _ = await svc.dispatch(opcode=op.OP_GAP_PAIR, controller_index=0, data=body)
    assert status == op.BTP_STATUS_SUCCESS
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    opcodes = [c.args[0].opcode for c in tester.emit_event.await_args_list]
    assert op.OP_GAP_EVENT_PAIRING_FAILED in opcodes


@pytest.mark.asyncio
async def test_pair_async_failure_reports_the_smp_reason_not_a_constant():
    """SM/CEN/JW/BI-06 (reflection) and the other self-abort negatives are judged
    on the *reason* the IUT reports to the Upper Tester: WID 175 asks for Confirm
    Value Failed (0x04), EKS for Encryption Key Size (0x06). Reporting a hardcoded
    0x05 makes PTS answer No even though the IUT aborted correctly."""
    from unittest.mock import MagicMock

    async def failing_pair(handle=None, *, io_cap=None, mitm=False):
        exc = RuntimeError("SMP pairing failed (reason=4)")
        exc.reason = 0x04
        raise exc

    actions = _FakeActions()
    addr_bytes = _make_connected_svc(actions, pair_impl=failing_pair)
    tester = MagicMock()
    tester.emit_event = AsyncMock()
    svc = GapService(actions=actions, tester=tester)
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + addr_bytes
    status, _ = await svc.dispatch(opcode=op.OP_GAP_PAIR, controller_index=0, data=body)
    assert status == op.BTP_STATUS_SUCCESS
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    frames = [c.args[0] for c in tester.emit_event.await_args_list
              if c.args[0].opcode == op.OP_GAP_EVENT_PAIRING_FAILED]
    assert frames, "expected a PAIRING_FAILED event"
    assert frames[0].data[-1] == 0x04


@pytest.mark.asyncio
async def test_unpair_returns_failed_when_actions_lacks_method():
    """Phase 1 IutActions has no unpair — handler returns STATUS_FAILED."""
    from unittest.mock import MagicMock
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    body = bytes([op.GAP_ADDR_TYPE_PUBLIC]) + bytes.fromhex("000000000000")
    status, _ = await svc.dispatch(opcode=op.OP_GAP_UNPAIR, controller_index=0, data=body)
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_passkey_entry_reply_rejects_wrong_length():
    from unittest.mock import MagicMock
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_PASSKEY_ENTRY_REPLY, controller_index=0, data=b"\x00\x01",
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_passkey_confirm_reply_rejects_wrong_length():
    from unittest.mock import MagicMock
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_PASSKEY_CONFIRM_REPLY, controller_index=0, data=b"\x00",
    )
    assert status == op.BTP_STATUS_FAILED


# ---------------------------------------------------------------------------
# T8: Start Directed Advertising (op 0x15)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_direct_adv_drives_directed_advertising():
    """op 0x15 must actually drive ADV_DIRECT_IND toward the decoded peer."""
    from unittest.mock import MagicMock
    actions = _FakeActions()

    async def fake_advertise(*, adv_type=None, data=None, scan_rsp=None, peer=None):
        actions.calls.append(("advertise", {"adv_type": adv_type, "peer": peer}))

    actions.advertise = fake_advertise
    svc = GapService(actions=actions, tester=MagicMock())
    # PTS dongle 5C:67:83:07:04:EE little-endian on the wire + own_addr_type.
    body = bytes([op.GAP_ADDR_TYPE_PUBLIC]) + bytes.fromhex("EE040783675C") + b"\x00"
    status, data = await svc.dispatch(
        opcode=op.OP_GAP_START_DIRECT_ADV, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    # ADVERTISING bit (10) now set in returned current_settings.
    assert int.from_bytes(data, "little") & (1 << 10)
    adv = [c for c in actions.calls if c[0] == "advertise"]
    assert adv, "expected advertise() to be called"
    assert adv[0][1]["adv_type"] == 0x01  # ADV_DIRECT_IND
    peer = adv[0][1]["peer"]
    assert str(peer) == "5C:67:83:07:04:EE"


@pytest.mark.asyncio
async def test_start_direct_adv_rejects_short_body():
    from unittest.mock import MagicMock
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_START_DIRECT_ADV, controller_index=0, data=b"\x00\x01\x02",
    )
    assert status == op.BTP_STATUS_FAILED


# ---------------------------------------------------------------------------
# Periodic advertising (GAP/PADV, opcodes 0x22-0x29)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_padv_configure_decodes_body_and_reports_settings():
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())

    status, resp = await svc.dispatch(
        opcode=op.OP_GAP_PADV_CONFIGURE, controller_index=0,
        data=bytes([0x01, 0x10, 0x00, 0x20, 0x00]),
    )

    assert status == op.BTP_STATUS_SUCCESS
    assert len(resp) == 4                       # current-settings bitmap
    name, kwargs = actions.calls[-1]
    assert name == "padv_configure"
    assert kwargs["include_tx_power"] is True
    assert kwargs["interval_min"] == 0x0010
    assert kwargs["interval_max"] == 0x0020


@pytest.mark.asyncio
async def test_padv_configure_rejects_short_body():
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_PADV_CONFIGURE, controller_index=0, data=b"\x01\x02",
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_padv_start_leaves_settings_bitmap_untouched():
    """auto-pts has NO periodic-advertising settings bit — bit 13 is Privacy.
    PADV_START must return the bitmap unchanged (setting bit 13 would make
    auto-pts believe privacy is on and corrupt the GAP/PRIV cases)."""
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())

    status, resp = await svc.dispatch(
        opcode=op.OP_GAP_PADV_START, controller_index=0, data=b"\x00",
    )

    assert status == op.BTP_STATUS_SUCCESS
    assert int.from_bytes(resp, "little") == 0
    assert actions.calls[-1][0] == "padv_start"


@pytest.mark.asyncio
async def test_padv_stop_leaves_settings_bitmap_untouched():
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())

    status, resp = await svc.dispatch(
        opcode=op.OP_GAP_PADV_STOP, controller_index=0, data=b"",
    )

    assert status == op.BTP_STATUS_SUCCESS
    assert int.from_bytes(resp, "little") == 0
    assert actions.calls[-1][0] == "padv_stop"


@pytest.mark.asyncio
async def test_padv_set_data_decodes_length_prefixed_payload():
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())

    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_PADV_SET_DATA, controller_index=0,
        data=b"\x03\x00" + b"abc",
    )

    assert status == op.BTP_STATUS_SUCCESS
    assert actions.calls[-1] == ("padv_set_data", {"data": b"abc"})


@pytest.mark.asyncio
async def test_padv_create_sync_decodes_all_fields():
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())

    body = (
        bytes([0x01]) + bytes.fromhex("ee6a1eff5394")   # addr type + LE addr
        + bytes([0x02])                                  # adv_sid
        + bytes([0x03, 0x00])                            # skip
        + bytes([0xB8, 0x0B])                            # sync_timeout
        + bytes([0x00])                                  # flags
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_PADV_CREATE_SYNC, controller_index=0, data=body,
    )

    assert status == op.BTP_STATUS_SUCCESS
    _, kw = actions.calls[-1]
    assert kw["adv_sid"] == 0x02
    assert kw["skip"] == 3
    assert kw["sync_timeout"] == 0x0BB8
    assert kw["address_type"] == 0x01
    assert kw["address"] == bytes.fromhex("ee6a1eff5394")


@pytest.mark.asyncio
async def test_padv_sync_transfer_recv_decodes_fields():
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())

    body = (
        bytes([0x00]) + bytes.fromhex("ee6a1eff5394")
        + bytes([0x04, 0x00])       # skip
        + bytes([0x10, 0x00])       # sync_timeout
        + bytes([0x01])             # flags
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_PADV_SYNC_TRANSFER_RECV, controller_index=0, data=body,
    )

    assert status == op.BTP_STATUS_SUCCESS
    _, kw = actions.calls[-1]
    assert kw["skip"] == 4
    assert kw["sync_timeout"] == 0x0010
    assert kw["flags"] == 0x01


@pytest.mark.asyncio
async def test_padv_sync_transfer_start_sets_info_then_starts():
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())

    body = bytes([0x00]) + bytes.fromhex("ee6a1eff5394") + bytes([0x05, 0x00])
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_PADV_SYNC_TRANSFER_START, controller_index=0, data=body,
    )

    assert status == op.BTP_STATUS_SUCCESS
    assert [c[0] for c in actions.calls[-2:]] == [
        "padv_sync_transfer_set_info", "padv_sync_transfer_start",
    ]


def test_gap_service_advertises_padv_opcodes_as_supported():
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    cmds = svc.supported_commands()
    for opcode in (op.OP_GAP_PADV_CONFIGURE, op.OP_GAP_PADV_START,
                   op.OP_GAP_PADV_STOP, op.OP_GAP_PADV_SET_DATA,
                   op.OP_GAP_PADV_CREATE_SYNC,
                   op.OP_GAP_PADV_SYNC_TRANSFER_SET_INFO,
                   op.OP_GAP_PADV_SYNC_TRANSFER_START,
                   op.OP_GAP_PADV_SYNC_TRANSFER_RECV):
        assert opcode in cmds


# ---------------------------------------------------------------------------
# SET_PRIVACY (0x1d) — the gate every private-address case depends on
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_privacy_sets_and_clears_the_settings_bit():
    """auto-pts gates GAP/PRIV + private-address cases on
    stack.gap.iut_has_privacy(), which reads the current-settings PRIVACY bit
    (bit 13). SET_PRIVACY must therefore return the bitmap, not an empty body."""
    svc = GapService(actions=_FakeActions(), tester=MagicMock())

    status, resp = await svc.dispatch(
        opcode=op.OP_GAP_SET_PRIVACY, controller_index=0, data=b"\x01",
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert int.from_bytes(resp, "little") & (1 << 13)

    status, resp = await svc.dispatch(
        opcode=op.OP_GAP_SET_PRIVACY, controller_index=0, data=b"\x00",
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert not int.from_bytes(resp, "little") & (1 << 13)


@pytest.mark.asyncio
async def test_controller_info_advertises_privacy_support():
    """The SUPPORTED-settings bitmap must include Privacy (bit 13); auto-pts
    hides private-address test cases whose capability is not advertised."""
    svc = GapService(actions=_FakeActions(), tester=MagicMock())

    status, data = await svc.dispatch(
        opcode=op.OP_GAP_READ_CONTROLLER_INFO, controller_index=0, data=b"",
    )

    assert status == op.BTP_STATUS_SUCCESS
    supported = int.from_bytes(data[6:10], "little")
    assert supported & (1 << 13)


# ---------------------------------------------------------------------------
# START_ADVERTISING own_addr_type (GAP/BROB/BCST/BV-03/04/05)
# ---------------------------------------------------------------------------

def _start_adv_body(*, ad=b"", sd=b"", duration=0, own_addr_type=0):
    import struct as _struct
    return (
        bytes([len(ad), len(sd)]) + ad + sd
        + _struct.pack("<I", duration) + bytes([own_addr_type])
    )


@pytest.mark.asyncio
async def test_start_advertising_forwards_own_address_type():
    """auto-pts's hdl_wid_79/80 ask for a NON-RESOLVABLE (2) or RESOLVABLE (1)
    private address via the tail byte of START_ADVERTISING. Dropping it makes
    the IUT advertise from its public address and the whole private-address
    family (BCST/BV-03/04/05) fails."""
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())

    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_START_ADVERTISING, controller_index=0,
        data=_start_adv_body(own_addr_type=2),
    )

    assert status == op.BTP_STATUS_SUCCESS
    _, kw = actions.calls[-1]
    assert kw["own_addr_type"] == 2


@pytest.mark.asyncio
async def test_start_advertising_defaults_own_address_type_to_identity():
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())

    await svc.dispatch(
        opcode=op.OP_GAP_START_ADVERTISING, controller_index=0,
        data=_start_adv_body(own_addr_type=0),
    )

    _, kw = actions.calls[-1]
    assert kw["own_addr_type"] == 0


@pytest.mark.asyncio
async def test_start_advertising_uses_rpa_when_privacy_is_enabled():
    """GAP/PRIV/CONN/BV-10 enables privacy (SET_PRIVACY) and then WID 91 asks
    for connectable advertising. auto-pts's generic handler always sends
    OwnAddrType 0 (identity) because it does not model the privacy setting,
    but the case's Lower Tester only accepts a resolvable private address it
    can resolve — the IUT's privacy state must win over the default."""
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())
    svc._privacy = True   # as left by SET_PRIVACY (op 0x1d)

    await svc.dispatch(
        opcode=op.OP_GAP_START_ADVERTISING, controller_index=0,
        data=_start_adv_body(own_addr_type=0),
    )

    _, kw = actions.calls[-1]
    assert kw["own_addr_type"] == 1


@pytest.mark.asyncio
async def test_start_advertising_keeps_an_explicit_private_request_with_privacy_on():
    """An explicit OwnAddrType (WID 79/80) is forwarded unchanged even with
    privacy enabled — only the identity default is overridden."""
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())
    svc._privacy = True

    await svc.dispatch(
        opcode=op.OP_GAP_START_ADVERTISING, controller_index=0,
        data=_start_adv_body(own_addr_type=2),
    )

    _, kw = actions.calls[-1]
    assert kw["own_addr_type"] == 2


class _RecordingTester:
    """Captures BTP frames the service emits (NEW_SETTINGS & co.)."""

    def __init__(self):
        self.events: list = []

    async def emit_event(self, frame):
        self.events.append(frame)


@pytest.mark.asyncio
async def test_limited_discoverable_advertising_stops_after_tgap_timeout(monkeypatch):
    """GAP.TS LIMM/*: after TGAP(lim_adv_timeout) from entering Limited
    Discoverable mode the LT must receive NO advertising carrying the Limited
    flag. The workspace pins TSPX_lim_adv_timeout=30720 and we advertised
    forever, so the LT kept seeing Limited=1 past the deadline -> FAIL
    (LIMM/BV-04). The IUT must stop advertising by itself when the window
    elapses, and re-sync auto-pts's model (NEW_SETTINGS — the stale
    'already advertising' short-circuit family of bugs)."""
    from pybluehost.pts.btp.services import gap as gap_mod
    monkeypatch.setattr(gap_mod, "_LIM_ADV_TIMEOUT_S", 0.05)
    actions = _FakeActions()
    tester = _RecordingTester()
    svc = GapService(actions=actions, tester=tester)

    await svc.dispatch(opcode=op.OP_GAP_SET_DISCOVERABLE, controller_index=0,
                       data=bytes([2]))  # GAP_LIMITED_DISCOVERABLE
    await svc.dispatch(opcode=op.OP_GAP_START_ADVERTISING, controller_index=0,
                       data=_start_adv_body())
    assert svc._current_settings & (1 << 10), "precondition: advertising"

    await asyncio.sleep(0.25)

    assert ("stop_advertising", {}) in actions.calls
    assert not (svc._current_settings & (1 << 10)), "ADVERTISING bit must drop"
    ns = [e for e in tester.events if e.opcode == op.OP_GAP_EVENT_NEW_SETTINGS]
    assert ns, "NEW_SETTINGS must keep the auto-pts model in sync"
    assert not (int.from_bytes(ns[0].data, "little") & (1 << 10))


@pytest.mark.asyncio
async def test_leaving_limited_mode_cancels_the_tgap_stop(monkeypatch):
    """Switching to general (or non-) discoverable before the deadline means
    the Limited flag is gone from the air — the timer must not stop later,
    unrelated advertising."""
    from pybluehost.pts.btp.services import gap as gap_mod
    monkeypatch.setattr(gap_mod, "_LIM_ADV_TIMEOUT_S", 0.05)
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())

    await svc.dispatch(opcode=op.OP_GAP_SET_DISCOVERABLE, controller_index=0,
                       data=bytes([2]))
    await svc.dispatch(opcode=op.OP_GAP_SET_DISCOVERABLE, controller_index=0,
                       data=bytes([1]))  # general

    await asyncio.sleep(0.25)
    assert not any(name == "stop_advertising" for name, _ in actions.calls)


@pytest.mark.asyncio
async def test_tgap_stop_is_a_noop_when_advertising_already_stopped(monkeypatch):
    """An explicit STOP_ADVERTISING before the deadline already silenced the
    air; the timer firing later must not call stop twice."""
    from pybluehost.pts.btp.services import gap as gap_mod
    monkeypatch.setattr(gap_mod, "_LIM_ADV_TIMEOUT_S", 0.05)
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())

    await svc.dispatch(opcode=op.OP_GAP_SET_DISCOVERABLE, controller_index=0,
                       data=bytes([2]))
    await svc.dispatch(opcode=op.OP_GAP_START_ADVERTISING, controller_index=0,
                       data=_start_adv_body())
    await svc.dispatch(opcode=op.OP_GAP_STOP_ADVERTISING, controller_index=0,
                       data=b"")
    assert sum(1 for name, _ in actions.calls if name == "stop_advertising") == 1

    await asyncio.sleep(0.25)
    assert sum(1 for name, _ in actions.calls
               if name == "stop_advertising") == 1, "timer must not re-stop"


@pytest.mark.asyncio
async def test_ead_key_material_and_encrypt_match_the_css_sample(monkeypatch):
    """SET_EAD_KEY_MATERIAL (0x31) + ENCRYPT_EAD_DATA (0x32).

    Replayed against CSS v15 §2.3.1 so the framing matches auto-pts's
    `gap_create_encrypted_adv_data` (len(1) + payload -> len(1) + EAD) and the
    ciphertext is the standard's, not merely self-consistent.
    """
    import pybluehost.ble.ead as ead

    key = bytes.fromhex("57A9DA12D12E6E131E20612AD10A6A19")
    iv = bytes.fromhex("46E77AB1EF007A9E")
    plaintext = bytes.fromhex("0F0953686F7274204D696E692D42757303190A8C")
    expected = bytes.fromhex(
        "18E157CADE74E4DCAFDC51C7282810C2217F0E4CEF4343181FBA0069CC")
    # The CSS quotes the randomizer most-significant-octet first.
    randomizer_wire = bytes.fromhex("DECA57E118")[::-1]
    monkeypatch.setattr(ead.os, "urandom", lambda n: randomizer_wire)

    svc = GapService(actions=_FakeActions(), tester=MagicMock())

    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_SET_EAD_KEY_MATERIAL, controller_index=0,
        # auto-pts hands the IV over little-endian (it converts PTS's
        # big-endian IXIT value with hex_str_to_le_bytes), so that is what the
        # handler receives — while the ciphertext below is the CSS's.
        data=key + iv[::-1])
    assert status == op.BTP_STATUS_SUCCESS

    status, data = await svc.dispatch(
        opcode=op.OP_GAP_ENCRYPT_EAD_DATA, controller_index=0,
        data=bytes([len(plaintext)]) + plaintext)
    assert status == op.BTP_STATUS_SUCCESS
    assert data[0] == len(expected)
    assert data[1:] == expected


@pytest.mark.asyncio
async def test_decrypt_ead_returns_the_plaintext():
    key = bytes.fromhex("57A9DA12D12E6E131E20612AD10A6A19")
    iv = bytes.fromhex("46E77AB1EF007A9E")
    plaintext = bytes.fromhex("0F0953686F7274204D696E692D42757303190A8C")
    ead_data = bytes.fromhex(
        "18E157CADE74E4DCAFDC51C7282810C2217F0E4CEF4343181FBA0069CC")

    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    await svc.dispatch(opcode=op.OP_GAP_SET_EAD_KEY_MATERIAL, controller_index=0,
                       data=key + iv[::-1])

    status, data = await svc.dispatch(
        opcode=op.OP_GAP_DECRYPT_EAD_DATA, controller_index=0,
        data=bytes([len(ead_data)]) + ead_data)
    assert status == op.BTP_STATUS_SUCCESS
    assert data == bytes([len(plaintext)]) + plaintext


@pytest.mark.asyncio
async def test_ead_commands_fail_before_key_material_is_set():
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_ENCRYPT_EAD_DATA, controller_index=0, data=b"\x01A")
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_set_filter_accept_list_programs_the_controller_list():
    """BTP bookkeeping alone changes nothing on the air: with
    Initiator_Filter_Policy 0x01 it is the *controller* that matches
    advertisers against its own filter accept list, so SET_FILTER_ACCEPT_LIST
    has to program it (GAP/CONN/ACEP)."""
    from unittest.mock import MagicMock

    actions = _FakeActions()
    programmed: list = []

    async def fake_program(entries):
        programmed.append(entries)

    actions.program_filter_accept_list = fake_program
    svc = GapService(actions=actions, tester=MagicMock())

    pts_wire = bytes.fromhex("ee6a1eff5394")
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_SET_FILTER_ACCEPT_LIST, controller_index=0,
        data=bytes([1, op.GAP_ADDR_TYPE_PUBLIC]) + pts_wire,
    )

    assert status == op.BTP_STATUS_SUCCESS
    assert programmed == [[(op.GAP_ADDR_TYPE_PUBLIC, pts_wire)]]


@pytest.mark.asyncio
async def test_start_discovery_reads_the_active_scan_bit_not_limited():
    """auto-pts's GAP_DISCOVERY_FLAG_*: LE=0x01, BR/EDR=0x02, LIMITED=0x04,
    LE_ACTIVE_SCAN=0x08, LE_OBSERVE=0x10.

    We read 0x04 (the *limited* bit) as "active", so every active scan the cases
    asked for was performed passively: no SCAN_REQ, no scan response, and every
    advertising report arrived with an empty response half — which is exactly
    what GAP/BROB/OBSV/BV-05/06 verify.
    """
    from unittest.mock import MagicMock

    actions = _FakeActions()
    captured: list = []

    async def fake_scan(*, active=False, on_result=None):
        captured.append(active)

    actions.scan = fake_scan
    svc = GapService(actions=actions, tester=MagicMock())

    # LE + active scan + observe: 0x01 | 0x08 | 0x10
    await svc.dispatch(opcode=op.OP_GAP_START_DISCOVERY, controller_index=0,
                       data=bytes([0x19]))
    # LE only: passive.
    await svc.dispatch(opcode=op.OP_GAP_START_DISCOVERY, controller_index=0,
                       data=bytes([0x01]))

    assert captured == [True, False]


@pytest.mark.asyncio
async def test_start_advertising_uses_filter_policy_when_accept_list_programmed():
    # GAP/BROB/BCST/BV-05-C: with a non-empty accept list the advertising
    # filter policy must be 0x03 so the controller ignores scan/connection
    # requests from the PTS dongle (deliberately absent from the list).
    from unittest.mock import MagicMock
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())
    svc._filter_accept_list = [(0, bytes.fromhex('ee6a1eff5395'))]
    adv_data = bytes([0x01, 0x01, 0x04])
    body = (
        bytes([len(adv_data), 0])
        + adv_data
        + (0).to_bytes(4, 'little')
        + bytes([op.GAP_ADDR_TYPE_PUBLIC])
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_START_ADVERTISING, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert actions.calls[0][1].get('filter_policy') == 0x03
