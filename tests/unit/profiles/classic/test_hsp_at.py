import pytest

from pybluehost.profiles.classic._at_parser import (
    ATCommand, ATResponse, ATUnsolicited,
)
from pybluehost.profiles.classic._hsp_at import (
    build_vgs_command, parse_vgs_command,
    build_vgs_unsolicited, parse_vgs_unsolicited,
    build_vgm_command, parse_vgm_command,
    build_vgm_unsolicited, parse_vgm_unsolicited,
    build_ckpd_command, parse_ckpd_command,
    build_ring_unsolicited,
)
from pybluehost.profiles.classic._hsp_constants import HSP_CKPD_KEY


def test_vgs_command_round_trip():
    cmd = build_vgs_command(gain=7)
    assert isinstance(cmd, ATCommand)
    assert cmd.name == "+VGS"
    assert cmd.kind == "set"
    assert cmd.args == ["7"]
    assert parse_vgs_command(cmd) == 7


def test_vgs_command_rejects_out_of_range():
    with pytest.raises(ValueError, match="gain"):
        build_vgs_command(gain=16)
    with pytest.raises(ValueError, match="gain"):
        build_vgs_command(gain=-1)


def test_vgs_unsolicited_round_trip():
    msg = build_vgs_unsolicited(gain=12)
    assert isinstance(msg, ATUnsolicited)
    assert msg.name == "+VGS"
    assert msg.args == ["12"]
    assert parse_vgs_unsolicited(msg) == 12


def test_vgm_command_round_trip():
    cmd = build_vgm_command(gain=4)
    assert cmd.name == "+VGM"
    assert cmd.kind == "set"
    assert cmd.args == ["4"]
    assert parse_vgm_command(cmd) == 4


def test_vgm_unsolicited_round_trip():
    msg = build_vgm_unsolicited(gain=15)
    assert isinstance(msg, ATUnsolicited)
    assert msg.name == "+VGM"
    assert parse_vgm_unsolicited(msg) == 15


def test_ckpd_command_default_key():
    cmd = build_ckpd_command()
    assert cmd.name == "+CKPD"
    assert cmd.kind == "set"
    assert cmd.args == [str(HSP_CKPD_KEY)]
    assert parse_ckpd_command(cmd) == HSP_CKPD_KEY


def test_ckpd_command_custom_keycode():
    cmd = build_ckpd_command(keycode=300)
    assert cmd.args == ["300"]
    assert parse_ckpd_command(cmd) == 300


def test_ring_unsolicited():
    msg = build_ring_unsolicited()
    assert isinstance(msg, ATUnsolicited)
    assert msg.name == "RING"
    assert msg.args == []
