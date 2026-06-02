from pybluehost.cli.app.mitm.acl import (
    CID_ATT,
    CID_SMP,
    PB_FIRST_FLUSH,
    RelayDirection,
)
from pybluehost.cli.app.mitm.relay import AclRelay, RelaySide
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

    assert len(target_sent) == 1
    h, pb, data = target_sent[0]
    assert h == 0x11
    assert data == bytes([0x03, 0x00, 0x04, 0x00, 0x0A, 0x03, 0x00])
    assert phone_sent == []


async def test_relay_refragments_for_small_peer_buffer():
    phone, _ = _make_side("phone", 0x40, 27)
    target, target_sent = _make_side("target", 0x11, 4)
    relay = AclRelay(phone_side=phone, target_side=target)

    payload = bytes(range(9))
    pdu = bytes([0x09, 0x00, 0x04, 0x00]) + payload
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=pdu))

    assert len(target_sent) == 4
    assert b"".join(d for _, _, d in target_sent) == pdu
    assert target_sent[0][1] == 0x00
    assert all(pb == 0x01 for _, pb, _ in target_sent[1:])


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
