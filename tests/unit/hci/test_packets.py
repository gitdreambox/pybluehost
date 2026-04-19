"""Tests for HCI packet encode/decode: commands, events, ACL, SCO, ISO."""

import struct

import pytest

from pybluehost.hci.packets import (
    HCIPacket,
    HCICommand,
    HCIEvent,
    HCIACLData,
    HCISCOData,
    HCIISOData,
    HCI_Reset,
    HCI_LE_Set_Scan_Enable,
    HCI_Command_Complete_Event,
    HCI_Command_Status_Event,
    HCI_Connection_Complete_Event,
    HCI_Disconnection_Complete_Event,
    HCI_Number_Of_Completed_Packets_Event,
    HCI_LE_Meta_Event,
    decode_hci_packet,
)
from pybluehost.hci.constants import EventCode, HCI_RESET


# --- HCI Command encode/decode ---

def test_hci_reset_encode():
    cmd = HCI_Reset()
    data = cmd.to_bytes()
    # H4 type(1) + opcode(2 LE) + param_len(1)
    assert data == bytes([0x01, 0x03, 0x0C, 0x00])


def test_hci_reset_decode():
    raw = bytes([0x01, 0x03, 0x0C, 0x00])
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCI_Reset)
    assert pkt.opcode == HCI_RESET


def test_le_set_scan_enable_encode():
    cmd = HCI_LE_Set_Scan_Enable(le_scan_enable=1, filter_duplicates=0)
    data = cmd.to_bytes()
    assert data[0] == 0x01  # HCI Command
    assert data[1:3] == bytes([0x0C, 0x20])  # opcode LE
    assert data[3] == 2  # param length
    assert data[4] == 1  # scan enable
    assert data[5] == 0  # filter duplicates


def test_le_set_scan_enable_decode():
    raw = bytes([0x01, 0x0C, 0x20, 0x02, 0x01, 0x00])
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCI_LE_Set_Scan_Enable)
    assert pkt.le_scan_enable == 1
    assert pkt.filter_duplicates == 0


def test_generic_command_encode():
    cmd = HCICommand(opcode=0x0C03, parameters=b"")
    data = cmd.to_bytes()
    assert data == bytes([0x01, 0x03, 0x0C, 0x00])


def test_generic_command_decode():
    raw = bytes([0x01, 0xFF, 0xFF, 0x02, 0xAA, 0xBB])
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCICommand)
    assert pkt.opcode == 0xFFFF
    assert pkt.parameters == b"\xAA\xBB"


# --- HCI Event decode ---

def test_command_complete_event_decode():
    raw = bytes([0x04, 0x0E, 0x04, 0x01, 0x03, 0x0C, 0x00])
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCI_Command_Complete_Event)
    assert pkt.num_hci_command_packets == 1
    assert pkt.command_opcode == HCI_RESET
    assert pkt.return_parameters == bytes([0x00])


def test_command_status_event_decode():
    raw = bytes([0x04, 0x0F, 0x04, 0x00, 0x01, 0x06, 0x04])
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCI_Command_Status_Event)
    assert pkt.status == 0x00
    assert pkt.num_hci_command_packets == 1
    assert pkt.command_opcode == 0x0406


def test_connection_complete_event_decode():
    # status(1) + handle(2) + addr(6) + link_type(1) + encryption(1)
    params = bytes([0x00, 0x01, 0x00]) + bytes(6) + bytes([0x01, 0x00])
    raw = bytes([0x04, 0x03, len(params)]) + params
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCI_Connection_Complete_Event)
    assert pkt.status == 0x00
    assert pkt.connection_handle == 0x0001


def test_disconnection_complete_event_decode():
    raw = bytes([0x04, 0x05, 0x04, 0x00, 0x40, 0x00, 0x13])
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCI_Disconnection_Complete_Event)
    assert pkt.status == 0x00
    assert pkt.connection_handle == 0x0040
    assert pkt.reason == 0x13


def test_num_completed_packets_event_decode():
    # num_handles(1)=1, handle(2)=0x0040, num_completed(2)=5
    raw = bytes([0x04, 0x13, 0x05, 0x01, 0x40, 0x00, 0x05, 0x00])
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCI_Number_Of_Completed_Packets_Event)
    assert pkt.completed == {0x0040: 5}


def test_le_meta_event_decode():
    # LE Connection Complete sub-event
    params = bytes([0x01]) + b"\x00" * 18  # sub_event=1 + dummy params
    raw = bytes([0x04, 0x3E, len(params)]) + params
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCI_LE_Meta_Event)
    assert pkt.subevent_code == 0x01


def test_unknown_event_decoded_as_base():
    raw = bytes([0x04, 0xFE, 0x02, 0x01, 0x02])
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCIEvent)
    assert pkt.event_code == 0xFE
    assert pkt.parameters == bytes([0x01, 0x02])


# --- HCI ACL Data ---

def test_acl_data_encode():
    pkt = HCIACLData(handle=0x0040, pb_flag=0x02, bc_flag=0x00, data=b"\x01\x02\x03")
    raw = pkt.to_bytes()
    assert raw[0] == 0x02  # ACL type
    handle_flags = struct.unpack_from("<H", raw, 1)[0]
    assert (handle_flags & 0x0FFF) == 0x0040
    assert ((handle_flags >> 12) & 0x03) == 0x02
    length = struct.unpack_from("<H", raw, 3)[0]
    assert length == 3
    assert raw[5:] == b"\x01\x02\x03"


def test_acl_data_decode():
    # handle=0x0040, PB=0x02, BC=0x00 → flags_handle = 0x2040
    raw = bytes([0x02, 0x40, 0x20, 0x03, 0x00, 0x01, 0x02, 0x03])
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCIACLData)
    assert pkt.handle == 0x0040
    assert pkt.pb_flag == 0x02
    assert pkt.data == b"\x01\x02\x03"


def test_acl_data_roundtrip():
    original = HCIACLData(handle=0x0001, pb_flag=0x02, bc_flag=0x00, data=b"hello")
    raw = original.to_bytes()
    decoded = decode_hci_packet(raw)
    assert isinstance(decoded, HCIACLData)
    assert decoded.handle == original.handle
    assert decoded.pb_flag == original.pb_flag
    assert decoded.data == original.data


# --- HCI SCO Data ---

def test_sco_data_encode():
    pkt = HCISCOData(handle=0x0001, packet_status=0, data=b"\xAB\xCD")
    raw = pkt.to_bytes()
    assert raw[0] == 0x03
    assert raw[4:] == b"\xAB\xCD"


def test_sco_data_decode():
    raw = bytes([0x03, 0x01, 0x00, 0x02, 0xAB, 0xCD])
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCISCOData)
    assert pkt.handle == 0x0001
    assert pkt.data == b"\xAB\xCD"


# --- HCI ISO Data (补充1) ---

def test_iso_data_encode():
    pkt = HCIISOData(
        handle=0x0001, pb_flag=0x00, ts_flag=0, data=b"\x01\x02\x03"
    )
    raw = pkt.to_bytes()
    assert raw[0] == 0x05  # ISO type


def test_iso_data_decode():
    # handle=0x0001, pb=0, ts=0 → handle_flags=0x0001, data_len=3
    handle_flags = 0x0001  # 12-bit handle, pb=0, ts=0
    data_len = 3  # 14-bit
    raw = struct.pack("<BHH", 0x05, handle_flags, data_len) + b"\x01\x02\x03"
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCIISOData)
    assert pkt.handle == 0x0001
    assert pkt.data == b"\x01\x02\x03"


def test_iso_data_roundtrip():
    original = HCIISOData(handle=0x0010, pb_flag=0x02, ts_flag=0, data=b"\xFF" * 10)
    raw = original.to_bytes()
    decoded = decode_hci_packet(raw)
    assert isinstance(decoded, HCIISOData)
    assert decoded.handle == original.handle
    assert decoded.data == original.data


# --- PacketRegistry roundtrip ---

def test_packet_registry_roundtrip():
    cmd = HCI_Reset()
    raw = cmd.to_bytes()
    decoded = decode_hci_packet(raw)
    assert type(decoded) is HCI_Reset
