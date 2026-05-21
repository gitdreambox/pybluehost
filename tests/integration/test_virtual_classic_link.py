"""Per-primitive integration tests for VirtualClassicLink."""
from __future__ import annotations

import asyncio
import struct

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.hci.virtual import VirtualController


def _make_vc(addr_hex: str = "AA:BB:CC:DD:EE:01") -> VirtualController:
    return VirtualController(address=BDAddress.from_string(addr_hex))


@pytest.mark.asyncio
async def test_virtual_controller_has_command_interceptor_attribute():
    vc = _make_vc()
    assert hasattr(vc, "command_interceptor")
    assert vc.command_interceptor is None


@pytest.mark.asyncio
async def test_virtual_controller_command_interceptor_runs_first():
    """When set, command_interceptor is called and its return value is used as
    the HCI response."""
    vc = _make_vc()
    seen: list = []

    async def _intercept(opcode: int, raw_params: bytes):
        seen.append((opcode, raw_params))
        return b"\x04\x05\x01\x00\x00\xCE\xCE"

    vc.command_interceptor = _intercept
    # H4 command frame: type=01, opcode=0x040C (arbitrary unused command), len=0
    frame = bytes([0x01, 0x0C, 0x04, 0x00])
    response = await vc.process(frame)
    assert seen and seen[0][0] == 0x040C
    assert response == b"\x04\x05\x01\x00\x00\xCE\xCE"


@pytest.mark.asyncio
async def test_virtual_controller_command_interceptor_passthrough_when_none():
    """When interceptor is unset (None), default dispatch runs."""
    vc = _make_vc()
    # HCI_Reset (0x0C03) → default dispatch produces a Command_Complete with status=0.
    frame = bytes([0x01, 0x03, 0x0C, 0x00])
    response = await vc.process(frame)
    assert response is not None
    # Command_Complete event_code=0x0E; status byte should be 0x00.
    assert response[0] == 0x04 and response[1] >= 4


from pybluehost.hci.virtual_classic_link import VirtualClassicLink, _ConnState


@pytest.mark.asyncio
async def test_virtual_classic_link_attach_detach_installs_interceptors():
    """attach() installs command_interceptor on both controllers; detach() removes."""
    central = _make_vc("AA:AA:AA:AA:AA:AA")
    peripheral = _make_vc("BB:BB:BB:BB:BB:BB")
    addr_c = BDAddress.from_string("AA:AA:AA:AA:AA:AA")
    addr_p = BDAddress.from_string("BB:BB:BB:BB:BB:BB")
    link = VirtualClassicLink(
        central=central, peripheral=peripheral,
        central_address=addr_c, peripheral_address=addr_p,
    )
    link.attach()
    assert central.command_interceptor is not None
    assert peripheral.command_interceptor is not None
    link.detach()
    assert central.command_interceptor is None
    assert peripheral.command_interceptor is None


def test_conn_state_enum_values():
    assert _ConnState.NONE == 0
    assert _ConnState.PENDING == 1
    assert _ConnState.CONNECTED == 2
    assert _ConnState.DISCONNECTING == 3


# ---------------------------------------------------------------------------
# Helpers used by sub-bridge tests (Tasks 3-8)
# ---------------------------------------------------------------------------

async def _h4_cmd(opcode: int, params: bytes = b"") -> bytes:
    return bytes([0x01]) + struct.pack("<H", opcode) + bytes([len(params)]) + params


async def _make_linked_pair(*, peer_discoverable: bool = True):
    """Create two VirtualControllers + bridge; optionally make peripheral discoverable."""
    c = _make_vc("0A:0A:0A:0A:0A:0A")
    p = _make_vc("0B:0B:0B:0B:0B:0B")
    addr_c = BDAddress.from_string("0A:0A:0A:0A:0A:0A")
    addr_p = BDAddress.from_string("0B:0B:0B:0B:0B:0B")
    link = VirtualClassicLink(
        central=c, peripheral=p,
        central_address=addr_c, peripheral_address=addr_p,
    )
    link.attach()
    if peer_discoverable:
        # Write_Scan_Enable = 0x03 (inquiry + page)
        await p.process(await _h4_cmd(0x0C1A, bytes([0x03])))
    return c, p, addr_c, addr_p, link


def _capture_events(vc: VirtualController) -> list:
    """Install a host-side sink that records all events the controller emits."""
    from pybluehost.hci.packets import HCIEvent as _HE
    captured: list = []

    class _Sink:
        async def on_transport_data(self, data: bytes):
            if data and data[0] == 0x04:  # event packet
                event = _HE(event_code=data[1], parameters=data[3:3 + data[2]])
                captured.append(event)

    vc._host_sink = _Sink()
    return captured


# ---------------------------------------------------------------------------
# Task 3 — InquiryBridge
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inquiry_discovers_discoverable_peer():
    from pybluehost.hci.constants import EventCode
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=True)
    events_c = _capture_events(c)
    inquiry_params = bytes([0x33, 0x8B, 0x9E, 0x08, 0x00])
    await c.process(await _h4_cmd(0x0401, inquiry_params))
    await asyncio.sleep(0.05)
    inquiry_results = [e for e in events_c if e.event_code == int(EventCode.INQUIRY_RESULT)]
    assert len(inquiry_results) == 1, f"got {len(inquiry_results)} inquiry_results"
    body = inquiry_results[0].parameters
    assert body[0] == 1
    assert body[1:7] == addr_p.address
    inquiry_completes = [e for e in events_c if e.event_code == int(EventCode.INQUIRY_COMPLETE)]
    assert len(inquiry_completes) == 1


@pytest.mark.asyncio
async def test_inquiry_skips_non_discoverable_peer():
    from pybluehost.hci.constants import EventCode
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=False)
    events_c = _capture_events(c)
    await c.process(await _h4_cmd(0x0401, bytes([0x33, 0x8B, 0x9E, 0x08, 0x00])))
    await asyncio.sleep(0.05)
    assert not [e for e in events_c if e.event_code == int(EventCode.INQUIRY_RESULT)]
    completes = [e for e in events_c if e.event_code == int(EventCode.INQUIRY_COMPLETE)]
    assert len(completes) == 1


@pytest.mark.asyncio
async def test_inquiry_cancel_completes_immediately():
    from pybluehost.hci.constants import EventCode
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=True)
    events_c = _capture_events(c)
    await c.process(await _h4_cmd(0x0402))
    await asyncio.sleep(0.05)
    completes = [e for e in events_c if e.event_code == int(EventCode.INQUIRY_COMPLETE)]
    assert len(completes) == 1


@pytest.mark.asyncio
async def test_virtual_controller_write_scan_enable_updates_flags():
    vc = _make_vc()
    assert vc._inquiry_scan is False and vc._page_scan is False
    # Write_Scan_Enable opcode = 0x0C1A; param = 0x03 (inquiry + page).
    frame = bytes([0x01, 0x1A, 0x0C, 0x01, 0x03])
    await vc.process(frame)
    assert vc._inquiry_scan is True
    assert vc._page_scan is True
    # Now disable inquiry, keep page.
    frame_disable_inquiry = bytes([0x01, 0x1A, 0x0C, 0x01, 0x02])
    await vc.process(frame_disable_inquiry)
    assert vc._inquiry_scan is False
    assert vc._page_scan is True
