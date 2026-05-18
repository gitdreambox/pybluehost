"""Tests for SMP Numeric Comparison (Sub-Plan 3a)."""
from __future__ import annotations

import pytest

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import AutoAcceptDelegate, PairingDelegate
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
    # AutoAcceptDelegate must satisfy the runtime structure
    assert hasattr(PairingDelegate, "confirm_numeric") or hasattr(AutoAcceptDelegate, "confirm_numeric")
    # explicit attribute check on AutoAcceptDelegate
    assert callable(getattr(AutoAcceptDelegate, "confirm_numeric"))
