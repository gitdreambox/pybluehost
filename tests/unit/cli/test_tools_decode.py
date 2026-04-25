import argparse
from pybluehost.cli.tools.decode import register_decode_command, _cmd_decode


def test_decode_hci_reset(capsys):
    args = argparse.Namespace(hex="01030c00")
    rc = _cmd_decode(args)
    captured = capsys.readouterr()
    assert rc == 0
    assert "HCI_Reset" in captured.out
    assert "0x0C03" in captured.out or "0xc03" in captured.out.lower()


def test_decode_invalid_hex(capsys):
    args = argparse.Namespace(hex="ZZ")
    rc = _cmd_decode(args)
    captured = capsys.readouterr()
    assert rc != 0


def test_decode_empty(capsys):
    args = argparse.Namespace(hex="")
    rc = _cmd_decode(args)
    assert rc != 0
