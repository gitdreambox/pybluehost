"""SMP PDU(L2CAP CID 0x06)操作码与编解码。"""
from __future__ import annotations

PAIRING_REQUEST = 0x01
PAIRING_RESPONSE = 0x02
PAIRING_CONFIRM = 0x03
PAIRING_RANDOM = 0x04
PAIRING_FAILED = 0x05
PAIRING_PUBLIC_KEY = 0x0C
PAIRING_DHKEY_CHECK = 0x0D

# authreq 位
AUTHREQ_BONDING = 0x01
AUTHREQ_MITM = 0x04
AUTHREQ_SC = 0x08

# IO capability
IOCAP_DISPLAY_ONLY = 0x00
IOCAP_DISPLAY_YESNO = 0x01
IOCAP_NO_INPUT_NO_OUTPUT = 0x03


def encode(opcode: int, body: bytes = b"") -> bytes:
    return bytes([opcode]) + body


def decode(pdu: bytes) -> tuple[int, bytes]:
    return pdu[0], pdu[1:]
