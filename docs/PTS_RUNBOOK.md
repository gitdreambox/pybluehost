# PyBlueHost PTS IUT — Operator Runbook (Phase 1, manual)

## Prerequisites

1. Windows host with **Bluetooth SIG PTS** (Profile Tuning Suite) installed.
2. PTS dongle attached + SIG license.
3. PyBlueHost installed in a venv on the same host (or reachable USB transport).
4. PyBlueHost capability dump for your hardware (`pybluehost tools info > hw.json`).

## One-time setup

```bash
# Generate PICS drafts from the captured capability dump
uv run pybluehost tools pics-gen -c hw.json -o docs/pts/pics/

# Hand-edit each docs/pts/pics/<group>.draft.yaml to remove PTS-internal items
# the predicate has no opinion on, and to correct any false positives.
```

Fill in `docs/pts/ixit/*.md` from `docs/pts/ixit/template.md` — substitute your IUT's Bluetooth address, roles, and any test-group-specific parameters PTS asks for.

In PTS UI, import the PICS values (manual click-through against the edited yaml drafts) and set IXIT params.

## Running a test group

For each target group (HCI / L2CAP / GAP / GATT / SMP / Classic-SDP / Classic-RFCOMM):

1. **Start the IUT REPL** with the PTS-mode flags appropriate for the test case:
   ```bash
   uv run pybluehost app pts-iut -t usb \
       --pts-secure-pair-only \
       --pts-disable-conn-updates
   ```
2. In PTS UI, select the test case and click **Start**.
3. When PTS shows an MMI prompt ("Please make the IUT do X"), use the REPL to execute the action. Common mappings:
   - "Initiate scanning" → `scan`
   - "Initiate connection to PTS" → `connect AA:BB:CC:DD:EE:FF`
   - "Initiate pairing" → `pair`
   - "Write characteristic" → `write 0x0023 010203`
4. Watch for the PTS verdict (PASS / FAIL / INCONC).
5. Record the result in `docs/pts/results/<YYYY-MM-DD>-<group>.md` (see template).

If PTS exposes a stack bug, file it as a Plan-tracked issue and (after fix) re-run the failing case.

## Specific PTS-mode flag recipes

- **SMP test cases that need Pairing Failed at confirm stage**:
  `--pts-smp-failure-at=confirm_value`
- **SMP test cases that need a specific Pairing Request body**:
  `--pts-smp-options=04000D100303` (hex 6 bytes)
- **GAP test cases that get tripped up by auto conn-param-update**:
  `--pts-disable-conn-updates` (defensive — no auto-sender exists today, but the flag is honored)

## NOT covered by this runbook

- BTP / auto-pts automation (Phase 2 — separate spec when launched)
- BLE profile groups (HRP/HOGP/...)
- Classic audio profile groups (will be added after v2.0 Classic Audio)
- LE Audio / Mesh
