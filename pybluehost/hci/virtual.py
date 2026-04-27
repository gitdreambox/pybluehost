"""VirtualController — software-only HCI controller for testing.

Processes HCI commands and returns synthetic Command Complete events,
allowing full HCI stack testing without hardware.
"""

from __future__ import annotations

import struct
from typing import Callable

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    ErrorCode,
    HCI_COMMAND_PACKET,
    HCI_HOST_BUFFER_SIZE,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_LE_SET_EVENT_MASK,
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_READ_BD_ADDR,
    HCI_READ_BUFFER_SIZE,
    HCI_READ_LOCAL_SUPPORTED_COMMANDS,
    HCI_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_READ_LOCAL_VERSION,
    HCI_RESET,
    HCI_SET_EVENT_MASK,
    HCI_WRITE_LE_HOST_SUPPORTED,
    HCI_WRITE_SCAN_ENABLE,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
)
from pybluehost.hci.packets import (
    HCI_Command_Complete_Event,
    HCICommand,
    decode_hci_packet,
)
from pybluehost.transport.base import Transport, TransportInfo


class VirtualController:
    """Software-only HCI controller for testing.

    Accepts raw H4+HCI command bytes, decodes the command, dispatches to a
    handler, and returns raw H4+HCI Command Complete event bytes.
    """

    def __init__(self, address: BDAddress) -> None:
        self._address = address
        self._handlers: dict[int, Callable[[HCICommand], bytes]] = {
            HCI_RESET: self._handle_reset,
            HCI_READ_BD_ADDR: self._handle_read_bd_addr,
            HCI_READ_LOCAL_VERSION: self._handle_read_local_version,
            HCI_READ_BUFFER_SIZE: self._handle_read_buffer_size,
            HCI_LE_READ_BUFFER_SIZE: self._handle_le_read_buffer_size,
            HCI_READ_LOCAL_SUPPORTED_COMMANDS: self._handle_read_local_supported_commands,
            HCI_READ_LOCAL_SUPPORTED_FEATURES: self._handle_read_local_supported_features,
            HCI_LE_READ_LOCAL_SUPPORTED_FEATURES: self._handle_le_read_local_supported_features,
            HCI_SET_EVENT_MASK: self._handle_status_only,
            HCI_LE_SET_EVENT_MASK: self._handle_status_only,
            HCI_WRITE_LE_HOST_SUPPORTED: self._handle_status_only,
            HCI_WRITE_SIMPLE_PAIRING_MODE: self._handle_status_only,
            HCI_WRITE_SCAN_ENABLE: self._handle_status_only,
            HCI_HOST_BUFFER_SIZE: self._handle_status_only,
            HCI_LE_SET_SCAN_PARAMS: self._handle_status_only,
            HCI_LE_SET_RANDOM_ADDRESS: self._handle_status_only,
        }

    @classmethod
    async def create(
        cls,
        address: BDAddress | None = None,
    ) -> tuple["VirtualController", Transport]:
        """Create a VirtualController with an opened host-side transport."""
        if address is None:
            address = BDAddress.from_string("AA:BB:CC:DD:EE:01")
        vc = cls(address=address)
        host_t, ctrl_t = _HCIPipe.pair()

        class _VCSink:
            async def on_transport_data(self, data: bytes) -> None:
                response = await vc.process(data)
                if response is not None and host_t._sink is not None:
                    await host_t._sink.on_transport_data(response)

        ctrl_t.set_sink(_VCSink())
        await host_t.open()
        await ctrl_t.open()
        return vc, host_t

    async def process(self, data: bytes) -> bytes | None:
        """Process raw H4+HCI bytes and return a Command Complete response.

        Returns None if the packet is not a command.
        """
        if not data or data[0] != HCI_COMMAND_PACKET:
            return None

        packet = decode_hci_packet(data)
        if not isinstance(packet, HCICommand):
            return None

        opcode = packet.opcode
        handler = self._handlers.get(opcode)
        if handler is not None:
            return_params = handler(packet)
        else:
            return_params = bytes([ErrorCode.UNKNOWN_COMMAND])

        return self._make_command_complete(opcode, return_params)

    def _make_command_complete(self, opcode: int, return_params: bytes) -> bytes:
        """Build a full H4+HCI Command Complete event."""
        event = HCI_Command_Complete_Event(
            num_hci_command_packets=1,
            command_opcode=opcode,
            return_parameters=return_params,
        )
        return event.to_bytes()

    # -- Handlers --------------------------------------------------------------

    def _handle_status_only(self, cmd: HCICommand) -> bytes:
        """Handler for commands that only return a status byte."""
        return b"\x00"

    def _handle_reset(self, cmd: HCICommand) -> bytes:
        return b"\x00"

    def _handle_read_bd_addr(self, cmd: HCICommand) -> bytes:
        # Address in HCI is little-endian (reversed from network order)
        return b"\x00" + bytes(reversed(self._address.address))

    def _handle_read_local_version(self, cmd: HCICommand) -> bytes:
        # status + HCI_Version(1) + HCI_Revision(2) + LMP_Version(1) + Manufacturer(2) + LMP_Subversion(2)
        return b"\x00" + struct.pack("<BHBHH", 0x0C, 0x0001, 0x0C, 0xFFFF, 0x0001)

    def _handle_read_buffer_size(self, cmd: HCICommand) -> bytes:
        # status + acl_data_packet_length(2) + sco_data_packet_length(1) + total_num_acl(2) + total_num_sco(2)
        return b"\x00" + struct.pack("<HBHH", 1024, 64, 8, 4)

    def _handle_le_read_buffer_size(self, cmd: HCICommand) -> bytes:
        # status + le_acl_data_packet_length(2) + total_num_le_acl(1)
        return b"\x00" + struct.pack("<HB", 251, 8)

    def _handle_read_local_supported_commands(self, cmd: HCICommand) -> bytes:
        # status + 64 bytes of supported commands bitmap
        return b"\x00" + b"\x00" * 64

    def _handle_read_local_supported_features(self, cmd: HCICommand) -> bytes:
        # status + 8 bytes of LMP features
        return b"\x00" + b"\x00" * 8

    def _handle_le_read_local_supported_features(self, cmd: HCICommand) -> bytes:
        # status + 8 bytes of LE features
        return b"\x00" + b"\x00" * 8


class _HCIPipe(Transport):
    """Private in-memory pipe used by VirtualController.create()."""

    def __init__(self) -> None:
        super().__init__()
        self._peer: "_HCIPipe | None" = None
        self._open = False

    @classmethod
    def pair(cls) -> tuple["_HCIPipe", "_HCIPipe"]:
        a = cls()
        b = cls()
        a._peer = b
        b._peer = a
        return a, b

    async def open(self) -> None:
        self._open = True

    async def close(self) -> None:
        self._open = False

    async def send(self, data: bytes) -> None:
        if not self._open:
            raise RuntimeError("_HCIPipe not open")
        if self._peer is None:
            raise RuntimeError("_HCIPipe has no peer")
        if self._peer._open and self._peer._sink is not None:
            await self._peer._sink.on_transport_data(data)

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="virtual",
            description="VirtualController pipe",
            platform="any",
            details={},
        )
