"""Firmware download from upstream linux-firmware.git repository."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from pathlib import Path


class FirmwareDownloadError(RuntimeError):
    """Raised when firmware download fails; includes manual download instructions."""

    def __init__(self, filename: str, url: str, reason: str) -> None:
        self.filename = filename
        self.url = url
        self.reason = reason
        super().__init__(
            f"[警告] 固件 '{filename}' 自动下载失败: {reason}\n\n"
            "请手动下载:\n"
            f"  1. 访问 https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/tree/{self._tree_path(filename)}\n"
            f"  2. 下载 {filename}\n"
            f"  3. 放置到正确的固件目录\n"
            "  4. 重新运行程序\n\n"
            "或者通过 CLI 下载:\n"
            f"  pybluehost tools fw download {self._vendor_from_filename(filename)}"
        )

    @staticmethod
    def _tree_path(filename: str) -> str:
        if filename.startswith("ibt-"):
            return f"intel/{filename}"
        if filename.startswith("rtl"):
            return f"rtl_bt/{filename}"
        return filename

    @staticmethod
    def _vendor_from_filename(filename: str) -> str:
        if filename.startswith("ibt-"):
            return "intel"
        if filename.startswith("rtl"):
            return "realtek"
        return "unknown"


class FirmwareDownloader:
    """Download Bluetooth firmware files from linux-firmware.git."""

    _BASE_URLS = {
        "intel": ((
            "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/"
            "linux-firmware.git/plain/intel/{filename}"
        ),),
        "realtek": (
            (
            "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/"
            "linux-firmware.git/plain/rtl_bt/{filename}"
            ),
            (
            "https://gitlab.com/kernel-firmware/linux-firmware/-/raw/main/"
            "rtl_bt/{filename}"
            ),
        ),
    }

    _MAX_RETRIES = 3
    _CONNECT_TIMEOUT = 10
    _READ_TIMEOUT = 30
    _RETRY_DELAY_BASE = 2.0

    @classmethod
    def download(cls, filename: str, vendor: str, dest_dir: Path) -> Path:
        """Download a firmware file, retrying on transient errors."""
        dest_path = dest_dir / filename
        dest_dir.mkdir(parents=True, exist_ok=True)

        last_error = ""
        last_url = ""
        for url in cls._build_urls(filename, vendor):
            last_url = url
            for attempt in range(1, cls._MAX_RETRIES + 1):
                try:
                    cls._download_file(url, dest_path)
                    return dest_path
                except (urllib.error.URLError, OSError) as e:
                    last_error = str(e)
                    if attempt < cls._MAX_RETRIES:
                        delay = cls._RETRY_DELAY_BASE * (2 ** (attempt - 1))
                        time.sleep(delay)

        raise FirmwareDownloadError(filename, last_url, last_error)

    @classmethod
    def _build_url(cls, filename: str, vendor: str) -> str:
        return cls._build_urls(filename, vendor)[0]

    @classmethod
    def _build_urls(cls, filename: str, vendor: str) -> list[str]:
        templates = cls._BASE_URLS.get(vendor)
        if templates is None:
            raise FirmwareDownloadError(filename, "", f"Unknown vendor: {vendor}")
        return [template.format(filename=filename) for template in templates]

    @classmethod
    def _download_file(cls, url: str, dest: Path) -> None:
        with urllib.request.urlopen(url, timeout=cls._CONNECT_TIMEOUT) as response:
            data = response.read()
            if not data:
                raise OSError("Empty response")
            dest.write_bytes(data)
