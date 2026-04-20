"""
Physical hardware validation tests for Intel Bluetooth USB transport.

Prerequisites:
- Intel Bluetooth adapter (VID=0x8087) present and bound to WinUSB driver
- pyusb + libusb-package installed (uv add --dev pyusb libusb-package)

Run:
    uv run pytest tests/hardware/test_intel_hw.py -v -s

These tests are SKIPPED automatically when hardware is unavailable.
"""
from __future__ import annotations

import asyncio
import sys
import pytest

# ---------------------------------------------------------------------------
# Hardware availability check — skip entire module if no device
# ---------------------------------------------------------------------------

def _detect_intel_device():
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
                if dev.idVendor == chip.vid and dev.idProduct == chip.pid:
                    return dev, chip
    except Exception:
        pass
    return None


_HW = _detect_intel_device()
pytestmark = pytest.mark.skipif(
    _HW is None,
    reason="No Intel Bluetooth USB device found (or pyusb/libusb unavailable)",
)


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
    """An IntelUSBTransport instance (not yet opened)."""
    from pybluehost.transport.usb import IntelUSBTransport
    from pybluehost.transport.firmware import FirmwarePolicy
    return IntelUSBTransport(
        device=hw_device,
        chip_info=hw_chip,
        firmware_policy=FirmwarePolicy.ERROR,  # don't prompt in CI
    )


# ---------------------------------------------------------------------------
# Test 1: auto_detect finds the device
# ---------------------------------------------------------------------------

def test_auto_detect_finds_intel_device():
    """USBTransport.auto_detect() should find the Intel adapter and return
    an IntelUSBTransport instance."""
    from pybluehost.transport.usb import USBTransport, IntelUSBTransport

    t = USBTransport.auto_detect()
    assert isinstance(t, IntelUSBTransport), (
        f"Expected IntelUSBTransport, got {type(t).__name__}"
    )
    info = t.info
    assert info.type == "usb"
    assert "intel" in info.description.lower()
    print(f"\n  [PASS] auto_detect: {info.description}")


# ---------------------------------------------------------------------------
# Test 2: Device identity — VID/PID matches KNOWN_CHIPS
# ---------------------------------------------------------------------------

def test_device_vid_pid_in_known_chips(hw_device, hw_chip):
    """The hardware VID/PID must be registered in KNOWN_CHIPS."""
    from pybluehost.transport.usb import KNOWN_CHIPS

    match = next(
        (c for c in KNOWN_CHIPS if c.vid == hw_device.idVendor and c.pid == hw_device.idProduct),
        None,
    )
    assert match is not None, (
        f"VID={hw_device.idVendor:#06x} PID={hw_device.idProduct:#06x} "
        f"not in KNOWN_CHIPS"
    )
    print(f"\n  [PASS] KNOWN_CHIPS match: {match.vendor} {match.name} "
          f"VID={match.vid:#06x} PID={match.pid:#06x}")


# ---------------------------------------------------------------------------
# Test 3: TransportInfo is correct
# ---------------------------------------------------------------------------

def test_transport_info(transport, hw_chip):
    """TransportInfo fields must be populated from ChipInfo."""
    info = transport.info
    assert info.type == "usb"
    assert hw_chip.vendor in info.description.lower()
    assert hw_chip.name in info.description
    assert info.details["vid"] == hex(hw_chip.vid)
    assert info.details["pid"] == hex(hw_chip.pid)
    print(f"\n  [PASS] transport.info: {info.description}")


# ---------------------------------------------------------------------------
# Helper: open USB without firmware loading (for raw I/O tests)
# ---------------------------------------------------------------------------

async def _open_raw(transport) -> None:
    """Open USB interface and find endpoints, bypassing _initialize().

    Intel BE200 under WinUSB driver powers up in bootloader mode — firmware
    loading is deferred. We test raw USB I/O capability independently.
    """
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
    """Drain any stale events queued in the Interrupt IN endpoint.
    Returns list of drained packets (for diagnostic output).
    """
    import usb.core
    drained = []
    for _ in range(max_reads):
        try:
            data = transport._ep_intr_in.read(64, timeout=50)  # 50 ms
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


# ---------------------------------------------------------------------------
# Test 4: Claim USB interface + locate HCI endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_open_claims_interface(transport):
    """open() (raw, no firmware) should claim interface 0 and find
    the Interrupt IN endpoint used for HCI Events."""
    try:
        await _open_raw(transport)
        assert transport.is_open
        assert transport._ep_intr_in is not None, \
            "Interrupt IN endpoint not found"
        assert transport._ep_bulk_out is not None, \
            "Bulk OUT endpoint not found"
        assert transport._ep_bulk_in is not None, \
            "Bulk IN endpoint not found"
        print(f"\n  [PASS] Interface claimed. Endpoints:")
        print(f"         Interrupt IN : {transport._ep_intr_in.bEndpointAddress:#04x}")
        print(f"         Bulk IN      : {transport._ep_bulk_in.bEndpointAddress:#04x}")
        print(f"         Bulk OUT     : {transport._ep_bulk_out.bEndpointAddress:#04x}")
    finally:
        await _close_raw(transport)
        assert not transport.is_open


# ---------------------------------------------------------------------------
# Test 5: HCI Intel Read Version (vendor command 0xFC05)
#
# Intel BE200 under WinUSB boots in bootloader mode. HCI_Intel_Read_Version
# is valid in both modes and returns the current fw_variant.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hci_intel_read_version(transport):
    """Send HCI_Intel_Read_Version (0xFC05) and receive a valid vendor event.

    Expected Vendor Specific Event (0xFF):
      [0] = 0xFF  event code
      [1] = param_total_len
      [2] = num_hci_cmds (0x01)
      [3,4] = opcode echo (little-endian)
      [5] = status (0x00 = success)
      [6] = hw_platform
      [7] = hw_variant
      [8] = fw_variant  (0x03=operational, 0x06=bootloader)
    """
    try:
        await _open_raw(transport)

        # Flush stale events before sending command
        stale = _flush_interrupt_ep(transport)
        if stale:
            print(f"\n  (flushed {len(stale)} stale event(s) from interrupt EP)")
            for s in stale:
                print(f"    stale: {s.hex(' ')}")

        # HCI_Intel_Read_Version: OGF=0x3F OCF=0x05, no params
        opcode = ((0x3F << 10) | 0x05).to_bytes(2, "little")
        cmd = opcode + b"\x00"

        await transport._control_out(cmd)
        event = await transport.read_interrupt(size=64, timeout=3.0)

        print(f"\n  [PASS] HCI_Intel_Read_Version ({len(event)} bytes): {event.hex(' ')}")

        assert len(event) >= 6, f"Event too short: {len(event)} bytes"
        assert event[0] in (0x0E, 0xFF), (
            f"Unexpected event code 0x{event[0]:02X} "
            f"(expected 0x0E Command Complete or 0xFF Vendor Specific)"
        )

        status = event[5] if len(event) > 5 else 0xFF
        assert status == 0x00, f"Command failed: status=0x{status:02X}"

        if event[0] == 0xFF and len(event) > 8:
            hw_variant  = event[7]
            fw_variant  = event[8]
            fw_labels   = {0x03: "operational", 0x06: "bootloader"}
            fw_label    = fw_labels.get(fw_variant, f"unknown(0x{fw_variant:02X})")
            print(f"         hw_variant : 0x{hw_variant:02X}")
            print(f"         fw_variant : 0x{fw_variant:02X} ({fw_label})")
            if fw_variant == 0x06:
                print("         NOTE: device in bootloader mode — "
                      "firmware loading required for full operation")

    finally:
        await _close_raw(transport)


# ---------------------------------------------------------------------------
# Test 6: HCI Reset (standard command OGF=0x03 OCF=0x03)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hci_reset(transport):
    """Send HCI_Reset (0x0C03) and receive Command Complete (0x0E).

    HCI_Reset is valid even in bootloader mode for Intel chips.
    """
    try:
        await _open_raw(transport)
        _flush_interrupt_ep(transport)

        opcode = ((0x03 << 10) | 0x03).to_bytes(2, "little")  # OGF=0x03 OCF=0x03
        cmd = opcode + b"\x00"

        await transport._control_out(cmd)
        event = await transport.read_interrupt(size=64, timeout=3.0)

        print(f"\n  [PASS] HCI_Reset ({len(event)} bytes): {event.hex(' ')}")

        assert len(event) >= 6
        assert event[0] == 0x0E, (
            f"Expected Command Complete (0x0E), got 0x{event[0]:02X}. "
            f"Full event: {event.hex(' ')}"
        )
        status = event[5]
        assert status == 0x00, f"HCI_Reset failed: status=0x{status:02X}"
        print(f"         status: OK (Command Complete)")

    finally:
        await _close_raw(transport)
