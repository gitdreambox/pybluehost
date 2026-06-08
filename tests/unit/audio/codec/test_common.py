import pytest

from pybluehost.audio.codec._common import BitReader, BitWriter, sbc_crc8


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
    assert data == b"\xD5\xE7"

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


def test_bitreader_remaining_bits():
    r = BitReader(b"\xAB\xCD")
    assert r.remaining_bits() == 16
    r.read(8)
    assert r.remaining_bits() == 8
    r.read(8)
    assert r.remaining_bits() == 0


def test_bitwriter_width_greater_than_byte():
    """16-bit write produces 2 bytes MSB-first."""
    w = BitWriter()
    w.write(0xABCD, 16)
    assert bytes(w.finish()) == b"\xAB\xCD"


def test_sbc_crc8_known_value():
    """Discriminating input — flush vs no-flush produces different values here.

    0x1234 / 16 bits: with flush=0x94, without flush=0x60. A missing flush loop
    would cause this test to fail, confirming the flush is exercised.
    """
    # 0x1234/16: flush=0x94, no-flush=0x60. Verifies the 8-bit flush is present.
    assert sbc_crc8(b"\x12\x34", num_bits=16) == 0x94


def test_sbc_crc8_zero_input():
    crc = sbc_crc8(b"\x00\x00", num_bits=16)
    # All-zero input: the polynomial only advances when an input bit causes
    # the MSB of the accumulator to be 1 after shift. Verify behaviour matches
    # bit-serial CRC-8 / 0x1D / init 0x0F.
    assert crc == 0x86


def test_sbc_crc8_partial_byte():
    """When num_bits is not a multiple of 8, only the leading `num_bits` bits matter."""
    crc = sbc_crc8(b"\xFF\xF8", num_bits=13)
    assert crc == 0x0A


def test_sbc_crc8_zero_num_bits_flushes_init():
    """num_bits=0 still runs the 8-bit flush on the init value (0x0F)."""
    assert sbc_crc8(b"", 0) == 0xBB
    assert sbc_crc8(b"\xFF\xFF", 0) == 0xBB    # data ignored when num_bits=0
