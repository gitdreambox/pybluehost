"""ECFC (Enhanced Credit-Based) signaling PDUs 0x17/0x18 — codec round-trips.

Core Spec Vol 3 Part A §5.1 (L2CAP_CREDIT_BASED_CONNECTION_REQ/RSP):
  Request 0x17:  SPSM(2) + MTU(2) + MPS(2) + InitialCredits(2) + SCID(2 × N)
  Response 0x18: MTU(2) + MPS(2) + InitialCredits(2) + Result(2) + DCID(2 × M)
(M is 0 when Result != 0x0000 — all-or-nothing acceptance.)
"""
import struct

import pytest

from pybluehost.l2cap.le_signaling import (
    ECFCConnectionRequest,
    ECFCConnectionResponse,
    LE_SIG_ECFC_CONNECTION_REQUEST,
    LE_SIG_ECFC_CONNECTION_RESPONSE,
    decode_le_signaling,
    encode_le_signaling,
)


def test_ecfc_request_round_trip():
    req = ECFCConnectionRequest(
        le_psm=0x0080, mtu=512, mps=247, initial_credits=10,
        scids=(0x0040, 0x0041, 0x0042),
    )
    raw = req.encode()
    # SPSM+MTU+MPS+credits = 8 bytes + 3 SCIDs = 14 bytes
    assert len(raw) == 14
    assert ECFCConnectionRequest.decode(raw) == req


def test_ecfc_request_decode_rejects_short_body():
    with pytest.raises(ValueError):
        ECFCConnectionRequest.decode(b"\x00" * 6)   # no room for even one SCID


def test_ecfc_request_decode_rejects_odd_scid_tail():
    # 8 fixed bytes + 2.5 SCIDs worth of bytes = malformed
    with pytest.raises(ValueError):
        ECFCConnectionRequest.decode(b"\x00" * 11)


def test_ecfc_response_round_trip_success():
    resp = ECFCConnectionResponse(
        mtu=512, mps=247, initial_credits=10, result=0x0000,
        dcids=(0x0060, 0x0061),
    )
    raw = resp.encode()
    assert len(raw) == 12
    assert ECFCConnectionResponse.decode(raw) == resp


def test_ecfc_response_round_trip_refused():
    """Refused (result != 0) responses carry NO dcids."""
    resp = ECFCConnectionResponse(
        mtu=0, mps=0, initial_credits=0, result=0x0004, dcids=(),
    )
    raw = resp.encode()
    assert len(raw) == 8
    assert ECFCConnectionResponse.decode(raw) == resp


def test_ecfc_response_decode_tolerates_refused_with_padding_dcids():
    # Spec says a refused response carries no DCIDs, but PTS pads the body with
    # zero DCIDs to match the requested channel count (e.g. the ECFC
    # Insufficient-Authentication refusal in L2CAP/ECFC/BV-10-C). Decode must
    # tolerate and drop them, surfacing only the result code.
    resp = ECFCConnectionResponse.decode(
        struct.pack("<HHHHHH", 0x0040, 0x0040, 0x0002, 0x0005, 0x0000, 0x0000)
    )
    assert resp.result == 0x0005
    assert resp.dcids == ()


def test_ecfc_frames_route_through_signaling_codec():
    req = ECFCConnectionRequest(
        le_psm=0x0080, mtu=512, mps=247, initial_credits=10, scids=(0x0040,),
    )
    frame = encode_le_signaling(LE_SIG_ECFC_CONNECTION_REQUEST, 0x07, req.encode())
    code, ident, payload = decode_le_signaling(frame)
    assert code == LE_SIG_ECFC_CONNECTION_REQUEST
    assert ident == 0x07
    assert isinstance(payload, ECFCConnectionRequest)
    assert payload == req

    resp = ECFCConnectionResponse(
        mtu=512, mps=247, initial_credits=10, result=0x0000, dcids=(0x0060,),
    )
    frame = encode_le_signaling(LE_SIG_ECFC_CONNECTION_RESPONSE, 0x07, resp.encode())
    code, _, payload = decode_le_signaling(frame)
    assert code == LE_SIG_ECFC_CONNECTION_RESPONSE
    assert isinstance(payload, ECFCConnectionResponse)
    assert payload == resp
