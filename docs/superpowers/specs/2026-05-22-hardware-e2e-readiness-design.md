# Hardware E2E Readiness — Design Spec

**Date**: 2026-05-22
**Scope**: Prepare the existing e2e suite to run on real BR/EDR + LE USB adapters without writing any hardware-only tests. Four deliverables: (1) `build_stack_from_spec` accepts `config=` kwarg so currently-skipped tests can run on hardware; (2) `e2e_timeout(...)` helper applies transport-aware budgets; (3) a `pybluehost tools info` CLI command dumps the full HCI capability set of an adapter; (4) a hardware runbook `docs/HARDWARE_E2E.md` that documents how to onboard, run, and triage. All four items are verifiable on virtual transport today; the verification on real hardware is a separate manual step that runs once an adapter pair is procured.
**Predecessors**: E2E LE Lifecycle, VirtualClassicLink, Classic Workflow E2E, Pytest Transport Selection (provides `--transport=` / `--transport-peer=` and `build_stack_from_spec`), HCI Tolerant Initialization (provides `HCIController.supported_commands` bitmap).
**Successors**: (B-option-only — C is not in scope here) Self-hosted hardware CI runner; phone-as-peer interop; per-vendor quirk catalog as adapters are surveyed.

---

## 1. Goals

The existing e2e suite is transport-agnostic in design but partially-blocked from hardware mode by three deferred items, all flagged in earlier Plans:

1. `build_stack_from_spec(spec)` doesn't accept a `config=` kwarg — so LE Test 3 (bonded reconnect), Classic Test 3 (bonded reconnect), and Classic Test 4 (pair-failure clean teardown) `pytest.skip` in hardware mode because they need per-test `JsonBondStorage` / `SecurityConfig`.
2. Test timeouts are tuned for virtual transport (sub-second). Real RF needs more headroom — inquiry takes 1–2 s, page-scan windows, vendor-specific delays.
3. There's no quick way to ask "does this adapter support what I'm about to test?" before running 30 s of tests that might skip the interesting parts.

This Plan delivers the four readiness items, all verifiable on virtual. The actual hardware verification — running the same suite on two real adapters — is then a documented manual step in `docs/HARDWARE_E2E.md`. No hardware is required to land this Plan.

Out of scope (separate Plans):
- Self-hosted hardware CI runner.
- Per-vendor quirk catalog (added incrementally as adapters get surveyed).
- Phone-as-peer interop (different scenarios).
- A2DP / HFP / SCO audio profiles.

## 2. Architecture

Four mostly-independent pieces:

```
docs/HARDWARE_E2E.md                              NEW  — runbook
pybluehost/cli/tools/info.py                      NEW  — full HCI capability dump
pybluehost/hci/features_decode.py                 NEW  — LE/BR-EDR feature bitmap decoder
pybluehost/hci/capabilities.py                    MODIFY — extend _OPCODE_BIT_POSITIONS for BR/EDR opcodes
tests/_transport_resolve.py                        MODIFY — build_stack_from_spec accepts config=
tests/e2e/_helpers.py                              MODIFY — add e2e_timeout(transport_mode, virtual=, usb=, uart=)
tests/e2e/test_le_lifecycle.py                     MODIFY — Test 3 uses build_stack_from_spec(config=)
tests/e2e/test_classic_lifecycle.py                MODIFY — Test 3 + Test 4 same; relevant tests use e2e_timeout
tests/unit/test_build_stack_from_spec_config.py    NEW  — config= round-trip tests
tests/unit/test_e2e_timeout.py                     NEW  — helper unit tests
tests/unit/cli/tools/test_info.py                  NEW  — info CLI tests against virtual stack
```

No production-code surface area changes outside the new CLI command + the small build_stack_from_spec signature extension + the constants in `capabilities.py` and `features_decode.py`.

## 3. `build_stack_from_spec(config=)`

Current signature in `tests/_transport_resolve.py`:

```python
async def build_stack_from_spec(spec: str) -> Stack:
    ...
    return await Stack.from_usb(...)  # or .from_uart, .virtual, ...
```

New signature:

```python
async def build_stack_from_spec(
    spec: str,
    *,
    config: StackConfig | None = None,
) -> Stack:
    ...
    return await Stack.from_usb(..., config=config)  # config threaded through every branch
```

All `Stack.from_*` factories (`from_usb`, `from_uart`, `from_tcp`, `from_btsnoop`, `virtual`) already accept `config: StackConfig | None`. The factory function just doesn't propagate it today. Adding `config=` to each branch is one line per branch. Backward-compatible (`config=None` matches today's behavior).

**Removes the `pytest.skip("hardware mode: build_stack_from_spec doesn't accept config=")` blocks** in:
- `tests/e2e/test_le_lifecycle.py::test_e2e_bonded_reconnect_auto_encrypt`
- `tests/e2e/test_classic_lifecycle.py::test_e2e_classic_bonded_reconnect_auto_encrypt`
- `tests/e2e/test_classic_lifecycle.py::test_e2e_classic_pair_failure_disconnects_cleanly`

Each test's `_open_pair` helper currently uses `Stack.virtual(config=...)` directly in virtual mode and skips otherwise. Replace the conditional with `await build_stack_from_spec(selected_transport_spec, config=cfg_c)` so the same code path works in either mode.

The bridge construction (`VirtualLELink` / `VirtualClassicLink`) stays virtual-mode-only via the existing `transport_mode == "virtual"` check (real RF doesn't need a bridge).

## 4. `e2e_timeout(transport_mode, virtual=, usb=, uart=)`

Small helper in `tests/e2e/_helpers.py`:

```python
def e2e_timeout(
    transport_mode: str,
    *,
    virtual: float,
    usb: float | None = None,
    uart: float | None = None,
) -> float:
    """Return a transport-appropriate timeout.

    Virtual is sub-second; real RF needs more headroom for inquiry timing,
    page-scan windows, and connection setup. Defaults: usb 5× virtual, uart 8×.
    """
    if transport_mode == "virtual":
        return virtual
    if transport_mode == "usb":
        return usb if usb is not None else virtual * 5
    if transport_mode == "uart":
        return uart if uart is not None else virtual * 8
    return virtual
```

Call sites:

```python
echoed = await asyncio.wait_for(
    spp_conn.recv(),
    timeout=e2e_timeout(transport_mode, virtual=1.0, usb=3.0),
)
```

Applied to:
- LE E2E: notification waits (Test 2), auto-encrypt event wait (Test 3), `pair()` and `stack.close()` (Test 4).
- Classic E2E: SPP echo recv (Test 2), `authenticate_classic` (Tests 3, 4), `enable_classic_encryption` (Test 3), `classic_discover_peripheral` + `connect_classic` (all four scenarios).

Audit pass during implementation: grep `asyncio.wait_for` and `timeout=` in `tests/e2e/`, wrap each numeric timeout < 3 s in `e2e_timeout(...)`. Long timeouts (60s SC Passkey, 20s pair) already accommodate hardware and stay as-is.

Mechanical migration. No behavior change in virtual mode (returns same number); hardware mode gets longer timeouts automatically.

## 5. `pybluehost tools info` CLI

Lives in `pybluehost/cli/tools/info.py`. Hooks into the existing `pybluehost/cli/tools/` subcommand dispatch alongside `usb_diagnose`.

### Invocation

```
pybluehost tools info --transport=<spec>      # human-readable table (default)
pybluehost tools info --transport=<spec> --json   # machine-readable JSON
pybluehost tools info --transport=<spec> --json > my-adapter.json  # save baseline
```

Same `--transport=` spec syntax as pytest. No `--transport-peer=` (info is single-adapter).

### Output (human-readable)

Five sections per Section-2 sketch (Adapter identity / Capability summary / LE Features / BR/EDR Features / Supported HCI commands), plus a "Recommended pytest invocations" footer.

### Capability decoding

Three data sources:
1. `HCIController.supported_commands.bitmap` (already populated during `initialize()`) — 64 bytes.
2. `Read_Local_Supported_Features` response (BR/EDR features bitmap).
3. `LE_Read_Local_Supported_Features` response (LE features bitmap).
4. `Read_Local_Version_Information` for HCI/LMP version + manufacturer ID.
5. `Read_BD_ADDR` for the address.

All five HCI commands run in `HCIController.initialize()` today and the responses are cached. `info` consumes the cache; no fresh HCI commands.

### Decoding tables

New module `pybluehost/hci/features_decode.py`:

```python
# Pure-data dictionaries. No logic.

LE_FEATURE_BIT_NAMES: dict[tuple[int, int], str] = {
    (0, 0): "LE Encryption",
    (0, 1): "Connection Parameters Request Procedure",
    (0, 2): "Extended Reject Indication",
    (0, 3): "Slave-initiated Features Exchange",
    (0, 4): "LE Ping",
    (0, 5): "LE Data Packet Length Extension",
    (0, 6): "LL Privacy",
    (0, 7): "Extended Scanner Filter Policies",
    (1, 0): "LE 2M PHY",
    (1, 1): "Stable Modulation Index — Transmitter",
    # ... per Core Spec Vol 6 Part B §4.6, up to byte 7
}

BREDR_FEATURE_BIT_NAMES: dict[tuple[int, int], str] = {
    (0, 0): "3-slot packets",
    (0, 1): "5-slot packets",
    (0, 2): "Encryption",
    # ... per Core Spec Vol 2 Part C §3.3 page 0
}

MANUFACTURER_NAMES: dict[int, str] = {
    0x0002: "Intel Corp.",
    0x000A: "CSR (Qualcomm)",
    0x000F: "Broadcom",
    0x005D: "Realtek Semiconductor Corp.",
    # ... small list of common BT chipset vendors; "Unknown (0xNNNN)" fallback
}
```

About 80 lines of constants, no logic. Easy to extend.

Extend `pybluehost/hci/capabilities.py`'s `_OPCODE_BIT_POSITIONS` (currently 17 entries from the HCI Tolerant Init Plan) with BR/EDR opcodes already used by `VirtualClassicLink` (Inquiry, Create_Connection, Disconnect, Auth_Requested, Set_Connection_Encryption, IO_Capability_Request_Reply, …) and the SC-related ones (LE_Read_Local_P-256_Public_Key, LE_Generate_DHKey) per Sub-Plan 3a Task 2. Roughly 25 more entries.

### `--json` output

```json
{
  "transport": "usb:vendor=intel",
  "bd_addr": "5C:80:B6:AA:BB:CC",
  "manufacturer_id": 2,
  "manufacturer_name": "Intel Corp.",
  "hci_version": "5.4",
  "lmp_version": 14,
  "lmp_subversion": 16,
  "capability_summary": {
    "le_secure_connections": true,
    "le_audio": true,
    "le_privacy_rpa": true,
    "le_extended_advertising": true,
    "bredr": true,
    "bredr_ssp": true,
    "bredr_sc": true,
    "extended_inquiry_response": true
  },
  "le_features": {
    "0/0": {"name": "LE Encryption", "supported": true},
    "0/1": {"name": "Connection Parameters Request Procedure", "supported": true}
  },
  "bredr_features": {
    "0/2": {"name": "Encryption", "supported": true},
    "0/3": {"name": "Encryption Pause Suspend Resume", "supported": true}
  },
  "supported_commands": {
    "decoded": {"0/4": "Inquiry", "0/5": "Inquiry Cancel"},
    "unknown_bits_set": [{"octet": 38, "bit": 3}]
  }
}
```

The "unknown bits" list is the bits set in the 64-byte command bitmap that don't appear in `_OPCODE_BIT_POSITIONS`. Useful for triaging "my adapter supports an opcode my host doesn't recognize" cases — the user can look up the (octet, bit) pair in the spec.

### Capability summary semantics

Each summary key is a 1-line predicate over the above data. Reuses existing helpers where they exist:

| Key | Predicate |
|---|---|
| `le_secure_connections` | LE Features bit (1, 0) set AND command bitmap bit for `HCI_LE_Read_Local_P-256_Public_Key` set |
| `le_audio` | LE Features byte 4 bit 4 (Isochronous Channels) set |
| `le_privacy_rpa` | LE Features bit (0, 6) set |
| `le_extended_advertising` | LE Features byte 1 bit 4 (LE Extended Advertising) set |
| `bredr` | BR/EDR Features byte 0 bit 2 (Encryption) set |
| `bredr_ssp` | command bitmap bit for `HCI_IO_Capability_Request_Reply` set |
| `bredr_sc` | LMP Features page 1 bit 0 (Secure Connections Host Support) set — requires `Read_Local_Extended_Features` extension if not already in init |
| `extended_inquiry_response` | command bitmap bit for `HCI_Write_Extended_Inquiry_Response` set |

If a feature requires HCI calls beyond what `initialize()` already issues (e.g., `bredr_sc` may need page-1 of extended features), `info` issues that one extra command transparently. Documented in the source.

## 6. `docs/HARDWARE_E2E.md` runbook

~400 lines. Outline per Section-4 of brainstorm. Key sections:

1. **Quick start** (~30 lines) — 5-minute happy path
2. **Adapter compatibility matrix** (~20 lines table) — populated with placeholder rows pending real surveys
3. **`info` CLI usage** (~40 lines) — sample outputs, --json baseline saving, diff between firmware versions
4. **Two-adapter pairing convention** (~20 lines) — Central = `--transport`, Peripheral = `--transport-peer`; roles aren't HCI-enforced
5. **Common failure triage** (~60 lines table) — symptom / likely cause / mitigation rows
6. **Adding a new adapter to known-good** (~20 lines) — checklist (run `info`, save JSON, add matrix row, run e2e suite as central+peer)
7. **What is NOT tested by this suite** (~15 lines) — cross-vendor interop, LE Audio streams, A2DP/HFP, high-throughput sustained traffic
8. **CI status** (~10 lines) — these tests do NOT run in CI; manual smoke before release

Matrix rows and "verified" tags use placeholder values now ("verified on hardware: TBD") — they get filled when an adapter is actually surveyed. The doc lands with the matrix template, not real data.

## 7. Test strategy

**All four pieces verifiable today on virtual transport. No real hardware needed.**

### `build_stack_from_spec(config=)` — `tests/unit/test_build_stack_from_spec_config.py`

3 tests:
- `test_build_stack_from_spec_virtual_with_config_threads_config` — pass a custom `StackConfig` to a virtual spec; assert `stack._config is cfg`.
- `test_build_stack_from_spec_usb_with_config_threads_config` — mock `USBTransport.auto_detect` to return a stub; pass a custom config; assert `Stack.from_usb` was called with `config=cfg`.
- `test_build_stack_from_spec_default_config_when_none` — call with no config; verify a `StackConfig()` is constructed (or `None` is passed through — pick whichever matches `Stack.from_*` actual signature).

### `e2e_timeout` — `tests/unit/test_e2e_timeout.py`

4 tests:
- `test_e2e_timeout_virtual_returns_virtual_value`
- `test_e2e_timeout_usb_uses_usb_when_supplied`
- `test_e2e_timeout_usb_defaults_to_5x_virtual_when_not_supplied`
- `test_e2e_timeout_unknown_transport_falls_back_to_virtual`

### `info` CLI — `tests/unit/cli/tools/test_info.py`

6 tests against a virtual stack (deterministic capability bitmap):
- `test_info_human_table_lists_bd_addr_and_manufacturer`
- `test_info_human_table_lists_le_features_decoded`
- `test_info_human_table_lists_bredr_features_decoded`
- `test_info_human_table_lists_capability_summary`
- `test_info_json_output_has_required_keys`
- `test_info_unknown_command_bits_appear_in_unknown_list`

The virtual stack's `VirtualController` returns a known bitmap (per HCI Tolerant Init Plan). The test asserts the CLI output contains the expected decoded names and the summary's Yes/No values match `_supports_le_sc(stack)` etc.

### Integration update — existing tests

Re-run `tests/e2e/` after the migration to confirm:
- LE Test 3 + Classic Test 3 + Classic Test 4 still pass on virtual mode (they did before; the `_open_pair` rewrite shouldn't change virtual behavior).
- e2e_timeout migration doesn't slow virtual tests (the helper returns the same number in virtual mode).

## 8. Known risks

1. **`Read_Local_Extended_Features` page-1 not in init**. The `bredr_sc` summary key needs page-1 LMP features. If `HCIController.initialize()` doesn't already issue `Read_Local_Extended_Features(page=1)`, `info` either:
   - Issues that one extra command transparently when computing the summary.
   - Or marks `bredr_sc` as "unknown" if the page-1 read fails.
   The implementer picks based on what's cleanest. Either is acceptable.

2. **Adapter that fails partway through init**. `info` requires a successful `HCIController.initialize()` to read the cached bitmaps. If init fails (e.g., USB transport opens but the adapter rejects commands), `info` should fail gracefully with a clear error message ("failed to initialize adapter; cannot survey").

3. **Manufacturer ID list staleness**. `MANUFACTURER_NAMES` will only cover the common vendors. Falls back to `"Unknown (0xNNNN)"` for unrecognized IDs. Not a correctness issue; readability only.

4. **`build_stack_from_spec` signature compatibility**. Every caller in the test suite uses `await build_stack_from_spec(spec)` (no kwargs). Adding a keyword-only `config=None` parameter is backward-compatible. Grep verifies no positional-arg callers exist.

5. **e2e_timeout in non-e2e tests**. The helper lives in `tests/e2e/_helpers.py` and is only imported by e2e tests. Integration tests (`tests/integration/`) keep their existing timeouts since they're virtual-only by design.

6. **Runbook placeholders**. The compatibility matrix lands empty (template rows). This is fine — it's the runbook's job to grow as adapters are surveyed. Document this explicitly so reviewers don't expect filled-in data.

## 9. Acceptance criteria

- [ ] `build_stack_from_spec(spec, *, config=None)` works across all transport branches; backward-compatible.
- [ ] `e2e_timeout(transport_mode, virtual=, usb=, uart=)` helper exists in `tests/e2e/_helpers.py`.
- [ ] LE Test 3 + Classic Test 3 + Classic Test 4 no longer carry `pytest.skip("build_stack_from_spec doesn't accept config=")` (skip reason changes to "no peer transport configured" when run without `--transport-peer`, OR they actually run when `--transport-peer` is provided).
- [ ] `pybluehost tools info --transport=virtual` runs successfully and produces decoded LE / BR-EDR features + capability summary.
- [ ] `pybluehost tools info --transport=virtual --json` runs and produces valid JSON with the documented keys.
- [ ] `docs/HARDWARE_E2E.md` exists with the eight outlined sections.
- [ ] All new unit tests pass (~13 tests total: 3 + 4 + 6).
- [ ] `uv run pytest tests/ -q --transport=virtual` → suite green minus the 3 pre-existing USB-diagnostics failures.

## 10. Out of scope (deferred)

| Item | When |
|---|---|
| Self-hosted hardware CI runner | Separate Plan; ops/security decisions out-of-band |
| Phone-as-peer interop tests | Separate Plan; requires per-OS bond-storage / RPA verification |
| Per-vendor quirk catalog | Grows incrementally as adapters are surveyed |
| A2DP / HFP / SCO audio | Independent Plan if needed |
| LE Audio CIS/BIS streams | Independent Plan if needed |
| High-throughput sustained traffic load | Independent Plan if needed |
| `info` color terminal output | Optional follow-up; current scope is monochrome |
| `info --diff <baseline.json>` flag | Optional follow-up |
