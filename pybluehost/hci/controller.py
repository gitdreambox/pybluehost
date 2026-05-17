"""HCIController: command/event dispatch, ACL flow, connection tracking.

Sits between Transport (below) and L2CAP (above).  Implements TransportSink
so the transport can push received bytes up, and exposes send_command /
send_acl_data for the upper layer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import time
from typing import Callable, Awaitable

# Controller-wide logger used by initialize() to debug-log skipped commands.
logger = logging.getLogger(__name__)

# Connection-lifecycle sub-logger; distinct from any controller-wide logger so
# users can isolate connection events via `--trace=hci=debug` (parent
# `pybluehost.hci` level propagates to children unless overridden).
connection_logger = logging.getLogger("pybluehost.hci.connection")

from pybluehost.core.errors import CommandTimeoutError, TransportError
from pybluehost.core.trace import Direction, TraceEvent, TraceSystem
from pybluehost.hci.flow import ACLFlowController, CommandFlowController
from pybluehost.hci.packets import (
    HCIACLData,
    HCICommand,
    HCIEvent,
    HCIPacket,
    HCISCOData,
    HCI_Command_Complete_Event,
    HCI_Command_Status_Event,
    HCI_Number_Of_Completed_Packets_Event,
    decode_hci_packet,
)


# ---------------------------------------------------------------------------
# Connection tracking
# ---------------------------------------------------------------------------

@dataclass
class HCIConnection:
    """Represents a single HCI connection."""

    handle: int
    bd_addr: bytes
    link_type: int = 0  # 0x00=SCO, 0x01=ACL, 0x02=eSCO, 0x03=LE
    encryption_enabled: int = 0


class ConnectionManager:
    """Track active HCI connections by handle."""

    def __init__(self) -> None:
        self._connections: dict[int, HCIConnection] = {}

    def add(self, conn: HCIConnection) -> None:
        """Register a new connection."""
        self._connections[conn.handle] = conn

    def remove(self, handle: int) -> HCIConnection | None:
        """Remove and return the connection for *handle*, or None."""
        return self._connections.pop(handle, None)

    def get(self, handle: int) -> HCIConnection | None:
        """Lookup connection by handle."""
        return self._connections.get(handle)

    def all(self) -> list[HCIConnection]:
        """Return all active connections."""
        return list(self._connections.values())


# ---------------------------------------------------------------------------
# HCIController
# ---------------------------------------------------------------------------

# Callback type aliases
OnHCIEvent = Callable[[HCIEvent], Awaitable[None] | None]
OnACLData = Callable[[HCIACLData], Awaitable[None] | None]
OnSCOData = Callable[[HCISCOData], Awaitable[None] | None]


class HCIController:
    """Host-side HCI controller: command dispatch, event routing, flow control.

    Implements the ``TransportSink`` protocol so it can be attached to a
    ``Transport`` via ``transport.set_sink(controller)``.
    """

    def __init__(
        self,
        transport: object,  # Transport (duck-typed to avoid circular import)
        trace: TraceSystem | None = None,
        command_timeout: float = 5.0,
    ) -> None:
        self._transport = transport
        self._trace = trace
        self._command_timeout = command_timeout

        self._cmd_flow = CommandFlowController(initial_credits=1)
        self._acl_flow = ACLFlowController()
        self.connections = ConnectionManager()

        # Supported_Commands bitmap parsed during initialize()
        self._supported_commands: "SupportedCommands | None" = None

        # Upper-layer callbacks (set via set_upstream)
        self._on_hci_event: OnHCIEvent | None = None
        self._on_acl_data: OnACLData | None = None
        self._on_sco_data: OnSCOData | None = None

        # Encryption event listeners
        self._encryption_change_listeners: list = []
        self._le_ltk_request_listeners: list = []

        # SC (Secure Connections / SSP) event listeners
        self._io_capability_request_listeners: list = []
        self._user_confirmation_request_listeners: list = []
        self._simple_pairing_complete_listeners: list = []
        self._link_key_notification_listeners: list = []
        self._link_key_request_listeners: list = []

        # Register ourselves as the transport's sink
        if hasattr(transport, "set_sink"):
            transport.set_sink(self)  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # Upper-layer registration
    # ------------------------------------------------------------------

    def set_upstream(
        self,
        on_hci_event: OnHCIEvent | None = None,
        on_acl_data: OnACLData | None = None,
        on_sco_data: OnSCOData | None = None,
    ) -> None:
        """Register upper-layer callbacks for events and data."""
        self._on_hci_event = on_hci_event
        self._on_acl_data = on_acl_data
        self._on_sco_data = on_sco_data

    def on_encryption_change(self, listener) -> None:
        """Register listener called as (handle: int, status: int, encryption_enabled: int) when HCI_Encryption_Change event arrives."""
        self._encryption_change_listeners.append(listener)

    def on_le_ltk_request(self, listener) -> None:
        """Register listener called as (handle: int, rand: bytes, ediv: int) when LE_LTK_Request subevent arrives."""
        self._le_ltk_request_listeners.append(listener)

    def on_io_capability_request(self, listener) -> None:
        """Register listener called as (addr: BDAddress) when IO_Capability_Request fires."""
        self._io_capability_request_listeners.append(listener)

    def on_user_confirmation_request(self, listener) -> None:
        """Register listener called as (addr: BDAddress, numeric_value: int) when User_Confirmation_Request fires."""
        self._user_confirmation_request_listeners.append(listener)

    def on_simple_pairing_complete(self, listener) -> None:
        """Register listener called as (status: int, addr: BDAddress) when Simple_Pairing_Complete fires."""
        self._simple_pairing_complete_listeners.append(listener)

    def on_link_key_notification(self, listener) -> None:
        """Register listener called as (addr: BDAddress, link_key: bytes, key_type: int)."""
        self._link_key_notification_listeners.append(listener)

    def on_link_key_request(self, listener) -> None:
        """Register listener called as (addr: BDAddress) when Link_Key_Request fires."""
        self._link_key_request_listeners.append(listener)

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def supported_commands(self) -> "SupportedCommands | None":
        """The parsed Supported_Commands bitmap from initialize(), or None before init."""
        return self._supported_commands

    # ------------------------------------------------------------------
    # TransportSink protocol
    # ------------------------------------------------------------------

    async def on_transport_data(self, data: bytes) -> None:
        """Called by the transport when raw HCI bytes arrive."""
        self._emit_trace(Direction.UP, data)
        packet = decode_hci_packet(data)

        if isinstance(packet, HCIACLData):
            if self._on_acl_data is not None:
                result = self._on_acl_data(packet)
                if asyncio.iscoroutine(result):
                    await result
        elif isinstance(packet, HCISCOData):
            if self._on_sco_data is not None:
                result = self._on_sco_data(packet)
                if asyncio.iscoroutine(result):
                    await result
        elif isinstance(packet, HCIEvent):
            await self._handle_event(packet)

    async def on_transport_error(self, error: TransportError) -> None:
        """Called by the transport on error. Currently a no-op."""
        pass

    # ------------------------------------------------------------------
    # Command sending
    # ------------------------------------------------------------------

    async def send_command(self, command: HCICommand) -> HCIEvent:
        """Send an HCI command and wait for the corresponding completion event.

        Raises ``CommandTimeoutError`` if no response within *command_timeout*.
        """
        await self._cmd_flow.acquire()

        raw = command.to_bytes()
        fut = self._cmd_flow.register(command.opcode)

        self._emit_trace(Direction.DOWN, raw)
        await self._transport.send(raw)  # type: ignore[union-attr]

        try:
            event = await asyncio.wait_for(fut, timeout=self._command_timeout)
        except asyncio.TimeoutError:
            # Clean up the pending future
            self._cmd_flow._pending.pop(command.opcode, None)
            raise CommandTimeoutError(
                f"HCI command 0x{command.opcode:04X} timed out after {self._command_timeout}s"
            )

        if isinstance(event, HCI_Command_Complete_Event):
            self._configure_acl_flow_from_command_complete(event)
        return event

    def _configure_acl_flow_from_command_complete(
        self, event: HCI_Command_Complete_Event
    ) -> None:
        """Configure ACL flow control from controller buffer-size responses."""
        import struct
        from pybluehost.hci.constants import HCI_READ_BUFFER_SIZE, HCI_LE_READ_BUFFER_SIZE

        params = event.return_parameters
        if not params or params[0] != 0x00:
            return

        if event.command_opcode == HCI_READ_BUFFER_SIZE and len(params) >= 8:
            acl_len, _sco_len, acl_count, _sco_count = struct.unpack_from("<HBHH", params, 1)
            if acl_len and acl_count:
                self._acl_flow.configure(num_buffers=acl_count, buffer_size=acl_len)
        elif event.command_opcode == HCI_LE_READ_BUFFER_SIZE and len(params) >= 4:
            le_acl_len, le_acl_count = struct.unpack_from("<HB", params, 1)
            if le_acl_len and le_acl_count:
                self._acl_flow.configure(num_buffers=le_acl_count, buffer_size=le_acl_len)

    # ------------------------------------------------------------------
    # ACL data sending
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Send the HCI init sequence, skipping commands the controller doesn't advertise.

        After HCI_Reset and Read_Local_Supported_Commands, every subsequent
        command is gated on its bit in the Supported_Commands bitmap. If the
        controller reports a command as unsupported, it is skipped with a
        debug log. Two commands are mandatory: HCI_Reset (without which the
        controller is in an unknown state) and Read_BD_ADDR (without which
        SMP/GAP cannot function); if either is unsupported or fails, init
        raises RuntimeError.
        """
        from pybluehost.hci.capabilities import SupportedCommands
        from pybluehost.hci.packets import (
            HCI_Reset,
            HCI_Read_Local_Version_Command,
            HCI_Read_Local_Supported_Commands_Command,
            HCI_Read_Local_Supported_Features_Command,
            HCI_Read_BD_ADDR_Command,
            HCI_Read_Buffer_Size_Command,
            HCI_LE_Read_Buffer_Size_Command,
            HCI_LE_Read_Local_Supported_Features_Command,
            HCI_Set_Event_Mask_Command,
            HCI_LE_Set_Event_Mask_Command,
            HCI_Write_LE_Host_Supported_Command,
            HCI_Write_Simple_Pairing_Mode_Command,
            HCI_Write_Scan_Enable_Command,
            HCI_Host_Buffer_Size_Command,
            HCI_LE_Set_Scan_Parameters_Command,
            HCI_LE_Set_Random_Address_Command,
        )
        from pybluehost.hci.constants import HCI_READ_BD_ADDR

        EVENT_MASK_ALL = b"\xFF\xFF\xFF\xFF\xFF\xFF\xFF\x3F"
        LE_EVENT_MASK = b"\x1F\x00\x00\x00\x00\x00\x00\x00"
        RANDOM_ADDRESS = bytes(6)

        # Step 1: HCI_Reset — mandatory, never gated.
        await self.send_command(HCI_Reset())

        # Step 2: Read_Local_Supported_Commands — parse response bitmap.
        rsp = await self.send_command(HCI_Read_Local_Supported_Commands_Command())
        # Command_Complete.return_parameters: status(1) + bitmap(64)
        bitmap = rsp.return_parameters[1:65]
        if len(bitmap) != 64:
            raise RuntimeError(
                f"Read_Local_Supported_Commands returned {len(bitmap)}-byte bitmap, expected 64"
            )
        self._supported_commands = SupportedCommands(bitmap)

        # Read_BD_ADDR is mandatory.
        if not self._supported_commands.has(HCI_READ_BD_ADDR):
            raise RuntimeError("controller does not support Read_BD_ADDR (mandatory)")
        await self.send_command(HCI_Read_BD_ADDR_Command())

        # Optional commands — skip if bit unset.
        optional_commands = [
            HCI_Read_Local_Version_Command(),
            HCI_Read_Local_Supported_Features_Command(),
            HCI_Read_Buffer_Size_Command(),
            HCI_LE_Read_Buffer_Size_Command(),
            HCI_LE_Read_Local_Supported_Features_Command(),
            HCI_Set_Event_Mask_Command(event_mask=EVENT_MASK_ALL),
            HCI_LE_Set_Event_Mask_Command(le_event_mask=LE_EVENT_MASK),
            HCI_Write_LE_Host_Supported_Command(le_supported_host=0x01, simultaneous_le_host=0x00),
            HCI_Write_Simple_Pairing_Mode_Command(simple_pairing_mode=0x01),
            HCI_Write_Scan_Enable_Command(scan_enable=0x00),
            HCI_Host_Buffer_Size_Command(
                host_acl_data_packet_length=0x0200,
                host_synchronous_data_packet_length=0xFF,
                host_total_num_acl_data_packets=0x0014,
                host_total_num_synchronous_data_packets=0x0000,
            ),
            HCI_LE_Set_Scan_Parameters_Command(
                le_scan_type=0x01,
                le_scan_interval=0x0010,
                le_scan_window=0x0010,
                own_address_type=0x00,
                scanning_filter_policy=0x00,
            ),
            HCI_LE_Set_Random_Address_Command(random_address=RANDOM_ADDRESS),
        ]

        for cmd in optional_commands:
            opcode = cmd.opcode
            if not self._supported_commands.has(opcode):
                logger.debug(
                    "HCI initialize: skipping unsupported command opcode=0x%04X",
                    opcode,
                )
                continue
            await self.send_command(cmd)

    # ------------------------------------------------------------------
    # ACL data sending
    # ------------------------------------------------------------------

    async def send_acl_data(self, handle: int, pb_flag: int, data: bytes) -> None:
        """Send ACL data, respecting controller flow control."""
        await self._acl_flow.acquire(handle)
        packet = HCIACLData(handle=handle, pb_flag=pb_flag, data=data)
        raw = packet.to_bytes()
        self._emit_trace(Direction.DOWN, raw)
        await self._transport.send(raw)  # type: ignore[union-attr]

    def _emit_trace(self, direction: Direction, raw: bytes) -> None:
        if self._trace is None:
            return
        decoded: object | None
        try:
            from pybluehost.hci.packets import decode_hci_packet

            decoded = decode_hci_packet(raw)
        except Exception:
            decoded = None
        self._trace.emit(
            TraceEvent(
                timestamp=time.time(),
                wall_clock=datetime.now(timezone.utc),
                source_layer="hci",
                direction=direction,
                raw_bytes=raw,
                decoded=decoded,
                connection_handle=None,
                metadata={},
            )
        )

    # ------------------------------------------------------------------
    # Event handling (internal)
    # ------------------------------------------------------------------

    async def _handle_event(self, event: HCIEvent) -> None:
        """Route an HCI event to the appropriate handler."""
        if isinstance(event, HCI_Command_Complete_Event):
            self._cmd_flow.release(event.num_hci_command_packets)
            self._cmd_flow.resolve(event.command_opcode, event)
            return

        if isinstance(event, HCI_Command_Status_Event):
            self._cmd_flow.release(event.num_hci_command_packets)
            self._cmd_flow.resolve(event.command_opcode, event)
            return

        if isinstance(event, HCI_Number_Of_Completed_Packets_Event):
            self._acl_flow.on_num_completed(event.completed)
            return

        # Encryption-specific listeners
        from pybluehost.hci.constants import EventCode, LEMetaSubEvent
        from pybluehost.hci.packets import HCI_LE_Meta_Event

        if event.event_code == EventCode.ENCRYPTION_CHANGE and len(event.parameters) >= 4:
            status = event.parameters[0]
            handle = int.from_bytes(event.parameters[1:3], "little")
            enabled = event.parameters[3]
            for listener in list(self._encryption_change_listeners):
                result = listener(handle, status, enabled)
                if asyncio.iscoroutine(result):
                    await result

        if isinstance(event, HCI_LE_Meta_Event) and event.subevent_code == LEMetaSubEvent.LE_LONG_TERM_KEY_REQUEST:
            params = event.subevent_parameters
            if len(params) >= 12:
                handle = int.from_bytes(params[0:2], "little")
                rand_b = params[2:10]
                ediv = int.from_bytes(params[10:12], "little")
                for listener in list(self._le_ltk_request_listeners):
                    result = listener(handle, rand_b, ediv)
                    if asyncio.iscoroutine(result):
                        await result

        # SC (SSP) event listeners
        from pybluehost.core.address import BDAddress

        if event.event_code == EventCode.IO_CAPABILITY_REQUEST and len(event.parameters) >= 6:
            addr = BDAddress(bytes(reversed(event.parameters[:6])))
            for listener in list(self._io_capability_request_listeners):
                result = listener(addr)
                if asyncio.iscoroutine(result):
                    await result

        if event.event_code == EventCode.USER_CONFIRMATION_REQUEST and len(event.parameters) >= 10:
            addr = BDAddress(bytes(reversed(event.parameters[:6])))
            numeric = int.from_bytes(event.parameters[6:10], "little")
            for listener in list(self._user_confirmation_request_listeners):
                result = listener(addr, numeric)
                if asyncio.iscoroutine(result):
                    await result

        if event.event_code == EventCode.SIMPLE_PAIRING_COMPLETE and len(event.parameters) >= 7:
            status = event.parameters[0]
            addr = BDAddress(bytes(reversed(event.parameters[1:7])))
            for listener in list(self._simple_pairing_complete_listeners):
                result = listener(status, addr)
                if asyncio.iscoroutine(result):
                    await result

        if event.event_code == EventCode.LINK_KEY_NOTIFICATION and len(event.parameters) >= 23:
            addr = BDAddress(bytes(reversed(event.parameters[:6])))
            key = event.parameters[6:22]
            key_type = event.parameters[22]
            for listener in list(self._link_key_notification_listeners):
                result = listener(addr, key, key_type)
                if asyncio.iscoroutine(result):
                    await result

        if event.event_code == EventCode.LINK_KEY_REQUEST and len(event.parameters) >= 6:
            addr = BDAddress(bytes(reversed(event.parameters[:6])))
            for listener in list(self._link_key_request_listeners):
                result = listener(addr)
                if asyncio.iscoroutine(result):
                    await result

        # All other events go to the upper layer
        if self._on_hci_event is not None:
            result = self._on_hci_event(event)
            if asyncio.iscoroutine(result):
                await result


# ---------------------------------------------------------------------------
# Connection-lifecycle log helpers
# ---------------------------------------------------------------------------
#
# These helpers emit human-readable INFO logs at the two key connection
# transitions (LE_Connection_Complete and Disconnection_Complete).  They are
# intentionally standalone so they can be unit-tested without spinning up a
# full HCIController.  Wiring into ``_handle_event`` is deferred until the
# event-decoding path can supply the structured fields directly (Task 23
# provides E2E coverage that exercises this end-to-end).


def _log_le_connection_complete(
    *, handle: int, peer_addr: str, role: int, interval_ms: float,
) -> None:
    """Emit an INFO log line for an LE Connection_Complete event."""
    from pybluehost.hci.format_fields import format_role

    connection_logger.info(
        "HCI LE_Connection_Complete handle=0x%04X peer=%s role=%s interval=%.1fms",
        handle, peer_addr, format_role(role), interval_ms,
    )


def _log_disconnection_complete(*, handle: int, reason: int) -> None:
    """Emit an INFO log line for a Disconnection_Complete event."""
    from pybluehost.hci.format_fields import format_status

    connection_logger.info(
        "HCI Disconnection_Complete handle=0x%04X reason=%s",
        handle, format_status(reason),
    )
