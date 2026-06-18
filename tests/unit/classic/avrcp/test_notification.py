import pytest

from pybluehost.classic.avrcp.constants import (
    AVCCtype, AVCOpCode, AVCSubunitType,
    AVRCPEventID, AVRCPMetadataPDU, AVRCPPlayStatus,
    AVRCP_BT_SIG_COMPANY_ID,
)
from pybluehost.classic.avrcp.frame import AVCFrame
from pybluehost.classic.avrcp.notification import (
    build_register_notification_command,
    build_notification_interim_response,
    build_notification_changed_response,
    parse_notification_response,
)


def test_register_notification_command_layout():
    frame = build_register_notification_command(
        event_id=AVRCPEventID.PLAYBACK_STATUS_CHANGED,
        playback_interval=0,
    )
    assert frame.ctype == AVCCtype.NOTIFY
    assert frame.subunit_type == AVCSubunitType.PANEL
    assert frame.opcode == AVCOpCode.VENDOR_DEPENDENT
    # operand bytes 0..2: BT SIG company id = 0x001958 BE
    assert frame.operands[0:3] == bytes([0x00, 0x19, 0x58])
    # byte 3: PDU = 0x31 (REGISTER_NOTIFICATION)
    assert frame.operands[3] == AVRCPMetadataPDU.REGISTER_NOTIFICATION
    # byte 4: packet_type = 0
    assert frame.operands[4] == 0x00
    # bytes 5..6: param_length = 0x0005 (event_id + 4-byte playback_interval)
    assert frame.operands[5:7] == bytes([0x00, 0x05])
    # byte 7: event id = 0x01 (PLAYBACK_STATUS_CHANGED)
    assert frame.operands[7] == AVRCPEventID.PLAYBACK_STATUS_CHANGED
    # bytes 8..11: playback_interval = 0
    assert frame.operands[8:12] == bytes([0x00, 0x00, 0x00, 0x00])


def test_notification_interim_response_playback_status():
    """INTERIM response for PLAYBACK_STATUS_CHANGED includes current status (1 byte)."""
    frame = build_notification_interim_response(
        event_id=AVRCPEventID.PLAYBACK_STATUS_CHANGED,
        event_payload=bytes([AVRCPPlayStatus.PLAYING]),
    )
    assert frame.ctype == AVCCtype.INTERIM
    # company id + PDU + packet_type + param_length=0x0002 + event_id + status
    assert frame.operands[5:7] == bytes([0x00, 0x02])
    assert frame.operands[7] == AVRCPEventID.PLAYBACK_STATUS_CHANGED
    assert frame.operands[8] == AVRCPPlayStatus.PLAYING


def test_notification_changed_response_track_changed():
    """CHANGED response for TRACK_CHANGED carries 8-byte track UID (big-endian)."""
    frame = build_notification_changed_response(
        event_id=AVRCPEventID.TRACK_CHANGED,
        event_payload=bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x42]),
    )
    assert frame.ctype == AVCCtype.CHANGED
    assert frame.operands[5:7] == bytes([0x00, 0x09])    # param_length = 9
    assert frame.operands[7] == AVRCPEventID.TRACK_CHANGED


def test_parse_notification_response_round_trip():
    frame = build_notification_interim_response(
        event_id=AVRCPEventID.PLAYBACK_STATUS_CHANGED,
        event_payload=bytes([AVRCPPlayStatus.PAUSED]),
    )
    ctype, event_id, payload = parse_notification_response(frame)
    assert ctype == AVCCtype.INTERIM
    assert event_id == AVRCPEventID.PLAYBACK_STATUS_CHANGED
    assert payload == bytes([AVRCPPlayStatus.PAUSED])


def test_parse_notification_response_wrong_company_id():
    frame = AVCFrame(
        ctype=AVCCtype.CHANGED, subunit_type=AVCSubunitType.PANEL, subunit_id=0,
        opcode=AVCOpCode.VENDOR_DEPENDENT,
        operands=bytes([0xDE, 0xAD, 0xBE, 0x31, 0x00, 0x00, 0x01, 0x01]),
    )
    with pytest.raises(ValueError, match="company"):
        parse_notification_response(frame)
