"""Smoke tests for 'tools audio list-devices' CLI."""
import argparse
from unittest.mock import patch


def _build_parser():
    from pybluehost.cli.tools.audio import register_audio_command
    p = argparse.ArgumentParser()
    subs = p.add_subparsers(dest="cmd")
    register_audio_command(subs)
    return p


def test_audio_subcommand_registers():
    p = _build_parser()
    args = p.parse_args(["audio", "list-devices"])
    assert args.cmd == "audio"
    assert args.audio_cmd == "list-devices"


def test_list_devices_unavailable_prints_install_hint(capsys):
    from pybluehost.cli.tools.audio import _list_devices_main
    with patch("pybluehost.audio._sounddevice_io.is_available", return_value=False):
        rc = _list_devices_main()
    out = capsys.readouterr().out
    assert "sounddevice is not installed" in out
    assert "pip install" in out
    assert rc == 1


def test_list_devices_prints_when_devices_present(capsys):
    from pybluehost.cli.tools.audio import _list_devices_main
    fake = [
        {"index": 0, "name": "Default Input",  "channels_in": 2, "channels_out": 0, "samplerate": 48000.0},
        {"index": 1, "name": "Default Output", "channels_in": 0, "channels_out": 2, "samplerate": 48000.0},
    ]
    with patch("pybluehost.audio._sounddevice_io.is_available", return_value=True), \
         patch("pybluehost.audio._sounddevice_io.list_devices", return_value=fake):
        rc = _list_devices_main()
    out = capsys.readouterr().out
    assert "Default Input" in out
    assert "Default Output" in out
    assert "48000" in out
    assert rc == 0


def test_list_devices_empty_list(capsys):
    from pybluehost.cli.tools.audio import _list_devices_main
    with patch("pybluehost.audio._sounddevice_io.is_available", return_value=True), \
         patch("pybluehost.audio._sounddevice_io.list_devices", return_value=[]):
        rc = _list_devices_main()
    out = capsys.readouterr().out
    assert "No audio devices" in out
    assert rc == 0
