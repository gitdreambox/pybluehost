"""JsonBondStorage compatibility with legacy bond files where rand was an int."""
from __future__ import annotations

import json

from pybluehost.ble.smp import JsonBondStorage
from pybluehost.core.address import BDAddress


async def test_load_bond_handles_legacy_int_rand(tmp_path):
    """Legacy bond files stored rand as int. New code stores it as hex string.

    load_bond must accept both formats to avoid breaking users who upgraded
    from pre-Sub-Plan-1.
    """
    bonds_path = tmp_path / "bonds.json"
    bonds_path.write_text(json.dumps({
        "01:02:03:04:05:06": {
            "peer_address": "01:02:03:04:05:06",
            "address_type": 0,
            "ltk": "aa" * 16,
            "irk": None,
            "csrk": None,
            "ediv": 0x1234,
            "rand": 0x55,  # LEGACY: int, not hex string
            "key_size": 16,
            "authenticated": False,
            "sc": False,
            "link_key": None,
            "link_key_type": None,
            "ctkd_derived": False,
        }
    }))

    storage = JsonBondStorage(bonds_path)
    bond = await storage.load_bond(BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    assert bond is not None
    assert isinstance(bond.rand, bytes)
    assert len(bond.rand) == 8
    # Conversion: int 0x55 → 8-byte little-endian
    assert bond.rand == (0x55).to_bytes(8, "little")
    assert bond.ediv == 0x1234


async def test_load_bond_handles_new_hex_string_rand(tmp_path):
    """New-format bond files (rand: hex string) load correctly."""
    bonds_path = tmp_path / "bonds.json"
    bonds_path.write_text(json.dumps({
        "01:02:03:04:05:06": {
            "peer_address": "01:02:03:04:05:06",
            "ltk": "aa" * 16,
            "ediv": 0x1234,
            "rand": "5500000000000000",
        }
    }))

    storage = JsonBondStorage(bonds_path)
    bond = await storage.load_bond(BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    assert bond is not None
    assert bond.rand == bytes.fromhex("5500000000000000")
