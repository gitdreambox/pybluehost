import pytest

from pybluehost.avrcp.constants import (
    AVCCtype, AVCOpCode, AVCSubunitType, AVRCPOperationID,
)
from pybluehost.avrcp.frame import AVCFrame
from pybluehost.avrcp.passthrough import (
    PassThroughCommand, PassThroughResponse,
)


def test_pass_through_play_pressed_to_avcframe():
    cmd = PassThroughCommand(
        operation_id=AVRCPOperationID.PLAY,
        pressed=True,
    )
    frame = cmd.to_avcframe()
    assert frame.ctype == AVCCtype.CONTROL
    assert frame.subunit_type == AVCSubunitType.PANEL
    assert frame.subunit_id == 0
    assert frame.opcode == AVCOpCode.PASS_THROUGH
    # operand byte 0: state=0 (pressed) << 7 | 0x44 (PLAY) = 0x44
    # operand byte 1: data_length = 0
    assert frame.operands == bytes([0x44, 0x00])


def test_pass_through_play_released_to_avcframe():
    cmd = PassThroughCommand(
        operation_id=AVRCPOperationID.PLAY,
        pressed=False,
    )
    frame = cmd.to_avcframe()
    # operand byte 0: state=1 << 7 | 0x44 = 0xC4
    assert frame.operands == bytes([0xC4, 0x00])


def test_pass_through_volume_up_with_extra_data():
    cmd = PassThroughCommand(
        operation_id=AVRCPOperationID.VOLUME_UP,
        pressed=True,
        operation_data=bytes([0xAA]),
    )
    frame = cmd.to_avcframe()
    # operand byte 0: 0x41 (VOLUME_UP)
    # operand byte 1: data_length = 1
    # operand byte 2: 0xAA
    assert frame.operands == bytes([0x41, 0x01, 0xAA])


def test_pass_through_from_avcframe_round_trip():
    original = PassThroughCommand(
        operation_id=AVRCPOperationID.PAUSE,
        pressed=False,
        operation_data=b"",
    )
    frame = original.to_avcframe()
    decoded = PassThroughCommand.from_avcframe(frame)
    assert decoded.operation_id == AVRCPOperationID.PAUSE
    assert decoded.pressed is False
    assert decoded.operation_data == b""


def test_pass_through_from_avcframe_invalid_opcode():
    bad = AVCFrame(
        ctype=AVCCtype.CONTROL, subunit_type=AVCSubunitType.PANEL,
        subunit_id=0, opcode=AVCOpCode.UNIT_INFO,
        operands=b"\x44\x00",
    )
    with pytest.raises(ValueError, match="PASS_THROUGH"):
        PassThroughCommand.from_avcframe(bad)


def test_pass_through_response_accepted():
    resp = PassThroughResponse.accepted(
        operation_id=AVRCPOperationID.PLAY, pressed=True,
    )
    frame = resp.to_avcframe()
    assert frame.ctype == AVCCtype.ACCEPTED
    assert frame.opcode == AVCOpCode.PASS_THROUGH
    assert frame.operands == bytes([0x44, 0x00])


def test_pass_through_response_not_implemented():
    resp = PassThroughResponse.not_implemented(
        operation_id=0x7F, pressed=False,
    )
    frame = resp.to_avcframe()
    assert frame.ctype == AVCCtype.NOT_IMPLEMENTED
    # operand: 0xFF (state=1 << 7 | 0x7F)
    assert frame.operands[0] == 0xFF
