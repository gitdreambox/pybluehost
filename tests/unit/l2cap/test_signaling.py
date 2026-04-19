import struct
import pytest
from pybluehost.l2cap.signaling import (
    SignalingPacket, encode_signaling, decode_signaling,
    ConnParamUpdateRequest, ConnParamUpdateResponse,
)
from pybluehost.l2cap.constants import SignalingCode


def test_encode_connection_request():
    pkt = SignalingPacket(
        code=SignalingCode.CONNECTION_REQUEST,
        identifier=0x01,
        data=struct.pack("<HH", 0x0003, 0x0040),  # PSM=RFCOMM, SCID=0x0040
    )
    raw = encode_signaling(pkt)
    assert raw[0] == SignalingCode.CONNECTION_REQUEST
    assert raw[1] == 0x01  # identifier
    length = struct.unpack_from("<H", raw, 2)[0]
    assert length == 4


def test_decode_connection_response():
    code = SignalingCode.CONNECTION_RESPONSE
    ident = 0x01
    data = struct.pack("<HHHH", 0x0041, 0x0040, 0x0000, 0x0000)  # DCID, SCID, result, status
    raw = bytes([code, ident]) + struct.pack("<H", len(data)) + data
    pkt = decode_signaling(raw)
    assert pkt.code == SignalingCode.CONNECTION_RESPONSE
    assert pkt.identifier == ident
    assert pkt.data == data


def test_le_credit_connection_request_encode():
    pkt = SignalingPacket(
        code=SignalingCode.LE_CREDIT_CONN_REQ,
        identifier=0x02,
        data=struct.pack("<HHHH", 0x0025, 0x0040, 512, 10),  # PSM, SCID, MTU, MPS
    )
    raw = encode_signaling(pkt)
    assert raw[0] == SignalingCode.LE_CREDIT_CONN_REQ


def test_encode_decode_roundtrip():
    original = SignalingPacket(
        code=SignalingCode.DISCONNECTION_REQUEST,
        identifier=0x05,
        data=struct.pack("<HH", 0x0041, 0x0040),  # DCID, SCID
    )
    raw = encode_signaling(original)
    decoded = decode_signaling(raw)
    assert decoded.code == original.code
    assert decoded.identifier == original.identifier
    assert decoded.data == original.data


def test_decode_too_short_raises():
    with pytest.raises(ValueError, match="too short"):
        decode_signaling(b"\x01\x02")


def test_unknown_code_preserved():
    raw = bytes([0xFF, 0x01]) + struct.pack("<H", 0)
    pkt = decode_signaling(raw)
    assert pkt.code == 0xFF
    assert pkt.identifier == 0x01


# --- Connection Parameter Update ---

def test_conn_param_update_request_roundtrip():
    req = ConnParamUpdateRequest(
        interval_min=0x0006, interval_max=0x000C,
        latency=0x0000, timeout=0x00C8,
    )
    raw = req.to_bytes()
    decoded = ConnParamUpdateRequest.from_bytes(raw)
    assert decoded.interval_min == 0x0006
    assert decoded.interval_max == 0x000C
    assert decoded.latency == 0x0000
    assert decoded.timeout == 0x00C8


def test_conn_param_update_response_roundtrip():
    resp = ConnParamUpdateResponse(result=0x0000)
    raw = resp.to_bytes()
    decoded = ConnParamUpdateResponse.from_bytes(raw)
    assert decoded.result == 0x0000

    rejected = ConnParamUpdateResponse(result=0x0001)
    raw2 = rejected.to_bytes()
    decoded2 = ConnParamUpdateResponse.from_bytes(raw2)
    assert decoded2.result == 0x0001
