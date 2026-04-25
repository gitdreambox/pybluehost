import argparse
from pybluehost.cli.tools import register_tools_commands


def test_register_tools_commands_adds_subcommands():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_tools_commands(subs)
    args = parser.parse_args(["tools", "decode", "01030c00"])
    assert args.cmd == "tools"
    assert args.tools_cmd == "decode"
    assert args.hex == "01030c00"


def test_register_tools_rpa_gen_irk():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_tools_commands(subs)
    args = parser.parse_args(["tools", "rpa", "gen-irk"])
    assert args.tools_cmd == "rpa"
    assert args.rpa_cmd == "gen-irk"


def test_register_tools_fw_list():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_tools_commands(subs)
    args = parser.parse_args(["tools", "fw", "list"])
    assert args.tools_cmd == "fw"
