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


import asyncio


class _RecordingSM:
    def __init__(self):
        self.fired: list = []
    async def fire(self, event):
        self.fired.append(event)


class _GoodPasskeyDelegate:
    def __init__(self, value: int = 314159):
        self.value = value
        self.calls: list = []
    async def get_passkey(self, peer_addr):
        self.calls.append(peer_addr)
        return self.value


class _RaisingDelegate:
    async def get_passkey(self, peer_addr):
        raise RuntimeError("user cancelled")


class _OutOfRangeDelegate:
    async def get_passkey(self, peer_addr):
        return 1_000_000


@pytest.mark.asyncio
async def test_passkey_await_user_input_fires_entered_event_and_stores_value():
    from pybluehost.ble._smp_state import _passkey_await_user_input
    from pybluehost.ble.smp import SMPEvent

    sm = _RecordingSM()
    delegate = _GoodPasskeyDelegate(value=271828)
    ctx = SimpleNamespace(
        peer_address=BDAddress(bytes(6)),
        state_machine=sm,
        _delegate=delegate,
    )
    await _passkey_await_user_input(ctx)
    for _ in range(5):
        await asyncio.sleep(0)
    assert sm.fired == [SMPEvent.PASSKEY_USER_ENTERED]
    assert ctx.passkey == 271828
    assert delegate.calls == [BDAddress(bytes(6))]


@pytest.mark.asyncio
async def test_passkey_await_user_input_fires_rejected_on_exception():
    from pybluehost.ble._smp_state import _passkey_await_user_input
    from pybluehost.ble.smp import SMPEvent

    sm = _RecordingSM()
    ctx = SimpleNamespace(
        peer_address=BDAddress(bytes(6)),
        state_machine=sm,
        _delegate=_RaisingDelegate(),
    )
    await _passkey_await_user_input(ctx)
    for _ in range(5):
        await asyncio.sleep(0)
    assert sm.fired == [SMPEvent.PASSKEY_USER_REJECTED]


@pytest.mark.asyncio
async def test_passkey_await_user_input_fires_rejected_on_out_of_range():
    from pybluehost.ble._smp_state import _passkey_await_user_input
    from pybluehost.ble.smp import SMPEvent

    sm = _RecordingSM()
    ctx = SimpleNamespace(
        peer_address=BDAddress(bytes(6)),
        state_machine=sm,
        _delegate=_OutOfRangeDelegate(),
    )
    await _passkey_await_user_input(ctx)
    for _ in range(5):
        await asyncio.sleep(0)
    assert sm.fired == [SMPEvent.PASSKEY_USER_REJECTED]


@pytest.mark.asyncio
async def test_passkey_await_user_input_uses_autoaccept_when_no_delegate():
    """AutoAcceptDelegate.get_passkey returns 0; helper accepts 0 as in-range."""
    from pybluehost.ble._smp_state import _passkey_await_user_input
    from pybluehost.ble.smp import SMPEvent

    sm = _RecordingSM()
    ctx = SimpleNamespace(
        peer_address=BDAddress(bytes(6)),
        state_machine=sm,
        _delegate=None,
    )
    await _passkey_await_user_input(ctx)
    for _ in range(5):
        await asyncio.sleep(0)
    assert sm.fired == [SMPEvent.PASSKEY_USER_ENTERED]
    assert ctx.passkey == 0


@pytest.mark.asyncio
async def test_passkey_buffer_peer_confirm_stashes_value():
    from pybluehost.ble._smp_state import _passkey_buffer_peer_confirm

    ctx = SimpleNamespace(peer_confirm=None)
    pdu = SimpleNamespace(confirm_value=b"\x12" * 16)
    await _passkey_buffer_peer_confirm(ctx, pdu=pdu)
    assert ctx.peer_confirm == b"\x12" * 16


@pytest.mark.asyncio
async def test_passkey_user_entered_initiator_computes_and_sends_confirm(monkeypatch):
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole

    monkeypatch.setattr(state_mod.SMPCrypto, "c1",
                        staticmethod(lambda *a, **k: b"\xaa" * 16))

    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)

    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        passkey=314159,
        saved_pairing_request=b"\x01" + b"\x00" * 6,
        saved_pairing_response=b"\x02" + b"\x00" * 6,
        peer_address=BDAddress(b"\x0B" * 6),
        local_address=BDAddress(b"\x0A" * 6),
        connection_handle=1,
        send=_send,
        peer_confirm=None,
    )
    await state_mod._passkey_user_entered(ctx)
    assert ctx.tk == (314159).to_bytes(16, "little")
    assert isinstance(ctx.local_random, bytes) and len(ctx.local_random) == 16
    assert ctx.local_confirm == b"\xaa" * 16
    assert len(sent) == 1
    assert sent[0][0] == 0x03


def test_passkey_input_pending_in_universal_failure_loop():
    """register_transitions must include PASSKEY_INPUT_PENDING in the universal
    failure-transition loop (PAIRING_FAILED_RX, TIMEOUT, DISCONNECTED → FAILED)."""
    import inspect
    from pybluehost.ble import _smp_state as state_mod
    src = inspect.getsource(state_mod.register_transitions)
    assert "PASSKEY_INPUT_PENDING" in src
    universal_loop_segment = src[src.find("Universal failure"):]
    assert "PASSKEY_INPUT_PENDING" in universal_loop_segment


def test_passkey_input_pending_timeout_set():
    """register_transitions must set a 60s timeout on PASSKEY_INPUT_PENDING."""
    import inspect
    from pybluehost.ble import _smp_state as state_mod
    src = inspect.getsource(state_mod.register_transitions)
    assert "set_timeout(SMPState.PASSKEY_INPUT_PENDING" in src
    assert "60.0" in src


@pytest.mark.asyncio
async def test_initiator_pairing_response_display_role_generates_displays_and_sends_confirm(monkeypatch):
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole, SMPPairingResponse, SMPState

    monkeypatch.setattr(state_mod, "_association_model", lambda _ctx: "passkey_entry")
    monkeypatch.setattr(state_mod, "_passkey_local_role", lambda _ctx: "display")
    monkeypatch.setattr(state_mod, "secrets",
                        SimpleNamespace(randbelow=lambda _n: 246813))
    monkeypatch.setattr(state_mod.SMPCrypto, "c1",
                        staticmethod(lambda *a, **k: b"\xbb" * 16))

    displayed: list = []

    class _CapturingDisplay:
        async def display_passkey(self, peer_addr, passkey):
            displayed.append((peer_addr, passkey))

    class _FakeSM:
        def __init__(self):
            self._state = SMPState.FEATURE_EXCHANGE
        async def fire(self, ev): pass

    sm = _FakeSM()
    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)
    pdu = SMPPairingResponse(
        io_capability=0x02, oob_data_flag=0, auth_req=0x05,
        max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    )
    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        peer_io_caps=0x02, peer_auth_req=0x05, peer_max_key_size=16,
        peer_init_key_dist=0x07, peer_resp_key_dist=0x07,
        local_io_caps=0x01, local_auth_req=0x05,
        peer_address=BDAddress(b"\x0B" * 6),
        local_address=BDAddress(b"\x0A" * 6),
        saved_pairing_request=b"\x01" + b"\x00" * 6,
        saved_pairing_response=b"\x02" + b"\x00" * 6,
        security_config=SimpleNamespace(
            enable_secure_connections=False, mitm_required=True,
        ),
        state_machine=sm,
        _delegate=_CapturingDisplay(),
        send=_send,
    )
    await state_mod._initiator_recv_pairing_response(ctx, pdu=pdu)
    assert ctx.passkey == 246813
    assert displayed == [(BDAddress(b"\x0B" * 6), 246813)]
    assert ctx.tk == (246813).to_bytes(16, "little")
    assert len(sent) == 1 and sent[0][0] == 0x03
    # action does not override state; SM transition target is CONFIRMING
    assert sm._state == SMPState.FEATURE_EXCHANGE


@pytest.mark.asyncio
async def test_initiator_pairing_response_input_role_overrides_state_to_passkey_pending(monkeypatch):
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole, SMPPairingResponse, SMPState

    monkeypatch.setattr(state_mod, "_association_model", lambda _ctx: "passkey_entry")
    monkeypatch.setattr(state_mod, "_passkey_local_role", lambda _ctx: "input")

    class _FakeSM:
        def __init__(self):
            self._state = SMPState.FEATURE_EXCHANGE
        async def fire(self, ev): pass

    sm = _FakeSM()
    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)
    pdu = SMPPairingResponse(
        io_capability=0x01, oob_data_flag=0, auth_req=0x05,
        max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    )
    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        peer_io_caps=0x01, peer_auth_req=0x05, peer_max_key_size=16,
        peer_init_key_dist=0x07, peer_resp_key_dist=0x07,
        local_io_caps=0x02, local_auth_req=0x05,
        peer_address=BDAddress(b"\x0B" * 6),
        local_address=BDAddress(b"\x0A" * 6),
        saved_pairing_request=b"\x01" + b"\x00" * 6,
        saved_pairing_response=b"\x02" + b"\x00" * 6,
        security_config=SimpleNamespace(
            enable_secure_connections=False, mitm_required=True,
        ),
        state_machine=sm,
        _delegate=_GoodPasskeyDelegate(),
        send=_send,
    )
    await state_mod._initiator_recv_pairing_response(ctx, pdu=pdu)
    assert sm._state == SMPState.PASSKEY_INPUT_PENDING
    assert sent == []


@pytest.mark.asyncio
async def test_responder_pairing_request_display_role_displays_and_sends_response(monkeypatch):
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole, SMPPairingRequest, SMPState

    monkeypatch.setattr(state_mod, "_association_model", lambda _ctx: "passkey_entry")
    monkeypatch.setattr(state_mod, "_passkey_local_role", lambda _ctx: "display")
    monkeypatch.setattr(state_mod, "secrets",
                        SimpleNamespace(randbelow=lambda _n: 135790))

    displayed: list = []
    class _CapturingDisplay:
        async def display_passkey(self, peer_addr, passkey):
            displayed.append((peer_addr, passkey))

    class _FakeSM:
        def __init__(self):
            self._state = SMPState.IDLE
        async def fire(self, ev): pass

    sm = _FakeSM()
    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)
    pdu = SMPPairingRequest(
        io_capability=0x02, oob_data_flag=0, auth_req=0x05,
        max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    )
    ctx = SimpleNamespace(
        role=PairingRole.RESPONDER,
        peer_io_caps=0x02, peer_auth_req=0x05, peer_max_key_size=16,
        peer_init_key_dist=0x07, peer_resp_key_dist=0x07,
        local_io_caps=0x01, bondable=True,
        peer_address=BDAddress(b"\x0B" * 6),
        local_address=BDAddress(b"\x0A" * 6),
        security_config=SimpleNamespace(
            enable_secure_connections=False, mitm_required=True,
        ),
        state_machine=sm,
        _delegate=_CapturingDisplay(),
        send=_send,
    )
    await state_mod._responder_recv_pairing_request(ctx, pdu=pdu)
    assert len(sent) == 1 and sent[0][0] == 0x02  # Pairing_Response sent
    assert ctx.passkey == 135790
    assert displayed == [(BDAddress(b"\x0B" * 6), 135790)]
    assert ctx.tk == (135790).to_bytes(16, "little")
    # action does not override state; SM transition target is CONFIRMING
    assert sm._state == SMPState.IDLE


@pytest.mark.asyncio
async def test_responder_pairing_request_input_role_overrides_to_passkey_pending(monkeypatch):
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole, SMPPairingRequest, SMPState

    monkeypatch.setattr(state_mod, "_association_model", lambda _ctx: "passkey_entry")
    monkeypatch.setattr(state_mod, "_passkey_local_role", lambda _ctx: "input")

    class _FakeSM:
        def __init__(self):
            self._state = SMPState.IDLE
        async def fire(self, ev): pass

    sm = _FakeSM()
    sent: list[bytes] = []
    async def _send(data):
        sent.append(data)
    pdu = SMPPairingRequest(
        io_capability=0x01, oob_data_flag=0, auth_req=0x05,
        max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    )
    ctx = SimpleNamespace(
        role=PairingRole.RESPONDER,
        peer_io_caps=0x01, peer_auth_req=0x05, peer_max_key_size=16,
        peer_init_key_dist=0x07, peer_resp_key_dist=0x07,
        local_io_caps=0x02, bondable=True,
        peer_address=BDAddress(b"\x0B" * 6),
        local_address=BDAddress(b"\x0A" * 6),
        security_config=SimpleNamespace(
            enable_secure_connections=False, mitm_required=True,
        ),
        state_machine=sm,
        _delegate=_GoodPasskeyDelegate(),
        send=_send,
    )
    await state_mod._responder_recv_pairing_request(ctx, pdu=pdu)
    # Pairing_Response sent BEFORE state override
    assert len(sent) == 1 and sent[0][0] == 0x02
    assert sm._state == SMPState.PASSKEY_INPUT_PENDING


@pytest.mark.asyncio
async def test_persist_bond_authenticated_true_for_legacy_passkey(monkeypatch):
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import BondInfo, PairingRole

    saved: list = []
    class _MemStorage:
        async def save_bond(self, bond):
            saved.append(bond)

    monkeypatch.setattr(state_mod, "_sc_negotiated", lambda _ctx: False)
    monkeypatch.setattr(state_mod, "_association_model", lambda _ctx: "passkey_entry")

    fut = asyncio.get_event_loop().create_future()
    ctx = SimpleNamespace(
        peer_address=BDAddress(bytes(6)),
        received_identity_address=(0, bytes(6)),
        role=PairingRole.INITIATOR,
        received_ltk=b"\x33" * 16,
        received_ediv=0,
        received_rand=b"\x00" * 8,
        local_ltk=None, local_ediv=0, local_rand=b"\x00" * 8,
        received_irk=None, received_csrk=None,
        connection_handle=1,
        _bond_storage=_MemStorage(),
        pairing_complete=fut,
    )
    await state_mod._persist_bond(ctx)
    assert saved[0].authenticated is True
    assert saved[0].sc is False
