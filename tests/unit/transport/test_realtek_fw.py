"""Tests for Realtek USB transport firmware loading sequence."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from pybluehost.transport.usb import RealtekUSBTransport, ChipInfo
from pybluehost.transport.firmware import FirmwarePolicy

_HCI_RESET_OK = bytes([
    0x0e, 0x04, 0x01,
    0x03, 0x0c, 0x00,
])

_RTL8852C_STOCK_LOCAL_VERSION = bytes([
    0x0e, 0x0c, 0x01,
    0x01, 0x10, 0x00,
    0x0c, 0x0c, 0x00, 0x0c,
    0x5d, 0x00, 0x52, 0x88,
])

_RTL8852B_STOCK_LOCAL_VERSION = bytes([
    0x0e, 0x0c, 0x01,
    0x01, 0x10, 0x00,
    0x0b, 0x0b, 0x00, 0x0b,
    0x5d, 0x00, 0x52, 0x88,
])

_REALTEK_OPERATIONAL_LOCAL_VERSION = bytes([
    0x0e, 0x0c, 0x01,
    0x01, 0x10, 0x00,
    0x0c, 0x34, 0x12, 0x0c,
    0x5d, 0x00, 0x99, 0x99,
])


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


def _make_epatch(*, chip_id: int = 2, version: int = 0x11223344, patch: bytes = b"PATCHDATA") -> bytes:
    """Build a minimal Realtek epatch image for parser tests."""
    header = b"Realtech" + version.to_bytes(4, "little") + (1).to_bytes(2, "little")
    tables = (
        chip_id.to_bytes(2, "little")
        + len(patch).to_bytes(2, "little")
        + (22).to_bytes(4, "little")
    )
    return header + tables + patch + bytes([0x51, 0x04, 0xFD, 0x77])


def _make_epatch_v2(
    *,
    eco: int = 2,
    prio: int = 7,
    payload: bytes = b"V2PATCH",
    opcode: int = 1,
    key_id: int = 0,
) -> bytes:
    """Build a minimal RTBTCore firmware image for parser tests."""
    subsection = bytes([eco, prio, key_id, 0]) + len(payload).to_bytes(4, "little") + payload
    section_data = (1).to_bytes(2, "little") + b"\x00\x00" + subsection
    section = opcode.to_bytes(4, "little") + len(section_data).to_bytes(4, "little") + section_data
    return b"RTBTCore" + b"\x01\x02\x03\x04\x05\x06\x07\x08" + (1).to_bytes(4, "little") + section + b"\xff\x02\x01\x01\x19\x01\x00" + bytes([0x51, 0x04, 0xFD, 0x77])


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
async def test_realtek_initialize_resets_before_read_rom_version():
    """_initialize() sends HCI Reset before HCI_Realtek_Read_ROM_Version."""
    transport = _make_realtek_transport()
    sent_opcodes = []

    async def capture(data):
        sent_opcodes.append(data[0:2])

    transport._control_out = capture

    # HCI Reset response + Read Local Version response
    reset_response = bytes([
        0x0e, 0x04, 0x01,
        0x03, 0x0c, 0x00,  # Reset complete
    ])
    transport._wait_for_event = AsyncMock(side_effect=[
        reset_response,
        _REALTEK_OPERATIONAL_LOCAL_VERSION,
    ])

    await transport._initialize()
    assert len(sent_opcodes) >= 2
    assert sent_opcodes[0] == b"\x03\x0c"
    assert sent_opcodes[1] == b"\x01\x10"


@pytest.mark.asyncio
async def test_realtek_initialize_stops_when_initial_reset_fails():
    transport = _make_realtek_transport()
    transport._control_out = AsyncMock(side_effect=TimeoutError("reset timeout"))

    with pytest.raises(RuntimeError, match="refusing firmware download"):
        await transport._initialize()


@pytest.mark.asyncio
async def test_realtek_initialize_downloads_fw_when_needed(tmp_path):
    """Full Realtek firmware download sequence when needed."""
    fw_dir = tmp_path / "realtek"
    fw_dir.mkdir()
    fw_file = fw_dir / "rtl8761b_fw"
    fw_file.write_bytes(_make_epatch(patch=b"\x55" * 512))

    transport = _make_realtek_transport(tmp_path=fw_dir)
    call_count = [0]
    writes = []

    async def mock_control(data):
        writes.append(data)
        call_count[0] += 1

    transport._control_out = mock_control

    # HCI Reset (initial) + Read Local Version + Read ROM Version +
    # download chunks + Read Local Version
    reset_resp = bytes([
        0x0e, 0x04, 0x01,
        0x03, 0x0c, 0x00,  # Reset complete
    ])
    rom_version_resp = bytes([
        0x0e, 0x05, 0x01,
        0x6d, 0xfc, 0x00,
        0x01,  # rom_version=1
    ])

    local_version_resp = bytes([
        0x0e, 0x0c, 0x01,
        0x01, 0x10, 0x00,
        0x0c, 0x0c, 0x00, 0x0c,
        0x5d, 0x00, 0x52, 0x88,
    ])

    responses = [reset_resp, _RTL8852C_STOCK_LOCAL_VERSION, rom_version_resp]
    call_idx = [0]

    async def mock_wait(*args, **kwargs):
        if call_idx[0] >= len(responses):
            last_write = writes[-1]
            if last_write[:2] == b"\x20\xfc":
                return b"\x0e\x05\x01\x20\xfc\x00" + last_write[3:4]
            return local_version_resp
        idx = call_idx[0]
        call_idx[0] += 1
        return responses[idx]

    transport._wait_for_event = mock_wait
    transport._needs_firmware_download = MagicMock(return_value=True)

    with patch.object(
        type(transport), '_find_firmware', return_value=fw_file
    ):
        await transport._initialize()

    # Should have sent: initial Reset + Read ROM Version + download chunks + Read Local Version
    assert call_count[0] >= 3


@pytest.mark.asyncio
async def test_realtek_fw_chunk_size():
    """Realtek firmware chunks should be ≤252 bytes."""
    transport = _make_realtek_transport()
    chunks = transport._split_firmware(b"\xBB" * 800)
    for chunk in chunks:
        assert len(chunk) <= 252


def test_realtek_epatch_payload_selects_rom_version_patch():
    firmware = _make_epatch(chip_id=2, version=0x11223344, patch=b"abcdWXYZ")

    payload = RealtekUSBTransport._build_firmware_payload(firmware, rom_version=1)

    assert payload == b"abcd" + bytes.fromhex("44 33 22 11")


def test_realtek_epatch_v2_payload_selects_rom_version_subsection():
    firmware = _make_epatch_v2(eco=2, prio=7, payload=b"selected")

    payload = RealtekUSBTransport._build_firmware_payload(firmware, rom_version=1)

    assert payload == b"selected"


def test_realtek_epatch_v2_skips_security_header_without_key_id():
    firmware = _make_epatch_v2(
        eco=2,
        prio=7,
        payload=b"security",
        opcode=RealtekUSBTransport._RTK_PATCH_SECURITY_HEADER,
        key_id=3,
    )

    with pytest.raises(RuntimeError, match="no epatch v2 entry"):
        RealtekUSBTransport._build_firmware_payload(firmware, rom_version=1)


def test_realtek_epatch_v2_selects_matching_security_key_id():
    firmware = _make_epatch_v2(
        eco=2,
        prio=7,
        payload=b"security",
        opcode=RealtekUSBTransport._RTK_PATCH_SECURITY_HEADER,
        key_id=3,
    )

    payload = RealtekUSBTransport._build_firmware_payload(
        firmware, rom_version=1, key_id=3
    )

    assert payload == b"security"


def test_realtek_firmware_candidates_prefer_rtl8852cu_v2():
    assert RealtekUSBTransport._firmware_candidates("rtl8852cu_fw.bin")[:2] == [
        "rtl8852cu_fw_v2.bin",
        "rtl8852cu_fw.bin",
    ]


def test_realtek_needs_firmware_download_for_rtl8852c_stock_tuple():
    transport = _make_realtek_transport()
    local_version = RealtekUSBTransport._parse_local_version(_RTL8852C_STOCK_LOCAL_VERSION)

    assert transport._needs_firmware_download(local_version) is True


def test_realtek_needs_firmware_download_for_rtl8852b_stock_tuple():
    transport = _make_realtek_transport()
    local_version = RealtekUSBTransport._parse_local_version(_RTL8852B_STOCK_LOCAL_VERSION)

    assert transport._needs_firmware_download(local_version) is True


def test_realtek_skips_firmware_download_for_unknown_operational_tuple():
    transport = _make_realtek_transport()
    local_version = RealtekUSBTransport._parse_local_version(_REALTEK_OPERATIONAL_LOCAL_VERSION)

    assert transport._needs_firmware_download(local_version) is False


@pytest.mark.asyncio
async def test_realtek_download_marks_final_fragment():
    transport = _make_realtek_transport()
    sent_params = []

    async def capture(ocf, params=b""):
        sent_params.append(params)
        return b"\x0e\x05\x01\x20\xfc\x00" + params[:1]

    async def capture_final(params):
        sent_params.append(params)

    transport._send_realtek_vendor_cmd = capture
    transport._send_realtek_download_final = capture_final

    await transport._download_firmware_payload(b"\xAA" * 253)

    assert sent_params[0][0] == 0x00
    assert sent_params[1][0] == 0x81


@pytest.mark.asyncio
async def test_realtek_download_skips_reserved_index_0x80():
    transport = _make_realtek_transport()
    sent_params = []

    async def capture(ocf, params=b""):
        sent_params.append(params)
        return b"\x0e\x05\x01\x20\xfc\x00" + params[:1]

    async def capture_final(params):
        sent_params.append(params)

    transport._send_realtek_vendor_cmd = capture
    transport._send_realtek_download_final = capture_final

    await transport._download_firmware_payload(b"\xAA" * (252 * 130))

    assert sent_params[127][0] == 0x7F
    assert sent_params[128][0] == 0x01
    assert sent_params[-1][0] == 0x82


@pytest.mark.asyncio
async def test_realtek_download_wraps_every_0x7f_fragments():
    transport = _make_realtek_transport()
    sent_params = []

    async def capture(ocf, params=b""):
        sent_params.append(params)
        return b"\x0e\x05\x01\x20\xfc\x00" + params[:1]

    async def capture_final(params):
        sent_params.append(params)

    transport._send_realtek_vendor_cmd = capture
    transport._send_realtek_download_final = capture_final

    await transport._download_firmware_payload(b"\xAA" * (252 * 286))

    assert sent_params[254][0] == 0x7F
    assert sent_params[255][0] == 0x01
    assert sent_params[-1][0] == 0x9F


@pytest.mark.asyncio
async def test_realtek_final_fragment_timeout_is_fatal():
    transport = _make_realtek_transport()
    writes = []

    class USBTimeoutError(Exception):
        pass

    async def capture(data):
        writes.append(data)

    async def timeout(*args, **kwargs):
        raise USBTimeoutError("timeout")

    transport._control_out = capture
    transport._wait_for_event = timeout

    with pytest.raises(USBTimeoutError):
        await transport._send_realtek_download_final(b"\x9fpayload")

    assert writes == [b"\x20\xfc\x08\x9fpayload"]


def test_realtek_download_response_rejects_bad_index():
    event = b"\x0e\x05\x01\x20\xfc\x00\x02"

    with pytest.raises(RuntimeError, match="download index echo mismatch"):
        RealtekUSBTransport._validate_download_response(event, expected_index=0x01)


@pytest.mark.asyncio
async def test_realtek_wait_for_command_complete_ignores_stale_event():
    transport = _make_realtek_transport()
    transport._wait_for_event = AsyncMock(side_effect=[
        _HCI_RESET_OK,
        _RTL8852C_STOCK_LOCAL_VERSION,
    ])

    event = await transport._wait_for_command_complete(0x1001)

    assert event == _RTL8852C_STOCK_LOCAL_VERSION


def test_realtek_rejects_unknown_firmware_format():
    with pytest.raises(RuntimeError, match="unsupported firmware format"):
        RealtekUSBTransport._build_firmware_payload(b"\x00" * 16, rom_version=1)


def test_realtek_transport_inherits_usb():
    from pybluehost.transport.usb import USBTransport
    chip = ChipInfo("realtek", "RTL8761B", 0x0BDA, 0x8771, "rtl_fw", RealtekUSBTransport)
    t = RealtekUSBTransport(device=MagicMock(), chip_info=chip)
    assert isinstance(t, USBTransport)


@pytest.mark.asyncio
async def test_realtek_wait_for_event_uses_usb_transport_fallback():
    transport = _make_realtek_transport()
    transport.read_interrupt_sync = MagicMock(side_effect=TimeoutError("interrupt timeout"))
    transport._ep_bulk_in = MagicMock()
    transport._ep_bulk_in.read = MagicMock(return_value=b"\x0e")

    assert await transport._wait_for_event(timeout=1.25) == b"\x0e"
    transport.read_interrupt_sync.assert_called_once_with(255, 50)
    transport._ep_bulk_in.read.assert_called_once_with(1024, timeout=1250)


@pytest.mark.asyncio
async def test_realtek_post_download_reads_local_version():
    transport = _make_realtek_transport()
    sent = []

    async def capture(data):
        sent.append(data)

    transport._control_out = capture
    transport._wait_for_event = AsyncMock(return_value=_RTL8852C_STOCK_LOCAL_VERSION)

    assert await transport._read_local_version_after_download() == _RTL8852C_STOCK_LOCAL_VERSION
    assert sent[0][:3] == b"\x01\x10\x00"
