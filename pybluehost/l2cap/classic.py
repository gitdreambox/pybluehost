"""Classic L2CAP channels: ClassicChannel with Basic, ERTM, and Streaming modes."""
from __future__ import annotations

import asyncio
import struct
from enum import IntEnum
from typing import Awaitable, Callable

from pybluehost.hci.constants import ACL_PB_FIRST_AUTO_FLUSH
from pybluehost.l2cap.channel import (
    Channel,
    ChannelEvents,
    ChannelState,
    SimpleChannelEvents,
)


class ChannelMode(IntEnum):
    BASIC = 0x00
    ERTM = 0x03
    STREAMING = 0x04


class ERTMEngine:
    """Enhanced Retransmission Mode engine.

    I-frame format (simplified): ctrl_lo(1) + ctrl_hi(1) + sdu_len(2 LE) + sdu_data
    - ctrl_lo: (tx_seq << 1) & 0xFE  -- bit 0 = 0 means I-frame
    - ctrl_hi: (req_seq << 1) & 0xFE

    S-frame format: ctrl_byte(1) + 0x00
    - ctrl_byte: 0x01 (S-frame marker) | ((req_seq & 0x3F) << 2)
    """

    def __init__(self, tx_window: int = 8) -> None:
        self._tx_window = tx_window
        self._tx_seq: int = 0
        self._req_seq: int = 0
        self._last_acked: int = 0
        self._unacked: dict[int, bytes] = {}
        self._credits = asyncio.Semaphore(tx_window)
        self._send_fn: Callable[[bytes], Awaitable[None]] | None = None
        self._received_sdus: list[bytes] = []

    def set_send_fn(self, fn: Callable[[bytes], Awaitable[None]]) -> None:
        self._send_fn = fn

    async def send_sdu(self, sdu: bytes) -> None:
        await self._credits.acquire()
        seq = self._tx_seq
        self._tx_seq = (self._tx_seq + 1) % 64
        ctrl_lo = (seq << 1) & 0xFE  # I-frame: bit 0 = 0
        ctrl_hi = (self._req_seq << 1) & 0xFE
        frame = struct.pack("<BBH", ctrl_lo, ctrl_hi, len(sdu)) + sdu
        self._unacked[seq] = frame
        if self._send_fn:
            await self._send_fn(frame)

    def _seq_in_range(self, seq: int, start: int, end: int) -> bool:
        """Check if seq is in [start, end) with mod-64 wraparound."""
        if start <= end:
            return start <= seq < end
        return seq >= start or seq < end

    def on_sframe(self, req_seq: int) -> None:
        acked = [
            s
            for s in self._unacked
            if self._seq_in_range(s, self._last_acked, req_seq)
        ]
        for s in sorted(acked):
            self._unacked.pop(s, None)
            self._credits.release()
        self._last_acked = req_seq

    def on_iframe(self, tx_seq: int, data: bytes) -> bytes:
        if tx_seq == self._req_seq:
            self._req_seq = (self._req_seq + 1) % 64
            self._received_sdus.append(data)
        sframe_ctrl = 0x01 | ((self._req_seq & 0x3F) << 2)
        return bytes([sframe_ctrl, 0x00])

    async def retransmit_unacked(self) -> None:
        if self._send_fn:
            for frame in self._unacked.values():
                await self._send_fn(frame)


class StreamingEngine:
    """Streaming Mode engine -- send-only I-frames, no ACK, no retransmit."""

    def __init__(self) -> None:
        self._tx_seq: int = 0
        self._send_fn: Callable[[bytes], Awaitable[None]] | None = None

    def set_send_fn(self, fn: Callable[[bytes], Awaitable[None]]) -> None:
        self._send_fn = fn

    async def send_sdu(self, sdu: bytes) -> None:
        seq = self._tx_seq
        self._tx_seq = (self._tx_seq + 1) % 64
        ctrl_lo = (seq << 1) & 0xFE
        ctrl_hi = 0x00
        frame = struct.pack("<BBH", ctrl_lo, ctrl_hi, len(sdu)) + sdu
        if self._send_fn:
            await self._send_fn(frame)


class ClassicChannel(Channel):
    """Classic L2CAP channel supporting Basic, ERTM, and Streaming modes."""

    def __init__(
        self,
        connection_handle: int,
        local_cid: int,
        peer_cid: int,
        mode: ChannelMode,
        hci: object,
        mtu: int = 672,
    ) -> None:
        self._connection_handle = connection_handle
        self._local_cid = local_cid
        self._peer_cid = peer_cid
        self._mode = mode
        self._hci = hci
        self._mtu = mtu
        self._state = ChannelState.CLOSED
        self._events: ChannelEvents | SimpleChannelEvents | None = None
        self._ertm: ERTMEngine | None = None
        self._streaming: StreamingEngine | None = None

        if mode == ChannelMode.ERTM:
            self._ertm = ERTMEngine()
            self._ertm.set_send_fn(self._send_l2cap_payload)
        elif mode == ChannelMode.STREAMING:
            self._streaming = StreamingEngine()
            self._streaming.set_send_fn(self._send_l2cap_payload)

    @property
    def cid(self) -> int:
        return self._local_cid

    @property
    def connection_handle(self) -> int:
        return self._connection_handle

    @property
    def state(self) -> ChannelState:
        return self._state

    @property
    def mtu(self) -> int:
        return self._mtu

    @property
    def mode(self) -> ChannelMode:
        return self._mode

    def set_events(self, events: ChannelEvents | SimpleChannelEvents) -> None:
        self._events = events

    def open(self) -> None:
        """Move to OPEN state (called after config completes)."""
        self._state = ChannelState.OPEN

    async def send(self, data: bytes) -> None:
        if self._state != ChannelState.OPEN:
            raise RuntimeError("Channel not open")
        if self._mode == ChannelMode.BASIC:
            await self._send_basic(data)
        elif self._mode == ChannelMode.ERTM and self._ertm:
            await self._ertm.send_sdu(data)
        elif self._mode == ChannelMode.STREAMING and self._streaming:
            await self._streaming.send_sdu(data)

    async def close(self) -> None:
        self._state = ChannelState.DISCONNECTING

    async def _on_pdu(self, data: bytes) -> None:
        if self._events and hasattr(self._events, "on_data") and self._events.on_data:
            result = self._events.on_data(data)
            if asyncio.iscoroutine(result):
                await result

    async def _send_basic(self, data: bytes) -> None:
        l2cap_pdu = struct.pack("<HH", len(data), self._peer_cid) + data
        await self._hci.send_acl_data(
            self._connection_handle, ACL_PB_FIRST_AUTO_FLUSH, l2cap_pdu
        )

    async def _send_l2cap_payload(self, payload: bytes) -> None:
        l2cap_pdu = struct.pack("<HH", len(payload), self._peer_cid) + payload
        await self._hci.send_acl_data(
            self._connection_handle, ACL_PB_FIRST_AUTO_FLUSH, l2cap_pdu
        )
