"""L2CAPManager -- main L2CAP dispatch: connection tracking, channel routing, SAR."""
from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

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
        self._pending_le_connect: dict[int, asyncio.Future] = {}      # ident -> future
        self._next_le_signaling_id: int = 1
        self._next_le_cid: int = 0x0040                               # LE dynamic CID range start
        self._le_channels: dict[int, object] = {}                     # local SCID -> channel

    # -- HCI upstream callbacks (registered via hci.set_upstream) --

    async def on_acl_data(self, pkt: HCIACLData) -> None:
        """Called by HCIController when ACL data arrives.

        NOTE: HCIController passes the full HCIACLData packet object.
        """
        result = self._sar.feed(
            handle=pkt.handle, pb_flag=pkt.pb_flag, data=pkt.data
        )
        if result is None:
            return  # incomplete reassembly

        cid, payload = result
        channels = self._connections.get(pkt.handle)
        if channels is None:
            return
        channel = channels.get(cid)
        if channel is None:
            return
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
                    on_data=lambda data, conn_handle=handle: self._on_le_signaling(conn_handle, data),
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

    def listen_le_coc_channel(self, psm: int, handler) -> None:
        """Register `handler(channel: LECoCChannel)` to receive incoming LE CoC
        connections on `psm`. Handler may be sync or async."""
        self._le_listeners[psm] = handler

    # -- LE Credit-Based Channel helpers --

    def _allocate_le_cid(self) -> int:
        cid = self._next_le_cid
        self._next_le_cid += 1
        return cid

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
        await sig_ch.send(encode_le_signaling(code, ident, payload))

    async def _on_le_signaling(self, handle: int, data: bytes) -> None:
        """Dispatch LE signaling PDUs received on the LE signaling fixed channel."""
        from pybluehost.l2cap.le_signaling import (
            DisconnectionRequest, DisconnectionResponse,
            LECreditBasedConnectionRequest, LECreditBasedConnectionResponse,
            LEFlowControlCredit,
            LE_SIG_DISCONNECTION_REQUEST,
            LE_SIG_DISCONNECTION_RESPONSE,
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

        if code == LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST:
            assert isinstance(payload, LECreditBasedConnectionRequest)
            await self._handle_incoming_le_coc_request(handle, ident, payload)
        elif code == LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE:
            assert isinstance(payload, LECreditBasedConnectionResponse)
            fut = self._pending_le_connect.pop(ident, None)
            if fut is not None and not fut.done():
                fut.set_result(payload)
        elif code == LE_SIG_LE_FLOW_CONTROL_CREDIT:
            assert isinstance(payload, LEFlowControlCredit)
            # Credit PDU's CID is the SENDER's CID (i.e., our peer's CID, our channel's peer_cid).
            for ch in self._le_channels.values():
                if getattr(ch, "peer_cid", None) == payload.cid:
                    ch.add_credits(payload.credits)
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
            logger.debug("LE signaling: unhandled code 0x%02X (ident=%d)", code, ident)

    async def connect_le_coc_channel(
        self,
        *,
        handle: int,
        psm: int,
        mtu: int = 512,
        mps: int = 247,
        initial_credits: int = 10,
        timeout: float = 5.0,
    ):
        """Open an LE Credit-Based Channel to the peer on `psm`.

        Returns the established `LECoCChannel`. Raises RuntimeError on
        result != 0x0000, asyncio.TimeoutError if no response within `timeout`.
        """
        from pybluehost.l2cap.ble import LECoCChannel
        from pybluehost.l2cap.le_signaling import (
            LECreditBasedConnectionRequest,
            LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST,
        )

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
            await self._send_le_signaling(
                handle=handle,
                code=LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST,
                ident=ident,
                payload=req.encode(),
            )
            try:
                resp = await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                self._pending_le_connect.pop(ident, None)
                raise
        except BaseException:
            self._pending_le_connect.pop(ident, None)
            raise

        if resp.result != 0x0000:
            raise RuntimeError(
                f"LE CoC connect failed: result=0x{resp.result:04X}"
            )
        ch = LECoCChannel(
            connection_handle=handle,
            local_cid=scid,
            peer_cid=resp.dcid,
            hci=self._hci,
            mtu=min(mtu, resp.mtu),
            mps=min(mps, resp.mps),
            initial_credits=resp.initial_credits,
        )
        self._le_channels[scid] = ch
        self._connections[handle][scid] = ch
        return ch

    async def _handle_incoming_le_coc_request(self, handle: int, ident: int, req) -> None:
        from pybluehost.l2cap.ble import LECoCChannel
        from pybluehost.l2cap.le_signaling import (
            LECreditBasedConnectionResponse,
            LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE,
            LE_CONN_RESULT_SUCCESS, LE_CONN_RESULT_PSM_NOT_SUPPORTED,
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
        )
        self._le_channels[dcid] = ch
        self._connections[handle][dcid] = ch

        try:
            result = listener(ch)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        except Exception:
            logger.exception("LE CoC listener raised")

    async def _handle_le_disconnection_request(self, handle, ident, req) -> None:
        """T5 replaces this stub."""
        logger.debug(
            "LE disconnection request stub (handle=0x%04X ident=%d dcid=0x%04X scid=0x%04X)",
            handle, ident, req.dcid, req.scid,
        )
