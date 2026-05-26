"""SSPManager handles SC HCI events + persists BondInfo with sc=True for P-256 keys."""
from __future__ import annotations

import asyncio

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import BondInfo, JsonBondStorage
from pybluehost.classic.gap import SSPManager
from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import EventCode
from pybluehost.hci.packets import HCIEvent


class FakeHCI:
    def __init__(self):
        self.sent: list = []

    async def send_command(self, cmd):
        self.sent.append(cmd)


async def test_ssp_io_capability_reply_sets_sc_bit_when_enabled():
    hci = FakeHCI()
    mgr = SSPManager(
        hci=hci,
        security_config=SecurityConfig(enable_secure_connections=True),
    )
    addr = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    # IO_Capability_Request event params: bd_addr (6 bytes; BT wire = little-endian)
    params = bytes(reversed(addr.address))
    evt = HCIEvent(event_code=int(EventCode.IO_CAPABILITY_REQUEST), parameters=params)
    await mgr.on_hci_event(evt)
    await asyncio.sleep(0.05)
    assert hci.sent, "SSPManager must reply to IO_Capability_Request"
    reply = hci.sent[0]
    raw = reply.to_bytes() if hasattr(reply, "to_bytes") else reply
    # Layout: H4(1) + opcode(2) + plen(1) + bd_addr(6) + io_cap(1) + oob(1) + auth_req(1)
    auth_req_byte = raw[4 + 6 + 2]
    assert auth_req_byte == 0x04, f"expected 0x04, got 0x{auth_req_byte:02x}"


async def test_ssp_link_key_notification_p256_key_type_sets_sc_true(tmp_path):
    """key_type 0x07 = SC Unauthenticated → sc=True, authenticated=False."""
    hci = FakeHCI()
    storage = JsonBondStorage(tmp_path / "bonds.json")
    mgr = SSPManager(
        hci=hci,
        security_config=SecurityConfig(enable_secure_connections=True),
        bond_storage=storage,
    )
    addr = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    params = bytes(reversed(addr.address)) + b"\xAA" * 16 + bytes([0x07])
    evt = HCIEvent(event_code=int(EventCode.LINK_KEY_NOTIFICATION), parameters=params)
    await mgr.on_hci_event(evt)
    await asyncio.sleep(0.05)

    bond = await storage.load_bond(addr)
    assert bond is not None
    assert bond.link_key == b"\xAA" * 16
    assert bond.link_key_type == 0x07
    assert bond.sc is True
    assert bond.authenticated is False


async def test_ssp_link_key_notification_legacy_key_type_sets_sc_false(tmp_path):
    """key_type 0x00 = Legacy combo → sc=False."""
    hci = FakeHCI()
    storage = JsonBondStorage(tmp_path / "bonds.json")
    mgr = SSPManager(
        hci=hci,
        security_config=SecurityConfig(enable_secure_connections=False),
        bond_storage=storage,
    )
    addr = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    params = bytes(reversed(addr.address)) + b"\xBB" * 16 + bytes([0x00])
    evt = HCIEvent(event_code=int(EventCode.LINK_KEY_NOTIFICATION), parameters=params)
    await mgr.on_hci_event(evt)
    await asyncio.sleep(0.05)
    bond = await storage.load_bond(addr)
    assert bond is not None
    assert bond.sc is False
    assert bond.link_key_type == 0x00


async def test_ssp_link_key_notification_p192_key_type_sets_sc_false(tmp_path):
    """key_type 0x05 is authenticated P-192, not Secure Connections/P-256."""
    hci = FakeHCI()
    storage = JsonBondStorage(tmp_path / "bonds.json")
    mgr = SSPManager(
        hci=hci,
        security_config=SecurityConfig(enable_secure_connections=False),
        bond_storage=storage,
    )
    addr = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    params = bytes(reversed(addr.address)) + b"\xCC" * 16 + bytes([0x05])
    evt = HCIEvent(event_code=int(EventCode.LINK_KEY_NOTIFICATION), parameters=params)
    await mgr.on_hci_event(evt)
    await asyncio.sleep(0.05)
    bond = await storage.load_bond(addr)
    assert bond is not None
    assert bond.sc is False
    assert bond.authenticated is True
    assert bond.link_key_type == 0x05


async def test_ssp_simple_pairing_complete_does_not_raise():
    hci = FakeHCI()
    mgr = SSPManager(
        hci=hci,
        security_config=SecurityConfig(enable_secure_connections=True),
    )
    addr = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    params = b"\x00" + bytes(reversed(addr.address))
    evt = HCIEvent(event_code=int(EventCode.SIMPLE_PAIRING_COMPLETE), parameters=params)
    await mgr.on_hci_event(evt)
    await asyncio.sleep(0.05)
    # Just verify it didn't raise; future Plans can add signal-emission tests


async def test_ssp_user_confirmation_request_still_auto_accepts():
    """Preserve Sub-Plan 1 / pre-SC behavior."""
    hci = FakeHCI()
    mgr = SSPManager(
        hci=hci,
        security_config=SecurityConfig(enable_secure_connections=True),
    )
    addr = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    params = bytes(reversed(addr.address)) + (0x12345678).to_bytes(4, "little")
    evt = HCIEvent(event_code=int(EventCode.USER_CONFIRMATION_REQUEST), parameters=params)
    await mgr.on_hci_event(evt)
    await asyncio.sleep(0.05)
    assert hci.sent


async def test_ssp_link_key_request_reply_when_bond_exists(tmp_path):
    """Link_Key_Request for a known peer → HCI_Link_Key_Request_Reply(addr, link_key)."""
    hci = FakeHCI()
    storage = JsonBondStorage(tmp_path / "bonds.json")
    # Pre-populate storage with a known SC bond
    addr = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=addr, address_type=0,
        link_key=b"\xCC" * 16, link_key_type=0x07, sc=True,
    ))

    mgr = SSPManager(
        hci=hci,
        security_config=SecurityConfig(enable_secure_connections=True),
        bond_storage=storage,
    )
    params = bytes(reversed(addr.address))  # BT wire LE
    evt = HCIEvent(event_code=int(EventCode.LINK_KEY_REQUEST), parameters=params)
    await mgr.on_hci_event(evt)
    await asyncio.sleep(0.05)

    # Look for HCI_Link_Key_Request_Reply
    from pybluehost.hci.packets import HCI_Link_Key_Request_Reply_Command
    replies = [c for c in hci.sent if isinstance(c, HCI_Link_Key_Request_Reply_Command)]
    assert len(replies) == 1, f"expected one Link_Key_Request_Reply; got hci.sent={hci.sent}"
    assert replies[0].link_key == b"\xCC" * 16
    # No negative reply
    from pybluehost.hci.constants import HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY
    for cmd in hci.sent:
        opcode = getattr(cmd, "opcode", None)
        assert opcode != HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY


async def test_ssp_link_key_request_negative_reply_when_no_bond(tmp_path):
    """Link_Key_Request for unknown peer → HCI_Link_Key_Request_Negative_Reply."""
    hci = FakeHCI()
    storage = JsonBondStorage(tmp_path / "bonds.json")
    mgr = SSPManager(
        hci=hci,
        security_config=SecurityConfig(enable_secure_connections=True),
        bond_storage=storage,
    )
    addr = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    params = bytes(reversed(addr.address))
    evt = HCIEvent(event_code=int(EventCode.LINK_KEY_REQUEST), parameters=params)
    await mgr.on_hci_event(evt)
    await asyncio.sleep(0.05)

    from pybluehost.hci.packets import HCI_Link_Key_Request_Reply_Command
    replies = [c for c in hci.sent if isinstance(c, HCI_Link_Key_Request_Reply_Command)]
    assert replies == [], "must not send positive reply when no bond stored"
    # At least one HCI command was sent (the negative reply)
    assert hci.sent


async def test_ssp_link_key_request_negative_reply_when_no_storage():
    """When SSPManager has no bond_storage configured, always negative-reply."""
    hci = FakeHCI()
    mgr = SSPManager(
        hci=hci,
        security_config=SecurityConfig(enable_secure_connections=True),
        # bond_storage explicitly omitted → None
    )
    addr = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    params = bytes(reversed(addr.address))
    evt = HCIEvent(event_code=int(EventCode.LINK_KEY_REQUEST), parameters=params)
    await mgr.on_hci_event(evt)
    await asyncio.sleep(0.05)

    from pybluehost.hci.packets import HCI_Link_Key_Request_Reply_Command
    replies = [c for c in hci.sent if isinstance(c, HCI_Link_Key_Request_Reply_Command)]
    assert replies == []
    assert hci.sent  # negative reply
