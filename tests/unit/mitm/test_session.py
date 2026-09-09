"""MitmSession skeleton: multi-subscriber events + ACL if/else dispatch + impersonate orchestration."""
import asyncio
from dataclasses import dataclass, field

import pytest

from pybluehost.cli.app.mitm.recon import ClonedIdentity
from pybluehost.cli.app.mitm.relay import AclRelay, RelaySide
from pybluehost.cli.app.mitm.session import MitmSession
from pybluehost.hci.constants import EventCode, HCI_READ_BD_ADDR
from pybluehost.hci.packets import HCIACLData, HCICommand, HCIEvent


class FakeCtl:
    """Minimal controller: records set_upstream and send_command; events are
    injected manually."""

    def __init__(self, name="ctl"):
        self.name = name
        self._on_hci_event = None
        self._on_acl_data = None
        self._on_sco_data = None
        self.commands: list[HCICommand] = []
        self.acl_sent: list[tuple[int, int, bytes]] = []  # send_acl_data recording
        self.bd_addr = bytes.fromhex("020304050607")      # Read_BD_ADDR reply value
        # buffer parameters (None = unknown, session falls back to 27; matches HCIController attribute semantics)
        self.acl_packet_length = None
        self.le_acl_packet_length = None
        # SSP listeners registered by SspTermination.attach() (recorded only, not dispatched)
        self.listeners: list[tuple[str, object]] = []

    def set_upstream(self, on_hci_event=None, on_acl_data=None, on_sco_data=None):
        self._on_hci_event = on_hci_event
        self._on_acl_data = on_acl_data
        self._on_sco_data = on_sco_data

    async def send_command(self, command):
        self.commands.append(command)
        if command.opcode == HCI_READ_BD_ADDR:
            # command complete event: num(1)+opcode(2)+status(1)+bd_addr(6); session takes [-6:]
            return HCIEvent.from_bytes(
                EventCode.COMMAND_COMPLETE,
                bytes([0x01]) + command.opcode.to_bytes(2, "little")
                + bytes([0x00]) + self.bd_addr,
            )

    def on_le_ltk_request(self, cb):
        self.listeners.append(("le_ltk_request", cb))

    async def send_acl_data(self, handle: int, pb_flag: int, data: bytes):
        self.acl_sent.append((handle, pb_flag, data))

    # The four SSP listener registration methods required by SspTermination.attach() (matching HCIController).
    def on_io_capability_request(self, cb):
        self.listeners.append(("io_capability_request", cb))

    def on_user_confirmation_request(self, cb):
        self.listeners.append(("user_confirmation_request", cb))

    def on_link_key_notification(self, cb):
        self.listeners.append(("link_key_notification", cb))

    def on_link_key_request(self, cb):
        self.listeners.append(("link_key_request", cb))

    def inject_event(self, code: int, params: bytes = b""):
        self._on_hci_event(HCIEvent.from_bytes(code, params))


@dataclass
class FakePair:
    upstream: object = field(default_factory=FakeCtl)
    downstream: object = field(default_factory=FakeCtl)
    pair_closed: list = field(default_factory=list)

    async def close(self):
        self.pair_closed.append(True)


IDENT = ClonedIdentity(address="38:D5:18:CD:52:F7", address_type=0, adv_data=b"",
                       scan_response=b"", name="X", class_of_device=None)


def _mk_session(identities=None):
    pair = FakePair()
    s = MitmSession(
        pair,
        identities=identities if identities is not None else {"bredr": IDENT, "le": None},
    )
    return s, pair


def _acl(handle: int, data: bytes = b"\x01\x00\x04\x00\x2A") -> HCIACLData:
    return HCIACLData(handle=handle, pb_flag=0x02, data=data)


def _recording_relay(phone_handle: int, target_handle: int):
    """Build a relay in the real shape: one RelaySide per handle, sharing a
    single sent list."""
    sent = []

    async def send_acl(h, pb, d):
        sent.append((h, pb, d))

    phone = RelaySide(name="phone", handle=phone_handle,
                      acl_max_payload=27, send_acl=send_acl)
    target = RelaySide(name="target", handle=target_handle,
                       acl_max_payload=27, send_acl=send_acl)
    return AclRelay(phone_side=phone, target_side=target), sent


async def test_event_dispatch_fans_out_to_all_subscribers():
    s, pair = _mk_session()
    s._install_dispatch()
    seen_down, seen_down2 = [], []
    s._subscribe("down", seen_down.append)
    s._subscribe("down", seen_down2.append)  # both subscribers should receive
    seen_up = []
    s._subscribe("up", seen_up.append)       # cross-side isolation: down events must not reach up
    pair.downstream.inject_event(EventCode.CONNECTION_REQUEST, b"x")
    assert len(seen_down) == 1 and len(seen_down2) == 1
    assert seen_up == []                     # a down injection only fans out to down subscribers
    s._unsubscribe("down", seen_down.append)
    pair.downstream.inject_event(EventCode.CONNECTION_REQUEST, b"x")
    assert len(seen_down) == 1 and len(seen_down2) == 2  # only the second subscriber remains


async def test_subscribe_never_replaces_controller_callback():
    """Single-owner contract pinned: subscribe/unsubscribe must never re-issue
    set_upstream.

    Regression guard: if anyone in the Task 7/8 methods calls set_upstream on
    the controller again (the old orchestrator's prev-forward chain-overwrite
    pattern), the already-registered event hooks would be silently replaced —
    this test is what catches that.
    """
    s, pair = _mk_session()
    s._install_dispatch()
    disp_down = pair.downstream._on_hci_event
    disp_up = pair.upstream._on_hci_event

    def cb(event):
        pass

    s._subscribe("down", cb)
    s._unsubscribe("down", cb)
    assert pair.downstream._on_hci_event is disp_down
    assert pair.upstream._on_hci_event is disp_up


async def test_unsubscribe_missing_is_silent():
    s, pair = _mk_session()
    s._install_dispatch()
    s._unsubscribe("down", lambda e: None)  # must not raise even if missing


async def test_acl_dispatch_routes_by_handle_if_else():
    """Each LE/BR handle goes into its own relay; unknown handles are ignored."""
    s, pair = _mk_session()
    le_relay, le_sent = _recording_relay(0x10, 0x11)
    br_relay, br_sent = _recording_relay(0x20, 0x21)
    s._le = s._make_link_state("le", phone_handle=0x10, earbud_handle=0x11, relay=le_relay)
    s._br = s._make_link_state("bredr", phone_handle=0x20, earbud_handle=0x21, relay=br_relay)

    await s._on_down_acl(_acl(0x10))   # → LE relay
    await s._on_down_acl(_acl(0x20))   # → BR relay
    await s._on_down_acl(_acl(0x99))   # unknown → ignored
    await s._on_up_acl(_acl(0x11))
    await s._on_up_acl(_acl(0x21))
    await asyncio.gather(s._le.relay.flush(), s._br.relay.flush())
    assert len(le_sent) == 2   # down 0x10 + up 0x11
    assert len(br_sent) == 2
    for h, _, _ in br_sent:
        assert h in (0x20, 0x21)
    await s._le.relay.stop()
    await s._br.relay.stop()


async def test_phone_acl_before_link_is_buffered_and_flushed():
    """Two-connection window: ACL sent by the phone after accept but before
    the link is built is buffered, then flushed into the relay in order."""
    s, pair = _mk_session()
    relay, sent = _recording_relay(0x10, 0x11)
    s._arm_pending(0x10)

    first, second = b"\x01\x00\x04\x00\x2A", b"\x01\x00\x04\x00\x2B"
    await s._on_down_acl(_acl(0x10, first))
    await s._on_down_acl(_acl(0x10, second))
    await s._on_down_acl(_acl(0x99))              # unknown handle: ignored as before
    assert sent == []                             # relay not built yet, nothing may reach the other side
    assert [a.data for a in s._pending_down_acl[0x10]] == [first, second]

    # link built: setattr (the same moment as connected.set() in _run_link) → flush
    link = s._make_link_state("le", phone_handle=0x10, earbud_handle=0x11,
                              relay=relay)
    s._le = link
    await s._flush_pending(link)
    await relay.flush()
    assert [d for _, _, d in sent] == [first, second]   # FIFO
    assert 0x10 not in s._pending_down_acl              # the handle is popped before flushing
    # after disarming, new frames take the normal path straight to the relay, no more buffering
    third = b"\x01\x00\x04\x00\x2C"
    await s._on_down_acl(_acl(0x10, third))
    await relay.flush()
    assert [d for _, _, d in sent] == [first, second, third]
    assert 0x10 not in s._pending_down_acl
    await relay.stop()


async def test_pending_buffer_is_bounded():
    """The buffer is bounded (maxlen=64): on overflow the oldest entries are
    evicted, preventing the two-connection window from running away in memory."""
    s, pair = _mk_session()
    s._arm_pending(0x10)
    for i in range(70):
        await s._on_down_acl(_acl(0x10, bytes([i & 0xFF])))
    assert len(s._pending_down_acl[0x10]) == 64
    assert s._pending_down_acl[0x10][0].data == b"\x06"   # the oldest 6 entries were evicted
    assert s._pending_down_acl[0x10][-1].data == b"\x45"  # the newest is still at the tail


async def test_pending_cleared_when_link_not_built():
    """Abandon paths such as target-connect failure: disarm + clear the buffer,
    so stale frames do not leak into the next round."""
    s, pair = _mk_session()
    s._arm_pending(0x10)
    await s._on_down_acl(_acl(0x10))
    assert len(s._pending_down_acl[0x10]) == 1
    s._disarm_pending(0x10)  # called before `continue` on _run_link target-connect failure / in finally cleanup
    assert 0x10 not in s._pending_down_acl
    # after disarming, frames for that handle fall back to drop semantics: no more buffering
    await s._on_down_acl(_acl(0x10))
    assert 0x10 not in s._pending_down_acl


async def test_pending_buffer_isolated_from_live_sibling_link():
    """Keyed by handle: the live link's (0x30) relay does not consume frames
    from a sibling window (0x10)."""
    s, pair = _mk_session()
    live_relay, live_sent = _recording_relay(0x30, 0x31)
    s._le = s._make_link_state("le", phone_handle=0x30, earbud_handle=0x31,
                               relay=live_relay)
    s._arm_pending(0x10)
    await s._on_down_acl(_acl(0x10))
    assert live_sent == []                        # the live link's relay is untouched
    assert len(s._pending_down_acl[0x10]) == 1    # the frame still goes into its own window queue as usual


async def test_run_requires_identity(monkeypatch):
    """No identity at all → a clear error."""
    s, pair = _mk_session(identities={"bredr": None, "le": None})
    with pytest.raises(RuntimeError):
        await s.run()


async def test_run_impersonates_each_section(monkeypatch):
    """Calls the impersonate for whichever section has an identity; sends
    commands on downstream."""
    s, pair = _mk_session(identities={"bredr": IDENT, "le": None})
    calls = []

    async def fake_bredr(ctl, ident, *, clone_address):
        calls.append(("bredr", ident.name))

    async def fake_le(ctl, ident, *, clone_address):
        calls.append(("le", ident.name))

    # Task 6's _accept_bredr is still a NotImplementedError stub; swap in a
    # resident blocking wait so that run() stops at "waiting for phone
    # connection" (test intent: the link wait stays resident).
    async def fake_accept():
        await asyncio.Event().wait()

    monkeypatch.setattr(
        "pybluehost.cli.app.mitm.bredr_impersonate.start_bredr_impersonation",
        fake_bredr,
    )
    monkeypatch.setattr(
        "pybluehost.cli.app.mitm.impersonate.start_impersonation", fake_le
    )
    monkeypatch.setattr(s, "_accept_bredr", fake_accept)
    task = asyncio.ensure_future(s.run())
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)  # let the cancelled _run_link child tasks settle, avoiding dangling tasks
    assert calls == [("bredr", "X")]
    # startup section: SSP enabled on upstream
    from pybluehost.hci.constants import HCI_WRITE_SIMPLE_PAIRING_MODE
    up_opcodes = [c.opcode for c in pair.upstream.commands]
    assert HCI_WRITE_SIMPLE_PAIRING_MODE in up_opcodes


async def test_teardown_disables_scan_and_closes():
    s, pair = _mk_session()
    closed = []

    async def fake_close():
        closed.append(True)

    s._capture_close = fake_close
    await s.teardown()
    from pybluehost.hci.constants import HCI_WRITE_SCAN_ENABLE
    for ctl in (pair.upstream, pair.downstream):
        opcodes = [c.opcode for c in ctl.commands]
        assert HCI_WRITE_SCAN_ENABLE in opcodes
    assert closed == [True]
    assert pair.pair_closed == [True]
