import pytest
import struct
from pybluehost.ble.gatt import (
    AttributeDatabase, GATTServer, GATTClient,
    ServiceDefinition, CharacteristicDefinition, DescriptorDefinition,
    CharProperties, Permissions, ServiceHandles,
)
from pybluehost.ble.att import (
    ATT_Read_Request, ATT_Read_Response,
    ATT_Read_Blob_Request, ATT_Read_Blob_Response,
    ATT_Write_Request, ATT_Write_Response, ATT_Write_Command,
    ATT_Error_Response, ATT_Exchange_MTU_Request,
    ATT_Exchange_MTU_Response,
    ATT_Find_Information_Response,
    ATT_Read_By_Type_Request, ATT_Read_By_Type_Response,
    ATTOpcode,
)
from pybluehost.core.uuid import UUID16


def test_attribute_database_add_and_read():
    db = AttributeDatabase()
    handle = db.add(type_uuid=UUID16(0x2800), permissions=Permissions.READABLE, value=b"\x0D\x18")
    assert handle == 0x0001
    assert db.read(handle) == b"\x0D\x18"


def test_attribute_database_write():
    db = AttributeDatabase()
    handle = db.add(UUID16(0x2803), Permissions.READABLE | Permissions.WRITABLE, b"\x00")
    db.write(handle, b"\xFF")
    assert db.read(handle) == b"\xFF"


def test_attribute_database_read_missing_raises():
    db = AttributeDatabase()
    with pytest.raises(KeyError):
        db.read(0x9999)


def test_gatt_server_add_service_expands_attributes():
    server = GATTServer()
    svc = ServiceDefinition(
        uuid=UUID16(0x180D),
        characteristics=[
            CharacteristicDefinition(
                uuid=UUID16(0x2A37),
                properties=CharProperties.NOTIFY,
                permissions=Permissions.READABLE,
            )
        ]
    )
    handles = server.add_service(svc)
    assert handles.service_handle == 0x0001
    assert handles.characteristic_handles[0].declaration_handle == 0x0002
    assert handles.characteristic_handles[0].value_handle == 0x0003
    assert handles.characteristic_handles[0].cccd_handle == 0x0004


def test_gatt_server_add_service_read_only():
    server = GATTServer()
    svc = ServiceDefinition(
        uuid=UUID16(0x180D),
        characteristics=[
            CharacteristicDefinition(
                uuid=UUID16(0x2A38),
                properties=CharProperties.READ,
                permissions=Permissions.READABLE,
                value=b"\x01",
            )
        ]
    )
    handles = server.add_service(svc)
    # No CCCD since no NOTIFY/INDICATE
    assert handles.characteristic_handles[0].cccd_handle is None
    assert handles.characteristic_handles[0].value_handle == 0x0003
    val = server.db.read(0x0003)
    assert val == b"\x01"


def test_gatt_server_add_service_emits_include_declaration():
    """A ServiceDefinition's includes become 0x2802 attributes emitted right
    after the service declaration and before the first characteristic.

    GATT/SR/GAS/BV-02: a client reaches secondary services ONLY through
    Include declarations, so an include that never reaches the on-air db hides
    the whole secondary service from its Database Hash discovery.
    """
    from pybluehost.ble.gatt import UUID_INCLUDE, IncludeDefinition

    server = GATTServer()
    secondary = server.add_service(ServiceDefinition(
        uuid=UUID16(0xAA40),
        is_primary=False,
        characteristics=[
            CharacteristicDefinition(
                uuid=UUID16(0xAA50), properties=CharProperties.READ,
                permissions=Permissions.READABLE, value=b""),
        ],
    ))
    primary = server.add_service(ServiceDefinition(
        uuid=UUID16(0xAA41),
        includes=[IncludeDefinition(
            start_handle=secondary.service_handle,
            end_handle=secondary.end_handle,
            uuid=UUID16(0xAA40),
        )],
        characteristics=[
            CharacteristicDefinition(
                uuid=UUID16(0xAA51), properties=CharProperties.READ,
                permissions=Permissions.READABLE, value=b""),
        ],
    ))

    inc_handle = primary.service_handle + 1
    inc = server.db.get(inc_handle)
    assert inc is not None
    assert inc.type_uuid.to_bytes() == UUID_INCLUDE.to_bytes()
    assert inc.value == (
        secondary.service_handle.to_bytes(2, "little")
        + secondary.end_handle.to_bytes(2, "little")
        + (0xAA40).to_bytes(2, "little")
    )
    # Secondary service stays reachable through its own group type too.
    groups = server.db.find_by_group_type(0x0001, 0xFFFF, UUID16(0x2801))
    assert groups and groups[0][0] == secondary.service_handle
    assert groups[0][1] == secondary.end_handle


async def test_gatt_server_handle_read_request():
    server = GATTServer()
    svc = ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A38), properties=CharProperties.READ,
                                  permissions=Permissions.READABLE, value=b"\x42")
    ])
    server.add_service(svc)
    req = ATT_Read_Request(attribute_handle=0x0003)
    response = await server.handle_request(conn_handle=0x0001, pdu=req)
    assert isinstance(response, ATT_Read_Response)
    assert response.attribute_value == b"\x42"


async def test_gatt_server_read_request_uses_bound_handler():
    server = GATTServer()
    svc = ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A38), properties=CharProperties.READ,
                                  permissions=Permissions.READABLE, value=b"\x01")
    ])
    server.add_service(svc)

    async def read_location():
        return b"\x02"

    server.register_read_handler(0x0003, read_location)
    response = await server.handle_request(conn_handle=0x0001, pdu=ATT_Read_Request(attribute_handle=0x0003))

    assert isinstance(response, ATT_Read_Response)
    assert response.attribute_value == b"\x02"
    assert server.db.read(0x0003) == b"\x02"


async def test_gatt_server_handle_read_not_found():
    server = GATTServer()
    req = ATT_Read_Request(attribute_handle=0x9999)
    response = await server.handle_request(conn_handle=0x0001, pdu=req)
    assert isinstance(response, ATT_Error_Response)
    # Read Request on a nonexistent handle -> Invalid Handle (0x01) per ATT spec
    # (Attribute Not Found 0x0A is for Read By Type / Find Information range
    # misses). PTS GAR/BI-02 "Invalid Handle Response" requires 0x01.
    assert response.error_code == 0x01  # Invalid Handle


async def test_gatt_server_handle_write_request():
    server = GATTServer()
    svc = ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A38), properties=CharProperties.READ | CharProperties.WRITE,
                                  permissions=Permissions.READABLE | Permissions.WRITABLE, value=b"\x00")
    ])
    server.add_service(svc)
    req = ATT_Write_Request(attribute_handle=0x0003, attribute_value=b"\xFF")
    response = await server.handle_request(conn_handle=0x0001, pdu=req)
    assert isinstance(response, ATT_Write_Response)
    assert server.db.read(0x0003) == b"\xFF"


async def test_gatt_server_write_request_uses_bound_handler():
    server = GATTServer()
    svc = ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A39), properties=CharProperties.WRITE,
                                  permissions=Permissions.WRITABLE, value=b"")
    ])
    server.add_service(svc)
    writes = []

    async def write_control_point(value: bytes):
        writes.append(value)

    server.register_write_handler(0x0003, write_control_point)
    response = await server.handle_request(
        conn_handle=0x0001,
        pdu=ATT_Write_Request(attribute_handle=0x0003, attribute_value=b"\x01"),
    )

    assert isinstance(response, ATT_Write_Response)
    assert writes == [b"\x01"]
    assert server.db.read(0x0003) == b"\x01"


async def test_gatt_server_handle_exchange_mtu():
    server = GATTServer()
    req = ATT_Exchange_MTU_Request(client_rx_mtu=256)
    response = await server.handle_request(conn_handle=0x0001, pdu=req)
    assert isinstance(response, ATT_Exchange_MTU_Response)
    assert response.server_rx_mtu == 512


async def test_gatt_server_write_command_stores_value_without_response():
    """GAP/GAT/BV-05 (Writeable Device Name): PTS writes the new Device Name via
    an ATT **Write Command** (0x52, Write Without Response) then reads it back —
    Pass iff the read returns the written value. The Write Command must commit
    the value and elicit NO ATT response (a command is never responded to)."""
    server = GATTServer()
    svc = ServiceDefinition(uuid=UUID16(0x1800), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A00), properties=CharProperties.READ | CharProperties.WRITE,
                                  permissions=Permissions.READABLE | Permissions.WRITABLE, value=b"PyBlueHost")
    ])
    server.add_service(svc)
    req = ATT_Write_Command(attribute_handle=0x0003, attribute_value=b"PTS-Name")
    response = await server.handle_request(conn_handle=0x0001, pdu=req)
    assert response is None, "Write Command must not be responded to"
    assert server.db.read(0x0003) == b"PTS-Name"


async def test_gatt_server_write_command_not_writable_drops_silently():
    """A Write Command to a non-writable attribute is dropped with no response
    (commands are never answered, even on error) and the value is unchanged."""
    server = GATTServer()
    svc = ServiceDefinition(uuid=UUID16(0x1800), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A00), properties=CharProperties.READ,
                                  permissions=Permissions.READABLE, value=b"PyBlueHost")
    ])
    server.add_service(svc)
    req = ATT_Write_Command(attribute_handle=0x0003, attribute_value=b"PTS-Name")
    response = await server.handle_request(conn_handle=0x0001, pdu=req)
    assert response is None
    assert server.db.read(0x0003) == b"PyBlueHost"


async def test_gatt_server_notify():
    server = GATTServer()
    svc = ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A37), properties=CharProperties.NOTIFY,
                                  permissions=Permissions.READABLE)
    ])
    server.add_service(svc)
    notifications = []
    server.on_notification_sent(lambda handle, value, conn: notifications.append((handle, value)))
    server.enable_notifications(conn_handle=0x0040, value_handle=0x0003)
    await server.notify(handle=0x0003, value=bytes([0x00, 72]), connections=[0x0040])
    assert len(notifications) == 1
    assert notifications[0][1] == bytes([0x00, 72])


def test_gatt_server_find_characteristic_value_handle():
    server = GATTServer()
    svc = ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A37), properties=CharProperties.NOTIFY,
                                  permissions=Permissions.READABLE)
    ])
    server.add_service(svc)
    handle = server.find_characteristic_value_handle(UUID16(0x2A37))
    assert handle == 0x0003  # service(1) + char_decl(2) + value(3)


async def test_gatt_server_cccd_indication_bit_enables_indication():
    """A CCCD write of 0x0002 (indication bit) must enable *indications* on the
    preceding value handle — tracked separately from notifications (0x0001)."""
    server = GATTServer()
    svc = ServiceDefinition(uuid=UUID16(0x1801), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A05), properties=CharProperties.INDICATE,
                                  permissions=Permissions.READABLE, value=b"\x00\x00\x00\x00")
    ])
    server.add_service(svc)
    # value handle = 0x0003, auto-added CCCD = 0x0004.
    req = ATT_Write_Request(attribute_handle=0x0004, attribute_value=b"\x02\x00")
    response = await server.handle_request(conn_handle=0x0001, pdu=req)
    assert isinstance(response, ATT_Write_Response)
    assert 0x0003 in server._indications_enabled[0x0001]
    assert 0x0003 not in server._notifications_enabled.get(0x0001, set())


async def test_gatt_server_indicate_uses_indication_callback_not_notification():
    """indicate() must drive the indication bridge (0x1D), not the notification
    bridge (0x1B) — GAS/BV-01 checks the PDU is an ATT_Handle_Value_Indication."""
    server = GATTServer()
    indications, notifications = [], []
    server.on_indication_sent(lambda h, v, c: indications.append((h, v, c)))
    server.on_notification_sent(lambda h, v, c: notifications.append((h, v, c)))
    await server.indicate(handle=0x0003, value=b"\x01\x00\x05\x00", connection=0x0001)
    assert indications == [(0x0003, b"\x01\x00\x05\x00", 0x0001)]
    assert notifications == []


async def test_indicate_service_changed_sends_range_to_subscribed_only():
    """GAS/BV-01: on db change the IUT indicates Service Changed (value =
    start+end handle) only to connections that enabled its CCCD indication."""
    server = GATTServer()
    svc = ServiceDefinition(uuid=UUID16(0x1801), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A05), properties=CharProperties.INDICATE,
                                  permissions=Permissions.READABLE, value=b"\x00\x00\x00\x00")
    ])
    server.add_service(svc)
    sent = []

    def _cb(h, v, c):
        sent.append((h, v, c))
        return True  # indication bridge delivered it (channel present)

    server.on_indication_sent(_cb)
    # conn 0x0001 subscribes (writes 0x0002 to CCCD 0x0004); conn 0x0002 does not.
    await server.handle_request(conn_handle=0x0001,
                                pdu=ATT_Write_Request(attribute_handle=0x0004, attribute_value=b"\x02\x00"))
    await server.indicate_service_changed(0x0001, 0x0007)
    assert sent == [(0x0003, b"\x01\x00\x07\x00", 0x0001)]
    assert server._service_changed_pending == {}


async def test_service_changed_cccd_persists_across_disconnect():
    """GAS/BV-01/BV-07: a bonded client's Service Changed CCCD subscription
    survives the disconnect so the IUT can resend the indication on reconnect."""
    server = GATTServer()
    svc = ServiceDefinition(uuid=UUID16(0x1801), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A05), properties=CharProperties.INDICATE,
                                  permissions=Permissions.READABLE, value=b"\x00\x00\x00\x00")
    ])
    server.add_service(svc)
    await server.handle_request(conn_handle=0x0001,
                                pdu=ATT_Write_Request(attribute_handle=0x0004, attribute_value=b"\x02\x00"))
    server.remove_connection(0x0001)
    assert 0x0003 in server._indications_enabled[0x0001], \
        "SC CCCD must persist across the disconnect for the reconnect resend"


async def test_indicate_service_changed_marks_pending_when_disconnected():
    """GAS/BV-01/BV-07: a db change while a SC-subscribed client is disconnected
    (bridge reports the channel is gone) is remembered for the reconnect."""
    server = GATTServer()
    svc = ServiceDefinition(uuid=UUID16(0x1801), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A05), properties=CharProperties.INDICATE,
                                  permissions=Permissions.READABLE, value=b"\x00\x00\x00\x00")
    ])
    server.add_service(svc)

    def _cb(h, v, c):
        return False  # channel absent — indication not delivered

    server.on_indication_sent(_cb)
    await server.handle_request(conn_handle=0x0001,
                                pdu=ATT_Write_Request(attribute_handle=0x0004, attribute_value=b"\x02\x00"))
    server.remove_connection(0x0001)
    await server.indicate_service_changed(0x0001, 0x0007)
    assert server._service_changed_pending == {0x0001: (0x0001, 0x0007)}


def _notify_server() -> GATTServer:
    """Server with one NOTIFY characteristic: value 0x0003, CCCD 0x0004."""
    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0xAA40), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0xAA50),
                                  properties=CharProperties.READ | CharProperties.NOTIFY,
                                  permissions=Permissions.READABLE, value=b"\x00"),
    ]))
    return server


async def test_update_attribute_value_notifies_subscribers():
    """BTP SET_VALUE is the Upper Tester's only lever for making the IUT server
    send a notification (GATT/SR/GAN/BV-01 step 1-2): store the value and push
    ATT_HANDLE_VALUE_NTF (0x1B) to every CCCD subscriber."""
    server = _notify_server()
    sent = []
    server.on_notification_sent(lambda h, v, c: sent.append((h, v, c)))
    await server.handle_request(conn_handle=0x0001,
                                pdu=ATT_Write_Request(attribute_handle=0x0004,
                                                      attribute_value=b"\x01\x00"))

    await server.update_attribute_value(0x0003, b"\xef\xcd\xab")

    assert sent == [(0x0003, b"\xef\xcd\xab", 0x0001)]
    assert server.db.read(0x0003) == b"\xef\xcd\xab", \
        "the committed db value must change too (later reads see it)"


async def test_update_attribute_value_sends_nothing_without_subscription():
    server = _notify_server()
    sent = []
    server.on_notification_sent(lambda h, v, c: sent.append((h, v, c)))

    await server.update_attribute_value(0x0003, b"\x01")

    assert sent == []
    assert server.db.read(0x0003) == b"\x01", "value still stored"


async def test_update_attribute_value_indicates_indication_subscribers():
    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0xAA40), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0xAA50),
                                  properties=CharProperties.READ | CharProperties.INDICATE,
                                  permissions=Permissions.READABLE, value=b"\x00"),
    ]))
    sent = []
    server.on_indication_sent(lambda h, v, c: sent.append((h, v, c)) or True)
    await server.handle_request(conn_handle=0x0001,
                                pdu=ATT_Write_Request(attribute_handle=0x0004,
                                                      attribute_value=b"\x02\x00"))

    await server.update_attribute_value(0x0003, b"\x07")

    assert sent == [(0x0003, b"\x07", 0x0001)]


async def test_unbonded_disconnect_resets_the_cccd():
    """GATT.TS GAN/BV-01 step 5A: after a non-bonded client disconnects and
    reconnects, the CCCD must read 0x0000."""
    server = _notify_server()
    await server.handle_request(conn_handle=0x0001,
                                pdu=ATT_Write_Request(attribute_handle=0x0004,
                                                      attribute_value=b"\x01\x00"))
    assert server.db.read(0x0004) == b"\x01\x00"

    server.remove_connection(0x0001, bonded=False)

    assert server.db.read(0x0004) == b"\x00\x00"


async def test_bonded_disconnect_keeps_the_cccd():
    """GATT.TS GAN/BV-03 step 5B: a bonded client's CCCD survives the
    disconnect (value 0x0001 on reconnect)."""
    server = _notify_server()
    await server.handle_request(conn_handle=0x0001,
                                pdu=ATT_Write_Request(attribute_handle=0x0004,
                                                      attribute_value=b"\x01\x00"))

    server.remove_connection(0x0001, bonded=True)

    assert server.db.read(0x0004) == b"\x01\x00"


async def test_unbonded_disconnect_resets_the_service_changed_cccd():
    """GATT.TS GAI/BV-01 step 7A.1: the Service Changed CCCD is *not* exempt —
    a non-bonded client must read 0x0000 after reconnecting, and its
    subscription (plus any deferred indication) is dropped with it."""
    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x1801), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A05), properties=CharProperties.INDICATE,
                                  permissions=Permissions.READABLE, value=b"\x00\x00\x00\x00")
    ]))
    server.add_service(ServiceDefinition(uuid=UUID16(0xAA40), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0xAA50), properties=CharProperties.INDICATE,
                                  permissions=Permissions.READABLE, value=b"\x00"),
    ]))
    await server.handle_request(conn_handle=0x0001,
                                pdu=ATT_Write_Request(attribute_handle=0x0004,
                                                      attribute_value=b"\x02\x00"))
    await server.handle_request(conn_handle=0x0001,
                                pdu=ATT_Write_Request(attribute_handle=0x0008,
                                                      attribute_value=b"\x02\x00"))
    server._service_changed_pending[0x0001] = (0x0001, 0x0007)

    server.remove_connection(0x0001, bonded=False)

    assert server.db.read(0x0004) == b"\x00\x00", "SC CCCD must be reset too"
    assert server.db.read(0x0008) == b"\x00\x00", "other CCCDs reset"
    assert server._indications_enabled.get(0x0001) is None
    assert 0x0001 not in server._service_changed_pending


async def test_bonded_disconnect_keeps_the_service_changed_cccd():
    """GAS/BV-01/BV-07: the clients that need the deferred Service Changed
    indication after reconnecting are bonded, so the bonded path keeps both the
    CCCD value and the subscription (and the pending range)."""
    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x1801), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A05), properties=CharProperties.INDICATE,
                                  permissions=Permissions.READABLE, value=b"\x00\x00\x00\x00")
    ]))
    await server.handle_request(conn_handle=0x0001,
                                pdu=ATT_Write_Request(attribute_handle=0x0004,
                                                      attribute_value=b"\x02\x00"))
    server._service_changed_pending[0x0001] = (0x0001, 0x0007)

    server.remove_connection(0x0001, bonded=True)

    assert server.db.read(0x0004) == b"\x02\x00", "SC CCCD must persist"
    assert server._indications_enabled.get(0x0001) == {0x0003}
    assert server._service_changed_pending.get(0x0001) == (0x0001, 0x0007)


async def test_reconnect_flushes_pending_service_changed_indication():
    """GAS/BV-01/BV-07: on reconnect the IUT proactively resends the Service
    Changed indication it deferred while the bonded client was disconnected —
    the Lower Tester waits for it without issuing any ATT request first."""
    server = GATTServer()
    svc = ServiceDefinition(uuid=UUID16(0x1801), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A05), properties=CharProperties.INDICATE,
                                  permissions=Permissions.READABLE, value=b"\x00\x00\x00\x00")
    ])
    server.add_service(svc)
    sent = []

    def _cb(h, v, c):
        sent.append((h, v, c))
        return True

    server.on_indication_sent(_cb)
    await server.handle_request(conn_handle=0x0001,
                                pdu=ATT_Write_Request(attribute_handle=0x0004, attribute_value=b"\x02\x00"))
    server.remove_connection(0x0001)
    server._service_changed_pending[0x0001] = (0x0001, 0x0007)

    # Reconnect: the connection-opened hook flushes the deferred indication.
    await server.on_connection_opened(0x0001)
    assert sent == [(0x0003, b"\x01\x00\x07\x00", 0x0001)]
    assert server._service_changed_pending == {}




async def test_gatt_client_discovers_characteristics():
    class FakeBearer:
        async def _request(self, pdu, response_opcode):
            assert response_opcode == ATTOpcode.READ_BY_TYPE_RESPONSE
            assert pdu.attribute_type == UUID16(0x2803).to_bytes()
            return ATT_Read_By_Type_Response(
                length=7,
                attribute_data_list=(
                    struct.pack("<H", 0x0002)
                    + bytes([int(CharProperties.READ)])
                    + struct.pack("<H", 0x0003)
                    + UUID16(0x2A19).to_bytes()
                ),
            )

    client = GATTClient(FakeBearer())

    chars = await client.discover_characteristics(0x0001, 0x0005)

    assert len(chars) == 1
    assert chars[0].declaration_handle == 0x0002
    assert chars[0].value_handle == 0x0003
    assert chars[0].uuid == UUID16(0x2A19).to_bytes()


async def test_gatt_client_discovers_descriptors():
    class FakeBearer:
        async def _request(self, pdu, response_opcode):
            assert response_opcode == ATTOpcode.FIND_INFORMATION_RESPONSE
            return ATT_Find_Information_Response(
                format=0x01,
                information_data=(
                    struct.pack("<H", 0x0004)
                    + UUID16(0x2902).to_bytes()
                ),
            )

    client = GATTClient(FakeBearer())

    descriptors = await client.discover_descriptors(0x0004, 0x0005)
    assert len(descriptors) == 1
    assert descriptors[0].handle == 0x0004
    assert descriptors[0].uuid == UUID16(0x2902).to_bytes()


async def test_gatt_client_discovers_included_services():
    """discover_included_services parses ATT Read By Type (0x2802) entries:
    incl_handle(2) + inc_start(2) + inc_end(2) + uuid."""
    class FakeBearer:
        async def _request(self, pdu, response_opcode):
            assert response_opcode == ATTOpcode.READ_BY_TYPE_RESPONSE
            assert pdu.attribute_type == UUID16(0x2802).to_bytes()
            return ATT_Read_By_Type_Response(
                length=8,
                attribute_data_list=(
                    struct.pack("<H", 0x0003)      # include declaration handle
                    + struct.pack("<H", 0x0010)    # included svc start handle
                    + struct.pack("<H", 0x0014)    # included svc end handle
                    + UUID16(0x180F).to_bytes()    # included svc uuid
                ),
            )

    client = GATTClient(FakeBearer())

    includes = await client.discover_included_services(0x0001, 0xFFFF)

    assert includes == [(0x0003, 0x0010, 0x0014, UUID16(0x180F).to_bytes())]


# --- ATT MTU truncation (PTS GATT/SR read cases connect without Exchange MTU,
# so the default ATT_MTU=23 applies; oversized responses are protocol violations
# that stall PTS to the time_guard). Regression for the GAR PTS-TIMEOUT bug. ---

def _multi_char_server(count: int) -> GATTServer:
    """Build a server whose single service exposes `count` read chars, so a
    Read By Type (0x2803) across it naturally exceeds the 23-byte default MTU."""
    server = GATTServer()
    chars = [
        CharacteristicDefinition(uuid=UUID16(0x2A38), properties=CharProperties.READ,
                                  permissions=Permissions.READABLE, value=b"\x01\x02\x03\x04")
        for _ in range(count)
    ]
    server.add_service(ServiceDefinition(uuid=UUID16(0x180D), characteristics=chars))
    return server


async def test_read_by_type_truncates_to_default_mtu():
    """Without Exchange MTU the response must fit 23 bytes (opcode+len+data)."""
    server = _multi_char_server(8)  # 8 chars -> untruncated would be ~50 bytes
    req = ATT_Read_By_Type_Request(
        starting_handle=0x0001, ending_handle=0xFFFF,
        attribute_type=UUID16(0x2803).to_bytes(),
    )
    resp = await server.handle_request(conn_handle=0x0001, pdu=req)
    assert isinstance(resp, ATT_Read_By_Type_Response)
    # 1 (opcode) + 1 (length) + len(data) must not exceed 23.
    assert 2 + len(resp.attribute_data_list) <= 23
    # Each entry is handle(2)+value(4)=6 bytes -> at most 3 entries fit in 21.
    assert len(resp.attribute_data_list) % resp.length == 0
    assert len(resp.attribute_data_list) == 3 * resp.length


async def test_read_by_type_uses_negotiated_mtu_after_exchange():
    server = _multi_char_server(8)
    # Negotiate a larger MTU first.
    await server.handle_request(conn_handle=0x0001,
                                pdu=ATT_Exchange_MTU_Request(client_rx_mtu=100))
    req = ATT_Read_By_Type_Request(
        starting_handle=0x0001, ending_handle=0xFFFF,
        attribute_type=UUID16(0x2803).to_bytes(),
    )
    resp = await server.handle_request(conn_handle=0x0001, pdu=req)
    assert 2 + len(resp.attribute_data_list) <= 100
    # With MTU 100 all 8 six-byte entries (48 bytes) fit.
    assert len(resp.attribute_data_list) == 8 * resp.length


async def test_read_response_truncates_long_value_to_default_mtu():
    server = GATTServer()
    long_val = bytes(range(60))
    server.add_service(ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A38), properties=CharProperties.READ,
                                  permissions=Permissions.READABLE, value=long_val)
    ]))
    resp = await server.handle_request(conn_handle=0x0001,
                                       pdu=ATT_Read_Request(attribute_handle=0x0003))
    assert isinstance(resp, ATT_Read_Response)
    assert len(resp.attribute_value) == 22  # ATT_MTU(23) - 1 (opcode)
    assert resp.attribute_value == long_val[:22]


async def test_read_blob_returns_offset_slice():
    server = GATTServer()
    long_val = bytes(range(60))
    server.add_service(ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A38), properties=CharProperties.READ,
                                  permissions=Permissions.READABLE, value=long_val)
    ]))
    resp = await server.handle_request(
        conn_handle=0x0001,
        pdu=ATT_Read_Blob_Request(attribute_handle=0x0003, value_offset=22))
    assert isinstance(resp, ATT_Read_Blob_Response)
    assert resp.part_attribute_value == long_val[22:44]  # next 22 bytes


async def test_read_blob_invalid_offset_rejected():
    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A38), properties=CharProperties.READ,
                                  permissions=Permissions.READABLE, value=b"\x01\x02")
    ]))
    resp = await server.handle_request(
        conn_handle=0x0001,
        pdu=ATT_Read_Blob_Request(attribute_handle=0x0003, value_offset=10))
    assert isinstance(resp, ATT_Error_Response)
    assert resp.error_code == 0x07  # Invalid Offset


# --- ATT security error codes + Read Multiple + Prepare/Execute Write -------
# Regression for the PTS GATT/SR BI (error-handling) cluster: the server must
# map ENC/AUTHN/AUTHZ permission bits + enc_key_size to the exact ATT error
# code, and support Read Multiple / Prepare+Execute Write. PTS BI cases connect
# UNENCRYPTED, so the default (absent) security state must trigger the errors.

from pybluehost.ble.gatt import (
    PERM_READ, PERM_WRITE, PERM_READ_ENC, PERM_READ_AUTHN, PERM_READ_AUTHZ,
    PERM_WRITE_ENC, PERM_WRITE_AUTHN, PERM_WRITE_AUTHZ,
)
from pybluehost.ble.att import (
    ATT_Read_Multiple_Request, ATT_Read_Multiple_Response,
    ATT_Read_Multiple_Variable_Request, ATT_Read_Multiple_Variable_Response,
    ATT_Prepare_Write_Request, ATT_Prepare_Write_Response,
    ATT_Execute_Write_Request, ATT_Execute_Write_Response,
)


def _server_with(perms: int, value: bytes = b"\x01\x02", enc_key_size: int = 0):
    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A38),
                                 properties=CharProperties.READ | CharProperties.WRITE,
                                 permissions=perms, value=value, enc_key_size=enc_key_size)
    ]))
    return server  # value handle is 0x0003


async def test_read_enc_required_unpaired_unencrypted_returns_insufficient_authentication():
    # GAP Vol 3 Part C §10.3: on an UNPAIRED link a read_enc char must return
    # 0x05 (Insufficient Authentication) so PTS is driven to PAIR — returning
    # 0x0F (Insufficient Encryption) is unactionable (no LTK to encrypt with)
    # and PTS gives up. PTS GAP/SEC/AUT/BV-11 regression.
    server = _server_with(PERM_READ | PERM_READ_ENC)
    resp = await server.handle_request(0x0001, ATT_Read_Request(attribute_handle=0x0003))
    assert isinstance(resp, ATT_Error_Response)
    assert resp.error_code == 0x05  # Insufficient Authentication (unpaired -> pair)


async def test_read_enc_required_bonded_unencrypted_returns_insufficient_encryption():
    # Once bonded (authenticated) but not yet encrypted, 0x0F is correct: PTS
    # just needs to turn on encryption with the existing LTK, not re-pair.
    server = _server_with(PERM_READ | PERM_READ_ENC)
    server.set_connection_security(0x0001, encrypted=False, authenticated=True, key_size=16)
    resp = await server.handle_request(0x0001, ATT_Read_Request(attribute_handle=0x0003))
    assert isinstance(resp, ATT_Error_Response)
    assert resp.error_code == 0x0F  # Insufficient Encryption (bonded -> encrypt)


async def test_read_authn_required_returns_insufficient_authentication():
    server = _server_with(PERM_READ | PERM_READ_AUTHN)
    resp = await server.handle_request(0x0001, ATT_Read_Request(attribute_handle=0x0003))
    assert resp.error_code == 0x05  # Insufficient Authentication


async def test_read_authz_required_returns_insufficient_authorization():
    server = _server_with(PERM_READ | PERM_READ_AUTHZ)
    resp = await server.handle_request(0x0001, ATT_Read_Request(attribute_handle=0x0003))
    assert resp.error_code == 0x08  # Insufficient Authorization


# --- Standalone security-bit perms (the REAL PTS BTP db shape) --------------
# The BTP GATT ADD_CHAR perm byte encodes the security level as INDEPENDENT
# bits and does NOT set the plain read/write bit: e.g. a "read requires
# encryption" char is stored as read_enc|write_enc = 0x0C with the plain
# read(0x01)/write(0x02) bits CLEAR. The server must still treat it as
# readable/writable and return the *specific* security error (0x0F/0x05/0x08),
# not 0x02/0x03. Regression for the GATT/SR GAR+GAW BI cluster, where every
# security-gated char wrongly returned Read/Write Not Permitted.

async def test_standalone_read_enc_unencrypted_returns_0x05_not_0x02():
    # perm byte 0x0C = read_enc|write_enc, plain read/write bits clear.
    # Default (absent) security = UNPAIRED -> 0x05 (Insufficient Authentication),
    # NOT Read Not Permitted (0x02). GAP §10.3 unpaired->pair rule.
    server = _server_with(PERM_READ_ENC | PERM_WRITE_ENC)
    resp = await server.handle_request(0x0001, ATT_Read_Request(attribute_handle=0x0003))
    assert isinstance(resp, ATT_Error_Response)
    assert resp.error_code == 0x05  # Insufficient Authentication, NOT Read Not Permitted


async def test_standalone_read_enc_bonded_unencrypted_returns_0x0f():
    # Same standalone perm shape but on a BONDED (authenticated) link -> 0x0F.
    server = _server_with(PERM_READ_ENC | PERM_WRITE_ENC)
    server.set_connection_security(0x0001, encrypted=False, authenticated=True, key_size=16)
    resp = await server.handle_request(0x0001, ATT_Read_Request(attribute_handle=0x0003))
    assert resp.error_code == 0x0F  # Insufficient Encryption (bonded -> encrypt)


async def test_standalone_read_authn_returns_0x05_not_0x02():
    # perm byte 0x30 = read_authn|write_authn.
    server = _server_with(PERM_READ_AUTHN | PERM_WRITE_AUTHN)
    resp = await server.handle_request(0x0001, ATT_Read_Request(attribute_handle=0x0003))
    assert resp.error_code == 0x05  # Insufficient Authentication


async def test_standalone_read_authz_returns_0x08_not_0x02():
    # perm byte 0xC0 = read_authz|write_authz.
    server = _server_with(PERM_READ_AUTHZ | PERM_WRITE_AUTHZ)
    resp = await server.handle_request(0x0001, ATT_Read_Request(attribute_handle=0x0003))
    assert resp.error_code == 0x08  # Insufficient Authorization


async def test_standalone_write_enc_unencrypted_returns_0x05_not_0x03():
    server = _server_with(PERM_READ_ENC | PERM_WRITE_ENC)
    resp = await server.handle_request(
        0x0001, ATT_Write_Request(attribute_handle=0x0003, attribute_value=b"\x01"))
    assert resp.error_code == 0x05  # Insufficient Authentication, NOT Write Not Permitted


async def test_standalone_write_enc_bonded_unencrypted_returns_0x0f():
    server = _server_with(PERM_READ_ENC | PERM_WRITE_ENC)
    server.set_connection_security(0x0001, encrypted=False, authenticated=True, key_size=16)
    resp = await server.handle_request(
        0x0001, ATT_Write_Request(attribute_handle=0x0003, attribute_value=b"\x01"))
    assert resp.error_code == 0x0F  # Insufficient Encryption (bonded -> encrypt)


async def test_standalone_read_enc_passes_when_encrypted():
    server = _server_with(PERM_READ_ENC | PERM_WRITE_ENC, value=b"\xAA")
    server.set_connection_security(0x0001, encrypted=True, authenticated=True, key_size=16)
    resp = await server.handle_request(0x0001, ATT_Read_Request(attribute_handle=0x0003))
    assert isinstance(resp, ATT_Read_Response)
    assert resp.attribute_value == b"\xAA"


async def test_no_read_bits_at_all_returns_0x02():
    # A genuinely non-readable attribute (write-only): no read-level bit set.
    server = _server_with(PERM_WRITE)
    resp = await server.handle_request(0x0001, ATT_Read_Request(attribute_handle=0x0003))
    assert resp.error_code == 0x02  # Read Not Permitted


async def test_read_enc_key_size_too_small_returns_0x0c():
    server = _server_with(PERM_READ | PERM_READ_ENC, enc_key_size=15)
    # Link encrypted but with only a 7-byte key (< required 15).
    server.set_connection_security(0x0001, encrypted=True, authenticated=True, key_size=7)
    resp = await server.handle_request(0x0001, ATT_Read_Request(attribute_handle=0x0003))
    assert resp.error_code == 0x0C  # Insufficient Encryption Key Size


async def test_read_enc_required_passes_when_encrypted():
    server = _server_with(PERM_READ | PERM_READ_ENC, value=b"\xAA", enc_key_size=7)
    server.set_connection_security(0x0001, encrypted=True, authenticated=True, key_size=16)
    resp = await server.handle_request(0x0001, ATT_Read_Request(attribute_handle=0x0003))
    assert isinstance(resp, ATT_Read_Response)
    assert resp.attribute_value == b"\xAA"


async def test_write_not_permitted_returns_0x03():
    server = _server_with(PERM_READ)  # no write bit
    resp = await server.handle_request(
        0x0001, ATT_Write_Request(attribute_handle=0x0003, attribute_value=b"\x01"))
    assert resp.error_code == 0x03  # Write Not Permitted


async def test_read_multiple_concatenates_values():
    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A38), properties=CharProperties.READ,
                                  permissions=PERM_READ, value=b"\x01\x02"),
        CharacteristicDefinition(uuid=UUID16(0x2A39), properties=CharProperties.READ,
                                  permissions=PERM_READ, value=b"\x03"),
    ]))
    # value handles 0x0003 (2 bytes) and 0x0005 (1 byte): svc(1) decl(2) val(3)
    # decl(4) val(5), no CCCD (read-only).
    handles = struct.pack("<HH", 0x0003, 0x0005)
    resp = await server.handle_request(0x0001, ATT_Read_Multiple_Request(set_of_handles=handles))
    assert isinstance(resp, ATT_Read_Multiple_Response)
    assert resp.set_of_values == b"\x01\x02\x03"


async def test_read_multiple_invalid_handle_returns_0x01():
    server = _server_with(PERM_READ)
    handles = struct.pack("<HH", 0x0003, 0x00FF)
    resp = await server.handle_request(0x0001, ATT_Read_Multiple_Request(set_of_handles=handles))
    assert isinstance(resp, ATT_Error_Response)
    assert resp.error_code == 0x01
    assert resp.attribute_handle_in_error == 0x00FF


async def test_prepare_execute_write_commits_long_value():
    server = GATTServer()
    # Realistic PTS long-write target: a pre-existing 6-byte value that the
    # prepare/execute sequence overwrites in fragments (offsets must be within
    # the current value length, per the Invalid Offset rule).
    server.add_service(ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A38), properties=CharProperties.WRITE,
                                  permissions=PERM_WRITE, value=b"\x00" * 6),
    ]))
    # Two prepare fragments at offsets 0 and 4, then execute.
    r1 = await server.handle_request(0x0001, ATT_Prepare_Write_Request(
        attribute_handle=0x0003, value_offset=0, part_attribute_value=b"\x01\x02\x03\x04"))
    assert isinstance(r1, ATT_Prepare_Write_Response)
    assert r1.part_attribute_value == b"\x01\x02\x03\x04"
    r2 = await server.handle_request(0x0001, ATT_Prepare_Write_Request(
        attribute_handle=0x0003, value_offset=4, part_attribute_value=b"\x05\x06"))
    assert isinstance(r2, ATT_Prepare_Write_Response)
    rexec = await server.handle_request(0x0001, ATT_Execute_Write_Request(flags=0x01))
    assert isinstance(rexec, ATT_Execute_Write_Response)
    assert server.db.read(0x0003) == b"\x01\x02\x03\x04\x05\x06"


async def test_execute_write_cancel_discards_queue():
    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A38), properties=CharProperties.WRITE,
                                  permissions=PERM_WRITE, value=b"\xFF"),
    ]))
    await server.handle_request(0x0001, ATT_Prepare_Write_Request(
        attribute_handle=0x0003, value_offset=0, part_attribute_value=b"\x01"))
    await server.handle_request(0x0001, ATT_Execute_Write_Request(flags=0x00))  # cancel
    assert server.db.read(0x0003) == b"\xFF"  # unchanged


# --- Read Multiple Variable Length (0x20) + Read-Using-UUID security --------
# Regression for PTS GATT/SR GAR BI-36..44 (Read Multiple Variable) and
# BI-09..11 (Read Using Characteristic UUID with a security-gated target).

def _three_char_server():
    """svc(1); char A decl(2)/val(3)=b'AB'; char B decl(4)/val(5)=b'CDE';
    char C decl(6)/val(7) read_enc."""
    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0xAA00), properties=CharProperties.READ,
                                  permissions=PERM_READ, value=b"AB"),
        CharacteristicDefinition(uuid=UUID16(0xAA01), properties=CharProperties.READ,
                                  permissions=PERM_READ, value=b"CDE"),
        CharacteristicDefinition(uuid=UUID16(0xAA02), properties=CharProperties.READ,
                                  permissions=PERM_READ_ENC, value=b"secret"),
    ]))
    return server  # value handles 0x0003, 0x0005, 0x0007


async def test_read_multiple_variable_returns_length_prefixed_values():
    server = _three_char_server()
    handles = struct.pack("<HH", 0x0003, 0x0005)
    resp = await server.handle_request(0x0001, ATT_Read_Multiple_Variable_Request(set_of_handles=handles))
    assert isinstance(resp, ATT_Read_Multiple_Variable_Response)
    assert resp.values == [b"AB", b"CDE"]
    # Wire format: opcode + [len][value][len][value]
    assert resp.to_bytes() == bytes([0x21, 2]) + b"AB" + bytes([3]) + b"CDE"


async def test_read_multiple_variable_invalid_handle_returns_0x01():
    server = _three_char_server()
    handles = struct.pack("<HH", 0x0003, 0x00FF)
    resp = await server.handle_request(0x0001, ATT_Read_Multiple_Variable_Request(set_of_handles=handles))
    assert isinstance(resp, ATT_Error_Response)
    assert resp.error_code == 0x01
    assert resp.attribute_handle_in_error == 0x00FF


async def test_read_multiple_variable_security_char_returns_its_error():
    server = _three_char_server()
    # First handle ok, second requires encryption on an UNPAIRED link -> 0x05
    # (Insufficient Authentication, GAP §10.3 unpaired->pair) at that handle.
    handles = struct.pack("<HH", 0x0003, 0x0007)
    resp = await server.handle_request(0x0001, ATT_Read_Multiple_Variable_Request(set_of_handles=handles))
    assert isinstance(resp, ATT_Error_Response)
    assert resp.error_code == 0x05
    assert resp.attribute_handle_in_error == 0x0007


async def test_read_using_uuid_security_char_returns_error_not_value():
    """Read By Type with a characteristic-value UUID (Read Using Char UUID) must
    return the security error for a gated match, not silently return 0x0A or the
    value. Declaration-type discovery (0x2803) stays unaffected."""
    server = _three_char_server()
    # Read Using UUID for the enc-gated char 0xAA02 (value handle 0x0007).
    req = ATT_Read_By_Type_Request(starting_handle=0x0001, ending_handle=0xFFFF,
                                   attribute_type=UUID16(0xAA02).to_bytes())
    resp = await server.handle_request(0x0001, req)
    assert isinstance(resp, ATT_Error_Response)
    assert resp.error_code == 0x05  # Insufficient Authentication (unpaired -> pair, GAP §10.3)
    assert resp.attribute_handle_in_error == 0x0007


async def test_read_using_uuid_readable_char_returns_value():
    server = _three_char_server()
    req = ATT_Read_By_Type_Request(starting_handle=0x0001, ending_handle=0xFFFF,
                                   attribute_type=UUID16(0xAA00).to_bytes())
    resp = await server.handle_request(0x0001, req)
    assert isinstance(resp, ATT_Read_By_Type_Response)
    # handle(0x0003 LE) + value(b"AB")
    assert resp.attribute_data_list == struct.pack("<H", 0x0003) + b"AB"


def test_add_service_does_not_duplicate_explicit_ccc():
    """PTS BTP init_server supplies the CCC descriptor explicitly via
    ADD_DESCRIPTOR; add_service must not auto-add a second one for a notify
    char (a duplicate CCC shifts every subsequent handle off the reference db)."""
    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A37),
                                 properties=CharProperties.READ | CharProperties.NOTIFY,
                                 permissions=PERM_READ, value=b"\x00",
                                 descriptors=[DescriptorDefinition(
                                     uuid=UUID16(0x2902), permissions=PERM_READ | PERM_WRITE,
                                     value=b"\x00\x00")]),
    ]))
    cccds = [a for a in server.db._attrs if a.type_uuid.to_bytes() == UUID16(0x2902).to_bytes()]
    assert len(cccds) == 1  # exactly one CCC, not two


def test_add_service_still_auto_adds_ccc_when_not_supplied():
    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A37),
                                 properties=CharProperties.READ | CharProperties.NOTIFY,
                                 permissions=PERM_READ, value=b"\x00"),
    ]))
    cccds = [a for a in server.db._attrs if a.type_uuid.to_bytes() == UUID16(0x2902).to_bytes()]
    assert len(cccds) == 1  # auto-added exactly once



async def test_execute_write_rejects_value_past_declared_max_length():
    """GATT/SR/GAW/BI-33 (Write Long, Attribute Value Length Too Long): every
    Prepare Write carries valid parameters and the rejection comes on the
    Execute Write, with ATT error 0x0D (Core Vol 3 Part F §3.4.6.4)."""
    from pybluehost.ble.att import (
        ATT_Error_Response, ATT_Execute_Write_Request, ATT_Prepare_Write_Request,
        ATT_Prepare_Write_Response,
    )
    from pybluehost.ble.gatt import ATT_ERR_INVALID_ATTRIBUTE_VALUE_LENGTH

    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x1800), characteristics=[
        CharacteristicDefinition(
            uuid=UUID16(0x2A00), properties=CharProperties.READ | CharProperties.WRITE,
            permissions=Permissions.READABLE | Permissions.WRITABLE,
            value=b"12345678",      # declared size = 8
            max_length=8,
        )
    ]))
    value_handle = 0x0003

    # Two valid fragments covering 10 bytes — together they exceed the size.
    for offset, frag in ((0x0000, b"ABCDE"), (0x0005, b"FGHIJ")):
        resp = await server.handle_request(0x0001, ATT_Prepare_Write_Request(
            attribute_handle=value_handle, value_offset=offset,
            part_attribute_value=frag,
        ))
        assert isinstance(resp, ATT_Prepare_Write_Response)

    resp = await server.handle_request(0x0001, ATT_Execute_Write_Request(flags=0x01))

    assert isinstance(resp, ATT_Error_Response)
    assert resp.error_code == ATT_ERR_INVALID_ATTRIBUTE_VALUE_LENGTH
    assert resp.attribute_handle_in_error == value_handle
    assert server.db.read(value_handle) == b"12345678"     # unchanged


async def test_execute_write_within_declared_max_length_commits():
    from pybluehost.ble.att import (
        ATT_Execute_Write_Request, ATT_Execute_Write_Response, ATT_Prepare_Write_Request,
    )

    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x1800), characteristics=[
        CharacteristicDefinition(
            uuid=UUID16(0x2A00), properties=CharProperties.READ | CharProperties.WRITE,
            permissions=Permissions.READABLE | Permissions.WRITABLE,
            value=b"12345678", max_length=8,
        )
    ]))
    await server.handle_request(0x0001, ATT_Prepare_Write_Request(
        attribute_handle=0x0003, value_offset=0x0000, part_attribute_value=b"ABCDE",
    ))
    await server.handle_request(0x0001, ATT_Prepare_Write_Request(
        attribute_handle=0x0003, value_offset=0x0005, part_attribute_value=b"FGH",
    ))

    resp = await server.handle_request(0x0001, ATT_Execute_Write_Request(flags=0x01))

    assert isinstance(resp, ATT_Execute_Write_Response)
    assert server.db.read(0x0003) == b"ABCDEFGH"


async def test_write_request_rejects_value_longer_than_declared_max():
    """GATT/SR/GAW/BI-32 (Write Characteristic Value, too long) → 0x0D."""
    from pybluehost.ble.att import ATT_Error_Response, ATT_Write_Request
    from pybluehost.ble.gatt import ATT_ERR_INVALID_ATTRIBUTE_VALUE_LENGTH

    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x1800), characteristics=[
        CharacteristicDefinition(
            uuid=UUID16(0x2A00), properties=CharProperties.READ | CharProperties.WRITE,
            permissions=Permissions.READABLE | Permissions.WRITABLE,
            value=b"12345678", max_length=8,
        )
    ]))

    resp = await server.handle_request(0x0001, ATT_Write_Request(
        attribute_handle=0x0003, attribute_value=b"123456789",
    ))

    assert isinstance(resp, ATT_Error_Response)
    assert resp.error_code == ATT_ERR_INVALID_ATTRIBUTE_VALUE_LENGTH
    assert server.db.read(0x0003) == b"12345678"     # unchanged


def test_characteristic_declaration_uses_le_uuid_on_the_wire():
    """GATT/SR/GAR/BV-03 (Read using Characteristic UUID): a 128-bit UUID in a
    characteristic declaration must be little-endian on the wire. UUID128 stores
    big-endian internally (RFC 4122 order), so the declaration must reverse it."""
    from pybluehost.ble.gatt import (
        CharProperties, CharacteristicDefinition, GATTServer,
        Permissions, ServiceDefinition,
    )
    from pybluehost.core.uuid import UUID128, UUID16

    server = GATTServer()
    uuid128 = UUID128(bytes(range(16)))  # BE: 00 01 02 ... 0f
    server.add_service(ServiceDefinition(
        uuid=UUID16(0x1801),
        characteristics=[CharacteristicDefinition(
            uuid=uuid128, properties=CharProperties.READ,
            permissions=Permissions.READABLE, value=b"\x00")],
    ))
    # service decl(1) + char decl(2) + value(3): declaration value at handle 2.
    decl = server.db.get(0x0002)
    # decl value = properties(1) + value_handle(2 LE) + uuid(16 LE)
    uuid_on_wire = decl.value[3:]
    assert uuid_on_wire == bytes(range(16))[::-1], \
        "128-bit UUID must be little-endian on the wire (reversed from BE internal)"


async def test_read_by_type_truncates_a_long_value_to_the_mtu():
    """GAR/BV-03 (Read using Characteristic UUID): a matching value longer than
    the ATT_MTU must be returned truncated, not dropped — the client then reads
    the remainder with Read Blob."""
    from pybluehost.core.uuid import UUID16

    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A37), properties=CharProperties.READ,
                                  permissions=Permissions.READABLE, value=b"\xAA" * 32)
    ]))
    req = ATT_Read_By_Type_Request(attribute_type=UUID16(0x2A37).to_bytes(),
                                   starting_handle=0x0001, ending_handle=0xFFFF)
    resp = await server.handle_request(conn_handle=0x0001, pdu=req)
    assert isinstance(resp, ATT_Read_By_Type_Response)
    # default MTU 23: value truncates to MTU-4 = 19; tuple = handle(2)+value(19)
    assert resp.length == 21
    assert resp.attribute_data_list == (0x0003).to_bytes(2, "little") + b"\xAA" * 19


async def test_read_by_type_invalid_handle_range_returns_invalid_handle():
    """GAR/BI-08: Read By Type with starting handle > ending handle must be
    rejected with Invalid Handle (0x01) at the starting handle — NOT Attribute
    Not Found (0x0A, which is the BI-07 expectation for a valid empty range)."""
    from pybluehost.core.uuid import UUID16

    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A37), properties=CharProperties.READ,
                                  permissions=Permissions.READABLE, value=b"\xAA")
    ]))
    req = ATT_Read_By_Type_Request(attribute_type=UUID16(0x2800).to_bytes(),
                                   starting_handle=0x0002, ending_handle=0x0001)
    resp = await server.handle_request(conn_handle=0x0001, pdu=req)
    assert isinstance(resp, ATT_Error_Response)
    assert resp.request_opcode_in_error == ATTOpcode.READ_BY_TYPE_REQUEST
    assert resp.attribute_handle_in_error == 0x0002
    assert resp.error_code == 0x01  # Invalid Handle


async def test_prepare_write_defers_invalid_offset_to_execute():
    """GAW/BI-09: prepare write with offset beyond the value length must be
    ACCEPTED with a Prepare Write Response; the Invalid Offset (0x07) error is
    issued when the Lower Tester executes the write (opcode 0x18)."""
    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A37),
                                  properties=CharProperties.READ | CharProperties.WRITE,
                                  permissions=Permissions.READABLE | Permissions.WRITABLE,
                                  value=b"\xAA" * 32)
    ]))
    from pybluehost.ble.att import ATT_Prepare_Write_Request, ATT_Execute_Write_Request
    prep = ATT_Prepare_Write_Request(attribute_handle=0x0003, value_offset=64,
                                     part_attribute_value=b"\xBB")
    resp = await server.handle_request(conn_handle=0x0001, pdu=prep)
    from pybluehost.ble.att import ATT_Prepare_Write_Response
    assert isinstance(resp, ATT_Prepare_Write_Response)
    assert (resp.attribute_handle, resp.value_offset) == (0x0003, 64)

    resp = await server.handle_request(conn_handle=0x0001,
                                       pdu=ATT_Execute_Write_Request(flags=0x01))
    assert isinstance(resp, ATT_Error_Response)
    assert resp.request_opcode_in_error == ATTOpcode.EXECUTE_WRITE_REQUEST
    assert resp.attribute_handle_in_error == 0x0003
    assert resp.error_code == 0x07  # Invalid Offset
    # nothing was committed
    assert server.db.get(0x0003).value == b"\xAA" * 32


async def test_prepare_write_on_write_enc_only_attr_returns_write_not_permitted():
    """GAW/BI-08: the SR db's first attr without the plain-write bit is the
    enc-gated VND16_1, and that is the handle hdl_wid_120 returns. A prepare
    write to it over a plain link must yield Write Not Permitted (0x03) —
    the level bits gate the *plain* Write Request path, not the absence of
    the plain bit itself."""
    from pybluehost.ble.att import ATT_Prepare_Write_Request
    server = GATTServer()
    server.add_service(ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A37),
                                  properties=CharProperties.READ | CharProperties.WRITE,
                                  permissions=Permissions(0x0C),  # read_enc | write_enc
                                  value=b"\xAA" * 8)
    ]))
    prep = ATT_Prepare_Write_Request(attribute_handle=0x0003, value_offset=0,
                                     part_attribute_value=b"\xBB")
    resp = await server.handle_request(conn_handle=0x0001, pdu=prep)
    assert isinstance(resp, ATT_Error_Response)
    assert resp.request_opcode_in_error == ATTOpcode.PREPARE_WRITE_REQUEST
    assert resp.attribute_handle_in_error == 0x0003
    assert resp.error_code == 0x03  # Write Not Permitted


def test_att_parses_rmvl_response_with_u16_length_tuples():
    """This PTS build encodes the Core-5.3 Read Multiple Variable Length
    Response tuples with 16-bit LE length fields. A per-spec-only u8 parser
    desyncs on the first tuple, and worse, a u8 walk can self-consume EXACTLY
    into bogus tuples — so u16 is tried first and u8 (spec) is the fallback."""
    from pybluehost.ble.att import ATT_Read_Multiple_Variable_Response

    # Captured 07:00 run (GAR/BV-08): description values 7F / 07000001005E01.
    pdu = ATT_Read_Multiple_Variable_Response.from_bytes(
        bytes.fromhex("2101007f070007000001005e01"))
    assert pdu.values == [b"\x7F", b"\x07\x00\x00\x01\x00\x5E\x01"]

    # Captured 06:56 run: description values 139C / 010203.
    pdu = ATT_Read_Multiple_Variable_Response.from_bytes(
        bytes.fromhex("210200139c0300010203"))
    assert pdu.values == [b"\x13\x9C", b"\x01\x02\x03"]

    # Captured 14:47 run (GAR/BV-10, EATT bearer): expected values 05 / 650534.
    # A u8 walk of this PDU self-consumes exactly into (1,'00'),(5,'03 00 65
    # 05 34') — the wrong-tuple trap that u16-first avoids.
    pdu = ATT_Read_Multiple_Variable_Response.from_bytes(
        bytes.fromhex("21010005030065053 4".replace(" ", "")))
    assert pdu.values == [b"\x05", b"\x65\x05\x34"]

    # Spec form (u8 lengths) still parses via the fallback — and round-trips.
    pdu = ATT_Read_Multiple_Variable_Response.from_bytes(
        b"\x21\x02\x13\x9C\x03\x01\x02\x03")
    assert pdu.values == [b"\x13\x9C", b"\x01\x02\x03"]
    assert pdu.to_bytes() == b"\x21\x02\x13\x9C\x03\x01\x02\x03"
