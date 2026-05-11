import argparse
from pathlib import Path

import pytest

from pybluehost.cli.app.bridge import DEFAULT_BRIDGE_PORT, register_bridge_command


def test_bridge_command_defaults_to_tcp_port_57123():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    register_bridge_command(subparsers)

    args = parser.parse_args(["bridge", "-t", "usb:vendor=csr"])

    assert args.cmd == "bridge"
    assert args.transport == "usb:vendor=csr"
    assert args.protocol == "tcp"
    assert args.host == "127.0.0.1"
    assert args.port == DEFAULT_BRIDGE_PORT == 57123


def test_bridge_command_accepts_udp_and_custom_port():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    register_bridge_command(subparsers)

    args = parser.parse_args(
        [
            "bridge",
            "-t",
            "uart:COM5@921600",
            "--protocol",
            "udp",
            "--host",
            "0.0.0.0",
            "--port",
            "60000",
        ]
    )

    assert args.transport == "uart:COM5@921600"
    assert args.protocol == "udp"
    assert args.host == "0.0.0.0"
    assert args.port == 60000


def test_bridge_command_accepts_btsnoop_option():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    register_bridge_command(subparsers)

    args = parser.parse_args(
        ["bridge", "-t", "usb:vendor=intel", "--btsnoop", "test.cfa"]
    )

    assert args.transport == "usb:vendor=intel"
    assert args.btsnoop == Path("test.cfa")


def test_bridge_command_help_uses_shared_uart_transport_spec(capsys):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    register_bridge_command(subparsers)

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["bridge", "--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "uart:<port>[@baud]" in out
    assert "uart:COM5@921600" not in out
