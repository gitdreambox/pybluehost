"""Tests for HCI constants: opcodes, event codes, error codes."""

from pybluehost.hci.constants import (
    make_opcode,
    ogf_ocf,
    OGF,
    HCI_RESET,
    HCI_READ_LOCAL_VERSION,
    HCI_READ_BD_ADDR,
    HCI_READ_BUFFER_SIZE,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_SET_SCAN_ENABLE,
    EventCode,
    LEMetaSubEvent,
    ErrorCode,
    HCI_COMMAND_PACKET,
    HCI_ACL_PACKET,
    HCI_SCO_PACKET,
    HCI_EVENT_PACKET,
    HCI_ISO_PACKET,
)


def test_opcode_construction():
    assert make_opcode(OGF.CONTROLLER_BB, 0x03) == 0x0C03  # HCI_Reset
    assert make_opcode(OGF.LE, 0x0C) == 0x200C  # LE_Set_Scan_Enable


def test_ogf_ocf_round_trip():
    opcode = 0x0406
    ogf, ocf = ogf_ocf(opcode)
    assert ogf == 0x01
    assert ocf == 0x06


def test_ogf_ocf_round_trip_all_named():
    for opcode in [HCI_RESET, HCI_READ_BD_ADDR, HCI_LE_SET_SCAN_ENABLE]:
        ogf, ocf = ogf_ocf(opcode)
        assert make_opcode(ogf, ocf) == opcode


def test_named_opcodes():
    assert HCI_RESET == 0x0C03
    assert HCI_READ_BD_ADDR == 0x1009
    assert HCI_READ_LOCAL_VERSION == 0x1001
    assert HCI_READ_BUFFER_SIZE == 0x1005
    assert HCI_LE_READ_BUFFER_SIZE == 0x2002
    assert HCI_LE_SET_SCAN_ENABLE == 0x200C


def test_event_codes():
    assert EventCode.COMMAND_COMPLETE == 0x0E
    assert EventCode.COMMAND_STATUS == 0x0F
    assert EventCode.CONNECTION_COMPLETE == 0x03
    assert EventCode.DISCONNECTION_COMPLETE == 0x05
    assert EventCode.LE_META == 0x3E
    assert EventCode.VENDOR_SPECIFIC == 0xFF


def test_le_meta_sub_events():
    assert LEMetaSubEvent.LE_CONNECTION_COMPLETE == 0x01
    assert LEMetaSubEvent.LE_ADVERTISING_REPORT == 0x02
    assert LEMetaSubEvent.LE_CONNECTION_UPDATE_COMPLETE == 0x03
    assert LEMetaSubEvent.LE_ENHANCED_CONNECTION_COMPLETE == 0x0A


def test_error_codes():
    assert ErrorCode.SUCCESS == 0x00
    assert ErrorCode.UNKNOWN_COMMAND == 0x01
    assert ErrorCode.CONNECTION_TIMEOUT == 0x08
    assert ErrorCode.UNSUPPORTED_FEATURE == 0x11
    assert ErrorCode.REMOTE_USER_TERMINATED == 0x13


def test_h4_packet_types():
    assert HCI_COMMAND_PACKET == 0x01
    assert HCI_ACL_PACKET == 0x02
    assert HCI_SCO_PACKET == 0x03
    assert HCI_EVENT_PACKET == 0x04
    assert HCI_ISO_PACKET == 0x05
