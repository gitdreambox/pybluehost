"""End-to-end LE Secure Connections Just Works pairing via VirtualLELink."""
from __future__ import annotations

import asyncio

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import JsonBondStorage
from pybluehost.core.address import BDAddress
from pybluehost.hci.virtual_link import VirtualLELink
from pybluehost.stack import Stack, StackConfig


async def test_two_virtual_stacks_pair_with_sc_just_works(tmp_path):
    """Both sides complete SC Just Works → BondInfo persisted with sc=True; LTKs match."""
    storage_a = JsonBondStorage(tmp_path / "bonds_a.json")
    storage_b = JsonBondStorage(tmp_path / "bonds_b.json")
    cfg_a = StackConfig(
        bond_storage=storage_a,
        security=SecurityConfig(enable_secure_connections=True),
        device_name="A",
    )
    cfg_b = StackConfig(
        bond_storage=storage_b,
        security=SecurityConfig(enable_secure_connections=True),
        device_name="B",
    )
    central_addr = BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A")
    peripheral_addr = BDAddress(b"\x0B\x0B\x0B\x0B\x0B\x0B")
    stack_a = await Stack.virtual(config=cfg_a, address=central_addr)
    stack_b = await Stack.virtual(config=cfg_b, address=peripheral_addr)

    link = VirtualLELink(
        central=stack_a._virtual_controller,
        peripheral=stack_b._virtual_controller,
        central_address=central_addr,
        peripheral_address=peripheral_addr,
    )
    handle = await link.connect()
    await asyncio.sleep(0.1)

    await stack_a.pair(handle=handle, timeout=20.0)

    bond_a = await storage_a.load_bond(peripheral_addr)
    bond_b = await storage_b.load_bond(central_addr)
    assert bond_a is not None and bond_a.sc is True, f"Central bond.sc must be True; got {bond_a}"
    assert bond_b is not None and bond_b.sc is True, f"Peripheral bond.sc must be True; got {bond_b}"
    # f5 LTK is identical on both sides
    assert bond_a.ltk == bond_b.ltk, "f5-derived LTK must be identical on both sides"
    # Just Works → unauthenticated
    assert bond_a.authenticated is False
    assert bond_b.authenticated is False

    await link.disconnect()
    await stack_a.close()
    await stack_b.close()


async def test_sc_reconnect_auto_restores_encryption(tmp_path):
    """After SC initial bond, reconnect auto-encrypts with the f5-derived LTK."""
    storage_a = JsonBondStorage(tmp_path / "bonds_a.json")
    storage_b = JsonBondStorage(tmp_path / "bonds_b.json")
    central_addr = BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A")
    peripheral_addr = BDAddress(b"\x0B\x0B\x0B\x0B\x0B\x0B")

    # First connect + pair
    stack_a = await Stack.virtual(
        config=StackConfig(bond_storage=storage_a, security=SecurityConfig(enable_secure_connections=True)),
        address=central_addr,
    )
    stack_b = await Stack.virtual(
        config=StackConfig(bond_storage=storage_b, security=SecurityConfig(enable_secure_connections=True)),
        address=peripheral_addr,
    )
    link = VirtualLELink(
        central=stack_a._virtual_controller, peripheral=stack_b._virtual_controller,
        central_address=central_addr, peripheral_address=peripheral_addr,
    )
    await link.connect()
    await stack_a.pair(handle=link.handle, timeout=20.0)
    await link.disconnect()
    await stack_a.close()
    await stack_b.close()

    # Reconnect — auto-encrypt path should fire
    stack_a = await Stack.virtual(
        config=StackConfig(bond_storage=storage_a, security=SecurityConfig(enable_secure_connections=True)),
        address=central_addr,
    )
    stack_b = await Stack.virtual(
        config=StackConfig(bond_storage=storage_b, security=SecurityConfig(enable_secure_connections=True)),
        address=peripheral_addr,
    )
    encrypted_seen: list = []
    stack_a.on_connection_event(
        lambda e: encrypted_seen.append(e) if getattr(e, "state", None) == "encrypted" else None
    )
    link = VirtualLELink(
        central=stack_a._virtual_controller, peripheral=stack_b._virtual_controller,
        central_address=central_addr, peripheral_address=peripheral_addr,
    )
    await link.connect()
    for _ in range(20):
        if encrypted_seen:
            break
        await asyncio.sleep(0.05)
    assert encrypted_seen, "auto-encrypt did not fire on SC reconnect"

    await link.disconnect()
    await stack_a.close()
    await stack_b.close()
