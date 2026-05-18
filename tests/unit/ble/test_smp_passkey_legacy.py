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


from types import SimpleNamespace

from pybluehost.ble._smp_state import _association_model, _passkey_local_role
from pybluehost.core.types import IOCapability


def _ctx_legacy(*, mitm_local=True, mitm_peer=True,
                io_local=IOCapability.DISPLAY_YES_NO,
                io_peer=IOCapability.KEYBOARD_ONLY,
                role_initiator=True):
    """Build a minimal pairing-context stub (Legacy, no SC)."""
    from pybluehost.ble.smp import PairingRole
    auth_local = (0x01) | (0x04 if mitm_local else 0x00)
    auth_peer = (0x01) | (0x04 if mitm_peer else 0x00)
    return SimpleNamespace(
        security_config=SimpleNamespace(
            enable_secure_connections=False,
            mitm_required=mitm_local,
        ),
        local_auth_req=auth_local,
        peer_auth_req=auth_peer,
        local_io_caps=int(io_local),
        peer_io_caps=int(io_peer),
        role=PairingRole.INITIATOR if role_initiator else PairingRole.RESPONDER,
    )


def test_association_model_passkey_displayyesno_keyboardonly():
    assert _association_model(_ctx_legacy()) == "passkey_entry"


def test_association_model_passkey_keyboarddisplay_keyboarddisplay():
    ctx = _ctx_legacy(
        io_local=IOCapability.KEYBOARD_DISPLAY,
        io_peer=IOCapability.KEYBOARD_DISPLAY,
    )
    assert _association_model(ctx) == "passkey_entry"


def test_association_model_just_works_when_local_mitm_off():
    ctx = _ctx_legacy(mitm_local=False)
    assert _association_model(ctx) == "just_works"


def test_association_model_just_works_when_peer_mitm_off():
    ctx = _ctx_legacy(mitm_peer=False)
    assert _association_model(ctx) == "just_works"


def test_association_model_just_works_for_no_input_no_output():
    ctx = _ctx_legacy(io_peer=IOCapability.NO_INPUT_NO_OUTPUT)
    assert _association_model(ctx) == "just_works"


def test_association_model_just_works_for_both_keyboard_only():
    ctx = _ctx_legacy(
        io_local=IOCapability.KEYBOARD_ONLY,
        io_peer=IOCapability.KEYBOARD_ONLY,
    )
    assert _association_model(ctx) == "just_works"


def test_passkey_local_role_display_for_display_only():
    ctx = _ctx_legacy(
        io_local=IOCapability.DISPLAY_ONLY,
        io_peer=IOCapability.KEYBOARD_ONLY,
    )
    assert _passkey_local_role(ctx) == "display"


def test_passkey_local_role_input_for_keyboard_only():
    ctx = _ctx_legacy(
        io_local=IOCapability.KEYBOARD_ONLY,
        io_peer=IOCapability.DISPLAY_YES_NO,
    )
    assert _passkey_local_role(ctx) == "input"


def test_passkey_local_role_keyboard_display_initiator_displays():
    ctx = _ctx_legacy(
        io_local=IOCapability.KEYBOARD_DISPLAY,
        io_peer=IOCapability.KEYBOARD_DISPLAY,
        role_initiator=True,
    )
    assert _passkey_local_role(ctx) == "display"


def test_passkey_local_role_keyboard_display_responder_inputs():
    ctx = _ctx_legacy(
        io_local=IOCapability.KEYBOARD_DISPLAY,
        io_peer=IOCapability.KEYBOARD_DISPLAY,
        role_initiator=False,
    )
    assert _passkey_local_role(ctx) == "input"
