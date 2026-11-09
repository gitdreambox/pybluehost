"""L2CAPManager -- main L2CAP dispatch: connection tracking, channel routing, SAR."""
from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# Connection Parameter Update validity, in raw HCI units (Vol 6 Part B §4.5.3
# ranges + Vol 3 Part A §4.20 supervision-timeout relation). GAP.TS keeps
# TGAP(conn_param_latency) at 500 — the ceiling itself stays acceptable, so the
# latency bound here is >500, not Core's RFU 0x01F4+.
_CPU_INTERVAL_MIN = 0x0006  # 7.5 ms
_CPU_INTERVAL_MAX = 0x0C80  # 4000 ms
_CPU_TIMEOUT_MIN = 0x000A   # 100 ms
_CPU_TIMEOUT_MAX = 0x3E80   # 32000 ms


def _le_cpu_params_valid(
    itvl_min: int, itvl_max: int, latency: int, timeout: int
) -> bool:
    """Mirror zephyr `bt_le_conn_param_valid`: range-check every field, then
    require Supervision_Timeout*4 > (1 + Latency) × Conn_Interval_Max × 2."""
    if not (_CPU_INTERVAL_MIN <= itvl_min <= _CPU_INTERVAL_MAX):
        return False
    if not (_CPU_INTERVAL_MIN <= itvl_max <= _CPU_INTERVAL_MAX):
        return False
    if itvl_max < itvl_min:
        return False
    if latency > 500:
        return False
    if not (_CPU_TIMEOUT_MIN <= timeout <= _CPU_TIMEOUT_MAX):
        return False
    return timeout * 4 > (1 + latency) * itvl_max * 2


from pybluehost.core.errors import LECoCConnectError
from pybluehost.core.types import LinkType
from pybluehost.hci.constants import ACL_PB_FIRST_AUTO_FLUSH
from pybluehost.hci.packets import HCIACLData, HCIEvent
from pybluehost.l2cap.ble import FixedChannel
from pybluehost.l2cap.channel import Channel, ChannelState, SimpleChannelEvents
from pybluehost.l2cap.classic import ChannelMode, ClassicChannel
from pybluehost.l2cap.constants import (
    CID_ATT,
    CID_CLASSIC_SIGNALING,
    CID_DYNAMIC_MAX,
    CID_DYNAMIC_MIN,
    CID_LE_SIGNALING,
    CID_SMP,
    SignalingCode,
)
from pybluehost.l2cap.sar import Reassembler
from pybluehost.l2cap.signaling import SignalingPacket, decode_signaling, encode_signaling


@dataclass
class _ClassicConnectPending:
    local_cid: int
    future: asyncio.Future[int]


@dataclass
class _ClassicConfigPending:
    channel: ClassicChannel | None
    future: asyncio.Future[ClassicChannel]
    local_config_done: bool = False
    peer_config_done: bool = False
    # Set when a peer CONFIG_REQ arrives for our local_cid BEFORE we've
    # received CONNECTION_RESPONSE (and therefore before we know peer_cid).
    # The CONN_RESP handler replays the response once peer_cid is known.
    early_peer_config_ident: int | None = None


@dataclass
class _ClassicInboundPending:
    channel: ClassicChannel
    handler: Callable[[ClassicChannel], object]


class L2CAPManager:
    """Manages L2CAP connections, channels, and PDU routing.

    Sits between HCIController (below) and ATT/SMP/profile layer (above).
    """

    # How long an outgoing LE signaling connect waits for a response before
    # the transaction is abandoned (Core Vol 3 Part A §6.2 allows RTX in
    # 1..60 s; 1 s is the legal minimum). The request is NOT retransmitted —
    # an on-air identifier replay is the BI-29 Fail condition. PTS
    # COS/CED/BI-29 runs 253 rounds that each get only invalid-id SUCCESS
    # responses; abandoning at ~1 s keeps the loop inside its 360 s
    # TSPX_time_guard (~291 s worst case).
    LE_CONNECT_RTX_INTERVAL: float = 1.0

    def __init__(self, hci: object, trace: object | None = None) -> None:
        self._hci = hci
        self._trace = trace
        self._sar = Reassembler()
        # handle -> {cid -> Channel}
        self._connections: dict[int, dict[int, Channel]] = {}
        self._next_dynamic_cid = CID_DYNAMIC_MIN
        self._next_signaling_id = 1
        self._classic_connect_pending: dict[tuple[int, int], _ClassicConnectPending] = {}
        self._classic_config_pending: dict[tuple[int, int], _ClassicConfigPending] = {}
        self._classic_config_pending_by_cid: dict[tuple[int, int], _ClassicConfigPending] = {}
        self._classic_listeners: dict[int, Callable[[ClassicChannel], object]] = {}
        self._classic_inbound_pending: dict[tuple[int, int], _ClassicInboundPending] = {}
        self._le_connection_open_listeners: list[Callable[[int, dict[int, "Channel"]], None]] = []
        # LE Credit-Based Channels (Plan 2026-06-23-le-coc-manager).
        self._le_listeners: dict[int, Callable] = {}                  # psm -> handler
        # psm -> required security level (BTP L2CAPConnectionResponse value, 0=none).
        # Set by listen_le_coc_channel(required_security=...) for PTS security-
        # responder cases (L2CAP/LE/CFC/BV-11/13/15/25): the listener refuses an
        # incoming CoC connect whose link doesn't meet the level.
        self._le_listener_security: dict[int, int] = {}
        # handle -> (encrypted, authenticated, key_size). Fed by
        # set_le_connection_security (stack pushes it on HCI Encryption Change).
        self._le_conn_security: dict[int, tuple[bool, bool, int]] = {}
        self._pending_le_connect: dict[int, asyncio.Future] = {}      # ident -> future
        # Pending initiator-side ECFC reconfigure (0x19 out → 0x1A in).
        self._pending_le_reconfigure: dict[int, asyncio.Future] = {}  # ident -> future
        # Pending peripheral-side Connection Parameter Update (0x12 out → 0x13 in).
        self._pending_le_cpu: dict[int, asyncio.Future] = {}          # ident -> future
        self._next_le_signaling_id: int = 1
        self._next_le_cid: int = 0x0040                               # LE dynamic CID range start
        self._le_channels: dict[int, object] = {}                     # local SCID -> channel
        # handle -> LE role (0x00 central / 0x01 peripheral). Supplied by the
        # Stack's live role map; the CPU Request direction check needs it.
        self._le_role_provider: Callable[[int], int] | None = None
        # Handles with an outgoing Credit-Based Connection Request outstanding.
        # Receiving one from the peer while ours is pending is a collision, and
        # the answer is result 0x0004 (PTS L2CAP/TIM/BV-03-C).
        self._outgoing_ecfc: set[int] = set()
        # handle -> (interval, latency, timeout) in raw HCI units.
        self._le_conn_params_provider: Callable[[int], tuple | None] | None = None
        # Callbacks invoked when a Credit-Based Reconfigure is applied.
        self._reconfigure_cbs: list[Callable[[object], None]] = []

    def set_le_role_provider(self, provider: Callable[[int], int]) -> None:
        """Register a callable returning the LE role for a connection handle
        (0x00 central, 0x01 peripheral)."""
        self._le_role_provider = provider

    def _le_role(self, handle: int) -> int:
        """LE role for a handle; defaults to central when unknown."""
        if self._le_role_provider is None:
            return 0x00
        return self._le_role_provider(handle)

    def le_role(self, handle: int) -> int:
        """Public accessor: LE role of a connection handle (0x00 central / 0x01 peripheral)."""
        return self._le_role(handle)

    def set_le_conn_params_provider(self, provider: Callable[[int], tuple | None]) -> None:
        """Register a callable returning ``(interval, latency, timeout)`` for a
        handle in raw HCI units, or None. Used to size the collision back-off."""
        self._le_conn_params_provider = provider

    def on_le_channel_reconfigured(self, cb: Callable[[object], None]) -> None:
        """Register ``cb(channel)``, called when a Credit-Based Reconfigure is
        applied to a channel (either direction).

        Upper layers keep a model of the channel's MTU/MPS; auto-pts needs the
        BTP RECONFIGURED event to refresh its own, otherwise it keeps grading
        against the pre-reconfigure sizes.
        """
        self._reconfigure_cbs.append(cb)

    def _emit_reconfigured(self, channel: object) -> None:
        for cb in self._reconfigure_cbs:
            try:
                cb(channel)
            except Exception:
                logger.exception("LE reconfigure notification raised")

    def _collision_backoff(self, handle: int) -> float:
        """Minimum wait before retrying a connection request that collided.

        Core Vol 3 Part A Table 4.17 / L2CAP.TS Table 4.72 for LE:
        ``max(100 ms, 2 x (connPeripheralLatency + 1) x connInterval)``.
        """
        params = None
        if self._le_conn_params_provider is not None:
            params = self._le_conn_params_provider(handle)
        if not params:
            return 0.1
        interval, latency = params[0], params[1]
        return max(0.1, 2 * (latency + 1) * interval * 0.00125)

    # -- HCI upstream callbacks (registered via hci.set_upstream) --

    async def on_acl_data(self, pkt: HCIACLData) -> None:
        """Called by HCIController when ACL data arrives.

        NOTE: HCIController passes the full HCIACLData packet object.
        """
        # First-fragment fast-path: an LE CoC K-frame framing violation (SDU
        # length > advertised MTU, Information Payload > advertised MPS) is
        # detectable from the L2CAP header / SDU-length prefix of the FIRST ACL
        # fragment, before SAR reassembly completes. PTS L2CAP/LE/CFC/BV-26/27
        # send only that first fragment and wait for the IUT to disconnect, so
        # without this hook the violation is never seen and PTS runs to its
        # ~300 s time guard.
        if pkt.pb_flag == ACL_PB_FIRST_AUTO_FLUSH and len(pkt.data) >= 4:
            declared_len, frag_cid = struct.unpack_from("<HH", pkt.data, 0)
            channels = self._connections.get(pkt.handle)
            frag_channel = channels.get(frag_cid) if channels else None
            checker = getattr(frag_channel, "check_first_fragment_violation", None)
            if checker is not None and await checker(declared_len, pkt.data[4:]):
                self._sar.reset(pkt.handle)
                return

        pdus = self._sar.feed(
            handle=pkt.handle, pb_flag=pkt.pb_flag, data=pkt.data
        )
        if not pdus:
            return  # incomplete reassembly

        channels = self._connections.get(pkt.handle)
        if channels is None:
            return
        # One ACL packet can complete several L2CAP PDUs — deliver all of them.
        for cid, payload in pdus:
            channel = channels.get(cid)
            if channel is None:
                continue
            await channel._on_pdu(payload)

    async def on_hci_event(self, event: HCIEvent) -> None:
        """Called by HCIController for non-flow-control events.

        Currently handles LE Connection Complete and Disconnection Complete.
        """
        from pybluehost.hci.packets import (
            HCI_LE_Meta_Event,
            HCI_Connection_Complete_Event,
            HCI_Disconnection_Complete_Event,
        )
        from pybluehost.hci.constants import LEMetaSubEvent, ErrorCode

        if isinstance(event, HCI_LE_Meta_Event):
            if event.subevent_code == LEMetaSubEvent.LE_CONNECTION_COMPLETE:
                # Parse sub-event parameters
                if len(event.subevent_parameters) >= 18:
                    status = event.subevent_parameters[0]
                    if status == ErrorCode.SUCCESS:
                        handle = struct.unpack_from("<H", event.subevent_parameters, 1)[0]
                        await self.on_connection(
                            handle=handle, link_type=LinkType.LE,
                            peer_address=None, role=None,
                        )
        elif isinstance(event, HCI_Connection_Complete_Event):
            if event.status == ErrorCode.SUCCESS:
                lt = LinkType.ACL if event.link_type == 0x01 else LinkType.SCO
                await self.on_connection(
                    handle=event.connection_handle,
                    link_type=lt, peer_address=event.bd_addr, role=None,
                )
        elif isinstance(event, HCI_Disconnection_Complete_Event):
            if event.status == ErrorCode.SUCCESS:
                await self.on_disconnection(
                    handle=event.connection_handle, reason=event.reason,
                )

    # -- Connection management --

    async def on_connection(
        self, handle: int, link_type: LinkType,
        peer_address: bytes | None, role: int | None,
    ) -> None:
        """Register a new connection and create fixed channels."""
        channels: dict[int, Channel] = {}
        if link_type == LinkType.LE:
            # A recycled handle must start unencrypted. `on_disconnection`
            # clears this too; setting it here as well means a missed teardown
            # cannot leave the next connection looking already-secured.
            self._le_conn_security[handle] = (False, False, 0)
            # LE connections get ATT, SMP, and LE signaling fixed channels
            channels[CID_ATT] = FixedChannel(
                connection_handle=handle, cid=CID_ATT, hci=self._hci, mtu=23,
            )
            channels[CID_SMP] = FixedChannel(
                connection_handle=handle, cid=CID_SMP, hci=self._hci, mtu=65,
            )
            le_sig_ch = FixedChannel(
                connection_handle=handle, cid=CID_LE_SIGNALING, hci=self._hci, mtu=23,
            )
            le_sig_ch.set_events(
                SimpleChannelEvents(
                    on_data=lambda data, conn_handle=handle: self._on_le_signaling_safe(conn_handle, data),
                )
            )
            channels[CID_LE_SIGNALING] = le_sig_ch
        else:
            # Classic connections get signaling fixed channel
            signaling = FixedChannel(
                connection_handle=handle, cid=CID_CLASSIC_SIGNALING, hci=self._hci, mtu=48,
            )
            signaling.set_events(
                SimpleChannelEvents(
                    on_data=lambda data, conn_handle=handle: self._on_classic_signaling(conn_handle, data)
                )
            )
            channels[CID_CLASSIC_SIGNALING] = signaling
        self._connections[handle] = channels
        if link_type == LinkType.LE:
            for listener in list(self._le_connection_open_listeners):
                try:
                    listener(handle, channels)
                except Exception:
                    logger.exception("LE connection listener raised")
        logger.info(
            "L2CAP connection handle=0x%04X link_type=%s opened",
            handle,
            link_type.name if hasattr(link_type, "name") else link_type,
        )

    async def on_disconnection(self, handle: int, reason: int) -> None:
        """Clean up all channels for a disconnected connection."""
        logger.info(
            "L2CAP connection handle=0x%04X closed (reason=0x%02X)", handle, reason
        )
        # Connection handles are recycled by the controller, so every per-handle
        # map must be emptied here. A stale `_le_conn_security` entry made the
        # next connection on the same handle look already-encrypted: a
        # security-required listener then ACCEPTED an unencrypted CoC request
        # and the case ended INDCSV instead of seeing the refusal it asserts
        # (PTS L2CAP/LE/CFC/BV-25: pair on connection N, reconnect, request the
        # channel before encryption is re-established).
        self._le_conn_security.pop(handle, None)
        channels = self._connections.pop(handle, None)
        if channels:
            for ch in channels.values():
                if (
                    hasattr(ch, "_events")
                    and ch._events is not None
                    and hasattr(ch._events, "on_close")
                    and ch._events.on_close is not None
                ):
                    try:
                        result = ch._events.on_close(reason)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        pass

    # -- Channel access --

    def on_le_connection_open(
        self,
        listener: Callable[[int, dict[int, "Channel"]], None],
    ) -> None:
        """Register a listener invoked once when an LE connection's fixed
        channels (ATT/SMP/LE signaling) are created.

        Listeners are called synchronously inside on_connection(); they must
        not block. Use this hook to bind upper-layer handlers (e.g. attach
        SMPManager to the CID_SMP channel) instead of polling.
        """
        self._le_connection_open_listeners.append(listener)

    def get_fixed_channel(self, handle: int, cid: int) -> Channel | None:
        """Get a fixed channel by connection handle and CID."""
        channels = self._connections.get(handle)
        if channels is None:
            return None
        return channels.get(cid)

    def register_channel(self, handle: int, channel: Channel) -> None:
        """Register a dynamic channel."""
        if handle not in self._connections:
            self._connections[handle] = {}
        self._connections[handle][channel.cid] = channel

    async def connect_classic_channel(
        self,
        handle: int,
        psm: int,
        *,
        timeout: float = 5.0,
    ) -> ClassicChannel:
        """Open a Classic L2CAP dynamic channel to a remote PSM."""
        signaling = self.get_fixed_channel(handle, CID_CLASSIC_SIGNALING)
        if signaling is None:
            raise RuntimeError(f"Classic signaling channel not available for handle 0x{handle:04X}")

        local_cid = self._allocate_dynamic_cid()
        conn_ident = self._next_identifier()
        loop = asyncio.get_running_loop()
        config_future: asyncio.Future[ClassicChannel] = loop.create_future()
        # Pre-register the config-pending entry under our local_cid so that a
        # CONFIGURE_REQUEST that races ahead of the CONNECTION_RESPONSE handler
        # (peer is fast: CONN_RESP and CONFIG_REQ ride back-to-back) can stash
        # its identifier on the entry. The CONN_RESP handler replays the
        # response once peer_cid is known and the channel is registered.
        config_pending = _ClassicConfigPending(
            channel=None,
            future=config_future,
        )
        self._classic_config_pending_by_cid[(handle, local_cid)] = config_pending
        self._classic_connect_pending[(handle, conn_ident)] = _ClassicConnectPending(
            local_cid=local_cid,
            future=loop.create_future(),  # unused; CONN_RESP handler drives config_future
        )
        request = SignalingPacket(
            code=SignalingCode.CONNECTION_REQUEST,
            identifier=conn_ident,
            data=struct.pack("<HH", psm, local_cid),
        )
        await signaling.send(encode_signaling(request))

        try:
            return await asyncio.wait_for(config_future, timeout=timeout)
        finally:
            self._classic_connect_pending.pop((handle, conn_ident), None)
            self._classic_config_pending_by_cid.pop((handle, local_cid), None)
            # config_pending may also have been keyed by (handle, config_ident);
            # the CONN_RESP handler does that bookkeeping and removes it on
            # completion. Defensive cleanup of any leftover identifier-keyed
            # entry for this channel.
            for key in list(self._classic_config_pending.keys()):
                if (
                    self._classic_config_pending[key] is config_pending
                ):
                    self._classic_config_pending.pop(key, None)

    def listen_classic_channel(
        self,
        psm: int,
        handler: Callable[[ClassicChannel], object],
    ) -> None:
        """Register an incoming Classic L2CAP dynamic channel handler for a PSM."""
        self._classic_listeners[psm] = handler

    def _allocate_dynamic_cid(self) -> int:
        cid = self._next_dynamic_cid
        self._next_dynamic_cid += 1
        if self._next_dynamic_cid > CID_DYNAMIC_MAX:
            self._next_dynamic_cid = CID_DYNAMIC_MIN
        return cid

    def _next_identifier(self) -> int:
        ident = self._next_signaling_id
        self._next_signaling_id += 1
        if self._next_signaling_id > 0xFF:
            self._next_signaling_id = 1
        return ident

    async def _on_classic_signaling(self, handle: int, data: bytes) -> None:
        packet = decode_signaling(data)
        if packet.code == SignalingCode.CONNECTION_REQUEST:
            await self._handle_classic_connection_request(handle, packet)
            return

        if packet.code == SignalingCode.CONFIGURE_REQUEST:
            await self._handle_classic_configure_request(handle, packet)
            return

        if packet.code == SignalingCode.DISCONNECTION_REQUEST:
            await self._handle_classic_disconnection_request(handle, packet)
            return

        if packet.code == SignalingCode.CONNECTION_RESPONSE:
            pending = self._classic_connect_pending.get((handle, packet.identifier))
            if pending is None:
                return
            if len(packet.data) < 8:
                self._fail_classic_connect(handle, pending, RuntimeError(
                    "Malformed L2CAP Connection Response"
                ))
                return
            dest_cid, source_cid, result, status = struct.unpack_from("<HHHH", packet.data)
            if source_cid != pending.local_cid:
                self._fail_classic_connect(handle, pending, RuntimeError(
                    f"L2CAP Connection Response source CID mismatch: 0x{source_cid:04X}"
                ))
                return
            if result == 0x0001:
                return  # Pending (Spec 5.4 Vol 3 Part A §4.3); wait for final response.
            if result != 0:
                self._fail_classic_connect(handle, pending, RuntimeError(
                    f"L2CAP Connection Response failed: result=0x{result:04X} status=0x{status:04X}"
                ))
                return
            # Build the channel, finish registration, send CONFIGURE_REQUEST, and
            # service any peer CONFIGURE_REQUEST that arrived before us.
            await self._on_classic_connection_complete(
                handle=handle, local_cid=pending.local_cid, peer_cid=dest_cid,
            )
            return

        if packet.code == SignalingCode.CONFIGURE_RESPONSE:
            pending = self._classic_config_pending.get((handle, packet.identifier))
            if pending is None or pending.future.done():
                return
            if len(packet.data) < 6:
                pending.future.set_exception(RuntimeError("Malformed L2CAP Configure Response"))
                return
            source_cid, _flags, result = struct.unpack_from("<HHH", packet.data)
            if source_cid != pending.channel.cid:
                pending.future.set_exception(
                    RuntimeError(
                        f"L2CAP Configure Response source CID mismatch: 0x{source_cid:04X}"
                    )
                )
                return
            if result != 0:
                logger.warning(
                    "L2CAP CID=0x%04X configuration rejected (result=0x%04X)",
                    pending.channel.cid,
                    result,
                )
                pending.future.set_exception(
                    RuntimeError(f"L2CAP Configure Response failed: result=0x{result:04X}")
                )
                return
            pending.local_config_done = True
            self._complete_classic_config_if_ready(pending)

    async def _handle_classic_connection_request(
        self,
        handle: int,
        packet: SignalingPacket,
    ) -> None:
        signaling = self.get_fixed_channel(handle, CID_CLASSIC_SIGNALING)
        if signaling is None:
            return
        if len(packet.data) < 4:
            return
        psm, source_cid = struct.unpack_from("<HH", packet.data)
        handler = self._classic_listeners.get(psm)
        if handler is None:
            response = SignalingPacket(
                code=SignalingCode.CONNECTION_RESPONSE,
                identifier=packet.identifier,
                data=struct.pack("<HHHH", 0x0000, source_cid, 0x0002, 0x0000),
            )
            await signaling.send(encode_signaling(response))
            return

        local_cid = self._allocate_dynamic_cid()
        channel = ClassicChannel(
            connection_handle=handle,
            local_cid=local_cid,
            peer_cid=source_cid,
            mode=ChannelMode.BASIC,
            hci=self._hci,
        )
        self.register_channel(handle, channel)
        logger.info(
            "L2CAP CID=0x%04X PSM=0x%04X opened", channel.cid, psm
        )
        self._classic_inbound_pending[(handle, local_cid)] = _ClassicInboundPending(
            channel=channel,
            handler=handler,
        )
        response = SignalingPacket(
            code=SignalingCode.CONNECTION_RESPONSE,
            identifier=packet.identifier,
            data=struct.pack("<HHHH", local_cid, source_cid, 0x0000, 0x0000),
        )
        await signaling.send(encode_signaling(response))
        configure = SignalingPacket(
            code=SignalingCode.CONFIGURE_REQUEST,
            identifier=self._next_identifier(),
            data=struct.pack("<HH", source_cid, 0x0000),
        )
        await signaling.send(encode_signaling(configure))

    async def _handle_classic_configure_request(
        self,
        handle: int,
        packet: SignalingPacket,
    ) -> None:
        signaling = self.get_fixed_channel(handle, CID_CLASSIC_SIGNALING)
        if signaling is None or len(packet.data) < 4:
            return
        dest_cid, _flags = struct.unpack_from("<HH", packet.data)
        outbound_pending = self._classic_config_pending_by_cid.get((handle, dest_cid))
        if outbound_pending is not None:
            if outbound_pending.channel is None:
                # Race: peer's CONFIGURE_REQUEST arrived before we processed the
                # CONNECTION_RESPONSE. Stash the identifier so the CONN_RESP
                # handler can send the response once peer_cid is known.
                outbound_pending.early_peer_config_ident = packet.identifier
                outbound_pending.peer_config_done = True
                return
            response = SignalingPacket(
                code=SignalingCode.CONFIGURE_RESPONSE,
                identifier=packet.identifier,
                data=struct.pack("<HHH", outbound_pending.channel._peer_cid, 0x0000, 0x0000),
            )
            await signaling.send(encode_signaling(response))
            outbound_pending.peer_config_done = True
            self._complete_classic_config_if_ready(outbound_pending)
            return

        pending = self._classic_inbound_pending.pop((handle, dest_cid), None)
        response = SignalingPacket(
            code=SignalingCode.CONFIGURE_RESPONSE,
            identifier=packet.identifier,
            data=struct.pack("<HHH", pending.channel._peer_cid if pending else 0x0000, 0x0000, 0x0000),
        )
        await signaling.send(encode_signaling(response))
        if pending is None:
            return
        pending.channel.open()
        result = pending.handler(pending.channel)
        if asyncio.iscoroutine(result):
            await result

    async def _handle_classic_disconnection_request(
        self,
        handle: int,
        packet: SignalingPacket,
    ) -> None:
        """Reply to an inbound L2CAP Disconnection Request and close the channel."""
        signaling = self.get_fixed_channel(handle, CID_CLASSIC_SIGNALING)
        if signaling is None or len(packet.data) < 4:
            return
        dest_cid, source_cid = struct.unpack_from("<HH", packet.data)
        channel = None
        channels = self._connections.get(handle)
        if channels is not None:
            channel = channels.get(dest_cid)
        response = SignalingPacket(
            code=SignalingCode.DISCONNECTION_RESPONSE,
            identifier=packet.identifier,
            data=struct.pack("<HH", dest_cid, source_cid),
        )
        await signaling.send(encode_signaling(response))
        if channel is not None:
            logger.info("L2CAP CID=0x%04X disconnected by peer", channel.cid)
            channels.pop(channel.cid, None)
            await channel.close()

    async def _on_classic_connection_complete(
        self,
        handle: int,
        local_cid: int,
        peer_cid: int,
    ) -> None:
        """CONN_RESP handler: build the channel, register, send CONFIGURE_REQUEST,
        and replay any early peer CONFIGURE_REQUEST that arrived ahead of us.
        """
        signaling = self.get_fixed_channel(handle, CID_CLASSIC_SIGNALING)
        pending = self._classic_config_pending_by_cid.get((handle, local_cid))
        if pending is None or pending.future.done():
            return
        channel = ClassicChannel(
            connection_handle=handle,
            local_cid=local_cid,
            peer_cid=peer_cid,
            mode=ChannelMode.BASIC,
            hci=self._hci,
        )
        self.register_channel(handle, channel)
        pending.channel = channel

        # If a peer CONFIG_REQ raced ahead of us, send the deferred response now.
        if pending.early_peer_config_ident is not None and signaling is not None:
            response = SignalingPacket(
                code=SignalingCode.CONFIGURE_RESPONSE,
                identifier=pending.early_peer_config_ident,
                data=struct.pack("<HHH", peer_cid, 0x0000, 0x0000),
            )
            pending.early_peer_config_ident = None
            await signaling.send(encode_signaling(response))

        config_ident = self._next_identifier()
        self._classic_config_pending[(handle, config_ident)] = pending
        configure = SignalingPacket(
            code=SignalingCode.CONFIGURE_REQUEST,
            identifier=config_ident,
            data=struct.pack("<HH", peer_cid, 0x0000),
        )
        if signaling is not None:
            await signaling.send(encode_signaling(configure))
        # In case the response races ahead of completion check.
        self._complete_classic_config_if_ready(pending)

    def _fail_classic_connect(
        self,
        handle: int,
        pending: _ClassicConnectPending,
        exc: BaseException,
    ) -> None:
        config_pending = self._classic_config_pending_by_cid.get(
            (handle, pending.local_cid)
        )
        if config_pending is not None and not config_pending.future.done():
            config_pending.future.set_exception(exc)

    def _complete_classic_config_if_ready(self, pending: _ClassicConfigPending) -> None:
        if (
            pending.local_config_done
            and pending.peer_config_done
            and not pending.future.done()
        ):
            pending.channel.open()
            logger.info(
                "L2CAP CID=0x%04X configured (MTU=%d)",
                pending.channel.cid,
                pending.channel.mtu,
            )
            pending.future.set_result(pending.channel)

    def listen_le_coc_channel(self, psm: int, handler, required_security: int = 0) -> None:
        """Register `handler(channel: LECoCChannel)` to receive incoming LE CoC
        connections on `psm`. Handler may be sync or async.

        `required_security` is a BTP ``L2CAPConnectionResponse`` value (0=success/
        no requirement, 1=authentication, 2=authorization, 3=encryption key size,
        4=encryption). When non-zero, an incoming connect whose link does not meet
        that level is refused with the mapped LE_CONN_RESULT_* code (PTS
        security-responder cases); the peer is expected to upgrade security and
        retry, at which point the re-evaluation accepts.
        """
        self._le_listeners[psm] = handler
        self._le_listener_security[psm] = required_security

    def set_le_connection_security(
        self, handle: int, *, encrypted: bool, authenticated: bool, key_size: int
    ) -> None:
        """Record the link-security state for an LE connection (called by the stack
        on HCI Encryption Change). Consulted by the LE CoC listener to enforce a
        PSM's required security level."""
        self._le_conn_security[handle] = (encrypted, authenticated, key_size)

    # Map BTP L2CAPConnectionResponse requirement -> (predicate, refusal result).
    # Predicate reads (encrypted, authenticated, key_size).
    _LE_SECURITY_CHECK = {
        1: (lambda e, a, k: e and a, 0x0005),   # auth  -> insufficient authentication
        2: (lambda e, a, k: e and a, 0x0006),   # authz -> insufficient authorization
        3: (lambda e, a, k: e and k >= 16, 0x0007),  # key size -> enc key size too short
        4: (lambda e, a, k: e, 0x0008),         # enc   -> insufficient encryption
    }

    def _le_security_met(self, handle: int, psm: int) -> tuple[bool, int]:
        """Return (ok, refusal_result). ok=True if the link meets the PSM's
        required security (or none required); otherwise ok=False and
        refusal_result is the LE_CONN_RESULT_* to send back."""
        required = self._le_listener_security.get(psm, 0)
        if required == 0:
            return True, 0
        check = self._LE_SECURITY_CHECK.get(required)
        if check is None:
            return True, 0
        predicate, refusal = check
        encrypted, authenticated, key_size = self._le_conn_security.get(
            handle, (False, False, 0))
        return (bool(predicate(encrypted, authenticated, key_size)), refusal)

    # -- LE Credit-Based Channel helpers --

    def _allocate_le_cid(self) -> int:
        cid = self._next_le_cid
        self._next_le_cid += 1
        return cid

    def _peer_source_cids(self) -> set[int]:
        """Source CIDs our peer has already used for open LE CoC channels.

        A request's SCID is the *peer's* endpoint, so a repeat of one already in
        use is what "Source CID already allocated" (§4.25 result 0x000A) means.
        """
        return {
            peer_cid
            for ch in self._le_channels.values()
            if (peer_cid := getattr(ch, "_peer_cid", None)) is not None
        }

    def _next_le_signaling_id_value(self) -> int:
        """Return current signaling id then advance, wrapping 0xFF → 0x01 (0 reserved)."""
        val = self._next_le_signaling_id
        nxt = (val % 0xFF) + 1
        # Skip 0 — Core Spec §4 says identifier 0 is invalid.
        self._next_le_signaling_id = nxt if nxt != 0 else 1
        return val

    async def _send_le_signaling(
        self, *, handle: int, code: int, ident: int, payload: bytes,
    ) -> None:
        from pybluehost.l2cap.le_signaling import encode_le_signaling
        sig_ch = self._connections.get(handle, {}).get(CID_LE_SIGNALING)
        if sig_ch is None:
            logger.warning("LE signaling: no LE signaling channel on handle 0x%04X", handle)
            return
        logger.debug(
            "LE signaling TX handle=0x%04X code=0x%02X id=%d len=%d raw=%s",
            handle, code, ident, len(payload) + 4,
            encode_le_signaling(code, ident, payload).hex(),
        )
        await sig_ch.send(encode_le_signaling(code, ident, payload))

    async def _handle_le_conn_param_update_request(
        self, handle: int, ident: int, payload: bytes
    ) -> None:
        """Handle an LE Connection Parameter Update Request (0x12).

        The CPU procedure is defined peripheral→central only (Core Spec Vol 3
        Part A §4.20). Guards before we accept:

        - If WE are the peripheral, receiving a CPU Request is an unsupported
          command in that direction — answer with COMMAND_REJECT_RSP reason
          0x0000 (PTS L2CAP/LE/CPU/BI-02-C).
        - Any invalid parameter — Core range check plus the TGAP
          (conn_param_latency)=500 ceiling (see `_le_cpu_params_valid`) —
          is answered result=0x0001 without touching the link (PTS
          L2CAP/LE/CPU/BI-01-C and GAP/CONN/CPUP/BV-05-C, where the Lower
          Tester builds the request from the TSPX_iut_invalid_connection_*
          IXITs).

        Otherwise accept (result=0x0000) and apply via HCI LE_Connection_Update
        so the link actually moves to the negotiated params — PTS GAP/CONN/CPUP
        BV-04/05 watch for the on-air update. Payload: itvl_min+itvl_max+latency
        +timeout (4x u16 LE, raw HCI units).
        """
        from pybluehost.hci.constants import HCI_LE_CONNECTION_UPDATE
        from pybluehost.hci.packets import HCICommand
        from pybluehost.l2cap.le_signaling import (
            LE_CONN_PARAM_UPDATE_ACCEPTED, LE_CONN_PARAM_UPDATE_REJECTED,
            LE_REJECT_REASON_COMMAND_NOT_UNDERSTOOD,
            LE_SIG_COMMAND_REJECT,
            LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
        )
        if self._le_role(handle) == 0x01:
            # We are the peripheral; a CPU Request is not valid in this direction.
            await self._send_le_signaling(
                handle=handle, code=LE_SIG_COMMAND_REJECT, ident=ident,
                payload=struct.pack("<H", LE_REJECT_REASON_COMMAND_NOT_UNDERSTOOD),
            )
            return
        if len(payload) < 8:
            await self._send_le_signaling(
                handle=handle, code=LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
                ident=ident, payload=struct.pack("<H", LE_CONN_PARAM_UPDATE_REJECTED),
            )
            return
        itvl_min, itvl_max, latency, timeout = struct.unpack_from("<HHHH", payload, 0)
        if not _le_cpu_params_valid(itvl_min, itvl_max, latency, timeout):
            await self._send_le_signaling(
                handle=handle, code=LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
                ident=ident, payload=struct.pack("<H", LE_CONN_PARAM_UPDATE_REJECTED),
            )
            return
        await self._send_le_signaling(
            handle=handle, code=LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
            ident=ident, payload=struct.pack("<H", LE_CONN_PARAM_UPDATE_ACCEPTED),
        )
        params = struct.pack(
            "<HHHHHHH", handle, itvl_min, itvl_max, latency, timeout, 0x0000, 0x0000,
        )
        await self._hci.send_command(
            HCICommand(opcode=HCI_LE_CONNECTION_UPDATE, parameters=params)
        )

    async def request_le_conn_param_update(
        self,
        *,
        handle: int,
        itvl_min: int,
        itvl_max: int,
        latency: int,
        timeout: int,
        timeout_s: float = 5.0,
    ) -> int:
        """Send an LE Connection Parameter Update Request (0x12) and await the 0x13.

        The CPU procedure is peripheral→central only (Core Spec Vol 3 Part A
        §4.20), so this is the path taken when WE are the peripheral and the
        central's LL feature set does not offer the LL-level Connection
        Parameters Request Procedure — the only way left is the L2CAP signalling
        channel. PTS L2CAP/LE/CPU/BV-01-C asserts exactly that: the IUT transmits
        L2CAP_CONNECTION_PARAMETER_UPDATE_REQ on CID=5 after the ACL comes up.

        Returns the 0x13 Result code (0x0000 accepted / 0x0001 rejected).
        Raises ``TimeoutError`` if the central never answers.
        """
        from pybluehost.l2cap.le_signaling import (
            LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST,
        )
        ident = self._next_le_signaling_id_value()
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending_le_cpu[ident] = fut
        try:
            await self._send_le_signaling(
                handle=handle,
                code=LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST,
                ident=ident,
                payload=struct.pack("<HHHH", itvl_min, itvl_max, latency, timeout),
            )
            result = await asyncio.wait_for(fut, timeout=timeout_s)
        finally:
            self._pending_le_cpu.pop(ident, None)
        return int(struct.unpack_from("<H", result, 0)[0]) if len(result) >= 2 else -1

    async def _on_le_signaling_safe(self, handle: int, data: bytes) -> None:
        """Fixed-channel entry point: run the dispatcher, but never let a handler
        exception escape. A raise here used to propagate into the ACL read task
        and vanish, leaving the peer waiting for a response that never came
        (PTS then runs to its time guard and reports a meaningless verdict)."""
        try:
            await self._on_le_signaling_frame(handle, data)
        except Exception:
            logger.exception(
                "LE signaling: handler raised handle=0x%04X (no response sent)", handle,
            )

    async def _on_le_signaling_frame(self, handle: int, data: bytes) -> None:
        """Split one C-frame into its signaling commands and dispatch each.

        A C-frame may carry several commands (Core Vol 3 Part A §3.1), but every
        command must be complete and the frame must end exactly on a command
        boundary. A trailing octet (L2CAP.TS COS/CED/BI-13) or a second command
        whose declared Data Length exceeds the octets present (BI-16/17) makes
        the WHOLE frame malformed: answer COMMAND_REJECT_RSP (reason 0x0000)
        and act on none of it. Accepting just the well-formed prefix is what
        failed those cases — the decoder used to slice `data[4:4+length]` and
        silently drop the rest, so a corrupted connection request was accepted.
        """
        import struct as _struct

        from pybluehost.l2cap.le_signaling import (
            LE_SIG_COMMAND_REJECT, LE_REJECT_REASON_COMMAND_NOT_UNDERSTOOD,
        )

        commands: list[bytes] = []
        offset = 0
        malformed = False
        while offset < len(data):
            if len(data) - offset < 4:
                malformed = True
                break
            length = _struct.unpack_from("<H", data, offset + 2)[0]
            end = offset + 4 + length
            if end > len(data):
                malformed = True
                break
            commands.append(data[offset:end])
            offset = end
        if malformed or not commands:
            ident = data[1] if len(data) >= 2 else 0
            logger.debug(
                "LE signaling: malformed C-frame handle=0x%04X len=%d -> command reject",
                handle, len(data),
            )
            await self._send_le_signaling(
                handle=handle, code=LE_SIG_COMMAND_REJECT, ident=ident,
                payload=_struct.pack("<H", LE_REJECT_REASON_COMMAND_NOT_UNDERSTOOD),
            )
            return
        for command in commands:
            await self._on_le_signaling(handle, command)

    async def _on_le_signaling(self, handle: int, data: bytes) -> None:
        """Dispatch LE signaling PDUs received on the LE signaling fixed channel."""
        from pybluehost.l2cap.le_signaling import (
            DisconnectionRequest, DisconnectionResponse,
            ECFCConnectionRequest, ECFCConnectionResponse,
            ECFCReconfigureRequest, ECFCReconfigureResponse,
            LECreditBasedConnectionRequest, LECreditBasedConnectionResponse,
            LEFlowControlCredit,
            LE_SIG_COMMAND_REJECT,
            LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST,
            LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE,
            LE_SIG_DISCONNECTION_REQUEST,
            LE_SIG_DISCONNECTION_RESPONSE,
            LE_SIG_ECFC_CONNECTION_REQUEST,
            LE_SIG_ECFC_CONNECTION_RESPONSE,
            LE_SIG_ECFC_RECONFIGURE_REQUEST,
            LE_SIG_ECFC_RECONFIGURE_RESPONSE,
            LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST,
            LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE,
            LE_SIG_LE_FLOW_CONTROL_CREDIT,
            decode_le_signaling,
        )
        try:
            code, ident, payload = decode_le_signaling(data)
        except ValueError:
            logger.exception("LE signaling: decode failed")
            return
        logger.debug(
            "LE signaling RX handle=0x%04X code=0x%02X id=%d len=%d raw=%s",
            handle, code, ident, len(data), data.hex(),
        )

        if code == LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST:
            assert isinstance(payload, LECreditBasedConnectionRequest)
            await self._handle_incoming_le_coc_request(handle, ident, payload)
        elif code == LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST:
            # Peripheral -> central Connection Parameter Update Request (raw
            # bytes: itvl_min+itvl_max+latency+timeout, 4x u16 LE). Accept and
            # apply via HCI LE_Connection_Update (PTS GAP/CONN/CPUP/BV-04/05).
            await self._handle_le_conn_param_update_request(handle, ident, payload)
        elif code == LE_SIG_ECFC_CONNECTION_REQUEST:
            assert isinstance(payload, ECFCConnectionRequest)
            await self._handle_incoming_ecfc_request(handle, ident, payload)
        elif code == LE_SIG_ECFC_RECONFIGURE_REQUEST:
            assert isinstance(payload, ECFCReconfigureRequest)
            await self._handle_incoming_ecfc_reconfigure(handle, ident, payload)
        elif code == LE_SIG_ECFC_RECONFIGURE_RESPONSE:
            # Result of OUR initiator-side reconfigure (0x19 out → 0x1A in).
            assert isinstance(payload, ECFCReconfigureResponse)
            fut = self._pending_le_reconfigure.pop(ident, None)
            if fut is not None and not fut.done():
                fut.set_result(payload)
        elif code == LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE:
            # Result of OUR peripheral-side CPU Request (0x12 out → 0x13 in).
            # Body is the raw 2-byte Result code (§4.16).
            fut = self._pending_le_cpu.pop(ident, None)
            if fut is not None and not fut.done():
                fut.set_result(payload)
        elif code == LE_SIG_COMMAND_REJECT:
            # Legacy peer rejected our credit-based request with a Command Reject
            # (it doesn't understand 0x14). Resolve the pending connect as a refusal
            # so the caller reports "channel not established" instead of hanging until
            # timeout (PTS L2CAP/LE/CFC/BV-01-C Legacy Peer).
            fut = self._pending_le_connect.pop(ident, None)
            if fut is not None and not fut.done():
                fut.set_exception(LECoCConnectError(
                    "LE CoC connect command-rejected (legacy peer)",
                    result=LECoCConnectError.RESULT_COMMAND_REJECT,
                ))
        elif code == LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE:
            assert isinstance(payload, LECreditBasedConnectionResponse)
            fut = self._pending_le_connect.pop(ident, None)
            if fut is None and payload.result != 0:
                # Invalid-ID refusal (L2CAP.TS 4.4.1.7 / BI-29): the peer
                # terminates the transaction with a non-zero-result response
                # whose identifier does not match (0x00 or a stale id —
                # hardware: TX 0x14 id=2 → RX id=3 → RTX → RX id=0 ×2). With a
                # single outstanding signaling request per link this can only
                # be OUR transaction's refusal — resolve it instead of waiting
                # out RTX. A result=0 response with a wrong id stays ignored:
                # treating a wrong-id SUCCESS as ours would fabricate a
                # connection, exactly the behavior BI-29 fails the IUT for.
                fut = next(iter(self._pending_le_connect.values()), None)
                self._pending_le_connect.clear()
            if fut is not None and not fut.done():
                fut.set_result(payload)
        elif code == LE_SIG_ECFC_CONNECTION_RESPONSE:
            assert isinstance(payload, ECFCConnectionResponse)
            fut = self._pending_le_connect.pop(ident, None)
            if fut is None and payload.result != 0:
                # Same invalid-ID refusal path for the Enhanced request.
                fut = next(iter(self._pending_le_connect.values()), None)
                self._pending_le_connect.clear()
            if fut is not None and not fut.done():
                fut.set_result(payload)
        elif code == LE_SIG_LE_FLOW_CONTROL_CREDIT:
            assert isinstance(payload, LEFlowControlCredit)
            # Credit PDU's CID is the SENDER's CID (i.e., our peer's CID, our channel's _peer_cid).
            for ch in self._le_channels.values():
                if getattr(ch, "_peer_cid", None) == payload.cid:
                    if not ch.add_credits(payload.credits):
                        # 16-bit counter overflow (§4.24) — tear the channel down.
                        logger.warning(
                            "LE signaling: credit overflow cid=0x%04X (+%d) — "
                            "disconnecting channel", payload.cid, payload.credits,
                        )
                        await self.disconnect_le_coc_channel(ch)
                    break
            else:
                logger.warning(
                    "LE signaling: credit PDU for unknown cid=0x%04X", payload.cid,
                )
        elif code == LE_SIG_DISCONNECTION_REQUEST:
            assert isinstance(payload, DisconnectionRequest)
            await self._handle_le_disconnection_request(handle, ident, payload)
        elif code == LE_SIG_DISCONNECTION_RESPONSE:
            # Optional: resolve any pending disconnect future. T5 adds a real impl.
            return
        else:
            # Unsupported / RFU code: Core Spec Vol 3 Part A §4.1 requires a
            # COMMAND_REJECT_RSP with Reason 0x0000 (Command not understood) and
            # no Reason Data field (PTS L2CAP/LE/REJ/BI-02-C). Staying silent
            # makes PTS run to its time guard.
            logger.debug("LE signaling: unhandled code 0x%02X (ident=%d)", code, ident)
            from pybluehost.l2cap.le_signaling import (
                LE_REJECT_REASON_COMMAND_NOT_UNDERSTOOD,
            )
            await self._send_le_signaling(
                handle=handle, code=LE_SIG_COMMAND_REJECT, ident=ident,
                payload=struct.pack("<H", LE_REJECT_REASON_COMMAND_NOT_UNDERSTOOD),
            )

    async def _await_le_connect_response(
        self, fut: asyncio.Future, *, handle: int, code: int, ident: int,
        payload: bytes, timeout: float,
    ):
        """Send a connect request PDU once and await its response future.

        NO retransmission: the identifier identifies one transaction (§5.2)
        and the L2CAP.TS BI-29 Lower Tester treats an on-air replay of the
        same identifier as its Fail condition ("the IUT reuses an
        Identifier"), aborting the link after the first repeats — hardware
        trace: TX 0x14 id=2 → RTX id=2 ×2 → LT 0x13 disconnect. Like the
        zephyr reference (``l2cap_rtx_timeout`` removes the channel without
        resending), the transaction is simply abandoned when nothing answers
        within the RTX window — surfaced as a refusal
        (``RESULT_NO_RESPONSE``), which the BTP layer reports as a refused
        channel rather than a hard error.
        """
        await self._send_le_signaling(
            handle=handle, code=code, ident=ident, payload=payload,
        )
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            raise LECoCConnectError(
                f"no response to LE signaling request ident={ident} "
                f"within {timeout}s (transaction abandoned)",
                result=LECoCConnectError.RESULT_NO_RESPONSE,
            ) from None

    async def connect_le_coc_channel(
        self,
        *,
        handle: int,
        psm: int,
        mtu: int = 512,
        mps: int = 247,
        initial_credits: int = 10,
        timeout: float | None = None,
    ):
        """Open an LE Credit-Based Channel to the peer on `psm`.

        Returns the established `LECoCChannel`. Raises LECoCConnectError on
        result != 0x0000 or when no response arrives within the RTX window
        (RESULT_NO_RESPONSE — the transaction is abandoned, not retransmitted).
        `timeout` defaults to ``LE_CONNECT_RTX_INTERVAL``; only override it for
        peers known to answer slowly — the BTP L2CAP CONNECT path must NOT,
        or BI-29's per-round abandonment outlives the client's 20 s read
        timeout and every round degrades into a BTP TIMEOUT.
        """
        from pybluehost.l2cap.ble import LECoCChannel
        from pybluehost.l2cap.le_signaling import (
            LECreditBasedConnectionRequest,
            LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST,
        )

        if timeout is None:
            timeout = self.LE_CONNECT_RTX_INTERVAL

        if handle not in self._connections or CID_LE_SIGNALING not in self._connections[handle]:
            raise RuntimeError(
                f"no LE connection on handle 0x{handle:04X}; cannot open LE CoC"
            )
        scid = self._allocate_le_cid()
        ident = self._next_le_signaling_id_value()
        req = LECreditBasedConnectionRequest(
            le_psm=psm, scid=scid, mtu=mtu, mps=mps, initial_credits=initial_credits,
        )
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_le_connect[ident] = fut
        try:
            resp = await self._await_le_connect_response(
                fut, handle=handle,
                code=LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST,
                ident=ident, payload=req.encode(), timeout=timeout,
            )
        except BaseException:
            self._pending_le_connect.pop(ident, None)
            raise

        if resp.result != 0x0000:
            raise LECoCConnectError(
                f"LE CoC connect refused: result=0x{resp.result:04X}",
                result=resp.result,
            )
        ch = LECoCChannel(
            connection_handle=handle,
            local_cid=scid,
            peer_cid=resp.dcid,
            hci=self._hci,
            mtu=min(mtu, resp.mtu),
            mps=min(mps, resp.mps),
            initial_credits=resp.initial_credits,
            rx_mtu=mtu, rx_mps=mps,
            psm=psm,
        )
        ch._credit_grant_cb = lambda n, _c=ch: self.grant_le_coc_credits(_c, n)
        ch._violation_cb = lambda _c=ch: self.disconnect_le_coc_channel(_c)
        self._le_channels[scid] = ch
        self._connections[handle][scid] = ch
        return ch

    async def connect_le_coc_channels(
        self, handle: int, psm: int, *, mtu: int = 512, mps: int = 247,
        initial_credits: int = 10, num: int = 1, timeout: float | None = None,
    ) -> list:
        """Initiate N Enhanced Credit-Based channels (0x17/0x18) on one request.

        PTS L2CAP/ECFC initiator cases connect several channels at once; the
        Enhanced Credit-Based request carries N SCIDs and the response either
        accepts all (result 0x0000, N DCIDs) or refuses all. Returns the list of
        established LECoCChannels; raises LECoCConnectError on refusal or
        RTX-window abandonment (same default as `connect_le_coc_channel`).
        """
        from pybluehost.l2cap.ble import LECoCChannel
        from pybluehost.l2cap.le_signaling import (
            ECFCConnectionRequest,
            LE_SIG_ECFC_CONNECTION_REQUEST,
        )

        if timeout is None:
            timeout = self.LE_CONNECT_RTX_INTERVAL

        if handle not in self._connections or CID_LE_SIGNALING not in self._connections[handle]:
            raise RuntimeError(
                f"no LE connection on handle 0x{handle:04X}; cannot open ECFC channels"
            )
        if num < 1 or num > 5:
            raise ValueError(f"num channels must be 1..5, got {num}")

        scids = [self._allocate_le_cid() for _ in range(num)]
        ident = self._next_le_signaling_id_value()
        req = ECFCConnectionRequest(
            le_psm=psm, mtu=mtu, mps=mps,
            initial_credits=initial_credits, scids=tuple(scids),
        )
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_le_connect[ident] = fut
        # Mark the request in flight so an incoming request from the peer is
        # answered as a collision (result 0x0004) rather than accepted.
        self._outgoing_ecfc.add(handle)
        try:
            resp = await self._await_le_connect_response(
                fut, handle=handle,
                code=LE_SIG_ECFC_CONNECTION_REQUEST,
                ident=ident, payload=req.encode(), timeout=timeout,
            )
        except BaseException:
            self._pending_le_connect.pop(ident, None)
            raise
        finally:
            self._outgoing_ecfc.discard(handle)

        if resp.result != 0x0000:
            raise LECoCConnectError(
                f"ECFC connect refused: result=0x{resp.result:04X}",
                result=resp.result,
            )
        if len(resp.dcids) != num:
            raise LECoCConnectError(
                f"ECFC response DCID count {len(resp.dcids)} != requested {num}",
                result=resp.result,
            )

        channels = []
        for scid, dcid in zip(scids, resp.dcids):
            ch = LECoCChannel(
                connection_handle=handle, local_cid=scid, peer_cid=dcid,
                hci=self._hci,
                mtu=min(mtu, resp.mtu), mps=min(mps, resp.mps),
                initial_credits=resp.initial_credits,
                rx_mtu=mtu, rx_mps=mps,
                psm=psm,
            )
            ch._credit_grant_cb = lambda n, _c=ch: self.grant_le_coc_credits(_c, n)
            ch._violation_cb = lambda _c=ch: self.disconnect_le_coc_channel(_c)
            self._le_channels[scid] = ch
            self._connections[handle][scid] = ch
            channels.append(ch)
        return channels

    async def connect_eatt_channels(
        self, handle: int, *, num: int = 1, timeout: float = 5.0,
    ) -> list:
        """Establish `num` Enhanced ATT bearers as the initiator.

        EATT rides Enhanced Credit-Based channels on the fixed EATT SPSM
        (0x0027). The request can collide with one the peer is sending us at the
        same moment; the peer then refuses ours with result 0x0004 ("insufficient
        resources", Table 4.17) and the spec requires a back-off before retrying.
        PTS L2CAP/TIM/BV-03-C drives exactly that: it collides, refuses, waits to
        see whether we honour the back-off, then accepts the retry.

        Returns the established channels. Raises ``LECoCConnectError`` if the
        retry is refused too.
        """
        from pybluehost.l2cap.constants import PSM_EATT
        from pybluehost.l2cap.le_signaling import (
            LE_CONN_RESULT_INSUFFICIENT_RESOURCES,
        )

        for attempt in (1, 2):
            try:
                return await self.connect_le_coc_channels(
                    handle, PSM_EATT, num=num, timeout=timeout,
                )
            except LECoCConnectError as e:
                if attempt == 1 and e.result == LE_CONN_RESULT_INSUFFICIENT_RESOURCES:
                    backoff = self._collision_backoff(handle)
                    logger.info(
                        "EATT connect collided on handle=0x%04X; backing off %.3fs",
                        handle, backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise
        raise LECoCConnectError("EATT connect failed after back-off retry")

    async def _handle_incoming_ecfc_request(self, handle: int, ident: int, req) -> None:
        """Respond to an Enhanced Credit-Based request (0x17) from the peer.

        Acceptance is all-or-nothing: if the PSM has a listener and the link
        meets the PSM's required security, allocate one DCID per requested SCID
        (shared negotiated MTU/MPS/credits) and answer 0x18 result=0x0000 with
        the DCIDs. Otherwise refuse all with the mapped result and no DCIDs.
        """
        from pybluehost.l2cap.ble import LECoCChannel
        from pybluehost.l2cap.le_signaling import (
            ECFCConnectionResponse,
            LE_SIG_ECFC_CONNECTION_RESPONSE,
            LE_MIN_CREDIT_BASED_MTU,
            LE_CONN_RESULT_SUCCESS, LE_CONN_RESULT_PSM_NOT_SUPPORTED,
            LE_CONN_RESULT_INVALID_PARAMETERS,
            LE_CONN_RESULT_INSUFFICIENT_RESOURCES,
            LE_CONN_RESULT_SCID_ALREADY_ALLOCATED,
        )

        listener = self._le_listeners.get(req.le_psm)
        duplicate = {s for s in req.scids if s in self._peer_source_cids()}
        result = LE_CONN_RESULT_SUCCESS
        if handle in self._outgoing_ecfc:
            # We have our own Credit-Based Connection Request outstanding on this
            # link, so this one collided with it. Table 4.17's "Some connections
            # refused - insufficient resources available" (0x0004) is the
            # collision answer; the peer then expects us to back off and retry
            # (PTS L2CAP/TIM/BV-03-C).
            result = LE_CONN_RESULT_INSUFFICIENT_RESOURCES
            logger.info(
                "ECFC request collided with our outstanding request handle=0x%04X "
                "-> result=0x0004", handle,
            )
        elif listener is None:
            result = LE_CONN_RESULT_PSM_NOT_SUPPORTED
        elif req.mtu < LE_MIN_CREDIT_BASED_MTU or req.mps < 1:
            # §4.22: LE_MTU is 64..65535; anything below is an invalid parameter
            # (L2CAP/ECFC/BV-26-C, whose request deliberately asks for MTU < 64).
            # A zero MPS would also make the sender's segmentation loop spin
            # without consuming the buffer.
            result = LE_CONN_RESULT_INVALID_PARAMETERS
        elif duplicate:
            # A Source CID we already own cannot be re-used by the peer
            # (L2CAP/ECFC/BV-20-C: the second request repeats the first
            # channel's SCID).
            result = LE_CONN_RESULT_SCID_ALREADY_ALLOCATED
        else:
            ok, refusal = self._le_security_met(handle, req.le_psm)
            if not ok:
                result = refusal
        # §4.25 calls 0x000A "Some connections refused": when only part of the
        # request is bad, the good channels are still established and their DCID
        # slots are filled in. Refusing all of them made PTS drop the ACL right
        # after our response (L2CAP/ECFC/BV-20-C stayed INDCSV).
        partial = (
            result == LE_CONN_RESULT_SCID_ALREADY_ALLOCATED
            and len(duplicate) < len(req.scids)
        )
        logger.debug(
            "ECFC request psm=0x%04X scids=%s mtu=%d mps=%d credits=%d listener=%s "
            "required_sec=%s -> result=0x%04X partial=%s",
            req.le_psm, req.scids, req.mtu, req.mps, req.initial_credits,
            listener is not None,
            self._le_listener_security.get(req.le_psm), result, partial,
        )

        our_mtu, our_mps, our_credits = 512, 247, 10

        if result != LE_CONN_RESULT_SUCCESS and not partial:
            # zephyr's l2cap_ecred_conn_rsp always emits one DCID slot per
            # requested SCID, zero-filled on refusal ("set dcid to zeros here,
            # in case of all connections refused error"). PTS expects those
            # slots to be present — a short refusal body makes it wait forever.
            await self._send_le_signaling(
                handle=handle,
                code=LE_SIG_ECFC_CONNECTION_RESPONSE, ident=ident,
                payload=ECFCConnectionResponse(
                    mtu=0, mps=0, initial_credits=0, result=result,
                    dcids=(0,) * len(req.scids),
                ).encode(),
            )
            return

        dcids: list[int] = []
        accepted: list[tuple[int, int]] = []
        for scid in req.scids:
            if partial and scid in duplicate:
                dcids.append(0)
                continue
            dcid = self._allocate_le_cid()
            dcids.append(dcid)
            accepted.append((scid, dcid))

        await self._send_le_signaling(
            handle=handle,
            code=LE_SIG_ECFC_CONNECTION_RESPONSE, ident=ident,
            payload=ECFCConnectionResponse(
                mtu=our_mtu, mps=our_mps, initial_credits=our_credits,
                result=result, dcids=tuple(dcids),
            ).encode(),
        )

        created = []
        for scid, dcid in accepted:
            ch = LECoCChannel(
                connection_handle=handle, local_cid=dcid, peer_cid=scid,
                hci=self._hci,
                mtu=min(our_mtu, req.mtu), mps=min(our_mps, req.mps),
                initial_credits=req.initial_credits,
                rx_mtu=our_mtu, rx_mps=our_mps,
                psm=req.le_psm,
            )
            ch._credit_grant_cb = lambda n, _c=ch: self.grant_le_coc_credits(_c, n)
            ch._violation_cb = lambda _c=ch: self.disconnect_le_coc_channel(_c)
            self._le_channels[dcid] = ch
            self._connections[handle][dcid] = ch
            created.append(ch)

        try:
            for ch in created:
                result_cb = listener(ch)
                if asyncio.iscoroutine(result_cb):
                    asyncio.create_task(result_cb)
        except Exception:
            logger.exception("ECFC listener raised; channels stay open")

    async def _handle_incoming_ecfc_reconfigure(self, handle: int, ident: int, req) -> None:
        """Respond to an Enhanced Credit-Based Reconfigure request (0x19).

        Validation per Core 5.2 Vol 3 Part A §4.25: every DCID must be one of
        our channels (else 0x0003); the new MTU/MPS must not exceed the current
        negotiated values — an increase is refused (0x0004); a *reduction* may
        cover only a single channel per request, so reducing the MTU (0x0001) or
        MPS (0x0002) for >1 channel is refused. A valid request is applied to
        the channel(s) and acknowledged (0x0000). PTS ECFC/BI cases drive each
        rejection path.
        """
        from pybluehost.l2cap.le_signaling import (
            ECFCReconfigureResponse,
            LE_SIG_ECFC_RECONFIGURE_RESPONSE,
            LE_MIN_CREDIT_BASED_MTU,
            RECONFIG_RESULT_SUCCESS, RECONFIG_RESULT_MTU_MULTI_CHANNEL,
            RECONFIG_RESULT_MPS_MULTI_CHANNEL, RECONFIG_RESULT_INVALID_CID,
            RECONFIG_RESULT_OTHER,
        )

        channels = []
        for dcid in req.dcids:
            ch = self._le_channels.get(dcid)
            if ch is None:
                channels = None
                break
            channels.append(ch)

        if channels is None:
            result = RECONFIG_RESULT_INVALID_CID
        else:
            # Result codes confirmed against PTS L2CAP/ECFC/BI-03..07 + BV-23/25
            # (bluez issue #1865). The MTU baseline is the *negotiated* channel
            # MTU (`_mtu` = PTS's advertised receive MTU): any MTU reduction is
            # refused 0x0001 regardless of channel count (BI-03). The MPS
            # baseline is the IUT's advertised receive MPS (`_rx_mps` = 247):
            # an MPS reduction covering >1 channel is refused 0x0002 (BI-04),
            # while a single-channel MPS reduction (even far below 247) is a
            # valid reconfigure (BI-04 second request, BV-23/25). An increase of
            # either is refused 0x0004 (BI-06).
            # anchored to the advertised value (`_reconfig_base_mps`), not the
            # enforcement-mutated `_rx_mps`, so a later request above the
            # already-reduced MPS is still judged a reduction (BI-07).
            cur_mtu = min(getattr(ch, "_mtu", req.mtu) for ch in channels)
            cur_mps = min(getattr(ch, "_reconfig_base_mps", req.mps) for ch in channels)
            # Result codes follow L2CAP.TS 4.9.1.16-4.9.1.20:
            #   0x0001 MTU reduced — never allowed (BI-03), any channel count.
            #   0x0002 MPS reduced across >1 channel (BI-04); a single-channel
            #          reduction is a legal reconfigure (BV-23/25).
            #   0x0004 MPS below the supported minimum (BI-06, "MPS < MPSMIN").
            # An *increase* is legal and is the whole point of BV-22/BV-23 — the
            # requester grows the MTU. Refusing increases here made the IUT
            # answer 0x0004 to BV-23's request to go from MTU 64 to 65, and PTS
            # dropped the ACL straight after (on-air: 0x19 mtu=65 mps=64 →
            # 0x1A result=0x0004).
            if req.mtu < cur_mtu:
                result = RECONFIG_RESULT_MTU_MULTI_CHANNEL
            elif len(channels) > 1 and req.mps < cur_mps:
                result = RECONFIG_RESULT_MPS_MULTI_CHANNEL
            elif req.mps < LE_MIN_CREDIT_BASED_MTU:
                result = RECONFIG_RESULT_OTHER
            else:
                result = RECONFIG_RESULT_SUCCESS

        await self._send_le_signaling(
            handle=handle,
            code=LE_SIG_ECFC_RECONFIGURE_RESPONSE, ident=ident,
            payload=ECFCReconfigureResponse(result=result).encode(),
        )

        if result == RECONFIG_RESULT_SUCCESS:
            for ch in channels:
                # Core Vol 3 Part A §4.26: the 0x19 carries the REQUESTER's new
                # receive limits — accepting it raises what WE may send
                # (`_mtu`/`_mps`), never what we accept (`_rx_mtu`/`_rx_mps`).
                # Applying them to the wrong side made auto-pts keep sending
                # 64-byte SDUs after BV-23's MTU growth (L2CAP/ECFC/BV-23).
                ch._mtu = req.mtu
                ch._mps = req.mps
                self._emit_reconfigured(ch)
            logger.info(
                "ECFC reconfigure applied: mtu=%d mps=%d on %d channel(s) handle=0x%04X",
                req.mtu, req.mps, len(channels), handle,
            )
        else:
            logger.info(
                "ECFC reconfigure refused result=0x%04X (mtu=%d mps=%d dcids=%s) handle=0x%04X",
                result, req.mtu, req.mps, [hex(d) for d in req.dcids], handle,
            )

    async def reconfigure_le_coc_channels(
        self, handle: int, *, mtu: int, channels: list, timeout: float = 5.0,
    ) -> None:
        """Initiate an ECFC Reconfigure (0x19) of the shared MTU on `channels`.

        PTS L2CAP/ECFC/BV-22/23/24 (Renegotiate MTU/MPS — Initiator): the IUT
        sends a Reconfigure Request listing the peer's CIDs (destination CIDs)
        and awaits the 0x1A result. On success the negotiated receive MTU of
        the listed channels is updated. Raises RuntimeError on refusal,
        asyncio.TimeoutError when no response arrives.
        """
        from pybluehost.l2cap.le_signaling import (
            ECFCReconfigureRequest, ECFCReconfigureResponse, LE_SIG_ECFC_RECONFIGURE_REQUEST,
        )
        if handle not in self._connections or CID_LE_SIGNALING not in self._connections[handle]:
            raise RuntimeError(
                f"no LE connection on handle 0x{handle:04X}; cannot reconfigure"
            )
        if not channels:
            raise RuntimeError("reconfigure requires at least one channel")
        dcids = tuple(ch._peer_cid for ch in channels)
        mps = min((getattr(ch, "_rx_mps", 247) for ch in channels), default=247)
        ident = self._next_le_signaling_id_value()
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_le_reconfigure[ident] = fut
        try:
            await self._send_le_signaling(
                handle=handle,
                code=LE_SIG_ECFC_RECONFIGURE_REQUEST, ident=ident,
                payload=ECFCReconfigureRequest(
                    mtu=mtu, mps=mps, dcids=dcids,
                ).encode(),
            )
            try:
                resp = await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                self._pending_le_reconfigure.pop(ident, None)
                raise
        except BaseException:
            self._pending_le_reconfigure.pop(ident, None)
            raise

        if getattr(resp, "result", 0) != 0:
            raise RuntimeError(
                f"ECFC reconfigure refused: result=0x{resp.result:04X}"
            )
        for ch in channels:
            ch._rx_mtu = mtu
            ch._mtu = mtu
            self._emit_reconfigured(ch)
        logger.info(
            "ECFC reconfigure (initiator) applied: mtu=%d on %d channel(s) handle=0x%04X",
            mtu, len(channels), handle,
        )

    async def _handle_incoming_le_coc_request(self, handle: int, ident: int, req) -> None:
        from pybluehost.l2cap.ble import LECoCChannel
        from pybluehost.l2cap.le_signaling import (
            LECreditBasedConnectionResponse,
            LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE,
            LE_CONN_RESULT_SUCCESS, LE_CONN_RESULT_PSM_NOT_SUPPORTED,
            LE_CONN_RESULT_SCID_ALREADY_ALLOCATED,
        )

        listener = self._le_listeners.get(req.le_psm)
        if listener is None:
            await self._send_le_signaling(
                handle=handle,
                code=LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE, ident=ident,
                payload=LECreditBasedConnectionResponse(
                    dcid=0, mtu=0, mps=0, initial_credits=0,
                    result=LE_CONN_RESULT_PSM_NOT_SUPPORTED,
                ).encode(),
            )
            return

        # Enforce the PSM's required security level (PTS security-responder cases:
        # L2CAP/LE/CFC/BV-11/13/15/25). If the link doesn't meet it, refuse with the
        # mapped result code; the peer upgrades security and retries, and the
        # re-evaluation below then accepts.
        ok, refusal = self._le_security_met(handle, req.le_psm)
        if not ok:
            await self._send_le_signaling(
                handle=handle,
                code=LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE, ident=ident,
                payload=LECreditBasedConnectionResponse(
                    dcid=0, mtu=0, mps=0, initial_credits=0,
                    result=refusal,
                ).encode(),
            )
            return

        # Refuse a connection request whose Source CID is already in use by an
        # established channel on this connection (Core Spec Vol 3 Part A —
        # Result=0x000A "Source CID already allocated"). PTS L2CAP/LE/CFC/BV-20
        # reuses the SCID of an open channel and expects this refusal (or a
        # Command Reject) rather than a second successful connect.
        for existing in self._le_channels.values():
            if (getattr(existing, "_connection_handle", None) == handle
                    and getattr(existing, "_peer_cid", None) == req.scid):
                await self._send_le_signaling(
                    handle=handle,
                    code=LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE, ident=ident,
                    payload=LECreditBasedConnectionResponse(
                        dcid=0, mtu=0, mps=0, initial_credits=0,
                        result=LE_CONN_RESULT_SCID_ALREADY_ALLOCATED,
                    ).encode(),
                )
                return

        # Allocate our local CID + pick our negotiation params.
        dcid = self._allocate_le_cid()
        our_mtu, our_mps, our_credits = 512, 247, 10

        await self._send_le_signaling(
            handle=handle,
            code=LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE, ident=ident,
            payload=LECreditBasedConnectionResponse(
                dcid=dcid, mtu=our_mtu, mps=our_mps,
                initial_credits=our_credits, result=LE_CONN_RESULT_SUCCESS,
            ).encode(),
        )

        ch = LECoCChannel(
            connection_handle=handle, local_cid=dcid, peer_cid=req.scid,
            hci=self._hci,
            mtu=min(our_mtu, req.mtu), mps=min(our_mps, req.mps),
            initial_credits=req.initial_credits,
            rx_mtu=our_mtu, rx_mps=our_mps,
            psm=req.le_psm,
        )
        ch._credit_grant_cb = lambda n, _c=ch: self.grant_le_coc_credits(_c, n)
        ch._violation_cb = lambda _c=ch: self.disconnect_le_coc_channel(_c)
        self._le_channels[dcid] = ch
        self._connections[handle][dcid] = ch

        try:
            result = listener(ch)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        except Exception:
            logger.exception("LE CoC listener raised")

    async def grant_le_coc_credits(self, channel, credits: int) -> None:
        """Send LE_FLOW_CONTROL_CREDIT on `channel`, granting the peer `credits`
        more send credits (BTP L2CAP CREDITS / PTS CFC flow-control tests)."""
        from pybluehost.l2cap.le_signaling import (
            LEFlowControlCredit, LE_SIG_LE_FLOW_CONTROL_CREDIT,
        )
        ident = self._next_le_signaling_id_value()
        await self._send_le_signaling(
            handle=channel.connection_handle,
            code=LE_SIG_LE_FLOW_CONTROL_CREDIT,
            ident=ident,
            payload=LEFlowControlCredit(cid=channel.cid, credits=credits).encode(),
        )

    async def disconnect_le_coc_channel(self, channel) -> None:
        """Tear down an LE CoC channel: send DISCONNECTION_REQUEST + remove
        local state. Peer's DISCONNECTION_RESPONSE is silently consumed (see
        _on_le_signaling)."""
        from pybluehost.l2cap.le_signaling import (
            DisconnectionRequest, LE_SIG_DISCONNECTION_REQUEST,
        )
        local_cid = channel.cid
        peer_cid = channel._peer_cid
        handle = channel.connection_handle
        ident = self._next_le_signaling_id_value()
        await self._send_le_signaling(
            handle=handle, code=LE_SIG_DISCONNECTION_REQUEST, ident=ident,
            payload=DisconnectionRequest(dcid=peer_cid, scid=local_cid).encode(),
        )
        self._le_channels.pop(local_cid, None)
        if handle in self._connections:
            self._connections[handle].pop(local_cid, None)

    def le_coc_channels(self, handle: int) -> list:
        """Return all channels (fixed + CoC) tracked for a connection handle;
        callers filter by `psm`/CID for what they need."""
        return list(self._connections.get(handle, {}).values())

    async def _handle_le_disconnection_request(self, handle: int, ident: int, req) -> None:
        from pybluehost.l2cap.le_signaling import (
            CommandReject, DisconnectionResponse, LE_SIG_COMMAND_REJECT,
            LE_SIG_DISCONNECTION_RESPONSE, LE_REJECT_REASON_INVALID_CID,
        )
        # req.dcid is OUR side's CID per Core Spec §4.6 (the request says
        # "disconnect this destination" — i.e., the CID the peer is sending TO).
        local_cid = req.dcid
        peer_cid = req.scid
        if local_cid not in self._le_channels:
            # The DCID is not one of our established LE CoC channels — either an
            # unrecognised CID or a fixed channel (ATT/SMP/signaling). Per Core
            # Spec §4.1 we must answer with COMMAND_REJECT_RSP Reason=0x0002
            # (Invalid CID in request), NOT a Disconnection Response (PTS
            # L2CAP/LE/CFC/BV-23-C — a plain response/stall makes PTS time out).
            await self._send_le_signaling(
                handle=handle, code=LE_SIG_COMMAND_REJECT, ident=ident,
                payload=CommandReject(
                    reason=LE_REJECT_REASON_INVALID_CID, refused_cid=local_cid,
                ).encode(),
            )
            return
        self._le_channels.pop(local_cid, None)
        if handle in self._connections:
            self._connections[handle].pop(local_cid, None)
        await self._send_le_signaling(
            handle=handle, code=LE_SIG_DISCONNECTION_RESPONSE, ident=ident,
            payload=DisconnectionResponse(dcid=local_cid, scid=peer_cid).encode(),
        )
