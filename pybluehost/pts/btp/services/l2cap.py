"""L2CAP BTP service — LE Credit-Based Channels.

Translates auto-pts L2CAP opcodes into IutActions / v1.0 L2CAP API calls.
Owns a per-session map of BTP chan_id (u8) → v1.0 channel object.

Handlers land in P.8 Tasks 2-4; this file is the skeleton.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pybluehost.l2cap.channel import SimpleChannelEvents
from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import BtpFrame
from pybluehost.pts.btp.services.base import BtpService

if TYPE_CHECKING:
    from pybluehost.pts.actions import IutActions
    from pybluehost.pts.btp.tester import BtpTester

logger = logging.getLogger(__name__)


class LeCoCService(BtpService):
    """LE Credit-Based Channel BTP service."""

    SERVICE_ID = op.SERVICE_L2CAP

    def __init__(self, *, actions: "IutActions", tester: "BtpTester") -> None:
        self._actions = actions
        self._tester = tester
        self._controller_index: int = 0
        # BTP chan_id (u8) → v1.0 channel object (whatever IutActions returns).
        self._channels: dict[int, object] = {}
        # Next chan_id to allocate when accepting/initiating a channel.
        self._next_chan_id: int = 1

    def _allocate_chan_id(self) -> int:
        cid = self._next_chan_id
        self._next_chan_id += 1
        return cid

    async def _handle_op_01(self, controller_index: int, data: bytes):
        """READ_SUPPORTED_COMMANDS — bitfield of supported L2CAP opcodes."""
        cmds = self.supported_commands()
        if not cmds:
            return op.BTP_STATUS_SUCCESS, bytes(0)
        n_bytes = (max(cmds) // 8) + 1
        out = bytearray(n_bytes)
        for code in cmds:
            bit_index = code - 1
            out[bit_index // 8] |= 1 << (bit_index % 8)
        return op.BTP_STATUS_SUCCESS, bytes(out)

    def _resolve_le_connection_handle(self, addr: bytes) -> int | None:
        """Look up an LE connection whose peer's 6-byte address matches `addr`."""
        try:
            session = self._actions.status()
        except Exception:
            return None
        target = bytes(addr)[:6]
        for h, info in session.connections.items():
            peer = getattr(info, "peer", None)
            if peer is None:
                continue
            raw = getattr(peer, "address", None) or getattr(peer, "bytes", None) or peer
            try:
                if bytes(raw)[:6] == target:
                    return h
            except Exception:
                continue
        return None

    async def _handle_op_02(self, controller_index: int, data: bytes):
        """L2CAP CONNECT (0x02) — body 13 bytes: addr_type(1) + addr(6) +
        PSM(u16 LE) + MTU(u16 LE) + Num(u8) + Options(u8).
        Response: Num(u8) + chan_ids(u8 × Num).
        """
        if len(data) != 13:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        psm = int.from_bytes(data[7:9], "little")
        mtu = int.from_bytes(data[9:11], "little")
        num = data[11]
        # options = data[12]  # ECFC modes etc. — P.8 v1 ignores
        if num != 1:
            logger.warning(
                "L2CAP CONNECT: Num=%d, only single-channel supported in P.8 v1", num,
            )
            return op.BTP_STATUS_FAILED, b""
        handle = self._resolve_le_connection_handle(addr)
        if handle is None:
            return op.BTP_STATUS_FAILED, b""
        stack = getattr(self._actions, "_stack", None)
        if stack is None or not hasattr(stack, "l2cap"):
            return op.BTP_STATUS_FAILED, b""
        try:
            ch = await stack.l2cap.connect_le_coc_channel(
                handle=handle, psm=psm,
                mtu=mtu or 512, mps=247, initial_credits=10, timeout=5.0,
            )
        except Exception:
            logger.exception("L2CAP CONNECT: connect_le_coc_channel raised")
            return op.BTP_STATUS_FAILED, b""
        chan_id = self._allocate_chan_id()
        self._channels[chan_id] = ch
        return op.BTP_STATUS_SUCCESS, bytes([1, chan_id & 0xFF])

    async def _handle_op_03(self, controller_index: int, data: bytes):
        """DISCONNECT — body: chan_id(u8)."""
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
        chan_id = data[0]
        ch = self._channels.get(chan_id)
        if ch is None:
            return op.BTP_STATUS_FAILED, b""
        stack = getattr(self._actions, "_stack", None)
        if stack is None or not hasattr(stack, "l2cap"):
            return op.BTP_STATUS_FAILED, b""
        try:
            await stack.l2cap.disconnect_le_coc_channel(ch)
        except Exception:
            logger.exception("L2CAP DISCONNECT: disconnect_le_coc_channel raised")
            return op.BTP_STATUS_FAILED, b""
        self._channels.pop(chan_id, None)
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_04(self, controller_index: int, data: bytes):
        """SEND_DATA — body: chan_id(u8) + data_len(u16 LE) + data."""
        if len(data) < 3:
            return op.BTP_STATUS_FAILED, b""
        chan_id = data[0]
        data_len = int.from_bytes(data[1:3], "little")
        if 3 + data_len != len(data):
            return op.BTP_STATUS_FAILED, b""
        payload = bytes(data[3:3 + data_len])
        ch = self._channels.get(chan_id)
        if ch is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            await ch.send(payload)
        except Exception:
            logger.exception("L2CAP SEND_DATA: ch.send raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    # ---- Listen (0x05) ---------------------------------------------------

    async def _handle_op_05(self, controller_index: int, data: bytes):
        """LISTEN — body: PSM(u16) + Transport(u8) + MTU(u16) + Security_Type(u8) + Key_Size(u8) + Response(u16). Min 9 bytes."""
        if len(data) < 9:
            return op.BTP_STATUS_FAILED, b""
        psm = int.from_bytes(data[0:2], "little")
        # Other fields ignored in P.8 v1.
        stack = getattr(self._actions, "_stack", None)
        if stack is None or not hasattr(stack, "l2cap"):
            return op.BTP_STATUS_FAILED, b""
        listen_fn = getattr(stack.l2cap, "listen_le_coc_channel", None)
        if listen_fn is None:
            return op.BTP_STATUS_FAILED, b""
        listen_fn(psm, self._make_incoming_handler(psm))
        return op.BTP_STATUS_SUCCESS, b""

    def _make_incoming_handler(self, psm: int):
        """Build a closure that captures the PSM for event emission."""
        def on_incoming(ch):
            self._handle_incoming_channel(ch, psm=psm)
        return on_incoming

    def _handle_incoming_channel(self, ch, *, psm: int) -> None:
        """Allocate BTP chan_id, wire data/close events, emit 0x81 Connected."""
        btp_chan_id = self._allocate_chan_id()
        self._channels[btp_chan_id] = ch

        # Wire per-channel events for Data Received / Disconnected emission.
        def on_data(data, _btp_id=btp_chan_id):
            self._emit_data_received(_btp_id, data)

        def on_close(reason, _btp_id=btp_chan_id, _psm=psm):
            self._emit_disconnected(_btp_id, _psm, reason)

        ch.set_events(SimpleChannelEvents(on_data=on_data, on_close=on_close))

        # Emit 0x81 Connected.
        # Per upstream: chan_id(1) + psm(2) + peer_mtu(2) + peer_mps(2) +
        # our_mtu(2) + our_mps(2) + addr_type(1) + addr(6) = 17 bytes.
        peer_mtu = getattr(ch, "mtu", 0)
        peer_mps = getattr(ch, "_mps", 0)
        our_mtu, our_mps = peer_mtu, peer_mps    # P.8 v1: we negotiated the min
        addr_type = 0
        addr = bytes(6)
        payload = (
            bytes([btp_chan_id])
            + psm.to_bytes(2, "little")
            + peer_mtu.to_bytes(2, "little")
            + peer_mps.to_bytes(2, "little")
            + our_mtu.to_bytes(2, "little")
            + our_mps.to_bytes(2, "little")
            + bytes([addr_type])
            + addr
        )
        self._emit_event(op.OP_L2CAP_EVENT_CONNECTED, payload)

    def _emit_data_received(self, btp_chan_id: int, data: bytes) -> None:
        # Payload: chan_id(1) + data_len(u16) + data
        payload = bytes([btp_chan_id]) + len(data).to_bytes(2, "little") + bytes(data)
        self._emit_event(op.OP_L2CAP_EVENT_DATA_RECEIVED, payload)

    def _emit_disconnected(self, btp_chan_id: int, psm: int, reason: int) -> None:
        # Payload: result(u16) + chan_id(1) + psm(u16) + addr_type(1) + addr(6) = 12 bytes
        payload = (
            (reason & 0xFFFF).to_bytes(2, "little")
            + bytes([btp_chan_id])
            + psm.to_bytes(2, "little")
            + bytes([0])    # addr_type placeholder
            + bytes(6)      # addr placeholder
        )
        self._emit_event(op.OP_L2CAP_EVENT_DISCONNECTED, payload)
        self._channels.pop(btp_chan_id, None)

    def _emit_event(self, opcode: int, payload: bytes) -> None:
        if self._tester is None:
            return
        frame = BtpFrame(
            service=op.SERVICE_L2CAP, opcode=opcode,
            controller_index=self._controller_index, data=payload,
        )
        try:
            asyncio.create_task(self._tester.emit_event(frame))
        except RuntimeError:
            logger.exception("L2CAP event %#x: no event loop; dropping", opcode)
