# Hardware E2E Verification

Manual smoke-testing of the PyBlueHost e2e suite against real BR/EDR + LE
USB adapters. Hardware verification runs **outside** CI and is performed
before each release.

> **Windows 用户**：本文档假设 Linux 主机（`lsusb`、`udev` 规则）。Windows 上做 survey 请参考 [`HARDWARE_SURVEY_WINDOWS.md`](HARDWARE_SURVEY_WINDOWS.md)——驱动绑定（Zadig 换 WinUSB）、PowerShell 等价命令、Windows-specific 常见坑都在那里。

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
   Confirm both show `yes` for `le_secure_connections` and `bredr_ssp` in
   the capability summary.
3. Run the e2e suite peer-to-peer:
   ```
   uv run pytest tests/e2e/ -v \
       --transport=usb:vendor=intel#1 \
       --transport-peer=usb:vendor=intel#2
   ```
   Expected: all e2e tests pass. Tests gated on capabilities the adapter
   lacks will `pytest.skip` with a clear reason.

## 2. Adapter compatibility matrix

| Adapter             | LE SC | BR/EDR SSP | BR/EDR SC | LE Audio | Notes                |
|---------------------|-------|------------|-----------|----------|----------------------|
| Intel BE200         | TBD   | TBD        | TBD       | TBD      | _Verified on hardware: TBD_ |
| Intel AX210         | TBD   | TBD        | TBD       | TBD      | _Verified on hardware: TBD_ |
| Realtek RTL8761B    | TBD   | TBD        | TBD       | TBD      | Needs firmware blob  |
| CSR8510 A10         | -     | TBD        | -         | -        | BT 4.0; SC unavailable; tests gating on SC will skip |
| Broadcom BCM20702   | TBD   | TBD        | -         | -        | _Verified on hardware: TBD_ |

This matrix is a **template** — `TBD` cells are filled in as adapters are
surveyed. See §6 for the workflow to add a new adapter.

## 3. `info` CLI usage

**Default human-readable table** — five sections (adapter identity,
capability summary, LE features, BR/EDR features, supported HCI commands)
plus recommended pytest invocations:

```
$ uv run pybluehost tools info --transport=usb:vendor=intel
PyBlueHost Hardware Survey
==========================

Adapter identity
----------------
  Transport       : usb:vendor=intel
  BD_ADDR         : XX:XX:XX:XX:XX:XX
  Manufacturer    : Intel Corp. (0x0002)
  HCI Version     : ...
...
```

**`--json` for machine-readable** output:
```
uv run pybluehost tools info --transport=usb:vendor=intel --json > my-adapter.json
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

For LE E2E, the Peripheral is the GATT server. For Classic E2E, the
Peripheral is the SPP service + SDP record holder.

These roles aren't enforced by HCI — they're test-design choices. Swap
freely if you suspect adapter-asymmetry issues.

## 5. Common failure triage

| Symptom | Likely cause | Mitigation |
|---|---|---|
| Tests skip with "adapter does not support LE Secure Connections" | Adapter is BT 4.0 (CSR8510) | Use a BT 4.2+ adapter |
| Tests skip with "adapter does not support BR/EDR SSP" | Adapter has BR/EDR disabled in firmware | Check `tools info`; if SSP is `-`, no host-side fix |
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
3. Run the full e2e suite as central+peer against this adapter (paired
   with another known-good adapter, or two USB instances if you have two
   of the same):
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

These tests do NOT run in GitHub Actions. A self-hosted runner with
adapters is a future Plan (out of scope here). For now: run manually
before each release; capture `tools info` baselines for each adapter.
