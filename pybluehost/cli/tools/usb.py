"""USB device probe CLI: enumerate and inspect Bluetooth USB controllers."""

from __future__ import annotations

import argparse
import asyncio
import ctypes.util
import logging
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pybluehost.transport.firmware import FirmwarePolicy

try:
    import usb.core
    import usb.util
except ImportError:
    usb = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)
_FIRMWARE_LOAD_LOGGER = "pybluehost.transport.usb"
_DEFAULT_FIRMWARE_LOAD_LOG = Path("pybluehost-usb-firmware-load.log")


def register_usb_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register 'usb' subcommand group."""
    usb_parser = subparsers.add_parser("usb", help="USB Bluetooth device tools")
    usb_sub = usb_parser.add_subparsers(dest="usb_command")

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
    color_group = probe_parser.add_mutually_exclusive_group()
    color_group.add_argument(
        "--color", dest="color", action="store_true", help="Force colored output"
    )
    color_group.add_argument(
        "--no-color", dest="color", action="store_false", help="Disable colored output"
    )
    probe_parser.set_defaults(color=None)
    probe_parser.set_defaults(func=_cmd_usb_probe)

    diag_parser = usb_sub.add_parser(
        "diagnose", help="Diagnose USB Bluetooth device accessibility issues"
    )
    diag_parser.add_argument(
        "--log-file",
        type=Path,
        default=_DEFAULT_FIRMWARE_LOAD_LOG,
        help=(
            "Also write firmware-load progress logs to this file "
            f"(default: {_DEFAULT_FIRMWARE_LOAD_LOG})"
        ),
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
    """Enumerate USB Bluetooth devices and return info dicts."""
    if usb is None:
        raise RuntimeError(
            "pyusb not installed. Run: pip install pyusb\n"
            "On Windows, also install: pip install libusb-package"
        )

    from pybluehost.transport.usb import USBTransport

    return USBTransport.probe_devices(verbose=verbose, intel_tlv=intel_tlv)


def _get_endpoints(dev: Any) -> list[dict[str, str]]:
    from pybluehost.transport.usb import get_usb_endpoints

    return get_usb_endpoints(dev)


def _probe_intel_tlv(dev: Any) -> dict[str, Any] | None:
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
        logger.error("Error: %s", e)
        return 1

    if not devices:
        logger.info("No USB Bluetooth devices found.")
        return 0

    color_choice = getattr(args, "color", None)
    if not isinstance(color_choice, bool):
        color_choice = None
    use_color = _should_use_color(color_choice)
    logger.info("Found %d USB Bluetooth device(s):\n", len(devices))

    for dev in devices:
        usb_id = dev.get("id") or dev["vid_pid"].upper()
        logger.info("ID %s", _color(usb_id, "id", use_color))
        if dev.get("vendor") or dev.get("chip_name"):
            _log_probe_field(
                "Name",
                f"{dev.get('vendor', 'unknown')} {dev.get('chip_name', 'Unknown')}",
                "name",
                use_color,
            )
        names = dev.get("transport_names") or dev.get("bumble_transport_names") or []
        if names:
            _log_probe_field("Bumble Transport Names", " or ".join(names), "name", use_color)
        _log_probe_field(
            "Bus/Device",
            f"{int(dev.get('bus') or 0):03d}/{int(dev.get('address') or 0):03d}",
            "number",
            use_color,
        )
        _log_probe_field(
            "Class",
            dev.get("class_name") or dev.get("device_class_name") or dev["device_class"],
            "class",
            use_color,
        )
        subclass = dev.get("subclass_name")
        protocol = dev.get("protocol_name")
        if subclass is not None and protocol is not None:
            sub_proto = f"{subclass} / {protocol}"
        else:
            sub_proto = dev.get("subclass_protocol", "0/0")
        _log_probe_field("Subclass/Protocol", sub_proto, "class", use_color)
        if dev.get("serial"):
            _log_probe_field("Serial", dev["serial"], "name", use_color)
        if dev.get("manufacturer"):
            _log_probe_field("Manufacturer", dev["manufacturer"], "name", use_color)
        if dev.get("product"):
            _log_probe_field("Product", dev["product"], "name", use_color)

        if args.verbose and dev.get("endpoints"):
            logger.info("  Endpoints:")
            for ep in dev["endpoints"]:
                logger.info("    EP %s  %s %s", ep["address"], ep["type"], ep["direction"])

        if args.intel_tlv and dev.get("image_type") is not None:
            logger.info(
                "      Mode: %s   SBE: %s   FW: %s",
                dev["image_type_str"],
                dev["sbe_type_str"],
                dev["fw_name"],
            )
            if dev.get("bd_addr"):
                logger.info("      BD_ADDR: %s", dev["bd_addr"])
            if args.verbose:
                logger.info(
                    "      TLV: CNVI_TOP=%s CNVR_TOP=%s CNVI_BT=%s",
                    dev["cnvi_top"],
                    dev["cnvr_top"],
                    dev["cnvi_bt"],
                )

        logger.info("")

    return 0


def _cmd_usb_diagnose(args: argparse.Namespace) -> int:
    """Handle 'usb diagnose' command with step-by-step USB/HCI checks."""
    if usb is None:
        logger.error(
            "Error: pyusb not installed. Run: pip install pyusb\n"
            "On Windows, also install: pip install libusb-package"
        )
        return 1

    from pybluehost.transport.usb import USBTransport

    exit_code = 0
    logger.info("USB Bluetooth diagnostics")
    dll = _libusb_library_path()
    if sys.platform == "win32":
        if dll:
            logger.info("[OK] libusb backend: available (%s)", dll)
        else:
            logger.warning("%s libusb DLL path: libusb-1.0.dll not found by path lookup", _warn_prefix())
            logger.info("       Continuing with pyusb backend discovery.")
    else:
        logger.info("[OK] libusb backend: pyusb backend resolved")

    try:
        diagnoses = USBTransport.diagnose_all_devices()
    except Exception as e:
        logger.error("[FAIL] enumerate USB devices: %s: %s", type(e).__name__, e)
        return 1

    if not diagnoses:
        logger.info("[FAIL] enumerate Bluetooth USB: no Bluetooth USB devices found")
        return 1

    logger.info("[OK] enumerate Bluetooth USB: found %d device(s)", len(diagnoses))
    logger.info("")

    for idx, diagnosis in enumerate(diagnoses, 1):
        dev = diagnosis.device
        chip = diagnosis.chip_info
        name = chip.name if chip else "Unknown BT Device"
        vid_pid = f"{dev.idVendor:04x}:{dev.idProduct:04x}"

        logger.info("[%d] %s  %s", idx, vid_pid, name)
        logger.info(
            "    location: bus=%s address=%s class=%s",
            getattr(dev, "bus", None),
            getattr(dev, "address", None),
            _format_device_class(dev),
        )

        for check in diagnosis.checks:
            logger.info(_format_check(check))
        if not diagnosis.ok:
            exit_code = 1
        if _diagnosis_needs_firmware_load(diagnosis):
            if _confirm_firmware_load(diagnosis):
                load_ok = _load_firmware_for_diagnosis(
                    diagnosis,
                    FirmwarePolicy.AUTO_DOWNLOAD,
                    _firmware_log_path_from_args(args),
                )
                exit_code = 0 if load_ok else 1

        logger.info("")

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


def _should_use_color(choice: bool | None) -> bool:
    if choice is not None:
        return bool(choice)
    return sys.stdout.isatty()


def _color(text: str, role: str, enabled: bool) -> str:
    if not enabled:
        return text
    colors = {
        "id": "\033[36;1m",
        "name": "\033[32m",
        "number": "\033[35m",
        "class": "\033[33m",
        "ok": "\033[32m",
        "warn": "\033[33;1m",
        "fail": "\033[31;1m",
    }
    color = colors.get(role)
    if color is None:
        return text
    return f"{color}{text}\033[0m"


def _log_probe_field(label: str, value: str, role: str, use_color: bool) -> None:
    logger.info("  %-24s%s", label + ":", _color(value, role, use_color))


def _warn_prefix() -> str:
    return _color("[WARN]", "warn", sys.stderr.isatty() or sys.stdout.isatty())


def _format_check(check: Any) -> str:
    labels = {
        "ok": _color("[OK]", "ok", sys.stdout.isatty()),
        "warn": _color("[WARN]", "warn", sys.stdout.isatty()),
        "fail": _color("[FAIL]", "fail", sys.stdout.isatty()),
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
        logger.info("[INFO] Firmware load skipped by user")
        return False
    logger.info("[INFO] Loading %s firmware after interactive confirmation...", vendor.capitalize())
    return True


def _firmware_log_path_from_args(args: argparse.Namespace) -> Path:
    log_file = getattr(args, "log_file", _DEFAULT_FIRMWARE_LOAD_LOG)
    if isinstance(log_file, Path):
        return log_file
    if isinstance(log_file, str):
        return Path(log_file)
    return _DEFAULT_FIRMWARE_LOAD_LOG


@contextmanager
def _firmware_load_file_logging(log_file: str | Path | None) -> Any:
    transport_logger = logging.getLogger(_FIRMWARE_LOAD_LOGGER)
    old_level = transport_logger.level
    handler: logging.Handler | None = None

    if log_file is not None:
        try:
            path = Path(log_file)
            if path.parent != Path("."):
                path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(path, mode="a", encoding="utf-8")
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            transport_logger.addHandler(handler)
            logger.info("[INFO] Firmware load log: %s", path)
        except OSError as e:
            logger.warning("%s Firmware load log unavailable: %s: %s", _warn_prefix(), type(e).__name__, e)

    transport_logger.setLevel(logging.INFO)
    try:
        yield
    finally:
        if handler is not None:
            transport_logger.removeHandler(handler)
            handler.close()
        transport_logger.setLevel(old_level)


def _load_firmware_for_diagnosis(
    diagnosis: Any,
    policy: FirmwarePolicy,
    log_file: str | Path | None = _DEFAULT_FIRMWARE_LOAD_LOG,
) -> bool:
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

        async def run_load() -> None:
            await transport.open()
            await transport.close()

        with _firmware_load_file_logging(log_file):
            asyncio.run(run_load())
        logger.info("[OK] Firmware load completed")
        return True
    except Exception as e:
        logger.error("[FAIL] Firmware load failed: %s: %s", type(e).__name__, e)
        logger.info("")
        logger.info("请运行以下命令查看详细诊断和解决方案:")
        logger.info("  pybluehost tools usb diagnose")
        return False
