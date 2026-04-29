"""USB HCI transport: ChipInfo registry, USBTransport base, Intel/Realtek subclasses."""

from __future__ import annotations

import asyncio
import collections
import logging
import struct
import sys
from dataclasses import asdict, dataclass
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pybluehost.core.errors import USBAccessDeniedError
from pybluehost.transport.base import Transport, TransportInfo
from pybluehost.transport.firmware import FirmwareManager, FirmwarePolicy

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Lazy import: pyusb is optional
try:
    import usb
    import usb.core
    import usb.util
except ImportError:
    usb = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ChipInfo:
    """Describes a known Bluetooth USB chip: vendor, VID/PID, firmware pattern."""

    vendor: str
    name: str
    vid: int
    pid: int
    firmware_pattern: str
    transport_class: type | None  # filled after subclass definitions


@dataclass(frozen=True)
class DeviceCandidate:
    """One enumerated Bluetooth USB device with location metadata."""

    chip_info: ChipInfo
    bus: int
    address: int

    @property
    def vendor(self) -> str:
        return self.chip_info.vendor

    @property
    def name(self) -> str:
        return self.chip_info.name


class FailureType(Enum):
    DRIVER_CONFLICT = auto()
    NO_DEVICE = auto()
    FIRMWARE_STATE_BAD = auto()
    PERMISSION_DENIED = auto()
    UNKNOWN = auto()


class DriverType(Enum):
    WINUSB = "winusb"
    BTHUSB = "bthusb"
    UNKNOWN = "unknown"


@dataclass
class USBDiagnosticReport:
    failure_type: FailureType
    driver_type: DriverType | None
    device_name: str
    steps: list[str]
    manual_url: str | None


@dataclass(frozen=True)
class USBDeviceCheck:
    level: str
    name: str
    message: str

    @property
    def ok(self) -> bool:
        return self.level == "ok"


@dataclass(frozen=True)
class USBDeviceDiagnosis:
    device: Any
    chip_info: ChipInfo | None
    checks: list[USBDeviceCheck]

    @property
    def ok(self) -> bool:
        return all(check.level != "fail" for check in self.checks)


class USBDeviceDiagnostics:
    @classmethod
    def diagnose(cls, device: Any, errno: int, platform: str) -> USBDiagnosticReport:
        driver = cls._detect_driver(device, errno, platform)
        name = cls._device_name(device)

        if errno in (13, -12):
            if platform == "win32":
                if driver == DriverType.WINUSB:
                    return USBDiagnosticReport(
                        failure_type=FailureType.DRIVER_CONFLICT,
                        driver_type=driver,
                        device_name=name,
                        steps=[
                            "检查是否有其他程序占用了该 USB 设备",
                            "尝试停止 Windows Bluetooth 支持服务 (bthserv)",
                            "重新运行程序",
                        ],
                        manual_url=None,
                    )
                if driver == DriverType.BTHUSB:
                    return USBDiagnosticReport(
                        failure_type=FailureType.DRIVER_CONFLICT,
                        driver_type=driver,
                        device_name=name,
                        steps=[
                            f"检测到 {name} 由 Windows 蓝牙驱动 (bthusb.sys) 控制。",
                            "pyusb / libusb 无法访问该设备，需要替换为 WinUSB 驱动。",
                            "",
                            "方法 A: 使用 Zadig (https://zadig.akeo.ie/)",
                            "  1. 运行 Zadig",
                            '  2. 菜单 Options → List All Devices',
                            f'  3. 选择 "{name}"',
                            '  4. 点击 "Replace Driver" (选择 WinUSB)',
                            "  5. 重新运行程序",
                            "",
                            "方法 B: 设备管理器手动替换",
                            "  1. 打开设备管理器",
                            f'  2. 找到 "{name}" 设备',
                            "  3. 右键 → 更新驱动程序 → 浏览我的计算机 → 让我从列表中选择",
                            '  4. 选择 "WinUSB" 驱动',
                            "  5. 重新运行程序",
                            "",
                            "注意: 替换驱动后 Windows 内置蓝牙功能将不可用。",
                            "      恢复方法: 设备管理器中卸载设备，然后扫描硬件改动。",
                        ],
                        manual_url="https://zadig.akeo.ie/",
                    )
                return USBDiagnosticReport(
                    failure_type=FailureType.DRIVER_CONFLICT,
                    driver_type=driver,
                    device_name=name,
                    steps=[
                        f"无法访问 {name}。可能原因：",
                        "  1) 设备被其他程序占用",
                        "  2) 设备未绑定 WinUSB 驱动",
                        "",
                        "排查步骤：",
                        "  1. 检查是否有其他程序占用了该 USB 设备",
                        "  2. 尝试停止 Windows Bluetooth 支持服务 (bthserv)",
                        "  3. 重新运行程序",
                        "",
                        "如果以上无效，请替换为 WinUSB 驱动：",
                        "",
                        "方法 A: 使用 Zadig (https://zadig.akeo.ie/)",
                        "  1. 运行 Zadig",
                        '  2. 菜单 Options → List All Devices',
                        f'  3. 选择 "{name}"',
                        '  4. 点击 "Replace Driver" (选择 WinUSB)',
                        "  5. 重新运行程序",
                    ],
                    manual_url="https://zadig.akeo.ie/",
                )
            try:
                vid = int(device.idVendor)
                pid = int(device.idProduct)
                udev_line = (
                    f'  echo \'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{vid:04x}", '
                    f'ATTR{{idProduct}}=="{pid:04x}", MODE="0666"\' | sudo tee '
                    f"/etc/udev/rules.d/50-bluetooth.rules"
                )
            except Exception:
                udev_line = "  # 无法生成 udev 规则（缺少 idVendor/idProduct）"
            return USBDiagnosticReport(
                failure_type=FailureType.PERMISSION_DENIED,
                driver_type=driver,
                device_name=name,
                steps=[
                    "尝试使用 sudo 运行程序",
                    "或者添加 udev 规则允许当前用户访问该 USB 设备",
                    udev_line,
                    "  sudo udevadm control --reload-rules && sudo udevadm trigger",
                ],
                manual_url=None,
            )

        if errno == 2:
            return USBDiagnosticReport(
                failure_type=FailureType.NO_DEVICE,
                driver_type=None,
                device_name=name,
                steps=[
                    "检查 USB 设备是否已插入",
                    "尝试更换 USB 端口",
                    "检查设备管理器中是否识别到该设备",
                ],
                manual_url=None,
            )

        return USBDiagnosticReport(
            failure_type=FailureType.UNKNOWN,
            driver_type=driver,
            device_name=name,
            steps=[
                f"USB 错误 (errno={errno})，请查看详细日志",
                "尝试重新插拔设备",
                "检查驱动是否正确安装",
            ],
            manual_url=None,
        )

    @classmethod
    def _detect_driver(cls, device: Any, errno: int, platform: str) -> DriverType:
        if platform != "win32":
            return DriverType.UNKNOWN
        try:
            vid = int(device.idVendor)
            if vid == 0x8087:
                return DriverType.BTHUSB
        except Exception:
            pass
        if errno == -12:
            return DriverType.BTHUSB
        return DriverType.UNKNOWN

    @classmethod
    def _device_name(cls, device: Any) -> str:
        try:
            product = device.product
            if product:
                return str(product)
        except Exception:
            pass
        try:
            manufacturer = device.manufacturer
            if manufacturer:
                return str(manufacturer)
        except Exception:
            pass
        try:
            return f"USB Device {device.idVendor:04x}:{device.idProduct:04x}"
        except Exception:
            return "Unknown USB Device"


class NoBluetoothDeviceError(RuntimeError):
    """No supported Bluetooth USB device was found."""


class WinUSBDriverError(RuntimeError):
    """Device is not bound to WinUSB driver (Windows)."""


def known_chip_for(dev: Any) -> ChipInfo | None:
    return next(
        (c for c in KNOWN_CHIPS if c.vid == dev.idVendor and c.pid == dev.idProduct),
        None,
    )


def usb_class_tuple(obj: Any, prefix: str) -> tuple[int, int, int]:
    return (
        int(getattr(obj, f"{prefix}Class", 0) or 0),
        int(getattr(obj, f"{prefix}SubClass", 0) or 0),
        int(getattr(obj, f"{prefix}Protocol", 0) or 0),
    )


def is_bluetooth_usb_class(values: tuple[int, int, int]) -> bool:
    return values == (0xE0, 0x01, 0x01)


def iter_usb_interfaces(dev: Any) -> list[Any]:
    interfaces: list[Any] = []
    try:
        for cfg in dev:
            for intf in cfg:
                interfaces.append(intf)
    except Exception:
        pass
    try:
        cfg = dev.get_active_configuration()
        interfaces.append(cfg[(0, 0)])
    except Exception:
        pass
    return interfaces


def is_bluetooth_usb_device(dev: Any) -> bool:
    if known_chip_for(dev) is not None:
        return True
    if is_bluetooth_usb_class(usb_class_tuple(dev, "bDevice")):
        return True
    for intf in iter_usb_interfaces(dev):
        if is_bluetooth_usb_class(usb_class_tuple(intf, "bInterface")):
            return True
    return False


def format_usb_class(values: tuple[int, int, int]) -> str:
    cls, sub, proto = values
    class_names = {
        0x00: "Device",
        0x09: "Hub",
        0xE0: "Wireless Controller",
    }
    return f"{class_names.get(cls, 'Unknown')} ({cls:02x}:{sub:02x}:{proto:02x})"


def _descriptor_string(dev: Any, attr: str) -> str | None:
    try:
        value = getattr(dev, attr)
        if value:
            return str(value)
    except Exception:
        pass
    return None


def get_usb_endpoints(dev: Any) -> list[dict[str, str]]:
    """Extract endpoint info from USB HCI interface 0."""
    endpoints = []
    if usb is None:
        return endpoints
    try:
        try:
            dev.set_configuration()
        except Exception:
            pass
        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]
        for ep in intf:
            direction = (
                "IN"
                if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN
                else "OUT"
            )
            ep_type_val = usb.util.endpoint_type(ep.bmAttributes)
            type_names = {0: "Control", 1: "Isochronous", 2: "Bulk", 3: "Interrupt"}
            endpoints.append(
                {
                    "address": f"0x{ep.bEndpointAddress:02x}",
                    "type": type_names.get(ep_type_val, "Unknown"),
                    "direction": direction,
                }
            )
    except Exception:
        pass
    return endpoints


def _bumble_transport_names(dev: Any, occurrence: int | None = None) -> list[str]:
    vid_pid = f"{int(dev.idVendor):04X}:{int(dev.idProduct):04X}"
    base = f"usb:{vid_pid}"
    serial = _descriptor_string(dev, "serial_number")
    if serial:
        return [base, f"{base}/{serial}"]
    if occurrence and occurrence > 1:
        return [f"{base}#{occurrence}"]
    return [base]


def parse_hci_reset_status(event: bytes) -> int | None:
    if len(event) >= 6 and event[0] == 0x0E and event[3:5] == bytes.fromhex("03 0c"):
        return event[5]
    return None


def _find_interrupt_in_endpoint(intf: Any) -> Any | None:
    if usb is None:
        return None
    try:
        return usb.util.find_descriptor(
            intf,
            custom_match=lambda e: (
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
                and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_INTR
            ),
        )
    except Exception:
        return None


def _diagnostic_report_checks(report: USBDiagnosticReport) -> list[USBDeviceCheck]:
    checks = [
        USBDeviceCheck("info", "access error diagnosis", report.failure_type.name),
    ]
    if report.driver_type:
        checks.append(USBDeviceCheck("info", "driver", report.driver_type.value))
    for step in report.steps:
        if step:
            checks.append(USBDeviceCheck("info", "next step", step))
    if report.manual_url:
        checks.append(USBDeviceCheck("info", "reference", report.manual_url))
    return checks


def _flush_interrupt_endpoint(ep_intr: Any) -> None:
    for _ in range(8):
        try:
            ep_intr.read(255, timeout=50)
        except Exception:
            break


def _send_hci_command_direct(dev: Any, ep_intr: Any, opcode: int, params: bytes = b"") -> bytes:
    command = opcode.to_bytes(2, "little") + len(params).to_bytes(1, "little") + params
    dev.ctrl_transfer(0x20, 0x00, 0x0000, 0x0000, command)
    return bytes(ep_intr.read(255, timeout=3000))


def _diagnose_intel_version_direct(dev: Any, ep_intr: Any) -> list[USBDeviceCheck]:
    checks: list[USBDeviceCheck] = []
    try:
        event = _send_hci_command_direct(dev, ep_intr, (0x3F << 10) | 0x05, b"\xff")
    except Exception as e:
        return [
            USBDeviceCheck(
                "warn",
                "Intel Read Version V2",
                f"{type(e).__name__}: {e}",
            )
        ]

    if len(event) < 6 or event[0] != 0x0E or event[3:5] != bytes.fromhex("05 fc"):
        return [
            USBDeviceCheck(
                "warn",
                "Intel Read Version V2",
                f"unexpected event: {event.hex(' ')}",
            )
        ]

    status = event[5]
    if status != 0:
        return [
            USBDeviceCheck(
                "warn",
                "Intel Read Version V2 status",
                f"0x{status:02X}; firmware load may be required",
            )
        ]

    tlv = IntelUSBTransport._parse_tlv(event[6:])
    if tlv:
        image_type = tlv.get(IntelUSBTransport._TLV_IMAGE_TYPE, b"\xff")[0]
        image_labels = {0x01: "BOOTLOADER", 0x03: "OPERATIONAL"}
        sbe_type_raw = tlv.get(IntelUSBTransport._TLV_SBE_TYPE)
        cnvi_top = int.from_bytes(
            tlv.get(IntelUSBTransport._TLV_CNVI_TOP, b"\0\0\0\0")[:4], "little"
        )
        cnvr_top = int.from_bytes(
            tlv.get(IntelUSBTransport._TLV_CNVR_TOP, b"\0\0\0\0")[:4], "little"
        )
        parts = [
            f"image={image_labels.get(image_type, f'0x{image_type:02X}')}",
            f"fw={IntelUSBTransport._compute_fw_name(cnvi_top, cnvr_top)}.sfi",
        ]
        if sbe_type_raw:
            parts.insert(1, f"sbe=0x{sbe_type_raw[0]:02X}")
        checks.append(
            USBDeviceCheck(
                "ok",
                "Intel Read Version V2",
                " ".join(parts),
            )
        )
    else:
        checks.append(USBDeviceCheck("ok", "Intel Read Version V2", event.hex(" ")))
    return checks


def _diagnose_realtek_version_direct(dev: Any, ep_intr: Any) -> list[USBDeviceCheck]:
    try:
        event = _send_hci_command_direct(dev, ep_intr, (0x3F << 10) | 0x6D)
    except Exception as e:
        return [
            USBDeviceCheck(
                "warn",
                "Realtek Read ROM Version",
                f"{type(e).__name__}: {e}",
            )
        ]
    if len(event) >= 7 and event[0] == 0x0E and event[3:5] == bytes.fromhex("6d fc"):
        status = event[5]
        if status == 0:
            return [
                USBDeviceCheck(
                    "ok",
                    "Realtek ROM Version",
                    f"0x{event[6]:02X}",
                )
            ]
        return [
            USBDeviceCheck(
                "warn",
                "Realtek Read ROM Version status",
                f"0x{status:02X}",
            )
        ]
    return [
        USBDeviceCheck(
            "warn",
            "Realtek Read ROM Version",
            f"unexpected event: {event.hex(' ')}",
        )
    ]


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
    ) -> "USBTransport":
        """Enumerate USB devices, match KNOWN_CHIPS, return correct subclass instance."""
        if usb is None:
            raise RuntimeError(
                "pyusb not installed. Run: pip install pyusb"
            )

        selected_vendor = vendor.lower() if vendor is not None else None
        if selected_vendor is not None and selected_vendor not in {"intel", "realtek", "csr"}:
            raise ValueError(
                "Unsupported USB vendor filter: "
                f"{vendor!r}. Expected one of: intel, realtek, csr."
            )

        backend = cls._get_usb_backend()
        chips = [
            chip for chip in KNOWN_CHIPS
            if selected_vendor is None or chip.vendor == selected_vendor
        ]

        # 1. Search known chips by VID/PID
        all_devices = list(usb.core.find(find_all=True, backend=backend))
        for dev in all_devices:
            if bus is not None and int(getattr(dev, "bus", 0) or 0) != bus:
                continue
            if address is not None and int(getattr(dev, "address", 0) or 0) != address:
                continue
            for chip in chips:
                if dev.idVendor == chip.vid and dev.idProduct == chip.pid:
                    transport_cls = chip.transport_class or cls
                    return transport_cls(
                        device=dev,
                        chip_info=chip,
                        firmware_policy=firmware_policy,
                    )

        # 2. Fallback: look for a generic Bluetooth USB device only when no vendor
        # filter is requested. A vendor-specific call should not silently return
        # a different adapter type.
        if selected_vendor is None and bus is None and address is None:
            bt_devices = list(
                usb.core.find(
                    find_all=True,
                    backend=backend,
                    bDeviceClass=0xE0,
                    bDeviceSubClass=0x01,
                    bDeviceProtocol=0x01,
                )
            )
            if bt_devices:
                dev = bt_devices[0]
                return cls(device=dev, firmware_policy=firmware_policy)

        target = f" {selected_vendor}" if selected_vendor is not None else ""
        loc = ""
        if bus is not None or address is not None:
            loc = f" at bus={bus} address={address}"
        raise NoBluetoothDeviceError(
            f"No supported{target} Bluetooth USB device found{loc}. "
            "Ensure your adapter is plugged in and (on Windows) has the WinUSB driver."
        )

    @classmethod
    def list_devices(cls) -> list[DeviceCandidate]:
        """Enumerate every plugged-in Bluetooth USB device known to KNOWN_CHIPS."""
        if usb is None:
            return []
        backend = cls._get_usb_backend()
        try:
            all_devices = list(usb.core.find(find_all=True, backend=backend))
        except Exception:
            return []

        result: list[DeviceCandidate] = []
        for dev in all_devices:
            for chip in KNOWN_CHIPS:
                if dev.idVendor == chip.vid and dev.idProduct == chip.pid:
                    result.append(
                        DeviceCandidate(
                            chip_info=chip,
                            bus=int(getattr(dev, "bus", 0) or 0),
                            address=int(getattr(dev, "address", 0) or 0),
                        )
                    )
                    break
        return result

    @classmethod
    def probe_devices(
        cls, verbose: bool = False, intel_tlv: bool = False
    ) -> list[dict[str, Any]]:
        """Enumerate Bluetooth USB devices, including unknown Bluetooth-class devices."""
        if usb is None:
            raise RuntimeError(
                "pyusb not installed. Run: pip install pyusb\n"
                "On Windows, also install: pip install libusb-package"
            )

        backend = cls._get_usb_backend()
        all_devices = list(usb.core.find(find_all=True, backend=backend))
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
        if usb is None:
            raise RuntimeError(
                "pyusb not installed. Run: pip install pyusb\n"
                "On Windows, also install: pip install libusb-package"
            )

        backend = cls._get_usb_backend()
        all_devices = list(usb.core.find(find_all=True, backend=backend))
        return [
            cls.diagnose_device(dev)
            for dev in all_devices
            if is_bluetooth_usb_device(dev)
        ]

    @classmethod
    def diagnose_device(cls, dev: Any) -> USBDeviceDiagnosis:
        """Check USB access, endpoint presence, HCI Reset send and reset event status."""
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
        except usb.core.USBError as e:
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
            usb.util.release_interface(dev, 0)
        except Exception:
            pass
        try:
            usb.util.dispose_resources(dev)
        except Exception:
            pass
        return USBDeviceDiagnosis(dev, chip, checks)

    @staticmethod
    def _probe_intel_tlv(dev: Any) -> dict[str, Any] | None:
        """Send Intel Read Version V2 and parse TLV response for probe output."""
        if usb is None:
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
                usb.util.release_interface(dev, 0)
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

        try:
            cfg = self._device.get_active_configuration()
        except (usb.core.USBError, NotImplementedError) as e:
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


class IntelUSBTransport(USBTransport):
    """Intel Bluetooth USB transport with firmware loading.

    Supports two protocols:
    - **Legacy** (hw_variant < 0x17): AX200, AX201, AC9560, AC8265, etc.
      Fixed-format Read Version, Enter Mfg Mode, Write Patch, Reset.
    - **New-gen** (hw_variant >= 0x17): AX210, AX211, BE200, etc.
      TLV-based Read Version V2, Secure Send firmware download, Reset with boot_param.
    """

    # Intel vendor command OCFs
    _INTEL_READ_VERSION = 0x05    # Read Version (legacy: no params; new-gen: param 0xFF)
    _INTEL_RESET = 0x01           # Intel Reset
    _INTEL_ENTER_MFG = 0x11      # Enter Manufacturer Mode (legacy only)
    _INTEL_SECURE_SEND = 0x09    # Secure Send (firmware download chunks)
    _INTEL_READ_BOOT_PARAMS = 0x0D  # Read Boot Params (legacy only)

    # Legacy firmware variant codes
    _FW_VARIANT_OPERATIONAL = 0x03
    _FW_VARIANT_BOOTLOADER = 0x06
    _FW_VARIANT_OPERATIONAL_NEW = 0x89   # operational on new platforms

    # Platform detection
    _HW_VARIANT_NEW_PLATFORM_MIN = 0x17  # hw_variant >= this → new-gen

    # New-gen image types (from TLV field 0x1C)
    _IMAGE_TYPE_BOOTLOADER = 0x01
    _IMAGE_TYPE_OPERATIONAL = 0x03

    # TLV type codes for new-gen Read Version V2
    _TLV_CNVI_TOP = 0x10
    _TLV_CNVR_TOP = 0x11
    _TLV_CNVI_BT = 0x12
    _TLV_DEV_REV_ID = 0x16
    _TLV_USB_VENDOR_ID = 0x17
    _TLV_USB_PRODUCT_ID = 0x18
    _TLV_IMAGE_TYPE = 0x1C
    _TLV_TIME_STAMP = 0x1D
    _TLV_BUILD_TYPE = 0x1E
    _TLV_BUILD_NUM = 0x1F
    _TLV_SECURE_BOOT = 0x27
    _TLV_OTP_LOCK = 0x28
    _TLV_API_LOCK = 0x29
    _TLV_DEBUG_LOCK = 0x2A
    _TLV_MIN_FW = 0x2B
    _TLV_FW_BUILD = 0x2D
    _TLV_SBE_TYPE = 0x2F       # SecureBootEngineType: 0x00=RSA, 0x01=ECDSA
    _TLV_OTP_BDADDR = 0x30
    _TLV_UNLOCKED_STATE = 0x31

    # Secure Boot Engine types
    _SBE_RSA = 0x00
    _SBE_ECDSA = 0x01

    # Boot params per engine type (from Bumble / Linux kernel)
    # BootParams(css_offset, css_size, pki_offset, pki_size,
    #            sig_offset, sig_size, write_offset)
    @dataclass(frozen=True)
    class _BootParams:
        css_offset: int
        css_size: int
        pki_offset: int
        pki_size: int
        sig_offset: int
        sig_size: int
        write_offset: int

    _BOOT_PARAMS_RSA = _BootParams(0, 128, 128, 256, 388, 256, 964)
    _BOOT_PARAMS_ECDSA = _BootParams(644, 128, 772, 96, 868, 96, 964)

    async def _initialize(self) -> None:
        """Intel firmware loading — auto-detects legacy vs new-gen platform.

        Tries V2 (TLV) Read Version first. If it succeeds with status 0x00 and
        returns TLV data, routes to the new-gen path. Otherwise falls back to
        the legacy fixed-format protocol.
        """
        reset_status = await self._try_initial_hci_reset()
        if reset_status == 0x00:
            logger.info("Intel: initial HCI Reset status=0x00")
        elif reset_status is not None:
            logger.warning(
                "Intel: initial HCI Reset status=0x%02X; firmware recovery may be required",
                reset_status,
            )
        else:
            logger.warning("Intel: initial HCI Reset failed or returned no status")

        # Try V2 Read Version (new-gen: 0xFC05 with param 0xFF)
        try:
            v2_data = await self._send_intel_vendor_cmd(
                self._INTEL_READ_VERSION, b"\xff"
            )
            v2_status = v2_data[5] if len(v2_data) > 5 else 0xFF
        except Exception:
            v2_status = 0xFF
            v2_data = b""

        if v2_status == 0x00 and len(v2_data) > 10:
            # New-gen platform: TLV response
            tlv = self._parse_tlv(v2_data[6:])
            logger.info("Intel new-gen platform detected (TLV response)")
            await self._initialize_newgen(tlv)
        else:
            # Legacy platform: fixed-format
            version_data = await self._send_intel_vendor_cmd(self._INTEL_READ_VERSION)
            hw_variant = self._parse_hw_variant(version_data)
            fw_variant = self._parse_fw_variant(version_data)
            logger.info(
                "Intel legacy platform: hw_variant=0x%02X fw_variant=0x%02X",
                hw_variant, fw_variant,
            )
            await self._initialize_legacy(hw_variant, fw_variant, version_data)

    async def _try_initial_hci_reset(self) -> int | None:
        try:
            event = await self._send_hci_reset()
        except Exception as e:
            logger.warning("Intel: initial HCI Reset command failed: %s: %s", type(e).__name__, e)
            return None
        return self._command_complete_status(event, (0x03 << 10) | 0x03)

    # ── New-gen initialization (BE200, AX210, AX211, etc.) ──────────────

    async def _initialize_newgen(self, tlv: dict[int, bytes]) -> None:
        """New-gen (TLV) firmware loading sequence (Bumble-compatible).

        1. Parse TLV: image_type, sbe_type, cnvi/cnvr
        2. If operational → done
        3. If bootloader → determine boot params (RSA/ECDSA),
           send CSS + PKI + Signature + payload, reset
        """
        image_type = tlv.get(self._TLV_IMAGE_TYPE, b"\xff")[0]
        cnvi_top = int.from_bytes(tlv.get(self._TLV_CNVI_TOP, b"\0\0\0\0")[:4], "little")
        cnvr_top = int.from_bytes(tlv.get(self._TLV_CNVR_TOP, b"\0\0\0\0")[:4], "little")
        sbe_type = tlv.get(self._TLV_SBE_TYPE, b"\x00")[0]
        otp_bdaddr = tlv.get(self._TLV_OTP_BDADDR, b"")

        logger.info(
            "Intel TLV: image_type=0x%02X sbe_type=0x%02X "
            "cnvi_top=0x%08X cnvr_top=0x%08X bdaddr=%s",
            image_type, sbe_type, cnvi_top, cnvr_top,
            otp_bdaddr.hex(":") if otp_bdaddr else "N/A",
        )

        if image_type == self._IMAGE_TYPE_OPERATIONAL:
            logger.info("Intel: firmware already operational, skipping load")
            return

        if image_type != self._IMAGE_TYPE_BOOTLOADER:
            raise RuntimeError(
                f"Intel: unexpected image_type=0x{image_type:02X} "
                f"(expected 0x01=bootloader or 0x03=operational)"
            )

        # Select boot params based on Secure Boot Engine type
        if sbe_type == self._SBE_ECDSA:
            bp = self._BOOT_PARAMS_ECDSA
            logger.info("Intel: ECDSA secure boot engine")
        else:
            bp = self._BOOT_PARAMS_RSA
            logger.info("Intel: RSA secure boot engine")

        # Compute firmware filename
        fw_basename = self._compute_fw_name(cnvi_top, cnvr_top)
        logger.info("Intel: bootloader mode — firmware needed: %s.sfi", fw_basename)

        # Find and load firmware
        fw_path = self._find_firmware_by_name(f"{fw_basename}.sfi")
        fw_data = fw_path.read_bytes()
        logger.info("Intel: firmware file %s (%d bytes)", fw_path.name, len(fw_data))

        if len(fw_data) < bp.write_offset:
            raise RuntimeError(
                f"Intel: firmware too small ({len(fw_data)} bytes, "
                f"need at least {bp.write_offset})"
            )

        # Download firmware via secure_send
        boot_address = await self._secure_send_firmware(fw_data, bp)
        logger.info("Intel: firmware download complete, boot_address=0x%08X", boot_address)

        # Wait for firmware_load_complete vendor event (type=0x06)
        logger.info("Intel: waiting for firmware load complete event...")
        await self._wait_for_vendor_event(expected_type=0x06, timeout=10.0)
        logger.info("Intel: firmware load complete")

        # Send Intel Reset with boot_address
        await self._intel_reset_newgen(boot_address)

        # Wait for boot complete vendor event (type=0x02)
        logger.info("Intel: waiting for boot complete event...")
        await self._wait_for_vendor_event(expected_type=0x02, timeout=10.0)
        logger.info("Intel: boot complete — device is now operational")

    async def _secure_send_firmware(
        self, fw_data: bytes, bp: _BootParams
    ) -> int:
        """Download firmware via Intel Secure Send (0xFC09).

        Uses BootParams to determine offsets for CSS/PKI/Signature/payload,
        which differ between RSA and ECDSA secure boot engines.

        Returns:
            boot_address: 32-bit boot address for Intel Reset.
        """
        # 1. Send CSS header (type=0x00)
        css = fw_data[bp.css_offset:bp.css_offset + bp.css_size]
        logger.info(
            "Intel: sending CSS header (type=0x00, offset=%d, %dB)",
            bp.css_offset, bp.css_size,
        )
        await self._secure_send(0x00, css)

        # 2. Send PKI key (type=0x03)
        pki = fw_data[bp.pki_offset:bp.pki_offset + bp.pki_size]
        logger.info(
            "Intel: sending PKI (type=0x03, offset=%d, %dB)",
            bp.pki_offset, bp.pki_size,
        )
        await self._secure_send(0x03, pki)

        # 3. Send Signature (type=0x02)
        sig = fw_data[bp.sig_offset:bp.sig_offset + bp.sig_size]
        logger.info(
            "Intel: sending Signature (type=0x02, offset=%d, %dB)",
            bp.sig_offset, bp.sig_size,
        )
        await self._secure_send(0x02, sig)

        # 4. Send firmware payload (type=0x01), 4-byte aligned HCI command chunks
        boot_address = 0
        offset = bp.write_offset
        frag_size = 0
        total_sent = 0
        payload_total = len(fw_data) - bp.write_offset
        payload_fragments: list[tuple[int, bytes, int]] = []

        while offset + frag_size + 3 <= len(fw_data):
            cmd_opcode = int.from_bytes(
                fw_data[offset + frag_size:offset + frag_size + 2], "little"
            )
            cmd_plen = fw_data[offset + frag_size + 2]

            # Check for boot_address command (0xFC0E)
            if cmd_opcode == 0xFC0E and offset + frag_size + 7 <= len(fw_data):
                boot_address = int.from_bytes(
                    fw_data[offset + frag_size + 3:offset + frag_size + 7], "little"
                )
                logger.info(
                    "Intel: found boot_address=0x%08X at offset %d",
                    boot_address, offset + frag_size,
                )

            frag_size += 3 + cmd_plen

            # Send when fragment is 4-byte aligned
            if frag_size % 4 == 0:
                payload_fragments.append(
                    (offset, fw_data[offset:offset + frag_size], total_sent)
                )
                total_sent += frag_size
                offset += frag_size
                frag_size = 0

        # Send any remaining data
        if frag_size > 0:
            payload_fragments.append(
                (offset, fw_data[offset:offset + frag_size], total_sent)
            )
            total_sent += frag_size

        await self._secure_send_payload(payload_fragments, payload_total=payload_total)
        logger.info("Intel: payload sent (%d bytes total)", total_sent)
        return boot_address

    async def _secure_send_payload(
        self,
        fragments: list[tuple[int, bytes, int]],
        *,
        payload_total: int,
    ) -> None:
        commands: list[tuple[bytes, str]] = []
        progress_by_command_index: dict[int, int] = {}
        last_progress_log = 0
        for offset, data, total_sent in fragments:
            self._append_secure_send_commands(
                commands,
                0x01,
                data,
                context=(
                    f"payload offset={offset} size={len(data)} "
                    f"sent={total_sent}/{payload_total}"
                ),
                base_offset=offset,
            )
            progress = total_sent + len(data)
            if (
                last_progress_log == 0
                or progress - last_progress_log >= 64 * 1024
                or progress == payload_total
            ):
                progress_by_command_index[len(commands) - 1] = progress
                last_progress_log = progress
        await self._send_intel_secure_send_commands(
            commands,
            progress_by_command_index=progress_by_command_index,
            progress_total=payload_total,
        )

    async def _secure_send(
        self,
        fragment_type: int,
        data: bytes,
        *,
        context: str | None = None,
        base_offset: int | None = None,
    ) -> None:
        """Send data via Intel Secure Send (vendor 0xFC09), chunking at 252 bytes.

        Args:
            fragment_type: 0x00=CSS header, 0x01=data, 0x03=PKCS key
            data: Payload (chunked internally at 252-byte boundaries).
        """
        commands: list[tuple[bytes, str]] = []
        self._append_secure_send_commands(
            commands,
            fragment_type,
            data,
            context=context,
            base_offset=base_offset,
        )
        await self._send_intel_secure_send_commands(commands)

    def _append_secure_send_commands(
        self,
        commands: list[tuple[bytes, str]],
        fragment_type: int,
        data: bytes,
        *,
        context: str | None = None,
        base_offset: int | None = None,
    ) -> None:
        total = (len(data) + 251) // 252
        for i in range(0, len(data), 252):
            chunk = data[i:i + 252]
            params = bytes([fragment_type]) + chunk
            chunk_num = i // 252 + 1
            chunk_context = (
                f"secure_send type={fragment_type} chunk={chunk_num}/{total} "
                f"len={len(chunk)}"
            )
            if base_offset is not None:
                chunk_context += f" offset={base_offset + i}"
            if context:
                chunk_context = f"{context}; {chunk_context}"
            commands.append(
                (
                    self._build_intel_vendor_command(
                        self._INTEL_SECURE_SEND, params
                    ),
                    chunk_context,
                )
            )
            logger.debug(
                "Intel: secure_send type=%d chunk %d/%d", fragment_type, chunk_num, total
            )

    async def _send_intel_secure_send_commands(
        self,
        commands: list[tuple[bytes, str]],
        *,
        progress_by_command_index: dict[int, int] | None = None,
        progress_total: int | None = None,
        timeout: float = 5.0,
    ) -> None:
        if not commands:
            return

        max_in_flight = 1
        next_command = 0
        pending_contexts: collections.deque[str] = collections.deque()

        while next_command < len(commands):
            while next_command < len(commands) and len(pending_contexts) < max_in_flight:
                command_index = next_command
                command, context = commands[next_command]
                logger.debug(
                    "Intel: vendor cmd 0xFC09 (%s) send in_flight=%d/%d",
                    context, len(pending_contexts) + 1, max_in_flight,
                )
                await self._control_out(command)
                if (
                    progress_by_command_index is not None
                    and progress_total is not None
                    and command_index in progress_by_command_index
                ):
                    logger.info(
                        "Intel: payload progress: %d/%d bytes",
                        progress_by_command_index[command_index],
                        progress_total,
                    )
                pending_contexts.append(context)
                next_command += 1

            if not pending_contexts or next_command >= len(commands):
                continue

            event = await self._wait_for_intel_firmware_command_complete(
                pending_contexts[0],
                timeout=timeout,
            )
            pending_contexts.popleft()
            num_packets = self._parse_command_complete_num_packets(
                event,
                expected_opcode=(0x3F << 10) | self._INTEL_SECURE_SEND,
            )
            if num_packets > 0:
                max_in_flight = max(1, num_packets)

    async def _wait_for_intel_firmware_command_complete(
        self,
        context: str,
        *,
        timeout: float = 5.0,
    ) -> bytes:
        label = f"vendor cmd 0xFC09 ({context})"
        while True:
            try:
                event = await self._wait_for_event_bulk_first(timeout=timeout)
            except TimeoutError:
                logger.info("Intel: %s timeout after %gs", label, timeout)
                raise
            except asyncio.CancelledError:
                logger.info("Intel: %s cancelled while waiting for Command Complete", label)
                raise

            if len(event) >= 3 and event[0] == 0xFF:
                self._defer_intel_vendor_event(event)
                continue
            break

        status = self._parse_command_complete_status(
            event,
            expected_opcode=(0x3F << 10) | self._INTEL_SECURE_SEND,
        )
        if status != 0:
            raise RuntimeError(f"Intel: {label} failed with status 0x{status:02X}")
        return event

    def _defer_intel_vendor_event(self, event: bytes) -> None:
        if not hasattr(self, "_deferred_intel_vendor_events"):
            self._deferred_intel_vendor_events: collections.deque[bytes] = (
                collections.deque()
            )
        self._deferred_intel_vendor_events.append(event)

    async def _wait_for_event_bulk_first(self, timeout: float = 5.0) -> bytes:
        if not hasattr(self, "_ep_bulk_in") or self._ep_bulk_in is None:
            return await self._wait_for_event(timeout=timeout)

        loop = asyncio.get_event_loop()
        timeout_ms = int(timeout * 1000)
        try:
            return await loop.run_in_executor(
                None,
                lambda: bytes(self._ep_bulk_in.read(1024, timeout=timeout_ms)),
            )
        except Exception:
            return await self._wait_for_event(timeout=timeout)

    @staticmethod
    def _parse_command_complete_num_packets(
        event: bytes,
        *,
        expected_opcode: int,
    ) -> int:
        if len(event) < 6 or event[0] != 0x0E:
            raise RuntimeError(f"Intel: expected Command Complete, got {event.hex(' ')}")
        opcode = int.from_bytes(event[3:5], "little")
        if opcode != expected_opcode:
            raise RuntimeError(
                "Intel: unexpected Command Complete opcode "
                f"0x{opcode:04X}, expected 0x{expected_opcode:04X}"
            )
        return event[2]

    @classmethod
    def _parse_command_complete_status(
        cls,
        event: bytes,
        *,
        expected_opcode: int,
    ) -> int:
        cls._parse_command_complete_num_packets(
            event,
            expected_opcode=expected_opcode,
        )
        return event[5]

    async def _wait_for_vendor_event(
        self, expected_type: int, timeout: float = 10.0
    ) -> bytes:
        """Wait for an Intel Vendor Specific Event (0xFF) with expected sub-type.

        Intel bootloader sends vendor events for:
        - type=0x02: boot complete
        - type=0x06: firmware download complete

        Events may arrive on either Interrupt IN or Bulk IN endpoint.
        """
        logger.info(
            "Intel: vendor event type=0x%02X wait start timeout=%gs",
            expected_type, timeout,
        )
        deferred_events = getattr(self, "_deferred_intel_vendor_events", None)
        if deferred_events is not None:
            for _ in range(len(deferred_events)):
                event = deferred_events.popleft()
                if len(event) >= 3 and event[0] == 0xFF and event[2] == expected_type:
                    return event
                deferred_events.append(event)

        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.info(
                    "Intel: vendor event type=0x%02X wait timeout after %gs",
                    expected_type, timeout,
                )
                raise TimeoutError(
                    f"Intel: vendor event type=0x{expected_type:02X} "
                    f"not received within {timeout}s"
                )
            try:
                event = await self._wait_for_event(timeout=min(remaining, 2.0))
            except (TimeoutError, Exception):
                continue

            if len(event) >= 3 and event[0] == 0xFF:
                event_type = event[2]
                logger.debug("Intel: vendor event type=0x%02X", event_type)
                if event_type == expected_type:
                    return event
            elif len(event) >= 1 and event[0] == 0x0E:
                # Command Complete — might be a leftover, skip
                logger.debug("Intel: skipping Command Complete during vendor event wait")

    async def _intel_reset_newgen(self, boot_address: int) -> None:
        """Send Intel Reset (0xFC01) with boot_address for new-gen platforms.

        The reset command is fire-and-forget (no Command Complete expected).
        The device will reboot and send a vendor event (type=0x02) when ready.
        """
        params = struct.pack("<BBBBI", 0x00, 0x01, 0x00, 0x01, boot_address)
        opcode = (0x3F << 10) | self._INTEL_RESET
        opcode_bytes = opcode.to_bytes(2, "little")
        param_len = len(params).to_bytes(1, "little")
        command = opcode_bytes + param_len + params
        await self._control_out(command)
        logger.info("Intel: reset command sent (boot_address=0x%08X)", boot_address)

    @staticmethod
    def _compute_fw_name(cnvi_top: int, cnvr_top: int) -> str:
        """Compute firmware basename from cnvi_top and cnvr_top values.

        Algorithm (from Linux kernel v6.12 btintel.h):
          INTEL_CNVX_TOP_TYPE(val)  = val & 0x00000FFF
          INTEL_CNVX_TOP_STEP(val)  = (val & 0x0F000000) >> 24
          INTEL_CNVX_TOP_PACK_SWAB(t, s) = __swab16((t) << 4 | s)

        Example: BE200 cnvi_top=0x02001910 → TYPE=0x910, STEP=2 → packed=0x0291
                 Firmware: ibt-0291-0291.sfi
        """
        def pack(val: int) -> int:
            t = val & 0x00000FFF          # bottom 12 bits
            s = (val & 0x0F000000) >> 24  # bits 24-27
            v = (t << 4) | s
            return ((v >> 8) & 0xFF) | ((v & 0xFF) << 8)  # swab16

        return f"ibt-{pack(cnvi_top):04x}-{pack(cnvr_top):04x}"

    @staticmethod
    def _parse_tlv(data: bytes) -> dict[int, bytes]:
        """Parse TLV (Type-Length-Value) entries from Intel Read Version V2 response."""
        tlv: dict[int, bytes] = {}
        pos = 0
        while pos + 2 <= len(data):
            tlv_type = data[pos]
            tlv_len = data[pos + 1]
            if pos + 2 + tlv_len > len(data):
                break
            tlv[tlv_type] = data[pos + 2 : pos + 2 + tlv_len]
            pos += 2 + tlv_len
        return tlv

    # ── Legacy initialization (AX200, AX201, AC9560, AC8265, etc.) ─────

    async def _initialize_legacy(
        self, hw_variant: int, fw_variant: int, version_data: bytes
    ) -> None:
        """Legacy firmware loading sequence.

        1. Check if already operational → skip
        2. Find firmware file
        3. Enter Manufacturer Mode (0xFC11)
        4. Stream firmware in ≤252-byte chunks via 0xFC09
        5. Intel Reset (0xFC01)
        6. Re-read version to verify
        """
        if self._is_operational(hw_variant, fw_variant):
            logger.info("Intel legacy: already operational, skipping")
            return

        logger.info("Intel legacy: bootloader mode, loading firmware")

        # Find firmware
        fw_path = self._find_firmware()
        fw_data = fw_path.read_bytes()

        # Enter Manufacturer Mode
        await self._send_intel_vendor_cmd(self._INTEL_ENTER_MFG)

        # Stream firmware in chunks
        for chunk in self._split_firmware(fw_data):
            await self._send_intel_vendor_cmd(self._INTEL_SECURE_SEND, chunk)

        # Intel Reset
        await self._send_intel_vendor_cmd(self._INTEL_RESET)

        # Verify
        version_data = await self._send_intel_vendor_cmd(self._INTEL_READ_VERSION)
        fw_variant = self._parse_fw_variant(version_data)
        if not self._is_operational(hw_variant, fw_variant):
            raise RuntimeError(
                f"Intel firmware load failed: fw_variant=0x{fw_variant:02X}, "
                f"expected operational variant for hw_variant=0x{hw_variant:02X}"
            )

    # ── Shared helpers ──────────────────────────────────────────────────

    @staticmethod
    def _build_intel_vendor_command(ocf: int, params: bytes = b"") -> bytes:
        opcode = (0x3F << 10) | ocf
        return opcode.to_bytes(2, "little") + len(params).to_bytes(1, "little") + params

    async def _send_intel_vendor_cmd(
        self,
        ocf: int,
        params: bytes = b"",
        *,
        context: str | None = None,
        timeout: float = 5.0,
    ) -> bytes:
        """Send Intel vendor command (OGF=0x3F) and await Command Complete Event."""
        opcode = (0x3F << 10) | ocf
        command = self._build_intel_vendor_command(ocf, params)
        label = f"vendor cmd 0x{opcode:04X}"
        if context:
            label = f"{label} ({context})"
        is_payload_fragment = bool(context and context.startswith("payload offset="))
        wait_logger = logger.debug if is_payload_fragment else logger.info
        wait_logger("Intel: %s waiting for Command Complete timeout=%gs", label, timeout)
        await self._control_out(command)
        try:
            event = await self._wait_for_event(timeout=timeout)
        except TimeoutError:
            logger.info("Intel: %s timeout after %gs", label, timeout)
            raise
        except asyncio.CancelledError:
            logger.info("Intel: %s cancelled while waiting for Command Complete", label)
            raise
        logger.debug("Intel: %s complete", label)
        return event

    def _parse_fw_variant(self, event_data: bytes) -> int:
        """Extract fw_variant from legacy HCI_Intel_Read_Version response.

        Response layout (Command Complete, 0x0E):
          [0]  event_code
          [1]  param_total_len
          [2]  num_hci_cmds
          [3,4] opcode (little-endian)
          [5]  status
          [6]  hw_platform
          [7]  hw_variant
          [8]  hw_revision
          [9]  fw_variant
        """
        if len(event_data) >= 10:
            return event_data[9]
        return 0xFF

    def _parse_hw_variant(self, event_data: bytes) -> int:
        """Extract hw_variant from legacy HCI_Intel_Read_Version response at [7]."""
        if len(event_data) >= 8:
            return event_data[7]
        return 0xFF

    def _is_operational(self, hw_variant: int, fw_variant: int) -> bool:
        """Return True if device is operational (legacy protocol)."""
        if hw_variant >= self._HW_VARIANT_NEW_PLATFORM_MIN:
            return fw_variant == self._FW_VARIANT_OPERATIONAL_NEW
        return fw_variant == self._FW_VARIANT_OPERATIONAL

    def _find_firmware(self) -> Path:
        """Locate Intel firmware file using FirmwareManager (legacy: glob pattern)."""
        mgr = FirmwareManager(
            vendor="intel",
            extra_dirs=self._extra_fw_dirs,
            policy=self._firmware_policy,
        )
        pattern = self._chip_info.firmware_pattern if self._chip_info else "ibt-*"
        for search_dir in mgr._search_dirs():
            matches = sorted(search_dir.glob(pattern))
            if matches:
                return matches[0]
        return mgr.find(pattern)

    def _find_firmware_by_name(self, filename: str) -> Path:
        """Locate firmware file by exact name (new-gen: computed from TLV)."""
        mgr = FirmwareManager(
            vendor="intel",
            extra_dirs=self._extra_fw_dirs,
            policy=self._firmware_policy,
        )
        return mgr.find(filename)

    @staticmethod
    def _split_firmware(data: bytes, chunk_size: int = 252) -> list[bytes]:
        """Split firmware binary into chunks of ≤chunk_size bytes."""
        return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]

    async def _wait_for_event(self, timeout: float = 5.0) -> bytes:
        """Wait for HCI event from either Interrupt IN or Bulk IN endpoint.

        Intel bootloaders deliver Command Complete events via the Bulk IN
        endpoint during firmware download. We try interrupt first with a very
        short timeout (50ms), then bulk IN for the remaining time.
        """
        loop = asyncio.get_event_loop()
        timeout_ms = int(timeout * 1000)

        # Quick check on interrupt IN (standard HCI event path, 50ms)
        try:
            data = await loop.run_in_executor(
                None,
                lambda: self.read_interrupt_sync(255, 50),
            )
            return data
        except Exception:
            pass

        # Then try bulk IN (Intel bootloader firmware loading path)
        if hasattr(self, "_ep_bulk_in") and self._ep_bulk_in is not None:
            try:
                data = await loop.run_in_executor(
                    None,
                    lambda: bytes(self._ep_bulk_in.read(1024, timeout=timeout_ms)),
                )
                return data
            except Exception:
                pass

        # Final attempt: interrupt IN with full timeout
        try:
            data = await loop.run_in_executor(
                None,
                lambda: self.read_interrupt_sync(255, timeout_ms),
            )
            return data
        except Exception:
            pass

        raise TimeoutError(
            f"No HCI event received within {timeout}s on either Interrupt or Bulk IN"
        )


class RealtekUSBTransport(USBTransport):
    """Realtek Bluetooth USB transport with firmware loading.

    Realtek firmware loading sequence:
    1. HCI_Realtek_Read_ROM_Version (vendor 0xFC6D) → lmp_subversion, rom_version
    2. Check if firmware download is needed
    3. Find firmware + optional config files via FirmwareManager
    4. Download firmware in ≤252-byte chunks (vendor cmd 0xFC20)
    5. HCI_Reset → verify
    """

    # Realtek vendor command OCFs
    _RTK_READ_ROM_VERSION = 0x6D
    _RTK_DOWNLOAD_FW = 0x20

    async def _initialize(self) -> None:
        """Realtek 5-step firmware loading sequence."""
        reset_status = await self._try_initial_hci_reset()
        if reset_status == 0x00:
            logger.info("Realtek: initial HCI Reset status=0x00")
        elif reset_status is not None:
            logger.warning(
                "Realtek: initial HCI Reset status=0x%02X; firmware recovery may be required",
                reset_status,
            )
        else:
            logger.warning("Realtek: initial HCI Reset failed or returned no status")

        # Step 1: Read ROM Version
        rom_data = await self._send_realtek_vendor_cmd(self._RTK_READ_ROM_VERSION)
        rom_version = self._parse_rom_version(rom_data)
        logger.info("Realtek: ROM version=0x%02X", rom_version)

        # Step 2: Check if firmware download is needed
        if not self._needs_firmware_download(rom_version):
            return

        # Step 3: Find firmware file
        fw_path = self._find_firmware()

        # Step 4: Download firmware in chunks
        fw_data = fw_path.read_bytes()
        chunks = self._split_firmware(fw_data)
        for i, chunk in enumerate(chunks):
            # Realtek download command includes chunk index
            index_byte = i.to_bytes(1, "little") if i < 256 else b"\xff"
            await self._send_realtek_vendor_cmd(
                self._RTK_DOWNLOAD_FW, index_byte + chunk
            )

        # Step 5: HCI Reset to activate firmware
        await self._send_hci_reset()

    async def _try_initial_hci_reset(self) -> int | None:
        try:
            event = await self._send_hci_reset()
        except Exception as e:
            logger.warning("Realtek: initial HCI Reset command failed: %s: %s", type(e).__name__, e)
            return None
        return self._command_complete_status(event, (0x03 << 10) | 0x03)

    async def _send_realtek_vendor_cmd(
        self, ocf: int, params: bytes = b""
    ) -> bytes:
        """Send Realtek vendor command (OGF=0x3F) and await Command Complete Event."""
        opcode = (0x3F << 10) | ocf
        opcode_bytes = opcode.to_bytes(2, "little")
        param_len = len(params).to_bytes(1, "little")
        command = opcode_bytes + param_len + params
        await self._control_out(command)
        return await self._wait_for_event()

    def _parse_rom_version(self, event_data: bytes) -> int:
        """Extract ROM version from Realtek Read ROM Version response."""
        # Event: event_code(1) + param_len(1) + num_hci_cmds(1) +
        #        opcode(2) + status(1) + rom_version(1)
        if len(event_data) >= 7:
            return event_data[6]
        return 0xFF

    def _needs_firmware_download(self, rom_version: int = 0) -> bool:
        """Determine if firmware download is needed based on ROM version."""
        # In practice, most Realtek chips always need firmware download
        # after power cycle. Override in tests.
        return True

    def _find_firmware(self) -> "Path":
        """Locate Realtek firmware file using FirmwareManager."""
        mgr = FirmwareManager(
            vendor="realtek",
            extra_dirs=self._extra_fw_dirs,
            policy=self._firmware_policy,
        )
        fw_name = self._chip_info.firmware_pattern if self._chip_info else "rtl_fw"
        return mgr.find(fw_name)

    @staticmethod
    def _split_firmware(data: bytes, chunk_size: int = 252) -> list[bytes]:
        """Split firmware binary into chunks of ≤chunk_size bytes."""
        return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]

    async def _wait_for_event(self, timeout: float = 5.0) -> bytes:
        """Wait for HCI event via interrupt IN endpoint."""
        return await self.read_interrupt(size=64, timeout=timeout)


class CSRUSBTransport(USBTransport):
    """CSR Bluetooth USB transport.

    CSR8510 currently follows the standard Bluetooth USB HCI path, so it can
    use the base USB transport behavior without vendor-specific initialization.
    """


# --- Known Bluetooth USB chips registry ---
# Transport class references are resolved here after subclass definitions.

KNOWN_CHIPS: list[ChipInfo] = [
    # Intel
    ChipInfo("intel", "AX200",  0x8087, 0x0029, "ibt-20-*",    IntelUSBTransport),
    ChipInfo("intel", "AX201",  0x8087, 0x0026, "ibt-20-*",    IntelUSBTransport),
    ChipInfo("intel", "AX210",  0x8087, 0x0032, "ibt-0040-*",  IntelUSBTransport),
    ChipInfo("intel", "AX211",  0x8087, 0x0033, "ibt-0040-*",  IntelUSBTransport),
    ChipInfo("intel", "AC9560", 0x8087, 0x0025, "ibt-18-*",    IntelUSBTransport),
    ChipInfo("intel", "AC8265", 0x8087, 0x0A2B, "ibt-12-*",    IntelUSBTransport),
    ChipInfo("intel", "BE200",  0x8087, 0x0036, "ibt-0040-*",  IntelUSBTransport),  # WiFi 7 / BT 5.4
    # Realtek
    ChipInfo("realtek", "RTL8761B", 0x0BDA, 0x8771, "rtl8761b_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852AE", 0x0BDA, 0x2852, "rtl8852au_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852BE", 0x0BDA, 0x887B, "rtl8852bu_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852CE", 0x0BDA, 0x4853, "rtl8852cu_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8723DE", 0x0BDA, 0xB009, "rtl8723d_fw", RealtekUSBTransport),
    # CSR
    ChipInfo("csr", "CSR8510", 0x0A12, 0x0001, "", CSRUSBTransport),
]
