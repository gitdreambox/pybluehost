"""Auto-encrypt on bonded reconnect."""
from __future__ import annotations

import asyncio
import struct

import pytest

from pybluehost.ble.smp import BondInfo, JsonBondStorage
from pybluehost.core.address import BDAddress
from pybluehost.stack import Stack, StackConfig


async def test_le_connection_complete_triggers_start_encryption_when_bonded(tmp_path, monkeypatch):
    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))
    cfg = StackConfig(bond_storage=storage)
    stack = await Stack.virtual(config=cfg)
    try:
        sent: list = []
        original = stack._hci.send_command

        async def _capture(cmd):
            sent.append(cmd)
            return await original(cmd)

        monkeypatch.setattr(stack._hci, "send_command", _capture)

        # Inject a synthetic LE_Connection_Complete (role=0x00 = Central) to peer
        from pybluehost.hci.constants import EventCode, LEMetaSubEvent
        from pybluehost.hci.packets import HCI_LE_Meta_Event

        # subevent_parameters layout (LE_CONNECTION_COMPLETE):
        #   [0]     status (1 byte)
        #   [1:3]   connection_handle (2 bytes, LE)
        #   [3]     role (1 byte): 0x00 = Central
        #   [4]     peer_address_type (1 byte)
        #   [5:11]  peer_bd_addr (6 bytes)
        #   [11:13] conn_interval (2 bytes)
        #   [13:15] conn_latency (2 bytes)
        #   [15:17] supervision_timeout (2 bytes)
        #   [17]    master_clock_accuracy (1 byte)
        subevent_params = (
            bytes([0x00])                            # status = SUCCESS
            + struct.pack("<H", 0x0040)              # handle = 0x0040
            + bytes([0x00])                          # role = Central
            + bytes([0x00])                          # peer_address_type = public
            + bytes(peer.address)                    # peer_bd_addr (6 bytes)
            + struct.pack("<HHH", 0x0028, 0, 0x0048) # interval, latency, timeout
            + bytes([0])                             # master_clock_accuracy
        )
        evt = HCI_LE_Meta_Event(
            subevent_code=int(LEMetaSubEvent.LE_CONNECTION_COMPLETE),
            subevent_parameters=subevent_params,
        )
        await stack._on_hci_event(evt)
        await asyncio.sleep(0.05)

        from pybluehost.hci.packets import HCI_LE_Start_Encryption_Command
        assert any(isinstance(c, HCI_LE_Start_Encryption_Command) for c in sent), (
            "expected auto Start_Encryption command on LE_Connection_Complete with bonded peer"
        )
    finally:
        await stack.close()


async def test_no_auto_encrypt_when_config_disabled(tmp_path, monkeypatch):
    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=1, rand=b"\xDD" * 8,
    ))
    cfg = StackConfig(bond_storage=storage, auto_encrypt_on_bonded_reconnect=False)
    stack = await Stack.virtual(config=cfg)
    try:
        sent: list = []
        original = stack._hci.send_command

        async def _capture(cmd):
            sent.append(cmd)
            return await original(cmd)

        monkeypatch.setattr(stack._hci, "send_command", _capture)

        from pybluehost.hci.constants import LEMetaSubEvent
        from pybluehost.hci.packets import HCI_LE_Meta_Event, HCI_LE_Start_Encryption_Command

        subevent_params = (
            bytes([0x00])
            + struct.pack("<H", 0x0040)
            + bytes([0x00])
            + bytes([0x00])
            + bytes(peer.address)
            + struct.pack("<HHH", 0x0028, 0, 0x0048)
            + bytes([0])
        )
        evt = HCI_LE_Meta_Event(
            subevent_code=int(LEMetaSubEvent.LE_CONNECTION_COMPLETE),
            subevent_parameters=subevent_params,
        )
        await stack._on_hci_event(evt)
        await asyncio.sleep(0.05)

        assert not any(isinstance(c, HCI_LE_Start_Encryption_Command) for c in sent)
    finally:
        await stack.close()
