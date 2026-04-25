import argparse
from pybluehost.cli.tools.rpa import _cmd_gen_irk, _cmd_gen_rpa, _cmd_verify


def test_gen_irk_outputs_32_hex_chars(capsys):
    rc = _cmd_gen_irk(argparse.Namespace())
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert len(out) == 32
    bytes.fromhex(out)  # must be valid hex


def test_gen_rpa_with_known_irk_round_trips(capsys):
    irk = "0102030405060708090a0b0c0d0e0f10"
    rc = _cmd_gen_rpa(argparse.Namespace(irk=irk))
    out = capsys.readouterr().out
    assert rc == 0
    addr_line = [l for l in out.splitlines() if "/random" in l][0]
    addr = addr_line.split()[-1].split("/")[0]
    parts = addr.split(":")
    assert len(parts) == 6


def test_verify_matches_freshly_generated(capsys):
    irk = "0102030405060708090a0b0c0d0e0f10"
    _cmd_gen_rpa(argparse.Namespace(irk=irk))
    out = capsys.readouterr().out
    addr = [l for l in out.splitlines() if "/random" in l][0].split()[-1].split("/")[0]
    rc = _cmd_verify(argparse.Namespace(irk=irk, addr=addr))
    out2 = capsys.readouterr().out
    assert rc == 0
    assert "match" in out2.lower()
    assert "no match" not in out2.lower()


def test_verify_no_match_with_wrong_irk(capsys):
    irk1 = "0102030405060708090a0b0c0d0e0f10"
    irk2 = "ffffffffffffffffffffffffffffffff"
    _cmd_gen_rpa(argparse.Namespace(irk=irk1))
    out = capsys.readouterr().out
    addr = [l for l in out.splitlines() if "/random" in l][0].split()[-1].split("/")[0]
    rc = _cmd_verify(argparse.Namespace(irk=irk2, addr=addr))
    out2 = capsys.readouterr().out
    assert rc == 1
    assert "no match" in out2.lower()


def test_gen_rpa_invalid_irk_length(capsys):
    rc = _cmd_gen_rpa(argparse.Namespace(irk="aabb"))
    assert rc != 0
