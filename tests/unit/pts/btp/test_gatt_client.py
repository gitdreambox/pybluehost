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
async def test_exchange_mtu_returns_negotiated_value():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client = _make_svc_with_conn(addr)
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + addr + (517).to_bytes(2, "little")
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_EXCHANGE_MTU, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert int.from_bytes(data, "little") == 247
    assert client.mtu_calls == [517]


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
    body = bytes([0]) + addr   # missing 2-byte mtu suffix
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_EXCHANGE_MTU, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED
