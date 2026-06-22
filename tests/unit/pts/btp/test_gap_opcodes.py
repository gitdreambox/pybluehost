from pybluehost.pts.btp import opcodes as op


def test_gap_service_id():
    assert op.SERVICE_GAP == 0x01


def test_gap_command_opcodes_distinct_and_in_range():
    cmds = [
        op.OP_GAP_READ_SUPPORTED_COMMANDS, op.OP_GAP_READ_CONTROLLER_INDEX_LIST,
        op.OP_GAP_READ_CONTROLLER_INFO, op.OP_GAP_RESET,
        op.OP_GAP_SET_POWERED, op.OP_GAP_SET_CONNECTABLE,
        op.OP_GAP_SET_FAST_CONNECTABLE, op.OP_GAP_SET_DISCOVERABLE,
        op.OP_GAP_SET_BONDABLE,
        op.OP_GAP_START_ADVERTISING, op.OP_GAP_STOP_ADVERTISING,
        op.OP_GAP_START_DISCOVERY, op.OP_GAP_STOP_DISCOVERY,
        op.OP_GAP_CONNECT, op.OP_GAP_DISCONNECT,
        op.OP_GAP_SET_IO_CAP, op.OP_GAP_PAIR, op.OP_GAP_UNPAIR,
        op.OP_GAP_PASSKEY_ENTRY_REPLY, op.OP_GAP_PASSKEY_CONFIRM_REPLY,
    ]
    assert len(set(cmds)) == len(cmds)
    assert all(0 < c < 0x80 for c in cmds)


def test_gap_event_opcodes_in_event_range():
    events = [
        op.OP_GAP_EVENT_NEW_SETTINGS, op.OP_GAP_EVENT_DEVICE_FOUND,
        op.OP_GAP_EVENT_DEVICE_CONNECTED, op.OP_GAP_EVENT_DEVICE_DISCONNECTED,
        op.OP_GAP_EVENT_PASSKEY_DISPLAY, op.OP_GAP_EVENT_PASSKEY_ENTRY_REQ,
        op.OP_GAP_EVENT_PASSKEY_CONFIRM_REQ, op.OP_GAP_EVENT_IDENTITY_RESOLVED,
        op.OP_GAP_EVENT_SEC_LEVEL_CHANGED, op.OP_GAP_EVENT_PAIRING_FAILED,
    ]
    assert all(e >= 0x80 for e in events)


def test_gap_address_type_constants():
    """BD_ADDR type byte from auto-pts: 0=public, 1=random."""
    assert op.GAP_ADDR_TYPE_PUBLIC == 0
    assert op.GAP_ADDR_TYPE_RANDOM == 1


def test_gap_io_capability_constants():
    """auto-pts uses SMP IO capability enum (HCI/SMP §3.5.1)."""
    assert op.GAP_IO_CAP_DISPLAY_ONLY == 0x00
    assert op.GAP_IO_CAP_DISPLAY_YESNO == 0x01
    assert op.GAP_IO_CAP_KEYBOARD_ONLY == 0x02
    assert op.GAP_IO_CAP_NO_INPUT_NO_OUTPUT == 0x03
    assert op.GAP_IO_CAP_KEYBOARD_DISPLAY == 0x04
