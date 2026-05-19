"""Tests for SMP SC Passkey Entry (Sub-Plan 3b-2)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pybluehost.ble.smp import SMPState
from pybluehost.core.address import BDAddress


def test_smp_state_passkey_sc_round_exists():
    assert SMPState.PASSKEY_SC_ROUND == 12


from pybluehost.ble._smp_state import _association_model
from pybluehost.core.types import IOCapability


def _ctx_sc(*, mitm_local=True, mitm_peer=True,
            io_local=IOCapability.DISPLAY_YES_NO,
            io_peer=IOCapability.KEYBOARD_ONLY,
            role_initiator=True):
    """Minimal pairing-context stub for SC selection tests."""
    from pybluehost.ble.smp import PairingRole
    auth_local = 0x01 | 0x08 | (0x04 if mitm_local else 0x00)  # bondable + SC + MITM
    auth_peer = 0x01 | 0x08 | (0x04 if mitm_peer else 0x00)
    return SimpleNamespace(
        security_config=SimpleNamespace(
            enable_secure_connections=True,
            mitm_required=mitm_local,
        ),
        local_auth_req=auth_local,
        peer_auth_req=auth_peer,
        local_io_caps=int(io_local),
        peer_io_caps=int(io_peer),
        role=PairingRole.INITIATOR if role_initiator else PairingRole.RESPONDER,
    )


def test_sc_association_model_passkey_displayyesno_keyboardonly():
    assert _association_model(_ctx_sc()) == "passkey_entry"


def test_sc_association_model_passkey_displayonly_keyboardonly():
    ctx = _ctx_sc(
        io_local=IOCapability.DISPLAY_ONLY,
        io_peer=IOCapability.KEYBOARD_ONLY,
    )
    assert _association_model(ctx) == "passkey_entry"


def test_sc_association_model_passkey_keyboarddisplay_keyboardonly():
    ctx = _ctx_sc(
        io_local=IOCapability.KEYBOARD_DISPLAY,
        io_peer=IOCapability.KEYBOARD_ONLY,
    )
    assert _association_model(ctx) == "passkey_entry"


def test_sc_association_model_nc_wins_over_passkey_for_dyn_dyn():
    ctx = _ctx_sc(
        io_local=IOCapability.DISPLAY_YES_NO,
        io_peer=IOCapability.DISPLAY_YES_NO,
    )
    assert _association_model(ctx) == "numeric_comparison"


def test_sc_association_model_nc_wins_over_passkey_for_dyn_kbd():
    ctx = _ctx_sc(
        io_local=IOCapability.DISPLAY_YES_NO,
        io_peer=IOCapability.KEYBOARD_DISPLAY,
    )
    assert _association_model(ctx) == "numeric_comparison"


def test_sc_association_model_nc_wins_over_passkey_for_kbd_kbd():
    ctx = _ctx_sc(
        io_local=IOCapability.KEYBOARD_DISPLAY,
        io_peer=IOCapability.KEYBOARD_DISPLAY,
    )
    assert _association_model(ctx) == "numeric_comparison"


def test_sc_association_model_just_works_when_no_input_no_output():
    ctx = _ctx_sc(io_peer=IOCapability.NO_INPUT_NO_OUTPUT)
    assert _association_model(ctx) == "just_works"


def test_sc_association_model_just_works_when_mitm_off():
    ctx = _ctx_sc(mitm_local=False)
    assert _association_model(ctx) == "just_works"


def test_sc_association_model_just_works_for_both_keyboard_only():
    ctx = _ctx_sc(
        io_local=IOCapability.KEYBOARD_ONLY,
        io_peer=IOCapability.KEYBOARD_ONLY,
    )
    assert _association_model(ctx) == "just_works"
