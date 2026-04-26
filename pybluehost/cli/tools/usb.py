"""USB device probe CLI: enumerate and inspect Bluetooth USB controllers."""

from __future__ import annotations

import argparse
import sys
from typing import Any

try:
    import usb.core
    import usb.util
except ImportError:
    usb = None  # type: ignore[assignment]


def register_usb_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register 'usb' subcommand group."""
    usb_parser = subparsers.add_parser("usb", help="USB Bluetooth device tools")
    usb_sub = usb_parser.add_subparsers(dest="usb_command")

    # usb probe
    probe_parser = usb_sub.add_parser(
        "probe", help="Enumerate and inspect USB Bluetooth devices"
    )
    probe_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show USB endpoint details"
    )
    probe_parser.add_argument(
        "--intel-tlv", action="store_true",
        help="Read Intel TLV version data (sends HCI command to device)",
    )
    probe_parser.set_defaults(func=_cmd_usb_probe)

    # usb diagnose
    diag_parser = usb_sub.add_parser(
        "diagnose", help="Diagnose USB Bluetooth device accessibility issues"
    )
    diag_parser.set_defaults(func=_cmd_usb_diagnose)

    usb_parser.set_defaults(func=lambda args: usb_parser.print_help() or 0)


def probe_usb_devices(
    verbose: bool = False, intel_tlv: bool = False
) -> list[dict[str, Any]]:
    """Enumerate USB Bluetooth devices and return info dicts.

    Args:
        verbose: Include endpoint info.
        intel_tlv: For Intel new-gen devices, send Read Version V2 to get TLV data.

    Returns:
        List of device info dicts.

    Raises:
        RuntimeError: If pyusb is not installed.
    """
    if usb is None:
        raise RuntimeError(
            "pyusb not installed. Run: pip install pyusb\n"
            "On Windows, also install: pip install libusb-package"
        )

    from pybluehost.transport.usb import (
        KNOWN_CHIPS,
        IntelUSBTransport,
        USBTransport,
    )

    backend = USBTransport._get_usb_backend()
    all_devices = list(usb.core.find(find_all=True, backend=backend))

    results: list[dict[str, Any]] = []
    index = 0

    for dev in all_devices:
        # Match against KNOWN_CHIPS
        chip = next(
            (c for c in KNOWN_CHIPS if c.vid == dev.idVendor and c.pid == dev.idProduct),
            None,
        )

        # If not in known list, check BT device class
        if chip is None:
            if (
                getattr(dev, "bDeviceClass", 0) == 0xE0
                and getattr(dev, "bDeviceSubClass", 0) == 0x01
                and getattr(dev, "bDeviceProtocol", 0) == 0x01
            ):
                pass  # Unknown BT device, include it
            else:
                continue  # Not a Bluetooth device

        index += 1
        info: dict[str, Any] = {
            "index": index,
            "vid": dev.idVendor,
            "pid": dev.idProduct,
            "vid_pid": f"{dev.idVendor:04x}:{dev.idProduct:04x}",
            "vendor": chip.vendor if chip else "unknown",
            "chip_name": chip.name if chip else "Unknown BT Device",
            "bus": getattr(dev, "bus", None),
            "address": getattr(dev, "address", None),
            "device_class": f"{getattr(dev, 'bDeviceClass', 0):02x}:"
                           f"{getattr(dev, 'bDeviceSubClass', 0):02x}:"
                           f"{getattr(dev, 'bDeviceProtocol', 0):02x}",
        }

        # Endpoint info
        if verbose:
            info["endpoints"] = _get_endpoints(dev)

        # Intel TLV probe
        if intel_tlv and chip and chip.vendor == "intel":
            tlv_info = _probe_intel_tlv(dev)
            if tlv_info:
                info.update(tlv_info)

        results.append(info)

    return results


def _get_endpoints(dev: Any) -> list[dict[str, str]]:
    """Extract endpoint info from USB device."""
    endpoints = []
    try:
        try:
            dev.set_configuration()
        except Exception:
            pass
        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]
        for ep in intf:
            direction = "IN" if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN else "OUT"
            ep_type_val = usb.util.endpoint_type(ep.bmAttributes)
            type_names = {0: "Control", 1: "Isochronous", 2: "Bulk", 3: "Interrupt"}
            ep_type = type_names.get(ep_type_val, "Unknown")
            endpoints.append({
                "address": f"0x{ep.bEndpointAddress:02x}",
                "type": ep_type,
                "direction": direction,
            })
    except Exception:
        pass
    return endpoints


def _probe_intel_tlv(dev: Any) -> dict[str, Any] | None:
    """Send Intel Read Version V2 and parse TLV response."""
    from pybluehost.transport.usb import IntelUSBTransport

    try:
        try:
            dev.set_configuration()
        except Exception:
            pass
        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]

        ep_intr = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: (
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
                and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_INTR
            ),
        )
        if ep_intr is None:
            return None

        # Flush stale events
        for _ in range(8):
            try:
                ep_intr.read(255, timeout=50)
            except Exception:
                break

        # Send Read Version V2: 0xFC05 with param 0xFF
        opcode = ((0x3F << 10) | 0x05).to_bytes(2, "little")
        cmd = opcode + b"\x01\xff"
        dev.ctrl_transfer(0x20, 0x00, 0x0000, 0x0000, cmd)

        resp = bytes(ep_intr.read(255, timeout=3000))

        if len(resp) < 7 or resp[0] != 0x0E or resp[5] != 0x00:
            return None

        tlv = IntelUSBTransport._parse_tlv(resp[6:])
        if not tlv:
            return None

        # Extract fields
        image_type = tlv.get(IntelUSBTransport._TLV_IMAGE_TYPE, b"\xff")[0]
        sbe_raw = tlv.get(IntelUSBTransport._TLV_SBE_TYPE, b"\xff")[0]
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
        bdaddr_str = ":".join(f"{b:02X}" for b in reversed(bdaddr_raw)) if len(bdaddr_raw) == 6 else None

        result: dict[str, Any] = {
            "image_type": image_type,
            "image_type_str": image_labels.get(image_type, f"0x{image_type:02X}"),
            "sbe_type": sbe_raw,
            "sbe_type_str": sbe_labels.get(sbe_raw, f"0x{sbe_raw:02X}"),
            "fw_name": f"{fw_name}.sfi",
            "cnvi_top": f"0x{cnvi_top:08X}",
            "cnvr_top": f"0x{cnvr_top:08X}",
            "cnvi_bt": f"0x{cnvi_bt:08X}",
        }
        if bdaddr_str:
            result["bd_addr"] = bdaddr_str

        usb.util.release_interface(dev, 0)
        return result

    except Exception:
        try:
            usb.util.release_interface(dev, 0)
        except Exception:
            pass
        return None


def _cmd_usb_probe(args: argparse.Namespace) -> int:
    """Handle 'usb probe' command."""
    try:
        devices = probe_usb_devices(
            verbose=args.verbose,
            intel_tlv=args.intel_tlv,
        )
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not devices:
        print("No USB Bluetooth devices found.")
        return 0

    print(f"Found {len(devices)} USB Bluetooth device(s):\n")

    for dev in devices:
        print(f"  [{dev['index']}] {dev['vid_pid']}  {dev['vendor']} {dev['chip_name']}")
        print(f"      Bus {dev['bus']:03d} Address {dev['address']:03d}  Class {dev['device_class']}")

        if args.verbose and dev.get("endpoints"):
            print("      Endpoints:")
            for ep in dev["endpoints"]:
                print(f"        EP {ep['address']}  {ep['type']} {ep['direction']}")

        if args.intel_tlv and dev.get("image_type") is not None:
            print(
                f"      Mode: {dev['image_type_str']}   "
                f"SBE: {dev['sbe_type_str']}   "
                f"FW: {dev['fw_name']}"
            )
            if dev.get("bd_addr"):
                print(f"      BD_ADDR: {dev['bd_addr']}")
            if args.verbose:
                print(
                    f"      TLV: CNVI_TOP={dev['cnvi_top']} "
                    f"CNVR_TOP={dev['cnvr_top']} "
                    f"CNVI_BT={dev['cnvi_bt']}"
                )

        print()

    return 0


def _cmd_usb_diagnose(args: argparse.Namespace) -> int:
    """Handle 'usb diagnose' command: enumerate devices and check accessibility."""
    if usb is None:
        print(
            "Error: pyusb not installed. Run: pip install pyusb\n"
            "On Windows, also install: pip install libusb-package",
            file=sys.stderr,
        )
        return 1

    from pybluehost.transport.usb import KNOWN_CHIPS, USBTransport

    backend = USBTransport._get_usb_backend()
    all_devices = list(usb.core.find(find_all=True, backend=backend))

    # Filter to Bluetooth devices using same logic as probe_usb_devices
    bt_devices = []
    for dev in all_devices:
        chip = next(
            (c for c in KNOWN_CHIPS if c.vid == dev.idVendor and c.pid == dev.idProduct),
            None,
        )
        if chip is None:
            if (
                getattr(dev, "bDeviceClass", 0) == 0xE0
                and getattr(dev, "bDeviceSubClass", 0) == 0x01
                and getattr(dev, "bDeviceProtocol", 0) == 0x01
            ):
                pass
            else:
                continue
        bt_devices.append(dev)

    if not bt_devices:
        print("No USB Bluetooth devices found.")
        return 0

    print(f"Found {len(bt_devices)} USB Bluetooth device(s):\n")

    for idx, dev in enumerate(bt_devices, 1):
        chip = next(
            (c for c in KNOWN_CHIPS if c.vid == dev.idVendor and c.pid == dev.idProduct),
            None,
        )
        name = chip.name if chip else "Unknown BT Device"
        vid_pid = f"{dev.idVendor:04x}:{dev.idProduct:04x}"

        print(f"  [{idx}] {vid_pid}  {name}")

        # Try to access the device
        errno = None
        exc_type = None
        try:
            try:
                dev.set_configuration()
            except Exception:
                pass
            dev.get_active_configuration()
            print("      Status: 正常可访问 (OK)")
        except usb.core.USBError as e:
            errno = getattr(e, "errno", None)
            exc_type = type(e).__name__
        except NotImplementedError as e:
            errno = -12
            exc_type = "NotImplementedError"

        if errno is not None:
            report = USBDeviceDiagnostics.diagnose(dev, errno, sys.platform)
            print(f"      Status: 访问被拒绝 ({exc_type}, errno={errno})")
            print(f"\n      诊断: {report.failure_type.name}")
            if report.driver_type:
                print(f"      驱动类型: {report.driver_type.value}")
            print("\n      解决步骤:")
            for step in report.steps:
                if step:
                    print(f"        {step}")
                else:
                    print()
            if report.manual_url:
                print(f"\n      参考: {report.manual_url}")

        print()

    return 0


# ---------------------------------------------------------------------------
# USB 设备诊断
# ---------------------------------------------------------------------------

from dataclasses import dataclass
from enum import Enum, auto


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
