"""'tools audio list-devices' — enumerate sounddevice/PortAudio I/O devices.

Use this to find the integer indices to pass to `app hfp-test --mic-device=N`
or `app hsp-test --speaker-device=N` for live SCO audio.
"""
from __future__ import annotations

import argparse


def register_audio_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("audio", help="Audio device utilities (PortAudio)")
    p.set_defaults(func=lambda _args: p.print_help() or 2)
    sub = p.add_subparsers(dest="audio_cmd")
    ld = sub.add_parser(
        "list-devices",
        help="List sounddevice/PortAudio input/output devices",
    )
    ld.set_defaults(func=lambda _args: _list_devices_main())


def _list_devices_main() -> int:
    from pybluehost.audio import _sounddevice_io as sdio
    if not sdio.is_available():
        print(
            "sounddevice is not installed or PortAudio backend unavailable.\n"
            "Install with: pip install 'pybluehost[audio]'"
        )
        return 1
    devs = sdio.list_devices()
    if not devs:
        print("No audio devices reported by PortAudio.")
        return 0
    print(f"{'idx':>4}  {'in':>3} {'out':>3} {'rate':>7}  name")
    for d in devs:
        print(
            f"{d['index']:>4}  {d['channels_in']:>3} {d['channels_out']:>3} "
            f"{int(d['samplerate']):>7}  {d['name']}"
        )
    return 0
