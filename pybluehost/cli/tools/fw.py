"""Firmware management CLI: pybluehost fw download/list/info/clean."""

from __future__ import annotations

import argparse
from pathlib import Path

from pybluehost.transport.firmware import FirmwareManager, FirmwarePolicy

_SUPPORTED_VENDORS = ("intel", "realtek")


def fw_list(fw_dir: Path | None = None) -> list[dict]:
    """List installed firmware files.

    Args:
        fw_dir: Directory to list. If None, uses default data dirs for all vendors.

    Returns:
        List of dicts with keys: name, size, path.
    """
    results = []
    if fw_dir is not None:
        dirs = [fw_dir]
    else:
        dirs = []
        for vendor in _SUPPORTED_VENDORS:
            mgr = FirmwareManager(vendor=vendor)
            dirs.append(mgr.data_dir)

    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.is_file():
                results.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "path": str(f),
                })
    return results


def fw_download(vendor: str, fw_dir: Path | None = None) -> list[Path]:
    """Download firmware files for a vendor.

    Args:
        vendor: "intel" or "realtek".
        fw_dir: Target directory. If None, uses platform default.

    Returns:
        List of downloaded file paths.
    """
    if vendor not in _SUPPORTED_VENDORS:
        raise ValueError(
            f"Unknown vendor: '{vendor}'. Supported: {', '.join(_SUPPORTED_VENDORS)}"
        )

    if fw_dir is None:
        mgr = FirmwareManager(vendor=vendor)
        fw_dir = mgr.data_dir

    fw_dir.mkdir(parents=True, exist_ok=True)
    return _download_firmware_files(vendor, fw_dir)


def _download_firmware_files(vendor: str, fw_dir: Path) -> list[Path]:
    """Download firmware files from upstream sources."""
    from pybluehost.transport.firmware.downloader import FirmwareDownloader

    downloaded: list[Path] = []

    if vendor == "intel":
        files = [
            "ibt-0291-0291.sfi",
            "ibt-0291-0291.ddc",
            "ibt-0040-0041.sfi",
            "ibt-0040-0041.ddc",
        ]
    elif vendor == "realtek":
        files = [
            "rtl8761b_fw.bin",
            "rtl8761b_config.bin",
        ]
    else:
        print(f"Unknown vendor: {vendor}")
        return downloaded

    for filename in files:
        try:
            path = FirmwareDownloader.download(filename, vendor, fw_dir)
            downloaded.append(path)
            print(f"  ok {filename}")
        except Exception as e:
            print(f"  fail {filename}: {e}")

    return downloaded


def fw_info(path: Path) -> dict:
    """Show metadata for a firmware file.

    Args:
        path: Path to the firmware file.

    Returns:
        Dict with keys: name, size, path.

    Raises:
        FileNotFoundError: If file does not exist.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Firmware file not found: {path}")

    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "path": str(path),
    }


def fw_clean(fw_dir: Path | None = None) -> int:
    """Remove all firmware files from the cache directory.

    Args:
        fw_dir: Directory to clean. If None, cleans default data dirs.

    Returns:
        Number of files removed.
    """
    removed = 0
    if fw_dir is not None:
        dirs = [fw_dir]
    else:
        dirs = []
        for vendor in _SUPPORTED_VENDORS:
            mgr = FirmwareManager(vendor=vendor)
            dirs.append(mgr.data_dir)

    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.is_file():
                f.unlink()
                removed += 1
    return removed


# --- CLI argument registration ---

def register_fw_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register 'fw' subcommand group."""
    fw_parser = subparsers.add_parser("fw", help="Firmware management")
    fw_sub = fw_parser.add_subparsers(dest="fw_command")

    # fw list
    list_parser = fw_sub.add_parser("list", help="List installed firmware")
    list_parser.add_argument("-d", "--dir", type=Path, default=None, help="Firmware directory")
    list_parser.set_defaults(func=_cmd_fw_list)

    # fw download
    dl_parser = fw_sub.add_parser("download", help="Download firmware")
    dl_parser.add_argument("vendor", choices=_SUPPORTED_VENDORS, help="Chip vendor")
    dl_parser.add_argument("-d", "--dir", type=Path, default=None, help="Target directory")
    dl_parser.set_defaults(func=_cmd_fw_download)

    # fw info
    info_parser = fw_sub.add_parser("info", help="Show firmware file info")
    info_parser.add_argument("path", type=Path, help="Path to firmware file")
    info_parser.set_defaults(func=_cmd_fw_info)

    # fw clean
    clean_parser = fw_sub.add_parser("clean", help="Clean firmware cache")
    clean_parser.add_argument("-d", "--dir", type=Path, default=None, help="Directory to clean")
    clean_parser.set_defaults(func=_cmd_fw_clean)

    fw_parser.set_defaults(func=lambda args: fw_parser.print_help() or 0)


def _cmd_fw_list(args: argparse.Namespace) -> int:
    files = fw_list(fw_dir=args.dir)
    if not files:
        print("No firmware files found.")
        return 0
    for f in files:
        print(f"  {f['name']:40s} {f['size']:>10d} bytes  {f['path']}")
    return 0


def _cmd_fw_download(args: argparse.Namespace) -> int:
    downloaded = fw_download(vendor=args.vendor, fw_dir=args.dir)
    if downloaded:
        print(f"Downloaded {len(downloaded)} file(s).")
    return 0


def _cmd_fw_info(args: argparse.Namespace) -> int:
    try:
        info = fw_info(args.path)
        print(f"Name: {info['name']}")
        print(f"Size: {info['size']} bytes")
        print(f"Path: {info['path']}")
        return 0
    except FileNotFoundError as e:
        print(str(e))
        return 1


def _cmd_fw_clean(args: argparse.Namespace) -> int:
    removed = fw_clean(fw_dir=args.dir)
    print(f"Removed {removed} file(s).")
    return 0
