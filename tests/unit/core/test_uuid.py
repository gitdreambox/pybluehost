import pytest
from pybluehost.core.uuid import UUID16, UUID128, BLUETOOTH_BASE_UUID


class TestUUID16:
    def test_create(self):
        u = UUID16(0x180D)
        assert u.value == 0x180D

    def test_str(self):
        assert str(UUID16(0x180D)) == "0x180D"

    def test_to_bytes_le(self):
        assert UUID16(0x180D).to_bytes() == b"\x0D\x18"

    def test_from_bytes_le(self):
        u = UUID16.from_bytes(b"\x0D\x18")
        assert u.value == 0x180D

    def test_to_uuid128(self):
        u128 = UUID16(0x180D).to_uuid128()
        assert isinstance(u128, UUID128)
        expected = bytearray(BLUETOOTH_BASE_UUID)
        expected[2] = 0x18
        expected[3] = 0x0D
        assert u128.value == bytes(expected)

    def test_equality(self):
        assert UUID16(0x180D) == UUID16(0x180D)
        assert UUID16(0x180D) != UUID16(0x180F)

    def test_hashable(self):
        s = {UUID16(0x180D), UUID16(0x180F), UUID16(0x180D)}
        assert len(s) == 2

    def test_from_bytes_wrong_length(self):
        with pytest.raises(ValueError):
            UUID16.from_bytes(b"\x01")

    def test_range_validation(self):
        with pytest.raises(ValueError):
            UUID16(0x10000)
        with pytest.raises(ValueError):
            UUID16(-1)


class TestUUID128:
    def test_create(self):
        val = bytes(range(16))
        u = UUID128(val)
        assert u.value == val

    def test_from_string(self):
        u = UUID128.from_string("0000180d-0000-1000-8000-00805f9b34fb")
        assert len(u.value) == 16

    def test_str(self):
        u = UUID128.from_string("0000180D-0000-1000-8000-00805F9B34FB")
        s = str(u)
        assert s.lower() == "0000180d-0000-1000-8000-00805f9b34fb"

    def test_to_bytes(self):
        val = bytes(range(16))
        assert UUID128(val).to_bytes() == val

    def test_from_bytes(self):
        val = bytes(range(16))
        u = UUID128.from_bytes(val)
        assert u.value == val

    def test_equality(self):
        a = UUID128.from_string("0000180d-0000-1000-8000-00805f9b34fb")
        b = UUID128.from_string("0000180d-0000-1000-8000-00805f9b34fb")
        assert a == b

    def test_hashable(self):
        a = UUID128.from_string("0000180d-0000-1000-8000-00805f9b34fb")
        d = {a: "test"}
        assert d[a] == "test"

    def test_from_string_invalid(self):
        with pytest.raises(ValueError):
            UUID128.from_string("not-a-uuid")

    def test_wrong_length_bytes(self):
        with pytest.raises(ValueError):
            UUID128(bytes(15))

    def test_is_bluetooth_base(self):
        u = UUID16(0x180D).to_uuid128()
        assert u.is_bluetooth_base is True

    def test_is_not_bluetooth_base(self):
        u = UUID128(bytes(16))
        assert u.is_bluetooth_base is False

    def test_to_uuid16_roundtrip(self):
        original = UUID16(0x180D)
        u128 = original.to_uuid128()
        back = u128.to_uuid16()
        assert back is not None
        assert back == original

    def test_to_uuid16_non_base_returns_none(self):
        u = UUID128(bytes(16))
        assert u.to_uuid16() is None
