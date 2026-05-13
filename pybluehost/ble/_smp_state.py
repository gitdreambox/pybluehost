"""SMP state machine transitions + action callbacks (Sub-Plan 1).

Phase 1 — Feature Exchange:
    Initiator path:
        IDLE  --(LOCAL_PAIR_REQUEST)--> FEATURE_EXCHANGE  [send PairingRequest]
        FEATURE_EXCHANGE --(PAIRING_RSP_RX)--> CONFIRMING [compute+send local Confirm]
    Responder path:
        IDLE  --(PAIRING_REQ_RX)--> CONFIRMING            [send PairingResponse; wait for Confirm]

Phase 2 & 3 transitions land in later tasks. Universal failure transitions
(PAIRING_FAILED_RX / TIMEOUT / DISCONNECTED → FAILED) are registered for all
states Phase 1 can reach.
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
# Helpers
# ---------------------------------------------------------------------------

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
