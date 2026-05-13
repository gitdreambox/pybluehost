"""JsonBondStorage round-trip with all BondInfo fields."""
from __future__ import annotations

from pybluehost.ble.smp import BondInfo, JsonBondStorage
from pybluehost.core.address import BDAddress


async def test_save_load_round_trip(tmp_path):
    storage = JsonBondStorage(tmp_path / "bonds.json")
    bond = BondInfo(
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        address_type=0,
        ltk=b"\xAA" * 16,
        irk=b"\xBB" * 16,
        csrk=b"\xCC" * 16,
        ediv=0x1234,
        rand=b"\x55" * 8,
        key_size=16,
        authenticated=False,
        sc=False,
    )
    await storage.save_bond(bond)
    loaded = await storage.load_bond(BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    assert loaded is not None
    assert loaded.ltk == b"\xAA" * 16
    assert loaded.rand == b"\x55" * 8  # bytes type confirmed
    assert loaded.ediv == 0x1234
    assert loaded.irk == b"\xBB" * 16


async def test_list_and_delete(tmp_path):
    storage = JsonBondStorage(tmp_path / "bonds.json")
    bond = BondInfo(peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    await storage.save_bond(bond)
    assert len(await storage.list_bonds()) == 1
    await storage.delete_bond(BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    assert await storage.list_bonds() == []
