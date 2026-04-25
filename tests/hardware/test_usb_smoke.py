"""Hardware tests — requires real USB Bluetooth adapter. Run with: pytest --hardware"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.hardware


async def test_usb_stack_powers_on(hardware_required):
    """Full stack on real hardware: power on, read BD_ADDR."""
    from pybluehost.stack import Stack

    stack = await Stack.from_usb()
    try:
        assert stack.is_powered
        addr = stack.local_address
        assert addr is not None
        assert str(addr) != "00:00:00:00:00:00"
    finally:
        await stack.close()


async def test_usb_stack_reset(hardware_required):
    """Power off and on should restore is_powered."""
    from pybluehost.stack import Stack

    stack = await Stack.from_usb()
    try:
        await stack.power_off()
        assert not stack.is_powered
        await stack.power_on()
        assert stack.is_powered
    finally:
        await stack.close()
