import pytest
from pybluehost.core.trace import Direction
from pybluehost.sniffer.wps import wps_frame_params


@pytest.mark.parametrize("h4,direction,expected", [
    (0x01, Direction.DOWN, (1, 0)),   # Command → Drf=1, HOST
    (0x04, Direction.UP,   (8, 1)),   # Event → Drf=8, CONTROLLER
    (0x02, Direction.DOWN, (2, 0)),   # ACL host
    (0x02, Direction.UP,   (2, 1)),   # ACL controller
    (0x03, Direction.DOWN, (4, 0)),   # SCO host
    (0x03, Direction.UP,   (4, 1)),   # SCO controller
])
def test_wps_frame_params_mapping(h4, direction, expected):
    assert wps_frame_params(h4, direction) == expected


def test_wps_iso_returns_none():
    """ISO not in default WPS personality Drf — caller must skip."""
    assert wps_frame_params(0x05, Direction.DOWN) is None
    assert wps_frame_params(0x05, Direction.UP) is None


def test_wps_unknown_h4_raises():
    with pytest.raises(ValueError, match="0x06"):
        wps_frame_params(0x06, Direction.DOWN)
