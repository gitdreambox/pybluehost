from __future__ import annotations

import re
from dataclasses import dataclass

# Bluetooth Base UUID: 00000000-0000-1000-8000-00805F9B34FB
BLUETOOTH_BASE_UUID = bytes([
    0x00, 0x00, 0x00, 0x00,  # bytes 0-3 (UUID16 goes in bytes 2-3)
    0x00, 0x00,              # bytes 4-5
    0x10, 0x00,              # bytes 6-7
    0x80, 0x00,              # bytes 8-9
    0x00, 0x80, 0x5F, 0x9B, 0x34, 0xFB,  # bytes 10-15
])

_UUID_RE = re.compile(
    r"^([0-9a-fA-F]{8})-([0-9a-fA-F]{4})-([0-9a-fA-F]{4})"
    r"-([0-9a-fA-F]{4})-([0-9a-fA-F]{12})$"
)


@dataclass(frozen=True)
class UUID16:
    """16-bit Bluetooth UUID."""

    value: int

    def __post_init__(self) -> None:
        if not (0 <= self.value <= 0xFFFF):
            raise ValueError(f"UUID16 value must be 0x0000-0xFFFF, got {self.value:#x}")

    def to_bytes(self) -> bytes:
        return self.value.to_bytes(2, "little")

    @classmethod
    def from_bytes(cls, data: bytes) -> UUID16:
        if len(data) != 2:
            raise ValueError(f"UUID16 requires 2 bytes, got {len(data)}")
        return cls(int.from_bytes(data, "little"))

    def to_uuid128(self) -> UUID128:
        buf = bytearray(BLUETOOTH_BASE_UUID)
        buf[2] = (self.value >> 8) & 0xFF
        buf[3] = self.value & 0xFF
        return UUID128(bytes(buf))

    def __str__(self) -> str:
        return f"0x{self.value:04X}"


@dataclass(frozen=True)
class UUID128:
    """128-bit UUID.

    Internal `value` is stored in RFC 4122 big-endian byte order, matching
    the hyphenated string form (e.g. ``0000180d-0000-1000-8000-00805f9b34fb``).

    ATT/HCI wire encoding requires little-endian. Callers writing to the wire
    must reverse the bytes; a future ATT layer is expected to provide a
    ``to_bytes_le()`` helper or do the reversal inline.
    """

    value: bytes

    def __post_init__(self) -> None:
        if len(self.value) != 16:
            raise ValueError(f"UUID128 requires 16 bytes, got {len(self.value)}")

    @classmethod
    def from_string(cls, s: str) -> UUID128:
        m = _UUID_RE.match(s)
        if not m:
            raise ValueError(f"Invalid UUID128 string: {s}")
        hex_str = "".join(m.groups())
        return cls(bytes.fromhex(hex_str))

    @classmethod
    def from_bytes(cls, data: bytes) -> UUID128:
        if len(data) != 16:
            raise ValueError(f"UUID128 requires 16 bytes, got {len(data)}")
        return cls(data)

    def to_bytes(self) -> bytes:
        return self.value

    @property
    def is_bluetooth_base(self) -> bool:
        return (
            self.value[0:2] == BLUETOOTH_BASE_UUID[0:2]
            and self.value[4:] == BLUETOOTH_BASE_UUID[4:]
        )

    def to_uuid16(self) -> UUID16 | None:
        if not self.is_bluetooth_base:
            return None
        return UUID16((self.value[2] << 8) | self.value[3])

    def __str__(self) -> str:
        h = self.value.hex()
        return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
