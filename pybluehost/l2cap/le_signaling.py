"""LE L2CAP signaling PDUs (Core Spec Vol 3 Part A §4 — LE-U mode subset).

Implements the subset PyBlueHost actually uses for LE Credit-Based Channels:
- 0x06 DISCONNECTION_REQUEST + 0x07 DISCONNECTION_RESPONSE
- 0x14 LE_CREDIT_BASED_CONNECTION_REQUEST + 0x15 LE_CREDIT_BASED_CONNECTION_RESPONSE
- 0x16 LE_FLOW_CONTROL_CREDIT

Out of scope (v1): 0x17/0x18/0x19 ECFC (Enhanced Credit Based Connections),
0x1A/0x1B Reconfigure.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass


# Signaling codes
LE_SIG_DISCONNECTION_REQUEST = 0x06
LE_SIG_DISCONNECTION_RESPONSE = 0x07
LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST = 0x14
LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE = 0x15
LE_SIG_LE_FLOW_CONTROL_CREDIT = 0x16

# Frame header is [code(1), ident(1), length(2 LE)] — 4 bytes.
LE_SIG_HEADER_SIZE = 4

# Common result codes for 0x15 responses (Core Spec Vol 3 Part A Table 4.20).
LE_CONN_RESULT_SUCCESS = 0x0000
LE_CONN_RESULT_PSM_NOT_SUPPORTED = 0x0002
LE_CONN_RESULT_NO_RESOURCES = 0x0004
LE_CONN_RESULT_INSUFFICIENT_AUTHENTICATION = 0x0005
LE_CONN_RESULT_INSUFFICIENT_AUTHORIZATION = 0x0006
LE_CONN_RESULT_ENC_KEY_SIZE_TOO_SHORT = 0x0007
LE_CONN_RESULT_INSUFFICIENT_ENCRYPTION = 0x0008
LE_CONN_RESULT_INVALID_SOURCE_CID = 0x0009
LE_CONN_RESULT_SCID_ALREADY_ALLOCATED = 0x000A


@dataclass(frozen=True)
class LECreditBasedConnectionRequest:
    le_psm: int
    scid: int
    mtu: int
    mps: int
    initial_credits: int

    def encode(self) -> bytes:
        return struct.pack(
            "<HHHHH",
            self.le_psm & 0xFFFF, self.scid & 0xFFFF, self.mtu & 0xFFFF,
            self.mps & 0xFFFF, self.initial_credits & 0xFFFF,
        )

    @classmethod
    def decode(cls, data: bytes) -> "LECreditBasedConnectionRequest":
        if len(data) != 10:
            raise ValueError(
                f"LE_CREDIT_BASED_CONNECTION_REQUEST: expected 10 bytes, got {len(data)}"
            )
        le_psm, scid, mtu, mps, initial_credits = struct.unpack("<HHHHH", data)
        return cls(le_psm=le_psm, scid=scid, mtu=mtu, mps=mps, initial_credits=initial_credits)


@dataclass(frozen=True)
class LECreditBasedConnectionResponse:
    dcid: int
    mtu: int
    mps: int
    initial_credits: int
    result: int

    def encode(self) -> bytes:
        return struct.pack(
            "<HHHHH",
            self.dcid & 0xFFFF, self.mtu & 0xFFFF, self.mps & 0xFFFF,
            self.initial_credits & 0xFFFF, self.result & 0xFFFF,
        )

    @classmethod
    def decode(cls, data: bytes) -> "LECreditBasedConnectionResponse":
        if len(data) != 10:
            raise ValueError(
                f"LE_CREDIT_BASED_CONNECTION_RESPONSE: expected 10 bytes, got {len(data)}"
            )
        dcid, mtu, mps, initial_credits, result = struct.unpack("<HHHHH", data)
        return cls(dcid=dcid, mtu=mtu, mps=mps, initial_credits=initial_credits, result=result)


@dataclass(frozen=True)
class LEFlowControlCredit:
    cid: int
    credits: int

    def encode(self) -> bytes:
        return struct.pack("<HH", self.cid & 0xFFFF, self.credits & 0xFFFF)

    @classmethod
    def decode(cls, data: bytes) -> "LEFlowControlCredit":
        if len(data) != 4:
            raise ValueError(f"LE_FLOW_CONTROL_CREDIT: expected 4 bytes, got {len(data)}")
        cid, credits = struct.unpack("<HH", data)
        return cls(cid=cid, credits=credits)


@dataclass(frozen=True)
class DisconnectionRequest:
    dcid: int
    scid: int

    def encode(self) -> bytes:
        return struct.pack("<HH", self.dcid & 0xFFFF, self.scid & 0xFFFF)

    @classmethod
    def decode(cls, data: bytes) -> "DisconnectionRequest":
        if len(data) != 4:
            raise ValueError(f"DISCONNECTION_REQUEST: expected 4 bytes, got {len(data)}")
        dcid, scid = struct.unpack("<HH", data)
        return cls(dcid=dcid, scid=scid)


@dataclass(frozen=True)
class DisconnectionResponse:
    dcid: int
    scid: int

    def encode(self) -> bytes:
        return struct.pack("<HH", self.dcid & 0xFFFF, self.scid & 0xFFFF)

    @classmethod
    def decode(cls, data: bytes) -> "DisconnectionResponse":
        if len(data) != 4:
            raise ValueError(f"DISCONNECTION_RESPONSE: expected 4 bytes, got {len(data)}")
        dcid, scid = struct.unpack("<HH", data)
        return cls(dcid=dcid, scid=scid)


# ---- Outer frame ---------------------------------------------------------

def encode_le_signaling(code: int, identifier: int, payload: bytes) -> bytes:
    """Wrap a signaling payload in the [code(1), ident(1), length(2 LE)] header."""
    return struct.pack("<BBH", code & 0xFF, identifier & 0xFF, len(payload)) + payload


_DECODERS = {
    LE_SIG_DISCONNECTION_REQUEST: DisconnectionRequest.decode,
    LE_SIG_DISCONNECTION_RESPONSE: DisconnectionResponse.decode,
    LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST: LECreditBasedConnectionRequest.decode,
    LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE: LECreditBasedConnectionResponse.decode,
    LE_SIG_LE_FLOW_CONTROL_CREDIT: LEFlowControlCredit.decode,
}


def decode_le_signaling(data: bytes):
    """Return (code, identifier, payload_obj). Unknown codes return the raw bytes."""
    if len(data) < LE_SIG_HEADER_SIZE:
        raise ValueError(
            f"LE signaling frame header truncated: got {len(data)} bytes, "
            f"need >= {LE_SIG_HEADER_SIZE}"
        )
    code, ident, length = struct.unpack("<BBH", data[:LE_SIG_HEADER_SIZE])
    body = data[LE_SIG_HEADER_SIZE : LE_SIG_HEADER_SIZE + length]
    if len(body) < length:
        raise ValueError(
            f"LE signaling frame data truncated: header says {length} bytes, "
            f"got {len(body)}"
        )
    decoder = _DECODERS.get(code)
    if decoder is None:
        return code, ident, body
    return code, ident, decoder(body)
