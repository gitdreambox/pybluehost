"""Tests for ServiceYAMLLoader."""
from __future__ import annotations

from pathlib import Path

from pybluehost.core.uuid import UUID16
from pybluehost.profiles.ble.yaml_loader import ServiceYAMLLoader


def test_load_dis_yaml():
    path = Path(__file__).parent.parent.parent.parent / "pybluehost/profiles/ble/services/dis.yaml"
    svc = ServiceYAMLLoader.load(path)
    assert svc.uuid == UUID16(0x180A)
    assert len(svc.characteristics) == 6
    char_uuids = [c.uuid for c in svc.characteristics]
    assert UUID16(0x2A29) in char_uuids  # Manufacturer Name
    assert UUID16(0x2A24) in char_uuids  # Model Number


def test_loads_from_string():
    yaml_str = """
service:
  uuid: "0x180D"
  name: Heart Rate
  type: primary
  characteristics:
    - uuid: "0x2A37"
      name: Heart Rate Measurement
      properties:
        notify: true
"""
    svc = ServiceYAMLLoader.loads(yaml_str)
    assert svc.uuid == UUID16(0x180D)
    assert len(svc.characteristics) == 1


def test_load_builtin_hrs():
    svc = ServiceYAMLLoader.load_builtin("hrs")
    assert svc.uuid == UUID16(0x180D)
    assert len(svc.characteristics) == 3


def test_load_builtin_with_yaml_extension():
    svc = ServiceYAMLLoader.load_builtin("hrs.yaml")
    assert svc.uuid == UUID16(0x180D)


def test_load_builtin_bas():
    svc = ServiceYAMLLoader.load_builtin("bas")
    assert svc.uuid == UUID16(0x180F)
    assert len(svc.characteristics) == 1


def test_load_builtin_gap():
    svc = ServiceYAMLLoader.load_builtin("gap")
    assert svc.uuid == UUID16(0x1800)
    assert len(svc.characteristics) == 2


def test_load_builtin_gatt():
    svc = ServiceYAMLLoader.load_builtin("gatt")
    assert svc.uuid == UUID16(0x1801)
    assert len(svc.characteristics) == 1


def test_load_builtin_bls():
    svc = ServiceYAMLLoader.load_builtin("bls")
    assert svc.uuid == UUID16(0x1810)
    assert len(svc.characteristics) == 3


def test_load_builtin_hids():
    svc = ServiceYAMLLoader.load_builtin("hids")
    assert svc.uuid == UUID16(0x1812)
    assert len(svc.characteristics) == 4


def test_load_builtin_rscs():
    svc = ServiceYAMLLoader.load_builtin("rscs")
    assert svc.uuid == UUID16(0x1814)
    assert len(svc.characteristics) == 2


def test_load_builtin_cscs():
    svc = ServiceYAMLLoader.load_builtin("cscs")
    assert svc.uuid == UUID16(0x1816)
    assert len(svc.characteristics) == 2


def test_validate_bad_yaml():
    errors = ServiceYAMLLoader.validate("nonexistent.yaml")
    assert len(errors) > 0
    assert "not found" in errors[0].lower()


def test_validate_good_yaml():
    path = Path(__file__).parent.parent.parent.parent / "pybluehost/profiles/ble/services/hrs.yaml"
    errors = ServiceYAMLLoader.validate(path)
    assert errors == []
