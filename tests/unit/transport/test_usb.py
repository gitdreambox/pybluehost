"""Tests for USB transport: ChipInfo, KNOWN_CHIPS, USBTransport, auto_detect, endpoint routing."""

import logging

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pybluehost.transport.usb import (
    ChipInfo,
    KNOWN_CHIPS,
    USBTransport,
    IntelUSBTransport,
    RealtekUSBTransport,
    NoBluetoothDeviceError,
)
from pybluehost.transport.firmware import FirmwarePolicy


# --- ChipInfo & KNOWN_CHIPS ---

def test_known_chips_not_empty():
    assert len(KNOWN_CHIPS) >= 10


def test_usb_transport_does_not_depend_on_cli_tools():
    source = Path("pybluehost/transport/usb.py").read_text(encoding="utf-8")
    assert "pybluehost.cli" not in source


def test_known_chips_intel_ax210():
    ax210 = next((c for c in KNOWN_CHIPS if c.name == "AX210"), None)
    assert ax210 is not None
    assert ax210.vid == 0x8087
    assert ax210.pid == 0x0032
    assert ax210.vendor == "intel"


def test_known_chips_realtek_rtl8761b():
    rtl = next((c for c in KNOWN_CHIPS if c.name == "RTL8761B"), None)
    assert rtl is not None
    assert rtl.vid == 0x0BDA
    assert rtl.pid == 0x8771
    assert rtl.vendor == "realtek"


def test_known_chips_realtek_rtl8852be_4853_uses_bu_firmware():
    rtl = next((c for c in KNOWN_CHIPS if c.vid == 0x0BDA and c.pid == 0x4853), None)

    assert rtl is not None
    assert rtl.name == "RTL8852BE"
    assert rtl.firmware_pattern == "rtl8852bu_fw.bin"
    assert rtl.vendor == "realtek"


def test_known_chips_CSR8510():
    csr = next((c for c in KNOWN_CHIPS if c.name == "CSR8510"), None)
    assert csr is not None
    assert csr.vid == 0x0A12
    assert csr.pid == 0x0001
    assert csr.vendor == "csr"


def test_chip_info_dataclass():
    chip = ChipInfo(
        vendor="intel",
        name="AX210",
        vid=0x8087,
        pid=0x0032,
        firmware_pattern="ibt-0040-*",
        transport_class=None,
    )
    assert chip.vid == 0x8087
    assert chip.firmware_pattern == "ibt-0040-*"


def test_chip_info_is_frozen():
    chip = ChipInfo("intel", "Test", 0x1234, 0x5678, "fw-*", None)
    with pytest.raises(AttributeError):
        chip.name = "Changed"


# --- auto_detect ---

@patch("pybluehost.transport.usb.usb")
def test_auto_detect_no_device_raises(mock_usb):
    mock_usb.core.find.return_value = []
    with pytest.raises(NoBluetoothDeviceError):
        USBTransport.auto_detect()


@patch("pybluehost.transport.usb.usb")
def test_auto_detect_known_intel_chip(mock_usb):
    mock_device = MagicMock()
    mock_device.idVendor = 0x8087
    mock_device.idProduct = 0x0032
    mock_usb.core.find.return_value = [mock_device]
    transport = USBTransport.auto_detect()
    assert isinstance(transport, IntelUSBTransport)


@patch("pybluehost.transport.usb.usb")
def test_auto_detect_known_realtek_chip(mock_usb):
    mock_device = MagicMock()
    mock_device.idVendor = 0x0BDA
    mock_device.idProduct = 0x8771
    mock_usb.core.find.return_value = [mock_device]
    transport = USBTransport.auto_detect()
    assert isinstance(transport, RealtekUSBTransport)


@patch("pybluehost.transport.usb.usb")
def test_auto_detect_known_csr_chip(mock_usb):
    from pybluehost.transport.usb import CSRUSBTransport

    mock_device = MagicMock()
    mock_device.idVendor = 0x0A12
    mock_device.idProduct = 0x0001
    mock_usb.core.find.return_value = [mock_device]
    transport = USBTransport.auto_detect()
    assert isinstance(transport, CSRUSBTransport)


@patch("pybluehost.transport.usb.usb")
def test_auto_detect_vendor_filter_selects_intel(mock_usb):
    csr_device = MagicMock()
    csr_device.idVendor = 0x0A12
    csr_device.idProduct = 0x0001

    intel_device = MagicMock()
    intel_device.idVendor = 0x8087
    intel_device.idProduct = 0x0032

    mock_usb.core.find.return_value = [csr_device, intel_device]
    transport = USBTransport.auto_detect(vendor="intel")
    assert isinstance(transport, IntelUSBTransport)


@patch("pybluehost.transport.usb.usb")
def test_auto_detect_vendor_filter_selects_csr(mock_usb):
    from pybluehost.transport.usb import CSRUSBTransport

    intel_device = MagicMock()
    intel_device.idVendor = 0x8087
    intel_device.idProduct = 0x0032

    csr_device = MagicMock()
    csr_device.idVendor = 0x0A12
    csr_device.idProduct = 0x0001

    mock_usb.core.find.return_value = [intel_device, csr_device]
    transport = USBTransport.auto_detect(vendor="csr")
    assert isinstance(transport, CSRUSBTransport)


@patch("pybluehost.transport.usb.usb")
def test_auto_detect_invalid_vendor_raises_value_error(mock_usb):
    with pytest.raises(ValueError, match="Unsupported USB vendor filter"):
        USBTransport.auto_detect(vendor="broadcom")


@patch("pybluehost.transport.usb.usb")
def test_auto_detect_unknown_bt_device_class(mock_usb):
    """Unknown VID/PID but Bluetooth device class → generic USBTransport."""
    mock_device = MagicMock()
    mock_device.idVendor = 0x9999
    mock_device.idProduct = 0x0001
    mock_device.bDeviceClass = 0xE0
    mock_device.bDeviceSubClass = 0x01
    mock_device.bDeviceProtocol = 0x01
    # First find (known chips) returns no match; second find (by class) returns device
    mock_usb.core.find.side_effect = [[], [mock_device]]
    transport = USBTransport.auto_detect()
    assert isinstance(transport, USBTransport)
    assert not isinstance(transport, (IntelUSBTransport, RealtekUSBTransport))


@patch("pybluehost.transport.usb.usb")
def test_auto_detect_nothing_at_all(mock_usb):
    """No known chips and no BT class device → NoBluetoothDeviceError."""
    mock_usb.core.find.side_effect = [[], []]
    with pytest.raises(NoBluetoothDeviceError):
        USBTransport.auto_detect()


# --- Endpoint routing ---

@pytest.mark.asyncio
async def test_send_command_routes_to_control():
    """H4 type 0x01 (HCI Command) routes to control endpoint."""
    chip = ChipInfo("intel", "AX210", 0x8087, 0x0032, "ibt-0040-*", IntelUSBTransport)
    transport = USBTransport(device=MagicMock(), chip_info=chip)
    control_calls = []

    async def fake_control_out(data):
        control_calls.append(data)

    transport._control_out = fake_control_out
    await transport.send(b"\x01\x03\x0c\x00")
    assert len(control_calls) == 1
    assert control_calls[0] == b"\x03\x0c\x00"


@pytest.mark.asyncio
async def test_send_acl_routes_to_bulk_out():
    """H4 type 0x02 (ACL Data) routes to bulk OUT endpoint."""
    chip = ChipInfo("intel", "AX210", 0x8087, 0x0032, "ibt-0040-*", IntelUSBTransport)
    transport = USBTransport(device=MagicMock(), chip_info=chip)
    bulk_calls = []

    async def fake_bulk_out(data):
        bulk_calls.append(data)

    transport._bulk_out = fake_bulk_out
    await transport.send(b"\x02\x00\x20\x04\x00test")
    assert len(bulk_calls) == 1
    assert bulk_calls[0] == b"\x00\x20\x04\x00test"


@pytest.mark.asyncio
async def test_send_sco_routes_to_isoch_out():
    """H4 type 0x03 (SCO Data) routes to isochronous OUT endpoint."""
    chip = ChipInfo("intel", "AX210", 0x8087, 0x0032, "ibt-0040-*", IntelUSBTransport)
    transport = USBTransport(device=MagicMock(), chip_info=chip)
    isoch_calls = []

    async def fake_isoch_out(data):
        isoch_calls.append(data)

    transport._isoch_out = fake_isoch_out
    await transport.send(b"\x03\x00\x10\x03abc")
    assert len(isoch_calls) == 1


@pytest.mark.asyncio
async def test_send_unknown_type_raises():
    """Unknown H4 packet type raises ValueError."""
    chip = ChipInfo("intel", "AX210", 0x8087, 0x0032, "ibt-0040-*", IntelUSBTransport)
    transport = USBTransport(device=MagicMock(), chip_info=chip)
    with pytest.raises(ValueError, match="Unknown H4 packet type"):
        await transport.send(b"\x05\x00\x00")


# --- Transport properties ---

def test_usb_transport_info():
    chip = ChipInfo("intel", "AX210", 0x8087, 0x0032, "ibt-0040-*", IntelUSBTransport)
    transport = USBTransport(device=MagicMock(), chip_info=chip)
    info = transport.info
    assert info.type == "usb"
    assert "AX210" in info.description


def test_usb_transport_is_open_default_false():
    chip = ChipInfo("intel", "AX210", 0x8087, 0x0032, "ibt-0040-*", IntelUSBTransport)
    transport = USBTransport(device=MagicMock(), chip_info=chip)
    assert transport.is_open is False


def test_intel_transport_is_usb_transport():
    chip = ChipInfo("intel", "AX210", 0x8087, 0x0032, "ibt-0040-*", IntelUSBTransport)
    transport = IntelUSBTransport(device=MagicMock(), chip_info=chip)
    assert isinstance(transport, USBTransport)


def test_realtek_transport_is_usb_transport():
    chip = ChipInfo("realtek", "RTL8761B", 0x0BDA, 0x8771, "rtl_fw", RealtekUSBTransport)
    transport = RealtekUSBTransport(device=MagicMock(), chip_info=chip)
    assert isinstance(transport, USBTransport)


def test_csr_transport_is_usb_transport():
    from pybluehost.transport.usb import CSRUSBTransport

    chip = ChipInfo("csr", "CSR8510", 0x0A12, 0x0001, "", CSRUSBTransport)
    transport = CSRUSBTransport(device=MagicMock(), chip_info=chip)
    assert isinstance(transport, USBTransport)


class TestUSBTransportDiagnostics:
    def test_open_access_denied_raises_diagnostic_error(self):
        """When get_active_configuration raises errno=13, we get USBAccessDeniedError."""
        import usb.core
        from pybluehost.core.errors import USBAccessDeniedError

        device = MagicMock()
        device.idVendor = 0x8087
        device.idProduct = 0x0036
        device.product = None
        device.manufacturer = None
        device.get_active_configuration.side_effect = usb.core.USBError(
            "Access denied", errno=13
        )

        transport = USBTransport(device=device)
        with pytest.raises(USBAccessDeniedError) as exc_info:
            import asyncio
            asyncio.run(transport.open())

        assert exc_info.value.report["failure_type"].name == "DRIVER_CONFLICT"
        assert "8087" in exc_info.value.report["device_name"]


# --- IntelUSBTransport firmware variant parsing ---

def test_parse_fw_variant_legacy_operational():
    """Legacy: fw_variant at [9], value 0x03 = operational."""
    t = IntelUSBTransport.__new__(IntelUSBTransport)
    # Minimal Command Complete: 0e len 01 opcode(2) status hw_plt hw_var hw_rev fw_var
    event = bytes([0x0E, 0x09, 0x01, 0x05, 0xFC, 0x00, 0x37, 0x10, 0x00, 0x03])
    assert t._parse_fw_variant(event) == 0x03


def test_parse_fw_variant_legacy_bootloader():
    """Legacy: fw_variant at [9], value 0x06 = bootloader."""
    t = IntelUSBTransport.__new__(IntelUSBTransport)
    event = bytes([0x0E, 0x09, 0x01, 0x05, 0xFC, 0x00, 0x37, 0x10, 0x00, 0x06])
    assert t._parse_fw_variant(event) == 0x06


def test_parse_fw_variant_be200():
    """BE200 real hardware response: fw_variant=0x89 at [9]."""
    t = IntelUSBTransport.__new__(IntelUSBTransport)
    event = bytes.fromhex("0e0d0105fc0037 1c a0 89 41 01 00 12 19".replace(" ", ""))
    assert t._parse_fw_variant(event) == 0x89


def test_is_operational_legacy():
    """Legacy platform (hw_variant < 0x17): 0x03 = operational, 0x06 = not."""
    t = IntelUSBTransport.__new__(IntelUSBTransport)
    assert t._is_operational(hw_variant=0x10, fw_variant=0x03) is True
    assert t._is_operational(hw_variant=0x10, fw_variant=0x06) is False
    assert t._is_operational(hw_variant=0x10, fw_variant=0x89) is False


def test_is_operational_new_platform():
    """New platform (hw_variant >= 0x17, e.g. BE200=0x1C): 0x89 = operational."""
    t = IntelUSBTransport.__new__(IntelUSBTransport)
    assert t._is_operational(hw_variant=0x1C, fw_variant=0x89) is True
    assert t._is_operational(hw_variant=0x1C, fw_variant=0x03) is False
    assert t._is_operational(hw_variant=0x17, fw_variant=0x89) is True


@pytest.mark.asyncio
async def test_intel_vendor_command_timeout_logs_context(caplog):
    transport = IntelUSBTransport.__new__(IntelUSBTransport)

    async def fake_control_out(data):
        assert data[:3] == bytes.fromhex("09 fc 02")

    async def fake_wait_for_event(timeout=5.0):
        assert timeout == 2.5
        raise TimeoutError("no event")

    transport._control_out = fake_control_out
    transport._wait_for_event = fake_wait_for_event

    with caplog.at_level(logging.INFO, logger="pybluehost.transport.usb"):
        with pytest.raises(TimeoutError):
            await transport._send_intel_vendor_cmd(
                transport._INTEL_SECURE_SEND,
                b"\x01\x00",
                context="payload offset=4096 size=252",
                timeout=2.5,
            )

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "vendor cmd 0xFC09" in messages
    assert "payload offset=4096 size=252" in messages
    assert "timeout after 2.5s" in messages


@pytest.mark.asyncio
async def test_intel_payload_vendor_command_success_does_not_log_every_wait(caplog):
    transport = IntelUSBTransport.__new__(IntelUSBTransport)

    async def fake_control_out(data):
        assert data[:2] == bytes.fromhex("09 fc")

    async def fake_wait_for_event(timeout=5.0):
        return b"\x0e\x04\x01\x09\xfc\x00"

    transport._control_out = fake_control_out
    transport._wait_for_event = fake_wait_for_event

    with caplog.at_level(logging.INFO, logger="pybluehost.transport.usb"):
        await transport._send_intel_vendor_cmd(
            transport._INTEL_SECURE_SEND,
            b"\x01\x00",
            context="payload offset=4096 size=252",
        )

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "waiting for Command Complete" not in messages


@pytest.mark.asyncio
async def test_secure_send_firmware_logs_payload_offsets(caplog):
    transport = IntelUSBTransport.__new__(IntelUSBTransport)
    calls: list[str] = []
    progress_values: list[int] = []

    async def fake_send_intel_secure_send_commands(commands, **kwargs):
        calls.extend(command[1] for command in commands)
        progress_values.extend(kwargs.get("progress_by_command_index", {}).values())

    transport._send_intel_secure_send_commands = fake_send_intel_secure_send_commands
    fw_data = bytearray(1100)
    fw_data[964:967] = bytes([0x01, 0xFC, 0x01])

    with caplog.at_level(logging.INFO, logger="pybluehost.transport.usb"):
        await transport._secure_send_firmware(
            bytes(fw_data),
            transport._BOOT_PARAMS_ECDSA,
        )

    assert any("payload offset=964" in call for call in calls)
    assert 4 in progress_values


@pytest.mark.asyncio
async def test_secure_send_firmware_pipelines_payload_fragments():
    transport = IntelUSBTransport.__new__(IntelUSBTransport)
    control_count = 0
    control_counts_at_wait: list[int] = []

    async def fake_control_out(data):
        nonlocal control_count
        assert data[:2] == bytes.fromhex("09 fc")
        control_count += 1

    async def fake_wait_for_firmware_command_complete(context, timeout=5.0):
        control_counts_at_wait.append(control_count)
        return bytes.fromhex("0e 04 1f 09 fc 00")

    transport._control_out = fake_control_out
    transport._wait_for_intel_firmware_command_complete = (
        fake_wait_for_firmware_command_complete
    )

    fragment = bytes([0x8E, 0xFC, 245]) + bytes(245)
    fw_data = bytearray(964)
    fw_data.extend(fragment * 40)

    await transport._secure_send_firmware(
        bytes(fw_data),
        transport._BOOT_PARAMS_ECDSA,
    )

    deltas = [
        current - previous
        for previous, current in zip(control_counts_at_wait, control_counts_at_wait[1:])
    ]
    assert max(deltas) > 1


@pytest.mark.asyncio
async def test_intel_firmware_vendor_event_is_deferred_during_flow_control():
    transport = IntelUSBTransport.__new__(IntelUSBTransport)
    events = [
        bytes.fromhex("ff 05 06 00 00 00 00"),
        bytes.fromhex("0e 04 1f 09 fc 00"),
    ]

    async def fake_wait_for_event_bulk_first(timeout=5.0):
        return events.pop(0)

    transport._wait_for_event_bulk_first = fake_wait_for_event_bulk_first

    event = await transport._wait_for_intel_firmware_command_complete(
        "payload offset=1",
    )

    assert event == bytes.fromhex("0e 04 1f 09 fc 00")
    deferred = await transport._wait_for_vendor_event(expected_type=0x06, timeout=0.01)
    assert deferred == bytes.fromhex("ff 05 06 00 00 00 00")


@pytest.mark.asyncio
async def test_intel_vendor_event_wait_logs_timeout(caplog):
    transport = IntelUSBTransport.__new__(IntelUSBTransport)

    async def fake_wait_for_event(timeout=5.0):
        raise TimeoutError("no event")

    transport._wait_for_event = fake_wait_for_event

    with caplog.at_level(logging.INFO, logger="pybluehost.transport.usb"):
        with pytest.raises(TimeoutError):
            await transport._wait_for_vendor_event(expected_type=0x06, timeout=0.01)

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "vendor event type=0x06 wait timeout after 0.01s" in messages
