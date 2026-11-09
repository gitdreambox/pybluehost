"""Stack — top-level factory that assembles all Bluetooth layers."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import BondStorage
from pybluehost.core.address import AddressType, BDAddress
from pybluehost.core.types import IOCapability
from pybluehost.pts.config import PTSModeConfig  # noqa: F401  (used by StackConfig type hint)


logger = logging.getLogger(__name__)


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

    # PTS mode (v1.2) — opt-in PTS conformance-testing tweaks. None = off.
    pts: PTSModeConfig | None = None


@dataclass(frozen=True)
class StackConnectionEvent:
    """Application-visible connection state update."""

    state: str
    handle: int | None = None
    reason: str | None = None
    peer_address: BDAddress | None = None
    # "classic" for BR/EDR links, "le" for LE — always set at the source so the
    # IUT session table can route BR connection reuse (SDP) vs LE ops without
    # guessing from the connection handle (LE handles can be >= 0x0100).
    transport: str | None = None
    # Security level reached, set on state="encrypted" only: 3 when the link is
    # authenticated (MITM), else 2. Matches the BTP SEC_LEVEL_CHANGED convention
    # in pts/btp/services/gap.py::_spawn_pair.
    sec_level: int | None = None


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
        self._eatt_listener_registered = False
        self._classic_auth_waiters: dict[int, list[asyncio.Future[None]]] = {}
        self._classic_encryption_waiters: dict[int, list[asyncio.Future[None]]] = {}
        self._encryption_waiters: dict[int, asyncio.Future[None]] = {}
        # Callbacks fired as cb(handle, peer) when the peer answers an
        # encryption request with "PIN or Key Missing" — its half of the bond is
        # gone (GAP/SEC/AUT/BV-21/22).
        self._bond_lost_cbs: list = []
        self._connection_event_handlers: list[Callable[[StackConnectionEvent], object]] = []
        # Callbacks fired as cb(handle, status, subrate_factor, peripheral_latency,
        # continuation_number, supervision_timeout) when the controller completes a
        # Connection Subrate Update procedure (GAP/CSUB).
        self._subrate_change_cbs: list = []
        # handle -> peer BDAddress for live LE connections. Tracked here (not via
        # SMP._peer_addrs, which is popped on channel-unbind before the disconnect
        # event is emitted) so the "disconnected" StackConnectionEvent can carry the
        # peer address — auto-pts's wait_for_disconnection() matches by address.
        self._le_peer_addrs: dict[int, "BDAddress"] = {}
        # Link-layer role per LE connection (0x00=central, 0x01=peripheral), from
        # LE Connection Complete. pair() is role-aware: a peripheral must send a
        # Security Request (it cannot send a Pairing Request).
        self._le_conn_roles: dict[int, int] = {}
        # Current connection parameters per LE connection (interval, latency,
        # supervision_timeout) in raw HCI units, from LE Connection Complete.
        # Reported to auto-pts in the DEVICE_CONNECTED event so its GAP model has
        # a real baseline for the Connection Parameter Update procedure
        # (PTS GAP/CONN/CPUP) — WID 46 reads conn_params and bumps latency.
        self._le_conn_params: dict[int, tuple[int, int, int]] = {}
        # Per-handle LE link-encryption state (True once Encryption Change
        # reports enabled). The GATT client uses it to gate forwarding of
        # incoming notifications/indications to the application (auto-pts):
        # a characteristic in LE security mode 1 must not be delivered to the
        # Upper Tester until the link is encrypted (PTS GAP/SEC/SEM BV-56..67).
        self._le_encrypted: dict[int, bool] = {}
        # Handles for which a bonded-reconnect re-encryption has been kicked off
        # (LE_Start_Encryption / Security Request sent) but not yet completed.
        # While pending, the GATT client queues incoming notifications instead of
        # forwarding them to the Upper Tester (PTS GAP/SEC/SEM expects delivery
        # only after the link encrypts).
        self._le_encrypt_pending: set[int] = set()
        # Non-zero Encryption_Change statuses, most recent per handle. The
        # Security-Request bond-resume watcher consumes these to detect that
        # the LT deliberately failed our re-encryption attempt (GAP.TS
        # 4.7.5.1.x: after the failure the IUT is expected to re-pair).
        self._le_encryption_failures: dict[int, int] = {}
        # The bond each handle's Security-Request resume is encrypting with, so
        # a successful Encryption_Change with no SMP context (no pairing ran)
        # can still derive the link's authenticated level — from the pairing
        # context when there is one, from this bond otherwise.
        self._le_resume_bonds: dict[int, object] = {}
        # The Security-Request auth level each handle's resume carries, reused
        # when the attempt fails and a fresh authenticated pairing is needed.
        self._le_resume_hints: dict[int, int] = {}
        # Peers whose resume was rejected and whose link died: on their next
        # connection, pair afresh instead of resuming the rejected bond
        # (peer-address-keyed hint).
        self._le_repair_pending: dict[str, int] = {}
        # Autonomous resume-repair attempts per peer, capped to avoid loops.
        self._resume_reconnects: dict[str, int] = {}
        # Pairing-internal encryption failures already answered with a fresh
        # pairing, per handle (GAP/SEC/SEM/BV-45 steps 5-6B: the LT fails the
        # encryption on purpose and expects the IUT to re-pair, not abort).
        self._pairing_repairs: dict[int, int] = {}
        # Handles whose bond-resume outcome is being watched — keeps the 0x06
        # branch and the watcher from both spawning a repair pairing.
        self._resume_watch: set[int] = set()
        # How long the resume watcher waits for the LL encryption outcome
        # before declaring the attempt silently stalled (test seam).
        self._resume_watch_timeout = 6.0
        # Optional hook fired synchronously each time a GATT-client ATT bearer is
        # created and registered as the ATT mux's _att_client_handler (connect_gatt
        # central path and the lazy peripheral path). Signature:
        # (bearer, connection_handle) -> None. pts-tester uses it to attach BTP
        # notification/indication forwarding at the earliest possible moment —
        # before PTS can send a secured indication on a reconnect (GAP/SEC/SEM).
        self.on_att_client_bearer = None

    def is_le_encrypted(self, handle: int) -> bool:
        """True if the LE link on ``handle`` is currently encrypted."""
        return bool(self._le_encrypted.get(handle, False))

    def is_le_encrypt_pending(self, handle: int) -> bool:
        """True if re-encryption has been initiated on ``handle`` but not finished."""
        return handle in self._le_encrypt_pending

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
            IsoBroadcastManager,
            PeriodicAdvertising,
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

        # PTS mode propagation (design spec §3). Single point: convert PTS-mode
        # intent into existing SecurityConfig fields so SMP only consults the
        # canonical security config.
        if cfg.pts is not None:
            if cfg.pts.secure_pair_only:
                cfg.security.sc_only_mode = True
                cfg.security.enable_secure_connections = True
            if cfg.pts.smp_options is not None:
                if len(cfg.pts.smp_options) != 6:
                    raise ValueError(
                        "pts.smp_options must be exactly 6 bytes (SMP Pairing Request body)"
                    )
            if cfg.pts.smp_failure_at is not None:
                stage = cfg.pts.smp_failure_at.split(":", 1)[-1]
                from pybluehost.ble.smp import SMPManager
                if stage not in SMPManager._VALID_PTS_FAILURE_STAGES:
                    raise ValueError(
                        f"unknown smp_failure_at stage '{stage}'; "
                        f"choose one of {sorted(SMPManager._VALID_PTS_FAILURE_STAGES)}"
                    )

        from pybluehost.ble.security import _validate_sc_dependencies
        _validate_sc_dependencies(cfg.security)
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
            security_config=cfg.security,
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
            stack._local_address = BDAddress.from_hci(raw_addr)

        # 4. L2CAP
        l2cap = L2CAPManager(hci=hci)
        stack._l2cap = l2cap
        # The LE Connection Parameter Update procedure is peripheral→central
        # only; L2CAP needs our role for a handle to reject the wrong direction.
        l2cap.set_le_role_provider(lambda h: stack._le_conn_roles.get(h, 0x00))
        # The collision back-off for an LE connection request is
        # max(100 ms, 2 x (connPeripheralLatency + 1) x connInterval), so L2CAP
        # needs the live link parameters (raw HCI units).
        l2cap.set_le_conn_params_provider(lambda h: stack._le_conn_params.get(h))

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
            security_config=cfg.security,
        )
        stack._smp = smp
        # Let SMP look up an existing bond when a Security Request arrives: a
        # bond that already meets the requested level means "encrypt", not
        # "pair again".
        smp.set_peer_address_provider(lambda h: stack._le_peer_addrs.get(h))
        smp.set_bond_resume_handler(stack._resume_encryption_with_bond)


        def _on_smp_bond_lost(handle: int, peer) -> None:
            # The peer answered our Security Request with a Pairing Request —
            # its half of the bond is gone (GAP/SEC/AUT/BV-22). Forget ours and
            # tell the upper layer. No re-pair spawn here: the pairing that
            # triggered this is already running as our responder.
            logger.info(
                "Bond lost on handle=0x%04X (peer %s answered our Security "
                "Request with a Pairing Request)", handle, peer,
            )
            asyncio.create_task(stack._purge_bond_and_notify(handle, peer))

        smp.on_bond_lost(_on_smp_bond_lost)

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
        classic_ssp = SSPManager(
            hci=hci,
            security_config=cfg.security,
            bond_storage=cfg.bond_storage,
            delegate=smp._delegate,
        )
        classic_ssp.set_io_capability(int(cfg.classic_io_capability))

        gap = GAP(
            ble_advertiser=BLEAdvertiser(hci=hci),
            ble_scanner=BLEScanner(hci=hci),
            ble_connections=BLEConnectionManager(hci=hci),
            ble_privacy=PrivacyManager(hci=hci),
            classic_discovery=ClassicDiscovery(hci=hci),
            classic_discoverability=ClassicDiscoverability(hci=hci),
            classic_connections=ClassicConnectionManager(hci=hci),
            classic_ssp=classic_ssp,
            whitelist=WhiteList(hci=hci),
            ble_extended_advertiser=ExtendedAdvertiser(hci=hci),
            periodic_advertising=PeriodicAdvertising(hci=hci),
            iso_broadcast=IsoBroadcastManager(hci=hci),
            smp=smp,
        )
        stack._gap = gap
        # Periodic advertising rides on an extended advertising set the
        # controller must have created first — give it the one from the facade.
        if gap.periodic_advertising is not None and gap.ble_extended_advertiser is not None:
            gap.periodic_advertising.bind_extended_advertiser(
                gap.ble_extended_advertiser
            )
        # Sync establishment needs scanning enabled to attempt anything at all
        # (Vol 4 Part E §7.8.67) — let it drive the shared scan engine.
        if gap.periodic_advertising is not None and gap.ble_scanner is not None:
            gap.periodic_advertising.bind_scanner(gap.ble_scanner)
        # Address rotation must pause advertising around the swap: the
        # controller refuses LE_Set_Random_Address while advertising is enabled.
        # The third hook exists because the advertising set draws its address
        # from LE_Set_Advertising_Set_Random_Address, not LE_Set_Random_Address,
        # once the extended advertising commands are in use.
        if gap.ble_privacy is not None and gap.ble_advertiser is not None:
            gap.ble_privacy.set_rotation_hooks(
                gap.ble_advertiser.pause_for_address_change,
                gap.ble_advertiser.resume_after_address_change,
                gap.ble_advertiser.set_random_address,
            )

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
        self._handle_subrate_change(event)
        if self._gap is None:
            return
        ble_scanner = getattr(self._gap, "ble_scanner", None)
        if ble_scanner is not None and hasattr(ble_scanner, "on_hci_event"):
            await ble_scanner.on_hci_event(event)
        periodic_advertising = getattr(self._gap, "periodic_advertising", None)
        if periodic_advertising is not None and hasattr(periodic_advertising, "on_hci_event"):
            await periodic_advertising.on_hci_event(event)
        iso_broadcast = getattr(self._gap, "iso_broadcast", None)
        if iso_broadcast is not None and hasattr(iso_broadcast, "on_hci_event"):
            await iso_broadcast.on_hci_event(event)
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
        logger.debug(
            "Encryption_Change handle=0x%04X status=0x%02X enabled=%d", handle, status, enabled)
        from pybluehost.hci.constants import ErrorCode
        from pybluehost.ble.smp import SMPState

        if status != 0:
            # Any encryption failure is worth one INFO line (this rig has been
            # seen reporting 0x08 LL timeout where the TS narrative says 0x06)
            # and feeds the bond-resume watcher below. The resume-bond stash
            # deliberately survives: the disconnect handler reads it to
            # recognize "resume rejected and link died".
            self._le_encryption_failures[handle] = status
            logger.info(
                "Encryption failed on handle=0x%04X status=0x%02X", handle, status)

        # A pairing-internal encryption failure while WE are central is not
        # necessarily the end of the pairing: GAP.TS step "The Lower Tester
        # fails the encryption procedure" (GAP/SEC/SEM/BV-45 steps 5-6B)
        # expects the IUT to answer it with a fresh pairing on the live link.
        # Intercept before the state machine fires the terminal transition —
        # that transition sends Pairing Failed to the peer, which kills the
        # link the re-pairing needs. Resume-driven failures keep their own
        # watcher (`_resume_watch`), and peripherals cannot initiate pairing.
        pairing_repair_hint: int | None = None
        if (
            status != 0
            and self._pairing_in_flight(handle)
            and self._le_conn_roles.get(handle, 0x00) == 0x00
            and handle not in self._resume_watch
            and self._smp is not None
        ):
            repair_ctx = self._smp.get_context(handle)
            if repair_ctx is not None and self._pairing_repairs.get(handle, 0) < 2:
                pairing_repair_hint = int(getattr(repair_ctx, "local_auth_req", 0) or 0)
                self._pairing_repairs[handle] = self._pairing_repairs.get(handle, 0) + 1
                # Retire the aborted attempt without a Pairing Failed on air:
                # the fresh pairing from _repair_pairing replaces the terminal
                # context (start_initiator accepts BONDED/FAILED contexts).
                repair_ctx.state_machine.state = SMPState.FAILED
                waiter = getattr(repair_ctx, "pairing_complete", None)
                if waiter is not None and not waiter.done():
                    waiter.set_exception(RuntimeError(
                        "SMP pairing failed (encryption phase; re-pairing)"))
                logger.info(
                    "Encryption failed during pairing on handle=0x%04X — "
                    "pairing afresh (attempt %d)",
                    handle, self._pairing_repairs[handle],
                )
                asyncio.create_task(self._repair_pairing(handle, pairing_repair_hint))

        if status == ErrorCode.PIN_KEY_MISSING:
            # The peer refused to encrypt with the LTK it distributed earlier, so
            # its half of the bond is gone. Forget our half and tell the upper
            # layer — that is the whole pass verdict of GAP/SEC/AUT/BV-21/22.
            peer = self._le_peer_addrs.get(handle)
            logger.info(
                "Bond lost on handle=0x%04X (peer %s answered PIN or Key Missing)",
                handle, peer,
            )
            await self._purge_bond_and_notify(handle, peer)
            # The peer just told us its half of the bond is gone, so resuming
            # encryption is impossible — the only way to restore security is a
            # fresh pairing. Core Vol 3 Part H §3.6.1 sanctions pairing as the
            # response to a Security Request, and the GAP/SEC/AUT family
            # expects it (BV-20 step 1B.3 "The IUT may initiate the pairing
            # procedure"; BV-24/25/27 phase 2 stall in INDCSV without it
            # because the LT drops its bond at disconnect, then waits for the
            # re-encryption forever). Central side only: a peripheral sending
            # a Pairing Request is a protocol violation (§3.2).
            if (
                self._le_conn_roles.get(handle, 0x00) == 0x00  # Central
                and handle in self._le_peer_addrs
                and self._smp is not None
                and handle not in self._resume_watch  # the watcher owns it
                and not self._pairing_in_flight(handle)
            ):
                logger.info(
                    "Bond lost on handle=0x%04X while central — re-pairing to restore security",
                    handle,
                )
                asyncio.create_task(self._repair_pairing(handle))
        if self._smp is not None and pairing_repair_hint is None:
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
        # Resolve any Stack.encrypt() waiter pending on this handle
        waiter = self._encryption_waiters.pop(handle, None)
        if waiter is not None and not waiter.done():
            if status == 0 and enabled:
                waiter.set_result(None)
            else:
                waiter.set_exception(RuntimeError(
                    f"encryption failed on handle=0x{handle:04X} status=0x{status:02X}"
                ))
        if status == 0 and enabled:
            self._le_encrypted[handle] = True
            self._le_encrypt_pending.discard(handle)
            self._le_encryption_failures.pop(handle, None)
            # Resolve authenticated/key_size once for the GATT server, the L2CAP
            # manager's security enforcement, and the "encrypted" event (which
            # feeds BTP SEC_LEVEL_CHANGED — auto-pts advances its sec_level
            # model only via that event, so a bond-resume that never pairs must
            # still report it: PTS GATT/SR/GAR/BV-11/12).
            authenticated = False
            key_size = 16
            ctx = self._smp.get_context(handle) if self._smp is not None else None
            if ctx is not None:
                authenticated = bool(getattr(ctx, "local_auth_req", 0) & 0x04) \
                    and bool(getattr(ctx, "peer_auth_req", 0) & 0x04)
                key_size = min(getattr(ctx, "peer_max_key_size", 16) or 16, 16)
            else:
                # A bond-resume (peer Security Request answered from the stored
                # LTK) never creates a pairing context, so the context cannot
                # describe the link — take the level from the bond that was
                # used, or the gate reads unauthenticated and the LT's
                # post-encryption service request still gets ErrRsp 0x05
                # (GAP/SEC/AUT/BV-24 phase 2).
                bond = self._le_resume_bonds.pop(handle, None)
                if bond is not None:
                    authenticated = bool(getattr(bond, "authenticated", False))
                    key_size = min(int(getattr(bond, "key_size", 16) or 16), 16)
            self._emit_connection_event(StackConnectionEvent(
                state="encrypted", handle=handle,
                peer_address=self._le_peer_addrs.get(handle),
                sec_level=3 if authenticated else 2,
            ))
            # Reflect link security into the GATT server so it can enforce the
            # ENC/AUTHN/AUTHZ permission bits and return the exact ATT error
            # code (PTS GATT/SR BI error-handling cases depend on this).
            if self._gatt_server is not None:
                self._gatt_server.set_connection_security(
                    handle, encrypted=True, authenticated=authenticated, key_size=key_size)
            # Mirror the same link-security state into the L2CAP manager so the
            # LE CoC listener can enforce a PSM's required security level (PTS
            # L2CAP/LE/CFC security-responder cases BV-11/13/15/25).
            if self._l2cap is not None and hasattr(self._l2cap, "set_le_connection_security"):
                self._l2cap.set_le_connection_security(
                    handle, encrypted=True, authenticated=authenticated, key_size=key_size)
            # The resume concluded successfully either way — clear the stash so
            # a later disconnect is not mistaken for a rejected resume.
            self._le_resume_bonds.pop(handle, None)
            self._le_resume_hints.pop(handle, None)

    async def _on_le_ltk_request(self, handle: int, rand: bytes, ediv: int) -> None:
        """Reply to LE_LTK_Request — pairing-time uses active SMP ctx.stk;
        reconnect-time looks up bond by (ediv, rand)."""
        from pybluehost.hci.packets import (
            HCI_LE_LTK_Request_Negative_Reply_Command,
            HCI_LE_LTK_Request_Reply_Command,
        )
        # Pairing-time LTK request: rand=0, ediv=0
        # SC sessions use the f5-derived ltk_sc; Legacy sessions use STK.
        if ediv == 0 and rand == b"\x00" * 8 and self._smp is not None:
            ctx = self._smp.get_context(handle)
            if ctx is not None:
                ltk = ctx.ltk_sc if ctx.ltk_sc else ctx.stk
                if ltk:
                    await self._hci.send_command(HCI_LE_LTK_Request_Reply_Command(
                        connection_handle=handle, long_term_key=ltk,
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
        key = str(peer_addr)
        if key in self._le_repair_pending:
            # The last resume with this peer was rejected (and its link died):
            # pair afresh instead of resuming the same rejected bond.
            hint = self._le_repair_pending.pop(key)
            logger.info(
                "Pairing afresh with %s — the previous resume was rejected", peer_addr)
            self._le_encrypt_pending.discard(handle)
            asyncio.create_task(self._repair_pairing(handle, hint))
            return
        bond = await self._load_bond_for_peer(peer_addr)
        if bond is None or not bond.ltk:
            # No bond: clear the optimistic pending flag so this peer's
            # notifications are not held back (plain GATT/GAN unaffected).
            self._le_encrypt_pending.discard(handle)
            return
        if getattr(bond, "sc", False):
            # Secure Connections bond: resume is unreliable (SC uses EDIV=0 /
            # RAND=0, so the peripheral must identify the LTK by address) and
            # SC test flows (SM/*/SCOB, SC re-pair rounds) pair FRESH each round
            # via an explicit Pairing Request. Resuming here races that explicit
            # pairing — the stale-bond LL_ENC_REQ collides with the new pairing
            # and the link drops (supervision timeout 0x08) before round 2 can
            # pair (SM/CEN/SCOB/BV-01 INDCSV). Skip the resume; the explicit
            # pairing re-establishes encryption. Legacy (EDIV/RAND) bonds still
            # resume (GAP/SEC/SEM bonded-reconnect relies on it).
            #
            # Deliberately do NOT clear `_le_encrypt_pending`: the bond is there,
            # so this link is still expected to reach an encrypted state (the
            # peer, or our own pairing, will do it). The gate that holds
            # indications/notifications until encryption (GAP.TS Table 4.20 step
            # 9A.4/9B.4) reads that flag, and clearing it made the Central-role
            # SC cases report an unencrypted IND#1 to the Upper Tester
            # (GAP/SEC/SEM/BV-63/64/67). It is cleared for real on
            # Encryption_Change. The Peripheral path keeps it set for the same
            # reason, which is why BV-57 passed all along.
            return
        if handle in self._resume_watch or self._pairing_in_flight(handle):
            # A Security-Request resume is already running for this link —
            # it is the same re-encryption this path wants; do not pile a
            # second LL procedure (or a second watcher) onto the handle.
            return
        self._le_encrypt_pending.add(handle)
        await self._hci.send_command(HCI_LE_Start_Encryption_Command(
            connection_handle=handle,
            random_number=bond.rand if bond.rand else b"\x00" * 8,
            encrypted_diversifier=bond.ediv,
            long_term_key=bond.ltk,
        ))
        # Watch the outcome like the Security-Request resume: the LT may
        # deliberately fail this encryption (GAP/SEC/AUT/BV-19 step 3b) and
        # then expects the IUT to re-pair on its own (step 4) — so start a
        # fresh pairing while the link is still alive (this rig's LT stalls
        # the LL procedure and the link dies with it).
        self._le_resume_bonds[handle] = bond
        self._le_resume_hints[handle] = 0x0D if getattr(bond, "authenticated", False) else 0
        self._resume_watch.add(handle)
        asyncio.create_task(self._watch_resume_outcome(
            handle, 0x0D if getattr(bond, "authenticated", False) else 0))

    async def _auto_security_request_on_reconnect(self, handle: int, peer_addr: "BDAddress") -> None:
        """Peripheral bonded-reconnect: ask the central to re-establish encryption.

        On a bonded reconnect the central commonly waits for the *peripheral* to
        request security before re-encrypting (PTS GAP/SEC/SEM round-2 expects
        exactly this). Send an SMP Security Request so the central re-encrypts
        with the stored LTK. No-op when there is no bond for the peer.
        """
        bond = await self._load_bond_for_peer(peer_addr)
        if bond is None or not bond.ltk:
            self._le_encrypt_pending.discard(handle)
            return
        # Build the AuthReq from the individual flags rather than the blanket
        # auth_requirements (0x0D includes MITM). A peripheral re-encryption
        # request must NOT force MITM: when the existing bond is Just Works
        # (Security Mode 1 Level 2), a MITM bit can't be satisfied without
        # re-pairing, so the central ignores the request and never re-encrypts
        # (PTS GAP/SEC/SEM/BV-56 FAIL). Request Bonding (+SC), MITM only when
        # explicitly required.
        sec = self._config.security
        auth_req = 0x01  # bonding
        if getattr(sec, "enable_secure_connections", False):
            auth_req |= 0x08
        if getattr(sec, "mitm_required", False):
            auth_req |= 0x04
        # The SMP fixed channel is bound by the L2CAP connection-open callback,
        # which runs after LE Connection Complete — retry until it appears.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 2.0
        while True:
            # Re-check under the (possibly late-scheduled) task: if a pairing
            # context exists or the link is already encrypted, the need for a
            # Security Request has passed — a pairing may have completed while
            # this task waited for its first scheduling slot (the bond lookup
            # then finds the just-stored bond and sends a redundant SecReq
            # that wedges PTS: L2CAP/ECFC/BV-11 never receives its 0x17).
            if self._smp.get_context(handle) is not None \
                    or self.is_le_encrypted(handle):
                self._le_encrypt_pending.discard(handle)
                return
            try:
                self._le_encrypt_pending.add(handle)
                await self._smp.request_security(handle, auth_req=auth_req)
                return
            except RuntimeError:
                self._le_encrypt_pending.discard(handle)
                if loop.time() >= deadline:
                    return
                await asyncio.sleep(0.01)

    async def _resume_encryption_with_bond(
        self, handle: int, bond, auth_req: int = 0,
    ) -> None:
        """Start LL encryption from a stored bond, on a peer Security Request.

        Same effect as ``_auto_encrypt_on_reconnect`` but a different trigger:
        there *we* decide to resume on connect, here the peer explicitly asked
        for an encrypted link. That difference is why the SC-bond carve-out in
        the reconnect path does not apply — the "stale LL_ENC_REQ races the
        peer's fresh pairing" hazard exists only when we jump the gun.

        ``auth_req`` is the Security Request's requested level, reused when
        the attempt fails and a fresh *authenticated* pairing is needed
        instead (GAP.TS 4.7.5.1.x makes the LT fail this first encryption on
        purpose and then expects a re-pair).
        """
        if bond is None or not bond.ltk or self._le_encrypted.get(handle):
            return
        if handle in self._resume_watch or self._pairing_in_flight(handle):
            # A resume attempt is already in flight (or a repair pairing is
            # running): it *is* the answer to this Security Request — a second
            # LL encryption procedure would collide with it.
            return
        from pybluehost.hci.packets import HCI_LE_Start_Encryption_Command
        # Remember which bond this attempt encrypts with (and the requested
        # level) so the success path can derive the link level without a
        # pairing context, and a rejected attempt can reconnect-and-repair.
        self._le_resume_bonds[handle] = bond
        self._le_resume_hints[handle] = auth_req
        self._le_encrypt_pending.add(handle)
        self._le_encryption_failures.pop(handle, None)
        await self._hci.send_command(HCI_LE_Start_Encryption_Command(
            connection_handle=handle,
            random_number=bond.rand if bond.rand else b"\x00" * 8,
            encrypted_diversifier=bond.ediv,
            long_term_key=bond.ltk,
        ))
        self._resume_watch.add(handle)
        asyncio.create_task(self._watch_resume_outcome(handle, auth_req))

    async def _watch_resume_outcome(self, handle: int, auth_req: int) -> None:
        """Repair with a fresh pairing when the bond resume fails.

        GAP.TS 4.7.5.1.1/4.7.5.1.2 (BV-25/26/27/28): the LT deliberately fails
        the IUT's post-reconnect encryption attempt and then expects the IUT
        to pair afresh. On this rig the failure arrives as *any* non-zero
        Encryption_Change status (0x08 LL timeout observed, not just 0x06) —
        or never arrives at all when the LT simply stops answering the LL
        procedure. Either way the link stays up but unencrypted, and for a
        central a fresh pairing (Core Vol 3 Part H §3.6.1) is the only way to
        restore security.
        """
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._resume_watch_timeout
            failed = False
            while True:
                if self._le_encrypted.get(handle):
                    return
                if handle not in self._le_peer_addrs:
                    # Link dropped mid-watch: nothing to pair on, and the
                    # pending marker must not leak onto a recycled handle.
                    self._le_encrypt_pending.discard(handle)
                    return
                if self._le_encryption_failures.pop(handle, None) is not None:
                    failed = True
                    break
                if loop.time() >= deadline:
                    failed = True  # silent stall: LT never answers the procedure
                    break
                await asyncio.sleep(0.02)
            if not failed:
                return
            if handle not in self._le_peer_addrs:
                # The link died with the failed procedure — the disconnect
                # handler owns the reconnect-and-repair from here.
                return
            if self._le_conn_roles.get(handle, 0x00) != 0x00:  # Central only
                return
            if self._smp is None or self._pairing_in_flight(handle):
                return  # a pairing is already in flight — let it finish
            logger.info(
                "Bond resume failed on handle=0x%04X — starting fresh pairing",
                handle,
            )
            await self._repair_pairing(handle, auth_req)
        finally:
            self._resume_watch.discard(handle)

    async def _reconnect_and_repair(self, peer: "BDAddress", hint: int) -> None:
        """Reconnect to a peer whose resume rejection killed the link, and pair
        afresh on the new connection (the fresh pairing is driven by the
        repair-pending hook in ``_auto_encrypt_on_reconnect``).

        GAP.TS Tables 4.31/4.32 (BV-24/25/26/27/28) make the LT fail the IUT's
        post-reconnect encryption on purpose and then expect user-interaction
        pairing; on this rig that rejection also drops the connection, so the
        procedure can only continue if the central reconnects on its own.
        """
        key = str(peer)
        attempts = self._resume_reconnects.get(key, 0)
        if attempts >= 2:
            logger.info(
                "Not reconnecting to %s after a rejected resume: %d attempts used",
                peer, attempts,
            )
            return
        self._resume_reconnects[key] = attempts + 1
        self._le_repair_pending[key] = hint
        logger.info(
            "Bond resume rejected and link dropped — reconnecting to %s for a fresh pairing",
            peer,
        )
        try:
            await self.connect_gatt(peer, timeout=10.0)
        except Exception as exc:
            logger.info("Auto-reconnect to %s failed: %s", peer, exc)
            self._le_repair_pending.pop(key, None)

    def _pairing_in_flight(self, handle: int) -> bool:
        """True while an SMP pairing is mid-flight on ``handle``.

        A finished context (BONDED / FAILED) does not count: the fresh pairing
        a repair spawns simply replaces it. Blocking on those would deadlock
        the BV-25/27 flow, whose encryption failure lands right *after* the
        preamble pairing completed.
        """
        if self._smp is None:
            return False
        from pybluehost.ble.smp import SMPState

        ctx = self._smp.get_context(handle)
        if ctx is None:
            return False
        return ctx.state_machine.state not in (SMPState.BONDED, SMPState.FAILED)

    async def _purge_bond_and_notify(self, handle: int, peer) -> None:
        """Forget our half of a dead bond and tell the upper layer.

        Shared by both lost-bond signals: the peer answering an encryption
        request with "PIN or Key Missing" (Encryption_Change status 0x06), and
        the peer answering our Security Request with a Pairing Request
        (SMPManager bond-lost callback). Fires the ``on_bond_lost`` listeners
        the BTP GAP layer subscribes to (BOND_LOST event, BTP 0x8B).
        """
        storage = getattr(self.config, "bond_storage", None)
        delete = getattr(storage, "delete_bond", None)
        if peer is not None and delete is not None:
            try:
                await delete(peer)
            except Exception:
                logger.exception("bond purge failed for %s", peer)
        for cb in self._bond_lost_cbs:
            try:
                cb(handle, peer)
            except Exception:
                logger.exception("bond-lost notification raised")

    async def _repair_pairing(self, handle: int, auth_req: int = 0) -> None:
        """Fresh pairing after a Key Missing (bond dead on the peer side).

        Fire-and-forget from ``_on_encryption_change``: a peer that lost its
        bond (LT drops it at disconnect in GAP/SEC/AUT BV-24/25/27) can never
        supply the LTK again, so re-pairing is the only path to an encrypted
        link. ``auth_req`` (the peer Security Request's level, when the repair
        comes from the resume watcher) is mirrored into the fresh Pairing
        Request so the re-pair reaches the level the case demands — an
        unauthenticated Just-Works re-pair defeats the point of the
        authenticated-bond family. Failures are logged and dropped — the
        caller is an HCI event handler and must not block on the pairing
        outcome.
        """
        try:
            await self._smp.start_initiator(
                handle, peer_sec_req_auth_req=auth_req or None)
        except Exception as exc:
            logger.info("re-pairing after bond loss failed on handle=0x%04X: %s", handle, exc)

    async def _load_bond_for_peer(self, peer_addr: "BDAddress"):
        storage = self._config.bond_storage
        if storage is None:
            return None
        bond = await storage.load_bond(peer_addr)
        if bond is not None:
            return bond
        if peer_addr.type not in (AddressType.RANDOM, AddressType.RANDOM_IDENTITY):
            return None

        from pybluehost.ble.gap import PrivacyManager

        for candidate in await storage.list_bonds():
            # resolve_rpa works on the on-air (little-endian) address bytes;
            # `BDAddress.address` is the display order, so convert.
            wire = peer_addr.to_hci() if hasattr(peer_addr, "to_hci") else bytes(peer_addr)
            if candidate.irk and PrivacyManager.resolve_rpa(wire, candidate.irk):
                return candidate
        return None

    async def _reset_gatt_cccd_if_unbonded(
        self, handle: int, value_handles: list[int], peer_addr: "BDAddress",
    ) -> None:
        """Reset a departed client's CCCD values unless it was bonded.

        Core Vol 3 Part G §3.3.3.3 persists a client's CCCD only for bonded
        clients, and GATT.TS GAN/BV-01 step 5A reads the CCCD after reconnect
        and expects 0x0000 (GAN/BV-03 step 5B, the bonded twin, expects
        0x0001). The disconnection handler is synchronous, so the bond lookup
        happens here, right after ``remove_connection``.
        """
        try:
            bonded = (await self._load_bond_for_peer(peer_addr)) is not None
        except Exception:
            logger.exception(
                "bond lookup failed on disconnect handle=0x%04X", handle)
            return
        if bonded or self._gatt_server is None:
            return
        self._gatt_server.reset_unbonded_cccd(handle, value_handles)
        logger.debug(
            "GATT conn=0x%04X not bonded: reset CCCD %s",
            handle, [hex(h) for h in value_handles])

    def _attach_gatt_server_to_att_channels(self) -> None:
        if self._l2cap is None or self._gatt_server is None:
            return

        from pybluehost.ble.att import (
            ATT_Handle_Value_Indication, ATT_Handle_Value_Notification,
            ATT_Multiple_Handle_Value_Notification,
        )
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

        async def on_indication(handle: int, value: bytes, conn_handle: int) -> bool:
            channel = self._l2cap.get_fixed_channel(conn_handle, CID_ATT)
            if channel is None:
                return False  # connection gone — the server defers the SC indication
            indication = ATT_Handle_Value_Indication(
                attribute_handle=handle,
                attribute_value=value,
            )
            await channel.send(indication.to_bytes())
            return True

        async def on_multiple_notification(hlv: list[tuple[int, bytes]], conn_handle: int) -> None:
            channel = self._l2cap.get_fixed_channel(conn_handle, CID_ATT)
            if channel is None:
                return
            notification = ATT_Multiple_Handle_Value_Notification(hlv=hlv)
            await channel.send(notification.to_bytes())

        self._gatt_server.on_notification_sent(on_notification)
        self._gatt_server.on_indication_sent(on_indication)
        self._gatt_server.on_multiple_notification_sent(on_multiple_notification)

        connections = getattr(self._l2cap, "_connections", {})
        for handle, channels in connections.items():
            channel = channels.get(CID_ATT)
            if channel is None or getattr(channel, "_gatt_server_bound", False):
                continue
            self._bind_gatt_server_to_channel(channel, conn_handle=handle, bearer_cid=CID_ATT)
            # Flush a Service Changed indication deferred while the bonded
            # client was disconnected (GAS/BV-01, BV-07): the Lower Tester
            # waits for it on reconnect without sending an ATT request first,
            # so it must be driven by the connection open. Fixed channel only —
            # EATT bearers attach after the connection is already up.
            asyncio.create_task(self._gatt_server.on_connection_opened(handle))

        self._ensure_eatt_listener()

    def _bind_gatt_server_to_channel(self, channel: Any, *, conn_handle: int, bearer_cid: int) -> None:
        """Attach the GATT server to one ATT-carrying channel (fixed ATT
        channel or EATT bearer). The ATT mux routes requests to the server with
        the bearer identity so per-bearer state (ATT_MTU, DoS marker) stays
        separate while per-client state (prepare queue, CCCD) is shared."""
        from pybluehost.ble.att import decode_att_pdu
        from pybluehost.l2cap.channel import install_att_channel_mux

        if getattr(channel, "_gatt_server_bound", False):
            return

        async def on_att_data(data: bytes, *, ch: Any = channel, handle: int = conn_handle, cid: int = bearer_cid) -> None:
            pdu = decode_att_pdu(data)
            response = await self._gatt_server.handle_request(handle, pdu, bearer_cid=cid)
            if response is None:
                # Write Command / Signed Write Command — never answered.
                return
            await ch.send(response.to_bytes())

        # Register the server into the ATT mux rather than set_events() —
        # a GATT client bearer may share this channel (GAP/SEC) and must not
        # be clobbered (and vice versa).
        install_att_channel_mux(channel)
        channel._att_server_handler = on_att_data

        async def on_confirmation(data: bytes, *, handle: int = conn_handle) -> None:
            # Handle Value Confirmation for the server's Service Changed
            # indication — clears the client's change-unaware flag so the
            # next read proceeds (GAS/BV-06).
            self._gatt_server.on_confirmation(handle)

        channel._att_confirmation_handler = on_confirmation
        setattr(channel, "_gatt_server_bound", True)
        logger.debug("GATT server bound to ATT channel conn=0x%04X cid=0x%04X", conn_handle, bearer_cid)

    def _ensure_eatt_listener(self) -> None:
        """Register the inbound EATT listener exactly once.

        EATT bearers are Enhanced Credit-Based channels on the fixed SPSM
        0x0027 and may only be established on an encrypted link (Core Vol 3
        Part G §5.2) — required_security=4 makes the L2CAP manager refuse
        unencrypted attempts with 0x0008 (Insufficient Encryption)."""
        if self._eatt_listener_registered:
            return
        listen = getattr(self._l2cap, "listen_le_coc_channel", None)
        if listen is None:
            return
        from pybluehost.l2cap.constants import PSM_EATT
        listen(PSM_EATT, self.attach_eatt_bearer, required_security=4)
        self._eatt_listener_registered = True

    def attach_eatt_bearer(self, channel: Any) -> None:
        """Attach the GATT server to an EATT channel — inbound (via the
        PSM_EATT listener) or outbound (BTP EATT_CONNECT). The bearer's ATT_MTU
        is the channel's negotiated L2CAP MTU (no Exchange MTU on EATT)."""
        if self._gatt_server is None:
            return
        self._gatt_server.add_eatt_bearer(
            channel.connection_handle, channel.cid, mtu=channel.mtu)
        self._bind_gatt_server_to_channel(
            channel, conn_handle=channel.connection_handle, bearer_cid=channel.cid)

    def on_connection_event(self, handler: Callable[[StackConnectionEvent], object]) -> None:
        self._connection_event_handlers.append(handler)

    def on_bond_lost(self, handler: Callable[[int, Any], object]) -> None:
        """Register ``handler(handle, peer)`` for a bond the peer has dropped."""
        self._bond_lost_cbs.append(handler)

    def on_subrate_change(self, handler: Callable[..., object]) -> None:
        """Register ``handler(handle, status, subrate_factor, latency, cont, timeout)``
        for LE Subrate Change events (GAP/CSUB)."""
        self._subrate_change_cbs.append(handler)

    def _handle_subrate_change(self, event: Any) -> None:
        from pybluehost.hci.constants import LEMetaSubEvent
        from pybluehost.hci.packets import HCI_LE_Meta_Event

        if not isinstance(event, HCI_LE_Meta_Event):
            return
        if event.subevent_code != LEMetaSubEvent.LE_SUBRATE_CHANGE:
            return
        params = event.subevent_parameters
        # Status(1) + Connection_Handle(2) + Subrate_Factor(2) + Peripheral_Latency(2)
        # + Continuation_Number(2) + Supervision_Timeout(2) — Vol 4 Part E §7.7.65.35.
        if len(params) < 11:
            return

        import struct

        status = params[0]
        handle, factor, latency, cont, timeout = struct.unpack_from("<HHHHH", params, 1)
        logger.debug(
            "LE Subrate Change handle=0x%04X status=0x%02X factor=%d latency=%d cont=%d timeout=%d",
            handle, status, factor, latency, cont, timeout,
        )
        for cb in list(self._subrate_change_cbs):
            cb(handle, status, factor, latency, cont, timeout)

    def _le_link_local_address(self, params: bytes) -> "BDAddress | None":
        """The random local address a fresh LE link was established with.

        SMP's Secure Connections f5/f6 (and the legacy c1) hash the addresses
        used *on air*. When we advertise or initiate from a host-programmed
        random address the controller does not report it back — the Enhanced
        Connection Complete's Local_RPA field is only filled for
        controller-generated privacy — so the stack has to remember what it
        programmed. Without this a peer that connected to our RPA computes its
        DHKey Check with that RPA while we hash the public identity, and every
        Secure Connections pairing over a private address dies as Pairing
        Failed 0x0B (GAP/PRIV/CONN/BV-10-C).
        """
        role = params[3]
        if role == 0x01:  # Peripheral — the link came from our advertising
            advertiser = getattr(self.gap, "ble_advertiser", None)
            raw = getattr(advertiser, "advertising_address", None)
            if raw:
                # Programmed addresses are in HCI (little-endian) order.
                return BDAddress.from_hci(bytes(raw), type=AddressType.RANDOM)
            return None
        connections = getattr(self.gap, "ble_connections", None)
        if getattr(connections, "initiator_own_address_type", 0x00) != 0x01:
            return None
        privacy = getattr(self.gap, "ble_privacy", None)
        raw = getattr(privacy, "_current_address", None)
        if raw:
            return BDAddress.from_hci(bytes(raw), type=AddressType.RANDOM)
        return None

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
                    self._gap.classic_connections.accept(BDAddress.from_hci(params[:6]), role=0x01)
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
                # Resolve the peer address so listeners (pts-tester's DEVICE_
                # DISCONNECTED synthesis) can identify the peer. Pop it — the
                # connection is gone. Without this the disconnect event has no
                # peer_address and auto-pts's wait_for_disconnection() times out.
                peer_addr = self._le_peer_addrs.pop(event.connection_handle, None)
                if self._gatt_server is not None:
                    # A non-bonded client's CCCD values are reset at disconnect
                    # (Core Vol 3 Part G §3.3.3.3; GATT.TS GAN/BV-01 step 5A)
                    # while a bonded client's persist (GAN/BV-03 step 5B). The
                    # bond lookup is async and this handler is sync, so snapshot
                    # what the client had subscribed to and settle it in a task.
                    enabled_cccds = self._gatt_server.connection_cccd_handles(
                        event.connection_handle)
                    self._gatt_server.remove_connection(event.connection_handle)
                    if peer_addr is not None and enabled_cccds:
                        asyncio.create_task(self._reset_gatt_cccd_if_unbonded(
                            event.connection_handle, enabled_cccds, peer_addr))
                # Capture the LE role BEFORE popping it — the reconnect
                # branches below are central-only (a peripheral's next
                # connection belongs to its peer, not to us).
                le_role = self._le_conn_roles.pop(event.connection_handle, 0x00)
                self._le_conn_params.pop(event.connection_handle, None)
                self._le_encrypted.pop(event.connection_handle, None)
                self._le_encrypt_pending.discard(event.connection_handle)
                self._pairing_repairs.pop(event.connection_handle, None)
                resume_bond = self._le_resume_bonds.pop(event.connection_handle, None)
                resume_hint = self._le_resume_hints.pop(event.connection_handle, 0)
                if (
                    resume_bond is not None
                    and peer_addr is not None
                    and le_role == 0x00
                    and self._config.auto_encrypt_on_bonded_reconnect
                ):
                    # A bond resume was still in flight when the link died: the
                    # peer rejected the re-encryption and dropped the connection
                    # (GAP.TS Tables 4.31/4.32 step 6A — and on this rig the
                    # rejection kills the link within moments, so no in-place
                    # repair is possible). Reconnect and pair afresh.
                    asyncio.create_task(
                        self._reconnect_and_repair(peer_addr, resume_hint)
                    )
                # Otherwise leave reconnection to the upper tester. A scripted
                # Pairing Failed before the drop is not a usable "peer waits for
                # us" signal: AUT/BV-25 and BV-27 share that fingerprint, and an
                # autonomous reconnect stalls BV-25 by racing its WID connect.
                # A rejected bond-resume above is different — that is our own
                # explicit recovery flow, so reconnect-and-repair remains there.
                self._emit_connection_event(
                    StackConnectionEvent(
                        state="disconnected",
                        handle=event.connection_handle,
                        peer_address=peer_addr,
                        reason=_hci_status_text(event.reason),
                    )
            )
            return
        if isinstance(event, HCI_Connection_Complete_Event):
            waiters = self._classic_connection_waiters
            self._classic_connection_waiters = []
            if event.status == ErrorCode.SUCCESS:
                self._emit_connection_event(
                    StackConnectionEvent(
                        state="connected", handle=event.connection_handle,
                        peer_address=BDAddress.from_hci(
                            event.bd_addr, type=AddressType.PUBLIC),
                        # HCI_Connection_Complete is always a BR/EDR link — mark it
                        # "classic" unconditionally. (Was gated on link_type == 0,
                        # but 0x00 = SCO; classic ACL is 0x01, so ACL links were
                        # left untagged and relied on a handle-threshold guess.)
                        transport="classic",
                    )
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
            params = event.subevent_parameters
            peer_addr = None
            if len(params) >= 11:
                peer_addr = BDAddress.from_hci(params[5:11], type=AddressType(params[4]))
                self._le_peer_addrs[handle] = peer_addr
                if self._smp is not None:
                    self._smp.register_peer_address(handle, peer_addr)
                    local_addr = self._le_link_local_address(params)
                    if local_addr is not None:
                        self._smp.register_local_address(handle, local_addr)
            # Capture current connection params (interval/latency/supervision
            # timeout) BEFORE emitting the connected event — listeners (pts-tester's
            # DEVICE_CONNECTED synthesis) read _le_conn_params synchronously. Layout
            # differs between LE Connection Complete (0x01) and Enhanced (0x0A, which
            # inserts local+peer RPA after the peer address, shifting params by 12).
            poff = 11 if event.subevent_code == LEMetaSubEvent.LE_CONNECTION_COMPLETE else 23
            if len(params) >= poff + 6:
                self._le_conn_params[handle] = (
                    struct.unpack_from("<H", params, poff)[0],
                    struct.unpack_from("<H", params, poff + 2)[0],
                    struct.unpack_from("<H", params, poff + 4)[0],
                )
            # A fresh LE link starts unencrypted; reset the gate so a reused
            # handle from a prior (encrypted) connection doesn't leak state.
            self._le_encrypted[handle] = False
            self._emit_connection_event(
                StackConnectionEvent(
                    state="connected", handle=handle, peer_address=peer_addr,
                    # Mark LE explicitly: LE handles can be >= 0x0100 (AX201
                    # hands out 0x0E01), so a handle-threshold guess in the IUT
                    # session table would mis-mark this as "classic".
                    transport="le",
                )
            )
            for waiter in waiters:
                if not waiter.done():
                    waiter.set_result(handle)
            # Register peer address in SMP + optional auto-encrypt on bonded reconnect
            if len(params) >= 11 and peer_addr is not None:
                role = params[3]
                self._le_conn_roles[handle] = role
                # Auto-encrypt on bonded reconnect (Central role only — Peripheral waits for LTK_Request)
                if (
                    self._config.auto_encrypt_on_bonded_reconnect
                    and self._config.bond_storage is not None
                    and role == 0x00  # Central
                ):
                    # Set encrypt-pending *synchronously*, before the task's bond
                    # lookup awaits: an indication PTS sends immediately on the
                    # reconnect (GAP/SEC/SEM/BV-62) must be held, not leaked. The
                    # task clears it if no bond is found.
                    self._le_encrypt_pending.add(handle)
                    asyncio.create_task(
                        self._auto_encrypt_on_reconnect(handle, peer_addr)
                    )
                elif (
                    self._config.auto_encrypt_on_bonded_reconnect
                    and self._config.bond_storage is not None
                    and role == 0x01  # Peripheral
                    and self._smp is not None
                ):
                    # Peripheral: the central waits for us to request security
                    # before re-encrypting a bonded link (PTS GAP/SEC/SEM).
                    self._le_encrypt_pending.add(handle)
                    asyncio.create_task(
                        self._auto_security_request_on_reconnect(handle, peer_addr)
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
        filter_policy: int = 0x00,
        own_address_type: int | None = None,
    ) -> Any:
        """Connect to a BLE peer and return a GATT client bound to ATT CID.

        ``filter_policy`` 0x01 asks the controller to ignore ``target`` and
        connect to whatever advertises matching its filter accept list — the
        Auto Connection Establishment procedure (GAP/CONN/ACEP).
        ``own_address_type`` overrides the initiator's own address type (0x01
        = random — an RPA programmed earlier, GAP/CONN/ACEP BV-03/04).
        """
        self._check_writable()
        if self._gap is None or self._l2cap is None:
            raise RuntimeError("Stack is not initialized")

        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[int] = loop.create_future()
        self._le_connection_waiters.append(waiter)
        try:
            # High-duty-cycle scan window while initiating: PTS (and sparse
            # advertisers) are easier to miss at the default 30ms/60ms duty,
            # which shows up as flaky 0x3E / connect timeouts on real hardware.
            from pybluehost.ble.gap import BLEConnectionConfig
            cfg_kwargs: dict = {
                "scan_interval_ms": 60.0, "scan_window_ms": 60.0,
                "filter_policy": filter_policy,
            }
            if own_address_type is not None:
                cfg_kwargs["own_address_type"] = own_address_type
            cfg = BLEConnectionConfig(**cfg_kwargs)
            await self._gap.ble_connections.connect(target, cfg)
            handle = await asyncio.wait_for(waiter, timeout=timeout)
        finally:
            if not waiter.done():
                waiter.cancel()
            with contextlib.suppress(ValueError):
                self._le_connection_waiters.remove(waiter)

        from pybluehost.ble.att import ATTBearer
        from pybluehost.ble.gatt import GATTClient
        from pybluehost.l2cap.channel import SimpleChannelEvents, install_att_channel_mux
        from pybluehost.l2cap.constants import CID_ATT

        # The ATT fixed channel is created by L2CAPManager.on_connection, a
        # separate handler of the same HCI connection-complete event that resolved
        # our waiter. Ordering isn't guaranteed, so poll briefly for the channel
        # instead of assuming it already exists.
        channel = None
        for _ in range(50):
            channel = self._l2cap.get_fixed_channel(handle, CID_ATT)
            if channel is not None:
                break
            await asyncio.sleep(0.01)
        if channel is None:
            raise RuntimeError(f"ATT fixed channel not available for handle 0x{handle:04X}")
        bearer = ATTBearer(channel, mtu=getattr(channel, "mtu", 23))
        install_att_channel_mux(channel)
        channel._att_client_handler = bearer._on_pdu
        setattr(channel, "_gatt_client_bound", True)
        if self.on_att_client_bearer is not None:
            try:
                self.on_att_client_bearer(bearer, handle)
            except Exception:
                logger.exception("on_att_client_bearer hook raised")
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
        """Initiate SMP pairing over an existing LE connection.

        Role-aware (Core Vol 3 Part H §3.2/§3.6): as link-layer **central** the
        IUT sends a Pairing Request (initiator); as **peripheral** it cannot, so
        it sends a Security Request asking the central to pair, then waits for
        the resulting responder pairing to complete. PTS GAP/SEC peripheral
        cases drive pairing via BTP GAP PAIR on an inbound (PTS-initiated)
        connection — sending a Pairing Request there is a protocol violation the
        central ignores, so pairing never happened (PTS TIMEOUT).

        Raises ReplayModeError if stack is in REPLAY mode.
        Raises RuntimeError if no SMP channel is bound for this handle
        (typically because no LE connection is open).
        """
        self._check_writable()
        if self._smp is None:
            raise RuntimeError("Stack is not initialized")
        if self._le_conn_roles.get(handle, 0x00) == 0x01:
            auth_req = self._local_auth_req()
            await self._smp.request_security_and_wait(
                handle, auth_req=auth_req, timeout=timeout)
            return
        fut = await self._smp.start_initiator(handle)
        try:
            await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(f"Pairing timeout on handle=0x{handle:04X}") from exc

    def _local_auth_req(self) -> int:
        """AuthReq the IUT advertises/requests: bonding + SC + MITM per config."""
        sec = self._config.security
        auth_req = 0x01  # bonding
        if getattr(sec, "enable_secure_connections", False):
            auth_req |= 0x08
        if getattr(sec, "mitm_required", False):
            auth_req |= 0x04
        return auth_req

    async def encrypt(self, handle: int, *, timeout: float = 5.0) -> None:
        """Restore encryption using a stored bond and wait for completion.

        Looks up the bonded peer for this connection handle, issues
        HCI_LE_Start_Encryption, and awaits the HCI_Encryption_Change event.

        Raises:
            ReplayModeError: stack is in REPLAY mode
            RuntimeError: bond storage not configured / no peer address bound /
                no bond available / controller reports encryption failure
            asyncio.TimeoutError: no Encryption_Change event arrives within timeout
        """
        self._check_writable()
        if self._smp is None:
            raise RuntimeError("Stack is not initialized")
        if self._config.bond_storage is None:
            raise RuntimeError("Bond storage not configured")
        peer = self._smp._peer_addrs.get(handle)
        if peer is None:
            raise RuntimeError(f"No peer address bound for handle=0x{handle:04X}")
        bond = await self._load_bond_for_peer(peer)
        if bond is None or not bond.ltk:
            raise RuntimeError(f"No bond available for peer={peer}")

        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()
        self._encryption_waiters[handle] = waiter

        from pybluehost.hci.packets import HCI_LE_Start_Encryption_Command
        try:
            await self._hci.send_command(HCI_LE_Start_Encryption_Command(
                connection_handle=handle,
                random_number=bond.rand if bond.rand else b"\x00" * 8,
                encrypted_diversifier=bond.ediv,
                long_term_key=bond.ltk,
            ))
            await asyncio.wait_for(waiter, timeout=timeout)
        finally:
            self._encryption_waiters.pop(handle, None)

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

    @property
    def config(self) -> StackConfig:
        """Return the StackConfig used to build this Stack."""
        return self._config
