from pybluehost.pts.btp import opcodes as op


def test_core_service_id():
    """Core is always Service ID 0x00 in auto-pts BTP."""
    assert op.SERVICE_CORE == 0x00


def test_status_response_opcode_universal():
    """All services use opcode 0x00 for status responses."""
    assert op.OP_STATUS_RESPONSE == 0x00


def test_core_opcodes_are_distinct_and_in_command_range():
    """Core opcodes 0x01-0x7F are commands; 0x80+ are events.

    Verified against upstream auto-pts doc/btp_core.txt 2026-06-22.
    Plan P.5 listed RESET_BOARD; upstream has no such command, so it's omitted.
    """
    cmds = [
        op.OP_CORE_READ_SUPPORTED_COMMANDS,
        op.OP_CORE_READ_SUPPORTED_SERVICES,
        op.OP_CORE_REGISTER,
        op.OP_CORE_UNREGISTER,
        op.OP_CORE_LOG_MESSAGE,
        op.OP_CORE_READ_BTP_MTU,
    ]
    assert len(set(cmds)) == len(cmds)
    assert all(0 < c < 0x80 for c in cmds)


def test_core_event_in_event_range():
    """Event opcodes have the high bit set."""
    assert op.OP_CORE_EVENT_READY >= 0x80


def test_btp_status_codes_have_named_values():
    """auto-pts upstream defines a status-byte enum for command responses."""
    assert op.BTP_STATUS_SUCCESS == 0x00
    assert op.BTP_STATUS_FAILED == 0x01
    assert op.BTP_STATUS_UNKNOWN_CMD == 0x02
    assert op.BTP_STATUS_NOT_READY == 0x03


def test_controller_index_none_constant():
    """Commands not tied to a specific controller use index 0xFF."""
    assert op.CONTROLLER_INDEX_NONE == 0xFF
