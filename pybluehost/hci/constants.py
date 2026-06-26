"""HCI constants: opcodes, event codes, error codes, packet type indicators.

Reference: Bluetooth Core Spec Vol 4, Part E.
"""

from __future__ import annotations

from enum import IntEnum


class OGF(IntEnum):
    """Opcode Group Field values."""

    LINK_CONTROL = 0x01
    LINK_POLICY = 0x02
    CONTROLLER_BB = 0x03
    INFO_PARAMS = 0x04
    STATUS_PARAMS = 0x05
    TESTING = 0x06
    LE = 0x08
    VENDOR = 0x3F


def make_opcode(ogf: int, ocf: int) -> int:
    """Construct a 16-bit HCI opcode from OGF and OCF."""
    return (ogf << 10) | (ocf & 0x03FF)


def ogf_ocf(opcode: int) -> tuple[int, int]:
    """Extract (OGF, OCF) from a 16-bit HCI opcode."""
    return (opcode >> 10) & 0x3F, opcode & 0x03FF


# ---------------------------------------------------------------------------
# Named opcodes — Link Control (OGF=0x01)
# ---------------------------------------------------------------------------
HCI_INQUIRY = make_opcode(OGF.LINK_CONTROL, 0x01)
HCI_INQUIRY_CANCEL = make_opcode(OGF.LINK_CONTROL, 0x02)
HCI_CREATE_CONNECTION = make_opcode(OGF.LINK_CONTROL, 0x05)
HCI_DISCONNECT = make_opcode(OGF.LINK_CONTROL, 0x06)
HCI_ACCEPT_CONNECTION_REQ = make_opcode(OGF.LINK_CONTROL, 0x09)
HCI_REJECT_CONNECTION_REQ = make_opcode(OGF.LINK_CONTROL, 0x0A)
HCI_LINK_KEY_REQUEST_REPLY = make_opcode(OGF.LINK_CONTROL, 0x0B)
HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY = make_opcode(OGF.LINK_CONTROL, 0x0C)
HCI_CHANGE_CONNECTION_PACKET_TYPE = make_opcode(OGF.LINK_CONTROL, 0x0F)


# Classic ACL packet-type mask bits (Core Spec Vol 4 Part E §7.1.14).
#
# Spec quirk worth burning in: BR bits ("may be used") are positive, but
# EDR bits ("shall NOT be used") are INVERTED. That is, setting bit
# TWO_DH1_DISALLOW disables 2-DH1; clearing it allows. Real adapters silently
# fall back to whatever the mask permits, so getting these wrong looks like
# "throughput just went down" rather than a hard error.
class ClassicPacketType:
    """Bitmask values for HCI_Change_Connection_Packet_Type."""

    # BR (1 Mbps) — set bit = packet type allowed
    DM1 = 0x0008
    DH1 = 0x0010
    DM3 = 0x0400
    DH3 = 0x0800
    DM5 = 0x4000
    DH5 = 0x8000

    # EDR (2 Mbps / 3 Mbps) — set bit = packet type DISALLOWED
    TWO_DH1_DISALLOW = 0x0002
    THREE_DH1_DISALLOW = 0x0004
    TWO_DH3_DISALLOW = 0x0100
    THREE_DH3_DISALLOW = 0x0200
    TWO_DH5_DISALLOW = 0x1000
    THREE_DH5_DISALLOW = 0x2000

    # Convenience aggregates
    ALL_BR = DM1 | DH1 | DM3 | DH3 | DM5 | DH5
    ALL_2DH_DISALLOW = TWO_DH1_DISALLOW | TWO_DH3_DISALLOW | TWO_DH5_DISALLOW
    ALL_3DH_DISALLOW = THREE_DH1_DISALLOW | THREE_DH3_DISALLOW | THREE_DH5_DISALLOW
HCI_PIN_CODE_REQUEST_REPLY = make_opcode(OGF.LINK_CONTROL, 0x0D)
HCI_PIN_CODE_REQUEST_NEGATIVE_REPLY = make_opcode(OGF.LINK_CONTROL, 0x0E)
HCI_AUTH_REQUESTED = make_opcode(OGF.LINK_CONTROL, 0x11)
HCI_SET_CONNECTION_ENCRYPTION = make_opcode(OGF.LINK_CONTROL, 0x13)
HCI_SETUP_SYNCHRONOUS_CONNECTION = make_opcode(OGF.LINK_CONTROL, 0x28)  # Core §7.1.41
HCI_REMOTE_NAME_REQUEST = make_opcode(OGF.LINK_CONTROL, 0x19)
HCI_IO_CAPABILITY_REQUEST_REPLY = make_opcode(OGF.LINK_CONTROL, 0x2B)
HCI_USER_CONFIRMATION_REQUEST_REPLY = make_opcode(OGF.LINK_CONTROL, 0x2C)
HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY = make_opcode(OGF.LINK_CONTROL, 0x2D)
HCI_IO_CAPABILITY_REQUEST_NEGATIVE_REPLY = make_opcode(OGF.LINK_CONTROL, 0x34)

# ---------------------------------------------------------------------------
# Controller & Baseband (OGF=0x03)
# ---------------------------------------------------------------------------
HCI_SET_EVENT_MASK = make_opcode(OGF.CONTROLLER_BB, 0x01)
HCI_RESET = make_opcode(OGF.CONTROLLER_BB, 0x03)
HCI_WRITE_LOCAL_NAME = make_opcode(OGF.CONTROLLER_BB, 0x13)
HCI_READ_LOCAL_NAME = make_opcode(OGF.CONTROLLER_BB, 0x14)
HCI_WRITE_SCAN_ENABLE = make_opcode(OGF.CONTROLLER_BB, 0x1A)
HCI_WRITE_AUTHENTICATION_ENABLE = make_opcode(OGF.CONTROLLER_BB, 0x20)
HCI_WRITE_CLASS_OF_DEVICE = make_opcode(OGF.CONTROLLER_BB, 0x24)
HCI_HOST_BUFFER_SIZE = make_opcode(OGF.CONTROLLER_BB, 0x33)
HCI_WRITE_EXTENDED_INQUIRY_RESPONSE = make_opcode(OGF.CONTROLLER_BB, 0x52)
HCI_WRITE_SIMPLE_PAIRING_MODE = make_opcode(OGF.CONTROLLER_BB, 0x56)
HCI_WRITE_LE_HOST_SUPPORTED = make_opcode(OGF.CONTROLLER_BB, 0x6D)
HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT = make_opcode(OGF.CONTROLLER_BB, 0x7A)

# ---------------------------------------------------------------------------
# Informational Parameters (OGF=0x04)
# ---------------------------------------------------------------------------
HCI_READ_LOCAL_VERSION = make_opcode(OGF.INFO_PARAMS, 0x01)
HCI_READ_LOCAL_SUPPORTED_COMMANDS = make_opcode(OGF.INFO_PARAMS, 0x02)
HCI_READ_LOCAL_SUPPORTED_FEATURES = make_opcode(OGF.INFO_PARAMS, 0x03)
HCI_READ_LOCAL_EXTENDED_FEATURES = make_opcode(OGF.INFO_PARAMS, 0x04)
HCI_READ_BUFFER_SIZE = make_opcode(OGF.INFO_PARAMS, 0x05)
HCI_READ_BD_ADDR = make_opcode(OGF.INFO_PARAMS, 0x09)

# ---------------------------------------------------------------------------
# LE Controller (OGF=0x08)
# ---------------------------------------------------------------------------
HCI_LE_SET_EVENT_MASK = make_opcode(OGF.LE, 0x01)
HCI_LE_READ_BUFFER_SIZE = make_opcode(OGF.LE, 0x02)
HCI_LE_READ_LOCAL_SUPPORTED_FEATURES = make_opcode(OGF.LE, 0x03)
HCI_LE_SET_RANDOM_ADDRESS = make_opcode(OGF.LE, 0x05)
HCI_LE_SET_ADVERTISING_PARAMS = make_opcode(OGF.LE, 0x06)
HCI_LE_SET_ADVERTISING_DATA = make_opcode(OGF.LE, 0x08)
HCI_LE_SET_SCAN_RESPONSE_DATA = make_opcode(OGF.LE, 0x09)
HCI_LE_SET_ADVERTISE_ENABLE = make_opcode(OGF.LE, 0x0A)
HCI_LE_SET_SCAN_PARAMS = make_opcode(OGF.LE, 0x0B)
HCI_LE_SET_SCAN_ENABLE = make_opcode(OGF.LE, 0x0C)
HCI_LE_CREATE_CONNECTION = make_opcode(OGF.LE, 0x0D)
HCI_LE_CREATE_CONNECTION_CANCEL = make_opcode(OGF.LE, 0x0E)
HCI_LE_CLEAR_WHITE_LIST = make_opcode(OGF.LE, 0x10)
HCI_LE_ADD_DEVICE_TO_WHITE_LIST = make_opcode(OGF.LE, 0x11)
HCI_LE_REMOVE_DEVICE_FROM_WHITE_LIST = make_opcode(OGF.LE, 0x12)
HCI_LE_READ_SUPPORTED_STATES = make_opcode(OGF.LE, 0x1C)
HCI_LE_SET_DATA_LENGTH = make_opcode(OGF.LE, 0x22)
HCI_LE_READ_LOCAL_P256_PUBLIC_KEY = make_opcode(OGF.LE, 0x0025)
HCI_LE_GENERATE_DHKEY = make_opcode(OGF.LE, 0x0026)
HCI_LE_ADD_DEVICE_TO_RESOLVING_LIST = make_opcode(OGF.LE, 0x27)
HCI_LE_CLEAR_RESOLVING_LIST = make_opcode(OGF.LE, 0x29)
HCI_LE_SET_ADDRESS_RESOLUTION_ENABLE = make_opcode(OGF.LE, 0x2D)
HCI_LE_SET_PHY = make_opcode(OGF.LE, 0x32)


# LE PHY values (Core Spec Vol 4 Part E §7.8.49 LE_Set_PHY,
# §7.7.65.12 LE_PHY_Update_Complete event).
#
# Command parameters TX_PHYS/RX_PHYS are bitfields (bit 0=1M, 1=2M, 2=Coded),
# while the event reports a single negotiated value per direction:
class LEPhy:
    """Single-PHY values reported by LE_PHY_Update_Complete."""

    LE_1M = 0x01
    LE_2M = 0x02
    LE_CODED = 0x03


class LEPhyMask:
    """Bitmask values for LE_Set_PHY TX_PHYS / RX_PHYS parameters."""

    LE_1M = 0x01  # bit 0
    LE_2M = 0x02  # bit 1
    LE_CODED = 0x04  # bit 2
# Note: Bluetooth Core Spec 6.1 renamed HCI_LE_Read_Local_Supported_Features
# (OCF 0x0003) to HCI_LE_Read_Local_Supported_Features_Page and added an
# optional 1-byte page_number parameter. SAME OCF 0x0003; SAME
# Supported_Commands bit (25, 2). The packet class supports both modes
# (page=0 → no params → Spec 5.4 behavior; page>=1 → 6.1 paged read).
HCI_LE_READ_MAXIMUM_DATA_LENGTH = make_opcode(OGF.LE, 0x2F)
HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS = make_opcode(OGF.LE, 0x36)
HCI_LE_SET_EXTENDED_ADVERTISING_DATA = make_opcode(OGF.LE, 0x37)
HCI_LE_SET_EXTENDED_SCAN_RSP_DATA = make_opcode(OGF.LE, 0x38)
HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE = make_opcode(OGF.LE, 0x39)
HCI_LE_SET_PRIVACY_MODE = make_opcode(OGF.LE, 0x4E)
HCI_LE_START_ENCRYPTION                       = make_opcode(OGF.LE, 0x19)
HCI_LE_LONG_TERM_KEY_REQUEST_REPLY            = make_opcode(OGF.LE, 0x1A)
HCI_LE_LONG_TERM_KEY_REQUEST_NEGATIVE_REPLY   = make_opcode(OGF.LE, 0x1B)


class EventCode(IntEnum):
    """HCI event codes (Bluetooth Core Spec Vol 4, Part E §7.7)."""

    INQUIRY_COMPLETE = 0x01
    INQUIRY_RESULT = 0x02
    CONNECTION_COMPLETE = 0x03
    CONNECTION_REQUEST = 0x04
    DISCONNECTION_COMPLETE = 0x05
    AUTH_COMPLETE = 0x06
    REMOTE_NAME_REQUEST_COMPLETE = 0x07
    ENCRYPTION_CHANGE = 0x08
    CHANGE_LINK_KEY_COMPLETE = 0x09
    READ_REMOTE_FEATURES_COMPLETE = 0x0B
    READ_REMOTE_VERSION_COMPLETE = 0x0C
    COMMAND_COMPLETE = 0x0E
    COMMAND_STATUS = 0x0F
    HARDWARE_ERROR = 0x10
    NUM_COMPLETED_PACKETS = 0x13
    PIN_CODE_REQUEST = 0x16
    LINK_KEY_REQUEST = 0x17
    LINK_KEY_NOTIFICATION = 0x18
    DATA_BUFFER_OVERFLOW = 0x1A
    MAX_SLOTS_CHANGE = 0x1B
    CONNECTION_PACKET_TYPE_CHANGED = 0x1D  # Core §7.7.29
    SYNCHRONOUS_CONNECTION_COMPLETE = 0x2C  # Core §7.7.35
    IO_CAPABILITY_REQUEST = 0x31
    IO_CAPABILITY_RESPONSE = 0x32
    USER_CONFIRMATION_REQUEST = 0x33
    USER_PASSKEY_REQUEST = 0x34
    SIMPLE_PAIRING_COMPLETE = 0x36
    LE_META = 0x3E
    VENDOR_SPECIFIC = 0xFF


class LEMetaSubEvent(IntEnum):
    """LE Meta event sub-event codes (Vol 4, Part E §7.7.65)."""

    LE_CONNECTION_COMPLETE = 0x01
    LE_ADVERTISING_REPORT = 0x02
    LE_CONNECTION_UPDATE_COMPLETE = 0x03
    LE_READ_REMOTE_FEATURES_COMPLETE = 0x04
    LE_LONG_TERM_KEY_REQUEST = 0x05
    LE_ENHANCED_CONNECTION_COMPLETE = 0x0A
    LE_DIRECTED_ADVERTISING_REPORT = 0x0B
    LE_PHY_UPDATE_COMPLETE = 0x0C
    LE_EXTENDED_ADVERTISING_REPORT = 0x0D


class ErrorCode(IntEnum):
    """HCI error codes (Vol 1, Part F §1.3)."""

    SUCCESS = 0x00
    UNKNOWN_COMMAND = 0x01
    NO_CONNECTION = 0x02
    HARDWARE_FAILURE = 0x03
    PAGE_TIMEOUT = 0x04
    AUTH_FAILURE = 0x05
    PIN_KEY_MISSING = 0x06
    MEMORY_FULL = 0x07
    CONNECTION_TIMEOUT = 0x08
    MAX_CONNECTIONS = 0x09
    COMMAND_DISALLOWED = 0x0C
    REJECTED_LIMITED_RESOURCES = 0x0D
    REJECTED_SECURITY = 0x0E
    REJECTED_BAD_BD_ADDR = 0x0F
    HOST_TIMEOUT = 0x10
    UNSUPPORTED_FEATURE = 0x11
    INVALID_PARAMETERS = 0x12
    REMOTE_USER_TERMINATED = 0x13
    REMOTE_LOW_RESOURCES = 0x14
    REMOTE_POWER_OFF = 0x15
    LOCAL_HOST_TERMINATED = 0x16
    REPEATED_ATTEMPTS = 0x17
    PAIRING_NOT_ALLOWED = 0x18
    UNSPECIFIED_ERROR = 0x1F
    LL_RESPONSE_TIMEOUT = 0x22
    LL_PROCEDURE_COLLISION = 0x23
    ENCRYPTION_MODE_NOT_ACCEPTABLE = 0x25
    UNIT_KEY_USED = 0x26
    QOS_NOT_SUPPORTED = 0x27
    INSTANT_PASSED = 0x28
    PAIRING_WITH_UNIT_KEY_NOT_SUPPORTED = 0x29
    DIFFERENT_TRANSACTION_COLLISION = 0x2A
    CHANNEL_ASSESSMENT_NOT_SUPPORTED = 0x2E
    INSUFFICIENT_SECURITY = 0x2F
    PARAMETER_OUT_OF_RANGE = 0x30
    ROLE_SWITCH_PENDING = 0x32
    RESERVED_SLOT_VIOLATION = 0x34
    ROLE_SWITCH_FAILED = 0x35
    EXTENDED_INQUIRY_RESPONSE_TOO_LARGE = 0x36
    SECURE_SIMPLE_PAIRING_NOT_SUPPORTED = 0x37
    HOST_BUSY_PAIRING = 0x38
    CONTROLLER_BUSY = 0x3A
    UNACCEPTABLE_CONNECTION_PARAMS = 0x3B
    DIRECTED_ADVERTISING_TIMEOUT = 0x3C
    CONNECTION_TERMINATED_MIC_FAILURE = 0x3D
    FAILED_TO_ESTABLISH_CONNECTION = 0x3E
    MAC_CONNECTION_FAILED = 0x3F


# ---------------------------------------------------------------------------
# H4 packet type indicators
# ---------------------------------------------------------------------------
HCI_COMMAND_PACKET = 0x01
HCI_ACL_PACKET = 0x02
HCI_SCO_PACKET = 0x03
HCI_EVENT_PACKET = 0x04
HCI_ISO_PACKET = 0x05

# ---------------------------------------------------------------------------
# ACL PB (Packet Boundary) flags
# ---------------------------------------------------------------------------
ACL_PB_FIRST_NON_AUTO_FLUSH = 0x00
ACL_PB_CONTINUING = 0x01
ACL_PB_FIRST_AUTO_FLUSH = 0x02
ACL_PB_COMPLETE_L2CAP = 0x03
