"""Smoke tests for demo-phone + demo-headphone CLI argparse layer."""
import argparse
import inspect


def test_register_demo_phone():
    from pybluehost.cli.app.demo_phone import register_demo_phone_command
    assert callable(register_demo_phone_command)


def test_register_demo_headphone():
    from pybluehost.cli.app.demo_headphone import register_demo_headphone_command
    assert callable(register_demo_headphone_command)


def test_demo_phone_main_is_async():
    from pybluehost.cli.app.demo_phone import _demo_phone_main
    assert inspect.iscoroutinefunction(_demo_phone_main)


def test_demo_headphone_main_is_async():
    from pybluehost.cli.app.demo_headphone import _demo_headphone_main
    assert inspect.iscoroutinefunction(_demo_headphone_main)


def test_demo_phone_argparse():
    from pybluehost.cli.app.demo_phone import register_demo_phone_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_demo_phone_command(subs)
    args = parser.parse_args([
        "demo-phone",
        "--wav", "music.wav",
        "--ring-after", "3",
        "--caller", "+15551234",
        "--transport", "virtual",
    ])
    assert args.wav == "music.wav"
    assert args.ring_after == 3.0
    assert args.caller == "+15551234"


def test_demo_headphone_argparse_minimal():
    from pybluehost.cli.app.demo_headphone import register_demo_headphone_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_demo_headphone_command(subs)
    args = parser.parse_args([
        "demo-headphone",
        "--target", "AA:BB:CC:DD:EE:FF",
        "--transport", "virtual",
    ])
    assert args.target == "AA:BB:CC:DD:EE:FF"
    assert args.output == "received_music.wav"   # default
    assert args.avrcp_cmd is None                # default
    assert args.auto_answer is False             # default


def test_demo_headphone_argparse_with_avrcp():
    from pybluehost.cli.app.demo_headphone import register_demo_headphone_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_demo_headphone_command(subs)
    args = parser.parse_args([
        "demo-headphone",
        "--target", "AA:BB:CC:DD:EE:FF",
        "--avrcp-cmd", "pause",
        "--avrcp-cmd-at", "1.5",
        "--auto-answer",
        "--transport", "virtual",
    ])
    assert args.avrcp_cmd == "pause"
    assert args.avrcp_cmd_at == 1.5
    assert args.auto_answer is True
