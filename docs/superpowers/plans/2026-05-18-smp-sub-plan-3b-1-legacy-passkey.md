# SMP Sub-Plan 3b-1 — Legacy Passkey Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Legacy (non-SC) Passkey Entry association model: a 6-digit passkey replaces the all-zero TK used by Just Works, providing MITM-protected pairing for IO-capability pairs that include at least one display and at least one keyboard.

**Architecture:** Selection extends `_association_model()` to return `"passkey_entry"` for in-scope Legacy IO×MITM combinations. The existing Phase-1→Phase-2 actions (`_initiator_recv_pairing_response`, `_responder_recv_pairing_request`) gain a Passkey branch that either generates+displays the passkey (Display role) and proceeds inline, or enters a new `PASSKEY_INPUT_PENDING` state and awaits `delegate.get_passkey` (Input role). Peer Confirm arriving during input is buffered. Everything downstream (c1, s1, STK, key distribution, reconnection) is unchanged.

**Tech Stack:** Python 3.10+, asyncio, pytest, `secrets.randbelow` (stdlib) for passkey generation, existing `pybluehost.core.statemachine.StateMachine`, existing `VirtualLELink` for loopback tests.

**Design spec:** [`docs/superpowers/specs/2026-05-18-smp-sub-plan-3b-1-legacy-passkey-design.md`](../specs/2026-05-18-smp-sub-plan-3b-1-legacy-passkey-design.md)

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Modify | `pybluehost/ble/smp.py` | Add `SMPState.PASSKEY_INPUT_PENDING` (=11); add `SMPEvent.PASSKEY_USER_ENTERED` (=20), `SMPEvent.PASSKEY_USER_REJECTED` (=21); rename `display_passkey(passkey)` → `display_passkey(peer_addr, passkey)`, `get_passkey()` → `get_passkey(peer_addr)`, `confirm_passkey(passkey)` → `confirm_passkey(peer_addr, passkey)` on `PairingDelegate` and `AutoAcceptDelegate` |
| Modify | `pybluehost/ble/_smp_state.py` | Add `_passkey_capable`; add `_passkey_local_role`; extend `_association_model`; add `_passkey_await_user_input`; add `_passkey_buffer_peer_confirm` and `_passkey_user_entered` actions; register PASSKEY_INPUT_PENDING transitions + 60 s timeout + universal-failure inclusion; branch `_initiator_recv_pairing_response` and `_responder_recv_pairing_request` on association model; extend `_persist_bond` Legacy branch to mark `authenticated=True` for passkey_entry |
| Create | `tests/unit/ble/test_smp_passkey_legacy.py` | Selection + role + state-transition unit tests (~12) |
| Create | `tests/integration/test_pairing_legacy_passkey_loopback.py` | Two-stack loopback: success path (matching passkey) + wrong-passkey-fails path |
| Modify | `docs/superpowers/STATUS.md` | Mark Sub-Plan 3b-1 complete |

---

## Task 1: Normalize PairingDelegate Passkey methods

**Files:**
- Modify: `pybluehost/ble/smp.py` (`PairingDelegate` Protocol around lines 601-609; `AutoAcceptDelegate` around lines 611-627)
- Test: `tests/unit/ble/test_smp_passkey_legacy.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/ble/test_smp_passkey_legacy.py`:

```python
"""Tests for SMP Legacy Passkey Entry (Sub-Plan 3b-1)."""
from __future__ import annotations

import pytest

from pybluehost.ble.smp import AutoAcceptDelegate, PairingDelegate
from pybluehost.core.address import BDAddress


@pytest.mark.asyncio
async def test_auto_accept_display_passkey_accepts_peer_addr():
    d = AutoAcceptDelegate()
    addr = BDAddress(bytes(6))
    # Must accept (peer_addr, passkey) signature without raising.
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_legacy.py -v`
Expected: 3 async tests FAIL with TypeError (existing methods don't accept `peer_addr`).

- [ ] **Step 3: Rename method signatures**

In `pybluehost/ble/smp.py` (around lines 601-627), replace `PairingDelegate` and `AutoAcceptDelegate`:

```python
class PairingDelegate(Protocol):
    """User interaction interface for SMP pairing decisions."""

    async def confirm_pairing(self, handle: int, io_cap: int) -> bool: ...
    async def confirm_passkey(self, peer_addr: BDAddress, passkey: int) -> bool: ...
    async def confirm_numeric(self, peer_addr: BDAddress, value: int) -> bool: ...
    async def get_passkey(self, peer_addr: BDAddress) -> int: ...
    async def display_passkey(self, peer_addr: BDAddress, passkey: int) -> None: ...


class AutoAcceptDelegate:
    """Default delegate that auto-accepts everything (for testing)."""

    async def confirm_pairing(self, handle: int, io_cap: int) -> bool:
        return True

    async def confirm_passkey(self, peer_addr: BDAddress, passkey: int) -> bool:
        return True

    async def confirm_numeric(self, peer_addr: BDAddress, value: int) -> bool:
        return True

    async def get_passkey(self, peer_addr: BDAddress) -> int:
        return 0

    async def display_passkey(self, peer_addr: BDAddress, passkey: int) -> None:
        pass
```

`BDAddress` is already imported at `pybluehost/ble/smp.py:14`. No new imports needed.

- [ ] **Step 4: Update any stale callers**

Run: `grep -rn "display_passkey\|get_passkey\|confirm_passkey" pybluehost/ tests/`

If any non-test callers exist with the old signature, update them to the new `peer_addr` form. (Expect zero production callers — these methods are placeholders.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_legacy.py -v`
Expected: 4 PASS.

Run: `uv run pytest tests/unit/ble/ -q`
Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add pybluehost/ble/smp.py tests/unit/ble/test_smp_passkey_legacy.py
git commit -m "feat(ble/smp): normalize Passkey delegate methods to include peer_addr

Sub-Plan 3b-1 Task 1. display_passkey, get_passkey, and confirm_passkey on
PairingDelegate and AutoAcceptDelegate now take peer_addr as first param,
matching the confirm_numeric precedent from Sub-Plan 3a."
```

---

## Task 2: SMPState.PASSKEY_INPUT_PENDING + NC events

**Files:**
- Modify: `pybluehost/ble/smp.py` (`SMPState` and `SMPEvent` IntEnums)
- Test: `tests/unit/ble/test_smp_passkey_legacy.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/ble/test_smp_passkey_legacy.py`:

```python
from pybluehost.ble.smp import SMPEvent, SMPState


def test_smp_state_passkey_input_pending_exists():
    assert SMPState.PASSKEY_INPUT_PENDING == 11


def test_smp_event_passkey_values():
    assert SMPEvent.PASSKEY_USER_ENTERED == 20
    assert SMPEvent.PASSKEY_USER_REJECTED == 21
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_legacy.py::test_smp_state_passkey_input_pending_exists tests/unit/ble/test_smp_passkey_legacy.py::test_smp_event_passkey_values -v`
Expected: FAIL with AttributeError on enum members.

- [ ] **Step 3: Add enum values**

In `pybluehost/ble/smp.py`, add to `SMPState` (immediately after `NUMERIC_COMPARE_PENDING = 10`):

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
```

And to `SMPEvent` (immediately after `NUMERIC_COMPARE_USER_REJECTED = 19`):

```python
    NUMERIC_COMPARE_USER_CONFIRMED = 18
    NUMERIC_COMPARE_USER_REJECTED = 19
    PASSKEY_USER_ENTERED = 20
    PASSKEY_USER_REJECTED = 21
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_legacy.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/ble/smp.py tests/unit/ble/test_smp_passkey_legacy.py
git commit -m "feat(ble/smp): SMPState.PASSKEY_INPUT_PENDING + Passkey events

Sub-Plan 3b-1 Task 2. State 11; events 20 (user-entered) and 21 (rejected)
for the new Legacy Passkey branch of the SMP state machine."
```

---

## Task 3: `_passkey_capable`, `_passkey_local_role`, `_association_model` extension

**Files:**
- Modify: `pybluehost/ble/_smp_state.py` (near `_association_model` around line 845)
- Test: `tests/unit/ble/test_smp_passkey_legacy.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/ble/test_smp_passkey_legacy.py`:

```python
from types import SimpleNamespace

from pybluehost.ble._smp_state import _association_model, _passkey_local_role
from pybluehost.core.types import IOCapability


def _ctx_legacy(*, mitm_local=True, mitm_peer=True,
                io_local=IOCapability.DISPLAY_YES_NO,
                io_peer=IOCapability.KEYBOARD_ONLY,
                role_initiator=True):
    """Build a minimal pairing-context stub (Legacy, no SC)."""
    from pybluehost.ble.smp import PairingRole
    auth_local = (0x01) | (0x04 if mitm_local else 0x00)  # bondable + maybe MITM, no SC
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
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_legacy.py -k "association_model or passkey_local_role" -v`
Expected: FAIL — neither `_association_model` extension nor `_passkey_local_role` exists yet.

- [ ] **Step 3: Implement helpers and extension**

In `pybluehost/ble/_smp_state.py`, locate the existing `_association_model` (around line 845, immediately after `_sc_negotiated`). Replace it with the extended version:

```python
def _association_model(ctx: "SMPPairingContext") -> str:
    """Return 'numeric_comparison' | 'passkey_entry' | 'just_works'.

    SC modes (Sub-Plan 3a + 3b-2): NC vs JW.
    Legacy mode (Sub-Plan 3b-1): Passkey Entry vs JW.
    Passkey Entry and OOB deferred to Sub-Plans 3b-2 and 3c.
    """
    from pybluehost.core.types import IOCapability

    both_mitm = bool(ctx.local_auth_req & 0x04) and bool(ctx.peer_auth_req & 0x04)

    if _sc_negotiated(ctx):
        if not both_mitm:
            return "just_works"
        nc_caps = {int(IOCapability.DISPLAY_YES_NO), int(IOCapability.KEYBOARD_DISPLAY)}
        if int(ctx.local_io_caps) in nc_caps and int(ctx.peer_io_caps) in nc_caps:
            return "numeric_comparison"
        return "just_works"

    # Legacy path — Sub-Plan 3b-1 addition
    if not both_mitm:
        return "just_works"
    if not _passkey_capable(int(ctx.local_io_caps), int(ctx.peer_io_caps)):
        return "just_works"
    return "passkey_entry"


def _passkey_capable(local_io: int, peer_io: int) -> bool:
    """True if the IO-cap pair supports Legacy Passkey Entry (Sub-Plan 3b-1 scope).

    Rules:
      * Neither side may be NO_INPUT_NO_OUTPUT.
      * At least one side must be able to display (DISPLAY_ONLY, DISPLAY_YES_NO, KEYBOARD_DISPLAY).
      * At least one side must be able to input (KEYBOARD_ONLY, KEYBOARD_DISPLAY).
      * Both-KeyboardOnly falls through to Just Works (out of scope; very rare).
    """
    from pybluehost.core.types import IOCapability
    NO = int(IOCapability.NO_INPUT_NO_OUTPUT)
    KO = int(IOCapability.KEYBOARD_ONLY)
    if local_io == NO or peer_io == NO:
        return False
    display_caps = {int(IOCapability.DISPLAY_ONLY),
                    int(IOCapability.DISPLAY_YES_NO),
                    int(IOCapability.KEYBOARD_DISPLAY)}
    input_caps = {int(IOCapability.KEYBOARD_ONLY),
                  int(IOCapability.KEYBOARD_DISPLAY)}
    has_display = local_io in display_caps or peer_io in display_caps
    has_input = local_io in input_caps or peer_io in input_caps
    if not (has_display and has_input):
        return False
    if local_io == KO and peer_io == KO:
        return False
    return True


def _passkey_local_role(ctx: "SMPPairingContext") -> str:
    """Return 'display' or 'input' for the local side.

    Only meaningful when _association_model(ctx) == 'passkey_entry'.
    """
    from pybluehost.core.types import IOCapability
    local = int(ctx.local_io_caps)
    peer = int(ctx.peer_io_caps)
    display_caps = {int(IOCapability.DISPLAY_ONLY),
                    int(IOCapability.DISPLAY_YES_NO),
                    int(IOCapability.KEYBOARD_DISPLAY)}
    input_caps = {int(IOCapability.KEYBOARD_ONLY),
                  int(IOCapability.KEYBOARD_DISPLAY)}
    local_can_display = local in display_caps
    local_can_input = local in input_caps
    peer_can_display = peer in display_caps
    peer_can_input = peer in input_caps

    # Both-KeyboardDisplay: spec says Initiator displays, Responder inputs.
    if local == int(IOCapability.KEYBOARD_DISPLAY) and peer == int(IOCapability.KEYBOARD_DISPLAY):
        return "display" if ctx.role == PairingRole.INITIATOR else "input"

    # If local can display and peer can't (i.e. peer is KeyboardOnly), local displays.
    if local_can_display and not peer_can_display:
        return "display"
    # If local can input and peer can't (peer is DisplayOnly/DisplayYesNo), local inputs.
    if local_can_input and not peer_can_input:
        return "input"
    # Local can both display and input (KeyboardDisplay) and peer can only one of them:
    if local == int(IOCapability.KEYBOARD_DISPLAY):
        if peer in (int(IOCapability.DISPLAY_ONLY), int(IOCapability.DISPLAY_YES_NO)):
            return "input"
        if peer == int(IOCapability.KEYBOARD_ONLY):
            return "display"
    # Defensive fallback (should not be hit if _passkey_capable returned True):
    return "display" if local_can_display else "input"
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_legacy.py -v`
Expected: all `association_model` and `passkey_local_role` tests PASS.

Run: `uv run pytest tests/unit/ble/ -q`
Expected: no regressions (Sub-Plan 3a's `_association_model` tests still pass — the SC branch is unchanged).

- [ ] **Step 5: Commit**

```bash
git add pybluehost/ble/_smp_state.py tests/unit/ble/test_smp_passkey_legacy.py
git commit -m "feat(ble/smp): _association_model returns 'passkey_entry' for Legacy MITM

Sub-Plan 3b-1 Task 3. Adds _passkey_capable and _passkey_local_role helpers
and extends _association_model to return 'passkey_entry' when SC is not
negotiated, both sides set MITM, and the IO-cap pair has at least one
display + at least one keyboard. Both-KeyboardOnly + NO_INPUT_NO_OUTPUT
fall through to Just Works."
```

---

## Task 4: `_passkey_await_user_input` helper

**Files:**
- Modify: `pybluehost/ble/_smp_state.py` (add helper near `_sc_compute_and_await_nc`)
- Test: `tests/unit/ble/test_smp_passkey_legacy.py`

- [ ] **Step 1: Append failing tests**

```python
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
        return 1_000_000  # one past max 6-digit


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
    # Let the spawned task run
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
    """AutoAcceptDelegate.get_passkey returns 0; helper accepts it as valid (in range)."""
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
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_legacy.py -k "await_user_input" -v`
Expected: FAIL — `_passkey_await_user_input` does not exist.

- [ ] **Step 3: Implement helper**

Add to `pybluehost/ble/_smp_state.py`, immediately after `_sc_compute_and_await_nc`:

```python
async def _passkey_await_user_input(ctx: "SMPPairingContext") -> None:
    """Input-role helper: spawn delegate.get_passkey task, fire user-entered or rejected.

    Mirrors _sc_compute_and_await_nc from Sub-Plan 3a. The function returns
    immediately; the spawned task fires PASSKEY_USER_ENTERED or
    PASSKEY_USER_REJECTED when the user finishes (or cancels).
    """
    from pybluehost.ble.smp import AutoAcceptDelegate, SMPEvent

    delegate = getattr(ctx, "_delegate", None) or AutoAcceptDelegate()

    async def _await() -> None:
        try:
            value = await delegate.get_passkey(ctx.peer_address)
        except AttributeError:
            value = 0  # backward-compat: delegate without get_passkey → auto-accept zero
        except Exception as exc:  # noqa: BLE001
            logger.warning("delegate.get_passkey raised: %s; rejecting passkey", exc)
            await ctx.state_machine.fire(SMPEvent.PASSKEY_USER_REJECTED)
            return
        if not isinstance(value, int) or not (0 <= value <= 999_999):
            await ctx.state_machine.fire(SMPEvent.PASSKEY_USER_REJECTED)
            return
        ctx.passkey = value
        await ctx.state_machine.fire(SMPEvent.PASSKEY_USER_ENTERED)

    asyncio.create_task(_await())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_legacy.py -k "await_user_input" -v`
Expected: 4 PASS.

Run: `uv run pytest tests/unit/ble/ -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/ble/_smp_state.py tests/unit/ble/test_smp_passkey_legacy.py
git commit -m "feat(ble/smp): _passkey_await_user_input helper

Sub-Plan 3b-1 Task 4. Spawns delegate.get_passkey task, validates the
returned 6-digit value, fires PASSKEY_USER_ENTERED (stores passkey on ctx)
or PASSKEY_USER_REJECTED on exception / out-of-range / missing method."
```

---

## Task 5: PASSKEY_INPUT_PENDING transitions + buffer + user-entered actions

**Files:**
- Modify: `pybluehost/ble/_smp_state.py` (`register_transitions`; new helpers `_passkey_buffer_peer_confirm`, `_passkey_user_entered`)
- Test: `tests/unit/ble/test_smp_passkey_legacy.py`

- [ ] **Step 1: Append failing tests**

```python
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
        saved_pairing_request=b"\x01" + b"\x00" * 6,   # 7-byte stub
        saved_pairing_response=b"\x02" + b"\x00" * 6,
        peer_address=BDAddress(b"\x0B" * 6),
        local_address=BDAddress(b"\x0A" * 6),
        connection_handle=1,
        send=_send,
        peer_confirm=None,
    )
    await state_mod._passkey_user_entered(ctx)
    # TK set to passkey little-endian, zero-padded to 16 bytes
    assert ctx.tk == (314159).to_bytes(16, "little")
    # local_random is 16 random bytes
    assert isinstance(ctx.local_random, bytes) and len(ctx.local_random) == 16
    # local_confirm matches the (mocked) c1 output
    assert ctx.local_confirm == b"\xaa" * 16
    # One PDU sent: SMPPairingConfirm with opcode 0x03
    assert len(sent) == 1
    assert sent[0][0] == 0x03  # Pairing Confirm opcode


def test_passkey_input_pending_in_universal_failure_loop():
    """register_transitions must include PASSKEY_INPUT_PENDING in the universal
    failure-transition loop (PAIRING_FAILED_RX, TIMEOUT, DISCONNECTED → FAILED)."""
    import inspect
    from pybluehost.ble import _smp_state as state_mod
    src = inspect.getsource(state_mod.register_transitions)
    assert "PASSKEY_INPUT_PENDING" in src
    # The universal-failure for loop must reference SMPState.PASSKEY_INPUT_PENDING
    # alongside the other states.
    universal_loop_segment = src[src.find("Universal failure"):]
    assert "PASSKEY_INPUT_PENDING" in universal_loop_segment


def test_passkey_input_pending_timeout_set():
    """register_transitions must set a 60s timeout on PASSKEY_INPUT_PENDING."""
    import inspect
    from pybluehost.ble import _smp_state as state_mod
    src = inspect.getsource(state_mod.register_transitions)
    assert "set_timeout(SMPState.PASSKEY_INPUT_PENDING" in src
    assert "60.0" in src  # may share constant with other states
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_legacy.py -k "buffer_peer_confirm or user_entered or universal_failure_loop or timeout_set" -v`
Expected: FAIL — helpers don't exist; transitions not registered.

- [ ] **Step 3: Implement helpers + register transitions**

A) Add the helpers to `pybluehost/ble/_smp_state.py`, immediately after `_passkey_await_user_input`:

```python
async def _passkey_buffer_peer_confirm(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """Input-side helper: stash peer's Pairing_Confirm while we wait on the user.

    Once PASSKEY_USER_ENTERED fires, the existing Phase-2 flow validates this
    buffered value against the recomputed c1 once both randoms are exchanged.
    """
    ctx.peer_confirm = pdu.confirm_value


async def _passkey_user_entered(ctx: "SMPPairingContext", **_kw) -> None:
    """Input-side helper: user entered passkey → set TK, send our Pairing_Confirm.

    For Initiator Input: peer Confirm has NOT yet arrived; we send first.
    For Responder Input: peer Confirm may already be in ctx.peer_confirm (buffered);
      we still just send our own Confirm — c1 verification of the peer's value
      happens later in _responder_recv_peer_random against ctx.peer_confirm.
    """
    from pybluehost.ble.smp import SMPPairingConfirm
    ctx.tk = ctx.passkey.to_bytes(16, "little")
    ctx.local_random = os.urandom(16)
    preq, pres, iat, rat, ia, ra = _build_c1_params(ctx)
    ctx.local_confirm = SMPCrypto.c1(
        ctx.tk, ctx.local_random, preq, pres, iat, rat, ia, ra,
    )
    await ctx.send(SMPPairingConfirm(confirm_value=ctx.local_confirm).to_bytes())
```

B) In `register_transitions` (around lines 170-179 — same area as the NC transitions), add the PASSKEY transitions immediately after the NC ones:

```python
    # ---- Sub-Plan 3b-1 — Legacy Passkey Entry transitions ----
    sm.add_transition(
        SMPState.PASSKEY_INPUT_PENDING, SMPEvent.PAIRING_CONFIRM_RX,
        SMPState.PASSKEY_INPUT_PENDING,
        action=lambda **kw: _passkey_buffer_peer_confirm(ctx, **kw),
    )
    sm.add_transition(
        SMPState.PASSKEY_INPUT_PENDING, SMPEvent.PASSKEY_USER_ENTERED,
        SMPState.CONFIRMING,
        action=lambda **kw: _passkey_user_entered(ctx, **kw),
    )
    sm.add_transition(
        SMPState.PASSKEY_INPUT_PENDING, SMPEvent.PASSKEY_USER_REJECTED,
        SMPState.FAILED,
        action=lambda **kw: _on_failed(ctx, reason=0x01, **kw),
    )
```

C) In the Phase-2 timeout block (around line 235), add the PASSKEY timeout:

```python
    sm.set_timeout(SMPState.PASSKEY_INPUT_PENDING, 60.0, SMPEvent.TIMEOUT)
```

(Use 60.0 rather than 30.0 because user input takes longer than glancing at a number.)

D) In the universal-failure-transitions tuple (around line 240-244), add `PASSKEY_INPUT_PENDING`:

```python
    for state in (
        SMPState.IDLE, SMPState.FEATURE_EXCHANGE, SMPState.CONFIRMING,
        SMPState.RANDOM_EXCHANGE, SMPState.STK_ENCRYPTING, SMPState.KEY_DISTRIBUTION,
        SMPState.PUBLIC_KEY_EXCHANGE, SMPState.DHKEY_CHECK,
        SMPState.NUMERIC_COMPARE_PENDING,
        SMPState.PASSKEY_INPUT_PENDING,
    ):
        ...
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_legacy.py -v`
Expected: all PASS.

Run: `uv run pytest tests/unit/ble/ -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/ble/_smp_state.py tests/unit/ble/test_smp_passkey_legacy.py
git commit -m "feat(ble/smp): PASSKEY_INPUT_PENDING transitions + 60s timeout

Sub-Plan 3b-1 Task 5. _passkey_buffer_peer_confirm stashes peer's
Pairing_Confirm while the input-side user is typing. _passkey_user_entered
sets TK = passkey.to_bytes(16, 'little'), generates local_random, computes
c1, sends own Pairing_Confirm. PASSKEY_USER_REJECTED → FAILED(0x01).
PASSKEY_INPUT_PENDING joins the universal failure loop and gets a 60s
timeout."
```

---

## Task 6: Branch `_initiator_recv_pairing_response` on association model

**Files:**
- Modify: `pybluehost/ble/_smp_state.py:303-340` (`_initiator_recv_pairing_response`)
- Test: `tests/unit/ble/test_smp_passkey_legacy.py`

- [ ] **Step 1: Append failing tests**

```python
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
        io_capability=0x02, oob_data_flag=0, auth_req=0x05,  # KbOnly + Bonding+MITM
        max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    )
    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        peer_io_caps=0x02, peer_auth_req=0x05, peer_max_key_size=16,
        peer_init_key_dist=0x07, peer_resp_key_dist=0x07,
        local_io_caps=0x01,                                  # DisplayYesNo
        local_auth_req=0x05,
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
    # Passkey was generated, displayed, TK set, Confirm sent
    assert ctx.passkey == 246813
    assert displayed == [(BDAddress(b"\x0B" * 6), 246813)]
    assert ctx.tk == (246813).to_bytes(16, "little")
    assert len(sent) == 1 and sent[0][0] == 0x03  # Pairing Confirm
    # State stays CONFIRMING (no override)
    assert sm._state == SMPState.FEATURE_EXCHANGE  # action doesn't override; SM transition target is CONFIRMING


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
        local_io_caps=0x02,                                  # KeyboardOnly
        local_auth_req=0x05,
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
    # State overridden to PASSKEY_INPUT_PENDING
    assert sm._state == SMPState.PASSKEY_INPUT_PENDING
    # No Pairing_Confirm sent yet
    assert sent == []
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_legacy.py -k "initiator_pairing_response" -v`
Expected: FAIL — current implementation doesn't branch on passkey.

- [ ] **Step 3: Modify `_initiator_recv_pairing_response`**

In `pybluehost/ble/_smp_state.py`, locate `_initiator_recv_pairing_response` (around line 303). After the SC branch and BEFORE the Legacy JW path, add the Passkey branch:

```python
async def _initiator_recv_pairing_response(ctx: "SMPPairingContext", *, pdu: SMPPairingResponse, **_kw) -> None:
    ctx.saved_pairing_response = pdu.to_bytes()
    ctx.peer_io_caps = pdu.io_capability
    ctx.peer_auth_req = pdu.auth_req
    ctx.peer_max_key_size = pdu.max_key_size
    ctx.peer_init_key_dist = pdu.init_key_dist
    ctx.peer_resp_key_dist = pdu.resp_key_dist

    if _sc_negotiated(ctx):
        # SC path: existing block unchanged.
        from pybluehost.ble._smp_sc_crypto import generate_p256_keypair
        from pybluehost.ble.smp import SMPPairingPublicKey
        priv, pub = generate_p256_keypair()
        ctx.local_private_key = priv
        ctx.local_public_key = pub
        ctx.state_machine._state = SMPState.PUBLIC_KEY_EXCHANGE
        await ctx.send(SMPPairingPublicKey(
            public_key_x=pub[:32], public_key_y=pub[32:],
        ).to_bytes())
        return

    # Legacy path — Sub-Plan 3b-1: branch on association model
    model = _association_model(ctx)
    if model == "passkey_entry":
        role = _passkey_local_role(ctx)
        if role == "display":
            ctx.passkey = secrets.randbelow(1_000_000)
            delegate = getattr(ctx, "_delegate", None)
            if delegate is not None:
                try:
                    await delegate.display_passkey(ctx.peer_address, ctx.passkey)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("delegate.display_passkey raised: %s; proceeding", exc)
            ctx.tk = ctx.passkey.to_bytes(16, "little")
            ctx.local_random = os.urandom(16)
            preq, pres, iat, rat, ia, ra = _build_c1_params(ctx)
            ctx.local_confirm = SMPCrypto.c1(
                ctx.tk, ctx.local_random, preq, pres, iat, rat, ia, ra,
            )
            await ctx.send(SMPPairingConfirm(confirm_value=ctx.local_confirm).to_bytes())
            return
        # role == "input": override state, spawn delegate task
        ctx.state_machine._state = SMPState.PASSKEY_INPUT_PENDING
        await _passkey_await_user_input(ctx)
        return

    # Just Works: existing block unchanged
    ctx.tk = b"\x00" * 16
    ctx.local_random = os.urandom(16)
    preq = ctx.saved_pairing_request[:7]
    pres = ctx.saved_pairing_response[:7]
    iat = 0x00
    rat = 0x00
    ia = _local_address_bytes(ctx)
    ra = _peer_address_bytes(ctx)
    ctx.local_confirm = SMPCrypto.c1(ctx.tk, ctx.local_random, preq, pres, iat, rat, ia, ra)
    await ctx.send(SMPPairingConfirm(confirm_value=ctx.local_confirm).to_bytes())
```

Add `import secrets` to the top of `_smp_state.py` if not already present.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_legacy.py -v`
Expected: all PASS.

Run: `uv run pytest tests/unit/ble/ -q`
Expected: no regressions (Sub-Plan 3a NC + Sub-Plan 1 Legacy JW tests stay green).

- [ ] **Step 5: Commit**

```bash
git add pybluehost/ble/_smp_state.py tests/unit/ble/test_smp_passkey_legacy.py
git commit -m "feat(ble/smp): branch Initiator Phase-1→2 action on Passkey role

Sub-Plan 3b-1 Task 6. _initiator_recv_pairing_response now consults
_association_model + _passkey_local_role:
  - Display: generates 6-digit passkey, calls delegate.display_passkey,
    sets TK = passkey.to_bytes(16, 'little'), proceeds inline through c1.
  - Input: overrides state to PASSKEY_INPUT_PENDING, spawns
    delegate.get_passkey via _passkey_await_user_input.
Just Works path unchanged."
```

---

## Task 7: Branch `_responder_recv_pairing_request` + `_persist_bond` authenticated for Passkey

**Files:**
- Modify: `pybluehost/ble/_smp_state.py:343-369` (`_responder_recv_pairing_request`); `_persist_bond` Legacy branch
- Test: `tests/unit/ble/test_smp_passkey_legacy.py`

- [ ] **Step 1: Append failing tests**

```python
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
        local_io_caps=0x01,                                  # DisplayYesNo
        bondable=True,
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
    # Pairing_Response sent
    assert len(sent) == 1 and sent[0][0] == 0x02
    # Passkey generated, displayed, TK set
    assert ctx.passkey == 135790
    assert displayed == [(BDAddress(b"\x0B" * 6), 135790)]
    assert ctx.tk == (135790).to_bytes(16, "little")
    # State stays CONFIRMING (registered transition target — action doesn't override)
    assert sm._state == SMPState.IDLE  # SM transition target is CONFIRMING; action doesn't touch _state


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
        local_io_caps=0x02,
        bondable=True,
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
    # Pairing_Response was sent BEFORE state override
    assert len(sent) == 1 and sent[0][0] == 0x02
    # State overridden to PASSKEY_INPUT_PENDING
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
    assert saved[0].sc is False  # Legacy
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_legacy.py -k "responder_pairing_request or persist_bond_authenticated_true_for_legacy_passkey" -v`
Expected: FAIL.

- [ ] **Step 3: Modify `_responder_recv_pairing_request`**

In `pybluehost/ble/_smp_state.py`, locate `_responder_recv_pairing_request` (around line 343). Add the Passkey branch AFTER the Pairing_Response is sent:

```python
async def _responder_recv_pairing_request(ctx: "SMPPairingContext", *, pdu: SMPPairingRequest, **_kw) -> None:
    ctx.saved_pairing_request = pdu.to_bytes()
    ctx.peer_io_caps = pdu.io_capability
    ctx.peer_auth_req = pdu.auth_req
    ctx.peer_max_key_size = pdu.max_key_size
    ctx.peer_init_key_dist = pdu.init_key_dist
    ctx.peer_resp_key_dist = pdu.resp_key_dist
    resp_auth_req = 0x01 if ctx.bondable else 0
    if ctx.security_config is not None and ctx.security_config.enable_secure_connections:
        resp_auth_req |= 0x08
    if ctx.security_config is not None and getattr(ctx.security_config, "mitm_required", False):
        resp_auth_req |= 0x04
    rsp = SMPPairingResponse(
        io_capability=ctx.local_io_caps,
        oob_data_flag=0,
        auth_req=resp_auth_req,
        max_key_size=16,
        init_key_dist=0x07,
        resp_key_dist=0x07,
    )
    raw = rsp.to_bytes()
    ctx.saved_pairing_response = raw
    ctx.local_auth_req = rsp.auth_req
    ctx.local_init_key_dist = rsp.init_key_dist
    ctx.local_resp_key_dist = rsp.resp_key_dist
    ctx.tk = b"\x00" * 16   # default; overwritten below for Passkey
    await ctx.send(raw)

    if _sc_negotiated(ctx):
        ctx.state_machine._state = SMPState.PUBLIC_KEY_EXCHANGE
        return

    # Sub-Plan 3b-1: Legacy Passkey branch
    model = _association_model(ctx)
    if model == "passkey_entry":
        role = _passkey_local_role(ctx)
        if role == "display":
            ctx.passkey = secrets.randbelow(1_000_000)
            delegate = getattr(ctx, "_delegate", None)
            if delegate is not None:
                try:
                    await delegate.display_passkey(ctx.peer_address, ctx.passkey)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("delegate.display_passkey raised: %s; proceeding", exc)
            ctx.tk = ctx.passkey.to_bytes(16, "little")
            # No PDU to send yet — Responder waits for Initiator's Pairing_Confirm in CONFIRMING.
            return
        # role == "input": override state and await user
        ctx.state_machine._state = SMPState.PASSKEY_INPUT_PENDING
        await _passkey_await_user_input(ctx)
```

- [ ] **Step 4: Modify `_persist_bond` Legacy branch**

In `_persist_bond` (around line 711), update the Legacy branch's `authenticated` assignment:

```python
        else:
            # Legacy pairing
            if ctx.role == PairingRole.RESPONDER and ctx.local_ltk:
                ltk_for_bond = ctx.local_ltk
                ediv_for_bond = ctx.local_ediv
                rand_for_bond = ctx.local_rand
            else:
                ltk_for_bond = ctx.received_ltk if ctx.received_ltk else None
                ediv_for_bond = ctx.received_ediv
                rand_for_bond = ctx.received_rand if ctx.received_rand else b"\x00" * 8
            # Sub-Plan 3b-1: Passkey provides MITM authentication; Just Works does not.
            authenticated = _association_model(ctx) == "passkey_entry"
            bond = BondInfo(
                peer_address=ctx.peer_address,
                address_type=ctx.received_identity_address[0],
                ltk=ltk_for_bond,
                irk=ctx.received_irk if ctx.received_irk else None,
                csrk=ctx.received_csrk if ctx.received_csrk else None,
                ediv=ediv_for_bond,
                rand=rand_for_bond,
                key_size=16,
                authenticated=authenticated,
                sc=False,
            )
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/ble/test_smp_passkey_legacy.py -v`
Expected: all PASS.

Run: `uv run pytest tests/unit/ble/ -q`
Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add pybluehost/ble/_smp_state.py tests/unit/ble/test_smp_passkey_legacy.py
git commit -m "feat(ble/smp): Responder Passkey branch + Legacy bond.authenticated

Sub-Plan 3b-1 Task 7. _responder_recv_pairing_request branches on the
association model after sending Pairing_Response: Display role generates +
displays passkey and waits for Initiator's Confirm; Input role overrides
state to PASSKEY_INPUT_PENDING and spawns delegate.get_passkey.
_persist_bond now marks Legacy bonds authenticated=True for passkey_entry
(matching the Sub-Plan 3a NC pattern)."
```

---

## Task 8: Loopback E2E + STATUS.md

**Files:**
- Create: `tests/integration/test_pairing_legacy_passkey_loopback.py`
- Modify: `docs/superpowers/STATUS.md`

- [ ] **Step 1: Write the E2E tests**

Create `tests/integration/test_pairing_legacy_passkey_loopback.py`:

```python
"""End-to-end Legacy Passkey Entry pairing via VirtualLELink."""
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


def _passkey_config(storage, *, io_cap):
    return StackConfig(
        bond_storage=storage,
        security=SecurityConfig(
            enable_secure_connections=False,  # Legacy
            mitm_required=True,
        ),
        le_io_capability=io_cap,
    )


async def test_legacy_passkey_pair_succeeds_with_matching_delegates(tmp_path):
    """Display side (Central=DisplayYesNo) + Input side (Peripheral=KeyboardOnly);
    both delegates carry the same passkey → pairing succeeds; bond authenticated."""
    storage_a = JsonBondStorage(tmp_path / "bonds_a.json")
    storage_b = JsonBondStorage(tmp_path / "bonds_b.json")
    central = BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A")
    peripheral = BDAddress(b"\x0B\x0B\x0B\x0B\x0B\x0B")

    cfg_a = _passkey_config(storage_a, io_cap=IOCapability.DISPLAY_YES_NO)
    cfg_b = _passkey_config(storage_b, io_cap=IOCapability.KEYBOARD_ONLY)

    stack_a = await Stack.virtual(config=cfg_a, address=central)
    stack_b = await Stack.virtual(config=cfg_b, address=peripheral)
    stack_a._smp.set_delegate(_FixedPasskeyDelegate(passkey=271828))
    stack_b._smp.set_delegate(_FixedPasskeyDelegate(passkey=271828))

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
    assert bond_a is not None and bond_a.sc is False
    assert bond_b is not None and bond_b.sc is False
    # Legacy Passkey → authenticated=True on both sides
    assert bond_a.authenticated is True
    assert bond_b.authenticated is True

    await link.disconnect()
    await stack_a.close()
    await stack_b.close()


async def test_legacy_passkey_pair_fails_on_wrong_passkey(tmp_path):
    """Mismatched passkeys → c1 verification fails → pair() raises with reason=0x04."""
    storage_a = JsonBondStorage(tmp_path / "bonds_a.json")
    storage_b = JsonBondStorage(tmp_path / "bonds_b.json")
    central = BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A")
    peripheral = BDAddress(b"\x0B\x0B\x0B\x0B\x0B\x0B")

    cfg_a = _passkey_config(storage_a, io_cap=IOCapability.DISPLAY_YES_NO)
    cfg_b = _passkey_config(storage_b, io_cap=IOCapability.KEYBOARD_ONLY)

    stack_a = await Stack.virtual(config=cfg_a, address=central)
    stack_b = await Stack.virtual(config=cfg_b, address=peripheral)
    stack_a._smp.set_delegate(_FixedPasskeyDelegate(passkey=111111))
    stack_b._smp.set_delegate(_FixedPasskeyDelegate(passkey=222222))  # wrong

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

- [ ] **Step 2: Run E2E tests**

Run: `uv run pytest tests/integration/test_pairing_legacy_passkey_loopback.py -v`

Expected: both PASS.

If they fail:
- For the success path: trace whether `_FixedPasskeyDelegate` is actually being invoked on the Input side. Confirm `set_delegate` propagates to `ctx._delegate` (Sub-Plan 3a Task 8 already added this — verify with `grep -n "ctx._delegate = self._delegate" pybluehost/ble/smp.py`).
- For the failure path: confirm that c1 verification mismatch surfaces as `RuntimeError("SMP pairing failed (reason=4)")`. If the Initiator receives `Pairing_Failed(0x04)` first (which is what should happen — Input side generates wrong Confirm, Display side's c1 verify fails first), the assertion should match.

You have permission to debug NC-adjacent wiring issues that surface (e.g., buffered Confirm not being consumed correctly), but stay scoped to Legacy Passkey integration.

- [ ] **Step 3: Run full suite for regressions**

Run: `uv run pytest tests/ -q`
Expected: only the 3 pre-existing USB-diagnostics failures; everything else PASS.

- [ ] **Step 4: Update STATUS.md**

In `docs/superpowers/STATUS.md`:
- Update the "**当前进行中**" / "**下一步**" lines to mark Sub-Plan 3b-1 complete and shift the "下一步" list.
- Add a new completed-Plan row at the end of the Plan-progress table (line ~52), with date 2026-05-18, link to the plan file, and the touched paths.
- Bump the "总计：N 个 Plan" line at line ~53 by one.
- Add a dedicated detailed-progress section near the existing Sub-Plan 3a section.

Surgical edits, match the surrounding markdown style.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_pairing_legacy_passkey_loopback.py docs/superpowers/STATUS.md
git commit -m "test(integration): Legacy Passkey Entry loopback E2E

Sub-Plan 3b-1 Task 8. Two Stack.virtual() instances with mitm_required=True
+ enable_secure_connections=False and DisplayYesNo×KeyboardOnly IO caps
pair via Legacy Passkey when both delegates carry the same passkey →
bond.authenticated=True. Mismatched passkeys → pair() raises with reason=0x04
(Confirm Value Failed). Marks Sub-Plan 3b-1 complete in STATUS.md."
```

---

## Acceptance Checklist

- [ ] `PairingDelegate.display_passkey/get_passkey/confirm_passkey` and `AutoAcceptDelegate` use `(peer_addr, value)` signature.
- [ ] `SMPState.PASSKEY_INPUT_PENDING = 11` exists; `SMPEvent.PASSKEY_USER_ENTERED = 20`, `PASSKEY_USER_REJECTED = 21` exist.
- [ ] `_association_model` returns `"passkey_entry"` for in-scope Legacy IO×MITM combinations.
- [ ] `_passkey_local_role` returns the expected role across §2.3 design table.
- [ ] `_passkey_await_user_input` spawns delegate task, fires CONFIRMED/REJECTED, validates 0–999_999 range.
- [ ] `_passkey_buffer_peer_confirm` stashes peer Confirm during input wait.
- [ ] `_passkey_user_entered` sets TK = passkey LE bytes, generates random, computes c1, sends Pairing_Confirm.
- [ ] Initiator Phase-1→2 action: Display branch generates+displays+sends inline; Input branch overrides state to `PASSKEY_INPUT_PENDING`.
- [ ] Responder Phase-1→2 action: Display branch generates+displays after sending Pairing_Response; Input branch overrides state after sending Pairing_Response.
- [ ] `PASSKEY_INPUT_PENDING` in universal-failure-transitions loop; 60 s timeout set.
- [ ] `_persist_bond` Legacy branch sets `authenticated=True` for `passkey_entry`.
- [ ] Loopback E2E: matching delegates → authenticated bond; mismatched → pair() raises reason=4.
- [ ] Full suite green minus pre-existing USB-diagnostics failures.
- [ ] STATUS.md updated to mark Sub-Plan 3b-1 ✅.

## Out of Scope (deferred)

| Item | Future Plan |
|---|---|
| SC Passkey Entry (20-round commit, f4 bit-by-bit reveal) | Sub-Plan 3b-2 |
| OOB (Legacy + SC) | Sub-Plan 3c |
| Both-KeyboardOnly IO pair (rare; spec says "both input") | None — falls through to JW |
| BR/EDR Passkey Entry SSP (`User_Passkey_Request`/`User_Passkey_Notification`) | Independent Plan |
| Real-hardware verification with phone in Passkey mode | Independent Plan |
