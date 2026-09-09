"""ScPairing — minimal LE Secure Connections pairing state machine (Just Works / Numeric Comparison).

Pure protocol state machine: does not touch HCI/transport. Inbound SMP PDUs are consumed
via ``feed(pdu)``; outbound SMP PDUs are emitted through the callback registered with
``set_output(cb)``. On success ``self.ltk`` exposes the 16-byte LTK.

Two ScPairing instances can be back-to-backed ("pumped") to verify the full flow offline.

Encryption-parameter conventions strictly mirror ``pybluehost/ble/_smp_state.py`` (authoritative reference):
  - Public keys are little-endian on the wire and used directly by f4/g2 (no reversal); PKx = first 32 bytes of the public key.
  - f4(PKx_self, PKx_peer_or_init, N, 0) (Z is the integer 0).
  - f5(DHKey, Na, Nb, A1, A2); A1 = initiator address, A2 = responder address.
  - Ea = f6(MacKey, Na, Nb, 0, IOcapA, A1, A2).
  - Eb = f6(MacKey, Nb, Na, 0, IOcapB, A2, A1).
  - g2(PKa_x, PKb_x, Na, Nb).
  - IOcap = bytes([auth_req, 0x00, io_cap]); Na = initiator nonce, Nb = responder nonce.

HARD RULE: do not import pybluehost.l2cap/.ble/.classic/.gap/.profiles/.stack.
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from .crypto import dhkey as compute_dhkey
from .crypto import f4, f5, f6, g2, generate_keypair
from .delegate import PairingDelegate
from .smp_pdu import (
    AUTHREQ_BONDING,
    AUTHREQ_SC,
    IOCAP_NO_INPUT_NO_OUTPUT,
    PAIRING_CONFIRM,
    PAIRING_DHKEY_CHECK,
    PAIRING_FAILED,
    PAIRING_PUBLIC_KEY,
    PAIRING_RANDOM,
    PAIRING_REQUEST,
    PAIRING_RESPONSE,
    decode,
    encode,
)

_AUTH_REQ = AUTHREQ_SC | AUTHREQ_BONDING  # 0x09
_IO_CAP = IOCAP_NO_INPUT_NO_OUTPUT  # 0x03

logger = logging.getLogger(__name__)

# PAIRING_FAILED reason codes
_REASON_CONFIRM_FAILED = 0x04
_REASON_UNSPECIFIED = 0x0A
_REASON_DHKEY_CHECK_FAILED = 0x0B
_REASON_NUMERIC_FAILED = 0x0C


def _pairing_body() -> bytes:
    # [io_cap, oob=0x00, auth_req, max_key=16, init_key_dist=0, resp_key_dist=0]
    return bytes([_IO_CAP, 0x00, _AUTH_REQ, 16, 0x00, 0x00])


class ScPairing:
    """LE Secure Connections Just Works / Numeric Comparison state machine."""

    def __init__(
        self,
        *,
        role: str,
        local_addr: bytes,
        peer_addr: bytes,
        delegate: PairingDelegate,
        side_name: str = "",
    ) -> None:
        if role not in ("initiator", "responder"):
            raise ValueError(f"role must be 'initiator' or 'responder', got {role!r}")
        self.role = role
        self.local_addr = bytes(local_addr)
        self.peer_addr = bytes(peer_addr)
        self.delegate = delegate
        self.side_name = side_name

        # A1 = initiator addr, A2 = responder addr (7-byte type+addr6), independent of role
        if role == "initiator":
            self.a1 = self.local_addr
            self.a2 = self.peer_addr
        else:
            self.a1 = self.peer_addr
            self.a2 = self.local_addr

        self._priv, self._pub = generate_keypair()  # priv 32 LE, pub 64 LE (X||Y)
        self._peer_pub: Optional[bytes] = None
        self._dhkey: Optional[bytes] = None

        # Na = initiator nonce, Nb = responder nonce (role-independent names)
        self._na: Optional[bytes] = None
        self._nb: Optional[bytes] = None
        self._peer_confirm: Optional[bytes] = None  # only used by initiator (responder's Cb)
        self._mac_key: Optional[bytes] = None
        self._ltk_candidate: Optional[bytes] = None  # promoted to self.ltk only after DHKey check passes

        # Pairing Request/Response bodies (used to derive IOcapA/IOcapB from peer capabilities)
        self._req_body: Optional[bytes] = None  # initiator's Pairing Request body
        self._rsp_body: Optional[bytes] = None  # responder's Pairing Response body

        self.ltk: Optional[bytes] = None
        self._complete = False
        self._failed = False

        self._output: Optional[Callable[[bytes], None]] = None

    # ------------------------------------------------------------------ API
    def set_output(self, cb: Callable[[bytes], None]) -> None:
        self._output = cb

    def is_complete(self) -> bool:
        return self._complete

    async def start(self) -> None:
        if self.role == "initiator":
            self._req_body = _pairing_body()
            self._send(PAIRING_REQUEST, self._req_body)
        # responder: no-op

    async def feed(self, pdu: bytes) -> None:
        if self._failed or self._complete or not pdu:
            return
        op, body = decode(pdu)
        if op == PAIRING_FAILED:
            self._failed = True
            return
        handler = self._dispatch.get((self.role, op))
        if handler is None:
            return
        await handler(self, body)

    # -------------------------------------------------------------- helpers
    def _send(self, opcode: int, body: bytes = b"") -> None:
        if self._output is None:
            raise RuntimeError("output callback not set; call set_output() first")
        self._output(encode(opcode, body))

    def _fail(self, reason: int) -> None:
        self._failed = True
        try:
            self._send(PAIRING_FAILED, bytes([reason]))
        except RuntimeError:
            pass

    def _require_len(self, body: bytes, n: int) -> bool:
        """If length is insufficient, send PAIRING_FAILED and return False (prevents malformed PDUs from raising)."""
        if len(body) < n:
            self._fail(_REASON_UNSPECIFIED)
            return False
        return True

    def _iocap_a(self) -> bytes:
        # initiator's IOcap = auth_req || oob || io_cap, taken from Pairing Request body
        b = self._req_body
        assert b is not None
        return bytes([b[2], b[1], b[0]])

    def _iocap_b(self) -> bytes:
        # responder's IOcap, taken from Pairing Response body
        b = self._rsp_body
        assert b is not None
        return bytes([b[2], b[1], b[0]])

    @property
    def _own_pkx(self) -> bytes:
        return self._pub[:32]

    @property
    def _peer_pkx(self) -> bytes:
        assert self._peer_pub is not None
        return self._peer_pub[:32]

    async def _numeric_ok(self) -> bool:
        # PKa_x = initiator X, PKb_x = responder X
        if self.role == "initiator":
            pka_x, pkb_x = self._own_pkx, self._peer_pkx
        else:
            pka_x, pkb_x = self._peer_pkx, self._own_pkx
        assert self._na is not None and self._nb is not None
        value = g2(pka_x, pkb_x, self._na, self._nb) % 1_000_000
        return bool(await self.delegate.confirm_numeric(self.side_name, value))

    def _derive_f5(self) -> None:
        assert self._dhkey is not None and self._na is not None and self._nb is not None
        mac_key, ltk = f5(self._dhkey, self._na, self._nb, self.a1, self.a2)
        self._mac_key = mac_key
        self._ltk_candidate = ltk  # promotion to self.ltk deferred until DHKey check passes

    # ---------------------------------------------------- initiator handlers
    async def _i_on_response(self, body: bytes) -> None:
        if not self._require_len(body, 6):
            return
        # ScPairing is SC-only: if SC is not negotiated, fail immediately; sending SC-only PDUs would violate spec and deadlock the peer state machine
        rsp_auth = body[2]
        if not (rsp_auth & AUTHREQ_SC):
            logger.warning(
                "对端拒绝 SC(responder auth_req=0x%02x),ScPairing 仅支持 SC,配对终止", rsp_auth
            )
            self._fail(_REASON_UNSPECIFIED)
            return
        # record responder capabilities (for IOcapB), then send own public key
        self._rsp_body = body[:6]
        self._send(PAIRING_PUBLIC_KEY, self._pub)

    async def _i_on_public_key(self, body: bytes) -> None:
        if not self._require_len(body, 64):
            return
        self._peer_pub = body[:64]
        self._dhkey = compute_dhkey(self._priv, self._peer_pub)

    async def _i_on_confirm(self, body: bytes) -> None:
        if not self._require_len(body, 16):
            return
        self._peer_confirm = body[:16]
        self._na = os.urandom(16)
        self._send(PAIRING_RANDOM, self._na)

    async def _i_on_random(self, body: bytes) -> None:
        if not self._require_len(body, 16):
            return
        self._nb = body[:16]
        # verify Cb = f4(PKb_x, PKa_x, Nb, 0); PKb_x = peer/responder X, PKa_x = own/initiator X
        expected = f4(self._peer_pkx, self._own_pkx, self._nb, 0)
        if expected != self._peer_confirm:
            self._fail(_REASON_CONFIRM_FAILED)
            return
        self._derive_f5()
        if not await self._numeric_ok():
            self._fail(_REASON_NUMERIC_FAILED)
            return
        # send Ea = f6(MacKey, Na, Nb, 0, IOcapA, A1, A2)
        assert self._mac_key is not None
        ea = f6(self._mac_key, self._na, self._nb, b"\x00" * 16, self._iocap_a(), self.a1, self.a2)
        self._send(PAIRING_DHKEY_CHECK, ea)

    async def _i_on_dhkey_check(self, body: bytes) -> None:
        if not self._require_len(body, 16):
            return
        eb = body[:16]
        # verify Eb = f6(MacKey, Nb, Na, 0, IOcapB, A2, A1)
        assert self._mac_key is not None and self._na is not None and self._nb is not None
        expected = f6(self._mac_key, self._nb, self._na, b"\x00" * 16, self._iocap_b(), self.a2, self.a1)
        if expected != eb:
            self._fail(_REASON_DHKEY_CHECK_FAILED)
            return
        self.ltk = self._ltk_candidate
        self._complete = True

    # ---------------------------------------------------- responder handlers
    async def _r_on_request(self, body: bytes) -> None:
        if not self._require_len(body, 6):
            return
        # ScPairing is SC-only: if SC is not negotiated, fail immediately; sending SC-only PDUs would violate spec and deadlock the peer state machine
        req_auth = body[2]
        if not (req_auth & AUTHREQ_SC):
            logger.warning(
                "对端拒绝 SC(initiator auth_req=0x%02x),ScPairing 仅支持 SC,配对终止", req_auth
            )
            self._fail(_REASON_UNSPECIFIED)
            return
        # record initiator capabilities (for IOcapA), then send own response
        self._req_body = body[:6]
        self._rsp_body = _pairing_body()
        self._send(PAIRING_RESPONSE, self._rsp_body)

    async def _r_on_public_key(self, body: bytes) -> None:
        if not self._require_len(body, 64):
            return
        self._peer_pub = body[:64]
        self._dhkey = compute_dhkey(self._priv, self._peer_pub)
        # send own public key
        self._send(PAIRING_PUBLIC_KEY, self._pub)
        # pick Nb, compute Cb = f4(PKb_x, PKa_x, Nb, 0); PKb_x = own/responder X, PKa_x = peer/initiator X
        self._nb = os.urandom(16)
        cb = f4(self._own_pkx, self._peer_pkx, self._nb, 0)
        self._send(PAIRING_CONFIRM, cb)

    async def _r_on_random(self, body: bytes) -> None:
        if not self._require_len(body, 16):
            return
        self._na = body[:16]
        # send own Nb
        assert self._nb is not None
        self._send(PAIRING_RANDOM, self._nb)
        self._derive_f5()
        # numeric check now; wait for initiator's DHKey check before sending own
        if not await self._numeric_ok():
            self._fail(_REASON_NUMERIC_FAILED)
            return

    async def _r_on_dhkey_check(self, body: bytes) -> None:
        if not self._require_len(body, 16):
            return
        ea = body[:16]
        assert self._mac_key is not None and self._na is not None and self._nb is not None
        # verify Ea = f6(MacKey, Na, Nb, 0, IOcapA, A1, A2)
        expected_ea = f6(self._mac_key, self._na, self._nb, b"\x00" * 16, self._iocap_a(), self.a1, self.a2)
        if expected_ea != ea:
            self._fail(_REASON_DHKEY_CHECK_FAILED)
            return
        # send Eb = f6(MacKey, Nb, Na, 0, IOcapB, A2, A1)
        eb = f6(self._mac_key, self._nb, self._na, b"\x00" * 16, self._iocap_b(), self.a2, self.a1)
        self._send(PAIRING_DHKEY_CHECK, eb)
        self.ltk = self._ltk_candidate
        self._complete = True

    # ----------------------------------------------------------- dispatch
    _dispatch = {
        ("initiator", PAIRING_RESPONSE): _i_on_response,
        ("initiator", PAIRING_PUBLIC_KEY): _i_on_public_key,
        ("initiator", PAIRING_CONFIRM): _i_on_confirm,
        ("initiator", PAIRING_RANDOM): _i_on_random,
        ("initiator", PAIRING_DHKEY_CHECK): _i_on_dhkey_check,
        ("responder", PAIRING_REQUEST): _r_on_request,
        ("responder", PAIRING_PUBLIC_KEY): _r_on_public_key,
        ("responder", PAIRING_RANDOM): _r_on_random,
        ("responder", PAIRING_DHKEY_CHECK): _r_on_dhkey_check,
    }
