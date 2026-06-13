import argparse
import inspect


def test_register_function_exists():
    from pybluehost.cli.app.a2dp_source import register_a2dp_source_command
    assert callable(register_a2dp_source_command)


def test_main_is_async():
    from pybluehost.cli.app.a2dp_source import _a2dp_source_main
    assert inspect.iscoroutinefunction(_a2dp_source_main)


def test_argparse_accepts_required_args():
    from pybluehost.cli.app.a2dp_source import register_a2dp_source_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_a2dp_source_command(subs)
    args = parser.parse_args([
        "a2dp-source",
        "--target", "AA:BB:CC:DD:EE:FF",
        "--play", "music.wav",
        "--transport", "virtual",
    ])
    assert args.target == "AA:BB:CC:DD:EE:FF"
    assert args.play == "music.wav"


def test_play_device_keyword():
    from pybluehost.cli.app.a2dp_source import register_a2dp_source_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_a2dp_source_command(subs)
    args = parser.parse_args([
        "a2dp-source",
        "--target", "AA:BB:CC:DD:EE:FF",
        "--play", "device",
        "--transport", "virtual",
    ])
    assert args.play == "device"
