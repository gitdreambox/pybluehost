"""Codec-shared primitives: bit-aligned I/O + SBC CRC-8."""
from __future__ import annotations


class BitWriter:
    """MSB-first bit-aligned writer; output is zero-padded to next byte."""

    __slots__ = ("_buf", "_acc", "_bits")

    def __init__(self) -> None:
        self._buf: bytearray = bytearray()
        self._acc: int = 0
        self._bits: int = 0

    def write(self, value: int, width: int) -> None:
        if width <= 0:
            raise ValueError("width must be > 0")
        if value < 0 or value >= (1 << width):
            raise ValueError(f"value {value} exceeds {width} bits")
        self._acc = (self._acc << width) | value
        self._bits += width
        while self._bits >= 8:
            self._bits -= 8
            self._buf.append((self._acc >> self._bits) & 0xFF)
            self._acc &= (1 << self._bits) - 1

    def finish(self) -> bytes:
        if self._bits > 0:
            self._buf.append((self._acc << (8 - self._bits)) & 0xFF)
            self._acc = 0
            self._bits = 0
        return bytes(self._buf)


class BitReader:
    """MSB-first bit-aligned reader; raises IndexError when input exhausted."""

    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes | bytearray) -> None:
        self._data = bytes(data)
        self._pos: int = 0

    def read(self, width: int) -> int:
        if width <= 0:
            raise ValueError("width must be > 0")
        if self._pos + width > len(self._data) * 8:
            raise IndexError("BitReader: out of data")
        value = 0
        for _ in range(width):
            byte_idx = self._pos >> 3
            bit_idx = 7 - (self._pos & 7)
            value = (value << 1) | ((self._data[byte_idx] >> bit_idx) & 1)
            self._pos += 1
        return value

    def remaining_bits(self) -> int:
        return len(self._data) * 8 - self._pos


def sbc_crc8(data: bytes, num_bits: int) -> int:
    """Compute the SBC frame-header CRC-8 over `num_bits` MSB-first bits of `data`.

    Polynomial 0x1D (x^8 + x^4 + x^3 + x^2 + 1), initial value 0x0F. Spec: A2DP v1.4 §B.4.

    Note: per the spec, the 8-bit flush phase runs unconditionally, so
    ``sbc_crc8(data, 0) == 0xBB`` regardless of ``data`` (init value flushed through
    the polynomial 8 times). In practice the SBC header builder always passes
    num_bits > 0.
    """
    if num_bits < 0 or num_bits > len(data) * 8:
        raise ValueError("num_bits out of range for input data")
    crc = 0x0F
    for i in range(num_bits):
        byte_idx = i >> 3
        bit_idx = 7 - (i & 7)
        bit = (data[byte_idx] >> bit_idx) & 1
        # Shift-and-XOR variant of bit-serial CRC-8 / 0x1D:
        top = (crc >> 7) & 1
        crc = ((crc << 1) | bit) & 0xFF
        if top:
            crc ^= 0x1D
    # Spec: after consuming all data bits, do 8 extra zero-shifts to flush the register.
    for _ in range(8):
        top = (crc >> 7) & 1
        crc = (crc << 1) & 0xFF
        if top:
            crc ^= 0x1D
    return crc
