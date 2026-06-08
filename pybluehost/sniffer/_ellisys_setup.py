"""PowerShell .ps1 generation + invocation for Ellisys Ice remote-control setup.

Windows-only code path, invoked from EllisysBackend._run_ice_setup. The
PowerShell sequence (load Ice.dll + the Bluetooth Remote Control plugin, cast
the analyzer proxy, SelectDataSource('injection') + StartRecording) is the
exact sequence validated by the original working demo and recovered from its
bytecode — it is the only validation this Windows path has, so it is
reproduced faithfully here.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from pybluehost.core.errors import SnifferError

logger = logging.getLogger(__name__)

# DLLs live under the analyzer install dir's RemoteControl subfolder.
_REMOTE_CONTROL_SUBDIR = "RemoteControl"
_ICE_DLL = "Ice.dll"
_PLUGIN_DLL = "EllisysAnalyzerBluetoothRemoteControlPlugin.dll"


def wait_for_tcp_port(
    host: str, port: int, timeout_s: float = 60.0, interval_s: float = 1.0
) -> None:
    """Poll-connect to (host, port) until reachable or timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=interval_s):
                return
        except OSError:
            time.sleep(interval_s)
    raise SnifferError(
        f"Ellisys TCP port {host}:{port} did not become ready within {timeout_s}s"
    )


def build_ice_setup_ps1(ellisys_path: Path, tcp_port: int) -> str:
    """Generate the PowerShell script that selects the injection data source and
    starts recording, via the Ellisys Bluetooth Analyzer Remote Control plugin.

    Recovered verbatim (structure + method calls) from the validated demo.
    """
    ice_dll = ellisys_path / _REMOTE_CONTROL_SUBDIR / _ICE_DLL
    plugin_dll = ellisys_path / _REMOTE_CONTROL_SUBDIR / _PLUGIN_DLL
    return (
        "\n$ErrorActionPreference = 'Stop'\n"
        f"[Reflection.Assembly]::LoadFrom('{ice_dll}') | Out-Null\n"
        f"[Reflection.Assembly]::LoadFrom('{plugin_dll}') | Out-Null\n"
        "$communicator = [Ice.Util]::initialize()\n"
        "try {\n"
        "  $proxy = $communicator.stringToProxy('Ellisys.AnalyzerRemoteControl."
        f"Bluetooth:tcp -h localhost -p {tcp_port}')\n"
        "  $remote = [Ellisys.Platform.NetworkRemoteControl.Analyzer."
        "BluetoothAnalyzerRemoteControlPrxHelper]::checkedCast($proxy)\n"
        "  if ($null -eq $remote) { throw 'Failed to cast Ellisys remote control proxy' }\n"
        "  if ($remote.IsRecording()) { $remote.AbortRecordingAndDiscardTraceFile() }\n"
        "  try {\n"
        "    $remote.SelectDataSource('injection')\n"
        "    Write-Host 'Selected data source: injection'\n"
        "  } catch {\n"
        "    Write-Host ('SelectDataSource(injection) skipped: ' + $_.Exception.Message)\n"
        "  }\n"
        "  try { $remote.CancelUserInteraction() } catch {}\n"
        "  try {\n"
        "    $remote.StartRecording()\n"
        "  } catch {\n"
        "    if (-not $remote.IsRecording()) {\n"
        "      try { $remote.CancelUserInteraction() } catch {}\n"
        "      Start-Sleep -Seconds 1\n"
        "      try { $remote.StartRecording() } catch { if (-not $remote.IsRecording()) { throw } }\n"
        "    }\n"
        "  }\n"
        "  if (-not $remote.IsRecording()) { throw 'Ellisys did not enter recording state' }\n"
        "  Write-Host 'Ellisys Ice setup OK'\n"
        "} finally {\n"
        "  if ($null -ne $communicator) { $communicator.destroy() }\n"
        "}\n"
    )


def _run_powershell(script_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )


async def run_ice_setup(tcp_port: int, ellisys_path: Path) -> None:
    """Write the .ps1 to a temp file, run it, raise SnifferError on failure."""
    script = build_ice_setup_ps1(ellisys_path, tcp_port)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ps1", delete=False, encoding="utf-8"
    ) as f:
        f.write(script)
        script_path = Path(f.name)
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run_powershell, script_path)
        if result.returncode != 0:
            raise SnifferError(
                f"Ellisys Ice setup failed (exit {result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        logger.info("Ellisys Ice setup: %s", result.stdout.strip())
    finally:
        script_path.unlink(missing_ok=True)
