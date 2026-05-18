"""Tests for SMP Numeric Comparison (Sub-Plan 3a)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pybluehost.ble._smp_state import _association_model
from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import AutoAcceptDelegate, PairingDelegate, SMPEvent, SMPState
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability


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


# ---------------------------------------------------------------------------
# Task 3 — _association_model() selection
# ---------------------------------------------------------------------------


def _ctx(*, sc_local=True, sc_peer=True, mitm_local=True, mitm_peer=True,
        io_local=IOCapability.DISPLAY_YES_NO, io_peer=IOCapability.DISPLAY_YES_NO):
    """Build a minimal pairing-context stub for _association_model()."""
    auth_local = (0x04 if mitm_local else 0x00) | (0x08 if sc_local else 0x00)
    auth_peer = (0x04 if mitm_peer else 0x00) | (0x08 if sc_peer else 0x00)
    return SimpleNamespace(
        security_config=SimpleNamespace(
            enable_secure_connections=sc_local,
            mitm_required=mitm_local,
        ),
        local_auth_req=auth_local,
        peer_auth_req=auth_peer,
        local_io_caps=int(io_local),
        peer_io_caps=int(io_peer),
    )


def test_association_model_nc_when_both_mitm_both_displayyesno():
    assert _association_model(_ctx()) == "numeric_comparison"


def test_association_model_nc_with_keyboard_display():
    ctx = _ctx(io_local=IOCapability.KEYBOARD_DISPLAY, io_peer=IOCapability.DISPLAY_YES_NO)
    assert _association_model(ctx) == "numeric_comparison"


def test_association_model_just_works_when_local_mitm_off():
    assert _association_model(_ctx(mitm_local=False)) == "just_works"


def test_association_model_just_works_when_peer_mitm_off():
    assert _association_model(_ctx(mitm_peer=False)) == "just_works"


def test_association_model_just_works_when_sc_not_negotiated():
    assert _association_model(_ctx(sc_peer=False)) == "just_works"


def test_association_model_just_works_when_io_caps_insufficient():
    assert _association_model(_ctx(io_peer=IOCapability.NO_INPUT_NO_OUTPUT)) == "just_works"
