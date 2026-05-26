"""HCI feature-bitmap decoding tables.

Pure-data dictionaries mapping (octet, bit) tuples to human-readable feature
names. Used by ``pybluehost tools info`` and any future capability-introspection
tooling. No logic; safe to import without HCI state.

References:
  * Core Spec 5.4 Vol 6 Part B §4.6 (LE Features)
  * Core Spec 5.4 Vol 2 Part C §3.3 (BR/EDR LMP Features page 0)
  * Bluetooth Assigned Numbers, Company Identifiers
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# LE Features bitmap: (octet, bit) -> name
# Core Spec 5.4 Vol 6 Part B §4.6 Table 4.6.1
# ---------------------------------------------------------------------------

LE_FEATURE_BIT_NAMES: dict[tuple[int, int], str] = {
    (0, 0): "LE Encryption",
    (0, 1): "Connection Parameters Request Procedure",
    (0, 2): "Extended Reject Indication",
    (0, 3): "Slave-initiated Features Exchange",
    (0, 4): "LE Ping",
    (0, 5): "LE Data Packet Length Extension",
    (0, 6): "LL Privacy",
    (0, 7): "Extended Scanner Filter Policies",
    (1, 0): "LE 2M PHY",
    (1, 1): "Stable Modulation Index - Transmitter",
    (1, 2): "Stable Modulation Index - Receiver",
    (1, 3): "LE Coded PHY",
    (1, 4): "LE Extended Advertising",
    (1, 5): "LE Periodic Advertising",
    (1, 6): "Channel Selection Algorithm #2",
    (1, 7): "LE Power Class 1",
    (2, 0): "Minimum Number of Used Channels Procedure",
    (2, 1): "Connection CTE Request",
    (2, 2): "Connection CTE Response",
    (2, 3): "Connectionless CTE Transmitter",
    (2, 4): "Connectionless CTE Receiver",
    (2, 5): "Antenna Switching During CTE Transmission (AoD)",
    (2, 6): "Antenna Switching During CTE Reception (AoA)",
    (2, 7): "Receiving Constant Tone Extensions",
    (3, 0): "Periodic Advertising Sync Transfer - Sender",
    (3, 1): "Periodic Advertising Sync Transfer - Recipient",
    (3, 2): "Sleep Clock Accuracy Updates",
    (3, 3): "Remote Public Key Validation",
    (3, 4): "Connected Isochronous Stream - Central",
    (3, 5): "Connected Isochronous Stream - Peripheral",
    (3, 6): "Isochronous Broadcaster",
    (3, 7): "Synchronized Receiver",
    (4, 0): "Connected Isochronous Stream (Host Support)",
    (4, 1): "LE Power Control Request",
    (4, 2): "LE Power Change Indication",
    (4, 3): "LE Path Loss Monitoring",
    (4, 4): "Periodic Advertising ADI Support",
    (4, 5): "Connection Subrating",
    (4, 6): "Connection Subrating (Host Support)",
    (4, 7): "Channel Classification",
}


# ---------------------------------------------------------------------------
# BR/EDR LMP Features page 0: (octet, bit) -> name
# Core Spec 5.4 Vol 2 Part C §3.3 Table 3.2
# ---------------------------------------------------------------------------

BREDR_FEATURE_BIT_NAMES: dict[tuple[int, int], str] = {
    (0, 0): "3-slot packets",
    (0, 1): "5-slot packets",
    (0, 2): "Encryption",
    (0, 3): "Slot offset",
    (0, 4): "Timing accuracy",
    (0, 5): "Role switch",
    (0, 6): "Hold mode",
    (0, 7): "Sniff mode",
    (1, 0): "Park state",
    (1, 1): "Power control requests",
    (1, 2): "Channel quality driven data rate (CQDDR)",
    (1, 3): "SCO link",
    (1, 4): "HV2 packets",
    (1, 5): "HV3 packets",
    (1, 6): "u-law log synchronous data",
    (1, 7): "A-law log synchronous data",
    (2, 0): "CVSD synchronous data",
    (2, 1): "Paging parameter negotiation",
    (2, 2): "Power control",
    (2, 3): "Transparent synchronous data",
    (2, 4): "Flow control lag (LSB)",
    (2, 5): "Flow control lag (Middle)",
    (2, 6): "Flow control lag (MSB)",
    (2, 7): "Broadcast Encryption",
    (3, 1): "EDR ACL 2 Mbps mode",
    (3, 2): "EDR ACL 3 Mbps mode",
    (3, 3): "Enhanced inquiry scan",
    (3, 4): "Interlaced inquiry scan",
    (3, 5): "Interlaced page scan",
    (3, 6): "RSSI with inquiry results",
    (3, 7): "EV3 packets",
    (4, 0): "EV4 packets",
    (4, 1): "EV5 packets",
    (4, 3): "AFH capable peripheral",
    (4, 4): "AFH classification peripheral",
    (4, 5): "BR/EDR Not Supported",
    (4, 6): "LE Supported (Controller)",
    (4, 7): "3-slot EDR ACL packets",
    (5, 0): "5-slot EDR ACL packets",
    (5, 1): "Sniff subrating",
    (5, 2): "Pause Encryption",
    (5, 3): "AFH capable central",
    (5, 4): "AFH classification central",
    (5, 5): "EDR eSCO 2 Mbps mode",
    (5, 6): "EDR eSCO 3 Mbps mode",
    (5, 7): "3-slot EDR eSCO packets",
    (6, 0): "Extended Inquiry Response",
    (6, 1): "Simultaneous LE and BR/EDR to Same Device Capable (Controller)",
    (6, 3): "Secure Simple Pairing (Controller Support)",
    (6, 4): "Encapsulated PDU",
    (6, 5): "Erroneous Data Reporting",
    (6, 6): "Non-flushable Packet Boundary Flag",
    (7, 0): "HCI_Link_Supervision_Timeout_Changed Event",
    (7, 1): "Variable Inquiry TX Power Level",
    (7, 2): "Enhanced Power Control",
    (7, 7): "Extended features",
}


# ---------------------------------------------------------------------------
# BR/EDR LMP Features page 1 — host-side features
# Core Spec 5.4 Vol 2 Part C §3.3 Table 3.3
# ---------------------------------------------------------------------------

BREDR_FEATURE_BIT_NAMES_P1: dict[tuple[int, int], str] = {
    (0, 0): "Secure Simple Pairing (Host Support)",
    (0, 1): "LE Supported (Host)",
    (0, 2): "Simultaneous LE and BR/EDR to Same Device Capable (Host)",
    (0, 3): "Secure Connections (Host Support)",
}


# ---------------------------------------------------------------------------
# BR/EDR LMP Features page 2 — extended controller-side features
# Core Spec 5.4 Vol 2 Part C §3.3 Table 3.4
# ---------------------------------------------------------------------------

BREDR_FEATURE_BIT_NAMES_P2: dict[tuple[int, int], str] = {
    (0, 0): "Connectionless Slave Broadcast - Transmitter Operation",
    (0, 1): "Connectionless Slave Broadcast - Receiver Operation",
    (0, 2): "Synchronization Train",
    (0, 3): "Synchronization Scan",
    (0, 4): "HCI_Inquiry_Response_Notification Event",
    (0, 5): "Generalized interlaced scan",
    (0, 6): "Coarse Clock Adjustment",
    (1, 0): "Secure Connections (Controller Support)",
    (1, 1): "Ping",
    (1, 2): "Slot Availability Mask",
    (1, 3): "Train Nudging",
}


# ---------------------------------------------------------------------------
# Bluetooth SIG Company Identifiers (common chipset vendors)
# Full list: https://www.bluetooth.com/specifications/assigned-numbers/company-identifiers/
# ---------------------------------------------------------------------------

MANUFACTURER_NAMES: dict[int, str] = {
    0x0001: "Nokia Mobile Phones",
    0x0002: "Intel Corp.",
    0x0003: "IBM Corp.",
    0x0004: "Toshiba Corp.",
    0x0005: "3Com",
    0x0006: "Microsoft",
    0x0007: "Lucent",
    0x0008: "Motorola",
    0x0009: "Infineon Technologies AG",
    0x000A: "CSR (Qualcomm)",
    0x000B: "Silicon Wave",
    0x000C: "Digianswer A/S",
    0x000D: "Texas Instruments Inc.",
    0x000F: "Broadcom Corporation",
    0x001D: "Atheros Communications",
    0x004C: "Apple Inc.",
    0x005D: "Realtek Semiconductor Corp.",
    0x005F: "MediaTek, Inc.",
    0x0075: "Samsung Electronics Co. Ltd.",
    0x00E0: "Google",
    0x05A7: "Linux Foundation",
}


def manufacturer_name(manufacturer_id: int) -> str:
    """Return the human-readable name for a Bluetooth SIG company identifier,
    or ``"Unknown (0x....)"`` for IDs not in :data:`MANUFACTURER_NAMES`.
    """
    return MANUFACTURER_NAMES.get(
        manufacturer_id, f"Unknown (0x{manufacturer_id:04X})"
    )


# ---------------------------------------------------------------------------
# HCI / LMP version identifiers
# Core Spec 5.4 Vol 4 Part E §7.4.1, also Assigned Numbers - Host Controller
# Interface. HCI_Version and LMP_Version share the same enumeration.
# ---------------------------------------------------------------------------

HCI_VERSION_NAMES: dict[int, str] = {
    0x00: "Bluetooth 1.0b",
    0x01: "Bluetooth 1.1",
    0x02: "Bluetooth 1.2",
    0x03: "Bluetooth 2.0 + EDR",
    0x04: "Bluetooth 2.1 + EDR",
    0x05: "Bluetooth 3.0 + HS",
    0x06: "Bluetooth 4.0",
    0x07: "Bluetooth 4.1",
    0x08: "Bluetooth 4.2",
    0x09: "Bluetooth 5.0",
    0x0A: "Bluetooth 5.1",
    0x0B: "Bluetooth 5.2",
    0x0C: "Bluetooth 5.3",
    0x0D: "Bluetooth 5.4",
    0x0E: "Bluetooth 6.0",
}


def hci_version_name(version: int) -> str:
    """Human-readable name for an HCI_Version / LMP_Version byte.

    Returns "Unknown (0x..)" for values not in :data:`HCI_VERSION_NAMES`.
    """
    return HCI_VERSION_NAMES.get(version, f"Unknown (0x{version:02X})")
