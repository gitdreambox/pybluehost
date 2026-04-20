"""Tests for ATT PDU codec and ATTBearer."""

import asyncio
import struct

import pytest

from pybluehost.ble.att import (
    ATT_Error_Response,
    ATT_Exchange_MTU_Request,
    ATT_Exchange_MTU_Response,
    ATT_Execute_Write_Request,
    ATT_Find_By_Type_Value_Request,
    ATT_Handle_Value_Confirmation,
    ATT_Handle_Value_Indication,
    ATT_Handle_Value_Notification,
    ATT_Prepare_Write_Request,
    ATT_Read_Blob_Request,
    ATT_Read_Blob_Response,
    ATT_Read_By_Group_Type_Request,
    ATT_Read_By_Type_Request,
    ATT_Read_Request,
    ATT_Read_Response,
    ATT_Write_Command,
    ATT_Write_Request,
    ATT_Write_Response,
    ATTBearer,
    ATTError,
    ATTOpcode,
    ATTPdu,
    decode_att_pdu,
)


# ---------------------------------------------------------------------------
# PDU encode/decode tests
# ---------------------------------------------------------------------------


def test_exchange_mtu_request_encode():
    pdu = ATT_Exchange_MTU_Request(client_rx_mtu=512)
    raw = pdu.to_bytes()
    assert raw[0] == ATTOpcode.EXCHANGE_MTU_REQUEST
    assert struct.unpack_from("<H", raw, 1)[0] == 512


def test_exchange_mtu_request_decode():
    raw = bytes([0x02]) + struct.pack("<H", 512)
    pdu = decode_att_pdu(raw)
    assert isinstance(pdu, ATT_Exchange_MTU_Request)
    assert pdu.client_rx_mtu == 512


def test_read_request_encode():
    pdu = ATT_Read_Request(attribute_handle=0x0003)
    raw = pdu.to_bytes()
    assert raw[0] == ATTOpcode.READ_REQUEST
    assert struct.unpack_from("<H", raw, 1)[0] == 0x0003


def test_read_response_decode():
    raw = bytes([0x0B, 0xAA, 0xBB, 0xCC])
    pdu = decode_att_pdu(raw)
    assert isinstance(pdu, ATT_Read_Response)
    assert pdu.attribute_value == b"\xAA\xBB\xCC"


def test_write_request_encode():
    pdu = ATT_Write_Request(attribute_handle=0x0005, attribute_value=b"\x01")
    raw = pdu.to_bytes()
    assert raw[0] == ATTOpcode.WRITE_REQUEST
    assert struct.unpack_from("<H", raw, 1)[0] == 0x0005
    assert raw[3:] == b"\x01"


def test_notification_encode():
    pdu = ATT_Handle_Value_Notification(attribute_handle=0x000A, attribute_value=b"\x42")
    raw = pdu.to_bytes()
    assert raw[0] == ATTOpcode.HANDLE_VALUE_NOTIFICATION
    assert raw[3:] == b"\x42"


def test_error_response_decode():
    raw = bytes([0x01, 0x0A, 0x03, 0x00, 0x0A])
    pdu = decode_att_pdu(raw)
    assert isinstance(pdu, ATT_Error_Response)
    assert pdu.request_opcode_in_error == 0x0A
    assert pdu.attribute_handle_in_error == 0x0003
    assert pdu.error_code == 0x0A


def test_read_blob_request_encode():
    pdu = ATT_Read_Blob_Request(attribute_handle=0x0003, value_offset=5)
    raw = pdu.to_bytes()
    assert raw[0] == ATTOpcode.READ_BLOB_REQUEST
    assert struct.unpack_from("<H", raw, 1)[0] == 0x0003
    assert struct.unpack_from("<H", raw, 3)[0] == 5


def test_write_response_encode():
    pdu = ATT_Write_Response()
    raw = pdu.to_bytes()
    assert raw == bytes([ATTOpcode.WRITE_RESPONSE])


def test_confirmation_encode():
    pdu = ATT_Handle_Value_Confirmation()
    raw = pdu.to_bytes()
    assert raw == bytes([ATTOpcode.HANDLE_VALUE_CONFIRMATION])


def test_prepare_write_request_encode():
    pdu = ATT_Prepare_Write_Request(
        attribute_handle=0x0005, value_offset=10, part_attribute_value=b"\xAB\xCD"
    )
    raw = pdu.to_bytes()
    assert raw[0] == ATTOpcode.PREPARE_WRITE_REQUEST
    assert struct.unpack_from("<H", raw, 1)[0] == 0x0005
    assert struct.unpack_from("<H", raw, 3)[0] == 10
    assert raw[5:] == b"\xAB\xCD"


def test_execute_write_request_encode():
    pdu = ATT_Execute_Write_Request(flags=0x01)
    raw = pdu.to_bytes()
    assert raw[0] == ATTOpcode.EXECUTE_WRITE_REQUEST
    assert raw[1] == 0x01


def test_roundtrip_error_response():
    original = ATT_Error_Response(
        request_opcode_in_error=0x0A,
        attribute_handle_in_error=0x0042,
        error_code=0x06,
    )
    raw = original.to_bytes()
    decoded = decode_att_pdu(raw)
    assert isinstance(decoded, ATT_Error_Response)
    assert decoded.request_opcode_in_error == 0x0A
    assert decoded.attribute_handle_in_error == 0x0042
    assert decoded.error_code == 0x06


def test_roundtrip_write_command():
    original = ATT_Write_Command(attribute_handle=0x0010, attribute_value=b"\xDE\xAD")
    raw = original.to_bytes()
    decoded = decode_att_pdu(raw)
    assert isinstance(decoded, ATT_Write_Command)
    assert decoded.attribute_handle == 0x0010
    assert decoded.attribute_value == b"\xDE\xAD"


def test_roundtrip_indication():
    original = ATT_Handle_Value_Indication(
        attribute_handle=0x0020, attribute_value=b"\x01\x02\x03"
    )
    raw = original.to_bytes()
    decoded = decode_att_pdu(raw)
    assert isinstance(decoded, ATT_Handle_Value_Indication)
    assert decoded.attribute_handle == 0x0020
    assert decoded.attribute_value == b"\x01\x02\x03"


def test_decode_unknown_opcode():
    with pytest.raises(ValueError, match="Unknown ATT opcode"):
        decode_att_pdu(bytes([0xFF]))


def test_decode_empty_data():
    with pytest.raises(ValueError, match="Empty ATT PDU"):
        decode_att_pdu(b"")


# ---------------------------------------------------------------------------
# ATTBearer tests
# ---------------------------------------------------------------------------


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    async def send(self, data: bytes) -> None:
        self.sent.append(data)


async def test_att_bearer_exchange_mtu():
    ch = FakeChannel()
    bearer = ATTBearer(channel=ch, mtu=23)

    async def inject_response():
        await asyncio.sleep(0.01)
        resp = ATT_Exchange_MTU_Response(server_rx_mtu=256)
        await bearer._on_pdu(resp.to_bytes())

    asyncio.ensure_future(inject_response())
    result_mtu = await bearer.exchange_mtu(512)
    assert result_mtu == 256  # min(512, 256)
    assert bearer.mtu == 256


async def test_att_bearer_read():
    ch = FakeChannel()
    bearer = ATTBearer(channel=ch, mtu=23)

    async def inject_response():
        await asyncio.sleep(0.01)
        resp = ATT_Read_Response(attribute_value=b"\xCA\xFE")
        await bearer._on_pdu(resp.to_bytes())

    asyncio.ensure_future(inject_response())
    value = await bearer.read(0x0003)
    assert value == b"\xCA\xFE"


async def test_att_bearer_read_error():
    ch = FakeChannel()
    bearer = ATTBearer(channel=ch, mtu=23)

    async def inject_response():
        await asyncio.sleep(0.01)
        resp = ATT_Error_Response(
            request_opcode_in_error=ATTOpcode.READ_REQUEST,
            attribute_handle_in_error=0x0003,
            error_code=0x0A,
        )
        await bearer._on_pdu(resp.to_bytes())

    asyncio.ensure_future(inject_response())
    with pytest.raises(ATTError) as exc_info:
        await bearer.read(0x0003)
    assert exc_info.value.error_code == 0x0A


async def test_att_bearer_write():
    ch = FakeChannel()
    bearer = ATTBearer(channel=ch, mtu=23)

    async def inject_response():
        await asyncio.sleep(0.01)
        resp = ATT_Write_Response()
        await bearer._on_pdu(resp.to_bytes())

    asyncio.ensure_future(inject_response())
    await bearer.write(0x0005, b"\x01")
    # Verify the request was sent
    assert len(ch.sent) == 1
    assert ch.sent[0][0] == ATTOpcode.WRITE_REQUEST


async def test_att_bearer_write_without_response():
    ch = FakeChannel()
    bearer = ATTBearer(channel=ch, mtu=23)
    await bearer.write_without_response(0x0005, b"\x01")
    assert len(ch.sent) == 1
    assert ch.sent[0][0] == ATTOpcode.WRITE_COMMAND


async def test_att_bearer_notification_handler():
    ch = FakeChannel()
    bearer = ATTBearer(channel=ch, mtu=23)
    received: list[tuple[int, bytes]] = []

    def on_notify(handle: int, value: bytes) -> None:
        received.append((handle, value))

    bearer.set_notification_handler(on_notify)
    notif = ATT_Handle_Value_Notification(attribute_handle=0x000A, attribute_value=b"\x42")
    await bearer._on_pdu(notif.to_bytes())
    assert received == [(0x000A, b"\x42")]


async def test_att_bearer_indication_auto_confirm():
    ch = FakeChannel()
    bearer = ATTBearer(channel=ch, mtu=23)
    received: list[tuple[int, bytes]] = []

    def on_indicate(handle: int, value: bytes) -> None:
        received.append((handle, value))

    bearer.set_indication_handler(on_indicate)
    ind = ATT_Handle_Value_Indication(attribute_handle=0x0020, attribute_value=b"\x99")
    await bearer._on_pdu(ind.to_bytes())
    assert received == [(0x0020, b"\x99")]
    # Should have auto-sent confirmation
    assert len(ch.sent) == 1
    assert ch.sent[0][0] == ATTOpcode.HANDLE_VALUE_CONFIRMATION
