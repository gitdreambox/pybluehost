# Virtual Sniffer — Manual Acceptance (Windows + Analyzer Software)

> The virtual sniffer injects PyBlueHost's **live HCI** (Command / Event / ACL /
> SCO) into the Ellisys Bluetooth Analyzer or Teledyne LeCroy WPS UI via their
> Remote / Live-Import APIs — no over-the-air capture hardware required.
>
> The pure-function encoding + transport layers are covered by CI unit tests
> (cross-platform). The steps below cover the parts that can only be validated
> on **Windows with the analyzer software installed**: actually seeing the
> injected frames appear in the analyzer UI.

Design spec: [`superpowers/specs/2026-05-29-prd-v1.1-virtual-sniffer-design.md`](superpowers/specs/2026-05-29-prd-v1.1-virtual-sniffer-design.md)
Plan: [`superpowers/plans/2026-05-31-v1.1-virtual-sniffer.md`](superpowers/plans/2026-05-31-v1.1-virtual-sniffer.md)

---

## Prerequisites

- Windows (the Ellisys / WPS analyzer software is Windows-only).
- A real Bluetooth adapter for `-t usb` (or any working transport).
- **Ellisys**: Ellisys Bluetooth Analyzer installed, with the Remote Control
  Plugin (`Ice.dll` + `EllisysAnalyzerBluetoothRemoteControlPlugin.dll` under
  the analyzer's `RemoteControl` folder) and the HCI Injection API enabled.
- **WPS**: Teledyne LeCroy Wireless Protocol Suite (4.60+) installed, with
  `LiveImportAPI.dll` available under the install dir.

PyBlueHost does **not** bundle vendor DLLs (licensing); they are located at
runtime from the install path you pass.

---

## 1. Ellisys — live HCI in "HCI Injection Overview"

```
pybluehost app ble-scan -t usb ^
    --virtual-sniffer=ellisys:ellisys-path="C:\ProgramData\Ellisys\Ellisys Bluetooth Analyzer\Updates\current"
```

Optional: override the default ports (`tcp=46148`, `udp=24352`):

```
... --virtual-sniffer=ellisys:ellisys-path=...,tcp=46148,udp=24352
```

**Expected:** the analyzer launches (if not already running), selects the
`injection` data source, starts recording, and HCI Command / Event / ACL frames
from the scan appear live in the "HCI Injection Overview".

---

## 2. WPS — live frames in Live Import

```
pybluehost app ble-scan -t usb ^
    --virtual-sniffer=wps:wps-path="C:\Program Files (x86)\Teledyne LeCroy Wireless\Wireless Protocol Suite 4.60"
```

**Expected:** the backend launches `Fts.exe` in Generic Live-Import mode, loads
`Executables\Core\LiveImportAPI_x64.dll`, reads the connection string from the
product `liveimport.ini [General]` + config from the dev-kit `[Configuration]`,
waits for `IsAppReady`, then starts capture. "frames analyzed" grows live as the
scan runs. **Note:** ISO frames are skipped on WPS (the default personality Drf
has no ISO) — a one-time warning is logged; this is expected.

---

## 3. Combined with btsnoop (independent sinks)

```
pybluehost app gatt-server -t usb --virtual-sniffer=ellisys:ellisys-path=... --btsnoop=scan.cfa
```

**Expected:** both work simultaneously — frames appear in the analyzer **and**
`scan.cfa` is a valid btsnoop file. The sinks are independent.

---

## 4. ACL traffic + long session (no dropped frames)

Run a longer GATT/SDP/A2DP session (e.g. `gatt-browser`, `sdp-browser`) and
visually compare the analyzer's frame counter against expectations.

**Expected:** ACL data frames (L2CAP/ATT traffic) are visible alongside
Command/Event, and high-frequency traffic injects without obvious frame loss.

---

## Notes / limitations

- Non-Windows: `--virtual-sniffer` raises a clear `SnifferUnavailableError`
  ("virtual sniffer requires Windows + Ellisys/WPS analyzer software").
- Bridge mode (`pybluehost app bridge`) does **not** support `--virtual-sniffer`
  (it is transport-layer; the sniffer filters hci-layer). Point the analyzer at
  the bridge's TCP/UDP port directly instead.
- Real SCO streams require the v2.0 audio path; v1.1 only validates SCO
  injection **encoding** (unit tests), not live SCO flow.
- Record the adapter, analyzer version, and observed result here when run:

| Date | Adapter | Backend | Analyzer version | Result |
|------|---------|---------|------------------|--------|
| 2026-06-09 | CSR8510 (0A12:0001) | ellisys | Ellisys Bluetooth Analyzer (ProgramData\Updates\current) | ✅ analyzer launched, Ice setup OK (SelectDataSource('injection') + StartRecording), full HCI init + LE scan + advertising reports injected over UDP, no errors |
| 2026-06-09 | CSR8510 (0A12:0001) | wps | Wireless Protocol Suite 4.60 | ✅ **HCI packets visible in the WPS UI.** Fts.exe launched, LiveImport init + IsAppReady + start capture, scan ran, frames injected via SendFrame3 |

> **Critical detail (found during hardware test):** `SendFrame3` takes 7 args
> with `iDatastreamId` first — `SendFrame3(iDatastreamId=0, iOriginalLength,
> iIncludedLength, pbytFrame, iDrf, iSide, i64Timestamp1ns)` (per
> `LiveImportAPI.h`). Omitting the leading datastream id makes the call "succeed"
> but render nothing. ISO frames are skipped on WPS (default personality Drf has
> no ISO) — a one-time warning is logged.

> The above runs validate the full pipeline up to and including injection with no
> errors. The final **visual** confirmation (frames rendered in the analyzer UI)
> is done by an operator watching the analyzer window during the run.
