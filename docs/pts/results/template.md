# PTS Test Result — <group> — <YYYY-MM-DD>

**Operator:** <name>
**Hardware:** Intel BE200 (or other)
**PyBlueHost commit:** <git sha>
**PTS version:** <SIG-PTS-version>
**Flags used:** `--pts-secure-pair-only`, etc.

## Test cases run

| Test Case | PTS Verdict | Notes / Bug ref |
|---|---|---|
| GAP/CENTRAL/CONN/BV-01 | PASS | |
| GAP/CENTRAL/CONN/BV-02 | FAIL | stack returns wrong response in <X>; bug #N filed |
| ... | ... | ... |

**Pass rate:** N/M (X%).

## Bugs exposed

- #N: <short description> — <fixed in commit / open>

## Re-run targets (next session)

- Re-run the FAIL cases after bug #N is fixed.
