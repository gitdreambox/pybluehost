# Hardware E2E Verification

Manual smoke-testing of the PyBlueHost e2e suite against real BR/EDR + LE
USB adapters. Hardware verification runs **outside** CI and is performed
before each release.

> **平台选择**：本文档是通用 runbook（默认 Linux 命令）。各平台的详细操作手册：
> - Linux（推荐，主开发平台）：[`HARDWARE_SURVEY_LINUX.md`](HARDWARE_SURVEY_LINUX.md)
> - Windows（需 Zadig 换 WinUSB 驱动）：[`HARDWARE_SURVEY_WINDOWS.md`](HARDWARE_SURVEY_WINDOWS.md)
> - macOS（实验状态，IOBluetooth 抢占问题较难解）：[`HARDWARE_SURVEY_MACOS.md`](HARDWARE_SURVEY_MACOS.md)

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

### 3.1 How `capability_summary` is computed

`capability_summary` is a small set of derived **bool** flags answering "can
this adapter do X?" by combining bits from the three raw bitmaps the
controller returns:

- **LE Features bitmap** (8 bytes from `HCI_LE_Read_Local_Supported_Features`,
  Core Spec 5.4 Vol 6 Part B §4.6 Table 4.6.1). Surfaced in JSON as `le_features`.
- **BR/EDR LMP Features page 0** (8 bytes from `HCI_Read_Local_Supported_Features`,
  Core Spec 5.4 Vol 2 Part C §3.3 Table 3.2). Surfaced as `bredr_features`.
- **HCI Supported_Commands bitmap** (64 bytes from `HCI_Read_Local_Supported_Commands`,
  Core Spec 5.4 Vol 4 Part E §6.27 Table 6.27). Surfaced under `supported_commands`.

Each summary row checks one or more (octet, bit) positions:

| Summary flag | Source | Position | Spec ref |
|---|---|---|---|
| `le_secure_connections` | Supported_Commands AND | (34, 1) **and** (34, 2) | Vol 4 Part E §6.27 — `HCI_LE_Read_Local_P-256_Public_Key` + `HCI_LE_Generate_DHKey` |
| `le_privacy_rpa` | LE Features | (0, 6) | Vol 6 Part B §4.6 "LL Privacy" |
| `le_extended_advertising` | LE Features | (1, 4) | Vol 6 Part B §4.6 "LE Extended Advertising" |
| `le_2m_phy` | LE Features | (1, 0) | Vol 6 Part B §4.6 "LE 2M PHY" |
| `le_coded_phy` | LE Features | (1, 3) | Vol 6 Part B §4.6 "LE Coded PHY" |
| `bredr_encryption` | BR/EDR Features | (0, 2) | Vol 2 Part C §3.3 "Encryption" |
| `bredr_ssp` | Supported_Commands | cmd (32, 5) | Vol 4 Part E §6.27 `HCI_IO_Capability_Request_Reply` (matches `tests/e2e/_helpers.py:_supports_classic_ssp`) |
| `extended_inquiry_response` | BR/EDR Features | (6, 0) | Vol 2 Part C §3.3 "Extended Inquiry Response" |

**Why some checks combine multiple bits**:
- `le_secure_connections` needs both P-256 and DHKey — host-side SC implementation requires both controller primitives to be exposed via HCI.

**Why some checks DON'T combine bits even though the spec offers both**:
- `bredr_ssp` only checks the HCI command bit, not the LMP page-0 feature bit. The Classic e2e test gate `_supports_classic_ssp` uses the same single-bit definition; reporting differently here would create confusion when the matrix says ✓ but tests skip (or vice versa). If you need to know whether the LMP feature bit is set independently, read `bredr_features["6/3"].supported` directly from the JSON.

**What `capability_summary` deliberately does NOT include**:
- **LE Audio host support** — this is set BY the host via `HCI_LE_Set_Host_Feature` bit 32, not read from the controller. Reporting it from these bitmaps would be misleading.
- **BR/EDR Secure Connections (controller)** — sits on LMP page 2, which PyBlueHost doesn't currently fetch (only page 0). Would need a separate `HCI_Read_Local_Extended_Features` round-trip.
- **LE Audio CIS/BIS** — there are LE Feature bits and HCI commands for these, but they require multi-bit combinations and are out-of-scope for the current capability gate.

If you need a raw bit not in the summary, read it from `le_features` /
`bredr_features` / `supported_commands.decoded` in the JSON — every named
feature bit is decoded there with its `(octet, bit)` key.

### 3.2 What to do when `capability_summary` reports `-`

For each row that's `-` (no support), the affected test scenarios will
`pytest.skip` with a clear reason. Examples:

| Flag = `-` | Affected tests skip with |
|---|---|
| `le_secure_connections` | "adapter does not support LE Secure Connections" — LE pairing/encryption tests |
| `bredr_ssp` | "adapter does not support BR/EDR SSP" — Classic pairing/encryption tests |
| `bredr_encryption` | All BR/EDR encryption-dependent tests skip implicitly via SSP gate |

A `-` in the matrix doesn't always mean "the adapter is broken" — it can
mean the standard predates the feature (CSR8510 is BT 4.0, predates LE SC).
The skip reason will tell you which.

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
