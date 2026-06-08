"""Install-validation: clear, actionable errors when analyzer software/plugin
is missing or incomplete. These functions are pure filesystem checks (no
platform guard) so they run on any OS / CI."""
import pytest

from pybluehost.core.errors import SnifferError
from pybluehost.sniffer.ellisys import validate_ellisys_install
from pybluehost.sniffer.wps import validate_wps_install


# ---------------------------------------------------------------- Ellisys

def test_ellisys_missing_exe_raises_actionable(tmp_path):
    with pytest.raises(SnifferError) as exc:
        validate_ellisys_install(str(tmp_path))
    msg = str(exc.value)
    assert "Ellisys" in msg
    assert "ellisys-path" in msg          # tells user how to fix


def test_ellisys_missing_remote_plugin_raises(tmp_path):
    # exe present, but RemoteControl plugin DLLs missing
    (tmp_path / "Ellisys.BluetoothAnalyzer.exe").write_text("x")
    with pytest.raises(SnifferError) as exc:
        validate_ellisys_install(str(tmp_path))
    msg = str(exc.value)
    assert "Remote Control" in msg or "插件" in msg
    assert "bta_remote_api" in msg        # how to fix


def test_ellisys_complete_install_passes(tmp_path):
    (tmp_path / "Ellisys.BluetoothAnalyzer.exe").write_text("x")
    rc = tmp_path / "RemoteControl"
    rc.mkdir()
    (rc / "Ice.dll").write_text("x")
    (rc / "EllisysAnalyzerBluetoothRemoteControlPlugin.dll").write_text("x")
    validate_ellisys_install(str(tmp_path))   # no raise


# ---------------------------------------------------------------- WPS

def test_wps_missing_fts_raises_actionable(tmp_path):
    with pytest.raises(SnifferError) as exc:
        validate_wps_install(str(tmp_path))
    msg = str(exc.value)
    assert "WPS" in msg
    assert "wps-path" in msg


def test_wps_missing_devkit_raises(tmp_path):
    core = tmp_path / "Executables" / "Core"
    core.mkdir(parents=True)
    (core / "Fts.exe").write_text("x")
    (core / "LiveImportAPI_x64.dll").write_text("x")
    # no "Live Import Developers Kit" dir
    with pytest.raises(SnifferError) as exc:
        validate_wps_install(str(tmp_path))
    msg = str(exc.value)
    assert "Developer Kit" in msg or "Developers Kit" in msg or "开发包" in msg


def test_wps_complete_install_passes(tmp_path):
    core = tmp_path / "Executables" / "Core"
    core.mkdir(parents=True)
    (core / "Fts.exe").write_text("x")
    (core / "LiveImportAPI_x64.dll").write_text("x")
    devkit = tmp_path / "Live Import Developers Kit"
    devkit.mkdir()
    (devkit / "liveimport.ini").write_text("[Configuration]\nVersion=6\n")
    validate_wps_install(str(tmp_path))   # no raise
