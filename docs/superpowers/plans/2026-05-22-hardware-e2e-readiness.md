# Hardware E2E Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing e2e suite runnable against real BR/EDR + LE USB adapters once one is procured, by (a) unblocking three currently-skipped tests via a `build_stack_from_spec(config=)` kwarg, (b) adding transport-aware timeouts so real RF latency doesn't false-fail tests, (c) shipping a `pybluehost tools info` CLI that dumps the full HCI capability set of an adapter, and (d) writing a runbook for the manual hardware verification step.

**Architecture:** Four mostly-independent deliverables. The factory + timeout helper are mechanical signature widening. The `info` CLI uses the existing `HCIController.supported_commands` cache plus a new pure-data feature-decode module. The runbook is documentation only. All four items are verifiable on virtual transport today; no real hardware required to land this Plan.

**Tech Stack:** Python 3.10+, pytest, pytest-asyncio. Reuses `Stack`, `HCIController`, `SupportedCommands`, the existing `pybluehost/cli/tools/` subcommand dispatch (`register_*_command` pattern), and the `tests/_transport_resolve.py` factory.

**Design spec:** [`docs/superpowers/specs/2026-05-22-hardware-e2e-readiness-design.md`](../specs/2026-05-22-hardware-e2e-readiness-design.md)

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Modify | `tests/_transport_resolve.py:118-139` | `build_stack_from_spec(spec, *, config=None)` threads `config` through every transport branch |
| Modify | `tests/e2e/_helpers.py` | Add `e2e_timeout(transport_mode, *, virtual, usb=None, uart=None) -> float` |
| Modify | `tests/e2e/test_le_lifecycle.py` | Replace virtual-only `_open_pair` in Test 3 with `build_stack_from_spec(config=)`; drop the hardware skip |
| Modify | `tests/e2e/test_classic_lifecycle.py` | Same migration in Tests 3 and 4 |
| Modify | `tests/e2e/test_le_lifecycle.py` + `tests/e2e/test_classic_lifecycle.py` | Wrap short-budget `asyncio.wait_for` calls in `e2e_timeout(transport_mode, ...)` |
| Create | `pybluehost/hci/features_decode.py` | Pure-data: `LE_FEATURE_BIT_NAMES`, `BREDR_FEATURE_BIT_NAMES`, `MANUFACTURER_NAMES` |
| Modify | `pybluehost/hci/capabilities.py:37` | Extend `_OPCODE_BIT_POSITIONS` with BR/EDR + SC opcodes used by the bridge |
| Create | `pybluehost/cli/tools/info.py` | `register_info_command` + `_cmd_info` rendering human-table or `--json` |
| Modify | `pybluehost/cli/tools/__init__.py` | Register `info` alongside existing tools |
| Create | `docs/HARDWARE_E2E.md` | Runbook covering quick-start, matrix, info usage, triage, etc. |
| Create | `tests/unit/test_build_stack_from_spec_config.py` | 3 unit tests for the kwarg |
| Create | `tests/unit/test_e2e_timeout.py` | 4 unit tests for the helper |
| Create | `tests/unit/cli/tools/test_info.py` | 6 unit tests for the CLI |
| Modify | `docs/superpowers/STATUS.md` | Mark Plan complete; add follow-ups |

---

## Task 1: `build_stack_from_spec(config=)` kwarg

**Files:**
- Modify: `tests/_transport_resolve.py` (around line 118)
- Test: `tests/unit/test_build_stack_from_spec_config.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_build_stack_from_spec_config.py`:

```python
"""Unit tests for build_stack_from_spec(config=) kwarg."""
from __future__ import annotations

import pytest

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import JsonBondStorage
from pybluehost.stack import StackConfig

from tests._transport_resolve import build_stack_from_spec


@pytest.mark.asyncio
async def test_build_stack_from_spec_virtual_with_config_threads_config(tmp_path):
    cfg = StackConfig(
        bond_storage=JsonBondStorage(tmp_path / "bonds.json"),
        security=SecurityConfig(enable_secure_connections=True),
    )
    stack = await build_stack_from_spec("virtual", config=cfg)
    try:
        assert stack._config is cfg
    finally:
        await stack.close()


@pytest.mark.asyncio
async def test_build_stack_from_spec_virtual_without_config_uses_default():
    """No config supplied: backward-compatible — Stack still constructs."""
    stack = await build_stack_from_spec("virtual")
    try:
        # Whether _config is None or a default StackConfig depends on Stack.virtual's
        # contract — both are acceptable; assert the stack works.
        assert stack._virtual_controller is not None
    finally:
        await stack.close()


@pytest.mark.asyncio
async def test_build_stack_from_spec_unknown_transport_raises():
    """Sanity: unknown spec still rejected even with config supplied."""
    cfg = StackConfig()
    with pytest.raises(Exception):
        await build_stack_from_spec("bogus:foo", config=cfg)
```

- [ ] **Step 2: Run failing tests**

```
uv run pytest tests/unit/test_build_stack_from_spec_config.py -v
```
Expected: 2 of 3 FAIL with `TypeError: build_stack_from_spec() got an unexpected keyword argument 'config'`. (The unknown-transport test should still pass since it doesn't depend on `config=` working.)

- [ ] **Step 3: Modify `build_stack_from_spec`**

In `tests/_transport_resolve.py`, change the signature and thread `config` through:

```python
async def build_stack_from_spec(spec: str, *, config=None):
    """Build a Stack from a transport spec string.

    Threads optional StackConfig through every transport branch so tests that
    need per-test bond storage / security config can use the same factory in
    both virtual and hardware modes.
    """
    if spec == "virtual":
        return await Stack.virtual(config=config) if config is not None else await Stack.virtual()
    if spec.startswith("usb:") or spec == "usb":
        # Parse the existing usb spec (vendor=, VID:PID, occurrence #N, etc.) the
        # same way the current code does, then pass config= to Stack.from_usb.
        # ... existing parse logic unchanged ...
        return await Stack.from_usb(
            # ... existing kwargs ...,
            config=config,
        )
    if spec.startswith("uart:") or spec == "uart":
        # ... existing parse ...
        return await Stack.from_uart(port=port, baudrate=baudrate, config=config)
    raise ValueError(f"unknown transport spec: {spec!r}")
```

Read the existing function first (it's around line 118-139 of `tests/_transport_resolve.py`) and apply the minimal diff: add `*, config=None` to the signature, add `config=config` to each `Stack.from_*` / `Stack.virtual()` call. Don't restructure other logic.

**Verification grep** before writing: `grep -n "Stack.virtual\|Stack.from_usb\|Stack.from_uart" pybluehost/stack.py | head` to confirm each factory's signature accepts `config`. (All do per the e2e Test 3 patterns from prior Plans.)

- [ ] **Step 4: Run tests**

```
uv run pytest tests/unit/test_build_stack_from_spec_config.py -v
```
Expected: all 3 PASS.

```
uv run pytest tests/ -q --transport=virtual
```
Expected: no regressions (the change is additive; existing positional callers `build_stack_from_spec(spec)` still work).

- [ ] **Step 5: Commit**

```bash
git add tests/_transport_resolve.py tests/unit/test_build_stack_from_spec_config.py
git commit -m "feat(tests): build_stack_from_spec accepts config= kwarg

Threads optional StackConfig through every transport branch (virtual, usb,
uart). Backward-compatible: existing positional callers are unaffected.

Unblocks LE Test 3 + Classic Tests 3/4 to run on --transport=usb in
hardware mode (currently they pytest.skip because the factory couldn't
forward the per-test bond_storage + security config)."
```

---

## Task 2: `e2e_timeout` helper

**Files:**
- Modify: `tests/e2e/_helpers.py`
- Test: `tests/unit/test_e2e_timeout.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_e2e_timeout.py`:

```python
"""Unit tests for e2e_timeout(transport_mode, virtual=, usb=, uart=)."""
from __future__ import annotations

from tests.e2e._helpers import e2e_timeout


def test_e2e_timeout_virtual_returns_virtual_value():
    assert e2e_timeout("virtual", virtual=1.0) == 1.0
    assert e2e_timeout("virtual", virtual=0.5, usb=10.0) == 0.5


def test_e2e_timeout_usb_uses_usb_when_supplied():
    assert e2e_timeout("usb", virtual=1.0, usb=5.0) == 5.0


def test_e2e_timeout_usb_defaults_to_5x_virtual_when_not_supplied():
    assert e2e_timeout("usb", virtual=1.0) == 5.0
    assert e2e_timeout("usb", virtual=2.0) == 10.0


def test_e2e_timeout_uart_defaults_to_8x_virtual_when_not_supplied():
    assert e2e_timeout("uart", virtual=1.0) == 8.0


def test_e2e_timeout_unknown_transport_falls_back_to_virtual():
    assert e2e_timeout("tcp", virtual=1.0, usb=5.0) == 1.0
```

- [ ] **Step 2: Run failing tests**

```
uv run pytest tests/unit/test_e2e_timeout.py -v
```
Expected: FAIL — `e2e_timeout` not defined.

- [ ] **Step 3: Add the helper to `tests/e2e/_helpers.py`**

Append:

```python
# ---------------------------------------------------------------------------
# Transport-aware timeout helper (used by e2e scenarios)
# ---------------------------------------------------------------------------

def e2e_timeout(
    transport_mode: str,
    *,
    virtual: float,
    usb: float | None = None,
    uart: float | None = None,
) -> float:
    """Return a transport-appropriate timeout budget.

    Virtual transport completes operations in sub-second time; real RF
    needs more headroom for inquiry timing, page-scan windows, and connection
    setup. Defaults: usb = 5× virtual, uart = 8× virtual.

    Unknown transports fall back to the virtual budget (best-effort).
    """
    if transport_mode == "virtual":
        return virtual
    if transport_mode == "usb":
        return usb if usb is not None else virtual * 5
    if transport_mode == "uart":
        return uart if uart is not None else virtual * 8
    return virtual
```

- [ ] **Step 4: Run tests**

```
uv run pytest tests/unit/test_e2e_timeout.py -v
```
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/_helpers.py tests/unit/test_e2e_timeout.py
git commit -m "feat(tests/e2e): e2e_timeout(transport_mode, virtual=, usb=, uart=) helper

Returns transport-appropriate timeout budget. Virtual transport is sub-second;
real RF needs headroom for inquiry timing and connection setup. Defaults:
usb = 5x virtual, uart = 8x virtual. Unknown transports fall back to the
virtual budget.

Used in Task 4 to widen the short-budget asyncio.wait_for calls in the
e2e scenarios."
```

---

## Task 3: Migrate LE Test 3 + Classic Tests 3/4 to `build_stack_from_spec(config=)`

**Files:**
- Modify: `tests/e2e/test_le_lifecycle.py` (Test 3's `_open_pair`)
- Modify: `tests/e2e/test_classic_lifecycle.py` (Tests 3 and 4's `_open_pair`)

- [ ] **Step 1: Survey the current skip pattern**

```
grep -n "pytest.skip.*hardware mode\|build_stack_from_spec.*config\|transport_mode != .virtual." tests/e2e/test_le_lifecycle.py tests/e2e/test_classic_lifecycle.py
```

Each test currently has either:
```python
if transport_mode != "virtual":
    pytest.skip("hardware mode: build_stack_from_spec doesn't accept config= yet")
```
or directly constructs `Stack.virtual(config=cfg, ...)` only in virtual mode.

- [ ] **Step 2: Replace virtual-only `_open_pair` with the factory**

For each affected test (LE Test 3, Classic Test 3), edit `_open_pair` (defined inside the test function):

Before (sketch):
```python
async def _open_pair():
    cfg_c = StackConfig(bond_storage=..., security=...)
    cfg_p = StackConfig(bond_storage=..., security=...)
    if transport_mode == "virtual":
        stack_c = await Stack.virtual(config=cfg_c, address=central_addr)
        stack_p = await Stack.virtual(config=cfg_p, address=peripheral_addr)
        link = VirtualClassicLink(...)
        link.attach()
    else:
        pytest.skip("...")
    return stack_c, stack_p, link
```

After:
```python
async def _open_pair():
    cfg_c = StackConfig(bond_storage=..., security=...)
    cfg_p = StackConfig(bond_storage=..., security=...)
    stack_c = await build_stack_from_spec(selected_transport_spec, config=cfg_c)
    stack_p = await build_stack_from_spec(selected_peer_spec, config=cfg_p)
    if transport_mode == "virtual":
        # Virtual mode needs an explicit bridge; hardware uses real RF.
        link = VirtualLELink(  # or VirtualClassicLink for Classic Test 3
            central=stack_c._virtual_controller,
            peripheral=stack_p._virtual_controller,
            central_address=stack_c._local_address,
            peripheral_address=stack_p._local_address,
        )
        # Classic only: link.attach()
    else:
        link = None
    return stack_c, stack_p, link
```

For virtual mode, the BD_ADDR can't be set per-test through `build_stack_from_spec` (the factory doesn't expose `address=`). The existing tests pass `address=` directly to `Stack.virtual()`. To preserve the distinct-address invariant for Test 3, **keep** the `Stack.virtual(config=cfg, address=addr)` direct call inside an `if transport_mode == "virtual"` branch — but DROP the `pytest.skip` in the else branch and call `build_stack_from_spec(spec, config=cfg)` instead. Two branches, but no skip.

Concretely:

```python
async def _open_pair():
    cfg_c = StackConfig(...)
    cfg_p = StackConfig(...)
    if transport_mode == "virtual":
        stack_c = await Stack.virtual(config=cfg_c, address=central_addr)
        stack_p = await Stack.virtual(config=cfg_p, address=peripheral_addr)
        link = VirtualLELink(...)   # or VirtualClassicLink for Classic Test 3
        if hasattr(link, "attach"):
            link.attach()
    else:
        # Hardware: use the factory; per-test address override isn't available
        # but the adapter's factory BD_ADDR is fine for hardware pairing tests.
        stack_c = await build_stack_from_spec(selected_transport_spec, config=cfg_c)
        stack_p = await build_stack_from_spec(selected_peer_spec, config=cfg_p)
        link = None
    return stack_c, stack_p, link
```

Drop the `pytest.skip` block entirely. Apply the same pattern to Classic Test 3 and Classic Test 4 (Test 4 doesn't use bond storage but still has a `transport_mode != "virtual"` skip per spec §3).

For Classic Test 4 specifically, the skip currently says `"hardware mode: build_stack_from_spec doesn't accept config= yet"`. Same treatment.

- [ ] **Step 3: Update the test body's `peripheral_addr` references in hardware mode**

In hardware mode, `peripheral_addr` (the constant `BDAddress.from_string("0B:0B:0B:0B:0B:0B")`) doesn't match the real adapter's BD_ADDR. The test needs to use `stack_p._local_address` instead in hardware mode. Update each reference:

```python
peripheral_addr = stack_p._local_address  # works in both modes; virtual stacks return the explicit address
central_addr = stack_c._local_address
```

These two lines go after the `_open_pair()` call in the test body.

- [ ] **Step 4: Run the tests in virtual mode**

```
uv run pytest tests/e2e/test_le_lifecycle.py::test_e2e_bonded_reconnect_auto_encrypt -v --transport=virtual
uv run pytest tests/e2e/test_classic_lifecycle.py::test_e2e_classic_bonded_reconnect_auto_encrypt -v --transport=virtual
uv run pytest tests/e2e/test_classic_lifecycle.py::test_e2e_classic_pair_failure_disconnects_cleanly -v --transport=virtual
```
Expected: all 3 PASS (behavior unchanged in virtual mode).

```
uv run pytest tests/e2e/ -q --transport=virtual
```
Expected: full e2e suite green (no regressions).

- [ ] **Step 5: Verify the hardware skip is gone**

```
grep -n "build_stack_from_spec.*doesn't accept config" tests/e2e/test_le_lifecycle.py tests/e2e/test_classic_lifecycle.py
```
Expected: no matches.

If `--transport=usb:...` were available, the tests would now attempt to run rather than skip. We can't verify this without hardware, but the absence of the skip message is the verifiable contract.

- [ ] **Step 6: Commit**

```bash
git add tests/e2e/test_le_lifecycle.py tests/e2e/test_classic_lifecycle.py
git commit -m "test(e2e): unblock hardware-mode skips for bonded-reconnect tests

LE Test 3, Classic Test 3, and Classic Test 4 previously pytest.skip-ped
in hardware mode because build_stack_from_spec didn't accept config=.
With Task 1's factory widening in place, the hardware-mode branch now
constructs both stacks via build_stack_from_spec(spec, config=cfg) and
uses stack._local_address (adapter BD_ADDR) instead of the virtual-only
palindromic address constants.

Virtual mode behavior unchanged. Hardware mode would now attempt the
test rather than skip (verifiable once a USB adapter pair is available)."
```

---

## Task 4: Wrap short-budget `asyncio.wait_for` calls in `e2e_timeout`

**Files:**
- Modify: `tests/e2e/test_le_lifecycle.py`
- Modify: `tests/e2e/test_classic_lifecycle.py`

- [ ] **Step 1: Survey current short-budget waits**

```
grep -n "asyncio.wait_for\|timeout=" tests/e2e/test_le_lifecycle.py tests/e2e/test_classic_lifecycle.py | grep -v "timeout=2[0-9]\|timeout=6[0-9]" | head -30
```

Focus on numeric timeouts < 5 s — those are the virtual-tuned ones that need widening for hardware.

Long timeouts (`timeout=20.0` for SC Passkey pair waits, `timeout=60.0` etc.) already accommodate hardware. Leave them alone.

- [ ] **Step 2: Wrap each short-budget call site**

For each `asyncio.wait_for(coro, timeout=N)` with N < 5, wrap N in `e2e_timeout`:

```python
# Before
await asyncio.wait_for(spp_conn.recv(), timeout=1.0)

# After
await asyncio.wait_for(
    spp_conn.recv(),
    timeout=e2e_timeout(transport_mode, virtual=1.0, usb=3.0),
)
```

Tests that don't currently parameterize on `transport_mode` need to add the fixture:

```python
async def test_e2e_classic_rfcomm_spp_echo(
    classic_central_peripheral_pair,
    virtual_classic_link_or_real_rf,
    transport_mode,                          # NEW
):
    ...
```

`transport_mode` is a session-scoped fixture from `tests/conftest.py`; injecting it into a function-scoped test is supported.

Import `e2e_timeout` at the top of each test file:

```python
from tests.e2e._helpers import e2e_timeout
```

(If the file already imports from `_helpers`, extend the existing import line.)

**Specific calls to wrap** (verify via grep — list is best-effort):

LE E2E (`test_le_lifecycle.py`):
- `wait_for_notifications(notify_events, n=2, timeout=2.0)` in Test 2 → `timeout=e2e_timeout(transport_mode, virtual=2.0, usb=5.0)`. NB: `wait_for_notifications` takes a `timeout=` parameter directly — wrap there, no `asyncio.wait_for`.
- The encryption-event polling loop in Test 3 (currently `for _ in range(40): if encrypted_events: break; await asyncio.sleep(0.05)`) — replace with `await asyncio.wait_for(_wait_for_encrypted(...), timeout=e2e_timeout(transport_mode, virtual=2.0, usb=10.0))`.
- `await asyncio.wait_for(stack_c.gap.ble_connections.disconnect(handle), timeout=2.0)` in Test 4 → `e2e_timeout(transport_mode, virtual=2.0, usb=3.0)`.
- `await asyncio.wait_for(stack_c.close(), timeout=2.0)` etc.

Classic E2E (`test_classic_lifecycle.py`):
- `await asyncio.wait_for(spp_conn.recv(), timeout=1.0)` in Test 2 → `e2e_timeout(transport_mode, virtual=1.0, usb=3.0)`.
- The `classic_discover_peripheral(..., timeout=3.0)` calls — these helper invocations don't currently use `asyncio.wait_for`, but the inner `await asyncio.wait_for(seen_event.wait(), timeout=timeout)` honors whatever the caller passes. Update each call to pass `timeout=e2e_timeout(transport_mode, virtual=3.0, usb=10.0)`.
- `connect_classic(addr, timeout=3.0)` → `e2e_timeout(transport_mode, virtual=3.0, usb=10.0)`.
- `authenticate_classic(handle, timeout=3.0)` → `e2e_timeout(transport_mode, virtual=3.0, usb=10.0)`.
- `enable_classic_encryption(handle, timeout=2.0)` → `e2e_timeout(transport_mode, virtual=2.0, usb=5.0)`.
- `asyncio.wait_for(stack_c.gap.classic_connections.disconnect(handle), timeout=2.0)` in Test 4 → `e2e_timeout(transport_mode, virtual=2.0, usb=3.0)`.

When in doubt about a specific call, choose `usb = 5 × virtual` (the default the helper applies if you pass `virtual=X` without `usb=`). The above explicit numbers are conservative bumps where the default isn't enough.

- [ ] **Step 3: Run e2e suite in virtual mode**

```
uv run pytest tests/e2e/ -v --transport=virtual
```
Expected: all tests still pass; no slowdown (virtual returns same numbers).

- [ ] **Step 4: Spot-check one wrapped call site**

```
grep -B2 -A2 "e2e_timeout" tests/e2e/test_classic_lifecycle.py | head -20
```
Verify the calls look right — `e2e_timeout(transport_mode, virtual=X, usb=Y)` form.

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/test_le_lifecycle.py tests/e2e/test_classic_lifecycle.py
git commit -m "test(e2e): use e2e_timeout for short-budget asyncio.wait_for calls

Wraps every numeric timeout < 5s in tests/e2e/test_le_lifecycle.py and
tests/e2e/test_classic_lifecycle.py with e2e_timeout(transport_mode,
virtual=, usb=). Virtual mode preserves the existing budgets; hardware
mode gets 3-10× longer budgets to accommodate real RF latency.

Long timeouts (20s pair, 60s SC Passkey) already accommodate hardware
and stay as-is."
```

---

## Task 5: `pybluehost/hci/features_decode.py` (pure-data feature tables)

**Files:**
- Create: `pybluehost/hci/features_decode.py`
- Test: `tests/unit/test_features_decode.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_features_decode.py`:

```python
"""Unit tests for HCI feature-bitmap decoding tables."""
from __future__ import annotations

from pybluehost.hci.features_decode import (
    BREDR_FEATURE_BIT_NAMES,
    LE_FEATURE_BIT_NAMES,
    MANUFACTURER_NAMES,
)


def test_le_feature_bit_names_has_le_encryption():
    assert LE_FEATURE_BIT_NAMES[(0, 0)] == "LE Encryption"


def test_le_feature_bit_names_has_le_2m_phy():
    assert LE_FEATURE_BIT_NAMES[(1, 0)] == "LE 2M PHY"


def test_le_feature_bit_names_keys_are_octet_bit_tuples():
    for key in LE_FEATURE_BIT_NAMES:
        assert isinstance(key, tuple) and len(key) == 2
        octet, bit = key
        assert 0 <= octet <= 7
        assert 0 <= bit <= 7


def test_bredr_feature_bit_names_has_encryption():
    # BR/EDR Features page 0 byte 0 bit 2 is "Encryption"
    assert BREDR_FEATURE_BIT_NAMES[(0, 2)] == "Encryption"


def test_bredr_feature_bit_names_keys_are_octet_bit_tuples():
    for key in BREDR_FEATURE_BIT_NAMES:
        assert isinstance(key, tuple) and len(key) == 2


def test_manufacturer_names_intel():
    assert MANUFACTURER_NAMES[0x0002] == "Intel Corp."


def test_manufacturer_names_realtek():
    assert MANUFACTURER_NAMES[0x005D] == "Realtek Semiconductor Corp."
```

- [ ] **Step 2: Run failing tests**

```
uv run pytest tests/unit/test_features_decode.py -v
```
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create the module**

Create `pybluehost/hci/features_decode.py`:

```python
"""HCI feature-bitmap decoding tables.

Pure-data dictionaries mapping (octet, bit) tuples to human-readable feature
names. Used by `pybluehost tools info` and any future capability-introspection
tooling. No logic; safe to import without HCI state.

References:
  * Core Spec 5.4 Vol 6 Part B §4.6 (LE Features)
  * Core Spec 5.4 Vol 2 Part C §3.3 (BR/EDR LMP Features page 0)
  * Bluetooth Assigned Numbers, Company Identifiers
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# LE Features bitmap (octet, bit) -> name
# Core Spec 5.4 Vol 6 Part B §4.6, Table 4.6.1 (FeatureSet bitmap)
# ---------------------------------------------------------------------------

LE_FEATURE_BIT_NAMES: dict[tuple[int, int], str] = {
    # Octet 0
    (0, 0): "LE Encryption",
    (0, 1): "Connection Parameters Request Procedure",
    (0, 2): "Extended Reject Indication",
    (0, 3): "Slave-initiated Features Exchange",
    (0, 4): "LE Ping",
    (0, 5): "LE Data Packet Length Extension",
    (0, 6): "LL Privacy",
    (0, 7): "Extended Scanner Filter Policies",
    # Octet 1
    (1, 0): "LE 2M PHY",
    (1, 1): "Stable Modulation Index - Transmitter",
    (1, 2): "Stable Modulation Index - Receiver",
    (1, 3): "LE Coded PHY",
    (1, 4): "LE Extended Advertising",
    (1, 5): "LE Periodic Advertising",
    (1, 6): "Channel Selection Algorithm #2",
    (1, 7): "LE Power Class 1",
    # Octet 2
    (2, 0): "Minimum Number of Used Channels Procedure",
    (2, 1): "Connection CTE Request",
    (2, 2): "Connection CTE Response",
    (2, 3): "Connectionless CTE Transmitter",
    (2, 4): "Connectionless CTE Receiver",
    (2, 5): "Antenna Switching During CTE Transmission (AoD)",
    (2, 6): "Antenna Switching During CTE Reception (AoA)",
    (2, 7): "Receiving Constant Tone Extensions",
    # Octet 3
    (3, 0): "Periodic Advertising Sync Transfer - Sender",
    (3, 1): "Periodic Advertising Sync Transfer - Recipient",
    (3, 2): "Sleep Clock Accuracy Updates",
    (3, 3): "Remote Public Key Validation",
    (3, 4): "Connected Isochronous Stream - Central",
    (3, 5): "Connected Isochronous Stream - Peripheral",
    (3, 6): "Isochronous Broadcaster",
    (3, 7): "Synchronized Receiver",
    # Octet 4
    (4, 0): "Connected Isochronous Stream (Host Support)",
    (4, 1): "LE Power Control Request",
    (4, 2): "LE Power Change Indication",
    (4, 3): "LE Path Loss Monitoring",
    (4, 4): "Periodic Advertising ADI Support",
    (4, 5): "Connection Subrating",
    (4, 6): "Connection Subrating (Host Support)",
    (4, 7): "Channel Classification",
    # Octets 5-7 reserved or unused in Spec 5.4 — left empty
}


# ---------------------------------------------------------------------------
# BR/EDR LMP Features page 0, (octet, bit) -> name
# Core Spec 5.4 Vol 2 Part C §3.3, Table 3.2 (LMP feature mask page 0)
# ---------------------------------------------------------------------------

BREDR_FEATURE_BIT_NAMES: dict[tuple[int, int], str] = {
    # Octet 0
    (0, 0): "3-slot packets",
    (0, 1): "5-slot packets",
    (0, 2): "Encryption",
    (0, 3): "Slot offset",
    (0, 4): "Timing accuracy",
    (0, 5): "Role switch",
    (0, 6): "Hold mode",
    (0, 7): "Sniff mode",
    # Octet 1
    (1, 0): "Park state",
    (1, 1): "Power control requests",
    (1, 2): "Channel quality driven data rate (CQDDR)",
    (1, 3): "SCO link",
    (1, 4): "HV2 packets",
    (1, 5): "HV3 packets",
    (1, 6): "u-law log synchronous data",
    (1, 7): "A-law log synchronous data",
    # Octet 2
    (2, 0): "CVSD synchronous data",
    (2, 1): "Paging parameter negotiation",
    (2, 2): "Power control",
    (2, 3): "Transparent synchronous data",
    (2, 4): "Flow control lag (LSB)",
    (2, 5): "Flow control lag (Middle)",
    (2, 6): "Flow control lag (MSB)",
    (2, 7): "Broadcast Encryption",
    # Octet 3
    (3, 1): "EDR ACL 2 Mbps mode",
    (3, 2): "EDR ACL 3 Mbps mode",
    (3, 3): "Enhanced inquiry scan",
    (3, 4): "Interlaced inquiry scan",
    (3, 5): "Interlaced page scan",
    (3, 6): "RSSI with inquiry results",
    (3, 7): "EV3 packets",
    # Octet 4
    (4, 0): "EV4 packets",
    (4, 1): "EV5 packets",
    (4, 3): "AFH capable peripheral",
    (4, 4): "AFH classification peripheral",
    (4, 5): "BR/EDR Not Supported",
    (4, 6): "LE Supported (Controller)",
    (4, 7): "3-slot EDR ACL packets",
    # Octet 5
    (5, 0): "5-slot EDR ACL packets",
    (5, 1): "Sniff subrating",
    (5, 2): "Pause Encryption",
    (5, 3): "AFH capable central",
    (5, 4): "AFH classification central",
    (5, 5): "EDR eSCO 2 Mbps mode",
    (5, 6): "EDR eSCO 3 Mbps mode",
    (5, 7): "3-slot EDR eSCO packets",
    # Octet 6
    (6, 0): "Extended Inquiry Response",
    (6, 1): "Simultaneous LE and BR/EDR to Same Device Capable (Controller)",
    (6, 3): "Secure Simple Pairing (Controller Support)",
    (6, 4): "Encapsulated PDU",
    (6, 5): "Erroneous Data Reporting",
    (6, 6): "Non-flushable Packet Boundary Flag",
    # Octet 7
    (7, 0): "HCI_Link_Supervision_Timeout_Changed Event",
    (7, 1): "Variable Inquiry TX Power Level",
    (7, 2): "Enhanced Power Control",
    (7, 7): "Extended features",
}


# ---------------------------------------------------------------------------
# Bluetooth SIG Company Identifiers (subset of common chipset vendors)
# Full list: https://www.bluetooth.com/specifications/assigned-numbers/company-identifiers/
# ---------------------------------------------------------------------------

MANUFACTURER_NAMES: dict[int, str] = {
    0x0001: "Nokia Mobile Phones",
    0x0002: "Intel Corp.",
    0x0003: "IBM Corp.",
    0x0004: "Toshiba Corp.",
    0x0005: "3Com",
    0x0006: "Microsoft",
    0x0007: "Lucent",
    0x0008: "Motorola",
    0x0009: "Infineon Technologies AG",
    0x000A: "CSR (Qualcomm)",
    0x000B: "Silicon Wave",
    0x000C: "Digianswer A/S",
    0x000D: "Texas Instruments Inc.",
    0x000F: "Broadcom Corporation",
    0x001D: "Atheros Communications",
    0x004C: "Apple Inc.",
    0x005D: "Realtek Semiconductor Corp.",
    0x005F: "MediaTek, Inc.",
    0x0075: "Samsung Electronics Co. Ltd.",
    0x00E0: "Google",
    0x05A7: "Linux Foundation",
}


def manufacturer_name(manufacturer_id: int) -> str:
    """Return the manufacturer name for a Bluetooth SIG company identifier,
    or a fallback string for unknown IDs.
    """
    return MANUFACTURER_NAMES.get(
        manufacturer_id, f"Unknown (0x{manufacturer_id:04X})"
    )
```

- [ ] **Step 4: Run tests**

```
uv run pytest tests/unit/test_features_decode.py -v
```
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/hci/features_decode.py tests/unit/test_features_decode.py
git commit -m "feat(hci): features_decode — LE/BR-EDR feature-bitmap + vendor tables

Pure-data dictionaries mapping (octet, bit) tuples to human-readable feature
names per Core Spec 5.4 Vol 6 Part B §4.6 (LE Features) and Vol 2 Part C §3.3
(BR/EDR LMP Features page 0). Plus a subset of Bluetooth SIG company IDs for
the common chipset vendors (Intel, CSR/Qualcomm, Broadcom, Realtek, etc.)
with an Unknown fallback.

Consumed by Task 7's pybluehost tools info CLI; safe to import without HCI
state."
```

---

## Task 6: Extend `_OPCODE_BIT_POSITIONS` with BR/EDR + SC opcodes

**Files:**
- Modify: `pybluehost/hci/capabilities.py:37`
- Test: `tests/unit/test_capabilities_opcodes.py` (new — or extend existing test)

- [ ] **Step 1: Survey the current map**

```
sed -n '37,60p' pybluehost/hci/capabilities.py
```

Find the list of opcodes already tracked.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_capabilities_opcodes.py`:

```python
"""Unit tests for _OPCODE_BIT_POSITIONS coverage."""
from __future__ import annotations

from pybluehost.hci.capabilities import _OPCODE_BIT_POSITIONS
from pybluehost.hci.constants import (
    HCI_INQUIRY,
    HCI_CREATE_CONNECTION,
    HCI_DISCONNECT,
    HCI_AUTH_REQUESTED,
    HCI_SET_CONNECTION_ENCRYPTION,
    HCI_IO_CAPABILITY_REQUEST_REPLY,
    HCI_USER_CONFIRMATION_REQUEST_REPLY,
    HCI_LE_READ_LOCAL_P256_PUBLIC_KEY,
    HCI_LE_GENERATE_DHKEY,
    HCI_WRITE_SCAN_ENABLE,
)


def test_bredr_basic_opcodes_in_map():
    for opcode in (HCI_INQUIRY, HCI_CREATE_CONNECTION, HCI_DISCONNECT):
        assert opcode in _OPCODE_BIT_POSITIONS, (
            f"opcode 0x{opcode:04X} missing from _OPCODE_BIT_POSITIONS"
        )


def test_bredr_ssp_opcodes_in_map():
    for opcode in (
        HCI_AUTH_REQUESTED,
        HCI_IO_CAPABILITY_REQUEST_REPLY,
        HCI_USER_CONFIRMATION_REQUEST_REPLY,
        HCI_SET_CONNECTION_ENCRYPTION,
    ):
        assert opcode in _OPCODE_BIT_POSITIONS


def test_le_sc_opcodes_in_map():
    for opcode in (HCI_LE_READ_LOCAL_P256_PUBLIC_KEY, HCI_LE_GENERATE_DHKEY):
        assert opcode in _OPCODE_BIT_POSITIONS


def test_write_scan_enable_in_map():
    assert HCI_WRITE_SCAN_ENABLE in _OPCODE_BIT_POSITIONS


def test_all_values_are_octet_bit_tuples():
    for opcode, position in _OPCODE_BIT_POSITIONS.items():
        assert isinstance(position, tuple) and len(position) == 2
        octet, bit = position
        assert 0 <= octet <= 63
        assert 0 <= bit <= 7
```

- [ ] **Step 3: Run failing tests**

```
uv run pytest tests/unit/test_capabilities_opcodes.py -v
```
Expected: FAIL — the opcodes aren't in `_OPCODE_BIT_POSITIONS` yet.

If any of the constants don't exist (`HCI_LE_READ_LOCAL_P256_PUBLIC_KEY`, `HCI_LE_GENERATE_DHKEY`), grep `pybluehost/hci/constants.py` for their actual names. The HCI Tolerant Init Plan added them; verify and adjust the test imports.

- [ ] **Step 4: Add the missing opcode positions**

In `pybluehost/hci/capabilities.py`, extend the `_OPCODE_BIT_POSITIONS` dict with entries per Core Spec 5.4 Vol 4 Part E §6.27, Table 6.27 (Supported Commands bitmap). Reference values (verify against the actual spec table):

```python
_OPCODE_BIT_POSITIONS: dict[int, tuple[int, int]] = {
    # ... existing entries ...

    # BR/EDR Link Control (OGF 0x01)
    HCI_INQUIRY: (0, 0),
    HCI_INQUIRY_CANCEL: (0, 1),
    HCI_CREATE_CONNECTION: (0, 4),
    HCI_DISCONNECT: (0, 5),
    HCI_ACCEPT_CONNECTION_REQ: (1, 0),
    HCI_REJECT_CONNECTION_REQ: (1, 1),
    HCI_LINK_KEY_REQUEST_REPLY: (1, 2),
    HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY: (1, 3),
    HCI_PIN_CODE_REQUEST_REPLY: (1, 4),
    HCI_PIN_CODE_REQUEST_NEGATIVE_REPLY: (1, 5),
    HCI_AUTH_REQUESTED: (1, 7),
    HCI_SET_CONNECTION_ENCRYPTION: (2, 1),
    # SSP commands at octet 32 bits 4-7
    HCI_IO_CAPABILITY_REQUEST_REPLY: (32, 5),
    HCI_USER_CONFIRMATION_REQUEST_REPLY: (32, 6),
    HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY: (32, 7),
    HCI_IO_CAPABILITY_REQUEST_NEGATIVE_REPLY: (33, 5),
    # Controller & Baseband
    HCI_WRITE_SCAN_ENABLE: (6, 2),
    # LE Secure Connections (added by Sub-Plan 3a)
    HCI_LE_READ_LOCAL_P256_PUBLIC_KEY: (34, 1),
    HCI_LE_GENERATE_DHKEY: (34, 2),
}
```

The exact `(octet, bit)` pairs are from Core Spec 5.4 Vol 4 Part E §6.27 Table 6.27. The implementer cross-references each row against the spec. If a value is wrong, that's a per-row fix; the structure is right.

Order the entries logically (group BR/EDR, then SC, then misc), match the existing file's style.

- [ ] **Step 5: Run tests**

```
uv run pytest tests/unit/test_capabilities_opcodes.py -v
```
Expected: 5 PASS.

```
uv run pytest tests/ -q --transport=virtual
```
Expected: no regressions. The new entries are additive; existing `SupportedCommands.has(opcode)` lookups for opcodes that weren't previously in the map start returning correct results, but the bitmap byte itself doesn't change — so existing tests that pass should keep passing.

- [ ] **Step 6: Commit**

```bash
git add pybluehost/hci/capabilities.py tests/unit/test_capabilities_opcodes.py
git commit -m "feat(hci/capabilities): extend _OPCODE_BIT_POSITIONS with BR/EDR + SC opcodes

Adds (octet, bit) positions per Core Spec 5.4 Vol 4 Part E §6.27 Table 6.27
for the BR/EDR opcodes already used by VirtualClassicLink (Inquiry,
Create_Connection, Auth_Requested, etc.) and the LE SC opcodes
(LE_Read_Local_P-256_Public_Key, LE_Generate_DHKey) used by Sub-Plan 3a's
capability gate. ~25 new entries.

Unblocks pybluehost tools info to decode 'supported commands' bits beyond
the original 17 entries from the HCI Tolerant Init Plan."
```

---

## Task 7: `pybluehost tools info` CLI

**Files:**
- Create: `pybluehost/cli/tools/info.py`
- Modify: `pybluehost/cli/tools/__init__.py` (register the subcommand)
- Test: `tests/unit/cli/tools/test_info.py` (new)

- [ ] **Step 1: Survey the existing CLI dispatch pattern**

```
sed -n '1,40p' pybluehost/cli/tools/__init__.py
sed -n '1,80p' pybluehost/cli/tools/usb.py
```

The pattern: each tool module exports `register_<name>_command(subparsers)` and an inner `_cmd_<name>(args)` returning an exit code (0 = success).

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/cli/tools/test_info.py`:

```python
"""Unit tests for `pybluehost tools info`."""
from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_info_human_table_lists_bd_addr_and_manufacturer(capsys):
    """`pybluehost tools info --transport=virtual` lists BD_ADDR + manufacturer."""
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = False

    rc = await _cmd_info_async(_Args())
    captured = capsys.readouterr().out
    assert rc == 0
    assert "BD_ADDR" in captured
    assert "Manufacturer" in captured


@pytest.mark.asyncio
async def test_info_human_table_lists_le_features_decoded(capsys):
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = False

    await _cmd_info_async(_Args())
    captured = capsys.readouterr().out
    # At least one decoded LE feature name should appear
    assert "LE Encryption" in captured or "LE 2M PHY" in captured


@pytest.mark.asyncio
async def test_info_human_table_lists_bredr_features_decoded(capsys):
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = False

    await _cmd_info_async(_Args())
    captured = capsys.readouterr().out
    assert "BR/EDR" in captured or "BR/EDR Features" in captured


@pytest.mark.asyncio
async def test_info_human_table_lists_capability_summary(capsys):
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = False

    await _cmd_info_async(_Args())
    captured = capsys.readouterr().out
    assert "Capability summary" in captured


@pytest.mark.asyncio
async def test_info_json_output_has_required_keys(capsys):
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = True

    rc = await _cmd_info_async(_Args())
    assert rc == 0
    captured = capsys.readouterr().out
    parsed = json.loads(captured)
    for key in ("transport", "bd_addr", "manufacturer_id", "manufacturer_name",
                "capability_summary", "le_features", "bredr_features",
                "supported_commands"):
        assert key in parsed, f"missing key {key!r} in JSON output"


@pytest.mark.asyncio
async def test_info_unknown_command_bits_appear_in_unknown_list(capsys):
    """If a bit is set in the cmd bitmap but not in _OPCODE_BIT_POSITIONS,
    it shows up in the JSON unknown_bits_set list."""
    from pybluehost.cli.tools.info import _cmd_info_async

    class _Args:
        transport = "virtual"
        json = True

    await _cmd_info_async(_Args())
    captured = capsys.readouterr().out
    parsed = json.loads(captured)
    # supported_commands.unknown_bits_set is a list (may be empty for virtual).
    assert "unknown_bits_set" in parsed["supported_commands"]
    assert isinstance(parsed["supported_commands"]["unknown_bits_set"], list)
```

- [ ] **Step 3: Run failing tests**

```
uv run pytest tests/unit/cli/tools/test_info.py -v
```
Expected: FAIL — module doesn't exist.

- [ ] **Step 4: Create the CLI module**

Create `pybluehost/cli/tools/info.py`:

```python
"""pybluehost tools info — dump full HCI capability set of an adapter.

Opens the adapter via the same `--transport=<spec>` syntax as pytest, runs
the standard HCI init sequence (consuming what HCIController.initialize()
caches), and prints either a human-readable table or `--json`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from pybluehost.hci.capabilities import _OPCODE_BIT_POSITIONS
from pybluehost.hci.features_decode import (
    BREDR_FEATURE_BIT_NAMES,
    LE_FEATURE_BIT_NAMES,
    manufacturer_name,
)


def register_info_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "info",
        help="Dump full HCI capability set of an adapter",
    )
    parser.add_argument(
        "--transport",
        required=True,
        help="Transport spec, e.g. 'virtual', 'usb:vendor=intel', 'uart:/dev/ttyUSB0:115200'",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of a human-readable table",
    )
    parser.set_defaults(func=_cmd_info)


def _cmd_info(args: argparse.Namespace) -> int:
    return asyncio.run(_cmd_info_async(args))


async def _cmd_info_async(args: argparse.Namespace) -> int:
    """Async body of the info command."""
    from tests._transport_resolve import build_stack_from_spec

    stack = await build_stack_from_spec(args.transport)
    try:
        data = _collect_capability_data(stack, transport=args.transport)
    finally:
        await stack.close()

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(_format_human_table(data))
    return 0


def _collect_capability_data(stack, *, transport: str) -> dict[str, Any]:
    """Read the cached capability state from the initialized stack."""
    hci = stack._hci
    bd_addr = (
        str(stack._local_address) if stack._local_address is not None else "unknown"
    )
    manufacturer_id = getattr(hci, "manufacturer_id", None) or 0
    hci_version = getattr(hci, "hci_version", None) or "unknown"
    lmp_version = getattr(hci, "lmp_version", None) or 0
    lmp_subversion = getattr(hci, "lmp_subversion", None) or 0

    # Bitmaps
    cmd_bitmap = bytes(hci.supported_commands.bitmap) if hci.supported_commands else b""
    le_features = bytes(getattr(hci, "le_features", b"") or b"")
    bredr_features = bytes(getattr(hci, "bredr_features", b"") or b"")

    le_decoded = _decode_bitmap(le_features, LE_FEATURE_BIT_NAMES)
    bredr_decoded = _decode_bitmap(bredr_features, BREDR_FEATURE_BIT_NAMES)
    cmd_decoded, unknown_bits = _decode_commands_bitmap(cmd_bitmap)

    summary = {
        "le_secure_connections": _bit_set(le_features, 1, 0) and _opcode_set(cmd_bitmap, 34, 1),
        "le_audio": _bit_set(le_features, 4, 4),
        "le_privacy_rpa": _bit_set(le_features, 0, 6),
        "le_extended_advertising": _bit_set(le_features, 1, 4),
        "bredr": _bit_set(bredr_features, 0, 2),
        "bredr_ssp": _opcode_set(cmd_bitmap, 32, 5),
        "bredr_sc": _bit_set(bredr_features, 6, 3),
        "extended_inquiry_response": _bit_set(bredr_features, 6, 0),
    }

    return {
        "transport": transport,
        "bd_addr": bd_addr,
        "manufacturer_id": manufacturer_id,
        "manufacturer_name": manufacturer_name(manufacturer_id),
        "hci_version": hci_version,
        "lmp_version": lmp_version,
        "lmp_subversion": lmp_subversion,
        "capability_summary": summary,
        "le_features": le_decoded,
        "bredr_features": bredr_decoded,
        "supported_commands": {
            "decoded": cmd_decoded,
            "unknown_bits_set": unknown_bits,
        },
    }


def _bit_set(bitmap: bytes, octet: int, bit: int) -> bool:
    if octet >= len(bitmap):
        return False
    return bool(bitmap[octet] & (1 << bit))


def _opcode_set(cmd_bitmap: bytes, octet: int, bit: int) -> bool:
    if octet >= len(cmd_bitmap):
        return False
    return bool(cmd_bitmap[octet] & (1 << bit))


def _decode_bitmap(
    bitmap: bytes, name_table: dict[tuple[int, int], str],
) -> dict[str, dict[str, Any]]:
    """Return {'<octet>/<bit>': {'name': ..., 'supported': bool}} for every named entry."""
    decoded: dict[str, dict[str, Any]] = {}
    for (octet, bit), name in name_table.items():
        decoded[f"{octet}/{bit}"] = {
            "name": name,
            "supported": _bit_set(bitmap, octet, bit),
        }
    return decoded


def _decode_commands_bitmap(
    cmd_bitmap: bytes,
) -> tuple[dict[str, str], list[dict[str, int]]]:
    """Decode the Supported Commands bitmap.

    Returns (decoded, unknown_bits_set). decoded is {'<octet>/<bit>': '<name>'}
    for every known opcode whose bit is set. unknown_bits_set lists set bits
    that don't appear in _OPCODE_BIT_POSITIONS.
    """
    # Build reverse map (octet, bit) -> opcode-name string
    position_to_name: dict[tuple[int, int], str] = {}
    from pybluehost.hci.constants import (
        HCI_INQUIRY, HCI_INQUIRY_CANCEL, HCI_CREATE_CONNECTION, HCI_DISCONNECT,
        # ... import each known opcode name; or use the constants module directly
    )
    # Simpler: build the reverse map at import-time once via inspection of constants.
    # For Plan brevity, the implementer hand-writes a small reverse lookup or
    # iterates _OPCODE_BIT_POSITIONS items and looks up the opcode's symbolic
    # name via vars(pybluehost.hci.constants).items().
    import pybluehost.hci.constants as hci_constants
    opcode_to_name: dict[int, str] = {
        v: k for k, v in vars(hci_constants).items()
        if k.startswith("HCI_") and isinstance(v, int)
    }
    for opcode, (octet, bit) in _OPCODE_BIT_POSITIONS.items():
        position_to_name[(octet, bit)] = opcode_to_name.get(opcode, f"opcode_0x{opcode:04X}")

    decoded: dict[str, str] = {}
    unknown: list[dict[str, int]] = []
    for octet in range(len(cmd_bitmap)):
        byte = cmd_bitmap[octet]
        for bit in range(8):
            if byte & (1 << bit):
                if (octet, bit) in position_to_name:
                    decoded[f"{octet}/{bit}"] = position_to_name[(octet, bit)]
                else:
                    unknown.append({"octet": octet, "bit": bit})
    return decoded, unknown


def _format_human_table(data: dict[str, Any]) -> str:
    """Render the human-readable table form."""
    lines: list[str] = []
    lines.append("PyBlueHost Hardware Survey")
    lines.append("==========================")
    lines.append("")

    lines.append("Adapter identity")
    lines.append("----------------")
    lines.append(f"  Transport       : {data['transport']}")
    lines.append(f"  BD_ADDR         : {data['bd_addr']}")
    lines.append(
        f"  Manufacturer    : {data['manufacturer_name']} "
        f"(0x{data['manufacturer_id']:04X})"
    )
    lines.append(
        f"  HCI Version     : {data['hci_version']} "
        f"(LMP {data['lmp_version']} / subversion 0x{data['lmp_subversion']:04X})"
    )
    lines.append("")

    lines.append("Capability summary")
    lines.append("------------------")
    for key, val in data["capability_summary"].items():
        marker = "✓" if val else "-"
        lines.append(f"  {key:<32} : {marker}")
    lines.append("")

    lines.append("LE Features (octet/bit)")
    lines.append("-----------------------")
    for ob, entry in data["le_features"].items():
        marker = "✓" if entry["supported"] else " "
        lines.append(f"  {ob:<5} {entry['name']:<55} : {marker}")
    lines.append("")

    lines.append("BR/EDR Features (page 0)")
    lines.append("------------------------")
    for ob, entry in data["bredr_features"].items():
        marker = "✓" if entry["supported"] else " "
        lines.append(f"  {ob:<5} {entry['name']:<55} : {marker}")
    lines.append("")

    lines.append("Supported HCI commands (octet/bit → name)")
    lines.append("-----------------------------------------")
    lines.append("  Known commands (decoded):")
    for ob, name in sorted(data["supported_commands"]["decoded"].items()):
        lines.append(f"    {ob:<7} {name}")
    unknown = data["supported_commands"]["unknown_bits_set"]
    lines.append(f"  Unknown bits set: {len(unknown)}")
    for u in unknown[:10]:  # cap at 10 to keep output bounded
        lines.append(f"    octet {u['octet']}, bit {u['bit']}")
    if len(unknown) > 10:
        lines.append(f"    ... and {len(unknown) - 10} more")
    lines.append("")

    lines.append("Recommended pytest invocations")
    lines.append("------------------------------")
    lines.append("  Same adapter only:")
    lines.append(f"    uv run pytest tests/ --transport={data['transport']}")
    lines.append("  Two-adapter peer-to-peer (requires second compatible adapter):")
    lines.append("    uv run pytest tests/e2e/ \\")
    lines.append(f"        --transport={data['transport']}#1 \\")
    lines.append(f"        --transport-peer={data['transport']}#2")
    return "\n".join(lines)
```

- [ ] **Step 5: Register the new subcommand**

In `pybluehost/cli/tools/__init__.py`, extend the imports and registrations:

```python
def register_tools_commands(subparsers: argparse._SubParsersAction) -> None:
    tools_parser = subparsers.add_parser("tools", help="Offline utility tools")
    tools_parser.set_defaults(func=lambda _args: tools_parser.print_help() or 2)
    tools_subs = tools_parser.add_subparsers(dest="tools_cmd")

    from pybluehost.cli.tools.decode import register_decode_command
    from pybluehost.cli.tools.fw import register_fw_commands
    from pybluehost.cli.tools.info import register_info_command   # NEW
    from pybluehost.cli.tools.rpa import register_rpa_commands
    from pybluehost.cli.tools.usb import register_usb_commands

    register_decode_command(tools_subs)
    register_fw_commands(tools_subs)
    register_info_command(tools_subs)   # NEW
    register_rpa_commands(tools_subs)
    register_usb_commands(tools_subs)
```

- [ ] **Step 6: Run tests**

```
uv run pytest tests/unit/cli/tools/test_info.py -v
```
Expected: 6 PASS. If any field assumption (`hci.manufacturer_id`, `hci.le_features`, etc.) doesn't exist on `HCIController`, fix the test to match the actual attribute names — grep `pybluehost/hci/controller.py` for what's actually cached.

```
uv run pytest tests/ -q --transport=virtual
```
Expected: no regressions.

```
uv run pybluehost tools info --transport=virtual
```
Expected: human-readable table prints, exit 0.

```
uv run pybluehost tools info --transport=virtual --json | head -20
```
Expected: valid JSON.

- [ ] **Step 7: Commit**

```bash
git add pybluehost/cli/tools/info.py pybluehost/cli/tools/__init__.py tests/unit/cli/tools/test_info.py
git commit -m "feat(cli/tools): info — dump full HCI capability set of an adapter

New 'pybluehost tools info --transport=<spec>' subcommand. Reads the
cached capability state from a freshly-initialized stack (no extra HCI
traffic beyond standard init) and prints either a human-readable five-section
table (adapter identity / capability summary / LE features / BR/EDR features /
supported HCI commands) or --json.

Decoded feature names come from features_decode.py (Task 5); opcode bit
positions come from _OPCODE_BIT_POSITIONS (extended in Task 6). Set bits
not in the position map appear in supported_commands.unknown_bits_set
for spec lookup.

Six unit tests against virtual stack verify the output structure."
```

---

## Task 8: `docs/HARDWARE_E2E.md` runbook

**Files:**
- Create: `docs/HARDWARE_E2E.md`

This is documentation. No tests; review-only.

- [ ] **Step 1: Write the document**

Create `docs/HARDWARE_E2E.md`:

```markdown
# Hardware E2E Verification

Manual smoke-testing of the PyBlueHost e2e suite against real BR/EDR + LE
USB adapters. Hardware verification runs **outside** CI and is performed
before each release.

## 1. Quick start (5-minute happy path)

**Prerequisites**:
- Two BR/EDR + LE USB adapters supporting Secure Connections (BT 4.2+)
- Linux host with `lsusb`, root or `udev` rules granting access to HCI
- `uv` installed; `uv sync --extra dev` already run

**Steps**:
1. Plug both adapters in. Identify each:
   ```
   lsusb | grep -iE "intel|broadcom|realtek|csr"
   ```
   Note the VID:PID of each (e.g., `8087:0033` for Intel BE200).
2. Survey each adapter independently:
   ```
   uv run pybluehost tools info --transport=usb:vendor=intel#1
   uv run pybluehost tools info --transport=usb:vendor=intel#2
   ```
   Confirm both show `✓` for `LE Secure Connections` and `BR/EDR Secure Simple Pairing`.
3. Run the e2e suite peer-to-peer:
   ```
   uv run pytest tests/e2e/ -v \
       --transport=usb:vendor=intel#1 \
       --transport-peer=usb:vendor=intel#2
   ```
   Expected: all e2e tests pass. Tests gated on capabilities the adapter lacks
   will `pytest.skip` with a clear reason.

## 2. Adapter compatibility matrix

| Adapter             | LE SC | BR/EDR SSP | BR/EDR SC | LE Audio | Notes                |
|---------------------|-------|------------|-----------|----------|----------------------|
| Intel BE200         | TBD   | TBD        | TBD       | TBD      | _Verified on hardware: TBD_ |
| Intel AX210         | TBD   | TBD        | TBD       | TBD      | _Verified on hardware: TBD_ |
| Realtek RTL8761B    | TBD   | TBD        | TBD       | TBD      | Needs firmware blob  |
| CSR8510 A10         | -     | TBD        | -         | -        | BT 4.0; SC unavailable; tests that gate on SC will skip |
| Broadcom BCM20702   | TBD   | TBD        | -         | -        | _Verified on hardware: TBD_ |

This matrix is a **template** — `TBD` cells are filled in as adapters are
surveyed. See §6 for the workflow to add a new adapter.

## 3. `info` CLI usage

**Default human-readable table** — five sections (adapter identity, capability
summary, LE features, BR/EDR features, supported HCI commands) plus
recommended pytest invocations:

```
$ pybluehost tools info --transport=usb:vendor=intel
PyBlueHost Hardware Survey
==========================
...
```

**`--json` for machine-readable** output:
```
pybluehost tools info --transport=usb:vendor=intel --json > my-adapter.json
```

**Diffing across firmware versions**:
```
diff my-adapter.json my-adapter-updated.json
```

**Per-adapter baseline files** live under `docs/hardware/<vendor>-<product>.json`
(populated as adapters are surveyed — see §6).

## 4. Two-adapter pairing convention

Test convention:
- `--transport` adapter = **Central** (initiates connections)
- `--transport-peer` adapter = **Peripheral**

For LE E2E, the Peripheral is the GATT server. For Classic E2E, the Peripheral
is the SPP service + SDP record holder.

These roles aren't enforced by HCI — they're test-design choices. Swap freely
if you suspect adapter-asymmetry issues.

## 5. Common failure triage

| Symptom | Likely cause | Mitigation |
|---|---|---|
| Tests skip with "adapter does not support LE Secure Connections" | Adapter is BT 4.0 (CSR8510) | Use a BT 4.2+ adapter |
| Tests skip with "adapter does not support BR/EDR SSP" | Adapter has BR/EDR disabled in firmware | Check `tools info`; if SSP shows ✗, no host-side fix |
| `connect_classic` times out (~10 s) | Peripheral not connectable/discoverable, or adapters too far apart | Verify `set_connectable(True)` + `set_discoverable(True)`; check physical proximity |
| SDP query times out | RFCOMM listener not registered, or L2CAP fragmentation issue | Check `stack._sdp._records` after fixture setup |
| Notify subscription fires once then stops | CCCD writes not honored — vendor quirk | Try a different adapter; report to vendor |
| `pair()` raises reason=4 unexpectedly | LTK/passkey mismatch, clock drift, vendor SC bug | Re-run; survey both adapters; check known-issue list per vendor |
| RFCOMM SABM never UA'd | Page timeout on real adapter; peer not page-scanning | Verify peripheral's `set_connectable(True)` was called **before** central's connect |
| Long inquiry/page setup (10s+) | Real RF takes longer than virtual | `e2e_timeout` already accounts for this; if still timing out, increase the `usb=` override in the test |
| Auto-encrypt event doesn't fire | Bond store mismatch between sessions | Check `JsonBondStorage` file path persists across sessions; verify the bond was actually written in session 1 |
| `find_rfcomm_channel` returns None despite SDP record registered | SDP request fragmented or peer's SDP server didn't respond | Increase `SDPClient.request_timeout`; capture btsnoop |

## 6. Adding a new adapter to known-good

1. Run `info` and save the JSON:
   ```
   uv run pybluehost tools info --transport=usb:<spec> --json > docs/hardware/<vendor>-<product>.json
   ```
2. Add a row to the compatibility matrix (§2), filling in actual values.
3. Run the full e2e suite as central+peer against this adapter (paired with
   another known-good adapter, or two USB instances if you have two of the same):
   ```
   uv run pytest tests/e2e/ -v \
       --transport=usb:<new>#1 \
       --transport-peer=usb:<known-good>#2
   ```
4. If any tests fail, attach the `tools info` JSON to a known-issues note.

## 7. What is NOT tested by this suite

- **Cross-vendor interop** — test against multi-vendor pairs (Intel + Realtek) to surface vendor-specific quirks.
- **LE Audio CIS/BIS streams** — Plan deferred.
- **A2DP / HFP audio profiles** — Plan deferred.
- **LE Connection Subrating** (BT 5.3+).
- **Privacy / RPA resolution against a phone-class peer** — use a real phone.
- **High-throughput sustained traffic** — the e2e suite sends ~10 PDUs per scenario.

## 8. CI status

These tests do NOT run in GitHub Actions. A self-hosted runner with adapters
is a future Plan (out of scope here). For now: run manually before each
release; capture `tools info` baselines for each adapter.
```

- [ ] **Step 2: Spot-check the document**

```
head -40 docs/HARDWARE_E2E.md
```
Verify no broken Markdown (no missing pipes in tables, no half-finished lists).

- [ ] **Step 3: Commit**

```bash
git add docs/HARDWARE_E2E.md
git commit -m "docs(hardware): HARDWARE_E2E.md runbook

Manual smoke-testing runbook for running the e2e suite against real BR/EDR
+ LE USB adapters. Eight sections: quick-start, compatibility matrix
(template), info CLI usage, two-adapter pairing convention, common-failure
triage table, adding-new-adapter checklist, what's-not-tested, CI status.

Matrix rows land with TBD placeholders — fill in as adapters get surveyed
per the §6 workflow."
```

---

## Task 9: STATUS.md update

**Files:**
- Modify: `docs/superpowers/STATUS.md`

**Use the absolute worktree path** for the Edit tool to avoid the main-repo CWD issue.

- [ ] **Step 1: Update top-of-file**

```
**当前进行中**：Hardware E2E Readiness — ✅ 完成
**下一步**：自托管硬件 CI runner（C 选项）/ 手机互联 / 真机首批 adapter survey
**不在路线图**：SMP Sub-Plan 3c (OOB) — 暂无计划支持
```

- [ ] **Step 2: Add row to Plan-progress table**

Append after the Classic Workflow E2E row:

```
| Hardware E2E Readiness | `build_stack_from_spec` 接 `config=` 解锁 hardware-mode skips；`e2e_timeout` 传输自适应超时；`pybluehost tools info` 全量 HCI 能力 dump CLI；`docs/HARDWARE_E2E.md` runbook。所有可在 virtual 上验证；真机验证待 adapter 到货后手动执行。 | ✅ 完成 | [2026-05-22-hardware-e2e-readiness](plans/2026-05-22-hardware-e2e-readiness.md) | `tests/_transport_resolve.py`, `tests/e2e/_helpers.py`, `tests/e2e/test_*_lifecycle.py`, `pybluehost/hci/{features_decode,capabilities}.py`, `pybluehost/cli/tools/info.py`, `docs/HARDWARE_E2E.md` |
```

Increment "总计：N 个 Plan" line by one.

- [ ] **Step 3: Add detailed-progress section**

Append after the Classic Workflow E2E section:

```markdown
### ✅ Hardware E2E Readiness
- 完成时间：2026-05-22
- Plan 文档：[2026-05-22-hardware-e2e-readiness.md](plans/2026-05-22-hardware-e2e-readiness.md)
- 提交范围：`tests/_transport_resolve.py`（`config=` kwarg）、`tests/e2e/_helpers.py`（`e2e_timeout`）、`tests/e2e/test_le_lifecycle.py` / `tests/e2e/test_classic_lifecycle.py`（去 skip + timeout 升级）、`pybluehost/hci/features_decode.py`（新 LE/BR-EDR 特性表 + 厂商表）、`pybluehost/hci/capabilities.py`（扩展 `_OPCODE_BIT_POSITIONS`）、`pybluehost/cli/tools/info.py` + `pybluehost/cli/tools/__init__.py`（新 CLI）、`docs/HARDWARE_E2E.md`（runbook）；test-only + 一个新 CLI 子命令 + 一份 runbook 文档。
- 四件交付物：
  - `build_stack_from_spec(spec, *, config=None)`：把 `StackConfig` 透传到每个 transport 分支。LE Test 3、Classic Test 3、Classic Test 4 不再因为 factory 不接 `config=` 而在 hardware 模式 skip。
  - `e2e_timeout(transport_mode, virtual=, usb=, uart=)`：virtual 返回 virtual 值；usb 默认 5×、uart 默认 8×。e2e 套件里所有 < 5s 的 `asyncio.wait_for` 都包了一层。virtual 模式行为不变，hardware 模式自动获得更宽的超时预算。
  - `pybluehost tools info --transport=<spec>` CLI：开适配器、跑 HCI init、打印全量能力 dump：adapter identity（BD_ADDR / 厂商 / HCI/LMP 版本）、capability summary（LE SC / LE Audio / BR/EDR SSP / SC / EIR 等）、LE Features 64-bit 解码、BR/EDR Features page 0 解码、Supported Commands 位图（已知 opcode 解码 + 未知 bit 列出）。`--json` 输出可写文件做基线，跨固件版本 diff。无额外 HCI 流量，全部消费 `HCIController.initialize()` 的缓存。
  - `docs/HARDWARE_E2E.md` runbook：quick-start、适配器兼容矩阵模板、`info` 用法、双适配器测试约定、失败分诊表、新增适配器流程、什么不在套件覆盖范围、CI 现状。
- 设计上不需要硬件即可落地：全部 13 个新单测在 virtual 上跑（3 build_stack_from_spec + 4 e2e_timeout + 6 info + 7 features_decode + 5 capabilities opcodes）。真机验证留作后续手动 smoke。
- 验收：`uv run pytest tests/e2e/ -v --transport=virtual` PASS（15/15，无 regression）；`pybluehost tools info --transport=virtual` 产生合理表格 + valid JSON；全套仅 3 个 pre-existing USB diagnostics 失败。
- 真机到货后执行流程：把适配器插上 → `lsusb` 找 VID:PID → `pybluehost tools info` 双 adapter survey → 用 `--transport=usb:VID:PID#1 --transport-peer=usb:VID:PID#2` 跑 e2e 套件。Test 3/Test 4 现在能跑而不是 skip。
- 不在范围（按设计推迟）：自托管硬件 CI runner（独立 ops 决策）；手机互联；A2DP/HFP/SCO/LE Audio；高吞吐持续流量；`info --diff` 标志；CLI 彩色输出。
```

- [ ] **Step 4: Verify markdown renders cleanly**

```
head -60 docs/superpowers/STATUS.md
```
Skim. No broken table syntax.

- [ ] **Step 5: Final full-suite run**

```
uv run pytest tests/ -q --transport=virtual
```
Expected: only the 3 pre-existing USB-diagnostics failures.

Verbatim report the pass/fail count.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/STATUS.md
git commit -m "docs(status): Hardware E2E Readiness complete

Four readiness deliverables: build_stack_from_spec(config=) kwarg,
e2e_timeout transport-aware helper, pybluehost tools info CLI, and
docs/HARDWARE_E2E.md runbook. All verifiable on virtual today; real
hardware verification becomes a documented manual smoke step once an
adapter pair is procured."
```

---

## Acceptance Checklist

- [ ] `build_stack_from_spec(spec, *, config=None)` works across all transport branches; backward-compatible.
- [ ] `e2e_timeout(transport_mode, virtual=, usb=, uart=)` helper exists in `tests/e2e/_helpers.py`.
- [ ] LE Test 3 + Classic Test 3 + Classic Test 4 no longer carry `pytest.skip("hardware mode: build_stack_from_spec doesn't accept config=")`.
- [ ] `pybluehost/hci/features_decode.py` exports `LE_FEATURE_BIT_NAMES`, `BREDR_FEATURE_BIT_NAMES`, `MANUFACTURER_NAMES`, `manufacturer_name`.
- [ ] `_OPCODE_BIT_POSITIONS` covers BR/EDR Link Control opcodes, SSP reply opcodes, LE SC opcodes, and Write_Scan_Enable.
- [ ] `pybluehost tools info --transport=virtual` runs successfully and produces decoded LE / BR-EDR features + capability summary.
- [ ] `pybluehost tools info --transport=virtual --json` outputs valid JSON with the documented keys.
- [ ] `docs/HARDWARE_E2E.md` exists with the eight outlined sections.
- [ ] All new unit tests pass (~25 tests: 3 + 5 + 7 + 5 + 6 = at least 26).
- [ ] `uv run pytest tests/ -q --transport=virtual` → suite green minus the 3 pre-existing USB-diagnostics failures.
- [ ] STATUS.md updated.

## Out of Scope (deferred)

| Item | When |
|---|---|
| Self-hosted hardware CI runner | Separate Plan; ops/security decisions out-of-band |
| Phone-as-peer interop tests | Separate Plan |
| Per-vendor quirk catalog | Grows incrementally as adapters are surveyed |
| A2DP / HFP / SCO audio | Independent Plan if needed |
| LE Audio CIS/BIS streams | Independent Plan if needed |
| High-throughput sustained traffic | Independent Plan if needed |
| `info` color terminal output | Optional follow-up |
| `info --diff <baseline.json>` flag | Optional follow-up |
