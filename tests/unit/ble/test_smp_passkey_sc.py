"""Tests for SMP SC Passkey Entry (Sub-Plan 3b-2)."""
from __future__ import annotations

import asyncio
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

    monkeypatch.setattr(state_mod, "_sc_f4", _stub_f4)

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
    # f4 called with SMP wire-order byte arrays.
    assert len(captured_args) == 1
    U, V, X, Z = captured_args[0]
    assert U == pkax
    assert V == pkbx
    assert X == ctx.passkey_local_random
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

    monkeypatch.setattr(state_mod, "_sc_f4", _stub_f4)

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

    monkeypatch.setattr(state_mod, "_sc_f4", _stub_f4)

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


@pytest.mark.asyncio
async def test_sc_passkey_recv_peer_confirm_initiator_sends_random(monkeypatch):
    """Initiator receives Cb_i → stores peer_confirm → sends Pairing_Random with Na_i."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole, SMPState

    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)

    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_public_key=bytes(64),
        peer_public_key=bytes(64),
        passkey=314159,
        passkey_round=1,
        passkey_round_phase="AWAIT_PEER_CONFIRM",
        passkey_local_random=b"\x11" * 16,   # Na_1 was generated in send_round_confirm
        passkey_local_confirm=b"\xaa" * 16,
        send=_send,
    )
    pdu = SimpleNamespace(confirm_value=b"\xcc" * 16)  # Cb_1
    await state_mod._sc_passkey_recv_peer_confirm(ctx, pdu=pdu)
    assert ctx.passkey_peer_confirm == b"\xcc" * 16
    # Pairing_Random sent (opcode 0x04) with Na_1
    assert len(sent) == 1 and sent[0][0] == 0x04
    assert sent[0][1:] == b"\x11" * 16
    assert ctx.passkey_round_phase == "AWAIT_PEER_RANDOM"


@pytest.mark.asyncio
async def test_sc_passkey_recv_peer_confirm_responder_computes_and_sends_confirm(monkeypatch):
    """Responder receives Ca_i -> computes Cb_i = f4(PKbx, PKax, Nb_i, 0x80|bit_i) -> sends."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole

    captured_args: list = []

    def _stub_f4(U, V, X, Z):
        captured_args.append((U, V, X, Z))
        return b"\xcb" * 16

    monkeypatch.setattr(state_mod, "_sc_f4", _stub_f4)

    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)

    pkax = bytes(range(32))         # Initiator's pubkey X = peer's
    pkbx = bytes(range(32, 64))     # Responder's pubkey X = local's
    ctx = SimpleNamespace(
        role=PairingRole.RESPONDER,
        local_public_key=pkbx + bytes(32),
        peer_public_key=pkax + bytes(32),
        passkey=0b10000000000000000000,   # bit_19 = 1
        passkey_round=1,
        passkey_round_phase="AWAIT_PEER_CONFIRM",
        send=_send,
    )
    pdu = SimpleNamespace(confirm_value=b"\xaa" * 16)
    await state_mod._sc_passkey_recv_peer_confirm(ctx, pdu=pdu)
    # f4 called with local X first, then peer X, in SMP wire order.
    assert captured_args[0][0] == pkbx
    assert captured_args[0][1] == pkax
    assert len(captured_args[0][2]) == 16
    assert captured_args[0][3] == 0x81
    # Pairing_Confirm sent
    assert len(sent) == 1 and sent[0][0] == 0x03
    assert ctx.passkey_round_phase == "AWAIT_PEER_RANDOM"


@pytest.mark.asyncio
async def test_sc_passkey_recv_peer_confirm_wrong_subphase_fails(monkeypatch):
    """Confirm arriving while in AWAIT_PEER_RANDOM → FAILED(0x08) protocol violation."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole, SMPState

    failed: list = []
    async def _stub_on_failed(ctx, **kw):
        failed.append(kw)
        ctx.state_machine._state = SMPState.FAILED

    monkeypatch.setattr(state_mod, "_on_failed", _stub_on_failed)

    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)

    class _SM:
        def __init__(self): self._state = SMPState.PASSKEY_SC_ROUND

    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        passkey_round=1,
        passkey_round_phase="AWAIT_PEER_RANDOM",   # wrong
        state_machine=_SM(),
        send=_send,
    )
    pdu = SimpleNamespace(confirm_value=b"\x00" * 16)
    await state_mod._sc_passkey_recv_peer_confirm(ctx, pdu=pdu)
    assert failed == [{"reason": 0x08}]


@pytest.mark.asyncio
async def test_sc_passkey_recv_peer_random_initiator_advances_round(monkeypatch):
    """Initiator verifies Cb_i = f4(PKbx, PKax, Nb_i, 0x80|bit_i); on match advances
    round and sends next Ca."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole

    def _stub_f4(U, V, X, Z):
        # Match the prior recv_peer_confirm path: when called for verification,
        # return whatever we stashed as peer_confirm.
        return b"\xcc" * 16

    monkeypatch.setattr(state_mod, "_sc_f4", _stub_f4)

    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)

    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_public_key=bytes(64),
        peer_public_key=bytes(64),
        passkey=123456,
        passkey_round=1,
        passkey_round_phase="AWAIT_PEER_RANDOM",
        passkey_peer_confirm=b"\xcc" * 16,    # matches stubbed f4 return
        passkey_local_random=b"\x11" * 16,
        send=_send,
    )
    pdu = SimpleNamespace(random_value=b"\xbb" * 16)
    await state_mod._sc_passkey_recv_peer_random(ctx, pdu=pdu)
    # On match: round advances to 2; new Ca_2 sent (Pairing_Confirm 0x03)
    assert ctx.passkey_round == 2
    assert ctx.passkey_round_phase == "AWAIT_PEER_CONFIRM"
    assert len(sent) == 1 and sent[0][0] == 0x03


@pytest.mark.asyncio
async def test_sc_passkey_recv_peer_random_responder_advances_round(monkeypatch):
    """Responder verifies Ca_i, sends Nb_i, advances round."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole

    def _stub_f4(U, V, X, Z):
        return b"\xaa" * 16

    monkeypatch.setattr(state_mod, "_sc_f4", _stub_f4)

    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)

    ctx = SimpleNamespace(
        role=PairingRole.RESPONDER,
        local_public_key=bytes(64),
        peer_public_key=bytes(64),
        passkey=123456,
        passkey_round=1,
        passkey_round_phase="AWAIT_PEER_RANDOM",
        passkey_peer_confirm=b"\xaa" * 16,
        passkey_local_random=b"\x22" * 16,
        send=_send,
    )
    pdu = SimpleNamespace(random_value=b"\xbb" * 16)
    await state_mod._sc_passkey_recv_peer_random(ctx, pdu=pdu)
    # Pairing_Random sent with Nb_1
    assert len(sent) == 1 and sent[0][0] == 0x04
    assert sent[0][1:] == b"\x22" * 16
    assert ctx.passkey_round == 2
    assert ctx.passkey_round_phase == "AWAIT_PEER_CONFIRM"


@pytest.mark.asyncio
async def test_sc_passkey_recv_peer_random_initiator_mismatch_fails(monkeypatch):
    """Cb verification mismatch -> FAILED(0x04)."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole

    monkeypatch.setattr(state_mod, "_sc_f4", lambda *a, **k: b"\xff" * 16)  # not what's stashed

    failed: list = []
    async def _stub_on_failed(ctx, **kw):
        failed.append(kw)

    monkeypatch.setattr(state_mod, "_on_failed", _stub_on_failed)

    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_public_key=bytes(64),
        peer_public_key=bytes(64),
        passkey=0,
        passkey_round=1,
        passkey_round_phase="AWAIT_PEER_RANDOM",
        passkey_peer_confirm=b"\xcc" * 16,
        passkey_local_random=b"\x00" * 16,
        send=lambda d: None,
    )
    pdu = SimpleNamespace(random_value=b"\x00" * 16)
    await state_mod._sc_passkey_recv_peer_random(ctx, pdu=pdu)
    assert failed == [{"reason": 0x04}]


@pytest.mark.asyncio
async def test_sc_passkey_recv_peer_random_initiator_round_20_exits_to_dhkey_check(monkeypatch):
    """On round 20 match, Initiator calls exit helper which sets DHKEY_CHECK state."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole, SMPState

    monkeypatch.setattr(state_mod, "_sc_f4", lambda *a, **k: b"\xcc" * 16)

    exit_called: list = []
    async def _stub_exit(ctx):
        exit_called.append(True)
        ctx.state_machine._state = SMPState.DHKEY_CHECK

    monkeypatch.setattr(state_mod, "_sc_passkey_exit_to_dhkey_check_initiator", _stub_exit)

    class _SM:
        def __init__(self): self._state = SMPState.PASSKEY_SC_ROUND

    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_public_key=bytes(64),
        peer_public_key=bytes(64),
        passkey=0,
        passkey_round=20,
        passkey_round_phase="AWAIT_PEER_RANDOM",
        passkey_peer_confirm=b"\xcc" * 16,
        passkey_local_random=b"\x99" * 16,
        state_machine=_SM(),
        send=lambda d: None,
    )
    pdu = SimpleNamespace(random_value=b"\x88" * 16)
    await state_mod._sc_passkey_recv_peer_random(ctx, pdu=pdu)
    # local_random / peer_random promoted to canonical Na/Nb for f5/f6
    assert ctx.local_random == b"\x99" * 16
    assert ctx.peer_random == b"\x88" * 16
    assert exit_called == [True]


@pytest.mark.asyncio
async def test_sc_passkey_recv_peer_random_responder_round_20_exits_to_random_exchange(monkeypatch):
    """On round 20 match, Responder exit helper sets RANDOM_EXCHANGE state."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole, SMPState

    monkeypatch.setattr(state_mod, "_sc_f4", lambda *a, **k: b"\xaa" * 16)

    exit_called: list = []
    async def _stub_exit(ctx):
        exit_called.append(True)
        ctx.state_machine._state = SMPState.RANDOM_EXCHANGE

    monkeypatch.setattr(state_mod, "_sc_passkey_exit_to_random_exchange_responder", _stub_exit)

    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)

    class _SM:
        def __init__(self): self._state = SMPState.PASSKEY_SC_ROUND

    ctx = SimpleNamespace(
        role=PairingRole.RESPONDER,
        local_public_key=bytes(64),
        peer_public_key=bytes(64),
        passkey=0,
        passkey_round=20,
        passkey_round_phase="AWAIT_PEER_RANDOM",
        passkey_peer_confirm=b"\xaa" * 16,
        passkey_local_random=b"\x77" * 16,
        state_machine=_SM(),
        send=_send,
    )
    pdu = SimpleNamespace(random_value=b"\x66" * 16)
    await state_mod._sc_passkey_recv_peer_random(ctx, pdu=pdu)
    # Responder sends Pairing_Random(Nb_20) first
    assert len(sent) == 1 and sent[0][0] == 0x04
    assert sent[0][1:] == b"\x77" * 16
    assert ctx.peer_random == b"\x66" * 16
    assert ctx.local_random == b"\x77" * 16
    assert exit_called == [True]


@pytest.mark.asyncio
async def test_sc_initiator_pubkey_passkey_display_role_enters_round(monkeypatch):
    """Initiator (Display): after pubkey exchange + DHKey, generates passkey,
    displays, sends Ca_1, state -> PASSKEY_SC_ROUND."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole, SMPPairingPublicKey, SMPState

    monkeypatch.setattr(state_mod, "_association_model", lambda _ctx: "passkey_entry")
    monkeypatch.setattr(state_mod, "_passkey_local_role", lambda _ctx: "display")
    async def _stub_resolve(ctx):
        return 555_555
    monkeypatch.setattr(state_mod, "_passkey_resolve_display_value", _stub_resolve)
    monkeypatch.setattr(state_mod, "_sc_f4", lambda *a, **k: b"\xaa" * 16)

    # Stub DHKey computation
    monkeypatch.setattr(
        "pybluehost.ble._smp_sc_crypto.compute_dhkey",
        lambda priv, pub: b"\xdd" * 32,
    )

    displayed: list = []
    class _CapturingDelegate:
        async def display_passkey(self, peer_addr, passkey):
            displayed.append((peer_addr, passkey))

    class _SM:
        def __init__(self): self._state = SMPState.PUBLIC_KEY_EXCHANGE

    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)

    pdu = SMPPairingPublicKey(public_key_x=bytes(range(32)),
                              public_key_y=bytes(range(32, 64)))
    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_private_key=b"\x00" * 32,
        local_public_key=bytes(64),
        peer_public_key=None,
        peer_address=BDAddress(b"\x0B" * 6),
        local_address=BDAddress(b"\x0A" * 6),
        state_machine=_SM(),
        _delegate=_CapturingDelegate(),
        send=_send,
        passkey=None,
    )
    await state_mod._sc_initiator_recv_peer_public_key(ctx, pdu=pdu)
    assert ctx.passkey == 555_555
    assert displayed == [(BDAddress(b"\x0B" * 6), 555_555)]
    assert ctx.passkey_round == 1
    assert ctx.passkey_round_phase == "AWAIT_PEER_CONFIRM"
    # Pairing_Confirm sent
    assert len(sent) == 1 and sent[0][0] == 0x03
    # State overridden to PASSKEY_SC_ROUND
    assert ctx.state_machine._state == SMPState.PASSKEY_SC_ROUND


@pytest.mark.asyncio
async def test_sc_initiator_pubkey_passkey_input_role_enters_input_pending(monkeypatch):
    """Initiator (Input): state -> PASSKEY_INPUT_PENDING; no PDU sent."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole, SMPPairingPublicKey, SMPState

    monkeypatch.setattr(state_mod, "_association_model", lambda _ctx: "passkey_entry")
    monkeypatch.setattr(state_mod, "_passkey_local_role", lambda _ctx: "input")
    monkeypatch.setattr(
        "pybluehost.ble._smp_sc_crypto.compute_dhkey",
        lambda priv, pub: b"\xdd" * 32,
    )

    await_called: list = []
    async def _stub_await(ctx):
        await_called.append(True)

    monkeypatch.setattr(state_mod, "_passkey_await_user_input", _stub_await)

    class _SM:
        def __init__(self): self._state = SMPState.PUBLIC_KEY_EXCHANGE

    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)

    pdu = SMPPairingPublicKey(public_key_x=bytes(range(32)),
                              public_key_y=bytes(range(32, 64)))
    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_private_key=b"\x00" * 32,
        local_public_key=bytes(64),
        peer_public_key=None,
        peer_address=BDAddress(b"\x0B" * 6),
        local_address=BDAddress(b"\x0A" * 6),
        state_machine=_SM(),
        _delegate=None,
        send=_send,
    )
    await state_mod._sc_initiator_recv_peer_public_key(ctx, pdu=pdu)
    assert ctx.state_machine._state == SMPState.PASSKEY_INPUT_PENDING
    assert sent == []
    assert await_called == [True]


@pytest.mark.asyncio
async def test_sc_responder_pubkey_passkey_display_skips_cb_send(monkeypatch):
    """Responder (Display): after sending own pubkey, does NOT send Cb (waits for Initiator's Ca_1)."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole, SMPPairingPublicKey, SMPState

    monkeypatch.setattr(state_mod, "_association_model", lambda _ctx: "passkey_entry")
    monkeypatch.setattr(state_mod, "_passkey_local_role", lambda _ctx: "display")
    async def _stub_resolve(ctx):
        return 246_810
    monkeypatch.setattr(state_mod, "_passkey_resolve_display_value", _stub_resolve)

    monkeypatch.setattr(
        "pybluehost.ble._smp_sc_crypto.generate_p256_keypair",
        lambda: (b"\x00" * 32, bytes(range(64))),
    )
    monkeypatch.setattr(
        "pybluehost.ble._smp_sc_crypto.compute_dhkey",
        lambda priv, pub: b"\xdd" * 32,
    )

    displayed: list = []
    class _CapturingDelegate:
        async def display_passkey(self, peer_addr, passkey):
            displayed.append((peer_addr, passkey))

    class _SM:
        def __init__(self): self._state = SMPState.PUBLIC_KEY_EXCHANGE

    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)

    pdu = SMPPairingPublicKey(public_key_x=bytes(range(32)),
                              public_key_y=bytes(range(32, 64)))
    ctx = SimpleNamespace(
        role=PairingRole.RESPONDER,
        local_private_key=None,
        local_public_key=None,
        peer_public_key=None,
        peer_address=BDAddress(b"\x0B" * 6),
        local_address=BDAddress(b"\x0A" * 6),
        state_machine=_SM(),
        _delegate=_CapturingDelegate(),
        send=_send,
    )
    await state_mod._sc_responder_recv_peer_public_key(ctx, pdu=pdu)
    # Exactly one PDU sent: own Public Key (opcode 0x0C). NO Pairing_Confirm.
    assert len(sent) == 1 and sent[0][0] == 0x0C
    assert ctx.passkey == 246_810
    assert displayed == [(BDAddress(b"\x0B" * 6), 246_810)]
    assert ctx.state_machine._state == SMPState.PASSKEY_SC_ROUND
    assert ctx.passkey_round == 1
    assert ctx.passkey_round_phase == "AWAIT_PEER_CONFIRM"


@pytest.mark.asyncio
async def test_passkey_user_entered_sc_initiator_sends_round1_confirm(monkeypatch):
    """SC Initiator + PASSKEY_USER_ENTERED → state PASSKEY_SC_ROUND + Ca_1 sent."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole, SMPState

    monkeypatch.setattr(state_mod, "_sc_negotiated", lambda _ctx: True)
    monkeypatch.setattr(state_mod, "_sc_f4", lambda *a, **k: b"\xaa" * 16)

    class _SM:
        def __init__(self): self._state = SMPState.PASSKEY_INPUT_PENDING

    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)

    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_public_key=bytes(64),
        peer_public_key=bytes(64),
        passkey=987654,
        state_machine=_SM(),
        send=_send,
    )
    await state_mod._passkey_user_entered(ctx)
    assert ctx.state_machine._state == SMPState.PASSKEY_SC_ROUND
    assert ctx.passkey_round == 1
    assert ctx.passkey_round_phase == "AWAIT_PEER_CONFIRM"
    assert len(sent) == 1 and sent[0][0] == 0x03  # Pairing_Confirm


@pytest.mark.asyncio
async def test_passkey_user_entered_sc_responder_awaits_confirm(monkeypatch):
    """SC Responder + PASSKEY_USER_ENTERED → state PASSKEY_SC_ROUND, no PDU sent."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole, SMPState

    monkeypatch.setattr(state_mod, "_sc_negotiated", lambda _ctx: True)

    class _SM:
        def __init__(self): self._state = SMPState.PASSKEY_INPUT_PENDING

    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)

    ctx = SimpleNamespace(
        role=PairingRole.RESPONDER,
        passkey=987654,
        state_machine=_SM(),
        send=_send,
    )
    await state_mod._passkey_user_entered(ctx)
    assert ctx.state_machine._state == SMPState.PASSKEY_SC_ROUND
    assert ctx.passkey_round == 1
    assert ctx.passkey_round_phase == "AWAIT_PEER_CONFIRM"
    assert sent == []


def test_passkey_sc_round_transitions_registered():
    import inspect
    from pybluehost.ble import _smp_state as state_mod
    src = inspect.getsource(state_mod.register_transitions)
    # Two reflexive transitions on PASSKEY_SC_ROUND
    assert "PASSKEY_SC_ROUND, SMPEvent.PAIRING_CONFIRM_RX" in src
    assert "PASSKEY_SC_ROUND, SMPEvent.PAIRING_RANDOM_RX" in src
    # 60s timeout
    assert "set_timeout(SMPState.PASSKEY_SC_ROUND, 60.0" in src
    # Universal failure inclusion
    universal = src[src.find("Universal failure"):]
    assert "PASSKEY_SC_ROUND" in universal


@pytest.mark.asyncio
async def test_persist_bond_authenticated_true_for_sc_passkey(monkeypatch):
    """SC + passkey_entry bond → authenticated=True (mirrors NC pattern)."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import BondInfo, PairingRole

    saved: list = []
    class _MemStorage:
        async def save_bond(self, bond):
            saved.append(bond)

    monkeypatch.setattr(state_mod, "_sc_negotiated", lambda _ctx: True)
    monkeypatch.setattr(state_mod, "_association_model", lambda _ctx: "passkey_entry")

    fut = asyncio.get_event_loop().create_future()
    ctx = SimpleNamespace(
        peer_address=BDAddress(bytes(6)),
        received_identity_address=(0, bytes(6)),
        ltk_sc=b"\x11" * 16,
        received_irk=None,
        received_csrk=None,
        role=PairingRole.INITIATOR,
        connection_handle=1,
        _bond_storage=_MemStorage(),
        pairing_complete=fut,
    )
    await state_mod._persist_bond(ctx)
    assert saved[0].authenticated is True
    assert saved[0].sc is True
