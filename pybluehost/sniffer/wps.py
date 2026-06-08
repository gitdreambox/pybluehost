"""Teledyne LeCroy WPS injection — pure encoding + Windows backend."""
from __future__ import annotations

from pybluehost.core.trace import Direction


# Drf bitfield (from liveimport.ini personality "Command;ACL;SCO;Event")
_DRF_COMMAND = 1
_DRF_ACL = 2
_DRF_SCO = 4
_DRF_EVENT = 8

# Stream
_STREAM_HOST = 0
_STREAM_CONTROLLER = 1


def wps_frame_params(h4_type: int, direction: Direction) -> tuple[int, int] | None:
    """Map (H4 packet type, direction) → (Drf, Stream) for WPS SendFrame3.

    Returns None for ISO (0x05) — not representable in default WPS personality.
    Caller (WpsBackend.inject) must skip None and warn once per session.

    See design spec §3.3.
    """
    if h4_type == 0x01:
        return (_DRF_COMMAND, _STREAM_HOST)
    if h4_type == 0x04:
        return (_DRF_EVENT, _STREAM_CONTROLLER)
    if h4_type == 0x02:
        return (_DRF_ACL, _STREAM_HOST if direction == Direction.DOWN else _STREAM_CONTROLLER)
    if h4_type == 0x03:
        return (_DRF_SCO, _STREAM_HOST if direction == Direction.DOWN else _STREAM_CONTROLLER)
    if h4_type == 0x05:
        return None
    raise ValueError(f"unknown H4 packet type: 0x{h4_type:02X}")


import asyncio  # noqa: E402
import ctypes  # noqa: E402
import logging  # noqa: E402
from datetime import datetime  # noqa: E402
from typing import Any  # noqa: E402

from pybluehost.core.errors import SnifferError, SnifferUnavailableError  # noqa: E402
from pybluehost.sniffer.backend import SnifferBackend  # noqa: E402

logger = logging.getLogger(__name__)


# WPS Live Import notification codes (recovered from the validated demo)
E_START_CAPTURE_TO_FILE = 6

# Connection string + [Configuration] block recovered verbatim from the working
# demo bytecode. The PRD stresses that this exact combination — the product-root
# connection string plus the developer-kit [Configuration] — is what makes WPS
# actually display injected HCI frames, so the values are reproduced faithfully.
LIVEIMPORT_CONNECTION_STRING = (
    "Wireless Protocol Suite Live Import.FDFFFFFF!"
    "A51EEBF13DE32BEA4933A8E519DB795D8EB02D;D06C136E"
)

_LIVEIMPORT_CONFIG_LINES = (
    "Version=6",
    "WindowTitle=PyBlueHost Virtual Sniffer",
    "DriverInfo=PyBlueHost Virtual Sniffer",
    'Sides="Host,1000000;Controller,1000000"',
    "StackAuto=true",
    "Stack=0x7f008039",
    'Drf="Command;ACL;SCO;Event"',
)


def build_liveimport_config() -> str:
    """Return the WPS Live Import [Configuration] string (recovered fallback)."""
    return "\n".join(_LIVEIMPORT_CONFIG_LINES)


def read_liveimport_settings(wps_path: str) -> tuple[str, str]:
    """Read (connection_string, config_string) from the WPS ini files.

    Connection string ← product-root ``liveimport.ini`` ``[General]``;
    config ← developer-kit ``liveimport.ini`` ``[Configuration]`` (this exact
    combination is what makes WPS display injected frames — PRD §3.3). Falls
    back to the recovered inlined constants when an ini is missing.
    """
    import configparser
    from pathlib import Path

    wps = Path(wps_path)
    product_ini = wps / "liveimport.ini"
    devkit_ini = wps / "Live Import Developers Kit" / "liveimport.ini"

    connection = LIVEIMPORT_CONNECTION_STRING
    if product_ini.exists():
        cp = configparser.ConfigParser()
        cp.optionxform = str  # preserve key case
        cp.read(product_ini, encoding="utf-8")
        if cp.has_section("General") and cp.has_option("General", "ConnectionString"):
            connection = cp.get("General", "ConnectionString").strip().strip('"')

    config = build_liveimport_config()
    if devkit_ini.exists():
        cp = configparser.ConfigParser()
        cp.optionxform = str
        cp.read(devkit_ini, encoding="utf-8")
        if cp.has_section("Configuration"):
            config = "\n".join(f"{k}={v}" for k, v in cp.items("Configuration"))

    return connection, config


class LiveImportLibrary:
    """Thin wrapper around ctypes.CDLL('LiveImportAPI.dll'); test-injectable.

    The real DLL is loaded by `LiveImportLibrary.load_default(wps_path)`. Tests
    construct LiveImportLibrary(fake_lib, ...) directly with a stub object that
    exposes InitializeLiveImportEx / SendFrame3 / SendNotification / IsAppReady.
    """

    def __init__(self, library: Any, connection_string: str, config_string: str) -> None:
        self._lib = library
        self.connection_string = connection_string
        self.config_string = config_string
        # If the injected lib is a real CDLL, configure ctypes signatures.
        if isinstance(library, ctypes.CDLL):
            self._configure_real_ctypes_signatures()

    def _configure_real_ctypes_signatures(self) -> None:
        self._lib.InitializeLiveImportEx.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_bool), ctypes.c_int,
        ]
        self._lib.InitializeLiveImportEx.restype = ctypes.c_long
        self._lib.SendFrame3.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int, ctypes.c_int, ctypes.c_ulonglong,
        ]
        self._lib.SendFrame3.restype = ctypes.c_long
        self._lib.SendNotification.argtypes = [ctypes.c_int]
        self._lib.SendNotification.restype = ctypes.c_long
        self._lib.IsAppReady.argtypes = [ctypes.POINTER(ctypes.c_bool)]
        self._lib.IsAppReady.restype = ctypes.c_long

    @classmethod
    def load_default(cls, wps_path: str) -> "LiveImportLibrary":
        """Windows-only: load LiveImportAPI.dll + the recovered connection/config."""
        import sys
        from pathlib import Path
        if sys.platform != "win32":
            raise SnifferUnavailableError(
                "WpsBackend requires Windows (Teledyne WPS is Windows-only)"
            )
        wps = Path(wps_path)
        # WPS ships the live-import DLL under Executables\Core (recovered from
        # the validated demo: <wps_path>/Executables/Core/LiveImportAPI_x64.dll).
        candidates = [
            wps / "Executables" / "Core" / "LiveImportAPI_x64.dll",
            wps / "Executables" / "Core" / "LiveImportAPI.dll",
            wps / "Automation" / "LiveImportAPI.dll",
            wps / "LiveImportAPI_x64.dll",
            wps / "LiveImportAPI.dll",
        ]
        dll = next((c for c in candidates if c.exists()), None)
        if dll is None:
            raise SnifferError(
                f"LiveImportAPI.dll not found under: {wps} (looked in Executables/Core/)"
            )
        connection_string, config_string = read_liveimport_settings(wps_path)
        return cls(
            ctypes.CDLL(str(dll)),
            connection_string=connection_string,
            config_string=config_string,
        )

    # ----- thin call helpers (used by WpsBackend; test-mock-friendly) -----

    def initialize(self) -> None:
        success = ctypes.c_bool(False)
        hresult = self._lib.InitializeLiveImportEx(
            self.connection_string.encode("ascii"),
            self.config_string.encode("ascii"),
            ctypes.byref(success),
            0,
        )
        if ctypes.c_long(hresult).value < 0 or not success.value:
            raise SnifferError(
                f"InitializeLiveImportEx failed: HRESULT=0x{ctypes.c_uint32(hresult).value:08X}"
            )

    def start_capture(self) -> None:
        hresult = self._lib.SendNotification(E_START_CAPTURE_TO_FILE)
        if ctypes.c_long(hresult).value < 0:
            raise SnifferError(
                f"SendNotification(start_capture) failed: "
                f"HRESULT=0x{ctypes.c_uint32(hresult).value:08X}"
            )

    def is_app_ready(self) -> bool:
        ready = ctypes.c_bool(False)
        self._lib.IsAppReady(ctypes.byref(ready))
        return bool(ready.value)

    def send_frame(self, payload: bytes, drf: int, stream: int, timestamp_ns: int) -> None:
        buf = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
        hresult = self._lib.SendFrame3(
            len(payload), len(payload), buf, drf, stream, timestamp_ns,
        )
        if ctypes.c_long(hresult).value < 0:
            raise SnifferError(
                f"SendFrame3 failed: HRESULT=0x{ctypes.c_uint32(hresult).value:08X}"
            )


class WpsBackend(SnifferBackend):
    """Teledyne WPS integration via LiveImportAPI.dll (ctypes).

    Design spec §6.2. Tests pass a LiveImportLibrary backed by a fake object;
    real use loads the DLL via `LiveImportLibrary.load_default(wps_path)`.
    """

    def __init__(self, *, library: LiveImportLibrary, wps_path: str | None = None) -> None:
        self._lib = library
        self._wps_path = wps_path
        self._warned_iso = False
        self._fts_proc = None

    def _launch_fts(self) -> None:
        """Windows-only: launch Fts.exe in Generic Live-Import mode.

        <wps_path>/Executables/Core/Fts.exe /ComProbe Protocol Analysis
        System=Generic /oemkey=Virtual  — recovered from the validated demo.
        """
        import subprocess
        import sys
        from pathlib import Path

        if sys.platform != "win32":
            raise SnifferUnavailableError(
                "WpsBackend requires Windows (Teledyne WPS is Windows-only)"
            )
        exe = Path(self._wps_path) / "Executables" / "Core" / "Fts.exe"
        if not exe.exists():
            raise SnifferError(f"WPS Fts.exe not found: {exe}")
        self._fts_proc = subprocess.Popen(
            [str(exe), "/ComProbe Protocol Analysis System=Generic", "/oemkey=Virtual"],
            close_fds=True,
        )

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        # Launch the WPS Live-Import host first (real use only; tests pass no wps_path).
        if self._wps_path is not None:
            await loop.run_in_executor(None, self._launch_fts)
        await loop.run_in_executor(None, self._lib.initialize)
        # Wait for Live Import to become ready before starting capture (real use).
        if self._wps_path is not None:
            deadline = 60.0
            waited = 0.0
            while not await loop.run_in_executor(None, self._lib.is_app_ready):
                if waited >= deadline:
                    raise SnifferError(
                        f"WPS LiveImport did not become ready within {deadline:.0f}s"
                    )
                await asyncio.sleep(0.5)
                waited += 0.5
        await loop.run_in_executor(None, self._lib.start_capture)

    async def inject(self, h4_type, direction, payload, wall_clock: datetime) -> None:
        params = wps_frame_params(h4_type, direction)
        if params is None:
            # ISO (h4_type=0x05) — not in default WPS personality Drf.
            if not self._warned_iso:
                logger.warning(
                    "WpsBackend: skipping ISO frame (Drf has no ISO in default personality)"
                )
                self._warned_iso = True
            return
        drf, stream = params
        ts_ns = int(wall_clock.timestamp() * 1_000_000_000)
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, self._lib.send_frame, payload, drf, stream, ts_ns
            )
        except SnifferError:
            logger.warning("WpsBackend.inject: SendFrame3 failed", exc_info=True)

    async def stop(self) -> None:
        # The LiveImport API has no explicit shutdown; releasing references is enough.
        pass
