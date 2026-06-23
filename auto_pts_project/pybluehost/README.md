# PyBlueHost auto-pts project module

This directory glues PyBlueHost into [`autoptsclient`](https://github.com/auto-pts/auto-pts)
as a Bluetooth SIG Profile Tuning Suite (PTS) Implementation Under Test (IUT).

After setup, `autoptsclient` drives PyBlueHost programmatically through the
BTP wire protocol (P.5–P.8), replacing the manual REPL workflow from
Phase 1 (`pybluehost app pts-iut`).

---

## Architecture

```
                ┌──────────────────────────────┐
   Windows ────►│ PTS.exe + dongle             │
                │   ▲                          │
                │   │ PTSControl COM           │
                │   ▼                          │
                │ autoptsserver  (XML-RPC)     │
                └──────────┬───────────────────┘
                           │ XML-RPC
                           ▼
   IUT host ────┐  autoptsclient
                │   ├── projects/pybluehost/    ◄── this package
                │   │     iutctl.py             ── spawns pts-tester subprocess
                │   │     pics.py               ── per-group PICS_<GROUP> dicts
                │   │     ixit.py               ── IXIT_<GROUP> param dicts
                │   │     wid/{gap,gatt,l2cap,sm}.py ── WID handler adapters
                │   └── wid/{gap,gatt,l2cap,sm}.py    (upstream — reused)
                │                  │
                │                  │ BTP (TCP 127.0.0.1:65103)
                │                  ▼
                │   pybluehost app pts-tester  ── this process is the IUT
                │                  │
                │                  ▼
                │   PyBlueHost stack            ── advertises / scans /
                └─────────────────────────────────  pairs / etc. via BTP.
```

`autoptsserver` runs on the Windows machine alongside PTS.exe (provides the
PTSControl COM wrapper). `autoptsclient` and PyBlueHost can run anywhere
they can both reach the Windows server over XML-RPC; running both on the
same Linux host is the simplest setup.

---

## Files

| File | Purpose |
|---|---|
| `__init__.py` | Package marker; exposes `PROJECT_NAME = "pybluehost"` |
| `iutctl.py` | `iut_init()` spawns `pybluehost app pts-tester` + waits for BTP READY; `iut_cleanup()` tears it down. |
| `pics.py` | `PICS_GAP / PICS_GATT / PICS_L2CAP / PICS_SMP / PICS_HCI / PICS_SDP / PICS_RFCOMM` — flat `dict[FEATURE_ID, bool]` loaded from `docs/pts/pics/*.draft.yaml`. |
| `ixit.py` | `IXIT_<GROUP>` flat string dicts. **Customise `TSPX_bd_addr_iut` before runs.** |
| `wid/*.py` | WID handler adapters — inherit upstream dispatch, override locally as needed. Baseline P.9 v1: no overrides. |

---

## Quick start (no PTS hardware — sanity only)

```bash
# 1. Install PyBlueHost + autoptsclient
pip install -e .          # PyBlueHost dev install
pip install autopts       # if available on PyPI; otherwise checkout + pip install -e

# 2. Smoke check: PyBlueHost spawns the BTP tester on virtual transport
uv run python -c "
import asyncio
from auto_pts_project.pybluehost import iutctl

async def main():
    ctx = {'listen': '127.0.0.1:65103', 'transport': 'virtual'}
    await iutctl.iut_init(ctx)
    await asyncio.sleep(0.5)
    await iutctl.iut_cleanup(ctx)
    print('iut_init/iut_cleanup OK')

asyncio.run(main())
"
```

If `iut_init/iut_cleanup OK` prints, the project module is wired up.

---

## Real-hardware run

### Prerequisites

- Windows machine with [PTS](https://www.bluetooth.com/develop-with-bluetooth/test-tools/pts/) installed + the PTS USB dongle.
- `autoptsserver` running on the Windows machine (see auto-pts upstream README).
- PyBlueHost host (Linux/macOS/Windows) with a Bluetooth USB adapter attached.
- `pybluehost tools info -t usb` reports the adapter's `bd_addr`.

### Step 1: Regenerate PICS for your adapter

The committed PICS drafts are for `intel-BE200`. Regenerate for your adapter:

```bash
# Generate a capability dump first
pybluehost tools info -t usb --json > docs/hardware/my-adapter.json

# Re-generate the PICS drafts
pybluehost tools pics-gen -c docs/hardware/my-adapter.json -o docs/pts/pics
```

The drafts at `docs/pts/pics/*.draft.yaml` are now feature-accurate for your
adapter. `pics.py` picks them up automatically.

### Step 2: Customise IXIT

Edit `auto_pts_project/pybluehost/ixit.py` and set
`TSPX_bd_addr_iut` (all four groups) to your adapter's BD address —
**uppercase hex, no separators**, e.g. `AC1F09FFEE12`.

### Step 3: Run autoptsclient

From the autoptsclient checkout:

```bash
autoptsclient \
  --project pybluehost \
  --project-path /path/to/pybluehost/auto_pts_project \
  --server <windows-host>:65000 \
  --workspace /path/to/PTS-workspace \
  --test-cases GAP/CONN/CPUP/BV-01-C    # or a list
```

The client:
1. Imports `auto_pts_project.pybluehost`
2. Calls `iutctl.iut_init({'transport': 'usb', 'listen': '127.0.0.1:65103'})`
3. Pulls `PICS_GAP / PICS_GATT / ...` and `IXIT_GAP / ...`
4. Issues `autoptsserver.RunTestCase(...)` for each requested test case
5. Bridges PTS's MMI prompts via `wid/*` handlers → BTP commands → PyBlueHost
6. Records pass/fail per case
7. Calls `iutctl.iut_cleanup(ctx)`

Results land in autoptsclient's log directory (run with `--log-dir` to control).

---

## Customising WID handlers

If a specific WID needs PyBlueHost-specific logic (rare — baseline reuses upstream):

```python
# auto_pts_project/pybluehost/wid/gap.py

def _wid_42_pybluehost_specific(desc, *args, **kwargs):
    """PyBlueHost-specific handler for WID 42."""
    # ... BTP command sequence ...
    return True

gap_wid_hdl[42] = _wid_42_pybluehost_specific
PYBLUEHOST_OVERRIDES.append(42)
```

Then commit + regression-test against the affected PTS test case.

---

## Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `iut_init` times out at 30 s | `pybluehost app pts-tester` failed to start. Check stdout/stderr of the subprocess (currently piped — surface them by running pts-tester manually with the same args). |
| `ModuleNotFoundError: wid.gap` in PyBlueHost unit tests | Expected — autoptsclient isn't installed in PyBlueHost's CI. WID adapters fall back gracefully. |
| autoptsclient says "PICS empty" | Your `docs/pts/pics/*.draft.yaml` files are missing or empty. Regenerate with `pybluehost tools pics-gen -c <adapter>.json`. |
| Test case fails with "TSPX_bd_addr_iut mismatch" | You didn't customise `ixit.py` for your adapter. Use `pybluehost tools info -t usb --json` to find the BD address. |
| BTP READY event not received | PyBlueHost stack failed to initialise — likely missing transport. Try `pybluehost app pts-tester -t usb --listen=127.0.0.1:65103` manually. |

---

## Out of scope (P.9 v1)

- Classic SDP / RFCOMM BTP services (PRD §5.4: deferred forever; Classic test groups stay in Phase 1 REPL).
- Mesh / LE Audio test groups.
- Reconfigurable LE CoC channels (ECFC) — `LECoCService` v1 is single-channel.
- WID overrides — start with upstream defaults; add overrides only as PTS exposes mismatches.

## Maintenance

- `pics.py` is committed reading from `docs/pts/pics/`. To support a new adapter without rewriting code, just regenerate the drafts.
- `ixit.py` is hand-edited per IUT setup.
- `wid/*.py` overrides are minimal and tracked via `PYBLUEHOST_OVERRIDES` lists for easy audit.
- `iutctl.py` spawns a fresh `pts-tester` per test session — no shared state across sessions.
