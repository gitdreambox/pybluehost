"""L2CAP signaling packet codec and handler.

Handles signaling PDUs on CID 0x0001 (Classic) and CID 0x0005 (LE).
"""
from __future__ import annotations
import struct
from dataclasses import dataclass
from pybluehost.l2cap.constants import SignalingCode


@dataclass
class SignalingPacket:
    """A single L2CAP signaling command."""
    code: SignalingCode | int
    identifier: int
    data: bytes = b""


def encode_signaling(pkt: SignalingPacket) -> bytes:
    """Encode a signaling packet: code(1) + ident(1) + length(2 LE) + data."""
    return struct.pack("<BBH", int(pkt.code), pkt.identifier, len(pkt.data)) + pkt.data


def decode_signaling(data: bytes) -> SignalingPacket:
    """Decode a signaling packet from raw bytes."""
    if len(data) < 4:
        raise ValueError(f"Signaling packet too short: {len(data)} bytes")
    code, ident, length = struct.unpack_from("<BBH", data)
    payload = data[4:4 + length]
    try:
        code = SignalingCode(code)
    except ValueError:
        pass  # keep as int for unknown codes
    return SignalingPacket(code=code, identifier=ident, data=payload)


# --- Connection Parameter Update ---

@dataclass
class ConnParamUpdateRequest:
    """LE Connection Parameter Update Request parameters."""
    interval_min: int
    interval_max: int
    latency: int
    timeout: int

    def to_bytes(self) -> bytes:
        return struct.pack("<HHHH", self.interval_min, self.interval_max,
                           self.latency, self.timeout)

    @classmethod
    def from_bytes(cls, data: bytes) -> ConnParamUpdateRequest:
        imin, imax, lat, to = struct.unpack_from("<HHHH", data)
        return cls(interval_min=imin, interval_max=imax, latency=lat, timeout=to)


@dataclass
class ConnParamUpdateResponse:
    """LE Connection Parameter Update Response parameters."""
    result: int  # 0x0000=accepted, 0x0001=rejected

    def to_bytes(self) -> bytes:
        return struct.pack("<H", self.result)

    @classmethod
    def from_bytes(cls, data: bytes) -> ConnParamUpdateResponse:
        result = struct.unpack_from("<H", data)[0]
        return cls(result=result)
