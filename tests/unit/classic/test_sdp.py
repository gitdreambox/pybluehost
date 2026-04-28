"""Tests for the SDP (Service Discovery Protocol) module."""
from __future__ import annotations

import asyncio
import struct
from pybluehost.l2cap.channel import SimpleChannelEvents

from pybluehost.classic.sdp import (
    DataElement,
    DataElementType,
    SDPClient,
    SDPServer,
    ServiceRecord,
    decode_data_element,
    encode_data_element,
    make_rfcomm_service_record,
)


def test_uint8_encode():
    de = DataElement.uint8(0x42)
    raw = encode_data_element(de)
    assert raw[0] == 0x08  # type=UINT(1), size_index=0 (1 byte)
    assert raw[1] == 0x42


def test_uint16_encode():
    de = DataElement.uint16(0x0003)
    raw = encode_data_element(de)
    assert raw[0] == 0x09  # type=UINT, size_index=1 (2 bytes)
    assert raw[1:3] == b"\x00\x03"


def test_uint32_encode():
    de = DataElement.uint32(0x0000FFFF)
    raw = encode_data_element(de)
    assert raw[0] == 0x0A  # type=UINT, size_index=2 (4 bytes)
    assert raw[1:5] == b"\x00\x00\xFF\xFF"


def test_uuid16_encode():
    de = DataElement.uuid16(0x0003)
    raw = encode_data_element(de)
    assert raw[0] == 0x19  # type=UUID(3), size_index=1 (2 bytes)


def test_text_encode():
    de = DataElement.text("SPP")
    raw = encode_data_element(de)
    assert raw[0] == 0x25  # type=TEXT(4), size_index=5 (1-byte length follows)
    assert raw[1] == 3
    assert raw[2:] == b"SPP"


def test_boolean_encode():
    de = DataElement.boolean(True)
    raw = encode_data_element(de)
    assert raw[0] == 0x28  # type=BOOLEAN(5), size_index=0 (1 byte)
    assert raw[1] == 0x01


def test_sequence_encode():
    seq = DataElement.sequence([DataElement.uuid16(0x0003)])
    raw = encode_data_element(seq)
    assert raw[0] == 0x35  # type=SEQUENCE(6), size_index=5


def test_decode_roundtrip_uint8():
    de = DataElement.uint8(0x42)
    raw = encode_data_element(de)
    decoded, consumed = decode_data_element(raw)
    assert decoded.type == DataElementType.UINT
    assert decoded.value == 0x42
    assert consumed == len(raw)


def test_decode_roundtrip_uint16():
    de = DataElement.uint16(0x1234)
    raw = encode_data_element(de)
    decoded, consumed = decode_data_element(raw)
    assert decoded.type == DataElementType.UINT
    assert decoded.value == 0x1234
    assert consumed == len(raw)


def test_decode_roundtrip_uint32():
    de = DataElement.uint32(0xDEADBEEF)
    raw = encode_data_element(de)
    decoded, consumed = decode_data_element(raw)
    assert decoded.type == DataElementType.UINT
    assert decoded.value == 0xDEADBEEF
    assert consumed == len(raw)


def test_decode_roundtrip_uuid16():
    de = DataElement.uuid16(0x1101)
    raw = encode_data_element(de)
    decoded, consumed = decode_data_element(raw)
    assert decoded.type == DataElementType.UUID
    assert decoded.value == 0x1101
    assert consumed == len(raw)


def test_decode_roundtrip_text():
    de = DataElement.text("Hello Bluetooth")
    raw = encode_data_element(de)
    decoded, consumed = decode_data_element(raw)
    assert decoded.type == DataElementType.TEXT
    assert decoded.value == "Hello Bluetooth"
    assert consumed == len(raw)


def test_decode_roundtrip_boolean():
    de = DataElement.boolean(False)
    raw = encode_data_element(de)
    decoded, consumed = decode_data_element(raw)
    assert decoded.type == DataElementType.BOOLEAN
    assert decoded.value is False
    assert consumed == len(raw)


def test_decode_roundtrip_sequence():
    seq = DataElement.sequence([
        DataElement.uint16(0x0100),
        DataElement.text("test"),
    ])
    raw = encode_data_element(seq)
    decoded, consumed = decode_data_element(raw)
    assert decoded.type == DataElementType.SEQUENCE
    assert len(decoded.value) == 2
    assert decoded.value[0].value == 0x0100
    assert decoded.value[1].value == "test"
    assert consumed == len(raw)


def test_service_record_rfcomm_channel():
    record = make_rfcomm_service_record(service_uuid=0x1101, channel=1, name="SPP")
    assert record.handle == 0
    assert 0x0001 in record.attributes  # ServiceClassIDList
    assert 0x0004 in record.attributes  # ProtocolDescriptorList


def test_sdp_server_register_and_handle_pdu():
    """SDPServer.handle_pdu() handles ServiceSearchAttributeRequest."""
    server = SDPServer()
    record = make_rfcomm_service_record(service_uuid=0x1101, channel=1, name="SPP")
    handle = server.register(record)
    assert handle >= 0x00010000

    # Craft ServiceSearchAttributeRequest PDU (ID=0x06)
    uuid_de = encode_data_element(DataElement.sequence([DataElement.uuid16(0x1101)]))
    attr_range = encode_data_element(DataElement.sequence([
        DataElement.uint32(0x0000FFFF)
    ]))
    continuation = b"\x00"
    max_count = struct.pack(">H", 0x00FF)
    params = uuid_de + max_count + attr_range + continuation
    pdu = bytes([0x06]) + struct.pack(">HH", 0x0001, len(params)) + params

    response = server.handle_pdu(pdu)
    assert response is not None
    assert len(response) > 5
    assert response[0] == 0x07  # ServiceSearchAttributeResponse


def test_sdp_server_unregister():
    server = SDPServer()
    record = make_rfcomm_service_record(service_uuid=0x1101, channel=1, name="SPP")
    handle = server.register(record)
    server.unregister(handle)
    # After unregister, search should return empty
    uuid_de = encode_data_element(DataElement.sequence([DataElement.uuid16(0x1101)]))
    attr_range = encode_data_element(DataElement.sequence([
        DataElement.uint32(0x0000FFFF)
    ]))
    params = uuid_de + struct.pack(">H", 0x00FF) + attr_range + b"\x00"
    pdu = bytes([0x06]) + struct.pack(">HH", 0x0002, len(params)) + params
    response = server.handle_pdu(pdu)
    assert response is not None
    # AttributeListsByteCount should be small (empty list)


def test_sdp_client_has_search_attributes():
    """SDPClient exposes search_attributes method."""
    import inspect
    sig = inspect.signature(SDPClient.search_attributes)
    params = list(sig.parameters)
    assert "uuid" in params
    assert "attr_ids" in params


async def test_sdp_client_search_attributes_over_l2cap_channel():
    server = SDPServer()
    server.register(make_rfcomm_service_record(service_uuid=0x1101, channel=3, name="SPP"))

    class FakeChannel:
        def __init__(self):
            self.sent = []
            self.events = None

        def set_events(self, events):
            self.events = events

        async def send(self, data):
            self.sent.append(data)
            response = server.handle_pdu(data)
            await self.events.on_data(response)

    channel = FakeChannel()
    client = SDPClient(channel)

    records = await client.search_attributes(
        target=None,
        uuid=0x1101,
        attr_ids=[0x0001, 0x0004, 0x0100],
    )

    assert len(records) == 1
    assert records[0][0x0100].value == "SPP"
    assert channel.sent[0][0] == 0x06


async def test_sdp_client_find_rfcomm_channel_over_l2cap_channel():
    server = SDPServer()
    server.register(make_rfcomm_service_record(service_uuid=0x1101, channel=7, name="SPP"))

    class FakeChannel:
        def __init__(self):
            self.events = None

        def set_events(self, events):
            self.events = events

        async def send(self, data):
            await self.events.on_data(server.handle_pdu(data))

    client = SDPClient(FakeChannel())

    channel = await client.find_rfcomm_channel(target=None, service_uuid=0x1101)

    assert channel == 7


async def test_sdp_client_retries_once_after_request_timeout():
    server = SDPServer()
    server.register(make_rfcomm_service_record(service_uuid=0x1101, channel=3, name="SPP"))

    class FakeChannel:
        def __init__(self):
            self.events = None
            self.sent = []

        def set_events(self, events):
            self.events = events

        async def send(self, data):
            self.sent.append(data)
            if len(self.sent) == 2:
                await self.events.on_data(server.handle_pdu(data))

    channel = FakeChannel()
    client = SDPClient(channel, request_timeout=0.01, retries=1)

    records = await client.search_attributes(
        target=None,
        uuid=0x1101,
        attr_ids=[0x0004],
    )

    assert len(records) == 1
    assert len(channel.sent) == 2
    assert client._pending == {}


async def test_sdp_client_uses_full_default_max_attribute_byte_count():
    class FakeChannel:
        def __init__(self):
            self.events = None
            self.sent = []

        def set_events(self, events):
            self.events = events

        async def send(self, data):
            self.sent.append(data)

    channel = FakeChannel()
    client = SDPClient(channel, request_timeout=0.01, retries=0)

    try:
        await client.search_attributes(target=None, uuid=0x1101, attr_ids=[0x0004])
    except TimeoutError:
        pass

    assert b"\xff\xff" in channel.sent[0]
