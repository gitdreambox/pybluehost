"""HCI packet encode/decode: commands, events, ACL, SCO, ISO data.

Provides a `decode_hci_packet()` dispatcher and a `PacketRegistry` that maps
(packet_type, opcode/event_code) → concrete class for automatic decoding.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import ClassVar

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    HCI_ACL_PACKET,
    HCI_COMMAND_PACKET,
    HCI_EVENT_PACKET,
    HCI_ISO_PACKET,
    HCI_RESET as HCI_RESET_OPCODE,
    HCI_SCO_PACKET,
    HCI_LE_SET_SCAN_ENABLE as HCI_LE_SET_SCAN_ENABLE_OPCODE,
    HCI_READ_BD_ADDR,
    HCI_READ_LOCAL_VERSION,
    HCI_READ_BUFFER_SIZE,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_SET_EVENT_MASK,
    HCI_LE_SET_EVENT_MASK,
    HCI_WRITE_LE_HOST_SUPPORTED,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
    HCI_WRITE_SCAN_ENABLE,
    HCI_HOST_BUFFER_SIZE,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_READ_LOCAL_SUPPORTED_COMMANDS,
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES_PAGE,
    HCI_READ_LOCAL_EXTENDED_FEATURES,
    HCI_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_LE_START_ENCRYPTION,
    HCI_LE_LONG_TERM_KEY_REQUEST_REPLY,
    HCI_LE_LONG_TERM_KEY_REQUEST_NEGATIVE_REPLY,
    HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT,
    HCI_LINK_KEY_REQUEST_REPLY,
    EventCode,
)


# ---------------------------------------------------------------------------
# PacketRegistry
# ---------------------------------------------------------------------------

class PacketRegistry:
    """Maps (packet_type, key) → packet class for automatic decoding.

    For commands: key is the opcode.
    For events: key is the event_code.
    """

    _command_classes: ClassVar[dict[int, type[HCICommand]]] = {}
    _event_classes: ClassVar[dict[int, type[HCIEvent]]] = {}

    @classmethod
    def register_command(cls, opcode: int):
        """Class decorator: register a command class for an opcode."""
        def decorator(klass):
            cls._command_classes[opcode] = klass
            return klass
        return decorator

    @classmethod
    def register_event(cls, event_code: int):
        """Class decorator: register an event class for an event code."""
        def decorator(klass):
            cls._event_classes[event_code] = klass
            return klass
        return decorator

    @classmethod
    def get_command_class(cls, opcode: int) -> type[HCICommand] | None:
        return cls._command_classes.get(opcode)

    @classmethod
    def get_event_class(cls, event_code: int) -> type[HCIEvent] | None:
        return cls._event_classes.get(event_code)


# ---------------------------------------------------------------------------
# Base packet classes
# ---------------------------------------------------------------------------

@dataclass
class HCIPacket:
    """Base class for all HCI packets."""

    def to_bytes(self) -> bytes:
        raise NotImplementedError


@dataclass
class HCICommand(HCIPacket):
    """Generic HCI command: H4(0x01) + opcode(2 LE) + param_len(1) + params."""

    opcode: int = 0
    parameters: bytes = b""

    def to_bytes(self) -> bytes:
        return struct.pack(
            "<BHB", HCI_COMMAND_PACKET, self.opcode, len(self.parameters)
        ) + self.parameters

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCICommand:
        return cls(opcode=opcode, parameters=parameters)


@dataclass
class HCIEvent(HCIPacket):
    """Generic HCI event: H4(0x04) + event_code(1) + param_len(1) + params."""

    event_code: int = 0
    parameters: bytes = b""

    def to_bytes(self) -> bytes:
        return struct.pack(
            "<BBB", HCI_EVENT_PACKET, self.event_code, len(self.parameters)
        ) + self.parameters

    @classmethod
    def from_bytes(cls, event_code: int, parameters: bytes) -> HCIEvent:
        return cls(event_code=event_code, parameters=parameters)


@dataclass
class HCIACLData(HCIPacket):
    """HCI ACL Data: H4(0x02) + handle+flags(2 LE) + data_len(2 LE) + data."""

    handle: int = 0  # 12 bits
    pb_flag: int = 0  # 2 bits
    bc_flag: int = 0  # 2 bits
    data: bytes = b""

    def to_bytes(self) -> bytes:
        handle_flags = (self.handle & 0x0FFF) | ((self.pb_flag & 0x03) << 12) | ((self.bc_flag & 0x03) << 14)
        return struct.pack(
            "<BHH", HCI_ACL_PACKET, handle_flags, len(self.data)
        ) + self.data

    @classmethod
    def from_bytes(cls, data: bytes) -> HCIACLData:
        """Decode from raw bytes (without H4 indicator)."""
        handle_flags, data_len = struct.unpack_from("<HH", data)
        handle = handle_flags & 0x0FFF
        pb_flag = (handle_flags >> 12) & 0x03
        bc_flag = (handle_flags >> 14) & 0x03
        payload = data[4 : 4 + data_len]
        return cls(handle=handle, pb_flag=pb_flag, bc_flag=bc_flag, data=payload)


@dataclass
class HCISCOData(HCIPacket):
    """HCI SCO Data: H4(0x03) + handle+status(2 LE) + data_len(1) + data."""

    handle: int = 0  # 12 bits
    packet_status: int = 0  # 2 bits
    data: bytes = b""

    def to_bytes(self) -> bytes:
        handle_flags = (self.handle & 0x0FFF) | ((self.packet_status & 0x03) << 12)
        return struct.pack(
            "<BHB", HCI_SCO_PACKET, handle_flags, len(self.data)
        ) + self.data

    @classmethod
    def from_bytes(cls, data: bytes) -> HCISCOData:
        """Decode from raw bytes (without H4 indicator)."""
        handle_flags, data_len = struct.unpack_from("<HB", data)
        handle = handle_flags & 0x0FFF
        packet_status = (handle_flags >> 12) & 0x03
        payload = data[3 : 3 + data_len]
        return cls(handle=handle, packet_status=packet_status, data=payload)


@dataclass
class HCIISOData(HCIPacket):
    """HCI ISO Data: H4(0x05) + handle+flags(2 LE) + data_len(2 LE, 14 bits) + data.

    See Bluetooth Core Spec Vol 4, Part E §5.4.5.
    """

    handle: int = 0  # 12 bits
    pb_flag: int = 0  # 2 bits
    ts_flag: int = 0  # 1 bit
    data: bytes = b""

    def to_bytes(self) -> bytes:
        handle_flags = (
            (self.handle & 0x0FFF)
            | ((self.pb_flag & 0x03) << 12)
            | ((self.ts_flag & 0x01) << 14)
        )
        data_len = len(self.data) & 0x3FFF  # 14 bits
        return struct.pack(
            "<BHH", HCI_ISO_PACKET, handle_flags, data_len
        ) + self.data

    @classmethod
    def from_bytes(cls, data: bytes) -> HCIISOData:
        """Decode from raw bytes (without H4 indicator)."""
        handle_flags, data_len_raw = struct.unpack_from("<HH", data)
        handle = handle_flags & 0x0FFF
        pb_flag = (handle_flags >> 12) & 0x03
        ts_flag = (handle_flags >> 14) & 0x01
        data_len = data_len_raw & 0x3FFF
        payload = data[4 : 4 + data_len]
        return cls(handle=handle, pb_flag=pb_flag, ts_flag=ts_flag, data=payload)


# ---------------------------------------------------------------------------
# Concrete HCI Command classes
# ---------------------------------------------------------------------------

@PacketRegistry.register_command(HCI_RESET_OPCODE)
@dataclass
class HCI_Reset(HCICommand):
    """HCI_Reset command (OGF=0x03, OCF=0x03)."""

    opcode: int = field(default=HCI_RESET_OPCODE, init=False)
    parameters: bytes = field(default=b"", init=False)

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_Reset:
        return cls()


@PacketRegistry.register_command(HCI_LE_SET_SCAN_ENABLE_OPCODE)
@dataclass
class HCI_LE_Set_Scan_Enable(HCICommand):
    """HCI_LE_Set_Scan_Enable (OGF=0x08, OCF=0x0C)."""

    opcode: int = field(default=HCI_LE_SET_SCAN_ENABLE_OPCODE, init=False)
    le_scan_enable: int = 0
    filter_duplicates: int = 0

    @property
    def parameters(self) -> bytes:  # type: ignore[override]
        return struct.pack("<BB", self.le_scan_enable, self.filter_duplicates)

    @parameters.setter
    def parameters(self, value: bytes) -> None:
        pass  # ignored — parameters are derived from fields

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_LE_Set_Scan_Enable:
        enable, dup = struct.unpack_from("<BB", parameters)
        return cls(le_scan_enable=enable, filter_duplicates=dup)


@PacketRegistry.register_command(HCI_READ_BD_ADDR)
@dataclass
class HCI_Read_BD_ADDR_Command(HCICommand):
    """HCI_Read_BD_ADDR command."""

    opcode: int = field(default=HCI_READ_BD_ADDR, init=False)
    parameters: bytes = field(default=b"", init=False)

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_Read_BD_ADDR_Command:
        return cls()


@PacketRegistry.register_command(HCI_READ_LOCAL_VERSION)
@dataclass
class HCI_Read_Local_Version_Command(HCICommand):
    """HCI_Read_Local_Version_Information command."""

    opcode: int = field(default=HCI_READ_LOCAL_VERSION, init=False)
    parameters: bytes = field(default=b"", init=False)

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_Read_Local_Version_Command:
        return cls()


@PacketRegistry.register_command(HCI_READ_BUFFER_SIZE)
@dataclass
class HCI_Read_Buffer_Size_Command(HCICommand):
    """HCI_Read_Buffer_Size command."""

    opcode: int = field(default=HCI_READ_BUFFER_SIZE, init=False)
    parameters: bytes = field(default=b"", init=False)

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_Read_Buffer_Size_Command:
        return cls()


@PacketRegistry.register_command(HCI_LE_READ_BUFFER_SIZE)
@dataclass
class HCI_LE_Read_Buffer_Size_Command(HCICommand):
    """HCI_LE_Read_Buffer_Size command."""

    opcode: int = field(default=HCI_LE_READ_BUFFER_SIZE, init=False)
    parameters: bytes = field(default=b"", init=False)

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_LE_Read_Buffer_Size_Command:
        return cls()


@PacketRegistry.register_command(HCI_READ_LOCAL_SUPPORTED_COMMANDS)
@dataclass
class HCI_Read_Local_Supported_Commands_Command(HCICommand):
    """HCI_Read_Local_Supported_Commands command."""

    opcode: int = field(default=HCI_READ_LOCAL_SUPPORTED_COMMANDS, init=False)
    parameters: bytes = field(default=b"", init=False)

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_Read_Local_Supported_Commands_Command:
        return cls()


@PacketRegistry.register_command(HCI_READ_LOCAL_SUPPORTED_FEATURES)
@dataclass
class HCI_Read_Local_Supported_Features_Command(HCICommand):
    """HCI_Read_Local_Supported_Features command."""

    opcode: int = field(default=HCI_READ_LOCAL_SUPPORTED_FEATURES, init=False)
    parameters: bytes = field(default=b"", init=False)

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_Read_Local_Supported_Features_Command:
        return cls()


@PacketRegistry.register_command(HCI_READ_LOCAL_EXTENDED_FEATURES)
@dataclass
class HCI_Read_Local_Extended_Features_Command(HCICommand):
    """HCI_Read_Local_Extended_Features command (Spec 5.4 Vol 4 Part E §7.4.4).

    Reads one 8-byte LMP features page. page_number=0 is equivalent to
    HCI_Read_Local_Supported_Features. Page 1 carries host-side bits
    (LE Supported (Host), Secure Connections (Host Support), ...). Page 2
    carries controller-side extended bits (Secure Connections (Controller), ...).
    """

    opcode: int = field(default=HCI_READ_LOCAL_EXTENDED_FEATURES, init=False)
    page_number: int = 0

    @property
    def parameters(self) -> bytes:  # type: ignore[override]
        return bytes([self.page_number & 0xFF])

    @parameters.setter
    def parameters(self, _value: bytes) -> None:  # type: ignore[override]
        pass

    @classmethod
    def from_bytes(
        cls, opcode: int, parameters: bytes
    ) -> HCI_Read_Local_Extended_Features_Command:
        page = parameters[0] if parameters else 0
        return cls(page_number=page)


@PacketRegistry.register_command(HCI_LE_READ_LOCAL_SUPPORTED_FEATURES)
@dataclass
class HCI_LE_Read_Local_Supported_Features_Command(HCICommand):
    """HCI_LE_Read_Local_P_Supported_Features command."""

    opcode: int = field(default=HCI_LE_READ_LOCAL_SUPPORTED_FEATURES, init=False)
    parameters: bytes = field(default=b"", init=False)

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_LE_Read_Local_Supported_Features_Command:
        return cls()


@PacketRegistry.register_command(HCI_LE_READ_LOCAL_SUPPORTED_FEATURES_PAGE)
@dataclass
class HCI_LE_Read_Local_Supported_Features_Page_Command(HCICommand):
    """HCI_LE_Read_Local_Supported_Features_Page command (Spec 6.0 era).

    Reads one 8-byte LE features page beyond the original 64-bit
    HCI_LE_Read_Local_Supported_Features bitmap. page_number=0 is
    equivalent to the non-paged read; page 1+ are 6.0 extension bits.

    Response payload (best-effort interpretation, mirrors BR/EDR
    Read_Local_Extended_Features layout):
        status(1) + page_number(1) + max_page_number(1) + features(8)

    No Spec 5.4 controller supports this; HCIController gates the call
    on Supported_Commands.has(opcode) so it's only sent to 6.0 adapters.
    """

    opcode: int = field(default=HCI_LE_READ_LOCAL_SUPPORTED_FEATURES_PAGE, init=False)
    page_number: int = 0

    @property
    def parameters(self) -> bytes:  # type: ignore[override]
        return bytes([self.page_number & 0xFF])

    @parameters.setter
    def parameters(self, _value: bytes) -> None:  # type: ignore[override]
        pass

    @classmethod
    def from_bytes(
        cls, opcode: int, parameters: bytes
    ) -> HCI_LE_Read_Local_Supported_Features_Page_Command:
        page = parameters[0] if parameters else 0
        return cls(page_number=page)


@PacketRegistry.register_command(HCI_SET_EVENT_MASK)
@dataclass
class HCI_Set_Event_Mask_Command(HCICommand):
    """HCI_Set_Event_Mask command."""

    opcode: int = field(default=HCI_SET_EVENT_MASK, init=False)
    event_mask: bytes = field(default=b"\x00" * 8)

    @property
    def parameters(self) -> bytes:  # type: ignore[override]
        return self.event_mask

    @parameters.setter
    def parameters(self, value: bytes) -> None:
        pass

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_Set_Event_Mask_Command:
        return cls(event_mask=parameters[:8])


@PacketRegistry.register_command(HCI_LE_SET_EVENT_MASK)
@dataclass
class HCI_LE_Set_Event_Mask_Command(HCICommand):
    """HCI_LE_Set_Event_Mask command."""

    opcode: int = field(default=HCI_LE_SET_EVENT_MASK, init=False)
    le_event_mask: bytes = field(default=b"\x00" * 8)

    @property
    def parameters(self) -> bytes:  # type: ignore[override]
        return self.le_event_mask

    @parameters.setter
    def parameters(self, value: bytes) -> None:
        pass

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_LE_Set_Event_Mask_Command:
        return cls(le_event_mask=parameters[:8])


@PacketRegistry.register_command(HCI_WRITE_LE_HOST_SUPPORTED)
@dataclass
class HCI_Write_LE_Host_Supported_Command(HCICommand):
    """HCI_Write_LE_Host_Supported command."""

    opcode: int = field(default=HCI_WRITE_LE_HOST_SUPPORTED, init=False)
    le_supported_host: int = 0
    simultaneous_le_host: int = 0

    @property
    def parameters(self) -> bytes:  # type: ignore[override]
        return struct.pack("<BB", self.le_supported_host, self.simultaneous_le_host)

    @parameters.setter
    def parameters(self, value: bytes) -> None:
        pass

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_Write_LE_Host_Supported_Command:
        le_sup, sim = struct.unpack_from("<BB", parameters)
        return cls(le_supported_host=le_sup, simultaneous_le_host=sim)


@PacketRegistry.register_command(HCI_WRITE_SIMPLE_PAIRING_MODE)
@dataclass
class HCI_Write_Simple_Pairing_Mode_Command(HCICommand):
    """HCI_Write_Simple_Pairing_Mode command."""

    opcode: int = field(default=HCI_WRITE_SIMPLE_PAIRING_MODE, init=False)
    simple_pairing_mode: int = 0

    @property
    def parameters(self) -> bytes:  # type: ignore[override]
        return struct.pack("<B", self.simple_pairing_mode)

    @parameters.setter
    def parameters(self, value: bytes) -> None:
        pass

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_Write_Simple_Pairing_Mode_Command:
        return cls(simple_pairing_mode=parameters[0])


@PacketRegistry.register_command(HCI_WRITE_SCAN_ENABLE)
@dataclass
class HCI_Write_Scan_Enable_Command(HCICommand):
    """HCI_Write_Scan_Enable command."""

    opcode: int = field(default=HCI_WRITE_SCAN_ENABLE, init=False)
    scan_enable: int = 0

    @property
    def parameters(self) -> bytes:  # type: ignore[override]
        return struct.pack("<B", self.scan_enable)

    @parameters.setter
    def parameters(self, value: bytes) -> None:
        pass

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_Write_Scan_Enable_Command:
        return cls(scan_enable=parameters[0])


@PacketRegistry.register_command(HCI_HOST_BUFFER_SIZE)
@dataclass
class HCI_Host_Buffer_Size_Command(HCICommand):
    """HCI_Host_Buffer_Size command."""

    opcode: int = field(default=HCI_HOST_BUFFER_SIZE, init=False)
    host_acl_data_packet_length: int = 0
    host_synchronous_data_packet_length: int = 0
    host_total_num_acl_data_packets: int = 0
    host_total_num_synchronous_data_packets: int = 0

    @property
    def parameters(self) -> bytes:  # type: ignore[override]
        return struct.pack(
            "<HBHH",
            self.host_acl_data_packet_length,
            self.host_synchronous_data_packet_length,
            self.host_total_num_acl_data_packets,
            self.host_total_num_synchronous_data_packets,
        )

    @parameters.setter
    def parameters(self, value: bytes) -> None:
        pass

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_Host_Buffer_Size_Command:
        acl_len, sco_len, acl_num, sco_num = struct.unpack_from("<HBHH", parameters)
        return cls(
            host_acl_data_packet_length=acl_len,
            host_synchronous_data_packet_length=sco_len,
            host_total_num_acl_data_packets=acl_num,
            host_total_num_synchronous_data_packets=sco_num,
        )


@PacketRegistry.register_command(HCI_LE_SET_SCAN_PARAMS)
@dataclass
class HCI_LE_Set_Scan_Parameters_Command(HCICommand):
    """HCI_LE_Set_Scan_Parameters command."""

    opcode: int = field(default=HCI_LE_SET_SCAN_PARAMS, init=False)
    le_scan_type: int = 0
    le_scan_interval: int = 0
    le_scan_window: int = 0
    own_address_type: int = 0
    scanning_filter_policy: int = 0

    @property
    def parameters(self) -> bytes:  # type: ignore[override]
        return struct.pack(
            "<BHHBB",
            self.le_scan_type,
            self.le_scan_interval,
            self.le_scan_window,
            self.own_address_type,
            self.scanning_filter_policy,
        )

    @parameters.setter
    def parameters(self, value: bytes) -> None:
        pass

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_LE_Set_Scan_Parameters_Command:
        scan_type, interval, window, addr_type, policy = struct.unpack_from("<BHHBB", parameters)
        return cls(
            le_scan_type=scan_type,
            le_scan_interval=interval,
            le_scan_window=window,
            own_address_type=addr_type,
            scanning_filter_policy=policy,
        )


@PacketRegistry.register_command(HCI_LE_SET_RANDOM_ADDRESS)
@dataclass
class HCI_LE_Set_Random_Address_Command(HCICommand):
    """HCI_LE_Set_Random_Address command."""

    opcode: int = field(default=HCI_LE_SET_RANDOM_ADDRESS, init=False)
    random_address: bytes = field(default=b"\x00" * 6)

    @property
    def parameters(self) -> bytes:  # type: ignore[override]
        return self.random_address

    @parameters.setter
    def parameters(self, value: bytes) -> None:
        pass

    @classmethod
    def from_bytes(cls, opcode: int, parameters: bytes) -> HCI_LE_Set_Random_Address_Command:
        return cls(random_address=parameters[:6])


@PacketRegistry.register_command(HCI_LE_START_ENCRYPTION)
@dataclass
class HCI_LE_Start_Encryption_Command(HCICommand):
    """HCI_LE_Start_Encryption (Vol 4 Part E §7.8.24)."""

    connection_handle: int = 0
    random_number: bytes = field(default_factory=lambda: bytes(8))
    encrypted_diversifier: int = 0
    long_term_key: bytes = field(default_factory=lambda: bytes(16))
    opcode: int = field(default=HCI_LE_START_ENCRYPTION)

    def __post_init__(self) -> None:
        if len(self.random_number) != 8:
            raise ValueError(f"random_number must be 8 bytes, got {len(self.random_number)}")
        if len(self.long_term_key) != 16:
            raise ValueError(f"long_term_key must be 16 bytes, got {len(self.long_term_key)}")
        self.parameters = (
            struct.pack("<H", self.connection_handle)
            + self.random_number
            + struct.pack("<H", self.encrypted_diversifier)
            + self.long_term_key
        )


@PacketRegistry.register_command(HCI_LE_LONG_TERM_KEY_REQUEST_REPLY)
@dataclass
class HCI_LE_LTK_Request_Reply_Command(HCICommand):
    """HCI_LE_Long_Term_Key_Request_Reply (Vol 4 Part E §7.8.25)."""

    connection_handle: int = 0
    long_term_key: bytes = field(default_factory=lambda: bytes(16))
    opcode: int = field(default=HCI_LE_LONG_TERM_KEY_REQUEST_REPLY)

    def __post_init__(self) -> None:
        if len(self.long_term_key) != 16:
            raise ValueError("long_term_key must be 16 bytes")
        self.parameters = (
            struct.pack("<H", self.connection_handle) + self.long_term_key
        )


@PacketRegistry.register_command(HCI_LE_LONG_TERM_KEY_REQUEST_NEGATIVE_REPLY)
@dataclass
class HCI_LE_LTK_Request_Negative_Reply_Command(HCICommand):
    """HCI_LE_Long_Term_Key_Request_Negative_Reply (Vol 4 Part E §7.8.26)."""

    connection_handle: int = 0
    opcode: int = field(default=HCI_LE_LONG_TERM_KEY_REQUEST_NEGATIVE_REPLY)

    def __post_init__(self) -> None:
        self.parameters = struct.pack("<H", self.connection_handle)


@PacketRegistry.register_command(HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT)
@dataclass
class HCI_Write_Secure_Connections_Host_Support_Command(HCICommand):
    """HCI_Write_Secure_Connections_Host_Support (Core 5.4 Vol 4 Part E §7.3.92)."""

    secure_connections_host_support: int = 0
    opcode: int = field(default=HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT)

    def __post_init__(self) -> None:
        self.parameters = bytes([self.secure_connections_host_support])


@PacketRegistry.register_command(HCI_LINK_KEY_REQUEST_REPLY)
@dataclass
class HCI_Link_Key_Request_Reply_Command(HCICommand):
    """HCI_Link_Key_Request_Reply (Core 5.4 Vol 4 Part E §7.1.10)."""

    bd_addr: "BDAddress | None" = None
    link_key: bytes = field(default_factory=lambda: bytes(16))
    opcode: int = field(default=HCI_LINK_KEY_REQUEST_REPLY)

    def __post_init__(self) -> None:
        if self.bd_addr is None:
            raise ValueError("bd_addr is required")
        if len(self.link_key) != 16:
            raise ValueError("link_key must be 16 bytes")
        # BT wire is little-endian; BDAddress.address is big-endian
        self.parameters = bytes(self.bd_addr.address[::-1]) + self.link_key


# ---------------------------------------------------------------------------
# Concrete HCI Event classes
# ---------------------------------------------------------------------------

@PacketRegistry.register_event(EventCode.COMMAND_COMPLETE)
@dataclass
class HCI_Command_Complete_Event(HCIEvent):
    """HCI Command Complete Event (0x0E)."""

    event_code: int = field(default=int(EventCode.COMMAND_COMPLETE), init=False)
    num_hci_command_packets: int = 0
    command_opcode: int = 0
    return_parameters: bytes = b""

    @property
    def parameters(self) -> bytes:  # type: ignore[override]
        return struct.pack(
            "<BH", self.num_hci_command_packets, self.command_opcode
        ) + self.return_parameters

    @parameters.setter
    def parameters(self, value: bytes) -> None:
        pass

    @classmethod
    def from_bytes(cls, event_code: int, parameters: bytes) -> HCI_Command_Complete_Event:
        num_cmds = parameters[0]
        opcode = struct.unpack_from("<H", parameters, 1)[0]
        return_params = parameters[3:]
        return cls(
            num_hci_command_packets=num_cmds,
            command_opcode=opcode,
            return_parameters=return_params,
        )


@PacketRegistry.register_event(EventCode.COMMAND_STATUS)
@dataclass
class HCI_Command_Status_Event(HCIEvent):
    """HCI Command Status Event (0x0F)."""

    event_code: int = field(default=int(EventCode.COMMAND_STATUS), init=False)
    status: int = 0
    num_hci_command_packets: int = 0
    command_opcode: int = 0

    @property
    def parameters(self) -> bytes:  # type: ignore[override]
        return struct.pack(
            "<BBH", self.status, self.num_hci_command_packets, self.command_opcode
        )

    @parameters.setter
    def parameters(self, value: bytes) -> None:
        pass

    @classmethod
    def from_bytes(cls, event_code: int, parameters: bytes) -> HCI_Command_Status_Event:
        status, num_cmds = parameters[0], parameters[1]
        opcode = struct.unpack_from("<H", parameters, 2)[0]
        return cls(status=status, num_hci_command_packets=num_cmds, command_opcode=opcode)


@PacketRegistry.register_event(EventCode.CONNECTION_COMPLETE)
@dataclass
class HCI_Connection_Complete_Event(HCIEvent):
    """HCI Connection Complete Event (0x03)."""

    event_code: int = field(default=int(EventCode.CONNECTION_COMPLETE), init=False)
    status: int = 0
    connection_handle: int = 0
    bd_addr: bytes = field(default=b"\x00" * 6)
    link_type: int = 0
    encryption_enabled: int = 0

    @classmethod
    def from_bytes(cls, event_code: int, parameters: bytes) -> HCI_Connection_Complete_Event:
        status = parameters[0]
        handle = struct.unpack_from("<H", parameters, 1)[0]
        addr = parameters[3:9]
        link_type = parameters[9] if len(parameters) > 9 else 0
        encryption = parameters[10] if len(parameters) > 10 else 0
        return cls(
            status=status, connection_handle=handle, bd_addr=addr,
            link_type=link_type, encryption_enabled=encryption,
        )


@PacketRegistry.register_event(EventCode.DISCONNECTION_COMPLETE)
@dataclass
class HCI_Disconnection_Complete_Event(HCIEvent):
    """HCI Disconnection Complete Event (0x05)."""

    event_code: int = field(default=int(EventCode.DISCONNECTION_COMPLETE), init=False)
    status: int = 0
    connection_handle: int = 0
    reason: int = 0

    @classmethod
    def from_bytes(cls, event_code: int, parameters: bytes) -> HCI_Disconnection_Complete_Event:
        status = parameters[0]
        handle = struct.unpack_from("<H", parameters, 1)[0]
        reason = parameters[3]
        return cls(status=status, connection_handle=handle, reason=reason)


@PacketRegistry.register_event(EventCode.NUM_COMPLETED_PACKETS)
@dataclass
class HCI_Number_Of_Completed_Packets_Event(HCIEvent):
    """HCI Number Of Completed Packets Event (0x13)."""

    event_code: int = field(default=int(EventCode.NUM_COMPLETED_PACKETS), init=False)
    completed: dict[int, int] = field(default_factory=dict)  # handle → count

    @classmethod
    def from_bytes(cls, event_code: int, parameters: bytes) -> HCI_Number_Of_Completed_Packets_Event:
        num_handles = parameters[0]
        completed: dict[int, int] = {}
        offset = 1
        for _ in range(num_handles):
            handle = struct.unpack_from("<H", parameters, offset)[0]
            count = struct.unpack_from("<H", parameters, offset + 2)[0]
            completed[handle] = count
            offset += 4
        return cls(completed=completed)


@PacketRegistry.register_event(EventCode.LE_META)
@dataclass
class HCI_LE_Meta_Event(HCIEvent):
    """HCI LE Meta Event (0x3E) — wraps a sub-event."""

    event_code: int = field(default=int(EventCode.LE_META), init=False)
    subevent_code: int = 0
    subevent_parameters: bytes = b""

    @classmethod
    def from_bytes(cls, event_code: int, parameters: bytes) -> HCI_LE_Meta_Event:
        subevent_code = parameters[0]
        subevent_params = parameters[1:]
        return cls(subevent_code=subevent_code, subevent_parameters=subevent_params)


# ---------------------------------------------------------------------------
# LE Advertising Report helper
# ---------------------------------------------------------------------------

@dataclass
class LEAdvertisingReport:
    """One entry from an LE Advertising Report sub-event (Vol 4, Part E §7.7.65.2)."""

    event_type: int           # 0=ADV_IND, 1=ADV_DIRECT_IND, 2=ADV_SCAN_IND, 3=ADV_NONCONN_IND, 4=SCAN_RSP
    address_type: int         # 0=public, 1=random
    address: bytes            # 6 bytes, raw HCI (little-endian) order
    data: bytes               # advertising/scan-response data
    rssi: int                 # signed dBm, 127 = not available


def parse_le_advertising_reports(subevent_parameters: bytes) -> list[LEAdvertisingReport]:
    """Parse the body of an LE Advertising Report sub-event into per-report entries.

    Layout: ``num_reports`` followed by N back-to-back
    ``(event_type, address_type, address[6], data_length, data, rssi)`` tuples.
    Returns an empty list on truncated input rather than raising — controllers
    occasionally emit malformed reports.
    """
    if not subevent_parameters:
        return []
    num_reports = subevent_parameters[0]
    offset = 1
    reports: list[LEAdvertisingReport] = []
    for _ in range(num_reports):
        if offset + 9 > len(subevent_parameters):
            break
        event_type = subevent_parameters[offset]
        address_type = subevent_parameters[offset + 1]
        address = bytes(subevent_parameters[offset + 2:offset + 8])
        data_len = subevent_parameters[offset + 8]
        offset += 9
        if offset + data_len + 1 > len(subevent_parameters):
            break
        data = bytes(subevent_parameters[offset:offset + data_len])
        rssi = struct.unpack_from("<b", subevent_parameters, offset + data_len)[0]
        offset += data_len + 1
        reports.append(LEAdvertisingReport(
            event_type=event_type,
            address_type=address_type,
            address=address,
            data=data,
            rssi=rssi,
        ))
    return reports


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------

def decode_hci_packet(data: bytes) -> HCIPacket:
    """Decode raw H4+HCI bytes into a typed HCIPacket subclass."""
    if not data:
        raise ValueError("Empty packet data")

    packet_type = data[0]

    if packet_type == HCI_COMMAND_PACKET:
        opcode = struct.unpack_from("<H", data, 1)[0]
        param_len = data[3]
        parameters = data[4 : 4 + param_len]
        klass = PacketRegistry.get_command_class(opcode)
        if klass is not None:
            return klass.from_bytes(opcode, parameters)
        return HCICommand(opcode=opcode, parameters=parameters)

    if packet_type == HCI_EVENT_PACKET:
        event_code = data[1]
        param_len = data[2]
        parameters = data[3 : 3 + param_len]
        klass = PacketRegistry.get_event_class(event_code)
        if klass is not None:
            return klass.from_bytes(event_code, parameters)
        return HCIEvent(event_code=event_code, parameters=parameters)

    if packet_type == HCI_ACL_PACKET:
        return HCIACLData.from_bytes(data[1:])

    if packet_type == HCI_SCO_PACKET:
        return HCISCOData.from_bytes(data[1:])

    if packet_type == HCI_ISO_PACKET:
        return HCIISOData.from_bytes(data[1:])

    raise ValueError(f"Unknown H4 packet type: 0x{packet_type:02X}")
