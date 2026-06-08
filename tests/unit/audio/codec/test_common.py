import pytest

from pybluehost.audio.codec._common import BitReader, BitWriter


def test_bitwriter_byte_boundary_round_trip():
    w = BitWriter()
    w.write(0xAB, 8)
    w.write(0xCD, 8)
    assert bytes(w.finish()) == b"\xAB\xCD"


def test_bitwriter_non_byte_aligned():
    w = BitWriter()
    w.write(0b1101, 4)
    w.write(0b1010, 4)
    assert bytes(w.finish()) == b"\xDA"


def test_bitwriter_multiple_widths_round_trip():
    w = BitWriter()
    w.write(0b1, 1)
    w.write(0xABC, 12)         # 12 bits
    w.write(0x7, 3)            # total = 1 + 12 + 3 = 16 bits = 2 bytes
    data = bytes(w.finish())
    assert len(data) == 2

    r = BitReader(data)
    assert r.read(1) == 0b1
    assert r.read(12) == 0xABC
    assert r.read(3) == 0x7


def test_bitwriter_pads_to_byte_boundary():
    w = BitWriter()
    w.write(0b101, 3)
    data = bytes(w.finish())
    # 3 bits written → padded with 5 zero bits → 0b10100000 = 0xA0
    assert data == b"\xA0"


def test_bitreader_out_of_data_raises():
    r = BitReader(b"\xFF")
    r.read(8)                  # ok
    with pytest.raises(IndexError):
        r.read(1)


def test_bitwriter_rejects_value_too_large():
    w = BitWriter()
    with pytest.raises(ValueError, match="exceeds"):
        w.write(0x100, 8)      # 256 doesn't fit in 8 bits
