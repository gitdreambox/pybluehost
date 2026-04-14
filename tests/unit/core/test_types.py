from pybluehost.core.types import IOCapability, ConnectionRole, LinkType


class TestIOCapability:
    def test_enum_values(self):
        assert IOCapability.DISPLAY_ONLY == 0x00
        assert IOCapability.DISPLAY_YES_NO == 0x01
        assert IOCapability.KEYBOARD_ONLY == 0x02
        assert IOCapability.NO_INPUT_NO_OUTPUT == 0x03
        assert IOCapability.KEYBOARD_DISPLAY == 0x04


class TestConnectionRole:
    def test_enum_values(self):
        assert ConnectionRole.CENTRAL == 0x00
        assert ConnectionRole.PERIPHERAL == 0x01


class TestLinkType:
    def test_enum_values(self):
        assert LinkType.SCO == 0x00
        assert LinkType.ACL == 0x01
        assert LinkType.ESCO == 0x02
        assert LinkType.LE == 0x03
