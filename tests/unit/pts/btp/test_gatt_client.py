"""GATT BTP client-side handlers — opcodes 0x0a/0x0b/0x0c.

Uses _FakeGattClient + _FakeActions to bypass the real stack."""
import pytest
from unittest.mock import MagicMock

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.gatt import GattService


class _FakeGattClient:
    def __init__(self):
        self.mtu_calls: list[int] = []
        self.next_mtu = 247
        self.discover_results = [
            # (start_handle, end_handle, uuid_bytes — LE wire form)
            (0x0001, 0x0005, bytes.fromhex("0018")),    # 0x1800 GAP
            (0x0006, 0x000F, bytes.fromhex("0F18")),    # 0x180F Battery
        ]

    async def exchange_mtu(self, mtu: int) -> int:
        self.mtu_calls.append(mtu)
        return self.next_mtu

    async def discover_all_services(self):
        return list(self.discover_results)


class _FakeIncludeClient(_FakeGattClient):
    def __init__(self):
        super().__init__()
        self.include_results = [
            # (include_handle, inc_start, inc_end, uuid_bytes — LE wire form)
            (0x0003, 0x0010, 0x0014, bytes.fromhex("0F18")),  # includes Battery 0x180F
        ]

    async def discover_included_services(self, start_handle, end_handle):
        return list(self.include_results)


class _ConnInfo:
    def __init__(self, peer, handle, gatt_client):
        self.peer = peer
        self.handle = handle
        self.transport = "le"
        self.gatt_client = gatt_client


class _FakeSession:
    def __init__(self):
        self.connections = {}


class _FakeActions:
    def __init__(self):
        self._session = _FakeSession()

    def status(self):
        return self._session


def _make_svc_with_conn(addr_bytes):
    actions = _FakeActions()
    client = _FakeGattClient()
    actions._session.connections[0x000C] = _ConnInfo(
        peer=addr_bytes, handle=0x000C, gatt_client=client,
    )
    svc = GattService(actions=actions, tester=MagicMock())
    return svc, client


@pytest.mark.asyncio
async def test_exchange_mtu_proposes_iut_mtu_empty_response():
    """Upstream EXCHANGE_MTU body is addr_type+addr (7 bytes, no MTU field);
    the IUT proposes its own preferred MTU and the response is empty."""
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + addr
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_EXCHANGE_MTU, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data == b""
    # IUT proposes its preferred MTU (247), not a peer-supplied value.
    assert client.mtu_calls == [247]


@pytest.mark.asyncio
async def test_exchange_mtu_unknown_peer_fails():
    svc, _ = _make_svc_with_conn(bytes.fromhex("AABBCCDDEEFF"))
    body = bytes([0]) + bytes.fromhex("000000000000") + (185).to_bytes(2, "little")
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_EXCHANGE_MTU, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_disc_all_prim_svcs_returns_encoded_list():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + addr
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_DISC_ALL_PRIM_SVCS, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    # Layout: count(u8) + [start(2) + end(2) + uuid_len(1) + uuid_bytes]*
    assert data[0] == 2
    offset = 1
    # First entry: 0x0001-0x0005 GAP service (0x1800)
    s = int.from_bytes(data[offset:offset+2], "little"); offset += 2
    e = int.from_bytes(data[offset:offset+2], "little"); offset += 2
    ul = data[offset]; offset += 1
    uu = data[offset:offset+ul]; offset += ul
    assert (s, e, ul, uu) == (0x0001, 0x0005, 2, bytes.fromhex("0018"))
    # Second entry: 0x0006-0x000F Battery (0x180F)
    s = int.from_bytes(data[offset:offset+2], "little"); offset += 2
    e = int.from_bytes(data[offset:offset+2], "little"); offset += 2
    ul = data[offset]; offset += 1
    uu = data[offset:offset+ul]; offset += ul
    assert (s, e, ul, uu) == (0x0006, 0x000F, 2, bytes.fromhex("0F18"))


def _make_include_svc_with_conn(addr_bytes):
    actions = _FakeActions()
    client = _FakeIncludeClient()
    actions._session.connections[0x000C] = _ConnInfo(
        peer=addr_bytes, handle=0x000C, gatt_client=client,
    )
    svc = GattService(actions=actions, tester=MagicMock())
    return svc, client


@pytest.mark.asyncio
async def test_find_included_returns_encoded_list():
    """FIND_INCLUDED_SVCS (0x0d): discover Include declarations (0x2802) and
    encode count + [incl_handle + inc_start + inc_end + uuid_len + uuid]*."""
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_include_svc_with_conn(addr)
    body = (bytes([op.GAP_ADDR_TYPE_RANDOM]) + addr
            + (0x0001).to_bytes(2, "little") + (0xFFFF).to_bytes(2, "little"))
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_FIND_INCLUDED_SVCS, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data[0] == 1  # one include
    incl_h = int.from_bytes(data[1:3], "little")
    inc_s = int.from_bytes(data[3:5], "little")
    inc_e = int.from_bytes(data[5:7], "little")
    ul = data[7]
    uu = data[8:8+ul]
    assert (incl_h, inc_s, inc_e, ul, uu) == (
        0x0003, 0x0010, 0x0014, 2, bytes.fromhex("0F18"))


@pytest.mark.asyncio
async def test_find_included_wrong_length_fails():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, _ = _make_include_svc_with_conn(addr)
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + addr + bytes([0x01])  # truncated
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_FIND_INCLUDED_SVCS, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_disc_prim_svc_by_uuid_filters_results():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + addr + bytes([2]) + bytes.fromhex("0F18")
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_DISC_PRIM_SVC_BY_UUID, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    # Only the Battery service (UUID 0x180F) survives the filter.
    assert data[0] == 1
    s = int.from_bytes(data[1:3], "little")
    e = int.from_bytes(data[3:5], "little")
    assert (s, e) == (0x0006, 0x000F)


@pytest.mark.asyncio
async def test_exchange_mtu_rejects_wrong_length():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, _ = _make_svc_with_conn(addr)
    body = bytes([0]) + addr[:5]   # truncated: < 7 bytes
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_EXCHANGE_MTU, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


# ---------------------------------------------------------------------------
# Task 6 — Discover Characteristics + Descriptors
# ---------------------------------------------------------------------------

from dataclasses import dataclass


@dataclass
class _FakeChar:
    declaration_handle: int
    value_handle: int
    properties: int
    uuid: bytes


@dataclass
class _FakeDesc:
    handle: int
    uuid: bytes


@pytest.mark.asyncio
async def test_disc_all_chrc_returns_encoded_list():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    fake_chars = [
        _FakeChar(declaration_handle=0x0006, value_handle=0x0007,
                  properties=0x12, uuid=bytes.fromhex("1929")),
        _FakeChar(declaration_handle=0x0009, value_handle=0x000A,
                  properties=0x02, uuid=bytes.fromhex("0A2A")),
    ]
    async def fake_dc(start, end):
        return list(fake_chars)
    client.discover_characteristics = fake_dc

    body = bytes([0]) + addr + (0x0001).to_bytes(2, "little") + (0x000F).to_bytes(2, "little")
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_DISC_ALL_CHRC, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data[0] == 2
    # Decode first entry (auto-pts order: handle, value_handle, props, uuid_len, uuid).
    offset = 1
    decl = int.from_bytes(data[offset:offset+2], "little"); offset += 2
    vh = int.from_bytes(data[offset:offset+2], "little"); offset += 2
    props = data[offset]; offset += 1
    ul = data[offset]; offset += 1
    uu = data[offset:offset+ul]; offset += ul
    assert (decl, vh, props, ul, uu) == (0x0006, 0x0007, 0x12, 2, bytes.fromhex("1929"))


@pytest.mark.asyncio
async def test_disc_chrc_by_uuid_filters_results():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    fake_chars = [
        _FakeChar(0x0006, 0x0007, 0x12, bytes.fromhex("1929")),
        _FakeChar(0x0009, 0x000A, 0x02, bytes.fromhex("0A2A")),
    ]
    async def fake_dc(start, end):
        return list(fake_chars)
    client.discover_characteristics = fake_dc

    body = (
        bytes([0]) + addr
        + (0x0001).to_bytes(2, "little") + (0x000F).to_bytes(2, "little")
        + bytes([2]) + bytes.fromhex("0A2A")
    )
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_DISC_CHRC_BY_UUID, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data[0] == 1
    decl = int.from_bytes(data[1:3], "little")
    assert decl == 0x0009


@pytest.mark.asyncio
async def test_disc_all_desc_returns_encoded_list():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    fake_descs = [
        _FakeDesc(handle=0x0008, uuid=bytes.fromhex("0229")),
    ]
    async def fake_dd(start, end):
        return list(fake_descs)
    client.discover_descriptors = fake_dd

    body = bytes([0]) + addr + (0x0001).to_bytes(2, "little") + (0x000F).to_bytes(2, "little")
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_DISC_ALL_DESC, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data[0] == 1
    h = int.from_bytes(data[1:3], "little")
    ul = data[3]
    uu = data[4:4+ul]
    assert (h, ul, uu) == (0x0008, 2, bytes.fromhex("0229"))


@pytest.mark.asyncio
async def test_find_included_svcs_returns_failed_not_supported():
    """FIND_INCLUDED_SVCS not on real GATTClient — handler returns STATUS_FAILED."""
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, _ = _make_svc_with_conn(addr)
    body = bytes([0]) + addr + (0x0001).to_bytes(2, "little") + (0x000F).to_bytes(2, "little")
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_FIND_INCLUDED_SVCS, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


# ---------------------------------------------------------------------------
# Task 7 — Client Read + Write (opcodes 0x11/0x13/0x14/0x15/0x17/0x18/0x19)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_returns_value_with_att_status():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    # Inject a known value at handle 0x0007.
    async def fake_read(handle):
        if handle == 0x0007:
            return b"\xAA\xBB\xCC"
        return b""
    client.read_long_characteristic = fake_read

    body = bytes([0]) + addr + (0x0007).to_bytes(2, "little")
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_READ, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    # Response: att_response(u8=0x00) + value_len(u16 LE) + value
    assert data[0] == 0x00
    assert int.from_bytes(data[1:3], "little") == 3
    assert data[3:6] == b"\xAA\xBB\xCC"


@pytest.mark.asyncio
async def test_read_returns_att_error_code_in_payload():
    """BI (error-handling) cases: an ATT error must come back as BTP_STATUS_SUCCESS
    with ATT_Response=error_code + zero-length value, so PTS can verify the
    expected error — not as a BTP-layer failure."""
    from pybluehost.ble.att import ATTError
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    async def fake_read(handle):
        raise ATTError(0x01)        # Invalid Handle
    client.read_long_characteristic = fake_read

    body = bytes([0]) + addr + (0x0007).to_bytes(2, "little")
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_READ, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data[0] == 0x01                       # ATT_Response = Invalid Handle
    assert int.from_bytes(data[1:3], "little") == 0   # zero-length value


@pytest.mark.asyncio
async def test_read_non_att_error_is_btp_failure():
    """A non-ATT exception (transport/no-channel) is a genuine BTP failure."""
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    async def fake_read(handle):
        raise RuntimeError("link dropped")
    client.read_long_characteristic = fake_read

    body = bytes([0]) + addr + (0x0007).to_bytes(2, "little")
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_READ, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_read_completes_long_value_beyond_mtu():
    """GATT/CL/GAR/BV-04: BTP READ must return the FULL value (Read + Read
    Blob continuation inside the client), not just the first ATT_MTU-1 chunk —
    PTS waits for the whole long-read procedure before issuing the next MMI."""
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    async def fake_read_long(handle):
        return b"\x11" * 100  # far beyond ATT_MTU-1
    client.read_long_characteristic = fake_read_long

    body = bytes([0]) + addr + (0x0007).to_bytes(2, "little")
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_READ, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data[0] == 0x00
    assert int.from_bytes(data[1:3], "little") == 100
    assert data[3:] == b"\x11" * 100


@pytest.mark.asyncio
async def test_read_long_uses_blob_pagination():
    """READ_LONG (0x13) body: addr_type+addr+handle(u16)+offset(u16).
    Must call read_long_characteristic (Read + Read Blob pagination)."""
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    calls: list[tuple[int, int]] = []

    async def fake_read_long(handle, offset=0):
        calls.append((handle, offset))
        return b"\x01" * 50
    client.read_long_characteristic = fake_read_long

    body = (
        bytes([0]) + addr + (0x0007).to_bytes(2, "little")
        + (0).to_bytes(2, "little")  # offset
    )
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_READ_LONG, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert calls == [(0x0007, 0)]
    assert data[0] == 0x00
    assert int.from_bytes(data[1:3], "little") == 50


@pytest.mark.asyncio
async def test_read_long_rejects_9byte_read_body():
    """READ (0x11)-style 9-byte body (no offset) is malformed for READ_LONG."""
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    body = bytes([0]) + addr + (0x0007).to_bytes(2, "little")
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_READ_LONG, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_read_uuid_returns_matching_values():
    """READ_UUID (0x12): body addr_type+addr+start+end+uuid_len+uuid;
    response att_status(u8)+count(u8)+[handle(u16)+len(u8)+data]*."""
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    captured = {}

    async def fake_read_uuid(start, end, uuid):
        captured["args"] = (start, end, uuid)
        return 0x00, [(0x0021, b"\x2A"), (0x0023, b"\x2B")]
    client.read_using_characteristic_uuid = fake_read_uuid

    uuid = bytes.fromhex("0F18")  # 0x180F Battery, LE wire
    body = (
        bytes([0]) + addr
        + (0x0001).to_bytes(2, "little") + (0xFFFF).to_bytes(2, "little")
        + bytes([len(uuid)]) + uuid
    )
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_READ_UUID, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert captured["args"] == (0x0001, 0xFFFF, uuid)
    assert data[0] == 0x00            # ATT_Response success
    assert data[1] == 0x02            # two values
    # first entry: handle 0x0021, len 1, 0x2A
    assert int.from_bytes(data[2:4], "little") == 0x0021
    assert data[4] == 1 and data[5] == 0x2A
    # second entry: handle 0x0023, len 1, 0x2B
    assert int.from_bytes(data[6:8], "little") == 0x0023
    assert data[8] == 1 and data[9] == 0x2B


@pytest.mark.asyncio
async def test_read_uuid_propagates_att_error_status():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    async def fake_read_uuid(start, end, uuid):
        return 0x0A, []             # Attribute Not Found
    client.read_using_characteristic_uuid = fake_read_uuid

    uuid = bytes.fromhex("0F18")
    body = (
        bytes([0]) + addr
        + (0x0001).to_bytes(2, "little") + (0xFFFF).to_bytes(2, "little")
        + bytes([len(uuid)]) + uuid
    )
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_READ_UUID, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS   # BTP layer OK; ATT layer reports the error
    assert data[0] == 0x0A
    assert data[1] == 0x00


@pytest.mark.asyncio
async def test_read_uuid_rejects_bad_uuid_length():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    uuid = bytes.fromhex("0F18FF")            # length 3 — invalid
    body = (
        bytes([0]) + addr
        + (0x0001).to_bytes(2, "little") + (0xFFFF).to_bytes(2, "little")
        + bytes([len(uuid)]) + uuid
    )
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_READ_UUID, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_read_multiple_uses_single_att_request():
    """READ_MULTIPLE (0x14) must send ONE ATT Read Multiple Request via
    read_multiple_characteristic — the PTS lower tester verifies that PDU."""
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    calls: list[list[int]] = []

    async def fake_read_multiple(handles):
        calls.append(list(handles))
        return b"\xAA\xBB\xCC"
    client.read_multiple_characteristic = fake_read_multiple

    # Body: addr_type+addr + handles_count(u8) + handles(2×n)
    body = (
        bytes([0]) + addr + bytes([2])
        + (0x0007).to_bytes(2, "little")
        + (0x0009).to_bytes(2, "little")
    )
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_READ_MULTIPLE, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert calls == [[0x0007, 0x0009]]
    assert data[0] == 0x00
    assert int.from_bytes(data[1:3], "little") == 3
    assert data[3:6] == b"\xAA\xBB\xCC"


@pytest.mark.asyncio
async def test_read_multiple_var_returns_raw_concatenated_values():
    """READ_MULTIPLE_VAR (0x20): single ATT Read Multiple Variable Length Request.
    Response: att_response(u8)+total_data_len(u16)+data, where data is the RAW
    concatenation of the values — upstream's gattc_read_multiple_var_rsp decodes
    it with gatt_dec_read_rsp (<BH + raw bytes) and hexlifies the WHOLE blob for
    the WID-55 substring check, so any per-value length prefix would pollute the
    hex and make GAR/BV-08-C's value verification unsatisfiable."""
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    calls: list[list[int]] = []

    async def fake_rmv(handles, *, bearer=None):
        calls.append(list(handles))
        return [b"\x11", b"\x22\x33\x44"]
    client.read_multiple_variable_characteristic = fake_rmv

    body = (
        bytes([0]) + addr + bytes([2])
        + (0x0007).to_bytes(2, "little")
        + (0x0009).to_bytes(2, "little")
    )
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_READ_MULTIPLE_VAR, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert calls == [[0x0007, 0x0009]]
    assert data[0] == 0x00
    # raw concatenation, no per-value length prefixes
    assert int.from_bytes(data[1:3], "little") == 4
    assert data[3:] == b"\x11\x22\x33\x44"


@pytest.mark.asyncio
async def test_read_multiple_var_propagates_att_error():
    """BI cases: ATT error must come back as BTP_STATUS_SUCCESS + ATT_Response
    byte + zero total_data_len, so PTS can verify the expected error."""
    from pybluehost.ble.att import ATTError
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    async def fake_rmv(handles, *, bearer=None):
        raise ATTError(0x01)        # Invalid Handle
    client.read_multiple_variable_characteristic = fake_rmv

    body = (
        bytes([0]) + addr + bytes([1])
        + (0x0007).to_bytes(2, "little")
    )
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_READ_MULTIPLE_VAR, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data[0] == 0x01
    assert int.from_bytes(data[1:3], "little") == 0


@pytest.mark.asyncio
async def test_read_multiple_var_rejects_truncated_body():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, _ = _make_svc_with_conn(addr)
    # count=2 but only one handle present.
    body = bytes([0]) + addr + bytes([2]) + (0x0007).to_bytes(2, "little")
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_READ_MULTIPLE_VAR, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_write_dispatches_and_returns_att_status():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    write_log: list[tuple[int, bytes]] = []
    async def fake_write(handle, value):
        write_log.append((handle, value))
    client.write_characteristic = fake_write

    body = (
        bytes([0]) + addr + (0x0007).to_bytes(2, "little")
        + (3).to_bytes(2, "little") + b"\x01\x02\x03"
    )
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_WRITE, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data == bytes([0x00])
    assert write_log == [(0x0007, b"\x01\x02\x03")]


@pytest.mark.asyncio
async def test_write_without_response_logs_write():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    write_log: list[tuple[int, bytes]] = []
    async def fake_write(handle, value):
        write_log.append((handle, value))
    client.write_characteristic = fake_write

    body = (
        bytes([0]) + addr + (0x0007).to_bytes(2, "little")
        + (2).to_bytes(2, "little") + b"\xAA\xBB"
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_WRITE_WITHOUT_RSP, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert write_log == [(0x0007, b"\xAA\xBB")]


@pytest.mark.asyncio
async def test_write_long_uses_prepare_execute_path():
    """WRITE_LONG (0x18) must go through write_long_characteristic (ATT
    Prepare/Execute Write), not a single ATT Write Request — the PTS lower
    tester verifies the long-write procedure explicitly.
    Body: addr_type+addr+handle(u16)+offset(u16)+value_len(u16)+value."""
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    write_log: list[tuple[int, bytes, int]] = []
    plain_log: list[tuple[int, bytes]] = []

    async def fake_write_long(handle, value, offset=0):
        write_log.append((handle, value, offset))

    async def fake_write(handle, value):  # must NOT be called for WRITE_LONG
        plain_log.append((handle, value))
    client.write_long_characteristic = fake_write_long
    client.write_characteristic = fake_write

    payload = b"\x00" * 30
    body = (
        bytes([0]) + addr + (0x0007).to_bytes(2, "little")
        + (0).to_bytes(2, "little")  # offset
        + len(payload).to_bytes(2, "little") + payload
    )
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_WRITE_LONG, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data == bytes([0x00])
    assert write_log == [(0x0007, payload, 0)]
    assert plain_log == []


@pytest.mark.asyncio
async def test_write_long_rejects_truncated_body():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    # addr_type+addr+handle only (9 bytes < 13) — missing offset/len/value.
    body = bytes([0]) + addr + (0x0007).to_bytes(2, "little")
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_WRITE_LONG, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED
