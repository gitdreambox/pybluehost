"""Tests for BLE profile base classes and decorators."""
from __future__ import annotations

import pytest

from pybluehost.profiles.ble.base import BLEProfileClient, BLEProfileServer
from pybluehost.profiles.ble.decorators import (
    ble_service,
    on_indicate,
    on_notify,
    on_read,
    on_write,
)
from pybluehost.ble.gatt import GATTServer
from pybluehost.core.uuid import UUID16


# ---------------------------------------------------------------------------
# Test profile subclass
# ---------------------------------------------------------------------------

class HeartRateTestServer(BLEProfileServer):
    service_uuid = UUID16(0x180D)

    @on_read(UUID16(0x2A38))
    async def read_location(self) -> bytes:
        return bytes([0x01])  # Chest

    @on_write(UUID16(0x2A39))
    async def write_control_point(self, value: bytes) -> None:
        self._last_cp = value

    @on_notify(UUID16(0x2A37))
    async def hrm_stream(self) -> bytes:
        return bytes([0x00, 0x48])  # flags=0, HR=72 bpm


# ---------------------------------------------------------------------------
# Decorator tests
# ---------------------------------------------------------------------------

def test_on_read_decorator_sets_metadata():
    assert hasattr(HeartRateTestServer.read_location, "_att_read")
    assert HeartRateTestServer.read_location._att_read == UUID16(0x2A38)
    assert HeartRateTestServer.read_location._ble_callback_type == "read"


def test_on_write_decorator_sets_metadata():
    assert hasattr(HeartRateTestServer.write_control_point, "_att_write")
    assert HeartRateTestServer.write_control_point._att_write == UUID16(0x2A39)
    assert HeartRateTestServer.write_control_point._ble_callback_type == "write"


def test_on_notify_decorator_sets_metadata():
    assert hasattr(HeartRateTestServer.hrm_stream, "_att_notify")
    assert HeartRateTestServer.hrm_stream._att_notify == UUID16(0x2A37)
    assert HeartRateTestServer.hrm_stream._ble_callback_type == "notify"


def test_on_indicate_decorator_marks_method():
    @on_indicate(UUID16(0x2A05))
    async def service_changed(self) -> bytes:
        return b"\x00\x01\x00\x01"

    assert service_changed._ble_callback_type == "indicate"
    assert service_changed._ble_uuid == UUID16(0x2A05)
    assert service_changed._att_indicate == UUID16(0x2A05)


def test_ble_service_decorator_sets_yaml():
    @ble_service("hrs.yaml")
    class MyProfile(BLEProfileServer):
        service_uuid = UUID16(0x180D)

    assert MyProfile._service_yaml == "hrs.yaml"


# ---------------------------------------------------------------------------
# BLEProfileServer.register() tests
# ---------------------------------------------------------------------------

async def test_profile_register_adds_service():
    server = HeartRateTestServer()
    gatt = GATTServer()
    handles = await server.register(gatt)
    assert handles is not None
    # GATTServer db should contain attributes now
    assert len(gatt.db._attrs) > 0


async def test_profile_read_callback_populates_value():
    server = HeartRateTestServer()
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A38))
    assert handle is not None
    value = gatt.db.read(handle)
    assert value == bytes([0x01])


async def test_profile_notify_method_returns_data():
    server = HeartRateTestServer()
    data = await server.hrm_stream()
    assert data == bytes([0x00, 0x48])


async def test_profile_builds_service_definition():
    server = HeartRateTestServer()
    svc_def = server._build_service_definition()
    assert svc_def.uuid == UUID16(0x180D)
    char_uuids = [c.uuid for c in svc_def.characteristics]
    assert UUID16(0x2A38) in char_uuids
    assert UUID16(0x2A39) in char_uuids
    assert UUID16(0x2A37) in char_uuids


# ---------------------------------------------------------------------------
# BLEProfileClient tests
# ---------------------------------------------------------------------------

def test_profile_client_base():
    class TestClient(BLEProfileClient):
        service_uuid = UUID16(0x180D)

    client = TestClient()
    assert client._gatt is None
    assert client._char_handles == {}
