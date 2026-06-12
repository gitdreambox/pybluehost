import pytest

from pybluehost.profiles.classic._at_parser import ATCommand, ATResponse, ATUnsolicited
from pybluehost.profiles.classic._hfp_at import (
    build_brsf_command, build_brsf_response, build_bac_command,
    build_cind_test_response, build_cind_read_response,
    build_cmer_command,
)
from pybluehost.profiles.classic._hfp_constants import (
    HFFeature, AGFeature, HFPCodecID,
)
from pybluehost.profiles.classic._hfp_state import (
    HFPStateMachine, SLCState,
)


def _make_hf():
    return HFPStateMachine(
        role="hf",
        local_features=int(HFFeature.EC_NR | HFFeature.CODEC_NEGOTIATION),
        local_codecs=[HFPCodecID.CVSD, HFPCodecID.MSBC],
    )


def _make_ag():
    return HFPStateMachine(
        role="ag",
        local_features=int(AGFeature.EC_NR | AGFeature.CODEC_NEGOTIATION),
        local_codecs=[HFPCodecID.CVSD, HFPCodecID.MSBC],
        indicators=[
            ("service", (0, 1)),
            ("call", (0, 1)),
            ("callsetup", (0, 3)),
        ],
        indicator_values={"service": 1, "call": 0, "callsetup": 0},
    )


def test_hf_initial_state_is_brsf_wait():
    sm = _make_hf()
    assert sm.state == SLCState.IDLE


def test_hf_begin_emits_brsf_command():
    sm = _make_hf()
    out = sm.begin()
    assert len(out) == 1
    assert isinstance(out[0], ATCommand)
    assert out[0].name == "+BRSF"
    assert sm.state == SLCState.BRSF_WAIT


def test_hf_receives_brsf_response_then_ok_emits_bac():
    sm = _make_hf()
    sm.begin()
    sm.feed(build_brsf_response(int(AGFeature.CODEC_NEGOTIATION)))
    out = sm.feed(ATResponse(name="OK", is_terminator=True))
    # Codec neg supported → next is AT+BAC
    assert len(out) == 1
    assert out[0].name == "+BAC"
    assert sm.state == SLCState.BAC_WAIT


def test_hf_full_slc_sequence():
    sm = _make_hf()
    sm.begin()    # → +BRSF
    sm.feed(build_brsf_response(int(AGFeature.CODEC_NEGOTIATION)))
    sm.feed(ATResponse(name="OK", is_terminator=True))    # → +BAC
    sm.feed(ATResponse(name="OK", is_terminator=True))    # → +CIND=?
    sm.feed(build_cind_test_response([
        ("service", (0, 1)), ("call", (0, 1)), ("callsetup", (0, 3)),
    ]))
    sm.feed(ATResponse(name="OK", is_terminator=True))    # → +CIND?
    sm.feed(build_cind_read_response(
        {"service": 1, "call": 0, "callsetup": 0},
        ordering=["service", "call", "callsetup"],
    ))
    sm.feed(ATResponse(name="OK", is_terminator=True))    # → +CMER
    sm.feed(ATResponse(name="OK", is_terminator=True))    # → SLC up
    assert sm.state == SLCState.ESTABLISHED


def test_ag_receives_brsf_then_emits_response_and_ok():
    sm = _make_ag()
    out = sm.feed(build_brsf_command(int(HFFeature.CODEC_NEGOTIATION)))
    assert len(out) == 2
    assert isinstance(out[0], ATResponse) and out[0].name == "+BRSF"
    assert isinstance(out[1], ATResponse) and out[1].name == "OK"


def test_ag_receives_bac_then_emits_ok():
    sm = _make_ag()
    sm.feed(build_brsf_command(int(HFFeature.CODEC_NEGOTIATION)))
    out = sm.feed(build_bac_command([HFPCodecID.CVSD, HFPCodecID.MSBC]))
    assert len(out) == 1
    assert out[0].is_terminator
    assert out[0].name == "OK"


def test_ag_reaches_established_after_cmer():
    sm = _make_ag()
    sm.feed(build_brsf_command(int(HFFeature.CODEC_NEGOTIATION)))
    sm.feed(build_bac_command([HFPCodecID.CVSD, HFPCodecID.MSBC]))
    sm.feed(ATCommand(name="+CIND", kind="test", args=[]))
    sm.feed(ATCommand(name="+CIND", kind="read", args=[]))
    sm.feed(build_cmer_command(mode=3, ind_reporting=1))
    assert sm.state == SLCState.ESTABLISHED
