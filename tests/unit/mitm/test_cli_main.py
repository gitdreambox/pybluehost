import argparse
from pybluehost.cli.app.mitm.cli import (
    build_relays_from_args, default_btsnoop_name, _select_delegate,
)
from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate, InteractiveNumericDelegate


def _args(**kw):
    base = dict(upstream="virtual", downstream="virtual", target="AA:BB:CC:DD:EE:FF",
                target_name=None, transport_mode="both", clone_address=False,
                btsnoop=None, pairing="just-works")
    base.update(kw)
    return argparse.Namespace(**base)


def test_default_btsnoop_name():
    n = default_btsnoop_name()
    assert n.endswith(".btsnoop") and "mitm" in n


def test_pairing_just_works_delegate():
    assert isinstance(_select_delegate("just-works"), AutoConfirmDelegate)


def test_pairing_numeric_delegate():
    assert isinstance(_select_delegate("numeric"), InteractiveNumericDelegate)


def test_both_mode_builds_le_and_bredr():
    specs = build_relays_from_args(_args(transport_mode="both"))
    assert {s.mode for s in specs} == {"le", "bredr"}


def test_le_mode_builds_one():
    specs = build_relays_from_args(_args(transport_mode="le"))
    assert [s.mode for s in specs] == ["le"]
