import pytest
from pybluehost.core.buffer import ByteBuffer


class TestByteBufferWrite:
    def test_write_uint8(self):
        buf = ByteBuffer()
        buf.write_uint8(0xFF)
        assert buf.getvalue() == b"\xFF"

    def test_write_uint16_le(self):
        buf = ByteBuffer()
        buf.write_uint16(0x1234)
        assert buf.getvalue() == b"\x34\x12"

    def test_write_uint32_le(self):
        buf = ByteBuffer()
        buf.write_uint32(0x12345678)
        assert buf.getvalue() == b"\x78\x56\x34\x12"

    def test_write_bytes(self):
        buf = ByteBuffer()
        buf.write_bytes(b"\x01\x02\x03")
        assert buf.getvalue() == b"\x01\x02\x03"

    def test_write_address(self):
        buf = ByteBuffer()
        buf.write_bytes(bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06]))
        assert len(buf.getvalue()) == 6

    def test_chaining(self):
        buf = ByteBuffer()
        buf.write_uint8(0x01)
        buf.write_uint16(0x0200)
        buf.write_bytes(b"\xAA")
        assert buf.getvalue() == b"\x01\x00\x02\xAA"

    def test_len(self):
        buf = ByteBuffer()
        buf.write_uint8(0x01)
        buf.write_uint16(0x0200)
        assert len(buf) == 3


class TestByteBufferRead:
    def test_read_uint8(self):
        buf = ByteBuffer(b"\xFF\xAA")
        assert buf.read_uint8() == 0xFF
        assert buf.read_uint8() == 0xAA

    def test_read_uint16_le(self):
        buf = ByteBuffer(b"\x34\x12")
        assert buf.read_uint16() == 0x1234

    def test_read_uint32_le(self):
        buf = ByteBuffer(b"\x78\x56\x34\x12")
        assert buf.read_uint32() == 0x12345678

    def test_read_bytes(self):
        buf = ByteBuffer(b"\x01\x02\x03\x04")
        assert buf.read_bytes(3) == b"\x01\x02\x03"
        assert buf.read_bytes(1) == b"\x04"

    def test_read_remaining(self):
        buf = ByteBuffer(b"\x01\x02\x03")
        buf.read_uint8()
        assert buf.read_remaining() == b"\x02\x03"

    def test_read_past_end_raises(self):
        buf = ByteBuffer(b"\x01")
        buf.read_uint8()
        with pytest.raises(ValueError, match="underflow"):
            buf.read_uint8()

    def test_remaining_count(self):
        buf = ByteBuffer(b"\x01\x02\x03")
        assert buf.remaining == 3
        buf.read_uint8()
        assert buf.remaining == 2

    def test_offset_tracking(self):
        buf = ByteBuffer(b"\x01\x02\x03")
        assert buf.offset == 0
        buf.read_uint8()
        assert buf.offset == 1
        buf.read_uint16()
        assert buf.offset == 3
