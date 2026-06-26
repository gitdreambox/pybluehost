# Two-Device Throughput Baseline — Operator Runbook

> Measures **real RF throughput** between two PyBlueHost adapters at each
> PHY (BLE 1M / 2M) and EDR rate (Classic 2-DH / 3-DH), in both directions.
> Numbers go into the hardware matrix at
> [`docs/hardware/throughput-baseline.md`](hardware/throughput-baseline.md)
> so future adapter survey work has a baseline to compare against.
>
> The PHY-control and packet-type-control APIs themselves are covered by
> in-process unit tests (33 tests across `tests/unit/hci/test_le_set_phy.py`,
> `tests/unit/ble/test_set_phy.py`,
> `tests/unit/hci/test_change_connection_packet_type.py`,
> `tests/unit/classic/test_set_acl_packet_types.py`). What's below is the
> part that only real silicon can validate — actual bytes/sec across the air.

Test file: [`tests/hardware/test_throughput_real.py`](../tests/hardware/test_throughput_real.py)

---

## Prerequisites

- Two real Bluetooth USB adapters that PyBlueHost supports (Intel AX200/AX210,
  Realtek 8761, CSR8510, etc. — see [`README.md`](../README.md) §已测试硬件).
- **Both adapters must support BT 5.0+** if you want LE 2M numbers. BT 4.x
  adapters silently negotiate back to LE 1M and the test will skip the 2M cells.
- **Both adapters must support EDR** for 2-DH / 3-DH. All adapters in the
  test matrix do, but verify with `pybluehost tools info -t usb`.
- A quiet 2.4 GHz environment helps reproducibility. Crowded WiFi pollutes
  EDR throughput numbers more than LE.
- Both adapters plugged into the same host (so `--transport-peer=usb:...`
  works without a network bridge).

Tag the adapters physically so you remember which is which between runs;
the test reports the central adapter first.

---

## Running the test

```bash
uv run pytest tests/hardware/test_throughput_real.py \
    --transport=usb:8087:0033#0 \
    --transport-peer=usb:8087:0033#1 \
    -v -s --junit-xml=throughput.xml
```

Adjust the `VID:PID#index` selectors to match `lsusb` / `pybluehost tools usb`.

Expected runtime: ~80 s (8 cells × ~10 s including connect/setup/teardown).

The `-s` flag is important — without it pytest swallows the `[THROUGHPUT]`
output lines and you only see the junit XML.

---

## Reading the output

Each cell prints one line like:

```
[THROUGHPUT] profile=ble rate=2M direction=uplink received=789120 bytes in 5.01s → 1.26 Mbps
```

…and writes the same number into the junit XML as
`throughput_<profile>_<rate>_<direction>_mbps`.

For LE CoC, the **theoretical maximum** is ~ (PHY rate / 2) minus protocol
overhead — a healthy LE 2M link usually lands 1.2–1.6 Mbps after L2CAP
credit-based framing and ACL packet headers eat the rest. LE 1M tops out
around 700–800 kbps.

For SPP / RFCOMM:
- 2-DH max effective payload rate ≈ 1.4–1.6 Mbps
- 3-DH max effective payload rate ≈ 2.0–2.3 Mbps

If your numbers are dramatically lower (under 50% of these envelopes),
suspect:

| Symptom | Likely cause |
|---|---|
| LE 2M numbers ≈ LE 1M numbers | Adapter or peer didn't actually switch — check pytest log for "Adapter or peer negotiated PHY tx=..." skip |
| Both LE rates < 200 kbps | LE CoC credits exhausted, or peer's `on_data` handler is slow. Bump `initial_credits=200` in the test if you tune. |
| 3-DH numbers ≈ 2-DH numbers | Adapter or peer doesn't actually advertise 3-Mbps EDR. Check `pybluehost tools info -t usb --json` |
| SPP rates < 500 kbps | RFCOMM frame-size negotiation may have capped at 127 bytes; check link-layer trace |
| Test skips with "set_phy returned status 0x1F" | Peer adapter doesn't support the PHY change at all (likely BT 4.0). Note it in the matrix and move on. |

---

## Recording into the hardware matrix

After a clean run, append a row to
[`docs/hardware/throughput-baseline.md`](hardware/throughput-baseline.md) (create
it if it doesn't exist yet). Format:

```markdown
## <adapter-A model> ↔ <adapter-B model> — <YYYY-MM-DD>

Adapter A (central): <VID:PID> / firmware <version> / kernel <ver>
Adapter B (peer):    <VID:PID> / firmware <version>

| profile | rate | uplink (Mbps) | downlink (Mbps) | notes |
|---|---|---|---|---|
| BLE     | 1M   | 0.68 | 0.71 | |
| BLE     | 2M   | 1.32 | 1.35 | |
| SPP     | 2-DH | 1.45 | 1.41 | |
| SPP     | 3-DH | 2.11 | 2.04 | |
```

If a cell skipped, write the skip reason in the `notes` column rather than
leaving the row blank — future operators benefit from "Intel AX200 rejects
LE 2M when peer is Realtek 8761" findings just as much as raw numbers.

---

## Troubleshooting / known gotchas

### "Adapter rejected packet-type change: status 0x1F"

The controller refused the requested EDR mask. Two common causes:

1. The peer doesn't advertise support for that EDR rate in its LMP features
   — verify with `pybluehost tools info -t usb --json` (look at `features`).
2. The adapter has a vendor-specific quirk on `Change_Connection_Packet_Type`
   — log it in the adapter matrix and skip that rate cell.

### "set_phy returned status 0x1F" / wrong PHY negotiated

LE_PHY_Update_Complete reports a non-zero status, OR comes back with the
old PHY in tx/rx. The peer refused the change. Most common reason: peer
is BT 4.x and can't do LE 2M. The test skips automatically and reports
the actual negotiated PHY in the skip reason.

### Numbers drift between runs

LE / EDR throughput at the radio layer is sensitive to ambient 2.4 GHz
noise. Two runs 5 minutes apart with someone joining a WiFi call can vary
by 20%. Run the test 3 times and report the median, or pick a clean RF
environment (no 2.4 GHz WiFi, no microwave).

### "no LE CoC data received — link likely failed"

The pump completed but the receiver counter is still 0. Usually means the
LE CoC connect succeeded but the L2CAP credit grant from the peer never
arrived. Re-run with `--pybluehost-trace=l2cap=debug` to see the credit
exchange.
