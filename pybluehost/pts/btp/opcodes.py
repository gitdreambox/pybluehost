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
