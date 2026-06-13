"""hsp-test CLI: --mic-device / --speaker-device, mutually exclusive with WAV args."""
import argparse
import pytest


def _build():
    from pybluehost.cli.app.hsp_test import register_hsp_test_command
    p = argparse.ArgumentParser()
    subs = p.add_subparsers(dest="cmd")
    register_hsp_test_command(subs)
    return p


def test_hsp_test_accepts_mic_and_speaker():
    p = _build()
    args = p.parse_args([
        "hsp-test", "--role=hs", "--target=AA:BB:CC:DD:EE:FF",
        "--mic-device=2", "--speaker-device=3",
        "--transport=virtual",
    ])
    assert args.mic_device == 2
    assert args.speaker_device == 3


def test_hsp_test_wav_and_mic_are_mutually_exclusive():
    p = _build()
    with pytest.raises(SystemExit):
        p.parse_args([
            "hsp-test", "--role=hs", "--target=AA:BB:CC:DD:EE:FF",
            "--wav=in.wav", "--mic-device=0",
            "--transport=virtual",
        ])


def test_hsp_test_out_and_speaker_are_mutually_exclusive():
    p = _build()
    with pytest.raises(SystemExit):
        p.parse_args([
            "hsp-test", "--role=hs", "--target=AA:BB:CC:DD:EE:FF",
            "--wav=in.wav", "--out=rx.wav", "--speaker-device=0",
            "--transport=virtual",
        ])


def test_hsp_test_defaults_keep_old_wav_path_working():
    p = _build()
    args = p.parse_args([
        "hsp-test", "--role=hs", "--target=AA:BB:CC:DD:EE:FF",
        "--wav=in.wav",
        "--transport=virtual",
    ])
    assert args.wav == "in.wav"
    assert args.mic_device is None
    assert args.speaker_device is None
