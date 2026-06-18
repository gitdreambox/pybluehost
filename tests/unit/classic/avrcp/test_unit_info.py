import pytest

from pybluehost.classic.avrcp.constants import (
    AVCCtype, AVCOpCode, AVCSubunitType, AVRCP_BT_SIG_COMPANY_ID,
)
from pybluehost.classic.avrcp.frame import AVCFrame
from pybluehost.classic.avrcp.unit_info import (
    build_unit_info_command, build_unit_info_response,
    parse_unit_info_response,
    build_subunit_info_command, build_subunit_info_response,
    parse_subunit_info_response,
)


def test_unit_info_command_has_5_byte_ff_operands():
    frame = build_unit_info_command()
    assert frame.ctype == AVCCtype.STATUS
    assert frame.subunit_type == AVCSubunitType.UNIT
    assert frame.subunit_id == 7    # unit subunit_id is always 7
    assert frame.opcode == AVCOpCode.UNIT_INFO
    assert frame.operands == bytes([0xFF] * 5)


def test_unit_info_response_includes_company_id():
    frame = build_unit_info_response(company_id=AVRCP_BT_SIG_COMPANY_ID)
    assert frame.ctype == AVCCtype.STABLE
    # operand byte 0: 0x07 (reserved)
    # operand byte 1: UNIT_type=0x1F << 3 | unit_id=7 = 0xFF
    # operand bytes 2..4: company id 0x001958 BE
    assert frame.operands[0] == 0x07
    assert frame.operands[1] == 0xFF
    assert frame.operands[2:5] == bytes([0x00, 0x19, 0x58])


def test_parse_unit_info_response_returns_company_id():
    frame = build_unit_info_response(company_id=AVRCP_BT_SIG_COMPANY_ID)
    cid = parse_unit_info_response(frame)
    assert cid == AVRCP_BT_SIG_COMPANY_ID


def test_subunit_info_command_page_0():
    frame = build_subunit_info_command(page=0)
    assert frame.opcode == AVCOpCode.SUBUNIT_INFO
    # operand byte 0: page(3 bits)=0 << 4 | extension(1)=7 = 0x07 (extension=7 per spec default)
    assert frame.operands[0] == 0x07
    assert frame.operands[1:5] == bytes([0xFF] * 4)


def test_subunit_info_response_advertises_panel():
    frame = build_subunit_info_response()
    # operand byte 0: same 0x07 (page=0, extension=7)
    # operand byte 1: PANEL(0x09) << 3 | 0 = 0x48
    # operand bytes 2..4: 0xFF (unused slots)
    assert frame.operands[0] == 0x07
    assert frame.operands[1] == 0x48
    assert frame.operands[2:5] == bytes([0xFF] * 3)


def test_parse_subunit_info_response_lists_panel():
    frame = build_subunit_info_response()
    units = parse_subunit_info_response(frame)
    assert (AVCSubunitType.PANEL, 0) in units
