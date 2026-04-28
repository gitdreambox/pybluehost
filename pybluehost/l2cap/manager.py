"""L2CAPManager -- main L2CAP dispatch: connection tracking, channel routing, SAR."""
from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass
from typing import Callable, Awaitable

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
    channel: ClassicChannel
    future: asyncio.Future[ClassicChannel]


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
        self._classic_listeners: dict[int, Callable[[ClassicChannel], object]] = {}
        self._classic_inbound_pending: dict[tuple[int, int], _ClassicInboundPending] = {}

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
            channels[CID_LE_SIGNALING] = FixedChannel(
                connection_handle=handle, cid=CID_LE_SIGNALING, hci=self._hci, mtu=23,
            )
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

    async def on_disconnection(self, handle: int, reason: int) -> None:
        """Clean up all channels for a disconnected connection."""
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
        conn_future: asyncio.Future[int] = loop.create_future()
        self._classic_connect_pending[(handle, conn_ident)] = _ClassicConnectPending(
            local_cid=local_cid,
            future=conn_future,
        )
        request = SignalingPacket(
            code=SignalingCode.CONNECTION_REQUEST,
            identifier=conn_ident,
            data=struct.pack("<HH", psm, local_cid),
        )
        await signaling.send(encode_signaling(request))

        try:
            peer_cid = await asyncio.wait_for(conn_future, timeout=timeout)
        finally:
            self._classic_connect_pending.pop((handle, conn_ident), None)

        channel = ClassicChannel(
            connection_handle=handle,
            local_cid=local_cid,
            peer_cid=peer_cid,
            mode=ChannelMode.BASIC,
            hci=self._hci,
        )
        self.register_channel(handle, channel)

        config_ident = self._next_identifier()
        config_future: asyncio.Future[ClassicChannel] = loop.create_future()
        self._classic_config_pending[(handle, config_ident)] = _ClassicConfigPending(
            channel=channel,
            future=config_future,
        )
        configure = SignalingPacket(
            code=SignalingCode.CONFIGURE_REQUEST,
            identifier=config_ident,
            data=struct.pack("<HH", peer_cid, 0x0000),
        )
        await signaling.send(encode_signaling(configure))

        try:
            return await asyncio.wait_for(config_future, timeout=timeout)
        finally:
            self._classic_config_pending.pop((handle, config_ident), None)

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
            if pending is None or pending.future.done():
                return
            if len(packet.data) < 8:
                pending.future.set_exception(RuntimeError("Malformed L2CAP Connection Response"))
                return
            dest_cid, source_cid, result, status = struct.unpack_from("<HHHH", packet.data)
            if source_cid != pending.local_cid:
                pending.future.set_exception(
                    RuntimeError(
                        f"L2CAP Connection Response source CID mismatch: 0x{source_cid:04X}"
                    )
                )
                return
            if result != 0:
                pending.future.set_exception(
                    RuntimeError(
                        f"L2CAP Connection Response failed: result=0x{result:04X} status=0x{status:04X}"
                    )
                )
                return
            pending.future.set_result(dest_cid)
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
                pending.future.set_exception(
                    RuntimeError(f"L2CAP Configure Response failed: result=0x{result:04X}")
                )
                return
            pending.channel.open()
            pending.future.set_result(pending.channel)

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

    async def _handle_classic_configure_request(
        self,
        handle: int,
        packet: SignalingPacket,
    ) -> None:
        signaling = self.get_fixed_channel(handle, CID_CLASSIC_SIGNALING)
        if signaling is None or len(packet.data) < 4:
            return
        dest_cid, _flags = struct.unpack_from("<HH", packet.data)
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
