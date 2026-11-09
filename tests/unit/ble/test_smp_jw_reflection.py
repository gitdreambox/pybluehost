"""Just Works reflection check (SM/CEN/JW/BI-06-C).

During Legacy Just Works phase 2 the Responder must not echo the Initiator's
own confirm value back (LP_CONFIRM_R == LP_CONFIRM_I is a reflection attack).
The IUT (initiator) must abort with "Confirm Value Failed" instead of moving on
to the Random exchange.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from pybluehost.ble import _smp_state as state_mod
from pybluehost.ble.smp import SMPCode, SMPState

HANDLE = 0x0800


def _ctx(local_confirm: bytes):
    sent: list[bytes] = []

    async def _send(data: bytes) -> None:
        sent.append(data)

    class _SM:
        _state = SMPState.CONFIRMING

        async def fire(self, _ev):
            pass

    ctx = SimpleNamespace(
        connection_handle=HANDLE,
        local_confirm=local_confirm,
        local_random=b"\x11" * 16,
        peer_confirm=None,
        send=_send,
        pairing_complete=asyncio.get_event_loop().create_future(),
        state_machine=_SM(),
    )
    return ctx, sent


class _Pdu:
    def __init__(self, confirm: bytes):
        self.confirm_value = confirm


@pytest.mark.asyncio
async def test_initiator_aborts_on_reflected_confirm():
    """LP_CONFIRM_R == LP_CONFIRM_I -> abort with Confirm Value Failed (0x04),
    and do NOT send the Random."""
    confirm = b"\x42" * 16
    ctx, sent = _ctx(local_confirm=confirm)
    await state_mod._initiator_recv_peer_confirm(ctx, pdu=_Pdu(confirm))

    assert sent[-1][0] == SMPCode.PAIRING_FAILED
    assert sent[-1][1] == 0x04, "reason must be Confirm Value Failed"
    assert all(b[0] != SMPCode.PAIRING_RANDOM for b in sent), \
        "must not proceed to the Random exchange on a reflection"
    with pytest.raises(RuntimeError):
        await ctx.pairing_complete


@pytest.mark.asyncio
async def test_initiator_proceeds_on_distinct_confirm():
    """Normal JW: a distinct peer confirm -> send our Random (no abort)."""
    ctx, sent = _ctx(local_confirm=b"\x42" * 16)
    await state_mod._initiator_recv_peer_confirm(ctx, pdu=_Pdu(b"\x99" * 16))

    assert sent[-1][0] == SMPCode.PAIRING_RANDOM
    assert not ctx.pairing_complete.done()


@pytest.mark.asyncio
async def test_on_failed_attaches_the_reason_to_the_pairing_exception():
    """The BTP layer turns a failed pair() into GAP PAIRING_FAILED for auto-pts;
    it can only name the right reason (WID 175 wants Confirm Value Failed, EKS
    wants Encryption Key Size) if the exception carries it."""
    ctx, _ = _ctx(local_confirm=b"\x42" * 16)
    await state_mod._on_failed(ctx, reason=0x04)
    with pytest.raises(RuntimeError) as excinfo:
        ctx.pairing_complete.result()
    assert excinfo.value.reason == 0x04
