import pytest

from pybluehost.avdtp.constants import MediaType, TSEP
from pybluehost.avdtp.sep import StreamEndpoint, SEPStateError


def _src_sep(seid: int = 1) -> StreamEndpoint:
    return StreamEndpoint(seid=seid, media_type=MediaType.AUDIO, tsep=TSEP.SRC)


def test_new_sep_is_idle_not_in_use():
    sep = _src_sep()
    assert sep.state == "IDLE"
    assert sep.in_use is False


def test_idle_to_configured():
    sep = _src_sep()
    sep.transition_set_configuration()
    assert sep.state == "CONFIGURED"
    assert sep.in_use is True


def test_configured_to_open():
    sep = _src_sep()
    sep.transition_set_configuration()
    sep.transition_open()
    assert sep.state == "OPEN"


def test_open_to_streaming():
    sep = _src_sep()
    sep.transition_set_configuration()
    sep.transition_open()
    sep.transition_start()
    assert sep.state == "STREAMING"


def test_streaming_to_open_on_suspend():
    sep = _src_sep()
    sep.transition_set_configuration()
    sep.transition_open()
    sep.transition_start()
    sep.transition_suspend()
    assert sep.state == "OPEN"


def test_any_state_to_idle_on_close():
    sep = _src_sep()
    sep.transition_set_configuration()
    sep.transition_open()
    sep.transition_close()
    assert sep.state == "IDLE"
    assert sep.in_use is False


def test_any_state_to_idle_on_abort():
    sep = _src_sep()
    sep.transition_set_configuration()
    sep.transition_open()
    sep.transition_start()
    sep.transition_abort()
    assert sep.state == "IDLE"
    assert sep.in_use is False


def test_open_from_idle_raises_bad_state():
    sep = _src_sep()
    with pytest.raises(SEPStateError):
        sep.transition_open()    # must SET_CONFIGURATION first


def test_start_from_configured_raises_bad_state():
    sep = _src_sep()
    sep.transition_set_configuration()
    with pytest.raises(SEPStateError):
        sep.transition_start()    # must OPEN first


def test_double_set_configuration_raises():
    sep = _src_sep()
    sep.transition_set_configuration()
    with pytest.raises(SEPStateError):
        sep.transition_set_configuration()    # already CONFIGURED
