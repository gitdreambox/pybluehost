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
