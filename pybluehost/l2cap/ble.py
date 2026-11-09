"""BLE L2CAP channels: FixedChannel and LECoCChannel."""
from __future__ import annotations

import asyncio
import inspect
import logging
import struct

from pybluehost.hci.constants import ACL_PB_FIRST_AUTO_FLUSH
from pybluehost.l2cap.channel import (
    Channel,
    ChannelEvents,
    ChannelState,
    SimpleChannelEvents,
)

logger = logging.getLogger(__name__)


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
        rx_mtu: int | None = None,
        rx_mps: int | None = None,
        psm: int | None = None,
    ) -> None:
        self._connection_handle = connection_handle
        self._local_cid = local_cid
        self._peer_cid = peer_cid
        self._hci = hci
        self._mtu = mtu
        self._mps = mps
        # Receive-side framing limits = the MTU/MPS *we* advertised to the peer
        # (what we told it we can receive). These gate the K-frame violation
        # checks and are generally LARGER than the negotiated ``mtu``/``mps``
        # (which are min(ours, peer) and bound the *send* path). Using the min
        # for receive validation falsely flags legal inbound frames — e.g. PTS
        # L2CAP/LE/CFC/BV-07, where we advertise MPS=247 but the peer's own MPS
        # is 64, so min=64 would reject the peer's legal 241-byte frames.
        self._rx_mtu = rx_mtu if rx_mtu is not None else mtu
        self._rx_mps = rx_mps if rx_mps is not None else mps
        # Immutable ECFC-reconfigure baseline: the receive MPS we advertised at
        # channel setup. A successful reconfigure mutates ``_rx_mps`` for data
        # enforcement, but the §4.25 "is this a reduction?" comparison must stay
        # anchored to the originally-advertised value — otherwise a later
        # request above the enforced (already-reduced) MPS looks like an illegal
        # increase (PTS L2CAP/ECFC/BI-07).
        self._reconfig_base_mps = self._rx_mps
        # The (S)PSM this channel was established for. EATT bearers ride the
        # fixed SPSM 0x0027 — BTP DISCONNECT_EATT_CHANS picks them out by it.
        self._psm = psm
        self._tx_credits = asyncio.Semaphore(initial_credits)
        # Outbound SDUs waiting for credits: [sdu-with-length-prefix, offset].
        # Kept as a queue so ``send`` can return without blocking (see send()).
        self._tx_queue: list[list] = []
        self._tx_drain_lock = asyncio.Lock()
        # Running total of credits the peer has granted us (the value that would
        # sit in the 16-bit credit field); guards against overflow (§4.24).
        self._tx_credits_total = initial_credits
        self._rx_credits = initial_credits
        self._initial_credits = initial_credits
        self._state = ChannelState.OPEN
        self._events: ChannelEvents | SimpleChannelEvents | None = None
        # Optional async callback ``cb(credits: int)`` invoked once per received
        # K-frame to grant the peer replacement send credits (LE Flow Control
        # Credit). The manager wires this to grant_le_coc_credits so the
        # receive path auto-replenishes the peer's credit pool — required by PTS
        # L2CAP/LE/CFC credit-exchange cases (e.g. BV-07), which stall if the
        # IUT consumes credits without returning them.
        self._credit_grant_cb = None
        # Optional async callback ``cb()`` invoked when a received K-frame
        # violates LE CoC framing rules (SDU length > MTU, segment > MPS,
        # segments overrunning the declared SDU length). The manager wires this
        # to disconnect_le_coc_channel so the IUT terminates the channel with an
        # L2CAP_DISCONNECTION_REQ — required by PTS L2CAP/LE/CFC/BV-26/27/28
        # (and their ECFC equivalents), where the IUT silently stalling instead
        # makes PTS run to its ~320 s time guard.
        self._violation_cb = None
        # Incoming SDU reassembly
        self._rx_sdu_buf = bytearray()
        self._rx_sdu_expected_len = 0

    # -- properties ----------------------------------------------------------

    @property
    def cid(self) -> int:
        return self._local_cid

    @property
    def psm(self) -> int | None:
        return self._psm

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
    def initial_credits(self) -> int:
        """Credits we granted the peer at channel setup (BTP CREDITS default)."""
        return self._initial_credits

    # -- public API ----------------------------------------------------------

    async def send(self, data: bytes) -> None:
        """Queue an SDU and push out as much of it as the credits allow.

        Deliberately does NOT block until the SDU reaches the wire: a peer may
        withhold credits for seconds, and a caller that blocks on them makes
        auto-pts time out. L2CAP/ECFC/BV-23 sends four SDUs; the fourth stalls
        on an exhausted credit budget and the case ends in a BTP TIMEOUT even
        though the reconfigure it was testing had already been accepted. The
        RFCOMM credit path needed exactly this fix (queue + drain, never block).

        With credits available the whole SDU still goes out before this
        returns, so nothing that sends on a funded channel changes behaviour.
        """
        # [sdu-with-length-prefix, offset] so a half-sent SDU resumes where it
        # stopped once credits arrive.
        self._tx_queue.append([struct.pack("<H", len(data)) + bytes(data), 0])
        await self._drain_tx()

    async def _drain_tx(self) -> None:
        async with self._tx_drain_lock:
            while self._tx_queue:
                entry = self._tx_queue[0]
                buf, offset = entry
                while offset < len(buf):
                    if self._tx_credits.locked():
                        entry[1] = offset
                        logger.debug(
                            "LE CoC tx stalled on credits handle=0x%04X cid=0x%04X "
                            "queued=%d offset=%d/%d",
                            self._connection_handle, self._local_cid,
                            len(self._tx_queue), offset, len(buf),
                        )
                        return
                    await self._tx_credits.acquire()
                    segment = buf[offset: offset + self._mps]
                    offset += len(segment)
                    # Build L2CAP basic header with *peer* CID.
                    l2cap_pdu = struct.pack("<HH", len(segment), self._peer_cid) + segment
                    await self._hci.send_acl_data(  # type: ignore[union-attr]
                        self._connection_handle, ACL_PB_FIRST_AUTO_FLUSH, l2cap_pdu
                    )
                self._tx_queue.pop(0)

    async def close(self) -> None:
        self._state = ChannelState.DISCONNECTING
        # Nothing more can go out; drop anything still waiting for credits.
        self._tx_queue.clear()

    def set_events(self, events: ChannelEvents | SimpleChannelEvents) -> None:
        self._events = events

    def add_credits(self, n: int) -> bool:
        """Called when the peer grants us *n* additional TX credits.

        The credit counter is a 16-bit field (Core Spec Vol 3 Part A §4.24): a
        grant that would carry the running total past 65535 is a protocol
        violation. Return False without applying it — the caller disconnects the
        channel (PTS L2CAP/LE/CFC/BI-01-C). Otherwise return True.
        """
        if self._tx_credits_total + n > 65535:
            return False
        self._tx_credits_total += n
        for _ in range(n):
            self._tx_credits.release()
        logger.debug(
            "LE CoC rx credit grant cid=0x%04X +%d (total=%d queued=%d)",
            self._local_cid, n, self._tx_credits_total, len(self._tx_queue),
        )
        # Credits may unblock a stalled queue — resume it. Safe to schedule from
        # a sync context (the signalling dispatcher holds a running loop).
        if self._tx_queue:
            try:
                asyncio.get_running_loop().create_task(self._drain_tx())
            except RuntimeError:
                pass
        return True

    async def _on_pdu(self, data: bytes) -> None:
        """Receive an L2CAP payload (header already stripped).

        The first segment of an SDU carries a 2-byte LE SDU-length prefix;
        subsequent continuation segments carry raw payload only.

        Framing violations (Core Spec Vol 3 Part A §3.4.2 — K-frame SDU length
        greater than the channel MTU, Information Payload greater than the MPS,
        or segments overrunning the declared SDU length) terminate the channel
        via ``_violation_cb`` instead of being buffered.
        """
        # Each K-frame we consume spends one of the peer's send credits; grant a
        # replacement credit back so the peer's pool doesn't drain (LE CoC flow
        # control). Done per K-frame, before reassembly.
        logger.debug(
            "LE CoC rx K-frame handle=0x%04X cid=0x%04X len=%d (grant_back=%s)",
            self._connection_handle, self._local_cid, len(data),
            self._credit_grant_cb is not None,
        )
        if self._credit_grant_cb is not None:
            try:
                await self._credit_grant_cb(1)
            except Exception:
                logger.exception("LE CoC credit grant failed")

        # Violation 1: Information Payload length greater than the MPS we
        # advertised (our receive capacity), NOT the negotiated min. On the
        # FIRST K-frame of an SDU the payload includes the 2-byte SDU-length
        # prefix (Core Vol 3 Part A §3.4.2), so the information payload is
        # len(data) - 2 there — a legal full-MPS K-frame arrives as MPS + 2.
        payload_len = (len(data) - 2
                       if self._rx_sdu_expected_len == 0 else len(data))
        if payload_len > self._rx_mps:
            return await self._signal_violation(
                f"K-frame payload {payload_len} > MPS {self._rx_mps}"
            )

        if self._rx_sdu_expected_len == 0:
            # First segment — extract SDU length.
            if len(data) < 2:
                return  # malformed
            sdu_len = struct.unpack_from("<H", data)[0]
            # Violation 2: SDU length greater than the MTU we advertised.
            if sdu_len > self._rx_mtu:
                return await self._signal_violation(
                    f"K-frame SDU length {sdu_len} > MTU {self._rx_mtu}"
                )
            self._rx_sdu_expected_len = sdu_len
            self._rx_sdu_buf = bytearray(data[2:])
        else:
            # Continuation segment.
            self._rx_sdu_buf.extend(data)
            # Violation 3: segments overrunning the declared SDU length.
            if len(self._rx_sdu_buf) > self._rx_sdu_expected_len:
                return await self._signal_violation(
                    f"segmented SDU overruns declared length "
                    f"{self._rx_sdu_expected_len}"
                )

        if len(self._rx_sdu_buf) >= self._rx_sdu_expected_len:
            sdu = bytes(self._rx_sdu_buf[: self._rx_sdu_expected_len])
            # Reset reassembly state.
            self._rx_sdu_buf = bytearray()
            self._rx_sdu_expected_len = 0
            if self._events is not None:
                await _invoke(self._events.on_data, sdu)

    async def check_first_fragment_violation(
        self, declared_len: int, payload_prefix: bytes
    ) -> bool:
        """Fast-path framing-violation check on the FIRST ACL fragment of a K-frame.

        PTS L2CAP/LE/CFC/BV-26/27 (and their ECFC equivalents) send ONLY the
        first ACL fragment of an oversized K-frame — declaring the violation in
        the L2CAP length field / SDU-length prefix — then wait (~300 s) for the
        IUT to disconnect the channel. SAR reassembly never completes, so
        ``_on_pdu`` never runs and the violation would go undetected. Both
        violations are knowable from the first fragment alone, so check here:

        - BV-27: the K-frame's Information Payload (the L2CAP ``length`` field,
          minus the 2-byte SDU-length prefix on a first K-frame) exceeds the
          MPS we advertised.
        - BV-26: the SDU-length prefix exceeds the MTU we advertised. Only the
          first K-frame of an SDU carries that prefix (``_rx_sdu_expected_len
          == 0``); continuation K-frames are SDU data, not a length prefix.

        Both limits are relative to the MTU/MPS *we* advertised (L2CAP.TS:
        "greater than the MTU/MPS of the IUT"), so a legal peer never trips
        this — no false positives on well-formed traffic.

        Returns True if a violation was found and the teardown was signaled.
        """
        # BV-27: Information Payload length greater than the MPS we advertised.
        # On a LE CoC FIRST K-frame the L2CAP length field counts the 2-byte
        # SDU-length prefix too (Core Vol 3 Part A §3.4.2), so the actual
        # Information Payload is declared_len - 2 there — a legal full-MPS
        # K-frame legitimately declares MPS + 2. Continuation K-frames carry
        # SDU data only, no prefix.
        payload_len = (declared_len - 2
                       if self._rx_sdu_expected_len == 0 else declared_len)
        if payload_len > self._rx_mps:
            await self._signal_violation(
                f"K-frame payload {payload_len} > MPS {self._rx_mps} "
                f"(first fragment)"
            )
            return True
        # BV-26: SDU length greater than the MTU we advertised.
        if self._rx_sdu_expected_len == 0 and len(payload_prefix) >= 2:
            sdu_len = struct.unpack_from("<H", payload_prefix)[0]
            if sdu_len > self._rx_mtu:
                await self._signal_violation(
                    f"K-frame SDU length {sdu_len} > MTU {self._rx_mtu} "
                    f"(first fragment)"
                )
                return True
        return False

    async def _signal_violation(self, reason: str) -> None:
        """Abort the channel on a K-frame framing violation (PTS BV-26/27/28)."""
        logger.warning("LE CoC channel 0x%04X framing violation: %s",
                       self._local_cid, reason)
        if self._violation_cb is not None:
            try:
                await self._violation_cb()
            except Exception:
                logger.exception("LE CoC violation disconnect failed")
