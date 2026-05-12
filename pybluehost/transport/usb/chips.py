"""USB chip identification dataclass.

ChipInfo identifies a known Bluetooth USB chip by VID/PID and links it to
the concrete Transport subclass that knows how to initialize it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChipInfo:
    """Known Bluetooth USB chip metadata.

    Fields:
        vendor: vendor family slug (e.g. "intel", "realtek", "csr", "barrot")
        name: human-readable chip name (e.g. "AX200", "RTL8852BE")
        vid: USB vendor ID
        pid: USB product ID
        firmware_pattern: glob pattern matching firmware files this chip needs
            (empty string for chips that need no firmware load)
        transport_class: Transport subclass to instantiate for this chip
    """
    vendor: str
    name: str
    vid: int
    pid: int
    firmware_pattern: str
    transport_class: type | None  # filled by KNOWN_CHIPS in __init__.py after subclass imports
