"""HCI feature-bitmap decoding tables.

Pure-data dictionaries mapping (octet, bit) tuples to human-readable feature
names. Used by ``pybluehost tools info`` and any future capability-introspection
tooling. No logic; safe to import without HCI state.

References:
  * Core Spec 5.4 Vol 6 Part B §4.6 (LE Features)
  * Core Spec 5.4 Vol 2 Part C §3.3 (BR/EDR LMP Features page 0)
  * Bluetooth Assigned Numbers, Company Identifiers
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# LE Features bitmap: (octet, bit) -> name
# Core Spec 5.4 Vol 6 Part B §4.6 Table 4.6.1
# ---------------------------------------------------------------------------

LE_FEATURE_BIT_NAMES: dict[tuple[int, int], str] = {
    (0, 0): "LE Encryption",
    (0, 1): "Connection Parameters Request Procedure",
    (0, 2): "Extended Reject Indication",
    (0, 3): "Slave-initiated Features Exchange",
    (0, 4): "LE Ping",
    (0, 5): "LE Data Packet Length Extension",
    (0, 6): "LL Privacy",
    (0, 7): "Extended Scanner Filter Policies",
    (1, 0): "LE 2M PHY",
    (1, 1): "Stable Modulation Index - Transmitter",
    (1, 2): "Stable Modulation Index - Receiver",
    (1, 3): "LE Coded PHY",
    (1, 4): "LE Extended Advertising",
    (1, 5): "LE Periodic Advertising",
    (1, 6): "Channel Selection Algorithm #2",
    (1, 7): "LE Power Class 1",
    (2, 0): "Minimum Number of Used Channels Procedure",
    (2, 1): "Connection CTE Request",
    (2, 2): "Connection CTE Response",
    (2, 3): "Connectionless CTE Transmitter",
    (2, 4): "Connectionless CTE Receiver",
    (2, 5): "Antenna Switching During CTE Transmission (AoD)",
    (2, 6): "Antenna Switching During CTE Reception (AoA)",
    (2, 7): "Receiving Constant Tone Extensions",
    (3, 0): "Periodic Advertising Sync Transfer - Sender",
    (3, 1): "Periodic Advertising Sync Transfer - Recipient",
    (3, 2): "Sleep Clock Accuracy Updates",
    (3, 3): "Remote Public Key Validation",
    (3, 4): "Connected Isochronous Stream - Central",
    (3, 5): "Connected Isochronous Stream - Peripheral",
    (3, 6): "Isochronous Broadcaster",
    (3, 7): "Synchronized Receiver",
    (4, 0): "Connected Isochronous Stream (Host Support)",
    (4, 1): "LE Power Control Request",
    (4, 2): "LE Power Change Indication",
    (4, 3): "LE Path Loss Monitoring",
    (4, 4): "Periodic Advertising ADI Support",
    (4, 5): "Connection Subrating",
    (4, 6): "Connection Subrating (Host Support)",
    (4, 7): "Channel Classification",
}


# ---------------------------------------------------------------------------
# BR/EDR LMP Features page 0: (octet, bit) -> name
# Core Spec 5.4 Vol 2 Part C §3.3 Table 3.2
# ---------------------------------------------------------------------------

BREDR_FEATURE_BIT_NAMES: dict[tuple[int, int], str] = {
    (0, 0): "3-slot packets",
    (0, 1): "5-slot packets",
    (0, 2): "Encryption",
    (0, 3): "Slot offset",
    (0, 4): "Timing accuracy",
    (0, 5): "Role switch",
    (0, 6): "Hold mode",
    (0, 7): "Sniff mode",
    (1, 0): "Park state",
    (1, 1): "Power control requests",
    (1, 2): "Channel quality driven data rate (CQDDR)",
    (1, 3): "SCO link",
    (1, 4): "HV2 packets",
    (1, 5): "HV3 packets",
    (1, 6): "u-law log synchronous data",
    (1, 7): "A-law log synchronous data",
    (2, 0): "CVSD synchronous data",
    (2, 1): "Paging parameter negotiation",
    (2, 2): "Power control",
    (2, 3): "Transparent synchronous data",
    (2, 4): "Flow control lag (LSB)",
    (2, 5): "Flow control lag (Middle)",
    (2, 6): "Flow control lag (MSB)",
    (2, 7): "Broadcast Encryption",
    (3, 1): "EDR ACL 2 Mbps mode",
    (3, 2): "EDR ACL 3 Mbps mode",
    (3, 3): "Enhanced inquiry scan",
    (3, 4): "Interlaced inquiry scan",
    (3, 5): "Interlaced page scan",
    (3, 6): "RSSI with inquiry results",
    (3, 7): "EV3 packets",
    (4, 0): "EV4 packets",
    (4, 1): "EV5 packets",
    (4, 3): "AFH capable peripheral",
    (4, 4): "AFH classification peripheral",
    (4, 5): "BR/EDR Not Supported",
    (4, 6): "LE Supported (Controller)",
    (4, 7): "3-slot EDR ACL packets",
    (5, 0): "5-slot EDR ACL packets",
    (5, 1): "Sniff subrating",
    (5, 2): "Pause Encryption",
    (5, 3): "AFH capable central",
    (5, 4): "AFH classification central",
    (5, 5): "EDR eSCO 2 Mbps mode",
    (5, 6): "EDR eSCO 3 Mbps mode",
    (5, 7): "3-slot EDR eSCO packets",
    (6, 0): "Extended Inquiry Response",
    (6, 1): "Simultaneous LE and BR/EDR to Same Device Capable (Controller)",
    (6, 3): "Secure Simple Pairing (Controller Support)",
    (6, 4): "Encapsulated PDU",
    (6, 5): "Erroneous Data Reporting",
    (6, 6): "Non-flushable Packet Boundary Flag",
    (7, 0): "HCI_Link_Supervision_Timeout_Changed Event",
    (7, 1): "Variable Inquiry TX Power Level",
    (7, 2): "Enhanced Power Control",
    (7, 7): "Extended features",
}


# ---------------------------------------------------------------------------
# BR/EDR LMP Features page 1 — host-side features
# Core Spec 5.4 Vol 2 Part C §3.3 Table 3.3
# ---------------------------------------------------------------------------

BREDR_FEATURE_BIT_NAMES_P1: dict[tuple[int, int], str] = {
    (0, 0): "Secure Simple Pairing (Host Support)",
    (0, 1): "LE Supported (Host)",
    (0, 2): "Simultaneous LE and BR/EDR to Same Device Capable (Host)",
    (0, 3): "Secure Connections (Host Support)",
}


# ---------------------------------------------------------------------------
# BR/EDR LMP Features page 2 — extended controller-side features
# Core Spec 5.4 Vol 2 Part C §3.3 Table 3.4
# ---------------------------------------------------------------------------

BREDR_FEATURE_BIT_NAMES_P2: dict[tuple[int, int], str] = {
    (0, 0): "Connectionless Slave Broadcast - Transmitter Operation",
    (0, 1): "Connectionless Slave Broadcast - Receiver Operation",
    (0, 2): "Synchronization Train",
    (0, 3): "Synchronization Scan",
    (0, 4): "HCI_Inquiry_Response_Notification Event",
    (0, 5): "Generalized interlaced scan",
    (0, 6): "Coarse Clock Adjustment",
    (1, 0): "Secure Connections (Controller Support)",
    (1, 1): "Ping",
    (1, 2): "Slot Availability Mask",
    (1, 3): "Train Nudging",
}


# ---------------------------------------------------------------------------
# Bluetooth SIG Company Identifiers (common chipset vendors)
# Full list: https://www.bluetooth.com/specifications/assigned-numbers/company-identifiers/
# ---------------------------------------------------------------------------

MANUFACTURER_NAMES: dict[int, str] = {
    0x0001: "Nokia Mobile Phones",
    0x0002: "Intel Corp.",
    0x0003: "IBM Corp.",
    0x0004: "Toshiba Corp.",
    0x0005: "3Com",
    0x0006: "Microsoft",
    0x0007: "Lucent",
    0x0008: "Motorola",
    0x0009: "Infineon Technologies AG",
    0x000A: "CSR (Qualcomm)",
    0x000B: "Silicon Wave",
    0x000C: "Digianswer A/S",
    0x000D: "Texas Instruments Inc.",
    0x000F: "Broadcom Corporation",
    0x001D: "Atheros Communications",
    0x004C: "Apple Inc.",
    0x005D: "Realtek Semiconductor Corp.",
    0x005F: "MediaTek, Inc.",
    0x0075: "Samsung Electronics Co. Ltd.",
    0x00E0: "Google",
    0x05A7: "Linux Foundation",
}


def manufacturer_name(manufacturer_id: int) -> str:
    """Return the human-readable name for a Bluetooth SIG company identifier,
    or ``"Unknown (0x....)"`` for IDs not in :data:`MANUFACTURER_NAMES`.
    """
    return MANUFACTURER_NAMES.get(
        manufacturer_id, f"Unknown (0x{manufacturer_id:04X})"
    )


# ---------------------------------------------------------------------------
# HCI / LMP version identifiers
# Core Spec 5.4 Vol 4 Part E §7.4.1, also Assigned Numbers - Host Controller
# Interface. HCI_Version and LMP_Version share the same enumeration.
# ---------------------------------------------------------------------------

HCI_VERSION_NAMES: dict[int, str] = {
    0x00: "Bluetooth 1.0b",
    0x01: "Bluetooth 1.1",
    0x02: "Bluetooth 1.2",
    0x03: "Bluetooth 2.0 + EDR",
    0x04: "Bluetooth 2.1 + EDR",
    0x05: "Bluetooth 3.0 + HS",
    0x06: "Bluetooth 4.0",
    0x07: "Bluetooth 4.1",
    0x08: "Bluetooth 4.2",
    0x09: "Bluetooth 5.0",
    0x0A: "Bluetooth 5.1",
    0x0B: "Bluetooth 5.2",
    0x0C: "Bluetooth 5.3",
    0x0D: "Bluetooth 5.4",
    0x0E: "Bluetooth 6.0",
}


def hci_version_name(version: int) -> str:
    """Human-readable name for an HCI_Version / LMP_Version byte.

    Returns "Unknown (0x..)" for values not in :data:`HCI_VERSION_NAMES`.
    """
    return HCI_VERSION_NAMES.get(version, f"Unknown (0x{version:02X})")


# ---------------------------------------------------------------------------
# HCI Supported_Commands bitmap — (octet, bit) -> command name
# Core Spec 5.4 Vol 4 Part E §6.27 Table 6.27.
#
# This is the DISPLAY table used by `pybluehost tools info` to decode the
# 64-byte bitmap into human-readable names. It's a separate concern from
# `pybluehost.hci.capabilities._OPCODE_BIT_POSITIONS`, which is the RUNTIME
# gate (only opcodes PyBlueHost issues + needs to check support of).
#
# Not exhaustive — covers ~270 of the ~280 named positions in Spec 5.4.
# Positions not in this table are reserved or vendor-reserved in the spec.
# ---------------------------------------------------------------------------

SUPPORTED_COMMAND_NAMES: dict[tuple[int, int], str] = {
    # Octet 0 — Link Control (OGF 0x01)
    (0, 0): "Inquiry",
    (0, 1): "Inquiry_Cancel",
    (0, 2): "Periodic_Inquiry_Mode",
    (0, 3): "Exit_Periodic_Inquiry_Mode",
    (0, 4): "Create_Connection",
    (0, 5): "Disconnect",
    (0, 6): "Add_SCO_Connection",  # deprecated
    (0, 7): "Create_Connection_Cancel",
    # Octet 1
    (1, 0): "Accept_Connection_Request",
    (1, 1): "Reject_Connection_Request",
    (1, 2): "Link_Key_Request_Reply",
    (1, 3): "Link_Key_Request_Negative_Reply",
    (1, 4): "PIN_Code_Request_Reply",
    (1, 5): "PIN_Code_Request_Negative_Reply",
    (1, 6): "Change_Connection_Packet_Type",
    (1, 7): "Authentication_Requested",
    # Octet 2
    (2, 0): "Set_Connection_Encryption",
    (2, 1): "Change_Connection_Link_Key",
    (2, 2): "Master_Link_Key",
    (2, 3): "Remote_Name_Request",
    (2, 4): "Remote_Name_Request_Cancel",
    (2, 5): "Read_Remote_Supported_Features",
    (2, 6): "Read_Remote_Extended_Features",
    (2, 7): "Read_Remote_Version_Information",
    # Octet 3
    (3, 0): "Read_Clock_Offset",
    (3, 1): "Read_LMP_Handle",
    # 3,2..3,7 reserved
    # Octet 4
    (4, 0): "Hold_Mode",
    (4, 1): "Sniff_Mode",
    (4, 2): "Exit_Sniff_Mode",
    (4, 3): "Park_State",  # deprecated
    (4, 4): "Exit_Park_State",  # deprecated
    (4, 5): "QoS_Setup",
    (4, 6): "Role_Discovery",
    (4, 7): "Switch_Role",
    # Octet 5
    (5, 0): "Read_Link_Policy_Settings",
    (5, 1): "Write_Link_Policy_Settings",
    (5, 2): "Read_Default_Link_Policy_Settings",
    (5, 3): "Write_Default_Link_Policy_Settings",
    (5, 4): "Flow_Specification",
    (5, 5): "Set_Event_Mask",
    (5, 6): "Reset",
    (5, 7): "Set_Event_Filter",
    # Octet 6
    (6, 0): "Flush",
    (6, 1): "Read_PIN_Type",
    (6, 2): "Write_PIN_Type",
    (6, 3): "Create_New_Unit_Key",
    (6, 4): "Read_Stored_Link_Key",
    (6, 5): "Write_Stored_Link_Key",
    (6, 6): "Delete_Stored_Link_Key",
    (6, 7): "Write_Local_Name",
    # Octet 7
    (7, 0): "Read_Local_Name",
    (7, 1): "Read_Connection_Accept_Timeout",
    (7, 2): "Write_Connection_Accept_Timeout",
    (7, 3): "Read_Page_Timeout",
    (7, 4): "Write_Page_Timeout",
    (7, 5): "Read_Scan_Enable",
    (7, 6): "Write_Scan_Enable",
    (7, 7): "Read_Page_Scan_Activity",
    # Octet 8
    (8, 0): "Write_Page_Scan_Activity",
    (8, 1): "Read_Inquiry_Scan_Activity",
    (8, 2): "Write_Inquiry_Scan_Activity",
    (8, 3): "Read_Authentication_Enable",
    (8, 4): "Write_Authentication_Enable",
    (8, 5): "Read_Encryption_Mode",  # deprecated
    (8, 6): "Write_Encryption_Mode",  # deprecated
    (8, 7): "Read_Class_Of_Device",
    # Octet 9
    (9, 0): "Write_Class_Of_Device",
    (9, 1): "Read_Voice_Setting",
    (9, 2): "Write_Voice_Setting",
    (9, 3): "Read_Automatic_Flush_Timeout",
    (9, 4): "Write_Automatic_Flush_Timeout",
    (9, 5): "Read_Num_Broadcast_Retransmissions",
    (9, 6): "Write_Num_Broadcast_Retransmissions",
    (9, 7): "Read_Hold_Mode_Activity",
    # Octet 10
    (10, 0): "Write_Hold_Mode_Activity",
    (10, 1): "Read_Transmit_Power_Level",
    (10, 2): "Read_Synchronous_Flow_Control_Enable",
    (10, 3): "Write_Synchronous_Flow_Control_Enable",
    (10, 4): "Set_Controller_To_Host_Flow_Control",
    (10, 5): "Host_Buffer_Size",
    (10, 6): "Host_Number_Of_Completed_Packets",
    (10, 7): "Read_Link_Supervision_Timeout",
    # Octet 11
    (11, 0): "Write_Link_Supervision_Timeout",
    (11, 1): "Read_Number_Of_Supported_IAC",
    (11, 2): "Read_Current_IAC_LAP",
    (11, 3): "Write_Current_IAC_LAP",
    (11, 4): "Read_Page_Scan_Mode_Period",  # deprecated
    (11, 5): "Write_Page_Scan_Mode_Period",  # deprecated
    (11, 6): "Read_Page_Scan_Mode",  # deprecated
    (11, 7): "Write_Page_Scan_Mode",  # deprecated
    # Octet 12
    (12, 0): "Set_AFH_Host_Channel_Classification",
    (12, 4): "Read_Inquiry_Scan_Type",
    (12, 5): "Write_Inquiry_Scan_Type",
    (12, 6): "Read_Inquiry_Mode",
    (12, 7): "Write_Inquiry_Mode",
    # Octet 13
    (13, 0): "Read_Page_Scan_Type",
    (13, 1): "Write_Page_Scan_Type",
    (13, 2): "Read_AFH_Channel_Assessment_Mode",
    (13, 3): "Write_AFH_Channel_Assessment_Mode",
    # Octet 14
    (14, 3): "Read_Local_Version_Information",
    (14, 4): "Read_Local_Supported_Features",
    (14, 5): "Read_Local_Supported_Commands",  # Self-referential
    (14, 6): "Read_Local_Extended_Features",
    (14, 7): "Read_Buffer_Size",
    # Octet 15
    (15, 0): "Read_Country_Code",  # deprecated
    (15, 1): "Read_BD_ADDR",
    (15, 2): "Read_Failed_Contact_Counter",
    (15, 3): "Reset_Failed_Contact_Counter",
    (15, 4): "Read_Link_Quality",
    (15, 5): "Read_RSSI",
    (15, 6): "Read_AFH_Channel_Map",
    (15, 7): "Read_Clock",
    # Octet 16
    (16, 0): "Read_Loopback_Mode",
    (16, 1): "Write_Loopback_Mode",
    (16, 2): "Enable_Device_Under_Test_Mode",
    (16, 3): "Setup_Synchronous_Connection_Request",
    (16, 4): "Accept_Synchronous_Connection_Request",
    (16, 5): "Reject_Synchronous_Connection_Request",
    # Octet 17
    (17, 0): "Read_Extended_Inquiry_Response",
    (17, 1): "Write_Extended_Inquiry_Response",
    (17, 2): "Refresh_Encryption_Key",
    (17, 4): "Sniff_Subrating",
    (17, 5): "Read_Simple_Pairing_Mode",
    (17, 6): "Write_Simple_Pairing_Mode",
    (17, 7): "Read_Local_OOB_Data",
    # Octet 18
    (18, 0): "Read_Inquiry_Response_Transmit_Power_Level",
    (18, 1): "Write_Inquiry_Transmit_Power_Level",
    (18, 2): "Read_Default_Erroneous_Data_Reporting",
    (18, 3): "Write_Default_Erroneous_Data_Reporting",
    (18, 7): "IO_Capability_Request_Reply",
    # Octet 19
    (19, 0): "User_Confirmation_Request_Reply",
    (19, 1): "User_Confirmation_Request_Negative_Reply",
    (19, 2): "User_Passkey_Request_Reply",
    (19, 3): "User_Passkey_Request_Negative_Reply",
    (19, 4): "Remote_OOB_Data_Request_Reply",
    (19, 5): "Write_Simple_Pairing_Debug_Mode",
    (19, 6): "Enhanced_Flush",
    (19, 7): "Remote_OOB_Data_Request_Negative_Reply",
    # Octet 20
    (20, 2): "Send_Keypress_Notification",
    (20, 3): "IO_Capability_Request_Negative_Reply",
    (20, 4): "Read_Encryption_Key_Size",
    # Octet 22 — LE Controller commands begin here on most adapters
    (22, 1): "Set_Event_Mask_Page_2",
    # Octet 23
    (23, 0): "Read_Flow_Control_Mode",
    (23, 1): "Write_Flow_Control_Mode",
    (23, 2): "Read_Data_Block_Size",
    # Octet 24
    (24, 0): "Read_Enhanced_Transmit_Power_Level",
    (24, 5): "Read_LE_Host_Support",
    (24, 6): "Write_LE_Host_Support",
    # Octet 25 — Bluetooth 4.0 LE Controller commands begin
    (25, 0): "LE_Set_Event_Mask",
    (25, 1): "LE_Read_Buffer_Size_V1",
    # Spec 6.1 renamed this to LE_Read_Local_Supported_Features_Page (same
    # OCF 0x0003, same bit position; added optional page_number parameter).
    (25, 2): "LE_Read_Local_Supported_Features_Page",
    (25, 4): "LE_Set_Random_Address",
    (25, 5): "LE_Set_Advertising_Parameters",
    (25, 6): "LE_Read_Advertising_Channel_TX_Power",
    (25, 7): "LE_Set_Advertising_Data",
    # Octet 26
    (26, 0): "LE_Set_Scan_Response_Data",
    (26, 1): "LE_Set_Advertising_Enable",
    (26, 2): "LE_Set_Scan_Parameters",
    (26, 3): "LE_Set_Scan_Enable",
    (26, 4): "LE_Create_Connection",
    (26, 5): "LE_Create_Connection_Cancel",
    (26, 6): "LE_Read_Filter_Accept_List_Size",
    (26, 7): "LE_Clear_Filter_Accept_List",
    # Octet 27
    (27, 0): "LE_Add_Device_To_Filter_Accept_List",
    (27, 1): "LE_Remove_Device_From_Filter_Accept_List",
    (27, 2): "LE_Connection_Update",
    (27, 3): "LE_Set_Host_Channel_Classification",
    (27, 4): "LE_Read_Channel_Map",
    (27, 5): "LE_Read_Remote_Features",
    (27, 6): "LE_Encrypt",
    (27, 7): "LE_Rand",
    # Octet 28
    (28, 0): "LE_Enable_Encryption",
    (28, 1): "LE_Long_Term_Key_Request_Reply",
    (28, 2): "LE_Long_Term_Key_Request_Negative_Reply",
    (28, 3): "LE_Read_Supported_States",
    (28, 4): "LE_Receiver_Test_V1",
    (28, 5): "LE_Transmitter_Test_V1",
    (28, 6): "LE_Test_End",
    # Octet 29 — BT 4.1 additions
    (29, 3): "Enhanced_Setup_Synchronous_Connection",
    (29, 4): "Enhanced_Accept_Synchronous_Connection",
    (29, 5): "Read_Local_Supported_Codecs",
    (29, 6): "Set_MWS_Channel_Parameters",
    (29, 7): "Set_External_Frame_Configuration",
    # Octet 30
    (30, 0): "Set_MWS_Signaling",
    (30, 1): "Set_MWS_Transport_Layer",
    (30, 2): "Set_MWS_Scan_Frequency_Table",
    (30, 3): "Get_MWS_Transport_Layer_Configuration",
    (30, 4): "Set_MWS_PATTERN_Configuration",
    (30, 5): "Set_Triggered_Clock_Capture",
    (30, 6): "Truncated_Page",
    (30, 7): "Truncated_Page_Cancel",
    # Octet 31
    (31, 0): "Set_Connectionless_Peripheral_Broadcast",
    (31, 1): "Set_Connectionless_Peripheral_Broadcast_Receive",
    (31, 2): "Start_Synchronization_Train",
    (31, 3): "Receive_Synchronization_Train",
    (31, 4): "Set_Reserved_LT_ADDR",
    (31, 5): "Delete_Reserved_LT_ADDR",
    (31, 6): "Set_Connectionless_Peripheral_Broadcast_Data",
    (31, 7): "Read_Synchronization_Train_Parameters",
    # Octet 32 — BT 4.2 additions
    (32, 0): "Write_Synchronization_Train_Parameters",
    (32, 1): "Remote_OOB_Extended_Data_Request_Reply",
    (32, 2): "Read_Secure_Connections_Host_Support",
    (32, 3): "Write_Secure_Connections_Host_Support",
    (32, 4): "Read_Authenticated_Payload_Timeout",
    (32, 5): "Write_Authenticated_Payload_Timeout",
    (32, 6): "Read_Local_OOB_Extended_Data",
    (32, 7): "Write_Secure_Connections_Test_Mode",
    # Octet 33
    (33, 0): "Read_Extended_Page_Timeout",
    (33, 1): "Write_Extended_Page_Timeout",
    (33, 2): "Read_Extended_Inquiry_Length",
    (33, 3): "Write_Extended_Inquiry_Length",
    (33, 4): "LE_Remote_Connection_Parameter_Request_Reply",
    (33, 5): "LE_Remote_Connection_Parameter_Request_Negative_Reply",
    (33, 6): "LE_Set_Data_Length",
    (33, 7): "LE_Read_Suggested_Default_Data_Length",
    # Octet 34
    (34, 0): "LE_Write_Suggested_Default_Data_Length",
    (34, 1): "LE_Read_Local_P-256_Public_Key",
    (34, 2): "LE_Generate_DHKey_V1",
    (34, 3): "LE_Add_Device_To_Resolving_List",
    (34, 4): "LE_Remove_Device_From_Resolving_List",
    (34, 5): "LE_Clear_Resolving_List",
    (34, 6): "LE_Read_Resolving_List_Size",
    (34, 7): "LE_Read_Peer_Resolvable_Address",
    # Octet 35
    (35, 0): "LE_Read_Local_Resolvable_Address",
    (35, 1): "LE_Set_Address_Resolution_Enable",
    (35, 2): "LE_Set_Resolvable_Private_Address_Timeout",
    (35, 3): "LE_Read_Maximum_Data_Length",
    (35, 4): "LE_Read_PHY",
    (35, 5): "LE_Set_Default_PHY",
    (35, 6): "LE_Set_PHY",
    (35, 7): "LE_Receiver_Test_V2",
    # Octet 36 — BT 5.0 additions (Extended Advertising)
    (36, 0): "LE_Transmitter_Test_V2",
    (36, 1): "LE_Set_Advertising_Set_Random_Address",
    (36, 2): "LE_Set_Extended_Advertising_Parameters",
    (36, 3): "LE_Set_Extended_Advertising_Data",
    (36, 4): "LE_Set_Extended_Scan_Response_Data",
    (36, 5): "LE_Set_Extended_Advertising_Enable",
    (36, 6): "LE_Read_Maximum_Advertising_Data_Length",
    (36, 7): "LE_Read_Number_Of_Supported_Advertising_Sets",
    # Octet 37
    (37, 0): "LE_Remove_Advertising_Set",
    (37, 1): "LE_Clear_Advertising_Sets",
    (37, 2): "LE_Set_Periodic_Advertising_Parameters",
    (37, 3): "LE_Set_Periodic_Advertising_Data",
    (37, 4): "LE_Set_Periodic_Advertising_Enable",
    (37, 5): "LE_Set_Extended_Scan_Parameters",
    (37, 6): "LE_Set_Extended_Scan_Enable",
    (37, 7): "LE_Extended_Create_Connection",
    # Octet 38
    (38, 0): "LE_Periodic_Advertising_Create_Sync",
    (38, 1): "LE_Periodic_Advertising_Create_Sync_Cancel",
    (38, 2): "LE_Periodic_Advertising_Terminate_Sync",
    (38, 3): "LE_Add_Device_To_Periodic_Advertiser_List",
    (38, 4): "LE_Remove_Device_From_Periodic_Advertiser_List",
    (38, 5): "LE_Clear_Periodic_Advertiser_List",
    (38, 6): "LE_Read_Periodic_Advertiser_List_Size",
    (38, 7): "LE_Read_Transmit_Power",
    # Octet 39
    (39, 0): "LE_Read_RF_Path_Compensation",
    (39, 1): "LE_Write_RF_Path_Compensation",
    (39, 2): "LE_Set_Privacy_Mode",
    (39, 3): "LE_Receiver_Test_V3",
    (39, 4): "LE_Transmitter_Test_V3",
    (39, 5): "LE_Set_Connectionless_CTE_Transmit_Parameters",
    (39, 6): "LE_Set_Connectionless_CTE_Transmit_Enable",
    (39, 7): "LE_Set_Connectionless_IQ_Sampling_Enable",
    # Octet 40 — BT 5.1 additions (Direction Finding)
    (40, 0): "LE_Set_Connection_CTE_Receive_Parameters",
    (40, 1): "LE_Set_Connection_CTE_Transmit_Parameters",
    (40, 2): "LE_Connection_CTE_Request_Enable",
    (40, 3): "LE_Connection_CTE_Response_Enable",
    (40, 4): "LE_Read_Antenna_Information",
    (40, 5): "LE_Set_Periodic_Advertising_Receive_Enable",
    (40, 6): "LE_Periodic_Advertising_Sync_Transfer",
    (40, 7): "LE_Periodic_Advertising_Set_Info_Transfer",
    # Octet 41
    (41, 0): "LE_Set_Periodic_Advertising_Sync_Transfer_Parameters",
    (41, 1): "LE_Set_Default_Periodic_Advertising_Sync_Transfer_Parameters",
    (41, 2): "LE_Generate_DHKey_V2",
    (41, 3): "Read_Local_Simple_Pairing_Options",
    (41, 4): "LE_Modify_Sleep_Clock_Accuracy",
    (41, 5): "LE_Read_Buffer_Size_V2",
    (41, 6): "LE_Read_ISO_TX_Sync",
    (41, 7): "LE_Set_CIG_Parameters",
    # Octet 42 — BT 5.2 additions (LE Audio)
    (42, 0): "LE_Set_CIG_Parameters_Test",
    (42, 1): "LE_Create_CIS",
    (42, 2): "LE_Remove_CIG",
    (42, 3): "LE_Accept_CIS_Request",
    (42, 4): "LE_Reject_CIS_Request",
    (42, 5): "LE_Create_BIG",
    (42, 6): "LE_Create_BIG_Test",
    (42, 7): "LE_Terminate_BIG",
    # Octet 43
    (43, 0): "LE_BIG_Create_Sync",
    (43, 1): "LE_BIG_Terminate_Sync",
    (43, 2): "LE_Request_Peer_SCA",
    (43, 3): "LE_Setup_ISO_Data_Path",
    (43, 4): "LE_Remove_ISO_Data_Path",
    (43, 5): "LE_ISO_Transmit_Test",
    (43, 6): "LE_ISO_Receive_Test",
    (43, 7): "LE_ISO_Read_Test_Counters",
    # Octet 44
    (44, 0): "LE_ISO_Test_End",
    (44, 1): "LE_Set_Host_Feature",
    (44, 2): "LE_Read_ISO_Link_Quality",
    (44, 3): "LE_Enhanced_Read_Transmit_Power_Level",
    (44, 4): "LE_Read_Remote_Transmit_Power_Level",
    (44, 5): "LE_Set_Path_Loss_Reporting_Parameters",
    (44, 6): "LE_Set_Path_Loss_Reporting_Enable",
    (44, 7): "LE_Set_Transmit_Power_Reporting_Enable",
    # Octet 45
    (45, 0): "LE_Transmitter_Test_V4",
    (45, 1): "Set_Ecosystem_Base_Interval",
    (45, 2): "Read_Local_Supported_Codecs_V2",
    (45, 3): "Read_Local_Supported_Codec_Capabilities",
    (45, 4): "Read_Local_Supported_Controller_Delay",
    (45, 5): "Configure_Data_Path",
    (45, 6): "LE_Set_Data_Related_Address_Changes",
    (45, 7): "Set_Min_Encryption_Key_Size",
    # Octet 46 — BT 5.3 additions (Subrating)
    (46, 0): "LE_Set_Default_Subrate",
    (46, 1): "LE_Subrate_Request",
}
