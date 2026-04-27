"""parse_transport_arg recognizes usb bus= and address= keys."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pybluehost.cli._transport import parse_transport_arg


@pytest.mark.asyncio
async def test_parse_usb_with_bus_and_address_passes_kwargs():
    fake_transport = MagicMock()
    with patch(
        "pybluehost.transport.usb.USBTransport.auto_detect",
        return_value=fake_transport,
    ) as auto_detect:
        result = await parse_transport_arg("usb:vendor=intel,bus=1,address=4")

    assert result is fake_transport
    auto_detect.assert_called_once_with(vendor="intel", bus=1, address=4)


@pytest.mark.asyncio
async def test_parse_usb_vendor_without_bus_address_passes_none():
    fake_transport = MagicMock()
    with patch(
        "pybluehost.transport.usb.USBTransport.auto_detect",
        return_value=fake_transport,
    ) as auto_detect:
        result = await parse_transport_arg("usb:vendor=intel")

    assert result is fake_transport
    auto_detect.assert_called_once_with(vendor="intel", bus=None, address=None)


@pytest.mark.asyncio
async def test_parse_usb_strips_key_and_value_whitespace():
    fake_transport = MagicMock()
    with patch(
        "pybluehost.transport.usb.USBTransport.auto_detect",
        return_value=fake_transport,
    ) as auto_detect:
        result = await parse_transport_arg("usb: vendor = intel , bus = 1 , address = 4 ")

    assert result is fake_transport
    auto_detect.assert_called_once_with(vendor="intel", bus=1, address=4)


@pytest.mark.asyncio
async def test_parse_usb_unknown_key_raises_value_error():
    with pytest.raises(ValueError, match="Unknown usb spec key: 'serial'"):
        await parse_transport_arg("usb:vendor=intel,serial=abc")


@pytest.mark.asyncio
async def test_parse_usb_invalid_bus_raises_value_error():
    with pytest.raises(ValueError, match="invalid literal"):
        await parse_transport_arg("usb:vendor=intel,bus=one")


@pytest.mark.asyncio
async def test_parse_usb_invalid_address_raises_value_error():
    with pytest.raises(ValueError, match="invalid literal"):
        await parse_transport_arg("usb:vendor=intel,address=four")
