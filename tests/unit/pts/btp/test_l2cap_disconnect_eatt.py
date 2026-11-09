"""BTP L2CAP DISCONNECT_EATT_CHANS (0x09) — disconnect N EATT bearers by CID
order (auto-pts WID 144; wire format per auto-pts l2cap_disconn_eatt_chans)."""
from __future__ import annotations

import pytest

from pybluehost.ble.gatt import GATTServer
from pybluehost.l2cap.constants import PSM_EATT
from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.l2cap import LeCoCService

pytestmark = pytest.mark.asyncio

WIRE_ADDR = bytes.fromhex("010203040506")
CONN = 0x0E01


class _FakePeer:
    def to_hci(self) -> bytes:
        return WIRE_ADDR


class _ConnInfo:
    peer = _FakePeer()


class _Session:
    connections = {CONN: _ConnInfo()}


class _FakeChannel:
    def __init__(self, cid: int, psm) -> None:
        self.cid = cid
        self.psm = psm
        self.connection_handle = CONN


class _FakeL2CAP:
    def __init__(self, channels, *, raise_on_cid: int | None = None) -> None:
        self._connections = {CONN: {ch.cid: ch for ch in channels}}
        self.disconnected: list[int] = []
        self.raise_on_cid = raise_on_cid

    async def disconnect_le_coc_channel(self, channel) -> None:
        if self.raise_on_cid is not None and channel.cid == self.raise_on_cid:
            raise RuntimeError("simulated disconnect failure")
        self.disconnected.append(channel.cid)
        self._connections[CONN].pop(channel.cid, None)

    def le_coc_channels(self, handle: int) -> list:
        return list(self._connections.get(handle, {}).values())

    def on_le_channel_reconfigured(self, cb) -> None:
        pass


class _FakeStack:
    def __init__(self, channels, *, raise_on_cid: int | None = None) -> None:
        self.l2cap = _FakeL2CAP(channels, raise_on_cid=raise_on_cid)
        self.gatt_server = GATTServer()


class _FakeActions:
    def __init__(self, channels, *, raise_on_cid: int | None = None) -> None:
        self._stack = _FakeStack(channels, raise_on_cid=raise_on_cid)

    def status(self):
        return _Session()


class _FakeTester:
    def emit_event(self, *args, **kwargs):
        pass


def _service(*cids_and_psms, raise_on_cid: int | None = None) -> LeCoCService:
    channels = [_FakeChannel(cid, psm) for cid, psm in cids_and_psms]
    return LeCoCService(
        actions=_FakeActions(channels, raise_on_cid=raise_on_cid),
        tester=_FakeTester(),
    )


async def test_disconnects_first_n_eatt_channels_by_cid_order():
    service = _service((0x45, PSM_EATT), (0x41, PSM_EATT), (0x43, PSM_EATT), (0x50, 0x0080))
    status, payload = await service._handle_op_09(0, bytes([0x00]) + WIRE_ADDR + bytes([2]))
    assert status == op.BTP_STATUS_SUCCESS
    assert payload == b""
    # Lowest two EATT CIDs; the 0x0080 CoC channel is untouched.
    assert service._actions._stack.l2cap.disconnected == [0x41, 0x43]


async def test_count_beyond_available_disconnects_all_eatt():
    service = _service((0x41, PSM_EATT), (0x42, PSM_EATT))
    status, _ = await service._handle_op_09(0, bytes([0x00]) + WIRE_ADDR + bytes([5]))
    assert status == op.BTP_STATUS_SUCCESS
    assert service._actions._stack.l2cap.disconnected == [0x41, 0x42]


async def test_disconnect_drops_the_gatt_bearer_state():
    service = _service((0x41, PSM_EATT))
    server = service._actions._stack.gatt_server
    server.add_eatt_bearer(CONN, 0x41, mtu=100)
    status, _ = await service._handle_op_09(0, bytes([0x00]) + WIRE_ADDR + bytes([1]))
    assert status == op.BTP_STATUS_SUCCESS
    assert not server.is_eatt_bearer(CONN, 0x41)
    assert server._att_mtu(CONN, 0x41) == 23


async def test_unknown_peer_fails():
    service = _service((0x41, PSM_EATT))
    status, _ = await service._handle_op_09(0, bytes([0x00]) + bytes(6) + bytes([1]))
    assert status == op.BTP_STATUS_FAILED


async def test_disconnect_failure_returns_failed():
    # Force the second (lowest-CID) disconnect to fail; expect FAILED and
    # partial teardown (the first bearer is removed, the second remains).
    service = _service((0x41, PSM_EATT), (0x42, PSM_EATT), raise_on_cid=0x42)
    server = service._actions._stack.gatt_server
    server.add_eatt_bearer(CONN, 0x41, mtu=100)
    server.add_eatt_bearer(CONN, 0x42, mtu=100)
    status, _ = await service._handle_op_09(0, bytes([0x00]) + WIRE_ADDR + bytes([2]))
    assert status == op.BTP_STATUS_FAILED
    assert service._actions._stack.l2cap.disconnected == [0x41]
    assert not server.is_eatt_bearer(CONN, 0x41)
    assert server.is_eatt_bearer(CONN, 0x42)
