from pybluehost.pts.btp import opcodes as op


def test_gatt_service_id():
    assert op.SERVICE_GATT == 0x02


def test_server_command_opcodes_distinct():
    cmds = [
        op.OP_GATT_READ_SUPPORTED_COMMANDS,
        op.OP_GATT_ADD_SERVICE, op.OP_GATT_ADD_CHARACTERISTIC,
        op.OP_GATT_ADD_DESCRIPTOR, op.OP_GATT_ADD_INCLUDED_SERVICE,
        op.OP_GATT_SET_VALUE, op.OP_GATT_START_SERVER,
        op.OP_GATT_RESET_SERVER, op.OP_GATT_SET_ENC_KEY_SIZE,
    ]
    assert len(set(cmds)) == len(cmds)
    assert all(0 < c < 0x80 for c in cmds)


def test_client_command_opcodes_distinct():
    cmds = [
        op.OP_GATT_EXCHANGE_MTU,
        op.OP_GATT_DISC_ALL_PRIM_SVCS, op.OP_GATT_DISC_PRIM_SVC_BY_UUID,
        op.OP_GATT_FIND_INCLUDED_SVCS,
        op.OP_GATT_DISC_ALL_CHRC, op.OP_GATT_DISC_CHRC_BY_UUID,
        op.OP_GATT_DISC_ALL_DESC,
        op.OP_GATT_READ, op.OP_GATT_READ_UUID,
        op.OP_GATT_READ_LONG, op.OP_GATT_READ_MULTIPLE,
        op.OP_GATT_WRITE_WITHOUT_RSP, op.OP_GATT_WRITE,
        op.OP_GATT_WRITE_LONG, op.OP_GATT_WRITE_RELIABLE,
        op.OP_GATT_CFG_NOTIFY, op.OP_GATT_CFG_INDICATE,
    ]
    assert len(set(cmds)) == len(cmds)
    assert all(0 < c < 0x80 for c in cmds)


def test_upstream_opcode_numbering():
    """Specific upstream values (auto-pts/doc/btp_gatt.txt 2026-06-22)."""
    assert op.OP_GATT_RESET_SERVER == 0x08
    assert op.OP_GATT_READ == 0x11
    assert op.OP_GATT_READ_UUID == 0x12
    assert op.OP_GATT_READ_LONG == 0x13
    assert op.OP_GATT_READ_MULTIPLE == 0x14
    assert op.OP_GATT_WRITE_WITHOUT_RSP == 0x15
    assert op.OP_GATT_WRITE == 0x17
    assert op.OP_GATT_WRITE_LONG == 0x18
    assert op.OP_GATT_WRITE_RELIABLE == 0x19
    assert op.OP_GATT_CFG_NOTIFY == 0x1A
    assert op.OP_GATT_CFG_INDICATE == 0x1B


def test_event_opcodes_in_event_range():
    assert op.OP_GATT_EVENT_NOTIFICATION >= 0x80
    assert op.OP_GATT_EVENT_ATTR_VALUE_CHANGED >= 0x80
