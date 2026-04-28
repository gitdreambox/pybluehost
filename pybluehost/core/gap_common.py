"""GAP common types shared between BLE and Classic layers."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum

from pybluehost.core.address import BDAddress


# ---------------------------------------------------------------------------
# Appearance (BLE GAP)
# ---------------------------------------------------------------------------

class Appearance(IntEnum):
    UNKNOWN = 0x0000
    GENERIC_PHONE = 0x0040
    GENERIC_COMPUTER = 0x0080
    GENERIC_WATCH = 0x00C0
    SPORTS_WATCH = 0x00C1
    GENERIC_CLOCK = 0x0100
    GENERIC_DISPLAY = 0x0140
    GENERIC_REMOTE_CONTROL = 0x0180
    GENERIC_EYE_GLASSES = 0x01C0
    GENERIC_TAG = 0x0200
    GENERIC_KEYRING = 0x0240
    GENERIC_MEDIA_PLAYER = 0x0280
    GENERIC_BARCODE_SCANNER = 0x02C0
    GENERIC_THERMOMETER = 0x0300
    HEART_RATE_SENSOR = 0x0341
    BLOOD_PRESSURE = 0x0381
    GENERIC_HID = 0x03C0
    HID_KEYBOARD = 0x03C1
    HID_MOUSE = 0x03C2
    CYCLING_SPEED_CADENCE = 0x0481
    RUNNING_WALKING_SENSOR = 0x0540


# ---------------------------------------------------------------------------
# FilterPolicy
# ---------------------------------------------------------------------------

class FilterPolicy(IntEnum):
    ACCEPT_ALL = 0x00
    WHITE_LIST_ONLY = 0x01
    ACCEPT_ALL_DIRECTED_RPA = 0x02
    WHITE_LIST_DIRECTED_RPA = 0x03


# ---------------------------------------------------------------------------
# ClassOfDevice (Classic)
# ---------------------------------------------------------------------------

@dataclass
class ClassOfDevice:
    """Bluetooth Class of Device (24-bit field)."""
    major_device_class: int = 0
    minor_device_class: int = 0
    service_class: int = 0

    def to_int(self) -> int:
        return (self.service_class << 13) | (self.major_device_class << 8) | (self.minor_device_class << 2)

    @classmethod
    def from_int(cls, val: int) -> ClassOfDevice:
        return cls(
            service_class=(val >> 13) & 0x7FF,
            major_device_class=(val >> 8) & 0x1F,
            minor_device_class=(val >> 2) & 0x3F,
        )


# ---------------------------------------------------------------------------
# DeviceInfo
# ---------------------------------------------------------------------------

@dataclass
class DeviceInfo:
    """Information about a discovered device."""
    address: BDAddress
    rssi: int = 0
    name: str | None = None
    class_of_device: int = 0
    appearance: Appearance = Appearance.UNKNOWN
    services: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# AdvertisingData (AD Structure encode/decode)
# ---------------------------------------------------------------------------

class AdvertisingData:
    """BLE Advertising Data (AD) structure encode/decode.

    Each AD structure: [length][type][data...]
    """

    # AD Type constants
    AD_FLAGS = 0x01
    AD_UUID16_MORE = 0x02
    AD_UUID16_COMPLETE = 0x03
    AD_UUID32_MORE = 0x04
    AD_UUID32_COMPLETE = 0x05
    AD_UUID128_MORE = 0x06
    AD_UUID128_COMPLETE = 0x07
    AD_SHORT_LOCAL_NAME = 0x08
    AD_COMPLETE_LOCAL_NAME = 0x09
    AD_TX_POWER = 0x0A
    AD_SLAVE_CONN_INTERVAL = 0x12
    AD_APPEARANCE = 0x19
    AD_MANUFACTURER_SPECIFIC = 0xFF

    def __init__(self) -> None:
        self._structures: dict[int, bytes] = {}

    # -- Setters -------------------------------------------------------------

    def set_flags(self, flags: int) -> None:
        self._structures[self.AD_FLAGS] = bytes([flags])

    def set_complete_local_name(self, name: str) -> None:
        self._structures[self.AD_COMPLETE_LOCAL_NAME] = name.encode("utf-8")

    def set_short_local_name(self, name: str) -> None:
        self._structures[self.AD_SHORT_LOCAL_NAME] = name.encode("utf-8")

    def add_service_uuid16(self, uuid: int) -> None:
        existing = self._structures.get(self.AD_UUID16_COMPLETE, b"")
        self._structures[self.AD_UUID16_COMPLETE] = existing + struct.pack("<H", uuid)

    def set_manufacturer_specific(self, company_id: int, data: bytes) -> None:
        self._structures[self.AD_MANUFACTURER_SPECIFIC] = struct.pack("<H", company_id) + data

    def set_tx_power(self, level: int) -> None:
        self._structures[self.AD_TX_POWER] = struct.pack("b", level)

    def set_appearance(self, appearance: int) -> None:
        self._structures[self.AD_APPEARANCE] = struct.pack("<H", appearance)

    # -- Getters -------------------------------------------------------------

    def get_flags(self) -> int | None:
        data = self._structures.get(self.AD_FLAGS)
        return data[0] if data else None

    def get_complete_local_name(self) -> str | None:
        data = self._structures.get(self.AD_COMPLETE_LOCAL_NAME)
        return data.decode("utf-8") if data else None

    def get_short_local_name(self) -> str | None:
        data = self._structures.get(self.AD_SHORT_LOCAL_NAME)
        return data.decode("utf-8") if data else None

    # -- Encode/Decode -------------------------------------------------------

    def to_bytes(self) -> bytes:
        result = bytearray()
        for ad_type, data in self._structures.items():
            length = 1 + len(data)  # type byte + data
            result.append(length)
            result.append(ad_type)
            result.extend(data)
        return bytes(result)

    @classmethod
    def from_bytes(cls, data: bytes) -> AdvertisingData:
        ad = cls()
        offset = 0
        while offset < len(data):
            if data[offset] == 0:
                break
            length = data[offset]
            offset += 1
            if offset + length > len(data):
                break
            ad_type = data[offset]
            ad_data = data[offset + 1:offset + length]
            ad._structures[ad_type] = ad_data
            offset += length
        return ad
