"""BLE GAP — advertising, scanning, connections, privacy, and white list."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable

from pybluehost.core.address import AddressType, BDAddress
from pybluehost.core.gap_common import AdvertisingData
from pybluehost.hci.constants import (
    LEMetaSubEvent,
    HCI_LE_ADD_DEVICE_TO_WHITE_LIST,
    HCI_LE_CLEAR_WHITE_LIST,
    HCI_LE_CREATE_CONNECTION,
    HCI_LE_CREATE_CONNECTION_CANCEL,
    HCI_LE_REMOVE_DEVICE_FROM_WHITE_LIST,
    HCI_LE_SET_ADVERTISE_ENABLE,
    HCI_LE_SET_ADVERTISING_DATA,
    HCI_LE_SET_ADVERTISING_PARAMS,
    HCI_LE_SET_EXTENDED_ADVERTISING_DATA,
    HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE,
    HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS,
    HCI_LE_SET_SCAN_ENABLE,
    HCI_LE_SET_SCAN_PARAMS,
)
from pybluehost.hci.packets import HCI_LE_Meta_Event, HCICommand, HCIEvent


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AdvertisingConfig:
    min_interval_ms: float = 100.0
    max_interval_ms: float = 100.0
    adv_type: int = 0x00       # ADV_IND
    channel_map: int = 0x07    # all channels
    filter_policy: int = 0x00


@dataclass
class ScanConfig:
    active: bool = False
    interval_ms: float = 100.0
    window_ms: float = 50.0
    filter_duplicates: bool = True


@dataclass
class ScanResult:
    address: BDAddress
    rssi: int
    advertising_data: AdvertisingData
    connectable: bool = True

    @property
    def local_name(self) -> str | None:
        return (
            self.advertising_data.get_complete_local_name()
            or self.advertising_data.get_short_local_name()
        )


@dataclass
class BLEConnectionConfig:
    scan_interval_ms: float = 60.0
    scan_window_ms: float = 30.0
    min_interval_ms: float = 30.0
    max_interval_ms: float = 50.0
    latency: int = 0
    supervision_timeout_ms: float = 5000.0


class ConnectionRole(IntEnum):
    CENTRAL = 0
    PERIPHERAL = 1


@dataclass
class BLEConnection:
    handle: int
    peer_address: BDAddress
    role: ConnectionRole
    att: object | None = None
    gatt_client: object | None = None
    gatt_server: object | None = None
    smp: object | None = None


@dataclass
class ExtAdvertisingConfig:
    adv_handle: int = 0
    primary_phy: int = 1       # 1=1M, 3=coded
    secondary_phy: int = 1
    adv_type: int = 0x05       # non-connectable, non-scannable, undirected
    max_skip: int = 0


# ---------------------------------------------------------------------------
# Helper: build a raw HCI command with given opcode and parameters
# ---------------------------------------------------------------------------

def _make_cmd(opcode: int, params: bytes = b"") -> HCICommand:
    """Create an HCICommand with the given opcode and parameters."""
    return HCICommand(opcode=opcode, parameters=params)


# ---------------------------------------------------------------------------
# BLEAdvertiser
# ---------------------------------------------------------------------------

class BLEAdvertiser:
    """Legacy BLE advertising controller."""

    def __init__(self, hci: object) -> None:
        self._hci = hci
        self._active = False

    async def start(
        self,
        config: AdvertisingConfig = AdvertisingConfig(),
        ad_data: AdvertisingData | None = None,
        scan_rsp_data: AdvertisingData | None = None,
    ) -> None:
        """Start advertising with the given config and data."""
        # Set advertising parameters
        min_interval = int(config.min_interval_ms / 0.625)
        max_interval = int(config.max_interval_ms / 0.625)
        params = struct.pack(
            "<HHBBB6sBB",
            min_interval, max_interval,
            config.adv_type,
            0x00,  # own address type
            0x00,  # peer address type
            bytes(6),  # peer address
            config.channel_map,
            config.filter_policy,
        )
        await self._hci.send_command(_make_cmd(HCI_LE_SET_ADVERTISING_PARAMS, params))

        # Set advertising data
        if ad_data is not None:
            raw = ad_data.to_bytes()
            ad_params = bytes([len(raw)]) + raw + bytes(31 - len(raw))
            await self._hci.send_command(_make_cmd(HCI_LE_SET_ADVERTISING_DATA, ad_params))
        else:
            await self._hci.send_command(_make_cmd(HCI_LE_SET_ADVERTISING_DATA, bytes(32)))

        # Enable advertising
        await self._hci.send_command(_make_cmd(HCI_LE_SET_ADVERTISE_ENABLE, bytes([0x01])))
        self._active = True

    async def stop(self) -> None:
        """Stop advertising."""
        await self._hci.send_command(_make_cmd(HCI_LE_SET_ADVERTISE_ENABLE, bytes([0x00])))
        self._active = False

    async def update_data(self, ad_data: AdvertisingData) -> None:
        """Update advertising data while advertising."""
        raw = ad_data.to_bytes()
        ad_params = bytes([len(raw)]) + raw + bytes(31 - len(raw))
        await self._hci.send_command(_make_cmd(HCI_LE_SET_ADVERTISING_DATA, ad_params))


# ---------------------------------------------------------------------------
# BLEScanner
# ---------------------------------------------------------------------------

class BLEScanner:
    """BLE scanning controller."""

    def __init__(self, hci: object) -> None:
        self._hci = hci
        self._handlers: list[Callable[[ScanResult], object]] = []
        self._active = False

    def on_result(self, handler: Callable[[ScanResult], object]) -> None:
        self._handlers.append(handler)

    async def on_hci_event(self, event: HCIEvent) -> None:
        if not isinstance(event, HCI_LE_Meta_Event):
            return
        if event.subevent_code != LEMetaSubEvent.LE_ADVERTISING_REPORT:
            return
        await self._on_legacy_advertising_report(event.subevent_parameters)

    async def start(self, config: ScanConfig = ScanConfig()) -> None:
        """Start scanning."""
        interval = int(config.interval_ms / 0.625)
        window = int(config.window_ms / 0.625)
        scan_type = 0x01 if config.active else 0x00
        params = struct.pack("<BHHBB", scan_type, interval, window, 0x00, 0x00)
        await self._hci.send_command(_make_cmd(HCI_LE_SET_SCAN_PARAMS, params))
        enable = bytes([0x01, 0x01 if config.filter_duplicates else 0x00])
        await self._hci.send_command(_make_cmd(HCI_LE_SET_SCAN_ENABLE, enable))
        self._active = True

    async def stop(self) -> None:
        """Stop scanning."""
        await self._hci.send_command(_make_cmd(HCI_LE_SET_SCAN_ENABLE, bytes([0x00, 0x00])))
        self._active = False

    async def _on_advertising_report(self, result: ScanResult) -> None:
        """Called by HCI event router when an advertising report arrives."""
        for handler in self._handlers:
            handler(result)

    async def _on_legacy_advertising_report(self, data: bytes) -> None:
        if not data:
            return
        count = data[0]
        offset = 1
        for _ in range(count):
            if offset + 10 > len(data):
                return
            event_type = data[offset]
            address_type = data[offset + 1]
            address = data[offset + 2 : offset + 8]
            data_len = data[offset + 8]
            offset += 9
            if offset + data_len + 1 > len(data):
                return
            ad_data = AdvertisingData.from_bytes(data[offset : offset + data_len])
            offset += data_len
            rssi = struct.unpack("b", data[offset : offset + 1])[0]
            offset += 1
            result = ScanResult(
                address=BDAddress(address, AddressType(address_type)),
                rssi=rssi,
                advertising_data=ad_data,
                connectable=event_type in (0x00, 0x01, 0x04),
            )
            await self._on_advertising_report(result)

    async def scan_for(
        self, duration: float, config: ScanConfig = ScanConfig(),
    ) -> list[ScanResult]:
        """Scan for a given duration and return collected results."""
        import asyncio
        collected: list[ScanResult] = []
        self.on_result(lambda r: collected.append(r))
        await self.start(config)
        await asyncio.sleep(duration)
        await self.stop()
        return collected


# ---------------------------------------------------------------------------
# BLEConnectionManager
# ---------------------------------------------------------------------------

class BLEConnectionManager:
    """Manages BLE connections (create, cancel, disconnect)."""

    def __init__(self, hci: object) -> None:
        self._hci = hci
        self._connections: dict[int, BLEConnection] = {}
        self._on_connection_handler: Callable[[BLEConnection], object] | None = None

    def on_connection(self, handler: Callable[[BLEConnection], object]) -> None:
        self._on_connection_handler = handler

    async def connect(
        self,
        target: BDAddress,
        config: BLEConnectionConfig = BLEConnectionConfig(),
    ) -> None:
        """Initiate a connection to a target device."""
        scan_interval = int(config.scan_interval_ms / 0.625)
        scan_window = int(config.scan_window_ms / 0.625)
        min_interval = int(config.min_interval_ms / 1.25)
        max_interval = int(config.max_interval_ms / 1.25)
        supervision = int(config.supervision_timeout_ms / 10)
        params = struct.pack(
            "<HHBB6sBHHHHHH",
            scan_interval, scan_window,
            0x00,  # filter policy
            target.type,  # peer address type
            target.address[::-1],  # HCI peer address is little-endian on the wire
            0x00,  # own address type
            min_interval, max_interval,
            config.latency,
            supervision,
            0x0000, 0x0000,  # min/max CE length
        )
        await self._hci.send_command(_make_cmd(HCI_LE_CREATE_CONNECTION, params))

    async def cancel_connect(self) -> None:
        await self._hci.send_command(_make_cmd(HCI_LE_CREATE_CONNECTION_CANCEL))

    async def disconnect(self, handle: int, reason: int = 0x13) -> None:
        from pybluehost.hci.constants import HCI_DISCONNECT
        params = struct.pack("<HB", handle, reason)
        await self._hci.send_command(_make_cmd(HCI_DISCONNECT, params))
        self._connections.pop(handle, None)


# ---------------------------------------------------------------------------
# PrivacyManager
# ---------------------------------------------------------------------------

class PrivacyManager:
    """BLE privacy (RPA generation and resolution)."""

    def __init__(self, hci: object | None = None) -> None:
        self._hci = hci
        self._enabled = False

    async def enable(self, irk: bytes | None = None) -> None:
        self._enabled = True

    async def disable(self) -> None:
        self._enabled = False

    @staticmethod
    def resolve_rpa(rpa: bytes, irk: bytes) -> bool:
        """Check if an RPA was generated with the given IRK.

        RPA format: hash(3 bytes) || prand(3 bytes).
        Verify: ah(IRK, prand) == hash.
        """
        from pybluehost.ble.smp import SMPCrypto
        rpa_hash = rpa[0:3]
        prand = rpa[3:6]
        computed = SMPCrypto.ah(irk, prand)
        return computed == rpa_hash


# ---------------------------------------------------------------------------
# WhiteList
# ---------------------------------------------------------------------------

class WhiteList:
    """BLE White List management via HCI commands."""

    def __init__(self, hci: object) -> None:
        self._hci = hci
        self._entries: list[tuple[BDAddress, int]] = []

    async def add(self, address: BDAddress, address_type: int = 0x00) -> None:
        params = bytes([address_type]) + address.address
        await self._hci.send_command(_make_cmd(HCI_LE_ADD_DEVICE_TO_WHITE_LIST, params))
        self._entries.append((address, address_type))

    async def remove(self, address: BDAddress, address_type: int = 0x00) -> None:
        params = bytes([address_type]) + address.address
        await self._hci.send_command(_make_cmd(HCI_LE_REMOVE_DEVICE_FROM_WHITE_LIST, params))
        self._entries = [(a, t) for a, t in self._entries if a != address]

    async def clear(self) -> None:
        await self._hci.send_command(_make_cmd(HCI_LE_CLEAR_WHITE_LIST))
        self._entries.clear()

    @property
    def entries(self) -> list[tuple[BDAddress, int]]:
        return list(self._entries)


# ---------------------------------------------------------------------------
# ExtendedAdvertiser (BT 5.0+)
# ---------------------------------------------------------------------------

class ExtendedAdvertiser:
    """BT 5.0 Extended Advertising — multiple advertising sets, coded PHY."""

    def __init__(self, hci: object) -> None:
        self._hci = hci
        self._sets: dict[int, ExtAdvertisingConfig] = {}

    async def create_set(self, config: ExtAdvertisingConfig) -> None:
        """Create an advertising set with the given parameters."""
        params = struct.pack(
            "<BBBBB",
            config.adv_handle,
            config.adv_type,
            config.primary_phy,
            config.secondary_phy,
            config.max_skip,
        )
        await self._hci.send_command(
            _make_cmd(HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS, params)
        )
        self._sets[config.adv_handle] = config

    async def set_data(self, handle: int, ad_data: AdvertisingData) -> None:
        raw = ad_data.to_bytes()
        params = struct.pack("<BBB", handle, 0x03, len(raw)) + raw  # 0x03 = complete
        await self._hci.send_command(
            _make_cmd(HCI_LE_SET_EXTENDED_ADVERTISING_DATA, params)
        )

    async def start(
        self,
        handles: list[int],
        durations: list[float] | None = None,
    ) -> None:
        """Start extended advertising on the given handles."""
        num_sets = len(handles)
        params = bytearray([0x01, num_sets])  # enable=1, num_sets
        for i, h in enumerate(handles):
            duration = int((durations[i] if durations else 0) * 100)  # in 10ms units
            params.extend(struct.pack("<BHB", h, duration, 0))
        await self._hci.send_command(
            _make_cmd(HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE, bytes(params))
        )

    async def stop(self, handles: list[int] | None = None) -> None:
        """Stop extended advertising."""
        if handles is None:
            handles = list(self._sets.keys())
        num_sets = len(handles)
        params = bytearray([0x00, num_sets])  # enable=0
        for h in handles:
            params.extend(struct.pack("<BHB", h, 0, 0))
        await self._hci.send_command(
            _make_cmd(HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE, bytes(params))
        )

    async def remove_set(self, handle: int) -> None:
        self._sets.pop(handle, None)
