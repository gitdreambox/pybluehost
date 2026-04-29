"""USB device probe CLI: enumerate and inspect Bluetooth USB controllers."""

from __future__ import annotations

import argparse
import ctypes.util
import sys
from typing import Any

from pybluehost.transport.usb import (
    DriverType,
    FailureType,
    USBDiagnosticReport,
    USBDeviceDiagnostics,
)

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
        "-v", "--verbose", action="store_true", help="Show USB endpoint details"
    )
    probe_parser.add_argument(
        "-i", "--intel-tlv", action="store_true",
        help="Read Intel TLV version data (sends HCI command to device)",
    )
    probe_parser.set_defaults(func=_cmd_usb_probe)

    # usb diagnose
    diag_parser = usb_sub.add_parser(
        "diagnose", help="Diagnose USB Bluetooth device accessibility issues"
    )
    diag_parser.set_defaults(func=_cmd_usb_diagnose)

    usb_parser.set_defaults(func=lambda args: usb_parser.print_help() or 0)


def _known_chip_for(dev: Any) -> Any | None:
    from pybluehost.transport.usb import known_chip_for

    return known_chip_for(dev)


def _class_tuple(obj: Any, prefix: str) -> tuple[int, int, int]:
    from pybluehost.transport.usb import usb_class_tuple

    return usb_class_tuple(obj, prefix)


def _is_bluetooth_class(values: tuple[int, int, int]) -> bool:
    from pybluehost.transport.usb import is_bluetooth_usb_class

    return is_bluetooth_usb_class(values)


def _iter_interfaces(dev: Any) -> list[Any]:
    from pybluehost.transport.usb import iter_usb_interfaces

    return iter_usb_interfaces(dev)


def _is_bluetooth_usb_device(dev: Any) -> bool:
    from pybluehost.transport.usb import is_bluetooth_usb_device

    return is_bluetooth_usb_device(dev)


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

    from pybluehost.transport.usb import USBTransport

    return USBTransport.probe_devices(verbose=verbose, intel_tlv=intel_tlv)


def _get_endpoints(dev: Any) -> list[dict[str, str]]:
    """Extract endpoint info from USB device."""
    from pybluehost.transport.usb import get_usb_endpoints

    return get_usb_endpoints(dev)


def _probe_intel_tlv(dev: Any) -> dict[str, Any] | None:
    """Send Intel Read Version V2 and parse TLV response."""
    from pybluehost.transport.usb import USBTransport

    return USBTransport._probe_intel_tlv(dev)


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
        print(_style(f"ID {dev['vid_pid'].upper()}", "name"))
        if dev.get("vendor") or dev.get("chip_name"):
            print(
                f"  {_style('Name:', 'label')}                   "
                f"{dev.get('vendor', 'unknown')} {dev.get('chip_name', 'Unknown')}"
            )
        names = dev.get("bumble_transport_names") or []
        if names:
            print(f"  {_style('Bumble Transport Names:', 'label')} {' or '.join(names)}")
        print(
            f"  {_style('Bus/Device:', 'label')}             "
            f"{int(dev['bus'] or 0):03d}/{int(dev['address'] or 0):03d}"
        )
        print(
            f"  {_style('Class:', 'label')}                  "
            f"{dev.get('device_class_name', dev['device_class'])}"
        )
        print(
            f"  {_style('Subclass/Protocol:', 'label')}      "
            f"{dev.get('subclass_protocol', '0/0')}"
        )
        if dev.get("serial"):
            print(f"  {_style('Serial:', 'label')}                 {dev['serial']}")
        if dev.get("manufacturer"):
            print(f"  {_style('Manufacturer:', 'label')}           {dev['manufacturer']}")
        if dev.get("product"):
            print(f"  {_style('Product:', 'label')}                {dev['product']}")

        if args.verbose and dev.get("endpoints"):
            print(f"  {_style('Endpoints:', 'label')}")
            for ep in dev["endpoints"]:
                print(f"    EP {ep['address']}  {ep['type']} {ep['direction']}")

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
    """Handle 'usb diagnose' command with step-by-step USB/HCI checks."""
    if usb is None:
        print(
            "Error: pyusb not installed. Run: pip install pyusb\n"
            "On Windows, also install: pip install libusb-package",
            file=sys.stderr,
        )
        return 1

    from pybluehost.transport.usb import USBTransport

    exit_code = 0
    print("USB Bluetooth diagnostics")
    backend = USBTransport._get_usb_backend()
    dll = _libusb_library_path()
    if sys.platform == "win32":
        if dll:
            print(f"[OK] libusb backend: available ({dll})")
        else:
            print("[WARN] libusb DLL path: libusb-1.0.dll not found by path lookup")
            print("       Continuing with pyusb backend discovery.")
    else:
        print("[OK] libusb backend: pyusb backend resolved")

    try:
        diagnoses = USBTransport.diagnose_all_devices()
    except Exception as e:
        print(f"[FAIL] enumerate USB devices: {type(e).__name__}: {e}")
        return 1

    if not diagnoses:
        print("[FAIL] enumerate Bluetooth USB: no Bluetooth USB devices found")
        return 1

    print(f"[OK] enumerate Bluetooth USB: found {len(diagnoses)} device(s)")
    print()

    for idx, diagnosis in enumerate(diagnoses, 1):
        dev = diagnosis.device
        chip = diagnosis.chip_info
        name = chip.name if chip else "Unknown BT Device"
        vid_pid = f"{dev.idVendor:04x}:{dev.idProduct:04x}"

        print(f"[{idx}] {vid_pid}  {name}")
        print(
            f"    location: bus={getattr(dev, 'bus', None)} "
            f"address={getattr(dev, 'address', None)} "
            f"class={_format_device_class(dev)}"
        )

        for check in diagnosis.checks:
            print(_format_check(check))
        if not diagnosis.ok:
            exit_code = 1
        if _diagnosis_needs_firmware_load(diagnosis):
            if _confirm_firmware_load(diagnosis):
                load_ok = _load_firmware_for_diagnosis(diagnosis, FirmwarePolicy.AUTO_DOWNLOAD)
                if load_ok:
                    exit_code = 0
                else:
                    exit_code = 1

        print()

    return exit_code


def _libusb_library_path() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import libusb_package
        path = libusb_package.get_library_path()
        if path:
            return path
        path = libusb_package.find_library("libusb-1.0")
        if path:
            return path
    except Exception:
        pass
    return ctypes.util.find_library("libusb-1.0") or ctypes.util.find_library("usb-1.0")


def _format_device_class(dev: Any) -> str:
    cls, sub, proto = _class_tuple(dev, "bDevice")
    return f"{cls:02x}:{sub:02x}:{proto:02x}"


def _style(text: str, role: str) -> str:
    if not sys.stdout.isatty():
        return text
    colors = {
        "name": "\033[36;1m",
        "label": "\033[33m",
        "ok": "\033[32m",
        "warn": "\033[33;1m",
        "fail": "\033[31;1m",
    }
    color = colors.get(role)
    if not color:
        return text
    return f"{color}{text}\033[0m"


def _format_check(check: Any) -> str:
    labels = {
        "ok": _style("[OK]", "ok"),
        "warn": _style("[WARN]", "warn"),
        "fail": _style("[FAIL]", "fail"),
        "info": "      ",
    }
    return f"{labels.get(check.level, '[INFO]')} {check.name}: {check.message}"


def _diagnosis_needs_firmware_load(diagnosis: Any) -> bool:
    chip = diagnosis.chip_info
    if chip is None or chip.vendor not in {"intel", "realtek"}:
        return False
    for check in diagnosis.checks:
        if check.name == "Intel Read Version V2" and "image=BOOTLOADER" in check.message:
            return True
        if check.name == "Intel Read Version V2 status":
            return True
        if check.name == "Realtek Read ROM Version status":
            return True
        if check.name == "HCI Reset status" and "firmware load may be required" in check.message:
            return True
    return False


def _confirm_firmware_load(diagnosis: Any) -> bool:
    chip = diagnosis.chip_info
    vendor = chip.vendor if chip else "USB"
    answer = input(f"Load {vendor.capitalize()} firmware now? [y/N] ")
    if answer.strip().lower() not in {"y", "yes"}:
        print("[INFO] Firmware load skipped by user")
        return False
    print(f"[INFO] Loading {vendor.capitalize()} firmware after interactive confirmation...")
    return True


def _load_firmware_for_diagnosis(diagnosis: Any, policy: Any) -> bool:
    from pybluehost.transport.usb import USBTransport

    chip = diagnosis.chip_info
    dev = diagnosis.device
    try:
        transport = USBTransport.auto_detect(
            firmware_policy=policy,
            vendor=chip.vendor if chip else None,
            bus=int(getattr(dev, "bus", 0) or 0),
            address=int(getattr(dev, "address", 0) or 0),
        )
        import asyncio
        async def run_load() -> None:
            await transport.open()
            await transport.close()
        asyncio.run(run_load())
        print("[OK] Firmware load completed")
        return True
    except Exception as e:
        print(f"[FAIL] Firmware load failed: {type(e).__name__}: {e}")
        print()
        print("请运行以下命令查看详细诊断和解决方案:")
        print("  pybluehost tools usb diagnose")
        return False
