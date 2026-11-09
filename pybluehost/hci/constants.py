"""HCI constants: opcodes, event codes, error codes, packet type indicators.

Reference: Bluetooth Core Spec Vol 4, Part E.
"""

from __future__ import annotations

from enum import IntEnum, IntFlag


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
HCI_READ_REMOTE_SUPPORTED_FEATURES = make_opcode(OGF.LINK_CONTROL, 0x1B)
HCI_READ_REMOTE_EXTENDED_FEATURES = make_opcode(OGF.LINK_CONTROL, 0x1C)
HCI_READ_REMOTE_VERSION_INFORMATION = make_opcode(OGF.LINK_CONTROL, 0x1D)
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
HCI_WRITE_INQUIRY_SCAN_ACTIVITY = make_opcode(OGF.CONTROLLER_BB, 0x1E)
HCI_WRITE_PAGE_SCAN_ACTIVITY = make_opcode(OGF.CONTROLLER_BB, 0x1F)
HCI_WRITE_AUTHENTICATION_ENABLE = make_opcode(OGF.CONTROLLER_BB, 0x20)
HCI_WRITE_CLASS_OF_DEVICE = make_opcode(OGF.CONTROLLER_BB, 0x24)
HCI_HOST_BUFFER_SIZE = make_opcode(OGF.CONTROLLER_BB, 0x33)
HCI_WRITE_INQUIRY_MODE = make_opcode(OGF.CONTROLLER_BB, 0x45)
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
HCI_LE_CONNECTION_UPDATE = make_opcode(OGF.LE, 0x13)
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
# Core Vol 4 Part E §7.8.52. With the extended advertising commands in use,
# LE_Set_Random_Address (0x2005) only reaches scanning and initiating; an
# advertising set with Own_Address_Type 0x01 draws its address from this
# set-scoped command instead (§7.8.5 note + §7.8.56 error table).
HCI_LE_SET_ADVERTISING_SET_RANDOM_ADDRESS = make_opcode(OGF.LE, 0x35)
HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS = make_opcode(OGF.LE, 0x36)
HCI_LE_SET_EXTENDED_ADVERTISING_DATA = make_opcode(OGF.LE, 0x37)
HCI_LE_SET_EXTENDED_SCAN_RSP_DATA = make_opcode(OGF.LE, 0x38)
HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE = make_opcode(OGF.LE, 0x39)
HCI_LE_SET_PERIODIC_ADVERTISING_PARAMS = make_opcode(OGF.LE, 0x3E)
HCI_LE_SET_PERIODIC_ADVERTISING_DATA = make_opcode(OGF.LE, 0x3F)
HCI_LE_SET_PERIODIC_ADVERTISING_ENABLE = make_opcode(OGF.LE, 0x40)
# Extended scanning (§7.8.64/7.8.65). LE_Set_Scan_Enable scans "for legacy
# PDUs (but not extended PDUs, even if the device supports extended
# advertising)" (§7.8.11), so anything that has to see an extended advertising
# PDU — periodic advertising sync above all — needs these instead.
HCI_LE_SET_EXTENDED_SCAN_PARAMS = make_opcode(OGF.LE, 0x41)
HCI_LE_SET_EXTENDED_SCAN_ENABLE = make_opcode(OGF.LE, 0x42)
# Extended initiator (§7.8.66). Needed because LE_Create_Connection (0x200D) is
# refused with Command Disallowed while any extended advertising set exists,
# and stays refused until HCI_Reset clears the set — measured on BE200
# 2026-09-16, where the same controller accepts this command and completes the
# connection. Guarded on Supported_Commands octet 38 bit 4 because BT 4.0/4.1
# controllers (CSR8510 and friends) do not implement it.
HCI_LE_EXTENDED_CREATE_CONNECTION = make_opcode(OGF.LE, 0x43)
HCI_LE_PERIODIC_ADVERTISING_CREATE_SYNC = make_opcode(OGF.LE, 0x44)
HCI_LE_PERIODIC_ADVERTISING_CREATE_SYNC_CANCEL = make_opcode(OGF.LE, 0x45)
HCI_LE_PERIODIC_ADVERTISING_TERMINATE_SYNC = make_opcode(OGF.LE, 0x46)
# Periodic Advertising Sync Transfer family (Vol 4 Part E §7.8.89–7.8.92). The
# OCFs are 0x5A / 0x59 / 0x5C / 0x5D — NOT 0x49/0x5A as this file once had.
# Sending 0x5A expecting "Set PAST Parameters" actually issues "PAST Sync
# Transfer", which addresses the third field as a Sync_Handle: our 8-octet body
# put 0x01F4 there and the controller answered "Unknown Advertising Identifier"
# (0x42), which is exactly what GAP/PADV hit on air.
HCI_LE_PERIODIC_ADVERTISING_SYNC_TRANSFER = make_opcode(OGF.LE, 0x5A)
HCI_LE_SET_PERIODIC_ADVERTISING_RECEIVE_ENABLE = make_opcode(OGF.LE, 0x59)
HCI_LE_SET_PERIODIC_ADVERTISING_SYNC_TRANSFER_PARAMS = make_opcode(OGF.LE, 0x5C)
HCI_LE_SET_DEFAULT_PERIODIC_ADVERTISING_SYNC_TRANSFER_PARAMS = make_opcode(OGF.LE, 0x5D)
# The *source* half of the procedure (§7.8.90): the command that actually puts
# synchronization information on air towards a connected peer. The three
# commands above are the sink/re-transfer halves — §7.8.91 and §7.8.92 tell the
# controller how to *process* incoming transfers, and §7.8.89 re-transfers a
# Sync_Handle the Host already holds. None of them sends anything the first
# time, which is why GAP/PADV/PAST answered every WID with Ok and then sat
# silent until PTS gave up.
HCI_LE_PERIODIC_ADVERTISING_SET_INFO_TRANSFER = make_opcode(OGF.LE, 0x5B)
# Isochronous channels (BIS/BIG), Vol 4 Part E §7.8.98–7.8.108. OCFs verified
# against Zephyr's BT_HCI_OP_LE_* table.
HCI_LE_READ_ISO_TX_SYNC = make_opcode(OGF.LE, 0x61)
HCI_LE_SET_CIG_PARAMETERS = make_opcode(OGF.LE, 0x62)
HCI_LE_CREATE_CIS = make_opcode(OGF.LE, 0x64)
HCI_LE_REMOVE_CIG = make_opcode(OGF.LE, 0x65)
HCI_LE_CREATE_BIG = make_opcode(OGF.LE, 0x68)
HCI_LE_TERMINATE_BIG = make_opcode(OGF.LE, 0x6A)
HCI_LE_BIG_CREATE_SYNC = make_opcode(OGF.LE, 0x6B)
HCI_LE_BIG_TERMINATE_SYNC = make_opcode(OGF.LE, 0x6C)
HCI_LE_SETUP_ISO_DATA_PATH = make_opcode(OGF.LE, 0x6E)
HCI_LE_REMOVE_ISO_DATA_PATH = make_opcode(OGF.LE, 0x6F)
# Connection Subrating (GAP/CSUB), Vol 4 Part E §7.8.123/124. Only the BE200
# implements these — the AX201 answers 0x01 Unknown HCI Command.
HCI_LE_SET_DEFAULT_SUBRATE = make_opcode(OGF.LE, 0x7D)
HCI_LE_SUBRATE_REQUEST = make_opcode(OGF.LE, 0x7E)
# Bits 0..63 of the LE FeatureSet are exchanged on air, and some of them are
# owned by the Host rather than the controller — the controller cannot set
# them itself. Bit 38 is Connection Subrating (Host Support): while it is
# clear a peer refuses to run the Connection Subrating procedure at all
# (Vol 6 Part B §5.1.19, §7.8.124).
HCI_LE_SET_HOST_FEATURE = make_opcode(OGF.LE, 0x74)
LE_FEATURE_BIT_CONNECTION_SUBRATING_HOST_SUPPORT = 38

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
    READ_REMOTE_SUPPORTED_FEATURES_COMPLETE = 0x0B  # spec name for 0x0B
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
    INQUIRY_RESULT_WITH_RSSI = 0x22
    READ_REMOTE_EXTENDED_FEATURES_COMPLETE = 0x23
    SYNCHRONOUS_CONNECTION_COMPLETE = 0x2C  # Core §7.7.35
    EXTENDED_INQUIRY_RESULT = 0x2F
    ENCRYPTION_KEY_REFRESH_COMPLETE = 0x30
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
    # Periodic advertising subevents, Core 6.3 Vol 4 Part E §7.7.65.14-16/24.
    # The [v2] variants sit at 0x24-0x26; these are the [v1] codes every
    # controller still reports by default.
    LE_PERIODIC_ADVERTISING_SYNC_ESTABLISHED = 0x0E
    LE_PERIODIC_ADVERTISING_REPORT = 0x0F
    LE_PERIODIC_ADVERTISING_SYNC_LOST = 0x10
    LE_PERIODIC_ADVERTISING_SYNC_TRANSFER_RECEIVED = 0x18
    # Isochronous broadcast (the BIG the IUT creates as a broadcaster),
    # Zephyr BT_HCI_EVT_LE_BIG_COMPLETE/_TERMINATE — the n+1 invariant holds.
    LE_CREATE_BIG_COMPLETE = 0x1B
    LE_TERMINATE_BIG_COMPLETE = 0x1C
    # BIGInfo is 0x22, not 0x23 — cross-checked against Zephyr's
    # BT_HCI_EVT_LE_* table, which has SUBRATE_CHANGE at 0x23.
    LE_BIGINFO_ADVERTISING_REPORT = 0x22
    LE_SUBRATE_CHANGE = 0x23


class LEEventMaskBit(IntFlag):
    """Bits of the LE Event Mask (Vol 4, Part E §7.8.1).

    Bit *n* here corresponds to LE Meta sub-event code *n + 1*: bit 12 is
    sub-event 0x0D, bit 13 is 0x0E, and so on down the table.
    """

    LE_CONNECTION_COMPLETE = 1 << 0
    LE_ADVERTISING_REPORT = 1 << 1
    LE_CONNECTION_UPDATE_COMPLETE = 1 << 2
    LE_READ_REMOTE_FEATURES_PAGE_0_COMPLETE = 1 << 3
    LE_LONG_TERM_KEY_REQUEST = 1 << 4
    LE_REMOTE_CONNECTION_PARAMETER_REQUEST = 1 << 5
    LE_DATA_LENGTH_CHANGE = 1 << 6
    LE_READ_LOCAL_P256_PUBLIC_KEY_COMPLETE = 1 << 7
    LE_GENERATE_DHKEY_COMPLETE = 1 << 8
    LE_ENHANCED_CONNECTION_COMPLETE = 1 << 9
    LE_DIRECTED_ADVERTISING_REPORT = 1 << 10
    LE_PHY_UPDATE_COMPLETE = 1 << 11
    LE_EXTENDED_ADVERTISING_REPORT = 1 << 12
    LE_PERIODIC_ADVERTISING_SYNC_ESTABLISHED = 1 << 13
    LE_PERIODIC_ADVERTISING_REPORT = 1 << 14
    LE_PERIODIC_ADVERTISING_SYNC_LOST = 1 << 15
    LE_SCAN_TIMEOUT = 1 << 16
    LE_ADVERTISING_SET_TERMINATED = 1 << 17
    LE_SCAN_REQUEST_RECEIVED = 1 << 18
    LE_CHANNEL_SELECTION_ALGORITHM = 1 << 19
    LE_CONNECTIONLESS_IQ_REPORT = 1 << 20
    LE_CONNECTION_IQ_REPORT = 1 << 21
    LE_CTE_REQUEST_FAILED = 1 << 22
    LE_PERIODIC_ADVERTISING_SYNC_TRANSFER_RECEIVED = 1 << 23
    LE_CIS_ESTABLISHED = 1 << 24
    LE_CIS_REQUEST = 1 << 25
    LE_CREATE_BIG_COMPLETE = 1 << 26
    LE_TERMINATE_BIG_COMPLETE = 1 << 27
    LE_BIG_SYNC_ESTABLISHED = 1 << 28


# The controller generates none of the events whose bit is clear, and that
# includes on reception of a command that succeeds — a masked event is simply
# never reported. So every event the stack has a consumer for belongs here.
#
# Deliberately omitted:
#   * Remote Connection Parameter Request (bit 5) — the LL procedure obliges
#     the host to answer with LE_Remote_Connection_Parameter_Request_Reply,
#     which we do not implement; enabling it would stall the peer.
#   * Enhanced Connection Complete (bit 9) — it replaces the legacy Connection
#     Complete on every connection, changing the shape of the hot path for
#     every test case. The legacy event is still the one the stack parses.
DEFAULT_LE_EVENT_MASK = (
    LEEventMaskBit.LE_CONNECTION_COMPLETE
    | LEEventMaskBit.LE_ADVERTISING_REPORT
    | LEEventMaskBit.LE_CONNECTION_UPDATE_COMPLETE
    | LEEventMaskBit.LE_READ_REMOTE_FEATURES_PAGE_0_COMPLETE
    | LEEventMaskBit.LE_LONG_TERM_KEY_REQUEST
    | LEEventMaskBit.LE_EXTENDED_ADVERTISING_REPORT
    | LEEventMaskBit.LE_PERIODIC_ADVERTISING_SYNC_ESTABLISHED
    | LEEventMaskBit.LE_PERIODIC_ADVERTISING_REPORT
    | LEEventMaskBit.LE_PERIODIC_ADVERTISING_SYNC_LOST
    | LEEventMaskBit.LE_PERIODIC_ADVERTISING_SYNC_TRANSFER_RECEIVED
    # The BIG the IUT broadcasts reports its BIS connection handles in
    # LE BIG Complete, and teardown in LE BIG Terminate — both consumed by
    # IsoBroadcastManager (GAP/BIS/BBM).
    | LEEventMaskBit.LE_CREATE_BIG_COMPLETE
    | LEEventMaskBit.LE_TERMINATE_BIG_COMPLETE
)


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
