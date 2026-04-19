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


# --- Intel Read Version ---

@pytest.mark.asyncio
async def test_intel_send_vendor_cmd_builds_correct_opcode():
    """_send_intel_vendor_cmd packs OGF=0x3F + OCF into a 3-byte HCI command header."""
    transport = _make_intel_transport()
    # Mock _control_out to capture what's sent
    sent = []
    async def capture(data):
        sent.append(data)
    transport._control_out = capture
    # Mock event response
    transport._wait_for_event = AsyncMock(return_value=b"\x0e\x04\x01\x05\xfc\x00")

    await transport._send_intel_vendor_cmd(0x05)  # OCF=0x05 → Read Version
    assert len(sent) == 1
    # Opcode: OCF=0x05, OGF=0x3F → 0xFC05 → little-endian: 0x05, 0xFC
    assert sent[0][0:2] == b"\x05\xfc"


@pytest.mark.asyncio
async def test_intel_initialize_calls_read_version_first():
    """_initialize() sends HCI_Intel_Read_Version (0xFC05) as first command."""
    transport = _make_intel_transport()
    sent_opcodes = []

    async def capture(data):
        sent_opcodes.append(data[0:2])

    transport._control_out = capture

    # Mock: Read Version response with hw_variant=0x17 (AX210), fw_variant=0x03 (operational)
    read_version_response = bytes([
        0x0e, 0x0b, 0x01,  # Event header: Command Complete, 11 params, 1 cmd
        0x05, 0xfc,          # Opcode: FC05
        0x00,                # Status: success
        0x37, 0x01,          # hw_platform, hw_variant
        0x03,                # fw_variant (0x03 = operational, no FW load needed)
        0x01, 0x00, 0x00,    # fw_revision
    ])
    transport._wait_for_event = AsyncMock(return_value=read_version_response)

    await transport._initialize()
    # First command should be Read Version (FC05)
    assert len(sent_opcodes) >= 1
    assert sent_opcodes[0] == b"\x05\xfc"


@pytest.mark.asyncio
async def test_intel_initialize_skips_fw_load_if_operational():
    """If fw_variant indicates operational firmware, skip firmware loading."""
    transport = _make_intel_transport()
    transport._control_out = AsyncMock()

    # fw_variant=0x03 → operational
    read_version_response = bytes([
        0x0e, 0x0b, 0x01,
        0x05, 0xfc,
        0x00,
        0x37, 0x17,
        0x03,  # operational
        0x01, 0x00, 0x00,
    ])
    transport._wait_for_event = AsyncMock(return_value=read_version_response)

    await transport._initialize()
    # Should only have sent Read Version, no firmware loading commands
    assert transport._control_out.call_count == 1


@pytest.mark.asyncio
async def test_intel_initialize_loads_fw_when_bootloader(tmp_path):
    """If fw_variant=0x06 (bootloader), perform full firmware loading sequence."""
    fw_dir = tmp_path / "intel"
    fw_dir.mkdir()
    # Create a dummy firmware file matching the pattern
    fw_file = fw_dir / "ibt-0040-0032.sfi"
    # Minimal firmware: 256-byte header + some data chunks
    fw_header = b"\x00" * 128  # Simplified header
    fw_body = b"\xAA" * 252 * 3  # 3 chunks of 252 bytes
    fw_file.write_bytes(fw_header + fw_body)

    transport = _make_intel_transport(tmp_path=fw_dir)
    call_count = [0]

    async def mock_control(data):
        call_count[0] += 1

    transport._control_out = mock_control

    # Read Version: fw_variant=0x06 (bootloader)
    read_version_boot = bytes([
        0x0e, 0x0b, 0x01,
        0x05, 0xfc,
        0x00,
        0x37, 0x17,
        0x06,  # bootloader — needs FW load
        0x01, 0x00, 0x00,
    ])
    # Post-load Read Version: fw_variant=0x03 (operational)
    read_version_operational = bytes([
        0x0e, 0x0b, 0x01,
        0x05, 0xfc,
        0x00,
        0x37, 0x17,
        0x03,  # operational
        0x01, 0x00, 0x00,
    ])

    responses = [read_version_boot, read_version_operational]
    call_idx = [0]

    async def mock_wait_event(*args, **kwargs):
        idx = min(call_idx[0], len(responses) - 1)
        call_idx[0] += 1
        return responses[idx]

    transport._wait_for_event = mock_wait_event

    # Patch FirmwareManager.find to return our dummy file
    with patch.object(
        type(transport), '_find_firmware', return_value=fw_file
    ):
        await transport._initialize()

    # Should have sent: Read Version + Enter Mfg + chunks + Reset + Read Version
    assert call_count[0] > 2


@pytest.mark.asyncio
async def test_intel_fw_chunk_size():
    """Firmware chunks should be ≤252 bytes."""
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
