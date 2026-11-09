"""SMP terminal states must absorb late events (GAP/SEC/AUT/BV-13).

A finished pairing is terminal for *that* pairing: a later Security Request drops
the context and starts a fresh one (SMPManager.on_pdu), so BONDED/FAILED only
ever see stragglers. PTS sends them routinely — a Lower Tester that already got
what it needed winds the case down by sending Pairing Failed after the bond was
persisted — and raising InvalidTransitionError on them buries real failures in
state-machine noise.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pybluehost.ble._smp_state import register_transitions
from pybluehost.ble.smp import (
    PairingRole, SMPEvent, SMPPairingFailed, SMPState,
)
from pybluehost.core.errors import InvalidTransitionError
from pybluehost.core.statemachine import StateMachine

HANDLE = 0x0800


def _bonded_ctx(state: SMPState):
    """A context already sitting in `state`, with the transitions registered."""
    ctx = SimpleNamespace(
        role=PairingRole.RESPONDER,
        connection_handle=HANDLE,
        state_machine=StateMachine("SMP", state),
        _smp_manager=None,
        pairing_complete=None,
        send=None,
    )
    register_transitions(ctx)
    return ctx


@pytest.mark.asyncio
async def test_bonded_absorbs_a_late_pairing_failed():
    ctx = _bonded_ctx(SMPState.BONDED)
    await ctx.state_machine.fire(
        SMPEvent.PAIRING_FAILED_RX, pdu=SMPPairingFailed(reason=0x08))
    # The bond stays valid — the abort is about a pairing, not about the bond.
    assert ctx.state_machine.state is SMPState.BONDED


@pytest.mark.asyncio
async def test_bonded_absorbs_disconnect_and_timeout():
    for event in (SMPEvent.DISCONNECTED, SMPEvent.TIMEOUT):
        ctx = _bonded_ctx(SMPState.BONDED)
        await ctx.state_machine.fire(event)
        assert ctx.state_machine.state is SMPState.BONDED


@pytest.mark.asyncio
async def test_bonded_late_failure_still_reaches_the_upper_tester():
    """Absorbing the event must not swallow the reason — auto-pts waits on the
    PAIRING_FAILED BTP event (stack.gap.pairing_failed_rcvd)."""
    seen: list[tuple[int, int]] = []
    ctx = _bonded_ctx(SMPState.BONDED)
    ctx._smp_manager = SimpleNamespace(
        _emit_pairing_failed=lambda h, reason: seen.append((h, reason)))

    await ctx.state_machine.fire(
        SMPEvent.PAIRING_FAILED_RX, pdu=SMPPairingFailed(reason=0x0F))

    assert seen == [(HANDLE, 0x0F)]


@pytest.mark.asyncio
async def test_failed_absorbs_a_repeat_pairing_failed():
    ctx = _bonded_ctx(SMPState.FAILED)
    await ctx.state_machine.fire(
        SMPEvent.PAIRING_FAILED_RX, pdu=SMPPairingFailed(reason=0x08))
    assert ctx.state_machine.state is SMPState.FAILED


@pytest.mark.asyncio
async def test_active_states_still_treat_pairing_failed_as_a_failure():
    """Regression guard: the new self-transitions must not have leaked into the
    states where a Pairing Failed really is the end of the pairing."""
    ctx = _bonded_ctx(SMPState.CONFIRMING)
    await ctx.state_machine.fire(
        SMPEvent.PAIRING_FAILED_RX, pdu=SMPPairingFailed(reason=0x04))
    assert ctx.state_machine.state is SMPState.FAILED


@pytest.mark.asyncio
async def test_unregistered_event_still_raises():
    """The guards must be specific: an event with no rule still surfaces."""
    ctx = _bonded_ctx(SMPState.BONDED)
    with pytest.raises(InvalidTransitionError):
        await ctx.state_machine.fire(SMPEvent.PAIRING_RSP_RX)
