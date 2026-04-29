"""Tests for 'app gatt-browser' command."""
import argparse
import asyncio
import logging
from pathlib import Path

import pytest
from pybluehost.cli.app.gatt_browser import _gatt_browser_main, register_gatt_browser_command

logger = logging.getLogger(__name__)


def test_gatt_browser_parser_has_target_example_and_trace_options():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    register_gatt_browser_command(subparsers)

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["gatt-browser", "--help"])
    assert exc.value.code == 0
    args = parser.parse_args(
        [
            "gatt-browser",
            "-t",
            "usb:vendor=csr",
            "-a",
            "A0:90:B5:10:40:82",
            "--hci-log",
            "--btsnoop",
            "gatt.cfa",
        ]
    )

    # Re-parse help through capsys is not available here, so inspect action metadata too.
    gatt_parser = next(
        action.choices["gatt-browser"]
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    target_action = next(action for action in gatt_parser._actions if "--target" in action.option_strings)
    assert "A0:90:B5:10:40:82" in target_action.help
    assert "A090B5104082" in target_action.help
    assert args.hci_log is True
    assert args.btsnoop == Path("gatt.cfa")


async def test_gatt_browser_requires_target_for_all_transports(capsys):
    args = argparse.Namespace(transport="virtual", target=None)
    rc = await _gatt_browser_main(args)
    err = capsys.readouterr().err
    assert rc == 2
    assert "--target is required" in err


async def test_gatt_browser_real_transport_discovers_services(monkeypatch, capsys):
    class FakeClient:
        async def discover_all_services(self):
            return [(0x0001, 0x0005, b"\x0f\x18")]

        async def discover_characteristics(self, start_handle, end_handle):
            return []

        async def discover_descriptors(self, start_handle, end_handle):
            return []

    class FakeStack:
        closed = False

        async def connect_gatt(self, target):
            return FakeClient()

        async def close(self):
            self.closed = True

    async def run_app(transport_arg, main_coro, **kwargs):
        assert transport_arg == "usb:vendor=csr"
        assert kwargs == {"hci_log": False, "btsnoop": None}
        await main_coro(FakeStack(), asyncio.Event())
        return 0

    monkeypatch.setattr("pybluehost.cli.app.gatt_browser.run_app_command", run_app)

    args = argparse.Namespace(
        transport="usb:vendor=csr",
        target="11:22:33:44:55:66/public",
        hci_log=False,
        btsnoop=None,
    )
    rc = await _gatt_browser_main(args)

    out = capsys.readouterr().out
    assert rc == 0
    assert "Connected to 11:22:33:44:55:66" in out
    assert "Service 0x180F" in out
    assert "not implemented" not in out


async def test_gatt_browser_real_transport_prints_characteristics_and_descriptors(monkeypatch, capsys):
    class FakeCharacteristic:
        declaration_handle = 0x0002
        value_handle = 0x0003
        properties = 0x12
        uuid = b"\x19\x2a"

    class FakeDescriptor:
        handle = 0x0004
        uuid = b"\x02\x29"

    class FakeClient:
        async def discover_all_services(self):
            return [(0x0001, 0x0005, b"\x0f\x18")]

        async def discover_characteristics(self, start_handle, end_handle):
            return [FakeCharacteristic()]

        async def discover_descriptors(self, start_handle, end_handle):
            return [FakeDescriptor()]

    class FakeStack:
        async def connect_gatt(self, target):
            return FakeClient()

        async def close(self):
            pass

    async def run_app(transport_arg, main_coro, **kwargs):
        await main_coro(FakeStack(), asyncio.Event())
        return 0

    monkeypatch.setattr("pybluehost.cli.app.gatt_browser.run_app_command", run_app)

    args = argparse.Namespace(
        transport="usb:vendor=csr",
        target="11:22:33:44:55:66/public",
        hci_log=False,
        btsnoop=None,
    )
    rc = await _gatt_browser_main(args)

    out = capsys.readouterr().out
    assert rc == 0
    assert "Char 0x2A19" in out
    assert "props=0x12 READ|NOTIFY" in out
    assert "Descriptor 0x2902" in out


async def test_gatt_browser_prints_meaningful_timeout(monkeypatch, capsys, caplog):
    class FakeStack:
        def on_connection_event(self, handler):
            pass

        async def connect_gatt(self, target):
            raise asyncio.TimeoutError()

        async def close(self):
            pass

    async def run_app(transport_arg, main_coro, **kwargs):
        try:
            await main_coro(FakeStack(), asyncio.Event())
        except Exception as e:
            logger.error("Error: %s", e)
            return 1
        return 0

    monkeypatch.setattr("pybluehost.cli.app.gatt_browser.run_app_command", run_app)

    args = argparse.Namespace(
        transport="usb:vendor=csr",
        target="11:22:33:44:55:66/public",
        hci_log=False,
        btsnoop=None,
    )
    rc = await _gatt_browser_main(args)

    capsys.readouterr()
    assert rc == 1
    assert "Timed out waiting for BLE connection or GATT response" in caplog.text


async def test_gatt_browser_prints_connection_events(monkeypatch, capsys, caplog):
    class FakeEvent:
        state = "disconnected"
        handle = 0x0041
        reason = "FAILED_TO_ESTABLISH_CONNECTION (0x3E)"

    class FakeStack:
        def on_connection_event(self, handler):
            handler(FakeEvent())

        async def connect_gatt(self, target):
            raise RuntimeError("LE connection failed: FAILED_TO_ESTABLISH_CONNECTION (0x3E)")

        async def close(self):
            pass

    async def run_app(transport_arg, main_coro, **kwargs):
        try:
            await main_coro(FakeStack(), asyncio.Event())
        except Exception as e:
            logger.error("Error: %s", e)
            return 1
        return 0

    monkeypatch.setattr("pybluehost.cli.app.gatt_browser.run_app_command", run_app)

    args = argparse.Namespace(
        transport="usb:vendor=csr",
        target="11:22:33:44:55:66/public",
        hci_log=False,
        btsnoop=None,
    )
    rc = await _gatt_browser_main(args)

    captured = capsys.readouterr()
    assert rc == 1
    assert "Disconnected handle=0x0041 reason=FAILED_TO_ESTABLISH_CONNECTION (0x3E)" in captured.err
    assert "LE connection failed: FAILED_TO_ESTABLISH_CONNECTION (0x3E)" in caplog.text
