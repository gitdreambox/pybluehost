"""HSP-specific AT message builders + parsers (HSP v1.2 §4.7)."""
from __future__ import annotations

from pybluehost.profiles.classic._at_parser import (
    ATCommand, ATResponse, ATUnsolicited,
)
from pybluehost.profiles.classic._hsp_constants import (
    HSP_AT_CKPD, HSP_AT_VGM, HSP_AT_VGS, HSP_CKPD_KEY, HSP_GAIN_MAX,
)


def _validate_gain(gain: int) -> None:
    if not 0 <= gain <= HSP_GAIN_MAX:
        raise ValueError(f"gain {gain} out of range 0..{HSP_GAIN_MAX}")


def build_vgs_command(*, gain: int) -> ATCommand:
    _validate_gain(gain)
    return ATCommand(name=HSP_AT_VGS, kind="set", args=[str(gain)])


def parse_vgs_command(cmd: ATCommand) -> int:
    if cmd.name != HSP_AT_VGS or not cmd.args:
        raise ValueError(f"not a VGS command: {cmd}")
    return int(cmd.args[0])


def build_vgs_unsolicited(*, gain: int) -> ATUnsolicited:
    _validate_gain(gain)
    return ATUnsolicited(name=HSP_AT_VGS, args=[str(gain)])


def parse_vgs_unsolicited(msg: ATUnsolicited) -> int:
    if msg.name != HSP_AT_VGS or not msg.args:
        raise ValueError(f"not a VGS unsolicited: {msg}")
    return int(msg.args[0])


def build_vgm_command(*, gain: int) -> ATCommand:
    _validate_gain(gain)
    return ATCommand(name=HSP_AT_VGM, kind="set", args=[str(gain)])


def parse_vgm_command(cmd: ATCommand) -> int:
    if cmd.name != HSP_AT_VGM or not cmd.args:
        raise ValueError(f"not a VGM command: {cmd}")
    return int(cmd.args[0])


def build_vgm_unsolicited(*, gain: int) -> ATUnsolicited:
    _validate_gain(gain)
    return ATUnsolicited(name=HSP_AT_VGM, args=[str(gain)])


def parse_vgm_unsolicited(msg: ATUnsolicited) -> int:
    if msg.name != HSP_AT_VGM or not msg.args:
        raise ValueError(f"not a VGM unsolicited: {msg}")
    return int(msg.args[0])


def build_ckpd_command(*, keycode: int = HSP_CKPD_KEY) -> ATCommand:
    return ATCommand(name=HSP_AT_CKPD, kind="set", args=[str(keycode)])


def parse_ckpd_command(cmd: ATCommand) -> int:
    if cmd.name != HSP_AT_CKPD or not cmd.args:
        raise ValueError(f"not a CKPD command: {cmd}")
    return int(cmd.args[0])


def build_ring_unsolicited() -> ATUnsolicited:
    return ATUnsolicited(name="RING", args=[])
