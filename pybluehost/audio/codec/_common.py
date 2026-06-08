"""Codec-shared primitives: bit-aligned I/O for SBC and other audio codecs."""
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
