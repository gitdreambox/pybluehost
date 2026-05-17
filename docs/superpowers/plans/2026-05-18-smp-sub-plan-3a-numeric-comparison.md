# SMP Sub-Plan 3a — Numeric Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Numeric Comparison (NC) association model on top of the existing LE Secure Connections + BR/EDR SC infrastructure, so MITM-protected pairing is available whenever both sides advertise SC + MITM + a display-and-confirm IO capability.

**Architecture:** Selection happens after Phase 2.2 (Random exchange / f5 derivation). A new `_association_model()` function inspects negotiated SC, both `auth_req` MITM bits and both IO capabilities. If NC is selected, both sides compute `Va = g2(PKax, PKbx, Na, Nb) mod 10^6`, enter a new `NUMERIC_COMPARE_PENDING` state, dispatch the value to `PairingDelegate.confirm_numeric(peer_addr, value)`, and only proceed to Phase 2.3 (Ea/Eb DHKey-Check exchange) on a positive confirmation. The BR/EDR side flips `SSPManager`'s existing `User_Confirmation_Request` handler from auto-accept to delegate-driven. `BondInfo.authenticated` is set `True` for NC bonds (vs `False` for SC Just Works).

**Tech Stack:** Python 3.10+, asyncio, pytest, `cryptography>=41.0` (AES-CMAC for `g2`), existing `pybluehost.core.statemachine.StateMachine`, existing `VirtualLELink` for loopback tests.

**Design spec:** [`docs/superpowers/specs/2026-05-17-smp-sub-plan-3a-numeric-comparison-design.md`](../specs/2026-05-17-smp-sub-plan-3a-numeric-comparison-design.md)

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `pybluehost/ble/security.py` | Add `SecurityConfig.mitm_required: bool = False` |
| Modify | `pybluehost/ble/smp.py` | Rename `PairingDelegate.confirm_numeric_comparison(value)` → `confirm_numeric(peer_addr, value)`; same for `AutoAcceptDelegate`; add `SMPState.NUMERIC_COMPARE_PENDING` (=10), `SMPEvent.NUMERIC_COMPARE_USER_CONFIRMED` (=18), `SMPEvent.NUMERIC_COMPARE_USER_REJECTED` (=19) |
| Modify | `pybluehost/ble/_smp_state.py` | Add `_association_model()`; add `_sc_compute_and_await_nc()`; branch `_sc_initiator_recv_peer_random` / `_sc_responder_recv_peer_random` on model; register NC transitions; extract Initiator Ea send into `_sc_send_dhkey_check_initiator()`; set `BondInfo.authenticated=True` in `_persist_bond` for NC |
| Modify | `pybluehost/classic/gap.py` | Add `delegate` kwarg to `SSPManager.__init__`; rewrite `USER_CONFIRMATION_REQUEST` handling in `on_hci_event` to call `delegate.confirm_numeric` (with fallback to legacy `_confirm_handler` for backward compat) |
| Modify | `pybluehost/stack.py` | Pass `delegate=smp._delegate` when constructing `SSPManager` |
| Create | `tests/unit/ble/test_smp_numeric_comparison.py` | Selection table tests + delegate Protocol shape + state-transition unit tests |
| Create | `tests/unit/classic/test_ssp_numeric_comparison.py` | SSPManager delegate dispatch + accept/reject/backward-compat paths |
| Create | `tests/integration/test_pairing_le_sc_nc_loopback.py` | Two-stack `Stack.virtual()` NC loopback: confirm path + reject path |
| Modify | `docs/superpowers/STATUS.md` | Mark Sub-Plan 3a complete |

---

## Task 1: SecurityConfig.mitm_required + PairingDelegate.confirm_numeric

**Files:**
- Modify: `pybluehost/ble/security.py:29-47`
- Modify: `pybluehost/ble/smp.py:601-627`
- Test: `tests/unit/ble/test_smp_numeric_comparison.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/ble/test_smp_numeric_comparison.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/ble/test_smp_numeric_comparison.py -v`
Expected: 4 failures — `mitm_required` doesn't exist; `confirm_numeric` doesn't exist on delegates.

- [ ] **Step 3: Add `mitm_required` to `SecurityConfig`**

In `pybluehost/ble/security.py`, inside the existing `@dataclass class SecurityConfig` (currently ending with the commented future-hook stubs), add the new field right after `ctkd_enable`:

```python
@dataclass
class SecurityConfig:
    """SMP security configuration for a connection."""
    io_capability: int = 0x03       # NoInputNoOutput
    oob_flag: int = 0x00
    auth_requirements: int = 0x0D   # Bonding | MITM | SC
    max_key_size: int = 16
    initiator_keys: int = 0x01      # LTK
    responder_keys: int = 0x01      # LTK
    # NEW:
    enable_secure_connections: bool = False
    ctkd_enable: bool = False
    mitm_required: bool = False     # Sub-Plan 3a: triggers NC when IO caps + SC permit
    # Future hooks (commented stubs):
    # lea_enable: bool = False
    # le_security_mode: str = "1_2"
    # classic_security_mode: str = "4_2"
    # sc_only_mode: bool = False
    # iso_encryption_enable: bool = False
    # numeric_comparison_enable: bool = False
```

- [ ] **Step 4: Rename `confirm_numeric_comparison` → `confirm_numeric` (peer_addr, value)**

In `pybluehost/ble/smp.py` around lines 601-627, replace the existing `PairingDelegate` and `AutoAcceptDelegate` bodies:

```python
class PairingDelegate(Protocol):
    """User interaction interface for SMP pairing decisions."""

    async def confirm_pairing(self, handle: int, io_cap: int) -> bool: ...
    async def confirm_passkey(self, passkey: int) -> bool: ...
    async def confirm_numeric(self, peer_addr: "BDAddress", value: int) -> bool: ...
    async def get_passkey(self) -> int: ...
    async def display_passkey(self, passkey: int) -> None: ...


class AutoAcceptDelegate:
    """Default delegate that auto-accepts everything (for testing)."""

    async def confirm_pairing(self, handle: int, io_cap: int) -> bool:
        return True

    async def confirm_passkey(self, passkey: int) -> bool:
        return True

    async def confirm_numeric(self, peer_addr: "BDAddress", value: int) -> bool:
        return True

    async def get_passkey(self) -> int:
        return 0

    async def display_passkey(self, passkey: int) -> None:
        pass
```

If `BDAddress` is not already imported at the top of `smp.py`, add `from pybluehost.core.address import BDAddress` to the imports (use TYPE_CHECKING-guarded import if there's a circular dependency).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/ble/test_smp_numeric_comparison.py -v`
Expected: 4 PASS

- [ ] **Step 6: Run full SMP suite to ensure no regressions**

Run: `uv run pytest tests/unit/ble/ -q`
Expected: all PASS (nothing else uses the old `confirm_numeric_comparison` name; grep to verify).

If grep finds remaining references: `grep -rn "confirm_numeric_comparison" pybluehost/ tests/` and update them.

- [ ] **Step 7: Commit**

```bash
git add pybluehost/ble/security.py pybluehost/ble/smp.py tests/unit/ble/test_smp_numeric_comparison.py
git commit -m "feat(ble/smp): SecurityConfig.mitm_required + PairingDelegate.confirm_numeric

Sub-Plan 3a Task 1. Adds mitm_required flag (default False) to SecurityConfig
and renames PairingDelegate.confirm_numeric_comparison(value) →
confirm_numeric(peer_addr, value) so NC dispatch can include the peer address."
```

---

## Task 2: SMPState.NUMERIC_COMPARE_PENDING + SMPEvent values

**Files:**
- Modify: `pybluehost/ble/smp.py:634-665`
- Test: `tests/unit/ble/test_smp_numeric_comparison.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/ble/test_smp_numeric_comparison.py`:

```python
from pybluehost.ble.smp import SMPEvent, SMPState


def test_smp_state_numeric_compare_pending_exists():
    assert SMPState.NUMERIC_COMPARE_PENDING == 10


def test_smp_event_numeric_compare_values():
    assert SMPEvent.NUMERIC_COMPARE_USER_CONFIRMED == 18
    assert SMPEvent.NUMERIC_COMPARE_USER_REJECTED == 19
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/ble/test_smp_numeric_comparison.py::test_smp_state_numeric_compare_pending_exists tests/unit/ble/test_smp_numeric_comparison.py::test_smp_event_numeric_compare_values -v`
Expected: FAIL with AttributeError on enum members.

- [ ] **Step 3: Add the new enum values**

In `pybluehost/ble/smp.py` around line 634, extend `SMPState`:

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
    DHKEY_CHECK         = 9
    NUMERIC_COMPARE_PENDING = 10
```

And `SMPEvent` (around line 647):

```python
class SMPEvent(IntEnum):
    LOCAL_PAIR_REQUEST = 0
    PAIRING_REQ_RX = 1
    PAIRING_RSP_RX = 2
    PAIRING_CONFIRM_RX = 3
    PAIRING_RANDOM_RX = 4
    ENCRYPTION_CHANGE_SUCCESS = 5
    ENCRYPTION_CHANGE_FAILED = 6
    ENCRYPTION_INFO_RX = 7
    MASTER_IDENT_RX = 8
    IDENTITY_INFO_RX = 9
    IDENTITY_ADDR_RX = 10
    SIGNING_INFO_RX = 11
    KEYS_RECEIVED = 12
    PAIRING_FAILED_RX = 13
    TIMEOUT = 14
    DISCONNECTED = 15
    PAIRING_PUBLIC_KEY_RX  = 16
    PAIRING_DHKEY_CHECK_RX = 17
    NUMERIC_COMPARE_USER_CONFIRMED = 18
    NUMERIC_COMPARE_USER_REJECTED = 19
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/ble/test_smp_numeric_comparison.py -v`
Expected: PASS (all 6 so far).

- [ ] **Step 5: Commit**

```bash
git add pybluehost/ble/smp.py tests/unit/ble/test_smp_numeric_comparison.py
git commit -m "feat(ble/smp): SMPState.NUMERIC_COMPARE_PENDING + NC events

Sub-Plan 3a Task 2. State value 10; events 18 (confirmed) and 19 (rejected)
for the new Numeric Comparison branch of the SC state machine."
```

---

## Task 3: `_association_model()` selection function

**Files:**
- Modify: `pybluehost/ble/_smp_state.py` (add at top, near other helpers)
- Test: `tests/unit/ble/test_smp_numeric_comparison.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/ble/test_smp_numeric_comparison.py`:

```python
from dataclasses import dataclass
from types import SimpleNamespace

from pybluehost.ble._smp_state import _association_model
from pybluehost.core.types import IOCapability


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
    # SC bit off on peer
    assert _association_model(_ctx(sc_peer=False)) == "just_works"


def test_association_model_just_works_when_io_caps_insufficient():
    # peer is NoInputNoOutput → cannot do NC
    assert _association_model(_ctx(io_peer=IOCapability.NO_INPUT_NO_OUTPUT)) == "just_works"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/ble/test_smp_numeric_comparison.py -k association_model -v`
Expected: FAIL — `_association_model` does not exist.

- [ ] **Step 3: Implement `_association_model()`**

Add to `pybluehost/ble/_smp_state.py`, just below the existing `_sc_negotiated` helper (after line 793):

```python
def _association_model(ctx: "SMPPairingContext") -> str:
    """Return 'numeric_comparison' or 'just_works' for the current SC pairing.

    Sub-Plan 3a covers NC vs JW only. Passkey Entry → Sub-Plan 3b; OOB → Sub-Plan 3c.

    NC requires:
      * SC negotiated (both sides advertise SC bit in auth_req)
      * Both sides have MITM bit (0x04) set in auth_req
      * Both sides have IO capability in {DisplayYesNo, KeyboardDisplay}
    Otherwise → "just_works".
    """
    from pybluehost.core.types import IOCapability

    if not _sc_negotiated(ctx):
        return "just_works"  # Legacy path; NC is not applicable
    both_mitm = bool(ctx.local_auth_req & 0x04) and bool(ctx.peer_auth_req & 0x04)
    if not both_mitm:
        return "just_works"
    nc_caps = {int(IOCapability.DISPLAY_YES_NO), int(IOCapability.KEYBOARD_DISPLAY)}
    if int(ctx.local_io_caps) in nc_caps and int(ctx.peer_io_caps) in nc_caps:
        return "numeric_comparison"
    return "just_works"
```

Verify the exact enum member names with `grep -n "class IOCapability" -A 10 pybluehost/core/types.py` — if names differ (e.g. `DisplayYesNo` instead of `DISPLAY_YES_NO`), adjust accordingly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/ble/test_smp_numeric_comparison.py -k association_model -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/ble/_smp_state.py tests/unit/ble/test_smp_numeric_comparison.py
git commit -m "feat(ble/smp): _association_model() selection (NC vs Just Works)

Sub-Plan 3a Task 3. Returns 'numeric_comparison' when SC+MITM+IO-caps qualify,
otherwise 'just_works'. Passkey/OOB models deferred to Sub-Plans 3b/3c."
```

---

## Task 4: `_sc_compute_and_await_nc()` helper

**Files:**
- Modify: `pybluehost/ble/_smp_state.py` (add helper)
- Test: `tests/unit/ble/test_smp_numeric_comparison.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/ble/test_smp_numeric_comparison.py`:

```python
import asyncio
import pytest

from pybluehost.ble._smp_state import _sc_compute_and_await_nc
from pybluehost.ble.smp import (
    AutoAcceptDelegate,
    PairingRole,
    SMPCrypto,
    SMPEvent,
)


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
    """g2 must be computed with the right key order, delegate called, confirm event fired."""
    # Synthetic but deterministic inputs
    pkax = bytes(range(32))           # Initiator pubkey X
    pkbx = bytes(range(32, 64))       # Responder pubkey X
    na = bytes(range(64, 80))
    nb = bytes(range(80, 96))
    expected_value = SMPCrypto.g2(pkax, pkbx, na, nb) % 1_000_000

    captured = _CapturingDelegate()
    from pybluehost.core.address import BDAddress
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
    # _sc_compute_and_await_nc spawns a task; let it run
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert captured.received == (peer, expected_value)
    assert sm.fired == [SMPEvent.NUMERIC_COMPARE_USER_CONFIRMED]


@pytest.mark.asyncio
async def test_sc_compute_and_await_nc_responder_uses_peer_pubkey_as_pkax():
    """When role=RESPONDER, PKax comes from peer_public_key (Initiator) not local."""
    pkax = bytes(range(32))
    pkbx = bytes(range(32, 64))
    na = bytes(range(64, 80))
    nb = bytes(range(80, 96))
    expected = SMPCrypto.g2(pkax, pkbx, na, nb) % 1_000_000

    captured = _CapturingDelegate()
    from pybluehost.core.address import BDAddress
    ctx = SimpleNamespace(
        role=PairingRole.RESPONDER,
        local_public_key=pkbx + bytes(32),   # Responder = local
        peer_public_key=pkax + bytes(32),    # Initiator = peer
        local_random=nb,                     # Responder Nb = local_random
        peer_random=na,                      # Initiator Na = peer_random
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
    from pybluehost.core.address import BDAddress
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
    from pybluehost.core.address import BDAddress
    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_public_key=bytes(64),
        peer_public_key=bytes(64),
        local_random=bytes(16),
        peer_random=bytes(16),
        peer_address=BDAddress(bytes(6)),
        state_machine=sm,
        _delegate=None,  # No delegate set
    )
    await _sc_compute_and_await_nc(ctx)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert sm.fired == [SMPEvent.NUMERIC_COMPARE_USER_CONFIRMED]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/ble/test_smp_numeric_comparison.py -k compute_and_await_nc -v`
Expected: FAIL — `_sc_compute_and_await_nc` does not exist.

- [ ] **Step 3: Implement `_sc_compute_and_await_nc()`**

Add to `pybluehost/ble/_smp_state.py` (place near `_sc_negotiated`):

```python
async def _sc_compute_and_await_nc(ctx: "SMPPairingContext") -> None:
    """Compute g2 value for NC, present to delegate, fire confirm/reject event.

    Spec: Va = g2(PKax, PKbx, Na, Nb) where PKax/PKbx are the X coordinates of
    Initiator/Responder public keys (32 bytes each). Both sides compute the
    same Va. Numeric value displayed to user is Va mod 10^6 (6 digits).
    """
    from pybluehost.ble.smp import (
        AutoAcceptDelegate,
        PairingRole,
        SMPCrypto,
        SMPEvent,
    )

    if ctx.role == PairingRole.INITIATOR:
        pkax = ctx.local_public_key[:32]
        pkbx = ctx.peer_public_key[:32]
        na = ctx.local_random
        nb = ctx.peer_random
    else:
        pkax = ctx.peer_public_key[:32]
        pkbx = ctx.local_public_key[:32]
        na = ctx.peer_random
        nb = ctx.local_random

    g2_value = SMPCrypto.g2(pkax, pkbx, na, nb)
    numeric_value = g2_value % 1_000_000

    delegate = getattr(ctx, "_delegate", None) or AutoAcceptDelegate()

    async def _await_user_confirm() -> None:
        try:
            confirmed = await delegate.confirm_numeric(ctx.peer_address, numeric_value)
        except AttributeError:
            # Older delegates without confirm_numeric: backward compat, auto-accept.
            confirmed = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("delegate.confirm_numeric raised: %s; rejecting NC", exc)
            confirmed = False
        if confirmed:
            await ctx.state_machine.fire(SMPEvent.NUMERIC_COMPARE_USER_CONFIRMED)
        else:
            await ctx.state_machine.fire(SMPEvent.NUMERIC_COMPARE_USER_REJECTED)

    asyncio.create_task(_await_user_confirm())
```

If `asyncio` is not already imported at the top of `_smp_state.py`, add it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/ble/test_smp_numeric_comparison.py -k compute_and_await_nc -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/ble/_smp_state.py tests/unit/ble/test_smp_numeric_comparison.py
git commit -m "feat(ble/smp): _sc_compute_and_await_nc helper

Sub-Plan 3a Task 4. Computes g2(PKax, PKbx, Na, Nb) % 10^6, dispatches to
PairingDelegate.confirm_numeric, fires NUMERIC_COMPARE_USER_CONFIRMED or
NUMERIC_COMPARE_USER_REJECTED. Falls back to AutoAcceptDelegate when no
delegate is configured."
```

---

## Task 5: Branch SC Random handlers + register NC transitions

**Files:**
- Modify: `pybluehost/ble/_smp_state.py:489-545` (`_sc_initiator_recv_peer_random`, `_sc_responder_recv_peer_random`) + transition registration
- Test: `tests/unit/ble/test_smp_numeric_comparison.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/ble/test_smp_numeric_comparison.py`:

```python
@pytest.mark.asyncio
async def test_initiator_random_branches_to_nc_when_selected(monkeypatch):
    """When _association_model returns NC, initiator does NOT immediately send Ea;
    instead it transitions to NUMERIC_COMPARE_PENDING and spawns the delegate task."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import SMPState
    sent_pdus: list[bytes] = []

    # Force NC selection
    monkeypatch.setattr(state_mod, "_association_model", lambda _ctx: "numeric_comparison")
    # Stub f4/f5 so we don't need real ECDH outputs
    monkeypatch.setattr(state_mod.SMPCrypto, "f4", staticmethod(lambda *a, **k: b"\x00" * 16))
    # Original confirm matches our stub so Cb verification passes
    monkeypatch.setattr(state_mod.SMPCrypto, "f5", staticmethod(lambda *a, **k: (b"\x11" * 16, b"\x22" * 16)))

    class _FakeSM:
        def __init__(self):
            self._state = SMPState.CONFIRMING
        async def fire(self, ev):
            pass

    sm = _FakeSM()
    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_public_key=bytes(64),
        peer_public_key=bytes(64),
        local_random=bytes(16),
        peer_random=bytes(16),
        peer_confirm=b"\x00" * 16,  # matches stubbed f4 output
        dhkey=bytes(32),
        local_auth_req=0x0D,
        local_io_caps=0x01,
        peer_address=__import__("pybluehost.core.address", fromlist=["BDAddress"]).BDAddress(bytes(6)),
        local_address=__import__("pybluehost.core.address", fromlist=["BDAddress"]).BDAddress(bytes(6)),
        state_machine=sm,
        _delegate=_CapturingDelegate(),
        _hci=None,
        send=lambda data: _record(sent_pdus, data),
    )

    async def _record(buf, data):
        buf.append(data)

    pdu = SimpleNamespace(random_value=bytes(16))
    await state_mod._sc_initiator_recv_peer_random(ctx, pdu=pdu)
    # Initiator must NOT have sent Ea (no DHKeyCheck PDU yet)
    assert all(b[0:1] != bytes([0x0D]) for b in sent_pdus)  # 0x0D = Pairing DHKey Check opcode
    # State must be NUMERIC_COMPARE_PENDING
    assert sm._state == SMPState.NUMERIC_COMPARE_PENDING


@pytest.mark.asyncio
async def test_initiator_random_just_works_path_still_sends_ea(monkeypatch):
    """When _association_model returns just_works, initiator immediately sends Ea
    and advances to DHKEY_CHECK (existing Sub-Plan 2 behavior)."""
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import SMPState
    sent_pdus: list[bytes] = []

    monkeypatch.setattr(state_mod, "_association_model", lambda _ctx: "just_works")
    monkeypatch.setattr(state_mod.SMPCrypto, "f4", staticmethod(lambda *a, **k: b"\x00" * 16))
    monkeypatch.setattr(state_mod.SMPCrypto, "f5", staticmethod(lambda *a, **k: (b"\x11" * 16, b"\x22" * 16)))
    monkeypatch.setattr(state_mod.SMPCrypto, "f6", staticmethod(lambda *a, **k: b"\xee" * 16))

    class _FakeSM:
        def __init__(self):
            self._state = SMPState.CONFIRMING
        async def fire(self, ev): pass

    sm = _FakeSM()
    from pybluehost.core.address import BDAddress
    ctx = SimpleNamespace(
        role=PairingRole.INITIATOR,
        local_public_key=bytes(64),
        peer_public_key=bytes(64),
        local_random=bytes(16),
        peer_random=bytes(16),
        peer_confirm=b"\x00" * 16,
        dhkey=bytes(32),
        local_auth_req=0x0D,
        local_io_caps=0x01,
        peer_address=BDAddress(bytes(6)),
        local_address=BDAddress(bytes(6)),
        state_machine=sm,
        _delegate=None,
        _hci=None,
        send=lambda data: sent_pdus.append(data),
    )
    pdu = SimpleNamespace(random_value=bytes(16))
    await state_mod._sc_initiator_recv_peer_random(ctx, pdu=pdu)
    assert sm._state == SMPState.DHKEY_CHECK
    # Should have sent one PDU (DHKey Check, opcode 0x0D)
    assert any(b[0:1] == bytes([0x0D]) for b in sent_pdus)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/ble/test_smp_numeric_comparison.py -k "initiator_random" -v`
Expected: FAIL — the current handler unconditionally sends Ea and never enters `NUMERIC_COMPARE_PENDING`.

- [ ] **Step 3: Extract Initiator Ea-send into a helper, then branch**

In `pybluehost/ble/_smp_state.py`, refactor `_sc_initiator_recv_peer_random` (around lines 489-526). Move the Phase 2.3 Ea-send block into a new function `_sc_send_dhkey_check_initiator`, then branch on the association model:

```python
async def _sc_send_dhkey_check_initiator(ctx: "SMPPairingContext") -> None:
    """Initiator Phase 2.3: compute and send Ea, advance to DHKEY_CHECK.

    Extracted from _sc_initiator_recv_peer_random so that NC pairing can defer
    this until the user confirms the numeric value.
    """
    from pybluehost.ble.smp import SMPPairingDHKeyCheck, SMPState
    local_addr = _local_address_bytes(ctx)
    peer_addr = _peer_address_bytes(ctx)
    a1 = b"\x00" + local_addr  # type 0 = public
    a2 = b"\x00" + peer_addr
    io_cap_a = bytes([ctx.local_auth_req, 0x00, int(ctx.local_io_caps)])
    ea = SMPCrypto.f6(ctx.mac_key, ctx.local_random, ctx.peer_random, b"\x00" * 16, io_cap_a, a1, a2)
    ctx.local_dhkey_check = ea
    await ctx.send(SMPPairingDHKeyCheck(dhkey_check=ea).to_bytes())
    ctx.state_machine._state = SMPState.DHKEY_CHECK
```

Then rewrite `_sc_initiator_recv_peer_random` to keep verify + f5, then branch:

```python
async def _sc_initiator_recv_peer_random(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Initiator: Responder's Random Nb arrived. Verify Cb, derive f5,
    then branch on association model (NC → NUMERIC_COMPARE_PENDING, JW → send Ea)."""
    ctx.peer_random = pdu.random_value
    # Verify Cb = f4(PKbx, PKax, Nb, 0)
    pkbx = ctx.peer_public_key[:32]
    pkax = ctx.local_public_key[:32]
    expected = SMPCrypto.f4(pkbx, pkax, ctx.peer_random, 0)
    if expected != ctx.peer_confirm:
        await _on_failed(ctx, reason=0x04)  # CONFIRM_VALUE_FAILED
        return
    # Override state: SC does not use STK; advance to RANDOM_EXCHANGE.
    ctx.state_machine._state = SMPState.RANDOM_EXCHANGE
    # Derive (MacKey, LTK_sc) = f5(DHKey, Na, Nb, A1, A2)
    local_addr = _local_address_bytes(ctx)
    peer_addr = _peer_address_bytes(ctx)
    a1 = b"\x00" + local_addr
    a2 = b"\x00" + peer_addr
    mac_key, ltk = SMPCrypto.f5(ctx.dhkey, ctx.local_random, ctx.peer_random, a1, a2)
    ctx.mac_key = mac_key
    ctx.ltk_sc = ltk

    # NEW (Sub-Plan 3a): branch on association model
    if _association_model(ctx) == "numeric_comparison":
        ctx.state_machine._state = SMPState.NUMERIC_COMPARE_PENDING
        await _sc_compute_and_await_nc(ctx)
        return
    # Just Works: send Ea immediately and advance to DHKEY_CHECK
    await _sc_send_dhkey_check_initiator(ctx)
```

Apply the same NC branching to `_sc_responder_recv_peer_random` (around lines 529-544). The Responder doesn't send Ea — it just derives f5 and waits for the Initiator's Ea. But for NC, we still want the Responder to compute g2 and await user confirm in parallel:

```python
async def _sc_responder_recv_peer_random(ctx: "SMPPairingContext", *, pdu, **_kw) -> None:
    """SC Responder: Initiator's Random Na arrived. Send own Nb, derive f5,
    then for NC: enter NUMERIC_COMPARE_PENDING and await user confirm."""
    from pybluehost.ble.smp import SMPPairingRandom
    ctx.peer_random = pdu.random_value
    await ctx.send(SMPPairingRandom(random_value=ctx.local_random).to_bytes())
    local_addr = _local_address_bytes(ctx)
    peer_addr = _peer_address_bytes(ctx)
    a1 = b"\x00" + peer_addr   # Initiator = peer
    a2 = b"\x00" + local_addr  # Responder = local
    mac_key, ltk = SMPCrypto.f5(ctx.dhkey, ctx.peer_random, ctx.local_random, a1, a2)
    ctx.mac_key = mac_key
    ctx.ltk_sc = ltk

    # NEW (Sub-Plan 3a): NC branch — enter pending state, await delegate
    if _association_model(ctx) == "numeric_comparison":
        ctx.state_machine._state = SMPState.NUMERIC_COMPARE_PENDING
        await _sc_compute_and_await_nc(ctx)
```

- [ ] **Step 4: Register NC state-machine transitions**

In `pybluehost/ble/_smp_state.py`, locate `register_transitions` (search for it; that's the function that wires `state_machine.add_transition(...)` calls). Add the NC transitions for both Initiator and Responder. Pattern:

```python
# Inside register_transitions(sm, ctx) — add after the SC RANDOM_EXCHANGE/DHKEY_CHECK transitions:

# Sub-Plan 3a: Numeric Comparison transitions
sm.add_transition(
    SMPState.NUMERIC_COMPARE_PENDING,
    SMPEvent.NUMERIC_COMPARE_USER_CONFIRMED,
    SMPState.DHKEY_CHECK,
    action=lambda **kw: _nc_user_confirmed(ctx, **kw),
)
sm.add_transition(
    SMPState.NUMERIC_COMPARE_PENDING,
    SMPEvent.NUMERIC_COMPARE_USER_REJECTED,
    SMPState.FAILED,
    action=lambda **kw: _on_failed(ctx, reason=0x03),  # Auth Requirements
)
# Universal failure transitions while in NC_PENDING (mirror Sub-Plan 1 pattern):
sm.add_transition(
    SMPState.NUMERIC_COMPARE_PENDING,
    SMPEvent.PAIRING_FAILED_RX,
    SMPState.FAILED,
    action=lambda **kw: _on_pairing_failed_rx(ctx, **kw),
)
sm.add_transition(
    SMPState.NUMERIC_COMPARE_PENDING,
    SMPEvent.DISCONNECTED,
    SMPState.FAILED,
    action=lambda **kw: _on_disconnected(ctx, **kw),
)
sm.add_transition(
    SMPState.NUMERIC_COMPARE_PENDING,
    SMPEvent.TIMEOUT,
    SMPState.FAILED,
    action=lambda **kw: _on_failed(ctx, reason=0x03),
)
```

Use the exact action-callback names that already exist in this file (e.g. `_on_pairing_failed_rx`, `_on_disconnected`) — grep first to confirm. If `_on_pairing_failed_rx` is not named exactly that, match it to the existing handler.

Then implement `_nc_user_confirmed`:

```python
async def _nc_user_confirmed(ctx: "SMPPairingContext", **_kw) -> None:
    """User confirmed numeric value; resume SC Phase 2.3 (Initiator sends Ea; Responder waits).

    Responder side: nothing to send — DHKEY_CHECK_RX will trigger Eb send via
    existing Sub-Plan 2 transition.
    """
    from pybluehost.ble.smp import PairingRole
    if ctx.role == PairingRole.INITIATOR:
        await _sc_send_dhkey_check_initiator(ctx)
    # Responder: no immediate action — wait for peer's Ea (PAIRING_DHKEY_CHECK_RX).
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/ble/test_smp_numeric_comparison.py -v`
Expected: all PASS.

Run: `uv run pytest tests/unit/ble/ -q`
Expected: no regressions in any existing SMP tests (Sub-Plans 1/2 still green).

- [ ] **Step 6: Commit**

```bash
git add pybluehost/ble/_smp_state.py tests/unit/ble/test_smp_numeric_comparison.py
git commit -m "feat(ble/smp): branch SC Random handlers on association model

Sub-Plan 3a Task 5. Both Initiator and Responder, after deriving the f5 keys,
now consult _association_model(): NC → enter NUMERIC_COMPARE_PENDING and
spawn delegate.confirm_numeric task; JW → unchanged (Initiator sends Ea
immediately, Responder waits for Ea). Adds NC transitions to register_transitions:
confirmed → DHKEY_CHECK, rejected/timeout/disconnect → FAILED(reason=0x03)."
```

---

## Task 6: `_persist_bond` sets `authenticated=True` for NC

**Files:**
- Modify: `pybluehost/ble/_smp_state.py:711-776` (`_persist_bond`)
- Test: `tests/unit/ble/test_smp_numeric_comparison.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
@pytest.mark.asyncio
async def test_persist_bond_authenticated_true_for_nc(monkeypatch, tmp_path):
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import BondInfo, PairingRole
    from pybluehost.core.address import BDAddress

    saved: list[BondInfo] = []

    class _MemStorage:
        async def save_bond(self, bond):
            saved.append(bond)

    monkeypatch.setattr(state_mod, "_sc_negotiated", lambda ctx: True)
    monkeypatch.setattr(state_mod, "_association_model", lambda ctx: "numeric_comparison")

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


@pytest.mark.asyncio
async def test_persist_bond_authenticated_false_for_sc_just_works(monkeypatch):
    from pybluehost.ble import _smp_state as state_mod
    from pybluehost.ble.smp import BondInfo, PairingRole
    from pybluehost.core.address import BDAddress

    saved: list[BondInfo] = []

    class _MemStorage:
        async def save_bond(self, bond):
            saved.append(bond)

    monkeypatch.setattr(state_mod, "_sc_negotiated", lambda ctx: True)
    monkeypatch.setattr(state_mod, "_association_model", lambda ctx: "just_works")

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
    assert saved[0].authenticated is False
    assert saved[0].sc is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/ble/test_smp_numeric_comparison.py -k persist_bond -v`
Expected: `authenticated` is `False` in both cases (current behavior).

- [ ] **Step 3: Update `_persist_bond`**

In `pybluehost/ble/_smp_state.py:711`, in the `sc_mode` branch (around lines 730-743), replace the `authenticated=False` hardcode with a derived value:

```python
        if sc_mode:
            # SC: both sides share the f5-derived LTK; EDIV/RAND are unused in SC.
            # Sub-Plan 3a: NC provides MITM authentication; Just Works does not.
            authenticated = _association_model(ctx) == "numeric_comparison"
            bond = BondInfo(
                peer_address=ctx.peer_address,
                address_type=ctx.received_identity_address[0],
                ltk=ctx.ltk_sc if ctx.ltk_sc else None,
                irk=ctx.received_irk if ctx.received_irk else None,
                csrk=ctx.received_csrk if ctx.received_csrk else None,
                ediv=0,
                rand=b"\x00" * 8,
                key_size=16,
                authenticated=authenticated,
                sc=True,
            )
```

Leave the Legacy branch untouched.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/ble/test_smp_numeric_comparison.py -k persist_bond -v`
Expected: 2 PASS.

Run: `uv run pytest tests/unit/ble/ -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/ble/_smp_state.py tests/unit/ble/test_smp_numeric_comparison.py
git commit -m "feat(ble/smp): BondInfo.authenticated=True for NC pairing

Sub-Plan 3a Task 6. _persist_bond now sets authenticated=True iff the SC
association model resolved to numeric_comparison. SC Just Works remains
unauthenticated. Legacy bonds unchanged."
```

---

## Task 7: SSPManager delegate dispatch for `User_Confirmation_Request`

**Files:**
- Modify: `pybluehost/classic/gap.py:280-366` (`SSPManager`)
- Modify: `pybluehost/stack.py:240-244`
- Test: `tests/unit/classic/test_ssp_numeric_comparison.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/classic/test_ssp_numeric_comparison.py`:

```python
"""Sub-Plan 3a: SSPManager delegate dispatch for BR/EDR Numeric Comparison."""
from __future__ import annotations

import asyncio
import pytest

from pybluehost.classic.gap import SSPManager
from pybluehost.core.address import BDAddress
from pybluehost.hci.controller import HCIEvent
from pybluehost.hci.events import EventCode


class _FakeHCI:
    def __init__(self):
        self.commands: list[bytes] = []

    async def send_command(self, pkt):
        # Capture command opcode for assertions
        self.commands.append(bytes(pkt))
        # Return a benign object (most callers don't await a return event here)
        return object()


class _CapturingDelegate:
    def __init__(self, accept: bool = True):
        self.accept = accept
        self.calls: list[tuple] = []
    async def confirm_numeric(self, peer_addr, value):
        self.calls.append((peer_addr, value))
        return self.accept


def _make_user_confirmation_event(addr_bytes: bytes, numeric: int) -> HCIEvent:
    # USER_CONFIRMATION_REQUEST parameters: BD_ADDR (6) + Numeric_Value (4 LE)
    params = addr_bytes + numeric.to_bytes(4, "little")
    return HCIEvent(event_code=EventCode.USER_CONFIRMATION_REQUEST, parameters=params)


@pytest.mark.asyncio
async def test_ssp_user_confirmation_calls_delegate_confirm_numeric():
    hci = _FakeHCI()
    delegate = _CapturingDelegate(accept=True)
    ssp = SSPManager(hci=hci, delegate=delegate)
    addr_bytes = bytes.fromhex("010203040506")
    await ssp.on_hci_event(_make_user_confirmation_event(addr_bytes, 314159))
    # Allow scheduled reply task to run
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert delegate.calls == [(BDAddress(addr_bytes), 314159)]
    # First HCI command sent is HCI_USER_CONFIRMATION_REQUEST_REPLY (opcode 0x042C)
    assert any(cmd[:2] == bytes.fromhex("2C04") for cmd in hci.commands)


@pytest.mark.asyncio
async def test_ssp_user_confirmation_negative_reply_when_delegate_rejects():
    hci = _FakeHCI()
    delegate = _CapturingDelegate(accept=False)
    ssp = SSPManager(hci=hci, delegate=delegate)
    addr_bytes = bytes.fromhex("AABBCCDDEEFF")
    await ssp.on_hci_event(_make_user_confirmation_event(addr_bytes, 42))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    # HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY opcode 0x042D
    assert any(cmd[:2] == bytes.fromhex("2D04") for cmd in hci.commands)


@pytest.mark.asyncio
async def test_ssp_user_confirmation_auto_accepts_when_no_delegate():
    """Backward compat: SSPManager with no delegate auto-accepts."""
    hci = _FakeHCI()
    ssp = SSPManager(hci=hci)  # No delegate
    await ssp.on_hci_event(_make_user_confirmation_event(bytes(6), 1))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    # Opcode 0x042C = HCI_USER_CONFIRMATION_REQUEST_REPLY (positive)
    assert any(cmd[:2] == bytes.fromhex("2C04") for cmd in hci.commands)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/classic/test_ssp_numeric_comparison.py -v`
Expected: FAIL — `SSPManager.__init__` does not accept `delegate=...`.

- [ ] **Step 3: Add `delegate` kwarg to `SSPManager.__init__` and rewrite the handler**

In `pybluehost/classic/gap.py:283-295`, extend `SSPManager.__init__`:

```python
class SSPManager:
    """Secure Simple Pairing manager."""

    def __init__(
        self,
        hci: object,
        *,
        security_config: object | None = None,
        bond_storage: object | None = None,
        delegate: object | None = None,  # NEW (Sub-Plan 3a)
    ) -> None:
        self._hci = hci
        self._security_config = security_config
        self._bond_storage = bond_storage
        self._delegate = delegate
        self._io_capability: int = 0x03  # NoInputNoOutput
        self._confirm_handler: Callable[[BDAddress, int], bool] | None = None
        self._pending_replies: set[asyncio.Task[object]] = set()
```

Then in `on_hci_event` (around lines 339-348), replace the `USER_CONFIRMATION_REQUEST` block with delegate-first dispatch:

```python
        if event.event_code == EventCode.USER_CONFIRMATION_REQUEST:
            address = BDAddress(event.parameters[:6])
            numeric_value = int.from_bytes(event.parameters[6:10], "little")
            self._schedule_reply(self._dispatch_user_confirmation(address, numeric_value))
            return
```

And add a new async method on `SSPManager`:

```python
    async def _dispatch_user_confirmation(self, address: BDAddress, numeric_value: int) -> None:
        """Sub-Plan 3a: prefer delegate.confirm_numeric, fall back to sync handler, else auto-accept."""
        if self._delegate is not None and hasattr(self._delegate, "confirm_numeric"):
            try:
                accepted = await self._delegate.confirm_numeric(address, numeric_value)
            except Exception:  # noqa: BLE001
                accepted = False
        elif self._confirm_handler is not None:
            accepted = bool(self._confirm_handler(address, numeric_value))
        else:
            accepted = True  # Backward compat: auto-accept
        if accepted:
            await self.confirm(address)
        else:
            await self.deny(address)
```

Note: the existing handler dispatch through `_schedule_reply(self.confirm(...))` returns an `asyncio.Task`. Verify the new helper integrates correctly with `_schedule_reply` — `_schedule_reply` expects an awaitable, and `_dispatch_user_confirmation(...)` is one.

- [ ] **Step 4: Wire delegate into `Stack._build`**

In `pybluehost/stack.py:240-244`, update the SSPManager construction to forward the SMP's delegate:

```python
            classic_ssp=SSPManager(
                hci=hci,
                security_config=cfg.security,
                bond_storage=cfg.bond_storage,
                delegate=smp._delegate,  # Sub-Plan 3a: share PairingDelegate with SMP
            ),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/classic/test_ssp_numeric_comparison.py -v`
Expected: 3 PASS.

Run: `uv run pytest tests/unit/classic/ tests/unit/ble/ -q`
Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add pybluehost/classic/gap.py pybluehost/stack.py tests/unit/classic/test_ssp_numeric_comparison.py
git commit -m "feat(classic/ssp): User_Confirmation_Request delegate dispatch

Sub-Plan 3a Task 7. SSPManager now accepts a delegate kwarg. On
USER_CONFIRMATION_REQUEST it calls delegate.confirm_numeric(addr, value);
falls back to the legacy sync _confirm_handler if no delegate; otherwise
auto-accepts (backward compat). Stack._build forwards SMPManager._delegate
to SSPManager so a single PairingDelegate handles both LE and BR/EDR NC."
```

---

## Task 8: LE SC NC loopback E2E + STATUS.md

**Files:**
- Create: `tests/integration/test_pairing_le_sc_nc_loopback.py`
- Modify: `docs/superpowers/STATUS.md`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_pairing_le_sc_nc_loopback.py` (model after the existing `tests/integration/test_pairing_le_sc_loopback.py` — read that file first for the exact `Stack.virtual()` fixture pattern and the VirtualLELink bridge setup).

```python
"""Sub-Plan 3a: LE SC Numeric Comparison E2E via VirtualLELink."""
from __future__ import annotations

import asyncio
import pytest

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import AutoAcceptDelegate
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability
from pybluehost.stack import Stack, StackConfig


class _RejectingDelegate(AutoAcceptDelegate):
    """Rejects every numeric-comparison request."""
    async def confirm_numeric(self, peer_addr, value):
        return False


def _nc_security_config() -> SecurityConfig:
    return SecurityConfig(
        enable_secure_connections=True,
        mitm_required=True,
        # auth_requirements: Bonding (0x01) | MITM (0x04) | SC (0x08) = 0x0D
        auth_requirements=0x0D,
    )


def _stack_config_with_nc(*, io_cap: int = int(IOCapability.DISPLAY_YES_NO)) -> StackConfig:
    cfg = StackConfig()
    cfg.security = _nc_security_config()
    cfg.le_io_capability = io_cap
    cfg.bondable = True
    return cfg


@pytest.mark.asyncio
async def test_le_sc_numeric_comparison_succeeds_with_auto_accept(virtual_le_link):
    """Two virtual stacks with NC settings pair, both bonds get authenticated=True
    and the same f5 LTK."""
    cfg_a = _stack_config_with_nc()
    cfg_b = _stack_config_with_nc()
    central_addr = BDAddress(bytes.fromhex("AA"*6))
    peripheral_addr = BDAddress(bytes.fromhex("BB"*6))

    stack_a = await Stack.virtual(config=cfg_a, address=central_addr)
    stack_b = await Stack.virtual(config=cfg_b, address=peripheral_addr)
    try:
        virtual_le_link.bridge(stack_a, stack_b)
        # Bring up an LE connection and trigger pairing — copy the pattern from
        # test_pairing_le_sc_loopback.py (look for `connect`, `pair`, await pairing_complete).
        # Both delegates auto-accept by default.
        handle_a, handle_b = await _establish_le_link(stack_a, stack_b, peripheral_addr)
        await asyncio.wait_for(stack_a._smp.pair(handle_a), timeout=5)

        bond_a = await cfg_a.bond_storage.load_bond(peripheral_addr)
        bond_b = await cfg_b.bond_storage.load_bond(central_addr)
        assert bond_a is not None and bond_b is not None
        assert bond_a.authenticated is True
        assert bond_b.authenticated is True
        assert bond_a.ltk == bond_b.ltk
    finally:
        await stack_a.close()
        await stack_b.close()


@pytest.mark.asyncio
async def test_le_sc_numeric_comparison_rejected_by_responder(virtual_le_link):
    """Responder's delegate returns False → pairing fails with reason=0x03."""
    cfg_a = _stack_config_with_nc()
    cfg_b = _stack_config_with_nc()
    central_addr = BDAddress(bytes.fromhex("AA"*6))
    peripheral_addr = BDAddress(bytes.fromhex("BB"*6))

    stack_a = await Stack.virtual(config=cfg_a, address=central_addr)
    stack_b = await Stack.virtual(config=cfg_b, address=peripheral_addr)
    try:
        virtual_le_link.bridge(stack_a, stack_b)
        # Inject rejecting delegate on stack_b
        stack_b._smp.set_delegate(_RejectingDelegate())
        # Also propagate to SSP — but for LE-only NC, SSP path doesn't run.
        handle_a, handle_b = await _establish_le_link(stack_a, stack_b, peripheral_addr)
        with pytest.raises(Exception):  # SMP raises PairingError(0x03) or similar
            await asyncio.wait_for(stack_a._smp.pair(handle_a), timeout=5)
    finally:
        await stack_a.close()
        await stack_b.close()


# Helper: copy or import _establish_le_link from the existing SC loopback test file.
```

**Note for the implementer:** The exact connection-establishment helper and SMP entry-point name may vary — read `tests/integration/test_pairing_le_sc_loopback.py` first and adapt. The conftest fixture `virtual_le_link` (or its actual name) likewise must match what already exists.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_pairing_le_sc_nc_loopback.py -v`
Expected: FAIL — likely on missing helper or because pairing currently does Just Works (not NC) even with mitm_required set, if any wiring is incomplete.

- [ ] **Step 3: Fix any wiring gaps surfaced by the test**

If `mitm_required=True` does not translate into `auth_req` bit 2 being set on the wire, find where `local_auth_req` is constructed from `SecurityConfig` (in `SMPManager.pair()` or feature-exchange code) and ensure `mitm_required` is OR'd into `auth_req`:

```python
auth_req = 0
if cfg.bondable: auth_req |= 0x01
if cfg.mitm_required: auth_req |= 0x04
if cfg.enable_secure_connections: auth_req |= 0x08
```

Grep for `auth_req` in `pybluehost/ble/smp.py` and `_smp_state.py` to find the exact construction site.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_pairing_le_sc_nc_loopback.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Run full suite**

Run: `uv run pytest tests/ -q`
Expected: only the 3 pre-existing USB-diagnostics failures (documented in STATUS.md); everything else PASS.

- [ ] **Step 6: Update STATUS.md**

In `docs/superpowers/STATUS.md`:
- In the "快速定位" block, move Sub-Plan 3a from in-progress to completed (✅).
- In the per-Plan progress block for Sub-Plan 3a (create one if absent), set 状态 to ✅ with completion date.
- Append the bond-authentication change to the architectural-decisions log if such a section exists.

- [ ] **Step 7: Commit**

```bash
git add tests/integration/test_pairing_le_sc_nc_loopback.py docs/superpowers/STATUS.md
git commit -m "test(integration): LE SC Numeric Comparison loopback E2E

Sub-Plan 3a Task 8. Two Stack.virtual() instances pair via NC with auto-accept
delegates → both bonds end up with authenticated=True and identical f5 LTKs.
Reject path: Responder's delegate returns False → pairing fails with reason
0x03 (Authentication Requirements). Marks Sub-Plan 3a complete in STATUS.md."
```

---

## Acceptance Checklist

- [ ] `SecurityConfig.mitm_required` field added; defaults False
- [ ] `PairingDelegate.confirm_numeric(peer_addr, value)` + `AutoAcceptDelegate.confirm_numeric`
- [ ] `_association_model()` returns NC vs Just Works correctly across the 6 unit-test scenarios
- [ ] `SMPState.NUMERIC_COMPARE_PENDING` (=10) + 2 SMPEvent values (=18,=19)
- [ ] `_sc_compute_and_await_nc()` computes `g2 % 10^6`, dispatches to delegate, fires the appropriate event
- [ ] `_sc_initiator_recv_peer_random` and `_sc_responder_recv_peer_random` branch on association model
- [ ] Initiator Ea send extracted into `_sc_send_dhkey_check_initiator` and gated behind user confirmation for NC
- [ ] `_persist_bond` sets `authenticated=True` for NC, `False` for SC Just Works
- [ ] `SSPManager` accepts `delegate` kwarg and dispatches `User_Confirmation_Request` via `delegate.confirm_numeric`
- [ ] `Stack._build` forwards SMP's delegate to SSPManager
- [ ] LE SC NC loopback E2E test: confirm path → authenticated bond; reject path → PAIRING_FAILED(0x03)
- [ ] Full suite: only pre-existing USB-diagnostics failures; coverage ≥ 85%
- [ ] STATUS.md updated to mark Sub-Plan 3a ✅

## Out of Scope (deferred)

| Item | Future Plan |
|------|-------------|
| Passkey Entry (Legacy 20-round + SC 20-round) | Sub-Plan 3b |
| OOB (Legacy + SC) | Sub-Plan 3c |
| DisplayOnly / KeyboardOnly IO caps + full 5×5 matrix | Sub-Plan 3b/3c |
| Real-hardware automated verification | Independent Plan |
| BR/EDR NC two-controller loopback | Independent Plan (current BR/EDR SC tests are HCI-event-driven only) |
