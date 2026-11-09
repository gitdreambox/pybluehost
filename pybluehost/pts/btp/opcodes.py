"""auto-pts BTP service IDs + Core opcodes.

Authoritative source: https://github.com/auto-pts/auto-pts ``doc/btp_*.txt``.

Upstream verification performed 2026-06-22 against auto-pts/auto-pts master
doc/btp_core.txt. Discrepancies vs plan values noted inline.
"""
from __future__ import annotations


# Service IDs (BTP frame byte 0).
SERVICE_CORE = 0x00
SERVICE_GAP = 0x01      # P.6
SERVICE_GATT = 0x02     # P.7
SERVICE_L2CAP = 0x03    # P.8
SERVICE_SMP = 0x04      # P.8 (or merged into GAP per upstream)

# Universal status response (opcode 0x00 in every service).
OP_STATUS_RESPONSE = 0x00

# Core service opcodes (0x01-0x7F = commands; 0x80+ = events).
# Verified against upstream doc/btp_core.txt 2026-06-22.
# Plan P.5 originally listed RESET_BOARD at 0x05; upstream has no such
# command. P.5 Task 4 should not implement RESET_BOARD — autoptsclient
# never sends it. LOG_MESSAGE + READ_BTP_MTU come from current upstream.
OP_CORE_READ_SUPPORTED_COMMANDS = 0x01
OP_CORE_READ_SUPPORTED_SERVICES = 0x02
OP_CORE_REGISTER = 0x03
OP_CORE_UNREGISTER = 0x04
OP_CORE_LOG_MESSAGE = 0x05
OP_CORE_READ_BTP_MTU = 0x06

# Core events.
OP_CORE_EVENT_READY = 0x80

# BTP status response byte (data of opcode 0x00 in every service response).
BTP_STATUS_SUCCESS = 0x00
BTP_STATUS_FAILED = 0x01
BTP_STATUS_UNKNOWN_CMD = 0x02
BTP_STATUS_NOT_READY = 0x03
BTP_STATUS_INVALID_INDEX = 0x04

# When a command isn't tied to any controller (e.g. Core's), use this sentinel.
CONTROLLER_INDEX_NONE = 0xFF


# GAP service opcodes (auto-pts doc/btp_gap.txt — verified 2026-06-22).
# This block covers the LE GAP test-case surface used by autoptsclient.
# Privacy / OOB / MITM / SC commands (upstream 0x15-0x34) are NOT defined here
# because the plan's numbering was wrong against upstream and P.6 scope
# excludes them anyway; if needed later, add them with their upstream values.
OP_GAP_READ_SUPPORTED_COMMANDS = 0x01
OP_GAP_READ_CONTROLLER_INDEX_LIST = 0x02
OP_GAP_READ_CONTROLLER_INFO = 0x03
OP_GAP_RESET = 0x04
OP_GAP_SET_POWERED = 0x05
OP_GAP_SET_CONNECTABLE = 0x06
OP_GAP_SET_FAST_CONNECTABLE = 0x07
OP_GAP_SET_DISCOVERABLE = 0x08
OP_GAP_SET_BONDABLE = 0x09
OP_GAP_START_ADVERTISING = 0x0A
OP_GAP_STOP_ADVERTISING = 0x0B
OP_GAP_START_DISCOVERY = 0x0C
OP_GAP_STOP_DISCOVERY = 0x0D
OP_GAP_CONNECT = 0x0E
OP_GAP_DISCONNECT = 0x0F
OP_GAP_SET_IO_CAP = 0x10
OP_GAP_PAIR = 0x11
OP_GAP_UNPAIR = 0x12
OP_GAP_PASSKEY_ENTRY_REPLY = 0x13
OP_GAP_PASSKEY_CONFIRM_REPLY = 0x14
OP_GAP_START_DIRECT_ADV = 0x15
OP_GAP_CONN_PARAM_UPDATE = 0x16
OP_GAP_PAIRING_CONSENT_RSP = 0x17
OP_GAP_OOB_LEGACY_SET_DATA = 0x18
OP_GAP_OOB_SC_GET_LOCAL_DATA = 0x19
OP_GAP_OOB_SC_SET_REMOTE_DATA = 0x1A
OP_GAP_SET_MITM = 0x1B
OP_GAP_SET_FILTER_ACCEPT_LIST = 0x1C
OP_GAP_SET_PRIVACY = 0x1D
OP_GAP_SET_SC_ONLY = 0x1E
OP_GAP_SET_SC = 0x1F
OP_GAP_SET_MIN_ENC_KEY_SIZE = 0x20
OP_GAP_SET_EXTENDED_ADVERTISING = 0x21
# Periodic advertising (GAP/PADV cases). Opcode numbering mirrors auto-pts
# defs.py exactly — do not renumber.
OP_GAP_PADV_CONFIGURE = 0x22
OP_GAP_PADV_START = 0x23
OP_GAP_PADV_STOP = 0x24
OP_GAP_PADV_SET_DATA = 0x25
OP_GAP_PADV_CREATE_SYNC = 0x26
OP_GAP_PADV_SYNC_TRANSFER_SET_INFO = 0x27
OP_GAP_PADV_SYNC_TRANSFER_START = 0x28
OP_GAP_PADV_SYNC_TRANSFER_RECV = 0x29
# Connection Subrating (GAP/CSUB). Per Core Vol 4 Part E §7.8.124 the one HCI
# command LE_Subrate_Request covers both roles, so a single BTP opcode drives
# both GAP/CSUB/CSR (Peripheral) and GAP/CSUB/CSU (Central).
OP_GAP_SUBRATE_REQUEST = 0x2B
# Broadcast Isochronous Group (GAP/BIS/BBM/BV-01-C). auto-pts's gap_create_big
# packs `<BBIHBBBB` + encryption byte (+ optional 16-byte broadcast code);
# gap_bis_broadcast packs bis_id(1) + len(1) + data.
OP_GAP_CREATE_BIG = 0x2D
OP_GAP_BIS_BROADCAST = 0x2E
# Encrypted Advertising Data (CSS v15 §1.23). Opcode numbering mirrors auto-pts
# defs.py: SET_EAD_KEY_MATERIAL 0x31 / ENCRYPT 0x32 / DECRYPT 0x33.
OP_GAP_SET_EAD_KEY_MATERIAL = 0x31
OP_GAP_ENCRYPT_EAD_DATA = 0x32
OP_GAP_DECRYPT_EAD_DATA = 0x33

# GAP events (0x80+ — unsolicited, tester → autoptsclient).
OP_GAP_EVENT_NEW_SETTINGS = 0x80
OP_GAP_EVENT_DEVICE_FOUND = 0x81
OP_GAP_EVENT_DEVICE_CONNECTED = 0x82
OP_GAP_EVENT_DEVICE_DISCONNECTED = 0x83
OP_GAP_EVENT_PASSKEY_DISPLAY = 0x84
OP_GAP_EVENT_PASSKEY_ENTRY_REQ = 0x85
OP_GAP_EVENT_PASSKEY_CONFIRM_REQ = 0x86
OP_GAP_EVENT_IDENTITY_RESOLVED = 0x87
OP_GAP_EVENT_CONN_PARAM_UPDATE = 0x88
OP_GAP_EVENT_SEC_LEVEL_CHANGED = 0x89
OP_GAP_EVENT_PAIRING_CONSENT_REQ = 0x8A
OP_GAP_EVENT_BOND_LOST = 0x8B
OP_GAP_EVENT_PAIRING_FAILED = 0x8C
OP_GAP_EVENT_PERIODIC_SYNC_ESTABLISHED = 0x8D
OP_GAP_EVENT_PERIODIC_SYNC_LOST = 0x8E
OP_GAP_EVENT_PERIODIC_REPORT = 0x8F
OP_GAP_EVENT_PERIODIC_TRANSFER_RECEIVED = 0x90
# GAP/CSUB: the controller completed a Connection Subrate Update procedure.
OP_GAP_EVENT_SUBRATE_CHANGE = 0x92
# GAP/BIS: one per BIS after CREATE_BIG — the IUT has set up the ISO data
# path (auto-pts's gap_bis_data_path_setup_ev_ parses `<B6sB` and only
# appends bis_id to stack.gap.big_bis_data_path_setup).
OP_GAP_EVENT_BIS_DATA_PATH_SETUP = 0x95

# BD_ADDR type byte preceding the 6-byte address in BTP commands.
GAP_ADDR_TYPE_PUBLIC = 0
GAP_ADDR_TYPE_RANDOM = 1

# IO capability values (per SMP §3.5.1 + auto-pts BTP enum).
GAP_IO_CAP_DISPLAY_ONLY = 0x00
GAP_IO_CAP_DISPLAY_YESNO = 0x01
GAP_IO_CAP_KEYBOARD_ONLY = 0x02
GAP_IO_CAP_NO_INPUT_NO_OUTPUT = 0x03
GAP_IO_CAP_KEYBOARD_DISPLAY = 0x04


# GATT service opcodes (auto-pts doc/btp_gatt.txt — verified 2026-06-22).
# P.7 v1 implements 0x01-0x1B; 0x16 SIGNED_WRITE_WITHOUT_RSP is out of scope.
# 0x1C GET_ATTRIBUTES / 0x1D GET_ATTRIBUTE_VALUE added 2026-08-20: the auto-pts
# GATT/SR discovery WID handlers call gatts_get_attrs/_attr_val to verify the
# IUT's committed server db, so they are required for the SR matrix.
OP_GATT_READ_SUPPORTED_COMMANDS = 0x01
OP_GATT_ADD_SERVICE = 0x02
OP_GATT_ADD_CHARACTERISTIC = 0x03
OP_GATT_ADD_DESCRIPTOR = 0x04
OP_GATT_ADD_INCLUDED_SERVICE = 0x05
OP_GATT_SET_VALUE = 0x06
OP_GATT_START_SERVER = 0x07
OP_GATT_RESET_SERVER = 0x08
OP_GATT_SET_ENC_KEY_SIZE = 0x09
OP_GATT_EXCHANGE_MTU = 0x0A
OP_GATT_DISC_ALL_PRIM_SVCS = 0x0B
OP_GATT_DISC_PRIM_SVC_BY_UUID = 0x0C
OP_GATT_FIND_INCLUDED_SVCS = 0x0D
OP_GATT_DISC_ALL_CHRC = 0x0E
OP_GATT_DISC_CHRC_BY_UUID = 0x0F
OP_GATT_DISC_ALL_DESC = 0x10
OP_GATT_READ = 0x11
OP_GATT_READ_UUID = 0x12
OP_GATT_READ_LONG = 0x13
OP_GATT_READ_MULTIPLE = 0x14
OP_GATT_WRITE_WITHOUT_RSP = 0x15
# 0x16 = SIGNED_WRITE_WITHOUT_RSP (out of P.7 v1 scope)
OP_GATT_WRITE = 0x17
OP_GATT_WRITE_LONG = 0x18
OP_GATT_WRITE_RELIABLE = 0x19
OP_GATT_CFG_NOTIFY = 0x1A
OP_GATT_CFG_INDICATE = 0x1B
OP_GATT_GET_ATTRIBUTES = 0x1C
OP_GATT_GET_ATTRIBUTE_VALUE = 0x1D
OP_GATT_CHANGE_DATABASE = 0x1E
OP_GATT_READ_MULTIPLE_VAR = 0x20
OP_GATT_NOTIFY_MULTIPLE = 0x21

# GATT events (only TWO per upstream — Notification/Indication share opcode 0x80,
# distinguished by a `type` byte in the payload).
OP_GATT_EVENT_NOTIFICATION = 0x80
OP_GATT_EVENT_ATTR_VALUE_CHANGED = 0x81


# GATT BTP enums (auto-pts BTP-specific, not Core spec).
GATT_SERVICE_PRIMARY = 0x00
GATT_SERVICE_SECONDARY = 0x01

# Characteristic property bits — per Core Spec Vol 3, Part G, §3.3.1.1.
GATT_CHRC_PROP_BROADCAST = 0x01
GATT_CHRC_PROP_READ = 0x02
GATT_CHRC_PROP_WRITE_WITHOUT_RSP = 0x04
GATT_CHRC_PROP_WRITE = 0x08
GATT_CHRC_PROP_NOTIFY = 0x10
GATT_CHRC_PROP_INDICATE = 0x20
GATT_CHRC_PROP_AUTH_SIGNED_WRITE = 0x40
GATT_CHRC_PROP_EXT_PROP = 0x80

# Attribute permissions — auto-pts BTP convention (NOT Bluetooth Core; BTP-specific).
GATT_PERM_READ = 0x01
GATT_PERM_WRITE = 0x02
GATT_PERM_READ_ENC = 0x04
GATT_PERM_WRITE_ENC = 0x08
GATT_PERM_READ_AUTHEN = 0x10
GATT_PERM_WRITE_AUTHEN = 0x20
GATT_PERM_READ_AUTHOR = 0x40
GATT_PERM_WRITE_AUTHOR = 0x80


# L2CAP service opcodes (auto-pts doc/btp_l2cap.txt — verified 2026-06-23).
# P.8 v1 implements 0x01-0x05 + events 0x80-0x83.
# Out of P.8 v1: 0x06 Accept Connection Request, 0x07 Reconfigure, 0x08 Credits,
# 0x0a ECHO, 0x0b Connect v2, 0x0c Listen v2, 0x0d Send Connectionless,
# 0x84 Reconfigured event.
OP_L2CAP_READ_SUPPORTED_COMMANDS = 0x01
OP_L2CAP_CONNECT = 0x02
OP_L2CAP_DISCONNECT = 0x03
OP_L2CAP_SEND_DATA = 0x04
OP_L2CAP_LISTEN = 0x05
# 0x08 CREDITS: implemented via L2CAPManager.grant_le_coc_credits (sends
# LE_FLOW_CONTROL_CREDIT). PTS CFC flow-control tests drive this.
OP_L2CAP_CREDITS = 0x08
# 0x09 DISCONNECT_EATT_CHANS: disconnect N EATT bearers of a connection
# (auto-pts l2cap_disconn_eatt_chans; WID 144 in the GATT/SR EATT cases).
OP_L2CAP_DISCONNECT_EATT_CHANS = 0x09
OP_L2CAP_CONNECT_V2 = 0x0B
OP_L2CAP_LISTEN_V2 = 0x0C

# L2CAP events (0x80+ — unsolicited, tester → autoptsclient).
OP_L2CAP_EVENT_CONNECTION_REQUEST = 0x80
OP_L2CAP_EVENT_CONNECTED = 0x81
OP_L2CAP_EVENT_DISCONNECTED = 0x82
OP_L2CAP_EVENT_DATA_RECEIVED = 0x83
OP_L2CAP_EVENT_RECONFIGURED = 0x84

# SDP service (BTP spec doc/btp_sdp.txt) — BR/EDR SDP client operations.
SERVICE_SDP = 0x1F
OP_SDP_READ_SUPPORTED_COMMANDS = 0x01
OP_SDP_SEARCH_REQ = 0x02
OP_SDP_ATTR_REQ = 0x03
OP_SDP_SEARCH_ATTR_REQ = 0x04
OP_SDP_EVENT_SERVICE_RECORD_HANDLE = 0x80

# RFCOMM service (BTP spec doc/btp_rfcomm.txt).
SERVICE_RFCOMM = 0x20
OP_RFCOMM_READ_SUPPORTED_COMMANDS = 0x01
OP_RFCOMM_CONNECT = 0x02
OP_RFCOMM_DISCONNECT = 0x03
OP_RFCOMM_SEND_DATA = 0x04
OP_RFCOMM_LISTEN = 0x05
OP_RFCOMM_SEND_RPN = 0x06
OP_RFCOMM_GET_DLC_INFO = 0x07
OP_RFCOMM_SEND_RLS = 0x08
OP_RFCOMM_EVENT_CONNECTED = 0x80
OP_RFCOMM_EVENT_DISCONNECTED = 0x81
OP_RFCOMM_EVENT_DATA_RECEIVED = 0x82
