"""Classic E2E smoke: two Stack.virtual() instances bridged by VirtualClassicLink
complete inquiry -> connect -> SSP Just Works pair -> encrypt -> disconnect.

Counterpart to the per-primitive bridge tests in test_virtual_classic_link.py: this
exercises the bridge through the real host-side public API (ClassicDiscovery /
ClassicDiscoverability / Stack.connect_classic / SSPManager / BondStorage) end-to-end.
"""
from __future__ import annotations

import asyncio

import pytest

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import JsonBondStorage
from pybluehost.core.address import BDAddress
from pybluehost.hci.virtual_classic_link import VirtualClassicLink
from pybluehost.stack import Stack, StackConfig


@pytest.mark.e2e
async def test_classic_inquiry_connect_ssp_jw_pair_disconnect(tmp_path):
    """End-to-end smoke: two Stack.virtual() instances bridged by VirtualClassicLink
    complete the canonical Classic flow."""
    storage_c = JsonBondStorage(tmp_path / "bonds_c.json")
    storage_p = JsonBondStorage(tmp_path / "bonds_p.json")
    cfg_c = StackConfig(
        bond_storage=storage_c,
        security=SecurityConfig(enable_secure_connections=False),
    )
    cfg_p = StackConfig(
        bond_storage=storage_p,
        security=SecurityConfig(enable_secure_connections=False),
    )
    central_addr = BDAddress.from_string("0A:0A:0A:0A:0A:0A")
    peripheral_addr = BDAddress.from_string("0B:0B:0B:0B:0B:0B")

    stack_c = await Stack.virtual(config=cfg_c, address=central_addr)
    stack_p = await Stack.virtual(config=cfg_p, address=peripheral_addr)

    link = VirtualClassicLink(
        central=stack_c._virtual_controller,
        peripheral=stack_p._virtual_controller,
        central_address=central_addr,
        peripheral_address=peripheral_addr,
        page_timeout_seconds=0.5,
    )
    link.attach()

    try:
        # --- Step 1: Peripheral becomes discoverable + connectable --------------
        await stack_p.gap.classic_discoverability.set_connectable(True)
        await stack_p.gap.classic_discoverability.set_discoverable(True)
        await asyncio.sleep(0.05)

        # --- Step 2: Central performs inquiry -----------------------------------
        discovered: list[BDAddress] = []

        def _on_inquiry_result(info) -> None:
            discovered.append(info.address)

        stack_c.gap.classic_discovery.on_result(_on_inquiry_result)
        await stack_c.gap.classic_discovery.start()
        # Bridge emits Inquiry_Result + Inquiry_Complete synchronously after start.
        await asyncio.sleep(0.1)
        assert peripheral_addr in discovered, (
            f"peripheral not discovered: {discovered}"
        )

        # --- Step 3: Central connects ------------------------------------------
        handle = await stack_c.connect_classic(peripheral_addr, timeout=2.0)
        assert handle != 0, "expected non-zero ACL handle"

        # --- Step 4: SSP Just Works pairing ------------------------------------
        # SSPManager defaults to IO capability 0x03 (NoInputNoOutput) and
        # auto-accepts USER_CONFIRMATION_REQUEST (no delegate or sync handler set),
        # which corresponds to Just Works on both sides.
        await stack_c.authenticate_classic(handle, timeout=2.0)

        # Bond persistence (Link_Key_Notification handler is async / scheduled)
        # may finish just after AUTH_COMPLETE — give it a moment.
        for _ in range(20):
            bond_c = await storage_c.load_bond(peripheral_addr)
            bond_p = await storage_p.load_bond(central_addr)
            if bond_c is not None and bond_p is not None:
                break
            await asyncio.sleep(0.05)

        assert bond_c is not None, (
            f"central bond not persisted; storage={await storage_c.list_bonds()}"
        )
        assert bond_p is not None, (
            f"peripheral bond not persisted; storage={await storage_p.list_bonds()}"
        )
        assert bond_c.link_key is not None
        assert bond_p.link_key is not None
        assert bond_c.link_key == bond_p.link_key, (
            "bridge must deliver identical link keys to both sides"
        )
        assert bond_c.link_key_type == 0x05  # Unauthenticated Combination Key (P-192)

        # --- Step 5: Encryption ------------------------------------------------
        await stack_c.enable_classic_encryption(handle, timeout=2.0)

        # --- Step 6: Disconnect ------------------------------------------------
        await stack_c.gap.classic_connections.disconnect(handle)
        await asyncio.sleep(0.1)
        # After Disconnection_Complete, the bridge releases the handle.
        assert handle not in link._handles

    finally:
        try:
            await link.disconnect()
        except Exception:
            pass
        await stack_c.close()
        await stack_p.close()
