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


def test_sdp_server_service_attribute_request_invalid_handle_returns_error():
    server = SDPServer()
    attr_id_list = encode_data_element(DataElement.sequence([
        DataElement.uint16(0x0000),
        DataElement.uint16(0xFFFF),
    ]))
    params = (
        struct.pack(">I", 0xEEEEEEEE)
        + struct.pack(">H", 0x0100)
        + attr_id_list
        + b"\x00"
    )
    pdu = bytes([0x04]) + struct.pack(">HH", 0x0000, len(params)) + params

    response = server.handle_pdu(pdu)

    assert response == b"\x01" + struct.pack(">HHH", 0x0000, 0x0002, 0x0002)

def test_sdp_server_service_search_request_returns_matching_handles():
    server = SDPServer()
    record = make_rfcomm_service_record(service_uuid=0x1101, channel=1, name="SPP")
    handle = server.register(record)
    search_pattern = encode_data_element(DataElement.sequence([DataElement.uuid16(0x1101)]))
    params = search_pattern + struct.pack(">H", 10) + b"\x00"
    pdu = bytes([0x02]) + struct.pack(">HH", 0x0003, len(params)) + params

    response = server.handle_pdu(pdu)

    assert response[0] == 0x03
    param_len = struct.unpack_from(">H", response, 3)[0]
    response_params = response[5:5 + param_len]
    assert struct.unpack_from(">H", response_params, 0)[0] == 1
    assert struct.unpack_from(">H", response_params, 2)[0] == 1
    assert struct.unpack_from(">I", response_params, 4)[0] == handle
    assert response_params[-1:] == b"\x00"


def test_sdp_server_service_attribute_request_returns_selected_attributes():
    server = SDPServer()
    record = make_rfcomm_service_record(service_uuid=0x1101, channel=1, name="SPP")
    handle = server.register(record)
    attr_id_list = encode_data_element(DataElement.sequence([DataElement.uint16(0x0100)]))
    params = struct.pack(">I", handle) + struct.pack(">H", 0x0100) + attr_id_list + b"\x00"
    pdu = bytes([0x04]) + struct.pack(">HH", 0x0004, len(params)) + params

    response = server.handle_pdu(pdu)

    assert response[0] == 0x05
    param_len = struct.unpack_from(">H", response, 3)[0]
    response_params = response[5:5 + param_len]
    attr_byte_count = struct.unpack_from(">H", response_params, 0)[0]
    attr_list, consumed = decode_data_element(response_params[2:2 + attr_byte_count])
    assert consumed == attr_byte_count
    assert attr_list.type == DataElementType.SEQUENCE
    assert attr_list.value[0].value == 0x0100
    assert attr_list.value[1].value == "SPP"
    assert response_params[-1:] == b"\x00"


def test_sdp_server_hosts_service_discovery_server_record_at_handle_zero():
    """SDP/SR cases rely on the mandatory ServiceDiscoveryServer record (Core
    Vol 3 Part B): ServiceClassIDList = 0x0100, handle 0x00000000."""
    server = SDPServer()
    record = server._records.get(0x00000000)
    assert record is not None
    class_list = record.attributes[0x0001]
    assert class_list.type == DataElementType.SEQUENCE
    assert any(e.value == 0x0100 for e in class_list.value)


def test_sdp_server_search_for_service_discovery_server_finds_record():
    """PTS searches with pattern 0x0100 (TSPX_sdp_service_search_pattern); the
    server must return its ServiceDiscoveryServer record handle."""
    server = SDPServer()
    search_pattern = encode_data_element(DataElement.sequence([DataElement.uuid16(0x0100)]))
    params = search_pattern + struct.pack(">H", 10) + b"\x00"
    pdu = bytes([0x02]) + struct.pack(">HH", 0x0001, len(params)) + params

    response = server.handle_pdu(pdu)

    assert response[0] == 0x03
    param_len = struct.unpack_from(">H", response, 3)[0]
    response_params = response[5:5 + param_len]
    assert struct.unpack_from(">H", response_params, 0)[0] == 1  # total
    assert struct.unpack_from(">H", response_params, 2)[0] == 1  # current
    assert struct.unpack_from(">I", response_params, 4)[0] == 0x00000000


def test_sdp_server_attribute_request_on_discovery_server_record_returns_attributes():
    """SDP/SR/SA/BV-01: Service Attribute Request on the discovery-server record
    with the full attribute range must return a non-empty attribute list."""
    server = SDPServer()
    # Full attribute range 0x0000-0xFFFF encoded as a single UINT32 range.
    attr_id_list = encode_data_element(DataElement.sequence([DataElement.uint32(0x0000FFFF)]))
    params = struct.pack(">I", 0x00000000) + struct.pack(">H", 0x0200) + attr_id_list + b"\x00"
    pdu = bytes([0x04]) + struct.pack(">HH", 0x0002, len(params)) + params

    response = server.handle_pdu(pdu)

    assert response[0] == 0x05
    param_len = struct.unpack_from(">H", response, 3)[0]
    response_params = response[5:5 + param_len]
    attr_byte_count = struct.unpack_from(">H", response_params, 0)[0]
    assert attr_byte_count > 0
    attr_list, _ = decode_data_element(response_params[2:2 + attr_byte_count])
    assert attr_list.type == DataElementType.SEQUENCE
    assert len(attr_list.value) > 0

def test_sdp_server_rejects_service_attribute_request_with_invalid_attr_id_list():
    server = SDPServer()
    handle = server.register(make_rfcomm_service_record(service_uuid=0x1101, channel=1, name="SPP"))
    attr_id_list = encode_data_element(DataElement.sequence([DataElement.uuid16(0x0000)]))
    params = struct.pack(">I", handle) + struct.pack(">H", 0x0100) + attr_id_list + b"\x00"
    pdu = bytes([0x04]) + struct.pack(">HH", 0x0005, len(params)) + params

    response = server.handle_pdu(pdu)

    assert response == b"\x01" + struct.pack(">HHH", 0x0005, 0x0002, 0x0003)


def test_sdp_server_rejects_search_attribute_request_with_invalid_attr_id_list():
    server = SDPServer()
    server.register(make_rfcomm_service_record(service_uuid=0x1101, channel=1, name="SPP"))
    search_pattern = encode_data_element(DataElement.sequence([DataElement.uuid16(0x1101)]))
    attr_id_list = encode_data_element(DataElement.sequence([DataElement.uuid16(0x0000)]))
    params = search_pattern + struct.pack(">H", 0x0100) + attr_id_list + b"\x00"
    pdu = bytes([0x06]) + struct.pack(">HH", 0x0006, len(params)) + params

    response = server.handle_pdu(pdu)

    assert response == b"\x01" + struct.pack(">HHH", 0x0006, 0x0002, 0x0003)


def test_sdp_server_rejects_pdu_size_mismatch():
    server = SDPServer()
    search_pattern = encode_data_element(DataElement.sequence([DataElement.uuid16(0x1101)]))
    attr_id_list = encode_data_element(DataElement.sequence([DataElement.uint32(0x0000FFFF)]))
    params = search_pattern + struct.pack(">H", 0x0100) + attr_id_list + b"\x00"
    pdu = bytes([0x06]) + struct.pack(">HH", 0x0007, 0x007F) + params

    response = server.handle_pdu(pdu)

    assert response == b"\x01" + struct.pack(">HHH", 0x0007, 0x0002, 0x0004)

def test_sdp_server_rejects_service_search_request_with_invalid_search_pattern():
    server = SDPServer()
    search_pattern = encode_data_element(DataElement.sequence([DataElement.uint16(0x0100)]))
    params = search_pattern + struct.pack(">H", 0x0100) + b"\x00"
    pdu = bytes([0x02]) + struct.pack(">HH", 0x0008, len(params)) + params

    response = server.handle_pdu(pdu)

    assert response == b"\x01" + struct.pack(">HHH", 0x0008, 0x0002, 0x0003)

def test_sdp_server_rejects_service_search_request_with_uint128_pattern():
    # PTS SDP/SR/SS/BI-02-C sends a 128-bit integer (type UINT, size 16) where a
    # UUID element is required. The decoder must not raise KeyError; the server
    # must return SDP error 0x0003 (Invalid Request Syntax).
    server = SDPServer()
    uint128_payload = bytes.fromhex("0C" + "00010000001000800000805F9B34FB")
    search_pattern = bytes([0x35, 0x11]) + uint128_payload  # DES(17) wrapping UINT128
    params = search_pattern + struct.pack(">H", 0x0100) + b"\x00"
    pdu = bytes([0x02]) + struct.pack(">HH", 0x0008, len(params)) + params

    response = server.handle_pdu(pdu)

    assert response == b"\x01" + struct.pack(">HHH", 0x0008, 0x0002, 0x0003)

def test_decode_data_element_supports_uint128_and_sint128():
    # 128-bit integers are valid SDP data element sizes; decode without KeyError.
    uint_de, consumed = decode_data_element(bytes.fromhex("0C" + "00" * 15 + "2A"))
    assert uint_de.type == DataElementType.UINT
    assert uint_de.value == 0x2A
    assert consumed == 17

    sint_de, _ = decode_data_element(bytes.fromhex("14" + "FF" * 16))  # SINT, size_idx=4
    assert sint_de.type == DataElementType.SINT
    assert sint_de.value == -1

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


async def test_sdp_client_uses_phone_observed_default_max_attribute_byte_count():
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

    assert b"\x03\xf0" in channel.sent[0]


class _FragmentingChannel:
    """Fake L2CAP channel whose SDP server fragments a large AttributeLists
    across multiple responses using the SDP continuation-state protocol.

    The continuation state encodes the next byte offset (N=2, big-endian) so the
    fake is stateless: it only serves fragment[2] when the request echoes the
    exact continuation bytes that fragment[1] returned.
    """

    def __init__(self, full_attr_bytes: bytes, frag_size: int) -> None:
        self.events = None
        self.sent: list[bytes] = []
        self.full = full_attr_bytes
        self.frag_size = frag_size

    def set_events(self, events: SimpleChannelEvents) -> None:
        self.events = events

    async def send(self, data: bytes) -> None:
        self.sent.append(data)
        txn = data[1:3]
        param_len = struct.unpack_from(">H", data, 3)[0]
        params = data[5:5 + param_len]
        # Robustly extract the request's ContinuationState field (trailing 1+N bytes).
        _sp, c1 = decode_data_element(params, 0)
        _ail, c2 = decode_data_element(params, c1 + 2)
        cont = params[c1 + 2 + c2:]
        offset = int.from_bytes(cont[1:1 + cont[0]], "big") if cont and cont[0] else 0
        frag = self.full[offset:offset + self.frag_size]
        new_offset = offset + len(frag)
        next_cont = b"\x00" if new_offset >= len(self.full) else bytes([2]) + struct.pack(">H", new_offset)
        resp_params = struct.pack(">H", len(frag)) + frag + next_cont
        resp = bytes([0x07]) + txn + struct.pack(">H", len(resp_params)) + resp_params
        await self.events.on_data(resp)


async def test_sdp_client_follows_continuation_state_for_fragmented_response():
    """A remote device that fragments its SDP response must not crash the client.

    Regression for the IndexError observed against a real multi-profile audio
    device: the client ignored ContinuationState, decoded only the first partial
    fragment, and walked off the end of the truncated buffer.
    """
    record_seq = DataElement.sequence([
        DataElement.uint16(0x0000), DataElement.uint32(0x00010001),
        DataElement.uint16(0x0100), DataElement.text("X" * 300),
    ])
    full_attr_bytes = encode_data_element(DataElement.sequence([record_seq]))

    channel = _FragmentingChannel(full_attr_bytes, frag_size=80)
    client = SDPClient(channel, request_timeout=1.0, retries=0)

    records = await client.search_attributes(target=None, uuid=0x1101)

    assert len(channel.sent) > 1, "client must send follow-up requests for continuation state"
    assert len(records) == 1
    assert records[0][0x0000].value == 0x00010001
    assert records[0][0x0100].value == "X" * 300
