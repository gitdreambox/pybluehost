"""HCIController: command/event dispatch, ACL flow, connection tracking.

Sits between Transport (below) and L2CAP (above).  Implements TransportSink
so the transport can push received bytes up, and exposes send_command /
send_acl_data for the upper layer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable, Awaitable

from pybluehost.core.errors import CommandTimeoutError, TransportError
from pybluehost.core.trace import TraceSystem
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

        # Upper-layer callbacks (set via set_upstream)
        self._on_hci_event: OnHCIEvent | None = None
        self._on_acl_data: OnACLData | None = None
        self._on_sco_data: OnSCOData | None = None

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

    # ------------------------------------------------------------------
    # TransportSink protocol
    # ------------------------------------------------------------------

    async def on_transport_data(self, data: bytes) -> None:
        """Called by the transport when raw HCI bytes arrive."""
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

        await self._transport.send(raw)  # type: ignore[union-attr]

        try:
            event = await asyncio.wait_for(fut, timeout=self._command_timeout)
        except asyncio.TimeoutError:
            # Clean up the pending future
            self._cmd_flow._pending.pop(command.opcode, None)
            raise CommandTimeoutError(
                f"HCI command 0x{command.opcode:04X} timed out after {self._command_timeout}s"
            )

        return event

    # ------------------------------------------------------------------
    # ACL data sending
    # ------------------------------------------------------------------

    async def send_acl_data(self, handle: int, pb_flag: int, data: bytes) -> None:
        """Send ACL data, respecting controller flow control."""
        await self._acl_flow.acquire(handle)
        packet = HCIACLData(handle=handle, pb_flag=pb_flag, data=data)
        await self._transport.send(packet.to_bytes())  # type: ignore[union-attr]

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

        # All other events go to the upper layer
        if self._on_hci_event is not None:
            result = self._on_hci_event(event)
            if asyncio.iscoroutine(result):
                await result
