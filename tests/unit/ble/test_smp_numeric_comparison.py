"""Tests for SMP Numeric Comparison (Sub-Plan 3a)."""
from __future__ import annotations

import pytest

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import AutoAcceptDelegate, PairingDelegate, SMPEvent, SMPState
from pybluehost.core.address import BDAddress


def test_security_config_mitm_required_default_false():
    cfg = SecurityConfig()
    assert cfg.mitm_required is False


def test_security_config_mitm_required_overrideable():
    cfg = SecurityConfig(mitm_required=True)
    assert cfg.mitm_required is True


@pytest.mark.asyncio
async def test_auto_accept_delegate_confirm_numeric_returns_true():
    d = AutoAcceptDelegate()
    addr = BDAddress(bytes(6))
    assert await d.confirm_numeric(addr, 123456) is True


def test_pairing_delegate_protocol_has_confirm_numeric():
    assert "confirm_numeric" in PairingDelegate.__dict__


def test_smp_state_numeric_compare_pending_exists():
    assert SMPState.NUMERIC_COMPARE_PENDING == 10


def test_smp_event_numeric_compare_values():
    assert SMPEvent.NUMERIC_COMPARE_USER_CONFIRMED == 18
    assert SMPEvent.NUMERIC_COMPARE_USER_REJECTED == 19
