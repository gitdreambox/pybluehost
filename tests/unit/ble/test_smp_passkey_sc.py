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


@pytest.mark.asyncio
async def test_sc_passkey_send_round_confirm_initiator_round_1(monkeypatch):
    """Round 1 uses MSB of passkey; computes f4(PKax, PKbx, Na_1, 0x80|bit_19)
    and sends Pairing_Confirm."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole

    captured_args: list = []

    def _stub_f4(U, V, X, Z):
        captured_args.append((U, V, X, Z))
        return b"\xa1" * 16

    monkeypatch.setattr(state_mod.SMPCrypto, "f4", staticmethod(_stub_f4))

    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)

    pkax = bytes(range(32))
    pkbx = bytes(range(32, 64))
    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_public_key=pkax + bytes(32),
        peer_public_key=pkbx + bytes(32),
        passkey=0b10000000000000000000,   # bit_19 = 1, others 0 (passkey = 524288)
        passkey_round=1,
        send=_send,
    )
    await state_mod._sc_passkey_send_round_confirm(ctx)
    # f4 called with (PKax, PKbx, Na_1, 0x80 | 1) = (pkax, pkbx, 16B random, 0x81)
    assert len(captured_args) == 1
    U, V, X, Z = captured_args[0]
    assert U == pkax
    assert V == pkbx
    assert len(X) == 16  # 16-byte random
    assert Z == 0x81
    # Pairing_Confirm sent (opcode 0x03)
    assert len(sent) == 1 and sent[0][0] == 0x03
    # ctx fields updated
    assert ctx.passkey_local_random == X
    assert ctx.passkey_local_confirm == b"\xa1" * 16


@pytest.mark.asyncio
async def test_sc_passkey_send_round_confirm_initiator_round_20(monkeypatch):
    """Round 20 uses LSB of passkey."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole

    captured_args: list = []

    def _stub_f4(U, V, X, Z):
        captured_args.append((U, V, X, Z))
        return b"\xa2" * 16

    monkeypatch.setattr(state_mod.SMPCrypto, "f4", staticmethod(_stub_f4))

    async def _send(data):
        pass

    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_public_key=bytes(64),
        peer_public_key=bytes(64),
        passkey=1,    # bit_0 = LSB = 1
        passkey_round=20,
        send=_send,
    )
    await state_mod._sc_passkey_send_round_confirm(ctx)
    # Round 20 → bit_index = 20 - 20 = 0 → bit = (1 >> 0) & 1 = 1
    assert captured_args[0][3] == 0x81


@pytest.mark.asyncio
async def test_sc_passkey_send_round_confirm_passkey_zero_uses_0x80(monkeypatch):
    """A passkey of 0 has bit_i=0 for all i → r_i = 0x80."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole

    captured_args: list = []

    def _stub_f4(U, V, X, Z):
        captured_args.append((U, V, X, Z))
        return b"\xa3" * 16

    monkeypatch.setattr(state_mod.SMPCrypto, "f4", staticmethod(_stub_f4))

    async def _send(data): pass

    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_public_key=bytes(64),
        peer_public_key=bytes(64),
        passkey=0,
        passkey_round=10,
        send=_send,
    )
    await state_mod._sc_passkey_send_round_confirm(ctx)
    assert captured_args[0][3] == 0x80
