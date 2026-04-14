from __future__ import annotations

import struct


class ByteBuffer:
    """PDU construction and parsing helper with little-endian defaults."""

    def __init__(self, data: bytes = b"") -> None:
        self._buf = bytearray(data)
        self._offset = 0
        self._write_mode = len(data) == 0

    # ── Write operations ──

    def write_uint8(self, value: int) -> None:
        self._buf.append(value & 0xFF)

    def write_uint16(self, value: int) -> None:
        self._buf.extend(struct.pack("<H", value))

    def write_uint32(self, value: int) -> None:
        self._buf.extend(struct.pack("<I", value))

    def write_bytes(self, data: bytes) -> None:
        self._buf.extend(data)

    def getvalue(self) -> bytes:
        return bytes(self._buf)

    # ── Read operations ──

    def _check_read(self, n: int) -> None:
        if self._offset + n > len(self._buf):
            raise ValueError(
                f"Buffer underflow: need {n} bytes at offset {self._offset}, "
                f"but only {len(self._buf) - self._offset} remaining"
            )

    def read_uint8(self) -> int:
        self._check_read(1)
        val = self._buf[self._offset]
        self._offset += 1
        return val

    def read_uint16(self) -> int:
        self._check_read(2)
        val = struct.unpack_from("<H", self._buf, self._offset)[0]
        self._offset += 2
        return val

    def read_uint32(self) -> int:
        self._check_read(4)
        val = struct.unpack_from("<I", self._buf, self._offset)[0]
        self._offset += 4
        return val

    def read_bytes(self, n: int) -> bytes:
        self._check_read(n)
        val = bytes(self._buf[self._offset : self._offset + n])
        self._offset += n
        return val

    def read_remaining(self) -> bytes:
        val = bytes(self._buf[self._offset :])
        self._offset = len(self._buf)
        return val

    @property
    def remaining(self) -> int:
        return len(self._buf) - self._offset

    @property
    def offset(self) -> int:
        return self._offset

    def __len__(self) -> int:
        return len(self._buf)
