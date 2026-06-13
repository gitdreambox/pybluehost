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

> **SCO data over USB** requires the adapter to be switched to Alt Setting ≥ 1
> so the isochronous endpoint becomes active. PyBlueHost v2.1 now does this
> automatically: `HCIController.setup_synchronous_connection` calls
> `transport.prepare_for_sco(codec)`, which on `IntelUSBTransport` selects
> Alt 1 (CVSD) or Alt 6 (mSBC) and on `RealtekUSBTransport` issues vendor
> command `0xFC8B` (`SET_SCO_ROUTING_TYPE` param `0x02` = HCI bus). See
> "Known Issues — USB SCO Alt Setting" below for the per-vendor matrix.

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

## Live Mic / Speaker (v2.1 Plan B.2)

Run HFP/HSP against an actual microphone and speaker instead of WAV files.

**Setup:**

```bash
pip install 'pybluehost[audio]'    # pulls sounddevice + PortAudio
pybluehost tools audio list-devices
```

Sample output:

```
 idx   in out    rate  name
   0    2   0   48000  Built-in Microphone
   1    0   2   48000  Built-in Speaker
   2    2   2   48000  USB Headset
```

**Use the indices with `app hfp-test` or `app hsp-test`:**

```bash
# HFP HF role — live phone call audio through USB headset
pybluehost app hfp-test --transport=usb \
    --role=hf \
    --target=AA:BB:CC:DD:EE:FF \
    --mic-device=2 \
    --speaker-device=2
```

```bash
# HSP HS role — same idea, CVSD-only
pybluehost app hsp-test --transport=usb \
    --role=hs \
    --target=AA:BB:CC:DD:EE:FF \
    --mic-device=2 \
    --speaker-device=2
```

`--mic-device` and `--wav` are mutually exclusive (same for `--speaker-device`
vs `--out`/`--output`). Mix-and-match is fine: `--mic-device=2 --out=rx.wav`
streams live mic to the peer while capturing the inbound audio to a file.

**Sample-rate matching:** PyBlueHost asks PortAudio for the native SCO rate
(8 kHz CVSD or 16 kHz mSBC) and lets the host audio backend resample. If your
device only supports 44.1/48 kHz, sounddevice/PortAudio handles the conversion
transparently.

**Latency:** end-to-end ~50–100 ms depending on platform. Buffer size is set
to one SCO packet's worth of samples (240 for CVSD, 120 for mSBC).

**Underrun handling:** if the mic stream stalls, the sender emits silence
frames so the SCO clock keeps ticking — the peer never hears a buffer hiccup.

**Known issues:**
- **PulseAudio default sinks may downmix to mono incorrectly.** If voice
  sounds garbled, pass an explicit mono-capable device index.
- **macOS CoreAudio:** sometimes refuses 8 kHz mono and silently up-samples;
  the result is fine but adds a few ms of extra latency.
- **Windows WinUSB-bound adapters** still need the v2.1 Plan B.1 SCO
  routing (handled automatically) — see "USB SCO Alt Setting" below.

## Known Issues

### USB SCO Alt Setting

USB Bluetooth controllers expose the SCO audio path via an isochronous
endpoint that's only active in Alt Setting 1 or higher. By default the
controller is in Alt 0 (no SCO data).

**v2.1 Plan B.1 implements this automatically.** `HCIController.
setup_synchronous_connection` infers the codec from the SCO preset
(`PRESET_CVSD_S1` → `"CVSD"`, `PRESET_MSBC_T2` → `"mSBC"`) and calls
`transport.prepare_for_sco(codec)` before issuing the HCI command.

Per-vendor implementations:
- **Intel** (`IntelUSBTransport`): selects Alt 1 (CVSD) or Alt 6 (mSBC) via
  `usb_set_interface(0, alt)`, then re-enumerates iso IN/OUT endpoints. The
  alt-to-codec mapping matches Linux BlueZ `drivers/bluetooth/btusb.c`
  (`BTUSB_ISOC_ALT_BAND_NB`/`_WB`).
- **Realtek** (`RealtekUSBTransport`): sends vendor HCI command `0xFC8B`
  (`HCI_VENDOR_RTK_SET_SCO_ROUTING_TYPE`) with parameter `0x02` (route SCO via
  HCI bus instead of PCM). Cached: sent only on the first SCO setup.
- **Broadcom / others**: not yet covered. Alt-Setting numbers differ from
  Intel — `prepare_for_sco` falls back to the no-op default until tested
  against actual hardware (Plan B.2).
- **CSR8510 and similar legacy 4.0 dongles**: hardware-incompatible
  (SCO routed only via PCM bus, not exposed externally).

Real-hardware verification is still pending an adapter; the v2.1 unit-test
coverage uses mocked `usb.core.Device` instances.

### Adapter Compatibility Matrix

| Adapter | A2DP | AVRCP | HFP SCO (data) | Notes |
|---|---|---|---|---|
| Intel AX200 | ✅ | ✅ | 🧪 Alt 1/6 selection implemented; awaiting hardware verification | Most reliable on Linux |
| Intel AX211 | ✅ | ✅ | 🧪 Same as AX200 | Same |
| Realtek RTL8761 | ✅ | ✅ | 🧪 Vendor cmd 0xFC8B implemented; awaiting hardware verification | Inquiry sometimes slow |
| CSR8510 | ✅ | ✅ | ❌ Hardware-incompatible (SCO via PCM only) | Legacy; ACL only |
| Broadcom BCM20702 | ✅ | ✅ | ⚠️ Alt numbers differ from Intel — needs adapter (Plan B.2) | Varies by firmware version |

✅ = works out of the box. 🧪 = code path implemented and unit-tested
(mocked USB), real-hardware verification pending. ⚠️ = not yet implemented.
❌ = hardware-incompatible.

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
