import pytest
from pybluehost.core.trace import Direction
from pybluehost.sniffer.ellisys import ellisys_packet_type


@pytest.mark.parametrize("h4,direction,expected", [
    (0x01, Direction.DOWN, 0x01),   # Command
    (0x04, Direction.UP,   0x84),   # Event
    (0x02, Direction.DOWN, 0x02),   # AclFromHost
    (0x02, Direction.UP,   0x82),   # AclFromController
    (0x03, Direction.DOWN, 0x03),   # ScoFromHost
    (0x03, Direction.UP,   0x83),   # ScoFromController
    (0x05, Direction.DOWN, 0x05),   # IsoFromHost
    (0x05, Direction.UP,   0x85),   # IsoFromController
])
def test_ellisys_packet_type_mapping(h4, direction, expected):
    assert ellisys_packet_type(h4, direction) == expected


def test_unknown_h4_type_raises_value_error():
    with pytest.raises(ValueError, match="0x06"):
        ellisys_packet_type(0x06, Direction.DOWN)
