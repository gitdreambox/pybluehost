"""Stack — top-level factory that assembles all Bluetooth layers."""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import BondStorage
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

    # Bond persistence — pluggable backend (PRD §5.4)
    bond_storage: BondStorage | None = None

    # SMP bonding behaviour
    bondable: bool = True
    auto_encrypt_on_bonded_reconnect: bool = True


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
        self._smp: Any = None
        self._rfcomm: Any = None
        self._virtual_controller: Any = None
        self._local_address: BDAddress | None = None
        self._powered = False
        self._mode: StackMode = StackMode.LIVE
        self._config: StackConfig = StackConfig()
        self._le_connection_waiters: list[asyncio.Future[int]] = []
        self._classic_connection_waiters: list[asyncio.Future[int]] = []
        self._classic_auth_waiters: dict[int, list[asyncio.Future[None]]] = {}
        self._classic_encryption_waiters: dict[int, list[asyncio.Future[None]]] = {}
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
        from pybluehost.l2cap.channel import SimpleChannelEvents
        from pybluehost.l2cap.constants import PSM_SDP
        from pybluehost.l2cap.manager import L2CAPManager

        cfg = config or StackConfig()
        stack = cls()
        stack._transport = transport
        stack._mode = mode
        stack._config = cfg

        # 1. Trace — always start the dispatch loop so sinks attached later
        # (e.g. ConsoleSink via attach_console_sink in cli/_lifecycle) deliver
        # events live instead of accumulating until stack.close().
        trace = TraceSystem()
        for sink in cfg.trace_sinks:
            trace.add_sink(sink)
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

        # 5b. SMP — bind to each LE connection's CID_SMP fixed channel.
        from pybluehost.ble.smp import SMPManager
        smp = SMPManager(
            hci=hci,
            bond_storage=cfg.bond_storage,
            local_io_caps=cfg.le_io_capability,
            bondable=cfg.bondable,
            local_address=stack._local_address,
        )
        stack._smp = smp

        def _bind_smp_to_le_connection(handle: int, channels: dict) -> None:
            from pybluehost.l2cap.channel import SimpleChannelEvents
            from pybluehost.l2cap.constants import CID_SMP

            smp_channel = channels.get(CID_SMP)
            if smp_channel is None:
                return

            async def _send(data: bytes) -> None:
                await smp_channel.send(data)

            smp.bind_channel(handle, _send)

            async def _on_data(data: bytes) -> None:
                await smp.on_pdu(data, connection_handle=handle)

            def _on_close(_reason: int) -> None:
                smp.unbind_channel(handle)

            smp_channel.set_events(SimpleChannelEvents(on_data=_on_data, on_close=_on_close))

        l2cap.on_le_connection_open(_bind_smp_to_le_connection)

        # 6. Classic layers
        sdp = SDPServer()
        stack._sdp = sdp

        def on_sdp_channel(channel: Any) -> None:
            async def on_sdp_data(data: bytes) -> None:
                await channel.send(sdp.handle_pdu(data))

            channel.set_events(SimpleChannelEvents(on_data=on_sdp_data))

        l2cap.listen_classic_channel(PSM_SDP, on_sdp_channel)
        rfcomm = RFCOMMManager(l2cap=l2cap)
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
            smp=smp,
        )
        stack._gap = gap

        hci.set_upstream(
            on_hci_event=stack._on_hci_event,
            on_acl_data=stack._on_acl_data,
        )

        hci.on_encryption_change(stack._on_encryption_change)
        hci.on_le_ltk_request(stack._on_le_ltk_request)

        return stack

    @classmethod
    async def from_usb(
        cls,
        vendor: str | None = None,
        bus: int | None = None,
        address: int | None = None,
        vid: int | None = None,
        pid: int | None = None,
        serial: str | None = None,
        occurrence: int | None = None,
        config: StackConfig | None = None,
    ) -> Stack:
        """Build a live Stack on a USB Bluetooth adapter."""
        from pybluehost.transport.usb import USBTransport

        transport = USBTransport.auto_detect(
            vendor=vendor,
            bus=bus,
            address=address,
            vid=vid,
            pid=pid,
            serial=serial,
            occurrence=occurrence,
        )
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
    async def from_tcp(
        cls,
        host: str,
        port: int,
        config: StackConfig | None = None,
    ) -> Stack:
        """Build a live Stack on a TCP HCI link (commonly btvirt/QEMU)."""
        from pybluehost.transport.tcp import TCPTransport

        transport = TCPTransport(host, port)
        await transport.open()
        try:
            return await cls._build(transport, config, StackMode.LIVE)
        except Exception:
            close = getattr(transport, "close", None)
            if close is not None:
                await close()
            raise

    @classmethod
    async def from_btsnoop(
        cls,
        path: str,
        *,
        realtime: bool = False,
        config: StackConfig | None = None,
    ) -> Stack:
        """Build a REPLAY-mode Stack that consumes a btsnoop capture file.

        Write operations (advertising, scanning, connecting, sending) raise
        :class:`ReplayModeError`. Use for offline reproduction of recorded
        sessions (PRD §3 P1, §9 acceptance indicator).
        """
        from pybluehost.transport.btsnoop import BtsnoopTransport

        transport = BtsnoopTransport(path, realtime=realtime)
        await transport.open()
        try:
            return await cls._build(transport, config, StackMode.REPLAY)
        except Exception:
            close = getattr(transport, "close", None)
            if close is not None:
                await close()
            raise

    @classmethod
    async def virtual(
        cls,
        config: StackConfig | None = None,
        *,
        address: "BDAddress | None" = None,
    ) -> Stack:
        """Create a single Stack backed by a software-emulated VirtualController.

        No real Bluetooth hardware required; suitable for unit/integration tests
        and CLI experimentation.

        Args:
            config: Optional stack configuration.
            address: Optional BD_ADDR for the virtual controller.  When omitted
                     a fixed default address is used (``AA:BB:CC:DD:EE:01``).
                     Pass distinct addresses when instantiating two stacks for
                     loopback E2E tests so SMP confirm values are computed with
                     the correct peer/local address pair.
        """
        from pybluehost.hci.virtual import VirtualController

        vc, host_t = await VirtualController.create(address=address)
        try:
            stack = await cls._build(host_t, config, StackMode.VIRTUAL)
        except Exception:
            close = getattr(host_t, "close", None)
            if close is not None:
                await close()
            raise
        stack._local_address = vc._address
        stack._virtual_controller = vc
        if stack._smp is not None:
            stack._smp.set_local_address(vc._address)
        return stack

    @classmethod
    async def loopback(cls, config: StackConfig | None = None) -> Stack:
        """PRD §5.7-compatible alias for :meth:`virtual`.

        Provided so user code following PRD documentation (Stack.loopback())
        continues to work after the internal rename to virtual().
        """
        return await cls.virtual(config=config)

    @classmethod
    async def build(
        cls,
        transport: Any,
        *,
        config: StackConfig | None = None,
        mode: StackMode = StackMode.LIVE,
    ) -> Stack:
        """Generic factory: assemble a Stack on a caller-provided transport.

        The transport must already be opened. On build failure the transport
        is left open (the caller owns it). For one-shot use prefer
        ``from_usb`` / ``from_uart`` / ``from_tcp`` / ``from_btsnoop``.
        """
        return await cls._build(transport, config, mode)

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
        classic_ssp = getattr(self._gap, "classic_ssp", None)
        if classic_ssp is not None and hasattr(classic_ssp, "on_hci_event"):
            await classic_ssp.on_hci_event(event)

    async def _on_acl_data(self, packet: Any) -> None:
        if self._l2cap is not None:
            self._attach_gatt_server_to_att_channels()
            await self._l2cap.on_acl_data(packet)

    async def _on_encryption_change(self, handle: int, status: int, enabled: int) -> None:
        """Forward to active SMP context (during pairing) + emit user event."""
        if self._smp is not None:
            ctx = self._smp.get_context(handle)
            if ctx is not None:
                from pybluehost.ble.smp import SMPEvent
                event = (
                    SMPEvent.ENCRYPTION_CHANGE_SUCCESS
                    if status == 0 and enabled
                    else SMPEvent.ENCRYPTION_CHANGE_FAILED
                )
                try:
                    await ctx.state_machine.fire(event)
                except Exception:
                    pass
        if status == 0 and enabled:
            self._emit_connection_event(StackConnectionEvent(state="encrypted", handle=handle))

    async def _on_le_ltk_request(self, handle: int, rand: bytes, ediv: int) -> None:
        """Reply to LE_LTK_Request — pairing-time uses active SMP ctx.stk;
        reconnect-time looks up bond by (ediv, rand)."""
        from pybluehost.hci.packets import (
            HCI_LE_LTK_Request_Negative_Reply_Command,
            HCI_LE_LTK_Request_Reply_Command,
        )
        # Pairing-time STK request: rand=0, ediv=0
        if ediv == 0 and rand == b"\x00" * 8 and self._smp is not None:
            ctx = self._smp.get_context(handle)
            if ctx is not None and ctx.stk:
                await self._hci.send_command(HCI_LE_LTK_Request_Reply_Command(
                    connection_handle=handle, long_term_key=ctx.stk,
                ))
                return
        # Reconnection LTK request: look up bond by EDIV/RAND
        if self._config.bond_storage is not None:
            for bond in await self._config.bond_storage.list_bonds():
                if bond.ediv == ediv and bond.rand == rand and bond.ltk:
                    await self._hci.send_command(HCI_LE_LTK_Request_Reply_Command(
                        connection_handle=handle, long_term_key=bond.ltk,
                    ))
                    return
        # No match
        await self._hci.send_command(
            HCI_LE_LTK_Request_Negative_Reply_Command(connection_handle=handle)
        )

    async def _auto_encrypt_on_reconnect(self, handle: int, peer_addr: "BDAddress") -> None:
        from pybluehost.hci.packets import HCI_LE_Start_Encryption_Command
        bond = await self._config.bond_storage.load_bond(peer_addr)  # type: ignore[union-attr]
        if bond is None or not bond.ltk:
            return
        await self._hci.send_command(HCI_LE_Start_Encryption_Command(
            connection_handle=handle,
            random_number=bond.rand if bond.rand else b"\x00" * 8,
            encrypted_diversifier=bond.ediv,
            long_term_key=bond.ltk,
        ))

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
        from pybluehost.hci.constants import ErrorCode, EventCode, LEMetaSubEvent
        from pybluehost.hci.packets import (
            HCI_Connection_Complete_Event,
            HCI_Disconnection_Complete_Event,
            HCI_LE_Meta_Event,
        )

        if getattr(event, "event_code", None) == EventCode.AUTH_COMPLETE:
            params = getattr(event, "parameters", b"")
            if len(params) >= 3:
                status = params[0]
                handle = int.from_bytes(params[1:3], "little")
                self._complete_classic_waiters(
                    self._classic_auth_waiters,
                    handle,
                    status,
                    "Classic authentication failed",
                )
            return
        if getattr(event, "event_code", None) == EventCode.CONNECTION_REQUEST:
            params = getattr(event, "parameters", b"")
            if len(params) >= 10 and params[9] == 0x01 and self._gap is not None:
                asyncio.create_task(
                    self._gap.classic_connections.accept(BDAddress(params[:6]), role=0x01)
                )
            return
        if getattr(event, "event_code", None) == EventCode.ENCRYPTION_CHANGE:
            params = getattr(event, "parameters", b"")
            if len(params) >= 4:
                status = params[0]
                handle = int.from_bytes(params[1:3], "little")
                encryption_enabled = params[3] != 0
                if status == ErrorCode.SUCCESS and not encryption_enabled:
                    status = ErrorCode.ENCRYPTION_MODE_NOT_ACCEPTABLE
                self._complete_classic_waiters(
                    self._classic_encryption_waiters,
                    handle,
                    status,
                    "Classic encryption failed",
                )
            return
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
        if isinstance(event, HCI_Connection_Complete_Event):
            waiters = self._classic_connection_waiters
            self._classic_connection_waiters = []
            if event.status == ErrorCode.SUCCESS:
                self._emit_connection_event(
                    StackConnectionEvent(state="connected", handle=event.connection_handle)
                )
                for waiter in waiters:
                    if not waiter.done():
                        waiter.set_result(event.connection_handle)
            else:
                reason = _hci_status_text(event.status)
                self._emit_connection_event(
                    StackConnectionEvent(
                        state="failed",
                        handle=event.connection_handle,
                        reason=reason,
                    )
                )
                error = RuntimeError(f"Classic ACL connection failed: {reason}")
                for waiter in waiters:
                    if not waiter.done():
                        waiter.set_exception(error)
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
            # Register peer address in SMP + optional auto-encrypt on bonded reconnect
            params = event.subevent_parameters
            if len(params) >= 11:
                role = params[3]
                peer_addr = BDAddress(params[5:11])
                # Always register peer address so SMP.start_initiator() can look it up
                if self._smp is not None:
                    self._smp.register_peer_address(handle, peer_addr)
                # Auto-encrypt on bonded reconnect (Central role only — Peripheral waits for LTK_Request)
                if (
                    self._config.auto_encrypt_on_bonded_reconnect
                    and self._config.bond_storage is not None
                    and role == 0x00  # Central
                ):
                    asyncio.create_task(
                        self._auto_encrypt_on_reconnect(handle, peer_addr)
                    )
        else:
            reason = _hci_status_text(status)
            self._emit_connection_event(StackConnectionEvent(state="failed", handle=handle, reason=reason))
            error = RuntimeError(f"LE connection failed: {reason}")
            for waiter in waiters:
                if not waiter.done():
                    waiter.set_exception(error)

    def _complete_classic_waiters(
        self,
        waiters_by_handle: dict[int, list[asyncio.Future[None]]],
        handle: int,
        status: int,
        message: str,
    ) -> None:
        waiters = waiters_by_handle.pop(handle, [])
        if status == 0:
            for waiter in waiters:
                if not waiter.done():
                    waiter.set_result(None)
            return
        error = RuntimeError(f"{message}: {_hci_status_text(status)}")
        for waiter in waiters:
            if not waiter.done():
                waiter.set_exception(error)

    def _emit_connection_event(self, event: StackConnectionEvent) -> None:
        for handler in list(self._connection_event_handlers):
            handler(event)

    def _check_writable(self) -> None:
        """Raise ReplayModeError if Stack is in REPLAY mode."""
        if self._mode == StackMode.REPLAY:
            from pybluehost.core.errors import ReplayModeError
            raise ReplayModeError(
                f"Operation not permitted in REPLAY mode (transport: "
                f"{type(self._transport).__name__})"
            )

    async def connect_gatt(
        self,
        target: BDAddress,
        *,
        timeout: float = 10.0,
    ) -> Any:
        """Connect to a BLE peer and return a GATT client bound to ATT CID."""
        self._check_writable()
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
        return GATTClient(
            bearer,
            connection_handle=handle,
            on_insufficient_encryption=self._on_gatt_insufficient_encryption,
        )

    async def _on_gatt_insufficient_encryption(self, handle: int) -> None:
        await self.pair(handle)

    async def connect_classic(
        self,
        target: BDAddress,
        *,
        timeout: float = 10.0,
    ) -> int:
        """Connect to a Classic BR/EDR peer and return the ACL handle."""
        self._check_writable()
        if self._gap is None or self._l2cap is None:
            raise RuntimeError("Stack is not initialized")

        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[int] = loop.create_future()
        self._classic_connection_waiters.append(waiter)
        try:
            await self._gap.classic_connections.connect(target)
            return await asyncio.wait_for(waiter, timeout=timeout)
        finally:
            if not waiter.done():
                waiter.cancel()
            with contextlib.suppress(ValueError):
                self._classic_connection_waiters.remove(waiter)

    async def authenticate_classic(
        self,
        handle: int,
        *,
        timeout: float = 10.0,
    ) -> None:
        """Authenticate an existing Classic ACL link and wait for completion."""
        self._check_writable()
        if self._gap is None:
            raise RuntimeError("Stack is not initialized")

        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()
        self._classic_auth_waiters.setdefault(handle, []).append(waiter)
        try:
            await self._gap.classic_connections.authenticate(handle)
            await asyncio.wait_for(waiter, timeout=timeout)
        finally:
            if not waiter.done():
                waiter.cancel()
            waiters = self._classic_auth_waiters.get(handle)
            if waiters is not None:
                with contextlib.suppress(ValueError):
                    waiters.remove(waiter)
                if not waiters:
                    self._classic_auth_waiters.pop(handle, None)

    async def pair(self, handle: int, *, timeout: float = 30.0) -> None:
        """Initiate SMP pairing as Initiator over an existing LE connection.

        Raises ReplayModeError if stack is in REPLAY mode.
        Raises RuntimeError if no SMP channel is bound for this handle
        (typically because no LE connection is open).
        """
        self._check_writable()
        if self._smp is None:
            raise RuntimeError("Stack is not initialized")
        fut = await self._smp.start_initiator(handle)
        try:
            await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(f"Pairing timeout on handle=0x{handle:04X}") from exc

    async def encrypt(self, handle: int, *, timeout: float = 5.0) -> None:
        """Restore encryption from a stored bond (Initiator/Central role).

        Looks up the peer address bound to this connection handle, loads the
        bond, and issues HCI_LE_Start_Encryption. Raises RuntimeError if no
        bond is available.

        Full integration (auto-trigger on LE_Connection_Complete) lands in Task 9.
        """
        self._check_writable()
        if self._smp is None:
            raise RuntimeError("Stack is not initialized")
        if self._config.bond_storage is None:
            raise RuntimeError("Bond storage not configured")
        # Look up peer address from SMPManager's peer-address binding (set during
        # L2CAP LE-connection-open hook in PRD 1.0 closure Plan).
        peer = self._smp._peer_addrs.get(handle)
        if peer is None:
            raise RuntimeError(f"No peer address bound for handle=0x{handle:04X}")
        bond = await self._config.bond_storage.load_bond(peer)
        if bond is None or not bond.ltk:
            raise RuntimeError(f"No bond available for peer={peer}")
        from pybluehost.hci.packets import HCI_LE_Start_Encryption_Command
        await self._hci.send_command(HCI_LE_Start_Encryption_Command(
            connection_handle=handle,
            random_number=bond.rand if bond.rand else b"\x00" * 8,
            encrypted_diversifier=bond.ediv,
            long_term_key=bond.ltk,
        ))
        # Wait for HCI_Encryption_Change is left to caller for now — Task 9 wires up event listeners

    async def enable_classic_encryption(
        self,
        handle: int,
        *,
        timeout: float = 10.0,
    ) -> None:
        """Enable encryption on an existing Classic ACL link and wait for completion."""
        self._check_writable()
        if self._gap is None:
            raise RuntimeError("Stack is not initialized")

        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()
        self._classic_encryption_waiters.setdefault(handle, []).append(waiter)
        try:
            await self._gap.classic_connections.set_encryption(handle, enabled=True)
            await asyncio.wait_for(waiter, timeout=timeout)
        finally:
            if not waiter.done():
                waiter.cancel()
            waiters = self._classic_encryption_waiters.get(handle)
            if waiters is not None:
                with contextlib.suppress(ValueError):
                    waiters.remove(waiter)
                if not waiters:
                    self._classic_encryption_waiters.pop(handle, None)

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

    @property
    def smp(self) -> Any:
        return self._smp
