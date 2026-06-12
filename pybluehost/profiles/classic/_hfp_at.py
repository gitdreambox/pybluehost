"""HFP-specific AT command builders + parsers (HFP v1.8 §4.34).

Wraps the generic _at_parser ATCommand / ATResponse / ATUnsolicited types with
typed accessors for each SLC-relevant message: BRSF, BAC, CIND, CMER, CIEV, BCS.
"""
from __future__ import annotations

from pybluehost.profiles.classic._at_parser import (
    ATCommand, ATResponse, ATUnsolicited,
)
from pybluehost.profiles.classic._hfp_constants import HFPCodecID


# --- AT+BRSF / +BRSF ----------------------------------------------------------

def build_brsf_command(hf_features: int) -> ATCommand:
    return ATCommand(name="+BRSF", kind="set", args=[str(int(hf_features))])


def parse_brsf_command(cmd: ATCommand) -> int:
    if cmd.name != "+BRSF" or not cmd.args:
        raise ValueError(f"not a BRSF command: {cmd}")
    return int(cmd.args[0])


def build_brsf_response(ag_features: int) -> ATResponse:
    return ATResponse(name="+BRSF", args=[str(int(ag_features))])


def parse_brsf_response(resp: ATResponse) -> int:
    if resp.name != "+BRSF" or not resp.args:
        raise ValueError(f"not a BRSF response: {resp}")
    return int(resp.args[0])


# --- AT+BAC ------------------------------------------------------------------

def build_bac_command(codecs: list[int]) -> ATCommand:
    return ATCommand(name="+BAC", kind="set", args=[str(int(c)) for c in codecs])


def parse_bac_command(cmd: ATCommand) -> list[HFPCodecID]:
    if cmd.name != "+BAC":
        raise ValueError(f"not a BAC command: {cmd}")
    return [HFPCodecID(int(a)) for a in cmd.args]


# --- AT+CIND=? / +CIND: (test) ----------------------------------------------

def build_cind_test_response(
    indicators: list[tuple[str, tuple[int, int]]],
) -> ATResponse:
    """Format: +CIND: ("service",(0,1)),("call",(0,1)),("callsetup",(0,3))..."""
    parts = []
    for name, (lo, hi) in indicators:
        parts.append(f'("{name}",({lo},{hi}))')
    blob = ",".join(parts)
    return ATResponse(name="+CIND", args=[blob])


def parse_cind_test_response(resp: ATResponse) -> list[tuple[str, tuple[int, int]]]:
    """Inverse of build_cind_test_response."""
    if resp.name != "+CIND" or not resp.args:
        raise ValueError(f"not a CIND test response: {resp}")
    blob = ",".join(resp.args)
    out: list[tuple[str, tuple[int, int]]] = []
    # Parse a sequence of ("name",(lo,hi)) tuples.
    i = 0
    s = blob
    while i < len(s):
        if s[i] != "(":
            i += 1
            continue
        # find matching closing paren
        depth = 0
        j = i
        while j < len(s):
            if s[j] == "(":
                depth += 1
            elif s[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        entry = s[i + 1:j]    # without outer parens
        # entry looks like: "name",(lo,hi)
        name_end = entry.index(",")
        name = entry[:name_end].strip().strip('"')
        rng_str = entry[name_end + 1:].strip().strip("()")
        lo_s, hi_s = rng_str.split(",")
        out.append((name, (int(lo_s.strip()), int(hi_s.strip()))))
        i = j + 1
    return out


# --- AT+CIND? / +CIND: (read) -----------------------------------------------

def build_cind_read_response(
    values: dict[str, int], *, ordering: list[str],
) -> ATResponse:
    """Format: +CIND: <v0>,<v1>,<v2>... in the order given by `ordering`."""
    return ATResponse(name="+CIND", args=[str(int(values[k])) for k in ordering])


def parse_cind_read_response(
    resp: ATResponse, *, ordering: list[str],
) -> dict[str, int]:
    if resp.name != "+CIND":
        raise ValueError(f"not a CIND read response: {resp}")
    return {k: int(v) for k, v in zip(ordering, resp.args)}


# --- AT+CMER ----------------------------------------------------------------

def build_cmer_command(*, mode: int, ind_reporting: int) -> ATCommand:
    """AT+CMER=<mode>,0,0,<ind>. Plan A.4 always uses mode=3, ind=1 to subscribe."""
    return ATCommand(
        name="+CMER", kind="set",
        args=[str(mode), "0", "0", str(ind_reporting)],
    )


def parse_cmer_command(cmd: ATCommand) -> tuple[int, int]:
    if cmd.name != "+CMER" or len(cmd.args) < 4:
        raise ValueError(f"not a CMER command: {cmd}")
    return int(cmd.args[0]), int(cmd.args[3])


# --- +CIEV ------------------------------------------------------------------

def build_ciev_unsolicited(*, index: int, value: int) -> ATUnsolicited:
    return ATUnsolicited(name="+CIEV", args=[str(index), str(value)])


def parse_ciev_unsolicited(msg: ATUnsolicited) -> tuple[int, int]:
    if msg.name != "+CIEV" or len(msg.args) < 2:
        raise ValueError(f"not a CIEV message: {msg}")
    return int(msg.args[0]), int(msg.args[1])


# --- +BCS / AT+BCS ----------------------------------------------------------

def build_bcs_unsolicited(codec: int) -> ATUnsolicited:
    return ATUnsolicited(name="+BCS", args=[str(int(codec))])


def parse_bcs_unsolicited(msg: ATUnsolicited) -> HFPCodecID:
    if msg.name != "+BCS" or not msg.args:
        raise ValueError(f"not a BCS message: {msg}")
    return HFPCodecID(int(msg.args[0]))


def build_bcs_command(codec: int) -> ATCommand:
    return ATCommand(name="+BCS", kind="set", args=[str(int(codec))])


def parse_bcs_command(cmd: ATCommand) -> HFPCodecID:
    if cmd.name != "+BCS" or not cmd.args:
        raise ValueError(f"not a BCS command: {cmd}")
    return HFPCodecID(int(cmd.args[0]))
