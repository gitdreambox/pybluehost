"""BLE Profile framework — base classes, decorators, YAML loader, and built-in profiles."""
from pybluehost.profiles.ble.base import BLEProfileClient, BLEProfileServer
from pybluehost.profiles.ble.decorators import (
    ble_service,
    on_indicate,
    on_notify,
    on_read,
    on_write,
)
from pybluehost.profiles.ble.yaml_loader import ServiceYAMLLoader
from pybluehost.profiles.ble.gap_service import GAPServiceServer
from pybluehost.profiles.ble.gatt_service import GATTServiceServer
from pybluehost.profiles.ble.dis import DeviceInformationClient, DeviceInformationServer
from pybluehost.profiles.ble.bas import BatteryClient, BatteryServer
from pybluehost.profiles.ble.hrs import HeartRateClient, HeartRateServer
from pybluehost.profiles.ble.bls import BloodPressureServer
from pybluehost.profiles.ble.hids import HIDServer
from pybluehost.profiles.ble.rscs import RSCServer
from pybluehost.profiles.ble.cscs import CSCServer

__all__ = [
    # framework
    "BLEProfileClient",
    "BLEProfileServer",
    "ServiceYAMLLoader",
    "ble_service",
    "on_indicate",
    "on_notify",
    "on_read",
    "on_write",
    # built-in profiles
    "BatteryClient",
    "BatteryServer",
    "BloodPressureServer",
    "CSCServer",
    "DeviceInformationClient",
    "DeviceInformationServer",
    "GAPServiceServer",
    "GATTServiceServer",
    "HIDServer",
    "HeartRateClient",
    "HeartRateServer",
    "RSCServer",
]
