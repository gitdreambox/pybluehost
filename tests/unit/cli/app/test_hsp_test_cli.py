import argparse
import inspect


def test_register_function_exists():
    from pybluehost.cli.app.hsp_test import register_hsp_test_command
    assert callable(register_hsp_test_command)


def test_main_is_async():
    from pybluehost.cli.app.hsp_test import _hsp_test_main
    assert inspect.iscoroutinefunction(_hsp_test_main)


def test_argparse_hs_role():
    from pybluehost.cli.app.hsp_test import register_hsp_test_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_hsp_test_command(subs)
    args = parser.parse_args([
        "hsp-test",
        "--role", "hs",
        "--target", "AA:BB:CC:DD:EE:FF",
        "--wav", "in.wav",
        "--out", "out.wav",
        "--transport", "virtual",
    ])
    assert args.role == "hs"


def test_argparse_ag_role():
    from pybluehost.cli.app.hsp_test import register_hsp_test_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_hsp_test_command(subs)
    args = parser.parse_args([
        "hsp-test",
        "--role", "ag",
        "--output", "received.wav",
        "--transport", "virtual",
    ])
    assert args.role == "ag"
