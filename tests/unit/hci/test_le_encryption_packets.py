"""HCI LE encryption command + event encode/decode tests."""
from __future__ import annotations

import struct

from pybluehost.hci.constants import (
    EventCode,
    HCI_LE_LONG_TERM_KEY_REQUEST_NEGATIVE_REPLY,
    HCI_LE_LONG_TERM_KEY_REQUEST_REPLY,
    HCI_LE_START_ENCRYPTION,
    LEMetaSubEvent,
)
from pybluehost.hci.packets import (
    HCI_LE_LTK_Request_Negative_Reply_Command,
    HCI_LE_LTK_Request_Reply_Command,
    HCI_LE_Start_Encryption_Command,
    decode_hci_packet,
)


def test_le_start_encryption_encode():
    """HCI_LE_Start_Encryption: handle(2) + rand(8) + ediv(2) + ltk(16) = 28 params."""
    cmd = HCI_LE_Start_Encryption_Command(
        connection_handle=0x0040,
        random_number=bytes(range(8)),
        encrypted_diversifier=0x1234,
        long_term_key=bytes(range(16)),
    )
    raw = cmd.to_bytes()
    assert raw[0] == 0x01  # H4 command
    opcode = int.from_bytes(raw[1:3], "little")
    assert opcode == HCI_LE_START_ENCRYPTION
    assert raw[3] == 28
    assert int.from_bytes(raw[4:6], "little") == 0x0040
    assert raw[6:14] == bytes(range(8))
    assert int.from_bytes(raw[14:16], "little") == 0x1234
    assert raw[16:32] == bytes(range(16))


def test_le_ltk_request_reply_encode():
    cmd = HCI_LE_LTK_Request_Reply_Command(
        connection_handle=0x0040,
        long_term_key=bytes(range(16)),
    )
    raw = cmd.to_bytes()
    opcode = int.from_bytes(raw[1:3], "little")
    assert opcode == HCI_LE_LONG_TERM_KEY_REQUEST_REPLY
    assert raw[3] == 18
    assert int.from_bytes(raw[4:6], "little") == 0x0040
    assert raw[6:22] == bytes(range(16))


def test_le_ltk_request_negative_reply_encode():
    cmd = HCI_LE_LTK_Request_Negative_Reply_Command(connection_handle=0x0040)
    raw = cmd.to_bytes()
    opcode = int.from_bytes(raw[1:3], "little")
    assert opcode == HCI_LE_LONG_TERM_KEY_REQUEST_NEGATIVE_REPLY
    assert raw[3] == 2
    assert int.from_bytes(raw[4:6], "little") == 0x0040


def test_le_ltk_request_event_decode():
    """LE_LTK_Request subevent (0x05): handle(2) + rand(8) + ediv(2) = 12 params."""
    raw = b"\x04\x3e\x0d" + bytes([LEMetaSubEvent.LE_LONG_TERM_KEY_REQUEST])
    raw += struct.pack("<H", 0x0040) + bytes(range(8)) + struct.pack("<H", 0x1234)
    packet = decode_hci_packet(raw)
    from pybluehost.hci.packets import HCI_LE_Meta_Event
    assert isinstance(packet, HCI_LE_Meta_Event)
    assert packet.subevent_code == LEMetaSubEvent.LE_LONG_TERM_KEY_REQUEST
    handle = int.from_bytes(packet.subevent_parameters[0:2], "little")
    rand = packet.subevent_parameters[2:10]
    ediv = int.from_bytes(packet.subevent_parameters[10:12], "little")
    assert handle == 0x0040
    assert rand == bytes(range(8))
    assert ediv == 0x1234


def test_encryption_change_event_decode():
    """HCI_Encryption_Change: event_code 0x08, params status(1) + handle(2) + encryption_enabled(1)."""
    raw = b"\x04\x08\x04\x00" + struct.pack("<H", 0x0040) + b"\x01"
    packet = decode_hci_packet(raw)
    from pybluehost.hci.packets import HCIEvent
    assert isinstance(packet, HCIEvent)
    assert packet.event_code == EventCode.ENCRYPTION_CHANGE
    assert packet.parameters[0] == 0
    assert int.from_bytes(packet.parameters[1:3], "little") == 0x0040
    assert packet.parameters[3] == 1
