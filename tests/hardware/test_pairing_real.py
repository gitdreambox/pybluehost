"""Manual hardware verification of Legacy Just Works pairing.

Run as: uv run --frozen pytest tests/hardware/test_pairing_real.py --transport=usb

NOT run in CI. Requires:
- A real Bluetooth USB adapter
- An Android phone advertising a connectable BLE peripheral
- The user to confirm any phone-side pairing prompts

Default ``pytest.skip`` is in place — replace placeholder BD_ADDR before running.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.real_hardware_only(transport="usb")


@pytest.mark.asyncio
async def test_pair_with_android_phone(stack):
    """Scan, connect, pair Just Works, verify bond persisted."""
    pytest.skip(
        "Manual: edit this test with your phone's BD_ADDR before running locally."
    )
    # Example:
    # from pybluehost.core.address import BDAddress
    # peer = BDAddress(bytes.fromhex("AABBCCDDEEFF"))
    # gatt = await stack.connect_gatt(peer, timeout=15.0)
    # handle = stack._smp._peer_addrs and next(iter(stack._smp._peer_addrs.keys()))
    # await stack.pair(handle, timeout=30.0)
    # bond = await stack._smp._bond_storage.load_bond(peer)
    # assert bond is not None and bond.ltk
