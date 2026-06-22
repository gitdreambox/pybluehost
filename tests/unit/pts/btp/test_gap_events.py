"""GAP event emission tests — scan callback -> DEVICE_FOUND."""
import asyncio
from dataclasses import dataclass

import pytest

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import BtpFrame
from pybluehost.pts.btp.services.gap import GapService


class _FakeTester:
    def __init__(self):
        self.events: list[BtpFrame] = []

    async def emit_event(self, frame: BtpFrame) -> None:
        self.events.append(frame)


@dataclass
class _FakeBDAddress:
    address_type: int
    raw: bytes

    @property
    def bytes(self) -> bytes:
        return self.raw


@dataclass
class _FakeAdvData:
    raw: bytes

    def to_bytes(self) -> bytes:
        return self.raw


@dataclass
class _FakeScanResult:
    address: _FakeBDAddress
    rssi: int
    advertising_data: _FakeAdvData
    connectable: bool = True


class _FakeActions:
    def __init__(self):
        self.calls = []
        self._scan_handler = None

    async def scan(self, *, active=False, on_result=None):
        self.calls.append(("scan", {"active": active}))
        self._scan_handler = on_result

    async def stop_scan(self):
        self.calls.append(("stop_scan", {}))
        self._scan_handler = None

    def simulate_scan_result(self, result):
        if self._scan_handler is not None:
            self._scan_handler(result)


@pytest.mark.asyncio
async def test_device_found_event_emitted_on_scan_result():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    await svc.dispatch(opcode=op.OP_GAP_START_DISCOVERY, controller_index=0,
                       data=bytes([1]))

    result = _FakeScanResult(
        address=_FakeBDAddress(address_type=op.GAP_ADDR_TYPE_RANDOM,
                               raw=bytes.fromhex("FFEEDDCCBBAA")),
        rssi=-50,
        advertising_data=_FakeAdvData(raw=bytes.fromhex("020106")),
        connectable=True,
    )
    actions.simulate_scan_result(result)
    await asyncio.sleep(0)

    assert len(tester.events) == 1
    event = tester.events[0]
    assert event.service == op.SERVICE_GAP
    assert event.opcode == op.OP_GAP_EVENT_DEVICE_FOUND
    # Payload: addr_type(u8) + addr(6) + rssi(s8) + flags(u8) + eir_len(u16 LE) + eir
    assert event.data[0] == op.GAP_ADDR_TYPE_RANDOM
    assert event.data[1:7] == bytes.fromhex("FFEEDDCCBBAA")
    assert event.data[7] == (256 - 50) & 0xFF      # int8(-50) as u8
    assert event.data[8] & 0x01                    # connectable flag
    assert int.from_bytes(event.data[9:11], "little") == 3
    assert event.data[11:14] == bytes.fromhex("020106")


@pytest.mark.asyncio
async def test_stop_discovery_clears_callback():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    await svc.dispatch(opcode=op.OP_GAP_START_DISCOVERY, controller_index=0,
                       data=bytes([1]))
    status, _ = await svc.dispatch(opcode=op.OP_GAP_STOP_DISCOVERY,
                                   controller_index=0, data=b"")
    assert status == op.BTP_STATUS_SUCCESS
    # After stop, simulating a result should not fire an event.
    result = _FakeScanResult(
        address=_FakeBDAddress(address_type=0, raw=bytes(6)),
        rssi=0, advertising_data=_FakeAdvData(raw=b""),
    )
    actions.simulate_scan_result(result)
    await asyncio.sleep(0)
    assert len(tester.events) == 0


# ---------------------------------------------------------------------------
# T6: DEVICE_CONNECTED / DEVICE_DISCONNECTED events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_device_connected_event_on_state_change():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    svc.on_connection_state_change(
        handle=0x000C, addr=bytes.fromhex("AABBCCDDEEFF"),
        addr_type=op.GAP_ADDR_TYPE_RANDOM, connected=True,
    )
    await asyncio.sleep(0)
    assert len(tester.events) == 1
    evt = tester.events[0]
    assert evt.opcode == op.OP_GAP_EVENT_DEVICE_CONNECTED
    assert evt.data[0] == op.GAP_ADDR_TYPE_RANDOM
    assert evt.data[1:7] == bytes.fromhex("AABBCCDDEEFF")
    # Payload includes conn_interval(2) + latency(2) + timeout(2) — 13 bytes total
    assert len(evt.data) == 13


@pytest.mark.asyncio
async def test_device_disconnected_event_on_state_change():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    svc.on_connection_state_change(
        handle=0x000C, addr=bytes.fromhex("AABBCCDDEEFF"),
        addr_type=op.GAP_ADDR_TYPE_RANDOM, connected=True,
    )
    svc.on_connection_state_change(
        handle=0x000C, addr=bytes.fromhex("AABBCCDDEEFF"),
        addr_type=op.GAP_ADDR_TYPE_RANDOM, connected=False,
    )
    await asyncio.sleep(0)
    assert tester.events[-1].opcode == op.OP_GAP_EVENT_DEVICE_DISCONNECTED
    assert len(tester.events[-1].data) == 7


# ---------------------------------------------------------------------------
# T7: Pairing events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pairing_failed_event_emitted():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    svc.on_pairing_failed(addr=bytes.fromhex("AABBCCDDEEFF"),
                          addr_type=op.GAP_ADDR_TYPE_RANDOM, reason=0x05)
    await asyncio.sleep(0)
    assert len(tester.events) == 1
    evt = tester.events[0]
    assert evt.opcode == op.OP_GAP_EVENT_PAIRING_FAILED
    assert evt.data == bytes([op.GAP_ADDR_TYPE_RANDOM]) + bytes.fromhex("AABBCCDDEEFF") + bytes([0x05])


@pytest.mark.asyncio
async def test_sec_level_changed_event_emitted():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    svc.on_sec_level_changed(addr=bytes(6), addr_type=0, sec_level=2)
    await asyncio.sleep(0)
    assert len(tester.events) == 1
    assert tester.events[-1].opcode == op.OP_GAP_EVENT_SEC_LEVEL_CHANGED
    assert tester.events[-1].data[-1] == 2


@pytest.mark.asyncio
async def test_passkey_display_event_emitted():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    svc.on_passkey_display(addr=bytes.fromhex("AABBCCDDEEFF"),
                            addr_type=op.GAP_ADDR_TYPE_RANDOM, passkey=123456)
    await asyncio.sleep(0)
    assert len(tester.events) == 1
    evt = tester.events[0]
    assert evt.opcode == op.OP_GAP_EVENT_PASSKEY_DISPLAY
    assert evt.data[:7] == bytes([op.GAP_ADDR_TYPE_RANDOM]) + bytes.fromhex("AABBCCDDEEFF")
    assert int.from_bytes(evt.data[7:11], "little") == 123456
