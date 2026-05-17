"""HCI Secure Connections command + event encode/decode."""
from __future__ import annotations

import struct

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    EventCode,
    HCI_LINK_KEY_REQUEST_REPLY,
    HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT,
)
from pybluehost.hci.packets import (
    HCI_Link_Key_Request_Reply_Command,
    HCI_Write_Secure_Connections_Host_Support_Command,
    decode_hci_packet,
)


def test_write_secure_connections_host_support_encode():
    cmd = HCI_Write_Secure_Connections_Host_Support_Command(secure_connections_host_support=0x01)
    raw = cmd.to_bytes()
    opcode = int.from_bytes(raw[1:3], "little")
    assert opcode == HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT
    assert raw[3] == 1
    assert raw[4] == 1


def test_link_key_request_reply_encode():
    addr = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    cmd = HCI_Link_Key_Request_Reply_Command(bd_addr=addr, link_key=b"\xAA" * 16)
    raw = cmd.to_bytes()
    opcode = int.from_bytes(raw[1:3], "little")
    assert opcode == HCI_LINK_KEY_REQUEST_REPLY
    assert raw[3] == 22  # 6 + 16
    # BT wire format = little-endian; BDAddress.address is big-endian
    assert raw[4:10] == bytes(addr.address[::-1])
    assert raw[10:26] == b"\xAA" * 16


def test_link_key_notification_event_decode():
    """HCI_Link_Key_Notification: bd_addr(6) + link_key(16) + key_type(1) = 23 params."""
    params = b"\x06\x05\x04\x03\x02\x01" + b"\xBB" * 16 + bytes([0x07])
    raw = b"\x04" + bytes([EventCode.LINK_KEY_NOTIFICATION]) + bytes([len(params)]) + params
    packet = decode_hci_packet(raw)
    from pybluehost.hci.packets import HCIEvent
    assert isinstance(packet, HCIEvent)
    assert packet.event_code == EventCode.LINK_KEY_NOTIFICATION


def test_simple_pairing_complete_event_decode():
    """HCI_Simple_Pairing_Complete: status(1) + bd_addr(6) = 7 params."""
    params = b"\x00" + b"\x06\x05\x04\x03\x02\x01"
    raw = b"\x04" + bytes([EventCode.SIMPLE_PAIRING_COMPLETE]) + bytes([len(params)]) + params
    packet = decode_hci_packet(raw)
    from pybluehost.hci.packets import HCIEvent
    assert isinstance(packet, HCIEvent)
    assert packet.event_code == EventCode.SIMPLE_PAIRING_COMPLETE
    assert packet.parameters[0] == 0
