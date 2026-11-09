"""GATT server EATT multi-bearer semantics (PTS GATT/SR GAR/BV-11, GAR/BV-12,
GAW/BV-12, GPM/BV-05, GAC/BI-01).

 bearer 轴只有两个 per-bearer 状态：ATT_MTU 与 "Database Out Of Sync sent
 once" 标记；prepare queue / CCCD / security / robust 主状态是 per-client
 （conn_handle 键控），跨 bearer 共享。
"""
from __future__ import annotations

import pytest

from pybluehost.ble.att import (
    ATT_Error_Response,
    ATT_Exchange_MTU_Request,
    ATT_Execute_Write_Request,
    ATT_Execute_Write_Response,
    ATT_Prepare_Write_Request,
    ATT_Prepare_Write_Response,
    ATT_Read_Multiple_Variable_Request,
    ATT_Read_Multiple_Variable_Response,
    ATT_Read_Request,
    ATT_Read_Response,
    ATT_Write_Request,
    ATT_Write_Response,
    ATTOpcode,
)
from pybluehost.ble.gatt import (
    CharacteristicDefinition,
    CharProperties,
    GATTServer,
    Permissions,
    ServiceDefinition,
)
from pybluehost.core.uuid import UUID16
from pybluehost.l2cap.constants import CID_ATT

pytestmark = pytest.mark.asyncio

CONN = 0x0040
BEARER1 = 0x0041  # EATT bearer CID（方向无关：我方端点 CID）
BEARER2 = 0x0042


def _server(*, long_value: bytes = b"AB" * 40) -> tuple[GATTServer, int]:
    """One readable characteristic with an 80-byte value; returns
    (server, value_handle). 80 bytes fits an EATT bearer MTU (>=64 only after
    registration — use mtu=100 in tests) but not the default 23."""
    server = GATTServer()
    handles = server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x180D),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2A38),
                    properties=CharProperties.READ,
                    permissions=Permissions.READABLE,
                    value=long_value,
                ),
            ],
        )
    )
    return server, handles.characteristic_handles[0].value_handle


async def test_exchange_mtu_is_tracked_per_bearer():
    """Exchange MTU on the fixed channel must not change an EATT bearer's MTU
    (and vice versa) — the key is (conn_handle, bearer_cid)."""
    server, value_handle = _server()
    await server.handle_request(CONN, ATT_Exchange_MTU_Request(client_rx_mtu=100))

    fixed = await server.handle_request(CONN, ATT_Read_Request(attribute_handle=value_handle))
    bearer = await server.handle_request(
        CONN, ATT_Read_Request(attribute_handle=value_handle), bearer_cid=BEARER1)

    assert isinstance(fixed, ATT_Read_Response)
    assert len(fixed.attribute_value) == 80  # negotiated 100 -> 100-1 fits all
    assert isinstance(bearer, ATT_Read_Response)
    assert len(bearer.attribute_value) == 22  # unregistered bearer -> default 23-1


async def test_handle_request_without_bearer_cid_behaves_as_fixed_channel():
    """Default bearer_cid=CID_ATT keeps the existing fixed-channel behaviour."""
    server, value_handle = _server(long_value=b"\x01\x02")
    rsp = await server.handle_request(CONN, ATT_Read_Request(attribute_handle=value_handle))
    assert isinstance(rsp, ATT_Read_Response)
    assert rsp.attribute_value == b"\x01\x02"
    assert server._att_mtu(CONN, CID_ATT) == 23


async def test_add_eatt_bearer_sets_channel_mtu():
    """An EATT bearer's ATT_MTU is its L2CAP channel MTU (GATT.TS §4.2.5)."""
    server, value_handle = _server()
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    rsp = await server.handle_request(
        CONN, ATT_Read_Request(attribute_handle=value_handle), bearer_cid=BEARER1)
    assert isinstance(rsp, ATT_Read_Response)
    assert len(rsp.attribute_value) == 80  # 100-1 fits the whole value
    assert server.is_eatt_bearer(CONN, BEARER1)


async def test_exchange_mtu_on_eatt_bearer_is_rejected_not_supported():
    """GAC/BI-01: Exchange MTU is not applicable on an EATT bearer — the server
    must answer ATT_ERROR_RSP(0x02, handle 0x0000, 0x06 Request Not Supported)
    and leave the bearer MTU untouched."""
    server, _ = _server()
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    rsp = await server.handle_request(
        CONN, ATT_Exchange_MTU_Request(client_rx_mtu=200), bearer_cid=BEARER1)
    assert isinstance(rsp, ATT_Error_Response)
    assert rsp.error_code == 0x06  # Request Not Supported
    assert int(rsp.request_opcode_in_error) == int(ATTOpcode.EXCHANGE_MTU_REQUEST)
    assert rsp.attribute_handle_in_error == 0x0000
    assert server._att_mtu(CONN, BEARER1) == 100


async def test_exchange_mtu_rejection_does_not_touch_fixed_channel():
    server, _ = _server()
    await server.handle_request(CONN, ATT_Exchange_MTU_Request(client_rx_mtu=100))
    server.add_eatt_bearer(CONN, BEARER1, mtu=64)
    await server.handle_request(
        CONN, ATT_Exchange_MTU_Request(client_rx_mtu=200), bearer_cid=BEARER1)
    assert server._att_mtu(CONN, CID_ATT) == 100
    assert server._att_mtu(CONN, BEARER1) == 64


async def test_remove_connection_clears_all_bearer_state():
    """Handle reuse must never see a previous connection's bearer MTUs."""
    server, _ = _server()
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    server.add_eatt_bearer(CONN, BEARER2, mtu=80)
    server.remove_connection(CONN)
    assert server._att_mtu(CONN, BEARER1) == 23
    assert server._att_mtu(CONN, BEARER2) == 23
    assert not server.is_eatt_bearer(CONN, BEARER1)


async def test_add_eatt_bearer_resets_mtu_on_cid_reuse():
    server, _ = _server()
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    server.add_eatt_bearer(CONN, BEARER1, mtu=64)
    assert server._att_mtu(CONN, BEARER1) == 64


async def test_remove_eatt_bearer_drops_only_that_bearer():
    server, _ = _server()
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    server.add_eatt_bearer(CONN, BEARER2, mtu=80)
    server.remove_eatt_bearer(CONN, BEARER1)
    assert not server.is_eatt_bearer(CONN, BEARER1)
    assert server._att_mtu(CONN, BEARER1) == 23
    assert server.is_eatt_bearer(CONN, BEARER2)
    assert server._att_mtu(CONN, BEARER2) == 80


def _robust_server() -> tuple[GATTServer, int, int]:
    """Server with a readable value characteristic + a Client Supported
    Features characteristic (0x2B29). Returns (server, value_handle, csf_handle)."""
    server, value_handle = _server(long_value=b"\x01\x02")
    server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x1801),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2B29),
                    properties=CharProperties.READ | CharProperties.WRITE,
                    permissions=Permissions.READABLE | Permissions.WRITABLE,
                    value=b"\x00",
                ),
            ],
        )
    )
    csf_handle = server._csf_value_handle()
    assert csf_handle is not None
    return server, value_handle, csf_handle


async def _enable_robust_caching(server: GATTServer, csf_handle: int) -> None:
    rsp = await server.handle_request(
        CONN, ATT_Write_Request(attribute_handle=csf_handle, attribute_value=b"\x01"))
    assert isinstance(rsp, ATT_Write_Response)


async def test_database_out_of_sync_is_sent_once_per_bearer():
    """Core Vol 3 Part G Figure 2.7: the 0x12 marker is per-BEARER — a
    change-unaware client gets one Database Out Of Sync on EACH bearer it uses
    before resyncing, not once per connection."""
    server, value_handle, csf_handle = _robust_server()
    await _enable_robust_caching(server, csf_handle)
    server.mark_database_changed()

    read = ATT_Read_Request(attribute_handle=value_handle)
    r1 = await server.handle_request(CONN, read, bearer_cid=BEARER1)
    assert isinstance(r1, ATT_Error_Response) and r1.error_code == 0x12
    # Bearer 2 hasn't had its 0x12 yet — the client is still unaware.
    r2 = await server.handle_request(CONN, read, bearer_cid=BEARER2)
    assert isinstance(r2, ATT_Error_Response) and r2.error_code == 0x12
    # The NEXT request on bearer 1 completes the resync (client now aware).
    r3 = await server.handle_request(CONN, read, bearer_cid=BEARER1)
    assert isinstance(r3, ATT_Read_Response) and r3.attribute_value == b"\x01\x02"
    # Aware is per-client: bearer 2 proceeds without another 0x12.
    r4 = await server.handle_request(CONN, read, bearer_cid=BEARER2)
    assert isinstance(r4, ATT_Read_Response) and r4.attribute_value == b"\x01\x02"


async def test_out_of_sync_once_marker_survives_on_other_bearer_after_resync():
    """synced_pending is consumed per bearer: resync on bearer 1 must not
    discard bearer 2's pending marker bookkeeping incorrectly (no crash, and a
    fresh database change re-arms both bearers)."""
    server, value_handle, csf_handle = _robust_server()
    await _enable_robust_caching(server, csf_handle)
    read = ATT_Read_Request(attribute_handle=value_handle)
    server.mark_database_changed()
    await server.handle_request(CONN, read, bearer_cid=BEARER1)  # 0x12 on b1
    await server.handle_request(CONN, read, bearer_cid=BEARER1)  # resync via b1
    # A second db change makes the client unaware again; both bearers re-arm.
    server.mark_database_changed()
    r1 = await server.handle_request(CONN, read, bearer_cid=BEARER2)
    assert isinstance(r1, ATT_Error_Response) and r1.error_code == 0x12
    r2 = await server.handle_request(CONN, read, bearer_cid=BEARER1)
    assert isinstance(r2, ATT_Error_Response) and r2.error_code == 0x12


async def test_bearer_removal_clears_synced_pending_for_cid_reuse():
    """A removed/re-added EATT CID must not inherit a stale '0x12 already sent'
    marker while the client is still change-unaware."""
    server, value_handle, csf_handle = _robust_server()
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    await _enable_robust_caching(server, csf_handle)
    read = ATT_Read_Request(attribute_handle=value_handle)
    server.mark_database_changed()

    r1 = await server.handle_request(CONN, read, bearer_cid=BEARER1)
    assert isinstance(r1, ATT_Error_Response) and r1.error_code == 0x12

    server.remove_eatt_bearer(CONN, BEARER1)
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)

    r2 = await server.handle_request(CONN, read, bearer_cid=BEARER1)
    assert isinstance(r2, ATT_Error_Response) and r2.error_code == 0x12


def _multi_char_server() -> tuple[GATTServer, int, int]:
    """Two readable value characteristics; returns (server, h1, h2)."""
    server = GATTServer()
    handles = server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x180D),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2A38),
                    properties=CharProperties.READ,
                    permissions=Permissions.READABLE,
                    value=b"\x11\x22",
                ),
                CharacteristicDefinition(
                    uuid=UUID16(0x2A39),
                    properties=CharProperties.READ,
                    permissions=Permissions.READABLE,
                    value=b"\x33\x44\x55",
                ),
            ],
        )
    )
    chars = handles.characteristic_handles
    return server, chars[0].value_handle, chars[1].value_handle


async def test_read_multiple_variable_answers_on_each_eatt_bearer():
    """GAR/BV-12: concurrent Read Multiple Variable on two EATT bearers — each
    bearer gets its own complete response."""
    server, h1, h2 = _multi_char_server()
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    server.add_eatt_bearer(CONN, BEARER2, mtu=100)
    pdu = ATT_Read_Multiple_Variable_Request(
        set_of_handles=h1.to_bytes(2, "little") + h2.to_bytes(2, "little"))
    r1 = await server.handle_request(CONN, pdu, bearer_cid=BEARER1)
    r2 = await server.handle_request(CONN, pdu, bearer_cid=BEARER2)
    for rsp in (r1, r2):
        assert isinstance(rsp, ATT_Read_Multiple_Variable_Response)
        assert rsp.values == [b"\x11\x22", b"\x33\x44\x55"]


async def test_mixed_fixed_and_eatt_bearer_reads():
    """GAR/BV-11: the fixed ATT channel and an EATT bearer serve reads
    concurrently, each truncated to its own bearer MTU."""
    server, value_handle = _server()  # 80-byte value
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    read = ATT_Read_Request(attribute_handle=value_handle)
    fixed = await server.handle_request(CONN, read)
    eatt = await server.handle_request(CONN, read, bearer_cid=BEARER1)
    assert len(fixed.attribute_value) == 22   # default MTU 23
    assert len(eatt.attribute_value) == 80    # bearer MTU 100


def _writable_server() -> tuple[GATTServer, int]:
    server = GATTServer()
    handles = server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x180D),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2A38),
                    properties=CharProperties.READ | CharProperties.WRITE,
                    permissions=Permissions.READABLE | Permissions.WRITABLE,
                    value=b"\x00" * 8,
                    max_length=8,
                ),
            ],
        )
    )
    return server, handles.characteristic_handles[0].value_handle


async def test_prepare_write_queue_is_shared_across_bearers():
    """GAW/BV-12: Prepare Writes issued on alternating bearers are committed by
    a single Execute Write (the queue is per-CLIENT, not per-bearer)."""
    server, value_handle = _writable_server()
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    server.add_eatt_bearer(CONN, BEARER2, mtu=100)
    p1 = ATT_Prepare_Write_Request(
        attribute_handle=value_handle, value_offset=0, part_attribute_value=b"AAAA")
    p2 = ATT_Prepare_Write_Request(
        attribute_handle=value_handle, value_offset=4, part_attribute_value=b"BBBB")
    r1 = await server.handle_request(CONN, p1, bearer_cid=BEARER1)
    assert isinstance(r1, ATT_Prepare_Write_Response)
    assert r1.part_attribute_value == b"AAAA"
    r2 = await server.handle_request(CONN, p2, bearer_cid=BEARER2)
    assert isinstance(r2, ATT_Prepare_Write_Response)
    assert r2.part_attribute_value == b"BBBB"
    # One Execute Write — on the FIXED channel even — commits both fragments.
    r3 = await server.handle_request(
        CONN, ATT_Execute_Write_Request(flags=0x01))  # 0x01 = write all prepared values
    assert isinstance(r3, ATT_Execute_Write_Response)
    assert server.db.read(value_handle) == b"AAAABBBB"


def _notify_server() -> tuple[GATTServer, int, int]:
    """Notify characteristic with its CCCD; returns (server, value_handle,
    cccd_handle)."""
    server = GATTServer()
    handles = server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x180D),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2A37),
                    properties=CharProperties.READ | CharProperties.NOTIFY,
                    permissions=Permissions.READABLE,
                    value=b"\x00",
                ),
            ],
        )
    )
    char = handles.characteristic_handles[0]
    assert char.cccd_handle is not None
    return server, char.value_handle, char.cccd_handle


async def test_cccd_written_on_one_bearer_reads_back_on_another():
    """GPM/BV-05: CCCD state is per-CLIENT — a CCCD write on EATT bearer 2 is
    visible to a read on the fixed channel (and to bearer 1)."""
    server, value_handle, cccd_handle = _notify_server()
    server.add_eatt_bearer(CONN, BEARER2, mtu=100)
    w = await server.handle_request(
        CONN,
        ATT_Write_Request(
            attribute_handle=cccd_handle, attribute_value=b"\x01\x00"  # enable notifications
        ),
        bearer_cid=BEARER2,
    )
    assert isinstance(w, ATT_Write_Response)
    for bearer in (CID_ATT, BEARER1):  # fixed + even an unregistered bearer key
        r = await server.handle_request(
            CONN, ATT_Read_Request(attribute_handle=cccd_handle), bearer_cid=bearer)
        assert isinstance(r, ATT_Read_Response)
        assert r.attribute_value == b"\x01\x00"
    assert server._notifications_enabled[CONN] == {value_handle}
