"""Tests for SMP Legacy Passkey Entry (Sub-Plan 3b-1)."""
from __future__ import annotations

import pytest

from pybluehost.ble.smp import AutoAcceptDelegate, PairingDelegate
from pybluehost.core.address import BDAddress


@pytest.mark.asyncio
async def test_auto_accept_display_passkey_accepts_peer_addr():
    d = AutoAcceptDelegate()
    addr = BDAddress(bytes(6))
    await d.display_passkey(addr, 123456)


@pytest.mark.asyncio
async def test_auto_accept_get_passkey_returns_int_with_peer_addr():
    d = AutoAcceptDelegate()
    addr = BDAddress(bytes(6))
    value = await d.get_passkey(addr)
    assert isinstance(value, int)
    assert 0 <= value <= 999_999


@pytest.mark.asyncio
async def test_auto_accept_confirm_passkey_accepts_peer_addr():
    d = AutoAcceptDelegate()
    addr = BDAddress(bytes(6))
    assert await d.confirm_passkey(addr, 0) is True


def test_pairing_delegate_protocol_passkey_methods_present():
    assert "display_passkey" in PairingDelegate.__dict__
    assert "get_passkey" in PairingDelegate.__dict__
    assert "confirm_passkey" in PairingDelegate.__dict__


from pybluehost.ble.smp import SMPEvent, SMPState


def test_smp_state_passkey_input_pending_exists():
    assert SMPState.PASSKEY_INPUT_PENDING == 11


def test_smp_event_passkey_values():
    assert SMPEvent.PASSKEY_USER_ENTERED == 20
    assert SMPEvent.PASSKEY_USER_REJECTED == 21
