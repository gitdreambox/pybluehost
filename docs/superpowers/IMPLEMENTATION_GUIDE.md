# PyBlueHost PRD v1.2 Implementation Guide

## Overview

This document guides the implementation of PRD v1.2 (PTS IUT Support) across 15 tasks organized into 4 Plans (P.1-P.4). The implementation is based on the design spec at `docs/superpowers/specs/2026-05-29-prd-v1.2-pts-iut-design.md` and the detailed plan at `docs/superpowers/plans/2026-05-31-v1.2-pts-iut-phase1.md`.

**Phase 1 delivers:**
1. PTS mode configuration flags (5 flags, Task 1-5)
2. IUT action layer + REPL front-end (Tasks 6-12)
3. PICS semi-automatic generator (Tasks 13-14)
4. Framework for manual PTS runs (Task 15)

**Phase 2 (future):** BTP tester + auto-pts integration (out of scope for v1.2)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│  Phase 1 REPL front-end (pybluehost app pts-iut)   │
│  - parse_repl_command (Task 11)                     │
│  - run_repl async loop (Task 12)                    │
│  - --pts-* CLI flags (Task 12)                      │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│  IUT action layer (pybluehost/pts/actions.py)       │
│  - advertise/scan (Task 6)                          │
│  - connect/disconnect (Task 7)                      │
│  - pair/encrypt (Task 8)                            │
│  - notify/indicate/read/write (Task 9)              │
│  - sdp_browse/rfcomm_open/l2cap_connect (Task 10)  │
│  - session state (ConnInfo, IutSession)             │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│  Stack with PTS mode flags (Tasks 1-5)              │
│  - StackConfig.pts: PTSModeConfig | None            │
│  - 5 PTS flags (Task 1)                             │
│  - sc_only_mode wiring (Task 2)                     │
│  - smp_options override (Task 3)                    │
│  - smp_failure_at injection (Task 4)                │
│  - disable_sdp_on_le_pair guard (Task 5)           │
└─────────────────────────────────────────────────────┘
```

---

## Implementation Status

### ✅ Completed
- **Task 1**: PTSModeConfig dataclass + StackConfig.pts integration
  - Created `pybluehost/pts/config.py` with PTSModeConfig (5 fields)
  - Updated `pybluehost/stack.py` with `StackConfig.pts` field
  - Tests pass (3/3); zero impact on existing tests

- **Partial Task 2**: Activate sc_only_mode
  - Uncommented `sc_only_mode: bool = False` in SecurityConfig
  - Updated `_validate_sc_dependencies` to check sc_only_mode

### ⏳ Next: Complete Tasks 2-5 (PTS mode flag hooks)

The following tasks complete the flag framework and require SMP modifications:

- **Task 2 (cont'd):** Wire `pts.secure_pair_only` → `security.sc_only_mode` at Stack._build
- **Task 3:** Add `smp_options` byte override at Pairing Request/Response construction
- **Task 4:** Implement `smp_failure_at` injection at 5 named SMP stages
- **Task 5:** Add `disable_sdp_on_le_pair` guard at LE-pair completion

### ⏳ Then: Implement Tasks 6-12 (IUT Action Layer + REPL)

- **Task 6:** Create `IutActions` skeleton + advertise/scan primitives
- **Task 7:** Implement connect/disconnect with session tracking
- **Task 8:** Implement pair/encrypt/set_io_cap + pairing helpers
- **Task 9:** Implement GATT client/server primitives (read/write/notify/indicate)
- **Task 10:** Implement Classic primitives (SDP/RFCOMM/L2CAP)
- **Task 11:** Implement `parse_repl_command` parser (shlex-based)
- **Task 12:** Implement REPL loop + CLI command + PTS flag wiring

### ⏳ Then: Implement Tasks 13-15 (PICS Generator + Framework)

- **Task 13:** Create PICS draft generator from capability dump
- **Task 14:** CLI command + docs/pts/ scaffolding
- **Task 15:** Runbook + results template + initial drafts

---

## Key Design Decisions

### 1. PTS mode = opt-in, zero-impact by default

```python
# When StackConfig.pts=None (default):
# - No behavior changes vs v1.0/v1.1
# - All hooks short-circuit
# - Regression tests pass 100%
```

### 2. Action layer has no front-end coupling

The `IutActions` class is designed to be a pure API layer:
- REPL front-end (Task 12) calls `IutActions` methods
- Phase 2 BTP tester (future) will also call same `IutActions` methods
- No REPL or BTP specific code in `IutActions`

### 3. Session state is maintained across commands

The `IutSession` dataclass tracks:
- Active connections (dict: handle → ConnInfo)
- Last handle (for command shorthand: `disconnect` without explicit handle)
- LE/Classic IO capabilities (mutable for `set-io-cap` command)

### 4. PICS generation is semi-automatic

- Generator reads existing `pybluehost tools info` output
- Produces human-readable YAML drafts (not proprietary PTS files)
- Operator manually imports into PTS UI

---

## File Structure (Complete)

```
pybluehost/pts/
├── __init__.py                      # Export PTSModeConfig, IutActions, etc
├── config.py                        # PTSModeConfig dataclass (Tasks 1-5)
├── actions.py                       # IutActions + ConnInfo + IutSession (Tasks 6-10)
├── repl.py                          # parse_repl_command + run_repl (Tasks 11-12)
├── pics_gen.py                      # generate_pics_draft (Task 13)
└── btp/                             # Phase 2 (out of scope for v1.2)

pybluehost/cli/
├── app/
│   ├── pts_iut.py                  # pybluehost app pts-iut command (Task 12)
│   └── __init__.py                 # Register pts-iut command
└── tools/
    ├── pics_gen.py                 # pybluehost tools pics-gen command (Task 14)
    └── __init__.py                 # Register pics-gen command

pybluehost/ble/
├── security.py                      # Activate sc_only_mode (Task 2)
├── smp.py                           # Add PTS mode hooks (Tasks 2-4)
└── gatt.py                          # (no changes needed for Phase 1)

pybluehost/stack.py                 # Add pts field + _build wiring (Tasks 1-2)

tests/unit/pts/
├── __init__.py
├── test_config.py                  # Task 1 tests
├── test_secure_pair_only.py        # Task 2 tests
├── test_smp_options.py             # Task 3 tests
├── test_smp_failure.py             # Task 4 tests
├── test_disable_sdp_on_le_pair.py  # Task 5 tests
├── test_actions_advertise_scan.py  # Task 6 tests
├── test_actions_connect.py         # Task 7 tests
├── test_actions_pair.py            # Task 8 tests
├── test_actions_gatt.py            # Task 9 tests
├── test_actions_classic.py         # Task 10 tests
├── test_repl_parse.py              # Task 11 tests
└── test_pics_gen.py                # Task 13 tests

tests/unit/cli/
├── test_pts_iut_command.py         # Task 12 CLI tests
└── test_pics_gen_command.py        # Task 14 CLI tests

docs/
├── PTS_RUNBOOK.md                  # Operator manual (Task 15)
├── pts/
│   ├── pics/
│   │   ├── .gitkeep
│   │   ├── hci.draft.yaml          # Generated (Task 14)
│   │   ├── l2cap.draft.yaml
│   │   ├── gap.draft.yaml
│   │   ├── gatt.draft.yaml
│   │   ├── smp.draft.yaml
│   │   ├── sdp.draft.yaml
│   │   └── rfcomm.draft.yaml
│   ├── ixit/
│   │   ├── .gitkeep
│   │   └── template.md             # IXIT template (Task 14)
│   └── results/
│       ├── .gitkeep
│       └── template.md             # Results recording template (Task 15)
└── superpowers/STATUS.md           # Updated with v1.2 entry (Task 15)
```

---

## Key Code Patterns

### Pairing Request/Response body structure (6 bytes)

```
Byte 0: IO Capability
Byte 1: OOB data flag
Byte 2: Auth Req (bits: Bonding=0-1, MITM=2, SC=3, Keypress=4)
Byte 3: Maximum Encryption Key Size
Byte 4: Initiator Key Distribution
Byte 5: Responder Key Distribution
```

### SC-only enforcement (Task 2)

When `security.sc_only_mode=True`:
1. On receiving peer's Pairing Request: check bit 3 of auth_req; if 0 → send Pairing Failed (0x03 = auth requirements)
2. On sending our Pairing Request: set bit 3 of auth_req; on peer response, same check

### SMP failure injection (Task 4)

Valid stages (with hook points):
- `pairing_request` — fail right after Pairing Request exchange
- `pairing_response` — fail right after Pairing Response
- `confirm_value` — fail during MConfirm/SConfirm phase
- `random_value` — fail during Random exchange
- `key_distribution` — fail during key distribution

Reason format: `<reason_hex>:<stage>` (e.g., `05:confirm_value`) or just `<stage>` (defaults to reason 0x08)

---

## Testing Strategy

### Unit tests (CI-friendly)
- PTS flags: loopback SMP flows with virtual Stack.virtual()
- Action layer: spy on Stack method calls, verify state mutations
- REPL parser: pure function tests
- PICS generator: fixture-based (capability JSON → draft YAML)

### Virtual e2e tests (no hardware needed)
- Advertise → Connect → Pair (with pts.secure_pair_only) → GATT read/write
- Verify pts=None retains v1.0 behavior (SMP regression)

### Manual PTS runs (hardware required)
- Operator uses `pybluehost app pts-iut -t usb --pts-secure-pair-only`
- Results recorded in `docs/pts/results/<date>-<group>.md`
- Phase 1 goal: "run complete group + record + fix bugs" (no ≥90% mandate)

---

## Next Steps

1. **Complete Tasks 2-5** — finish PTS flag wiring in Stack._build + SMP
2. **Implement Tasks 6-10** — build IutActions action layer
3. **Implement Tasks 11-12** — add REPL + CLI integration
4. **Implement Tasks 13-14** — PICS generator + scaffolding
5. **Task 15** — runbook + initial drafts
6. **Regression testing** — ensure pts=None has zero impact
7. **Create PR** — target master for Phase 1 delivery

---

## Resources

- **PRD:** `docs/PRD-v1.2.md`
- **Design Spec:** `docs/superpowers/specs/2026-05-29-prd-v1.2-pts-iut-design.md`
- **Detailed Plan:** `docs/superpowers/plans/2026-05-31-v1.2-pts-iut-phase1.md`
- **Bluetooth Core Spec:** Vol 3, Part H (HCI), Vol 3, Part H (LE Security)
