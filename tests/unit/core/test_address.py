import pytest
from pybluehost.core.address import BDAddress, AddressType


class TestAddressType:
    def test_enum_values(self):
        assert AddressType.PUBLIC == 0x00
        assert AddressType.RANDOM == 0x01
        assert AddressType.PUBLIC_IDENTITY == 0x02
        assert AddressType.RANDOM_IDENTITY == 0x03


class TestBDAddress:
    def test_from_string_public(self):
        addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        assert addr.address == bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])
        assert addr.type == AddressType.PUBLIC

    def test_from_string_random(self):
        addr = BDAddress.from_string("11:22:33:44:55:66", AddressType.RANDOM)
        assert addr.type == AddressType.RANDOM

    def test_from_string_lowercase(self):
        addr = BDAddress.from_string("aa:bb:cc:dd:ee:ff")
        assert addr.address == bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])

    def test_from_string_invalid_length(self):
        with pytest.raises(ValueError, match="6 colon-separated"):
            BDAddress.from_string("AA:BB:CC")

    def test_from_string_invalid_hex(self):
        with pytest.raises(ValueError):
            BDAddress.from_string("GG:HH:II:JJ:KK:LL")

    def test_str_representation(self):
        addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        assert str(addr) == "AA:BB:CC:DD:EE:FF"

    def test_equality(self):
        a = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        b = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        assert a == b

    def test_inequality_different_address(self):
        a = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        b = BDAddress.from_string("11:22:33:44:55:66")
        assert a != b

    def test_inequality_different_type(self):
        a = BDAddress.from_string("AA:BB:CC:DD:EE:FF", AddressType.PUBLIC)
        b = BDAddress.from_string("AA:BB:CC:DD:EE:FF", AddressType.RANDOM)
        assert a != b

    def test_hashable(self):
        addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        d = {addr: "test"}
        assert d[addr] == "test"

    def test_frozen(self):
        addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        with pytest.raises(AttributeError):
            addr.type = AddressType.RANDOM  # type: ignore[misc]

    def test_is_rpa_true(self):
        # RPA: top 2 bits of first byte are 01 (0x40-0x7F)
        addr = BDAddress(address=bytes([0x4A, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]), type=AddressType.RANDOM)
        assert addr.is_rpa is True

    def test_is_rpa_false_public(self):
        addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF", AddressType.PUBLIC)
        assert addr.is_rpa is False

    def test_is_rpa_false_static_random(self):
        # Static random: top 2 bits are 11 (0xC0-0xFF)
        addr = BDAddress(address=bytes([0xC0, 0x11, 0x22, 0x33, 0x44, 0x55]), type=AddressType.RANDOM)
        assert addr.is_rpa is False

    def test_random_factory(self):
        addr = BDAddress.random()
        assert addr.type == AddressType.RANDOM
        assert len(addr.address) == 6
        # Static random address: top 2 bits must be 11
        assert addr.address[0] & 0xC0 == 0xC0

    def test_from_bytes(self):
        raw = bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06])
        addr = BDAddress(address=raw)
        assert addr.address == raw
        assert addr.type == AddressType.PUBLIC
