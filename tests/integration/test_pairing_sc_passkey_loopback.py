"""End-to-end SC Passkey Entry pairing via VirtualLELink."""
from __future__ import annotations

import asyncio

import pytest

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import AutoAcceptDelegate, JsonBondStorage
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability
from pybluehost.hci.virtual_link import VirtualLELink
from pybluehost.stack import Stack, StackConfig


class _FixedPasskeyDelegate(AutoAcceptDelegate):
    """Returns a pre-set passkey value for both display and input."""

    def __init__(self, passkey: int):
        self.passkey = passkey
        self.displayed: list = []

    async def display_passkey(self, peer_addr, passkey):
        self.displayed.append((peer_addr, passkey))

    async def get_passkey(self, peer_addr):
        return self.passkey


def _sc_passkey_config(storage, *, io_cap):
    return StackConfig(
        bond_storage=storage,
        security=SecurityConfig(
            enable_secure_connections=True,
            mitm_required=True,
        ),
        le_io_capability=io_cap,
    )


async def test_sc_passkey_pair_succeeds_with_matching_delegates(tmp_path):
    """Display side (Central=DisplayYesNo) + Input side (Peripheral=KeyboardOnly).
    Both delegates carry the same passkey → 20 rounds complete; bond authenticated, sc=True."""
    storage_a = JsonBondStorage(tmp_path / "bonds_a.json")
    storage_b = JsonBondStorage(tmp_path / "bonds_b.json")
    central = BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A")
    peripheral = BDAddress(b"\x0B\x0B\x0B\x0B\x0B\x0B")

    cfg_a = _sc_passkey_config(storage_a, io_cap=IOCapability.DISPLAY_YES_NO)
    cfg_b = _sc_passkey_config(storage_b, io_cap=IOCapability.KEYBOARD_ONLY)

    stack_a = await Stack.virtual(config=cfg_a, address=central)
    stack_b = await Stack.virtual(config=cfg_b, address=peripheral)
    stack_a._smp.set_delegate(_FixedPasskeyDelegate(passkey=314159))
    stack_b._smp.set_delegate(_FixedPasskeyDelegate(passkey=314159))

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
    # SC Passkey → authenticated=True on both sides
    assert bond_a.authenticated is True
    assert bond_b.authenticated is True
    # f5-derived LTK matches
    assert bond_a.ltk == bond_b.ltk

    await link.disconnect()
    await stack_a.close()
    await stack_b.close()


async def test_sc_passkey_pair_fails_on_wrong_passkey(tmp_path):
    """Mismatched passkeys → round-1 f4 verification fails → pair() raises reason=0x04."""
    storage_a = JsonBondStorage(tmp_path / "bonds_a.json")
    storage_b = JsonBondStorage(tmp_path / "bonds_b.json")
    central = BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A")
    peripheral = BDAddress(b"\x0B\x0B\x0B\x0B\x0B\x0B")

    cfg_a = _sc_passkey_config(storage_a, io_cap=IOCapability.DISPLAY_YES_NO)
    cfg_b = _sc_passkey_config(storage_b, io_cap=IOCapability.KEYBOARD_ONLY)

    stack_a = await Stack.virtual(config=cfg_a, address=central)
    stack_b = await Stack.virtual(config=cfg_b, address=peripheral)
    stack_a._smp.set_delegate(_FixedPasskeyDelegate(passkey=111111))
    stack_b._smp.set_delegate(_FixedPasskeyDelegate(passkey=999999))

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
