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
OP_GAP_EVENT_BOND_LOST = 0x8A
OP_GAP_EVENT_PAIRING_FAILED = 0x8B

# BD_ADDR type byte preceding the 6-byte address in BTP commands.
GAP_ADDR_TYPE_PUBLIC = 0
GAP_ADDR_TYPE_RANDOM = 1

# IO capability values (per SMP §3.5.1 + auto-pts BTP enum).
GAP_IO_CAP_DISPLAY_ONLY = 0x00
GAP_IO_CAP_DISPLAY_YESNO = 0x01
GAP_IO_CAP_KEYBOARD_ONLY = 0x02
GAP_IO_CAP_NO_INPUT_NO_OUTPUT = 0x03
GAP_IO_CAP_KEYBOARD_DISPLAY = 0x04
