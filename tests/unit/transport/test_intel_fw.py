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

_AX201_BOOTLOADER = bytes([
    0x0E, 0x0D, 0x20,
    0x05, 0xFC,
    0x00,        # status
    0x37,        # hw_platform
    0x13,        # hw_variant (HrP / 19)
    0x00,        # hw_revision
    0x06,        # fw_variant (bootloader)
    0x04,        # fw_revision
    0x00, 0x1E, 0x12, 0x00,
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
async def test_intel_initialize_treats_fixed_format_v2_as_legacy():
    """AX201 may accept FC05+FF but still return fixed-format legacy version data."""
    transport = _make_intel_transport()
    transport._control_out = AsyncMock()

    transport._wait_for_event = _make_response_sequence(
        _HCI_RESET_OK, _LEGACY_OPERATIONAL, _LEGACY_OPERATIONAL
    )

    await transport._initialize()
    assert transport._control_out.call_count == 3


@pytest.mark.asyncio
async def test_intel_initialize_loads_fw_when_bootloader(tmp_path):
    """If fw_variant=0x06 (bootloader), download firmware via Intel Secure Send."""
    fw_dir = tmp_path / "intel"
    fw_dir.mkdir()
    fw_file = fw_dir / "ibt-0040-0032.sfi"
    fw_file.write_bytes(b"\x00" * 644 + b"\x0e\xfc\x04\x78\x56\x34\x12")

    transport = _make_intel_transport(tmp_path=fw_dir)
    transport._secure_send_firmware = AsyncMock(return_value=0x12345678)
    transport._intel_reset_newgen = AsyncMock()
    transport._wait_for_vendor_event = AsyncMock(
        side_effect=[b"\xff\x01\x06", b"\xff\x01\x02"]
    )

    # Reset OK, V2 → rejected, V1 → bootloader, then all subsequent → operational
    transport._wait_for_event = _make_response_sequence(
        _HCI_RESET_OK, _V2_REJECT, _LEGACY_BOOTLOADER, _LEGACY_OPERATIONAL
    )

    with patch.object(
        type(transport), '_find_firmware', return_value=fw_file
    ):
        await transport._initialize()

    transport._secure_send_firmware.assert_awaited_once_with(
        fw_file.read_bytes(),
        transport._BOOT_PARAMS_LEGACY_RSA,
    )
    transport._intel_reset_newgen.assert_awaited_once_with(0x12345678)
    assert transport._wait_for_vendor_event.await_args_list[0].kwargs == {
        "expected_type": 0x06,
        "timeout": 10.0,
    }
    assert transport._wait_for_vendor_event.await_args_list[1].kwargs == {
        "expected_type": 0x02,
        "timeout": 10.0,
    }


def test_intel_find_firmware_uses_firmware_manager(tmp_path):
    fw_dir = tmp_path / "intel"
    fw_dir.mkdir()
    fw_file = fw_dir / "ibt-0040-0032.sfi"
    fw_file.write_bytes(b"\x00")

    transport = _make_intel_transport(tmp_path=fw_dir)

    assert transport._find_firmware() == fw_file


def test_intel_find_firmware_prefers_exact_legacy_version_name(tmp_path):
    fw_dir = tmp_path / "intel"
    fw_dir.mkdir()
    exact_fw = fw_dir / "ibt-19-0-4.sfi"
    fallback_fw = fw_dir / "ibt-20-0-3.sfi"
    exact_fw.write_bytes(b"\x19")
    fallback_fw.write_bytes(b"\x20")

    chip = ChipInfo("intel", "AX201", 0x8087, 0x0026, "ibt-20-*", IntelUSBTransport)
    transport = IntelUSBTransport(
        device=MagicMock(),
        chip_info=chip,
        firmware_policy=FirmwarePolicy.ERROR,
        extra_fw_dirs=[fw_dir],
    )

    assert transport._find_firmware(_AX201_BOOTLOADER) == exact_fw


def test_intel_legacy_fw_variant_0x23_is_operational():
    transport = _make_intel_transport()

    assert transport._is_operational(0x13, 0x23) is True


@pytest.mark.asyncio
async def test_intel_secure_send_pipeline_drains_final_command_complete():
    transport = _make_intel_transport()
    transport._control_out = AsyncMock()
    complete = bytes([0x0E, 0x04, 0x01, 0x09, 0xFC, 0x00])
    transport._wait_for_intel_firmware_command_complete = AsyncMock(return_value=complete)

    commands = [
        (b"\x09\xfc\x01\x00", "chunk 1"),
        (b"\x09\xfc\x01\x00", "chunk 2"),
        (b"\x09\xfc\x01\x00", "chunk 3"),
    ]

    await transport._send_intel_secure_send_commands(commands)

    assert transport._control_out.await_count == 3
    assert transport._wait_for_intel_firmware_command_complete.await_count == 3


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


@pytest.mark.asyncio
async def test_intel_newgen_empty_tlv_has_recovery_guidance():
    """Invalid TLV responses should explain hardware recovery, not just say image_type=0xFF."""
    transport = _make_intel_transport()

    with pytest.raises(RuntimeError) as excinfo:
        await transport._initialize_newgen({})

    message = str(excinfo.value)
    assert "missing required TLV fields" in message
    assert "0x10" in message
    assert "0x11" in message
    assert "0x1C" in message
    assert "pybluehost tools usb diagnose" in message
    assert "power-cycle" in message
