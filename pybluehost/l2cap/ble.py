"""BLE L2CAP channels: FixedChannel and LECoCChannel."""
from __future__ import annotations

import asyncio
import inspect
import struct

from pybluehost.hci.constants import ACL_PB_FIRST_AUTO_FLUSH
from pybluehost.l2cap.channel import (
    Channel,
    ChannelEvents,
    ChannelState,
    SimpleChannelEvents,
)


async def _invoke(cb: object, *args: object) -> None:
    """Call a callback that may be sync or async."""
    if cb is None:
        return
    result = cb(*args)  # type: ignore[operator]
    if inspect.isawaitable(result):
        await result


class FixedChannel(Channel):
    """A fixed L2CAP channel (always OPEN, no state machine)."""

    def __init__(
        self,
        connection_handle: int,
        cid: int,
        hci: object,
        mtu: int = 23,
    ) -> None:
        self._connection_handle = connection_handle
        self._cid = cid
        self._hci = hci
        self._mtu = mtu
        self._state = ChannelState.OPEN
        self._events: ChannelEvents | SimpleChannelEvents | None = None

    # -- properties ----------------------------------------------------------

    @property
    def cid(self) -> int:
        return self._cid

    @property
    def connection_handle(self) -> int:
        return self._connection_handle

    @property
    def state(self) -> ChannelState:
        return self._state

    @property
    def mtu(self) -> int:
        return self._mtu

    # -- public API ----------------------------------------------------------

    async def send(self, data: bytes) -> None:
        l2cap_pdu = struct.pack("<HH", len(data), self._cid) + data
        await self._hci.send_acl_data(  # type: ignore[union-attr]
            self._connection_handle, ACL_PB_FIRST_AUTO_FLUSH, l2cap_pdu
        )

    async def close(self) -> None:
        # Fixed channels cannot be truly closed; mark CLOSED for bookkeeping.
        self._state = ChannelState.CLOSED

    def set_events(self, events: ChannelEvents | SimpleChannelEvents) -> None:
        self._events = events

    async def _on_pdu(self, data: bytes) -> None:
        if self._events is not None:
            await _invoke(self._events.on_data, data)


class LECoCChannel(Channel):
    """LE Credit-Based Connection-Oriented Channel."""

    def __init__(
        self,
        connection_handle: int,
        local_cid: int,
        peer_cid: int,
        hci: object,
        mtu: int = 512,
        mps: int = 247,
        initial_credits: int = 10,
    ) -> None:
        self._connection_handle = connection_handle
        self._local_cid = local_cid
        self._peer_cid = peer_cid
        self._hci = hci
        self._mtu = mtu
        self._mps = mps
        self._tx_credits = asyncio.Semaphore(initial_credits)
        self._rx_credits = initial_credits
        self._state = ChannelState.OPEN
        self._events: ChannelEvents | SimpleChannelEvents | None = None
        # Incoming SDU reassembly
        self._rx_sdu_buf = bytearray()
        self._rx_sdu_expected_len = 0

    # -- properties ----------------------------------------------------------

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

    # -- public API ----------------------------------------------------------

    async def send(self, data: bytes) -> None:
        """Send an SDU, segmenting by MPS and consuming one credit per segment."""
        # Prepend SDU length to the payload for segmentation purposes.
        sdu_with_len = struct.pack("<H", len(data)) + data
        offset = 0
        first = True
        while offset < len(sdu_with_len):
            # Determine max payload this segment.  The first segment includes
            # the 2-byte SDU length inside the MPS budget already (it's part of
            # sdu_with_len), so we just slice by MPS uniformly.
            segment = sdu_with_len[offset : offset + self._mps]
            offset += len(segment)

            # Acquire one TX credit (blocks if none available).
            await self._tx_credits.acquire()

            # Build L2CAP basic header with *peer* CID.
            l2cap_pdu = struct.pack("<HH", len(segment), self._peer_cid) + segment
            await self._hci.send_acl_data(  # type: ignore[union-attr]
                self._connection_handle, ACL_PB_FIRST_AUTO_FLUSH, l2cap_pdu
            )
            first = False

    async def close(self) -> None:
        self._state = ChannelState.DISCONNECTING

    def set_events(self, events: ChannelEvents | SimpleChannelEvents) -> None:
        self._events = events

    def add_credits(self, n: int) -> None:
        """Called when the peer grants us *n* additional TX credits."""
        for _ in range(n):
            self._tx_credits.release()

    async def _on_pdu(self, data: bytes) -> None:
        """Receive an L2CAP payload (header already stripped).

        The first segment of an SDU carries a 2-byte LE SDU-length prefix;
        subsequent continuation segments carry raw payload only.
        """
        if self._rx_sdu_expected_len == 0:
            # First segment — extract SDU length.
            if len(data) < 2:
                return  # malformed
            self._rx_sdu_expected_len = struct.unpack_from("<H", data)[0]
            self._rx_sdu_buf = bytearray(data[2:])
        else:
            # Continuation segment.
            self._rx_sdu_buf.extend(data)

        if len(self._rx_sdu_buf) >= self._rx_sdu_expected_len:
            sdu = bytes(self._rx_sdu_buf[: self._rx_sdu_expected_len])
            # Reset reassembly state.
            self._rx_sdu_buf = bytearray()
            self._rx_sdu_expected_len = 0
            if self._events is not None:
                await _invoke(self._events.on_data, sdu)
