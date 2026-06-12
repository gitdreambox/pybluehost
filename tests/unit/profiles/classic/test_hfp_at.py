import pytest

from pybluehost.profiles.classic._at_parser import ATCommand, ATResponse, ATUnsolicited
from pybluehost.profiles.classic._hfp_at import (
    build_brsf_command, parse_brsf_command,
    build_brsf_response, parse_brsf_response,
    build_bac_command, parse_bac_command,
    build_cind_test_response, parse_cind_test_response,
    build_cind_read_response, parse_cind_read_response,
    build_cmer_command, parse_cmer_command,
    build_ciev_unsolicited, parse_ciev_unsolicited,
    build_bcs_unsolicited, parse_bcs_unsolicited,
    build_bcs_command, parse_bcs_command,
)
from pybluehost.profiles.classic._hfp_constants import (
    HFFeature, AGFeature, HFPCodecID,
    HFPCallState, HFPCallSetupState,
)


def test_brsf_command_build_and_parse():
    cmd = build_brsf_command(HFFeature.EC_NR | HFFeature.CODEC_NEGOTIATION)
    assert cmd.name == "+BRSF"
    assert cmd.kind == "set"
    assert cmd.args == [str(HFFeature.EC_NR | HFFeature.CODEC_NEGOTIATION)]
    parsed = parse_brsf_command(cmd)
    assert parsed == int(HFFeature.EC_NR | HFFeature.CODEC_NEGOTIATION)


def test_brsf_response_build_and_parse():
    resp = build_brsf_response(AGFeature.CODEC_NEGOTIATION | AGFeature.EC_NR)
    assert resp.name == "+BRSF"
    assert resp.args == [str(int(AGFeature.CODEC_NEGOTIATION | AGFeature.EC_NR))]
    parsed = parse_brsf_response(resp)
    assert parsed == int(AGFeature.CODEC_NEGOTIATION | AGFeature.EC_NR)


def test_bac_command_round_trip():
    cmd = build_bac_command([HFPCodecID.CVSD, HFPCodecID.MSBC])
    assert cmd.name == "+BAC"
    assert cmd.args == ["1", "2"]
    parsed = parse_bac_command(cmd)
    assert parsed == [HFPCodecID.CVSD, HFPCodecID.MSBC]


def test_cind_test_response_round_trip():
    indicators = [
        ("service", (0, 1)),
        ("call", (0, 1)),
        ("callsetup", (0, 3)),
    ]
    resp = build_cind_test_response(indicators)
    # The args list is a single string blob — verify by re-parsing
    parsed = parse_cind_test_response(resp)
    assert parsed == indicators


def test_cind_read_response_round_trip():
    values = {"service": 1, "call": 0, "callsetup": 0}
    resp = build_cind_read_response(values, ordering=["service", "call", "callsetup"])
    assert resp.name == "+CIND"
    assert resp.args == ["1", "0", "0"]
    parsed = parse_cind_read_response(resp, ordering=["service", "call", "callsetup"])
    assert parsed == values


def test_cmer_command_round_trip():
    cmd = build_cmer_command(mode=3, ind_reporting=1)
    assert cmd.args == ["3", "0", "0", "1"]
    mode, ind = parse_cmer_command(cmd)
    assert mode == 3
    assert ind == 1


def test_ciev_unsolicited_round_trip():
    msg = build_ciev_unsolicited(index=2, value=int(HFPCallState.ACTIVE))
    assert msg.name == "+CIEV"
    assert msg.args == ["2", "1"]
    index, value = parse_ciev_unsolicited(msg)
    assert index == 2
    assert value == 1


def test_bcs_unsolicited_round_trip():
    msg = build_bcs_unsolicited(HFPCodecID.MSBC)
    assert msg.name == "+BCS"
    assert msg.args == ["2"]
    cid = parse_bcs_unsolicited(msg)
    assert cid == HFPCodecID.MSBC


def test_bcs_command_round_trip():
    cmd = build_bcs_command(HFPCodecID.MSBC)
    assert cmd.name == "+BCS"
    assert cmd.kind == "set"
    assert cmd.args == ["2"]
    cid = parse_bcs_command(cmd)
    assert cid == HFPCodecID.MSBC
