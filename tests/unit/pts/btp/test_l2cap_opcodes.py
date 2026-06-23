from pybluehost.pts.btp import opcodes as op


def test_l2cap_service_id():
    assert op.SERVICE_L2CAP == 0x03


def test_l2cap_command_opcodes_distinct_and_in_range():
    cmds = [
        op.OP_L2CAP_READ_SUPPORTED_COMMANDS,
        op.OP_L2CAP_CONNECT, op.OP_L2CAP_DISCONNECT,
        op.OP_L2CAP_SEND_DATA, op.OP_L2CAP_LISTEN,
    ]
    assert len(set(cmds)) == len(cmds)
    assert all(0 < c < 0x80 for c in cmds)


def test_l2cap_event_opcodes_in_event_range():
    events = [
        op.OP_L2CAP_EVENT_CONNECTION_REQUEST,
        op.OP_L2CAP_EVENT_CONNECTED,
        op.OP_L2CAP_EVENT_DISCONNECTED,
        op.OP_L2CAP_EVENT_DATA_RECEIVED,
    ]
    assert all(e >= 0x80 for e in events)


def test_l2cap_opcode_numbering_matches_upstream():
    """Verified against auto-pts master doc/btp_l2cap.txt 2026-06-23."""
    assert op.OP_L2CAP_READ_SUPPORTED_COMMANDS == 0x01
    assert op.OP_L2CAP_CONNECT == 0x02
    assert op.OP_L2CAP_DISCONNECT == 0x03
    assert op.OP_L2CAP_SEND_DATA == 0x04
    assert op.OP_L2CAP_LISTEN == 0x05
    assert op.OP_L2CAP_EVENT_CONNECTION_REQUEST == 0x80
    assert op.OP_L2CAP_EVENT_CONNECTED == 0x81
    assert op.OP_L2CAP_EVENT_DISCONNECTED == 0x82
    assert op.OP_L2CAP_EVENT_DATA_RECEIVED == 0x83
