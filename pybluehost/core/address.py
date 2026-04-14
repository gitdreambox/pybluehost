from __future__ import annotations

import os
from dataclasses import dataclass
from enum import IntEnum


class AddressType(IntEnum):
    PUBLIC = 0x00
    RANDOM = 0x01
    PUBLIC_IDENTITY = 0x02
    RANDOM_IDENTITY = 0x03


@dataclass(frozen=True)
class BDAddress:
    """Bluetooth Device Address (6 bytes + type)."""

    address: bytes
    type: AddressType = AddressType.PUBLIC

    @classmethod
    def from_string(cls, s: str, type: AddressType = AddressType.PUBLIC) -> BDAddress:
        parts = s.split(":")
        if len(parts) != 6:
            raise ValueError(f"Expected 6 colon-separated hex bytes, got {len(parts)}")
        raw = bytes(int(p, 16) for p in parts)
        return cls(address=raw, type=type)

    @classmethod
    def random(cls) -> BDAddress:
        raw = bytearray(os.urandom(6))
        raw[0] = (raw[0] & 0x3F) | 0xC0  # static random: top 2 bits = 11
        return cls(address=bytes(raw), type=AddressType.RANDOM)

    @property
    def is_rpa(self) -> bool:
        if self.type != AddressType.RANDOM:
            return False
        return (self.address[0] & 0xC0) == 0x40

    def __str__(self) -> str:
        return ":".join(f"{b:02X}" for b in self.address)
