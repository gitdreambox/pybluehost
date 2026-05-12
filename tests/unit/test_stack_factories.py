"""Stack.from_usb() and Stack.from_uart() factory methods."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pybluehost.stack import Stack, StackConfig, StackMode


@pytest.mark.asyncio
async def test_from_usb_calls_auto_detect_with_filters():
    fake_transport = MagicMock()
    fake_transport.open = AsyncMock()
    config = StackConfig(device_name="USB")

    with patch(
        "pybluehost.transport.usb.USBTransport.auto_detect",
        return_value=fake_transport,
    ) as auto_detect:
        with patch.object(
            Stack,
            "_build",
            new=AsyncMock(return_value=MagicMock(spec=Stack)),
        ) as build:
            await Stack.from_usb(vendor="intel", bus=1, address=4, config=config)

    auto_detect.assert_called_once_with(
        vendor="intel",
        bus=1,
        address=4,
        vid=None,
        pid=None,
        serial=None,
        occurrence=None,
    )
    fake_transport.open.assert_awaited_once()
    build.assert_awaited_once_with(fake_transport, config, StackMode.LIVE)


@pytest.mark.asyncio
async def test_from_usb_calls_auto_detect_with_transport_name_identity():
    fake_transport = MagicMock()
    fake_transport.open = AsyncMock()

    with patch(
        "pybluehost.transport.usb.USBTransport.auto_detect",
        return_value=fake_transport,
    ) as auto_detect:
        with patch.object(
            Stack,
            "_build",
            new=AsyncMock(return_value=MagicMock(spec=Stack)),
        ):
            await Stack.from_usb(vid=0x0A12, pid=0x0001, occurrence=2)

    auto_detect.assert_called_once_with(
        vendor=None,
        bus=None,
        address=None,
        vid=0x0A12,
        pid=0x0001,
        serial=None,
        occurrence=2,
    )


@pytest.mark.asyncio
async def test_from_usb_closes_transport_when_build_fails():
    fake_transport = MagicMock()
    fake_transport.open = AsyncMock()
    fake_transport.close = AsyncMock()
    error = RuntimeError("build failed")

    with patch(
        "pybluehost.transport.usb.USBTransport.auto_detect",
        return_value=fake_transport,
    ):
        with patch.object(Stack, "_build", new=AsyncMock(side_effect=error)):
            with pytest.raises(RuntimeError, match="build failed"):
                await Stack.from_usb(vendor="intel")

    fake_transport.open.assert_awaited_once()
    fake_transport.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_from_uart_constructs_uart_transport():
    fake_transport = MagicMock()
    fake_transport.open = AsyncMock()
    config = StackConfig(device_name="UART")

    with patch(
        "pybluehost.transport.uart.UARTTransport",
        return_value=fake_transport,
    ) as ctor:
        with patch.object(
            Stack,
            "_build",
            new=AsyncMock(return_value=MagicMock(spec=Stack)),
        ) as build:
            await Stack.from_uart(port="/dev/ttyUSB0", baudrate=921600, config=config)

    ctor.assert_called_once_with(port="/dev/ttyUSB0", baudrate=921600)
    fake_transport.open.assert_awaited_once()
    build.assert_awaited_once_with(fake_transport, config, StackMode.LIVE)


@pytest.mark.asyncio
async def test_from_uart_closes_transport_when_build_fails():
    fake_transport = MagicMock()
    fake_transport.open = AsyncMock()
    fake_transport.close = AsyncMock()
    error = RuntimeError("build failed")

    with patch(
        "pybluehost.transport.uart.UARTTransport",
        return_value=fake_transport,
    ):
        with patch.object(Stack, "_build", new=AsyncMock(side_effect=error)):
            with pytest.raises(RuntimeError, match="build failed"):
                await Stack.from_uart(port="/dev/ttyUSB0")

    fake_transport.open.assert_awaited_once()
    fake_transport.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_loopback_is_alias_for_virtual():
    """PRD §5.7 reserves the name Stack.loopback(); virtual() is the impl."""
    from pybluehost.stack import Stack, StackMode

    stack = await Stack.loopback()
    try:
        assert stack.mode == StackMode.VIRTUAL
        assert stack.is_powered is True
    finally:
        await stack.close()


@pytest.mark.asyncio
async def test_build_factory_uses_provided_transport():
    """Stack.build(transport) wires arbitrary transport through _build."""
    from pybluehost.hci.virtual import VirtualController
    from pybluehost.stack import Stack, StackMode

    vc, host_transport = await VirtualController.create()
    stack = await Stack.build(host_transport, mode=StackMode.VIRTUAL)
    try:
        assert stack.mode == StackMode.VIRTUAL
        assert stack._transport is host_transport
    finally:
        await stack.close()
