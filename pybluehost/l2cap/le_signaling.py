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
LE_SIG_COMMAND_REJECT = 0x01
LE_SIG_CONNECTION_PARAMETER_UPDATE_REQUEST = 0x12
LE_SIG_CONNECTION_PARAMETER_UPDATE_RESPONSE = 0x13
LE_SIG_DISCONNECTION_REQUEST = 0x06
LE_SIG_DISCONNECTION_RESPONSE = 0x07
LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST = 0x14
LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE = 0x15
LE_SIG_LE_FLOW_CONTROL_CREDIT = 0x16
LE_SIG_ECFC_CONNECTION_REQUEST = 0x17
LE_SIG_ECFC_CONNECTION_RESPONSE = 0x18
LE_SIG_ECFC_RECONFIGURE_REQUEST = 0x19
LE_SIG_ECFC_RECONFIGURE_RESPONSE = 0x1A

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
# §4.25 Table 4.17 result codes that only exist for the Enhanced Credit-Based
# response. 0x0004 is also the answer to a connection-request collision: the
# peer is asking for a channel while we have our own request outstanding.
LE_CONN_RESULT_INSUFFICIENT_RESOURCES = 0x0004
LE_CONN_RESULT_INVALID_PARAMETERS = 0x000C

# Minimum MTU an LE Credit-Based channel request may ask for (Core Vol 3 Part A
# §4.22: LE_MTU range 64..65535). A request below it is refused with
# LE_CONN_RESULT_INVALID_PARAMETERS (L2CAP/ECFC/BV-26-C).
LE_MIN_CREDIT_BASED_MTU = 64

# COMMAND_REJECT_RSP (0x01) Reason values (Core Spec Vol 3 Part A §4.1).
LE_REJECT_REASON_COMMAND_NOT_UNDERSTOOD = 0x0000
LE_REJECT_REASON_SIGNALING_MTU_EXCEEDED = 0x0001
LE_REJECT_REASON_INVALID_CID = 0x0002

# CONNECTION_PARAMETER_UPDATE_RESPONSE (0x13) Result values (§4.16).
LE_CONN_PARAM_UPDATE_ACCEPTED = 0x0000
LE_CONN_PARAM_UPDATE_REJECTED = 0x0001


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
        """Body (Core Vol 3 Part A §4.23): DCID(2) + MTU(2) + MPS(2) +
        InitialCredits(2) + Result(2).

        A **refused** response omits the DCID (§4.23: the field "shall only be
        present if Result = 0x0000"), so its body is 8 bytes rather than 10.
        PTS pads refusals with a zero DCID anyway — the same quirk the ECFC twin
        documents. Accept either form: raising here escapes the signaling
        dispatcher, the pending connect future never resolves, and the case dies
        in a 5 s timeout + BTP ERROR instead of reporting the refusal the test
        is asserting (L2CAP/COS/CED/BI-29-C).
        """
        if len(data) == 10:
            dcid, mtu, mps, initial_credits, result = struct.unpack("<HHHHH", data)
        elif len(data) == 8:
            dcid = 0
            mtu, mps, initial_credits, result = struct.unpack("<HHHH", data)
        else:
            raise ValueError(
                f"LE_CREDIT_BASED_CONNECTION_RESPONSE: malformed body of "
                f"{len(data)} bytes (expected 8 or 10)"
            )
        return cls(dcid=dcid, mtu=mtu, mps=mps,
                   initial_credits=initial_credits, result=result)


@dataclass(frozen=True)
class ECFCConnectionRequest:
    """L2CAP_CREDIT_BASED_CONNECTION_REQ (0x17) — Enhanced Credit-Based.

    SPSM(2) + MTU(2) + MPS(2) + InitialCredits(2) + SCID(2 × N). All requested
    channels share the MTU/MPS/credits; each gets its own SCID.
    """

    le_psm: int
    mtu: int
    mps: int
    initial_credits: int
    scids: tuple[int, ...]

    def encode(self) -> bytes:
        if len(self.scids) == 0:
            raise ValueError("ECFC request must carry at least one SCID")
        out = struct.pack(
            "<HHHH", self.le_psm & 0xFFFF, self.mtu & 0xFFFF,
            self.mps & 0xFFFF, self.initial_credits & 0xFFFF,
        )
        for scid in self.scids:
            out += struct.pack("<H", scid & 0xFFFF)
        return out

    @classmethod
    def decode(cls, data: bytes) -> "ECFCConnectionRequest":
        if len(data) < 10 or (len(data) - 8) % 2 != 0:
            raise ValueError(
                f"ECFC_CONNECTION_REQUEST: malformed body of {len(data)} bytes"
            )
        le_psm, mtu, mps, initial_credits = struct.unpack_from("<HHHH", data)
        scids = tuple(
            struct.unpack_from("<H", data, 8 + 2 * i)[0]
            for i in range((len(data) - 8) // 2)
        )
        return cls(le_psm=le_psm, mtu=mtu, mps=mps,
                   initial_credits=initial_credits, scids=scids)


@dataclass(frozen=True)
class ECFCConnectionResponse:
    """L2CAP_CREDIT_BASED_CONNECTION_RSP (0x18) — Enhanced Credit-Based.

    MTU(2) + MPS(2) + InitialCredits(2) + Result(2) + DCID(2 × M).

    M == number of SCIDs the request asked for, **including refusals**: zephyr's
    ``l2cap_ecred_conn_rsp`` always allocates ``sizeof(scid) * req_cid_count``
    DCID slots and memsets them to zero "in case of all connections refused
    error". PTS's parser expects those slots to be present — a refusal that
    omits them makes PTS wait forever (L2CAP/ECFC/BV-11/13/15). Non-zero DCIDs
    on a refusal are still rejected.
    """

    mtu: int
    mps: int
    initial_credits: int
    result: int
    dcids: tuple[int, ...]

    def encode(self) -> bytes:
        if self.result == 0x0000 and len(self.dcids) == 0:
            raise ValueError("successful ECFC response must carry DCIDs")
        # A non-zero Result does NOT imply every slot is zero: §4.25 names
        # 0x0009/0x000A "**Some** connections refused — …", where the refused
        # channels keep a zero DCID slot and the accepted ones carry a real
        # DCID. PTS asserts exactly that shape (L2CAP/ECFC/BV-20-C); an
        # all-refused response contradicts the "some" in the result's name.
        out = struct.pack(
            "<HHHH", self.mtu & 0xFFFF, self.mps & 0xFFFF,
            self.initial_credits & 0xFFFF, self.result & 0xFFFF,
        )
        for dcid in self.dcids:
            out += struct.pack("<H", dcid & 0xFFFF)
        return out

    @classmethod
    def decode(cls, data: bytes) -> "ECFCConnectionResponse":
        if len(data) < 8 or (len(data) - 8) % 2 != 0:
            raise ValueError(
                f"ECFC_CONNECTION_RESPONSE: malformed body of {len(data)} bytes"
            )
        mtu, mps, initial_credits, result = struct.unpack_from("<HHHH", data)
        n_dcids = (len(data) - 8) // 2
        if result != 0x0000:
            # Spec: a refused response carries no DCIDs. PTS pads the body with
            # zero DCIDs to match the requested channel count anyway (e.g. the
            # ECFC Insufficient-Authentication refusal). Tolerate and drop them
            # rather than rejecting the whole PDU — the caller only needs the
            # result code to report the refusal to the Upper Tester.
            return cls(mtu=mtu, mps=mps, initial_credits=initial_credits,
                       result=result, dcids=())
        dcids = tuple(
            struct.unpack_from("<H", data, 8 + 2 * i)[0]
            for i in range(n_dcids)
        )
        return cls(mtu=mtu, mps=mps, initial_credits=initial_credits,
                   result=result, dcids=dcids)


@dataclass(frozen=True)
class ECFCReconfigureRequest:
    """L2CAP_CREDIT_BASED_RECONFIGURE_REQ (0x19) — Enhanced Credit-Based.

    MTU(2) + MPS(2) + DCID(2 × N). The peer asks to renegotiate the (shared)
    MTU/MPS of N already-established channels. Per Core 5.2 Vol 3 Part A §4.25
    only a *reduction* is permitted, and a reduction may cover only a single
    channel per request.
    """

    mtu: int
    mps: int
    dcids: tuple[int, ...]

    def encode(self) -> bytes:
        if len(self.dcids) == 0:
            raise ValueError("reconfigure request must carry at least one DCID")
        out = struct.pack("<HH", self.mtu & 0xFFFF, self.mps & 0xFFFF)
        for dcid in self.dcids:
            out += struct.pack("<H", dcid & 0xFFFF)
        return out

    @classmethod
    def decode(cls, data: bytes) -> "ECFCReconfigureRequest":
        if len(data) < 6 or (len(data) - 4) % 2 != 0:
            raise ValueError(
                f"ECFC_RECONFIGURE_REQUEST: malformed body of {len(data)} bytes"
            )
        mtu, mps = struct.unpack_from("<HH", data)
        dcids = tuple(
            struct.unpack_from("<H", data, 4 + 2 * i)[0]
            for i in range((len(data) - 4) // 2)
        )
        return cls(mtu=mtu, mps=mps, dcids=dcids)


@dataclass(frozen=True)
class ECFCReconfigureResponse:
    """L2CAP_CREDIT_BASED_RECONFIGURE_RSP (0x1A). Result(2)."""

    result: int

    def encode(self) -> bytes:
        return struct.pack("<H", self.result & 0xFFFF)

    @classmethod
    def decode(cls, data: bytes) -> "ECFCReconfigureResponse":
        if len(data) != 2:
            raise ValueError(
                f"ECFC_RECONFIGURE_RESPONSE: malformed body of {len(data)} bytes"
            )
        (result,) = struct.unpack_from("<H", data)
        return cls(result=result)


# Reconfigure result codes (Core 5.2 Vol 3 Part A §4.25).
RECONFIG_RESULT_SUCCESS = 0x0000
#: Reduction of the MTU covering more than one channel in a single request.
RECONFIG_RESULT_MTU_MULTI_CHANNEL = 0x0001
#: Reduction of the MPS covering more than one channel in a single request.
RECONFIG_RESULT_MPS_MULTI_CHANNEL = 0x0002
#: One or more Destination CIDs are not valid for this device.
RECONFIG_RESULT_INVALID_CID = 0x0003
#: Any other failure — including an attempt to *increase* MTU/MPS.
RECONFIG_RESULT_OTHER = 0x0004


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
class CommandReject:
    """COMMAND_REJECT_RSP (0x01). For Reason=0x0002 (Invalid CID in request) the
    data echoes the refused CID (Core Spec Vol 3 Part A §4.1)."""

    reason: int
    refused_cid: int | None = None

    def encode(self) -> bytes:
        body = struct.pack("<H", self.reason & 0xFFFF)
        if self.refused_cid is not None:
            body += struct.pack("<H", self.refused_cid & 0xFFFF)
        return body

    @classmethod
    def decode(cls, data: bytes) -> "CommandReject":
        if len(data) < 2:
            raise ValueError(f"COMMAND_REJECT: expected >=2 bytes, got {len(data)}")
        reason = struct.unpack_from("<H", data)[0]
        refused = struct.unpack_from("<H", data, 2)[0] if len(data) >= 4 else None
        return cls(reason=reason, refused_cid=refused)


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
    LE_SIG_COMMAND_REJECT: CommandReject.decode,
    LE_SIG_DISCONNECTION_REQUEST: DisconnectionRequest.decode,
    LE_SIG_DISCONNECTION_RESPONSE: DisconnectionResponse.decode,
    LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST: LECreditBasedConnectionRequest.decode,
    LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE: LECreditBasedConnectionResponse.decode,
    LE_SIG_LE_FLOW_CONTROL_CREDIT: LEFlowControlCredit.decode,
    LE_SIG_ECFC_CONNECTION_REQUEST: ECFCConnectionRequest.decode,
    LE_SIG_ECFC_CONNECTION_RESPONSE: ECFCConnectionResponse.decode,
    LE_SIG_ECFC_RECONFIGURE_REQUEST: ECFCReconfigureRequest.decode,
    LE_SIG_ECFC_RECONFIGURE_RESPONSE: ECFCReconfigureResponse.decode,
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
