"""GATT BTP — Cfg Notify (0x1A) / Cfg Indicate (0x1B) + Notification event (0x80)."""
import asyncio

import pytest

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import BtpFrame
from pybluehost.pts.btp.services.gatt import GattService


class _FakeTester:
    def __init__(self):
        self.events: list[BtpFrame] = []

    async def emit_event(self, frame):
        self.events.append(frame)


class _FakeGattClient:
    def __init__(self):
        self.write_log: list[tuple[int, bytes]] = []
        self._notify_cb = None

    async def write_characteristic(self, handle, value):
        self.write_log.append((handle, value))

    def on_notification(self, cb):
        self._notify_cb = cb

    def simulate_incoming(self, char_handle, value):
        if self._notify_cb is not None:
            self._notify_cb(char_handle, value)


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


def _make_svc_with_conn(addr):
    actions = _FakeActions()
    client = _FakeGattClient()
    actions._session.connections[0x000C] = _ConnInfo(
        peer=addr, handle=0x000C, gatt_client=client,
    )
    tester = _FakeTester()
    svc = GattService(actions=actions, tester=tester)
    return svc, client, tester


@pytest.mark.asyncio
async def test_cfg_notify_enable_writes_0001_to_cccd():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client, _ = _make_svc_with_conn(addr)
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + addr + bytes([1]) + (0x0008).to_bytes(2, "little")
    status, _ = await svc.dispatch(opcode=op.OP_GATT_CFG_NOTIFY, controller_index=0, data=body)
    assert status == op.BTP_STATUS_SUCCESS
    assert client.write_log == [(0x0008, b"\x01\x00")]


@pytest.mark.asyncio
async def test_cfg_indicate_enable_writes_0002_to_cccd():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client, _ = _make_svc_with_conn(addr)
    body = bytes([op.GAP_ADDR_TYPE_RANDOM]) + addr + bytes([1]) + (0x0008).to_bytes(2, "little")
    status, _ = await svc.dispatch(opcode=op.OP_GATT_CFG_INDICATE, controller_index=0, data=body)
    assert status == op.BTP_STATUS_SUCCESS
    assert client.write_log == [(0x0008, b"\x02\x00")]


@pytest.mark.asyncio
async def test_cfg_notify_disable_writes_zero_cccd():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client, _ = _make_svc_with_conn(addr)
    body = bytes([0]) + addr + bytes([0]) + (0x0008).to_bytes(2, "little")
    status, _ = await svc.dispatch(opcode=op.OP_GATT_CFG_NOTIFY, controller_index=0, data=body)
    assert status == op.BTP_STATUS_SUCCESS
    assert client.write_log == [(0x0008, b"\x00\x00")]


@pytest.mark.asyncio
async def test_cfg_notify_unknown_peer_fails():
    svc, _, _ = _make_svc_with_conn(bytes.fromhex("AABBCCDDEEFF"))
    body = bytes([0]) + bytes.fromhex("000000000000") + bytes([1]) + (0x0008).to_bytes(2, "little")
    status, _ = await svc.dispatch(opcode=op.OP_GATT_CFG_NOTIFY, controller_index=0, data=body)
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_incoming_notification_emits_btp_event():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client, tester = _make_svc_with_conn(addr)
    svc.attach_to_gatt_client(client, peer=addr, addr_type=op.GAP_ADDR_TYPE_RANDOM)

    client.simulate_incoming(0x0007, b"\x42")
    await asyncio.sleep(0)
    assert len(tester.events) == 1
    ev = tester.events[0]
    assert ev.service == op.SERVICE_GATT
    assert ev.opcode == op.OP_GATT_EVENT_NOTIFICATION
    # Payload: addr_type(1) + addr(6) + handle(u16 LE) + value_len(u16 LE) + value
    assert ev.data[0] == op.GAP_ADDR_TYPE_RANDOM
    assert ev.data[1:7] == addr
    assert int.from_bytes(ev.data[7:9], "little") == 0x0007
    assert int.from_bytes(ev.data[9:11], "little") == 1
    assert ev.data[11:] == b"\x42"
