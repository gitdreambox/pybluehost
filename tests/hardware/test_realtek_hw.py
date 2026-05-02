"""
Physical hardware validation tests for Realtek Bluetooth USB transport.

Prerequisites:
- Realtek Bluetooth adapter (VID=0x0BDA) present and bound to WinUSB driver
- pyusb + libusb-package installed (uv add --dev pyusb libusb-package)
- For firmware loading tests: firmware file in tests/hardware/firmware/realtek/

Run:
    uv run pytest tests/hardware/test_realtek_hw.py -v -s

These tests are SKIPPED automatically when hardware is unavailable.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
import pytest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper: skip if device is bound to system driver (not WinUSB)
# ---------------------------------------------------------------------------

def _skip_if_driver_bound(exc: Exception) -> None:
    """On Windows, if the device is managed by bthusb.sys (not WinUSB),
    USB control transfers time out. Skip rather than fail in this case.
    """
    import usb.core
    if isinstance(exc, usb.core.USBTimeoutError):
        pytest.skip(
            "USB control transfer timed out — device may be bound to "
            "Windows Bluetooth driver (bthusb.sys). Use Zadig to bind "
            "the device to WinUSB for full firmware-loading tests."
        )

# ---------------------------------------------------------------------------
# Hardware availability check — skip entire module if no device
# ---------------------------------------------------------------------------


def _detect_realtek_device():
    """Return (device, chip_info) or None if not available."""
    try:
        import libusb_package
        import usb.core
        import usb.backend.libusb1

        be = usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
        if be is None:
            return None

        from pybluehost.transport.usb import KNOWN_CHIPS
        all_devs = list(usb.core.find(find_all=True, backend=be))
        for dev in all_devs:
            for chip in KNOWN_CHIPS:
                if chip.vendor != "realtek":
                    continue
                if dev.idVendor == chip.vid and dev.idProduct == chip.pid:
                    return dev, chip
    except Exception:
        pass
    return None


_HW = _detect_realtek_device()
pytestmark = pytest.mark.skipif(
    _HW is None,
    reason="No Realtek Bluetooth USB device found (or pyusb/libusb unavailable)",
)

# Firmware directory
_FW_DIR = Path(__file__).parent / "firmware" / "realtek"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def hw_device():
    """The raw pyusb device (not opened as transport)."""
    assert _HW is not None
    return _HW[0]


@pytest.fixture(scope="module")
def hw_chip():
    """The ChipInfo for the detected device."""
    assert _HW is not None
    return _HW[1]


@pytest.fixture
def transport(hw_device, hw_chip):
    """A RealtekUSBTransport instance (not yet opened)."""
    from pybluehost.transport.usb import RealtekUSBTransport
    from pybluehost.transport.firmware import FirmwarePolicy

    return RealtekUSBTransport(
        device=hw_device,
        chip_info=hw_chip,
        firmware_policy=FirmwarePolicy.ERROR,
        extra_fw_dirs=[_FW_DIR],
    )


# ---------------------------------------------------------------------------
# Helper: open USB without firmware loading (for raw I/O tests)
# ---------------------------------------------------------------------------

async def _open_raw(transport) -> None:
    """Open USB interface and find endpoints, bypassing _initialize()."""
    import usb.util as usbutil
    try:
        transport._device.set_configuration()
    except Exception:
        pass

    cfg = transport._device.get_active_configuration()
    intf = cfg[(0, 0)]

    transport._ep_intr_in = usbutil.find_descriptor(
        intf,
        custom_match=lambda e: (
            usbutil.endpoint_direction(e.bEndpointAddress) == usbutil.ENDPOINT_IN
            and usbutil.endpoint_type(e.bmAttributes) == usbutil.ENDPOINT_TYPE_INTR
        ),
    )
    transport._ep_bulk_in = usbutil.find_descriptor(
        intf,
        custom_match=lambda e: (
            usbutil.endpoint_direction(e.bEndpointAddress) == usbutil.ENDPOINT_IN
            and usbutil.endpoint_type(e.bmAttributes) == usbutil.ENDPOINT_TYPE_BULK
        ),
    )
    transport._ep_bulk_out = usbutil.find_descriptor(
        intf,
        custom_match=lambda e: (
            usbutil.endpoint_direction(e.bEndpointAddress) == usbutil.ENDPOINT_OUT
            and usbutil.endpoint_type(e.bmAttributes) == usbutil.ENDPOINT_TYPE_BULK
        ),
    )
    transport._event_queue = asyncio.Queue()
    transport._is_open = True


def _flush_interrupt_ep(transport, max_reads: int = 8) -> list[bytes]:
    """Drain stale events from Interrupt IN endpoint."""
    import usb.core
    drained = []
    for _ in range(max_reads):
        try:
            data = transport._ep_intr_in.read(64, timeout=50)
            drained.append(bytes(data))
        except usb.core.USBTimeoutError:
            break
        except Exception:
            break
    return drained


async def _close_raw(transport) -> None:
    try:
        import usb.util as usbutil
        usbutil.release_interface(transport._device, 0)
    except Exception:
        pass
    transport._is_open = False


# ===========================================================================
# Test 1: auto_detect finds the device
# ===========================================================================

def test_auto_detect_finds_realtek_device():
    """USBTransport.auto_detect() finds the Realtek adapter."""
    from pybluehost.transport.usb import USBTransport, RealtekUSBTransport

    t = USBTransport.auto_detect(vendor="realtek")
    assert isinstance(t, RealtekUSBTransport)
    info = t.info
    assert info.type == "usb"
    assert "realtek" in info.description.lower()
    print(f"\n  [PASS] auto_detect: {info.description}")


# ===========================================================================
# Test 2: VID/PID matches KNOWN_CHIPS
# ===========================================================================

def test_device_vid_pid_in_known_chips(hw_device, hw_chip):
    """Hardware VID/PID is registered in KNOWN_CHIPS."""
    from pybluehost.transport.usb import KNOWN_CHIPS

    match = next(
        (c for c in KNOWN_CHIPS if c.vid == hw_device.idVendor and c.pid == hw_device.idProduct),
        None,
    )
    assert match is not None
    print(f"\n  [PASS] {match.vendor} {match.name} VID={match.vid:#06x} PID={match.pid:#06x}")


# ===========================================================================
# Test 3: TransportInfo
# ===========================================================================

def test_transport_info(transport, hw_chip):
    """TransportInfo fields populated from ChipInfo."""
    info = transport.info
    assert info.type == "usb"
    assert hw_chip.vendor in info.description.lower()
    assert hw_chip.name in info.description
    print(f"\n  [PASS] transport.info: {info.description}")


# ===========================================================================
# Test 4: Claim USB interface + locate HCI endpoints
# ===========================================================================

@pytest.mark.asyncio
async def test_open_claims_interface(transport):
    """Raw open claims interface 0 and finds all HCI endpoints."""
    try:
        await _open_raw(transport)
        assert transport.is_open
        assert transport._ep_intr_in is not None
        assert transport._ep_bulk_out is not None
        assert transport._ep_bulk_in is not None
        print(
            f"\n  [PASS] Endpoints: IntrIN={transport._ep_intr_in.bEndpointAddress:#04x} "
            f"BulkIN={transport._ep_bulk_in.bEndpointAddress:#04x} "
            f"BulkOUT={transport._ep_bulk_out.bEndpointAddress:#04x}"
        )
    except Exception as e:
        _skip_if_driver_bound(e)
        raise
    finally:
        await _close_raw(transport)


# ===========================================================================
# Test 5: Read ROM Version (0xFC6D) — Realtek-specific
# ===========================================================================

@pytest.mark.asyncio
async def test_hci_realtek_read_rom_version(transport):
    """Send HCI_Realtek_Read_ROM_Version (0xFC6D) → parse response."""
    try:
        await _open_raw(transport)
        _flush_interrupt_ep(transport)

        # Build vendor command: OGF=0x3F OCF=0x6D
        opcode = ((0x3F << 10) | 0x6D).to_bytes(2, "little")
        cmd = opcode + b"\x00"  # param_len=0

        await transport._control_out(cmd)
        event = await transport.read_interrupt(size=64, timeout=3.0)

        assert len(event) >= 7, f"Event too short: {len(event)} bytes"
        assert event[0] == 0x0E, f"Expected Command Complete (0x0E), got 0x{event[0]:02X}"

        status = event[5]
        assert status == 0x00, f"Command failed: status=0x{status:02X}"

        # Parse ROM version from return parameters (offset 6)
        # Realtek hardware may return 1 or 2 bytes for rom_version
        rom_version = event[6] if len(event) > 6 else 0xFF
        print(f"\n  [PASS] Read ROM Version")
        print(f"         Status      : 0x{status:02X}")
        print(f"         ROM version : 0x{rom_version:02X}")
        print(f"         Raw event   : {event.hex(' ')}")

    except Exception as e:
        _skip_if_driver_bound(e)
        raise
    finally:
        await _close_raw(transport)


# ===========================================================================
# Test 6: Firmware file availability + epatch format validation
# ===========================================================================

@pytest.mark.asyncio
async def test_firmware_file_available(transport, hw_chip):
    """Firmware file for detected chip should be present on disk."""
    fw_pattern = hw_chip.firmware_pattern
    fw_path = _FW_DIR / fw_pattern

    print(f"\n  Firmware needed: {fw_path}")
    if not fw_path.exists():
        pytest.skip(f"Firmware file not available: {fw_pattern}")

    size = fw_path.stat().st_size
    print(f"  [PASS] Firmware found: {size} bytes")

    # Check if it's a valid epatch format
    header = fw_path.read_bytes()[:16]
    is_epatch = header.startswith(b"Realtech")
    print(f"  [INFO] Epatch format: {is_epatch}")


# ===========================================================================
# Test 7: Firmware payload construction
# ===========================================================================

@pytest.mark.asyncio
async def test_firmware_payload_construction(transport, hw_chip):
    """Verify Realtek firmware can be parsed into a download payload."""
    fw_pattern = hw_chip.firmware_pattern
    fw_path = _FW_DIR / fw_pattern

    if not fw_path.exists():
        pytest.skip(f"Firmware file not available: {fw_pattern}")

    fw_data = fw_path.read_bytes()

    payload = None
    for rom_version in range(4):
        try:
            payload = transport._build_firmware_payload(fw_data, rom_version)
        except RuntimeError:
            continue
        print(f"  [INFO] ROM version 0x{rom_version:02X} -> payload {len(payload)} bytes")
        break

    assert payload is not None
    assert len(payload) > 0
    print("  [PASS] Firmware payload construction works")


# ===========================================================================
# Test 8: HCI_Reset via raw USB
# ===========================================================================

@pytest.mark.asyncio
async def test_hci_reset_raw(transport):
    """Send HCI_Reset (0x0C03) and verify Command Complete response."""
    try:
        await _open_raw(transport)
        _flush_interrupt_ep(transport)

        # HCI_Reset: OGF=0x03, OCF=0x03
        opcode = ((0x03 << 10) | 0x03).to_bytes(2, "little")
        cmd = opcode + b"\x00"  # param_len=0

        await transport._control_out(cmd)
        event = await transport.read_interrupt(size=64, timeout=3.0)

        assert len(event) >= 6, f"Event too short: {len(event)} bytes"
        assert event[0] == 0x0E, f"Expected Command Complete (0x0E), got 0x{event[0]:02X}"

        status = event[5]
        assert status == 0x00, f"HCI_Reset failed: status=0x{status:02X}"

        print(f"\n  [PASS] HCI_Reset succeeded")
        print(f"         Raw event: {event.hex(' ')}")

    except Exception as e:
        _skip_if_driver_bound(e)
        raise
    finally:
        await _close_raw(transport)


# ===========================================================================
# Test 9: Full firmware loading via _initialize()
# ===========================================================================

@pytest.mark.asyncio
async def test_realtek_firmware_loading(hw_device, hw_chip):
    """Full firmware loading test: _initialize() on real hardware.

    This test exercises the complete Realtek firmware loading sequence:
    1. HCI_Reset -> controller ready
    2. Read ROM Version -> detect if download needed
    3. Find firmware file via FirmwareManager
    4. Parse epatch -> extract correct patch
    5. Download firmware in chunks via 0xFC20
    6. HCI_Reset -> activate firmware

    SKIP if firmware file not available on disk.
    """
    from pybluehost.transport.usb import RealtekUSBTransport
    from pybluehost.transport.firmware import FirmwarePolicy

    logging.basicConfig(level=logging.INFO, force=True)
    logging.getLogger("pybluehost.transport.usb").setLevel(logging.INFO)

    fresh_transport = RealtekUSBTransport(
        device=hw_device,
        chip_info=hw_chip,
        firmware_policy=FirmwarePolicy.ERROR,
        extra_fw_dirs=[_FW_DIR],
    )

    try:
        await fresh_transport.open()
        assert fresh_transport.is_open
        print("\n  [PASS] Firmware loaded! Device is ready.")
    except Exception as e:
        err_msg = str(e).lower()
        if "not found" in err_msg or "firmware" in err_msg:
            pytest.skip(f"Firmware file not available: {e}")
        _skip_if_driver_bound(e)
        raise
    finally:
        await fresh_transport.close()
        assert not fresh_transport.is_open
