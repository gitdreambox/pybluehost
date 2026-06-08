import pytest

from pybluehost.cli._sniffer_arg import SnifferSpec, parse_sniffer_arg


def test_parse_bare_ellisys():
    s = parse_sniffer_arg("ellisys")
    assert s == SnifferSpec(backend="ellisys", options={})


def test_parse_bare_wps():
    s = parse_sniffer_arg("wps")
    assert s == SnifferSpec(backend="wps", options={})


def test_parse_ellisys_with_ports():
    s = parse_sniffer_arg("ellisys:tcp=46148,udp=24352")
    assert s.backend == "ellisys"
    assert s.options == {"tcp": "46148", "udp": "24352"}


def test_parse_wps_with_path():
    s = parse_sniffer_arg("wps:wps-path=C:\\WPS")
    assert s.backend == "wps"
    assert s.options == {"wps-path": "C:\\WPS"}


def test_unknown_backend_raises():
    with pytest.raises(ValueError, match="unknown sniffer backend"):
        parse_sniffer_arg("kismet")


def test_empty_string_raises():
    with pytest.raises(ValueError, match="empty"):
        parse_sniffer_arg("")


def test_malformed_option_raises():
    with pytest.raises(ValueError, match="malformed option"):
        parse_sniffer_arg("ellisys:tcpnoequals")
