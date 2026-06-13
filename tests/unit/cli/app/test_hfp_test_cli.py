import argparse
import inspect


def test_register_function_exists():
    from pybluehost.cli.app.hfp_test import register_hfp_test_command
    assert callable(register_hfp_test_command)


def test_main_is_async():
    from pybluehost.cli.app.hfp_test import _hfp_test_main
    assert inspect.iscoroutinefunction(_hfp_test_main)


def test_argparse_hf_role():
    from pybluehost.cli.app.hfp_test import register_hfp_test_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_hfp_test_command(subs)
    args = parser.parse_args([
        "hfp-test",
        "--role", "hf",
        "--target", "AA:BB:CC:DD:EE:FF",
        "--wav", "in.wav",
        "--out", "out.wav",
        "--transport", "virtual",
    ])
    assert args.role == "hf"
    assert args.target == "AA:BB:CC:DD:EE:FF"
    assert args.wav == "in.wav"
    assert args.out == "out.wav"


def test_argparse_ag_role():
    from pybluehost.cli.app.hfp_test import register_hfp_test_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_hfp_test_command(subs)
    args = parser.parse_args([
        "hfp-test",
        "--role", "ag",
        "--output", "received.wav",
        "--transport", "virtual",
    ])
    assert args.role == "ag"
    assert args.output == "received.wav"
