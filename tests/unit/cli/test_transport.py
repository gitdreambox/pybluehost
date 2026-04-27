import pytest
from unittest.mock import patch, MagicMock

from pybluehost.cli._transport import parse_transport_arg
from pybluehost.transport.base import Transport
from pybluehost.transport.uart import UARTTransport


async def test_parse_virtual():
    t = await parse_transport_arg("virtual")
    assert isinstance(t, Transport)
    assert t.is_open


async def test_parse_virtual_full_stack_works():
    """Verify virtual transport from parse_transport_arg can drive a full Stack."""
    from pybluehost.stack import Stack

    transport = await parse_transport_arg("virtual")
    stack = await Stack._build(transport=transport)
    assert stack.is_powered
    await stack.close()


async def test_parse_uart_default_baud():
    t = await parse_transport_arg("uart:/dev/ttyUSB0")
    assert isinstance(t, UARTTransport)
    assert t._port == "/dev/ttyUSB0"
    assert t._baudrate == 115200


async def test_parse_uart_custom_baud():
    t = await parse_transport_arg("uart:/dev/ttyUSB0@921600")
    assert isinstance(t, UARTTransport)
    assert t._baudrate == 921600


async def test_parse_unknown_raises():
    with pytest.raises(ValueError, match="Unknown transport"):
        await parse_transport_arg("foo")


async def test_parse_uart_missing_port_raises():
    with pytest.raises(ValueError, match="UART port required"):
        await parse_transport_arg("uart:")


async def test_parse_usb_plain():
    mock_t = MagicMock()
    with patch("pybluehost.transport.usb.USBTransport.auto_detect", return_value=mock_t) as m:
        result = await parse_transport_arg("usb")
        m.assert_called_once_with(vendor=None, bus=None, address=None)
    assert result is mock_t


async def test_parse_usb_vendor():
    mock_t = MagicMock()
    with patch("pybluehost.transport.usb.USBTransport.auto_detect", return_value=mock_t) as m:
        result = await parse_transport_arg("usb:vendor=intel")
        m.assert_called_once_with(vendor="intel", bus=None, address=None)
    assert result is mock_t
