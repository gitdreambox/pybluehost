# SMP Sub-Plan 1 Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address the 5 non-blocking items surfaced by the final whole-branch review of SMP Sub-Plan 1 (Legacy Just Works). Pure cleanup: no new features, no behavior changes outside the stated scope.

**Architecture:** Each task is mechanical and independent. Touches `pybluehost/ble/smp.py`, `pybluehost/stack.py`, `tests/`, plus a doc tick-pass on the SMP Sub-Plan 1 Plan doc + STATUS.md.

**Tech Stack:** Python 3.10+, pytest (`--transport=virtual`), existing infrastructure from Sub-Plan 1.

**Review baseline**: Final code review of branch `worktree-smp-legacy-jw` merged in commit `3594e37`.

---

## 范围声明

**包含**：

1. State-machine path coverage: unit tests for `TIMEOUT`, `DISCONNECTED`, and `PAIRING_FAILED_RX` events
2. `Stack.encrypt(handle)` waits for the `HCI_Encryption_Change` success event (no longer fire-and-forget)
3. `BondInfo.rand` legacy compatibility: `JsonBondStorage.load_bond` handles both legacy int and new hex-string formats
4. `SMPManager.register_peer_address(handle, address)` public method to replace `stack._smp._peer_addrs[handle] = ...` direct private access
5. Tick the 75 unchecked checkboxes in `docs/superpowers/plans/2026-05-13-smp-pairing-legacy-jw.md` per CLAUDE.md rule; update STATUS.md to mark this follow-up Plan complete

**不包含**（推迟）：

- New SMP features (LE SC, Passkey, NC, OOB) → Sub-Plan 2/3
- Refactors beyond the 5 review items
- `SecurityConfig.bondable` / `SecurityConfig.auto_encrypt_on_bonded_reconnect` (review noted this lives only on `StackConfig`; that's the public API surface, no change needed)

---

## 文件改动清单

| 类型 | 路径 | 责任 |
|------|------|------|
| Create | `tests/unit/ble/test_smp_state_machine_failure_paths.py` | 3 tests covering TIMEOUT / DISCONNECTED / PAIRING_FAILED_RX |
| Modify | `pybluehost/stack.py` | `Stack.encrypt` 等待 `Encryption_Change` 事件 |
| Create | `tests/unit/test_stack_encrypt_waits.py` | 2 tests for `Stack.encrypt` async wait |
| Modify | `pybluehost/ble/smp.py` | `JsonBondStorage.load_bond` 兼容 legacy `rand: int`；新 `SMPManager.register_peer_address` 方法 |
| Modify | `pybluehost/stack.py` | 把 `self._smp._peer_addrs[handle] = peer_addr` 改成 `self._smp.register_peer_address(handle, peer_addr)` |
| Create | `tests/unit/ble/test_bond_storage_legacy_rand.py` | 1 test for legacy int-rand load |
| Modify | `docs/superpowers/plans/2026-05-13-smp-pairing-legacy-jw.md` | tick all `- [ ]` → `- [x]` |
| Modify | `docs/superpowers/STATUS.md` | mark follow-up Plan complete |

---

## 任务依赖图

```
Task 1 (failure-path tests) ─┐
Task 2 (Stack.encrypt wait) ─┤
Task 3 (BondInfo rand legacy) ┼─► Task 5 (Plan checkboxes + STATUS)
Task 4 (register_peer_address) ─┘
```

Tasks 1–4 are independent and can run in any order. Task 5 closes the Plan.

---

## Task 1: State-machine failure-path unit tests

**Files:**
- Create: `tests/unit/ble/test_smp_state_machine_failure_paths.py`

### Step 1.1: 写测试

- [ ] **Create `tests/unit/ble/test_smp_state_machine_failure_paths.py`:**

```python
"""SMP state-machine failure-path coverage: TIMEOUT, DISCONNECTED, PAIRING_FAILED_RX."""
from __future__ import annotations

import asyncio

import pytest

from pybluehost.ble._smp_state import register_transitions
from pybluehost.ble.smp import (
    PairingRole,
    SMPCode,
    SMPEvent,
    SMPPairingContext,
    SMPPairingFailed,
    SMPState,
    decode_smp_pdu,
)
from pybluehost.core.address import BDAddress


async def test_pairing_failed_rx_transitions_to_failed_state():
    """Inbound SMPPairingFailed PDU drives state machine to FAILED + rejects pairing future."""
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    ctx = SMPPairingContext.create(
        connection_handle=0x0040,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        role=PairingRole.INITIATOR,
        send=send,
    )
    ctx.pairing_complete = asyncio.get_running_loop().create_future()
    register_transitions(ctx)

    # Push state into FEATURE_EXCHANGE by firing LOCAL_PAIR_REQUEST
    await ctx.state_machine.fire(SMPEvent.LOCAL_PAIR_REQUEST)
    sent.clear()

    # Peer sends PAIRING_FAILED — should advance to FAILED, not echo back
    failed = SMPPairingFailed(reason=0x05)  # PAIRING_NOT_SUPPORTED
    await ctx.state_machine.fire(SMPEvent.PAIRING_FAILED_RX, pdu=failed)

    assert ctx.state_machine.state == SMPState.FAILED
    assert sent == [], "must not echo SMPPairingFailed back to peer on inbound failure"
    assert ctx.pairing_complete.done()
    with pytest.raises(RuntimeError):
        ctx.pairing_complete.result()


async def test_disconnected_event_drives_to_failed_state():
    """Firing DISCONNECTED on an active context drives state machine to FAILED."""
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    ctx = SMPPairingContext.create(
        connection_handle=0x0040,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        role=PairingRole.RESPONDER,
        send=send,
    )
    ctx.pairing_complete = asyncio.get_running_loop().create_future()
    register_transitions(ctx)

    # Push the responder into CONFIRMING by firing a synthetic Pairing Request.
    from pybluehost.ble.smp import SMPPairingRequest
    from pybluehost.core.types import IOCapability
    req = SMPPairingRequest(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT,
        oob_data_flag=0,
        auth_req=0x01,
        max_key_size=16,
        init_key_dist=0x07,
        resp_key_dist=0x07,
    )
    await ctx.state_machine.fire(SMPEvent.PAIRING_REQ_RX, pdu=req)
    sent.clear()

    await ctx.state_machine.fire(SMPEvent.DISCONNECTED)

    assert ctx.state_machine.state == SMPState.FAILED
    # DISCONNECTED should NOT send anything (peer is already gone)
    assert sent == [], "must not send PDUs after disconnect"


async def test_timeout_drives_to_failed_state_and_sends_pairing_failed():
    """Firing TIMEOUT sends a PAIRING_FAILED PDU with reason=Unspecified and goes FAILED."""
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    ctx = SMPPairingContext.create(
        connection_handle=0x0040,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        role=PairingRole.INITIATOR,
        send=send,
    )
    ctx.pairing_complete = asyncio.get_running_loop().create_future()
    register_transitions(ctx)
    await ctx.state_machine.fire(SMPEvent.LOCAL_PAIR_REQUEST)
    sent.clear()

    await ctx.state_machine.fire(SMPEvent.TIMEOUT)

    assert ctx.state_machine.state == SMPState.FAILED
    assert len(sent) == 1
    pdu = decode_smp_pdu(sent[0])
    assert isinstance(pdu, SMPPairingFailed)
    assert pdu.reason == 0x08  # Unspecified
    assert ctx.pairing_complete.done()
    with pytest.raises(RuntimeError):
        ctx.pairing_complete.result()
```

### Step 1.2: 跑测试确认绿

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/ble/test_smp_state_machine_failure_paths.py -v --transport=virtual
```

预期：3 passed. Transitions are already registered in `_smp_state.register_transitions` (PAIRING_FAILED_RX/TIMEOUT/DISCONNECTED → FAILED for all Phase 1+2+3 states), so the tests verify behavior is correctly wired without needing implementation changes.

If a test fails, the implementation is missing a transition. **Do not edit tests to make them pass** — fix the implementation in `pybluehost/ble/_smp_state.py`. The most likely missing piece is that `TIMEOUT` may need to send `SMPPairingFailed(reason=0x08)`; check `_on_failed(ctx, reason=0x08)` is called with `send_failed=True` (the default in `_smp_state.py`).

### Step 1.3: 提交

- [ ] **Run:**

```bash
git add tests/unit/ble/test_smp_state_machine_failure_paths.py
git commit -m "test(ble/smp): cover TIMEOUT / DISCONNECTED / PAIRING_FAILED_RX paths

Three unit tests verify the failure transitions registered by
register_transitions() (in _smp_state.py) actually advance to FAILED
state, reject the pairing future, and produce/suppress PDUs per spec:
- TIMEOUT sends PAIRING_FAILED(Unspecified=0x08) before failing
- DISCONNECTED silently fails (peer is gone)
- PAIRING_FAILED_RX silently fails (don't echo failure back)

Closes one of the 5 follow-up items from SMP Sub-Plan 1 final review."
```

---

## Task 2: `Stack.encrypt(handle)` waits for `Encryption_Change`

**Files:**
- Modify: `pybluehost/stack.py`
- Create: `tests/unit/test_stack_encrypt_waits.py`

### Step 2.1: 写失败测试

- [ ] **Create `tests/unit/test_stack_encrypt_waits.py`:**

```python
"""Stack.encrypt(handle) waits for HCI_Encryption_Change event."""
from __future__ import annotations

import asyncio

import pytest

from pybluehost.ble.smp import BondInfo, JsonBondStorage
from pybluehost.core.address import BDAddress
from pybluehost.stack import Stack, StackConfig


async def test_encrypt_resolves_on_encryption_change_success(tmp_path):
    """Stack.encrypt completes when HCI emits Encryption_Change(status=0, enabled=1)."""
    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))

    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        stack._smp.register_peer_address(0x0040, peer)

        # Drive encrypt + simulate Encryption_Change success after a short delay
        async def _emit_success():
            await asyncio.sleep(0.01)
            await stack._on_encryption_change(0x0040, status=0, enabled=1)

        emitter = asyncio.create_task(_emit_success())
        await asyncio.wait_for(stack.encrypt(0x0040, timeout=1.0), timeout=2.0)
        await emitter
    finally:
        await stack.close()


async def test_encrypt_raises_on_encryption_change_failed(tmp_path):
    """Stack.encrypt raises if HCI emits Encryption_Change(status!=0)."""
    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))

    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        stack._smp.register_peer_address(0x0040, peer)

        async def _emit_failure():
            await asyncio.sleep(0.01)
            # status=0x06 = PIN/Key Missing
            await stack._on_encryption_change(0x0040, status=0x06, enabled=0)

        emitter = asyncio.create_task(_emit_failure())
        with pytest.raises(RuntimeError, match="encryption"):
            await stack.encrypt(0x0040, timeout=1.0)
        await emitter
    finally:
        await stack.close()
```

### Step 2.2: 跑测试确认失败

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/test_stack_encrypt_waits.py -v --transport=virtual
```

预期：FAIL — `Stack.encrypt` returns immediately (no wait), or `Stack._smp.register_peer_address` doesn't exist yet (handled in Task 4).

For Task 2 we need `register_peer_address` available. If it doesn't exist yet because Task 4 hasn't landed, the test can use `stack._smp._peer_addrs[0x0040] = peer` directly as a workaround. Pick whichever path leaves the test cleaner — if you do Task 4 first, use the public method. Otherwise inline the dict access in the test setup with a `# TODO Task 4` comment that you remove during Task 4.

### Step 2.3: Modify `Stack.encrypt`

In `pybluehost/stack.py`, find `Stack.encrypt` (around line 791). Replace its body so it awaits a per-handle `Encryption_Change` future. The cleanest approach is to add a private dict `self._encryption_waiters: dict[int, asyncio.Future[None]]` and have `_on_encryption_change` resolve them.

(a) In `Stack.__init__` (or wherever per-instance state is initialized), add:

```python
        self._encryption_waiters: dict[int, asyncio.Future[None]] = {}
```

(b) In `Stack._on_encryption_change` (around line 434), after firing the SMP context's event, resolve any waiter for this handle:

```python
        # Resolve any pending Stack.encrypt() waiter
        waiter = self._encryption_waiters.pop(handle, None)
        if waiter is not None and not waiter.done():
            if status == 0 and enabled:
                waiter.set_result(None)
            else:
                waiter.set_exception(RuntimeError(
                    f"encryption failed on handle=0x{handle:04X} status=0x{status:02X}"
                ))
```

(c) Replace the body of `Stack.encrypt`:

```python
    async def encrypt(self, handle: int, *, timeout: float = 5.0) -> None:
        """Restore encryption using a stored bond and wait for completion.

        Looks up the bonded peer for this connection handle, issues
        HCI_LE_Start_Encryption, and awaits the HCI_Encryption_Change event.

        Raises:
            ReplayModeError: if stack is in REPLAY mode
            RuntimeError: if bond storage is not configured, no peer address
                is bound for this handle, no bond exists for the peer, or
                the controller reports encryption failure.
            asyncio.TimeoutError: if no Encryption_Change event arrives within
                the timeout.
        """
        self._check_writable()
        if self._smp is None:
            raise RuntimeError("Stack is not initialized")
        if self._config.bond_storage is None:
            raise RuntimeError("Bond storage not configured")
        peer = self._smp._peer_addrs.get(handle)
        if peer is None:
            raise RuntimeError(f"No peer address bound for handle=0x{handle:04X}")
        bond = await self._config.bond_storage.load_bond(peer)
        if bond is None or not bond.ltk:
            raise RuntimeError(f"No bond available for peer={peer}")

        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()
        self._encryption_waiters[handle] = waiter

        from pybluehost.hci.packets import HCI_LE_Start_Encryption_Command
        try:
            await self._hci.send_command(HCI_LE_Start_Encryption_Command(
                connection_handle=handle,
                random_number=bond.rand if bond.rand else b"\x00" * 8,
                encrypted_diversifier=bond.ediv,
                long_term_key=bond.ltk,
            ))
            await asyncio.wait_for(waiter, timeout=timeout)
        finally:
            self._encryption_waiters.pop(handle, None)
```

### Step 2.4: 跑测试确认绿

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/test_stack_encrypt_waits.py -v --transport=virtual
uv run --frozen pytest tests/unit/test_stack_pair_api.py tests/unit/test_stack_auto_encrypt.py -v --transport=virtual
```

预期：2 new tests PASS; existing stack tests no regressions.

### Step 2.5: 提交

- [ ] **Run:**

```bash
git add pybluehost/stack.py tests/unit/test_stack_encrypt_waits.py
git commit -m "feat(stack): Stack.encrypt waits for HCI_Encryption_Change event

Closes one of the 5 follow-up items from SMP Sub-Plan 1 final review.

Stack.encrypt(handle) is no longer fire-and-forget. It now creates a
per-handle waiter Future, sends HCI_LE_Start_Encryption, and awaits the
Encryption_Change event. On success the future resolves; on failure
(status != 0) it raises RuntimeError. asyncio.TimeoutError on no event.

Stack._on_encryption_change resolves waiters in addition to forwarding
the event to the active SMP context's state machine."
```

---

## Task 3: `BondInfo.rand` legacy int → bytes load

**Files:**
- Modify: `pybluehost/ble/smp.py` (`JsonBondStorage.load_bond`)
- Create: `tests/unit/ble/test_bond_storage_legacy_rand.py`

### Step 3.1: 写失败测试

- [ ] **Create `tests/unit/ble/test_bond_storage_legacy_rand.py`:**

```python
"""JsonBondStorage compatibility with legacy bond files where rand was an int."""
from __future__ import annotations

import json

from pybluehost.ble.smp import JsonBondStorage
from pybluehost.core.address import BDAddress


async def test_load_bond_handles_legacy_int_rand(tmp_path):
    """Legacy bond files stored rand as int. New code stores it as hex string.

    load_bond must accept both formats to avoid breaking users who upgraded
    from pre-Sub-Plan-1.
    """
    bonds_path = tmp_path / "bonds.json"
    # Build a legacy-format entry by hand (rand: int instead of hex string)
    bonds_path.write_text(json.dumps({
        "01:02:03:04:05:06": {
            "peer_address": "01:02:03:04:05:06",
            "address_type": 0,
            "ltk": "aa" * 16,
            "irk": None,
            "csrk": None,
            "ediv": 0x1234,
            "rand": 0x55,  # LEGACY: int, not hex string
            "key_size": 16,
            "authenticated": False,
            "sc": False,
            "link_key": None,
            "link_key_type": None,
            "ctkd_derived": False,
        }
    }))

    storage = JsonBondStorage(bonds_path)
    bond = await storage.load_bond(BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    assert bond is not None
    assert isinstance(bond.rand, bytes)
    assert len(bond.rand) == 8
    # Conversion: int 0x55 → 8-byte little-endian → b"\x55\x00\x00\x00\x00\x00\x00\x00"
    assert bond.rand == (0x55).to_bytes(8, "little")
    assert bond.ediv == 0x1234


async def test_load_bond_handles_new_hex_string_rand(tmp_path):
    """New-format bond files (rand: hex string) load correctly."""
    bonds_path = tmp_path / "bonds.json"
    bonds_path.write_text(json.dumps({
        "01:02:03:04:05:06": {
            "peer_address": "01:02:03:04:05:06",
            "ltk": "aa" * 16,
            "ediv": 0x1234,
            "rand": "5500000000000000",
        }
    }))

    storage = JsonBondStorage(bonds_path)
    bond = await storage.load_bond(BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    assert bond is not None
    assert bond.rand == bytes.fromhex("5500000000000000")
```

### Step 3.2: 跑测试确认失败

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/ble/test_bond_storage_legacy_rand.py -v --transport=virtual
```

预期：`test_load_bond_handles_legacy_int_rand` FAILS with `TypeError: fromhex() argument must be str, not int` because `JsonBondStorage.load_bond` currently calls `bytes.fromhex(entry.get("rand", "0000000000000000"))` without handling int input.

### Step 3.3: 修复 `JsonBondStorage.load_bond`

In `pybluehost/ble/smp.py`, find `load_bond` (around line 500). Replace the `rand=` line with a helper that handles both formats:

```python
            rand=_decode_legacy_rand(entry.get("rand", "0000000000000000")),
```

And add the helper at module scope (above `class JsonBondStorage`):

```python
def _decode_legacy_rand(value: int | str | None) -> bytes:
    """Decode the bond ``rand`` field, accepting both legacy int and new hex string.

    Pre-Sub-Plan-1 stored rand as an int; current code stores it as an 8-byte
    hex string. Old JSON files must still load.
    """
    if isinstance(value, int):
        return value.to_bytes(8, "little")
    if isinstance(value, str):
        return bytes.fromhex(value)
    return b"\x00" * 8
```

### Step 3.4: 跑测试确认绿

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/ble/test_bond_storage_legacy_rand.py tests/unit/ble/test_bond_storage_roundtrip.py -v --transport=virtual
```

预期：legacy + new tests both PASS.

### Step 3.5: 提交

- [ ] **Run:**

```bash
git add pybluehost/ble/smp.py tests/unit/ble/test_bond_storage_legacy_rand.py
git commit -m "fix(ble/smp): load legacy int rand from old bond storage files

Closes one of the 5 follow-up items from SMP Sub-Plan 1 final review.

Pre-Sub-Plan-1 JsonBondStorage stored BondInfo.rand as an int. Sub-Plan 1
changed it to bytes (serialized as hex string). load_bond now accepts
both formats so existing user bond files upgrade without manual editing."
```

---

## Task 4: `SMPManager.register_peer_address` public API

**Files:**
- Modify: `pybluehost/ble/smp.py` (add public method)
- Modify: `pybluehost/stack.py` (replace direct private access)

### Step 4.1: 加 public 方法

- [ ] **Modify `pybluehost/ble/smp.py`**: in `SMPManager` class (next to `bind_channel`), add:

```python
    def register_peer_address(self, connection_handle: int, address: BDAddress) -> None:
        """Bind a peer BD address to an LE connection handle.

        Called from Stack on LE_Connection_Complete so SMP can:
        - Look up the bond by peer address on reconnect
        - Build the c1/s1 parameters for legacy pairing using the actual peer addr
        - Persist BondInfo.peer_address correctly after Phase 3
        """
        self._peer_addrs[connection_handle] = address
```

### Step 4.2: 更新调用点

- [ ] **Modify `pybluehost/stack.py`**: find the line `self._smp._peer_addrs[handle] = peer_addr` (around line 633, inside `_handle_connection_event`). Replace with:

```python
                    self._smp.register_peer_address(handle, peer_addr)
```

Search for any other direct accesses to `_peer_addrs` in `stack.py` and convert similarly. Grep:

```bash
grep -n "_peer_addrs\[" pybluehost/stack.py
```

All write-side accesses should go through `register_peer_address`. Read-side accesses (e.g. `self._smp._peer_addrs.get(handle)` in `Stack.encrypt`) can stay as direct reads or be exposed via a public getter — for this Plan, leave reads alone (a getter is bigger scope; this task only fixes the write side per the review item).

### Step 4.3: 跑回归

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/ble/ tests/unit/test_stack.py tests/unit/test_stack_pair_api.py tests/unit/test_stack_auto_encrypt.py tests/integration/test_pairing_loopback.py -v --transport=virtual
```

预期：all PASS.

### Step 4.4: 提交

- [ ] **Run:**

```bash
git add pybluehost/ble/smp.py pybluehost/stack.py
git commit -m "refactor(ble/smp): add SMPManager.register_peer_address public API

Closes one of the 5 follow-up items from SMP Sub-Plan 1 final review.

Replaces direct private-dict access stack._smp._peer_addrs[handle] = ...
in Stack._handle_connection_event with a public setter method on
SMPManager. The read-side _peer_addrs.get(handle) in Stack.encrypt is
left as-is for now (a public getter is out of scope for this follow-up)."
```

---

## Task 5: Tick Plan checkboxes + STATUS.md update

**Files:**
- Modify: `docs/superpowers/plans/2026-05-13-smp-pairing-legacy-jw.md`
- Modify: `docs/superpowers/STATUS.md`

### Step 5.1: Tick all SMP Sub-Plan 1 Plan checkboxes

- [ ] **Run** (in-place replacement of all unchecked boxes):

```bash
sed -i 's/^- \[ \]/- [x]/g' docs/superpowers/plans/2026-05-13-smp-pairing-legacy-jw.md
```

Verify count of `[ ]` is now 0:

```bash
grep -c "^- \[ \]" docs/superpowers/plans/2026-05-13-smp-pairing-legacy-jw.md
```

预期：`0`.

And the count of `[x]` should be 75 (per the pre-Task count noted in the review):

```bash
grep -c "^- \[x\]" docs/superpowers/plans/2026-05-13-smp-pairing-legacy-jw.md
```

预期：`75`.

### Step 5.2: Update STATUS.md

- [ ] **Modify `docs/superpowers/STATUS.md`**:

(a) Locate the "快速定位" section near the top. Replace the current "下一步" line with:

```markdown
**下一步**：SMP Sub-Plan 2 (LE Secure Connections) / HCI 容错初始化 / 断线重连闭环 / e2e 覆盖
```

(b) In the Plan 总览 table, append a new row after the SMP Sub-Plan 1 row:

```markdown
| SMP Sub-Plan 1 收尾 | TIMEOUT/DISCONNECTED/PAIRING_FAILED_RX 单测 + Stack.encrypt 等事件 + BondInfo.rand 兼容 + register_peer_address + Plan checkbox | ✅ 完成 | [2026-05-16-smp-sub-plan-1-followups](plans/2026-05-16-smp-sub-plan-1-followups.md) | `pybluehost/ble/smp.py`, `pybluehost/stack.py` |
```

If there's a `**总计：N 个 Plan**` line, increment N by 1.

(c) In 详细进度, append:

```markdown
### ✅ SMP Sub-Plan 1 收尾
- 完成时间：2026-05-16
- Plan 文档：[2026-05-16-smp-sub-plan-1-followups.md](plans/2026-05-16-smp-sub-plan-1-followups.md)
- 关键变化（5 项非阻塞 review item）：
  - 加 3 个状态机失败路径单测（TIMEOUT/DISCONNECTED/PAIRING_FAILED_RX）
  - `Stack.encrypt(handle)` 不再 fire-and-forget；用 per-handle Future 等 `HCI_Encryption_Change`
  - `JsonBondStorage.load_bond` 兼容 legacy `rand: int`（自动 little-endian 转 8 字节）
  - `SMPManager.register_peer_address(handle, addr)` 公开 API 替代 `stack._smp._peer_addrs[handle] = ...` 私有访问
  - SMP Sub-Plan 1 Plan 文档 75 个 checkbox 全部勾选
- 验收：`uv run --frozen pytest tests/ -q --transport=virtual` 仅 3 个 pre-existing USB diagnostics 失败
```

### Step 5.3: 全套回归

- [ ] **Run:**

```bash
uv run --frozen pytest tests/ -q --transport=virtual --cov=pybluehost --cov-fail-under=85 --tb=no 2>&1 | tail -10
```

预期：only 3 pre-existing USB diagnostics failures; coverage ≥ 85%.

### Step 5.4: 提交

- [ ] **Run:**

```bash
git add docs/superpowers/plans/2026-05-13-smp-pairing-legacy-jw.md docs/superpowers/STATUS.md
git commit -m "docs(progress): SMP Sub-Plan 1 follow-up Plan complete

- Tick 75 checkboxes in 2026-05-13-smp-pairing-legacy-jw.md (CLAUDE.md
  rule: each completed step must be ticked)
- STATUS.md updated: SMP Sub-Plan 1 收尾 marked complete

Closes the 5 non-blocking items from SMP Sub-Plan 1 final review."
```

---

## 验收清单

- [ ] 3 failure-path unit tests added and passing (TIMEOUT/DISCONNECTED/PAIRING_FAILED_RX)
- [ ] `Stack.encrypt(handle)` awaits `HCI_Encryption_Change` (resolves on success, raises on failure, raises `asyncio.TimeoutError` on no event)
- [ ] `JsonBondStorage.load_bond` accepts both legacy `int` and new hex-string `rand`
- [ ] `SMPManager.register_peer_address(handle, addr)` public method replaces direct private dict assignment in `stack.py`
- [ ] All 75 `- [ ]` in the SMP Sub-Plan 1 Plan doc are now `- [x]`
- [ ] STATUS.md marks the follow-up Plan complete; Plan count incremented
- [ ] Full suite: only the 3 pre-existing USB diagnostics failures remain; coverage ≥ 85%

## 常见问题 / Troubleshooting

### Q: Task 1 test passes immediately without any code change
- **现象**：The 3 failure-path tests already pass on the existing `_smp_state.py` implementation
- **原因**：Tasks 5/6/7 of SMP Sub-Plan 1 already registered all the failure transitions. The review flagged the **test coverage** gap, not the code gap. These tests are documenting the existing behavior — they're not driving new implementation.
- **解决方案**：That's expected for Task 1. Move on.

### Q: Task 2 `_on_encryption_change` is called twice — once from HCI controller, once from the test's direct call
- **现象**：The waiter Future is set_result-ed twice and the second call raises `InvalidStateError`
- **解决方案**：The implementation already uses `if not waiter.done()` guards. If you see this error, double-check the guard is in place. The test pops the waiter from the dict, so the second call should see no waiter and silently no-op.

### Q: Task 3 — Some user has stored `rand` as a Python list of ints (e.g. JSON serialization of bytes via `list(b)`)
- **现象**：Theoretical bug not covered by the test
- **解决方案**：Out of scope. The fix handles the two formats we know about: legacy int, new hex string. If users have a third format, they file an issue.

### Q: Task 4 — Read-side `_peer_addrs.get(handle)` access in `Stack.encrypt` is not refactored
- **现象**：Linter / code review may flag the remaining private access at `stack.py:797` (or wherever `Stack.encrypt` reads `_peer_addrs`)
- **原因**：The review flagged only the write side as a concern; adding a getter is bigger scope
- **解决方案**：Leave it. Document via a code comment if helpful: `# NOTE: read-side _peer_addrs access — public getter is out of scope for this follow-up`

Self-review 结论：
- 5 review-flagged items each map to a Task (1→Task 1, 2→Task 2, 3→Task 3, 4→Task 4, 5→Task 5)
- No TBD/TODO/placeholder steps
- Type consistency: `register_peer_address(connection_handle: int, address: BDAddress)` named consistently in Task 4's add + Task 2/Task 4 callsites
- All file paths absolute; all `git commit` commands include exact files; all test code has complete bodies
