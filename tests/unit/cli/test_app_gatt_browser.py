"""Tests for 'app gatt-browser' command."""
import argparse
import pytest
from pybluehost.cli.app.gatt_browser import _gatt_browser_main


async def test_gatt_browser_loopback_prints_battery_service(capsys):
    args = argparse.Namespace(transport="loopback", target=None)
    rc = await _gatt_browser_main(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "0x180F" in out or "180F" in out.upper() or "Battery" in out
