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


# ---------------------------------------------------------------------------
# Task 4 — _sc_compute_and_await_nc()
# ---------------------------------------------------------------------------

import asyncio

from pybluehost.ble._smp_state import _sc_compute_and_await_nc
from pybluehost.ble.smp import PairingRole, SMPCrypto


class _RecordingSM:
    def __init__(self):
        self.fired: list[SMPEvent] = []

    async def fire(self, event):
        self.fired.append(event)


class _RejectingDelegate:
    async def confirm_numeric(self, peer_addr, value):
        return False


class _CapturingDelegate:
    def __init__(self):
        self.received: tuple | None = None
    async def confirm_numeric(self, peer_addr, value):
        self.received = (peer_addr, value)
        return True


@pytest.mark.asyncio
async def test_sc_compute_and_await_nc_initiator_fires_confirmed_event():
    pkax = bytes(range(32))
    pkbx = bytes(range(32, 64))
    na = bytes(range(64, 80))
    nb = bytes(range(80, 96))
    expected_value = SMPCrypto.g2(pkax, pkbx, na, nb) % 1_000_000

    captured = _CapturingDelegate()
    peer = BDAddress(bytes(reversed(bytes.fromhex("AABBCCDDEEFF"))))
    sm = _RecordingSM()
    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_public_key=pkax + bytes(32),
        peer_public_key=pkbx + bytes(32),
        local_random=na,
        peer_random=nb,
        peer_address=peer,
        state_machine=sm,
        _delegate=captured,
    )
    await _sc_compute_and_await_nc(ctx)
    # Give the spawned task time to run
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert captured.received == (peer, expected_value)
    assert sm.fired == [SMPEvent.NUMERIC_COMPARE_USER_CONFIRMED]


@pytest.mark.asyncio
async def test_sc_compute_and_await_nc_responder_uses_peer_pubkey_as_pkax():
    pkax = bytes(range(32))
    pkbx = bytes(range(32, 64))
    na = bytes(range(64, 80))
    nb = bytes(range(80, 96))
    expected = SMPCrypto.g2(pkax, pkbx, na, nb) % 1_000_000

    captured = _CapturingDelegate()
    ctx = SimpleNamespace(
        role=PairingRole.RESPONDER,
        local_public_key=pkbx + bytes(32),
        peer_public_key=pkax + bytes(32),
        local_random=nb,
        peer_random=na,
        peer_address=BDAddress(bytes(6)),
        state_machine=_RecordingSM(),
        _delegate=captured,
    )
    await _sc_compute_and_await_nc(ctx)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert captured.received[1] == expected


@pytest.mark.asyncio
async def test_sc_compute_and_await_nc_fires_rejected_when_delegate_returns_false():
    sm = _RecordingSM()
    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_public_key=bytes(64),
        peer_public_key=bytes(64),
        local_random=bytes(16),
        peer_random=bytes(16),
        peer_address=BDAddress(bytes(6)),
        state_machine=sm,
        _delegate=_RejectingDelegate(),
    )
    await _sc_compute_and_await_nc(ctx)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert sm.fired == [SMPEvent.NUMERIC_COMPARE_USER_REJECTED]


@pytest.mark.asyncio
async def test_sc_compute_and_await_nc_falls_back_to_autoaccept_when_no_delegate():
    sm = _RecordingSM()
    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_public_key=bytes(64),
        peer_public_key=bytes(64),
        local_random=bytes(16),
        peer_random=bytes(16),
        peer_address=BDAddress(bytes(6)),
        state_machine=sm,
        _delegate=None,
    )
    await _sc_compute_and_await_nc(ctx)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert sm.fired == [SMPEvent.NUMERIC_COMPARE_USER_CONFIRMED]
