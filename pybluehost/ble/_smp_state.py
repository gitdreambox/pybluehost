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
import secrets
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
    _aes_cmac,
    _log_pairing_complete,
)
from pybluehost.ble.smp import PAIRING_FAILED_REASON_ENCRYPTION_KEY_SIZE
from pybluehost.core.address import AddressType, BDAddress

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

    # ---- Sub-Plan 3b-1 — Legacy Passkey Entry transitions ----
    sm.add_transition(
        SMPState.PASSKEY_INPUT_PENDING, SMPEvent.PAIRING_CONFIRM_RX,
        SMPState.PASSKEY_INPUT_PENDING,
        action=lambda **kw: _passkey_buffer_peer_confirm(ctx, **kw),
    )
    sm.add_transition(
        SMPState.PASSKEY_INPUT_PENDING, SMPEvent.PASSKEY_USER_ENTERED,
        SMPState.CONFIRMING,
        action=lambda **kw: _passkey_user_entered(ctx, **kw),
    )
    sm.add_transition(
        SMPState.PASSKEY_INPUT_PENDING, SMPEvent.PASSKEY_USER_REJECTED,
        SMPState.FAILED,
        action=lambda **kw: _on_failed(ctx, reason=0x01, **kw),
    )

    # ---- Sub-Plan 3b-2 — SC Passkey Entry per-round transitions ----
    sm.add_transition(
        SMPState.PASSKEY_SC_ROUND, SMPEvent.PAIRING_CONFIRM_RX,
        SMPState.PASSKEY_SC_ROUND,
        action=lambda **kw: _sc_passkey_recv_peer_confirm(ctx, **kw),
    )
    sm.add_transition(
        SMPState.PASSKEY_SC_ROUND, SMPEvent.PAIRING_RANDOM_RX,
        SMPState.PASSKEY_SC_ROUND,
        action=lambda **kw: _sc_passkey_recv_peer_random(ctx, **kw),
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
    sm.set_timeout(SMPState.PASSKEY_INPUT_PENDING, 60.0, SMPEvent.TIMEOUT)
    sm.set_timeout(SMPState.PASSKEY_SC_ROUND, 60.0, SMPEvent.TIMEOUT)

    # ---- Terminal states must absorb late events ----
    # A finished pairing is terminal for *that* pairing: a later Security Request
    # drops the context and starts a fresh one (SMPManager.on_pdu), so BONDED /
    # FAILED only ever see stragglers. Without these the state machine raises
    # InvalidTransitionError on them — routine, not exceptional: a PTS Lower
    # Tester that already got what it needed winds the case down by sending
    # Pairing Failed after the bond was persisted (GAP/SEC/AUT/BV-13).
    sm.add_transition(
        SMPState.BONDED, SMPEvent.PAIRING_FAILED_RX, SMPState.BONDED,
        action=lambda **kw: _bonded_peer_pairing_failed(ctx, **kw),
    )
    # The bond is already on disk and stays valid, so nothing to tear down here.
    sm.add_transition(SMPState.BONDED, SMPEvent.DISCONNECTED, SMPState.BONDED)
    sm.add_transition(SMPState.BONDED, SMPEvent.TIMEOUT, SMPState.BONDED)
    sm.add_transition(SMPState.FAILED, SMPEvent.PAIRING_FAILED_RX, SMPState.FAILED)
    sm.add_transition(SMPState.FAILED, SMPEvent.DISCONNECTED, SMPState.FAILED)

    # Universal failure transitions
    for state in (
        SMPState.IDLE, SMPState.FEATURE_EXCHANGE, SMPState.CONFIRMING,
        SMPState.RANDOM_EXCHANGE, SMPState.STK_ENCRYPTING, SMPState.KEY_DISTRIBUTION,
        SMPState.PUBLIC_KEY_EXCHANGE, SMPState.DHKEY_CHECK,
        SMPState.NUMERIC_COMPARE_PENDING,
        SMPState.PASSKEY_INPUT_PENDING,
        SMPState.PASSKEY_SC_ROUND,
    ):
        sm.add_transition(
            state, SMPEvent.PAIRING_FAILED_RX, SMPState.FAILED,
            action=lambda **kw: _recv_peer_pairing_failed(ctx, **kw),
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
    sec_req = getattr(ctx, "peer_sec_req_auth_req", None)
    if sec_req is not None:
        # Pairing triggered by a peer's Security Request: mirror the security
        # level the peripheral asked for, including its MITM bit — do NOT force
        # MITM on from the global config. A SC-only request (0x08, no MITM) must
        # yield Just Works (SM/CEN/PIS/BV-03); forcing MITM would make the peer
        # pick passkey entry while we compute JW → model mismatch → timeout.
        # Conversely an authenticated request (MITM set) must set MITM so a
        # protected read that prompted the Security Request succeeds
        # (GAP/SEC/AUT). Core Vol 3 Part H §3.6.1.
        if sec_req & 0x04:
            auth_req |= 0x04  # MITM bit
    elif ctx.security_config is not None and getattr(ctx.security_config, "mitm_required", False):
        auth_req |= 0x04  # MITM bit (locally-initiated pair, from config)
    # SC-only mode constrains the *SC bit*, NOT the MITM bit: GAP.TS pairs each
    # authenticated SC-only case (BV-42/44 level 3, BV-28/29 level 4) with an
    # UNAUTHENTICATED level-2 twin (BV-41/43) whose PTS responder answers
    # AuthReq 0x09. Forcing MITM here split the association models on those
    # twins (we computed passkey display, PTS computed Just Works) and the LT
    # disconnected right after the public key. Authenticated SC-only cases
    # enable mitm_required per case instead (pybluehost_iut/gap.py).
    req = SMPPairingRequest(
        io_capability=ctx.local_io_caps,
        oob_data_flag=_local_oob_data_flag(ctx),
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


# Core Vol 3 Part H §2.3.4: the encryption key size is 7..16 octets. If the
# negotiated size (min of both Max_Encryption_Key_Size) would fall below the
# spec floor the IUT must abort with "Encryption Key Size" (SM/*/EKS/BI-xx:
# the Lower Tester offers Max_Encryption_Key_Size = min-1 and expects a
# Pairing Failed, not a continued pairing).
_MIN_ENCRYPTION_KEY_SIZE = 7


async def _reject_undersized_key(ctx: "SMPPairingContext") -> bool:
    """Abort with "Encryption Key Size" if the negotiated key size is invalid.

    Two floors apply (Core Vol 3 Part H §2.3.4):
    - legacy pairing: 7 octets;
    - LE Secure Connections: exactly 16 — the spec fixes the SC key length, so a
      peer offering a smaller Maximum_Encryption_Key_Size is out of range.

    PTS exercises the SC floor as a peripheral with a Secure Connections Pairing
    Request carrying Max_Encryption_Key_Size in [7, 15] and expects Pairing
    Failed 0x06 on every round (GAP/SEC/SEM/BI-09/20/21/22/23).

    Returns True when the pairing was aborted (caller must stop).
    """
    negotiated = _negotiated_key_size(ctx)
    floor = max(_MIN_ENCRYPTION_KEY_SIZE, _configured_min_key_size(ctx))
    if negotiated >= floor:
        return False
    await _on_failed(ctx, reason=PAIRING_FAILED_REASON_ENCRYPTION_KEY_SIZE)
    return True


def _configured_min_key_size(ctx: "SMPPairingContext") -> int:
    """Minimum key size the IUT is configured to accept (BTP GAP
    SET_MIN_ENC_KEY_SIZE), defaulting to the 7-octet spec floor.

    Raising it to 16 is how the PTS IUT behaves as "LE security mode 1 level
    3/4": GAP/SEC/SEM/BI-09/20/21/22/23 sweep Max_Encryption_Key_Size over
    [7,15] and require Pairing Failed 0x06 on every round. The default stays 7
    because other suites pair with SC + a short key on purpose (the GATT/SR
    key-size preambles) and must succeed.
    """
    cfg = ctx.security_config
    return int(getattr(cfg, "min_encryption_key_size", _MIN_ENCRYPTION_KEY_SIZE))


def _negotiated_key_size(ctx: "SMPPairingContext") -> int:
    """min(local, peer) Max_Encryption_Key_Size (Core Vol 3 Part H §2.3.4)."""
    local_max = getattr(ctx, "local_max_key_size", 16)
    peer_max = getattr(ctx, "peer_max_key_size", 16)
    return min(local_max, peer_max)


def _reduce_key(key: bytes, size: int) -> bytes:
    """Zero the most significant (16 - size) octets of a 16-octet key (§2.3.4).

    A key shorter than 16 octets keeps only its ``size`` least significant
    octets; the rest are zero. Both sides must apply this to the STK and the
    distributed LTK — replying to LE_LTK_Request with the unreduced key makes
    the LL MIC fail and the link drops (SM/PER/EKS/BV-02).
    """
    if len(key) != 16:
        return key
    return bytes(key[:size]) + b"\x00" * (16 - size)


async def _initiator_recv_pairing_response(ctx: "SMPPairingContext", *, pdu: SMPPairingResponse, **_kw) -> None:
    ctx.saved_pairing_response = pdu.to_bytes()
    ctx.peer_io_caps = pdu.io_capability
    ctx.peer_oob_data_flag = pdu.oob_data_flag
    ctx.peer_auth_req = pdu.auth_req
    ctx.peer_max_key_size = pdu.max_key_size
    ctx.peer_init_key_dist = pdu.init_key_dist
    ctx.peer_resp_key_dist = pdu.resp_key_dist

    # SC-only mode (GAP/SEC/SEM/BV-28, outgoing): the peer answered without
    # the SC bit — abort with Pairing Failed "Authentication Requirements"
    # instead of continuing a legacy exchange.
    cfg = ctx.security_config
    if cfg is not None and getattr(cfg, "sc_only_mode", False) \
            and not (pdu.auth_req & 0x08):
        await _on_failed(ctx, reason=0x03)
        return

    if await _reject_undersized_key(ctx):
        return

    if _sc_negotiated(ctx):
        # SC path: generate our P-256 keypair, send Pairing_Public_Key.
        # The state machine already set state to CONFIRMING per the registered
        # transition; override it to PUBLIC_KEY_EXCHANGE for SC mode.
        from pybluehost.ble._smp_sc_crypto import generate_p256_keypair
        from pybluehost.ble.smp import SMPPairingPublicKey
        # SC OOB: reuse the keypair our OOB confirm commits to, so the confirm
        # PTS holds matches the public key we send over the air.
        if getattr(ctx, "oob_sc_keypair", None):
            priv, pub = ctx.oob_sc_keypair
        else:
            priv, pub = generate_p256_keypair()
        ctx.local_private_key = priv
        ctx.local_public_key = pub
        ctx.state_machine._state = SMPState.PUBLIC_KEY_EXCHANGE
        await ctx.send(SMPPairingPublicKey(
            public_key_x=pub[:32], public_key_y=pub[32:],
        ).to_bytes())
        # SC Passkey Display: emit the passkey now — PTS's passkey MMIs (WID
        # 141/106) race ahead of the public-key exchange (SCPK/BI-03).
        if _association_model(ctx) == "passkey_entry" \
                and _passkey_local_role(ctx) == "display":
            await _sc_passkey_display_now(ctx)
        return

    # Sub-Plan 3c: Legacy OOB. When an OOB TK is provisioned (BTP
    # OOB_LEGACY_SET_DATA) AND the peer also has OOB data (its Pairing Response
    # OOB flag set), both devices share that data as the TK — use it directly and
    # run the Just Works confirm/random exchange, bypassing the association-model
    # selection (OOB outranks passkey/just-works). Core §2.3.5.3: OOB applies
    # only when BOTH sides have OOB data; if the peer's flag is 0 we must fall
    # through to the IO-capability model (SM/CEN/OOB/BV-03 passkey, BV-09 JW).
    if getattr(ctx, "oob_tk", b"") and ctx.peer_oob_data_flag:
        ctx.tk = ctx.oob_tk
        ctx.local_random = os.urandom(16)
        preq, pres, iat, rat, ia, ra = _build_c1_params(ctx)
        ctx.local_confirm = SMPCrypto.c1(
            ctx.tk, ctx.local_random, preq, pres, iat, rat, ia, ra,
        )
        await ctx.send(SMPPairingConfirm(confirm_value=ctx.local_confirm).to_bytes())
        return

    # Sub-Plan 3b-1: Legacy Passkey Entry branch
    model = _association_model(ctx)
    if model == "passkey_entry":
        role = _passkey_local_role(ctx)
        if role == "display":
            # Display role: obtain a 6-digit passkey (delegate may preset one for
            # scripted/test scenarios; otherwise generate randomly), show it to
            # the user, then compute c1 and send Pairing_Confirm.
            ctx.passkey = await _passkey_resolve_display_value(ctx)
            delegate = getattr(ctx, "_delegate", None)
            if delegate is not None:
                try:
                    await delegate.display_passkey(ctx.peer_address, ctx.passkey)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "delegate.display_passkey raised: %s; proceeding", exc,
                    )
            ctx.tk = ctx.passkey.to_bytes(16, "little")
            ctx.local_random = os.urandom(16)
            preq, pres, iat, rat, ia, ra = _build_c1_params(ctx)
            ctx.local_confirm = SMPCrypto.c1(
                ctx.tk, ctx.local_random, preq, pres, iat, rat, ia, ra,
            )
            await ctx.send(SMPPairingConfirm(confirm_value=ctx.local_confirm).to_bytes())
            return
        # Input role: override state to PASSKEY_INPUT_PENDING and spawn the
        # delegate task; the user-entered handler will send our Confirm later.
        ctx.state_machine._state = SMPState.PASSKEY_INPUT_PENDING
        await _passkey_await_user_input(ctx)
        return

    # Legacy path: Just Works → tk = 0
    ctx.tk = b"\x00" * 16
    # Generate local random
    ctx.local_random = os.urandom(16)
    # Compute c1 confirm value
    # SMPCrypto.c1(k, r, preq, pres, iat, rat, ia, ra)
    # preq/pres are the full 7-byte PDUs (opcode included) per BT Spec Vol 3 Part H §2.2.3
    preq, pres, iat, rat, ia, ra = _build_c1_params(ctx)
    ctx.local_confirm = SMPCrypto.c1(ctx.tk, ctx.local_random, preq, pres, iat, rat, ia, ra)
    await ctx.send(SMPPairingConfirm(confirm_value=ctx.local_confirm).to_bytes())


async def _responder_recv_pairing_request(ctx: "SMPPairingContext", *, pdu: SMPPairingRequest, **_kw) -> None:
    ctx.saved_pairing_request = pdu.to_bytes()
    ctx.peer_io_caps = pdu.io_capability
    ctx.peer_oob_data_flag = pdu.oob_data_flag
    ctx.peer_auth_req = pdu.auth_req
    ctx.peer_max_key_size = pdu.max_key_size
    ctx.peer_init_key_dist = pdu.init_key_dist
    ctx.peer_resp_key_dist = pdu.resp_key_dist
    # A Pairing Request right after our own Security Request means the central
    # had no usable bond for us — a bonded central answers the request by
    # encrypting (Core Vol 3 Part H §3.6.1). GAP/SEC/AUT/BV-22's whole verdict
    # is the IUT reporting the lost bond at exactly this point (MSC: Security
    # Request -> Pairing Request -> Bond Lost); pairing itself still proceeds.
    mgr = getattr(ctx, "_smp_manager", None)
    if mgr is not None and ctx.connection_handle in mgr._secreq_sent:
        mgr._secreq_sent.discard(ctx.connection_handle)
        storage = getattr(ctx, "_bond_storage", None)
        if storage is not None and await storage.load_bond(ctx.peer_address) is not None:
            mgr._emit_bond_lost(ctx.connection_handle)
    # SC-only mode: a legacy Pairing Request (no SC bit) is rejected with
    # Pairing Failed "Authentication Requirements" — no Pairing Response.
    cfg = ctx.security_config
    if cfg is not None and getattr(cfg, "sc_only_mode", False) \
            and not (pdu.auth_req & 0x08):
        await _on_failed(ctx, reason=0x03)
        return
    if await _reject_undersized_key(ctx):
        return
    # Mirror the peer's Bonding_Flags too (gated on local bondable): claiming
    # bonding when the peer requested none (e.g. SM/*/OOB where PTS sends
    # auth_req=0x04 with key_dist=0x0000) makes PTS expect a bond that never
    # forms across the test's re-pair rounds -> INDCSV.
    resp_auth_req = (pdu.auth_req & 0x01) if ctx.bondable else 0
    # Mirror the peer's requested security level so the IUT adapts to each PTS
    # case's intent (qualification-IUT behaviour). A static "always SC+MITM"
    # makes PTS abort with Pairing Failed 0x0A (Invalid Parameters) on cases that
    # request legacy/unauthenticated pairing (e.g. GAP/SEC/SEM/BV-23-C), and a
    # static "legacy only" fails the SC cases. Mirror instead: SC if the peer
    # asked AND we're SC-capable; MITM if the peer asked (a local mitm_required
    # policy can still force it on).
    peer_auth = pdu.auth_req
    if (peer_auth & 0x08) and ctx.security_config is not None \
            and ctx.security_config.enable_secure_connections:
        resp_auth_req |= 0x08  # SC bit
    # MITM mirrors the peer's request, with the local mitm_required policy as an
    # explicit per-case override (SM/PER/PKE/BV-05: SM.TS Table 4.3 requires the
    # response's MITM=1 even though the LT requests 0). The SM profile enables
    # that policy PER CASE — never globally, because a global force leaks into
    # cases that are unauthenticated by design (SM/PER/KDU/BV-08, PKE/BV-06):
    # the response then claims MITM, PTS selects passkey entry while we compute
    # Just Works, and the pairing dies. The initiator's REQUEST takes MITM from
    # the same config (CEN PKE/NC cases need it).
    if (peer_auth & 0x04) or (
        ctx.security_config is not None
        and getattr(ctx.security_config, "mitm_required", False)
    ):
        resp_auth_req |= 0x04  # MITM bit
    supported_key_dist = 0x07  # EncKey | IdKey | Sign
    rsp = SMPPairingResponse(
        io_capability=ctx.local_io_caps,
        oob_data_flag=_local_oob_data_flag(ctx),
        auth_req=resp_auth_req,
        max_key_size=16,
        init_key_dist=pdu.init_key_dist & supported_key_dist,
        resp_key_dist=pdu.resp_key_dist & supported_key_dist,
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
        # SC Passkey Display: emit the passkey now — PTS's passkey MMIs (WID
        # 141/106) race ahead of the public-key exchange (SCPK/BI-05).
        if _association_model(ctx) == "passkey_entry" \
                and _passkey_local_role(ctx) == "display":
            await _sc_passkey_display_now(ctx)
        return

    # Sub-Plan 3c: Legacy OOB — use the provisioned OOB TK and wait for the
    # Initiator's Pairing_Confirm (no PDU to send here), but ONLY when the peer
    # also has OOB data (its Pairing Request OOB flag set). Core §2.3.5.3: with
    # only one side holding OOB data we fall through to the IO-capability model
    # (SM/PER/OOB/BV-04 passkey, BV-10 JW). The confirm/random handlers use ctx.tk.
    if getattr(ctx, "oob_tk", b"") and ctx.peer_oob_data_flag:
        ctx.tk = ctx.oob_tk
        return

    # Sub-Plan 3b-1: Legacy Passkey branch
    model = _association_model(ctx)
    if model == "passkey_entry":
        role = _passkey_local_role(ctx)
        if role == "display":
            ctx.passkey = await _passkey_resolve_display_value(ctx)
            delegate = getattr(ctx, "_delegate", None)
            if delegate is not None:
                try:
                    await delegate.display_passkey(ctx.peer_address, ctx.passkey)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "delegate.display_passkey raised: %s; proceeding", exc,
                    )
            ctx.tk = ctx.passkey.to_bytes(16, "little")
            # No PDU to send — Responder waits for Initiator's Pairing_Confirm.
            return
        # role == "input": override state and spawn delegate task
        ctx.state_machine._state = SMPState.PASSKEY_INPUT_PENDING
        await _passkey_await_user_input(ctx)


# ---------------------------------------------------------------------------
# Phase 2 actions
# ---------------------------------------------------------------------------

async def _initiator_recv_peer_confirm(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """Initiator: peer (Responder) Confirm arrived. Store it; send our Random."""
    from pybluehost.ble.smp import SMPPairingRandom
    ctx.peer_confirm = pdu.confirm_value
    # SM/CEN/JW/BI-06-C: a Responder that echoes back the Initiator's own confirm
    # (LP_CONFIRM_R == LP_CONFIRM_I) is a reflection — the IUT must abort, not
    # proceed to the Random exchange.
    if ctx.peer_confirm == getattr(ctx, "local_confirm", None):
        await _on_failed(ctx, reason=0x04)  # Confirm Value Failed
        return
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
    ctx.stk = _reduce_key(
        SMPCrypto.s1(ctx.tk, ctx.peer_random, ctx.local_random),
        _negotiated_key_size(ctx))
    # Drive encryption
    if ctx._hci is None:
        await _on_failed(ctx, reason=0x08)
        return
    status = await ctx._hci.send_command(HCI_LE_Start_Encryption_Command(
        connection_handle=ctx.connection_handle,
        random_number=b"\x00" * 8,
        encrypted_diversifier=0,
        long_term_key=ctx.stk,
    ))
    # A non-zero status means no HCI_Encryption_Change will ever arrive, and the
    # state machine would just sit in STK_ENCRYPTING until its 30 s timeout —
    # which is how a re-pair on an already-encrypted link (GAP/SEC/AUT/BV-13,
    # where the controller answers Command Disallowed) surfaces as a bare
    # "Pairing Failed: Unspecified Reason" with no other clue.
    logger.debug(
        "LE_Start_Encryption (legacy STK) handle=0x%04X status=%s",
        ctx.connection_handle, getattr(status, "status", "?"),
    )


async def _responder_recv_peer_confirm(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """Responder: peer (Initiator) Confirm arrived. Generate Srand and own Confirm.

    Sub-Plan 3b-1: in Legacy Passkey Input role we already sent our Confirm in
    ``_passkey_user_entered`` once the user typed the passkey. If the user input
    races ahead of the Initiator's Confirm (e.g. an instant scripted delegate
    in tests), this handler runs in CONFIRMING after we already transmitted —
    so we must only buffer the peer's value, not generate a fresh local_random
    and send a duplicate Confirm.
    """
    from pybluehost.ble.smp import SMPPairingConfirm
    ctx.peer_confirm = pdu.confirm_value
    if (
        _association_model(ctx) == "passkey_entry"
        and _passkey_local_role(ctx) == "input"
        and ctx.local_confirm is not None
    ):
        # Already sent our Confirm via _passkey_user_entered; nothing more to do.
        return
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
    ctx.stk = _reduce_key(
        SMPCrypto.s1(ctx.tk, ctx.local_random, ctx.peer_random),
        _negotiated_key_size(ctx))


async def _sc_passkey_display_now(ctx: "SMPPairingContext") -> None:
    """Resolve and surface the display-side SC passkey at feature-exchange time.

    PTS issues its passkey MMIs (WID 141 "enter passkey", WID 106 "enter WRONG
    passkey" for the BI negative cases) as soon as pairing starts — before the
    public-key exchange — and auto-pts computes the entry from
    ``stack.gap.passkey.data``, fed by our BTP PASSKEY_DISPLAY event. Deferring
    the display until the key exchange completes loses that race: passkey.data
    is still None and WID 106 crashes with ``int(None)`` (SCPK/BI-03/BI-05
    FATAL ERROR). Idempotent: the later ``_sc_passkey_*_display_enter`` reuses
    the already-displayed ``ctx.passkey`` instead of drawing a new one.
    """
    if getattr(ctx, "_passkey_displayed", False):
        return
    ctx.passkey = await _passkey_resolve_display_value(ctx)
    ctx._passkey_displayed = True
    logger.debug("SMP sc passkey display: model=%s role=%s passkey=%06d",
                 _association_model(ctx), _passkey_local_role(ctx), ctx.passkey)
    delegate = getattr(ctx, "_delegate", None)
    if delegate is not None:
        try:
            await delegate.display_passkey(ctx.peer_address, ctx.passkey)
        except Exception as exc:  # noqa: BLE001
            logger.warning("delegate.display_passkey raised: %s; proceeding", exc)


async def _sc_passkey_initiator_display_enter(ctx: "SMPPairingContext") -> None:
    """Initiator Display: resolve passkey, display, send Ca_1, state -> PASSKEY_SC_ROUND."""
    await _sc_passkey_display_now(ctx)
    ctx.passkey_round = 1
    ctx.passkey_round_phase = "AWAIT_PEER_CONFIRM"
    ctx.state_machine._state = SMPState.PASSKEY_SC_ROUND
    await _sc_passkey_send_round_confirm(ctx)


async def _sc_passkey_responder_display_enter(ctx: "SMPPairingContext") -> None:
    """Responder Display: resolve passkey, display, state -> PASSKEY_SC_ROUND (no PDU)."""
    await _sc_passkey_display_now(ctx)
    ctx.passkey_round = 1
    ctx.passkey_round_phase = "AWAIT_PEER_CONFIRM"
    ctx.state_machine._state = SMPState.PASSKEY_SC_ROUND


async def _sc_initiator_recv_peer_public_key(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Initiator: peer's Public Key arrived → compute DHKey.

    For Just Works / NC: stay in PUBLIC_KEY_EXCHANGE (await Responder's Confirm).
    For SC Passkey Display: enter PASSKEY_SC_ROUND and send Ca_1.
    For SC Passkey Input: enter PASSKEY_INPUT_PENDING and spawn delegate task.
    """
    from pybluehost.ble._smp_sc_crypto import compute_dhkey, peer_public_key_valid
    ctx.peer_public_key = pdu.public_key_x + pdu.public_key_y
    # SM/*/KDU/BI-04: reject an invalid (off-curve) peer public key with DHKey
    # Check Failed instead of computing a DHKey from it / crashing the handler.
    if not peer_public_key_valid(ctx.peer_public_key):
        await _on_failed(ctx, reason=0x0B)  # DHKey Check Failed
        return
    ctx.dhkey = compute_dhkey(ctx.local_private_key, ctx.peer_public_key)

    if _association_model(ctx) == "oob":
        # SC OOB (§2.3.5.6.4): the peer's confirm arrived out of band, not in a
        # Pairing Confirm PDU. Verify its in-band public key against the OOB
        # confirm, then skip the Confirm PDU and send our Random (Na) directly.
        if not _sc_oob_verify_peer_confirm(ctx):
            await _on_failed(ctx, reason=0x04)
            return
        import os
        from pybluehost.ble.smp import SMPPairingRandom
        ctx.local_random = os.urandom(16)
        ctx.state_machine._state = SMPState.CONFIRMING
        await ctx.send(SMPPairingRandom(random_value=ctx.local_random).to_bytes())
        return

    if _association_model(ctx) == "passkey_entry":
        if _passkey_local_role(ctx) == "display":
            await _sc_passkey_initiator_display_enter(ctx)
        else:
            ctx.state_machine._state = SMPState.PASSKEY_INPUT_PENDING
            await _passkey_await_user_input(ctx)


async def _sc_responder_recv_peer_public_key(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Responder: Initiator's Public Key arrived.

    All paths: store peer pubkey, generate own keypair, send own pubkey, compute DHKey.
    For Just Works / NC: also generate Nb + Cb = f4(PKbx, PKax, Nb, 0) and send Pairing_Confirm.
    For SC Passkey Display: enter PASSKEY_SC_ROUND (no Cb send).
    For SC Passkey Input: enter PASSKEY_INPUT_PENDING (no Cb send).
    """
    import os
    from pybluehost.ble._smp_sc_crypto import (
        compute_dhkey,
        generate_p256_keypair,
        peer_public_key_valid,
    )
    from pybluehost.ble.smp import SMPPairingConfirm, SMPPairingPublicKey

    ctx.peer_public_key = pdu.public_key_x + pdu.public_key_y
    # SM/*/KDU/BI-04: reject an invalid (off-curve) peer public key with DHKey
    # Check Failed instead of computing a DHKey from it / crashing the handler.
    if not peer_public_key_valid(ctx.peer_public_key):
        await _on_failed(ctx, reason=0x0B)  # DHKey Check Failed
        return
    # SC OOB: reuse the keypair our OOB confirm commits to (else the confirm PTS
    # holds would not match the public key we send over the air).
    if getattr(ctx, "oob_sc_keypair", None):
        priv, pub = ctx.oob_sc_keypair
    else:
        priv, pub = generate_p256_keypair()
    ctx.local_private_key = priv
    ctx.local_public_key = pub
    await ctx.send(SMPPairingPublicKey(
        public_key_x=pub[:32], public_key_y=pub[32:],
    ).to_bytes())
    ctx.dhkey = compute_dhkey(priv, ctx.peer_public_key)

    model = _association_model(ctx)
    if model == "oob":
        # SC OOB (§2.3.5.6.4): verify the initiator's in-band public key against
        # its OOB confirm, then DON'T send a Pairing Confirm — just generate Nb
        # and await the initiator's Random (the transition left us in
        # CONFIRMING, whose PAIRING_RANDOM_RX edge advances to RANDOM_EXCHANGE).
        if not _sc_oob_verify_peer_confirm(ctx):
            ctx.state_machine._state = SMPState.FAILED
            await _on_failed(ctx, reason=0x04)
            return
        ctx.local_random = os.urandom(16)
        return
    if model == "passkey_entry":
        if _passkey_local_role(ctx) == "display":
            await _sc_passkey_responder_display_enter(ctx)
        else:
            ctx.state_machine._state = SMPState.PASSKEY_INPUT_PENDING
            await _passkey_await_user_input(ctx)
        return

    # Just Works / NC: generate Nb, send Cb.
    ctx.local_random = os.urandom(16)
    ctx.local_confirm = _sc_f4(ctx.local_public_key[:32], ctx.peer_public_key[:32], ctx.local_random, 0)
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
    a1 = _local_sc_address(ctx)
    a2 = _peer_sc_address(ctx)
    io_cap_a = bytes([int(ctx.local_io_caps), _local_oob_data_flag(ctx), ctx.local_auth_req])
    ea = _sc_f6(ctx.mac_key, ctx.local_random, ctx.peer_random, _sc_f6_r_for_ea(ctx), io_cap_a, a1, a2)
    ctx.local_dhkey_check = ea
    await ctx.send(SMPPairingDHKeyCheck(dhkey_check=ea).to_bytes())
    ctx.state_machine._state = SMPState.DHKEY_CHECK


async def _sc_initiator_recv_peer_random(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Initiator: Responder's Random Nb arrived. Verify Cb, derive f5,
    then branch on association model (NC -> NUMERIC_COMPARE_PENDING, JW -> send Ea)."""
    ctx.peer_random = pdu.random_value
    if _association_model(ctx) != "oob":
        # SC OOB has no over-the-air Confirm to check (it was verified against
        # the OOB data when the peer's public key arrived).
        expected = _sc_f4(ctx.peer_public_key[:32], ctx.local_public_key[:32], ctx.peer_random, 0)
        if expected != ctx.peer_confirm:
            await _on_failed(ctx, reason=0x04)  # CONFIRM_VALUE_FAILED
            return
    # Override state: SC does not use STK; advance to RANDOM_EXCHANGE instead.
    ctx.state_machine._state = SMPState.RANDOM_EXCHANGE
    # Derive (MacKey, LTK_sc) = f5(DHKey, Na, Nb, A1, A2)
    # A1 = Initiator (local) addr; A2 = Responder (peer) addr
    a1 = _local_sc_address(ctx)
    a2 = _peer_sc_address(ctx)
    mac_key, ltk = _sc_f5(ctx.dhkey, ctx.local_random, ctx.peer_random, a1, a2)
    ctx.mac_key = mac_key
    ctx.ltk_sc = _reduce_key(ltk, _negotiated_key_size(ctx))

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
    a1 = _peer_sc_address(ctx)   # Initiator = peer
    a2 = _local_sc_address(ctx)  # Responder = local
    # Na = peer_random (Initiator's); Nb = local_random (Responder's)
    mac_key, ltk = _sc_f5(ctx.dhkey, ctx.peer_random, ctx.local_random, a1, a2)
    ctx.mac_key = mac_key
    ctx.ltk_sc = _reduce_key(ltk, _negotiated_key_size(ctx))

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
    # Expected Eb = f6(MacKey, Nb, Na, ra, IOcapB, B, A)
    # IOcapB = (IO_Capability || OOB_Flag || Auth_Req) of Responder (peer)
    io_cap_b = bytes([int(ctx.peer_io_caps), ctx.peer_oob_data_flag, ctx.peer_auth_req])
    a1 = _local_sc_address(ctx)  # Initiator = us
    a2 = _peer_sc_address(ctx)   # Responder = peer
    expected_eb = _sc_f6(ctx.mac_key, ctx.peer_random, ctx.local_random, _sc_f6_r_for_eb(ctx), io_cap_b, a2, a1)
    if expected_eb != ctx.peer_dhkey_check:
        ctx.state_machine._state = SMPState.FAILED  # override the pre-set to_state
        await _on_failed(ctx, reason=0x0B)  # DHKEY_CHECK_FAILED
        return
    # Drive encryption with the f5 LTK directly
    if ctx._hci is None:
        ctx.state_machine._state = SMPState.FAILED
        await _on_failed(ctx, reason=0x08)
        return
    logger.debug(
        "SC initiator DHKey check OK; LE_Start_Encryption handle=0x%04X ltk_sc=%s",
        ctx.connection_handle, getattr(ctx, "ltk_sc", b"").hex(),
    )
    await ctx._hci.send_command(HCI_LE_Start_Encryption_Command(
        connection_handle=ctx.connection_handle,
        random_number=b"\x00" * 8,
        encrypted_diversifier=0,
        long_term_key=ctx.ltk_sc,
    ))
    logger.debug(
        "SC initiator LE_Start_Encryption sent handle=0x%04X; awaiting Encryption_Change",
        ctx.connection_handle,
    )


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
    # IOcap = IO_Capability || OOB_Flag || Auth_Req (from the Pairing Request/
    # Response — the middle byte is the OOB data flag, 1 for OOB pairing).
    io_cap_a = bytes([int(ctx.peer_io_caps), ctx.peer_oob_data_flag, ctx.peer_auth_req])
    io_cap_b = bytes([int(ctx.local_io_caps), _local_oob_data_flag(ctx), ctx.local_auth_req])
    a1 = _peer_sc_address(ctx)   # Initiator = peer
    a2 = _local_sc_address(ctx)  # Responder = us
    # Verify Ea = f6(MacKey, Na, Nb, ra=0, IOcapA, A, B)
    # Na = peer_random; Nb = local_random
    expected_ea = _sc_f6(ctx.mac_key, ctx.peer_random, ctx.local_random, _sc_f6_r_for_ea(ctx), io_cap_a, a1, a2)
    if expected_ea != ctx.peer_dhkey_check:
        ctx.state_machine._state = SMPState.FAILED  # override the pre-set to_state
        await _on_failed(ctx, reason=0x0B)  # DHKEY_CHECK_FAILED
        return
    # Compute and send Eb = f6(MacKey, Nb, Na, rb=0, IOcapB, B, A)
    eb = _sc_f6(ctx.mac_key, ctx.local_random, ctx.peer_random, _sc_f6_r_for_eb(ctx), io_cap_b, a2, a1)
    ctx.local_dhkey_check = eb
    await ctx.send(SMPPairingDHKeyCheck(dhkey_check=eb).to_bytes())


def _local_key_distribution_mask(ctx: "SMPPairingContext") -> int:
    """Keys this device should distribute after Phase 1 negotiation."""
    if ctx.role == PairingRole.INITIATOR:
        return ctx.local_init_key_dist & ctx.peer_init_key_dist
    return ctx.local_resp_key_dist & ctx.peer_resp_key_dist


def _peer_key_distribution_mask(ctx: "SMPPairingContext") -> int:
    """Keys the peer should distribute after Phase 1 negotiation."""
    if ctx.role == PairingRole.INITIATOR:
        return ctx.local_resp_key_dist & ctx.peer_resp_key_dist
    return ctx.local_init_key_dist & ctx.peer_init_key_dist


async def _start_phase3(ctx: "SMPPairingContext", **_kw) -> None:
    """Phase 3 entry: distribute our keys per the negotiated mask, then await peer keys."""
    from pybluehost.ble.smp import (
        SMPEncryptionInformation, SMPIdentityAddressInformation,
        SMPIdentityInformation, SMPMasterIdentification, SMPSigningInformation,
    )
    logger.debug("entered KEY_DISTRIBUTION on handle=0x%04X", ctx.connection_handle)
    mask = _local_key_distribution_mask(ctx)
    sc_mode = _sc_negotiated(ctx)

    if mask & 0x01 and not sc_mode:  # EncKey: LTK + EDIV + RAND (Legacy only; SC derives LTK via f5)
        ltk = _reduce_key(os.urandom(16), _negotiated_key_size(ctx))
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
        # Use the stack's stable local IRK (not a fresh random): the peer must
        # be able to resolve the RPAs we advertise later with the same key
        # (GAP/BROB/BCST/BV-03, GAP/PRIV/CONN).
        mgr = getattr(ctx, "_smp_manager", None)
        irk = mgr.local_irk if mgr is not None else os.urandom(16)
        await ctx.send(SMPIdentityInformation(irk=irk).to_bytes())
        # Phase 2 hashes the link's on-air address, which can be an RPA.
        # IdKey must distribute the stable public/static identity instead:
        # controllers reject an RPA as a resolving-list identity (status 0x12).
        local_addr = (
            ctx.local_identity_address or ctx.local_address or BDAddress(b"\x00" * 6)
        )
        local_addr_bytes = local_addr.to_hci() if hasattr(local_addr, "to_hci") else bytes(local_addr)
        local_addr_type = int(getattr(local_addr, "type", AddressType.PUBLIC)) & 0x01
        await ctx.send(SMPIdentityAddressInformation(
            addr_type=local_addr_type, bd_addr=local_addr_bytes,
        ).to_bytes())
    if mask & 0x04:  # Sign: CSRK
        csrk = os.urandom(16)
        await ctx.send(SMPSigningInformation(signature_key=csrk).to_bytes())

    while (
        ctx.pending_phase3_pdus
        and ctx.state_machine.state == SMPState.KEY_DISTRIBUTION
    ):
        event, pdu = ctx.pending_phase3_pdus.pop(0)
        await ctx.state_machine.fire(event, pdu=pdu)

    if ctx.state_machine.state != SMPState.KEY_DISTRIBUTION:
        return

    # If we expect no keys from peer, finalize immediately.
    # In SC mode, strip out the EncKey bit (0x01) since we will never receive a peer LTK.
    expected = _peer_key_distribution_mask(ctx)
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
    expected = _peer_key_distribution_mask(ctx)
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
    identity_type, identity_addr = ctx.received_identity_address
    if len(identity_addr) == 6 and any(identity_addr):
        bond_peer_address = BDAddress.from_hci(identity_addr, type=AddressType(identity_type))
    else:
        bond_peer_address = ctx.peer_address
    bond_address_type = int(getattr(bond_peer_address, "type", identity_type))
    # Core Vol 3 Part H §2.3.4: the keys are stored when either side asked for
    # bonding (Bonding_Flags = 0x01 in the Pairing Request or Response).  With
    # both flags clear the keys only serve this connection — storing them would
    # make a later reconnect look bonded and, among other things, keep the GATT
    # CCCD that a non-bonded client must have reset by then (GATT/SR/GAN/
    # BV-01-C pairs with Bonding_Flags = 0 and checks exactly that).
    bonding = bool(
        (int(getattr(ctx, "local_auth_req", 0)) | int(getattr(ctx, "peer_auth_req", 0))) & 0x01
    )
    if storage is None:
        logger.debug("no bond storage configured; not persisting bond")
    elif not bonding:
        logger.debug(
            "pairing without bonding (local_auth_req=0x%02X peer_auth_req=0x%02X); "
            "keys not persisted",
            int(getattr(ctx, "local_auth_req", 0)),
            int(getattr(ctx, "peer_auth_req", 0)),
        )
    else:
        if sc_mode:
            # SC: both sides share the f5-derived LTK; EDIV/RAND are unused in SC.
            # NC, Passkey Entry and OOB provide MITM authentication; JW does not.
            authenticated = _association_model(ctx) in {"numeric_comparison", "passkey_entry", "oob"}
            bond = BondInfo(
                peer_address=bond_peer_address,
                address_type=bond_address_type,
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
            # Sub-Plan 3b-1: Passkey provides MITM authentication; Just Works does not.
            authenticated = _association_model(ctx) == "passkey_entry"
            bond = BondInfo(
                peer_address=bond_peer_address,
                address_type=bond_address_type,
                ltk=ltk_for_bond,
                irk=ctx.received_irk if ctx.received_irk else None,
                csrk=ctx.received_csrk if ctx.received_csrk else None,
                ediv=ediv_for_bond,
                rand=rand_for_bond,
                key_size=16,
                authenticated=authenticated,
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
    """Return 'oob' | 'numeric_comparison' | 'passkey_entry' | 'just_works'.

    SC: OOB when either side provisioned Secure Connections OOB data (it
    outranks every IO-capability-derived model — Core §2.3.5.6.4); otherwise NC
    for both-DYN/KbD; SC Passkey for remaining MITM-qualifying pairs; else JW.
    Legacy (Sub-Plan 3b-1): Passkey Entry for MITM-qualifying pairs; otherwise JW.
    """
    from pybluehost.core.types import IOCapability

    both_mitm = bool(ctx.local_auth_req & 0x04) and bool(ctx.peer_auth_req & 0x04)

    if _sc_negotiated(ctx):
        if _sc_oob_present(ctx):
            return "oob"
        if not both_mitm:
            return "just_works"
        nc_caps = {int(IOCapability.DISPLAY_YES_NO), int(IOCapability.KEYBOARD_DISPLAY)}
        if int(ctx.local_io_caps) in nc_caps and int(ctx.peer_io_caps) in nc_caps:
            return "numeric_comparison"
        # Sub-Plan 3b-2: SC Passkey for remaining MITM-qualifying pairs
        if _passkey_capable(int(ctx.local_io_caps), int(ctx.peer_io_caps)):
            return "passkey_entry"
        return "just_works"

    # Legacy path — Sub-Plan 3b-1
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

    g2_value = _sc_g2(pkax, pkbx, na, nb)
    numeric_value = g2_value % 1_000_000

    delegate = getattr(ctx, "_delegate", None) or AutoAcceptDelegate()

    # Numeric Comparison is a *display* on our side: the 6-digit value has to
    # reach the Upper Tester, and auto-pts reads it out of the same
    # PASSKEY_DISPLAY event legacy passkey entry uses. Emitting only
    # ``confirm_numeric`` (a local UI callback) left PTS's WID waiting for a
    # value that never came, and the case hung with no verdict at all
    # (GAP/SEC/SEM/BV-57/63/64/67 — all configure io_cap=KeyboardDisplay via
    # WID 241, so both sides are KeyboardDisplay and SC picks Numeric
    # Comparison).
    try:
        await delegate.display_passkey(ctx.peer_address, numeric_value)
    except Exception as exc:  # noqa: BLE001
        logger.warning("delegate.display_passkey (NC) raised: %s; continuing", exc)

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


async def _passkey_resolve_display_value(ctx: "SMPPairingContext") -> int:
    """Return the 6-digit passkey the Display side should present.

    If the delegate exposes a ``passkey: int`` attribute (e.g. a scripted /
    test fixture), that value is used; otherwise a fresh random 6-digit value
    is drawn. The delegate's ``get_passkey()`` is intentionally NOT consulted
    here — that method belongs to the Input role and may return 0 (e.g.
    AutoAcceptDelegate's default) which is unsuitable as a fresh display
    challenge.
    """
    delegate = getattr(ctx, "_delegate", None)
    if delegate is not None:
        preset = getattr(delegate, "passkey", None)
        if isinstance(preset, int) and 0 <= preset <= 999_999:
            return preset
    return secrets.randbelow(1_000_000)


async def _passkey_await_user_input(ctx: "SMPPairingContext") -> None:
    """Input-role helper: spawn delegate.get_passkey task, fire user-entered or rejected.

    Mirrors _sc_compute_and_await_nc from Sub-Plan 3a. The function returns
    immediately; the spawned task fires PASSKEY_USER_ENTERED or
    PASSKEY_USER_REJECTED when the user finishes (or cancels).
    """
    from pybluehost.ble.smp import AutoAcceptDelegate, SMPEvent

    delegate = getattr(ctx, "_delegate", None) or AutoAcceptDelegate()

    async def _await() -> None:
        try:
            value = await delegate.get_passkey(ctx.peer_address)
        except AttributeError:
            value = 0  # backward-compat: delegate without get_passkey → auto-accept zero
        except Exception as exc:  # noqa: BLE001
            logger.warning("delegate.get_passkey raised: %s; rejecting passkey", exc)
            await ctx.state_machine.fire(SMPEvent.PASSKEY_USER_REJECTED)
            return
        if not isinstance(value, int) or not (0 <= value <= 999_999):
            await ctx.state_machine.fire(SMPEvent.PASSKEY_USER_REJECTED)
            return
        ctx.passkey = value
        await ctx.state_machine.fire(SMPEvent.PASSKEY_USER_ENTERED)

    asyncio.create_task(_await())


async def _sc_passkey_send_round_confirm(ctx: "SMPPairingContext") -> None:
    """Initiator-only round helper: generate Na_i, compute Ca_i = f4(PKax, PKbx, Na_i, 0x80|bit_i), send.

    Round i (1..20) uses bit (i - 1) of ctx.passkey — i=1 is the LSB (bit 0),
    matching zephyr's `r = (passkey >> passkey_round) & 1` with passkey_round 0-based.
    """
    from pybluehost.ble.smp import SMPPairingConfirm
    i = ctx.passkey_round
    bit = (ctx.passkey >> (i - 1)) & 1
    ctx.passkey_local_random = os.urandom(16)
    ctx.passkey_local_confirm = _sc_f4(
        ctx.local_public_key[:32], ctx.peer_public_key[:32], ctx.passkey_local_random, 0x80 | bit,
    )
    await ctx.send(SMPPairingConfirm(confirm_value=ctx.passkey_local_confirm).to_bytes())


async def _sc_passkey_recv_peer_confirm(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Passkey reflexive transition: PAIRING_CONFIRM_RX while in PASSKEY_SC_ROUND.

    Initiator: stash peer_confirm, send Pairing_Random with Na_i (generated earlier).
    Responder: stash peer_confirm, compute Cb_i = f4(PKbx, PKax, Nb_i, 0x80|bit_i), send.
    Either way, advance subphase to AWAIT_PEER_RANDOM.
    """
    from pybluehost.ble.smp import PairingRole, SMPPairingConfirm, SMPPairingRandom
    if ctx.passkey_round_phase != "AWAIT_PEER_CONFIRM":
        await _on_failed(ctx, reason=0x08)
        return
    ctx.passkey_peer_confirm = pdu.confirm_value
    if ctx.role == PairingRole.INITIATOR:
        # Initiator already has Na_i from _sc_passkey_send_round_confirm; reveal it now.
        await ctx.send(SMPPairingRandom(random_value=ctx.passkey_local_random).to_bytes())
    else:
        # Responder: compute Cb_i with own Nb_i.
        i = ctx.passkey_round
        bit = (ctx.passkey >> (i - 1)) & 1
        ctx.passkey_local_random = os.urandom(16)
        ctx.passkey_local_confirm = _sc_f4(
            ctx.local_public_key[:32], ctx.peer_public_key[:32], ctx.passkey_local_random, 0x80 | bit,
        )
        await ctx.send(SMPPairingConfirm(confirm_value=ctx.passkey_local_confirm).to_bytes())
    ctx.passkey_round_phase = "AWAIT_PEER_RANDOM"


async def _sc_passkey_recv_peer_random(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Passkey reflexive transition: PAIRING_RANDOM_RX while in PASSKEY_SC_ROUND.

    Verify peer's Confirm matches f4 over their just-revealed Random and the
    current bit. On match, advance round or exit; on mismatch, FAILED(0x04).
    Wrong subphase -> FAILED(0x08).
    """
    from pybluehost.ble.smp import PairingRole, SMPPairingRandom
    if ctx.passkey_round_phase != "AWAIT_PEER_RANDOM":
        await _on_failed(ctx, reason=0x08)
        return
    ctx.passkey_peer_random = pdu.random_value
    i = ctx.passkey_round
    bit = (ctx.passkey >> (i - 1)) & 1

    if ctx.role == PairingRole.INITIATOR:
        # Verify Cb_i = f4(PKbx, PKax, Nb_i, 0x80|bit).
        expected = _sc_f4(
            ctx.peer_public_key[:32], ctx.local_public_key[:32], ctx.passkey_peer_random, 0x80 | bit,
        )
        if expected != ctx.passkey_peer_confirm:
            await _on_failed(ctx, reason=0x04)
            return
        if i < 20:
            ctx.passkey_round = i + 1
            ctx.passkey_round_phase = "AWAIT_PEER_CONFIRM"
            await _sc_passkey_send_round_confirm(ctx)
        else:
            ctx.local_random = ctx.passkey_local_random   # Na_20
            ctx.peer_random = ctx.passkey_peer_random     # Nb_20
            await _sc_passkey_exit_to_dhkey_check_initiator(ctx)
    else:
        # Responder: verify Ca_i = f4(PKax, PKbx, Na_i, 0x80|bit), then send Nb_i.
        expected = _sc_f4(
            ctx.peer_public_key[:32], ctx.local_public_key[:32], ctx.passkey_peer_random, 0x80 | bit,
        )
        if expected != ctx.passkey_peer_confirm:
            await _on_failed(ctx, reason=0x04)
            return
        await ctx.send(SMPPairingRandom(random_value=ctx.passkey_local_random).to_bytes())
        if i < 20:
            ctx.passkey_round = i + 1
            ctx.passkey_round_phase = "AWAIT_PEER_CONFIRM"
        else:
            ctx.peer_random = ctx.passkey_peer_random     # Na_20
            ctx.local_random = ctx.passkey_local_random   # Nb_20
            await _sc_passkey_exit_to_random_exchange_responder(ctx)


async def _sc_passkey_exit_to_dhkey_check_initiator(ctx: "SMPPairingContext") -> None:
    """Initiator exit after round 20: derive f5, call existing _sc_send_dhkey_check_initiator.

    _sc_send_dhkey_check_initiator (Sub-Plan 2) sends Ea and sets state to DHKEY_CHECK.
    """
    a1 = _local_sc_address(ctx)
    a2 = _peer_sc_address(ctx)
    mac_key, ltk = _sc_f5(ctx.dhkey, ctx.local_random, ctx.peer_random, a1, a2)
    ctx.mac_key = mac_key
    ctx.ltk_sc = _reduce_key(ltk, _negotiated_key_size(ctx))
    await _sc_send_dhkey_check_initiator(ctx)


async def _sc_passkey_exit_to_random_exchange_responder(ctx: "SMPPairingContext") -> None:
    """Responder exit after round 20: derive f5, state -> RANDOM_EXCHANGE.

    The existing RANDOM_EXCHANGE + PAIRING_DHKEY_CHECK_RX transition handles
    Initiator's incoming Ea. No PDU sent here.
    """
    a1 = _peer_sc_address(ctx)   # Initiator = peer
    a2 = _local_sc_address(ctx)  # Responder = local
    mac_key, ltk = _sc_f5(ctx.dhkey, ctx.peer_random, ctx.local_random, a1, a2)
    ctx.mac_key = mac_key
    ctx.ltk_sc = _reduce_key(ltk, _negotiated_key_size(ctx))
    ctx.state_machine._state = SMPState.RANDOM_EXCHANGE


async def _passkey_buffer_peer_confirm(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """Input-side helper: stash peer's Pairing_Confirm while we wait on the user.

    Once PASSKEY_USER_ENTERED fires, the existing Phase-2 flow validates this
    buffered value against the recomputed c1 once both randoms are exchanged.
    """
    ctx.peer_confirm = pdu.confirm_value


async def _passkey_user_entered(ctx: "SMPPairingContext", **_kw) -> None:
    """Input-side helper: user entered passkey → next phase.

    SC (Sub-Plan 3b-2): state -> PASSKEY_SC_ROUND, round=1; Initiator sends Ca_1.
    Legacy (Sub-Plan 3b-1): set TK, compute c1, send Pairing_Confirm, stay in CONFIRMING.

    For Legacy Initiator Input: peer Confirm has NOT yet arrived; we send first.
    For Legacy Responder Input: peer Confirm may already be in ctx.peer_confirm
      (buffered); we still just send our own Confirm — c1 verification of the
      peer's value happens later in _responder_recv_peer_random against
      ctx.peer_confirm.
    """
    from pybluehost.ble.smp import PairingRole, SMPPairingConfirm
    if _sc_negotiated(ctx):
        ctx.state_machine._state = SMPState.PASSKEY_SC_ROUND
        ctx.passkey_round = 1
        ctx.passkey_round_phase = "AWAIT_PEER_CONFIRM"
        if ctx.role == PairingRole.INITIATOR:
            await _sc_passkey_send_round_confirm(ctx)
        return
    # Legacy path — unchanged from Sub-Plan 3b-1
    ctx.tk = ctx.passkey.to_bytes(16, "little")
    ctx.local_random = os.urandom(16)
    preq, pres, iat, rat, ia, ra = _build_c1_params(ctx)
    ctx.local_confirm = SMPCrypto.c1(
        ctx.tk, ctx.local_random, preq, pres, iat, rat, ia, ra,
    )
    await ctx.send(SMPPairingConfirm(confirm_value=ctx.local_confirm).to_bytes())


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
    if ctx.role == PairingRole.INITIATOR:
        ia = _c1_address_bytes(ctx.local_address)
        ra = _c1_address_bytes(ctx.peer_address)
        iat = _local_address_type(ctx)
        rat = _peer_address_type(ctx)
    else:
        ia = _c1_address_bytes(ctx.peer_address)   # peer is Initiator
        ra = _c1_address_bytes(ctx.local_address)  # local is Responder
        iat = _peer_address_type(ctx)
        rat = _local_address_type(ctx)
    return preq, pres, iat, rat, ia, ra


def _c1_address_bytes(addr: object | None) -> bytes:
    """Address in big-endian (display) order for the legacy c1 confirm.

    Validated against a real Android↔CSR8510 capture
    (``test_c1_matches_android_legacy_confirm_capture``): the legacy c1 p2 block
    takes the 6-octet address MSB-first, which is ``BDAddress.address`` — NOT
    ``to_hci()`` (that is the little-endian wire form used elsewhere). Feeding
    the wire form here makes PTS reject the confirm value (Pairing Failed,
    reason 0x04) at the random-exchange step.
    """
    if addr is None:
        return b"\x00" * 6
    if hasattr(addr, "address"):
        return bytes(addr.address)
    to_hci = getattr(addr, "to_hci", None)
    if callable(to_hci):
        return bytes(to_hci())[::-1]
    raw = getattr(addr, "bytes", None)
    if raw is not None:
        return bytes(raw)
    return bytes(addr)


def _c1_address_type(addr: object | None) -> int:
    if addr is None or not hasattr(addr, "type"):
        return 0
    return int(addr.type) & 0x01


def _local_address_type(ctx: "SMPPairingContext") -> int:
    return _c1_address_type(ctx.local_address)


def _peer_address_type(ctx: "SMPPairingContext") -> int:
    return _c1_address_type(ctx.peer_address)


def _local_address_bytes(ctx: "SMPPairingContext") -> bytes:
    if ctx.local_address is None:
        return b"\x00" * 6
    addr = ctx.local_address
    if hasattr(addr, "to_hci"):
        return addr.to_hci()
    if hasattr(addr, "address"):
        return bytes(addr.address)
    return bytes(addr)


def _peer_address_bytes(ctx: "SMPPairingContext") -> bytes:
    addr = ctx.peer_address
    if hasattr(addr, "to_hci"):
        return addr.to_hci()
    if hasattr(addr, "address"):
        return bytes(addr.address)
    return bytes(addr)


def _address_canonical_bytes(addr) -> bytes:
    if addr is None:
        return b"\x00" * 6
    if hasattr(addr, "address"):
        return bytes(addr.address)
    if hasattr(addr, "to_hci"):
        return addr.to_hci()[::-1]
    return bytes(addr)


def _local_sc_address(ctx: "SMPPairingContext") -> bytes:
    return _local_address_bytes(ctx) + bytes([_address_type_value(ctx.local_address)])


def _peer_sc_address(ctx: "SMPPairingContext") -> bytes:
    return _peer_address_bytes(ctx) + bytes([_address_type_value(ctx.peer_address)])


def _address_type_value(addr) -> int:
    if addr is None:
        return 0x00
    addr_type = getattr(addr, "type", None)
    if addr_type is None:
        return 0x00
    return int(addr_type)


def _sc_aes_cmac(key: bytes, message: bytes) -> bytes:
    """AES-CMAC for SMP SC little-endian byte arrays."""
    return _aes_cmac(key[::-1], message[::-1])[::-1]


def _sc_f4(u: bytes, v: bytes, x: bytes, z: int) -> bytes:
    return _sc_aes_cmac(x, bytes([z]) + v + u)


def _sc_f5(w: bytes, n1: bytes, n2: bytes, a1: bytes, a2: bytes) -> tuple[bytes, bytes]:
    salt = bytes.fromhex("be83605adb0b376038a5f5aa9183886c")
    key_id = b"eltb"
    length = b"\x00\x01"
    t = _sc_aes_cmac(salt, w)
    message = length + a2 + a1 + n2 + n1 + key_id
    return _sc_aes_cmac(t, message + b"\x00"), _sc_aes_cmac(t, message + b"\x01")


def _sc_f6(w: bytes, n1: bytes, n2: bytes, r: bytes, io_cap: bytes, a1: bytes, a2: bytes) -> bytes:
    return _sc_aes_cmac(w, a2 + a1 + io_cap + r + n2 + n1)


def _sc_oob_verify_peer_confirm(ctx: "SMPPairingContext") -> bool:
    """Verify the peer's over-the-air public key against its OOB confirm (step 5).

    Ca/Cb = f4(PK_peer_x, PK_peer_x, r_peer, 0) commits the peer to the public
    key it sent in band; a mismatch means the in-band key is not the one the
    peer committed to out of band. Applies whenever we hold the peer's OOB
    block (its confirm); skips when we never received it.
    """
    if not getattr(ctx, "oob_sc_remote_conf", b""):
        return True
    peer_x = ctx.peer_public_key[:32]
    expected = _sc_f4(peer_x, peer_x, ctx.oob_sc_remote_rand, 0)
    return expected == ctx.oob_sc_remote_conf


def _sc_f6_r(ctx: "SMPPairingContext") -> bytes:
    """Return the 16-octet ``r`` input for the f6 DHKey check.

    Just Works / Numeric Comparison use r = 0. Passkey Entry uses the shared
    passkey as a 20-bit value little-endian-padded to 16 octets (zephyr:
    ``memcpy(r, &passkey, sizeof(passkey))`` into a zeroed 16-octet buffer).
    """
    if _association_model(ctx) == "passkey_entry":
        return int(ctx.passkey).to_bytes(16, "little")
    return b"\x00" * 16


def _sc_oob_present(ctx: "SMPPairingContext") -> bool:
    """True when SC OOB authentication is in play on either side (§2.3.5.6.4).

    OOB is used if we hold the peer's OOB block (we can authenticate the peer)
    OR the peer advertised OOB data (it can authenticate us).
    """
    return bool(getattr(ctx, "oob_sc_remote_conf", b"")) or bool(
        getattr(ctx, "peer_oob_data_flag", 0))


def _local_oob_data_flag(ctx: "SMPPairingContext") -> int:
    """OOB data flag for our Pairing Request/Response.

    Legacy: 1 when we hold a shared OOB TK (Sub-Plan 3c). Secure Connections:
    the flag means "OOB Authentication data FROM REMOTE DEVICE present" — set
    only when we actually received the peer's OOB block (BTP
    OOB_SC_SET_REMOTE_DATA), NOT merely because we generated our own local
    block. Advertising 1 without the peer's data makes PTS abort Pairing Not
    Supported (0x05).
    """
    if getattr(ctx, "oob_tk", b""):
        return 1
    if getattr(ctx, "oob_sc_remote_conf", b""):
        return 1
    return 0


def _oob_rand_own(ctx: "SMPPairingContext") -> bytes:
    """This device's effective OOB random (r_own) for f6.

    Per §2.3.5.6.4 rule 3, if the peer's Pairing Request/Response OOB data flag
    says "OOB Authentication data not present", our own r is forced to 0 (the
    peer cannot verify our OOB confirm, so OOB gives no authentication in our
    direction). Otherwise it is the random we published via OOB.
    """
    if not getattr(ctx, "oob_sc_local_rand", b""):
        return b"\x00" * 16
    if not getattr(ctx, "peer_oob_data_flag", 0):
        return b"\x00" * 16
    return ctx.oob_sc_local_rand


def _oob_rand_peer(ctx: "SMPPairingContext") -> bytes:
    """The peer's effective OOB random (r_peer) for f6.

    Non-zero only when we actually received the peer's OOB block (BTP
    OOB_SC_SET_REMOTE_DATA); otherwise assumed 0 (§2.3.5.6.4 rule 2).
    """
    if not getattr(ctx, "oob_sc_remote_rand", b""):
        return b"\x00" * 16
    return ctx.oob_sc_remote_rand


def _sc_f6_r_for_ea(ctx: "SMPPairingContext") -> bytes:
    """f6 ``r`` input for the Initiator's DHKey check EA (Figure 2.6 step 10a).

    EA = f6(MacKey, Na, Nb, rb, IOcapA, A, B): r = rb, the RESPONDER's OOB
    random. Passkey Entry uses the shared passkey for both checks; JW/NC use 0.
    """
    model = _association_model(ctx)
    if model == "passkey_entry":
        return int(ctx.passkey).to_bytes(16, "little")
    if model == "oob":
        from pybluehost.ble.smp import PairingRole
        # Responder's OOB random: peer's if we are the initiator, ours if we respond.
        return (_oob_rand_peer(ctx) if ctx.role == PairingRole.INITIATOR
                else _oob_rand_own(ctx))
    return b"\x00" * 16


def _sc_f6_r_for_eb(ctx: "SMPPairingContext") -> bytes:
    """f6 ``r`` input for the Responder's DHKey check EB (Figure 2.6 step 10b).

    EB = f6(MacKey, Nb, Na, ra, IOcapB, B, A): r = ra, the INITIATOR's OOB
    random. Passkey Entry uses the shared passkey for both checks; JW/NC use 0.
    """
    model = _association_model(ctx)
    if model == "passkey_entry":
        return int(ctx.passkey).to_bytes(16, "little")
    if model == "oob":
        from pybluehost.ble.smp import PairingRole
        # Initiator's OOB random: ours if we initiate, peer's if we respond.
        return (_oob_rand_own(ctx) if ctx.role == PairingRole.INITIATOR
                else _oob_rand_peer(ctx))
    return b"\x00" * 16


def _sc_g2(u: bytes, v: bytes, x: bytes, y: bytes) -> int:
    mac = _sc_aes_cmac(x, y + v + u)
    return int.from_bytes(mac[:4], "little")


async def _recv_peer_pairing_failed(ctx: "SMPPairingContext", *, pdu=None, **_kw) -> None:
    """Peer aborted the pairing with a Pairing Failed PDU (SM/*/KDU/BI-02/03).

    Surface the peer's reason to any registered listener (BTP GAP PAIRING_FAILED)
    — a responder has no pair() waiter, so without this the Upper Tester / PTS
    never learns the pairing was rejected — then drive the state machine to FAILED
    without echoing a Pairing Failed back.
    """
    reason = getattr(pdu, "reason", None)
    mgr = getattr(ctx, "_smp_manager", None)
    if mgr is not None and reason is not None:
        mgr._emit_pairing_failed(ctx.connection_handle, reason)
    await _on_failed(ctx, send_failed=False)


async def _bonded_peer_pairing_failed(ctx: "SMPPairingContext", *, pdu=None, **_kw) -> None:
    """Peer aborted a pairing *after* one already completed.

    Different from ``_recv_peer_pairing_failed``: the bond is already persisted,
    so the abort says nothing about it and the state stays BONDED (the link's
    bond is still valid; the next Security Request starts a fresh context). Only
    the reason is passed on to any listener.
    """
    reason = getattr(pdu, "reason", None)
    mgr = getattr(ctx, "_smp_manager", None)
    if mgr is not None and reason is not None:
        mgr._emit_pairing_failed(ctx.connection_handle, reason)
    logger.debug(
        "SMP peer aborted after bonding handle=0x%04X reason=%s",
        ctx.connection_handle, reason,
    )


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
        exc = RuntimeError(f"SMP pairing failed (reason={reason})")
        # The BTP layer reports pair() failures to auto-pts as GAP PAIRING_FAILED;
        # the negative SM cases are judged on that reason (WID 175 = Confirm Value
        # Failed, EKS = Encryption Key Size), so carry it on the exception.
        exc.reason = reason
        ctx.pairing_complete.set_exception(exc)
