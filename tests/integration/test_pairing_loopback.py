"""End-to-end Legacy Just Works pairing across two Stack.virtual() instances."""
from __future__ import annotations

import asyncio

from pybluehost.ble.smp import JsonBondStorage
from pybluehost.core.address import BDAddress
from pybluehost.hci.virtual_link import VirtualLELink
from pybluehost.stack import Stack, StackConfig

_CENTRAL_ADDR = BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A")
_PERIPHERAL_ADDR = BDAddress(b"\x0B\x0B\x0B\x0B\x0B\x0B")


async def test_two_virtual_stacks_pair_and_bond(tmp_path):
    """Initiator + Responder both reach BONDED + each side persists peer's keys."""
    storage_a = JsonBondStorage(tmp_path / "bonds_a.json")
    storage_b = JsonBondStorage(tmp_path / "bonds_b.json")
    cfg_a = StackConfig(bond_storage=storage_a, device_name="A")
    cfg_b = StackConfig(bond_storage=storage_b, device_name="B")
    # Give each virtual controller a distinct address so SMP c1 uses
    # distinct ia/ra values on both sides (confirm values will match).
    stack_a = await Stack.virtual(config=cfg_a, address=_CENTRAL_ADDR)
    stack_b = await Stack.virtual(config=cfg_b, address=_PERIPHERAL_ADDR)

    link = VirtualLELink(
        central=stack_a._virtual_controller,
        peripheral=stack_b._virtual_controller,
        central_address=_CENTRAL_ADDR,
        peripheral_address=_PERIPHERAL_ADDR,
    )
    handle = await link.connect()
    await asyncio.sleep(0.1)  # let LE_Connection_Complete propagate to both stacks

    await stack_a.pair(handle=handle, timeout=10.0)

    bond_a = await storage_a.load_bond(_PERIPHERAL_ADDR)
    bond_b = await storage_b.load_bond(_CENTRAL_ADDR)
    assert bond_a is not None and bond_a.ltk, "Central side didn't persist peer bond"
    assert bond_b is not None and bond_b.ltk, "Peripheral side didn't persist peer bond"

    await link.disconnect()
    await stack_a.close()
    await stack_b.close()


async def test_reconnect_auto_restores_encryption(tmp_path):
    """After initial bond, reconnecting an already-bonded peer triggers auto-encrypt
    without needing to re-pair."""
    storage_a = JsonBondStorage(tmp_path / "bonds_a.json")
    storage_b = JsonBondStorage(tmp_path / "bonds_b.json")

    # First connect + pair
    stack_a = await Stack.virtual(config=StackConfig(bond_storage=storage_a), address=_CENTRAL_ADDR)
    stack_b = await Stack.virtual(config=StackConfig(bond_storage=storage_b), address=_PERIPHERAL_ADDR)
    link = VirtualLELink(
        central=stack_a._virtual_controller,
        peripheral=stack_b._virtual_controller,
        central_address=_CENTRAL_ADDR,
        peripheral_address=_PERIPHERAL_ADDR,
    )
    await link.connect()
    await stack_a.pair(handle=link.handle, timeout=10.0)
    await link.disconnect()
    await stack_a.close()
    await stack_b.close()

    # Reconnect
    stack_a = await Stack.virtual(config=StackConfig(bond_storage=storage_a), address=_CENTRAL_ADDR)
    stack_b = await Stack.virtual(config=StackConfig(bond_storage=storage_b), address=_PERIPHERAL_ADDR)
    encrypted_seen: list = []
    stack_a.on_connection_event(
        lambda e: encrypted_seen.append(e) if getattr(e, "state", None) == "encrypted" else None
    )
    link = VirtualLELink(
        central=stack_a._virtual_controller,
        peripheral=stack_b._virtual_controller,
        central_address=_CENTRAL_ADDR,
        peripheral_address=_PERIPHERAL_ADDR,
    )
    await link.connect()
    for _ in range(20):
        if encrypted_seen:
            break
        await asyncio.sleep(0.05)
    assert encrypted_seen, "auto-encrypt did not fire on reconnect"

    await link.disconnect()
    await stack_a.close()
    await stack_b.close()
