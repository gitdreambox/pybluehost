"""HCI packet encode/decode: commands, events, ACL, SCO, ISO data.

Provides a `decode_hci_packet()` dispatcher and a `PacketRegistry` that maps
(packet_type, opcode/event_code) → concrete class for automatic decoding.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import ClassVar

from pybluehost.hci.constants import (
    HCI_ACL_PACKET,
    HCI_COMMAND_PACKET,
    HCI_EVENT_PACKET,
    HCI_ISO_PACKET,
    HCI_RESET as HCI_RESET_OPCODE,
    HCI_SCO_PACKET,
    HCI_LE_SET_SCAN_ENABLE as HCI_LE_SET_SCAN_ENABLE_OPCODE,
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
