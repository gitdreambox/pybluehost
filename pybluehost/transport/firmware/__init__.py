"""Firmware management: locate, verify, and download Bluetooth firmware files."""

from __future__ import annotations

import os
import platform
from enum import Enum
from pathlib import Path


class FirmwarePolicy(str, Enum):
    """Policy for handling missing firmware files."""

    AUTO_DOWNLOAD = "auto"
    PROMPT = "prompt"
    ERROR = "error"


class FirmwareNotFoundError(RuntimeError):
    """Raised when a firmware file cannot be found in any search directory."""


# Vendor → default system firmware directories (Linux)
_SYSTEM_FW_DIRS: dict[str, list[Path]] = {
    "intel": [Path("/lib/firmware/intel")],
    "realtek": [Path("/lib/firmware/rtl_bt")],
}

# Environment variable names for per-vendor firmware override
_ENV_VARS: dict[str, str] = {
    "intel": "PYBLUEHOST_INTEL_FW_DIR",
    "realtek": "PYBLUEHOST_RTK_FW_DIR",
}


class FirmwareManager:
    """Locate firmware files using a priority search order.

    Search priority (first match wins):
    1. Environment variable (PYBLUEHOST_INTEL_FW_DIR / PYBLUEHOST_RTK_FW_DIR)
    2. extra_dirs (passed by caller, in order)
    3. Platform user data dir (~/.local/share/pybluehost/firmware/<vendor>/)
    4. System firmware dir (Linux: /lib/firmware/intel/ etc.)
    """

    def __init__(
        self,
        vendor: str,
        extra_dirs: list[Path] | None = None,
        policy: FirmwarePolicy = FirmwarePolicy.PROMPT,
    ) -> None:
        self._vendor = vendor
        self._extra_dirs = list(extra_dirs) if extra_dirs else []
        self._policy = policy

    @property
    def policy(self) -> FirmwarePolicy:
        return self._policy

    @property
    def data_dir(self) -> Path:
        """Platform-specific user data directory for firmware storage."""
        system = platform.system()
        if system == "Windows":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        elif system == "Darwin":
            base = Path.home() / "Library" / "Application Support"
        else:  # Linux and others
            base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        return base / "pybluehost" / "firmware" / self._vendor

    def _search_dirs(self) -> list[Path]:
        """Build ordered list of directories to search."""
        dirs: list[Path] = []

        # 1. Environment variable override
        env_var = _ENV_VARS.get(self._vendor)
        if env_var:
            env_path = os.environ.get(env_var)
            if env_path:
                dirs.append(Path(env_path))

        # 2. Extra dirs (caller-supplied, in order)
        dirs.extend(self._extra_dirs)

        # 3. Platform user data dir
        dirs.append(self.data_dir)

        # 4. System firmware dirs
        system_dirs = _SYSTEM_FW_DIRS.get(self._vendor, [])
        dirs.extend(system_dirs)

        return dirs

    def find(self, filename: str) -> Path:
        """Find a firmware file by name across all search directories.

        Returns the path to the first match found.
        Raises FirmwareNotFoundError if not found (message depends on policy).
        """
        for search_dir in self._search_dirs():
            candidate = search_dir / filename
            if candidate.is_file():
                return candidate

        # Not found — raise with policy-appropriate message
        raise FirmwareNotFoundError(self._format_not_found_message(filename))

    def find_or_download(self, filename: str) -> Path:
        """Find a firmware file, or download it if missing and policy allows.

        Raises FirmwareNotFoundError if the file cannot be found and
        auto-download is not enabled or fails.
        """
        try:
            return self.find(filename)
        except FirmwareNotFoundError:
            if self._policy == FirmwarePolicy.AUTO_DOWNLOAD:
                return self._auto_download(filename)
            raise

    def _auto_download(self, filename: str) -> Path:
        """Download the firmware file into the platform data directory."""
        from pybluehost.transport.firmware.downloader import FirmwareDownloader

        self.data_dir.mkdir(parents=True, exist_ok=True)
        return FirmwareDownloader.download(filename, self._vendor, self.data_dir)

    def _format_not_found_message(self, filename: str) -> str:
        """Build a user-friendly error message with download instructions."""
        searched = [str(d) for d in self._search_dirs()]
        searched_str = "\n  ".join(searched) if searched else "(none)"

        msg = (
            f"Firmware file '{filename}' not found for vendor '{self._vendor}'.\n"
            f"Searched directories:\n  {searched_str}\n\n"
        )

        if self._policy == FirmwarePolicy.ERROR:
            msg += (
                "To download firmware, run:\n"
                f"  pybluehost fw download {self._vendor}\n\n"
                "Or set the firmware directory via environment variable:\n"
                f"  export {_ENV_VARS.get(self._vendor, 'PYBLUEHOST_FW_DIR')}=/path/to/firmware"
            )
        elif self._policy == FirmwarePolicy.PROMPT:
            msg += (
                "To resolve this, you can:\n"
                f"  Option 1: pybluehost fw download {self._vendor}\n"
                f"  Option 2: Manually place '{filename}' in {self.data_dir}\n"
                f"  Option 3: Set {_ENV_VARS.get(self._vendor, 'PYBLUEHOST_FW_DIR')}=/path/to/firmware"
            )
        else:
            # AUTO_DOWNLOAD
            msg += (
                "Auto-download failed or was disabled.\n"
                f"Please run: pybluehost fw download {self._vendor}"
            )

        return msg
