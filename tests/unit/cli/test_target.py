import pytest
from pybluehost.cli._target import parse_target_arg
from pybluehost.core.address import BDAddress, AddressType


def test_parse_default_public():
    addr, atype = parse_target_arg("AA:BB:CC:DD:EE:FF")
    assert addr == BDAddress.from_string("AA:BB:CC:DD:EE:FF")
    assert atype == AddressType.PUBLIC


def test_parse_explicit_public():
    addr, atype = parse_target_arg("AA:BB:CC:DD:EE:FF/public")
    assert atype == AddressType.PUBLIC


def test_parse_compact_default_public():
    addr, atype = parse_target_arg("1A8D8D1BF56B")
    assert str(addr) == "1A:8D:8D:1B:F5:6B"
    assert atype == AddressType.PUBLIC


def test_parse_compact_random():
    addr, atype = parse_target_arg("1A8D8D1BF56B/random")
    assert str(addr) == "1A:8D:8D:1B:F5:6B"
    assert atype == AddressType.RANDOM
    assert addr.type == AddressType.RANDOM


def test_parse_random():
    addr, atype = parse_target_arg("AA:BB:CC:DD:EE:FF/random")
    assert atype == AddressType.RANDOM
    assert addr.type == AddressType.RANDOM


def test_parse_invalid_address_raises():
    with pytest.raises(ValueError):
        parse_target_arg("ZZZZZZ")


def test_parse_invalid_type_raises():
    with pytest.raises(ValueError, match="Unknown address type"):
        parse_target_arg("AA:BB:CC:DD:EE:FF/bogus")
