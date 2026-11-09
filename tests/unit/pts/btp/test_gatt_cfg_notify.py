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


class _FakeAttBearer:
    def __init__(self):
        self._notify_cb = None
        self._indicate_cb = None

    def set_notification_handler(self, cb):
        self._notify_cb = cb

    def set_indication_handler(self, cb):
        self._indicate_cb = cb


class _FakeGattClient:
    def __init__(self):
        self.write_log: list[tuple[int, bytes]] = []
        self._bearer = _FakeAttBearer()

    async def write_characteristic(self, handle, value):
        self.write_log.append((handle, value))

    def simulate_incoming(self, char_handle, value):
        if self._bearer._notify_cb is not None:
            self._bearer._notify_cb(char_handle, value)

    def simulate_indication(self, char_handle, value):
        if self._bearer._indicate_cb is not None:
            self._bearer._indicate_cb(char_handle, value)


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
    # Payload: addr_type(1) + addr(6) + notification_type(1) + handle(u16 LE)
    #          + value_len(u16 LE) + value   (matches auto-pts gattc_dec_notification_ev_data)
    assert ev.data[0] == op.GAP_ADDR_TYPE_RANDOM
    assert ev.data[1:7] == addr
    assert ev.data[7] == 1  # notification
    assert int.from_bytes(ev.data[8:10], "little") == 0x0007
    assert int.from_bytes(ev.data[10:12], "little") == 1
    assert ev.data[12:] == b"\x42"


@pytest.mark.asyncio
async def test_incoming_indication_emits_btp_event_with_type_2():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client, tester = _make_svc_with_conn(addr)
    svc.attach_to_gatt_client(client, peer=addr, addr_type=op.GAP_ADDR_TYPE_RANDOM)

    client.simulate_indication(0x0009, b"\x99")
    await asyncio.sleep(0)
    assert len(tester.events) == 1
    ev = tester.events[0]
    assert ev.opcode == op.OP_GATT_EVENT_NOTIFICATION
    assert ev.data[7] == 2  # indication
    assert int.from_bytes(ev.data[8:10], "little") == 0x0009
    assert ev.data[12:] == b"\x99"


@pytest.mark.asyncio
async def test_attach_to_gatt_client_is_idempotent():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client, tester = _make_svc_with_conn(addr)
    svc.attach_to_gatt_client(client, peer=addr, addr_type=op.GAP_ADDR_TYPE_RANDOM)
    first_cb = client._bearer._notify_cb
    svc.attach_to_gatt_client(client, peer=addr, addr_type=op.GAP_ADDR_TYPE_RANDOM)
    assert client._bearer._notify_cb is first_cb  # not re-registered

    client.simulate_incoming(0x0007, b"\x42")
    await asyncio.sleep(0)
    assert len(tester.events) == 1  # single forward, not duplicated


@pytest.mark.asyncio
async def test_notification_dropped_while_encrypt_pending():
    """SEC/SEM: unencrypted + re-encryption in flight -> DROP (CFM only, never
    report to Upper Tester). GAP.TS step 9A.4/9B.4: the pre-encryption IND is not
    forwarded; PTS sends a *second* IND after encryption which is. Holding and
    flushing the first would leak it into the WID-236 'must not report' check."""
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client, tester = _make_svc_with_conn(addr)
    svc.attach_to_gatt_client(
        client, peer=addr, addr_type=op.GAP_ADDR_TYPE_RANDOM,
        conn_handle=0x000C,
        is_encrypted=lambda h: False,
        encrypt_pending=lambda h: True,
    )
    client.simulate_incoming(0x0007, b"\x42")
    await asyncio.sleep(0)
    assert len(tester.events) == 0  # dropped, not forwarded (and no flush path)


@pytest.mark.asyncio
async def test_notification_forwarded_immediately_when_no_encryption_expected():
    """Plain GAN: unencrypted but no re-encryption coming -> forward now."""
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client, tester = _make_svc_with_conn(addr)
    svc.attach_to_gatt_client(
        client, peer=addr, addr_type=op.GAP_ADDR_TYPE_RANDOM,
        conn_handle=0x000C,
        is_encrypted=lambda h: False,
        encrypt_pending=lambda h: False,
    )
    client.simulate_incoming(0x0007, b"\x42")
    await asyncio.sleep(0)
    assert len(tester.events) == 1


@pytest.mark.asyncio
async def test_notification_forwarded_immediately_when_encrypted():
    addr = bytes.fromhex("AABBCCDDEEFF")
    svc, client, tester = _make_svc_with_conn(addr)
    svc.attach_to_gatt_client(
        client, peer=addr, addr_type=op.GAP_ADDR_TYPE_RANDOM,
        conn_handle=0x000C,
        is_encrypted=lambda h: True,
        encrypt_pending=lambda h: False,
    )
    client.simulate_incoming(0x0007, b"\x42")
    await asyncio.sleep(0)
    assert len(tester.events) == 1
