"""SMP state machine transitions + action callbacks (Sub-Plan 1).

Phase 1 — Feature Exchange:
    Initiator path:
        IDLE  --(LOCAL_PAIR_REQUEST)--> FEATURE_EXCHANGE  [send PairingRequest]
        FEATURE_EXCHANGE --(PAIRING_RSP_RX)--> CONFIRMING [compute+send local Confirm]
    Responder path:
        IDLE  --(PAIRING_REQ_RX)--> CONFIRMING            [send PairingResponse; wait for Confirm]

Phase 2 — Confirm/Random/STK:
    Initiator path:
        CONFIRMING --(PAIRING_CONFIRM_RX)--> CONFIRMING   [store peer Confirm, send local Random]
        CONFIRMING --(PAIRING_RANDOM_RX)--> STK_ENCRYPTING
            [verify peer Confirm, derive STK, send HCI_LE_Start_Encryption]
    Responder path:
        CONFIRMING --(PAIRING_CONFIRM_RX)--> CONFIRMING   [gen Srand, compute+send own Confirm]
        CONFIRMING --(PAIRING_RANDOM_RX)--> RANDOM_EXCHANGE
            [verify peer Confirm, send own Random, derive STK]

Phase 3 transitions land in Task 7. Universal failure transitions
(PAIRING_FAILED_RX / TIMEOUT / DISCONNECTED → FAILED) are registered for all
states Phases 1–2 can reach.
"""
from __future__ import annotations

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
)

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

    # ---- Phase 2 — Confirm/Random ----
    if ctx.role == PairingRole.INITIATOR:
        # Initiator already sent its Confirm in Phase 1 transition.
        # Now waits to receive peer Confirm, then peer Random.
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

    # Encryption-change advancement (both roles use the same target state)
    sm.add_transition(
        SMPState.STK_ENCRYPTING, SMPEvent.ENCRYPTION_CHANGE_SUCCESS,
        SMPState.KEY_DISTRIBUTION,
        action=lambda **kw: _start_phase3_placeholder(ctx, **kw),
    )
    sm.add_transition(
        SMPState.RANDOM_EXCHANGE, SMPEvent.ENCRYPTION_CHANGE_SUCCESS,
        SMPState.KEY_DISTRIBUTION,
        action=lambda **kw: _start_phase3_placeholder(ctx, **kw),
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

    # Phase-2 timeouts
    sm.set_timeout(SMPState.RANDOM_EXCHANGE, 30.0, SMPEvent.TIMEOUT)
    sm.set_timeout(SMPState.STK_ENCRYPTING, 30.0, SMPEvent.TIMEOUT)

    # Universal failure transitions
    for state in (
        SMPState.IDLE, SMPState.FEATURE_EXCHANGE, SMPState.CONFIRMING,
        SMPState.RANDOM_EXCHANGE, SMPState.STK_ENCRYPTING, SMPState.KEY_DISTRIBUTION,
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
    for state in (SMPState.FEATURE_EXCHANGE, SMPState.CONFIRMING):
        sm.set_timeout(state, 30.0, SMPEvent.TIMEOUT)


# ---------------------------------------------------------------------------
# Phase 1 actions
# ---------------------------------------------------------------------------

async def _initiator_send_pairing_request(ctx: "SMPPairingContext", **_kw) -> None:
    req = SMPPairingRequest(
        io_capability=ctx.local_io_caps,
        oob_data_flag=0,
        auth_req=0x01 if ctx.bondable else 0,
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
    # Just Works → tk = 0
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
    rsp = SMPPairingResponse(
        io_capability=ctx.local_io_caps,
        oob_data_flag=0,
        auth_req=0x01 if ctx.bondable else 0,
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
    """Initiator: peer (Responder) Random arrived. Verify Confirm, derive STK, start encryption."""
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
    """Responder: peer (Initiator) Random arrived. Verify peer Confirm, send own Random."""
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


async def _start_phase3_placeholder(ctx: "SMPPairingContext", **_kw) -> None:
    """Placeholder for Phase 3 entry (filled in by Task 7).

    For Task 6 we just log; Phase 3 key distribution + bonding lands later.
    """
    logger.debug("entered KEY_DISTRIBUTION on handle=0x%04X (Phase 3 lands in Task 7)",
                 ctx.connection_handle)


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
