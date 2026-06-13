# Classic Audio (A2DP / AVRCP / HFP / HSP) Real-Hardware Runbook

> **Companion to:** `HARDWARE_E2E.md` (BLE / Classic non-audio).
> **Implements:** Plans A.1-A.6 of PRD v2.0.

This runbook covers the manual real-hardware procedures for the four Classic
Bluetooth audio profiles. All four profiles have automated virtual-loopback
tests (`tests/e2e/test_{a2dp,avrcp,hfp,hsp}_lifecycle.py`); this document
covers what those tests can't reach: pairing with a real phone, streaming to
a real Bluetooth speaker, and the USB SCO Alt-Setting quirks that ship in
most consumer Intel/Realtek USB controllers.

## Prerequisites

- One Linux host with PyBlueHost installed: `pip install -e '.[audio]'` (the
  `audio` extras pull `sounddevice>=0.4`).
- One BlueZ-supported USB adapter (Intel AX2xx, Realtek RTL8761, CSR8510, ...).
- One real Bluetooth peer:
  - A2DP/AVRCP testing: a Bluetooth speaker (e.g., JBL Flip, UE Boom).
  - HFP/HSP testing: a phone (Android or iPhone), OR a headset (Plantronics,
    Jabra) that advertises HSP/HFP HF.
- For SCO testing on real hardware: an adapter with documented Alt-Setting
  support. See "Known Issues" below.

## A2DP — Push Audio to a Bluetooth Speaker

```bash
# 1. Inquiry to find the speaker.
pybluehost app classic-inquiry --transport=usb --duration=10

# Look for an entry like:
#   AA:BB:CC:DD:EE:FF   "JBL Flip 5"   class=0x240414 (audio)

# 2. Push a WAV file to it.
pybluehost app a2dp-source --transport=usb \
    --target=AA:BB:CC:DD:EE:FF \
    --play=music.wav

# Or push from your default sounddevice input (requires audio extras):
pybluehost app a2dp-source --transport=usb \
    --target=AA:BB:CC:DD:EE:FF \
    --play=device
```

Verification: speaker plays the audio. Latency is typically 100-300 ms
(SBC + AVDTP framing + L2CAP); not low enough for live monitoring but fine for
playback.

If the speaker doesn't pair: check `bluetoothctl scan on` separately to verify
it's discoverable; some speakers go to sleep after ~30 seconds.

## A2DP Sink — Receive Audio from a Phone

```bash
pybluehost app a2dp-sink --transport=usb --output=received.wav
```

Then on the phone: pair to your PyBlueHost adapter (will appear as a generic
Bluetooth device with audio class), and play music — it'll write to
`received.wav` until you Ctrl-C.

## AVRCP — Remote Control a Phone

```bash
# Play.
pybluehost app avrcp-control --transport=usb \
    --target=AA:BB:CC:DD:EE:FF --cmd=play

# Pause / next / prev / volume up/down work the same way.
pybluehost app avrcp-control --transport=usb \
    --target=AA:BB:CC:DD:EE:FF --cmd=pause
```

The phone's media app (Spotify, music app, etc.) should respond. AVRCP doesn't
need an active A2DP session — the AVCTP signaling channel is independent.

To act as the controllable side (e.g., let a phone control PyBlueHost):

```bash
pybluehost app avrcp-target --transport=usb
# Each incoming PASS_THROUGH command is logged to stdout.
```

## HFP — Connect to a Phone as a Headset

> **CRITICAL:** SCO data over USB requires Alt-Setting switching. Most adapters
> default to Alt 0 (no isochronous endpoint); SCO data path will not work until
> the adapter is moved to Alt 1+. See "Known Issues — USB SCO Alt Setting"
> below.

```bash
# Pair the phone first via your OS Bluetooth UI (or bluetoothctl).
# Then run the HF role; PyBlueHost connects, drives SLC, then opens SCO.
pybluehost app hfp-test --transport=usb \
    --role=hf \
    --target=AA:BB:CC:DD:EE:FF \
    --wav=mic_input.wav \
    --out=speaker_output.wav
```

For the AG role (PyBlueHost emulating the phone, e.g., for testing a real
headset):

```bash
pybluehost app hfp-test --transport=usb \
    --role=ag \
    --output=received.wav
```

The headset will see PyBlueHost as an AG and try to establish HFP SLC + SCO.

## HSP — Same as HFP but Simpler

```bash
# HS side (PyBlueHost acts as a headset; CKPD triggers audio).
pybluehost app hsp-test --transport=usb \
    --role=hs \
    --target=AA:BB:CC:DD:EE:FF \
    --wav=mic_input.wav

# AG side.
pybluehost app hsp-test --transport=usb \
    --role=ag \
    --output=received.wav
```

HSP uses CVSD only; no codec negotiation, no SLC. The HS sends `AT+CKPD=200`
to request audio, AG accepts, SCO opens.

## Known Issues

### USB SCO Alt Setting

USB Bluetooth controllers expose the SCO audio path via an isochronous
endpoint that's only active in Alt Setting 1 or higher. By default the
controller is in Alt 0 (no SCO data). PyBlueHost's HFP/HSP signaling completes
and `HCI Setup_Synchronous_Connection` succeeds, but **SCO data packets are
dropped silently** until the adapter is in Alt ≥ 1.

Workarounds:
- **Intel adapters**: BlueZ's `btusb` driver switches Alt automatically when
  a SCO connection completes if `CONFIG_BT_HCIUART_AG6XX` or similar is set.
  Verify with `dmesg | grep btusb` after SCO setup — look for
  "Alternate setting" log entries. If absent, the kernel module needs a patch
  or a vendor-specific HCI command.
- **Realtek adapters**: Often need a vendor HCI command (`HCI_VENDOR_OP=0xFC1E`
  or similar) to switch Alt. See `pybluehost/transport/usb/realtek.py` for the
  v2.1 plan.

This is **explicitly deferred to v2.1** (`docs/PRD-v2.1.md`, when written).
For v2.0, SCO data paths are validated on the virtual transport only;
real-hardware HFP/HSP SCO is best-effort.

### Adapter Compatibility Matrix

| Adapter | A2DP | AVRCP | HFP SCO (data) | Notes |
|---|---|---|---|---|
| Intel AX200 | ✅ | ✅ | ⚠️ Alt Setting required | Most reliable on Linux |
| Intel AX211 | ✅ | ✅ | ⚠️ Alt Setting required | Same |
| Realtek RTL8761 | ✅ | ✅ | ⚠️ Vendor command needed | Inquiry sometimes slow |
| CSR8510 | ✅ | ✅ | ❌ No SCO over USB | Legacy; ACL only |
| Broadcom BCM20702 | ✅ | ✅ | ⚠️ Alt Setting required | Varies by firmware version |

✅ = works out of the box. ⚠️ = works after kernel/vendor config. ❌ = not
supported in v2.0 scope.

### Phone-Specific Quirks

- **iPhone**: Will only respond to PASS_THROUGH PLAY/PAUSE when an A2DP
  stream is active. PASS_THROUGH while music is paused returns NOT_IMPLEMENTED.
- **Android (Samsung)**: Sends `AT+BCS=2` (mSBC selection) even when the HF
  only advertised CVSD; the HFP state machine ignores unsupported codec
  selections and falls back to CVSD.
- **Google Pixel**: Aggressively reconnects A2DP if PyBlueHost disconnects
  mid-track; the source CLI handles this by logging and exiting cleanly.

### Bluetooth Speaker Quirks

- **JBL Flip series**: Goes to sleep after 30 seconds of silence; the source CLI
  may fail to reconnect. Press the speaker's power button to wake it.
- **UE Boom**: Refuses A2DP connection if it has a more recent paired device
  in range; unpair other devices in the speaker's memory first.
- **Sony WH-1000XM4 (headphones)**: Negotiates AAC if both ends support it;
  PyBlueHost v2.0 doesn't ship AAC, so the headphones fall back to SBC.
  Audio quality is noticeably lower than AAC but still usable.

## Reporting Bugs

If real-hardware testing surfaces a regression, include:
- Adapter chipset (`lsusb` + kernel `dmesg`)
- Peer device model + firmware version
- `pybluehost --trace=hci,acl,sdp,rfcomm app <cmd> ...` output
- BlueZ version (`bluetoothd --version`) — sometimes a Linux-side bug, not
  PyBlueHost.

File issues at https://github.com/anthropics/pybluehost.
