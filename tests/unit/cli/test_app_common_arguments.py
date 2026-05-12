import argparse

import pytest

from pybluehost.cli.app import register_app_commands


APP_COMMANDS = [
    "ble-scan",
    "ble-adv",
    "classic-inquiry",
    "gatt-browser",
    "sdp-browser",
    "gatt-server",
    "hr-monitor",
    "spp-echo",
    "bridge",
]


@pytest.mark.parametrize("app_command", APP_COMMANDS)
def test_app_transport_help_uses_canonical_transport_name(app_command, capsys):
    parser = argparse.ArgumentParser(prog="pybluehost")
    subparsers = parser.add_subparsers(dest="command")
    register_app_commands(subparsers)

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["app", app_command, "--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "usb[:VID:PID#N]" in out
    assert "uart:<port>[@baud]" in out
    assert "usb[:vendor=...]" not in out
    assert "--hci-log" in out
    assert "--btsnoop" in out
