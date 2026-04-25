import pytest
from pybluehost.cli._transport import parse_transport_arg
from pybluehost.transport.loopback import LoopbackTransport
from pybluehost.transport.uart import UARTTransport


def test_parse_loopback():
    t = parse_transport_arg("loopback")
    assert isinstance(t, LoopbackTransport)


def test_parse_uart_default_baud():
    t = parse_transport_arg("uart:/dev/ttyUSB0")
    assert isinstance(t, UARTTransport)
    assert t._port == "/dev/ttyUSB0"
    assert t._baudrate == 115200


def test_parse_uart_custom_baud():
    t = parse_transport_arg("uart:/dev/ttyUSB0@921600")
    assert isinstance(t, UARTTransport)
    assert t._baudrate == 921600


def test_parse_unknown_raises():
    with pytest.raises(ValueError, match="Unknown transport"):
        parse_transport_arg("foo")


def test_parse_uart_missing_port_raises():
    with pytest.raises(ValueError, match="UART port required"):
        parse_transport_arg("uart:")
