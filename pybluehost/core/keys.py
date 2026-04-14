from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class LinkKeyType(IntEnum):
    UNAUTHENTICATED_P192 = 0x04
    AUTHENTICATED_P192 = 0x05
    UNAUTHENTICATED_P256 = 0x07
    AUTHENTICATED_P256 = 0x08


def _validate_16(value: bytes, name: str) -> None:
    if len(value) != 16:
        raise ValueError(f"{name} requires 16 bytes, got {len(value)}")


@dataclass(frozen=True)
class LinkKey:
    """BR/EDR Link Key."""
    value: bytes
    key_type: LinkKeyType

    def __post_init__(self) -> None:
        _validate_16(self.value, "LinkKey")


@dataclass(frozen=True)
class LTK:
    """BLE Long Term Key."""
    value: bytes
    ediv: int
    rand: int
    key_size: int = 16

    def __post_init__(self) -> None:
        _validate_16(self.value, "LTK")


@dataclass(frozen=True)
class IRK:
    """Identity Resolving Key."""
    value: bytes

    def __post_init__(self) -> None:
        _validate_16(self.value, "IRK")


@dataclass(frozen=True)
class CSRK:
    """Connection Signature Resolving Key."""
    value: bytes

    def __post_init__(self) -> None:
        _validate_16(self.value, "CSRK")
