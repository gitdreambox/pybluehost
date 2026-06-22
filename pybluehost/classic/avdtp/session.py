"""AVDTPSession — owns one peer's signaling channel + transaction tracker.

The session reads incoming AVDTP packets from the signaling channel, demuxes
them by transaction_id (for responses to commands we sent) or signal_id (for
peer-initiated commands), and dispatches to handlers.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from pybluehost.classic.avdtp.constants import (
    AVDTPErrorCode, AVDTPMessageType, AVDTPPacketType, AVDTPSignalID,
    ServiceCategory,
)
from pybluehost.classic.avdtp.media import AVDTPMediaPacket
from pybluehost.classic.avdtp.sep import StreamEndpoint
from pybluehost.classic.avdtp.signaling import (
    AVDTPMessage,
    decode_capabilities, decode_sep_descriptors, decode_seid_byte,
    encode_capabilities, encode_sep_descriptor, encode_seid_byte,
)


_log = logging.getLogger(__name__)


class AVDTPProtocolError(RuntimeError):
    """Raised when a peer returns REJECT or sends a malformed packet."""

    def __init__(self, message: str, error_code: int | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class AVDTPSession:
    """One AVDTP signaling channel to a single peer.

    `local_seps`: SEPs this session exposes to the peer.
    `channel`: must have async `send(bytes)` and `recv() -> bytes`.
    """

    def __init__(self, channel, *, local_seps: list[StreamEndpoint]) -> None:
        self._channel = channel
        self._local_seps = {sep.seid: sep for sep in local_seps}
        self._capabilities: dict[int, list[tuple[ServiceCategory, bytes]]] = {}
        self._pending: dict[int, asyncio.Future] = {}
        self._next_tid = 0
        self._rx_task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()
        self._media_channel = None
        self._media_uses_callback = False
        self._media_attached = asyncio.Event()
        # Inbound queues. Real L2CAP ClassicChannel pushes via on_data callback;
        # in-memory test channels expose async recv() and the rx loop pulls
        # from there directly. We bridge both into one queue per channel type.
        self._inbound: asyncio.Queue[bytes] = asyncio.Queue()
        self._media_inbound: asyncio.Queue[bytes] = asyncio.Queue()
        self._channel_uses_callback = hasattr(channel, "set_events")
        if self._channel_uses_callback:
            from pybluehost.l2cap.channel import SimpleChannelEvents
            channel.set_events(SimpleChannelEvents(on_data=self._on_channel_data))

    async def _on_channel_data(self, data: bytes) -> None:
        await self._inbound.put(bytes(data))

    # lifecycle ------------------------------------------------------
    async def start(self) -> None:
        if self._rx_task is not None:
            return
        self._rx_task = asyncio.create_task(self._rx_loop())

    async def stop(self) -> None:
        self._stopped.set()
        if self._rx_task is not None:
            self._rx_task.cancel()
            try:
                await self._rx_task
            except asyncio.CancelledError:
                pass
            self._rx_task = None
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    # SEP introspection ----------------------------------------------
    def get_sep(self, seid: int) -> StreamEndpoint:
        return self._local_seps[seid]

    def set_capabilities(self, *, seid: int, capabilities: list[tuple[ServiceCategory, bytes]]) -> None:
        self._capabilities[seid] = capabilities

    # media channel ---------------------------------------------------
    def attach_media_channel(self, channel) -> None:
        """Attach the L2CAP media channel that was opened in response to OPEN.

        Caller arranges the L2CAP connect+config; AVDTPSession handles only the
        AVDTP layer on top of the channel.
        """
        self._media_channel = channel
        self._media_uses_callback = hasattr(channel, "set_events")
        if self._media_uses_callback:
            from pybluehost.l2cap.channel import SimpleChannelEvents
            channel.set_events(SimpleChannelEvents(on_data=self._on_media_data))
        self._media_attached.set()

    async def _on_media_data(self, data: bytes) -> None:
        await self._media_inbound.put(bytes(data))

    async def send_media(self, packet: AVDTPMediaPacket) -> None:
        if self._media_channel is None:
            raise RuntimeError("media channel not attached — call attach_media_channel() after OPEN")
        await self._media_channel.send(packet.to_bytes())

    async def recv_media(self) -> AVDTPMediaPacket:
        # Block until a media channel is attached (peer-side path: the channel
        # arrives asynchronously via the L2CAP listener after OPEN).
        if self._media_channel is None:
            await self._media_attached.wait()
        if self._media_uses_callback:
            data = await self._media_inbound.get()
        else:
            data = await self._media_channel.recv()
        return AVDTPMediaPacket.from_bytes(data)

    # transaction allocator ------------------------------------------
    def _allocate_tid(self) -> int:
        tid = self._next_tid
        self._next_tid = (self._next_tid + 1) & 0xF
        return tid

    # commands sent to peer ------------------------------------------
    async def _send_command(self, signal_id: AVDTPSignalID, payload: bytes = b"") -> bytes:
        tid = self._allocate_tid()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[tid] = fut
        msg = AVDTPMessage(
            transaction_id=tid,
            packet_type=AVDTPPacketType.SINGLE,
            message_type=AVDTPMessageType.COMMAND,
            signal_id=signal_id,
            payload=payload,
        )
        await self._channel.send(msg.to_bytes())
        try:
            response = await asyncio.wait_for(fut, timeout=5.0)
        finally:
            self._pending.pop(tid, None)
        if isinstance(response, AVDTPProtocolError):
            raise response
        return response

    async def discover(self) -> list[StreamEndpoint]:
        raw = await self._send_command(AVDTPSignalID.DISCOVER)
        descriptors = decode_sep_descriptors(raw)
        out: list[StreamEndpoint] = []
        for seid, in_use, media_type, tsep in descriptors:
            sep = StreamEndpoint(seid=seid, media_type=media_type, tsep=tsep)
            if in_use:
                sep._state = "CONFIGURED"
            out.append(sep)
        return out

    async def get_capabilities(self, *, peer_seid: int) -> list[tuple[ServiceCategory, bytes]]:
        payload = bytes([encode_seid_byte(peer_seid)])
        raw = await self._send_command(AVDTPSignalID.GET_CAPABILITIES, payload)
        return decode_capabilities(raw)

    async def get_all_capabilities(self, *, peer_seid: int) -> list[tuple[ServiceCategory, bytes]]:
        payload = bytes([encode_seid_byte(peer_seid)])
        raw = await self._send_command(AVDTPSignalID.GET_ALL_CAPABILITIES, payload)
        return decode_capabilities(raw)

    async def set_configuration(
        self,
        *,
        peer_seid: int,
        local_seid: int,
        capabilities: list[tuple[ServiceCategory, bytes]],
    ) -> None:
        payload = (
            bytes([encode_seid_byte(peer_seid), encode_seid_byte(local_seid)])
            + encode_capabilities(capabilities)
        )
        await self._send_command(AVDTPSignalID.SET_CONFIGURATION, payload)

    async def open(self, *, peer_seid: int) -> None:
        payload = bytes([encode_seid_byte(peer_seid)])
        await self._send_command(AVDTPSignalID.OPEN, payload)

    async def start_stream(self, *, peer_seids: list[int]) -> None:
        payload = bytes(encode_seid_byte(s) for s in peer_seids)
        await self._send_command(AVDTPSignalID.START, payload)

    async def suspend(self, *, peer_seids: list[int]) -> None:
        payload = bytes(encode_seid_byte(s) for s in peer_seids)
        await self._send_command(AVDTPSignalID.SUSPEND, payload)

    async def close(self, *, peer_seid: int) -> None:
        payload = bytes([encode_seid_byte(peer_seid)])
        await self._send_command(AVDTPSignalID.CLOSE, payload)

    async def abort(self, *, peer_seid: int) -> None:
        payload = bytes([encode_seid_byte(peer_seid)])
        await self._send_command(AVDTPSignalID.ABORT, payload)

    # rx loop --------------------------------------------------------
    async def _rx_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                if self._channel_uses_callback:
                    data = await self._inbound.get()
                else:
                    data = await self._channel.recv()
            except asyncio.CancelledError:
                raise
            except Exception:
                return
            try:
                msg = AVDTPMessage.from_bytes(data)
            except ValueError:
                _log.warning("dropping malformed AVDTP message")
                continue
            await self._dispatch(msg)

    async def _dispatch(self, msg: AVDTPMessage) -> None:
        if msg.message_type in (AVDTPMessageType.RESPONSE_ACCEPT, AVDTPMessageType.RESPONSE_REJECT):
            fut = self._pending.get(msg.transaction_id)
            if fut is None or fut.done():
                return
            if msg.message_type == AVDTPMessageType.RESPONSE_ACCEPT:
                fut.set_result(msg.payload)
            else:
                err = AVDTPProtocolError(
                    f"peer rejected signal {AVDTPSignalID(msg.signal_id).name}",
                    error_code=msg.payload[0] if msg.payload else None,
                )
                fut.set_result(err)
            return
        await self._handle_peer_command(msg)

    async def _handle_peer_command(self, msg: AVDTPMessage) -> None:
        try:
            if msg.signal_id == AVDTPSignalID.DISCOVER:
                payload = b"".join(
                    encode_sep_descriptor(
                        seid=sep.seid, in_use=sep.in_use,
                        media_type=sep.media_type, tsep=sep.tsep,
                    )
                    for sep in self._local_seps.values()
                )
                await self._send_accept(msg, payload)
            elif msg.signal_id in (
                AVDTPSignalID.GET_CAPABILITIES,
                AVDTPSignalID.GET_ALL_CAPABILITIES,
            ):
                seid = decode_seid_byte(msg.payload[0])
                caps = self._capabilities.get(seid, [])
                await self._send_accept(msg, encode_capabilities(caps))
            elif msg.signal_id == AVDTPSignalID.SET_CONFIGURATION:
                if len(msg.payload) < 2:
                    raise AVDTPProtocolError("SET_CONFIGURATION too short", AVDTPErrorCode.BAD_LENGTH)
                acp_seid = decode_seid_byte(msg.payload[0])
                config_bytes = bytes(msg.payload[2:])
                sep = self._local_seps[acp_seid]
                sep.transition_set_configuration(config_bytes)
                await self._send_accept(msg, b"")
            elif msg.signal_id == AVDTPSignalID.OPEN:
                acp_seid = decode_seid_byte(msg.payload[0])
                sep = self._local_seps[acp_seid]
                sep.transition_open()
                await self._send_accept(msg, b"")
            elif msg.signal_id == AVDTPSignalID.START:
                for byte in msg.payload:
                    sep = self._local_seps[decode_seid_byte(byte)]
                    sep.transition_start()
                await self._send_accept(msg, b"")
            elif msg.signal_id == AVDTPSignalID.SUSPEND:
                for byte in msg.payload:
                    sep = self._local_seps[decode_seid_byte(byte)]
                    sep.transition_suspend()
                await self._send_accept(msg, b"")
            elif msg.signal_id == AVDTPSignalID.CLOSE:
                acp_seid = decode_seid_byte(msg.payload[0])
                self._local_seps[acp_seid].transition_close()
                await self._send_accept(msg, b"")
            elif msg.signal_id == AVDTPSignalID.ABORT:
                acp_seid = decode_seid_byte(msg.payload[0])
                self._local_seps[acp_seid].transition_abort()
                await self._send_accept(msg, b"")
            else:
                await self._send_reject(msg, AVDTPErrorCode.NOT_SUPPORTED_COMMAND)
        except AVDTPProtocolError as e:
            await self._send_reject(msg, e.error_code or AVDTPErrorCode.BAD_STATE)
        except Exception as e:
            _log.exception("AVDTP command handler raised: %s", e)
            await self._send_reject(msg, AVDTPErrorCode.BAD_STATE)

    async def _send_accept(self, request: AVDTPMessage, payload: bytes) -> None:
        response = AVDTPMessage(
            transaction_id=request.transaction_id,
            packet_type=AVDTPPacketType.SINGLE,
            message_type=AVDTPMessageType.RESPONSE_ACCEPT,
            signal_id=request.signal_id,
            payload=payload,
        )
        await self._channel.send(response.to_bytes())

    async def _send_reject(self, request: AVDTPMessage, error_code: int) -> None:
        response = AVDTPMessage(
            transaction_id=request.transaction_id,
            packet_type=AVDTPPacketType.SINGLE,
            message_type=AVDTPMessageType.RESPONSE_REJECT,
            signal_id=request.signal_id,
            payload=bytes([int(error_code)]),
        )
        await self._channel.send(response.to_bytes())
