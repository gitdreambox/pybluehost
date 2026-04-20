import pytest
import struct
from pybluehost.ble.gatt import (
    AttributeDatabase, GATTServer, GATTClient,
    ServiceDefinition, CharacteristicDefinition, DescriptorDefinition,
    CharProperties, Permissions, ServiceHandles,
)
from pybluehost.ble.att import (
    ATT_Read_Request, ATT_Read_Response,
    ATT_Write_Request, ATT_Write_Response,
    ATT_Error_Response, ATT_Exchange_MTU_Request,
    ATT_Exchange_MTU_Response,
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


async def test_gatt_server_handle_read_not_found():
    server = GATTServer()
    req = ATT_Read_Request(attribute_handle=0x9999)
    response = await server.handle_request(conn_handle=0x0001, pdu=req)
    assert isinstance(response, ATT_Error_Response)
    assert response.error_code == 0x0A  # Attribute Not Found


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


async def test_gatt_server_handle_exchange_mtu():
    server = GATTServer()
    req = ATT_Exchange_MTU_Request(client_rx_mtu=256)
    response = await server.handle_request(conn_handle=0x0001, pdu=req)
    assert isinstance(response, ATT_Exchange_MTU_Response)
    assert response.server_rx_mtu == 512


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
