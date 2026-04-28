"""RFCOMM — serial port emulation over L2CAP (TS 07.10 adaptation)."""
from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass
from enum import IntEnum

from pybluehost.l2cap.channel import SimpleChannelEvents
from pybluehost.l2cap.constants import PSM_RFCOMM


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


def encode_frame(frame: RFCOMMFrame) -> bytes:
    """Encode an RFCOMM frame to bytes."""
    # Address byte: EA(1) | C/R(1) | DLCI(6)
    # EA=1 (always for single-byte address), C/R=1 (initiator command)
    address = ((frame.dlci & 0x3F) << 2) | 0x03  # EA=1, C/R=1

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
        self._server_handlers = server_handlers or {}
        self._handler_tasks: set[asyncio.Task[object]] = set()
        if l2cap_channel is not None and hasattr(l2cap_channel, "set_events"):
            l2cap_channel.set_events(SimpleChannelEvents(on_data=self._on_frame))

    async def open(self) -> None:
        """Open the multiplexer session (SABM on DLCI 0)."""
        await self._send_sabm_and_wait_ua(dlci=0)

    async def open_dlc(self, server_channel: int) -> RFCOMMChannel:
        """Open a data link connection to a remote server channel."""
        dlci = server_channel << 1  # initiator direction bit = 0
        await self._send_sabm_and_wait_ua(dlci=dlci)
        ch = RFCOMMChannel(dlci=dlci, session=self, max_frame_size=127)
        self._dlcs[dlci] = ch
        return ch

    async def close(self) -> None:
        """Close the multiplexer session."""
        self._dlcs.clear()

    async def _send_sabm_and_wait_ua(self, dlci: int) -> None:
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
                    self._dlcs[frame.dlci] = channel
                    result = handler(channel)
                    if asyncio.iscoroutine(result):
                        task = asyncio.create_task(result)
                        self._handler_tasks.add(task)
                        task.add_done_callback(self._handler_tasks.discard)
                    await self._send_modem_status(frame.dlci)
            return
        if frame.frame_type == RFCOMMFrameType.UIH:
            if frame.dlci == 0:
                await self._handle_mcc(frame.data)
                return
            channel = self._dlcs.get(frame.dlci)
            if channel is not None:
                await channel._on_data(frame.data)

    async def _send_ua(self, dlci: int) -> None:
        if self._l2cap_channel is None:
            return
        await self._l2cap_channel.send(
            encode_frame(
                RFCOMMFrame(
                    dlci=dlci,
                    frame_type=RFCOMMFrameType.UA,
                    pf=True,
                    data=b"",
                )
            )
        )

    async def _handle_mcc(self, data: bytes) -> None:
        if self._l2cap_channel is None or len(data) < 2:
            return
        command_type = data[0]
        length_field = data[1]
        if command_type == _MCC_TYPE_PN_COMMAND:
            response_type = _MCC_TYPE_PN_RESPONSE
        elif command_type == _MCC_TYPE_MSC_COMMAND:
            response_type = _MCC_TYPE_MSC_RESPONSE
        else:
            return
        length = length_field >> 1
        payload = data[2:2 + length]
        if len(payload) != length:
            return
        await self._l2cap_channel.send(
            encode_frame(
                RFCOMMFrame(
                    dlci=0,
                    frame_type=RFCOMMFrameType.UIH,
                    pf=False,
                    data=bytes([response_type, length_field]) + payload,
                )
            )
        )

    async def _send_modem_status(self, dlci: int) -> None:
        if self._l2cap_channel is None:
            return
        await self._l2cap_channel.send(
            encode_frame(
                RFCOMMFrame(
                    dlci=0,
                    frame_type=RFCOMMFrameType.UIH,
                    pf=False,
                    data=bytes([
                        _MCC_TYPE_MSC_COMMAND,
                        0x05,  # EA=1, payload length=2
                        ((dlci & 0x3F) << 2) | 0x03,
                        0x8D,  # EA + RTC + RTR + DV
                    ]),
                )
            )
        )


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
        """Send data over this DLC, segmenting by max_frame_size."""
        if self._session is None or self._session._l2cap_channel is None:
            raise NotImplementedError("RFCOMM send requires an open L2CAP-backed session")
        for offset in range(0, len(data), self._max_frame_size):
            frame = RFCOMMFrame(
                dlci=self._dlci,
                frame_type=RFCOMMFrameType.UIH,
                pf=False,
                data=data[offset:offset + self._max_frame_size],
            )
            await self._session._l2cap_channel.send(encode_frame(frame))

    async def close(self) -> None:
        """Close this DLC (send DISC)."""
        if self._session is None or self._session._l2cap_channel is None:
            raise NotImplementedError("RFCOMM close requires an open L2CAP-backed session")
        frame = RFCOMMFrame(dlci=self._dlci, frame_type=RFCOMMFrameType.DISC, pf=True, data=b"")
        await self._session._l2cap_channel.send(encode_frame(frame))

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
