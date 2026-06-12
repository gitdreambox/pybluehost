"""AVCTPSession — owns one peer's L2CAP signaling channel and runs the
transaction tracker on top.

Mirrors the pattern from pybluehost/avdtp/session.py: allocate transaction
labels for outgoing commands, await peer responses, dispatch incoming
peer commands to an async callback, bridge L2CAP callback → recv queue.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from pybluehost.avctp.constants import (
    AVCTPMessageDirection, AVCTPPacketType,
)
from pybluehost.avctp.message import AVCTPMessage, AVCTPReassembler


_log = logging.getLogger(__name__)


class AVCTPSession:
    """One AVCTP signaling channel to a single peer."""

    def __init__(
        self,
        channel,
        *,
        profile_id: int,
        on_command: Optional[Callable[[bytes], Awaitable[bytes]]] = None,
    ) -> None:
        self._channel = channel
        self._profile_id = profile_id
        self._on_command = on_command
        self._pending: dict[int, asyncio.Future] = {}
        self._next_tid = 0
        self._rx_task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()
        self._reassembler = AVCTPReassembler()
        self._inbound: asyncio.Queue[bytes] = asyncio.Queue()
        self._channel_uses_callback = hasattr(channel, "set_events")
        if self._channel_uses_callback:
            from pybluehost.l2cap.channel import SimpleChannelEvents
            channel.set_events(SimpleChannelEvents(on_data=self._on_channel_data))

    async def _on_channel_data(self, data: bytes) -> None:
        await self._inbound.put(bytes(data))

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

    def _allocate_tid(self) -> int:
        tid = self._next_tid
        self._next_tid = (self._next_tid + 1) & 0xF
        return tid

    async def send_command(self, payload: bytes) -> bytes:
        """Send a command payload to the peer; await and return its response payload."""
        tid = self._allocate_tid()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[tid] = fut
        msg = AVCTPMessage(
            transaction_label=tid,
            packet_type=AVCTPPacketType.SINGLE,
            cr=AVCTPMessageDirection.COMMAND,
            ipid=0,
            profile_id=self._profile_id,
            payload=payload,
        )
        await self._channel.send(msg.to_bytes())
        try:
            response = await asyncio.wait_for(fut, timeout=5.0)
        finally:
            self._pending.pop(tid, None)
        if isinstance(response, RuntimeError):
            raise response
        return response

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
                raw_msg = AVCTPMessage.from_bytes(data)
            except ValueError:
                _log.warning("dropping malformed AVCTP packet")
                continue
            msg = self._reassembler.feed(raw_msg)
            if msg is None:
                continue
            await self._dispatch(msg)

    async def _dispatch(self, msg: AVCTPMessage) -> None:
        if msg.cr == AVCTPMessageDirection.RESPONSE:
            fut = self._pending.get(msg.transaction_label)
            if fut is None or fut.done():
                return
            if msg.ipid == 1:
                fut.set_result(RuntimeError(
                    f"peer returned IPID=1 (unknown profile_id 0x{msg.profile_id:04X})"
                ))
            else:
                fut.set_result(msg.payload)
            return

        # Peer command. If no handler, respond with IPID=1.
        if self._on_command is None:
            await self._send_ipid_response(msg)
            return
        try:
            resp_payload = await self._on_command(msg.payload)
        except Exception:
            _log.exception("AVCTP on_command handler raised")
            await self._send_ipid_response(msg)
            return
        await self._send_response(msg, resp_payload)

    async def _send_response(self, request: AVCTPMessage, payload: bytes) -> None:
        response = AVCTPMessage(
            transaction_label=request.transaction_label,
            packet_type=AVCTPPacketType.SINGLE,
            cr=AVCTPMessageDirection.RESPONSE,
            ipid=0,
            profile_id=self._profile_id,
            payload=payload,
        )
        await self._channel.send(response.to_bytes())

    async def _send_ipid_response(self, request: AVCTPMessage) -> None:
        response = AVCTPMessage(
            transaction_label=request.transaction_label,
            packet_type=AVCTPPacketType.SINGLE,
            cr=AVCTPMessageDirection.RESPONSE,
            ipid=1,
            profile_id=request.profile_id,
            payload=b"",
        )
        await self._channel.send(response.to_bytes())
