"""Database Hash characteristic computation (Core Vol 3 Part G §7.3.1).

PTS GATT/SR/GAS/BV-02: the Lower Tester discovers the whole database, reads
the Database Hash characteristic, computes the hash itself per RFC-4493 and
compares. The spec's Appendix B provides a worked example used here as the
test vector: 22 attributes (GAP + GATT + Glucose services) hash to
F1CA2D48ECF58BAC8A8830BBB9FBA990.
"""
from __future__ import annotations

from pybluehost.ble.gatt import AttributeDatabase, Permissions, PERM_READ
from pybluehost.core.uuid import UUID16

EXPECTED = bytes.fromhex("F1CA2D48ECF58BAC8A8830BBB9FBA990")


def _appendix_b_db() -> AttributeDatabase:
    """Rebuild Core 5.4 Vol 3 Part G Appendix B Table B.1 exactly.

    Handles auto-assign 0x0001..0x0016 in add order, matching the table.
    """
    db = AttributeDatabase()
    R = PERM_READ
    # 0x0001 GAP primary service (0x1800 per Appendix B Table B.1)
    db.add(UUID16(0x2800), R, (0x1800).to_bytes(2, "little"))
    # 0x0002 Device Name declaration {0x0A, 0x0003, 0x2A00}
    db.add(UUID16(0x2803), R, bytes([0x0A]) + (0x0003).to_bytes(2, "little")
           + (0x2A00).to_bytes(2, "little"))
    # 0x0003 Device Name value (ignored by hash)
    db.add(UUID16(0x2A00), R, b"any")
    # 0x0004 Appearance declaration {0x02, 0x0005, 0x2A01}
    db.add(UUID16(0x2803), R, bytes([0x02]) + (0x0005).to_bytes(2, "little")
           + (0x2A01).to_bytes(2, "little"))
    db.add(UUID16(0x2A01), R, b"any")            # 0x0005 value (ignored)
    # 0x0006 GATT primary service
    db.add(UUID16(0x2800), R, (0x1801).to_bytes(2, "little"))
    # 0x0007 Service Changed declaration {0x20, 0x0008, 0x2A05}
    db.add(UUID16(0x2803), R, bytes([0x20]) + (0x0008).to_bytes(2, "little")
           + (0x2A05).to_bytes(2, "little"))
    db.add(UUID16(0x2A05), R, b"any")            # 0x0008 value (ignored)
    db.add(UUID16(0x2902), R)                    # 0x0009 CCC (handle+type only)
    # 0x000A Client Supported Features declaration {0x0A, 0x000B, 0x2B29}
    db.add(UUID16(0x2803), R, bytes([0x0A]) + (0x000B).to_bytes(2, "little")
           + (0x2B29).to_bytes(2, "little"))
    db.add(UUID16(0x2B29), R)                    # 0x000B CSF value (ignored)
    # 0x000C Database Hash declaration {0x02, 0x000D, 0x2B2A}
    db.add(UUID16(0x2803), R, bytes([0x02]) + (0x000D).to_bytes(2, "little")
           + (0x2B2A).to_bytes(2, "little"))
    db.add(UUID16(0x2B2A), R)                    # 0x000D hash value (ignored)
    # 0x000E Glucose primary service
    db.add(UUID16(0x2800), R, (0x1808).to_bytes(2, "little"))
    # 0x000F Included Service {0x0014, 0x0016, 0x180F}
    db.add(UUID16(0x2802), R, (0x0014).to_bytes(2, "little")
           + (0x0016).to_bytes(2, "little") + (0x180F).to_bytes(2, "little"))
    # 0x0010 Glucose Measurement declaration {0xA2, 0x0011, 0x2A18}
    db.add(UUID16(0x2803), R, bytes([0xA2]) + (0x0011).to_bytes(2, "little")
           + (0x2A18).to_bytes(2, "little"))
    db.add(UUID16(0x2A18), R, b"any")            # 0x0011 value (ignored)
    db.add(UUID16(0x2902), R)                    # 0x0012 CCC (handle+type only)
    db.add(UUID16(0x2900), R, (0).to_bytes(2, "little"))  # 0x0013 CEP (with value)
    # 0x0014 Battery secondary service
    db.add(UUID16(0x2801), R, (0x180F).to_bytes(2, "little"))
    # 0x0015 Battery Level declaration {0x02, 0x0016, 0x2A19}
    db.add(UUID16(0x2803), R, bytes([0x02]) + (0x0016).to_bytes(2, "little")
           + (0x2A19).to_bytes(2, "little"))
    db.add(UUID16(0x2A19), R, b"any")            # 0x0016 value (ignored)
    return db


def test_database_hash_matches_spec_appendix_b():
    db = _appendix_b_db()
    assert db.database_hash() == EXPECTED, \
        "hash must match the Core spec Appendix B worked example"


def test_database_hash_value_is_the_little_endian_form_of_the_cmac():
    """The characteristic value is the CMAC byte-swapped.

    Core Vol 3 Part F §3.3.1 makes multi-octet characteristic values
    little-endian, and PTS compares the received value in that order —
    zephyr's ``db_hash_gen`` swaps the CMAC for the same reason. Serving the
    raw (big-endian) CMAC made GAS/BV-02 report "Received ... 2B2A-C9D3-..."
    against "calculated ... 3968-6A9F-..." (exact byte reversal).
    """
    db = _appendix_b_db()
    assert db.database_hash_value() == EXPECTED[::-1]


def test_database_hash_changes_when_service_added():
    db = _appendix_b_db()
    before = db.database_hash()
    db.add(UUID16(0x2800), PERM_READ, (0x180D).to_bytes(2, "little"))
    assert db.database_hash() != before, "adding a service must change the hash"


def test_database_hash_ignores_characteristic_value_writes():
    """Characteristic VALUE attributes are not part of m — writing one must
    not change the hash (Core §7.3.1: 'ignore the attribute if it has any
    other type')."""
    db = _appendix_b_db()
    before = db.database_hash()
    db.write(0x0003, b"different")   # Device Name value
    assert db.database_hash() == before


def test_server_read_by_type_returns_current_hash():
    """GAS/BV-02: Read Using Characteristic UUID (0x2B2A) returns the CURRENT
    hash — and it changes after the db changes (CHANGE_DATABASE)."""
    from pybluehost.ble.att import ATT_Read_By_Type_Request
    from pybluehost.ble.gatt import (
        CharProperties, CharacteristicDefinition, GATTServer,
        Permissions, PERM_READ, ServiceDefinition,
    )
    from pybluehost.core.uuid import UUID16

    server = GATTServer()
    server.add_service(ServiceDefinition(
        uuid=UUID16(0x1801),
        characteristics=[
            CharacteristicDefinition(
                uuid=UUID16(0x2A05), properties=CharProperties.INDICATE,
                permissions=Permissions.READABLE, value=b"\x00" * 4),
        ]))
    from pybluehost.pts.btp.services.gatt import _standard_gap_gatt_services
    for std in _standard_gap_gatt_services():
        server.add_service(std)

    def _read_hash():
        import asyncio
        return asyncio.run(server.handle_request(0x0001, ATT_Read_By_Type_Request(
            attribute_type=UUID16(0x2B2A).to_bytes(),
            starting_handle=0x0001, ending_handle=0xFFFF)))

    h1 = _read_hash()
    assert h1 is not None
    v1 = h1.attribute_data_list[2:]  # per entry: handle(2) + len(1) + value
    assert len(v1) == 16
    assert v1 == server.db.database_hash_value()

    # Change the db: add a service -> hash must differ on the next read.
    server.add_service(ServiceDefinition(
        uuid=UUID16(0x180F),
        characteristics=[
            CharacteristicDefinition(
                uuid=UUID16(0x2A19), properties=CharProperties.READ,
                permissions=PERM_READ, value=b"\x64"),
        ]))
    h2 = _read_hash()
    v2 = h2.attribute_data_list[2:]
    assert v2 != v1, "hash must change after the database changes"
