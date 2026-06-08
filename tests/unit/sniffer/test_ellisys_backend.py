import pytest

from pybluehost.sniffer.ellisys import EllisysBackend


def test_ellisys_backend_defaults():
    b = EllisysBackend()
    assert b.host == "127.0.0.1"
    assert b.udp_port == 24352
    assert b.tcp_port == 46148
    assert b.skip_launch is False


def test_ellisys_backend_overrides():
    b = EllisysBackend(host="192.168.0.5", udp_port=24400, tcp_port=46200, skip_launch=True)
    assert b.host == "192.168.0.5"
    assert b.udp_port == 24400
    assert b.tcp_port == 46200
    assert b.skip_launch is True
