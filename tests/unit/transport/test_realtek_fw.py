"""Tests for Realtek USB transport firmware loading sequence."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from pybluehost.transport.usb import RealtekUSBTransport, ChipInfo
from pybluehost.transport.firmware import FirmwarePolicy


def _make_realtek_transport(tmp_path=None):
    """Helper: create a RealtekUSBTransport with mocked USB device."""
    chip = ChipInfo("realtek", "RTL8761B", 0x0BDA, 0x8771, "rtl8761b_fw", RealtekUSBTransport)
    transport = RealtekUSBTransport(
        device=MagicMock(),
        chip_info=chip,
        firmware_policy=FirmwarePolicy.ERROR,
        extra_fw_dirs=[tmp_path] if tmp_path else [],
    )
    transport._control_out = AsyncMock()
    transport._bulk_out = AsyncMock()
    return transport


@pytest.mark.asyncio
async def test_realtek_send_vendor_cmd_builds_correct_opcode():
    """_send_realtek_vendor_cmd uses OGF=0x3F + OCF."""
    transport = _make_realtek_transport()
    sent = []

    async def capture(data):
        sent.append(data)

    transport._control_out = capture
    transport._wait_for_event = AsyncMock(return_value=b"\x0e\x04\x01\x6d\xfc\x00")

    await transport._send_realtek_vendor_cmd(0x6D)  # Read ROM Version
    assert len(sent) == 1
    assert sent[0][0:2] == b"\x6d\xfc"


@pytest.mark.asyncio
async def test_realtek_initialize_calls_read_rom_version_first():
    """_initialize() sends HCI_Realtek_Read_ROM_Version (0xFC6D) first."""
    transport = _make_realtek_transport()
    sent_opcodes = []

    async def capture(data):
        sent_opcodes.append(data[0:2])

    transport._control_out = capture

    # Read ROM Version response
    rom_version_response = bytes([
        0x0e, 0x05, 0x01,
        0x6d, 0xfc,          # Opcode: FC6D
        0x00,                # Status: success
        0x01,                # ROM version
    ])
    transport._wait_for_event = AsyncMock(return_value=rom_version_response)

    # FW already loaded scenario — skip download
    transport._needs_firmware_download = MagicMock(return_value=False)

    await transport._initialize()
    assert len(sent_opcodes) >= 1
    assert sent_opcodes[0] == b"\x6d\xfc"


@pytest.mark.asyncio
async def test_realtek_initialize_downloads_fw_when_needed(tmp_path):
    """Full Realtek firmware download sequence when needed."""
    fw_dir = tmp_path / "realtek"
    fw_dir.mkdir()
    fw_file = fw_dir / "rtl8761b_fw"
    fw_file.write_bytes(b"\x55" * 512)

    transport = _make_realtek_transport(tmp_path=fw_dir)
    call_count = [0]

    async def mock_control(data):
        call_count[0] += 1

    transport._control_out = mock_control

    # Read ROM Version response
    rom_version_resp = bytes([
        0x0e, 0x05, 0x01,
        0x6d, 0xfc, 0x00,
        0x01,  # rom_version=1
    ])

    # HCI Reset response (post-download verification)
    reset_resp = bytes([
        0x0e, 0x04, 0x01,
        0x03, 0x0c, 0x00,  # Reset complete
    ])

    responses = [rom_version_resp, reset_resp]
    call_idx = [0]

    async def mock_wait(*args, **kwargs):
        idx = min(call_idx[0], len(responses) - 1)
        call_idx[0] += 1
        return responses[idx]

    transport._wait_for_event = mock_wait
    transport._needs_firmware_download = MagicMock(return_value=True)

    with patch.object(
        type(transport), '_find_firmware', return_value=fw_file
    ):
        await transport._initialize()

    # Should have sent: Read ROM Version + download chunks + Reset
    assert call_count[0] >= 2


@pytest.mark.asyncio
async def test_realtek_fw_chunk_size():
    """Realtek firmware chunks should be ≤252 bytes."""
    transport = _make_realtek_transport()
    chunks = transport._split_firmware(b"\xBB" * 800)
    for chunk in chunks:
        assert len(chunk) <= 252


def test_realtek_transport_inherits_usb():
    from pybluehost.transport.usb import USBTransport
    chip = ChipInfo("realtek", "RTL8761B", 0x0BDA, 0x8771, "rtl_fw", RealtekUSBTransport)
    t = RealtekUSBTransport(device=MagicMock(), chip_info=chip)
    assert isinstance(t, USBTransport)
