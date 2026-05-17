"""BR/EDR Secure Connections HCI-event-driven integration test.

We don't simulate a true two-controller Classic ACL bridge (deferred).
Instead, we inject the SSP event sequence and assert that SSPManager
replies with the right HCI commands and persists BondInfo correctly.
"""
from __future__ import annotations

import asyncio

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import JsonBondStorage
from pybluehost.core.address import BDAddress
from pybluehost.stack import Stack, StackConfig


async def test_classic_sc_pairing_persists_p256_bond(tmp_path):
    """Inject SSP event sequence with key_type=0x07 → bond persisted with sc=True."""
    storage = JsonBondStorage(tmp_path / "bonds.json")
    cfg = StackConfig(
        bond_storage=storage,
        security=SecurityConfig(enable_secure_connections=True),
    )
    stack = await Stack.virtual(config=cfg)
    try:
        peer_bd_addr = b"\x01\x02\x03\x04\x05\x06"  # BT wire LE
        peer_canonical = BDAddress(bytes(reversed(peer_bd_addr)))

        stack._virtual_controller.simulate_ssp_pairing(bd_addr=peer_bd_addr, key_type=0x07)
        # Wait for the 4-event sequence to flow through + SSPManager to persist bond
        await asyncio.sleep(0.2)

        bond = await storage.load_bond(peer_canonical)
        assert bond is not None, f"BondInfo not persisted; storage={await storage.list_bonds()}"
        assert bond.link_key_type == 0x07
        assert bond.sc is True
        assert bond.authenticated is False
        assert bond.link_key == b"\x88" * 16
    finally:
        await stack.close()


async def test_classic_sc_legacy_key_type_persists_legacy_bond(tmp_path):
    """Inject SSP event sequence with key_type=0x00 → bond persisted with sc=False."""
    storage = JsonBondStorage(tmp_path / "bonds.json")
    cfg = StackConfig(
        bond_storage=storage,
        security=SecurityConfig(enable_secure_connections=False),
    )
    stack = await Stack.virtual(config=cfg)
    try:
        peer_bd_addr = b"\xAA\xBB\xCC\xDD\xEE\xFF"
        peer_canonical = BDAddress(bytes(reversed(peer_bd_addr)))
        stack._virtual_controller.simulate_ssp_pairing(bd_addr=peer_bd_addr, key_type=0x00)
        await asyncio.sleep(0.2)
        bond = await storage.load_bond(peer_canonical)
        assert bond is not None
        assert bond.sc is False
        assert bond.link_key_type == 0x00
    finally:
        await stack.close()


async def test_classic_sc_reconnect_replies_with_stored_link_key(tmp_path):
    """After bond is stored, controller's Link_Key_Request triggers reply with the link_key."""
    from pybluehost.ble.smp import BondInfo
    from pybluehost.hci.constants import EventCode
    from pybluehost.hci.packets import HCIEvent

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer_canonical = BDAddress(b"\xAA\xBB\xCC\xDD\xEE\xFF")
    await storage.save_bond(BondInfo(
        peer_address=peer_canonical, address_type=0,
        link_key=b"\x77" * 16, link_key_type=0x07, sc=True,
    ))
    cfg = StackConfig(
        bond_storage=storage,
        security=SecurityConfig(enable_secure_connections=True),
    )
    stack = await Stack.virtual(config=cfg)
    try:
        # Capture HCI commands sent
        sent: list = []
        original = stack._hci.send_command

        async def _capture(cmd):
            sent.append(cmd)
            return await original(cmd)
        stack._hci.send_command = _capture

        # Inject Link_Key_Request event — BD_ADDR in BT wire LE format
        peer_bd_addr_le = bytes(reversed(peer_canonical.address))
        evt = HCIEvent(
            event_code=int(EventCode.LINK_KEY_REQUEST),
            parameters=peer_bd_addr_le,
        )
        await stack._virtual_controller._send_event_to_host(evt)
        await asyncio.sleep(0.1)

        from pybluehost.hci.packets import HCI_Link_Key_Request_Reply_Command
        replies = [c for c in sent if isinstance(c, HCI_Link_Key_Request_Reply_Command)]
        assert len(replies) == 1
        assert replies[0].link_key == b"\x77" * 16
    finally:
        await stack.close()
