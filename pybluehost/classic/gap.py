"""Classic GAP — inquiry, discoverability, connections, and SSP."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable

from pybluehost.core.address import BDAddress
from pybluehost.core.gap_common import ClassOfDevice, DeviceInfo
from pybluehost.hci.constants import (
    HCI_ACCEPT_CONNECTION_REQ,
    HCI_CREATE_CONNECTION,
    HCI_INQUIRY,
    HCI_INQUIRY_CANCEL,
    HCI_IO_CAPABILITY_REQUEST_REPLY,
    HCI_REMOTE_NAME_REQUEST,
    HCI_USER_CONFIRMATION_REQUEST_REPLY,
    HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY,
    HCI_WRITE_CLASS_OF_DEVICE,
    HCI_WRITE_EXTENDED_INQUIRY_RESPONSE,
    HCI_WRITE_LOCAL_NAME,
    HCI_WRITE_SCAN_ENABLE,
)
from pybluehost.hci.packets import HCICommand


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_cmd(opcode: int, params: bytes = b"") -> HCICommand:
    return HCICommand(opcode=opcode, parameters=params)


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class InquiryConfig:
    """Inquiry parameters."""
    lap: int = 0x9E8B33  # GIAC
    duration: int = 8  # * 1.28s = ~10s
    max_responses: int = 0  # 0 = unlimited


class ScanEnableFlags(IntEnum):
    """HCI Write_Scan_Enable bit flags."""
    NO_SCANS = 0x00
    INQUIRY_SCAN_ONLY = 0x01
    PAGE_SCAN_ONLY = 0x02
    INQUIRY_AND_PAGE_SCAN = 0x03


class SSPMethod(IntEnum):
    """Secure Simple Pairing methods."""
    JUST_WORKS = 0
    NUMERIC_COMPARISON = 1
    PASSKEY_ENTRY = 2
    OOB = 3


@dataclass
class ClassicConnection:
    """A Classic Bluetooth ACL connection."""
    handle: int
    peer_address: BDAddress
    link_type: int = 0x01  # ACL
    encrypted: bool = False


# ---------------------------------------------------------------------------
# ClassicDiscovery
# ---------------------------------------------------------------------------

class ClassicDiscovery:
    """Classic Bluetooth inquiry (device discovery)."""

    def __init__(self, hci: object) -> None:
        self._hci = hci
        self._handlers: list[Callable[[DeviceInfo], object]] = []
        self._active = False

    def on_result(self, handler: Callable[[DeviceInfo], object]) -> None:
        self._handlers.append(handler)

    async def start(self, config: InquiryConfig = InquiryConfig()) -> None:
        """Start inquiry."""
        lap_bytes = config.lap.to_bytes(3, "little")
        params = lap_bytes + bytes([config.duration, config.max_responses])
        await self._hci.send_command(_make_cmd(HCI_INQUIRY, params))
        self._active = True

    async def stop(self) -> None:
        """Cancel ongoing inquiry."""
        await self._hci.send_command(_make_cmd(HCI_INQUIRY_CANCEL))
        self._active = False

    async def request_remote_name(self, address: BDAddress) -> None:
        """Send Remote_Name_Request for a device."""
        params = address.address + bytes([
            0x01,  # page scan repetition mode R1
            0x00,  # reserved
            0x00, 0x00,  # clock offset
        ])
        await self._hci.send_command(_make_cmd(HCI_REMOTE_NAME_REQUEST, params))

    async def _on_inquiry_result(self, info: DeviceInfo) -> None:
        """Called by HCI event router on inquiry result."""
        for handler in self._handlers:
            handler(info)


# ---------------------------------------------------------------------------
# ClassicDiscoverability
# ---------------------------------------------------------------------------

class ClassicDiscoverability:
    """Controls Classic BT discoverability and page scan."""

    def __init__(self, hci: object) -> None:
        self._hci = hci
        self._scan_enable: int = ScanEnableFlags.NO_SCANS

    async def set_discoverable(self, enabled: bool) -> None:
        """Enable or disable inquiry scan (discoverability)."""
        if enabled:
            self._scan_enable |= ScanEnableFlags.INQUIRY_SCAN_ONLY
        else:
            self._scan_enable &= ~ScanEnableFlags.INQUIRY_SCAN_ONLY
        await self._hci.send_command(
            _make_cmd(HCI_WRITE_SCAN_ENABLE, bytes([self._scan_enable]))
        )

    async def set_connectable(self, enabled: bool) -> None:
        """Enable or disable page scan (connectability)."""
        if enabled:
            self._scan_enable |= ScanEnableFlags.PAGE_SCAN_ONLY
        else:
            self._scan_enable &= ~ScanEnableFlags.PAGE_SCAN_ONLY
        await self._hci.send_command(
            _make_cmd(HCI_WRITE_SCAN_ENABLE, bytes([self._scan_enable]))
        )

    async def set_device_name(self, name: str) -> None:
        """Set the local device name via HCI_Write_Local_Name."""
        name_bytes = name.encode("utf-8")[:248]
        padded = name_bytes + bytes(248 - len(name_bytes))
        await self._hci.send_command(_make_cmd(HCI_WRITE_LOCAL_NAME, padded))

    async def set_class_of_device(self, cod: ClassOfDevice) -> None:
        """Set the Class of Device."""
        cod_bytes = cod.to_int().to_bytes(3, "little")
        await self._hci.send_command(_make_cmd(HCI_WRITE_CLASS_OF_DEVICE, cod_bytes))

    async def set_extended_inquiry_response(self, eir_data: bytes) -> None:
        """Set the Extended Inquiry Response data."""
        fec = bytes([0x01])  # FEC required
        padded = eir_data[:240] + bytes(240 - min(len(eir_data), 240))
        await self._hci.send_command(
            _make_cmd(HCI_WRITE_EXTENDED_INQUIRY_RESPONSE, fec + padded)
        )


# ---------------------------------------------------------------------------
# ClassicConnectionManager
# ---------------------------------------------------------------------------

class ClassicConnectionManager:
    """Manages Classic Bluetooth ACL connections."""

    def __init__(self, hci: object) -> None:
        self._hci = hci
        self._connections: dict[int, ClassicConnection] = {}
        self._on_connection_handler: Callable[[ClassicConnection], object] | None = None

    def on_connection(self, handler: Callable[[ClassicConnection], object]) -> None:
        self._on_connection_handler = handler

    async def connect(self, target: BDAddress, allow_role_switch: bool = True) -> None:
        """Initiate an ACL connection to a remote device."""
        params = (
            target.address
            + struct.pack("<H", 0x0018)  # packet type: DM1, DH1
            + bytes([0x01])  # page scan repetition mode R1
            + bytes([0x00])  # reserved
            + struct.pack("<H", 0x0000)  # clock offset
            + bytes([0x01 if allow_role_switch else 0x00])
        )
        await self._hci.send_command(_make_cmd(HCI_CREATE_CONNECTION, params))

    async def accept(self, address: BDAddress, role: int = 0x01) -> None:
        """Accept an incoming connection request."""
        params = address.address + bytes([role])
        await self._hci.send_command(_make_cmd(HCI_ACCEPT_CONNECTION_REQ, params))

    async def disconnect(self, handle: int, reason: int = 0x13) -> None:
        """Disconnect an ACL connection."""
        from pybluehost.hci.constants import HCI_DISCONNECT
        params = struct.pack("<HB", handle, reason)
        await self._hci.send_command(_make_cmd(HCI_DISCONNECT, params))
        self._connections.pop(handle, None)


# ---------------------------------------------------------------------------
# SSPManager
# ---------------------------------------------------------------------------

class SSPManager:
    """Secure Simple Pairing manager."""

    def __init__(self, hci: object) -> None:
        self._hci = hci
        self._io_capability: int = 0x03  # NoInputNoOutput
        self._confirm_handler: Callable[[BDAddress, int], bool] | None = None

    def set_io_capability(self, cap: int) -> None:
        """Set local IO capability (0x00=Display+Yes/No, 0x03=NoInputNoOutput, etc.)."""
        self._io_capability = cap

    def on_user_confirmation(
        self, handler: Callable[[BDAddress, int], bool]
    ) -> None:
        """Register handler for numeric comparison confirmation requests."""
        self._confirm_handler = handler

    async def reply_io_capability(
        self, address: BDAddress, oob_present: bool = False
    ) -> None:
        """Reply to an IO Capability Request event."""
        params = (
            address.address
            + bytes([self._io_capability])
            + bytes([0x01 if oob_present else 0x00])
            + bytes([0x05])  # auth req: MITM + Bonding
        )
        await self._hci.send_command(
            _make_cmd(HCI_IO_CAPABILITY_REQUEST_REPLY, params)
        )

    async def confirm(self, address: BDAddress) -> None:
        """Accept a user confirmation request (numeric comparison)."""
        await self._hci.send_command(
            _make_cmd(HCI_USER_CONFIRMATION_REQUEST_REPLY, address.address)
        )

    async def deny(self, address: BDAddress) -> None:
        """Reject a user confirmation request."""
        await self._hci.send_command(
            _make_cmd(
                HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY, address.address
            )
        )
