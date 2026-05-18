"""End-to-end LE Secure Connections Numeric Comparison pairing via VirtualLELink."""
from __future__ import annotations

import asyncio

import pytest

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import AutoAcceptDelegate, JsonBondStorage
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability
from pybluehost.hci.virtual_link import VirtualLELink
from pybluehost.stack import Stack, StackConfig


class _RejectingDelegate(AutoAcceptDelegate):
    """Rejects numeric comparison; auto-accepts everything else."""

    async def confirm_numeric(self, peer_addr, value):
        return False


def _nc_config(storage, *, io_cap=IOCapability.DISPLAY_YES_NO):
    return StackConfig(
        bond_storage=storage,
        security=SecurityConfig(
            enable_secure_connections=True,
            mitm_required=True,
        ),
        le_io_capability=io_cap,
    )


async def test_le_sc_numeric_comparison_auto_accept_pair_succeeds(tmp_path):
    """Both stacks default to AutoAcceptDelegate; NC selected; both bonds authenticated."""
    storage_a = JsonBondStorage(tmp_path / "bonds_a.json")
    storage_b = JsonBondStorage(tmp_path / "bonds_b.json")
    central = BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A")
    peripheral = BDAddress(b"\x0B\x0B\x0B\x0B\x0B\x0B")
    stack_a = await Stack.virtual(config=_nc_config(storage_a), address=central)
    stack_b = await Stack.virtual(config=_nc_config(storage_b), address=peripheral)
    link = VirtualLELink(
        central=stack_a._virtual_controller,
        peripheral=stack_b._virtual_controller,
        central_address=central,
        peripheral_address=peripheral,
    )
    handle = await link.connect()
    await asyncio.sleep(0.1)
    await stack_a.pair(handle=handle, timeout=20.0)

    bond_a = await storage_a.load_bond(peripheral)
    bond_b = await storage_b.load_bond(central)
    assert bond_a is not None and bond_a.sc is True
    assert bond_b is not None and bond_b.sc is True
    assert bond_a.ltk == bond_b.ltk
    # Critical: NC pairing -> authenticated=True on both sides
    assert bond_a.authenticated is True, "NC must mark bond authenticated"
    assert bond_b.authenticated is True, "NC must mark bond authenticated"

    await link.disconnect()
    await stack_a.close()
    await stack_b.close()


async def test_le_sc_numeric_comparison_responder_rejects(tmp_path):
    """Responder's delegate returns False -> pairing fails."""
    storage_a = JsonBondStorage(tmp_path / "bonds_a.json")
    storage_b = JsonBondStorage(tmp_path / "bonds_b.json")
    central = BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A")
    peripheral = BDAddress(b"\x0B\x0B\x0B\x0B\x0B\x0B")
    stack_a = await Stack.virtual(config=_nc_config(storage_a), address=central)
    stack_b = await Stack.virtual(config=_nc_config(storage_b), address=peripheral)
    # Inject rejecting delegate on the peripheral
    stack_b._smp.set_delegate(_RejectingDelegate())

    link = VirtualLELink(
        central=stack_a._virtual_controller,
        peripheral=stack_b._virtual_controller,
        central_address=central,
        peripheral_address=peripheral,
    )
    handle = await link.connect()
    await asyncio.sleep(0.1)

    with pytest.raises(Exception):
        await stack_a.pair(handle=handle, timeout=10.0)

    await link.disconnect()
    await stack_a.close()
    await stack_b.close()
