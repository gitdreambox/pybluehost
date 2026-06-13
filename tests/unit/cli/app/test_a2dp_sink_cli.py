import argparse
import inspect


def test_register_function_exists():
    from pybluehost.cli.app.a2dp_sink import register_a2dp_sink_command
    assert callable(register_a2dp_sink_command)


def test_main_is_async():
    from pybluehost.cli.app.a2dp_sink import _a2dp_sink_main
    assert inspect.iscoroutinefunction(_a2dp_sink_main)


def test_argparse_accepts_output_wav():
    from pybluehost.cli.app.a2dp_sink import register_a2dp_sink_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_a2dp_sink_command(subs)
    args = parser.parse_args([
        "a2dp-sink",
        "--output", "received.wav",
        "--transport", "virtual",
    ])
    assert args.output == "received.wav"


def test_argparse_accepts_output_device():
    from pybluehost.cli.app.a2dp_sink import register_a2dp_sink_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_a2dp_sink_command(subs)
    args = parser.parse_args([
        "a2dp-sink",
        "--output", "device",
        "--transport", "virtual",
    ])
    assert args.output == "device"
