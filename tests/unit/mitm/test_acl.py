from pybluehost.cli.app.mitm.acl import (
    CID_ATT,
    CID_SMP,
    CidAction,
    PB_CONTINUATION,
    PB_FIRST_FLUSH,
    L2capReassembler,
    classify,
    encode_l2cap_basic,
)
from pybluehost.hci.packets import HCIACLData


def test_encode_l2cap_basic():
    # ATT Read Request (opcode 0x0A, handle 0x0003) over CID 0x0004
    pdu = encode_l2cap_basic(CID_ATT, bytes([0x0A, 0x03, 0x00]))
    assert pdu == bytes([0x03, 0x00, 0x04, 0x00, 0x0A, 0x03, 0x00])


def test_classify_smp_is_terminate():
    assert classify(CID_SMP) is CidAction.TERMINATE_SMP


def test_classify_att_is_relay():
    assert classify(CID_ATT) is CidAction.RELAY


def test_classify_signaling_is_relay():
    assert classify(0x0001) is CidAction.RELAY  # BR signaling
    assert classify(0x0005) is CidAction.RELAY  # LE signaling


def test_reassembler_single_complete_pdu():
    r = L2capReassembler()
    acl = HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH,
                     data=bytes([0x03, 0x00, 0x04, 0x00, 0x0A, 0x03, 0x00]))
    out = r.feed(acl)
    assert out == [(0x0004, bytes([0x0A, 0x03, 0x00]))]


def test_reassembler_fragmented_pdu():
    r = L2capReassembler()
    first = HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH,
                       data=bytes([0x05, 0x00, 0x04, 0x00, 0xAA, 0xBB]))
    cont = HCIACLData(handle=0x40, pb_flag=PB_CONTINUATION,
                      data=bytes([0xCC, 0xDD, 0xEE]))
    assert r.feed(first) == []
    assert r.feed(cont) == [(0x0004, bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE]))]


def test_reassembler_two_pdus_in_one_fragment():
    r = L2capReassembler()
    pdu1 = bytes([0x01, 0x00, 0x04, 0x00, 0xAA])
    pdu2 = bytes([0x02, 0x00, 0x06, 0x00, 0xBB, 0xCC])
    acl = HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=pdu1 + pdu2)
    assert r.feed(acl) == [(0x0004, bytes([0xAA])), (0x0006, bytes([0xBB, 0xCC]))]
