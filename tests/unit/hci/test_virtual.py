"""Tests for VirtualController."""

import struct

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    ErrorCode,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_READ_BD_ADDR,
    HCI_READ_BUFFER_SIZE,
    HCI_READ_LOCAL_SUPPORTED_COMMANDS,
    HCI_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_READ_LOCAL_VERSION,
    HCI_RESET,
    HCI_SET_EVENT_MASK,
    HCI_LE_SET_EVENT_MASK,
    HCI_WRITE_LE_HOST_SUPPORTED,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
    HCI_WRITE_SCAN_ENABLE,
    HCI_HOST_BUFFER_SIZE,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES,
)
from pybluehost.hci.packets import (
    HCI_Command_Complete_Event,
    HCI_LE_Read_Buffer_Size_Command,
    HCI_Read_BD_ADDR_Command,
    HCI_Read_Buffer_Size_Command,
    HCI_Read_Local_Supported_Commands_Command,
    HCI_Read_Local_Supported_Features_Command,
    HCI_Read_Local_Version_Command,
    HCI_Reset,
    HCI_Set_Event_Mask_Command,
    HCI_LE_Set_Event_Mask_Command,
    HCI_Write_LE_Host_Supported_Command,
    HCI_Write_Simple_Pairing_Mode_Command,
    HCI_Write_Scan_Enable_Command,
    HCI_Host_Buffer_Size_Command,
    HCI_LE_Set_Scan_Parameters_Command,
    HCI_LE_Set_Random_Address_Command,
    HCI_LE_Read_Local_Supported_Features_Command,
    decode_hci_packet,
)
from pybluehost.hci.virtual import VirtualController


@pytest.fixture
def vc():
    return VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:FF"))


async def test_reset_command(vc):
    cmd = HCI_Reset()
    response = await vc.process(cmd.to_bytes())
    assert response is not None
    event = decode_hci_packet(response)
    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.command_opcode == HCI_RESET
    assert event.return_parameters[0] == ErrorCode.SUCCESS


async def test_read_bd_addr(vc):
    cmd = HCI_Read_BD_ADDR_Command()
    response = await vc.process(cmd.to_bytes())
    event = decode_hci_packet(response)
    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.command_opcode == HCI_READ_BD_ADDR
    assert event.return_parameters[0] == ErrorCode.SUCCESS
    # Address bytes follow status byte (6 bytes, reversed from colon notation)
    addr_bytes = event.return_parameters[1:7]
    assert len(addr_bytes) == 6
    # Should be reversed: AA:BB:CC:DD:EE:FF -> FF:EE:DD:CC:BB:AA in LE
    assert addr_bytes == b"\xFF\xEE\xDD\xCC\xBB\xAA"


async def test_read_local_version(vc):
    cmd = HCI_Read_Local_Version_Command()
    response = await vc.process(cmd.to_bytes())
    event = decode_hci_packet(response)
    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.command_opcode == HCI_READ_LOCAL_VERSION
    assert event.return_parameters[0] == ErrorCode.SUCCESS
    # status(1) + HCI_Version(1) + HCI_Revision(2) + LMP_Version(1) + Manufacturer(2) + LMP_Subversion(2) = 9
    assert len(event.return_parameters) == 9


async def test_read_buffer_size(vc):
    cmd = HCI_Read_Buffer_Size_Command()
    response = await vc.process(cmd.to_bytes())
    event = decode_hci_packet(response)
    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.command_opcode == HCI_READ_BUFFER_SIZE
    assert event.return_parameters[0] == ErrorCode.SUCCESS
    # Parse: acl_data_packet_length(2) + sco(1) + total_acl(2) + total_sco(2)
    acl_len, sco_len, acl_num, sco_num = struct.unpack_from(
        "<HBHH", event.return_parameters, 1
    )
    assert acl_len == 1024
    assert sco_len == 64
    assert acl_num == 8
    assert sco_num == 4


async def test_le_read_buffer_size(vc):
    cmd = HCI_LE_Read_Buffer_Size_Command()
    response = await vc.process(cmd.to_bytes())
    event = decode_hci_packet(response)
    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.command_opcode == HCI_LE_READ_BUFFER_SIZE
    assert event.return_parameters[0] == ErrorCode.SUCCESS
    # status(1) + le_acl_data_packet_length(2) + total_num_le_acl(1) = 4 bytes
    assert len(event.return_parameters) >= 4
    le_acl_len, le_acl_num = struct.unpack_from("<HB", event.return_parameters, 1)
    assert le_acl_len == 251
    assert le_acl_num == 8


async def test_read_local_supported_commands(vc):
    cmd = HCI_Read_Local_Supported_Commands_Command()
    response = await vc.process(cmd.to_bytes())
    event = decode_hci_packet(response)
    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.command_opcode == HCI_READ_LOCAL_SUPPORTED_COMMANDS
    assert event.return_parameters[0] == ErrorCode.SUCCESS
    # status(1) + 64 bytes = 65
    assert len(event.return_parameters) == 65


async def test_read_local_supported_features(vc):
    cmd = HCI_Read_Local_Supported_Features_Command()
    response = await vc.process(cmd.to_bytes())
    event = decode_hci_packet(response)
    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.command_opcode == HCI_READ_LOCAL_SUPPORTED_FEATURES
    assert event.return_parameters[0] == ErrorCode.SUCCESS
    # status(1) + 8 bytes = 9
    assert len(event.return_parameters) == 9


async def test_le_read_local_supported_features(vc):
    cmd = HCI_LE_Read_Local_Supported_Features_Command()
    response = await vc.process(cmd.to_bytes())
    event = decode_hci_packet(response)
    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.command_opcode == HCI_LE_READ_LOCAL_SUPPORTED_FEATURES
    assert event.return_parameters[0] == ErrorCode.SUCCESS
    assert len(event.return_parameters) == 9


async def test_unknown_command_returns_unknown_command_error(vc):
    # Build a command with unknown opcode 0xFFFE
    raw = bytes([0x01, 0xFE, 0xFF, 0x00])  # H4 cmd, opcode=0xFFFE, param_len=0
    response = await vc.process(raw)
    event = decode_hci_packet(response)
    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.command_opcode == 0xFFFE
    assert event.return_parameters[0] == ErrorCode.UNKNOWN_COMMAND


async def test_non_command_returns_none(vc):
    # H4 event packet (0x04) should return None
    raw = bytes([0x04, 0x0E, 0x03, 0x01, 0x00, 0x00])
    result = await vc.process(raw)
    assert result is None


async def test_empty_data_returns_none(vc):
    result = await vc.process(b"")
    assert result is None


@pytest.mark.parametrize(
    "cmd_factory,expected_opcode",
    [
        (lambda: HCI_Set_Event_Mask_Command(), HCI_SET_EVENT_MASK),
        (lambda: HCI_LE_Set_Event_Mask_Command(), HCI_LE_SET_EVENT_MASK),
        (lambda: HCI_Write_LE_Host_Supported_Command(), HCI_WRITE_LE_HOST_SUPPORTED),
        (lambda: HCI_Write_Simple_Pairing_Mode_Command(), HCI_WRITE_SIMPLE_PAIRING_MODE),
        (lambda: HCI_Write_Scan_Enable_Command(), HCI_WRITE_SCAN_ENABLE),
        (lambda: HCI_Host_Buffer_Size_Command(), HCI_HOST_BUFFER_SIZE),
        (lambda: HCI_LE_Set_Scan_Parameters_Command(), HCI_LE_SET_SCAN_PARAMS),
        (lambda: HCI_LE_Set_Random_Address_Command(), HCI_LE_SET_RANDOM_ADDRESS),
    ],
)
async def test_status_only_commands(vc, cmd_factory, expected_opcode):
    """Commands that only return a status byte should all succeed."""
    cmd = cmd_factory()
    response = await vc.process(cmd.to_bytes())
    assert response is not None
    event = decode_hci_packet(response)
    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.command_opcode == expected_opcode
    assert event.return_parameters[0] == ErrorCode.SUCCESS
