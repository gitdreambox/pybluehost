# PRD v1.2 Implementation Handoff

## Current Status (Session End)

**Completed:**
- ✅ Task 1: PTSModeConfig + StackConfig.pts integration (committed)
- ✅ Partial Task 2: sc_only_mode field activated in SecurityConfig

**In Progress:**
- 🔄 Task 2: Wire pts.secure_pair_only → security.sc_only_mode + SMP SC-only enforcement

**Not Yet Started:**
- ⏳ Tasks 3-15

## Session Work Summary

### Commits Made
1. `36dedb0` — feat(pts): add PTSModeConfig + StackConfig.pts (default None, zero impact)
2. `f740cf1` — feat(pts): activate sc_only_mode field in SecurityConfig
3. `303a1b3` — docs: add v1.2 PTS IUT implementation guide

### Branch
- Working on: `claude/elastic-aryabhata-eace93`
- PRD reference: `docs/PRD-v1.2.md` + `docs/superpowers/specs/2026-05-29-prd-v1.2-pts-iut-design.md`

### Files Created
- `pybluehost/pts/__init__.py` — module exports
- `pybluehost/pts/config.py` — PTSModeConfig dataclass
- `tests/unit/pts/__init__.py` — test module marker
- `tests/unit/pts/test_config.py` — Task 1 tests (3 passing)
- `docs/superpowers/IMPLEMENTATION_GUIDE.md` — high-level roadmap

### Files Modified
- `pybluehost/stack.py` — added `pts: PTSModeConfig | None = None` field
- `pybluehost/ble/security.py` — uncommented `sc_only_mode` + updated `_validate_sc_dependencies`

---

## Next Session Quickstart

### 1. Resume from Current Branch
```bash
cd H:\github\bluetooth\pybluehost\.claude\worktrees\elastic-aryabhata-eace93
git log --oneline -5  # Verify commits are there
```

### 2. Complete Task 2 (SC-only enforcement)
- Find `Stack._build` method in `pybluehost/stack.py`
- Add PTS-mode propagation block at top of method:
  ```python
  # PTS mode propagation (design spec §3)
  if config.pts is not None and config.pts.secure_pair_only:
      config.security.sc_only_mode = True
      config.security.enable_secure_connections = True
  # Validate combined security config
  from pybluehost.ble.security import _validate_sc_dependencies
  _validate_sc_dependencies(config.security)
  ```

- In `pybluehost/ble/smp.py`, find Pairing Request/Response handling
- Add SC-only enforcement: when `self._security.sc_only_mode=True`, check peer's SC bit (bit 3 of auth_req)
- If peer lacks SC: send `SMPPairingFailed` with reason 0x03
- Create comprehensive tests in `tests/unit/pts/test_secure_pair_only.py` (loopback SMP with virtual stacks)

### 3. Complete Tasks 3-5 (SMP hooks)
See `docs/superpowers/plans/2026-05-31-v1.2-pts-iut-phase1.md` §§Task 3-5 for exact test specs and implementation guidance

Tasks 3-5 follow same pattern:
- Add validation at Stack._build
- Add hook in SMP code
- Write comprehensive unit tests with virtual loopback

### 4. Implement Tasks 6-10 (IutActions)
- Create `pybluehost/pts/actions.py` with:
  - `ConnInfo` dataclass (handle, peer, transport, gatt_client)
  - `IutSession` dataclass (connections dict, last_handle, IO capabilities)
  - `IutActions` class with 13 primitives (advertise, scan, connect, disconnect, pair, encrypt, notify, indicate, read, write, sdp_browse, rfcomm_open, l2cap_connect)
  - Connection event handler for incoming connections

- Each primitive maps 1:1 to Stack API:
  - advertise → `stack.gap.ble_advertiser.start()`
  - connect (LE) → `stack.connect_gatt()` + store GATTClient
  - connect (Classic) → `stack.connect_classic()`
  - pair → `stack.pair(handle)` with optional io_cap mutation
  - notify → `stack.gatt_server.notify()`
  - read → `conn.gatt_client.read_characteristic()`
  - sdp_browse → `stack.sdp.search()`
  - etc.

- Handle-elision: when `handle=None`, use `session.last_handle`
- Error handling: raise descriptive ValueError (REPL catches + prints + continues)

### 5. Implement Tasks 11-12 (REPL)
- `pybluehost/pts/repl.py`:
  - `parse_repl_command(line) → (cmd, args)` pure parser using shlex
  - `run_repl(actions) → async` loop using `run_in_executor` for stdin
  - `_dispatch(actions, cmd, args) → async` handler for each command

- `pybluehost/cli/app/pts_iut.py`:
  - `register_pts_iut_command(subparsers)` — register `pts-iut` subcommand
  - Add 5 `--pts-*` CLI flags (disable_conn_updates, secure_pair_only, etc.)
  - `_pts_config_from_args(args) → PTSModeConfig | None`
  - `_pts_iut_main(stack, stop_event) → async` entry point

- Wire into CLI: modify `pybluehost/cli/app/__init__.py` to call `register_pts_iut_command`

### 6. Implement Tasks 13-14 (PICS)
- `pybluehost/pts/pics_gen.py`:
  - `generate_pics_draft(capabilities) → dict[group, dict[feature, {supported, evidence}]]`
  - Hardcode rules mapping PyBlueHost capabilities to PTS PICS items
  - Output format: YAML-friendly dict per group (HCI, L2CAP, GAP, GATT, SMP, SDP, RFCOMM)

- `pybluehost/cli/tools/pics_gen.py`:
  - `register_pics_gen_command(subparsers)` — register `tools pics-gen` subcommand
  - `_run(args) → int` — read JSON capability, call generator, write YAML drafts

### 7. Task 15 (Framework)
- Generate initial PICS drafts from hardware fixtures
- Create `docs/PTS_RUNBOOK.md` — operator manual for manual PTS runs
- Create `docs/pts/results/template.md` — result recording template
- Create `docs/pts/ixit/template.md` — IXIT parameter template
- Scaffold `docs/pts/{pics,ixit,results}/` directories with .gitkeep

---

## Testing Checklist

Before merging each task:

- [ ] Unit tests pass: `uv run pytest tests/unit/pts/` (or relevant subset)
- [ ] No SMP regression: `uv run pytest tests/unit/ble/ -q` (zero-impact when pts=None)
- [ ] CLI sanity: `uv run pybluehost app pts-iut --help` (or tools pics-gen)
- [ ] Manual smoke test (if applicable): `uv run pybluehost app pts-iut -t virtual` → type `help`, `quit`

---

## References for Implementation

- **Design Spec:** `docs/superpowers/specs/2026-05-29-prd-v1.2-pts-iut-design.md`
  - §1: Stack API contact points (with real method names, line numbers)
  - §3: PTS mode flags detailed spec
  - §4: IutActions signatures + ConnInfo/IutSession shapes
  - §5: REPL command grammar
  - §6: PICS generator rules

- **Detailed Plan:** `docs/superpowers/plans/2026-05-31-v1.2-pts-iut-phase1.md`
  - Each task (1-15) has step-by-step TDD instructions
  - Includes failing test code, implementation skeleton, commit messages

- **Bluetooth Core Spec Vol 3 Part H:**
  - SMP Pairing Request/Response body layout (6 bytes)
  - Auth Req bit assignments (MITM, SC, Bonding, Keypress)
  - SMP error codes (Pairing Failed reason bytes)

---

## Known Issues / Edge Cases

1. **SMP SC-only enforcement:**
   - Must enforce on both outgoing (we initiate pair) and incoming (peer initiates) paths
   - Reject peer if their auth_req lacks SC bit (bit 3)
   - Test with virtual loopback: IUT(sc_only=True) vs Peer(sc=False) → Pairing Failed

2. **Handle elision (IutActions):**
   - `disconnect()` without handle uses `last_handle`
   - Error if no `last_handle` → "no active connection; specify <handle>"
   - Update `last_handle` on every connect/pair/incoming-connection

3. **GATT client vs server:**
   - read/write require central role (has GATTClient from connect_gatt)
   - notify/indicate use server (stack.gatt_server)
   - Error if trying to read on peripheral incoming connection

4. **PICS generation:**
   - Only reads existing capability dump (tools info JSON)
   - Generates human-readable drafts, **not** PTS proprietary .project files
   - Operator must manually import into PTS UI

5. **Zero-impact constraint:**
   - When `StackConfig.pts=None` (default), **all** PTS hooks must short-circuit
   - Regression test: run v1.0 SMP test suite with pts=None, must pass 100%

---

## Architecture Decision Checklist

Verify these before committing:

- [ ] **Pure action layer:** IutActions has zero REPL/BTP coupling
- [ ] **Config-only changes:** PTS flags don't require Stack subclass or method override
- [ ] **Build-time wiring:** pts.secure_pair_only → security.sc_only_mode at Stack._build
- [ ] **Short-circuit on None:** All hook code checks `if self._stack.config.pts is None: return`
- [ ] **Session state:** ConnInfo + IutSession track connections + last_handle across REPL commands
- [ ] **Handle elision:** All IutActions methods accept optional `handle=None`, use `last_handle` fallback
- [ ] **No form-fitting:** REPL grammar is simple (cmd + positional + --key=value), not argparse subparsers

---

## Estimated Remaining Work

- **Tasks 2-5** (complete PTS flags): ~2-3 hours (SMP hooks + tests)
- **Tasks 6-10** (IutActions): ~4-5 hours (13 primitives + session tracking)
- **Tasks 11-12** (REPL + CLI): ~2 hours (parser + loop + registration)
- **Tasks 13-14** (PICS + scaffolding): ~1-2 hours (rules + generator + CLI)
- **Task 15** (Framework + runbook): ~1 hour (docs + templates)
- **Final regression + PR**: ~1 hour

**Total: ~11-15 hours of implementation + testing**

---

## Questions for Next Session

1. Should PTS flags also apply to Classic (BR/EDR) SMP, or LE-only for Phase 1?
   - Current design is LE-centric; Classic SDP/RFCOMM reserved for REPL manual mode (Phase 2 BTP doesn't cover them)

2. When `disable_sdp_on_le_pair=True`, should we also skip CTKD-classic derivation?
   - Per design spec §5 comment, yes: "LE pair completion does not auto-trigger SDP/CTKD-classic"

3. For PICS generation, should we hardcode ALL PTS PICS items or just the minimal subset?
   - Minimal subset sufficient for Phase 1 (7 target groups); extensible pattern for future

4. Should REPL support hexadecimal input for all numeric parameters?
   - Yes: `0x0023` (hex) or `35` (decimal) both valid; use `int(x, 0)` to auto-detect

---

## Key Contacts / Context

- **PRD Approved:** 2026-05-29 (brainstorm confirmed)
- **Design Spec Draft:** 2026-05-31 (waiting for plan review)
- **Phase 1 Delivery Target:** v1.2 release
- **Phase 2 (BTP/auto-pts):** Separate brainstorm + plan after Phase 1 complete

---

**Generated:** End of implementation session
**Next action:** Resume with Task 2 completion or delegate to parallel implementers
