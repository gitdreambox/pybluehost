"""Per-field formatters used by format_hci_packet().

Each function takes a raw value and returns a short human-readable string.
SIG-DB lookups are passed in as callables so this module stays pure
(no module-level I/O); the caller wires sig_db.
"""
from __future__ import annotations

from typing import Callable

# Standard HCI status / error codes (Core spec Vol 2 Part D §1.3).
_STATUS_NAMES: dict[int, str] = {
    0x00: "Success",
    0x01: "Unknown_HCI_Command",
    0x02: "Unknown_Connection_Identifier",
    0x03: "Hardware_Failure",
    0x04: "Page_Timeout",
    0x05: "Authentication_Failure",
    0x06: "PIN_Or_Key_Missing",
    0x07: "Memory_Capacity_Exceeded",
    0x08: "Connection_Timeout",
    0x09: "Connection_Limit_Exceeded",
    0x0A: "Synchronous_Connection_Limit_Exceeded",
    0x0B: "Connection_Already_Exists",
    0x0C: "Command_Disallowed",
    0x0D: "Connection_Rejected_Limited_Resources",
    0x0E: "Connection_Rejected_Security_Reasons",
    0x0F: "Connection_Rejected_Unacceptable_BD_ADDR",
    0x10: "Connection_Accept_Timeout_Exceeded",
    0x11: "Unsupported_Feature_Or_Parameter",
    0x12: "Invalid_HCI_Command_Parameters",
    0x13: "Remote_User_Terminated_Connection",
    0x14: "Remote_Device_Terminated_Low_Resources",
    0x15: "Remote_Device_Terminated_Power_Off",
    0x16: "Connection_Terminated_By_Local_Host",
    0x17: "Repeated_Attempts",
    0x18: "Pairing_Not_Allowed",
    # Truncated; extend as needed.
}

_ADDR_TYPE_NAMES: dict[int, str] = {
    0: "PUBLIC",
    1: "RANDOM",
    2: "PUBLIC_IDENTITY",
    3: "RANDOM_IDENTITY",
}

_LE_PHY_NAMES: dict[int, str] = {
    1: "1M",
    2: "2M",
    3: "Coded",
    4: "Coded_S2",
}

_ROLE_NAMES: dict[int, str] = {
    0: "Central",
    1: "Peripheral",
}


def format_address(addr_bytes: bytes, *, addr_type: int) -> str:
    """Render BD_ADDR with address-type prefix (Public / Random / ...)."""
    label = "Public" if addr_type == 0 else "Random"
    msb_first = bytes(reversed(addr_bytes))
    hex_str = ":".join(f"{b:02X}" for b in msb_first)
    return f"{label} {hex_str}"


def format_address_type(value: int) -> str:
    return _ADDR_TYPE_NAMES.get(value, f"0x{value:02X}")


def format_status(value: int) -> str:
    name = _STATUS_NAMES.get(value)
    if name is None:
        return f"0x{value:02X}"
    if value == 0x00:
        return name
    return f"{name}(0x{value:02X})"


# Alias used by error-code-only event fields.
format_error_code = format_status


def format_le_phy(value: int) -> str:
    return _LE_PHY_NAMES.get(value, f"0x{value:02X}")


def format_role(value: int) -> str:
    return _ROLE_NAMES.get(value, f"0x{value:02X}")


def format_scan_interval(value: int) -> str:
    """LE scan / adv interval: raw units of 0.625 ms."""
    ms = value * 0.625
    return f"0x{value:04X} ({ms:.1f} ms)"


def format_rssi(value: int) -> str:
    """LE RSSI in dBm; per Core spec 127 means 'not available'."""
    if value == 127:
        return "N/A"
    return f"{value} dBm"


def format_uuid16(value: int, *, sig_lookup: Callable[[int], str | None]) -> str:
    """16-bit UUID; appends the SIG name when sig_lookup returns one."""
    name = sig_lookup(value)
    if name is None:
        return f"0x{value:04X}"
    return f"0x{value:04X} ({name})"


def format_company_id(value: int) -> str:
    """Company identifier (Bluetooth assigned numbers)."""
    from pybluehost.core.sig_db import SIGDatabase

    name = SIGDatabase.get().company_name(value)
    if name is None:
        return f"0x{value:04X}"
    return f"0x{value:04X} ({name})"


def format_uuid16_default(value: int) -> str:
    """16-bit UUID using the project SIGDatabase for lookup."""
    from pybluehost.core.sig_db import SIGDatabase

    db = SIGDatabase.get()

    def lookup(v: int) -> str | None:
        return (
            db.service_name(v)
            or db.characteristic_name(v)
            or db.descriptor_name(v)
        )

    return format_uuid16(value, sig_lookup=lookup)


def format_uuid128(raw: bytes) -> str:
    """128-bit UUID in canonical xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx form."""
    if len(raw) != 16:
        raise ValueError(f"UUID128 must be 16 bytes, got {len(raw)}")
    msb_first = bytes(reversed(raw))
    h = msb_first.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# Major Service Class bits (CoD octets 13..23, here we encode the most useful subset).
_COD_MAJOR_DEVICE_CLASS: dict[int, str] = {
    0x00: "Miscellaneous",
    0x01: "Computer",
    0x02: "Phone",
    0x03: "LAN/Network_Access_Point",
    0x04: "Audio/Video",
    0x05: "Peripheral",
    0x06: "Imaging",
    0x07: "Wearable",
    0x08: "Toy",
    0x09: "Health",
    0x1F: "Uncategorized",
}

# Phone minor classes (when major = 0x02).
_COD_PHONE_MINOR: dict[int, str] = {
    0x00: "Uncategorized",
    0x01: "Cellular",
    0x02: "Cordless",
    0x03: "Smartphone",
    0x04: "Wired_Modem_Or_Voice_Gateway",
    0x05: "ISDN",
}


def format_class_of_device(value: int) -> str:
    """Class of Device (24-bit) -> '0xNNNNNN (Major, Minor)' if classifiable."""
    major = (value >> 8) & 0x1F
    minor = (value >> 2) & 0x3F
    major_name = _COD_MAJOR_DEVICE_CLASS.get(major)
    if major_name is None:
        return f"0x{value:06X}"
    if major == 0x02:
        minor_name = _COD_PHONE_MINOR.get(minor, f"minor=0x{minor:02X}")
        return f"0x{value:06X} ({major_name}, {minor_name})"
    return f"0x{value:06X} ({major_name})"


def format_ad_type(value: int) -> str:
    """Advertising data type byte; uses SIG DB ad_type_name."""
    from pybluehost.core.sig_db import SIGDatabase

    name = SIGDatabase.get().ad_type_name(value)
    if name is None:
        return f"0x{value:02X}"
    return f"0x{value:02X} ({name})"
