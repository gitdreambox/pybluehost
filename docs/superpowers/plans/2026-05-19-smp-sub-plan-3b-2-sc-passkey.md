# SMP Sub-Plan 3b-2 — SC Passkey Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement LE Secure Connections Passkey Entry — the 20-round bit-by-bit f4 commit protocol on top of the existing SC infrastructure. Both sides reveal one passkey bit per round through `f4(U, V, X, 0x80 | bit_i)` commits, achieving MITM protection in a single virtual session.

**Architecture:** One new state `SMPState.PASSKEY_SC_ROUND` (=12) with reflexive transitions on `PAIRING_CONFIRM_RX` and `PAIRING_RANDOM_RX`. Action dispatch keys on `ctx.role` and `ctx.passkey_round_phase`. Round counter (`ctx.passkey_round`, 1..20) advances inside the actions; round 20 transitions out to the existing SC f5/f6 path (`_sc_send_dhkey_check_initiator` for Initiator; `RANDOM_EXCHANGE` for Responder). Selection extends `_association_model`'s SC branch to return `"passkey_entry"` for in-scope IO pairs; NC still wins for DYN×DYN, DYN×KbD, KbD×KbD. Display side reuses `_passkey_resolve_display_value`; Input side reuses `PASSKEY_INPUT_PENDING` from 3b-1.

**Tech Stack:** Python 3.10+, asyncio, pytest, existing `SMPCrypto.f4`/`f5`/`f6`, existing `VirtualLELink` for loopback tests, `secrets` (stdlib) for passkey generation.

**Design spec:** [`docs/superpowers/specs/2026-05-19-smp-sub-plan-3b-2-sc-passkey-design.md`](../specs/2026-05-19-smp-sub-plan-3b-2-sc-passkey-design.md)

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Modify | `pybluehost/ble/smp.py` | Add `SMPState.PASSKEY_SC_ROUND = 12`. No new events. |
| Modify | `pybluehost/ble/_smp_state.py` | Extend `_association_model` SC branch for Passkey; add round helpers (`_sc_passkey_send_round_confirm`, `_sc_passkey_recv_peer_confirm`, `_sc_passkey_recv_peer_random`, `_sc_passkey_exit_to_dhkey_check_initiator`, `_sc_passkey_exit_to_random_exchange_responder`, `_sc_passkey_initiator_display_enter`, `_sc_passkey_responder_display_enter`); branch `_sc_initiator_recv_peer_public_key` and `_sc_responder_recv_peer_public_key` on association model + role; extend `_passkey_user_entered` with SC branch; register `PASSKEY_SC_ROUND` reflexive transitions + 60s timeout + universal-failure inclusion. |
| Create | `tests/unit/ble/test_smp_passkey_sc.py` | Selection + bit extraction + per-round actions + exit hooks + error paths (~14 tests) |
| Create | `tests/integration/test_pairing_sc_passkey_loopback.py` | SC Passkey E2E (matching + mismatched passkey paths) |
| Modify | `docs/superpowers/STATUS.md` | Mark Sub-Plan 3b-2 complete |

---

## Task 1: `SMPState.PASSKEY_SC_ROUND` enum value

**Files:**
- Modify: `pybluehost/ble/smp.py` (`SMPState` IntEnum)
- Test: `tests/unit/ble/test_smp_passkey_sc.py` (new file)

- [ ] **Step 1: Create test file with the failing test**

Create `tests/unit/ble/test_smp_passkey_sc.py`:

```python
"""Tests for SMP SC Passkey Entry (Sub-Plan 3b-2)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pybluehost.ble.smp import SMPState
from pybluehost.core.address import BDAddress


def test_smp_state_passkey_sc_round_exists():
    assert SMPState.PASSKEY_SC_ROUND == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_sc.py::test_smp_state_passkey_sc_round_exists -v`
Expected: FAIL with AttributeError on `SMPState.PASSKEY_SC_ROUND`.

- [ ] **Step 3: Add the enum value**

In `pybluehost/ble/smp.py`, add `PASSKEY_SC_ROUND = 12` to `SMPState` immediately after `PASSKEY_INPUT_PENDING = 11`. Preserve `=` column alignment:

```python
class SMPState(IntEnum):
    IDLE = 0
    FEATURE_EXCHANGE = 1
    CONFIRMING = 2
    RANDOM_EXCHANGE = 3
    STK_ENCRYPTING = 4
    KEY_DISTRIBUTION = 5
    BONDED = 6
    FAILED = 7
    PUBLIC_KEY_EXCHANGE = 8
    DHKEY_CHECK = 9
    NUMERIC_COMPARE_PENDING = 10
    PASSKEY_INPUT_PENDING = 11
    PASSKEY_SC_ROUND = 12
```

- [ ] **Step 4: Run tests**

`uv run pytest tests/unit/ble/test_smp_passkey_sc.py -v` — expect 1 PASS.
`uv run pytest tests/unit/ble/ -q` — expect no regressions.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/ble/smp.py tests/unit/ble/test_smp_passkey_sc.py
git commit -m "feat(ble/smp): SMPState.PASSKEY_SC_ROUND

Sub-Plan 3b-2 Task 1. State value 12 for the SC Passkey 20-round protocol
state. No new events — reuses PAIRING_CONFIRM_RX and PAIRING_RANDOM_RX."
```

---

## Task 2: `_association_model` SC Passkey extension

**Files:**
- Modify: `pybluehost/ble/_smp_state.py` (`_association_model`)
- Test: `tests/unit/ble/test_smp_passkey_sc.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/ble/test_smp_passkey_sc.py`:

```python
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
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_sc.py -k "sc_association_model" -v`
Expected: the 3 `_passkey_*` cases FAIL (return `"just_works"` today); NC cases PASS; JW cases PASS.

- [ ] **Step 3: Extend `_association_model`**

In `pybluehost/ble/_smp_state.py`, locate `_association_model` (currently extended in Sub-Plan 3b-1, around line 845). Replace the SC branch (the `if _sc_negotiated(ctx):` block) with the extended version:

```python
def _association_model(ctx: "SMPPairingContext") -> str:
    """Return 'numeric_comparison' | 'passkey_entry' | 'just_works'.

    SC: NC for both-DYN/KbD; SC Passkey (Sub-Plan 3b-2) for remaining MITM-qualifying
    pairs; otherwise JW.
    Legacy (Sub-Plan 3b-1): Passkey Entry for MITM-qualifying pairs; otherwise JW.
    OOB deferred to Sub-Plan 3c.
    """
    from pybluehost.core.types import IOCapability

    both_mitm = bool(ctx.local_auth_req & 0x04) and bool(ctx.peer_auth_req & 0x04)

    if _sc_negotiated(ctx):
        if not both_mitm:
            return "just_works"
        nc_caps = {int(IOCapability.DISPLAY_YES_NO), int(IOCapability.KEYBOARD_DISPLAY)}
        if int(ctx.local_io_caps) in nc_caps and int(ctx.peer_io_caps) in nc_caps:
            return "numeric_comparison"
        # Sub-Plan 3b-2: SC Passkey for remaining MITM-qualifying pairs
        if _passkey_capable(int(ctx.local_io_caps), int(ctx.peer_io_caps)):
            return "passkey_entry"
        return "just_works"

    # Legacy path — Sub-Plan 3b-1
    if not both_mitm:
        return "just_works"
    if not _passkey_capable(int(ctx.local_io_caps), int(ctx.peer_io_caps)):
        return "just_works"
    return "passkey_entry"
```

`_passkey_capable` already exists (added in 3b-1) and excludes both-NoInputNoOutput and both-KbOnly correctly.

- [ ] **Step 4: Run tests**

`uv run pytest tests/unit/ble/test_smp_passkey_sc.py -v` — expect all PASS.
`uv run pytest tests/unit/ble/ -q` — expect no regressions (Sub-Plan 3a NC tests, 3b-1 Legacy Passkey tests, Sub-Plan 1 JW tests all still pass).

- [ ] **Step 5: Commit**

```bash
git add pybluehost/ble/_smp_state.py tests/unit/ble/test_smp_passkey_sc.py
git commit -m "feat(ble/smp): _association_model returns 'passkey_entry' for SC + MITM

Sub-Plan 3b-2 Task 2. Extends the SC branch: NC wins for both-DYN/KbD pairs;
SC Passkey activates for remaining MITM-qualifying pairs via _passkey_capable.
Both-KbOnly and NoInputNoOutput fall through to Just Works."
```

---

## Task 3: `_sc_passkey_send_round_confirm` + bit extraction

**Files:**
- Modify: `pybluehost/ble/_smp_state.py` (add helper near other passkey helpers)
- Test: `tests/unit/ble/test_smp_passkey_sc.py`

- [ ] **Step 1: Append failing tests**

```python
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
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_sc.py -k "send_round_confirm" -v`
Expected: FAIL — `_sc_passkey_send_round_confirm` does not exist.

- [ ] **Step 3: Implement**

Add to `pybluehost/ble/_smp_state.py`, immediately after `_passkey_user_entered` (or near the other SC helpers; pick a stable home — recommend placing near `_passkey_await_user_input`):

```python
async def _sc_passkey_send_round_confirm(ctx: "SMPPairingContext") -> None:
    """Initiator-only round helper: generate Na_i, compute Ca_i = f4(PKax, PKbx, Na_i, 0x80|bit_i), send.

    Round i (1..20) uses bit (20 - i) of ctx.passkey — i=1 is the MSB.
    """
    from pybluehost.ble.smp import SMPPairingConfirm
    i = ctx.passkey_round
    bit = (ctx.passkey >> (20 - i)) & 1
    ctx.passkey_local_random = os.urandom(16)
    pkax = ctx.local_public_key[:32]
    pkbx = ctx.peer_public_key[:32]
    ctx.passkey_local_confirm = SMPCrypto.f4(pkax, pkbx, ctx.passkey_local_random, 0x80 | bit)
    await ctx.send(SMPPairingConfirm(confirm_value=ctx.passkey_local_confirm).to_bytes())
```

- [ ] **Step 4: Run tests**

`uv run pytest tests/unit/ble/test_smp_passkey_sc.py -k "send_round_confirm" -v` — expect 3 PASS.
`uv run pytest tests/unit/ble/ -q` — expect no regressions.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/ble/_smp_state.py tests/unit/ble/test_smp_passkey_sc.py
git commit -m "feat(ble/smp): _sc_passkey_send_round_confirm helper

Sub-Plan 3b-2 Task 3. Initiator-side per-round helper: generates 16-byte Na_i,
computes Ca_i = f4(PKax, PKbx, Na_i, 0x80|bit_i) with bit_i =
(passkey >> (20-i)) & 1 (MSB-first), sends Pairing_Confirm."
```

---

## Task 4: `_sc_passkey_recv_peer_confirm` (reflexive PAIRING_CONFIRM_RX)

**Files:**
- Modify: `pybluehost/ble/_smp_state.py` (add action)
- Test: `tests/unit/ble/test_smp_passkey_sc.py`

- [ ] **Step 1: Append failing tests**

```python
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
    """Responder receives Ca_i → computes Cb_i = f4(PKbx, PKax, Nb_i, 0x80|bit_i) → sends."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole

    captured_args: list = []

    def _stub_f4(U, V, X, Z):
        captured_args.append((U, V, X, Z))
        return b"\xcb" * 16

    monkeypatch.setattr(state_mod.SMPCrypto, "f4", staticmethod(_stub_f4))

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
    # f4 called with (PKbx, PKax, Nb, 0x81)
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
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_sc.py -k "recv_peer_confirm" -v`
Expected: FAIL — `_sc_passkey_recv_peer_confirm` does not exist.

- [ ] **Step 3: Implement**

Add to `pybluehost/ble/_smp_state.py`, immediately after `_sc_passkey_send_round_confirm`:

```python
async def _sc_passkey_recv_peer_confirm(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Passkey reflexive transition: PAIRING_CONFIRM_RX while in PASSKEY_SC_ROUND.

    Initiator: stash peer_confirm, send Pairing_Random with Na_i (generated earlier).
    Responder: stash peer_confirm, compute Cb_i = f4(PKbx, PKax, Nb_i, 0x80|bit_i), send.
    Either way, advance subphase to AWAIT_PEER_RANDOM.
    """
    from pybluehost.ble.smp import PairingRole, SMPPairingConfirm, SMPPairingRandom
    if ctx.passkey_round_phase != "AWAIT_PEER_CONFIRM":
        await _on_failed(ctx, reason=0x08)
        return
    ctx.passkey_peer_confirm = pdu.confirm_value
    if ctx.role == PairingRole.INITIATOR:
        # Initiator already has Na_i from _sc_passkey_send_round_confirm; reveal it now.
        await ctx.send(SMPPairingRandom(random_value=ctx.passkey_local_random).to_bytes())
    else:
        # Responder: compute Cb_i with own Nb_i.
        i = ctx.passkey_round
        bit = (ctx.passkey >> (20 - i)) & 1
        ctx.passkey_local_random = os.urandom(16)
        pkax = ctx.peer_public_key[:32]   # Initiator's
        pkbx = ctx.local_public_key[:32]  # Responder's
        ctx.passkey_local_confirm = SMPCrypto.f4(pkbx, pkax, ctx.passkey_local_random, 0x80 | bit)
        await ctx.send(SMPPairingConfirm(confirm_value=ctx.passkey_local_confirm).to_bytes())
    ctx.passkey_round_phase = "AWAIT_PEER_RANDOM"
```

- [ ] **Step 4: Run tests**

`uv run pytest tests/unit/ble/test_smp_passkey_sc.py -k "recv_peer_confirm" -v` — expect 3 PASS.
`uv run pytest tests/unit/ble/ -q` — expect no regressions.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/ble/_smp_state.py tests/unit/ble/test_smp_passkey_sc.py
git commit -m "feat(ble/smp): _sc_passkey_recv_peer_confirm action

Sub-Plan 3b-2 Task 4. Reflexive PASSKEY_SC_ROUND + PAIRING_CONFIRM_RX action.
Initiator sends Pairing_Random with Na_i. Responder computes own Cb_i and
sends Pairing_Confirm. Both advance subphase to AWAIT_PEER_RANDOM.
Wrong-subphase event → FAILED(0x08)."
```

---

## Task 5: `_sc_passkey_recv_peer_random` + exit hooks

**Files:**
- Modify: `pybluehost/ble/_smp_state.py` (add action + exit helpers)
- Test: `tests/unit/ble/test_smp_passkey_sc.py`

- [ ] **Step 1: Append failing tests**

```python
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

    monkeypatch.setattr(state_mod.SMPCrypto, "f4", staticmethod(_stub_f4))

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

    monkeypatch.setattr(state_mod.SMPCrypto, "f4", staticmethod(_stub_f4))

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
    """Cb verification mismatch → FAILED(0x04)."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole

    monkeypatch.setattr(state_mod.SMPCrypto, "f4",
                        staticmethod(lambda *a, **k: b"\xff" * 16))   # not what's stashed

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

    monkeypatch.setattr(state_mod.SMPCrypto, "f4",
                        staticmethod(lambda *a, **k: b"\xcc" * 16))

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

    monkeypatch.setattr(state_mod.SMPCrypto, "f4",
                        staticmethod(lambda *a, **k: b"\xaa" * 16))

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
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_sc.py -k "recv_peer_random" -v`
Expected: FAIL — `_sc_passkey_recv_peer_random` and exit helpers do not exist.

- [ ] **Step 3: Implement action + exit helpers**

In `pybluehost/ble/_smp_state.py`, add immediately after `_sc_passkey_recv_peer_confirm`:

```python
async def _sc_passkey_recv_peer_random(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Passkey reflexive transition: PAIRING_RANDOM_RX while in PASSKEY_SC_ROUND.

    Verify peer's Confirm matches f4 over their just-revealed Random and the
    current bit. On match, advance round or exit; on mismatch, FAILED(0x04).
    Wrong subphase → FAILED(0x08).
    """
    from pybluehost.ble.smp import PairingRole, SMPPairingRandom
    if ctx.passkey_round_phase != "AWAIT_PEER_RANDOM":
        await _on_failed(ctx, reason=0x08)
        return
    ctx.passkey_peer_random = pdu.random_value
    i = ctx.passkey_round
    bit = (ctx.passkey >> (20 - i)) & 1

    if ctx.role == PairingRole.INITIATOR:
        # Verify Cb_i = f4(PKbx, PKax, Nb_i, 0x80|bit)
        pkax = ctx.local_public_key[:32]
        pkbx = ctx.peer_public_key[:32]
        expected = SMPCrypto.f4(pkbx, pkax, ctx.passkey_peer_random, 0x80 | bit)
        if expected != ctx.passkey_peer_confirm:
            await _on_failed(ctx, reason=0x04)
            return
        if i < 20:
            ctx.passkey_round = i + 1
            ctx.passkey_round_phase = "AWAIT_PEER_CONFIRM"
            await _sc_passkey_send_round_confirm(ctx)
        else:
            ctx.local_random = ctx.passkey_local_random   # Na_20
            ctx.peer_random = ctx.passkey_peer_random     # Nb_20
            await _sc_passkey_exit_to_dhkey_check_initiator(ctx)
    else:
        # Responder: verify Ca_i = f4(PKax, PKbx, Na_i, 0x80|bit), then send Nb_i.
        pkax = ctx.peer_public_key[:32]
        pkbx = ctx.local_public_key[:32]
        expected = SMPCrypto.f4(pkax, pkbx, ctx.passkey_peer_random, 0x80 | bit)
        if expected != ctx.passkey_peer_confirm:
            await _on_failed(ctx, reason=0x04)
            return
        await ctx.send(SMPPairingRandom(random_value=ctx.passkey_local_random).to_bytes())
        if i < 20:
            ctx.passkey_round = i + 1
            ctx.passkey_round_phase = "AWAIT_PEER_CONFIRM"
        else:
            ctx.peer_random = ctx.passkey_peer_random     # Na_20
            ctx.local_random = ctx.passkey_local_random   # Nb_20
            await _sc_passkey_exit_to_random_exchange_responder(ctx)


async def _sc_passkey_exit_to_dhkey_check_initiator(ctx: "SMPPairingContext") -> None:
    """Initiator exit after round 20: derive f5, call existing _sc_send_dhkey_check_initiator.

    _sc_send_dhkey_check_initiator (Sub-Plan 2) sends Ea and sets state to DHKEY_CHECK.
    """
    local_addr = _local_address_bytes(ctx)
    peer_addr = _peer_address_bytes(ctx)
    a1 = b"\x00" + local_addr
    a2 = b"\x00" + peer_addr
    mac_key, ltk = SMPCrypto.f5(ctx.dhkey, ctx.local_random, ctx.peer_random, a1, a2)
    ctx.mac_key = mac_key
    ctx.ltk_sc = ltk
    await _sc_send_dhkey_check_initiator(ctx)


async def _sc_passkey_exit_to_random_exchange_responder(ctx: "SMPPairingContext") -> None:
    """Responder exit after round 20: derive f5, state -> RANDOM_EXCHANGE.

    The existing RANDOM_EXCHANGE + PAIRING_DHKEY_CHECK_RX transition handles
    Initiator's incoming Ea. No PDU sent here.
    """
    local_addr = _local_address_bytes(ctx)
    peer_addr = _peer_address_bytes(ctx)
    a1 = b"\x00" + peer_addr   # Initiator = peer
    a2 = b"\x00" + local_addr  # Responder = local
    mac_key, ltk = SMPCrypto.f5(ctx.dhkey, ctx.peer_random, ctx.local_random, a1, a2)
    ctx.mac_key = mac_key
    ctx.ltk_sc = ltk
    ctx.state_machine._state = SMPState.RANDOM_EXCHANGE
```

- [ ] **Step 4: Run tests**

`uv run pytest tests/unit/ble/test_smp_passkey_sc.py -k "recv_peer_random" -v` — expect 5 PASS.
`uv run pytest tests/unit/ble/ -q` — expect no regressions.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/ble/_smp_state.py tests/unit/ble/test_smp_passkey_sc.py
git commit -m "feat(ble/smp): _sc_passkey_recv_peer_random + round-20 exit helpers

Sub-Plan 3b-2 Task 5. Reflexive PASSKEY_SC_ROUND + PAIRING_RANDOM_RX action.
Verifies peer's Confirm against revealed Random+bit; on match advances round
(<20) or exits (=20). Initiator exit derives f5 and sends Ea (reuses Sub-Plan 2
_sc_send_dhkey_check_initiator). Responder exit derives f5 and sets state to
RANDOM_EXCHANGE for the existing PAIRING_DHKEY_CHECK_RX transition. f4
mismatch → FAILED(0x04); wrong subphase → FAILED(0x08)."
```

---

## Task 6: Branch SC pubkey-handlers + Display-side enter helpers

**Files:**
- Modify: `pybluehost/ble/_smp_state.py` (`_sc_initiator_recv_peer_public_key`, `_sc_responder_recv_peer_public_key`; add enter helpers)
- Test: `tests/unit/ble/test_smp_passkey_sc.py`

- [ ] **Step 1: Append failing tests**

```python
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
    monkeypatch.setattr(state_mod.SMPCrypto, "f4",
                        staticmethod(lambda *a, **k: b"\xaa" * 16))

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
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_sc.py -k "sc_initiator_pubkey_passkey or sc_responder_pubkey_passkey" -v`
Expected: FAIL — current handlers don't branch on Passkey.

- [ ] **Step 3: Add enter helpers + branch the pubkey handlers**

A) Add Initiator + Responder Display enter helpers to `pybluehost/ble/_smp_state.py`, near the other passkey helpers:

```python
async def _sc_passkey_initiator_display_enter(ctx: "SMPPairingContext") -> None:
    """Initiator Display: resolve passkey, display, send Ca_1, state -> PASSKEY_SC_ROUND."""
    ctx.passkey = await _passkey_resolve_display_value(ctx)
    delegate = getattr(ctx, "_delegate", None)
    if delegate is not None:
        try:
            await delegate.display_passkey(ctx.peer_address, ctx.passkey)
        except Exception as exc:  # noqa: BLE001
            logger.warning("delegate.display_passkey raised: %s; proceeding", exc)
    ctx.passkey_round = 1
    ctx.passkey_round_phase = "AWAIT_PEER_CONFIRM"
    ctx.state_machine._state = SMPState.PASSKEY_SC_ROUND
    await _sc_passkey_send_round_confirm(ctx)


async def _sc_passkey_responder_display_enter(ctx: "SMPPairingContext") -> None:
    """Responder Display: resolve passkey, display, state -> PASSKEY_SC_ROUND (no PDU)."""
    ctx.passkey = await _passkey_resolve_display_value(ctx)
    delegate = getattr(ctx, "_delegate", None)
    if delegate is not None:
        try:
            await delegate.display_passkey(ctx.peer_address, ctx.passkey)
        except Exception as exc:  # noqa: BLE001
            logger.warning("delegate.display_passkey raised: %s; proceeding", exc)
    ctx.passkey_round = 1
    ctx.passkey_round_phase = "AWAIT_PEER_CONFIRM"
    ctx.state_machine._state = SMPState.PASSKEY_SC_ROUND
```

Note: `_passkey_resolve_display_value` is async (returns int via `await`) — added as async in Sub-Plan 3b-1 Task 8 wiring fix.

B) Replace `_sc_initiator_recv_peer_public_key` (around line 536) with the branched version:

```python
async def _sc_initiator_recv_peer_public_key(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Initiator: peer's Public Key arrived → compute DHKey.

    For Just Works / NC: stay in PUBLIC_KEY_EXCHANGE (await Responder's Confirm).
    For SC Passkey Display: enter PASSKEY_SC_ROUND and send Ca_1.
    For SC Passkey Input: enter PASSKEY_INPUT_PENDING and spawn delegate task.
    """
    from pybluehost.ble._smp_sc_crypto import compute_dhkey
    ctx.peer_public_key = pdu.public_key_x + pdu.public_key_y
    ctx.dhkey = compute_dhkey(ctx.local_private_key, ctx.peer_public_key)

    if _association_model(ctx) == "passkey_entry":
        if _passkey_local_role(ctx) == "display":
            await _sc_passkey_initiator_display_enter(ctx)
        else:
            ctx.state_machine._state = SMPState.PASSKEY_INPUT_PENDING
            await _passkey_await_user_input(ctx)
```

C) Replace `_sc_responder_recv_peer_public_key` (around line 547) — note the existing version sends own pubkey AND a Pairing_Confirm with Cb (for NC/JW). For Passkey we still send own pubkey but skip the Cb:

```python
async def _sc_responder_recv_peer_public_key(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Responder: Initiator's Public Key arrived.

    All paths: store peer pubkey, generate own keypair, send own pubkey, compute DHKey.
    For Just Works / NC: also generate Nb + Cb = f4(PKbx, PKax, Nb, 0) and send Pairing_Confirm.
    For SC Passkey Display: enter PASSKEY_SC_ROUND (no Cb send).
    For SC Passkey Input: enter PASSKEY_INPUT_PENDING (no Cb send).
    """
    import os
    from pybluehost.ble._smp_sc_crypto import compute_dhkey, generate_p256_keypair
    from pybluehost.ble.smp import SMPPairingConfirm, SMPPairingPublicKey

    ctx.peer_public_key = pdu.public_key_x + pdu.public_key_y
    priv, pub = generate_p256_keypair()
    ctx.local_private_key = priv
    ctx.local_public_key = pub
    await ctx.send(SMPPairingPublicKey(
        public_key_x=pub[:32], public_key_y=pub[32:],
    ).to_bytes())
    ctx.dhkey = compute_dhkey(priv, ctx.peer_public_key)

    model = _association_model(ctx)
    if model == "passkey_entry":
        if _passkey_local_role(ctx) == "display":
            await _sc_passkey_responder_display_enter(ctx)
        else:
            ctx.state_machine._state = SMPState.PASSKEY_INPUT_PENDING
            await _passkey_await_user_input(ctx)
        return

    # Just Works / NC: generate Nb, send Cb (existing behavior)
    ctx.local_random = os.urandom(16)
    pkbx = ctx.local_public_key[:32]
    pkax = ctx.peer_public_key[:32]
    ctx.local_confirm = SMPCrypto.f4(pkbx, pkax, ctx.local_random, 0)
    await ctx.send(SMPPairingConfirm(confirm_value=ctx.local_confirm).to_bytes())
```

- [ ] **Step 4: Run tests**

`uv run pytest tests/unit/ble/test_smp_passkey_sc.py -v` — expect all PASS.
`uv run pytest tests/unit/ble/ -q` — expect no regressions (Sub-Plan 3a SC NC and Sub-Plan 2 SC Just Works tests still pass).
`uv run pytest tests/integration/test_pairing_le_sc_loopback.py tests/integration/test_pairing_le_sc_nc_loopback.py -v` — both SC loopback integration tests still pass.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/ble/_smp_state.py tests/unit/ble/test_smp_passkey_sc.py
git commit -m "feat(ble/smp): branch SC pubkey handlers on Passkey role

Sub-Plan 3b-2 Task 6. _sc_initiator_recv_peer_public_key and
_sc_responder_recv_peer_public_key now branch on _association_model +
_passkey_local_role: Display side resolves passkey, displays, enters
PASSKEY_SC_ROUND (Initiator also sends Ca_1); Input side enters
PASSKEY_INPUT_PENDING and spawns delegate. JW / NC paths unchanged.
Responder Display correctly skips the Just-Works Cb send."
```

---

## Task 7: Extend `_passkey_user_entered` SC branch + register `PASSKEY_SC_ROUND` transitions

**Files:**
- Modify: `pybluehost/ble/_smp_state.py` (`_passkey_user_entered` + `register_transitions`)
- Test: `tests/unit/ble/test_smp_passkey_sc.py`

- [ ] **Step 1: Append failing tests**

```python
@pytest.mark.asyncio
async def test_passkey_user_entered_sc_initiator_sends_round1_confirm(monkeypatch):
    """SC Initiator + PASSKEY_USER_ENTERED → state PASSKEY_SC_ROUND + Ca_1 sent."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import PairingRole, SMPState

    monkeypatch.setattr(state_mod, "_sc_negotiated", lambda _ctx: True)
    monkeypatch.setattr(state_mod.SMPCrypto, "f4",
                        staticmethod(lambda *a, **k: b"\xaa" * 16))

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
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_sc.py -k "passkey_user_entered_sc or passkey_sc_round_transitions" -v`
Expected: FAIL — SC branch missing from `_passkey_user_entered`; transitions not registered.

- [ ] **Step 3: Extend `_passkey_user_entered`**

In `pybluehost/ble/_smp_state.py`, locate `_passkey_user_entered` (added in Sub-Plan 3b-1 Task 5). Add an SC branch at the top:

```python
async def _passkey_user_entered(ctx: "SMPPairingContext", **_kw) -> None:
    """Input-side helper: user entered passkey → next phase.

    SC (Sub-Plan 3b-2): state -> PASSKEY_SC_ROUND, round=1; Initiator sends Ca_1.
    Legacy (Sub-Plan 3b-1): set TK, compute c1, send Pairing_Confirm, stay in CONFIRMING.
    """
    from pybluehost.ble.smp import PairingRole, SMPPairingConfirm
    if _sc_negotiated(ctx):
        ctx.state_machine._state = SMPState.PASSKEY_SC_ROUND
        ctx.passkey_round = 1
        ctx.passkey_round_phase = "AWAIT_PEER_CONFIRM"
        if ctx.role == PairingRole.INITIATOR:
            await _sc_passkey_send_round_confirm(ctx)
        return
    # Legacy path — unchanged from Sub-Plan 3b-1
    ctx.tk = ctx.passkey.to_bytes(16, "little")
    ctx.local_random = os.urandom(16)
    preq, pres, iat, rat, ia, ra = _build_c1_params(ctx)
    ctx.local_confirm = SMPCrypto.c1(
        ctx.tk, ctx.local_random, preq, pres, iat, rat, ia, ra,
    )
    await ctx.send(SMPPairingConfirm(confirm_value=ctx.local_confirm).to_bytes())
```

- [ ] **Step 4: Register `PASSKEY_SC_ROUND` transitions + timeout + universal failure**

In `register_transitions` (around line 184 where the existing PASSKEY_INPUT_PENDING block lives), add the PASSKEY_SC_ROUND transitions immediately after:

```python
    # ---- Sub-Plan 3b-2 — SC Passkey Entry per-round transitions ----
    sm.add_transition(
        SMPState.PASSKEY_SC_ROUND, SMPEvent.PAIRING_CONFIRM_RX,
        SMPState.PASSKEY_SC_ROUND,
        action=lambda **kw: _sc_passkey_recv_peer_confirm(ctx, **kw),
    )
    sm.add_transition(
        SMPState.PASSKEY_SC_ROUND, SMPEvent.PAIRING_RANDOM_RX,
        SMPState.PASSKEY_SC_ROUND,
        action=lambda **kw: _sc_passkey_recv_peer_random(ctx, **kw),
    )
```

In the Phase-2 timeout block (around line 237 where `set_timeout` calls live), add:

```python
    sm.set_timeout(SMPState.PASSKEY_SC_ROUND, 60.0, SMPEvent.TIMEOUT)
```

In the universal-failure tuple (around line 240-244, where `NUMERIC_COMPARE_PENDING` and `PASSKEY_INPUT_PENDING` are listed), add `PASSKEY_SC_ROUND`:

```python
    for state in (
        SMPState.IDLE, SMPState.FEATURE_EXCHANGE, SMPState.CONFIRMING,
        SMPState.RANDOM_EXCHANGE, SMPState.STK_ENCRYPTING, SMPState.KEY_DISTRIBUTION,
        SMPState.PUBLIC_KEY_EXCHANGE, SMPState.DHKEY_CHECK,
        SMPState.NUMERIC_COMPARE_PENDING,
        SMPState.PASSKEY_INPUT_PENDING,
        SMPState.PASSKEY_SC_ROUND,
    ):
        ...
```

- [ ] **Step 5: Run tests**

`uv run pytest tests/unit/ble/test_smp_passkey_sc.py -v` — expect all PASS.
`uv run pytest tests/unit/ble/ -q` — expect no regressions.
`uv run pytest tests/integration/test_pairing_le_sc_loopback.py tests/integration/test_pairing_le_sc_nc_loopback.py tests/integration/test_pairing_legacy_passkey_loopback.py -v` — all prior loopback tests still pass.

- [ ] **Step 6: Commit**

```bash
git add pybluehost/ble/_smp_state.py tests/unit/ble/test_smp_passkey_sc.py
git commit -m "feat(ble/smp): wire PASSKEY_SC_ROUND into state machine

Sub-Plan 3b-2 Task 7. _passkey_user_entered now branches on _sc_negotiated:
SC path transitions to PASSKEY_SC_ROUND with round=1 (Initiator sends Ca_1).
Legacy path unchanged (Sub-Plan 3b-1). register_transitions adds the two
reflexive transitions on PASSKEY_SC_ROUND (PAIRING_CONFIRM_RX +
PAIRING_RANDOM_RX), 60s timeout, and universal-failure-loop inclusion."
```

---

## Task 8: Loopback E2E + STATUS.md

**Files:**
- Create: `tests/integration/test_pairing_sc_passkey_loopback.py`
- Modify: `docs/superpowers/STATUS.md`

- [ ] **Step 1: Write the E2E tests**

Create `tests/integration/test_pairing_sc_passkey_loopback.py`:

```python
"""End-to-end SC Passkey Entry pairing via VirtualLELink."""
from __future__ import annotations

import asyncio

import pytest

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import AutoAcceptDelegate, JsonBondStorage
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability
from pybluehost.hci.virtual_link import VirtualLELink
from pybluehost.stack import Stack, StackConfig


class _FixedPasskeyDelegate(AutoAcceptDelegate):
    """Returns a pre-set passkey value for both display and input."""

    def __init__(self, passkey: int):
        self.passkey = passkey
        self.displayed: list = []

    async def display_passkey(self, peer_addr, passkey):
        self.displayed.append((peer_addr, passkey))

    async def get_passkey(self, peer_addr):
        return self.passkey


def _sc_passkey_config(storage, *, io_cap):
    return StackConfig(
        bond_storage=storage,
        security=SecurityConfig(
            enable_secure_connections=True,
            mitm_required=True,
        ),
        le_io_capability=io_cap,
    )


async def test_sc_passkey_pair_succeeds_with_matching_delegates(tmp_path):
    """Display side (Central=DisplayYesNo) + Input side (Peripheral=KeyboardOnly).
    Both delegates carry the same passkey → 20 rounds complete; bond authenticated, sc=True."""
    storage_a = JsonBondStorage(tmp_path / "bonds_a.json")
    storage_b = JsonBondStorage(tmp_path / "bonds_b.json")
    central = BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A")
    peripheral = BDAddress(b"\x0B\x0B\x0B\x0B\x0B\x0B")

    cfg_a = _sc_passkey_config(storage_a, io_cap=IOCapability.DISPLAY_YES_NO)
    cfg_b = _sc_passkey_config(storage_b, io_cap=IOCapability.KEYBOARD_ONLY)

    stack_a = await Stack.virtual(config=cfg_a, address=central)
    stack_b = await Stack.virtual(config=cfg_b, address=peripheral)
    stack_a._smp.set_delegate(_FixedPasskeyDelegate(passkey=314159))
    stack_b._smp.set_delegate(_FixedPasskeyDelegate(passkey=314159))

    link = VirtualLELink(
        central=stack_a._virtual_controller,
        peripheral=stack_b._virtual_controller,
        central_address=central,
        peripheral_address=peripheral,
    )
    handle = await link.connect()
    await asyncio.sleep(0.1)
    await stack_a.pair(handle=handle, timeout=20.0)

    bond_a = await storage_a.load_bond(peripheral)
    bond_b = await storage_b.load_bond(central)
    assert bond_a is not None and bond_a.sc is True
    assert bond_b is not None and bond_b.sc is True
    # SC Passkey → authenticated=True on both sides
    assert bond_a.authenticated is True
    assert bond_b.authenticated is True
    # f5-derived LTK matches
    assert bond_a.ltk == bond_b.ltk

    await link.disconnect()
    await stack_a.close()
    await stack_b.close()


async def test_sc_passkey_pair_fails_on_wrong_passkey(tmp_path):
    """Mismatched passkeys → round-1 f4 verification fails → pair() raises reason=0x04."""
    storage_a = JsonBondStorage(tmp_path / "bonds_a.json")
    storage_b = JsonBondStorage(tmp_path / "bonds_b.json")
    central = BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A")
    peripheral = BDAddress(b"\x0B\x0B\x0B\x0B\x0B\x0B")

    cfg_a = _sc_passkey_config(storage_a, io_cap=IOCapability.DISPLAY_YES_NO)
    cfg_b = _sc_passkey_config(storage_b, io_cap=IOCapability.KEYBOARD_ONLY)

    stack_a = await Stack.virtual(config=cfg_a, address=central)
    stack_b = await Stack.virtual(config=cfg_b, address=peripheral)
    stack_a._smp.set_delegate(_FixedPasskeyDelegate(passkey=111111))
    stack_b._smp.set_delegate(_FixedPasskeyDelegate(passkey=999999))

    link = VirtualLELink(
        central=stack_a._virtual_controller,
        peripheral=stack_b._virtual_controller,
        central_address=central,
        peripheral_address=peripheral,
    )
    handle = await link.connect()
    await asyncio.sleep(0.1)
    with pytest.raises(Exception):
        await stack_a.pair(handle=handle, timeout=10.0)

    await link.disconnect()
    await stack_a.close()
    await stack_b.close()
```

- [ ] **Step 2: Run the E2E tests**

`uv run pytest tests/integration/test_pairing_sc_passkey_loopback.py -v`

Expected: both PASS.

Debug guide if they don't:

- **Success test fails with bond.authenticated=False**: trace `_association_model` invocation — confirm both sides advertise SC bit + MITM bit; confirm `_passkey_capable(DisplayYesNo, KeyboardOnly)` returns True; confirm `_passkey_local_role` returns "display" on Initiator and "input" on Responder.
- **pair() times out or hangs**: trace round counter / subphase. Add temporary `print(f"round={ctx.passkey_round} phase={ctx.passkey_round_phase} role={ctx.role}")` at the top of `_sc_passkey_recv_peer_confirm` and `_sc_passkey_recv_peer_random`. The expected sequence is 20 rounds × 4 messages each.
- **Failure test doesn't raise**: confirm round-1 f4 verification mismatch surfaces as `_on_failed(0x04)`. Race: if Initiator already sent Ca_1 with wrong bit AND Responder happens to send Cb_1 with the wrong corresponding bit on the same first divergent bit, the Initiator's verification (round 1 PAIRING_RANDOM_RX action) is where mismatch is detected. The `Pairing_Failed` reaches the other side via PAIRING_FAILED_RX universal transition.

You have permission to debug Passkey-adjacent wiring issues. Stay scoped to SC Passkey integration.

- [ ] **Step 3: Run full suite for regressions**

`uv run pytest tests/ -q`
Expected: only the 3 pre-existing USB-diagnostics failures.

- [ ] **Step 4: Update STATUS.md**

Read `docs/superpowers/STATUS.md`. Apply these edits:
- Top "**当前进行中**" line: mark Sub-Plan 3b-2 ✅ complete. "**下一步**" list: drop 3b-2; keep 3c / 重连闭环 / e2e.
- At the end of the Plan-progress table, add a row for Sub-Plan 3b-2 with date 2026-05-19, plan link, and touched paths.
- Increment "总计：N 个 Plan" by one.
- Add a dedicated detailed-progress section near the existing Sub-Plan 3a / 3b-1 sections.

Surgical edits, match surrounding markdown style.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_pairing_sc_passkey_loopback.py docs/superpowers/STATUS.md
git commit -m "test(integration): SC Passkey Entry loopback E2E

Sub-Plan 3b-2 Task 8. Two Stack.virtual() instances with mitm_required=True,
enable_secure_connections=True, DisplayYesNo×KeyboardOnly IO caps, matching
_FixedPasskeyDelegate → 20 rounds of f4 commits complete; bonds end up
authenticated=True, sc=True; identical f5-derived LTKs. Mismatched passkey
→ round-1 f4 mismatch → pair() raises reason=4. Marks Sub-Plan 3b-2 complete
in STATUS.md."
```

---

## Acceptance Checklist

- [ ] `SMPState.PASSKEY_SC_ROUND = 12` exists.
- [ ] `_association_model` returns `"passkey_entry"` for SC + MITM + in-scope IO pairs.
- [ ] `_association_model` returns `"numeric_comparison"` (not Passkey) for DYN×DYN, DYN×KbD, KbD×KbD.
- [ ] `_sc_passkey_send_round_confirm`: generates 16-byte Na/Nb, computes f4 with `0x80|bit_i` (MSB-first), sends `Pairing_Confirm`.
- [ ] `_sc_passkey_recv_peer_confirm`: Initiator sends Pairing_Random; Responder computes and sends own Confirm. Wrong subphase → FAILED(0x08).
- [ ] `_sc_passkey_recv_peer_random`: f4 verification; on match advance round or exit; on mismatch FAILED(0x04). Wrong subphase → FAILED(0x08).
- [ ] Round 20 exit Initiator: derives f5, calls `_sc_send_dhkey_check_initiator`.
- [ ] Round 20 exit Responder: derives f5, sets state to `RANDOM_EXCHANGE`.
- [ ] `_sc_initiator_recv_peer_public_key` branches on Passkey role: Display enters PASSKEY_SC_ROUND + sends Ca_1; Input enters PASSKEY_INPUT_PENDING.
- [ ] `_sc_responder_recv_peer_public_key` branches on Passkey role: Display enters PASSKEY_SC_ROUND (skips JW Cb send); Input enters PASSKEY_INPUT_PENDING.
- [ ] `_passkey_user_entered` SC branch transitions to PASSKEY_SC_ROUND; Initiator sends Ca_1.
- [ ] `PASSKEY_SC_ROUND` reflexive transitions registered + 60s timeout + universal-failure inclusion.
- [ ] Loopback E2E: matching passkey → authenticated SC bond, matching LTKs; mismatched → pair() raises reason=4.
- [ ] Full suite green minus pre-existing USB-diagnostics failures.
- [ ] STATUS.md updated to mark Sub-Plan 3b-2 ✅.

## Out of Scope (deferred)

| Item | Future Plan |
|---|---|
| OOB (Legacy + SC) | Sub-Plan 3c |
| Both-KeyboardOnly IO pair | None — falls through to JW |
| BR/EDR Passkey Entry SSP | Independent Plan |
| Real-hardware verification with phone | Independent Plan |
| Spec test-vector cross-check (Vol 6 Part C §7.2.3) | Optional follow-up |
