"""VirtualController — software-only HCI controller for testing.

Processes HCI commands and returns synthetic Command Complete events,
allowing full HCI stack testing without hardware.
"""

from __future__ import annotations

import asyncio
import struct
from typing import Callable

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    ErrorCode,
    EventCode,
    HCI_ACL_PACKET,
    HCI_COMMAND_PACKET,
    HCI_HOST_BUFFER_SIZE,
    HCI_LE_LONG_TERM_KEY_REQUEST_NEGATIVE_REPLY,
    HCI_LE_LONG_TERM_KEY_REQUEST_REPLY,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_LE_SET_EVENT_MASK,
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_LE_START_ENCRYPTION,
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
    LEMetaSubEvent,
)
from pybluehost.hci.packets import (
    HCI_Command_Complete_Event,
    HCI_Command_Status_Event,
    HCI_LE_LTK_Request_Negative_Reply_Command,
    HCI_LE_LTK_Request_Reply_Command,
    HCI_LE_Start_Encryption_Command,
    HCIACLData,
    HCICommand,
    HCIEvent,
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
        self._host_sink: object | None = None  # set by create(); used for async event injection
        self._acl_forwarder = None  # set by VirtualLELink to bridge ACL frames
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
        # Give the controller a way to push async events to the host
        vc._host_sink = host_t._sink  # type: ignore[attr-defined]
        # Intercept future sink assignments so the reference stays current
        _orig_set_sink = host_t.set_sink

        def _patched_set_sink(sink: object) -> None:
            _orig_set_sink(sink)
            vc._host_sink = sink

        host_t.set_sink = _patched_set_sink  # type: ignore[method-assign]
        return vc, host_t

    async def _send_event_to_host(self, event: HCIEvent) -> None:
        """Push a raw HCI event to the host-side sink."""
        sink = self._host_sink
        if sink is not None:
            await sink.on_transport_data(event.to_bytes())  # type: ignore[union-attr]

    def set_acl_forwarder(self, forwarder) -> None:
        """Register an async callback invoked with each ACL frame coming from the host.

        forwarder: async callable taking HCIACLData. Used by VirtualLELink to bridge
        ACL frames between two VirtualControllers.
        """
        self._acl_forwarder = forwarder

    async def _inject_acl_to_host(self, acl) -> None:
        """Push an ACL frame to the host-side sink. Used by the loopback bridge."""
        sink = self._host_sink
        if sink is not None:
            await sink.on_transport_data(acl.to_bytes())  # type: ignore[union-attr]

    async def process(self, data: bytes) -> bytes | None:
        """Process raw H4+HCI bytes and return a response event.

        For most commands returns a Command Complete event.
        For HCI_LE_Start_Encryption returns a Command Status event and
        schedules an async Encryption_Change event via _send_event_to_host.
        Returns None if the packet is not a command.
        """
        if not data:
            return None

        # Route ACL frames to the registered forwarder (if any)
        if data[0] == HCI_ACL_PACKET:
            if self._acl_forwarder is not None and len(data) >= 5:
                h_f = int.from_bytes(data[1:3], "little")
                handle = h_f & 0x0FFF
                pb_flag = (h_f >> 12) & 0x03
                bc_flag = (h_f >> 14) & 0x03
                length = int.from_bytes(data[3:5], "little")
                payload = data[5:5 + length]
                acl = HCIACLData(
                    handle=handle, pb_flag=pb_flag,
                    bc_flag=bc_flag, data=payload,
                )
                asyncio.create_task(self._acl_forwarder(acl))
            return None

        if data[0] != HCI_COMMAND_PACKET:
            return None

        # Parse opcode and raw parameters directly from the H4 frame so that
        # fields are always correct (typed subclasses may not implement from_bytes
        # and their __post_init__ can overwrite self.parameters with defaults).
        if len(data) < 4:
            return None
        opcode = struct.unpack_from("<H", data, 1)[0]
        param_len = data[3]
        raw_params = data[4 : 4 + param_len]

        # --- Encryption commands with special response sequences ---
        if opcode == HCI_LE_START_ENCRYPTION:
            handle = struct.unpack_from("<H", raw_params, 0)[0]
            # Spec: LE_Start_Encryption gets Command_Status, then Encryption_Change
            asyncio.create_task(
                self._emit_simulated_encryption_change(handle, status=0, enabled=1)
            )
            return self._make_command_status(opcode, status=0)

        if opcode == HCI_LE_LONG_TERM_KEY_REQUEST_REPLY:
            handle = struct.unpack_from("<H", raw_params, 0)[0]
            asyncio.create_task(
                self._emit_simulated_encryption_change(handle, status=0, enabled=1)
            )
            return self._make_command_complete(
                opcode, b"\x00" + struct.pack("<H", handle)
            )

        if opcode == HCI_LE_LONG_TERM_KEY_REQUEST_NEGATIVE_REPLY:
            handle = struct.unpack_from("<H", raw_params, 0)[0]
            asyncio.create_task(
                self._emit_simulated_encryption_change(handle, status=0x06, enabled=0)
            )
            return self._make_command_complete(
                opcode, b"\x00" + struct.pack("<H", handle)
            )

        # --- Standard Command Complete dispatch ---
        packet = decode_hci_packet(data)
        if not isinstance(packet, HCICommand):
            return None

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

    def _make_command_status(self, opcode: int, status: int) -> bytes:
        """Build a full H4+HCI Command Status event."""
        event = HCI_Command_Status_Event(
            status=status,
            num_hci_command_packets=1,
            command_opcode=opcode,
        )
        return event.to_bytes()

    async def _emit_simulated_encryption_change(
        self, handle: int, status: int, enabled: int
    ) -> None:
        """Emit an HCI_Encryption_Change event after yielding to the event loop."""
        await asyncio.sleep(0)  # let Command Status/Complete reach the host first
        params = bytes([status]) + struct.pack("<H", handle) + bytes([enabled])
        event = HCIEvent(event_code=int(EventCode.ENCRYPTION_CHANGE), parameters=params)
        await self._send_event_to_host(event)

    def simulate_le_ltk_request(self, *, handle: int, rand: bytes, ediv: int) -> None:
        """Test hook: inject an LE_LTK_Request subevent from the controller to the host."""
        if len(rand) != 8:
            raise ValueError("rand must be 8 bytes")
        subevent_data = (
            bytes([int(LEMetaSubEvent.LE_LONG_TERM_KEY_REQUEST)])
            + struct.pack("<H", handle)
            + rand
            + struct.pack("<H", ediv)
        )
        meta_event = HCIEvent(
            event_code=int(EventCode.LE_META), parameters=subevent_data
        )
        asyncio.create_task(self._send_event_to_host(meta_event))

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
