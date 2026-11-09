"""RFCOMM BTP service (doc/btp_rfcomm.txt) — DLC connect/data/listen ops.

auto-pts drives RFCOMM/DEVA/DEVB cases through these commands over the
case's Classic ACL. Connection/data lifecycle events (0x80/0x81/0x82) flow
back so auto-pts's stack.rfcomm model tracks DLC state for the WID handlers.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import BtpFrame
from pybluehost.pts.btp.services.base import BtpService

if TYPE_CHECKING:
    from pybluehost.pts.actions import IutActions
    from pybluehost.pts.btp.tester import BtpTester

logger = logging.getLogger(__name__)


class RfcommService(BtpService):
    """BR/EDR RFCOMM BTP service."""

    SERVICE_ID = op.SERVICE_RFCOMM

    def __init__(self, *, actions: "IutActions", tester: "BtpTester") -> None:
        self._actions = actions
        self._tester = tester

    def _emit(self, opcode: int, payload: bytes) -> None:
        frame = BtpFrame(service=self.SERVICE_ID, opcode=opcode,
                         controller_index=0, data=payload)
        try:
            import asyncio
            asyncio.create_task(self._tester.emit_event(frame))
        except Exception:
            logger.exception("RFCOMM event emit failed")

    async def _handle_op_01(self, controller_index: int, data: bytes):
        """READ_SUPPORTED_COMMANDS — bitfield of supported RFCOMM opcodes."""
        cmds = self.supported_commands()
        if not cmds:
            return op.BTP_STATUS_SUCCESS, bytes(0)
        n_bytes = (max(cmds) // 8) + 1
        out = bytearray(n_bytes)
        for code in cmds:
            out[code // 8] |= 1 << (code % 8)
        return op.BTP_STATUS_SUCCESS, bytes(out)

    async def _handle_op_02(self, controller_index: int, data: bytes):
        """CONNECT — body: addr_type(1)+addr(6)+channel(1).

        Opens (or reuses) the Classic ACL and establishes the DLC; the
        Connected event (0x80) carries the negotiated MTU. Channel 0 means
        "session only" (RFCOMM/DEVA/RFC/BV-01 initialises just the
        multiplexer — SABM(0)↔UA — and PTS drops the link on an un-invited
        DLC negotiation).
        """
        if len(data) < 8:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        channel = data[7]
        if channel == 0:
            try:
                await self._actions.rfcomm_session_only(addr)
            except Exception:
                logger.exception("RFCOMM CONNECT (session-only) raised")
                return op.BTP_STATUS_FAILED, b""
            return op.BTP_STATUS_SUCCESS, b""
        try:
            ch, mtu = await self._actions.rfcomm_connect(addr, channel)
        except Exception:
            logger.exception("RFCOMM CONNECT raised")
            return op.BTP_STATUS_FAILED, b""
        payload = bytes([data[0]]) + addr + bytes([channel]) + \
            int(mtu).to_bytes(2, "little")
        self._emit(op.OP_RFCOMM_EVENT_CONNECTED, payload)
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_03(self, controller_index: int, data: bytes):
        """DISCONNECT — body: addr_type(1)+addr(6)+channel(1)."""
        if len(data) < 8:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        channel = data[7]
        try:
            if channel == 0:
                # Session shutdown (BV-04 WID 14 "close the DLC" after the
                # peer already released it): DISC on the control channel.
                await self._actions.rfcomm_close_session(addr)
            else:
                await self._actions.rfcomm_disconnect(addr, channel)
        except Exception:
            logger.exception("RFCOMM DISCONNECT raised")
            return op.BTP_STATUS_FAILED, b""
        payload = bytes([data[0]]) + addr + bytes([channel])
        self._emit(op.OP_RFCOMM_EVENT_DISCONNECTED, payload)
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_04(self, controller_index: int, data: bytes):
        """SEND_DATA — body: addr_type(1)+addr(6)+channel(1)+len(2)+data."""
        if len(data) < 10:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        channel = data[7]
        data_len = int.from_bytes(data[8:10], "little")
        value = bytes(data[10:10 + data_len])
        try:
            await self._actions.rfcomm_send(addr, channel, value)
        except Exception:
            logger.exception("RFCOMM SEND_DATA raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_05(self, controller_index: int, data: bytes):
        """LISTEN — body: channel(1). Register a server channel; incoming DLCs
        emit the Connected event and their data emits Data Received."""
        if len(data) < 1:
            return op.BTP_STATUS_FAILED, b""
        channel = data[0]
        try:
            await self._actions.rfcomm_listen(channel)
        except Exception:
            logger.exception("RFCOMM LISTEN raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_06(self, controller_index: int, data: bytes):
        """SEND_RPN — body: addr_type(1)+addr(6)+channel(1)+baud_rate(1)+
        line_settings(1)+flow_control(1)+xon(1)+xoff(1)+param_mask(2).
        Sends a real RPN MCC command on the DLC's session (BV-17/19)."""
        if len(data) < 14:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        channel = data[7]
        try:
            await self._actions.rfcomm_send_rpn(
                addr, channel, baud_rate=data[8], line_settings=data[9],
                flow_control=data[10], xon_char=data[11], xoff_char=data[12],
                param_mask=int.from_bytes(data[13:15], "little"))
        except Exception:
            logger.exception("RFCOMM SEND_RPN raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_07(self, controller_index: int, data: bytes):
        """GET_DLC_INFO — body: addr_type(1)+addr(6)+channel(1).
        Response: MTU(2)+state(1)."""
        if len(data) < 8:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        channel = data[7]
        try:
            mtu, state = await self._actions.rfcomm_dlc_info(addr, channel)
        except Exception:
            logger.exception("RFCOMM GET_DLC_INFO raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, \
            int(mtu).to_bytes(2, "little") + bytes([state])

    async def _handle_op_08(self, controller_index: int, data: bytes):
        """SEND_RLS — body: addr_type(1)+addr(6)+channel(1)+line_status(1).
        Sends a real RLS MCC command (BV-14 WID 23 Framing Error)."""
        if len(data) < 9:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        channel = data[7]
        try:
            await self._actions.rfcomm_send_rls(addr, channel, data[8])
        except Exception:
            logger.exception("RFCOMM SEND_RLS raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    # -- event plumbing from the actions layer ---------------------------------

    def on_incoming_connected(self, addr_le: bytes, addr_type: int,
                              channel: int, mtu: int) -> None:
        payload = bytes([addr_type]) + addr_le + bytes([channel]) + \
            int(mtu).to_bytes(2, "little")
        self._emit(op.OP_RFCOMM_EVENT_CONNECTED, payload)

    def on_incoming_disconnected(self, addr_le: bytes, addr_type: int,
                                 channel: int) -> None:
        payload = bytes([addr_type]) + addr_le + bytes([channel])
        self._emit(op.OP_RFCOMM_EVENT_DISCONNECTED, payload)

    def on_data_received(self, addr_le: bytes, addr_type: int,
                         channel: int, value: bytes) -> None:
        payload = bytes([addr_type]) + addr_le + bytes([channel]) + \
            len(value).to_bytes(2, "little") + value
        self._emit(op.OP_RFCOMM_EVENT_DATA_RECEIVED, payload)
