"""LE L2CAP signaling PDU codec — 0x06/0x07/0x14/0x15/0x16."""
import pytest

from pybluehost.l2cap.le_signaling import (
    DisconnectionRequest, DisconnectionResponse,
    LECreditBasedConnectionRequest, LECreditBasedConnectionResponse,
    LEFlowControlCredit,
    LE_SIG_DISCONNECTION_REQUEST,
    LE_SIG_DISCONNECTION_RESPONSE,
    LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST,
    LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE,
    LE_SIG_LE_FLOW_CONTROL_CREDIT,
    decode_le_signaling, encode_le_signaling,
)


def test_constants_match_spec():
    assert LE_SIG_DISCONNECTION_REQUEST == 0x06
    assert LE_SIG_DISCONNECTION_RESPONSE == 0x07
    assert LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST == 0x14
    assert LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE == 0x15
    assert LE_SIG_LE_FLOW_CONTROL_CREDIT == 0x16


def test_le_credit_based_connection_request_round_trip():
    req = LECreditBasedConnectionRequest(
        le_psm=0x0080, scid=0x0040, mtu=512, mps=251, initial_credits=10,
    )
    raw = req.encode()
    # Per spec: 5 × u16 LE = 10 bytes
    assert len(raw) == 10
    assert raw == (
        (0x0080).to_bytes(2, "little") + (0x0040).to_bytes(2, "little")
        + (512).to_bytes(2, "little") + (251).to_bytes(2, "little")
        + (10).to_bytes(2, "little")
    )
    parsed = LECreditBasedConnectionRequest.decode(raw)
    assert parsed == req


def test_le_credit_based_connection_response_round_trip():
    resp = LECreditBasedConnectionResponse(
        dcid=0x0041, mtu=247, mps=247, initial_credits=5, result=0x0000,
    )
    raw = resp.encode()
    assert len(raw) == 10
    assert LECreditBasedConnectionResponse.decode(raw) == resp


def test_le_credit_based_connection_response_failure_result():
    resp = LECreditBasedConnectionResponse(
        dcid=0, mtu=0, mps=0, initial_credits=0, result=0x0002,
    )
    raw = resp.encode()
    parsed = LECreditBasedConnectionResponse.decode(raw)
    assert parsed.result == 0x0002


def test_le_flow_control_credit_round_trip():
    pdu = LEFlowControlCredit(cid=0x0040, credits=5)
    raw = pdu.encode()
    assert raw == (0x0040).to_bytes(2, "little") + (5).to_bytes(2, "little")
    assert LEFlowControlCredit.decode(raw) == pdu


def test_disconnection_request_round_trip():
    req = DisconnectionRequest(dcid=0x0041, scid=0x0040)
    raw = req.encode()
    assert len(raw) == 4
    assert DisconnectionRequest.decode(raw) == req


def test_disconnection_response_round_trip():
    resp = DisconnectionResponse(dcid=0x0041, scid=0x0040)
    raw = resp.encode()
    assert len(raw) == 4
    assert DisconnectionResponse.decode(raw) == resp


# ---- Outer frame ---------------------------------------------------------

def test_encode_le_signaling_frame_layout():
    body = bytes.fromhex("4000400000020F00FB000A00")    # arbitrary 12-byte payload
    pdu = encode_le_signaling(0x14, 0x01, body)
    # Frame: code(1) + ident(1) + length(2 LE) + body
    assert pdu[0] == 0x14
    assert pdu[1] == 0x01
    assert int.from_bytes(pdu[2:4], "little") == len(body)
    assert pdu[4:] == body


def test_decode_le_signaling_dispatches_to_correct_type():
    inner = LECreditBasedConnectionRequest(
        le_psm=0x0080, scid=0x0040, mtu=512, mps=251, initial_credits=10,
    ).encode()
    raw = encode_le_signaling(LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, 0x01, inner)
    code, ident, payload = decode_le_signaling(raw)
    assert code == LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST
    assert ident == 0x01
    assert isinstance(payload, LECreditBasedConnectionRequest)
    assert payload.le_psm == 0x0080


def test_decode_le_signaling_rejects_truncated():
    with pytest.raises(ValueError):
        decode_le_signaling(b"\x14\x01\xFF")    # length field truncated


def test_decode_le_signaling_rejects_data_underflow():
    raw = b"\x14\x01" + (10).to_bytes(2, "little") + b"\x00\x00"
    with pytest.raises(ValueError, match="truncated"):
        decode_le_signaling(raw)


def test_decode_le_signaling_unknown_code_returns_raw_payload():
    raw = b"\x99\x01" + (3).to_bytes(2, "little") + b"\x01\x02\x03"
    code, ident, payload = decode_le_signaling(raw)
    assert code == 0x99
    assert ident == 0x01
    assert payload == b"\x01\x02\x03"
