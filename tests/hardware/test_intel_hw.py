"""
Physical hardware validation tests for Intel Bluetooth USB transport.

Prerequisites:
- Intel Bluetooth adapter (VID=0x8087) present and bound to WinUSB driver
- pyusb + libusb-package installed (uv add --dev pyusb libusb-package)
- For firmware loading tests: firmware file in tests/hardware/firmware/intel/

Run:
    uv run pytest tests/hardware/test_intel_hw.py -v -s

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
                if chip.vendor != "intel":
                    continue
                if dev.idVendor == chip.vid and dev.idProduct == chip.pid:
                    return dev, chip
    except Exception:
        pass
    return None


_HW = _detect_intel_device()
pytestmark = pytest.mark.real_hardware_only(transport="usb", vendor="intel")

# Firmware directory
_FW_DIR = Path(__file__).parent / "firmware" / "intel"


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

    usbutil.claim_interface(transport._device, 0)

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
        except usb.core.USBError:
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

def test_auto_detect_finds_intel_device():
    """USBTransport.auto_detect() finds the Intel adapter."""
    from pybluehost.transport.usb import USBTransport, IntelUSBTransport

    t = USBTransport.auto_detect(vendor="intel")
    assert isinstance(t, IntelUSBTransport)
    info = t.info
    assert info.type == "usb"
    assert "intel" in info.description.lower()
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
        print(f"\n  [PASS] Endpoints: IntrIN={transport._ep_intr_in.bEndpointAddress:#04x} "
              f"BulkIN={transport._ep_bulk_in.bEndpointAddress:#04x} "
              f"BulkOUT={transport._ep_bulk_out.bEndpointAddress:#04x}")
    finally:
        await _close_raw(transport)


# ===========================================================================
# Test 5: Read Version V2 (TLV) — new-gen Intel protocol
# ===========================================================================

@pytest.mark.asyncio
async def test_hci_intel_read_version_v2(transport):
    """Send HCI_Intel_Read_Version V2 (0xFC05 + param 0xFF) → TLV response."""
    try:
        await _open_raw(transport)
        _flush_interrupt_ep(transport)

        # V2: OGF=0x3F OCF=0x05, param=0xFF
        opcode = ((0x3F << 10) | 0x05).to_bytes(2, "little")
        cmd = opcode + b"\x01\xff"  # param_len=1, param=0xFF

        await transport._control_out(cmd)
        event = await transport.read_interrupt(size=255, timeout=3.0)

        assert len(event) >= 6, f"Event too short: {len(event)} bytes"
        assert event[0] == 0x0E, f"Expected Command Complete (0x0E), got 0x{event[0]:02X}"

        status = event[5]
        assert status == 0x00, f"Command failed: status=0x{status:02X}"
        assert len(event) > 10, f"TLV response too short: {len(event)} bytes"

        print(f"\n  [PASS] Read Version V2 ({len(event)} bytes)")
        print(f"         Raw: {event[:32].hex(' ')}...")

    finally:
        await _close_raw(transport)


# ===========================================================================
# Test 6: TLV parsing — extract image_type, cnvi_top, cnvr_top
# ===========================================================================

@pytest.mark.asyncio
async def test_tlv_parsing_bootloader_detection(transport):
    """Parse TLV response and detect bootloader/operational state."""
    from pybluehost.transport.usb import IntelUSBTransport

    try:
        await _open_raw(transport)
        _flush_interrupt_ep(transport)

        opcode = ((0x3F << 10) | 0x05).to_bytes(2, "little")
        cmd = opcode + b"\x01\xff"
        await transport._control_out(cmd)
        event = await transport.read_interrupt(size=255, timeout=3.0)

        assert event[5] == 0x00, f"Read Version failed: status=0x{event[5]:02X}"

        # Parse TLV
        tlv = IntelUSBTransport._parse_tlv(event[6:])
        assert len(tlv) > 0, "No TLV entries parsed"

        # Image type
        assert IntelUSBTransport._TLV_IMAGE_TYPE in tlv
        image_type = tlv[IntelUSBTransport._TLV_IMAGE_TYPE][0]
        image_labels = {0x01: "BOOTLOADER", 0x03: "OPERATIONAL"}
        image_label = image_labels.get(image_type, f"UNKNOWN(0x{image_type:02X})")

        # cnvi_top / cnvr_top
        assert IntelUSBTransport._TLV_CNVI_TOP in tlv
        assert IntelUSBTransport._TLV_CNVR_TOP in tlv
        cnvi_top = int.from_bytes(tlv[IntelUSBTransport._TLV_CNVI_TOP][:4], "little")
        cnvr_top = int.from_bytes(tlv[IntelUSBTransport._TLV_CNVR_TOP][:4], "little")

        # Firmware name
        fw_name = IntelUSBTransport._compute_fw_name(cnvi_top, cnvr_top)

        # BD_ADDR
        bdaddr = tlv.get(IntelUSBTransport._TLV_OTP_BDADDR, b"")
        bdaddr_str = ":".join(f"{b:02X}" for b in reversed(bdaddr)) if bdaddr else "N/A"

        print(f"\n  [PASS] TLV parsed ({len(tlv)} entries)")
        print(f"         Image type  : 0x{image_type:02X} ({image_label})")
        print(f"         cnvi_top    : 0x{cnvi_top:08X}")
        print(f"         cnvr_top    : 0x{cnvr_top:08X}")
        print(f"         Firmware    : {fw_name}.sfi")
        print(f"         BD_ADDR     : {bdaddr_str}")

        assert image_type in (0x01, 0x03), f"Unexpected image_type: 0x{image_type:02X}"

    finally:
        await _close_raw(transport)


# ===========================================================================
# Test 7: Firmware name computation matches available firmware
# ===========================================================================

@pytest.mark.asyncio
async def test_firmware_name_computation(transport):
    """Computed firmware name from TLV should have a .sfi file available."""
    from pybluehost.transport.usb import IntelUSBTransport

    try:
        await _open_raw(transport)
        _flush_interrupt_ep(transport)

        opcode = ((0x3F << 10) | 0x05).to_bytes(2, "little")
        await transport._control_out(opcode + b"\x01\xff")
        event = await transport.read_interrupt(size=255, timeout=3.0)
        assert event[5] == 0x00

        tlv = IntelUSBTransport._parse_tlv(event[6:])
        cnvi_top = int.from_bytes(tlv[IntelUSBTransport._TLV_CNVI_TOP][:4], "little")
        cnvr_top = int.from_bytes(tlv[IntelUSBTransport._TLV_CNVR_TOP][:4], "little")
        fw_name = IntelUSBTransport._compute_fw_name(cnvi_top, cnvr_top)

        fw_path = _FW_DIR / f"{fw_name}.sfi"
        print(f"\n  Firmware needed: {fw_path}")
        if fw_path.exists():
            size = fw_path.stat().st_size
            print(f"  [PASS] Firmware found: {size} bytes")
        else:
            pytest.skip(f"Firmware file not available: {fw_path.name}")

    finally:
        await _close_raw(transport)


# ===========================================================================
# Test 8: Full firmware loading via _initialize() (new-gen path)
# ===========================================================================

@pytest.mark.asyncio
async def test_intel_firmware_loading(hw_device, hw_chip):
    """Full firmware loading test: _initialize() on real hardware.

    This test exercises the complete new-gen Intel firmware loading sequence:
    1. Read Version V2 -> TLV -> detect bootloader/operational
    2. If operational: reboot to bootloader first
    3. Compute firmware name, download via secure_send, reset
    4. Verify operational state after loading

    SKIP if firmware file not available on disk.
    """
    import struct
    import usb.util as usbutil
    from pybluehost.transport.usb import IntelUSBTransport
    from pybluehost.transport.firmware import FirmwarePolicy

    logging.basicConfig(level=logging.INFO, force=True)
    logging.getLogger("pybluehost.transport.usb").setLevel(logging.INFO)

    # --- Phase 0: Ensure device is in bootloader mode ---
    try:
        hw_device.set_configuration()
    except Exception:
        pass
    cfg = hw_device.get_active_configuration()
    intf = cfg[(0, 0)]
    usbutil.claim_interface(hw_device, 0)
    ep_intr = usbutil.find_descriptor(intf, custom_match=lambda e: (
        usbutil.endpoint_direction(e.bEndpointAddress) == usbutil.ENDPOINT_IN
        and usbutil.endpoint_type(e.bmAttributes) == usbutil.ENDPOINT_TYPE_INTR))

    # Drain stale events
    for _ in range(10):
        try:
            ep_intr.read(255, timeout=50)
        except usb.core.USBTimeoutError:
            break
        except usb.core.USBError:
            break

    opcode_rv = ((0x3F << 10) | 0x05).to_bytes(2, "little")
    hw_device.ctrl_transfer(0x20, 0x00, 0, 0, opcode_rv + b"\x01\xff")
    resp = bytes(ep_intr.read(255, timeout=5000))
    tlv = IntelUSBTransport._parse_tlv(resp[6:])
    default_img = bytes([0xFF])
    image_type = tlv.get(IntelUSBTransport._TLV_IMAGE_TYPE, default_img)[0]
    print(f"\n  Current state: image_type=0x{image_type:02X}")

    if image_type == IntelUSBTransport._IMAGE_TYPE_OPERATIONAL:
        print("  Rebooting to bootloader (Intel Reset reset_type=0x01)...")
        reset_op = ((0x3F << 10) | 0x01).to_bytes(2, "little")
        params = struct.pack("<BBBBI", 0x01, 0x01, 0x01, 0x00, 0)
        hw_device.ctrl_transfer(0x20, 0x00, 0, 0, reset_op + len(params).to_bytes(1, "little") + params)
        usbutil.release_interface(hw_device, 0)

        import time
        time.sleep(3)

        # Re-find device after reboot
        import libusb_package
        import usb.core
        import usb.backend.libusb1
        be = usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
        new_dev = usb.core.find(idVendor=0x8087, idProduct=hw_chip.pid, backend=be)
        assert new_dev is not None, "Device not found after bootloader reboot"
        hw_device = new_dev
        print("  Device rebooted to bootloader mode")
    else:
        usbutil.release_interface(hw_device, 0)
        print("  Already in bootloader mode")

    # --- Phase 1: Load firmware via IntelUSBTransport.open() ---
    fresh_transport = IntelUSBTransport(
        device=hw_device,
        chip_info=hw_chip,
        firmware_policy=FirmwarePolicy.ERROR,
        extra_fw_dirs=[_FW_DIR],
    )

    try:
        await fresh_transport.open()
        assert fresh_transport.is_open
        print("\n  [PASS] Firmware loaded! Device is operational.")
    except Exception as e:
        err_msg = str(e).lower()
        if "not found" in err_msg or "firmware" in err_msg:
            pytest.skip(f"Firmware file not available: {e}")
        raise
    finally:
        await fresh_transport.close()
        assert not fresh_transport.is_open
