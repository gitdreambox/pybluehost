import pytest

from pybluehost.classic.avrcp.constants import (
    AVCCtype, AVCOpCode, AVCSubunitType,
)
from pybluehost.classic.avrcp.frame import AVCFrame


def test_avc_frame_to_bytes_control_panel_passthrough():
    frame = AVCFrame(
        ctype=AVCCtype.CONTROL,
        subunit_type=AVCSubunitType.PANEL,
        subunit_id=0,
        opcode=AVCOpCode.PASS_THROUGH,
        operands=bytes([0x44, 0x00]),    # PLAY, pressed
    )
    # byte 0: 0x00 (high 4 bits 0) | 0x00 (CONTROL=0)  = 0x00
    # byte 1: PANEL(0x09)<<3 | 0 = 0x48
    # byte 2: 0x7C (PASS_THROUGH)
    # operands: 0x44, 0x00
    assert frame.to_bytes() == bytes([0x00, 0x48, 0x7C, 0x44, 0x00])


def test_avc_frame_from_bytes_round_trip():
    raw = bytes([0x09, 0x48, 0x7C, 0x44, 0x00])    # ACCEPTED response
    frame = AVCFrame.from_bytes(raw)
    assert frame.ctype == AVCCtype.ACCEPTED
    assert frame.subunit_type == AVCSubunitType.PANEL
    assert frame.subunit_id == 0
    assert frame.opcode == AVCOpCode.PASS_THROUGH
    assert frame.operands == bytes([0x44, 0x00])


def test_avc_frame_from_bytes_too_short_raises():
    with pytest.raises(ValueError, match="too short"):
        AVCFrame.from_bytes(b"\x00\x48")    # missing opcode


def test_avc_frame_subunit_id_masking():
    """Subunit ID is low 3 bits of byte 1."""
    frame = AVCFrame(
        ctype=AVCCtype.STATUS,
        subunit_type=AVCSubunitType.PANEL,
        subunit_id=7,    # all 3 bits set
        opcode=AVCOpCode.UNIT_INFO,
        operands=b"",
    )
    raw = frame.to_bytes()
    # byte 1: 0x09 << 3 | 7 = 0x4F
    assert raw[1] == 0x4F


def test_avc_ctype_constants():
    assert AVCCtype.CONTROL == 0x0
    assert AVCCtype.STATUS == 0x1
    assert AVCCtype.NOTIFY == 0x3
    assert AVCCtype.NOT_IMPLEMENTED == 0x8
    assert AVCCtype.ACCEPTED == 0x9
    assert AVCCtype.REJECTED == 0xA
    assert AVCCtype.CHANGED == 0xD
    assert AVCCtype.INTERIM == 0xF


def test_avc_opcode_constants():
    assert AVCOpCode.VENDOR_DEPENDENT == 0x00
    assert AVCOpCode.UNIT_INFO == 0x30
    assert AVCOpCode.SUBUNIT_INFO == 0x31
    assert AVCOpCode.PASS_THROUGH == 0x7C
