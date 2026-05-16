"""Stack.encrypt(handle) waits for HCI_Encryption_Change event."""
from __future__ import annotations

import asyncio

import pytest

from pybluehost.ble.smp import BondInfo, JsonBondStorage
from pybluehost.core.address import BDAddress
from pybluehost.stack import Stack, StackConfig


async def test_encrypt_resolves_on_encryption_change_success(tmp_path):
    """Stack.encrypt completes when HCI emits Encryption_Change(status=0, enabled=1).

    The virtual controller auto-emits a success Encryption_Change, so this
    test verifies that Stack.encrypt waits for and properly resolves on that event.
    """
    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))

    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        # Bind peer address so encrypt() can find it
        stack._smp._peer_addrs[0x0040] = peer  # NOTE: read-side direct access; FU Task 4 adds setter

        # Virtual controller auto-emits Encryption_Change(success) after send_command,
        # so encrypt() should complete without a manual emitter.
        await asyncio.wait_for(stack.encrypt(0x0040, timeout=1.0), timeout=2.0)
    finally:
        await stack.close()


async def test_encrypt_raises_on_encryption_change_failed(tmp_path, monkeypatch):
    """Stack.encrypt raises RuntimeError if HCI emits Encryption_Change(status != 0).

    Uses monkeypatch to make send_command a no-op so the virtual controller does
    not auto-emit a success event; instead we inject a failure event manually.
    """
    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))

    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        stack._smp._peer_addrs[0x0040] = peer

        # Prevent the virtual controller from auto-emitting a success event.
        async def _noop_send_command(cmd):
            return None

        monkeypatch.setattr(stack._hci, "send_command", _noop_send_command)

        async def _emit_failure():
            await asyncio.sleep(0.01)
            await stack._on_encryption_change(0x0040, status=0x06, enabled=0)

        emitter = asyncio.create_task(_emit_failure())
        with pytest.raises(RuntimeError, match="encryption"):
            await stack.encrypt(0x0040, timeout=1.0)
        await emitter
    finally:
        await stack.close()
