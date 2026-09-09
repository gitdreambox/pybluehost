import asyncio

from pybluehost.cli.app.mitm.acl import (
    CID_ATT,
    CID_SMP,
    PB_FIRST_FLUSH,
    RelayDirection,
)
from pybluehost.cli.app.mitm.relay import AclRelay, RelaySide
from pybluehost.cli.app.mitm.transform import ReplaceRule, RegexReplacer
from pybluehost.hci.packets import HCIACLData


def _make_side(name, handle, max_payload):
    sent = []

    async def send_acl(h, pb, data):
        sent.append((h, pb, data))

    side = RelaySide(name=name, handle=handle, acl_max_payload=max_payload, send_acl=send_acl)
    return side, sent


async def test_att_pdu_relayed_to_peer():
    phone, phone_sent = _make_side("phone", 0x40, 27)
    target, target_sent = _make_side("target", 0x11, 27)
    relay = AclRelay(phone_side=phone, target_side=target)

    acl = HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH,
                     data=bytes([0x03, 0x00, 0x04, 0x00, 0x0A, 0x03, 0x00]))
    await relay.on_phone_acl(acl)
    await relay.flush()  # after decoupling, forwarding happens in a background drain; wait for the queue to drain before asserting

    assert len(target_sent) == 1
    h, pb, data = target_sent[0]
    assert h == 0x11
    assert data == bytes([0x03, 0x00, 0x04, 0x00, 0x0A, 0x03, 0x00])
    assert phone_sent == []
    await relay.stop()


async def test_relay_refragments_for_small_peer_buffer():
    phone, _ = _make_side("phone", 0x40, 27)
    target, target_sent = _make_side("target", 0x11, 4)
    relay = AclRelay(phone_side=phone, target_side=target)

    payload = bytes(range(9))
    pdu = bytes([0x09, 0x00, 0x04, 0x00]) + payload
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=pdu))
    await relay.flush()

    assert len(target_sent) == 4
    assert b"".join(d for _, _, d in target_sent) == pdu
    assert target_sent[0][1] == 0x00
    assert all(pb == 0x01 for _, pb, _ in target_sent[1:])
    await relay.stop()


async def test_smp_cid_terminated_not_relayed():
    phone, phone_sent = _make_side("phone", 0x40, 27)
    target, target_sent = _make_side("target", 0x11, 27)
    seen = []

    async def smp_handler(side_name, cid, payload):
        seen.append((side_name, cid, payload))

    relay = AclRelay(phone_side=phone, target_side=target, smp_handler=smp_handler)

    smp = bytes([0x01, 0x00, 0x06, 0x00, 0x01])
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=smp))

    assert target_sent == []
    assert seen == [("phone", CID_SMP, bytes([0x01]))]


async def test_disconnect_hook_invoked():
    phone, _ = _make_side("phone", 0x40, 27)
    target, _ = _make_side("target", 0x11, 27)
    closed = []
    relay = AclRelay(phone_side=phone, target_side=target,
                     on_teardown=lambda: closed.append(True))
    await relay.teardown()
    assert closed == [True]


async def test_teardown_without_hook_is_safe():
    phone, _ = _make_side("phone", 0x40, 27)
    target, _ = _make_side("target", 0x11, 27)
    relay = AclRelay(phone_side=phone, target_side=target)  # on_teardown defaults to None
    await relay.teardown()  # just must not raise (the default NullTap capture is also closed)


async def test_async_teardown_hook_is_awaited():
    phone, _ = _make_side("phone", 0x40, 27)
    target, _ = _make_side("target", 0x11, 27)
    closed = []

    async def on_teardown():
        closed.append("async")

    relay = AclRelay(phone_side=phone, target_side=target, on_teardown=on_teardown)
    await relay.teardown()
    assert closed == ["async"]


async def test_smp_dropped_without_handler_warns(caplog):
    phone, phone_sent = _make_side("phone", 0x40, 27)
    target, target_sent = _make_side("target", 0x11, 27)
    relay = AclRelay(phone_side=phone, target_side=target)  # no smp_handler

    smp = bytes([0x01, 0x00, 0x06, 0x00, 0x01])
    import logging
    with caplog.at_level(logging.WARNING):
        await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=smp))

    assert target_sent == []  # still not forwarded
    assert any("smp_handler" in r.message for r in caplog.records)


async def test_forward_happens_before_capture():
    """Forwarding (send_acl) must happen before capture (capture.on_pdu); the
    capture must not block the forwarding critical path."""
    events: list[str] = []

    async def send_acl(h, pb, d):
        events.append("send")

    class _OrderTap:
        async def on_pdu(self, direction, handle, pdu):
            events.append("capture")
        async def close(self):
            pass

    phone = RelaySide(name="phone", handle=0x40, acl_max_payload=27, send_acl=send_acl)
    target = RelaySide(name="target", handle=0x11, acl_max_payload=27, send_acl=send_acl)

    relay = AclRelay(phone_side=phone, target_side=target, capture=_OrderTap())
    pdu = bytes([0x03, 0x00, 0x04, 0x00, 0x0A, 0x03, 0x00])
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=pdu))
    await relay.flush()  # wait for the drain to finish (both send and capture run inside the drain)

    # at least one send, and capture is last (after all sends)
    assert "send" in events and events[-1] == "capture"
    assert events.index("capture") > events.index("send")
    await relay.stop()


# ---------------------------------------------------------------------------
# Amplifier protection: decoupled outbound (bounded queue + background drain)
# ---------------------------------------------------------------------------

def _mk_pdu(i: int) -> bytes:
    """l2cap basic: len=1, cid=0x0004 (ATT), payload=[i]."""
    return bytes([0x01, 0x00, 0x04, 0x00, i])


async def test_blocking_peer_does_not_stall_source_read():
    """When dst.send_acl is wedged, on_phone_acl must return immediately and
    not back-pressure the src read loop."""
    gate = asyncio.Event()  # never set → simulates a wedged dst dongle TX

    async def blocking_send(h, pb, d):
        await gate.wait()

    phone = RelaySide(name="phone", handle=0x40, acl_max_payload=27, send_acl=blocking_send)
    target = RelaySide(name="target", handle=0x11, acl_max_payload=27, send_acl=blocking_send)
    relay = AclRelay(phone_side=phone, target_side=target)

    # on_phone_acl should return immediately (not wait for the stuck send); a
    # wait_for timeout means failure.
    await asyncio.wait_for(
        relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=_mk_pdu(0))),
        timeout=0.5,
    )
    await relay.stop()


async def test_queue_full_drops_oldest_and_counts():
    """dst wedged + queue full → drop down to the **low-water mark** (not just
    1 entry), and on_phone_acl does not block.

    An isochronous stream's backlog does not drain by itself; dropping to the
    low-water mark pulls latency back down immediately and frees headroom.
    """
    gate = asyncio.Event()

    async def blocking_send(h, pb, d):
        await gate.wait()

    phone = RelaySide(name="phone", handle=0x40, acl_max_payload=27, send_acl=blocking_send)
    target = RelaySide(name="target", handle=0x11, acl_max_payload=27, send_acl=blocking_send)
    relay = AclRelay(phone_side=phone, target_side=target, egress_max=4, egress_low=1)

    # entry 0: the drain picks it up and gets stuck in send (gate never opens).
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=_mk_pdu(0)))
    await asyncio.sleep(0.05)  # let the drain actually enter the blocked send
    # fill the queue (capacity 4): now 4 in the queue, 1 stuck in the drain.
    for i in range(1, 5):
        await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=_mk_pdu(i)))
    # one more → queue full → drop down to low-water 1 (drops 3), then enqueue this new one.
    await asyncio.wait_for(
        relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=_mk_pdu(5))),
        timeout=0.5,
    )
    assert relay.dropped >= 3  # one-shot drop to the low-water mark, not just 1 entry
    # the queue is pulled back near the low-water mark (low-water 1 + 1 newly enqueued)
    eg = relay._egress["target"]
    assert eg.queue.qsize() <= 2
    await relay.stop()


async def test_stop_cancels_drain_and_drops_further_input():
    phone, _ = _make_side("phone", 0x40, 27)
    target, target_sent = _make_side("target", 0x11, 27)
    relay = AclRelay(phone_side=phone, target_side=target)

    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=_mk_pdu(0)))
    assert relay._egress  # drain tasks already created
    await relay.stop()
    assert all(eg.task.done() for eg in relay._egress.values())

    # PDUs received after stop() are dropped directly: no more enqueue/send.
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=_mk_pdu(1)))
    await asyncio.sleep(0.02)
    assert len(target_sent) <= 1  # at most entry 0 was sent (likely not even that, due to stop)


# ---------------------------------------------------------------------------
# transform hook: PDU-level replacement (fail-open); default None behaves
# byte-for-byte identical to now
# ---------------------------------------------------------------------------

async def test_transform_rewrites_payload_and_l2cap_length():
    """After a variable-length replacement, the L2CAP length header must be
    rewritten to the new payload."""
    phone, _ = _make_side("phone", 0x40, 27)
    target, target_sent = _make_side("target", 0x11, 27)
    relay = AclRelay(phone_side=phone, target_side=target,
                     transform=RegexReplacer([ReplaceRule(b"WQ7035", b"MITM!")]))
    pdu = bytes([0x06, 0x00, 0x04, 0x00]) + b"WQ7035"      # len=6, cid=0x0004
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=pdu))
    await relay.flush()
    assert len(target_sent) == 1
    out = target_sent[0][2]
    assert out == bytes([0x05, 0x00, 0x04, 0x00]) + b"MITM!"  # length header becomes 5
    await relay.stop()


async def test_no_transform_is_identity():
    phone, _ = _make_side("phone", 0x40, 27)
    target, target_sent = _make_side("target", 0x11, 27)
    relay = AclRelay(phone_side=phone, target_side=target)   # no transform configured
    pdu = bytes([0x06, 0x00, 0x04, 0x00]) + b"WQ7035"
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=pdu))
    await relay.flush()
    assert target_sent[0][2] == pdu
    await relay.stop()


async def test_transform_exception_fails_open():
    """A transform exception → log and forward the original frame; do not kill
    the media stream."""
    phone, _ = _make_side("phone", 0x40, 27)
    target, target_sent = _make_side("target", 0x11, 27)

    def boom(direction, cid, payload):
        raise RuntimeError("boom")

    relay = AclRelay(phone_side=phone, target_side=target, transform=boom)
    pdu = bytes([0x01, 0x00, 0x04, 0x00, 0x2A])
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=pdu))
    await relay.flush()
    assert target_sent[0][2] == pdu
    await relay.stop()


async def test_transform_receives_direction_and_cid():
    seen = []

    def spy(direction, cid, payload):
        seen.append((direction, cid))
        return payload

    phone, _ = _make_side("phone", 0x40, 27)
    target, _ = _make_side("target", 0x11, 27)
    relay = AclRelay(phone_side=phone, target_side=target, transform=spy)
    pdu = bytes([0x01, 0x00, 0x04, 0x00, 0x2A])
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=pdu))
    await relay.flush()
    assert seen == [(RelayDirection.PHONE_TO_TARGET, 0x0004)]
    await relay.stop()
