"""L2CAPManager -- main L2CAP dispatch: connection tracking, channel routing, SAR."""
from __future__ import annotations

import asyncio
import struct
from typing import Callable, Awaitable

from pybluehost.core.types import LinkType
from pybluehost.hci.constants import ACL_PB_FIRST_AUTO_FLUSH
from pybluehost.hci.packets import HCIACLData, HCIEvent
from pybluehost.l2cap.ble import FixedChannel
from pybluehost.l2cap.channel import Channel, ChannelState, SimpleChannelEvents
from pybluehost.l2cap.constants import CID_ATT, CID_CLASSIC_SIGNALING, CID_LE_SIGNALING, CID_SMP
from pybluehost.l2cap.sar import Reassembler


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
            channels[CID_CLASSIC_SIGNALING] = FixedChannel(
                connection_handle=handle, cid=CID_CLASSIC_SIGNALING, hci=self._hci, mtu=48,
            )
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
