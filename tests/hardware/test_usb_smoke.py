"""Smoke tests on real USB hardware (any vendor) via the stack fixture."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.real_hardware_only(transport="usb")


@pytest.mark.asyncio
async def test_usb_stack_powers_on(stack):
    """Full stack on real hardware: powered, has BD_ADDR."""
    assert stack.is_powered
    assert stack.local_address is not None
    assert str(stack.local_address) != "00:00:00:00:00:00"


@pytest.mark.asyncio
async def test_usb_stack_reset(stack):
    """power_off / power_on round-trip restores is_powered."""
    await stack.power_off()
    assert not stack.is_powered
    await stack.power_on()
    assert stack.is_powered
