from pybluehost.cli.app.mitm.acl import (
    CID_ATT,
    CID_SMP,
    CidAction,
    classify,
    encode_l2cap_basic,
)


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
