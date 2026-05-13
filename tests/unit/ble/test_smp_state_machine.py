"""SMPPairingContext skeleton: enum completeness + initial state."""
from __future__ import annotations

import pytest

from pybluehost.core.errors import InvalidTransitionError
from pybluehost.ble.smp import (
    PairingRole,
    SMPEvent,
    SMPPairingContext,
    SMPState,
)


def test_state_enum_contains_all_required_states():
    expected = {
        "IDLE", "FEATURE_EXCHANGE", "CONFIRMING", "RANDOM_EXCHANGE",
        "STK_ENCRYPTING", "KEY_DISTRIBUTION", "BONDED", "FAILED",
    }
    actual = {s.name for s in SMPState}
    assert expected.issubset(actual)


def test_event_enum_contains_all_required_events():
    expected = {
        "LOCAL_PAIR_REQUEST", "PAIRING_REQ_RX", "PAIRING_RSP_RX",
        "PAIRING_CONFIRM_RX", "PAIRING_RANDOM_RX",
        "ENCRYPTION_CHANGE_SUCCESS", "ENCRYPTION_CHANGE_FAILED",
        "ENCRYPTION_INFO_RX", "MASTER_IDENT_RX",
        "IDENTITY_INFO_RX", "IDENTITY_ADDR_RX", "SIGNING_INFO_RX",
        "PAIRING_FAILED_RX", "TIMEOUT", "DISCONNECTED",
        "KEYS_RECEIVED",
    }
    actual = {e.name for e in SMPEvent}
    assert expected.issubset(actual)


def test_pairing_role_enum():
    assert PairingRole.INITIATOR != PairingRole.RESPONDER


def test_context_starts_in_idle():
    from pybluehost.core.address import BDAddress
    ctx = SMPPairingContext.create(
        connection_handle=0x0040,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        role=PairingRole.INITIATOR,
    )
    assert ctx.state_machine.state == SMPState.IDLE


async def test_context_rejects_invalid_event():
    from pybluehost.core.address import BDAddress
    ctx = SMPPairingContext.create(
        connection_handle=0x0040,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        role=PairingRole.INITIATOR,
    )
    with pytest.raises(InvalidTransitionError):
        # No transitions registered yet → any fire should raise
        await ctx.state_machine.fire(SMPEvent.PAIRING_REQ_RX)
