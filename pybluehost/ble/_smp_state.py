"""SMP state machine transitions + action callbacks (Sub-Plan 1).

Phase 1 — Feature Exchange:
    Initiator path:
        IDLE  --(LOCAL_PAIR_REQUEST)--> FEATURE_EXCHANGE  [send PairingRequest]
        FEATURE_EXCHANGE --(PAIRING_RSP_RX)--> CONFIRMING [compute+send local Confirm]
            (SC path: action overrides state to PUBLIC_KEY_EXCHANGE and sends Public Key)
    Responder path:
        IDLE  --(PAIRING_REQ_RX)--> CONFIRMING            [send PairingResponse; wait for Confirm]
            (SC path: action overrides state to PUBLIC_KEY_EXCHANGE and waits for peer Public Key)

Phase 2 Legacy — Confirm/Random/STK:
    Initiator path:
        CONFIRMING --(PAIRING_CONFIRM_RX)--> CONFIRMING   [store peer Confirm, send local Random]
        CONFIRMING --(PAIRING_RANDOM_RX)--> STK_ENCRYPTING
            [verify peer Confirm, derive STK, send HCI_LE_Start_Encryption]
    Responder path:
        CONFIRMING --(PAIRING_CONFIRM_RX)--> CONFIRMING   [gen Srand, compute+send own Confirm]
        CONFIRMING --(PAIRING_RANDOM_RX)--> RANDOM_EXCHANGE
            [verify peer Confirm, send own Random, derive STK]

Phase 2 SC — Public Key Exchange (Task 8):
    Initiator path:
        PUBLIC_KEY_EXCHANGE --(PAIRING_PUBLIC_KEY_RX)--> PUBLIC_KEY_EXCHANGE
            [compute DHKey, wait for peer Confirm]
    Responder path:
        PUBLIC_KEY_EXCHANGE --(PAIRING_PUBLIC_KEY_RX)--> CONFIRMING
            [gen keypair, send Public Key + Cb, advance to CONFIRMING]

Phase 2 SC — DHKey Check (Task 10):
    Initiator path:
        RANDOM_EXCHANGE → (action appended in _sc_initiator_recv_peer_random): send Ea, state → DHKEY_CHECK
        DHKEY_CHECK --(PAIRING_DHKEY_CHECK_RX)--> STK_ENCRYPTING
            [verify peer Eb; on match issue HCI_LE_Start_Encryption with ltk_sc]
    Responder path:
        RANDOM_EXCHANGE --(PAIRING_DHKEY_CHECK_RX)--> DHKEY_CHECK
            [verify peer Ea, compute+send Eb; await controller Encryption_Change]
        DHKEY_CHECK --(ENCRYPTION_CHANGE_SUCCESS)--> KEY_DISTRIBUTION
            [same as STK_ENCRYPTING path]

Phase 3 transitions land in Task 7. Universal failure transitions
(PAIRING_FAILED_RX / TIMEOUT / DISCONNECTED → FAILED) are registered for all
states Phases 1–2 can reach.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from pybluehost.ble.smp import (
    PairingRole,
    SMPCode,
    SMPCrypto,
    SMPEvent,
    SMPPairingConfirm,
    SMPPairingFailed,
    SMPPairingRequest,
    SMPPairingResponse,
    SMPState,
    _log_pairing_complete,
)
from pybluehost.core.address import BDAddress

if TYPE_CHECKING:
    from pybluehost.ble.smp import SMPPairingContext

logger = logging.getLogger(__name__)


def register_transitions(ctx: "SMPPairingContext") -> None:
    """Wire up all transitions for a context based on its role."""
    sm = ctx.state_machine

    if ctx.role == PairingRole.INITIATOR:
        sm.add_transition(
            SMPState.IDLE, SMPEvent.LOCAL_PAIR_REQUEST,
            SMPState.FEATURE_EXCHANGE,
            action=lambda **kw: _initiator_send_pairing_request(ctx, **kw),
        )
        sm.add_transition(
            SMPState.FEATURE_EXCHANGE, SMPEvent.PAIRING_RSP_RX,
            SMPState.CONFIRMING,
            action=lambda **kw: _initiator_recv_pairing_response(ctx, **kw),
        )
    else:
        sm.add_transition(
            SMPState.IDLE, SMPEvent.PAIRING_REQ_RX,
            SMPState.CONFIRMING,
            action=lambda **kw: _responder_recv_pairing_request(ctx, **kw),
        )

    # ---- SC Phase 2.1 — Public Key Exchange ----
    # These transitions fire only when the action in Phase 1 has already
    # overridden ctx.state_machine._state to PUBLIC_KEY_EXCHANGE.
    if ctx.role == PairingRole.INITIATOR:
        sm.add_transition(
            SMPState.PUBLIC_KEY_EXCHANGE, SMPEvent.PAIRING_PUBLIC_KEY_RX,
            SMPState.PUBLIC_KEY_EXCHANGE,  # stay; wait for peer Confirm next
            action=lambda **kw: _sc_initiator_recv_peer_public_key(ctx, **kw),
        )
    else:
        sm.add_transition(
            SMPState.PUBLIC_KEY_EXCHANGE, SMPEvent.PAIRING_PUBLIC_KEY_RX,
            SMPState.CONFIRMING,  # advance; will await Initiator's Random in CONFIRMING
            action=lambda **kw: _sc_responder_recv_peer_public_key(ctx, **kw),
        )

    # ---- SC Phase 2.2 — Initiator receives peer Confirm (only in SC) ----
    # In SC Just Works the Initiator does NOT send a Confirm first; it waits for
    # the Responder's Confirm (Cb).  This transition lives in PUBLIC_KEY_EXCHANGE
    # (where SC Initiator stays after receiving peer's Public Key).
    if ctx.role == PairingRole.INITIATOR:
        sm.add_transition(
            SMPState.PUBLIC_KEY_EXCHANGE, SMPEvent.PAIRING_CONFIRM_RX,
            SMPState.CONFIRMING,
            action=lambda **kw: _sc_initiator_recv_peer_confirm(ctx, **kw),
        )

    # ---- Phase 2 — Confirm/Random ----
    if ctx.role == PairingRole.INITIATOR:
        # Initiator already sent its Confirm in Phase 1 transition (Legacy).
        # Now waits to receive peer Confirm, then peer Random.
        # In SC the PAIRING_CONFIRM_RX transition above already advances to
        # CONFIRMING; from there the PAIRING_RANDOM_RX transition below fires.
        sm.add_transition(
            SMPState.CONFIRMING, SMPEvent.PAIRING_CONFIRM_RX,
            SMPState.CONFIRMING,
            action=lambda **kw: _initiator_recv_peer_confirm(ctx, **kw),
        )
        sm.add_transition(
            SMPState.CONFIRMING, SMPEvent.PAIRING_RANDOM_RX,
            SMPState.STK_ENCRYPTING,
            action=lambda **kw: _initiator_recv_peer_random(ctx, **kw),
        )
    else:
        # Responder: in CONFIRMING after sending Pairing Response.
        # First receives Initiator Confirm → sends own Confirm.
        # Then receives Initiator Random → sends own Random, advances to RANDOM_EXCHANGE.
        sm.add_transition(
            SMPState.CONFIRMING, SMPEvent.PAIRING_CONFIRM_RX,
            SMPState.CONFIRMING,
            action=lambda **kw: _responder_recv_peer_confirm(ctx, **kw),
        )
        sm.add_transition(
            SMPState.CONFIRMING, SMPEvent.PAIRING_RANDOM_RX,
            SMPState.RANDOM_EXCHANGE,
            action=lambda **kw: _responder_recv_peer_random(ctx, **kw),
        )

    # ---- SC Phase 2.3 — DHKey Check ----
    # Initiator: after _sc_initiator_recv_peer_random sends Ea and overrides state
    # to DHKEY_CHECK, it waits for peer Eb here.
    # Responder: still in RANDOM_EXCHANGE when Initiator's Ea arrives.
    if ctx.role == PairingRole.INITIATOR:
        sm.add_transition(
            SMPState.DHKEY_CHECK, SMPEvent.PAIRING_DHKEY_CHECK_RX,
            SMPState.STK_ENCRYPTING,  # SC reuses STK_ENCRYPTING = "encryption pending"
            action=lambda **kw: _sc_initiator_recv_peer_dhkey_check(ctx, **kw),
        )
    else:
        sm.add_transition(
            SMPState.RANDOM_EXCHANGE, SMPEvent.PAIRING_DHKEY_CHECK_RX,
            SMPState.DHKEY_CHECK,  # Responder verifies Ea, sends Eb, waits for Encryption_Change
            action=lambda **kw: _sc_responder_recv_peer_dhkey_check(ctx, **kw),
        )

    # ---- SC Sub-Plan 3a — Numeric Comparison transitions ----
    sm.add_transition(
        SMPState.NUMERIC_COMPARE_PENDING, SMPEvent.NUMERIC_COMPARE_USER_CONFIRMED,
        SMPState.DHKEY_CHECK,
        action=lambda **kw: _nc_user_confirmed(ctx, **kw),
    )
    sm.add_transition(
        SMPState.NUMERIC_COMPARE_PENDING, SMPEvent.NUMERIC_COMPARE_USER_REJECTED,
        SMPState.FAILED,
        action=lambda **kw: _on_failed(ctx, reason=0x03, **kw),
    )

    # Encryption-change advancement (both roles use the same target state)
    sm.add_transition(
        SMPState.STK_ENCRYPTING, SMPEvent.ENCRYPTION_CHANGE_SUCCESS,
        SMPState.KEY_DISTRIBUTION,
        action=lambda **kw: _start_phase3(ctx, **kw),
    )
    sm.add_transition(
        SMPState.RANDOM_EXCHANGE, SMPEvent.ENCRYPTION_CHANGE_SUCCESS,
        SMPState.KEY_DISTRIBUTION,
        action=lambda **kw: _start_phase3(ctx, **kw),
    )
    sm.add_transition(
        SMPState.DHKEY_CHECK, SMPEvent.ENCRYPTION_CHANGE_SUCCESS,
        SMPState.KEY_DISTRIBUTION,
        action=lambda **kw: _start_phase3(ctx, **kw),
    )
    sm.add_transition(
        SMPState.STK_ENCRYPTING, SMPEvent.ENCRYPTION_CHANGE_FAILED,
        SMPState.FAILED,
        action=lambda **kw: _on_failed(ctx, reason=0x08, **kw),
    )
    sm.add_transition(
        SMPState.RANDOM_EXCHANGE, SMPEvent.ENCRYPTION_CHANGE_FAILED,
        SMPState.FAILED,
        action=lambda **kw: _on_failed(ctx, reason=0x08, **kw),
    )
    sm.add_transition(
        SMPState.DHKEY_CHECK, SMPEvent.ENCRYPTION_CHANGE_FAILED,
        SMPState.FAILED,
        action=lambda **kw: _on_failed(ctx, reason=0x08, **kw),
    )

    # ---- Phase 3 — Key distribution ----
    sm.add_transition(
        SMPState.KEY_DISTRIBUTION, SMPEvent.ENCRYPTION_INFO_RX,
        SMPState.KEY_DISTRIBUTION,
        action=lambda **kw: _recv_encryption_info(ctx, **kw),
    )
    sm.add_transition(
        SMPState.KEY_DISTRIBUTION, SMPEvent.MASTER_IDENT_RX,
        SMPState.KEY_DISTRIBUTION,
        action=lambda **kw: _recv_master_ident(ctx, **kw),
    )
    sm.add_transition(
        SMPState.KEY_DISTRIBUTION, SMPEvent.IDENTITY_INFO_RX,
        SMPState.KEY_DISTRIBUTION,
        action=lambda **kw: _recv_identity_info(ctx, **kw),
    )
    sm.add_transition(
        SMPState.KEY_DISTRIBUTION, SMPEvent.IDENTITY_ADDR_RX,
        SMPState.KEY_DISTRIBUTION,
        action=lambda **kw: _recv_identity_addr(ctx, **kw),
    )
    sm.add_transition(
        SMPState.KEY_DISTRIBUTION, SMPEvent.SIGNING_INFO_RX,
        SMPState.KEY_DISTRIBUTION,
        action=lambda **kw: _recv_signing_info(ctx, **kw),
    )
    sm.add_transition(
        SMPState.KEY_DISTRIBUTION, SMPEvent.KEYS_RECEIVED,
        SMPState.BONDED,
        action=lambda **kw: _persist_bond(ctx, **kw),
    )
    sm.set_timeout(SMPState.KEY_DISTRIBUTION, 30.0, SMPEvent.TIMEOUT)

    # Phase-2 timeouts
    sm.set_timeout(SMPState.RANDOM_EXCHANGE, 30.0, SMPEvent.TIMEOUT)
    sm.set_timeout(SMPState.STK_ENCRYPTING, 30.0, SMPEvent.TIMEOUT)
    sm.set_timeout(SMPState.DHKEY_CHECK, 30.0, SMPEvent.TIMEOUT)
    sm.set_timeout(SMPState.NUMERIC_COMPARE_PENDING, 30.0, SMPEvent.TIMEOUT)

    # Universal failure transitions
    for state in (
        SMPState.IDLE, SMPState.FEATURE_EXCHANGE, SMPState.CONFIRMING,
        SMPState.RANDOM_EXCHANGE, SMPState.STK_ENCRYPTING, SMPState.KEY_DISTRIBUTION,
        SMPState.PUBLIC_KEY_EXCHANGE, SMPState.DHKEY_CHECK,
        SMPState.NUMERIC_COMPARE_PENDING,
    ):
        sm.add_transition(
            state, SMPEvent.PAIRING_FAILED_RX, SMPState.FAILED,
            action=lambda **kw: _on_failed(ctx, send_failed=False, **kw),
        )
        sm.add_transition(
            state, SMPEvent.TIMEOUT, SMPState.FAILED,
            action=lambda **kw: _on_failed(ctx, reason=0x08, **kw),  # 0x08 = Unspecified
        )
        sm.add_transition(
            state, SMPEvent.DISCONNECTED, SMPState.FAILED,
            action=lambda **kw: _on_failed(ctx, send_failed=False, **kw),
        )

    # 30-second cumulative timeout (Core 5.4 Vol 3 Part H §3.4)
    for state in (SMPState.FEATURE_EXCHANGE, SMPState.CONFIRMING, SMPState.PUBLIC_KEY_EXCHANGE):
        sm.set_timeout(state, 30.0, SMPEvent.TIMEOUT)


# ---------------------------------------------------------------------------
# Phase 1 actions
# ---------------------------------------------------------------------------

async def _initiator_send_pairing_request(ctx: "SMPPairingContext", **_kw) -> None:
    auth_req = 0x01 if ctx.bondable else 0
    if ctx.security_config is not None and ctx.security_config.enable_secure_connections:
        auth_req |= 0x08  # SC bit
    if ctx.security_config is not None and getattr(ctx.security_config, "mitm_required", False):
        auth_req |= 0x04  # MITM bit
    req = SMPPairingRequest(
        io_capability=ctx.local_io_caps,
        oob_data_flag=0,
        auth_req=auth_req,
        max_key_size=16,
        init_key_dist=0x07,  # EncKey | IdKey | Sign
        resp_key_dist=0x07,
    )
    raw = req.to_bytes()
    ctx.saved_pairing_request = raw
    ctx.local_auth_req = req.auth_req
    ctx.local_init_key_dist = req.init_key_dist
    ctx.local_resp_key_dist = req.resp_key_dist
    await ctx.send(raw)


async def _initiator_recv_pairing_response(ctx: "SMPPairingContext", *, pdu: SMPPairingResponse, **_kw) -> None:
    ctx.saved_pairing_response = pdu.to_bytes()
    ctx.peer_io_caps = pdu.io_capability
    ctx.peer_auth_req = pdu.auth_req
    ctx.peer_max_key_size = pdu.max_key_size
    ctx.peer_init_key_dist = pdu.init_key_dist
    ctx.peer_resp_key_dist = pdu.resp_key_dist

    if _sc_negotiated(ctx):
        # SC path: generate our P-256 keypair, send Pairing_Public_Key.
        # The state machine already set state to CONFIRMING per the registered
        # transition; override it to PUBLIC_KEY_EXCHANGE for SC mode.
        from pybluehost.ble._smp_sc_crypto import generate_p256_keypair
        from pybluehost.ble.smp import SMPPairingPublicKey
        priv, pub = generate_p256_keypair()
        ctx.local_private_key = priv
        ctx.local_public_key = pub
        ctx.state_machine._state = SMPState.PUBLIC_KEY_EXCHANGE
        await ctx.send(SMPPairingPublicKey(
            public_key_x=pub[:32], public_key_y=pub[32:],
        ).to_bytes())
        return

    # Legacy path: Just Works → tk = 0
    ctx.tk = b"\x00" * 16
    # Generate local random
    ctx.local_random = os.urandom(16)
    # Compute c1 confirm value
    # SMPCrypto.c1(k, r, preq, pres, iat, rat, ia, ra)
    # preq/pres are the full 7-byte PDUs (opcode included) per BT Spec Vol 3 Part H §2.2.3
    preq = ctx.saved_pairing_request[:7]
    pres = ctx.saved_pairing_response[:7]
    iat = 0x00  # initiator address type (public)
    rat = 0x00  # responder address type (public)
    ia = _local_address_bytes(ctx)
    ra = _peer_address_bytes(ctx)
    ctx.local_confirm = SMPCrypto.c1(ctx.tk, ctx.local_random, preq, pres, iat, rat, ia, ra)
    await ctx.send(SMPPairingConfirm(confirm_value=ctx.local_confirm).to_bytes())


async def _responder_recv_pairing_request(ctx: "SMPPairingContext", *, pdu: SMPPairingRequest, **_kw) -> None:
    ctx.saved_pairing_request = pdu.to_bytes()
    ctx.peer_io_caps = pdu.io_capability
    ctx.peer_auth_req = pdu.auth_req
    ctx.peer_max_key_size = pdu.max_key_size
    ctx.peer_init_key_dist = pdu.init_key_dist
    ctx.peer_resp_key_dist = pdu.resp_key_dist
    resp_auth_req = 0x01 if ctx.bondable else 0
    if ctx.security_config is not None and ctx.security_config.enable_secure_connections:
        resp_auth_req |= 0x08  # SC bit
    if ctx.security_config is not None and getattr(ctx.security_config, "mitm_required", False):
        resp_auth_req |= 0x04  # MITM bit
    rsp = SMPPairingResponse(
        io_capability=ctx.local_io_caps,
        oob_data_flag=0,
        auth_req=resp_auth_req,
        max_key_size=16,
        init_key_dist=0x07,
        resp_key_dist=0x07,
    )
    raw = rsp.to_bytes()
    ctx.saved_pairing_response = raw
    ctx.local_auth_req = rsp.auth_req
    ctx.local_init_key_dist = rsp.init_key_dist
    ctx.local_resp_key_dist = rsp.resp_key_dist
    ctx.tk = b"\x00" * 16
    await ctx.send(raw)

    if _sc_negotiated(ctx):
        # SC path: override state to PUBLIC_KEY_EXCHANGE to await Initiator's Public Key.
        # The state machine already set state to CONFIRMING per the registered transition.
        ctx.state_machine._state = SMPState.PUBLIC_KEY_EXCHANGE


# ---------------------------------------------------------------------------
# Phase 2 actions
# ---------------------------------------------------------------------------

async def _initiator_recv_peer_confirm(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """Initiator: peer (Responder) Confirm arrived. Store it; send our Random."""
    from pybluehost.ble.smp import SMPPairingRandom
    ctx.peer_confirm = pdu.confirm_value
    # Send our Random
    await ctx.send(SMPPairingRandom(random_value=ctx.local_random).to_bytes())


async def _initiator_recv_peer_random(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """Initiator: peer (Responder) Random arrived. Branch on SC vs Legacy."""
    if _sc_negotiated(ctx):
        await _sc_initiator_recv_peer_random(ctx, pdu=pdu)
        return
    # --- Legacy path ---
    from pybluehost.hci.packets import HCI_LE_Start_Encryption_Command
    ctx.peer_random = pdu.random_value
    # Verify peer's confirm: expected = c1(tk, peer_random, preq, pres, iat, rat, ia, ra)
    preq, pres, iat, rat, ia, ra = _build_c1_params(ctx)
    expected = SMPCrypto.c1(ctx.tk, ctx.peer_random, preq, pres, iat, rat, ia, ra)
    if expected != ctx.peer_confirm:
        await _on_failed(ctx, reason=0x04)  # Confirm Value Failed
        return
    # Derive STK = s1(tk, Srand, Mrand)
    # Initiator's local_random = Mrand; peer_random = Srand.
    ctx.stk = SMPCrypto.s1(ctx.tk, ctx.peer_random, ctx.local_random)
    # Drive encryption
    if ctx._hci is None:
        await _on_failed(ctx, reason=0x08)
        return
    await ctx._hci.send_command(HCI_LE_Start_Encryption_Command(
        connection_handle=ctx.connection_handle,
        random_number=b"\x00" * 8,
        encrypted_diversifier=0,
        long_term_key=ctx.stk,
    ))


async def _responder_recv_peer_confirm(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """Responder: peer (Initiator) Confirm arrived. Generate Srand and own Confirm."""
    from pybluehost.ble.smp import SMPPairingConfirm
    ctx.peer_confirm = pdu.confirm_value
    ctx.local_random = os.urandom(16)
    preq, pres, iat, rat, ia, ra = _build_c1_params(ctx)
    ctx.local_confirm = SMPCrypto.c1(ctx.tk, ctx.local_random, preq, pres, iat, rat, ia, ra)
    await ctx.send(SMPPairingConfirm(confirm_value=ctx.local_confirm).to_bytes())


async def _responder_recv_peer_random(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """Responder: peer (Initiator) Random arrived. Branch on SC vs Legacy."""
    if _sc_negotiated(ctx):
        await _sc_responder_recv_peer_random(ctx, pdu=pdu)
        return
    # --- Legacy path ---
    from pybluehost.ble.smp import SMPPairingRandom
    ctx.peer_random = pdu.random_value
    preq, pres, iat, rat, ia, ra = _build_c1_params(ctx)
    expected = SMPCrypto.c1(ctx.tk, ctx.peer_random, preq, pres, iat, rat, ia, ra)
    if expected != ctx.peer_confirm:
        await _on_failed(ctx, reason=0x04)
        return
    # Send our random
    await ctx.send(SMPPairingRandom(random_value=ctx.local_random).to_bytes())
    # Derive STK locally too (Responder computes the same STK once it has both randoms).
    # s1(TK, Srand, Mrand) — Responder's local_random = Srand; peer_random = Mrand.
    ctx.stk = SMPCrypto.s1(ctx.tk, ctx.local_random, ctx.peer_random)


async def _sc_initiator_recv_peer_public_key(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Initiator: peer's Public Key arrived → compute DHKey, stay in PUBLIC_KEY_EXCHANGE.

    Initiator does NOT send a Confirm in SC Just Works; it waits for the
    Responder's Confirm (Task 9 will handle that transition).
    """
    from pybluehost.ble._smp_sc_crypto import compute_dhkey
    ctx.peer_public_key = pdu.public_key_x + pdu.public_key_y
    ctx.dhkey = compute_dhkey(ctx.local_private_key, ctx.peer_public_key)


async def _sc_responder_recv_peer_public_key(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Responder: Initiator's Public Key arrived.

    1. Store peer public key.
    2. Generate own P-256 keypair, send Pairing_Public_Key.
    3. Compute DHKey.
    4. Generate Nb (random 16 bytes), compute Cb = f4(PKbx, PKax, Nb, 0).
    5. Send Pairing_Confirm(Cb).
    State advances to CONFIRMING (will await Initiator's Random Na in Task 9).
    """
    import os
    from pybluehost.ble._smp_sc_crypto import compute_dhkey, generate_p256_keypair
    from pybluehost.ble.smp import SMPPairingConfirm, SMPPairingPublicKey

    ctx.peer_public_key = pdu.public_key_x + pdu.public_key_y

    # Generate own keypair
    priv, pub = generate_p256_keypair()
    ctx.local_private_key = priv
    ctx.local_public_key = pub

    # Send own Public Key
    await ctx.send(SMPPairingPublicKey(
        public_key_x=pub[:32], public_key_y=pub[32:],
    ).to_bytes())

    # Compute DHKey
    ctx.dhkey = compute_dhkey(priv, ctx.peer_public_key)

    # Generate Nb and compute Cb = f4(PKbx, PKax, Nb, 0)
    # PKbx = our public X (first 32 LE bytes); PKax = peer's public X
    ctx.local_random = os.urandom(16)
    pkbx = ctx.local_public_key[:32]
    pkax = ctx.peer_public_key[:32]
    # f4(U, V, X, Z): U=PKbx, V=PKax, X=Nb(16 bytes), Z=0 (int)
    ctx.local_confirm = SMPCrypto.f4(pkbx, pkax, ctx.local_random, 0)

    # Send Confirm(Cb)
    await ctx.send(SMPPairingConfirm(confirm_value=ctx.local_confirm).to_bytes())


async def _sc_initiator_recv_peer_confirm(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Initiator: Responder's Confirm Cb arrived. Generate Na, send Pairing_Random."""
    from pybluehost.ble.smp import SMPPairingRandom
    ctx.peer_confirm = pdu.confirm_value
    ctx.local_random = os.urandom(16)
    await ctx.send(SMPPairingRandom(random_value=ctx.local_random).to_bytes())


async def _sc_send_dhkey_check_initiator(ctx: "SMPPairingContext") -> None:
    """Initiator Phase 2.3: compute and send Ea, advance to DHKEY_CHECK.

    Extracted from _sc_initiator_recv_peer_random so that NC pairing can defer
    this until the user confirms the numeric value.
    """
    from pybluehost.ble.smp import SMPPairingDHKeyCheck
    local_addr = _local_address_bytes(ctx)
    peer_addr = _peer_address_bytes(ctx)
    a1 = b"\x00" + local_addr
    a2 = b"\x00" + peer_addr
    io_cap_a = bytes([ctx.local_auth_req, 0x00, int(ctx.local_io_caps)])
    ea = SMPCrypto.f6(ctx.mac_key, ctx.local_random, ctx.peer_random, b"\x00" * 16, io_cap_a, a1, a2)
    ctx.local_dhkey_check = ea
    await ctx.send(SMPPairingDHKeyCheck(dhkey_check=ea).to_bytes())
    ctx.state_machine._state = SMPState.DHKEY_CHECK


async def _sc_initiator_recv_peer_random(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Initiator: Responder's Random Nb arrived. Verify Cb, derive f5,
    then branch on association model (NC -> NUMERIC_COMPARE_PENDING, JW -> send Ea)."""
    ctx.peer_random = pdu.random_value
    # Verify Cb = f4(PKbx, PKax, Nb, 0)
    pkbx = ctx.peer_public_key[:32]
    pkax = ctx.local_public_key[:32]
    expected = SMPCrypto.f4(pkbx, pkax, ctx.peer_random, 0)
    if expected != ctx.peer_confirm:
        await _on_failed(ctx, reason=0x04)  # CONFIRM_VALUE_FAILED
        return
    # Override state: SC does not use STK; advance to RANDOM_EXCHANGE instead.
    ctx.state_machine._state = SMPState.RANDOM_EXCHANGE
    # Derive (MacKey, LTK_sc) = f5(DHKey, Na, Nb, A1, A2)
    # A1 = Initiator (local) addr; A2 = Responder (peer) addr
    local_addr = _local_address_bytes(ctx)
    peer_addr = _peer_address_bytes(ctx)
    a1 = b"\x00" + local_addr  # type 0 = public
    a2 = b"\x00" + peer_addr
    mac_key, ltk = SMPCrypto.f5(ctx.dhkey, ctx.local_random, ctx.peer_random, a1, a2)
    ctx.mac_key = mac_key
    ctx.ltk_sc = ltk

    if _association_model(ctx) == "numeric_comparison":
        ctx.state_machine._state = SMPState.NUMERIC_COMPARE_PENDING
        await _sc_compute_and_await_nc(ctx)
        return
    await _sc_send_dhkey_check_initiator(ctx)


async def _sc_responder_recv_peer_random(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Responder: Initiator's Random Na arrived. Send own Nb, derive f5,
    then for NC enter NUMERIC_COMPARE_PENDING and await user confirm."""
    from pybluehost.ble.smp import SMPPairingRandom
    ctx.peer_random = pdu.random_value
    # Responder's local_random (Nb) was generated in _sc_responder_recv_peer_public_key
    await ctx.send(SMPPairingRandom(random_value=ctx.local_random).to_bytes())
    # Derive (MacKey, LTK_sc) = f5(DHKey, Na, Nb, A1, A2)
    # In SC: A1 = Initiator (peer) addr; A2 = Responder (local) addr
    local_addr = _local_address_bytes(ctx)
    peer_addr = _peer_address_bytes(ctx)
    a1 = b"\x00" + peer_addr   # Initiator = peer
    a2 = b"\x00" + local_addr  # Responder = local
    # Na = peer_random (Initiator's); Nb = local_random (Responder's)
    mac_key, ltk = SMPCrypto.f5(ctx.dhkey, ctx.peer_random, ctx.local_random, a1, a2)
    ctx.mac_key = mac_key
    ctx.ltk_sc = ltk

    if _association_model(ctx) == "numeric_comparison":
        ctx.state_machine._state = SMPState.NUMERIC_COMPARE_PENDING
        await _sc_compute_and_await_nc(ctx)


async def _nc_user_confirmed(ctx: "SMPPairingContext", **_kw) -> None:
    """User confirmed NC; resume SC Phase 2.3.

    Initiator: send Ea (which advances state to DHKEY_CHECK).
    Responder: no PDU to send -- reset state back to RANDOM_EXCHANGE so the
    existing PAIRING_DHKEY_CHECK_RX transition (registered from RANDOM_EXCHANGE)
    fires when the Initiator's Ea arrives.
    """
    from pybluehost.ble.smp import PairingRole
    if ctx.role == PairingRole.INITIATOR:
        await _sc_send_dhkey_check_initiator(ctx)
    else:
        ctx.state_machine._state = SMPState.RANDOM_EXCHANGE


async def _sc_initiator_recv_peer_dhkey_check(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Initiator: peer's Eb arrived in DHKEY_CHECK state.

    Verify Eb = f6(MacKey, Nb, Na, 0, IOcapB, B, A), then issue
    HCI_LE_Start_Encryption with the f5-derived ltk_sc (not STK).

    Note: the state machine has already advanced the state to STK_ENCRYPTING
    before calling this action.  On failure we must force the state back to
    FAILED manually (same pattern as other "verify-inside-action" paths).
    """
    from pybluehost.hci.packets import HCI_LE_Start_Encryption_Command

    ctx.peer_dhkey_check = pdu.dhkey_check
    # Expected Eb = f6(MacKey, Nb, Na, rb=0, IOcapB, B, A)
    # IOcapB = (Auth_Req || OOB_Flag || IO_Capability) of Responder (peer)
    io_cap_b = bytes([ctx.peer_auth_req, 0x00, int(ctx.peer_io_caps)])
    local_addr = _local_address_bytes(ctx)
    peer_addr = _peer_address_bytes(ctx)
    a1 = b"\x00" + local_addr  # Initiator = us
    a2 = b"\x00" + peer_addr   # Responder = peer
    expected_eb = SMPCrypto.f6(ctx.mac_key, ctx.peer_random, ctx.local_random, b"\x00" * 16, io_cap_b, a2, a1)
    if expected_eb != ctx.peer_dhkey_check:
        ctx.state_machine._state = SMPState.FAILED  # override the pre-set to_state
        await _on_failed(ctx, reason=0x0B)  # DHKEY_CHECK_FAILED
        return
    # Drive encryption with the f5 LTK directly
    if ctx._hci is None:
        ctx.state_machine._state = SMPState.FAILED
        await _on_failed(ctx, reason=0x08)
        return
    await ctx._hci.send_command(HCI_LE_Start_Encryption_Command(
        connection_handle=ctx.connection_handle,
        random_number=b"\x00" * 8,
        encrypted_diversifier=0,
        long_term_key=ctx.ltk_sc,
    ))


async def _sc_responder_recv_peer_dhkey_check(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Responder: Initiator's Ea arrived in RANDOM_EXCHANGE state.

    Verify Ea = f6(MacKey, Na, Nb, 0, IOcapA, A, B), then compute and send
    Eb = f6(MacKey, Nb, Na, 0, IOcapB, B, A). State advances to DHKEY_CHECK
    (awaiting the controller's LE_LTK_Request / Encryption_Change).

    Note: the state machine has already advanced the state to DHKEY_CHECK
    before calling this action.  On failure we force state back to FAILED.
    """
    from pybluehost.ble.smp import SMPPairingDHKeyCheck

    ctx.peer_dhkey_check = pdu.dhkey_check
    # IOcapA = Initiator's (peer); IOcapB = Responder's (local)
    io_cap_a = bytes([ctx.peer_auth_req, 0x00, int(ctx.peer_io_caps)])
    io_cap_b = bytes([ctx.local_auth_req, 0x00, int(ctx.local_io_caps)])
    local_addr = _local_address_bytes(ctx)
    peer_addr = _peer_address_bytes(ctx)
    a1 = b"\x00" + peer_addr   # Initiator = peer
    a2 = b"\x00" + local_addr  # Responder = us
    # Verify Ea = f6(MacKey, Na, Nb, ra=0, IOcapA, A, B)
    # Na = peer_random; Nb = local_random
    expected_ea = SMPCrypto.f6(ctx.mac_key, ctx.peer_random, ctx.local_random, b"\x00" * 16, io_cap_a, a1, a2)
    if expected_ea != ctx.peer_dhkey_check:
        ctx.state_machine._state = SMPState.FAILED  # override the pre-set to_state
        await _on_failed(ctx, reason=0x0B)  # DHKEY_CHECK_FAILED
        return
    # Compute and send Eb = f6(MacKey, Nb, Na, rb=0, IOcapB, B, A)
    eb = SMPCrypto.f6(ctx.mac_key, ctx.local_random, ctx.peer_random, b"\x00" * 16, io_cap_b, a2, a1)
    ctx.local_dhkey_check = eb
    await ctx.send(SMPPairingDHKeyCheck(dhkey_check=eb).to_bytes())


async def _start_phase3(ctx: "SMPPairingContext", **_kw) -> None:
    """Phase 3 entry: distribute our keys per the negotiated mask, then await peer keys."""
    from pybluehost.ble.smp import (
        SMPEncryptionInformation, SMPIdentityAddressInformation,
        SMPIdentityInformation, SMPMasterIdentification, SMPSigningInformation,
    )
    logger.debug("entered KEY_DISTRIBUTION on handle=0x%04X", ctx.connection_handle)
    mask = ctx.local_init_key_dist if ctx.role == PairingRole.INITIATOR else ctx.local_resp_key_dist
    sc_mode = _sc_negotiated(ctx)

    if mask & 0x01 and not sc_mode:  # EncKey: LTK + EDIV + RAND (Legacy only; SC derives LTK via f5)
        ltk = os.urandom(16)
        ediv = int.from_bytes(os.urandom(2), "little")
        rand = os.urandom(8)
        # Save locally so _persist_bond can record what we sent (Peripheral needs
        # these to respond to LE_LTK_Request during reconnect).
        ctx.local_ltk = ltk
        ctx.local_ediv = ediv
        ctx.local_rand = rand
        await ctx.send(SMPEncryptionInformation(long_term_key=ltk).to_bytes())
        await ctx.send(SMPMasterIdentification(ediv=ediv, rand=rand).to_bytes())
    if mask & 0x02:  # IdKey: IRK + IdentityAddress
        irk = os.urandom(16)
        await ctx.send(SMPIdentityInformation(irk=irk).to_bytes())
        local_addr = ctx.local_address if ctx.local_address is not None else BDAddress(b"\x00" * 6)
        local_addr_bytes = bytes(local_addr.address) if hasattr(local_addr, "address") else bytes(local_addr)
        await ctx.send(SMPIdentityAddressInformation(
            addr_type=0, bd_addr=local_addr_bytes,
        ).to_bytes())
    if mask & 0x04:  # Sign: CSRK
        csrk = os.urandom(16)
        await ctx.send(SMPSigningInformation(signature_key=csrk).to_bytes())

    # If we expect no keys from peer, finalize immediately.
    # In SC mode, strip out the EncKey bit (0x01) since we will never receive a peer LTK.
    expected = ctx.peer_resp_key_dist if ctx.role == PairingRole.INITIATOR else ctx.peer_init_key_dist
    if sc_mode:
        expected &= ~0x01
    if expected == 0:
        await ctx.state_machine.fire(SMPEvent.KEYS_RECEIVED)


# ---------------------------------------------------------------------------
# Phase 3 actions
# ---------------------------------------------------------------------------

async def _recv_encryption_info(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    ctx.received_ltk = pdu.long_term_key
    await _check_phase3_complete(ctx)


async def _recv_master_ident(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    ctx.received_ediv = pdu.ediv
    ctx.received_rand = pdu.rand
    await _check_phase3_complete(ctx)


async def _recv_identity_info(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    ctx.received_irk = pdu.irk
    await _check_phase3_complete(ctx)


async def _recv_identity_addr(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    # SMPIdentityAddressInformation uses addr_type and bd_addr (raw bytes)
    ctx.received_identity_address = (pdu.addr_type, bytes(pdu.bd_addr))
    await _check_phase3_complete(ctx)


async def _recv_signing_info(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    # SMPSigningInformation uses signature_key (not csrk)
    ctx.received_csrk = pdu.signature_key
    await _check_phase3_complete(ctx)


async def _check_phase3_complete(ctx: "SMPPairingContext") -> None:
    """Fire KEYS_RECEIVED if every expected peer key has arrived."""
    expected = ctx.peer_resp_key_dist if ctx.role == PairingRole.INITIATOR else ctx.peer_init_key_dist
    sc_mode = _sc_negotiated(ctx)
    if sc_mode:
        # In SC mode the peer will not send a LTK/EDIV/RAND — both sides already
        # hold the f5-derived LTK.  Strip out the EncKey expectation.
        expected &= ~0x01
    have_enc = (expected & 0x01) == 0 or (
        bool(ctx.received_ltk) and bool(ctx.received_rand)
    )
    have_id = (expected & 0x02) == 0 or (
        bool(ctx.received_irk) and bool(ctx.received_identity_address[1])
    )
    have_sign = (expected & 0x04) == 0 or bool(ctx.received_csrk)
    if have_enc and have_id and have_sign:
        await ctx.state_machine.fire(SMPEvent.KEYS_RECEIVED)


async def _persist_bond(ctx: "SMPPairingContext", **_kw) -> None:
    """Save keys to BondStorage and resolve pairing_complete Future.

    Key storage strategy:
    - SC mode: both sides hold the same f5-derived LTK (ctx.ltk_sc).
      EDIV/RAND are not used in SC — stored as 0/zeros.
    - LE Legacy — Central (Initiator): stores the LTK received from the Peripheral
      (received_ltk/ediv/rand).  At reconnect, Central issues
      HCI_LE_Start_Encryption with these values.
    - LE Legacy — Peripheral (Responder): stores the LTK it generated and sent to
      the Central (local_ltk/ediv/rand).  At reconnect, Peripheral responds to
      LE_LTK_Request with these values.
    """
    from pybluehost.ble.smp import BondInfo, PairingRole
    storage = getattr(ctx, "_bond_storage", None)
    sc_mode = _sc_negotiated(ctx)
    if storage is None:
        logger.debug("no bond storage configured; not persisting bond")
    else:
        if sc_mode:
            # SC: both sides share the f5-derived LTK; EDIV/RAND are unused in SC.
            # NC provides MITM authentication; Just Works does not.
            authenticated = _association_model(ctx) == "numeric_comparison"
            bond = BondInfo(
                peer_address=ctx.peer_address,
                address_type=ctx.received_identity_address[0],
                ltk=ctx.ltk_sc if ctx.ltk_sc else None,
                irk=ctx.received_irk if ctx.received_irk else None,
                csrk=ctx.received_csrk if ctx.received_csrk else None,
                ediv=0,
                rand=b"\x00" * 8,
                key_size=16,
                authenticated=authenticated,
                sc=True,
            )
        else:
            # Legacy pairing
            if ctx.role == PairingRole.RESPONDER and ctx.local_ltk:
                # Peripheral: use the locally generated LTK so reconnect replies work.
                ltk_for_bond = ctx.local_ltk
                ediv_for_bond = ctx.local_ediv
                rand_for_bond = ctx.local_rand
            else:
                # Central: use the LTK received from the Peripheral.
                ltk_for_bond = ctx.received_ltk if ctx.received_ltk else None
                ediv_for_bond = ctx.received_ediv
                rand_for_bond = ctx.received_rand if ctx.received_rand else b"\x00" * 8
            bond = BondInfo(
                peer_address=ctx.peer_address,
                address_type=ctx.received_identity_address[0],
                ltk=ltk_for_bond,
                irk=ctx.received_irk if ctx.received_irk else None,
                csrk=ctx.received_csrk if ctx.received_csrk else None,
                ediv=ediv_for_bond,
                rand=rand_for_bond,
                key_size=16,
                authenticated=False,
                sc=False,
            )
        ltk_stored = bool(bond.ltk)
        await storage.save_bond(bond)
        _log_pairing_complete(
            handle=ctx.connection_handle,
            peer_addr=str(ctx.peer_address),
            ltk_stored=ltk_stored,
        )
    if ctx.pairing_complete and not ctx.pairing_complete.done():
        ctx.pairing_complete.set_result(None)


# ---------------------------------------------------------------------------
# SC negotiation helper (used by Tasks 8-11)
# ---------------------------------------------------------------------------

def _sc_negotiated(ctx: "SMPPairingContext") -> bool:
    """True iff both local config and peer auth_req advertise SC.

    Used by Phase 2 transition routing in Tasks 8-11.
    """
    return (
        ctx.security_config is not None
        and ctx.security_config.enable_secure_connections
        and bool(ctx.local_auth_req & 0x08)
        and bool(ctx.peer_auth_req & 0x08)
    )


def _association_model(ctx: "SMPPairingContext") -> str:
    """Return 'numeric_comparison' | 'passkey_entry' | 'just_works'.

    SC modes (Sub-Plan 3a + 3b-2): NC vs JW.
    Legacy mode (Sub-Plan 3b-1): Passkey Entry vs JW.
    Passkey Entry (SC) and OOB deferred to Sub-Plans 3b-2 and 3c.
    """
    from pybluehost.core.types import IOCapability

    both_mitm = bool(ctx.local_auth_req & 0x04) and bool(ctx.peer_auth_req & 0x04)

    if _sc_negotiated(ctx):
        if not both_mitm:
            return "just_works"
        nc_caps = {int(IOCapability.DISPLAY_YES_NO), int(IOCapability.KEYBOARD_DISPLAY)}
        if int(ctx.local_io_caps) in nc_caps and int(ctx.peer_io_caps) in nc_caps:
            return "numeric_comparison"
        return "just_works"

    # Legacy path — Sub-Plan 3b-1 addition
    if not both_mitm:
        return "just_works"
    if not _passkey_capable(int(ctx.local_io_caps), int(ctx.peer_io_caps)):
        return "just_works"
    return "passkey_entry"


def _passkey_capable(local_io: int, peer_io: int) -> bool:
    """True if the IO-cap pair supports Legacy Passkey Entry (Sub-Plan 3b-1 scope).

    Rules:
      * Neither side may be NO_INPUT_NO_OUTPUT.
      * At least one side must be able to display
        (DISPLAY_ONLY, DISPLAY_YES_NO, KEYBOARD_DISPLAY).
      * At least one side must be able to input
        (KEYBOARD_ONLY, KEYBOARD_DISPLAY).
      * Both-KeyboardOnly falls through to Just Works (out of scope; very rare).
    """
    from pybluehost.core.types import IOCapability
    NO = int(IOCapability.NO_INPUT_NO_OUTPUT)
    KO = int(IOCapability.KEYBOARD_ONLY)
    if local_io == NO or peer_io == NO:
        return False
    display_caps = {int(IOCapability.DISPLAY_ONLY),
                    int(IOCapability.DISPLAY_YES_NO),
                    int(IOCapability.KEYBOARD_DISPLAY)}
    input_caps = {int(IOCapability.KEYBOARD_ONLY),
                  int(IOCapability.KEYBOARD_DISPLAY)}
    has_display = local_io in display_caps or peer_io in display_caps
    has_input = local_io in input_caps or peer_io in input_caps
    if not (has_display and has_input):
        return False
    if local_io == KO and peer_io == KO:
        return False
    return True


def _passkey_local_role(ctx: "SMPPairingContext") -> str:
    """Return 'display' or 'input' for the local side.

    Only meaningful when _association_model(ctx) == 'passkey_entry'.
    """
    from pybluehost.core.types import IOCapability
    local = int(ctx.local_io_caps)
    peer = int(ctx.peer_io_caps)
    display_caps = {int(IOCapability.DISPLAY_ONLY),
                    int(IOCapability.DISPLAY_YES_NO),
                    int(IOCapability.KEYBOARD_DISPLAY)}
    input_caps = {int(IOCapability.KEYBOARD_ONLY),
                  int(IOCapability.KEYBOARD_DISPLAY)}
    local_can_display = local in display_caps
    local_can_input = local in input_caps
    peer_can_display = peer in display_caps
    peer_can_input = peer in input_caps

    # Both-KeyboardDisplay: spec says Initiator displays, Responder inputs.
    if local == int(IOCapability.KEYBOARD_DISPLAY) and peer == int(IOCapability.KEYBOARD_DISPLAY):
        return "display" if ctx.role == PairingRole.INITIATOR else "input"

    # If local can display and peer can't (i.e. peer is KeyboardOnly), local displays.
    if local_can_display and not peer_can_display:
        return "display"
    # If local can input and peer can't (peer is DisplayOnly/DisplayYesNo), local inputs.
    if local_can_input and not peer_can_input:
        return "input"
    # Local is KeyboardDisplay; peer is either DisplayOnly/DisplayYesNo or KeyboardOnly:
    if local == int(IOCapability.KEYBOARD_DISPLAY):
        if peer in (int(IOCapability.DISPLAY_ONLY), int(IOCapability.DISPLAY_YES_NO)):
            return "input"
        if peer == int(IOCapability.KEYBOARD_ONLY):
            return "display"
    # Defensive fallback
    return "display" if local_can_display else "input"


async def _sc_compute_and_await_nc(ctx: "SMPPairingContext") -> None:
    """Compute g2 value for NC, present to delegate, fire confirm/reject event.

    Va = g2(PKax, PKbx, Na, Nb) where PKax/PKbx are the X coordinates of
    Initiator/Responder public keys (32 bytes each). Both sides compute the
    same Va. Numeric value displayed to user is Va mod 10^6 (6 digits).
    """
    from pybluehost.ble.smp import (
        AutoAcceptDelegate,
        PairingRole,
        SMPCrypto,
        SMPEvent,
    )

    if ctx.role == PairingRole.INITIATOR:
        pkax = ctx.local_public_key[:32]
        pkbx = ctx.peer_public_key[:32]
        na = ctx.local_random
        nb = ctx.peer_random
    else:
        pkax = ctx.peer_public_key[:32]
        pkbx = ctx.local_public_key[:32]
        na = ctx.peer_random
        nb = ctx.local_random

    g2_value = SMPCrypto.g2(pkax, pkbx, na, nb)
    numeric_value = g2_value % 1_000_000

    delegate = getattr(ctx, "_delegate", None) or AutoAcceptDelegate()

    async def _await_user_confirm() -> None:
        try:
            confirmed = await delegate.confirm_numeric(ctx.peer_address, numeric_value)
        except AttributeError:
            confirmed = True  # backward compat: older delegate without confirm_numeric
        except Exception as exc:  # noqa: BLE001
            logger.warning("delegate.confirm_numeric raised: %s; rejecting NC", exc)
            confirmed = False
        if confirmed:
            await ctx.state_machine.fire(SMPEvent.NUMERIC_COMPARE_USER_CONFIRMED)
        else:
            await ctx.state_machine.fire(SMPEvent.NUMERIC_COMPARE_USER_REJECTED)

    asyncio.create_task(_await_user_confirm())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_c1_params(
    ctx: "SMPPairingContext",
) -> tuple[bytes, bytes, int, int, bytes, bytes]:
    """Return (preq, pres, iat, rat, ia, ra) for c1 confirm computation.

    Per BT Spec Vol 3 Part H §2.2.3:
      preq = full 7-byte Pairing Request PDU (opcode included)
      pres = full 7-byte Pairing Response PDU (opcode included)
      iat  = Initiator address type (0 = public)
      rat  = Responder address type (0 = public)
      ia   = Initiator device address (6 bytes, LSB first)
      ra   = Responder device address (6 bytes, LSB first)
    """
    preq = ctx.saved_pairing_request[:7]
    pres = ctx.saved_pairing_response[:7]
    iat = 0x00  # address type public
    rat = 0x00
    if ctx.role == PairingRole.INITIATOR:
        ia = _local_address_bytes(ctx)
        ra = _peer_address_bytes(ctx)
    else:
        ia = _peer_address_bytes(ctx)   # peer is Initiator
        ra = _local_address_bytes(ctx)  # local is Responder
    return preq, pres, iat, rat, ia, ra


def _local_address_bytes(ctx: "SMPPairingContext") -> bytes:
    if ctx.local_address is None:
        return b"\x00" * 6
    addr = ctx.local_address
    if hasattr(addr, "address"):
        return bytes(addr.address)
    return bytes(addr)


def _peer_address_bytes(ctx: "SMPPairingContext") -> bytes:
    addr = ctx.peer_address
    if hasattr(addr, "address"):
        return bytes(addr.address)
    return bytes(addr)


async def _on_failed(
    ctx: "SMPPairingContext",
    *,
    reason: int | None = None,
    send_failed: bool = True,
    **_kw,
) -> None:
    logger.warning("SMP pairing failed handle=0x%04X reason=%s", ctx.connection_handle, reason)
    if send_failed and reason is not None and ctx.send is not None:
        try:
            await ctx.send(SMPPairingFailed(reason=reason).to_bytes())
        except Exception:
            logger.debug("failed to send SMPPairingFailed", exc_info=True)
    if ctx.pairing_complete is not None and not ctx.pairing_complete.done():
        ctx.pairing_complete.set_exception(
            RuntimeError(f"SMP pairing failed (reason={reason})")
        )
