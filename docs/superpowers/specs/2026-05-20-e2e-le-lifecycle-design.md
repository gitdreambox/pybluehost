# E2E LE Lifecycle — Design Spec

**Date**: 2026-05-20
**Scope**: First end-to-end (`tests/e2e/`) coverage Plan; LE workflows only. Transport-agnostic from day one — same scenarios run on `--transport=virtual` (CI) and `--transport=usb:VID:PID --transport-peer=usb:VID:PID#2` (hardware bench).
**Predecessors**: PRD 1.0 closure, SMP Sub-Plans 1 / 3a / 3b-1 / 3b-2, Pytest Transport Selection.
**Successors**: Classic E2E (BR/EDR inquiry → SDP → RFCOMM/SPP), trace/btsnoop assertion harness, CLI subprocess orchestration, hardware-specific scenarios (phone interop). Each gets its own Plan when concretely scoped.

---

## 1. Goals

Fill `tests/e2e/` (currently empty per pytest transport-selection Task 15) with a small, high-signal LE workflow suite. Each scenario exercises **multiple subsystems in composition** (GAP discovery + connection + SMP pairing + GATT discovery + R/W/notify + bond persistence + auto-encrypt), in contrast to per-feature `tests/integration/` tests that stop after one capability is proven.

Design priorities, in order:
1. **Catch composition bugs unit/integration tests miss** (e.g., the `Number_Of_Completed_Packets` flow-control bug surfaced by SC Passkey's 80-PDU exchange).
2. **Transport-agnostic**: scenarios use the existing `stack` + `peer_stack` fixtures from `tests/conftest.py`; no `Stack.virtual()` hard-coding; bridge between the two stacks is the only mode-specific fixture.
3. **CI-runnable**: virtual mode produces deterministic sub-30-second runs.
4. **Hardware-reusable**: identical scenarios produce a useful smoke test when run with USB transport specs.

Out of scope (separate Plans when scoped): Classic stack workflows, trace/btsnoop assertions, CLI subprocess invocation, phone-interop tests that need an external peer.

## 2. Test inventory

Four scenarios in `tests/e2e/test_le_lifecycle.py`.

| # | Test | Asserts |
|---|---|---|
| 1 | `test_e2e_scan_connect_pair_read` | Peripheral advertises with the canonical E2E service; Central scans, discovers by address, connects, pairs (SC Just Works), discovers the service, reads a characteristic, disconnects. Discovered name matches, pair succeeds, read returns the expected bytes, disconnect callback fires. |
| 2 | `test_e2e_gatt_write_and_notify` | Post-pair: Central writes to a writable characteristic and Peripheral observes it; Central subscribes to notifications via CCCD; Peripheral emits two notifications and Central observes both; Central unsubscribes; a subsequent Peripheral notify is **not** observed. |
| 3 | `test_e2e_bonded_reconnect_auto_encrypt` | Two sequential "sessions" sharing the same on-disk bond storage. Session 1 = pair + bond. Session 2 = reconnect → auto-encrypt event fires → GATT read succeeds on the encrypted link without redoing SMP. |
| 4 | `test_e2e_pair_failure_disconnects_cleanly` | Mismatched NC delegates → `stack.pair()` raises with `reason=4` → both stacks close within 2 s (regression guard against the leaked `pairing_complete` future seen in 3a/3b reviews). |

**Coverage rationale**: Test 1 is the smoke baseline (shortest valuable end-to-end path). Test 2 covers GATT write + CCCD subscription, the highest-value capability no current test exercises end-to-end. Test 3 is the PRD acceptance lifecycle (bonded reconnect with auto-encrypt) that drove much of the bond-storage work. Test 4 is the negative-path teardown guard. Pair-flavor matrix (NC / Passkey / SC Passkey vs SC JW) is **not** in scope — per-flavor pair correctness is already proven by `tests/integration/test_pairing_*.py`; E2E validates composition, not per-feature correctness.

## 3. Capability gating

SC is required by Tests 1–3 (Test 4 specifically uses NC, which subsumes SC). The skip-logic is **HCI capability introspection**, not per-vendor allowlist:

```python
def _supports_le_sc(stack) -> bool:
    """Returns True iff the controller's Read_Local_Supported_Commands bitmap
    advertises HCI_LE_Read_Local_P-256_Public_Key + HCI_LE_Generate_DHKey, and
    the LE Features bitmap has the LE Secure Connections (Host Support) bit."""
```

Read the cached capability data already populated by `pybluehost/hci/capabilities.py` during `HCIController.initialize()` (HCI tolerant-init Plan). Virtual mode always returns True (the `VirtualController` advertises full feature support); any hardware adapter is asked directly. Tests that require SC begin with `if not _supports_le_sc(stack): pytest.skip("adapter does not support LE Secure Connections")`.

## 4. Fixtures + helpers

### 4.1 Shared test service

`tests/e2e/_test_service.py` — a small module exporting:

```python
TEST_SERVICE_UUID   = UUID128(bytes.fromhex("0000feed0000100080000000746573e2"))
TEST_READ_CHAR_UUID = UUID128(bytes.fromhex("0000feed0000100080000000feed0001"))
TEST_WRITE_CHAR_UUID = UUID128(bytes.fromhex("0000feed0000100080000000feed0002"))
TEST_NOTIFY_CHAR_UUID = UUID128(bytes.fromhex("0000feed0000100080000000feed0003"))

INITIAL_READ_VALUE = b"PyBlueHost E2E v1"

def build_test_service() -> ServiceDefinition: ...
```

Three characteristics: read-only with a fixed initial value; writable with an observer hook on the server side; notify with a CCCD. Defining the service once keeps the scenario files focused on assertions.

### 4.2 Fixtures (`tests/e2e/conftest.py`)

```python
@pytest_asyncio.fixture
async def central_peripheral_pair(stack, peer_stack, transport_mode):
    """Yields (stack_central, stack_peripheral) with the E2E service registered
    on the Peripheral. Cleans up on teardown."""
    peer_stack._gatt_server.add_service(build_test_service())
    yield stack, peer_stack
    # stack/peer_stack fixtures own their own close()


@pytest_asyncio.fixture
async def virtual_link_or_real_rf(central_peripheral_pair, transport_mode):
    """Virtual mode: create VirtualLELink to bridge the two virtual controllers.
    Hardware mode: yield None (real RF connects them)."""
    stack_c, stack_p = central_peripheral_pair
    if transport_mode == "virtual":
        link = VirtualLELink(
            central=stack_c._virtual_controller,
            peripheral=stack_p._virtual_controller,
            central_address=stack_c._local_address,
            peripheral_address=stack_p._local_address,
        )
        try:
            yield link
        finally:
            try:
                await link.disconnect()
            except Exception:
                pass
    else:
        yield None
```

`stack` and `peer_stack` come from the existing session-level fixtures in `tests/conftest.py` and adapt to the `--transport` / `--transport-peer` command-line specs.

### 4.3 Helpers (`tests/e2e/_helpers.py`)

```python
async def central_discover_peripheral(stack_c, expected_addr, timeout=2.0) -> int:
    """Start scanner, wait for advertising report matching expected_addr, stop
    scanner, call gap.ble_connections.connect(), return the connection handle."""

async def central_discover_and_pair_sc_jw(stack_c, expected_addr, timeout=20.0) -> int:
    """Convenience composition for Tests 1–3: discover + connect + SC JW pair.
    Returns the handle on success; raises on any failure."""

async def wait_for_notifications(events: list, n: int, timeout: float = 1.0) -> None:
    """Block until len(events) >= n or asyncio.TimeoutError."""
```

## 5. Per-scenario data flow

### Test 1 — `test_e2e_scan_connect_pair_read`

```
Setup: central_peripheral_pair + virtual_link_or_real_rf
Skip:  if not _supports_le_sc(stack_c): pytest.skip(...)

P: gap.ble_advertiser.start(adv_data including TEST_SERVICE_UUID + local_name "PBH-E2E")
C: handle = await central_discover_and_pair_sc_jw(stack_c, P.local_address)
C: client = stack_c.gatt_client(handle)                  # exact API name verified at impl time
   services = await client.discover_services()
   assert TEST_SERVICE_UUID in [s.uuid for s in services]
   svc = next(s for s in services if s.uuid == TEST_SERVICE_UUID)
   chars = await client.discover_characteristics(svc.handle_range)
   read_char = next(c for c in chars if c.uuid == TEST_READ_CHAR_UUID)
   value = await client.read_characteristic(read_char.value_handle)
   assert value == INITIAL_READ_VALUE
C: await stack_c.gap.ble_connections.disconnect(handle)
   (verify disconnect lifecycle event observed on stack_c)
```

### Test 2 — `test_e2e_gatt_write_and_notify`

```
Setup: same fixture; register a write-observer on the peripheral that appends
       every received write to TEST_WRITE_CHAR_UUID into a list.
Skip:  if not _supports_le_sc(stack_c): pytest.skip(...)

P: gap.ble_advertiser.start(...)
C: handle = await central_discover_and_pair_sc_jw(stack_c, P.local_address)
C: client = stack_c.gatt_client(handle); await client.discover_services(); etc.
C: write_handle = chars[TEST_WRITE_CHAR_UUID].value_handle
   notify_value_handle = chars[TEST_NOTIFY_CHAR_UUID].value_handle
   notify_cccd_handle = chars[TEST_NOTIFY_CHAR_UUID].cccd_handle
C: await client.write_characteristic(write_handle, b"hello e2e")
P: await asyncio.sleep(0.05)
   assert peripheral_writes == [b"hello e2e"]

C: notify_events = []
   client.on_notification(notify_value_handle, lambda v: notify_events.append(v))
   await client.write_descriptor(notify_cccd_handle, bytes([0x01, 0x00]))  # subscribe
P: stack_p._gatt_server.notify(notify_value_handle, b"ping-1")
   stack_p._gatt_server.notify(notify_value_handle, b"ping-2")
C: await wait_for_notifications(notify_events, n=2, timeout=2.0)
   assert notify_events == [b"ping-1", b"ping-2"]

C: await client.write_descriptor(notify_cccd_handle, bytes([0x00, 0x00]))  # unsubscribe
P: stack_p._gatt_server.notify(notify_value_handle, b"ping-3")
C: await asyncio.sleep(0.1)
   assert notify_events == [b"ping-1", b"ping-2"]   # still 2 — unsubscribed

teardown via fixture
```

Note: the `client.on_notification`, `stack_p._gatt_server.notify`, and CCCD write helpers may be spelled differently in the actual implementation. The implementation Plan will resolve names against the real API; the contract here is the *behavior* of each step.

### Test 3 — `test_e2e_bonded_reconnect_auto_encrypt`

This test does NOT use `central_peripheral_pair` directly; it manages its own two-session lifecycle so each session opens fresh stacks pointing at the same on-disk bond storage.

```
Skip: virtual-mode only for now (hardware needs adapter capability check; defer).
      Actually: same SC capability gate as Tests 1–2 — works on both transports.

Session 1:
  storage_c = JsonBondStorage(tmp_path / "bonds_c.json")
  storage_p = JsonBondStorage(tmp_path / "bonds_p.json")
  cfg_c = StackConfig(bond_storage=storage_c, security=SecurityConfig(enable_secure_connections=True))
  cfg_p = StackConfig(bond_storage=storage_p, security=SecurityConfig(enable_secure_connections=True))
  stack_c = build_stack_from_spec(selected_transport_spec, config=cfg_c)
  stack_p = build_stack_from_spec(selected_peer_spec, config=cfg_p)
  stack_p._gatt_server.add_service(build_test_service())
  (virtual mode: also bridge with VirtualLELink as in fixture)
  handle = await central_discover_and_pair_sc_jw(stack_c, stack_p._local_address)
  bond = await storage_c.load_bond(stack_p._local_address)
  assert bond is not None and bond.sc is True
  await stack_c.gap.ble_connections.disconnect(handle)
  await stack_c.close(); await stack_p.close()

Session 2 (same tmp_path):
  Repeat the stack-open dance with the SAME storage paths.
  encrypted_seen = []
  stack_c.on_connection_event(lambda e: encrypted_seen.append(e) if e.state == "encrypted" else None)
  handle = await central_discover_peripheral(stack_c, stack_p._local_address, timeout=5.0)
  # NOTE: no pair() call here — auto-encrypt should fire because the bond exists.
  for _ in range(20):
      if encrypted_seen:
          break
      await asyncio.sleep(0.05)
  assert encrypted_seen, "auto-encrypt did not fire on bonded reconnect"

  # Now verify GATT works on the encrypted link
  client = stack_c.gatt_client(handle)
  services = await client.discover_services()
  read_handle = ... resolve TEST_READ_CHAR_UUID ...
  value = await client.read_characteristic(read_handle)
  assert value == INITIAL_READ_VALUE

  teardown
```

### Test 4 — `test_e2e_pair_failure_disconnects_cleanly`

```
Setup: two stacks with SC + mitm_required=True + DisplayYesNo / KeyboardOnly
       IO caps (which selects NC under the 3a rules).
       Inject mismatched _FixedPasskeyDelegate (or any NC delegate that rejects)
       on stack_p. Stack_c uses an auto-accept NC delegate.
Skip:  same SC capability gate.

P: gap.ble_advertiser.start(...)
C: handle = await central_discover_peripheral(stack_c, stack_p._local_address)
C: with pytest.raises(RuntimeError, match="SMP pairing failed"):
       await stack_c.pair(handle, timeout=5.0)

# Teardown must complete promptly even after the failed pair.
await asyncio.wait_for(stack_c.gap.ble_connections.disconnect(handle), timeout=2.0)
# Fixture teardown closes both stacks; if either stack.close() hangs longer than
# 2s the pytest run fails on overall test timeout.
```

## 6. Error & edge handling

| Scenario | Failure mode | Handling |
|---|---|---|
| All | SC capability absent on hardware | `pytest.skip("adapter does not support LE Secure Connections")` |
| Test 1, 2 | No advertising report seen within 2 s | `pytest.fail("no peripheral advert")` |
| Test 2 | Notification timeout | `wait_for_notifications` raises with the list received so far |
| Test 3 | Auto-encrypt event doesn't fire within 5 s | `assert encrypted_seen` fails with the explicit message |
| Test 3 | GATT read on encrypted link fails | propagate the ATT error code for clean diagnosis |
| Test 4 | `pair()` doesn't raise | `pytest.raises` catches that and fails |
| Test 4 | Teardown hangs after failure | `asyncio.wait_for(..., timeout=2.0)` raises `TimeoutError` |

Each scenario:
- Carries `@pytest.mark.e2e` (already registered in `tests/conftest.py`).
- Uses `tmp_path` for any bond storage — hermetic.
- Bounds all awaits with `asyncio.wait_for(..., timeout=...)`; per-scenario budget ≤ 15 s.
- Uses `pytest_asyncio.fixture` (already in dependencies).

## 7. File layout

```
tests/e2e/
├── __init__.py             (exists, empty)
├── conftest.py             (REPLACE — adds central_peripheral_pair, virtual_link_or_real_rf)
├── _test_service.py        (NEW — TEST_SERVICE_UUID + build_test_service)
├── _helpers.py             (NEW — central_discover_peripheral,
│                                  central_discover_and_pair_sc_jw,
│                                  wait_for_notifications,
│                                  _supports_le_sc)
└── test_le_lifecycle.py    (NEW — the 4 scenarios)
```

The current `tests/e2e/conftest.py` (created by Pytest Transport Selection Task 15 as a placeholder) is replaced with the new fixtures. No production-code changes anticipated — this Plan is test-only.

## 8. Test strategy

Already covered per scenario in §5. Top-level acceptance:

- `uv run pytest tests/e2e/ -v --transport=virtual` → 4 passed.
- `uv run pytest tests/ -q --transport=virtual` → suite green minus the 3 pre-existing USB-diagnostics failures.
- `uv run pytest tests/e2e/ -v --transport=usb:VID:PID#1 --transport-peer=usb:VID:PID#2` → either passes (full hardware coverage) or skips per scenario (capability-gated). Documented in §9 below as a manual smoke step before each release; **no CI integration in this Plan**.

## 9. Running on hardware

The same scenarios run against two USB adapters:

```bash
uv run pytest tests/e2e/ -v \
    --transport=usb:vendor=intel#1 \
    --transport-peer=usb:vendor=intel#2
```

Capability gates (§3) auto-skip scenarios when the adapter lacks SC. No code change required.

If hardware E2E later reveals real-world issues (RF timing, vendor quirks, firmware bugs) that require new test logic, those issues get their own scoped Plan rather than living in this generic E2E suite.

## 10. Known risks

1. **GATT client API name drift** — `stack_c.gatt_client(handle)`, `client.on_notification(...)`, `stack_p._gatt_server.notify(...)`, and CCCD descriptor write spellings are best-effort and need verification against the real implementation during the writing-plans / implementation phase. The contract (what each step does) is stable; the exact spelling may shift.

2. **`stack._local_address` after Stack.virtual()** — virtual stacks accept an explicit `address=` argument; hardware stacks compute it from `Read_BD_ADDR` during init. Tests must use `stack._local_address` to be transport-agnostic. Existing loopback tests already use this pattern.

3. **Bond storage round-trip in Test 3** — `JsonBondStorage` persistence on disk works correctly for SC bonds today (proven by `test_sc_reconnect_auto_restores_encryption`). Re-opening the same file in session 2 must produce the same `BondInfo` (verified there too). No new functionality needed.

4. **Auto-encrypt timing on real hardware** — virtual mode triggers auto-encrypt in single-digit milliseconds; real RF needs the controller to send `HCI_LE_Long_Term_Key_Request` after connection, then `HCI_LE_Long_Term_Key_Request_Reply`, then `HCI_Encryption_Change`. 5-second budget is generous for hardware too. If a real adapter needs more, that becomes a documented issue with a per-test override, not a redesign.

5. **NC delegate API surface on Test 4** — `stack._smp.set_delegate(...)` is used today by all four integration loopback tests; should work transparently for hardware mode as well (the delegate is host-side, not radio-side).

6. **Two USB adapters in CI** — out of scope. CI runs `--transport=virtual` only. Hardware coverage is manual via the invocation in §9.

## 11. Acceptance criteria

- [ ] `tests/e2e/_test_service.py`, `tests/e2e/_helpers.py`, `tests/e2e/conftest.py` exist with the documented surfaces.
- [ ] `tests/e2e/test_le_lifecycle.py` has the 4 scenarios named per §2.
- [ ] All 4 scenarios use `@pytest.mark.e2e`.
- [ ] All 4 scenarios use `stack` + `peer_stack` fixtures (no `Stack.virtual()` hard-coded in scenario bodies; Test 3 manually opens stacks via `build_stack_from_spec` and is the documented exception).
- [ ] `_supports_le_sc()` capability-gates each SC-requiring scenario.
- [ ] `uv run pytest tests/e2e/ -v --transport=virtual` → 4 passed in under 30 s.
- [ ] `uv run pytest tests/ -q --transport=virtual` → suite green minus the 3 pre-existing USB-diagnostics failures.
- [ ] STATUS.md updated to mark this Plan ✅; "下一步" reflects the new state.

## 12. Out of scope (deferred)

| Item | When |
|---|---|
| Classic E2E (inquiry → SDP browse → RFCOMM/SPP echo) | Separate Plan when scoped |
| Trace/btsnoop assertion harness | Separate Plan when scoped |
| CLI subprocess orchestration (`pybluehost app gatt-server` + scan/connect from another process) | Separate Plan when scoped |
| Phone interop (real Android/iOS as peer) | Separate Plan; requires per-OS bond-storage / RPA verification |
| Hardware CI runner / test bench | Infrastructure work; out of test-code scope |
| Pair-flavor matrix in E2E (NC, Passkey, SC Passkey lifecycles) | Per-flavor pair correctness already covered by `tests/integration/test_pairing_*.py`; adding E2E variants is value-low unless a specific composition bug surfaces |
| OOB | **Not on roadmap**; recorded in STATUS.md |
