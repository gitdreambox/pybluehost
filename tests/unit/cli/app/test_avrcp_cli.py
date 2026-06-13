import argparse
import inspect

import pytest


def test_register_control_command():
    from pybluehost.cli.app.avrcp_control import register_avrcp_control_command
    assert callable(register_avrcp_control_command)


def test_register_target_command():
    from pybluehost.cli.app.avrcp_target import register_avrcp_target_command
    assert callable(register_avrcp_target_command)


def test_control_main_is_async():
    from pybluehost.cli.app.avrcp_control import _avrcp_control_main
    assert inspect.iscoroutinefunction(_avrcp_control_main)


def test_target_main_is_async():
    from pybluehost.cli.app.avrcp_target import _avrcp_target_main
    assert inspect.iscoroutinefunction(_avrcp_target_main)


def test_control_argparse_accepts_play():
    from pybluehost.cli.app.avrcp_control import register_avrcp_control_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_avrcp_control_command(subs)
    args = parser.parse_args([
        "avrcp-control",
        "--target", "AA:BB:CC:DD:EE:FF",
        "--cmd", "play",
        "--transport", "virtual",
    ])
    assert args.target == "AA:BB:CC:DD:EE:FF"
    assert args.cmd_action == "play"


def test_control_rejects_unknown_command():
    from pybluehost.cli.app.avrcp_control import register_avrcp_control_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_avrcp_control_command(subs)
    with pytest.raises(SystemExit):
        parser.parse_args([
            "avrcp-control",
            "--target", "AA:BB:CC:DD:EE:FF",
            "--cmd", "fly-to-mars",
            "--transport", "virtual",
        ])


def test_target_argparse_minimal():
    from pybluehost.cli.app.avrcp_target import register_avrcp_target_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_avrcp_target_command(subs)
    args = parser.parse_args(["avrcp-target", "--transport", "virtual"])
    assert args is not None
