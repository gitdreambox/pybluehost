"""Tests for VirtualController remote-information command handling."""
from __future__ import annotations

import asyncio
import struct

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    ErrorCode,
    EventCode,
    HCI_COMMAND_PACKET,
    HCI_READ_REMOTE_EXTENDED_FEATURES,
    HCI_READ_REMOTE_SUPPORTED_FEATURES,
    HCI_READ_REMOTE_VERSION_INFORMATION,
    HCI_REMOTE_NAME_REQUEST,
)
from pybluehost.hci.packets import HCI_Command_Status_Event, HCICommand, decode_hci_packet
from pybluehost.hci.virtual import VirtualController

LOCAL_ADDRESS = BDAddress.from_string("AA:BB:CC:DD:EE:01")
PEER = BDAddress.from_string("1A:8D:8D:1B:F5:6B")

# Generous compared with the one event-loop turn the emitter needs; a failure
# here means no event was emitted at all, not that the loop was slow.
EVENT_TIMEOUT = 0.5

OPCODES = [
    HCI_REMOTE_NAME_REQUEST,
    HCI_READ_REMOTE_SUPPORTED_FEATURES,
    HCI_READ_REMOTE_EXTENDED_FEATURES,
    HCI_READ_REMOTE_VERSION_INFORMATION,
]
OPCODE_IDS = ["remote-name", "supported-features", "extended-features", "version"]

# Well-formed request bodies, per command.
WELL_FORMED_BODIES = {
    HCI_REMOTE_NAME_REQUEST: PEER.to_hci() + bytes([0x01, 0x00, 0x00, 0x00]),
    HCI_READ_REMOTE_SUPPORTED_FEATURES: struct.pack("<H", 0x0042),
    HCI_READ_REMOTE_EXTENDED_FEATURES: struct.pack("<HB", 0x0042, 1),
    HCI_READ_REMOTE_VERSION_INFORMATION: struct.pack("<H", 0x0042),
}

# Bodies shorter than the command requires, one octet short of the guard.
SHORT_BODIES = {
    HCI_REMOTE_NAME_REQUEST: PEER.to_hci()[:-1],
    HCI_READ_REMOTE_SUPPORTED_FEATURES: b"\x42",
    HCI_READ_REMOTE_EXTENDED_FEATURES: b"\x42",
    HCI_READ_REMOTE_VERSION_INFORMATION: b"\x42",
}

COMPLETION_EVENTS = {
    HCI_REMOTE_NAME_REQUEST: EventCode.REMOTE_NAME_REQUEST_COMPLETE,
    HCI_READ_REMOTE_SUPPORTED_FEATURES: EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE,
    HCI_READ_REMOTE_EXTENDED_FEATURES: EventCode.READ_REMOTE_EXTENDED_FEATURES_COMPLETE,
    HCI_READ_REMOTE_VERSION_INFORMATION: EventCode.READ_REMOTE_VERSION_COMPLETE,
}


class CapturingSink:
    """Records host-bound events and signals the first one."""

    def __init__(self) -> None:
        self.events: list[bytes] = []
        self.received = asyncio.Event()

    async def on_transport_data(self, data: bytes) -> None:
        self.events.append(data)
        self.received.set()


def make_controller() -> tuple[VirtualController, CapturingSink]:
    controller = VirtualController(LOCAL_ADDRESS)
    sink = CapturingSink()
    controller._host_sink = sink
    return controller, sink


async def wait_for_event(sink: CapturingSink) -> None:
    """Wait until at least one event reached the sink."""
    try:
        await asyncio.wait_for(sink.received.wait(), EVENT_TIMEOUT)
    except asyncio.TimeoutError:
        raise AssertionError(
            f"no event reached the host within {EVENT_TIMEOUT}s"
        ) from None


async def wait_for_events(sink: CapturingSink, count: int) -> None:
    """Wait until at least *count* events reached the sink."""
    async def until_count() -> None:
        while len(sink.events) < count:
            await asyncio.sleep(0)

    try:
        await asyncio.wait_for(until_count(), EVENT_TIMEOUT)
    except asyncio.TimeoutError:
        raise AssertionError(
            f"expected {count} events within {EVENT_TIMEOUT}s, saw "
            f"{len(sink.events)}: {[raw.hex() for raw in sink.events]}"
        ) from None


async def assert_no_event(sink: CapturingSink) -> None:
    """Give scheduled emitters a bounded window, then assert nothing arrived."""
    await asyncio.sleep(0.05)
    assert sink.events == [], f"unexpected events: {[raw.hex() for raw in sink.events]}"


def decode_completion(sink: CapturingSink):
    assert len(sink.events) == 1, [raw.hex() for raw in sink.events]
    return decode_hci_packet(sink.events[0])


@pytest.mark.parametrize("opcode", OPCODES, ids=OPCODE_IDS)
async def test_virtual_controller_replies_with_command_status(opcode):
    controller, sink = make_controller()
    command = HCICommand(opcode=opcode, parameters=WELL_FORMED_BODIES[opcode])
    reply = decode_hci_packet(await controller.process(command.to_bytes()))
    assert isinstance(reply, HCI_Command_Status_Event)
    assert reply.status == 0
    assert reply.command_opcode == opcode
    await wait_for_event(sink)
    assert len(sink.events) == 1
    assert decode_hci_packet(sink.events[0]).event_code == int(COMPLETION_EVENTS[opcode])


@pytest.mark.parametrize("opcode", OPCODES, ids=OPCODE_IDS)
async def test_virtual_controller_rejects_short_body(opcode):
    controller, sink = make_controller()
    command = HCICommand(opcode=opcode, parameters=SHORT_BODIES[opcode])
    reply = decode_hci_packet(await controller.process(command.to_bytes()))
    assert isinstance(reply, HCI_Command_Status_Event)
    assert reply.status == ErrorCode.INVALID_PARAMETERS
    assert reply.command_opcode == opcode
    await assert_no_event(sink)


async def test_virtual_controller_guards_on_the_payload_not_the_declared_length():
    """A frame declaring more octets than it carries must not fake a completion."""
    controller, sink = make_controller()
    carried = PEER.to_hci()[:3]
    frame = (
        bytes([HCI_COMMAND_PACKET])
        + struct.pack("<H", HCI_REMOTE_NAME_REQUEST)
        + bytes([10])  # declares the full 10-octet request body
        + carried
    )
    reply = decode_hci_packet(await controller.process(frame))
    assert isinstance(reply, HCI_Command_Status_Event)
    assert reply.status == ErrorCode.INVALID_PARAMETERS
    await assert_no_event(sink)


async def test_virtual_controller_rejects_six_octet_remote_name_request_body():
    """BD_ADDR alone (6 octets) is not a complete Remote_Name_Request."""
    controller, sink = make_controller()
    command = HCICommand(
        opcode=HCI_REMOTE_NAME_REQUEST,
        parameters=PEER.to_hci(),
    )
    reply = decode_hci_packet(await controller.process(command.to_bytes()))
    assert isinstance(reply, HCI_Command_Status_Event)
    assert reply.status == ErrorCode.INVALID_PARAMETERS
    assert reply.command_opcode == HCI_REMOTE_NAME_REQUEST
    await assert_no_event(sink)


async def test_virtual_controller_rejects_two_octet_extended_features_body():
    """Handle alone (2 octets) is not a complete Read_Remote_Extended_Features."""
    controller, sink = make_controller()
    command = HCICommand(
        opcode=HCI_READ_REMOTE_EXTENDED_FEATURES,
        parameters=struct.pack("<H", 0x0042),
    )
    reply = decode_hci_packet(await controller.process(command.to_bytes()))
    assert isinstance(reply, HCI_Command_Status_Event)
    assert reply.status == ErrorCode.INVALID_PARAMETERS
    assert reply.command_opcode == HCI_READ_REMOTE_EXTENDED_FEATURES
    await assert_no_event(sink)


async def test_command_status_reaches_the_host_before_the_completion_event():
    """Through a real pipe, the status reply is observed ahead of the completion."""
    _, host_t = await VirtualController.create(LOCAL_ADDRESS)
    sink = CapturingSink()
    host_t.set_sink(sink)
    command = HCICommand(
        opcode=HCI_READ_REMOTE_SUPPORTED_FEATURES,
        parameters=WELL_FORMED_BODIES[HCI_READ_REMOTE_SUPPORTED_FEATURES],
    )
    await host_t.send(command.to_bytes())
    await wait_for_events(sink, 2)
    assert [decode_hci_packet(raw).event_code for raw in sink.events] == [
        int(EventCode.COMMAND_STATUS),
        int(EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE),
    ]


async def test_virtual_controller_emits_remote_name_request_complete():
    controller, sink = make_controller()
    command = HCICommand(
        opcode=HCI_REMOTE_NAME_REQUEST,
        parameters=WELL_FORMED_BODIES[HCI_REMOTE_NAME_REQUEST],
    )
    assert (await controller.process(command.to_bytes())) is not None
    await wait_for_event(sink)
    event = decode_completion(sink)
    assert event.event_code == int(EventCode.REMOTE_NAME_REQUEST_COMPLETE)
    assert event.parameters[0] == 0
    assert event.parameters[1:7] == PEER.to_hci()
    assert event.parameters[7:].rstrip(b"\x00") == b"Virtual Peer"


async def test_virtual_controller_emits_remote_supported_features_complete():
    controller, sink = make_controller()
    command = HCICommand(
        opcode=HCI_READ_REMOTE_SUPPORTED_FEATURES,
        parameters=struct.pack("<H", 0x0042),
    )
    await controller.process(command.to_bytes())
    await wait_for_event(sink)
    event = decode_completion(sink)
    assert event.event_code == int(EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE)
    assert event.parameters[0] == 0
    assert struct.unpack_from("<H", event.parameters, 1)[0] == 0x0042
    assert len(event.parameters) == 11


async def test_virtual_controller_emits_remote_extended_features_complete():
    controller, sink = make_controller()
    command = HCICommand(
        opcode=HCI_READ_REMOTE_EXTENDED_FEATURES,
        parameters=struct.pack("<HB", 0x0042, 1),
    )
    await controller.process(command.to_bytes())
    await wait_for_event(sink)
    event = decode_completion(sink)
    assert event.event_code == int(EventCode.READ_REMOTE_EXTENDED_FEATURES_COMPLETE)
    assert event.parameters[0] == 0
    assert struct.unpack_from("<H", event.parameters, 1)[0] == 0x0042
    assert event.parameters[3:5] == b"\x01\x02"
    assert len(event.parameters) == 13


async def test_virtual_controller_emits_remote_version_information_complete():
    controller, sink = make_controller()
    command = HCICommand(
        opcode=HCI_READ_REMOTE_VERSION_INFORMATION,
        parameters=struct.pack("<H", 0x0042),
    )
    await controller.process(command.to_bytes())
    await wait_for_event(sink)
    event = decode_completion(sink)
    assert event.event_code == int(EventCode.READ_REMOTE_VERSION_COMPLETE)
    assert event.parameters[0] == 0
    assert struct.unpack_from("<H", event.parameters, 1)[0] == 0x0042
    assert struct.unpack_from("<BHH", event.parameters, 3) == (0x0C, 0x0002, 0x0001)
