"""Tests for HCIController and ConnectionManager."""

from __future__ import annotations

import asyncio
import struct

import pytest

from pybluehost.core.errors import CommandTimeoutError
from pybluehost.hci.constants import (
    HCI_ACL_PACKET,
    HCI_EVENT_PACKET,
    HCI_READ_BUFFER_SIZE,
    HCI_RESET,
    EventCode,
)
from pybluehost.hci.controller import ConnectionManager, HCIConnection, HCIController
from pybluehost.hci.packets import (
    HCI_Command_Complete_Event,
    HCI_Reset,
    HCIACLData,
)
from pybluehost.core.trace import TraceSystem


# ---------------------------------------------------------------------------
# Fake transport for testing
# ---------------------------------------------------------------------------

class FakeTransport:
    """Minimal transport that records sent bytes and allows injecting data."""

    def __init__(self) -> None:
        self._sink = None
        self.sent: list[bytes] = []
        self._open = True

    def set_sink(self, sink) -> None:
        self._sink = sink

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def inject(self, data: bytes) -> None:
        """Push raw HCI bytes into the controller as if received from HW."""
        if self._sink:
            await self._sink.on_transport_data(data)

    @property
    def is_open(self) -> bool:
        return self._open


# ---------------------------------------------------------------------------
# Helper: build a raw Command Complete event (with H4 header)
# ---------------------------------------------------------------------------

def build_command_complete(opcode: int, status: int = 0x00, return_params: bytes = b"") -> bytes:
    """Build raw H4 + HCI Command Complete event bytes."""
    num_cmds = 1
    params = struct.pack("<BH", num_cmds, opcode) + bytes([status]) + return_params
    header = struct.pack("<BBB", HCI_EVENT_PACKET, EventCode.COMMAND_COMPLETE, len(params))
    return header + params


# ---------------------------------------------------------------------------
# Async tests
# ---------------------------------------------------------------------------

async def test_send_command_awaits_complete():
    """send_command should return the Command Complete event."""
    transport = FakeTransport()
    ctrl = HCIController(transport, command_timeout=2.0)

    cmd = HCI_Reset()

    async def inject_response():
        # Give send_command time to actually send and register
        await asyncio.sleep(0.01)
        raw_event = build_command_complete(HCI_RESET, status=0x00)
        await transport.inject(raw_event)

    task = asyncio.ensure_future(inject_response())
    event = await ctrl.send_command(cmd)
    await task

    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.command_opcode == HCI_RESET
    assert len(transport.sent) == 1  # command was sent


async def test_acl_data_routed_to_upstream():
    """Injected ACL data should be delivered to the upstream callback."""
    transport = FakeTransport()
    ctrl = HCIController(transport)

    received: list[HCIACLData] = []

    def on_acl(pkt: HCIACLData) -> None:
        received.append(pkt)

    ctrl.set_upstream(on_acl_data=on_acl)

    # Build raw ACL packet: H4(0x02) + handle_flags(2) + length(2) + data
    acl = HCIACLData(handle=0x0040, pb_flag=0x02, data=b"\x01\x02\x03")
    await transport.inject(acl.to_bytes())

    assert len(received) == 1
    assert received[0].handle == 0x0040
    assert received[0].data == b"\x01\x02\x03"


async def test_send_command_timeout():
    """send_command should raise CommandTimeoutError when no response arrives."""
    transport = FakeTransport()
    ctrl = HCIController(transport, command_timeout=0.05)

    cmd = HCI_Reset()
    with pytest.raises(CommandTimeoutError):
        await ctrl.send_command(cmd)


def test_configure_acl_flow_from_read_buffer_size_complete():
    transport = FakeTransport()
    ctrl = HCIController(transport)
    event = HCI_Command_Complete_Event(
        num_hci_command_packets=1,
        command_opcode=HCI_READ_BUFFER_SIZE,
        return_parameters=b"\x00" + struct.pack("<HBHH", 0x0136, 0x40, 10, 0),
    )

    ctrl._configure_acl_flow_from_command_complete(event)

    assert ctrl._acl_flow.buffer_size == 0x0136
    assert ctrl._acl_flow.available == 10


# ---------------------------------------------------------------------------
# Sync ConnectionManager tests
# ---------------------------------------------------------------------------

def test_connection_manager_track_new_le_connection():
    cm = ConnectionManager()
    conn = HCIConnection(handle=0x0040, bd_addr=b"\x01\x02\x03\x04\x05\x06", link_type=0x03)
    cm.add(conn)
    assert cm.get(0x0040) is conn


def test_connection_manager_track_disconnection():
    cm = ConnectionManager()
    conn = HCIConnection(handle=0x0040, bd_addr=b"\x01\x02\x03\x04\x05\x06")
    cm.add(conn)
    removed = cm.remove(0x0040)
    assert removed is conn
    assert cm.get(0x0040) is None


def test_connection_manager_lookup_by_handle():
    cm = ConnectionManager()
    c1 = HCIConnection(handle=0x0001, bd_addr=b"\x11" * 6)
    c2 = HCIConnection(handle=0x0002, bd_addr=b"\x22" * 6)
    cm.add(c1)
    cm.add(c2)
    assert cm.get(0x0001) is c1
    assert cm.get(0x0002) is c2
    assert cm.get(0x9999) is None


def test_connection_manager_all_connections():
    cm = ConnectionManager()
    c1 = HCIConnection(handle=0x0001, bd_addr=b"\x11" * 6)
    c2 = HCIConnection(handle=0x0002, bd_addr=b"\x22" * 6)
    cm.add(c1)
    cm.add(c2)
    all_conns = cm.all()
    assert len(all_conns) == 2
    assert c1 in all_conns
    assert c2 in all_conns


def test_connection_manager_disconnect_missing_handle_returns_none():
    cm = ConnectionManager()
    assert cm.remove(0xFFFF) is None
