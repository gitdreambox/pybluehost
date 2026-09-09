"""transform: ACL PDU regex replacement engine."""
from pybluehost.cli.app.mitm.acl import RelayDirection
from pybluehost.cli.app.mitm.transform import DEMO_RULES, RegexReplacer, ReplaceRule


def test_matches_and_replaces():
    r = RegexReplacer([ReplaceRule(pattern=b"WQ7035", repl=b"MITM7035")])
    out = r(RelayDirection.PHONE_TO_TARGET, 0x0040, b"hello WQ7035!")
    assert out == b"hello MITM7035!"


def test_no_match_returns_original_bytes():
    r = RegexReplacer([ReplaceRule(pattern=b"XYZZY", repl=b"A")])
    payload = bytes(range(32))
    assert r(RelayDirection.TARGET_TO_PHONE, 0x0040, payload) == payload


def test_direction_filter():
    r = RegexReplacer([ReplaceRule(pattern=b"ab", repl=b"X",
                                   direction=RelayDirection.PHONE_TO_TARGET)])
    assert r(RelayDirection.PHONE_TO_TARGET, 0x0040, b"ab") == b"X"
    assert r(RelayDirection.TARGET_TO_PHONE, 0x0040, b"ab") == b"ab"


def test_cid_filter():
    r = RegexReplacer([ReplaceRule(pattern=b"ab", repl=b"X", cid=0x0004)])
    assert r(RelayDirection.PHONE_TO_TARGET, 0x0004, b"ab") == b"X"
    assert r(RelayDirection.PHONE_TO_TARGET, 0x0001, b"ab") == b"ab"


def test_backreference_supported():
    r = RegexReplacer([ReplaceRule(pattern=b"((ab)+)", repl=b"\\g<1>!")])
    assert r(RelayDirection.PHONE_TO_TARGET, 0x0040, b"abab") == b"abab!"


def test_demo_rules_default_empty():
    """Default rules are empty: once a session attaches transform, overhead ≈0 and behavior is identity."""
    assert DEMO_RULES == []
