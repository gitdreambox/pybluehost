"""Session BR link: accept / connect / disconnect cascade / graceful / secure-link / scan-reopen.

Mechanically ported from the orchestrator BR unit tests (test_orchestrator_bredr_accept /
_connect / _disconnect, test_secure_target_link): event-parsing assertions are kept
verbatim; wiring assertions are rewritten for the subscription model —
callback-replacement assertions (`ctl._on_hci_event is prev`) become unsubscribe
assertions (`s._subs[side] == []`), `_make_link_watch` becomes `_make_watch` (with
link), and event injection goes through the multi-point dispatch of
`_install_dispatch`.
"""
import asyncio
from dataclasses import dataclass, field

import pytest

from pybluehost.cli.app.mitm.recon import ClonedIdentity
from pybluehost.cli.app.mitm.capture import NullTap
from pybluehost.cli.app.mitm.session import (
    MitmSession,
    build_create_connection_params,
)
from pybluehost.hci.constants import (
    EventCode,
    HCI_ACCEPT_CONNECTION_REQ,
    HCI_AUTH_REQUESTED,
    HCI_CREATE_CONNECTION,
    HCI_DISCONNECT,
    HCI_REJECT_CONNECTION_REQ,
    HCI_SET_CONNECTION_ENCRYPTION,
    HCI_WRITE_SCAN_ENABLE,
    HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT,
)
from pybluehost.hci.packets import HCICommand, HCIEvent

# --- accept group constants --------------------------------------------------
PHONE_ADDR_LE = bytes.fromhex("20E8AABBCCDD")  # phone BR/EDR address, little-endian (illustrative)
ACL_LINK = 0x01
SCO_LINK = 0x00
# --- connect group constants -------------------------------------------------
TARGET = "98:1D:F9:90:11:1E"
TARGET_LE = bytes.fromhex("1E1190F91D98")  # the above address in little-endian wire order
WRONG_LE = bytes.fromhex("DEADBEEFCAFE")
# --- secure-link group constants ---------------------------------------------
HANDLE = 0x100
_AUTH_REQUESTED = HCI_AUTH_REQUESTED
_SET_ENCRYPTION = HCI_SET_CONNECTION_ENCRYPTION


class FakeCtl:
    """Minimal controller: records set_upstream and send_command; events injected manually."""

    def __init__(self, name="ctl"):
        self.name = name
        self._on_hci_event = None
        self._on_acl_data = None
        self._on_sco_data = None
        self.sent: list[HCICommand] = []

    def set_upstream(self, on_hci_event=None, on_acl_data=None, on_sco_data=None):
        self._on_hci_event = on_hci_event
        self._on_acl_data = on_acl_data
        self._on_sco_data = on_sco_data

    async def send_command(self, command):
        self.sent.append(command)

    def inject_event(self, code: int, params: bytes):
        self._on_hci_event(HCIEvent.from_bytes(code, params))

    def inject_disconnect(self, handle, reason=0x13):
        params = bytes([0x00]) + handle.to_bytes(2, "little") + bytes([reason])
        self.inject_event(EventCode.DISCONNECTION_COMPLETE, params)


@dataclass
class FakePair:
    upstream: object = field(default_factory=FakeCtl)
    downstream: object = field(default_factory=FakeCtl)


class FakeAcceptController:
    def __init__(self):
        self._on_hci_event = None
        self._on_acl_data = None
        self._on_sco_data = None
        self.sent: list[HCICommand] = []
        self.accept_sent = asyncio.Event()

    def set_upstream(self, on_hci_event=None, on_acl_data=None, on_sco_data=None):
        self._on_hci_event = on_hci_event
        self._on_acl_data = on_acl_data
        self._on_sco_data = on_sco_data

    async def send_command(self, command):
        self.sent.append(command)
        if command.opcode == HCI_ACCEPT_CONNECTION_REQ:
            self.accept_sent.set()

    def inject_conn_request(self, link_type=ACL_LINK):
        params = PHONE_ADDR_LE + b"\x24\x04\x0C" + bytes([link_type])  # CoD arbitrary
        self._on_hci_event(HCIEvent.from_bytes(EventCode.CONNECTION_REQUEST, params))

    def inject_conn_complete(self, handle=0x0021):
        params = bytes([0x00]) + handle.to_bytes(2, "little") + PHONE_ADDR_LE + b"\x01\x00"
        self._on_hci_event(HCIEvent.from_bytes(EventCode.CONNECTION_COMPLETE, params))

    def inject_disconnect(self, handle, reason=0x13):
        params = bytes([0x00]) + handle.to_bytes(2, "little") + bytes([reason])
        self._on_hci_event(HCIEvent.from_bytes(EventCode.DISCONNECTION_COMPLETE, params))


class FakeConnectController:
    """Captures set_upstream callbacks + records sent commands; can inject events."""

    def __init__(self):
        # upstream callback with the same semantics as the real HCIController.set_upstream
        self.on_hci_event = None
        self._on_hci_event = None
        self._on_acl_data = None
        self._on_sco_data = None
        self.sent: list[HCICommand] = []
        # pre-scheduled queue of Connection Complete events to inject after each
        # Create_Connection. int means status (uses TARGET_LE); None means inject
        # nothing this time (simulates a timeout); tuple[int, bytes] means
        # (status, addr_le).
        self.complete_statuses: list[int | None | tuple[int, bytes]] = []

    def set_upstream(self, on_hci_event=None, on_acl_data=None, on_sco_data=None):
        self.on_hci_event = on_hci_event
        self._on_hci_event = on_hci_event
        self._on_acl_data = on_acl_data
        self._on_sco_data = on_sco_data

    async def send_command(self, command):
        self.sent.append(command)
        if command.opcode == HCI_CREATE_CONNECTION and self.complete_statuses:
            entry = self.complete_statuses.pop(0)
            if entry is None:
                return  # simulate timeout: inject no event
            if isinstance(entry, tuple):
                status, addr_le = entry
            else:
                status = entry
                addr_le = TARGET_LE
            if status == 0x00:
                params = bytes([0x00]) + (0x0011).to_bytes(2, "little") + addr_le + b"\x01\x00"
            else:
                params = bytes([status]) + (0x0000).to_bytes(2, "little") + addr_le + b"\x01\x00"
            self.on_hci_event(HCIEvent.from_bytes(EventCode.CONNECTION_COMPLETE, params))


class FakeAuthController:
    def __init__(self, auth_status: int = 0x00):
        self._on_hci_event = None
        self._on_acl_data = None
        self._on_sco_data = None
        self.sent: list = []
        self._auth_status = auth_status

    def set_upstream(self, on_hci_event=None, on_acl_data=None, on_sco_data=None):
        self._on_hci_event = on_hci_event
        self._on_acl_data = on_acl_data
        self._on_sco_data = on_sco_data

    async def send_command(self, command):
        self.sent.append(command)
        if command.opcode == _AUTH_REQUESTED:
            h = int.from_bytes(command.parameters[:2], "little")
            evt = HCIEvent.from_bytes(
                EventCode.AUTH_COMPLETE, bytes([self._auth_status]) + h.to_bytes(2, "little")
            )
            # simulate the controller asynchronously reporting the event (via the currently installed hook)
            asyncio.get_running_loop().call_soon(self._dispatch, evt)

    def _dispatch(self, evt):
        if self._on_hci_event is not None:
            self._on_hci_event(evt)


def _bare(pair=None, *, connect_timeout=1.0, accept_timeout=1.0, identities=None):
    """Bare MitmSession instance: minimal field set for direct `_xxx_on` calls, with event dispatch installed.

    Follows the spirit of the source test's `_bare_relay`; `_install_dispatch` routes
    injected events through the session's multi-point subscription dispatch
    (subscribe/unsubscribe is itself part of the path under test).
    """
    if pair is None:
        pair = FakePair()
    s = MitmSession.__new__(MitmSession)
    s._pair = pair
    s._identities = identities if identities is not None else {"bredr": None, "le": None}
    s._connect_timeout = connect_timeout
    s._accept_timeout = accept_timeout
    s._bredr_conns = {}
    s._subs = {"down": [], "up": []}
    s._ssp = {}
    s._forget_counts = {}
    s._sc_mirrored = False
    s._capture = NullTap()
    s._transform = None
    s._installed = False
    s._install_dispatch()
    return s, pair


# ============================================================ accept group (from _bredr_accept)
async def test_auto_accept_replies_accept_for_acl():
    pair = FakePair(downstream=FakeAcceptController())
    s, pair = _bare(pair)
    ctl = pair.downstream
    task = asyncio.ensure_future(s._accept_bredr_on(ctl, auto_accept=True))
    await asyncio.sleep(0)  # let the hook get installed
    ctl.inject_conn_request(ACL_LINK)
    await asyncio.wait_for(ctl.accept_sent.wait(), 1.0)
    assert ctl.sent[0].opcode == HCI_ACCEPT_CONNECTION_REQ
    assert ctl.sent[0].parameters[0:6] == PHONE_ADDR_LE
    assert ctl.sent[0].parameters[6] == 0x01  # role=slave, phone is master
    ctl.inject_conn_complete()
    assert await asyncio.wait_for(task, 1.0) == 0x0021


async def test_auto_accept_ignores_sco_request():
    pair = FakePair(downstream=FakeAcceptController())
    s, pair = _bare(pair)
    ctl = pair.downstream
    task = asyncio.ensure_future(s._accept_bredr_on(ctl, auto_accept=True))
    await asyncio.sleep(0)
    ctl.inject_conn_request(SCO_LINK)
    await asyncio.sleep(0.05)
    assert ctl.sent == []
    ctl.inject_conn_complete()
    await asyncio.wait_for(task, 1.0)


async def test_no_accept_when_auto_accept_off():
    pair = FakePair(downstream=FakeAcceptController())
    s, pair = _bare(pair)
    ctl = pair.downstream
    task = asyncio.ensure_future(s._accept_bredr_on(ctl, auto_accept=False))
    await asyncio.sleep(0)
    ctl.inject_conn_request(ACL_LINK)
    await asyncio.sleep(0.05)
    assert ctl.sent == []
    ctl.inject_conn_complete()
    await asyncio.wait_for(task, 1.0)


async def test_accept_timeout_raises_when_no_connection():
    """With a finite accept_timeout, timing out before a connection should raise TimeoutError, and the finally block should have unsubscribed."""
    pair = FakePair(downstream=FakeAcceptController())
    s, pair = _bare(pair, accept_timeout=0.05)
    with pytest.raises(asyncio.TimeoutError):
        await s._accept_bredr_on(pair.downstream, auto_accept=True)
    assert s._subs["down"] == []  # unsubscribed (subscription model, no callback replacement)


async def test_accept_timeout_none_waits_indefinitely():
    """accept_timeout=None waits indefinitely: no timeout return within a short window; resolves only when an event arrives."""
    pair = FakePair(downstream=FakeAcceptController())
    s, pair = _bare(pair, accept_timeout=None)
    ctl = pair.downstream
    task = asyncio.ensure_future(s._accept_bredr_on(ctl, auto_accept=True))
    await asyncio.sleep(0.1)  # far beyond any window that could "mistakenly use connect_timeout"
    assert not task.done()  # not cancelled / errored by timeout
    ctl.inject_conn_complete(handle=0x0042)
    assert await asyncio.wait_for(task, 1.0) == 0x0042


async def test_auto_accept_rejects_target_earbud_page():
    """Earbud paging the downstream impersonation device (treating us as its paired phone) -> must Reject and not resolve the connection.

    Field experience (2026-09-04): after pairing with upstream, the earbud treats
    downstream's impersonation broadcasts as another paired phone reconnecting; if
    auto-accept takes it as the "phone", A2DP gets occupied by the earbud's own
    requests and self-loop relaying may be triggered. A page to the target address
    must be rejected.
    """
    pair = FakePair(downstream=FakeAcceptController())
    # big-endian display order of PHONE_ADDR_LE 20E8AABBCCDD
    earbud_identity = ClonedIdentity(address="DD:CC:BB:AA:E8:20", address_type=0,
                                     adv_data=b"", scan_response=b"", name=None)
    s, pair = _bare(pair, identities={"bredr": earbud_identity, "le": None})
    ctl = pair.downstream
    task = asyncio.ensure_future(s._accept_bredr_on(ctl, auto_accept=True))
    await asyncio.sleep(0)      # let the hook get installed
    ctl.inject_conn_request(ACL_LINK)  # earbud pages the impersonation identity
    await asyncio.sleep(0.05)   # let the reject go out
    with pytest.raises(asyncio.TimeoutError):
        await task  # the earbud connection does not count as the phone, so the future never resolves -> timeout
    opcodes = [c.opcode for c in ctl.sent]
    assert HCI_REJECT_CONNECTION_REQ in opcodes, "耳机地址的 page 必须拒绝"
    assert HCI_ACCEPT_CONNECTION_REQ not in opcodes
    assert opcodes[0] == HCI_REJECT_CONNECTION_REQ
    assert ctl.sent[0].parameters[0:6] == PHONE_ADDR_LE


# ============================================================ connect group (from _connect_bredr_on)
def test_build_create_connection_params_layout():
    params = build_create_connection_params(TARGET_LE)
    assert params[0:6] == TARGET_LE
    assert int.from_bytes(params[6:8], "little") == 0xFC7E  # EDR multi-slot all on
    assert params[8] == 0x01   # page_scan_repetition_mode R1
    assert params[9] == 0x00   # reserved
    assert params[10:12] == b"\x00\x00"  # clock_offset unknown
    assert params[12] == 0x01  # allow_role_switch


def test_build_create_connection_params_allow_role_switch():
    assert build_create_connection_params(TARGET_LE, allow_role_switch=True)[12] == 0x01
    assert build_create_connection_params(TARGET_LE, allow_role_switch=False)[12] == 0x00


async def test_connect_returns_handle_on_success():
    pair = FakePair(upstream=FakeConnectController())
    s, pair = _bare(pair, connect_timeout=2.0)
    ctl = pair.upstream
    ctl.complete_statuses = [0x00]
    handle = await s._connect_bredr_on(ctl, TARGET)
    assert handle == 0x0011
    assert ctl.sent[0].opcode == HCI_CREATE_CONNECTION
    assert s._subs["up"] == []  # unsubscribed (subscription model, no callback replacement)


async def test_connect_retries_on_page_timeout():
    pair = FakePair(upstream=FakeConnectController())
    s, pair = _bare(pair, connect_timeout=2.0)
    ctl = pair.upstream
    ctl.complete_statuses = [0x04, 0x00]  # first page timeout, second succeeds
    handle = await s._connect_bredr_on(ctl, TARGET)
    assert handle == 0x0011
    assert len(ctl.sent) == 2  # Create_Connection sent twice


async def test_connect_raises_after_max_retries():
    pair = FakePair(upstream=FakeConnectController())
    s, pair = _bare(pair, connect_timeout=2.0)
    ctl = pair.upstream
    ctl.complete_statuses = [0x04, 0x04, 0x04]
    with pytest.raises(RuntimeError, match="Create_Connection"):
        await s._connect_bredr_on(ctl, TARGET, max_retries=3)


async def test_connect_ignores_mismatched_connection_complete():
    pair = FakePair(upstream=FakeConnectController())
    s, pair = _bare(pair, connect_timeout=2.0)
    ctl = pair.upstream
    # first inject an event with a mismatched address, succeed on the second try
    ctl.complete_statuses = [(0x00, WRONG_LE), 0x00]
    handle = await s._connect_bredr_on(ctl, TARGET, max_retries=2)
    assert handle == 0x0011
    opcodes = [c.opcode for c in ctl.sent]
    assert opcodes[0] == HCI_CREATE_CONNECTION
    assert opcodes[1] == 0x0408  # address mismatch caused a timeout, so Cancel was sent
    assert opcodes[2] == HCI_CREATE_CONNECTION


async def test_connect_cancels_on_timeout_then_retries():
    pair = FakePair(upstream=FakeConnectController())
    s, pair = _bare(pair, connect_timeout=2.0)
    ctl = pair.upstream
    # first inject no event (causing a timeout), succeed on the second; a Create_Connection_Cancel should be sent in between
    ctl.complete_statuses = [None, 0x00]
    handle = await s._connect_bredr_on(ctl, TARGET, max_retries=2)
    assert handle == 0x0011
    opcodes = [c.opcode for c in ctl.sent]
    assert opcodes[0] == HCI_CREATE_CONNECTION
    assert opcodes[1] == 0x0408  # HCI_Create_Connection_Cancel
    assert opcodes[2] == HCI_CREATE_CONNECTION


async def test_connect_reuses_tracked_earbud_connection_without_paging():
    """Earbud has reconnected to upstream on its own (recorded in the connection table) -> reuse the handle directly, send no page.

    Field experience (2026-09-04 phone-swap scenario): the earbud treats upstream as its
    paired phone and auto-reconnects after being released; paging again would just time
    out 5x30s while the phone gives up and disconnects. When the connection table has a
    record it must be reused immediately.
    """
    pair = FakePair(upstream=FakeConnectController())
    s, pair = _bare(pair, connect_timeout=2.0)
    ctl = pair.upstream
    s._bredr_conns = {TARGET_LE.hex(): 0x0042}
    handle = await s._connect_bredr_on(ctl, TARGET, max_retries=1)
    assert handle == 0x0042
    assert not any(c.opcode == HCI_CREATE_CONNECTION for c in ctl.sent)


async def test_connect_adopts_earbud_connection_arriving_between_attempts():
    """Between pages (not in_flight) the earbud reconnects on its own -> record it in the connection table, reuse on the next loop iteration.

    The old behavior treated such a "late" event as stale and ignored it, causing paging
    to continue against the already-reconnected earbud (timing out forever). New
    behavior: update the connection table, check at the top of the loop and reuse.
    """
    pair = FakePair(upstream=FakeConnectController())
    s, pair = _bare(pair, connect_timeout=2.0)
    ctl = pair.upstream
    ctl.complete_statuses = [None, None]  # neither page completes
    orig_send = ctl.send_command
    injected = asyncio.Event()

    async def send_with_stale_inject(command):
        await orig_send(command)
        # in the Cancel (non-in_flight window) after attempt 1 times out, the earbud reconnects on its own
        if command.opcode == 0x0408 and not injected.is_set():
            injected.set()
            params = bytes([0x00]) + (0x0042).to_bytes(2, "little") + TARGET_LE + b"\x01\x00"
            ctl.on_hci_event(HCIEvent.from_bytes(EventCode.CONNECTION_COMPLETE, params))

    ctl.send_command = send_with_stale_inject
    handle = await asyncio.wait_for(
        s._connect_bredr_on(ctl, TARGET, max_retries=5), 30.0
    )
    assert handle == 0x0042
    # only 1 Create_Connection sent: iteration 2 sees the connection-table hit and reuses it directly
    assert sum(1 for c in ctl.sent if c.opcode == HCI_CREATE_CONNECTION) == 1


# ============================================================ disconnect cascade group (from _make_watch)
async def test_phone_disconnect_triggers_target_disconnect():
    s, pair = _bare()
    link = s._make_link_state("bredr", phone_handle=0x0021, earbud_handle=0x0011,
                              relay=None)
    cb = s._make_watch("bredr", link, 0x0021, pair.upstream, 0x0011)
    s._subscribe("down", cb)
    pair.downstream.inject_disconnect(0x0021)
    await asyncio.sleep(0.05)
    assert pair.upstream.sent[0].opcode == HCI_DISCONNECT
    assert int.from_bytes(pair.upstream.sent[0].parameters[0:2], "little") == 0x0011
    assert link.link_lost.is_set()


async def test_disconnect_for_other_handle_ignored():
    s, pair = _bare()
    link = s._make_link_state("bredr", phone_handle=0x0021, earbud_handle=0x0011,
                              relay=None)
    cb = s._make_watch("bredr", link, 0x0021, pair.upstream, 0x0011)
    s._subscribe("down", cb)
    pair.downstream.inject_disconnect(0x0099)  # a different handle
    await asyncio.sleep(0.05)
    assert pair.upstream.sent == []
    assert not link.link_lost.is_set()


async def test_second_disconnect_is_idempotent():
    s, pair = _bare()
    link = s._make_link_state("bredr", phone_handle=0x0021, earbud_handle=0x0011,
                              relay=None)
    cb = s._make_watch("bredr", link, 0x0021, pair.upstream, 0x0011)
    s._subscribe("down", cb)
    pair.downstream.inject_disconnect(0x0021)
    await asyncio.sleep(0.05)
    pair.downstream.inject_disconnect(0x0021)  # duplicate disconnect; the guard should block the second one
    await asyncio.sleep(0.05)
    assert len(pair.upstream.sent) == 1
    assert pair.upstream.sent[0].opcode == HCI_DISCONNECT
    assert link.link_lost.is_set()


# ============================================================ graceful disconnect group
async def test_graceful_disconnect_sends_and_waits():
    """_graceful_disconnect_on: while the link is still up, send an extra HCI_Disconnect and wait for Disconnection_Complete."""
    s, pair = _bare()
    task = asyncio.ensure_future(
        s._graceful_disconnect_on(pair.downstream, 0x0021, timeout=1.0)
    )
    await asyncio.sleep(0.05)
    # HCI_DISCONNECT already sent (reason must be 0x13: 0x16 is the event-side code, BE200 rejects it with 0x12)
    assert pair.downstream.sent[0].opcode == HCI_DISCONNECT
    assert int.from_bytes(pair.downstream.sent[0].parameters[0:2], "little") == 0x0021
    assert pair.downstream.sent[0].parameters[2] == 0x13
    assert not task.done()  # waiting for the event
    pair.downstream.inject_disconnect(0x0021, reason=0x16)
    await asyncio.wait_for(task, timeout=1.0)  # returns once the event lands


async def test_graceful_disconnect_already_down_times_out_quietly():
    """When the link is already down (no event will come): after sending, wait out the timeout and return quietly without raising."""
    s, pair = _bare()
    await s._graceful_disconnect_on(pair.downstream, 0x0021, timeout=0.05)
    assert pair.downstream.sent[0].opcode == HCI_DISCONNECT


async def test_graceful_disconnect_tolerates_command_error():
    """When the link is already down and the controller errors on HCI_Disconnect: swallow the error, do not propagate it."""
    class ErrCtl(FakeCtl):
        async def send_command(self, command):
            raise RuntimeError("unknown connection handle")

    pair = FakePair(downstream=ErrCtl())
    s, pair = _bare(pair)
    await s._graceful_disconnect_on(pair.downstream, 0x0021, timeout=0.05)  # must not raise


# ============================================================ secure-link + scan group
async def test_auth_success_then_set_encryption():
    pair = FakePair(upstream=FakeAuthController(auth_status=0x00))
    s, pair = _bare(pair)
    task = asyncio.ensure_future(s._secure_target_link_on(pair.upstream, HANDLE))
    await asyncio.wait_for(task, 5.0)
    opcodes = [c.opcode for c in pair.upstream.sent]
    assert _AUTH_REQUESTED in opcodes, "必须主动发 Authentication_Requested"
    assert _SET_ENCRYPTION in opcodes, "认证成功后必须 Set_Connection_Encryption"
    assert opcodes.index(_AUTH_REQUESTED) < opcodes.index(_SET_ENCRYPTION)
    # Set_Connection_Encryption parameters: handle (2 LE) + enable (0x01)
    enc = next(c for c in pair.upstream.sent if c.opcode == _SET_ENCRYPTION)
    assert enc.parameters == HANDLE.to_bytes(2, "little") + bytes([0x01])
    assert s._subs["up"] == []  # unsubscribed (subscription model, no callback replacement)


async def test_auth_failure_skips_encryption():
    pair = FakePair(upstream=FakeAuthController(auth_status=0x05))
    s, pair = _bare(pair)
    task = asyncio.ensure_future(s._secure_target_link_on(pair.upstream, HANDLE))
    await asyncio.wait_for(task, 5.0)
    opcodes = [c.opcode for c in pair.upstream.sent]
    assert _AUTH_REQUESTED in opcodes
    assert _SET_ENCRYPTION not in opcodes, "认证失败不得启用加密"


async def test_ensure_phone_visible_reopens_scan_each_round():
    """Re-open inquiry+page scan before waiting for the phone in each round.

    Field experience: the Intel controller automatically pauses inquiry scan while an
    ACL is being established and does not resume it after the link drops -> after the
    first connection the phone can no longer find the impersonation device. The
    reconnect loop must resend Scan_Enable=0x03 every round.
    """
    s, pair = _bare()
    await s._ensure_phone_visible()
    scan = [c for c in pair.downstream.sent if c.opcode == HCI_WRITE_SCAN_ENABLE]
    assert scan and scan[-1].parameters == bytes([0x03])


# ============================================================ auth-failure self-heal group
# Field experience (2026-09-04): after the relay connects to the earbud, Authentication_Requested
# finds the earbud-side bond expired (key mismatch) -> the link dies with 0x05, and the earbud then
# self-heals (deletes its own bond and re-pairs); the relay must mirror this: drop the local stale
# key and retry the whole round (accept -> connect -> secure).
class FakeSsp:
    """Stand-in for SspTermination that records forget_key calls."""

    def __init__(self, *, has_key: bool = True, last_link_key_type=None):
        self._link_keys = {TARGET: b"\x00" * 16} if has_key else {}
        self.forgotten: list[str] = []
        self.last_link_key_type = last_link_key_type

    def forget_key(self, addr: str) -> None:
        self.forgotten.append(addr)
        for known in [k for k in self._link_keys if k.upper() == addr.upper()]:
            del self._link_keys[known]


def _ident():
    return ClonedIdentity(address=TARGET, address_type=0, adv_data=b"",
                          scan_response=b"", name=None)


async def _drive_phone_connection(ctl):
    """Drive one full phone connect-in round: Connection_Request -> auto accept -> Complete.

    The accept wait is resident and re-armed each round: an injection may land in the
    event vacuum between two rounds and be dropped, so resend within a short window
    until it is actually accepted.
    """
    for _ in range(50):
        ctl.inject_conn_request(ACL_LINK)
        try:
            await asyncio.wait_for(ctl.accept_sent.wait(), 0.2)
            break
        except asyncio.TimeoutError:
            continue
    else:
        raise AssertionError("手机连接未被 accept")
    ctl.accept_sent.clear()
    ctl.inject_conn_complete()


async def _wait_until(pred, timeout=5.0):
    async def _poll():
        while not pred():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_poll(), timeout)


async def test_auth_failure_forgets_key_and_retries():
    """bring_up auth failure + a local stale key present -> forget_key, then redo the whole round (accept again)."""
    pair = FakePair(downstream=FakeAcceptController(), upstream=FakeConnectController())
    s, pair = _bare(pair, identities={"bredr": _ident(), "le": None})
    ssp = FakeSsp()
    s._ssp = {"target": ssp}
    s.connected = asyncio.Event()
    s._br = None
    s._le = None
    s._pending_down_acl = {}
    for ctl in (pair.downstream, pair.upstream):
        ctl.acl_packet_length = 27

        async def _send_acl(handle, pb_flag, data):
            pass

        ctl.send_acl_data = _send_acl
    pair.upstream.complete_statuses = [0x00, 0x00]

    bring_up_calls: list = []
    bring_up_ok = {1: False, 2: True}  # round 1 auth fails, round 2 succeeds

    async def fake_bring_up(link):
        bring_up_calls.append(link)
        return bring_up_ok[len(bring_up_calls)]

    s._bredr_bring_up = fake_bring_up

    task = asyncio.ensure_future(s._run_link("bredr"))
    # round 1: phone connects in -> connect target -> bring_up fails -> forget -> cleanup, back to accept
    await _drive_phone_connection(pair.downstream)
    await _wait_until(lambda: ssp.forgotten == [TARGET] and len(bring_up_calls) == 1)
    # round 2: accept awaited again, connect succeeds again, bring_up succeeds -> resident wait for disconnect
    await _drive_phone_connection(pair.downstream)
    await _wait_until(lambda: len(bring_up_calls) == 2)
    assert ssp.forgotten == [TARGET]  # round 2 succeeded, no further forget
    assert s._forget_counts.get(TARGET) == 1
    # cleanup: drop the phone side -> cleanup, back to round-3 accept; let the cancel land
    pair.downstream.inject_disconnect(0x0021)
    await _wait_until(lambda: s._br is None)  # finally cleanup done, already back waiting for round 3
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)  # let cancelled child tasks land, avoiding dangling tasks


async def test_forget_count_capped_at_two_consecutive_failures():
    """At most 2 consecutive forgets for the same address: guards against hot-rotating "never paired" devices; success-reset is tested separately."""
    pair = FakePair()
    s, pair = _bare(pair, identities={"bredr": _ident(), "le": None})
    ssp = FakeSsp()
    s._ssp = {"target": ssp}

    assert s._bredr_forget_stale_key() is True
    assert ssp.forgotten == [TARGET]
    assert s._forget_counts[TARGET] == 1

    ssp._link_keys[TARGET] = b"\x01" * 16  # simulate a key reappearing before the retry (re-persisted next round)
    assert s._bredr_forget_stale_key() is True
    assert s._forget_counts[TARGET] == 2

    ssp._link_keys[TARGET] = b"\x02" * 16
    assert s._bredr_forget_stale_key() is False  # cap reached, no further forget
    assert ssp.forgotten == [TARGET, TARGET]
    assert s._forget_counts[TARGET] == 2


async def test_forget_skipped_when_no_stored_key():
    """No stored key for this address (a pure not-paired failure) -> do not forget, do not count, return to waiting normally."""
    pair = FakePair()
    s, pair = _bare(pair, identities={"bredr": _ident(), "le": None})
    ssp = FakeSsp(has_key=False)
    s._ssp = {"target": ssp}
    assert s._bredr_forget_stale_key() is False
    assert ssp.forgotten == []
    assert s._forget_counts == {}


async def test_auth_success_clears_forget_count():
    """Auth success (including reusing an existing bond) -> the forget count for that address is cleared."""
    pair = FakePair(upstream=FakeAuthController(auth_status=0x00))
    s, pair = _bare(pair, identities={"bredr": _ident(), "le": None})
    s._ssp = {"target": FakeSsp(last_link_key_type=0x04)}
    s._forget_counts = {TARGET: 2}
    await asyncio.wait_for(s._secure_target_link_on(pair.upstream, HANDLE), 5.0)
    assert s._forget_counts == {}


# ============================================================ SC capability mirror group
# After the first successful target pairing, the Link_Key_Notification key type reflects the sink's
# SC capability: 0x04/0x05 = SC-derived key (sink supports SC); 0x00-0x03 = legacy (sink has no BR SC).
# Behavior should match the selected device as closely as possible: downstream also disables SC host
# support (affects only subsequent phone pairings).
async def test_mirror_disables_downstream_sc_when_sink_legacy():
    pair = FakePair(upstream=FakeAuthController(auth_status=0x00))
    s, pair = _bare(pair, identities={"bredr": _ident(), "le": None})
    s._ssp = {"target": FakeSsp(last_link_key_type=0x03)}  # legacy key
    await asyncio.wait_for(s._secure_target_link_on(pair.upstream, HANDLE), 5.0)
    writes = [c for c in pair.downstream.sent
              if c.opcode == HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT]
    assert len(writes) == 1, "sink 无 BR SC,下游必须关 SC host support"
    assert writes[0].parameters == bytes([0x00])


async def test_mirror_skipped_when_sink_supports_sc():
    pair = FakePair(upstream=FakeAuthController(auth_status=0x00))
    s, pair = _bare(pair, identities={"bredr": _ident(), "le": None})
    s._ssp = {"target": FakeSsp(last_link_key_type=0x04)}  # SC-derived key
    await asyncio.wait_for(s._secure_target_link_on(pair.upstream, HANDLE), 5.0)
    writes = [c for c in pair.downstream.sent
              if c.opcode == HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT]
    assert writes == [], "sink 支持 SC,下游保持开启,不发 Write 命令"


async def test_mirror_applies_once_per_session():
    pair = FakePair(upstream=FakeAuthController(auth_status=0x00))
    s, pair = _bare(pair, identities={"bredr": _ident(), "le": None})
    s._ssp = {"target": FakeSsp(last_link_key_type=0x02)}
    await asyncio.wait_for(s._secure_target_link_on(pair.upstream, HANDLE), 5.0)
    await asyncio.wait_for(s._secure_target_link_on(pair.upstream, HANDLE), 5.0)
    writes = [c for c in pair.downstream.sent
              if c.opcode == HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT]
    assert len(writes) == 1, "镜像每 session 只应用一次"


async def test_mirror_not_spent_by_bond_reuse_then_legacy_still_mirrors():
    """Reusing an existing bond (unknown key type) does not consume the mirror slot; a later brand-new legacy pairing can still trigger it.

    When the relay restarts with a key file, the first-round auth goes through LKR
    reuse with no Link_Key_Notification, so last_link_key_type stays None — this must
    NOT set _sc_mirrored, otherwise a later brand-new legacy pairing in the same
    session would never get the mirror.
    """
    pair = FakePair(upstream=FakeAuthController(auth_status=0x00))
    s, pair = _bare(pair, identities={"bredr": _ident(), "le": None})
    ssp = FakeSsp(last_link_key_type=None)
    s._ssp = {"target": ssp}
    await asyncio.wait_for(s._secure_target_link_on(pair.upstream, HANDLE), 5.0)
    assert not s._sc_mirrored, "bond 复用(无 key type)不得消耗镜像名额"
    ssp.last_link_key_type = 0x03  # a brand-new later pairing in the same session: legacy key
    await asyncio.wait_for(s._secure_target_link_on(pair.upstream, HANDLE), 5.0)
    writes = [c for c in pair.downstream.sent
              if c.opcode == HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT]
    assert len(writes) == 1, "后续 legacy 配对必须补发镜像 Write"
