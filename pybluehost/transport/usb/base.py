"""USBTransport base class.

Provides USB device enumeration (auto_detect, list_devices), endpoint
routing, and the abstract initialize() hook that vendor-specific subclasses
override for firmware upload. Subclasses (Intel/Realtek/CSR) live in
sibling modules.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import asdict
from typing import Any

from pybluehost.core.errors import USBAccessDeniedError
from pybluehost.transport.base import Transport, TransportInfo
from pybluehost.transport.firmware import FirmwarePolicy
from pybluehost.transport.usb.chips import ChipInfo
from pybluehost.transport.usb.discovery import (
    DeviceCandidate,
    _bluetooth_usb_occurrence_indexes,
    _bumble_transport_names,
    _descriptor_string,
    _matches_usb_selection,
    format_usb_class,
    get_usb_endpoints,
    is_bluetooth_usb_device,
    known_chip_for,
    known_usb_vendors,
    usb_class_tuple,
)
from pybluehost.transport.usb.diagnostics import (
    USBDeviceCheck,
    USBDeviceDiagnosis,
    USBDeviceDiagnostics,
    _diagnose_intel_version_direct,
    _diagnose_realtek_version_direct,
    _diagnostic_report_checks,
    _find_interrupt_in_endpoint,
)
from pybluehost.transport.usb.errors import NoBluetoothDeviceError

logger = logging.getLogger(__name__)

# Lazy import: pyusb is optional
try:
    import usb
    import usb.core
    import usb.util
except ImportError:
    usb = None  # type: ignore[assignment]


def _usb():
    """Return the usb module from the parent package's namespace.

    Tests patch ``pybluehost.transport.usb.usb``; accessing via the parent
    package ensures this module sees the same (potentially patched) reference.
    """
    pkg = sys.modules.get("pybluehost.transport.usb")
    if pkg is not None:
        return getattr(pkg, "usb", usb)
    return usb


def parse_hci_reset_status(event: bytes) -> int | None:
    if len(event) >= 6 and event[0] == 0x0E and event[3:5] == bytes.fromhex("03 0c"):
        return event[5]
    return None


class USBTransport(Transport):
    """USB HCI transport via pyusb (WinUSB on Windows, libusb on Linux)."""

    def __init__(
        self,
        device: Any,
        chip_info: ChipInfo | None = None,
        firmware_policy: FirmwarePolicy = FirmwarePolicy.PROMPT,
        extra_fw_dirs: list | None = None,
    ) -> None:
        super().__init__()
        self._device = device
        self._chip_info = chip_info
        self._firmware_policy = firmware_policy
        self._extra_fw_dirs = extra_fw_dirs or []
        self._is_open = False
        self._reader_tasks: list[asyncio.Task] = []  # type: ignore[type-arg]
        self._ep_iso_in: Any = None
        self._ep_iso_out: Any = None
        self._current_alt_setting: int = 0

    @classmethod
    def _get_usb_backend(cls) -> Any:
        """Return the best available pyusb backend for this platform.

        On Windows, prefers libusb-package (bundles libusb-1.0.dll).
        Falls back to pyusb default backend discovery on Linux/macOS.
        """
        if sys.platform == "win32":
            try:
                import libusb_package
                import usb.backend.libusb1
                be = usb.backend.libusb1.get_backend(
                    find_library=libusb_package.find_library
                )
                if be is not None:
                    return be
            except ImportError:
                pass
        return None  # pyusb default discovery

    @classmethod
    def auto_detect(
        cls,
        firmware_policy: FirmwarePolicy = FirmwarePolicy.PROMPT,
        vendor: str | None = None,
        bus: int | None = None,
        address: int | None = None,
        vid: int | None = None,
        pid: int | None = None,
        serial: str | None = None,
        occurrence: int | None = None,
    ) -> "USBTransport":
        """Enumerate USB devices, match KNOWN_CHIPS, return correct subclass instance."""
        from pybluehost.transport.usb import KNOWN_CHIPS  # local to avoid circular import
        usb_mod = _usb()
        if usb_mod is None:
            raise RuntimeError(
                "pyusb not installed. Run: pip install pyusb"
            )
        if (vid is None) != (pid is None):
            raise ValueError("USB VID/PID filters must be provided together")
        if occurrence is not None and occurrence <= 0:
            raise ValueError("USB occurrence filter must be greater than zero")
        if occurrence is not None and (vid is None or pid is None):
            raise ValueError("USB occurrence filter requires VID/PID filters")
        if serial is not None and not serial:
            raise ValueError("USB serial filter cannot be empty")

        selected_vendor = vendor.lower() if vendor is not None else None
        supported_vendors = sorted(known_usb_vendors())
        if selected_vendor is not None and selected_vendor not in supported_vendors:
            raise ValueError(
                "Unsupported USB vendor filter: "
                f"{vendor!r}. Expected one of: {', '.join(supported_vendors)}."
            )

        backend = cls._get_usb_backend()
        chips = [
            chip for chip in KNOWN_CHIPS
            if selected_vendor is None or chip.vendor == selected_vendor
        ]

        # 1. Search known chips by VID/PID
        all_devices = list(usb_mod.core.find(find_all=True, backend=backend))
        occurrence_indexes = _bluetooth_usb_occurrence_indexes(all_devices)
        for dev in all_devices:
            if not _matches_usb_selection(
                dev,
                bus=bus,
                address=address,
                vid=vid,
                pid=pid,
                serial=serial,
                occurrence=occurrence,
                occurrence_index=occurrence_indexes.get(id(dev)),
            ):
                continue
            for chip in chips:
                if dev.idVendor == chip.vid and dev.idProduct == chip.pid:
                    transport_cls = chip.transport_class or cls
                    return transport_cls(
                        device=dev,
                        chip_info=chip,
                        firmware_policy=firmware_policy,
                    )

        # 2. Generic fallback for Bluetooth-class adapters that are not in
        # KNOWN_CHIPS. Vendor-specific calls should not silently return a
        # different adapter type.
        if selected_vendor is None:
            for dev in all_devices:
                if not _matches_usb_selection(
                    dev,
                    bus=bus,
                    address=address,
                    vid=vid,
                    pid=pid,
                    serial=serial,
                    occurrence=occurrence,
                    occurrence_index=occurrence_indexes.get(id(dev)),
                ):
                    continue
                if is_bluetooth_usb_device(dev):
                    return cls(
                        device=dev,
                        chip_info=None,
                        firmware_policy=firmware_policy,
                    )

        target = f" {selected_vendor}" if selected_vendor is not None else ""
        loc_parts: list[str] = []
        if vid is not None and pid is not None:
            loc_parts.append(f"vid={vid:04x} pid={pid:04x}")
        if serial is not None:
            loc_parts.append(f"serial={serial}")
        if occurrence is not None:
            loc_parts.append(f"occurrence={occurrence}")
        if bus is not None or address is not None:
            loc_parts.append(f"bus={bus} address={address}")
        loc = f" at {', '.join(loc_parts)}" if loc_parts else ""
        raise NoBluetoothDeviceError(
            f"No supported{target} Bluetooth USB device found{loc}. "
            "Ensure your adapter is plugged in and (on Windows) has the WinUSB driver."
        )

    @classmethod
    def list_devices(cls) -> list[DeviceCandidate]:
        """Enumerate every plugged-in Bluetooth USB device known to KNOWN_CHIPS."""
        from pybluehost.transport.usb import KNOWN_CHIPS  # local to avoid circular import
        usb_mod = _usb()
        if usb_mod is None:
            return []
        backend = cls._get_usb_backend()
        try:
            all_devices = list(usb_mod.core.find(find_all=True, backend=backend))
        except Exception:
            return []

        result: list[DeviceCandidate] = []
        occurrence_indexes = _bluetooth_usb_occurrence_indexes(all_devices)
        for dev in all_devices:
            for chip in KNOWN_CHIPS:
                if dev.idVendor == chip.vid and dev.idProduct == chip.pid:
                    result.append(
                        DeviceCandidate(
                            chip_info=chip,
                            bus=int(getattr(dev, "bus", 0) or 0),
                            address=int(getattr(dev, "address", 0) or 0),
                            occurrence=occurrence_indexes.get(id(dev), 1),
                        )
                    )
                    break
        return result

    @classmethod
    def probe_devices(
        cls, verbose: bool = False, intel_tlv: bool = False
    ) -> list[dict[str, Any]]:
        """Enumerate Bluetooth USB devices, including unknown Bluetooth-class devices."""
        usb_mod = _usb()
        if usb_mod is None:
            raise RuntimeError(
                "pyusb not installed. Run: pip install pyusb\n"
                "On Windows, also install: pip install libusb-package"
            )

        backend = cls._get_usb_backend()
        all_devices = list(usb_mod.core.find(find_all=True, backend=backend))
        results: list[dict[str, Any]] = []
        vid_pid_counts: dict[tuple[int, int], int] = {}

        for dev in all_devices:
            chip = known_chip_for(dev)
            if not is_bluetooth_usb_device(dev):
                continue

            vid_pid_key = (int(dev.idVendor), int(dev.idProduct))
            vid_pid_counts[vid_pid_key] = vid_pid_counts.get(vid_pid_key, 0) + 1

            info: dict[str, Any] = {
                "index": len(results) + 1,
                "vid": dev.idVendor,
                "pid": dev.idProduct,
                "vid_pid": f"{dev.idVendor:04x}:{dev.idProduct:04x}",
                "id": f"{dev.idVendor:04X}:{dev.idProduct:04X}",
                "vendor": chip.vendor if chip else "unknown",
                "chip_name": chip.name if chip else "Unknown BT Device",
                "bus": getattr(dev, "bus", None),
                "address": getattr(dev, "address", None),
                "device_class": f"{getattr(dev, 'bDeviceClass', 0):02x}:"
                               f"{getattr(dev, 'bDeviceSubClass', 0):02x}:"
                               f"{getattr(dev, 'bDeviceProtocol', 0):02x}",
                "device_class_name": format_usb_class(usb_class_tuple(dev, "bDevice")),
                "subclass_protocol": (
                    f"{int(getattr(dev, 'bDeviceSubClass', 0) or 0)}/"
                    f"{int(getattr(dev, 'bDeviceProtocol', 0) or 0)}"
                ),
                "bumble_transport_names": _bumble_transport_names(
                    dev, vid_pid_counts[vid_pid_key]
                ),
            }
            info["transport_names"] = info["bumble_transport_names"]
            device_class_name = info["device_class_name"]
            info["class_name"] = (
                device_class_name.split(" (", 1)[0]
                if isinstance(device_class_name, str)
                else device_class_name
            )
            class_code, subclass, protocol = usb_class_tuple(dev, "bDevice")
            info["subclass_name"] = (
                "RF Controller"
                if (class_code, subclass) == (0xE0, 0x01)
                else str(subclass)
            )
            info["protocol_name"] = (
                "Bluetooth Programming Interface"
                if (class_code, subclass, protocol) == (0xE0, 0x01, 0x01)
                else str(protocol)
            )
            serial = _descriptor_string(dev, "serial_number")
            manufacturer = _descriptor_string(dev, "manufacturer")
            product = _descriptor_string(dev, "product")
            if serial:
                info["serial"] = serial
            if manufacturer:
                info["manufacturer"] = manufacturer
            if product:
                info["product"] = product

            if verbose:
                info["endpoints"] = get_usb_endpoints(dev)

            if intel_tlv and chip and chip.vendor == "intel":
                tlv_info = cls._probe_intel_tlv(dev)
                if tlv_info:
                    info.update(tlv_info)

            results.append(info)

        return results

    @classmethod
    def diagnose_all_devices(cls) -> list[USBDeviceDiagnosis]:
        """Run transport-layer USB/HCI diagnostics for every Bluetooth USB device."""
        usb_mod = _usb()
        if usb_mod is None:
            raise RuntimeError(
                "pyusb not installed. Run: pip install pyusb\n"
                "On Windows, also install: pip install libusb-package"
            )

        backend = cls._get_usb_backend()
        all_devices = list(usb_mod.core.find(find_all=True, backend=backend))
        return [
            cls.diagnose_device(dev)
            for dev in all_devices
            if is_bluetooth_usb_device(dev)
        ]

    @classmethod
    def diagnose_device(cls, dev: Any) -> USBDeviceDiagnosis:
        """Check USB access, endpoint presence, HCI Reset send and reset event status."""
        usb_mod = _usb()
        checks: list[USBDeviceCheck] = []
        chip = known_chip_for(dev)

        try:
            try:
                dev.set_configuration()
            except Exception:
                pass
            cfg = dev.get_active_configuration()
            checks.append(USBDeviceCheck("ok", "USB access", "configuration readable"))
            checks.append(
                USBDeviceCheck("ok", "WinUSB/libusb driver access", "interface is accessible")
            )
        except usb_mod.core.USBError as e:
            errno = getattr(e, "errno", None)
            checks.append(
                USBDeviceCheck(
                    "fail",
                    "USB access",
                    f"{type(e).__name__}: {e} (errno={errno})",
                )
            )
            report = USBDeviceDiagnostics.diagnose(dev, errno or 0, sys.platform)
            checks.extend(_diagnostic_report_checks(report))
            return USBDeviceDiagnosis(dev, chip, checks)
        except NotImplementedError as e:
            checks.append(
                USBDeviceCheck(
                    "fail",
                    "WinUSB/libusb driver access",
                    f"{type(e).__name__}: {e}",
                )
            )
            report = USBDeviceDiagnostics.diagnose(dev, -12, sys.platform)
            checks.extend(_diagnostic_report_checks(report))
            return USBDeviceDiagnosis(dev, chip, checks)
        except Exception as e:
            checks.append(USBDeviceCheck("fail", "USB access", f"{type(e).__name__}: {e}"))
            return USBDeviceDiagnosis(dev, chip, checks)

        try:
            intf = cfg[(0, 0)]
        except Exception as e:
            checks.append(USBDeviceCheck("fail", "USB interface 0", f"{type(e).__name__}: {e}"))
            return USBDeviceDiagnosis(dev, chip, checks)

        ep_intr = _find_interrupt_in_endpoint(intf)
        if ep_intr is None:
            checks.append(USBDeviceCheck("fail", "Interrupt IN endpoint", "not found"))
            return USBDeviceDiagnosis(dev, chip, checks)
        checks.append(USBDeviceCheck("ok", "Interrupt IN endpoint", "found"))

        try:
            for _ in range(8):
                try:
                    ep_intr.read(255, timeout=50)
                except Exception:
                    break
            dev.ctrl_transfer(0x20, 0x00, 0x0000, 0x0000, bytes.fromhex("03 0c 00"))
            checks.append(USBDeviceCheck("ok", "HCI Reset command sent", "success"))
        except Exception as e:
            checks.append(
                USBDeviceCheck("fail", "HCI Reset command sent", f"{type(e).__name__}: {e}")
            )
            return USBDeviceDiagnosis(dev, chip, checks)

        try:
            event = bytes(ep_intr.read(255, timeout=3000))
            checks.append(
                USBDeviceCheck("ok", "HCI Reset event received", event.hex(" "))
            )
        except Exception as e:
            checks.append(
                USBDeviceCheck("fail", "HCI Reset event received", f"{type(e).__name__}: {e}")
            )
            return USBDeviceDiagnosis(dev, chip, checks)

        status = parse_hci_reset_status(event)
        if status is None:
            checks.append(
                USBDeviceCheck("fail", "HCI Reset event status", "unexpected event format")
            )
        elif status != 0:
            checks.append(
                USBDeviceCheck(
                    "fail",
                    "HCI Reset status",
                    f"0x{status:02X}; Controller rejected HCI Reset; firmware load may be required.",
                )
            )
        else:
            checks.append(USBDeviceCheck("ok", "HCI Reset status", "0x00"))

        if chip and chip.vendor == "intel":
            checks.extend(_diagnose_intel_version_direct(dev, ep_intr))
        elif chip and chip.vendor == "realtek":
            checks.extend(_diagnose_realtek_version_direct(dev, ep_intr))

        try:
            usb_mod.util.release_interface(dev, 0)
        except Exception:
            pass
        try:
            usb_mod.util.dispose_resources(dev)
        except Exception:
            pass
        return USBDeviceDiagnosis(dev, chip, checks)

    @staticmethod
    def _probe_intel_tlv(dev: Any) -> dict[str, Any] | None:
        """Send Intel Read Version V2 and parse TLV response for probe output."""
        from pybluehost.transport.usb import IntelUSBTransport  # local to avoid circular import
        usb_mod = _usb()
        if usb_mod is None:
            return None
        try:
            try:
                dev.set_configuration()
            except Exception:
                pass
            cfg = dev.get_active_configuration()
            intf = cfg[(0, 0)]

            ep_intr = _find_interrupt_in_endpoint(intf)
            if ep_intr is None:
                return None

            for _ in range(8):
                try:
                    ep_intr.read(255, timeout=50)
                except Exception:
                    break

            opcode = ((0x3F << 10) | 0x05).to_bytes(2, "little")
            dev.ctrl_transfer(0x20, 0x00, 0x0000, 0x0000, opcode + b"\x01\xff")
            resp = bytes(ep_intr.read(255, timeout=3000))

            if len(resp) < 7 or resp[0] != 0x0E or resp[5] != 0x00:
                return None

            tlv = IntelUSBTransport._parse_tlv(resp[6:])
            if not tlv:
                return None

            image_type = tlv.get(IntelUSBTransport._TLV_IMAGE_TYPE, b"\xff")[0]
            sbe_raw = tlv.get(IntelUSBTransport._TLV_SBE_TYPE)
            cnvi_top_raw = tlv.get(IntelUSBTransport._TLV_CNVI_TOP, b"\0\0\0\0")
            cnvr_top_raw = tlv.get(IntelUSBTransport._TLV_CNVR_TOP, b"\0\0\0\0")
            cnvi_bt_raw = tlv.get(IntelUSBTransport._TLV_CNVI_BT, b"\0\0\0\0")
            bdaddr_raw = tlv.get(IntelUSBTransport._TLV_OTP_BDADDR, b"")

            cnvi_top = int.from_bytes(cnvi_top_raw[:4], "little")
            cnvr_top = int.from_bytes(cnvr_top_raw[:4], "little")
            cnvi_bt = int.from_bytes(cnvi_bt_raw[:4], "little")
            image_labels = {0x01: "BOOTLOADER", 0x03: "OPERATIONAL"}
            sbe_labels = {0x00: "RSA", 0x01: "ECDSA"}
            fw_name = IntelUSBTransport._compute_fw_name(cnvi_top, cnvr_top)
            bdaddr_str = (
                ":".join(f"{b:02X}" for b in reversed(bdaddr_raw))
                if len(bdaddr_raw) == 6
                else None
            )

            result: dict[str, Any] = {
                "image_type": image_type,
                "image_type_str": image_labels.get(image_type, f"0x{image_type:02X}"),
                "sbe_type": sbe_raw[0] if sbe_raw else None,
                "sbe_type_str": (
                    sbe_labels.get(sbe_raw[0], f"0x{sbe_raw[0]:02X}")
                    if sbe_raw
                    else "N/A"
                ),
                "fw_name": f"{fw_name}.sfi",
                "cnvi_top": f"0x{cnvi_top:08X}",
                "cnvr_top": f"0x{cnvr_top:08X}",
                "cnvi_bt": f"0x{cnvi_bt:08X}",
            }
            if bdaddr_str:
                result["bd_addr"] = bdaddr_str
            return result
        except Exception:
            return None
        finally:
            try:
                _usb().util.release_interface(dev, 0)
            except Exception:
                pass

    async def open(self) -> None:
        """Open USB transport: claim interface, locate endpoints, initialize."""
        if sys.platform == "win32":
            self._verify_winusb_driver()

        # Claim HCI interface 0 (HCI Commands/Events/ACL)
        import usb.util as usbutil
        try:
            self._device.set_configuration()
        except Exception:
            pass  # Already configured

        usb_mod = _usb()
        try:
            cfg = self._device.get_active_configuration()
        except (usb_mod.core.USBError, NotImplementedError) as e:
            errno = getattr(e, "errno", None)
            if errno is None and isinstance(e, NotImplementedError):
                errno = -12  # LIBUSB_ERROR_NOT_SUPPORTED on Windows
            report = USBDeviceDiagnostics.diagnose(self._device, errno, sys.platform)
            raise USBAccessDeniedError(asdict(report)) from e

        intf = cfg[(0, 0)]  # Interface 0, alternate setting 0

        # Claim the interface (required for endpoint I/O on most platforms)
        usbutil.claim_interface(self._device, 0)

        # Locate Interrupt IN endpoint (HCI Events)
        self._ep_intr_in = usbutil.find_descriptor(
            intf,
            custom_match=lambda e: (
                usbutil.endpoint_direction(e.bEndpointAddress) == usbutil.ENDPOINT_IN
                and usbutil.endpoint_type(e.bmAttributes) == usbutil.ENDPOINT_TYPE_INTR
            ),
        )
        # Locate Bulk IN/OUT endpoints (ACL Data)
        self._ep_bulk_in = usbutil.find_descriptor(
            intf,
            custom_match=lambda e: (
                usbutil.endpoint_direction(e.bEndpointAddress) == usbutil.ENDPOINT_IN
                and usbutil.endpoint_type(e.bmAttributes) == usbutil.ENDPOINT_TYPE_BULK
            ),
        )
        self._ep_bulk_out = usbutil.find_descriptor(
            intf,
            custom_match=lambda e: (
                usbutil.endpoint_direction(e.bEndpointAddress) == usbutil.ENDPOINT_OUT
                and usbutil.endpoint_type(e.bmAttributes) == usbutil.ENDPOINT_TYPE_BULK
            ),
        )

        # Event queue for _wait_for_event
        self._event_queue: asyncio.Queue[bytes] = asyncio.Queue()

        await self._initialize()
        self._is_open = True

        # Start background readers to push data to the sink
        self._reader_tasks = [
            asyncio.create_task(self._read_interrupt_loop()),
            asyncio.create_task(self._read_bulk_loop()),
        ]

    async def close(self) -> None:
        """Close USB transport: cancel readers, release interface, close device."""
        self._is_open = False
        if self._reader_tasks:
            done, pending = await asyncio.wait(  # pragma: no cover
                self._reader_tasks,
                timeout=1.0,
            )
            for task in pending:
                task.cancel()  # pragma: no cover
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)  # pragma: no cover
        self._reader_tasks.clear()
        try:
            import usb.util as usbutil
            usbutil.release_interface(self._device, 0)
            usbutil.dispose_resources(self._device)  # pragma: no cover
        except Exception:
            pass
        try:
            self._device.close()
        except Exception:
            pass

    async def select_sco_alt_setting(self, alt: int) -> None:
        """Switch USB Interface 0 to alternate setting `alt`, then re-enumerate
        the iso IN/OUT endpoints.

        Alt 0 = SCO off (only HCI events + ACL); iso endpoints are absent.
        Alt >= 1 = SCO on; vendor-specific iso packet sizes (CVSD vs mSBC).

        Cached: a no-op if we're already on the requested alt setting.
        """
        if self._current_alt_setting == alt:
            return
        import usb.util as usbutil
        self._device.set_interface_altsetting(interface=0, alternate_setting=alt)
        cfg = self._device.get_active_configuration()
        iface = cfg[(0, alt)]
        self._ep_iso_in = usbutil.find_descriptor(
            iface,
            custom_match=lambda e: (
                usbutil.endpoint_direction(e.bEndpointAddress) == usbutil.ENDPOINT_IN
                and usbutil.endpoint_type(e.bmAttributes) == usbutil.ENDPOINT_TYPE_ISO
            ),
        )
        self._ep_iso_out = usbutil.find_descriptor(
            iface,
            custom_match=lambda e: (
                usbutil.endpoint_direction(e.bEndpointAddress) == usbutil.ENDPOINT_OUT
                and usbutil.endpoint_type(e.bmAttributes) == usbutil.ENDPOINT_TYPE_ISO
            ),
        )
        self._current_alt_setting = alt

    async def send(self, data: bytes) -> None:
        """Route by H4 packet type indicator byte."""
        if not data:
            raise ValueError("Cannot send empty data")
        packet_type = data[0]
        payload = data[1:]
        if packet_type == 0x01:
            await self._control_out(payload)  # HCI Command → Control EP
        elif packet_type == 0x02:
            await self._bulk_out(payload)  # ACL Data → Bulk OUT
        elif packet_type == 0x03:
            await self._isoch_out(payload)  # SCO Data → Isoch OUT
        else:
            raise ValueError(
                f"Unknown H4 packet type: 0x{packet_type:02X}. "
                "Expected 0x01 (Command), 0x02 (ACL), or 0x03 (SCO)."
            )

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def info(self) -> TransportInfo:
        name = self._chip_info.name if self._chip_info else "Unknown"
        vendor = self._chip_info.vendor if self._chip_info else "unknown"
        return TransportInfo(
            type="usb",
            description=f"USB Bluetooth: {vendor} {name}",
            platform=sys.platform,
            details={
                "vendor": vendor,
                "name": name,
                "vid": hex(self._chip_info.vid) if self._chip_info else None,
                "pid": hex(self._chip_info.pid) if self._chip_info else None,
            },
        )

    async def _initialize(self) -> None:
        """Override in subclasses for firmware loading. Default: no-op."""
        logger.info("Generic USBTransport initialized")

    async def _send_hci_command(self, opcode: int, params: bytes = b"") -> bytes:
        """Send a standard HCI command and wait for its Command Complete event."""
        command = opcode.to_bytes(2, "little") + len(params).to_bytes(1, "little") + params
        await self._control_out(command)
        return await self._wait_for_event()

    async def _send_hci_reset(self) -> bytes:
        """Send HCI_Reset and return the raw Command Complete event."""
        return await self._send_hci_command((0x03 << 10) | 0x03)

    @staticmethod
    def _command_complete_status(event: bytes, opcode: int) -> int | None:
        expected = opcode.to_bytes(2, "little")
        if len(event) >= 6 and event[0] == 0x0E and event[3:5] == expected:
            return event[5]
        return None

    async def _wait_for_event(self, timeout: float = 5.0) -> bytes:
        """Wait for HCI event via interrupt IN endpoint."""
        return await self.read_interrupt(size=255, timeout=timeout)

    async def _read_interrupt_loop(self) -> None:
        """Background task: read HCI events from Interrupt IN and push to sink."""
        while self._is_open:
            try:
                data = await self.read_interrupt(size=255, timeout=0.5)
                if self._sink is not None and data:
                    await self._sink.on_transport_data(b"\x04" + data)
            except asyncio.CancelledError:
                break
            except Exception:
                # Timeout or transient error — keep reading
                await asyncio.sleep(0.01)

    async def _read_bulk_loop(self) -> None:
        """Background task: read ACL data from Bulk IN and push to sink."""
        if self._ep_bulk_in is None:
            return
        loop = asyncio.get_event_loop()
        while self._is_open:
            try:
                data = await loop.run_in_executor(
                    None,
                    lambda: bytes(self._ep_bulk_in.read(1024, timeout=50)),
                )
                if self._sink is not None and data:
                    await self._sink.on_transport_data(b"\x02" + data)
            except asyncio.CancelledError:
                break
            except Exception:
                # Timeout or transient error — keep reading
                await asyncio.sleep(0.01)

    async def _control_out(self, data: bytes) -> None:
        """Send HCI command via USB control transfer (EP0, BT class request)."""
        # HCI Command via control transfer:
        # bmRequestType = 0x20 (Class | Interface | Host-to-Device)
        # bRequest      = 0x00
        # wValue        = 0x0000
        # wIndex        = 0x0000 (interface 0)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._device.ctrl_transfer(
                0x20,   # bmRequestType
                0x00,   # bRequest
                0x0000, # wValue
                0x0000, # wIndex
                data,
            ),
        )

    async def _bulk_out(self, data: bytes) -> None:
        """Send ACL data via USB bulk OUT endpoint."""
        if not hasattr(self, "_ep_bulk_out") or self._ep_bulk_out is None:
            raise RuntimeError("Bulk OUT endpoint not found (call open() first)")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._ep_bulk_out.write(data))

    async def _isoch_out(self, data: bytes) -> None:
        """Send SCO data via USB isochronous OUT endpoint.
        (Isochronous transfers not fully supported by libusb on Windows.)
        """
        raise NotImplementedError("Isochronous SCO transfers require OS-level access")

    def read_interrupt_sync(self, size: int = 64, timeout: int = 5000) -> bytes:
        """Blocking interrupt IN read (runs in executor thread)."""
        if not hasattr(self, "_ep_intr_in") or self._ep_intr_in is None:
            raise RuntimeError("Interrupt IN endpoint not found (call open() first)")
        data = self._ep_intr_in.read(size, timeout=timeout)
        return bytes(data)

    async def read_interrupt(self, size: int = 64, timeout: float = 5.0) -> bytes:
        """Async wrapper around interrupt IN read."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.read_interrupt_sync(size, int(timeout * 1000)),
        )

    def _verify_winusb_driver(self) -> None:
        """Windows: check device is bound to WinUSB, not Microsoft Bluetooth driver.

        On Windows, Intel BT devices bound to WinUSB are accessible via pyusb.
        If the device is still on bthusb.sys, pyusb will get Access Denied.
        We rely on pyusb raising USBError at open() time to surface this.
        """
