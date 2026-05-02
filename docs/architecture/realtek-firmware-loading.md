# Realtek Bluetooth USB Firmware Loading

> Scope: Realtek USB Bluetooth controllers, especially RTL8852B/RTL8852BE
> devices such as `0bda:4853`.
> Primary reference: Linux `drivers/bluetooth/btrtl.c`.
> Secondary reference: Google Bumble `bumble/drivers/rtk.py`.
>
> Status on 2026-05-02: PyBlueHost follows Linux's stock-ROM tuple rule for
> RTL8852B (`0x8852/0x000b/0x0b`) and RTL8852C
> (`0x8852/0x000c/0x0c`). Linux maps USB PID `0bda:4853` to RTL8852BE, so
> that device must use `rtl8852bu_fw.bin`, not `rtl8852cu_fw.bin`.
> `RTBTCore` v2 parsing is implemented for the RTL8852C path, legacy
> `Realtech` parsing remains supported, and post-download validation uses
> `Read Local Version`. Unknown tuples are not treated as "must load"; Linux
> and Bumble both skip firmware when no known driver entry matches.

---

## Executive Summary

Linux `btrtl.c` is the best reference implementation. Bumble is useful as a
userspace reference, but it lags Linux for newer Realtek firmware details and
contains a fragment-index expression that does not match Linux behavior for
payloads larger than 128 fragments.

For PyBlueHost, the target implementation should follow Linux semantics:

1. Reset or otherwise bring the controller into a known state.
2. Read local version (`HCI_Read_Local_Version_Information`, opcode `0x1001`).
3. Match `(lmp_subver, hci_rev, hci_ver, bus)` to a Realtek driver entry.
4. Read ROM version with vendor command `0xFC6D` when the chip entry requires it.
5. Select firmware from the matched entry:
   - RTL8852B USB: `lmp_subver=0x8852`, `hci_rev=0x000b`, `hci_ver=0x0b`,
     `rtl8852bu_fw.bin`.
   - RTL8852C USB: `lmp_subver=0x8852`, `hci_rev=0x000c`, `hci_ver=0x0c`;
     prefer `rtl8852cu_fw_v2.bin`, then fall back to `rtl8852cu_fw.bin`.
6. Parse firmware:
   - `Realtech`: legacy epatch format.
   - `RTBTCore`: v2 section/subsection format.
7. Append config data only when applicable.
8. Download payload with vendor command `0xFC20` in 252-byte fragments.
9. After download, read local version to verify the loaded firmware.
10. Let the upper initialization flow continue with normal HCI setup; do not assume the final firmware fragment behaves like a normal reset event on every adapter.

PyBlueHost now implements items 2, 5, 6, and 9 for the RTL8852B/RTL8852C USB
paths covered by current hardware work. Full Linux chip-table coverage and
config parsing are still pending.

---

## Source Comparison

| Topic | Linux `btrtl.c` | Bumble `rtk.py` | PyBlueHost current state |
| --- | --- | --- | --- |
| Chip identification | Reads local version and matches table | Reads local version and matches table | Reads local version; only known stock tuples enter download path |
| RTL8852B firmware name | Uses `rtl8852bu_fw.bin` | Uses `rtl8852bu_fw.bin` | Uses `rtl8852bu_fw.bin` |
| RTL8852C firmware name | Tries `rtl8852cu_fw_v2.bin`, then `rtl8852cu_fw.bin` | Uses `rtl8852cu_fw.bin` only | Tries `rtl8852cu_fw_v2.bin`, then `rtl8852cu_fw.bin` |
| Legacy epatch signature | `Realtech` | `Realtech` | Implemented |
| V2 firmware signature | `RTBTCore` | Not implemented in observed version | Implemented for selected subsections; security headers require matching key id |
| Config file | Loads optional or mandatory config based on table and key id | Loads config when found; enforces mandatory configs | Not implemented for Realtek USB path |
| Fragment size | 252 bytes | 252 bytes | 252 bytes |
| Fragment index after `0x7f` | Wraps to `0x01` | Code intends to follow Linux, but expression does not actually do so | Implemented as Linux wrap after hardware debugging |
| Event receive path | Standard HCI events are expected on interrupt; some boot paths may need transport-specific handling | Uses the host transport event path | Realtek waits try Interrupt IN, Bulk IN, then Interrupt IN, and filters Command Complete by opcode |
| Post-download verification | Reads local version and logs firmware version | Reads ROM version, then `init_controller()` sends HCI Reset | Reads local version after download |
| Safety gate | Kernel driver owns the device and can recover through kernel reset paths | No separate gate | Firmware write requires a known stock local-version tuple |
| Drop firmware recovery | Uses vendor command `0xFC66` for unknown IC path | Mentions this as TODO | Not implemented |

References:

- Linux source: `drivers/bluetooth/btrtl.c` and `drivers/bluetooth/btusb.c`
  in the Linux kernel tree.
- Bumble source: `bumble/drivers/rtk.py` in Google Bumble.

---

## Firmware Selection

Linux first binds supported USB devices in `btusb.c`, then `btrtl.c` matches
Realtek controllers by controller-reported version fields. Current Linux
`btusb.c` lists `0bda:4853` under RTL8852BE, not RTL8852CE.

For RTL8852B USB the important Linux/Bumble entry is:

```text
lmp_subver = 0x8852
hci_rev    = 0x000b
hci_ver    = 0x0b
bus        = USB
fw_name    = rtl_bt/rtl8852bu_fw
cfg_name   = rtl_bt/rtl8852bu_config
```

For RTL8852C USB the important Linux/Bumble entry is:

```text
lmp_subver = 0x8852
hci_rev    = 0x000c
hci_ver    = 0x0c
bus        = USB
fw_name    = rtl_bt/rtl8852cu_fw
cfg_name   = rtl_bt/rtl8852cu_config
```

Linux then applies a special rule:

```text
if lmp_subver == 0x8852 and hci_rev == 0x000c:
    try rtl8852cu_fw_v2.bin first
fallback:
    try rtl8852cu_fw.bin
```

This is significant. The local `0bda:4853` hardware was initially treated as
RTL8852C and tested with `rtl8852cu_fw.bin`/`rtl8852cu_fw_v2.bin`, but Linux
classifies that PID as RTL8852BE. The correct next hardware test for
`0bda:4853` is therefore `rtl8852bu_fw.bin`.

PyBlueHost should therefore support both names and both formats.

---

## Legacy Epatch Format (`Realtech`)

Legacy epatch files start with:

```text
offset 0   8 bytes  "Realtech"
offset 8   4 bytes  firmware version, little-endian
offset 12  2 bytes  patch count, little-endian
offset 14           chip-id table      (uint16 * patch_count)
                    patch-length table (uint16 * patch_count)
                    patch-offset table (uint32 * patch_count)
                    patch payloads
tail                extension signature: 51 04 fd 77
```

Patch selection:

```python
target_chip_id = rom_version + 1
selected_patch = patch where patch_chip_id == target_chip_id
payload = selected_patch[:-4] + firmware_version_le32
```

If no patch matches, fail explicitly. Do not fall back to sending the whole
firmware image; that can wedge the controller.

Previously inspected RTL8852C/cu legacy file:

```text
file: rtl8852cu_fw.bin
size: 113336 bytes
signature: Realtech
patches:
  chip_id 0x0001 -> 52005 bytes
  chip_id 0x0002 -> 61105 bytes
ROM version: 0x01
selected chip_id: 0x0002
download payload: 61105 bytes
fragment count: 243
```

This file is not the Linux-selected firmware for USB PID `0bda:4853`; that PID
maps to RTL8852BE and should use `rtl8852bu_fw.bin`.

---

## V2 Firmware Format (`RTBTCore`)

Linux supports a newer format with signature `RTBTCore`. This is preferred for
RTL8852C when `rtl8852cu_fw_v2.bin` is present.

High-level behavior:

1. Parse a v2 header containing section count and firmware version.
2. Iterate sections.
3. For supported section opcodes, parse subsections.
4. Keep subsections matching `rom_version + 1`.
5. For security-header subsections, also match key id when required.
6. Order selected subsections by priority.
7. Concatenate selected subsection payloads into the final download payload.

PyBlueHost implements the section/subsection parser needed by the observed
`rtl8852cu_fw_v2.bin` file. Security-header subsections follow Linux's
conservative rule: if no key id has been read from the controller, security
headers are ignored; if a key id is available, only matching subsections are
included.

---

## Download Command

Realtek download command:

```text
opcode: 0xFC20
params:
  byte 0: fragment index
  bytes 1..N: payload fragment, max 252 bytes
```

Each command returns a Command Complete event. The response length should be
validated; Linux treats length mismatch as an error.

Fragment size:

```text
RTL_FRAG_LEN = 252
```

---

## Fragment Index Rule

Linux uses a counter `j`:

```c
dl_cmd->index = j++;
if (dl_cmd->index == 0x7f)
    j = 1;

if (i == frag_num - 1)
    dl_cmd->index |= 0x80;
```

Equivalent Python:

```python
index = 0
for i in range(fragment_count):
    download_index = index
    index += 1
    if download_index == 0x7F:
        index = 1
    if i == fragment_count - 1:
        download_index |= 0x80
```

Sequence around the wrap point:

```text
... 0x7d, 0x7e, 0x7f, 0x01, 0x02, 0x03 ...
```

For the previously tested RTL8852C/cu legacy payload:

```text
fragment 1/243   index=0x00
fragment 129/243 index=0x01
fragment 243/243 index=0xf3
```

Incorrect behavior that wedges hardware:

```text
0x7d, 0x7e, 0x7f, 0x00 ...
```

Also incorrect for this hardware:

```text
0x7d, 0x7e, 0x7f, 0x81 ...
```

`0x80` is the final-fragment marker bit. It must not be used as a normal
non-final index.

---

## Post-Download Behavior

Linux does not immediately issue `HCI_Reset` as the next validation step inside
`rtl_download_firmware()`. It reads local version and logs the resulting firmware
version.

Bumble does:

1. Download firmware.
2. Read ROM version again.
3. In `init_controller()`, send HCI Reset.

PyBlueHost current code:

1. Downloads firmware.
2. Reads local version after download.

Hardware observation on the `0bda:4853` RTL8852BE adapter while testing the
RTL8852C/cu firmware path:

```text
All 243 fragments are sent.
The process times out immediately after the final fragment path.
Subsequent HCI Reset attempts time out until physical unplug/replug.
```

Interpretation:

- The fragment index issue has been fixed.
- The remaining failure needs a new hardware run using the Linux-selected
  RTL8852B/bu firmware path.
- If v2 firmware still times out after the final fragment, the next likely causes
  are missing key-id/config handling or stale USB handle behavior after firmware
  activation.

---

## Recommended PyBlueHost Implementation Plan

1. Add Realtek local-version probing:
   - Send `HCI_Read_Local_Version_Information` (`0x1001`).
   - Parse `hci_ver`, `hci_rev`, `lmp_ver`, `lmp_subver`.
   - Match a Realtek table modeled on Linux.

2. Add firmware-name resolution: DONE for RTL8852B and RTL8852C.
   - For RTL8852B/`0bda:4853`, use `rtl8852bu_fw.bin`.
   - For RTL8852C, try `rtl8852cu_fw_v2.bin`.
   - Fall back to `rtl8852cu_fw.bin`.
   - Keep `.bin` suffixes in `KNOWN_CHIPS` and download tooling.

3. Add `RTBTCore` parser: DONE for ordinary subsections, partial for security headers.
   - Parse sections and subsections.
   - Select `eco == rom_version + 1`.
   - Respect security key id when present; skip security headers when key id is unknown.
   - Concatenate selected subsections by priority.

4. Add optional config handling:
   - Load config when available and allowed.
   - Enforce config only for chips where Linux marks `config_needed`.
   - For RTL8852C USB, config is not mandatory.

5. Change post-download validation: DONE.
   - After final fragment, issue `HCI_Read_Local_Version_Information`.
   - Log loaded firmware version.
   - Only perform HCI Reset if required by the subsequent stack initialization path.

6. Add recovery path:
   - Implement vendor command `0xFC66` drop-firmware flow for unknown/loaded states,
     matching Linux's recovery branch.
   - Add a bounded retry path that can release/reopen the USB handle after firmware
     activation.

7. Keep hardware safety rules:
   - Never send whole epatch files as raw payload when no patch matches.
   - Log fragment progress near wrap and final fragment.
   - On timeout after firmware download, instruct physical unplug/replug because
     software USB reset may not recover the RTL8852B/BE adapter.

---

## Current PyBlueHost Hardware Findings

Environment:

```text
OS: Windows
USB driver: WinUSB/libusb accessible
Device: RTL8852BE per Linux btusb.c
VID/PID: 0bda:4853
ROM version: 0x01
Firmware previously tested: rtl8852cu_fw.bin, rtl8852cu_fw_v2.bin
Correct firmware per Linux: rtl8852bu_fw.bin
Previously tested signatures: Realtech, RTBTCore
```

Verified:

```text
USB enumeration works.
HCI Reset works before firmware download.
Read ROM Version works before firmware download.
Legacy epatch parser selects chip_id 0x0002 for rom_version 0x01.
RTBTCore parser selects eco 0x02 subsections for rom_version 0x01.
Fragment index now follows Linux wrap behavior.
All 243 legacy fragments are sent.
All 286 v2 fragments are sent with final index 0x9f.
One RTL8852C v2 hardware load attempt after power cycle left the controller
responsive enough for BLE scan setup, but the follow-up local version reports
the RTL8852B stock tuple:
  hci=0x0b hci_rev=0x000b lmp=0x0b manufacturer=0x005d lmp_subver=0x8852
That tuple is not operational according to Linux/Bumble matching; it maps to
RTL8852B and should enter the firmware-load path using rtl8852bu_fw.bin.
BLE scan setup commands completed with status 0x00 through LE Set Scan Enable
in the previous cu-firmware test, but that is not proof that the correct
firmware was loaded.
The 2026-05-02 no-gate hardware run also confirmed that stale Command Complete
events can appear; opcode filtering skips the stale HCI Reset completion and
continues to the Read Local Version response.

After the `0bda:4853` mapping was corrected to RTL8852BE/`rtl8852bu_fw.bin`,
a subsequent run found the controller already in an operational state:
  hci=0x0b hci_rev=0x127c lmp=0x0b manufacturer=0x005d lmp_subver=0xfd78
This tuple does not match a Linux stock-ROM entry, so PyBlueHost skipped
firmware download. BLE scanning succeeded and the `--btsnoop test.cfa` capture
contained a valid btsnoop header plus 46 HCI records.
```

Last failing runs:

```text
Legacy path: timeout after final fragment.
V2 path: final fragment is sent, then post-download Read Local Version times out.
After that, the adapter stops accepting the initial HCI Reset control transfer.
Current safeguard: PyBlueHost only writes firmware when the pre-download
local-version tuple matches a known stock-ROM entry.
```

Current safe hardware verification:

```text
Physically unplug/replug the RTL8852B/BE adapter only when a fresh firmware-load test is needed.
Then run:
uv run pybluehost app ble-scan -t usb

Expected firmware path:
0bda:4853 -> RTL8852BE -> rtl8852bu_fw.bin -> selected rom_version+1 patch -> Read Local Version.

After a successful load, re-open and check the returned local-version tuple.
If it is still 0x8852/0x000b/0x0b, Linux/Bumble would still classify it as a
stock RTL8852B tuple, not as an operational skip state.
```

---

## References

- Linux kernel Realtek driver:
  `drivers/bluetooth/btrtl.c`
  https://github.com/torvalds/linux/blob/master/drivers/bluetooth/btrtl.c

- Google Bumble Realtek driver:
  `bumble/drivers/rtk.py`
  https://github.com/google/bumble/blob/main/bumble/drivers/rtk.py

- Linux firmware files:
  `rtl_bt/rtl8852bu_fw.bin`
  `rtl_bt/rtl8852cu_fw.bin`
  `rtl_bt/rtl8852cu_fw_v2.bin`
  https://gitlab.com/kernel-firmware/linux-firmware/-/tree/main/rtl_bt
