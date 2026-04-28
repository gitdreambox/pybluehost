"""Stack — top-level factory that assembles all Bluetooth layers."""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from pybluehost.ble.security import SecurityConfig
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability


# ---------------------------------------------------------------------------
# StackMode + StackConfig
# ---------------------------------------------------------------------------

class StackMode(str, Enum):
    LIVE = "live"
    VIRTUAL = "virtual"
    REPLAY = "replay"


@dataclass
class StackConfig:
    """Configuration for a Stack instance."""

    # GAP
    device_name: str = "PyBlueHost"
    appearance: int = 0x0000
    le_io_capability: IOCapability = IOCapability.NO_INPUT_NO_OUTPUT
    classic_io_capability: IOCapability = IOCapability.DISPLAY_YES_NO

    # Security
    security: SecurityConfig = field(default_factory=SecurityConfig)

    # HCI
    command_timeout: float = 5.0

    # Trace
    trace_sinks: list = field(default_factory=list)


@dataclass(frozen=True)
class StackConnectionEvent:
    """Application-visible connection state update."""

    state: str
    handle: int | None = None
    reason: str | None = None


def _hci_status_text(status: int) -> str:
    from pybluehost.hci.constants import ErrorCode

    try:
        return f"{ErrorCode(status).name} (0x{status:02X})"
    except ValueError:
        return f"UNKNOWN_STATUS (0x{status:02X})"


# ---------------------------------------------------------------------------
# Stack
# ---------------------------------------------------------------------------

class Stack:
    """Top-level Bluetooth stack — assembles HCI, L2CAP, BLE, Classic, GAP.

    Use factory methods (``virtual()``, ``from_uart()``, etc.) to create.
    """

    def __init__(self) -> None:
        self._transport: Any = None
        self._hci: Any = None
        self._l2cap: Any = None
        self._gap: Any = None
        self._gatt_server: Any = None
        self._trace: Any = None
        self._sdp: Any = None
        self._rfcomm: Any = None
        self._local_address: BDAddress | None = None
        self._powered = False
        self._mode: StackMode = StackMode.LIVE
        self._config: StackConfig = StackConfig()
        self._le_connection_waiters: list[asyncio.Future[int]] = []
        self._connection_event_handlers: list[Callable[[StackConnectionEvent], object]] = []

    # -- Factory methods -----------------------------------------------------

    @classmethod
    async def _build(
        cls,
        transport: Any,
        config: StackConfig | None = None,
        mode: StackMode = StackMode.LIVE,
    ) -> Stack:
        """Internal factory: assemble layers on a given transport."""
        from pybluehost.ble.gap import (
            BLEAdvertiser,
            BLEConnectionManager,
            BLEScanner,
            ExtendedAdvertiser,
            PrivacyManager,
            WhiteList,
        )
        from pybluehost.ble.gatt import GATTServer
        from pybluehost.classic.gap import (
            ClassicConnectionManager,
            ClassicDiscoverability,
            ClassicDiscovery,
            SSPManager,
        )
        from pybluehost.classic.rfcomm import RFCOMMManager
        from pybluehost.classic.sdp import SDPServer
        from pybluehost.core.trace import TraceSystem
        from pybluehost.gap import GAP
        from pybluehost.hci.controller import HCIController
        from pybluehost.l2cap.manager import L2CAPManager

        cfg = config or StackConfig()
        stack = cls()
        stack._transport = transport
        stack._mode = mode
        stack._config = cfg

        # 1. Trace
        trace = TraceSystem()
        for sink in cfg.trace_sinks:
            trace.add_sink(sink)
        if cfg.trace_sinks:
            await trace.start()
        stack._trace = trace

        # 2. HCI Controller
        hci = HCIController(
            transport=transport,
            trace=trace,
            command_timeout=cfg.command_timeout,
        )
        stack._hci = hci

        # 3. HCI init sequence
        await asyncio.wait_for(hci.initialize(), timeout=cfg.command_timeout * 20)
        stack._powered = True

        # 3a. Read BD_ADDR for local_address
        from pybluehost.hci.packets import HCI_Read_BD_ADDR_Command
        addr_event = await hci.send_command(HCI_Read_BD_ADDR_Command())
        if hasattr(addr_event, "return_parameters") and len(addr_event.return_parameters) >= 7:
            raw_addr = addr_event.return_parameters[1:7]
            stack._local_address = BDAddress(raw_addr)

        # 4. L2CAP
        l2cap = L2CAPManager(hci=hci)
        stack._l2cap = l2cap

        # 5. BLE layers
        gatt_server = GATTServer()
        stack._gatt_server = gatt_server

        # 6. Classic layers
        sdp = SDPServer()
        stack._sdp = sdp
        rfcomm = RFCOMMManager()
        stack._rfcomm = rfcomm

        # 7. GAP (unified)
        gap = GAP(
            ble_advertiser=BLEAdvertiser(hci=hci),
            ble_scanner=BLEScanner(hci=hci),
            ble_connections=BLEConnectionManager(hci=hci),
            ble_privacy=PrivacyManager(hci=hci),
            classic_discovery=ClassicDiscovery(hci=hci),
            classic_discoverability=ClassicDiscoverability(hci=hci),
            classic_connections=ClassicConnectionManager(hci=hci),
            classic_ssp=SSPManager(hci=hci),
            whitelist=WhiteList(hci=hci),
            ble_extended_advertiser=ExtendedAdvertiser(hci=hci),
        )
        stack._gap = gap

        hci.set_upstream(
            on_hci_event=stack._on_hci_event,
            on_acl_data=stack._on_acl_data,
        )

        return stack

    @classmethod
    async def from_usb(
        cls,
        vendor: str | None = None,
        bus: int | None = None,
        address: int | None = None,
        config: StackConfig | None = None,
    ) -> Stack:
        """Build a live Stack on a USB Bluetooth adapter."""
        from pybluehost.transport.usb import USBTransport

        transport = USBTransport.auto_detect(vendor=vendor, bus=bus, address=address)
        await transport.open()
        try:
            return await cls._build(transport, config, StackMode.LIVE)
        except Exception:
            close = getattr(transport, "close", None)
            if close is not None:
                await close()
            raise

    @classmethod
    async def from_uart(
        cls,
        port: str,
        baudrate: int = 115200,
        config: StackConfig | None = None,
    ) -> Stack:
        """Build a live Stack on a UART HCI link."""
        from pybluehost.transport.uart import UARTTransport

        transport = UARTTransport(port=port, baudrate=baudrate)
        await transport.open()
        try:
            return await cls._build(transport, config, StackMode.LIVE)
        except Exception:
            close = getattr(transport, "close", None)
            if close is not None:
                await close()
            raise

    @classmethod
    async def virtual(
        cls,
        config: StackConfig | None = None,
    ) -> Stack:
        """Create a single Stack backed by a software-emulated VirtualController.

        No real Bluetooth hardware required; suitable for unit/integration tests
        and CLI experimentation.
        """
        from pybluehost.hci.virtual import VirtualController

        vc, host_t = await VirtualController.create()
        stack = await cls._build(host_t, config, StackMode.VIRTUAL)
        stack._local_address = vc._address
        return stack

    async def _on_hci_event(self, event: Any) -> None:
        if self._l2cap is not None:
            await self._l2cap.on_hci_event(event)
            self._attach_gatt_server_to_att_channels()
        self._handle_connection_event(event)
        if self._gap is None:
            return
        ble_scanner = getattr(self._gap, "ble_scanner", None)
        if ble_scanner is not None and hasattr(ble_scanner, "on_hci_event"):
            await ble_scanner.on_hci_event(event)
        classic_discovery = getattr(self._gap, "classic_discovery", None)
        if classic_discovery is not None and hasattr(classic_discovery, "on_hci_event"):
            await classic_discovery.on_hci_event(event)

    async def _on_acl_data(self, packet: Any) -> None:
        if self._l2cap is not None:
            self._attach_gatt_server_to_att_channels()
            await self._l2cap.on_acl_data(packet)

    def _attach_gatt_server_to_att_channels(self) -> None:
        if self._l2cap is None or self._gatt_server is None:
            return

        from pybluehost.ble.att import ATT_Handle_Value_Notification, decode_att_pdu
        from pybluehost.l2cap.channel import SimpleChannelEvents
        from pybluehost.l2cap.constants import CID_ATT

        async def on_notification(handle: int, value: bytes, conn_handle: int) -> None:
            channel = self._l2cap.get_fixed_channel(conn_handle, CID_ATT)
            if channel is None:
                return
            notification = ATT_Handle_Value_Notification(
                attribute_handle=handle,
                attribute_value=value,
            )
            await channel.send(notification.to_bytes())

        self._gatt_server.on_notification_sent(on_notification)

        connections = getattr(self._l2cap, "_connections", {})
        for handle, channels in connections.items():
            channel = channels.get(CID_ATT)
            if channel is None or getattr(channel, "_gatt_server_bound", False):
                continue

            async def on_att_data(data: bytes, *, conn_handle: int = handle, att_channel: Any = channel) -> None:
                pdu = decode_att_pdu(data)
                response = await self._gatt_server.handle_request(conn_handle, pdu)
                await att_channel.send(response.to_bytes())

            channel.set_events(SimpleChannelEvents(on_data=on_att_data))
            setattr(channel, "_gatt_server_bound", True)

    def on_connection_event(self, handler: Callable[[StackConnectionEvent], object]) -> None:
        self._connection_event_handlers.append(handler)

    def _handle_connection_event(self, event: Any) -> None:
        from pybluehost.hci.constants import ErrorCode, LEMetaSubEvent
        from pybluehost.hci.packets import HCI_Disconnection_Complete_Event, HCI_LE_Meta_Event

        if isinstance(event, HCI_Disconnection_Complete_Event):
            if event.status == ErrorCode.SUCCESS:
                self._emit_connection_event(
                    StackConnectionEvent(
                        state="disconnected",
                        handle=event.connection_handle,
                        reason=_hci_status_text(event.reason),
                    )
                )
            return
        if not isinstance(event, HCI_LE_Meta_Event):
            return
        if event.subevent_code not in (
            LEMetaSubEvent.LE_CONNECTION_COMPLETE,
            LEMetaSubEvent.LE_ENHANCED_CONNECTION_COMPLETE,
        ):
            return
        if len(event.subevent_parameters) < 3:
            return

        import struct

        status = event.subevent_parameters[0]
        handle = struct.unpack_from("<H", event.subevent_parameters, 1)[0]
        waiters = self._le_connection_waiters
        self._le_connection_waiters = []
        if status == ErrorCode.SUCCESS:
            self._emit_connection_event(StackConnectionEvent(state="connected", handle=handle))
            for waiter in waiters:
                if not waiter.done():
                    waiter.set_result(handle)
        else:
            reason = _hci_status_text(status)
            self._emit_connection_event(StackConnectionEvent(state="failed", handle=handle, reason=reason))
            error = RuntimeError(f"LE connection failed: {reason}")
            for waiter in waiters:
                if not waiter.done():
                    waiter.set_exception(error)

    def _emit_connection_event(self, event: StackConnectionEvent) -> None:
        for handler in list(self._connection_event_handlers):
            handler(event)

    async def connect_gatt(
        self,
        target: BDAddress,
        *,
        timeout: float = 10.0,
    ) -> Any:
        """Connect to a BLE peer and return a GATT client bound to ATT CID."""
        if self._gap is None or self._l2cap is None:
            raise RuntimeError("Stack is not initialized")

        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[int] = loop.create_future()
        self._le_connection_waiters.append(waiter)
        try:
            await self._gap.ble_connections.connect(target)
            handle = await asyncio.wait_for(waiter, timeout=timeout)
        finally:
            if not waiter.done():
                waiter.cancel()
            with contextlib.suppress(ValueError):
                self._le_connection_waiters.remove(waiter)

        from pybluehost.ble.att import ATTBearer
        from pybluehost.ble.gatt import GATTClient
        from pybluehost.l2cap.channel import SimpleChannelEvents
        from pybluehost.l2cap.constants import CID_ATT

        channel = self._l2cap.get_fixed_channel(handle, CID_ATT)
        if channel is None:
            raise RuntimeError(f"ATT fixed channel not available for handle 0x{handle:04X}")
        bearer = ATTBearer(channel, mtu=getattr(channel, "mtu", 23))
        channel.set_events(SimpleChannelEvents(on_data=bearer._on_pdu))
        setattr(channel, "_gatt_client_bound", True)
        return GATTClient(bearer)

    # -- Lifecycle -----------------------------------------------------------

    async def power_on(self) -> None:
        """Re-initialize HCI after power_off."""
        if not self._powered:
            await asyncio.wait_for(
                self._hci.initialize(),
                timeout=self._config.command_timeout * 20,
            )
            self._powered = True

    async def power_off(self) -> None:
        """Shut down connections and advertising, keep transport open."""
        self._powered = False

    async def close(self) -> None:
        """Release all resources."""
        self._powered = False
        if self._trace is not None:
            await self._trace.stop()
        if self._transport is not None and hasattr(self._transport, "close"):
            await self._transport.close()

    async def __aenter__(self) -> Stack:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # -- Properties ----------------------------------------------------------

    @property
    def hci(self) -> Any:
        return self._hci

    @property
    def l2cap(self) -> Any:
        return self._l2cap

    @property
    def gap(self) -> Any:
        return self._gap

    @property
    def gatt_server(self) -> Any:
        return self._gatt_server

    @property
    def sdp(self) -> Any:
        return self._sdp

    @property
    def rfcomm(self) -> Any:
        return self._rfcomm

    @property
    def trace(self) -> Any:
        return self._trace

    @property
    def local_address(self) -> BDAddress | None:
        return self._local_address

    @property
    def is_powered(self) -> bool:
        return self._powered

    @property
    def mode(self) -> StackMode:
        return self._mode
