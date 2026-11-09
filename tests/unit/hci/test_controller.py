"""Tests for HCIController and ConnectionManager."""

from __future__ import annotations

import asyncio
import struct

import pytest

from pybluehost.core.errors import CommandTimeoutError
from pybluehost.hci.constants import (
    HCI_ACL_PACKET,
    HCI_EVENT_PACKET,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_READ_BUFFER_SIZE,
    HCI_RESET,
    EventCode,
    LEMetaSubEvent,
)
from pybluehost.hci.controller import (
    LINK_TYPE_ACL,
    LINK_TYPE_LE,
    ConnectionManager,
    HCIConnection,
    HCIController,
)
from pybluehost.hci.packets import (
    HCI_Command_Complete_Event,
    HCI_LE_Meta_Event,
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


async def test_async_encryption_listener_does_not_block_acl_credit_events():
    transport = FakeTransport()
    ctrl = HCIController(transport)
    ctrl._acl_flow.configure(num_buffers=1, buffer_size=251)

    await ctrl._acl_flow.acquire(handle=0x0001)
    listener_done = asyncio.Event()

    async def listener(_handle: int, _status: int, _enabled: int) -> None:
        await ctrl._acl_flow.acquire(handle=0x0001)
        listener_done.set()

    ctrl.on_encryption_change(listener)

    enc_event = bytes([
        HCI_EVENT_PACKET,
        EventCode.ENCRYPTION_CHANGE,
        0x04,
        0x00,
        0x01, 0x00,
        0x01,
    ])
    completed_event = bytes([
        HCI_EVENT_PACKET,
        EventCode.NUM_COMPLETED_PACKETS,
        0x05,
        0x01,
        0x01, 0x00,
        0x01, 0x00,
    ])

    await asyncio.wait_for(transport.inject(enc_event), timeout=0.05)
    await transport.inject(completed_event)

    await asyncio.wait_for(listener_done.wait(), timeout=0.2)


async def test_encryption_key_refresh_complete_advances_encryption_listeners():
    """Re-pairing an already encrypted LE link refreshes its session key.

    The controller then emits Encryption Key Refresh Complete (0x30), whose
    payload is only status + handle, instead of another Encryption Change
    (0x08). It is the success event SMP must use to enter Phase 3; dropping it
    leaves GAP/SEC/AUT/BV-19 deferred in STK_ENCRYPTING until timeout.
    """
    transport = FakeTransport()
    ctrl = HCIController(transport)
    seen: list[tuple[int, int, int]] = []
    ctrl.on_encryption_change(lambda h, s, e: seen.append((h, s, e)))

    refresh_event = bytes([
        HCI_EVENT_PACKET,
        0x30,  # Encryption Key Refresh Complete
        0x03,  # status(1) + connection_handle(2); no enabled byte
        0x00,
        0x00, 0x08,
    ])
    await transport.inject(refresh_event)

    assert seen == [(0x0800, 0x00, 0x01)]


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


def test_le_buffer_size_configures_separate_le_pool():
    """LE_Read_Buffer_Size must configure a separate LE pool and must never
    overwrite the BR/EDR pool.

    Regression: the BR/EDR relay once had LE (num=6) overwrite the shared
    acl_flow of BR/EDR (num=4), causing over-send to exhaust the BR/EDR
    4-buffer -> Data_Buffer_Overflow (0x1A) -> stream stall.
    """
    transport = FakeTransport()
    ctrl = HCIController(transport)
    # init order: BR/EDR Read_Buffer_Size (4x1021) first, then LE_Read_Buffer_Size (6x251).
    ctrl._configure_acl_flow_from_command_complete(HCI_Command_Complete_Event(
        num_hci_command_packets=1,
        command_opcode=HCI_READ_BUFFER_SIZE,
        return_parameters=b"\x00" + struct.pack("<HBHH", 1021, 0x40, 4, 0),
    ))
    ctrl._configure_acl_flow_from_command_complete(HCI_Command_Complete_Event(
        num_hci_command_packets=1,
        command_opcode=HCI_LE_READ_BUFFER_SIZE,
        return_parameters=b"\x00" + struct.pack("<HB", 251, 6),
    ))

    # BR/EDR pool is still 4x1021; LE pool is separate at 6x251.
    assert ctrl._acl_flow.available == 4
    assert ctrl._acl_flow.buffer_size == 1021
    assert ctrl._le_acl_flow.available == 6
    assert ctrl._le_acl_flow.buffer_size == 251


def test_acl_flow_for_routes_by_link_type():
    """_acl_flow_for routes by the connection type of the handle; unknown handles default to the BR/EDR pool."""
    transport = FakeTransport()
    ctrl = HCIController(transport)
    ctrl._acl_flow.configure(num_buffers=4, buffer_size=1021)
    ctrl._le_acl_flow.configure(num_buffers=6, buffer_size=251)

    ctrl._conn_link_type[0x0001] = LINK_TYPE_ACL
    assert ctrl._acl_flow_for(0x0001) is ctrl._acl_flow

    ctrl._conn_link_type[0x0002] = LINK_TYPE_LE
    assert ctrl._acl_flow_for(0x0002) is ctrl._le_acl_flow

    # unregistered handle -> defaults to the BR/EDR pool
    assert ctrl._acl_flow_for(0x0099) is ctrl._acl_flow


def test_acl_flow_for_le_shared_pool_falls_back_to_bredr():
    """LE reports 0 (shares the pool with BR/EDR) -> LE pool not configured -> LE handles fall back to the BR/EDR pool."""
    transport = FakeTransport()
    ctrl = HCIController(transport)
    ctrl._acl_flow.configure(num_buffers=4, buffer_size=1021)
    # _le_acl_flow intentionally left unconfigured (shared-pool case)
    ctrl._conn_link_type[0x0002] = LINK_TYPE_LE
    assert ctrl._acl_flow_for(0x0002) is ctrl._acl_flow


async def test_send_acl_data_fragments_to_the_le_buffer_size():
    """An L2CAP PDU larger than the controller's ACL buffer is split into
    fragments with the PB continuation flag.

    GATT/SR/GAC/BV-01-C: after Exchange MTU (512) the Lower Tester reads a
    512-byte characteristic value. The 512-byte ATT PDU went out as a single
    516-byte ACL packet, far past the LE buffers (251 bytes) advertised by
    Read_Buffer_Size, and never reached the air - PTS timed out after 30 s and
    failed with "Cannot find characteristic value with size equal to MTU-1".

    Continuations must carry PB 0b01 (non-automatically-flushable), not the
    0b11 that ``pb_flag | 0b01`` produced: the Intel BE200 transmits the first
    fragment and then silently discards every 0b11 continuation (on-air:
    251 of 516 bytes), while 0b01 delivers the whole PDU.
    """
    transport = FakeTransport()
    ctrl = HCIController(transport)
    ctrl._acl_flow.configure(num_buffers=4, buffer_size=1021)
    ctrl._le_acl_flow.configure(num_buffers=6, buffer_size=251)
    ctrl._conn_link_type[0x0800] = LINK_TYPE_LE

    payload = bytes([0x1B]) + bytes(511)  # 512-byte ATT Read Response
    await ctrl.send_acl_data(0x0800, 0x02, payload)

    packets = [HCIACLData.from_bytes(raw[1:]) for raw in transport.sent]
    assert [len(p.data) for p in packets] == [251, 251, 10]
    assert [p.pb_flag for p in packets] == [0x02, 0x01, 0x01]
    assert b"".join(p.data for p in packets) == payload
    # each fragment costs one controller buffer
    assert ctrl._le_acl_flow.available == 3


async def test_send_acl_data_keeps_small_payloads_in_one_packet():
    """Payloads that fit stay a single ACL packet with the original PB flag."""
    transport = FakeTransport()
    ctrl = HCIController(transport)
    ctrl._le_acl_flow.configure(num_buffers=6, buffer_size=251)
    ctrl._conn_link_type[0x0800] = LINK_TYPE_LE

    l2cap = bytes([0x04, 0x00, 0x04, 0x00]) + b"hello"
    await ctrl.send_acl_data(0x0800, 0x02, l2cap)

    assert len(transport.sent) == 1
    packet = HCIACLData.from_bytes(transport.sent[0][1:])
    assert packet.pb_flag == 0x02
    assert packet.data == l2cap
    assert ctrl._le_acl_flow.available == 5


async def test_conn_link_type_tracked_on_bredr_connect_and_disconnect():
    """BR/EDR Connection_Complete registers link_type; Disconnection_Complete removes it."""
    transport = FakeTransport()
    ctrl = HCIController(transport)
    # Connection_Complete: status=0, handle=0x0001, bd_addr(6), link_type=0x01(ACL), enc=0
    conn = bytes([
        HCI_EVENT_PACKET, EventCode.CONNECTION_COMPLETE, 0x0B,
        0x00, 0x01, 0x00,
        0x66, 0x55, 0x44, 0x33, 0x22, 0x11,
        0x01, 0x00,
    ])
    await transport.inject(conn)
    assert ctrl._conn_link_type[0x0001] == LINK_TYPE_ACL

    disc = bytes([
        HCI_EVENT_PACKET, EventCode.DISCONNECTION_COMPLETE, 0x04,
        0x00, 0x01, 0x00, 0x16,
    ])
    await transport.inject(disc)
    assert 0x0001 not in ctrl._conn_link_type


async def test_conn_link_type_tracked_on_le_connect():
    """LE_Connection_Complete (LE meta subevent 0x01) is registered as LE."""
    transport = FakeTransport()
    ctrl = HCIController(transport)
    # LE meta: subevent=0x01, params = status(1)+handle(2 LE)+role(1)+...
    sub_params = bytes([0x00, 0x07, 0x00, 0x00]) + b"\x00" * 20
    payload = bytes([LEMetaSubEvent.LE_CONNECTION_COMPLETE]) + sub_params
    evt = bytes([HCI_EVENT_PACKET, EventCode.LE_META, len(payload)]) + payload
    await transport.inject(evt)
    assert ctrl._conn_link_type[0x0007] == LINK_TYPE_LE


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
