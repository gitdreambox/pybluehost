"""USB transport diagnostic helpers.

USBDeviceDiagnostics inspects a device that failed to open and produces
a structured report (driver state, endpoint availability, firmware health)
that the CLI uses to print actionable remediation steps.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from pybluehost.transport.usb.chips import ChipInfo

logger = logging.getLogger(__name__)

# Lazy import: pyusb is optional
try:
    import usb
    import usb.core
    import usb.util
except ImportError:
    usb = None  # type: ignore[assignment]


# --- 12 symbols below in source order ---


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


def _find_interrupt_in_endpoint(intf: Any) -> Any | None:
    # Import via parent module so that test patches on pybluehost.transport.usb.usb
    # are respected (the parent module re-exports this function and holds the mock).
    from pybluehost.transport.usb import usb as _usb  # noqa: PLC0415
    if _usb is None:
        return None
    try:
        return _usb.util.find_descriptor(
            intf,
            custom_match=lambda e: (
                _usb.util.endpoint_direction(e.bEndpointAddress) == _usb.util.ENDPOINT_IN
                and _usb.util.endpoint_type(e.bmAttributes) == _usb.util.ENDPOINT_TYPE_INTR
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

    # Deferred import to avoid circular dependency: IntelUSBTransport is in __init__.py
    from pybluehost.transport.usb import IntelUSBTransport  # noqa: PLC0415

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
