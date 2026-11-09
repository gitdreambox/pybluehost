"""RFCOMM — serial port emulation over L2CAP (TS 07.10 adaptation)."""
from __future__ import annotations

import asyncio
import logging
import struct
from collections import deque
from dataclasses import dataclass
from enum import IntEnum

from pybluehost.l2cap.channel import SimpleChannelEvents
from pybluehost.l2cap.constants import PSM_RFCOMM

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifecycle log helpers
# ---------------------------------------------------------------------------

def _log_channel_opened(*, dlci: int, channel: int, mtu: int) -> None:
    """Log INFO when an RFCOMM DLC has been successfully opened."""
    logger.info("RFCOMM DLCI=0x%02X (channel %d) opened MTU=%d", dlci, channel, mtu)


def _log_channel_closed(*, dlci: int) -> None:
    """Log INFO when an RFCOMM DLC has been gracefully closed."""
    logger.info("RFCOMM DLCI=0x%02X closed", dlci)


def _log_channel_disconnect_abnormal(*, dlci: int, reason: str) -> None:
    """Log WARN when an RFCOMM DLC disconnects abnormally."""
    logger.warning("RFCOMM DLCI=0x%02X abnormal disconnect: %s", dlci, reason)


# ---------------------------------------------------------------------------
# RFCOMM Frame Types
# ---------------------------------------------------------------------------

class RFCOMMFrameType(IntEnum):
    SABM = 0x2F  # Set Asynchronous Balanced Mode
    UA = 0x63    # Unnumbered Acknowledgment (without P/F bit)
    DM = 0x0F    # Disconnected Mode
    DISC = 0x43  # Disconnect (without P/F bit)
    UIH = 0xEF   # Unnumbered Information with Header check
    UI = 0x03    # Unnumbered Information


_MCC_TYPE_PN_COMMAND = 0x83
_MCC_TYPE_PN_RESPONSE = 0x81
_MCC_TYPE_MSC_COMMAND = 0xE3
_MCC_TYPE_MSC_RESPONSE = 0xE1
_MCC_TYPE_TEST_COMMAND = 0x23
_MCC_TYPE_TEST_RESPONSE = 0x21
_MCC_TYPE_RPN_COMMAND = 0x93
_MCC_TYPE_RPN_RESPONSE = 0x91
_MCC_TYPE_RLS_COMMAND = 0x53
_MCC_TYPE_RLS_RESPONSE = 0x51
_MCC_TYPE_NSC_RESPONSE = 0x11


# ---------------------------------------------------------------------------
# FCS (CRC-8) calculation per TS 07.10
# ---------------------------------------------------------------------------

# Precomputed CRC table for polynomial 0xE0 (reversed: x^8+x^2+x^1+x^0)
_CRC_TABLE = [0] * 256


def _init_crc_table() -> None:
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xE0
            else:
                crc >>= 1
        _CRC_TABLE[i] = crc


_init_crc_table()


def calc_fcs(data: bytes) -> int:
    """Calculate RFCOMM FCS (CRC-8) over the given bytes."""
    fcs = 0xFF
    for b in data:
        fcs = _CRC_TABLE[fcs ^ b]
    return 0xFF - fcs


def _check_fcs(data: bytes, received_fcs: int) -> bool:
    """Verify FCS: calc over data + received_fcs should give 0xCF."""
    fcs = 0xFF
    for b in data:
        fcs = _CRC_TABLE[fcs ^ b]
    fcs = _CRC_TABLE[fcs ^ received_fcs]
    return fcs == 0xCF


# ---------------------------------------------------------------------------
# RFCOMMFrame
# ---------------------------------------------------------------------------

@dataclass
class RFCOMMFrame:
    dlci: int
    frame_type: RFCOMMFrameType
    pf: bool  # Poll/Final bit
    data: bytes
    # C/R bit for the address byte. Only meaningful on DLCI 0 where it marks
    # the session direction (initiator=1, responder=0); other DLCIs follow the
    # TS 27.10 command/response table and stay 1 for our traffic.
    cr: int = 1


def encode_frame(frame: RFCOMMFrame) -> bytes:
    """Encode an RFCOMM frame to bytes."""
    # Address byte: EA(bit0, always 1) | C/R(bit1) | DLCI(bits 2-7).
    # C/R is direction-based for commands AND data UIH (TS 27.10 §5.2.1.2,
    # zephyr BT_RFCOMM_UIH_CR: initiator=1, acceptor=0); only UA/DM echo the
    # command's C/R. Callers set ``cr`` (default 1 = initiator command) —
    # channels driven by an acceptor session pass cr=0.
    cr = getattr(frame, "cr", 1)
    address = ((frame.dlci & 0x3F) << 2) | ((cr & 0x01) << 1) | 0x01

    # Control byte: frame type | P/F bit
    control = frame.frame_type & 0xEF  # strip P/F position
    if frame.pf:
        control |= 0x10  # P/F is bit 4

    # Length field
    length = len(frame.data)
    if length <= 127:
        length_field = bytes([(length << 1) | 0x01])  # EA=1
    else:
        # 2-byte length: first byte EA=0, second byte has high bits
        length_field = bytes([
            (length << 1) & 0xFE,           # low 7 bits, EA=0
            (length >> 7) & 0xFF,            # high 8 bits
        ])

    # FCS calculation:
    # For UIH: FCS over address + control only
    # For others: FCS over address + control + length
    if (frame.frame_type & 0xEF) == (RFCOMMFrameType.UIH & 0xEF):
        fcs_data = bytes([address, control])
    else:
        fcs_data = bytes([address, control]) + length_field
    fcs = calc_fcs(fcs_data)

    return bytes([address, control]) + length_field + frame.data + bytes([fcs])


def decode_frame(data: bytes) -> RFCOMMFrame:
    """Decode an RFCOMM frame from bytes."""
    address = data[0]
    control = data[1]

    # Parse address
    dlci = (address >> 2) & 0x3F

    # Parse control: extract P/F bit, then get frame type
    pf = bool(control & 0x10)
    frame_type_val = control & 0xEF  # mask out P/F bit
    frame_type = RFCOMMFrameType(frame_type_val)

    # Parse length
    offset = 2
    if data[offset] & 0x01:  # EA=1: single byte length
        length = data[offset] >> 1
        offset += 1
    else:  # EA=0: two byte length
        length = (data[offset] >> 1) | (data[offset + 1] << 7)
        offset += 2

    # Extract data
    payload = data[offset:offset + length]
    # FCS is last byte (skipped for verification in this basic decode)

    return RFCOMMFrame(dlci=dlci, frame_type=frame_type, pf=pf, data=payload)


# ---------------------------------------------------------------------------
# RFCOMMSession
# ---------------------------------------------------------------------------

class RFCOMMSession:
    """Manages an RFCOMM session over an L2CAP channel."""

    def __init__(
        self,
        l2cap_channel: object | None = None,
        server_handlers: dict[int, object] | None = None,
    ) -> None:
        self._l2cap_channel = l2cap_channel
        self._dlcs: dict[int, RFCOMMChannel] = {}
        self._ua_waiters: dict[int, asyncio.Future[None]] = {}
        # DLCI → initial TX credits the peer issued in its 9-byte PN command
        # (credit-based flow control); applied to the channel at SABM time.
        self._pending_credits: dict[int, int] = {}
        self._server_handlers = server_handlers or {}
        self._handler_tasks: set[asyncio.Task[object]] = set()
        # True once open() sends SABM(0) — the initiator. A session created by
        # the inbound-listen path (no open()) is the responder and must mark
        # its DLCI-0 frames C/R=0.
        self._initiator = False
        if l2cap_channel is not None and hasattr(l2cap_channel, "set_events"):
            l2cap_channel.set_events(SimpleChannelEvents(on_data=self._on_frame))

    async def open(self) -> None:
        """Open the multiplexer session (SABM on DLCI 0)."""
        self._initiator = True
        await self._send_sabm_and_wait_ua(dlci=0)

    async def open_dlc(self, server_channel: int) -> RFCOMMChannel:
        """Open a data link connection to a remote server channel.

        Initiator sequence (TS 27.10 §5.5.3 / zephyr parity): PN negotiation
        first, then SABM — a responder like PTS does not answer a bare SABM on
        an un-negotiated DLC (RFCOMM/DEVA cases stall waiting for UA)."""
        dlci = server_channel << 1  # initiator direction bit = 0
        if self._initiator:
            await self._send_pn_and_wait(dlci)
        await self._send_sabm_and_wait_ua(dlci=dlci)
        ch = RFCOMMChannel(dlci=dlci, session=self, max_frame_size=127)
        ch._tx_credits = self._pending_credits.pop(dlci, None)
        self._dlcs[dlci] = ch
        _log_channel_opened(dlci=dlci, channel=server_channel, mtu=ch.max_frame_size)
        return ch

    async def _send_pn_and_wait(self, dlci: int) -> None:
        """Send DLC Parameter Negotiation and wait for the PN response."""
        if self._l2cap_channel is None:
            raise NotImplementedError("RFCOMM PN requires an L2CAP-backed session")
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()
        self._ua_waiters[-(dlci + 1000)] = waiter  # PN waiter under a distinct key
        # PN body (§5.5.3 / zephyr rfcomm_send_pn): DLCI | flow 0xF0
        # (PN_CFC_CMD — propose credit flow, the TS BV-05 "CL=0x0F" shape) |
        # priority | ack_timer | frame_size(2 LE) | max_retrans | credits.
        # K=7 is the credit budget we issue the PEER for this DLC.
        body = bytes([dlci, 0xF0, 0x0F, 0x00]) + (127).to_bytes(2, "little") \
            + bytes([0x00, 0x07])
        mcc = bytes([_MCC_TYPE_PN_COMMAND, (len(body) << 1) | 0x01]) + body
        logger.debug("RFCOMM TX PN dlci=%d", dlci)
        await self._l2cap_channel.send(encode_frame(
            RFCOMMFrame(dlci=0, frame_type=RFCOMMFrameType.UIH, pf=False, data=mcc)))
        try:
            await asyncio.wait_for(waiter, timeout=5.0)
        finally:
            self._ua_waiters.pop(-(dlci + 1000), None)

    async def close(self) -> None:
        """Close the multiplexer session: DISC(DLCI 0) and await UA."""
        if self._l2cap_channel is not None:
            await self._send_disc_and_wait_ua(dlci=0)
        self._dlcs.clear()

    async def _send_disc_and_wait_ua(self, dlci: int) -> None:
        if self._l2cap_channel is None:
            raise NotImplementedError("RFCOMM close requires an L2CAP-backed session")
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()
        self._ua_waiters[dlci] = waiter
        frame = RFCOMMFrame(dlci=dlci, frame_type=RFCOMMFrameType.DISC, pf=True, data=b"")
        if dlci == 0 and not self._initiator:
            frame.cr = 0
        logger.debug("RFCOMM TX DISC dlci=%d", dlci)
        await self._l2cap_channel.send(encode_frame(frame))
        try:
            await asyncio.wait_for(waiter, timeout=5.0)
        except asyncio.TimeoutError:
            pass  # best effort: the peer may drop the ACL instead
        finally:
            self._ua_waiters.pop(dlci, None)

    async def _send_sabm_and_wait_ua(self, dlci: int) -> None:
        logger.debug("RFCOMM TX SABM dlci=%d", dlci)
        if self._l2cap_channel is None:
            raise NotImplementedError("RFCOMM multiplexer open requires Classic L2CAP dynamic channel support")
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()
        self._ua_waiters[dlci] = waiter
        await self._l2cap_channel.send(
            encode_frame(
                RFCOMMFrame(
                    dlci=dlci,
                    frame_type=RFCOMMFrameType.SABM,
                    pf=True,
                    data=b"",
                )
            )
        )
        try:
            await asyncio.wait_for(waiter, timeout=5.0)
        finally:
            self._ua_waiters.pop(dlci, None)

    async def _on_frame(self, data: bytes) -> None:
        frame = decode_frame(data)
        logger.debug("RFCOMM RX raw=%s dlci=%d type=%s pf=%s len=%d",
                     data.hex(), frame.dlci, frame.frame_type.name, frame.pf,
                     len(frame.data))
        if frame.frame_type == RFCOMMFrameType.UA:
            waiter = self._ua_waiters.get(frame.dlci)
            if waiter is not None and not waiter.done():
                waiter.set_result(None)
            return
        if frame.frame_type == RFCOMMFrameType.SABM:
            await self._send_ua(frame.dlci)
            if frame.dlci != 0 and frame.dlci not in self._dlcs:
                server_channel = frame.dlci >> 1
                handler = self._server_handlers.get(server_channel)
                if handler is not None:
                    channel = RFCOMMChannel(
                        dlci=frame.dlci,
                        session=self,
                        max_frame_size=127,
                    )
                    channel._tx_credits = self._pending_credits.pop(
                        frame.dlci, None)
                    self._dlcs[frame.dlci] = channel
                    _log_channel_opened(
                        dlci=frame.dlci,
                        channel=server_channel,
                        mtu=channel.max_frame_size,
                    )
                    result = handler(channel)
                    if asyncio.iscoroutine(result):
                        task = asyncio.create_task(result)
                        self._handler_tasks.add(task)
                        task.add_done_callback(self._handler_tasks.discard)
                        # Yield once so the handler's synchronous setup
                        # (e.g. channel.on_data(...)) runs before subsequent
                        # frames are dispatched to the channel.
                        await asyncio.sleep(0)
                    await self._send_modem_status(frame.dlci)
            return
        if frame.frame_type == RFCOMMFrameType.DISC:
            # Peer closes a DLC or the whole session (BV-03/BV-08): answer
            # UA (same C/R convention as the SABM answer) and forget the DLC.
            await self._send_ua(frame.dlci)
            ch = self._dlcs.pop(frame.dlci, None)
            if ch is not None:
                _log_channel_closed(dlci=frame.dlci)
            return
        if frame.frame_type == RFCOMMFrameType.UIH:
            if frame.dlci == 0:
                await self._handle_mcc(frame.data)
                return
            channel = self._dlcs.get(frame.dlci)
            if channel is not None:
                data = frame.data
                if frame.pf and data:
                    # Credit-issuing UIH (TS 07.10 §6.5): first byte is the
                    # credit count granted to US; the rest is user data.
                    channel._add_tx_credits(data[0])
                    data = data[1:]
                if data:
                    await channel._on_data(data)
                    if channel._tx_credits is not None:
                        # Credit mode: return one credit per consumed frame
                        # so the peer's budget never runs dry (zephyr's
                        # recv-complete top-up).
                        await channel.grant_credits(1)
                elif not frame.pf:
                    await channel._on_data(data)

    async def _send_ua(self, dlci: int) -> None:
        if self._l2cap_channel is None:
            return
        # TS 27.10 §5.4.3.1: a response to the initiator's command carries the
        # SAME C/R as the command — the responder's UA(0) uses C/R=1 (addr
        # 0x03), identical to the SABM it answers. (C/R=0 on DLCI 0 marks
        # responder-originated COMMANDS, not responses.)
        frame = RFCOMMFrame(
            dlci=dlci, frame_type=RFCOMMFrameType.UA, pf=True, data=b"",
        )
        encoded = encode_frame(frame)
        logger.debug("RFCOMM TX UA dlci=%d bytes=%s", dlci, encoded.hex())
        await self._l2cap_channel.send(encoded)

    async def _handle_mcc(self, data: bytes) -> None:
        if self._l2cap_channel is None or len(data) < 2:
            return
        command_type = data[0]
        length_field = data[1]
        if command_type == _MCC_TYPE_PN_COMMAND:
            response_type = _MCC_TYPE_PN_RESPONSE
        elif command_type == _MCC_TYPE_MSC_COMMAND:
            response_type = _MCC_TYPE_MSC_RESPONSE
        elif command_type == _MCC_TYPE_TEST_COMMAND:
            # Test command: echo the payload back in a Test response
            # (BV-04's MMI says "respond PN" but the peer actually sends
            # TEST with a random payload — dropping it stalls the case).
            response_type = _MCC_TYPE_TEST_RESPONSE
        elif command_type == _MCC_TYPE_RPN_COMMAND:
            response_type = _MCC_TYPE_RPN_RESPONSE
        elif command_type == _MCC_TYPE_RLS_COMMAND:
            response_type = _MCC_TYPE_RLS_RESPONSE
        elif command_type == _MCC_TYPE_PN_RESPONSE:
            # Answer to OUR initiator PN — resolve the pending negotiation;
            # if the peer accepted credit flow (PN_CFC_RESP=0xE0) its K
            # (body byte 8) is our TX credit budget for the DLC.
            length = length_field >> 1
            payload = data[2:2 + length]
            if len(payload) >= 8 and payload[1] == 0xE0:
                self._pending_credits[payload[0]] = payload[7]
            if payload:
                waiter = self._ua_waiters.pop(-(payload[0] + 1000), None)
                if waiter is not None and not waiter.done():
                    waiter.set_result(None)
            return
        elif command_type in (_MCC_TYPE_MSC_RESPONSE, _MCC_TYPE_RPN_RESPONSE,
                              _MCC_TYPE_RLS_RESPONSE, _MCC_TYPE_TEST_RESPONSE,
                              _MCC_TYPE_NSC_RESPONSE):
            # Responses to OUR commands — consume silently. NSC-ing a response
            # (e.g. the MSC response PTS sends to our MSC) corrupts the case.
            return
        else:
            # Unknown/unsupported MCC command — TS 07.10 §5.4.6.3.9 requires
            # a Non-Supported Command response carrying the offending type
            # (RFCOMM/DEVA-DEVB/RFC/BV-25 checks exactly this).
            await self._send_nsc(command_type)
            return
        length = length_field >> 1
        payload = data[2:2 + length]
        if len(payload) != length:
            return
        # Our own pending PN (initiator) is answered by the PN response —
        # resolve its waiter.
        if command_type == _MCC_TYPE_PN_COMMAND and payload:
            waiter = self._ua_waiters.pop(-(payload[0] + 1000), None)
            if waiter is not None and not waiter.done():
                waiter.set_result(None)
                return  # negotiated: accept the peer's parameters as-is
        if command_type == _MCC_TYPE_RPN_COMMAND and len(payload) == 1:
            # RPN "request for current port values" (TS 07.10 §5.4.6.3.2 —
            # only the DLCI byte present) must be answered with our full
            # current settings, not an echo (RFCOMM/DEVA-DEVB/RFC/BV-19).
            dlci = payload[0]
            mask = 0x3EFF  # all parameter bits valid, bit 8 (reserved) = 0
            payload = (bytes([dlci, 0x07, 0x03, 0x00, 0x11, 0x13])
                       + mask.to_bytes(2, "little"))
            length_field = (len(payload) << 1) | 0x01
        if command_type == _MCC_TYPE_PN_COMMAND and len(payload) >= 8 \
                and payload[1] == 0xF0:
            # Peer proposes credit-based flow control (TS 07.10 §6.5,
            # PN_CFC_CMD=0xF0). zephyr parity: accept — respond PN_CFC_RESP
            # (0xE0, the TS BV-15 "CL-bits=0x0E" value), priority/ack/retrans
            # 0, frame size min(peer,127), and issue our own K=7 credits in
            # body byte 8. The peer's K (byte 8 of the request) becomes our
            # TX credit budget for the DLC (BV-21/22).
            dlci = payload[0]
            frame_size = min(int.from_bytes(payload[4:6], "little") or 127, 127)
            self._pending_credits[dlci] = payload[7]
            payload = (bytes([dlci, 0xE0, 0x00, 0x00])
                       + frame_size.to_bytes(2, "little")
                       + bytes([0x00, 0x07]))
        elif command_type == _MCC_TYPE_PN_COMMAND and len(payload) >= 8:
            # PN RESPONSE without credit — byte shape PTS itself uses when
            # answering OUR PN (captured on air during RFCOMM/DEVA/RFC/BV-05):
            # flow 0x00, priority 0x0F, ack 0x00, frame size min(peer,127),
            # retry/window 0. A C/R=1 address or 0xE0/0xF0 echo stalls it.
            dlci = payload[0]
            frame_size = min(int.from_bytes(payload[4:6], "little") or 127, 127)
            payload = (bytes([dlci, 0x00, 0x0F, 0x00])
                       + frame_size.to_bytes(2, "little")
                       + bytes([0x00, 0x00]))
        echo_frame = RFCOMMFrame(
            dlci=0,
            frame_type=RFCOMMFrameType.UIH,
            pf=False,
            data=bytes([response_type, length_field]) + payload,
        )
        # MCC responses ride the DLCI-0 UIH with the address C/R bit CLEAR
        # (response direction) — mirrored from PTS's own PN-RSP on air.
        if not self._initiator:
            echo_frame.cr = 0
        echo = encode_frame(echo_frame)
        logger.debug("RFCOMM TX MCC rsp type=0x%02x bytes=%s",
                     response_type, echo.hex())
        await self._l2cap_channel.send(echo)

    async def _send_modem_status(self, dlci: int) -> None:
        if self._l2cap_channel is None:
            return
        msc_frame = RFCOMMFrame(
            dlci=0,
            frame_type=RFCOMMFrameType.UIH,
            pf=False,
            # Responder-originated MCC COMMANDS on DLCI 0 use the response
            # direction (C/R=0) — same address rule as MCC responses.
            data=bytes([
                _MCC_TYPE_MSC_COMMAND,
                0x05,  # EA=1, payload length=2
                ((dlci & 0x3F) << 2) | 0x03,
                0x8D,  # EA + RTC + RTR + DV
            ]),
        )
        if not self._initiator:
            msc_frame.cr = 0
        encoded = encode_frame(msc_frame)
        logger.debug("RFCOMM TX MSC dlci=%d bytes=%s", dlci, encoded.hex())
        await self._l2cap_channel.send(encoded)

    async def send_rls(self, dlci: int, line_status: int) -> None:
        """Remote Line Status command (TS 07.10 §5.4.6.3.7).

        ``line_status`` is the raw status byte; BTP's encoding already sets
        the L bit with the error code (framing=0x09, parity=0x05,
        overrun=0x03, no-error=0x00)."""
        if self._l2cap_channel is None:
            return
        payload = bytes([((dlci & 0x3F) << 2) | 0x03, line_status & 0xFF])
        frame = RFCOMMFrame(
            dlci=0,
            frame_type=RFCOMMFrameType.UIH,
            pf=False,
            data=bytes([_MCC_TYPE_RLS_COMMAND, (len(payload) << 1) | 0x01])
            + payload,
        )
        if not self._initiator:
            frame.cr = 0
        encoded = encode_frame(frame)
        logger.debug("RFCOMM TX RLS dlci=%d status=0x%02x bytes=%s",
                     dlci, line_status, encoded.hex())
        await self._l2cap_channel.send(encoded)

    async def send_rpn(
        self,
        dlci: int,
        baud_rate: int = 0,
        line_settings: int = 0,
        flow_control: int = 0,
        xon_char: int = 0,
        xoff_char: int = 0,
        param_mask: int = 0,
    ) -> None:
        """Remote Port Negotiation command (TS 07.10 §5.4.6.3.2)."""
        if self._l2cap_channel is None:
            return
        payload = (bytes([
            ((dlci & 0x3F) << 2) | 0x03,
            baud_rate & 0xFF,
            line_settings & 0xFF,
            flow_control & 0xFF,
            xon_char & 0xFF,
            xoff_char & 0xFF,
        ]) + (param_mask & 0xFFFF).to_bytes(2, "little"))
        frame = RFCOMMFrame(
            dlci=0,
            frame_type=RFCOMMFrameType.UIH,
            pf=False,
            data=bytes([_MCC_TYPE_RPN_COMMAND, (len(payload) << 1) | 0x01])
            + payload,
        )
        if not self._initiator:
            frame.cr = 0
        encoded = encode_frame(frame)
        logger.debug("RFCOMM TX RPN dlci=%d bytes=%s", dlci, encoded.hex())
        await self._l2cap_channel.send(encoded)

    async def _send_nsc(self, command_type: int) -> None:
        """Non-Supported Command response (TS 07.10 §5.4.6.3.9) — carries
        the unsupported command's type byte as its only payload byte."""
        if self._l2cap_channel is None:
            return
        frame = RFCOMMFrame(
            dlci=0,
            frame_type=RFCOMMFrameType.UIH,
            pf=False,
            data=bytes([_MCC_TYPE_NSC_RESPONSE, 0x03, command_type]),
        )
        if not self._initiator:
            frame.cr = 0
        encoded = encode_frame(frame)
        logger.debug("RFCOMM TX NSC for type=0x%02x bytes=%s",
                     command_type, encoded.hex())
        await self._l2cap_channel.send(encoded)


# ---------------------------------------------------------------------------
# RFCOMMChannel
# ---------------------------------------------------------------------------

class RFCOMMChannel:
    """A single RFCOMM data link connection (DLC)."""

    def __init__(
        self,
        dlci: int,
        session: RFCOMMSession | None,
        max_frame_size: int = 127,
    ) -> None:
        self._dlci = dlci
        self._session = session
        self._max_frame_size = max_frame_size
        self._data_handler: object | None = None
        # Credit-based flow control (TS 07.10 §6.5): None = basic mode
        # (unlimited); an int = frames we may still send before the peer
        # issues more credits via a P/F=1 UIH.
        self._tx_credits: int | None = None
        self._credit_event: asyncio.Event | None = None
        # Credit-mode TX queue: send() enqueues and returns immediately; a
        # single drainer task emits frames as credits allow (PTS's BV-21
        # top-up can arrive tens of seconds after we stop — blocking the
        # BTP command on credit wait would time the case out first).
        self._tx_queue: deque[bytes] = deque()
        self._tx_task: asyncio.Task[None] | None = None

    def _cr(self) -> int:
        """Address C/R for frames we ORIGINATE on this DLC: direction-based
        (initiator session=1, acceptor=0) — zephyr BT_RFCOMM_UIH_CR."""
        return 1 if self._session is None or self._session._initiator else 0

    def _add_tx_credits(self, k: int) -> None:
        if self._tx_credits is None:
            self._tx_credits = 0
        self._tx_credits += k
        if self._credit_event is not None and self._tx_credits > 0:
            self._credit_event.set()

    async def _drain_tx_queue(self) -> None:
        if self._session is None or self._session._l2cap_channel is None:
            return
        if self._credit_event is None:
            self._credit_event = asyncio.Event()
        try:
            while self._tx_queue:
                while self._tx_credits is not None and self._tx_credits <= 0:
                    self._credit_event.clear()
                    await self._credit_event.wait()
                data = self._tx_queue.popleft()
                if self._tx_credits is not None:
                    self._tx_credits -= 1
                frame = RFCOMMFrame(
                    dlci=self._dlci,
                    frame_type=RFCOMMFrameType.UIH,
                    pf=False,
                    data=data,
                    cr=self._cr(),
                )
                logger.debug(
                    "RFCOMM TX data dlci=%d len=%d credits_left=%s",
                    self._dlci, len(data), self._tx_credits)
                await self._session._l2cap_channel.send(encode_frame(frame))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("RFCOMM DLCI=%d TX drain failed", self._dlci)
        finally:
            self._tx_task = None

    @property
    def dlci(self) -> int:
        return self._dlci

    @property
    def server_channel(self) -> int:
        return self._dlci >> 1

    @property
    def max_frame_size(self) -> int:
        return self._max_frame_size

    async def send(self, data: bytes) -> None:
        """Send data over this DLC, segmenting by max_frame_size.

        Credit mode (TS 07.10 §6.5): segments are queued and a drainer
        emits them as credits allow — exactly K frames go out, then it
        stops until the peer's credit-issuing UIH arrives (BV-21/22).
        Basic mode: frames go out inline."""
        if self._session is None or self._session._l2cap_channel is None:
            raise NotImplementedError("RFCOMM send requires an open L2CAP-backed session")
        segments = [data[offset:offset + self._max_frame_size]
                    for offset in range(0, len(data), self._max_frame_size)]
        if self._tx_credits is not None:
            self._tx_queue.extend(segments)
            if self._tx_task is None or self._tx_task.done():
                self._tx_task = asyncio.create_task(self._drain_tx_queue())
            return
        for segment in segments:
            frame = RFCOMMFrame(
                dlci=self._dlci,
                frame_type=RFCOMMFrameType.UIH,
                pf=False,
                data=segment,
                cr=self._cr(),
            )
            await self._session._l2cap_channel.send(encode_frame(frame))

    async def grant_credits(self, k: int) -> None:
        """Issue K credits to the peer: UIH on this DLC with P/F=1 and the
        credit byte, no user payload (TS 07.10 §6.5)."""
        if self._session is None or self._session._l2cap_channel is None:
            return
        frame = RFCOMMFrame(
            dlci=self._dlci,
            frame_type=RFCOMMFrameType.UIH,
            pf=True,
            data=bytes([k & 0xFF]),
            cr=self._cr(),
        )
        await self._session._l2cap_channel.send(encode_frame(frame))

    async def close(self) -> None:
        """Close this DLC (send DISC)."""
        if self._session is None or self._session._l2cap_channel is None:
            raise NotImplementedError("RFCOMM close requires an open L2CAP-backed session")
        frame = RFCOMMFrame(dlci=self._dlci, frame_type=RFCOMMFrameType.DISC,
                            pf=True, data=b"", cr=self._cr())
        await self._session._l2cap_channel.send(encode_frame(frame))
        _log_channel_closed(dlci=self._dlci)

    def on_data(self, handler: object) -> None:
        self._data_handler = handler

    async def _on_data(self, data: bytes) -> None:
        if self._data_handler is None:
            return
        result = self._data_handler(data)  # type: ignore[operator]
        if asyncio.iscoroutine(result):
            await result


# ---------------------------------------------------------------------------
# RFCOMMManager
# ---------------------------------------------------------------------------

class RFCOMMManager:
    """High-level RFCOMM connection manager."""

    def __init__(self, l2cap: object | None = None) -> None:
        self._l2cap = l2cap
        self._sessions: dict[int, RFCOMMSession] = {}  # handle -> session
        self._listeners: dict[int, object] = {}

    async def connect(self, acl_handle: int, server_channel: int) -> RFCOMMChannel:
        """Connect to a remote RFCOMM server channel."""
        if self._l2cap is None or not hasattr(self._l2cap, "connect_classic_channel"):
            raise NotImplementedError("Requires L2CAP connection")
        l2cap_channel = await self._l2cap.connect_classic_channel(acl_handle, PSM_RFCOMM)
        session = RFCOMMSession(l2cap_channel)
        await session.open()
        channel = await session.open_dlc(server_channel)
        self._sessions[acl_handle] = session
        return channel

    async def listen(self, server_channel: int, handler: object) -> None:
        """Register a handler for incoming connections on a server channel."""
        if self._l2cap is None or not hasattr(self._l2cap, "listen_classic_channel"):
            raise NotImplementedError("RFCOMM listen requires Classic L2CAP PSM 0x0003 support")
        self._listeners[server_channel] = handler

        async def on_l2cap_channel(channel: object) -> None:
            session = RFCOMMSession(channel, server_handlers=self._listeners)
            self._sessions[getattr(channel, "connection_handle", id(channel))] = session

        self._l2cap.listen_classic_channel(PSM_RFCOMM, on_l2cap_channel)
