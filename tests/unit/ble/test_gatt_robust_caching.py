"""Robust Caching core (Core Vol 3 Part G §2.5.2.1).

A client that set the Robust Caching bit in its Client Supported Features
becomes change-unaware when the database changes; its ATT requests then get
Database Out Of Sync (0x12) — sent once per bearer — until it re-syncs by
reading the Database Hash (the following request proceeds normally).
ATT commands from an unaware client are ignored, and READ_BY_TYPE requests
for discovery (type Include/Characteristic or the full 0x0001-0xFFFF range)
are always answered normally.
"""
from __future__ import annotations

import pytest

from pybluehost.ble.att import (
    ATT_Error_Response, ATT_Read_By_Type_Request, ATT_Read_Request,
    ATT_Write_Command, ATTOpcode,
)
from pybluehost.ble.gatt import (
    CharProperties, CharacteristicDefinition, GATTServer,
    Permissions, PERM_READ, ServiceDefinition,
)
from pybluehost.core.uuid import UUID16


def _server() -> GATTServer:
    """Server with the standard GATT service (SC + Database Hash + CSF)."""
    from pybluehost.pts.btp.services.gatt import _standard_gap_gatt_services
    server = GATTServer()
    for std in _standard_gap_gatt_services():
        server.add_service(std)
    return server


def _csf_value_handle(server: GATTServer) -> int:
    for attr in server.db._attrs:
        if isinstance(attr.type_uuid, UUID16) and attr.type_uuid.value == 0x2B29:
            return attr.handle
    raise AssertionError("no CSF characteristic in db")


def _hash_handle(server: GATTServer) -> int:
    for attr in server.db._attrs:
        if isinstance(attr.type_uuid, UUID16) and attr.type_uuid.value == 0x2B2A:
            return attr.handle
    raise AssertionError("no Database Hash characteristic in db")


async def _write_csf_robust(server: GATTServer, handle=0x0001):
    """Enable Robust Caching for the connection like PTS does (BV-03 step 1)."""
    from pybluehost.ble.att import ATT_Write_Request
    resp = await server.handle_request(handle, ATT_Write_Request(
        attribute_handle=_csf_value_handle(server),
        attribute_value=bytes([0x01]) + b"\x00",
    ))
    assert not isinstance(resp, ATT_Error_Response), f"CSF write failed: {resp}"


@pytest.mark.asyncio
async def test_unaware_client_gets_0x12_once_then_next_request_ok():
    """BV-05: after a db change a robust-caching client's ATT read gets
    Database Out Of Sync exactly once; the FOLLOWING request proceeds."""
    server = _server()
    await _write_csf_robust(server)
    name_handle = _csf_value_handle(server)  # any readable handle works

    server.mark_database_changed()

    r1 = await server.handle_request(0x0001, ATT_Read_Request(
        attribute_handle=name_handle))
    assert isinstance(r1, ATT_Error_Response)
    assert r1.error_code == 0x12

    # Second read: the 0x12 was already delivered once — per Figure 2.7 the
    # client has been told; this request transitions it to change-aware.
    r2 = await server.handle_request(0x0001, ATT_Read_Request(
        attribute_handle=name_handle))
    assert not isinstance(r2, ATT_Error_Response), \
        "after the one-time 0x12 the next request must proceed normally"


@pytest.mark.asyncio
async def test_hash_read_resynchronizes_client():
    """Reading the Database Hash (by UUID, full range) always succeeds and
    the next request proceeds even though no 0x12 was delivered."""
    server = _server()
    await _write_csf_robust(server)
    server.mark_database_changed()

    h = await server.handle_request(0x0001, ATT_Read_By_Type_Request(
        attribute_type=UUID16(0x2B2A).to_bytes(),
        starting_handle=0x0001, ending_handle=0xFFFF))
    assert not isinstance(h, ATT_Error_Response), \
        "hash read by UUID over the full range is the resync path — never 0x12"

    r = await server.handle_request(0x0001, ATT_Read_Request(
        attribute_handle=_csf_value_handle(server)))
    assert not isinstance(r, ATT_Error_Response), \
        "hash read + next request -> change-aware"


@pytest.mark.asyncio
async def test_discovery_read_by_type_exempt_from_0x12():
    """READ_BY_TYPE with type Characteristic (discovery) or a full-range
    query is answered normally even while change-unaware."""
    server = _server()
    await _write_csf_robust(server)
    server.mark_database_changed()

    d = await server.handle_request(0x0001, ATT_Read_By_Type_Request(
        attribute_type=UUID16(0x2803).to_bytes(),
        starting_handle=0x0001, ending_handle=0xFFFF))
    assert not isinstance(d, ATT_Error_Response), \
        "discovery (Characteristic type) is exempt"

    # Non-discovery by-type over a LIMITED range from an unaware client -> 0x12
    d2 = await server.handle_request(0x0001, ATT_Read_By_Type_Request(
        attribute_type=UUID16(0x2B2A).to_bytes(),
        starting_handle=0x0002, ending_handle=0x0030))
    assert isinstance(d2, ATT_Error_Response) and d2.error_code == 0x12


@pytest.mark.asyncio
async def test_commands_from_unaware_client_ignored():
    """ATT commands (Write Command) from an unaware client are silently
    ignored — no response at all (Figure 2.6)."""
    server = _server()
    await _write_csf_robust(server)
    server.mark_database_changed()

    resp = await server.handle_request(0x0001, ATT_Write_Command(
        attribute_handle=_csf_value_handle(server), attribute_value=b"\x01\x00"))
    assert resp is None, "commands from unaware clients are ignored"


@pytest.mark.asyncio
async def test_client_without_robust_caching_never_gets_0x12():
    """Legacy clients (robust caching bit not set) are never blocked."""
    server = _server()
    server.mark_database_changed()
    r = await server.handle_request(0x0001, ATT_Read_Request(
        attribute_handle=_csf_value_handle(server)))
    assert not isinstance(r, ATT_Error_Response)


@pytest.mark.asyncio
async def test_csf_write_clearing_robust_caching_bit_returns_value_not_allowed():
    """BV-05 step 11 / BV-07 step 7: once Robust Caching is enabled, the client
    cannot disable it by writing 0 while connected — the server returns Value
    Not Allowed (0x13) and leaves the bit set."""
    from pybluehost.ble.att import ATT_Read_Request, ATT_Write_Request
    server = _server()
    h = _csf_value_handle(server)
    await _write_csf_robust(server)  # RC = 1

    w = await server.handle_request(0x0001, ATT_Write_Request(
        attribute_handle=h, attribute_value=b"\x00\x00"))
    assert isinstance(w, ATT_Error_Response)
    assert w.error_code == 0x13  # Value Not Allowed

    r = await server.handle_request(0x0001, ATT_Read_Request(attribute_handle=h))
    assert r.attribute_value[:1] == b"\x01", "RC bit must remain 1"


@pytest.mark.asyncio
async def test_service_changed_confirmation_clears_change_unaware():
    """BV-06 step 7: after the client confirms a Service Changed indication it
    becomes change-aware again — the next read returns a value, not 0x12."""
    from pybluehost.ble.att import ATT_Read_Request
    server = _server()
    await _write_csf_robust(server)
    server.mark_database_changed()

    server.on_confirmation(0x0001)

    r = await server.handle_request(0x0001, ATT_Read_Request(
        attribute_handle=_csf_value_handle(server)))
    assert not isinstance(r, ATT_Error_Response), \
        "confirmation clears change-unaware; the read must proceed"


@pytest.mark.asyncio
async def test_csf_write_masks_rfu_bits_and_reads_back_per_connection():
    """BV-03: PTS writes Robust-Caching=1 + all RFU bits 1 (0xF9) and expects
    the read-back to carry only the defined bit (0x01); another connection
    reads its own instance (default zero)."""
    server = _server()
    from pybluehost.ble.att import ATT_Read_Request, ATT_Write_Request
    h = _csf_value_handle(server)
    w = await server.handle_request(0x0001, ATT_Write_Request(
        attribute_handle=h, attribute_value=b"\xF9\xFF"))
    assert not isinstance(w, ATT_Error_Response)
    r1 = await server.handle_request(0x0001, ATT_Read_Request(attribute_handle=h))
    assert r1.attribute_value[:1] == b"\x01", \
        "RFU bits stored as 0, robust-caching bit kept"

    r2 = await server.handle_request(0x0002, ATT_Read_Request(attribute_handle=h))
    assert r2.attribute_value[:1] == b"\x00", \
        "second connection sees its own CSF instance"


@pytest.mark.asyncio
async def test_remove_connection_resets_synced_pending_for_the_next_bearer():
    """GAS/BV-07 step 9: the '0x12 sent once' marker is per-bearer, so after a
    disconnect the first read on the NEW connection gets DoS again — the client
    never resynced, so it is still change-unaware."""
    from pybluehost.ble.att import ATT_Read_Request

    server = _server()
    await _write_csf_robust(server)
    server.mark_database_changed()

    r1 = await server.handle_request(0x0001, ATT_Read_Request(
        attribute_handle=_csf_value_handle(server)))
    assert isinstance(r1, ATT_Error_Response) and r1.error_code == 0x12

    # Disconnect then reconnect on the same handle (controller reuses it).
    server.remove_connection(0x0001)

    r2 = await server.handle_request(0x0001, ATT_Read_Request(
        attribute_handle=_csf_value_handle(server)))
    assert isinstance(r2, ATT_Error_Response) and r2.error_code == 0x12, \
        "the new bearer must get its own 0x12; the old one was on the previous connection"


@pytest.mark.asyncio
async def test_notify_multiple_sends_only_when_mhnv_bit_set():
    """GAN/BV-02: the IUT sends a Multiple Handle Value Notification (0x23) only
    for a client whose CSF Multiple Handle Value Notifications bit is set."""
    from pybluehost.ble.att import ATT_Write_Request
    from pybluehost.core.uuid import UUID16

    server = _server()
    sent = []
    server.on_multiple_notification_sent(lambda hlv, c: sent.append((hlv, c)))

    # Client 0x0001 writes CSF=0x04 (MHNV bit only, per-client).
    csf_handle = _csf_value_handle(server)
    await server.handle_request(0x0001, ATT_Write_Request(
        attribute_handle=csf_handle, attribute_value=b"\x04\x00"))

    await server.notify_multiple(0x0001, [0x0001, 0x0003])
    assert len(sent) == 1, "MHNV-enabled client gets the 0x23 notification"

    # Client 0x0002 never enabled MHNV -> no notification.
    await server.notify_multiple(0x0002, [0x0001, 0x0003])
    assert len(sent) == 1, "client without MHNV must not be notified"
