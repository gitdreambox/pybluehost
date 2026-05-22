"""Unit tests for e2e_timeout(transport_mode, virtual=, usb=, uart=)."""
from __future__ import annotations

from tests.e2e._helpers import e2e_timeout


def test_e2e_timeout_virtual_returns_virtual_value():
    assert e2e_timeout("virtual", virtual=1.0) == 1.0
    assert e2e_timeout("virtual", virtual=0.5, usb=10.0) == 0.5


def test_e2e_timeout_usb_uses_usb_when_supplied():
    assert e2e_timeout("usb", virtual=1.0, usb=5.0) == 5.0


def test_e2e_timeout_usb_defaults_to_5x_virtual_when_not_supplied():
    assert e2e_timeout("usb", virtual=1.0) == 5.0
    assert e2e_timeout("usb", virtual=2.0) == 10.0


def test_e2e_timeout_uart_defaults_to_8x_virtual_when_not_supplied():
    assert e2e_timeout("uart", virtual=1.0) == 8.0


def test_e2e_timeout_unknown_transport_falls_back_to_virtual():
    assert e2e_timeout("tcp", virtual=1.0, usb=5.0) == 1.0
