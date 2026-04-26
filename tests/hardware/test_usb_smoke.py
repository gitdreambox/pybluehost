"""Hardware tests — requires real USB Bluetooth adapter. Run with: pytest --hardware"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.hardware


async def test_usb_stack_lifecycle(hardware_required):
    """Full stack on real hardware: power on, read BD_ADDR, reset cycle."""
    from pybluehost.stack import Stack

    stack = await Stack.from_usb(vendor="csr")
    try:
        # Power on / init
        assert stack.is_powered
        addr = stack.local_address
        assert addr is not None
        assert str(addr) != "00:00:00:00:00:00"
        print(f"\n  [PASS] USB stack powered on, BD_ADDR={addr}")

        # Power off
        await stack.power_off()
        assert not stack.is_powered
        print("  [PASS] USB stack powered off")

        # Power on again
        await stack.power_on()
        assert stack.is_powered
        print("  [PASS] USB stack reset OK")
    finally:
        await stack.close()
