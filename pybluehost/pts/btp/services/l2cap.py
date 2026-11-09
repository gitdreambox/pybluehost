"""L2CAP BTP service — LE Credit-Based Channels.

Translates auto-pts L2CAP opcodes into IutActions / v1.0 L2CAP API calls.
Owns a per-session map of BTP chan_id (u8) → v1.0 channel object.

Handlers land in P.8 Tasks 2-4; this file is the skeleton.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pybluehost.core.errors import LECoCConnectError
from pybluehost.l2cap.channel import SimpleChannelEvents
from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import BtpFrame
from pybluehost.pts.btp.services.base import BtpService

if TYPE_CHECKING:
    from pybluehost.pts.actions import IutActions
    from pybluehost.pts.btp.tester import BtpTester

logger = logging.getLogger(__name__)

# Response budget for the PTS-driven CONNECT path. This is the same 1 s RTX
# window as L2CAPManager: the request is sent once and abandoned if no matching
# response arrives. Do not shorten this to speed up COS/CED/BI-29's repeated
# invalid-ID rounds. On Windows the controller can receive a valid response in
# 16 ms yet deliver it to asyncio after a 100 ms timeout has already removed the
# pending future (L2CAP/LE/CFC/BV-29), silently discarding a successful connect.
_CONNECT_WINDOW_S = 1.0

# Delay before the refusal-path 0x82 Disconnected event. The BTP response
# (num=1 + chan_id) must be readable and the WID handler must have registered
# the pending channel (l2cap.connect(chans)) before the event flips it to
# DISCONNECTED — an event that races ahead lands as "unknown channel" in the
# auto-pts model and leaves wait_for_disconnection hanging.
_REFUSAL_EVENT_DELAY_S = 0.1

# Result codes auto-pts's L2CapChannelStatusCode map can decode — its
# l2cap_disconnected_ev does L2CapChannelStatusCode(res) and raises KeyError
# (dropping the event) on anything else. Anything outside the map is clamped
# to 0x0004 (insufficient resources — the generic refusal).
_WIRE_REJECT_RESULTS = {0x0000, 0x0002, 0x0004, 0x0005, 0x0006, 0x0007,
                        0x0008, 0x0009, 0x000A, 0x000B, 0x000C}
_WIRE_REJECT_RESULT_FALLBACK = 0x0004


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
        # auto-pts WID handlers address the FIRST channel as chan_id 0
        # (wait_for_connection(0) / chan_lookup_id(0) / l2cap_send_data(0, …)),
        # so allocation must start at 0 — starting at 1 leaves the autopts stack
        # model with channel 1 while every WID looks up channel 0 → INCONC.
        self._next_chan_id: int = 0
        # Tell auto-pts whenever a Credit-Based Reconfigure lands on a channel.
        # Without this its model keeps the pre-reconfigure MTU/MPS and grades
        # later steps against stale sizes (BTP L2CAP_EV_RECONFIGURED, 0x84).
        stack = getattr(actions, "_stack", None)
        l2cap = getattr(stack, "l2cap", None) if stack is not None else None
        if l2cap is not None and hasattr(l2cap, "on_le_channel_reconfigured"):
            l2cap.on_le_channel_reconfigured(self._on_channel_reconfigured)

    def _on_channel_reconfigured(self, channel) -> None:
        """Emit BTP L2CAP_EV_RECONFIGURED — body chan_id(u8) + peer_mtu(u16) +
        peer_mps(u16) + our_mtu(u16) + our_mps(u16)."""
        chan_id = next(
            (cid for cid, ch in self._channels.items() if ch is channel), None
        )
        if chan_id is None:
            return
        peer_mtu = int(getattr(channel, "_mtu", 0))
        peer_mps = int(getattr(channel, "_mps", 0))
        our_mtu = int(getattr(channel, "_rx_mtu", peer_mtu))
        our_mps = int(getattr(channel, "_rx_mps", peer_mps))
        payload = (
            bytes([chan_id])
            + peer_mtu.to_bytes(2, "little")
            + peer_mps.to_bytes(2, "little")
            + our_mtu.to_bytes(2, "little")
            + our_mps.to_bytes(2, "little")
        )
        self._emit_event(op.OP_L2CAP_EVENT_RECONFIGURED, payload)

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
            bit_index = code
            out[bit_index // 8] |= 1 << (bit_index % 8)
        return op.BTP_STATUS_SUCCESS, bytes(out)

    def _resolve_le_connection_handle(self, addr: bytes) -> int | None:
        """Look up an LE connection whose peer's 6-byte address matches `addr`.

        ``addr`` arrives on the BTP wire in little-endian (HCI) order — auto-pts
        builds it with ``addr_str_to_le_bytes``. ``BDAddress.address`` is the
        big-endian *display* order, so we must compare against ``to_hci()``
        (little-endian), exactly like the GAP DEVICE_FOUND/CONNECTED events.
        """
        try:
            session = self._actions.status()
        except Exception:
            return None
        target = bytes(addr)[:6]
        for h, info in session.connections.items():
            peer = getattr(info, "peer", None)
            if peer is None:
                continue
            to_hci = getattr(peer, "to_hci", None)
            if callable(to_hci):
                try:
                    if bytes(to_hci())[:6] == target:
                        return h
                except Exception:
                    pass
                continue
            raw = getattr(peer, "address", None) or getattr(peer, "bytes", None) or peer
            try:
                if bytes(raw)[:6] == target:
                    return h
            except Exception:
                continue
        return None

    async def _do_connect(self, addr: bytes, psm: int, mtu: int, num: int,
                          addr_type: int = 0):
        """Shared LE CoC connect. Returns (status, chan_ids).

        chan_ids is a list on success (possibly EMPTY when the peer refused —
        reported as num=0, not an error) and None on genuine BTP failure.
        num == 1 uses the classic LE CoC request (0x14); num > 1 uses the
        Enhanced Credit-Based request (0x17) that carries N SCIDs at once
        (PTS ECFC initiator cases).
        """
        handle = self._resolve_le_connection_handle(addr)
        if handle is None:
            return op.BTP_STATUS_FAILED, None
        stack = getattr(self._actions, "_stack", None)
        if stack is None or not hasattr(stack, "l2cap"):
            return op.BTP_STATUS_FAILED, None
        if num < 1 or num > 5:
            logger.warning("L2CAP CONNECT: Num=%d out of supported range 1..5", num)
            return op.BTP_STATUS_FAILED, None
        if num == 1:
            try:
                channels = [await stack.l2cap.connect_le_coc_channel(
                    handle=handle, psm=psm, timeout=_CONNECT_WINDOW_S,
                    mtu=mtu or 512, mps=247, initial_credits=10,
                )]
            except LECoCConnectError as e:
                # The peer actively REFUSED the channel (non-zero result, or a
                # Command Reject from a legacy peer). This is an expected protocol
                # outcome that the test wants reported to the Upper Tester — NOT a
                # BTP-level error. Per btp_l2cap.txt op 0x02 the response carries
                # the chan_ids CREATED ("to allow cancellation of this connection
                # request using Disconnect") and a Disconnected event follows in
                # case of an error — so report one pending chan_id per requested
                # channel and then emit 0x82 with the refusal's result code.
                # (auto-pts's hdl_wid_280 — BI-29 connect rounds — indexes
                # chans[0] right after l2cap_conn(); num=0 crashes the WID.)
                # Returning BTP_STATUS_FAILED here would make autopts raise
                # BTPError → BTP ERROR.
                #
                # NOTE: this applies to SECURITY refusals (0x0005-0x0008) too. The
                # Security-Initiator cases (BV-22/23/24) only require the IUT to
                # "inform the Upper Tester about the rejection" (L2CAP.TS) — the
                # autopts WID 251-254 then just calls wait_for_disconnection(0),
                # which returns True immediately because no channel was
                # registered. Do NOT pair-and-retry here: PTS is not prepared for
                # pairing at this point and drops the ACL (reason 0x13), turning
                # the case into a BTP TIMEOUT.
                logger.info("L2CAP CONNECT refused by peer: %s", e)
                chan_ids = [self._allocate_chan_id() for _ in range(num)]
                self._emit_refused(chan_ids, psm=psm, result=e.result)
                return op.BTP_STATUS_SUCCESS, chan_ids
            except Exception:
                logger.exception("L2CAP CONNECT: connect_le_coc_channel raised")
                return op.BTP_STATUS_FAILED, None
        else:
            connect_many = getattr(stack.l2cap, "connect_le_coc_channels", None)
            if connect_many is None:
                logger.warning("L2CAP CONNECT: multi-channel unsupported")
                return op.BTP_STATUS_FAILED, None
            try:
                channels = await connect_many(
                    handle=handle, psm=psm, timeout=_CONNECT_WINDOW_S,
                    mtu=mtu or 512, mps=247,
                    initial_credits=10, num=num,
                )
            except LECoCConnectError as e:
                logger.info("L2CAP CONNECT (ECFC) refused by peer: %s", e)
                chan_ids = [self._allocate_chan_id() for _ in range(num)]
                self._emit_refused(chan_ids, psm=psm, result=e.result)
                return op.BTP_STATUS_SUCCESS, chan_ids
            except Exception:
                logger.exception("L2CAP CONNECT: connect_le_coc_channels raised")
                return op.BTP_STATUS_FAILED, None
        chan_ids = []
        for ch in channels:
            chan_id = self._allocate_chan_id()
            # Wire events + emit 0x81 Connected so the autopts stack model marks
            # each channel up (l2cap.connected()), exactly like the incoming path.
            self._register_connected_channel(
                chan_id, ch, psm=psm, addr_type=addr_type, addr=addr)
            chan_ids.append(chan_id)
        return op.BTP_STATUS_SUCCESS, chan_ids

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
        status, chan_ids = await self._do_connect(addr, psm, mtu, num,
                                                  addr_type=data[0])
        if status != op.BTP_STATUS_SUCCESS:
            return status, b""
        return op.BTP_STATUS_SUCCESS, bytes([len(chan_ids)]) + bytes(chan_ids)

    async def _handle_op_0b(self, controller_index: int, data: bytes):
        """L2CAP CONNECT_V2 (0x0b) — body 17 bytes: addr_type(1) + addr(6) +
        PSM(u16 LE) + MTU(u16 LE) + Num(u8) + Mode(u8) + Options(u32 LE).
        Response: Num(u8) + chan_ids(u8 × Num).

        Mode/Options (ECFC, hold-credit) are parsed for framing but not acted on —
        PyBlueHost LE CoC negotiates a single plain credit-based channel.
        """
        if len(data) != 17:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        psm = int.from_bytes(data[7:9], "little")
        mtu = int.from_bytes(data[9:11], "little")
        num = data[11]
        # mode = data[12]; options = data[13:17] — ignored in P.8 v1.
        status, chan_ids = await self._do_connect(addr, psm, mtu, num,
                                                  addr_type=data[0])
        if status != op.BTP_STATUS_SUCCESS:
            return status, b""
        return op.BTP_STATUS_SUCCESS, bytes([len(chan_ids)]) + bytes(chan_ids)

    async def _handle_op_07(self, controller_index: int, data: bytes):
        """RECONFIGURE — body: addr_type(1)+addr(6)+mtu(2)+count(1)+chan_ids(1×N).

        Initiates an ECFC Reconfigure (0x19) on the listed BTP channels
        (PTS L2CAP/ECFC/BV-22/23/24 — Renegotiate MTU, WID 103 calls
        ``l2cap_reconfigure`` with current MTU + 1 on every channel).
        """
        if len(data) < 11:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        mtu = int.from_bytes(data[7:9], "little")
        count = data[9]
        chan_ids = list(data[10:10 + count])
        handle = self._resolve_le_connection_handle(addr)
        if handle is None:
            return op.BTP_STATUS_FAILED, b""
        channels = [self._channels[c] for c in chan_ids if c in self._channels]
        if not channels:
            return op.BTP_STATUS_FAILED, b""
        stack = getattr(self._actions, "_stack", None)
        if stack is None or not hasattr(stack, "l2cap"):
            return op.BTP_STATUS_FAILED, b""
        try:
            await stack.l2cap.reconfigure_le_coc_channels(
                handle, mtu=mtu, channels=channels)
        except Exception:
            logger.exception("L2CAP RECONFIGURE raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

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

    # ---- Credits (0x08) ---------------------------------------------------

    async def _handle_op_08(self, controller_index: int, data: bytes):
        """CREDITS — body: chan_id(u8). Grant the peer more send credits.

        BTP carries no count; replenish the channel's initial-credit amount.
        """
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
        chan_id = data[0]
        ch = self._channels.get(chan_id)
        if ch is None:
            return op.BTP_STATUS_FAILED, b""
        stack = getattr(self._actions, "_stack", None)
        if stack is None or not hasattr(stack, "l2cap"):
            return op.BTP_STATUS_FAILED, b""
        grant = getattr(stack.l2cap, "grant_le_coc_credits", None)
        if grant is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            await grant(ch, credits=getattr(ch, "initial_credits", 10))
        except Exception:
            logger.exception("L2CAP CREDITS: grant_le_coc_credits raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    # ---- Disconnect EATT channels (0x09) ----------------------------------

    async def _handle_op_09(self, controller_index: int, data: bytes):
        """DISCONNECT_EATT_CHANS (0x09) — body addr_type(1) + addr(6 LE) +
        channel_count(1). Response is parameterless.

        Disconnect the first `count` EATT bearers (channels on the fixed EATT
        SPSM 0x0027) of the resolved connection, lowest CID first; a count
        beyond what exists disconnects all of them. auto-pts drives this from
        WID 144 (the GATT/SR EATT multi-bearer cases tear down bearers
        mid-test).
        """
        from pybluehost.l2cap.constants import PSM_EATT

        if len(data) != 8:
            return op.BTP_STATUS_FAILED, b""
        # data[0] is addr_type; the address match is type-agnostic here.
        addr = bytes(data[1:7])
        count = data[7]
        stack = getattr(self._actions, "_stack", None)
        l2cap = getattr(stack, "l2cap", None) if stack is not None else None
        if l2cap is None:
            return op.BTP_STATUS_FAILED, b""
        handle = self._resolve_le_connection_handle(addr)
        if handle is None:
            return op.BTP_STATUS_FAILED, b""
        le_coc_channels = getattr(l2cap, "le_coc_channels", None)
        if le_coc_channels is None:
            return op.BTP_STATUS_FAILED, b""
        channels = sorted(
            (ch for ch in le_coc_channels(handle)
             if getattr(ch, "psm", None) == PSM_EATT),
            key=lambda ch: ch.cid,
        )
        gatt_server = getattr(stack, "gatt_server", None)
        for ch in channels[:count]:
            cid = ch.cid
            try:
                await l2cap.disconnect_le_coc_channel(ch)
            except Exception:
                logger.exception(
                    "L2CAP DISCONNECT_EATT_CHANS: disconnect_le_coc_channel "
                    "raised (cid=0x%04X)", cid,
                )
                return op.BTP_STATUS_FAILED, b""
            if gatt_server is not None:
                gatt_server.remove_eatt_bearer(handle, cid)
        return op.BTP_STATUS_SUCCESS, b""

    # ---- Listen (0x05) ---------------------------------------------------

    async def _handle_op_05(self, controller_index: int, data: bytes):
        """LISTEN — register an LE CoC listener on PSM.

        Wire format drift: the btp_l2cap.txt spec documents a 9-octet body
        PSM(2)+Transport(1)+MTU(2)+Security_Type(1)+Key_Size(1)+Response(2),
        but the auto-pts master ``l2cap_listen`` actually packs only **7 octets**
        (PSM+Transport+MTU+Response) — it predates the Security_Type/Key_Size
        fields. Accept both: we take PSM (offset 0), MTU (offset 3) and
        Response (offset differs by body form, see below) to listen;
        Transport/Security_Type/Key_Size are not acted on. ``Response`` is the
        L2CAPConnectionResponse result the listener must enforce (0=accept,
        1..4 = require auth/authz/key-size/encryption) and is forwarded as
        ``required_security``, so the security-rejection cases work too.
        """
        if len(data) < 7:
            return op.BTP_STATUS_FAILED, b""
        psm = int.from_bytes(data[0:2], "little")
        # Response (u16 LE) = the L2CAPConnectionResponse the listener must enforce:
        # 0=accept-all, 1/2/3/4 = require authentication/authorization/key-size/
        # encryption before accepting. Its offset differs by body form:
        #   7-octet auto-pts master form: PSM(0:2) Transport(2) MTU(3:5) Response(5:7)
        #   9-octet spec form:            PSM(0:2) Transport(2) MTU(3:5)
        #                                 Security_Type(5) Key_Size(6) Response(7:9)
        # auto-pts master always sends the 7-octet form.
        if len(data) >= 9:
            response = int.from_bytes(data[7:9], "little")
        else:
            response = int.from_bytes(data[5:7], "little")
        stack = getattr(self._actions, "_stack", None)
        if stack is None or not hasattr(stack, "l2cap"):
            return op.BTP_STATUS_FAILED, b""
        listen_fn = getattr(stack.l2cap, "listen_le_coc_channel", None)
        if listen_fn is None:
            return op.BTP_STATUS_FAILED, b""
        listen_fn(psm, self._make_incoming_handler(psm), required_security=response)
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_0c(self, controller_index: int, data: bytes):
        """LISTEN_V2 (0x0c) — body 12 bytes: PSM(2) + Transport(1) + MTU(2) +
        Response(2) + Mode(1) + Options(4).

        auto-pts ``l2cap_listen_v2`` sends this for ECFC listener setup (and
        for ERTM/Streaming-mode listeners we don't implement). We register the
        same LE CoC listener with the Response forwarded as the required
        security level; Mode/Options frame the credit model but a plain
        credit-based listener already accepts ECFC (0x17) requests.
        """
        if len(data) < 12:
            return op.BTP_STATUS_FAILED, b""
        psm = int.from_bytes(data[0:2], "little")
        response = int.from_bytes(data[5:7], "little")
        # mode = data[7]; options = data[8:12] — not acted on.
        stack = getattr(self._actions, "_stack", None)
        if stack is None or not hasattr(stack, "l2cap"):
            return op.BTP_STATUS_FAILED, b""
        listen_fn = getattr(stack.l2cap, "listen_le_coc_channel", None)
        if listen_fn is None:
            return op.BTP_STATUS_FAILED, b""
        listen_fn(psm, self._make_incoming_handler(psm), required_security=response)
        return op.BTP_STATUS_SUCCESS, b""

    def _make_incoming_handler(self, psm: int):
        """Build a closure that captures the PSM for event emission."""
        def on_incoming(ch):
            self._handle_incoming_channel(ch, psm=psm)
        return on_incoming

    def _handle_incoming_channel(self, ch, *, psm: int) -> None:
        """Allocate BTP chan_id, wire data/close events, emit 0x81 Connected."""
        btp_chan_id = self._allocate_chan_id()
        # Incoming: peer addr unknown at this layer — emit zeros.
        self._register_connected_channel(btp_chan_id, ch, psm=psm,
                                         addr_type=0, addr=bytes(6))

    def _register_connected_channel(self, btp_chan_id: int, ch, *, psm: int,
                                    addr_type: int, addr: bytes) -> None:
        """Store the channel, wire Data-Received/Disconnected events, and emit
        the 0x81 Connected event so the autopts stack model marks it up. Shared
        by the incoming (LISTEN) and outgoing (CONNECT) paths."""
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
        # our_mtu/our_mps = OUR advertised receive limits (`_rx_*`): what the
        # peer may send US. auto-pts grades received-SDU sizes against
        # chan.our_mtu (WID 261) — duplicating the peer-facing values here left
        # its model unable to tell the two directions apart (BV-23 renegotiate).
        our_mtu = int(getattr(ch, "_rx_mtu", peer_mtu))
        our_mps = int(getattr(ch, "_rx_mps", peer_mps))
        payload = (
            bytes([btp_chan_id])
            + psm.to_bytes(2, "little")
            + int(peer_mtu).to_bytes(2, "little")
            + int(peer_mps).to_bytes(2, "little")
            + int(our_mtu).to_bytes(2, "little")
            + int(our_mps).to_bytes(2, "little")
            + bytes([addr_type & 0xFF])
            + bytes(addr)[:6].ljust(6, b"\x00")
        )
        self._emit_event(op.OP_L2CAP_EVENT_CONNECTED, payload)

    def _emit_data_received(self, btp_chan_id: int, data: bytes) -> None:
        # Payload: chan_id(1) + data_len(u16) + data
        payload = bytes([btp_chan_id]) + len(data).to_bytes(2, "little") + bytes(data)
        self._emit_event(op.OP_L2CAP_EVENT_DATA_RECEIVED, payload)

    def _emit_refused(self, chan_ids: list[int], *, psm: int, result: int) -> None:
        """Report a refused connect: one Disconnected event (0x82) per pending
        chan_id, delayed a beat so the chan reaches the auto-pts stack model
        (l2cap.connect(chans)) before the event marks it DISCONNECTED."""
        wire_result = result if result in _WIRE_REJECT_RESULTS \
            else _WIRE_REJECT_RESULT_FALLBACK

        async def _delayed():
            await asyncio.sleep(_REFUSAL_EVENT_DELAY_S)
            for cid in chan_ids:
                self._emit_disconnected(cid, psm, 0, result=wire_result)

        asyncio.ensure_future(_delayed())

    def _emit_disconnected(self, btp_chan_id: int, psm: int, reason: int,
                           result: int = 0) -> None:
        # Payload: result(u16) + chan_id(1) + psm(u16) + addr_type(1) + addr(6) = 12 bytes
        #
        # Per btp_l2cap.txt the Result field carries a connection-request
        # REJECTION code ONLY; for an established channel that is later torn
        # down "it shall be set to zero" (the default here). The `reason` arg
        # for teardowns is the HCI disconnect reason (e.g. 0x13
        # remote-user-terminated), NOT an L2CAP result — forwarding it raw
        # makes auto-pts's l2cap_disconnected_ev raise KeyError(reason) (its
        # l2cap_result_str map only knows the connection-result codes
        # 0/2/4/5/6/7/8/9/10), dropping the event and corrupting the stack
        # model. The refusal path (_emit_refused) passes the L2CAP result
        # explicitly.
        if reason:
            logger.debug(
                "L2CAP chan_id=%d disconnected (HCI reason=0x%02X); reporting result=0",
                btp_chan_id, reason,
            )
        payload = (
            int(result).to_bytes(2, "little")
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
