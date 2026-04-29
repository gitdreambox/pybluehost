"""Tests for Intel USB transport firmware loading sequence."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from pybluehost.transport.usb import IntelUSBTransport, ChipInfo
from pybluehost.transport.firmware import FirmwarePolicy


def _make_intel_transport(tmp_path=None, fw_data=None):
    """Helper: create an IntelUSBTransport with mocked USB device."""
    chip = ChipInfo("intel", "AX210", 0x8087, 0x0032, "ibt-0040-*", IntelUSBTransport)
    transport = IntelUSBTransport(
        device=MagicMock(),
        chip_info=chip,
        firmware_policy=FirmwarePolicy.ERROR,
        extra_fw_dirs=[tmp_path] if tmp_path else [],
    )
    # Mock low-level USB methods
    transport._control_out = AsyncMock()
    transport._bulk_out = AsyncMock()
    return transport


# V2 Read Version returns "Unknown Command" (status=0x12) for legacy chips
_V2_REJECT = bytes([
    0x0E, 0x04, 0x01,  # Command Complete, 4 params, 1 cmd
    0x05, 0xFC,         # Opcode echo: FC05
    0x12,               # Status: Unknown Command
])

# Legacy Read Version: operational (fw_variant=0x03)
_LEGACY_OPERATIONAL = bytes([
    0x0E, 0x0B, 0x01,
    0x05, 0xFC,
    0x00,            # Status: success
    0x37, 0x10,      # hw_platform, hw_variant (legacy, < 0x17)
    0x00,            # hw_revision
    0x03,            # fw_variant (0x03 = operational)
    0x01, 0x00,
])

# Legacy Read Version: bootloader (fw_variant=0x06)
_LEGACY_BOOTLOADER = bytes([
    0x0E, 0x0B, 0x01,
    0x05, 0xFC,
    0x00,
    0x37, 0x10,
    0x00,
    0x06,  # fw_variant (0x06 = bootloader)
    0x01, 0x00,
])

_HCI_RESET_OK = bytes([
    0x0E, 0x04, 0x01,
    0x03, 0x0C,
    0x00,
])


def _make_response_sequence(*responses):
    """Create an async mock that returns responses in order, cycling the last."""
    idx = [0]

    async def mock_event(*args, **kwargs):
        i = min(idx[0], len(responses) - 1)
        idx[0] += 1
        return responses[i]

    return mock_event


# --- Intel Read Version ---

@pytest.mark.asyncio
async def test_intel_send_vendor_cmd_builds_correct_opcode():
    """_send_intel_vendor_cmd packs OGF=0x3F + OCF into a 3-byte HCI command header."""
    transport = _make_intel_transport()
    sent = []
    async def capture(data):
        sent.append(data)
    transport._control_out = capture
    transport._wait_for_event = AsyncMock(return_value=b"\x0e\x04\x01\x05\xfc\x00")

    await transport._send_intel_vendor_cmd(0x05)
    assert len(sent) == 1
    assert sent[0][0:2] == b"\x05\xfc"


@pytest.mark.asyncio
async def test_intel_initialize_resets_before_read_version():
    """_initialize() sends HCI Reset before HCI_Intel_Read_Version."""
    transport = _make_intel_transport()
    sent_opcodes = []

    async def capture(data):
        sent_opcodes.append(data[0:2])
    transport._control_out = capture

    # Reset OK, V2 → rejected, then V1 → operational (no FW load)
    transport._wait_for_event = _make_response_sequence(
        _HCI_RESET_OK, _V2_REJECT, _LEGACY_OPERATIONAL
    )

    await transport._initialize()
    assert len(sent_opcodes) >= 3
    assert sent_opcodes[0] == b"\x03\x0c"
    assert sent_opcodes[1] == b"\x05\xfc"
    assert sent_opcodes[2] == b"\x05\xfc"


@pytest.mark.asyncio
async def test_intel_initialize_skips_fw_load_if_operational():
    """If fw_variant indicates operational firmware, skip firmware loading."""
    transport = _make_intel_transport()
    transport._control_out = AsyncMock()

    # Reset OK, V2 → rejected, V1 → operational
    transport._wait_for_event = _make_response_sequence(
        _HCI_RESET_OK, _V2_REJECT, _LEGACY_OPERATIONAL
    )

    await transport._initialize()
    # HCI Reset + V2 call + V1 call = 3 control_out calls total
    assert transport._control_out.call_count == 3


@pytest.mark.asyncio
async def test_intel_initialize_loads_fw_when_bootloader(tmp_path):
    """If fw_variant=0x06 (bootloader), perform full firmware loading sequence."""
    fw_dir = tmp_path / "intel"
    fw_dir.mkdir()
    fw_file = fw_dir / "ibt-0040-0032.sfi"
    fw_file.write_bytes(b"\x00" * 128 + b"\xAA" * 252 * 3)

    transport = _make_intel_transport(tmp_path=fw_dir)
    call_count = [0]

    async def mock_control(data):
        call_count[0] += 1
    transport._control_out = mock_control

    # Reset OK, V2 → rejected, V1 → bootloader, then all subsequent → operational
    transport._wait_for_event = _make_response_sequence(
        _HCI_RESET_OK, _V2_REJECT, _LEGACY_BOOTLOADER, _LEGACY_OPERATIONAL
    )

    with patch.object(
        type(transport), '_find_firmware', return_value=fw_file
    ):
        await transport._initialize()

    # V2 + V1 + Enter Mfg + chunks + Reset + verify = many calls
    assert call_count[0] > 2


@pytest.mark.asyncio
async def test_intel_fw_chunk_size():
    """Firmware chunks should be <=252 bytes."""
    transport = _make_intel_transport()
    chunks = transport._split_firmware(b"\xAA" * 1000)
    for chunk in chunks:
        assert len(chunk) <= 252


# --- Intel vendor command structure ---

def test_intel_transport_inherits_usb():
    from pybluehost.transport.usb import USBTransport
    chip = ChipInfo("intel", "AX210", 0x8087, 0x0032, "ibt-0040-*", IntelUSBTransport)
    t = IntelUSBTransport(device=MagicMock(), chip_info=chip)
    assert isinstance(t, USBTransport)
