"""Tests for 'app gatt-browser' command."""
import argparse
import pytest
from pybluehost.cli.app.gatt_browser import _gatt_browser_main


async def test_gatt_browser_virtual_prints_battery_service(capsys):
    args = argparse.Namespace(transport="virtual", target=None)
    rc = await _gatt_browser_main(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "0x180F" in out or "180F" in out.upper() or "Battery" in out


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

    fake_stack = FakeStack()

    async def build_stack(transport_arg):
        assert transport_arg == "usb:vendor=csr"
        return fake_stack

    monkeypatch.setattr("pybluehost.cli.app.gatt_browser._build_stack", build_stack)

    args = argparse.Namespace(
        transport="usb:vendor=csr",
        target="11:22:33:44:55:66/public",
    )
    rc = await _gatt_browser_main(args)

    out = capsys.readouterr().out
    assert rc == 0
    assert "Connected to 11:22:33:44:55:66" in out
    assert "Service 0x180F" in out
    assert "not implemented" not in out
    assert fake_stack.closed


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

    async def build_stack(transport_arg):
        return FakeStack()

    monkeypatch.setattr("pybluehost.cli.app.gatt_browser._build_stack", build_stack)

    args = argparse.Namespace(
        transport="usb:vendor=csr",
        target="11:22:33:44:55:66/public",
    )
    rc = await _gatt_browser_main(args)

    out = capsys.readouterr().out
    assert rc == 0
    assert "Char 0x2A19" in out
    assert "Descriptor 0x2902" in out
