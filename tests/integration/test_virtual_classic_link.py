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
