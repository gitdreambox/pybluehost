"""Tests for REPL command parser."""
import pytest

from pybluehost.pts.repl import parse_repl_command


def test_parse_simple_advertise():
    cmd, args = parse_repl_command("advertise")
    assert cmd == "advertise"
    assert args == {"_positional": []}


def test_parse_advertise_with_data():
    cmd, args = parse_repl_command("advertise --data=01020304")
    assert cmd == "advertise"
    assert args["data"] == "01020304"


def test_parse_connect_with_classic_flag():
    cmd, args = parse_repl_command("connect AA:BB:CC:DD:EE:FF --classic")
    assert cmd == "connect"
    assert args["_positional"] == ["AA:BB:CC:DD:EE:FF"]
    assert args["classic"] is True


def test_parse_notify_with_two_positionals():
    cmd, args = parse_repl_command("notify 0x0023 0102")
    assert cmd == "notify"
    assert args["_positional"] == ["0x0023", "0102"]


def test_parse_pair_with_io_cap_and_mitm():
    cmd, args = parse_repl_command("pair --io-cap=DisplayYesNo --mitm")
    assert cmd == "pair"
    assert args["io-cap"] == "DisplayYesNo"
    assert args["mitm"] is True


def test_parse_empty_line():
    cmd, args = parse_repl_command("")
    assert cmd is None


def test_parse_help():
    cmd, _ = parse_repl_command("help")
    assert cmd == "help"


def test_parse_quit_and_exit_both_resolve_to_quit():
    assert parse_repl_command("quit")[0] == "quit"
    assert parse_repl_command("exit")[0] == "quit"


def test_parse_unknown_command_returns_unknown():
    cmd, _ = parse_repl_command("frobnicate")
    assert cmd == "unknown"


def test_parse_handles_quoted_data():
    """shlex must handle quoted strings (e.g. for write payloads)."""
    cmd, args = parse_repl_command('write 0x0023 "0102"')
    assert cmd == "write"
    assert args["_positional"][1] == "0102"
