# Plan 4b: HCI Controller + VirtualController

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement `pybluehost/hci/controller.py` (HCIController + EventRouter + ConnectionManager + 16-step init sequence) and `pybluehost/hci/virtual.py` (VirtualController). Stateful asyncio logic building on Plan 4a's codec and flow primitives.

**Architecture reference:** `docs/architecture/07-hci.md`, `docs/architecture/02-sap.md`

**Dependencies:** `pybluehost/core/`, `pybluehost/transport/`, Plan 4a (HCI Packet Codec + Flow Control)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/hci/controller.py` | `HCIController` main class (TransportSink + HCIDownstream) + `HCIConnection` + `ConnectionManager` |
| `pybluehost/hci/virtual.py` | `VirtualController` — software-only HCI controller |
| `pybluehost/hci/__init__.py` | Re-export public HCI API (finalize) |
| `tests/unit/hci/test_controller.py` | HCIController with FakeTransport + ConnectionManager unit tests |
| `tests/unit/hci/test_virtual.py` | VirtualController command dispatch |
| `tests/integration/test_hci_init.py` | HCIController + VirtualController init sequence integration test |

---

## Task 1: HCIController + ConnectionManager

## Task 1: HCIController + ConnectionManager

**Files:** `pybluehost/hci/controller.py`, `tests/unit/hci/test_controller.py`

- [x] **Step 1: Write failing tests using FakeTransport (including ConnectionManager tests)**

```python
# tests/unit/hci/test_controller.py
import asyncio
import struct
import pytest
from pybluehost.core.trace import TraceSystem
from pybluehost.hci.controller import HCIController, HCIConnection, ConnectionManager
from pybluehost.hci.packets import (
    HCI_Reset, HCI_Command_Complete_Event, HCI_LE_Meta_Event,
    HCI_LE_Connection_Complete_SubEvent, HCI_Disconnection_Complete_Event,
    HCIACLData, decode_hci_packet,
)
from pybluehost.hci.constants import HCI_RESET, EventCode, ErrorCode

class FakeTransport:
    def __init__(self):
        self.sent: list[bytes] = []
        self._sink = None

    def set_sink(self, sink): self._sink = sink
    async def open(self): pass
    async def close(self): pass
    async def send(self, data: bytes): self.sent.append(data)

    async def inject(self, data: bytes):
        if self._sink:
            await self._sink.on_data(data)

@pytest.fixture
def transport():
    return FakeTransport()

@pytest.fixture
def controller(transport):
    trace = TraceSystem()
    ctrl = HCIController(transport=transport, trace=trace)
    return ctrl

@pytest.mark.asyncio
async def test_send_command_awaits_complete(transport, controller):
    async def reply():
        await asyncio.sleep(0)
        # Simulate Command Complete event
        event = HCI_Command_Complete_Event(
            num_hci_command_packets=1,
            command_opcode=HCI_RESET,
            return_parameters=bytes([ErrorCode.SUCCESS]),
        )
        await transport.inject(event.to_bytes())

    asyncio.create_task(reply())
    result = await asyncio.wait_for(
        controller.send_command(HCI_Reset()), timeout=1.0
    )
    assert isinstance(result, HCI_Command_Complete_Event)
    assert result.command_opcode == HCI_RESET

@pytest.mark.asyncio
async def test_acl_data_routed_to_upstream(transport, controller):
    received = []
    async def on_acl(handle, pb_flag, data):
        received.append((handle, pb_flag, data))

    controller.set_upstream(on_acl_data=on_acl)

    pkt = HCIACLData(handle=0x0040, pb_flag=0x02, bc_flag=0x00, data=b"\xAB\xCD")
    await transport.inject(pkt.to_bytes())
    await asyncio.sleep(0)
    assert len(received) == 1
    assert received[0] == (0x0040, 0x02, b"\xAB\xCD")

@pytest.mark.asyncio
async def test_send_command_timeout(transport, controller):
    from pybluehost.core.errors import CommandTimeoutError
    controller._command_timeout = 0.05
    with pytest.raises(CommandTimeoutError):
        await controller.send_command(HCI_Reset())

# --- ConnectionManager unit tests ---

def test_connection_manager_track_new_le_connection():
    mgr = ConnectionManager()
    peer = bytes.fromhex("AABBCCDDEEFF")
    conn = mgr.on_connection(handle=0x0001, link_type=0x01, role=0x01, peer_address=peer)
    assert conn.handle == 0x0001
    assert conn.link_type == 0x01   # LE
    assert conn.role == 0x01        # slave
    assert conn.peer_address == peer
    assert mgr.get(0x0001) is conn

def test_connection_manager_track_disconnection():
    mgr = ConnectionManager()
    peer = bytes.fromhex("112233445566")
    mgr.on_connection(handle=0x0002, link_type=0x01, role=0x00, peer_address=peer)
    removed = mgr.on_disconnection(handle=0x0002)
    assert removed is not None
    assert removed.handle == 0x0002
    assert mgr.get(0x0002) is None

def test_connection_manager_lookup_by_handle():
    mgr = ConnectionManager()
    peer_a = bytes.fromhex("AABBCCDDEEFF")
    peer_b = bytes.fromhex("112233445566")
    mgr.on_connection(handle=0x0010, link_type=0x01, role=0x00, peer_address=peer_a)
    mgr.on_connection(handle=0x0011, link_type=0x00, role=0x00, peer_address=peer_b)
    assert mgr.get(0x0010).peer_address == peer_a
    assert mgr.get(0x0011).peer_address == peer_b
    assert mgr.get(0x9999) is None

def test_connection_manager_all_connections():
    mgr = ConnectionManager()
    mgr.on_connection(handle=0x0001, link_type=0x01, role=0x00, peer_address=bytes(6))
    mgr.on_connection(handle=0x0002, link_type=0x01, role=0x01, peer_address=bytes(6))
    conns = mgr.all_connections()
    assert len(conns) == 2
    handles = {c.handle for c in conns}
    assert handles == {0x0001, 0x0002}

def test_connection_manager_disconnect_missing_handle_returns_none():
    mgr = ConnectionManager()
    result = mgr.on_disconnection(handle=0xDEAD)
    assert result is None
```

- [x] **Step 2: Run tests — verify they fail**

- [x] **Step 3: Implement `pybluehost/hci/controller.py`**

Design:
- `HCIConnection` dataclass and `ConnectionManager` class (see below)
- `HCIController.__init__(transport, trace, command_timeout=5.0)`
- Implements `TransportSink`: `on_data(data)`, `on_transport_error(error)`
- Implements `HCIDownstream`: `send_command(cmd)`, `send_acl_data(handle, pb_flag, data)`, `send_sco_data(handle, data)`
- Internal: `_flow = CommandFlowController()`, `_acl_flow = ACLFlowController()`
- Internal: `_conn_mgr = ConnectionManager()`
- `set_upstream(on_hci_event, on_acl_data, on_sco_data)` for upper layer callbacks
- `send_command`: acquire credit → encode+send → register future → await with timeout → CommandTimeoutError on timeout
- `on_data`: decode packet → route by type (ACL→upstream, Event→handle_event)
- `_handle_event`: Command Complete → resolve flow+future; Num Completed Packets → ACL flow; others → upstream

```python
# pybluehost/hci/controller.py (relevant additions)
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Awaitable
import asyncio

from pybluehost.hci.constants import ErrorCode
from pybluehost.hci.flow import CommandFlowController, ACLFlowController
from pybluehost.hci.packets import (
    HCIPacket, HCICommand, HCIEvent, HCIACLData,
    HCI_Command_Complete_Event, HCI_Number_Of_Completed_Packets_Event,
    decode_hci_packet,
)
from pybluehost.core.errors import CommandTimeoutError


@dataclass
class HCIConnection:
    handle: int
    link_type: int  # 0x00=BR/EDR, 0x01=LE
    role: int       # 0x00=master, 0x01=slave
    peer_address: bytes


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, HCIConnection] = {}

    def on_connection(
        self, handle: int, link_type: int, role: int, peer_address: bytes
    ) -> HCIConnection:
        conn = HCIConnection(
            handle=handle, link_type=link_type, role=role, peer_address=peer_address
        )
        self._connections[handle] = conn
        return conn

    def on_disconnection(self, handle: int) -> HCIConnection | None:
        return self._connections.pop(handle, None)

    def get(self, handle: int) -> HCIConnection | None:
        return self._connections.get(handle)

    def all_connections(self) -> list[HCIConnection]:
        return list(self._connections.values())


class HCIController:
    def __init__(self, transport, trace, command_timeout: float = 5.0) -> None:
        self._transport = transport
        self._trace = trace
        self._command_timeout = command_timeout
        self._flow = CommandFlowController(initial_credits=1)
        self._acl_flow = ACLFlowController()
        self._conn_mgr = ConnectionManager()
        self._on_hci_event: Callable | None = None
        self._on_acl_data: Callable | None = None
        self._on_sco_data: Callable | None = None
        transport.set_sink(self)

    def set_upstream(
        self,
        on_hci_event: Callable | None = None,
        on_acl_data: Callable | None = None,
        on_sco_data: Callable | None = None,
    ) -> None:
        self._on_hci_event = on_hci_event
        self._on_acl_data = on_acl_data
        self._on_sco_data = on_sco_data

    async def send_command(self, cmd: HCICommand) -> HCI_Command_Complete_Event:
        await self._flow.acquire()
        fut = self._flow.register(cmd.opcode)
        await self._transport.send(cmd.to_bytes())
        try:
            return await asyncio.wait_for(fut, timeout=self._command_timeout)
        except asyncio.TimeoutError:
            raise CommandTimeoutError(
                f"Timeout waiting for response to opcode 0x{cmd.opcode:04X}"
            )

    async def send_acl_data(self, handle: int, pb_flag: int, data: bytes) -> None:
        await self._acl_flow.acquire(handle=handle)
        pkt = HCIACLData(handle=handle, pb_flag=pb_flag, bc_flag=0x00, data=data)
        await self._transport.send(pkt.to_bytes())

    async def on_data(self, data: bytes) -> None:
        pkt = decode_hci_packet(data)
        if isinstance(pkt, HCIACLData):
            if self._on_acl_data:
                await self._on_acl_data(pkt.handle, pkt.pb_flag, pkt.data)
        elif isinstance(pkt, HCIEvent):
            await self._handle_event(pkt)

    async def _handle_event(self, event: HCIEvent) -> None:
        if isinstance(event, HCI_Command_Complete_Event):
            self._flow.release(event.num_hci_command_packets)
            self._flow.resolve(event.command_opcode, event)
        elif isinstance(event, HCI_Number_Of_Completed_Packets_Event):
            self._acl_flow.on_num_completed(event.completed)
        else:
            if self._on_hci_event:
                await self._on_hci_event(event)

    async def on_transport_error(self, error: Exception) -> None:
        self._trace.error(f"Transport error: {error}")
```

- [x] **Step 4: Run tests — verify they pass**

- [x] **Step 5: Add `CommandTimeoutError` to `core/errors.py` if missing, then commit**
```bash
git add pybluehost/hci/controller.py tests/unit/hci/test_controller.py
git commit -m "feat(hci): add HCIController with command/ACL flow, event routing, and ConnectionManager"
```

---

---

## Task 2: VirtualController

## Task 2: VirtualController

**Files:** `pybluehost/hci/virtual.py`, `tests/unit/hci/test_virtual.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/hci/test_virtual.py
import asyncio
import pytest
from pybluehost.hci.virtual import VirtualController
from pybluehost.hci.packets import (
    HCI_Reset, HCI_Command_Complete_Event,
    HCI_Read_BD_ADDR_Command, HCI_LE_Read_Buffer_Size_Command,
    decode_hci_packet,
)
from pybluehost.hci.constants import ErrorCode
from pybluehost.core.address import BDAddress

@pytest.fixture
def vc():
    return VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:01"))

@pytest.mark.asyncio
async def test_reset_command(vc):
    cmd = HCI_Reset()
    response = await vc.process(cmd.to_bytes())
    assert response is not None
    event = decode_hci_packet(response)
    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.return_parameters[0] == ErrorCode.SUCCESS

@pytest.mark.asyncio
async def test_read_bd_addr(vc):
    cmd = HCI_Read_BD_ADDR_Command()
    response = await vc.process(cmd.to_bytes())
    event = decode_hci_packet(response)
    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.return_parameters[0] == ErrorCode.SUCCESS
    addr_bytes = event.return_parameters[1:7]
    assert addr_bytes == bytes(reversed(bytes.fromhex("AABBCCDDEEE01".replace("EEE", "EE"))))

@pytest.mark.asyncio
async def test_unknown_command_returns_unknown_command_error(vc):
    raw = bytes([0x01, 0xFE, 0xFF, 0x00])  # Unknown opcode
    response = await vc.process(raw)
    event = decode_hci_packet(response)
    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.return_parameters[0] == ErrorCode.UNKNOWN_COMMAND

@pytest.mark.asyncio
async def test_le_read_buffer_size(vc):
    from pybluehost.hci.packets import HCI_LE_Read_Buffer_Size_Command
    cmd = HCI_LE_Read_Buffer_Size_Command()
    response = await vc.process(cmd.to_bytes())
    event = decode_hci_packet(response)
    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.return_parameters[0] == ErrorCode.SUCCESS
```

- [x] **Step 2: Run tests — verify they fail**

- [x] **Step 3: Implement `pybluehost/hci/virtual.py`**

Design:
- `VirtualController(address: BDAddress)`
- `async def process(data: bytes) -> bytes | None`: decode command → dispatch to handler → return encoded event
- Handler registry: dict from opcode → async handler method
- Implement handlers: `HCI_Reset`, `HCI_Read_Local_Version`, `HCI_Read_BD_ADDR`, `HCI_Read_Buffer_Size`, `HCI_LE_Read_Buffer_Size`, `HCI_LE_Read_Local_Supported_Features`, `HCI_Set_Event_Mask`, `HCI_LE_Set_Event_Mask`, `HCI_Write_LE_Host_Supported`, `HCI_Read_Local_Supported_Commands`, `HCI_Read_Local_Supported_Features`, `HCI_Write_Simple_Pairing_Mode`
- Unknown opcode → `Command_Complete` with `UNKNOWN_COMMAND` status
- `connect_to(other: VirtualController)`: wire loopback for ACL

- [x] **Step 4: Run tests — verify they pass**

- [x] **Step 5: Commit**
```bash
git add pybluehost/hci/virtual.py tests/unit/hci/test_virtual.py
git commit -m "feat(hci): add VirtualController with basic command dispatch"
```

---

---

## Task 3: Package Exports + Final Tests

## Task 3: Package Exports + Final Tests

**Files:** `pybluehost/hci/__init__.py`, full test suite run

- [x] **Step 1: Write `pybluehost/hci/__init__.py`**

```python
from pybluehost.hci.constants import (
    OGF, EventCode, LEMetaSubEvent, ErrorCode,
    HCI_RESET, HCI_READ_BD_ADDR, HCI_READ_BUFFER_SIZE,
    HCI_LE_READ_BUFFER_SIZE, HCI_LE_SET_SCAN_ENABLE,
    HCI_COMMAND_PACKET, HCI_ACL_PACKET, HCI_EVENT_PACKET,
)
from pybluehost.hci.packets import (
    HCIPacket, HCICommand, HCIEvent, HCIACLData, HCISCOData, HCIISOData,
    PacketRegistry, decode_hci_packet,
    HCI_Reset, HCI_LE_Set_Scan_Enable,
    HCI_Command_Complete_Event, HCI_Command_Status_Event,
    HCI_Connection_Complete_Event, HCI_Disconnection_Complete_Event,
    HCI_Number_Of_Completed_Packets_Event, HCI_LE_Meta_Event,
)
from pybluehost.hci.flow import CommandFlowController, ACLFlowController
from pybluehost.hci.controller import HCIController, HCIConnection, ConnectionManager
from pybluehost.hci.virtual import VirtualController

__all__ = [
    "OGF", "EventCode", "LEMetaSubEvent", "ErrorCode",
    "HCI_RESET", "HCI_READ_BD_ADDR", "HCI_READ_BUFFER_SIZE",
    "HCI_LE_READ_BUFFER_SIZE", "HCI_LE_SET_SCAN_ENABLE",
    "HCI_COMMAND_PACKET", "HCI_ACL_PACKET", "HCI_EVENT_PACKET",
    "HCIPacket", "HCICommand", "HCIEvent", "HCIACLData", "HCISCOData", "HCIISOData",
    "PacketRegistry", "decode_hci_packet",
    "HCI_Reset", "HCI_LE_Set_Scan_Enable",
    "HCI_Command_Complete_Event", "HCI_Command_Status_Event",
    "HCI_Connection_Complete_Event", "HCI_Disconnection_Complete_Event",
    "HCI_Number_Of_Completed_Packets_Event", "HCI_LE_Meta_Event",
    "CommandFlowController", "ACLFlowController",
    "HCIController", "HCIConnection", "ConnectionManager",
    "VirtualController",
]
```

- [x] **Step 2: Run all HCI tests**
```bash
uv run pytest tests/unit/hci/ -v --tb=short
```

- [x] **Step 3: Run full test suite — no regressions**
```bash
uv run pytest tests/ -v --tb=short
```

- [x] **Step 4: Commit**
```bash
git add pybluehost/hci/__init__.py
git commit -m "feat(hci): finalize HCI package exports"
```

---

---

## Task 4: HCI Init Sequence Integration Test

## Task 4: HCI Init Sequence Integration Test

**Files:** Create `tests/integration/__init__.py` (if absent), `tests/integration/test_hci_init.py`

This test wires a real `HCIController` to a `VirtualController` via a `LoopbackTransport`
and verifies that `controller.initialize()` issues all 16 mandatory init commands.
It serves as a smoke test that the full HCI stack can come up without errors.

- [x] **Step 1: Write the integration test**

```python
# tests/integration/test_hci_init.py
"""Integration test: HCIController init sequence against VirtualController.

Topology:
    HCIController  <──LoopbackTransport──>  VirtualController

The LoopbackTransport forwards every bytes frame written by HCIController
to VirtualController.process(), then delivers the response back as if it
arrived from hardware.  No real Bluetooth adapter is required.
"""
from __future__ import annotations

import asyncio
import pytest
from typing import Callable, Awaitable

from pybluehost.core.address import BDAddress
from pybluehost.core.trace import TraceSystem
from pybluehost.hci.controller import HCIController
from pybluehost.hci.virtual import VirtualController
from pybluehost.hci.packets import HCICommand, decode_hci_packet, HCI_Command_Complete_Event
from pybluehost.hci.constants import (
    HCI_RESET,
    HCI_READ_LOCAL_VERSION,
    HCI_READ_LOCAL_SUPPORTED_COMMANDS,
    HCI_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_READ_BD_ADDR,
    HCI_READ_BUFFER_SIZE,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_SET_EVENT_MASK,
    HCI_LE_SET_EVENT_MASK,
    HCI_WRITE_LE_HOST_SUPPORTED,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
    HCI_WRITE_SCAN_ENABLE,
    HCI_HOST_BUFFER_SIZE,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_LE_SET_RANDOM_ADDRESS,
)

# The 16 init commands HCIController.initialize() must send, in order.
EXPECTED_INIT_OPCODES: list[int] = [
    HCI_RESET,
    HCI_READ_LOCAL_VERSION,
    HCI_READ_LOCAL_SUPPORTED_COMMANDS,
    HCI_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_READ_BD_ADDR,
    HCI_READ_BUFFER_SIZE,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_SET_EVENT_MASK,
    HCI_LE_SET_EVENT_MASK,
    HCI_WRITE_LE_HOST_SUPPORTED,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
    HCI_WRITE_SCAN_ENABLE,
    HCI_HOST_BUFFER_SIZE,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_LE_SET_RANDOM_ADDRESS,
]


class LoopbackTransport:
    """In-process transport that routes HCIController bytes through VirtualController.

    Usage::

        transport = LoopbackTransport(virtual_controller)
        controller = HCIController(transport=transport, trace=TraceSystem())

    When HCIController calls ``transport.send(data)``, LoopbackTransport:
    1. Records the decoded opcode in ``sent_opcodes``.
    2. Passes ``data`` to ``VirtualController.process()``.
    3. Delivers the response to the HCIController sink.
    """

    def __init__(self, vc: VirtualController) -> None:
        self._vc = vc
        self._sink = None
        self.sent_opcodes: list[int] = []

    # TransportSource protocol
    def set_sink(self, sink) -> None:
        self._sink = sink

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def send(self, data: bytes) -> None:
        # Decode and record the opcode (bytes[1:3] LE for HCI commands)
        pkt = decode_hci_packet(data)
        if isinstance(pkt, HCICommand):
            self.sent_opcodes.append(pkt.opcode)

        # Forward to VirtualController and deliver the response
        response = await self._vc.process(data)
        if response is not None and self._sink is not None:
            await self._sink.on_data(response)


@pytest.mark.asyncio
async def test_hci_init_sequence_sends_all_16_commands():
    """HCIController.initialize() must issue exactly the 16 expected init commands."""
    vc = VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:FF"))
    transport = LoopbackTransport(vc)
    trace = TraceSystem()
    controller = HCIController(transport=transport, trace=trace)

    await asyncio.wait_for(controller.initialize(), timeout=5.0)

    assert len(transport.sent_opcodes) == len(EXPECTED_INIT_OPCODES), (
        f"Expected {len(EXPECTED_INIT_OPCODES)} init commands, "
        f"got {len(transport.sent_opcodes)}: "
        f"{[hex(op) for op in transport.sent_opcodes]}"
    )
    assert transport.sent_opcodes == EXPECTED_INIT_OPCODES, (
        f"Init command sequence mismatch.\n"
        f"Expected: {[hex(op) for op in EXPECTED_INIT_OPCODES]}\n"
        f"Got:      {[hex(op) for op in transport.sent_opcodes]}"
    )


@pytest.mark.asyncio
async def test_hci_init_sequence_all_commands_succeed():
    """Every init command must receive a successful Command Complete (status=0x00)."""
    vc = VirtualController(address=BDAddress.from_string("11:22:33:44:55:66"))
    transport = LoopbackTransport(vc)
    trace = TraceSystem()
    controller = HCIController(transport=transport, trace=trace)

    # Capture every Command Complete event delivered during initialize()
    received_events: list[HCI_Command_Complete_Event] = []
    original_handle = controller._handle_event

    async def capturing_handle(event):
        if isinstance(event, HCI_Command_Complete_Event):
            received_events.append(event)
        await original_handle(event)

    controller._handle_event = capturing_handle

    await asyncio.wait_for(controller.initialize(), timeout=5.0)

    assert len(received_events) == len(EXPECTED_INIT_OPCODES), (
        f"Expected {len(EXPECTED_INIT_OPCODES)} Command Complete events"
    )
    for evt in received_events:
        assert evt.return_parameters[0] == 0x00, (
            f"Command 0x{evt.command_opcode:04X} failed with status "
            f"0x{evt.return_parameters[0]:02X}"
        )


@pytest.mark.asyncio
async def test_hci_init_sequence_timeout_raises():
    """If the transport never responds, initialize() must raise CommandTimeoutError."""
    from pybluehost.core.errors import CommandTimeoutError

    class SilentTransport:
        """Accepts sends but never delivers a response."""
        def set_sink(self, sink): pass
        async def open(self): pass
        async def close(self): pass
        async def send(self, data: bytes): pass  # deliberately silent

    controller = HCIController(
        transport=SilentTransport(),
        trace=TraceSystem(),
        command_timeout=0.05,  # short timeout for test speed
    )
    with pytest.raises(CommandTimeoutError):
        await controller.initialize()
```

- [x] **Step 2: Run the integration test — verify it fails (initialize() not yet implemented)**
```bash
uv run pytest tests/integration/test_hci_init.py -v
```

- [x] **Step 3: Implement `HCIController.initialize()` in `controller.py`**

Add the following method to `HCIController`.  It sends each of the 16 init commands in
sequence, using `send_command()` (which already handles credit flow and timeouts).
Each command awaits its Command Complete before the next is issued.

```python
async def initialize(self) -> None:
    """Send the standard HCI initialization sequence.

    Issues the 16 mandatory commands required to bring up a Bluetooth
    controller from reset.  Each command is sent sequentially; the method
    waits for Command Complete before proceeding to the next command.

    Raises
    ------
    CommandTimeoutError
        If any command does not receive a Command Complete within the
        configured ``_command_timeout``.
    """
    from pybluehost.hci.packets import (
        HCI_Reset_Command,
        HCI_Read_Local_Version_Command,
        HCI_Read_Local_Supported_Commands_Command,
        HCI_Read_Local_Supported_Features_Command,
        HCI_Read_BD_ADDR_Command,
        HCI_Read_Buffer_Size_Command,
        HCI_LE_Read_Buffer_Size_Command,
        HCI_LE_Read_Local_Supported_Features_Command,
        HCI_Set_Event_Mask_Command,
        HCI_LE_Set_Event_Mask_Command,
        HCI_Write_LE_Host_Supported_Command,
        HCI_Write_Simple_Pairing_Mode_Command,
        HCI_Write_Scan_Enable_Command,
        HCI_Host_Buffer_Size_Command,
        HCI_LE_Set_Scan_Parameters_Command,
        HCI_LE_Set_Random_Address_Command,
    )

    # Standard event mask: enable all classic events
    EVENT_MASK_ALL = b"\xFF\xFF\xFF\xFF\xFF\xFF\xFF\x3F"
    # LE event mask: enable LE Connection Complete + LE Advertising Report
    LE_EVENT_MASK = b"\x1F\x00\x00\x00\x00\x00\x00\x00"
    # Random address placeholder (all zeros — upper layer sets a real address later)
    RANDOM_ADDRESS = bytes(6)

    init_commands = [
        HCI_Reset_Command(),
        HCI_Read_Local_Version_Command(),
        HCI_Read_Local_Supported_Commands_Command(),
        HCI_Read_Local_Supported_Features_Command(),
        HCI_Read_BD_ADDR_Command(),
        HCI_Read_Buffer_Size_Command(),
        HCI_LE_Read_Buffer_Size_Command(),
        HCI_LE_Read_Local_Supported_Features_Command(),
        HCI_Set_Event_Mask_Command(event_mask=EVENT_MASK_ALL),
        HCI_LE_Set_Event_Mask_Command(le_event_mask=LE_EVENT_MASK),
        HCI_Write_LE_Host_Supported_Command(le_supported_host=0x01, simultaneous_le_host=0x00),
        HCI_Write_Simple_Pairing_Mode_Command(simple_pairing_mode=0x01),
        HCI_Write_Scan_Enable_Command(scan_enable=0x00),  # no scan during init
        HCI_Host_Buffer_Size_Command(
            host_acl_data_packet_length=0x0200,
            host_synchronous_data_packet_length=0xFF,
            host_total_num_acl_data_packets=0x0014,
            host_total_num_synchronous_data_packets=0x0000,
        ),
        HCI_LE_Set_Scan_Parameters_Command(
            le_scan_type=0x01,           # active scanning
            le_scan_interval=0x0010,
            le_scan_window=0x0010,
            own_address_type=0x00,       # public
            scanning_filter_policy=0x00,
        ),
        HCI_LE_Set_Random_Address_Command(random_address=RANDOM_ADDRESS),
    ]

    for cmd in init_commands:
        await self.send_command(cmd)
```

- [x] **Step 4: Run the integration test — verify it passes**
```bash
uv run pytest tests/integration/test_hci_init.py -v
```

- [x] **Step 5: Run the full test suite — no regressions**
```bash
uv run pytest tests/ -v --tb=short
```

- [x] **Step 6: Commit**
```bash
git add tests/integration/ pybluehost/hci/controller.py
git commit -m "test(hci): add integration test for HCI init sequence (16 commands)"
```

- [x] **Step 7: Update STATUS.md — mark Plan 3 complete**

Edit `docs/superpowers/STATUS.md`: change Plan 3 from 🔄 to ✅, set Plan 4 as current.

```bash
git add docs/superpowers/STATUS.md
git commit -m "docs: mark Plan 3 (HCI) complete in STATUS.md"
```

---

---

## 审查补充事项 (from Plan 4 review)

### 补充 1: SCO 数据路由测试（架构 07-hci.md §7.4）

`HCIController.on_transport_data` 的 `case 0x03` 分支需要测试：
- SCO 数据能正确路由到 `HCIUpstream.on_sco_data()` 回调
- connection handle 匹配/不匹配时的行为

### 补充 2: Vendor Event 路由机制

`hci/vendor/intel.py` 和 `hci/vendor/realtek.py` 的 Vendor Event 解析：
- Intel Vendor Event 解析（用于固件加载响应）
- Realtek Vendor Event 解析
- Vendor event 路由机制（VendorEventRouter 或 EventRouter 的扩展）

### 补充 3: TransportSource 引用修正

Plan 中 `HCIController.__init__` 签名使用 `transport: TransportSource`，但 `TransportSource` 类不存在于实际代码中。应改为：
```python
def __init__(self, transport: Transport, trace: TraceSystem) -> None:
```

### 补充 4: TransportSink 接口已更新

**注意**：TransportSink 方法已从 `on_data` 重命名为 `on_transport_data`（2026-04-18）。Plan 中实现 TransportSink 的类需使用新名称。同时 TransportSink 新增了 `on_transport_error(error: TransportError)` 方法。
