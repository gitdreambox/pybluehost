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
    with pytest.raises(ValueError, match="Invalid usb bus value: 'one'"):
        await parse_transport_arg("usb:vendor=intel,bus=one")


@pytest.mark.asyncio
async def test_parse_usb_invalid_address_raises_value_error():
    with pytest.raises(ValueError, match="Invalid usb address value: 'four'"):
        await parse_transport_arg("usb:vendor=intel,address=four")


@pytest.mark.asyncio
async def test_parse_usb_duplicate_key_raises_value_error():
    with pytest.raises(ValueError, match="Duplicate usb spec key: 'vendor'"):
        await parse_transport_arg("usb:vendor=intel,vendor=realtek")


@pytest.mark.asyncio
async def test_parse_usb_malformed_token_raises_value_error():
    with pytest.raises(ValueError, match="Malformed usb spec token: 'bus'"):
        await parse_transport_arg("usb:vendor=intel,bus,address=4")


@pytest.mark.asyncio
async def test_parse_usb_empty_key_raises_value_error():
    with pytest.raises(ValueError, match="Empty usb spec key"):
        await parse_transport_arg("usb:=1")


@pytest.mark.asyncio
async def test_parse_usb_empty_vendor_raises_value_error():
    with pytest.raises(ValueError, match="Empty usb vendor value"):
        await parse_transport_arg("usb:vendor=,bus=1")


@pytest.mark.asyncio
async def test_parse_usb_empty_bus_raises_value_error():
    with pytest.raises(ValueError, match="Empty usb bus value"):
        await parse_transport_arg("usb:vendor=intel,bus=,address=4")


@pytest.mark.asyncio
async def test_parse_usb_empty_address_raises_value_error():
    with pytest.raises(ValueError, match="Empty usb address value"):
        await parse_transport_arg("usb:vendor=intel,address=")


@pytest.mark.parametrize(
    "spec",
    [
        "usb:",
        "usb:vendor=intel,",
        "usb:vendor=intel,,bus=1",
        "usb:=intel",
        "usb:vendor",
        "usb:vendor:intel",
        "usb:vendor=intel,bus",
        "usb:vendor=intel,bus=",
        "usb:vendor=intel,address=",
        "usb:vendor=intel,vendor=realtek",
        "usb:bus=1,bus=2",
        "usb:address=4,address=5",
    ],
)
@pytest.mark.asyncio
async def test_cli_rejects_same_empty_duplicate_malformed_usb_tokens_as_helper(spec):
    from tests._transport_select import InvalidSpec, parse_spec

    with pytest.raises(InvalidSpec):
        parse_spec(spec)
    with pytest.raises(ValueError):
        await parse_transport_arg(spec)
