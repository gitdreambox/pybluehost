# Plan 4: HCI Layer Implementation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement `pybluehost/hci/` — the HCI packet codec, command/ACL flow control, event router, connection manager, vendor constants, and VirtualController. This layer sits between `transport/` and `l2cap/`, consuming `TransportSource` SAP and exposing `HCIDownstream` / `HCIUpstream` SAPs.

**Architecture reference:** `docs/architecture/07-hci.md`, `docs/architecture/02-sap.md`

**Dependencies:** `pybluehost/core/`, `pybluehost/transport/`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/hci/__init__.py` | Re-export public HCI API |
| `pybluehost/hci/constants.py` | OGF/OCF opcodes, event codes, error codes, LE meta sub-event codes |
| `pybluehost/hci/packets.py` | `HCIPacket` hierarchy + `PacketRegistry` decode |
| `pybluehost/hci/flow.py` | `CommandFlowController` + `ACLFlowController` |
| `pybluehost/hci/controller.py` | `HCIController` main class (TransportSink + HCIDownstream) + `HCIConnection` + `ConnectionManager` |
| `pybluehost/hci/virtual.py` | `VirtualController` — software-only HCI controller |
| `pybluehost/hci/vendor/__init__.py` | Re-export vendor subpackage |
| `pybluehost/hci/vendor/intel.py` | Intel vendor opcodes, TLV constants, `IntelReadVersionResponse` |
| `pybluehost/hci/vendor/realtek.py` | Realtek vendor opcodes, `RealtekROMVersion` |
| `tests/unit/hci/__init__.py` | |
| `tests/unit/hci/test_constants.py` | Opcode construction, error code values |
| `tests/unit/hci/test_packets.py` | Encode/decode round-trips for all packet types |
| `tests/unit/hci/test_flow.py` | Command credit semaphore, ACL flow control |
| `tests/unit/hci/test_controller.py` | HCIController with FakeTransport + ConnectionManager unit tests |
| `tests/unit/hci/test_virtual.py` | VirtualController command dispatch |
| `tests/integration/test_hci_init.py` | HCIController + VirtualController init sequence integration test |

---

## Task 1: Constants

**Files:** Create `pybluehost/hci/constants.py`, `tests/unit/hci/__init__.py`, `tests/unit/hci/test_constants.py`

- [ ] **Step 1: Write failing tests for opcode construction**

```python
# tests/unit/hci/test_constants.py
from pybluehost.hci.constants import (
    make_opcode, ogf_ocf, OGF, OCF_LINK_CONTROL, OCF_CONTROLLER_BB,
    OCF_INFO_PARAMS, OCF_LE, HCI_RESET, HCI_READ_LOCAL_VERSION,
    HCI_READ_BD_ADDR, HCI_READ_BUFFER_SIZE,
    HCI_LE_READ_BUFFER_SIZE, HCI_LE_SET_SCAN_ENABLE,
    EventCode, LEMetaSubEvent, ErrorCode,
)

def test_opcode_construction():
    assert make_opcode(OGF.CONTROLLER_BB, 0x03) == 0x0C03  # HCI_Reset
    assert make_opcode(OGF.LE, 0x0C) == 0x200C              # LE_Set_Scan_Enable

def test_ogf_ocf_round_trip():
    opcode = 0x0406
    ogf, ocf = ogf_ocf(opcode)
    assert ogf == 0x01
    assert ocf == 0x06

def test_named_opcodes():
    assert HCI_RESET == 0x0C03
    assert HCI_READ_BD_ADDR == 0x1009
    assert HCI_LE_SET_SCAN_ENABLE == 0x200C

def test_event_codes():
    assert EventCode.COMMAND_COMPLETE == 0x0E
    assert EventCode.COMMAND_STATUS == 0x0F
    assert EventCode.CONNECTION_COMPLETE == 0x03
    assert EventCode.LE_META == 0x3E

def test_le_meta_sub_events():
    assert LEMetaSubEvent.LE_CONNECTION_COMPLETE == 0x01
    assert LEMetaSubEvent.LE_ADVERTISING_REPORT == 0x02

def test_error_codes():
    assert ErrorCode.SUCCESS == 0x00
    assert ErrorCode.UNKNOWN_COMMAND == 0x01
    assert ErrorCode.CONNECTION_TIMEOUT == 0x08
```

- [ ] **Step 2: Run tests — verify they fail**
```bash
uv run pytest tests/unit/hci/test_constants.py -v
```

- [ ] **Step 3: Implement `pybluehost/hci/constants.py`**

```python
from enum import IntEnum

class OGF(IntEnum):
    LINK_CONTROL    = 0x01
    LINK_POLICY     = 0x02
    CONTROLLER_BB   = 0x03
    INFO_PARAMS     = 0x04
    STATUS_PARAMS   = 0x05
    TESTING         = 0x06
    LE              = 0x08
    VENDOR          = 0x3F

def make_opcode(ogf: int, ocf: int) -> int:
    return (ogf << 10) | (ocf & 0x03FF)

def ogf_ocf(opcode: int) -> tuple[int, int]:
    return (opcode >> 10) & 0x3F, opcode & 0x03FF

# Link Control (OGF=0x01)
HCI_INQUIRY                  = make_opcode(OGF.LINK_CONTROL, 0x01)
HCI_CREATE_CONNECTION        = make_opcode(OGF.LINK_CONTROL, 0x05)
HCI_DISCONNECT               = make_opcode(OGF.LINK_CONTROL, 0x06)
HCI_ACCEPT_CONNECTION_REQ    = make_opcode(OGF.LINK_CONTROL, 0x09)
HCI_REJECT_CONNECTION_REQ   = make_opcode(OGF.LINK_CONTROL, 0x0A)
HCI_LINK_KEY_REQUEST_REPLY   = make_opcode(OGF.LINK_CONTROL, 0x0B)
HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY = make_opcode(OGF.LINK_CONTROL, 0x0C)
HCI_AUTH_REQUESTED           = make_opcode(OGF.LINK_CONTROL, 0x11)
HCI_SET_CONNECTION_ENCRYPTION = make_opcode(OGF.LINK_CONTROL, 0x13)
HCI_REMOTE_NAME_REQUEST      = make_opcode(OGF.LINK_CONTROL, 0x19)
HCI_IO_CAPABILITY_REQUEST_REPLY = make_opcode(OGF.LINK_CONTROL, 0x2B)
HCI_USER_CONFIRMATION_REQUEST_REPLY = make_opcode(OGF.LINK_CONTROL, 0x2C)
HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY = make_opcode(OGF.LINK_CONTROL, 0x2D)

# Controller & Baseband (OGF=0x03)
HCI_RESET                    = make_opcode(OGF.CONTROLLER_BB, 0x03)
HCI_SET_EVENT_MASK           = make_opcode(OGF.CONTROLLER_BB, 0x01)
HCI_READ_LOCAL_NAME          = make_opcode(OGF.CONTROLLER_BB, 0x14)
HCI_WRITE_LOCAL_NAME         = make_opcode(OGF.CONTROLLER_BB, 0x13)
HCI_WRITE_SCAN_ENABLE        = make_opcode(OGF.CONTROLLER_BB, 0x1A)
HCI_WRITE_AUTHENTICATION_ENABLE = make_opcode(OGF.CONTROLLER_BB, 0x20)
HCI_WRITE_CLASS_OF_DEVICE    = make_opcode(OGF.CONTROLLER_BB, 0x24)
HCI_HOST_BUFFER_SIZE         = make_opcode(OGF.CONTROLLER_BB, 0x33)
HCI_WRITE_SIMPLE_PAIRING_MODE = make_opcode(OGF.CONTROLLER_BB, 0x56)
HCI_WRITE_LE_HOST_SUPPORTED  = make_opcode(OGF.CONTROLLER_BB, 0x6D)
HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT = make_opcode(OGF.CONTROLLER_BB, 0x7A)

# Informational Parameters (OGF=0x04)
HCI_READ_LOCAL_VERSION       = make_opcode(OGF.INFO_PARAMS, 0x01)
HCI_READ_LOCAL_SUPPORTED_COMMANDS = make_opcode(OGF.INFO_PARAMS, 0x02)
HCI_READ_LOCAL_SUPPORTED_FEATURES = make_opcode(OGF.INFO_PARAMS, 0x03)
HCI_READ_LOCAL_EXTENDED_FEATURES = make_opcode(OGF.INFO_PARAMS, 0x04)
HCI_READ_BUFFER_SIZE         = make_opcode(OGF.INFO_PARAMS, 0x05)
HCI_READ_BD_ADDR             = make_opcode(OGF.INFO_PARAMS, 0x09)

# LE Controller (OGF=0x08)
HCI_LE_SET_EVENT_MASK        = make_opcode(OGF.LE, 0x01)
HCI_LE_READ_BUFFER_SIZE      = make_opcode(OGF.LE, 0x02)
HCI_LE_READ_LOCAL_SUPPORTED_FEATURES = make_opcode(OGF.LE, 0x03)
HCI_LE_SET_RANDOM_ADDRESS    = make_opcode(OGF.LE, 0x05)
HCI_LE_SET_ADVERTISING_PARAMS = make_opcode(OGF.LE, 0x06)
HCI_LE_SET_ADVERTISING_DATA  = make_opcode(OGF.LE, 0x08)
HCI_LE_SET_SCAN_RESPONSE_DATA = make_opcode(OGF.LE, 0x09)
HCI_LE_SET_ADVERTISE_ENABLE  = make_opcode(OGF.LE, 0x0A)
HCI_LE_SET_SCAN_PARAMS       = make_opcode(OGF.LE, 0x0B)
HCI_LE_SET_SCAN_ENABLE       = make_opcode(OGF.LE, 0x0C)
HCI_LE_CREATE_CONNECTION     = make_opcode(OGF.LE, 0x0D)
HCI_LE_CREATE_CONNECTION_CANCEL = make_opcode(OGF.LE, 0x0E)
HCI_LE_READ_SUPPORTED_STATES = make_opcode(OGF.LE, 0x1C)
HCI_LE_SET_DATA_LENGTH       = make_opcode(OGF.LE, 0x22)
HCI_LE_READ_MAXIMUM_DATA_LENGTH = make_opcode(OGF.LE, 0x2F)

class EventCode(IntEnum):
    INQUIRY_COMPLETE            = 0x01
    INQUIRY_RESULT              = 0x02
    CONNECTION_COMPLETE         = 0x03
    CONNECTION_REQUEST          = 0x04
    DISCONNECTION_COMPLETE      = 0x05
    AUTH_COMPLETE               = 0x06
    REMOTE_NAME_REQUEST_COMPLETE = 0x07
    ENCRYPTION_CHANGE           = 0x08
    CHANGE_LINK_KEY_COMPLETE    = 0x09
    READ_REMOTE_FEATURES_COMPLETE = 0x0B
    READ_REMOTE_VERSION_COMPLETE = 0x0C
    COMMAND_COMPLETE            = 0x0E
    COMMAND_STATUS              = 0x0F
    HARDWARE_ERROR              = 0x10
    NUM_COMPLETED_PACKETS       = 0x13
    DATA_BUFFER_OVERFLOW        = 0x1A
    MAX_SLOTS_CHANGE            = 0x1B
    LINK_KEY_REQUEST            = 0x17
    LINK_KEY_NOTIFICATION       = 0x18
    IO_CAPABILITY_REQUEST       = 0x31
    IO_CAPABILITY_RESPONSE      = 0x32
    USER_CONFIRMATION_REQUEST   = 0x33
    USER_PASSKEY_REQUEST        = 0x34
    SIMPLE_PAIRING_COMPLETE     = 0x36
    LE_META                     = 0x3E
    VENDOR_SPECIFIC             = 0xFF

class LEMetaSubEvent(IntEnum):
    LE_CONNECTION_COMPLETE          = 0x01
    LE_ADVERTISING_REPORT           = 0x02
    LE_CONNECTION_UPDATE_COMPLETE   = 0x03
    LE_READ_REMOTE_FEATURES_COMPLETE = 0x04
    LE_LONG_TERM_KEY_REQUEST        = 0x05
    LE_ENHANCED_CONNECTION_COMPLETE = 0x0A
    LE_DIRECTED_ADVERTISING_REPORT  = 0x0B
    LE_PHY_UPDATE_COMPLETE          = 0x0C
    LE_EXTENDED_ADVERTISING_REPORT  = 0x0D

class ErrorCode(IntEnum):
    SUCCESS                     = 0x00
    UNKNOWN_COMMAND             = 0x01
    NO_CONNECTION               = 0x02
    HARDWARE_FAILURE            = 0x03
    PAGE_TIMEOUT                = 0x04
    AUTH_FAILURE                = 0x05
    PIN_KEY_MISSING             = 0x06
    MEMORY_FULL                 = 0x07
    CONNECTION_TIMEOUT          = 0x08
    MAX_CONNECTIONS             = 0x09
    COMMAND_DISALLOWED          = 0x0C
    REJECTED_LIMITED_RESOURCES  = 0x0D
    REJECTED_SECURITY           = 0x0E
    REJECTED_BAD_BD_ADDR        = 0x0F
    HOST_TIMEOUT                = 0x10
    UNSUPPORTED_FEATURE         = 0x11
    INVALID_PARAMETERS          = 0x12
    REMOTE_USER_TERMINATED      = 0x13
    REMOTE_LOW_RESOURCES        = 0x14
    REMOTE_POWER_OFF            = 0x15
    LOCAL_HOST_TERMINATED       = 0x16
    REPEATED_ATTEMPTS           = 0x17
    PAIRING_NOT_ALLOWED         = 0x18
    UNSPECIFIED_ERROR           = 0x1F
    LL_RESPONSE_TIMEOUT         = 0x22
    LL_PROCEDURE_COLLISION      = 0x23
    ENCRYPTION_MODE_NOT_ACCEPTABLE = 0x25
    UNIT_KEY_USED               = 0x26
    QOS_NOT_SUPPORTED           = 0x27
    INSTANT_PASSED              = 0x28
    PAIRING_WITH_UNIT_KEY_NOT_SUPPORTED = 0x29
    DIFFERENT_TRANSACTION_COLLISION = 0x2A
    CHANNEL_ASSESSMENT_NOT_SUPPORTED = 0x2E
    INSUFFICIENT_SECURITY       = 0x2F
    PARAMETER_OUT_OF_RANGE      = 0x30
    ROLE_SWITCH_PENDING         = 0x32
    RESERVED_SLOT_VIOLATION     = 0x34
    ROLE_SWITCH_FAILED          = 0x35
    EXTENDED_INQUIRY_RESPONSE_TOO_LARGE = 0x36
    SECURE_SIMPLE_PAIRING_NOT_SUPPORTED = 0x37
    HOST_BUSY_PAIRING           = 0x38
    CONTROLLER_BUSY             = 0x3A
    UNACCEPTABLE_CONNECTION_PARAMS = 0x3B
    DIRECTED_ADVERTISING_TIMEOUT = 0x3C
    CONNECTION_TERMINATED_MIC_FAILURE = 0x3D
    FAILED_TO_ESTABLISH_CONNECTION = 0x3E
    MAC_CONNECTION_FAILED       = 0x3F

# Packet type indicators (H4 framing)
HCI_COMMAND_PACKET  = 0x01
HCI_ACL_PACKET      = 0x02
HCI_SCO_PACKET      = 0x03
HCI_EVENT_PACKET    = 0x04
HCI_ISO_PACKET      = 0x05

# ACL PB flags
ACL_PB_FIRST_NON_AUTO_FLUSH  = 0x00
ACL_PB_CONTINUING            = 0x01
ACL_PB_FIRST_AUTO_FLUSH      = 0x02
ACL_PB_COMPLETE_L2CAP        = 0x03
```

- [ ] **Step 4: Run tests — verify they pass**
```bash
uv run pytest tests/unit/hci/test_constants.py -v
```

- [ ] **Step 5: Commit**
```bash
git add pybluehost/hci/constants.py tests/unit/hci/
git commit -m "feat(hci): add HCI constants — opcodes, event codes, error codes"
```

---

## Task 2: Packet System

**Files:** Modify `pybluehost/hci/packets.py`, `tests/unit/hci/test_packets.py`

- [ ] **Step 1: Write failing tests for packet encode/decode**

```python
# tests/unit/hci/test_packets.py
import struct
import pytest
from pybluehost.hci.packets import (
    HCIPacket, HCICommand, HCIEvent, HCIACLData, HCISCOData,
    PacketRegistry, HCI_Reset, HCI_LE_Set_Scan_Enable,
    HCI_Command_Complete_Event, HCI_Command_Status_Event,
    HCI_Connection_Complete_Event, HCI_Disconnection_Complete_Event,
    HCI_Number_Of_Completed_Packets_Event, HCI_LE_Meta_Event,
    HCI_LE_Connection_Complete_SubEvent,
    decode_hci_packet,
)
from pybluehost.hci.constants import EventCode, ErrorCode, HCI_RESET

def test_hci_command_encode():
    cmd = HCI_Reset()
    data = cmd.to_bytes()
    # H4 type(1) + opcode(2 LE) + param_len(1)
    assert data == bytes([0x01, 0x03, 0x0C, 0x00])

def test_hci_command_decode():
    raw = bytes([0x01, 0x03, 0x0C, 0x00])
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCI_Reset)
    assert pkt.opcode == HCI_RESET

def test_le_set_scan_enable_encode():
    cmd = HCI_LE_Set_Scan_Enable(le_scan_enable=1, filter_duplicates=0)
    data = cmd.to_bytes()
    assert data[0] == 0x01                    # HCI Command
    assert data[1:3] == bytes([0x0C, 0x20])   # opcode LE
    assert data[3] == 2                        # param length
    assert data[4] == 1                        # scan enable
    assert data[5] == 0                        # filter duplicates

def test_command_complete_event_decode():
    # HCI_Command_Complete for HCI_Reset: status=0
    raw = bytes([0x04, 0x0E, 0x04, 0x01, 0x03, 0x0C, 0x00])
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCI_Command_Complete_Event)
    assert pkt.num_hci_command_packets == 1
    assert pkt.command_opcode == HCI_RESET
    assert pkt.return_parameters == bytes([0x00])

def test_acl_data_encode_decode():
    pkt = HCIACLData(handle=0x0040, pb_flag=0x02, bc_flag=0x00, data=b"\x01\x02\x03")
    raw = pkt.to_bytes()
    assert raw[0] == 0x02                      # HCI ACL type
    handle_flags = struct.unpack_from("<H", raw, 1)[0]
    assert (handle_flags & 0x0FFF) == 0x0040
    assert ((handle_flags >> 12) & 0x03) == 0x02
    length = struct.unpack_from("<H", raw, 3)[0]
    assert length == 3
    assert raw[5:] == b"\x01\x02\x03"

def test_sco_data_encode():
    pkt = HCISCOData(handle=0x0001, packet_status=0, data=b"\xAB\xCD")
    raw = pkt.to_bytes()
    assert raw[0] == 0x03
    assert raw[4:] == b"\xAB\xCD"

def test_packet_registry_roundtrip():
    cmd = HCI_Reset()
    raw = cmd.to_bytes()
    decoded = decode_hci_packet(raw)
    assert type(decoded) is HCI_Reset

def test_unknown_event_decoded_as_base():
    raw = bytes([0x04, 0xFE, 0x02, 0x01, 0x02])
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCIEvent)
    assert pkt.event_code == 0xFE
    assert pkt.parameters == bytes([0x01, 0x02])

def test_le_meta_connection_complete():
    # LE Meta Event with LE Connection Complete sub-event
    sub_event = 0x01
    status = 0x00
    handle = 0x0001
    role = 0x00
    addr_type = 0x00
    addr = bytes(6)
    interval = 0x0028
    latency = 0x0000
    timeout = 0x00C8
    accuracy = 0x00
    params = struct.pack("<BBHBBBBHHHBx", sub_event, status, handle, role,
                         addr_type, *addr, interval, latency, timeout, accuracy)
    # actually simplified — just test sub-event routing
    raw = bytes([0x04, 0x3E, len(params)]) + params
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCI_LE_Meta_Event)
    assert pkt.subevent_code == 0x01
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `pybluehost/hci/packets.py`**

Key design:
- `HCIPacket` base with `to_bytes()` / `from_bytes()` class method
- `HCICommand(HCIPacket)`: H4 type=0x01, opcode(2 LE), param_len(1), parameters
- `HCIEvent(HCIPacket)`: H4 type=0x04, event_code(1), param_len(1), parameters
- `HCIACLData(HCIPacket)`: H4 type=0x02, handle+flags(2 LE), data_len(2 LE), data
- `HCISCOData(HCIPacket)`: H4 type=0x03, handle+status(2 LE), data_len(1), data
- `PacketRegistry`: dict from (packet_type, opcode/event_code) → class
- `decode_hci_packet(data: bytes) -> HCIPacket`: dispatcher
- Concrete command classes: `HCI_Reset`, `HCI_LE_Set_Scan_Enable`, etc.
- Concrete event classes: `HCI_Command_Complete_Event`, `HCI_Command_Status_Event`, `HCI_Connection_Complete_Event`, `HCI_Disconnection_Complete_Event`, `HCI_Number_Of_Completed_Packets_Event`, `HCI_LE_Meta_Event`, `HCI_LE_Connection_Complete_SubEvent`, `HCI_LE_Advertising_Report_SubEvent`

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**
```bash
git add pybluehost/hci/packets.py tests/unit/hci/test_packets.py
git commit -m "feat(hci): add HCI packet codec with PacketRegistry"
```

---

## Task 3: Flow Control

**Files:** `pybluehost/hci/flow.py`, `tests/unit/hci/test_flow.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/hci/test_flow.py
import asyncio
import pytest
from pybluehost.hci.flow import CommandFlowController, ACLFlowController
from pybluehost.hci.packets import HCIEvent, HCI_Command_Complete_Event

@pytest.mark.asyncio
async def test_command_flow_single_credit():
    ctrl = CommandFlowController(initial_credits=1)
    # First acquire should be immediate
    await asyncio.wait_for(ctrl.acquire(), timeout=0.1)

@pytest.mark.asyncio
async def test_command_flow_blocks_at_zero_credits():
    ctrl = CommandFlowController(initial_credits=1)
    await ctrl.acquire()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(ctrl.acquire(), timeout=0.05)

@pytest.mark.asyncio
async def test_command_flow_release_unblocks():
    ctrl = CommandFlowController(initial_credits=1)
    await ctrl.acquire()
    ctrl.release(1)
    await asyncio.wait_for(ctrl.acquire(), timeout=0.1)

@pytest.mark.asyncio
async def test_command_flow_future_resolve():
    ctrl = CommandFlowController(initial_credits=1)
    await ctrl.acquire()
    fut = ctrl.register(opcode=0x0C03)
    event = HCI_Command_Complete_Event(num_hci_command_packets=1,
                                        command_opcode=0x0C03,
                                        return_parameters=b"\x00")
    ctrl.resolve(0x0C03, event)
    result = await asyncio.wait_for(fut, timeout=0.1)
    assert result is event

def test_acl_flow_configure():
    ctrl = ACLFlowController()
    ctrl.configure(num_buffers=10, buffer_size=251)
    assert ctrl.available == 10
    assert ctrl.buffer_size == 251

@pytest.mark.asyncio
async def test_acl_flow_acquire_and_return():
    ctrl = ACLFlowController()
    ctrl.configure(num_buffers=2, buffer_size=251)
    await ctrl.acquire(handle=0x0001)
    await ctrl.acquire(handle=0x0001)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(ctrl.acquire(handle=0x0001), timeout=0.05)
    ctrl.on_num_completed({0x0001: 1})
    await asyncio.wait_for(ctrl.acquire(handle=0x0001), timeout=0.1)

def test_acl_segment():
    ctrl = ACLFlowController()
    ctrl.configure(num_buffers=10, buffer_size=4)
    data = bytes(range(10))
    segments = ctrl.segment(data)
    assert len(segments) == 3  # 4 + 4 + 2
    assert b"".join(s for s in segments) == data
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `pybluehost/hci/flow.py`**

```python
import asyncio
from dataclasses import dataclass, field
from pybluehost.hci.packets import HCIEvent

class CommandFlowController:
    def __init__(self, initial_credits: int = 1) -> None:
        self._credits = asyncio.Semaphore(initial_credits)
        self._pending: dict[int, asyncio.Future] = {}

    async def acquire(self) -> None:
        await self._credits.acquire()

    def release(self, num: int = 1) -> None:
        for _ in range(num):
            self._credits.release()

    def register(self, opcode: int) -> "asyncio.Future[HCIEvent]":
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[HCIEvent] = loop.create_future()
        self._pending[opcode] = fut
        return fut

    def resolve(self, opcode: int, event: HCIEvent) -> None:
        fut = self._pending.pop(opcode, None)
        if fut and not fut.done():
            fut.set_result(event)

class ACLFlowController:
    def __init__(self) -> None:
        self._sem: asyncio.Semaphore | None = None
        self._buffer_size: int = 0

    def configure(self, num_buffers: int, buffer_size: int) -> None:
        self._sem = asyncio.Semaphore(num_buffers)
        self._buffer_size = buffer_size

    @property
    def available(self) -> int:
        return self._sem._value if self._sem else 0

    @property
    def buffer_size(self) -> int:
        return self._buffer_size

    async def acquire(self, handle: int) -> None:
        if self._sem is None:
            raise RuntimeError("ACLFlowController not configured")
        await self._sem.acquire()

    def on_num_completed(self, completed: dict[int, int]) -> None:
        if self._sem is None:
            return
        for _, count in completed.items():
            for _ in range(count):
                self._sem.release()

    def segment(self, data: bytes) -> list[bytes]:
        size = self._buffer_size or len(data)
        return [data[i:i+size] for i in range(0, len(data), size)]
```

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**
```bash
git add pybluehost/hci/flow.py tests/unit/hci/test_flow.py
git commit -m "feat(hci): add CommandFlowController and ACLFlowController"
```

---

## Task 4: HCIController + ConnectionManager

**Files:** `pybluehost/hci/controller.py`, `tests/unit/hci/test_controller.py`

- [ ] **Step 1: Write failing tests using FakeTransport (including ConnectionManager tests)**

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

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `pybluehost/hci/controller.py`**

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

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Add `CommandTimeoutError` to `core/errors.py` if missing, then commit**
```bash
git add pybluehost/hci/controller.py tests/unit/hci/test_controller.py
git commit -m "feat(hci): add HCIController with command/ACL flow, event routing, and ConnectionManager"
```

---

## Task 5: VirtualController

**Files:** `pybluehost/hci/virtual.py`, `tests/unit/hci/test_virtual.py`

- [ ] **Step 1: Write failing tests**

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

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `pybluehost/hci/virtual.py`**

Design:
- `VirtualController(address: BDAddress)`
- `async def process(data: bytes) -> bytes | None`: decode command → dispatch to handler → return encoded event
- Handler registry: dict from opcode → async handler method
- Implement handlers: `HCI_Reset`, `HCI_Read_Local_Version`, `HCI_Read_BD_ADDR`, `HCI_Read_Buffer_Size`, `HCI_LE_Read_Buffer_Size`, `HCI_LE_Read_Local_Supported_Features`, `HCI_Set_Event_Mask`, `HCI_LE_Set_Event_Mask`, `HCI_Write_LE_Host_Supported`, `HCI_Read_Local_Supported_Commands`, `HCI_Read_Local_Supported_Features`, `HCI_Write_Simple_Pairing_Mode`
- Unknown opcode → `Command_Complete` with `UNKNOWN_COMMAND` status
- `connect_to(other: VirtualController)`: wire loopback for ACL

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**
```bash
git add pybluehost/hci/virtual.py tests/unit/hci/test_virtual.py
git commit -m "feat(hci): add VirtualController with basic command dispatch"
```

---

## Task 6: Package Exports + Final Tests

**Files:** `pybluehost/hci/__init__.py`, full test suite run

- [ ] **Step 1: Write `pybluehost/hci/__init__.py`**

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

- [ ] **Step 2: Run all HCI tests**
```bash
uv run pytest tests/unit/hci/ -v --tb=short
```

- [ ] **Step 3: Run full test suite — no regressions**
```bash
uv run pytest tests/ -v --tb=short
```

- [ ] **Step 4: Commit**
```bash
git add pybluehost/hci/__init__.py
git commit -m "feat(hci): finalize HCI package exports"
```

---

## Task 7: Vendor Constants

**Files:** Create `pybluehost/hci/vendor/__init__.py`, `pybluehost/hci/vendor/intel.py`, `pybluehost/hci/vendor/realtek.py`

These vendor modules are consumed by `USBTransport` (Plan 2.5) during firmware loading.
They re-use `make_opcode` and `OGF.VENDOR` from `constants.py` so that opcodes are
guaranteed to match the bit layout expected by `PacketRegistry`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/hci/test_vendor.py
import struct
from pybluehost.hci.vendor.intel import (
    HCI_VS_INTEL_READ_VERSION,
    HCI_VS_INTEL_WRITE_FIRMWARE,
    INTEL_TLV_TYPE_CNV,
    INTEL_TLV_TYPE_TIMESTAMP,
    IntelReadVersionResponse,
)
from pybluehost.hci.vendor.realtek import (
    HCI_VS_REALTEK_READ_ROM_VERSION,
    HCI_VS_REALTEK_WRITE_FIRMWARE,
    RealtekROMVersion,
)
from pybluehost.hci.constants import OGF, make_opcode


# --- Intel opcode values ---

def test_intel_read_version_opcode():
    # OGF=0x3F, OCF=0x05 → (0x3F << 10) | 0x05 = 0xFC05
    assert HCI_VS_INTEL_READ_VERSION == 0xFC05

def test_intel_write_firmware_opcode():
    # OGF=0x3F, OCF=0x20 → (0x3F << 10) | 0x20 = 0xFC20
    assert HCI_VS_INTEL_WRITE_FIRMWARE == 0xFC20

def test_intel_opcodes_use_vendor_ogf():
    assert (HCI_VS_INTEL_READ_VERSION >> 10) & 0x3F == int(OGF.VENDOR)
    assert (HCI_VS_INTEL_WRITE_FIRMWARE >> 10) & 0x3F == int(OGF.VENDOR)

def test_intel_tlv_constants():
    assert INTEL_TLV_TYPE_CNV == 0x10
    assert INTEL_TLV_TYPE_TIMESTAMP == 0x18


# --- Intel IntelReadVersionResponse dataclass ---

def test_intel_read_version_response_fields():
    resp = IntelReadVersionResponse(
        status=0x00,
        hw_platform=0x37,
        hw_variant=0x17,
        hw_revision=0x00,
        fw_variant=0x23,
        fw_revision=0x10,
        fw_build_num=0x00,
        fw_build_week=0x27,
        fw_build_year=0x19,
        fw_patch_num=0x00,
    )
    assert resp.status == 0x00
    assert resp.hw_platform == 0x37
    assert resp.hw_variant == 0x17
    assert resp.fw_variant == 0x23
    assert resp.fw_build_week == 0x27
    assert resp.fw_build_year == 0x19

def test_intel_read_version_response_from_bytes():
    # status(1) + hw_platform(1) + hw_variant(1) + hw_revision(1)
    # + fw_variant(1) + fw_revision(1) + fw_build_num(1)
    # + fw_build_week(1) + fw_build_year(1) + fw_patch_num(1)
    raw = bytes([0x00, 0x37, 0x17, 0x00, 0x23, 0x10, 0x00, 0x27, 0x19, 0x00])
    resp = IntelReadVersionResponse.from_bytes(raw)
    assert resp.status == 0x00
    assert resp.hw_platform == 0x37
    assert resp.hw_variant == 0x17
    assert resp.fw_build_week == 0x27
    assert resp.fw_build_year == 0x19
    assert resp.fw_patch_num == 0x00


# --- Realtek opcode values ---

def test_realtek_read_rom_version_opcode():
    # OGF=0x3F, OCF=0x6D → (0x3F << 10) | 0x6D = 0xFC6D
    assert HCI_VS_REALTEK_READ_ROM_VERSION == 0xFC6D

def test_realtek_write_firmware_opcode():
    # OGF=0x3F, OCF=0x20 → 0xFC20 (same OCF as Intel write firmware)
    assert HCI_VS_REALTEK_WRITE_FIRMWARE == 0xFC20

def test_realtek_opcodes_use_vendor_ogf():
    assert (HCI_VS_REALTEK_READ_ROM_VERSION >> 10) & 0x3F == int(OGF.VENDOR)
    assert (HCI_VS_REALTEK_WRITE_FIRMWARE >> 10) & 0x3F == int(OGF.VENDOR)


# --- Realtek RealtekROMVersion dataclass ---

def test_realtek_rom_version_fields():
    rv = RealtekROMVersion(status=0x00, rom_version=0x000E)
    assert rv.status == 0x00
    assert rv.rom_version == 0x000E

def test_realtek_rom_version_from_bytes():
    # status(1) + rom_version(2 LE)
    raw = bytes([0x00, 0x0E, 0x00])
    rv = RealtekROMVersion.from_bytes(raw)
    assert rv.status == 0x00
    assert rv.rom_version == 0x000E

def test_realtek_rom_version_from_bytes_nonzero_status():
    raw = bytes([0x01, 0x00, 0x00])
    rv = RealtekROMVersion.from_bytes(raw)
    assert rv.status == 0x01
    assert rv.rom_version == 0x0000
```

- [ ] **Step 2: Run tests — verify they fail**
```bash
uv run pytest tests/unit/hci/test_vendor.py -v
```

- [ ] **Step 3: Implement `pybluehost/hci/vendor/__init__.py`**

```python
# pybluehost/hci/vendor/__init__.py
from pybluehost.hci.vendor.intel import (
    HCI_VS_INTEL_READ_VERSION,
    HCI_VS_INTEL_WRITE_FIRMWARE,
    INTEL_TLV_TYPE_CNV,
    INTEL_TLV_TYPE_TIMESTAMP,
    IntelReadVersionResponse,
)
from pybluehost.hci.vendor.realtek import (
    HCI_VS_REALTEK_READ_ROM_VERSION,
    HCI_VS_REALTEK_WRITE_FIRMWARE,
    RealtekROMVersion,
)

__all__ = [
    "HCI_VS_INTEL_READ_VERSION",
    "HCI_VS_INTEL_WRITE_FIRMWARE",
    "INTEL_TLV_TYPE_CNV",
    "INTEL_TLV_TYPE_TIMESTAMP",
    "IntelReadVersionResponse",
    "HCI_VS_REALTEK_READ_ROM_VERSION",
    "HCI_VS_REALTEK_WRITE_FIRMWARE",
    "RealtekROMVersion",
]
```

- [ ] **Step 4: Implement `pybluehost/hci/vendor/intel.py`**

```python
# pybluehost/hci/vendor/intel.py
"""Intel Bluetooth vendor-specific HCI constants and response parsers.

These opcodes are used by USBTransport during firmware loading (Plan 2.5).
All opcodes use OGF=0x3F (VENDOR) as per Bluetooth Core Spec Vol 4, Part E §7.6.
"""
from __future__ import annotations
import struct
from dataclasses import dataclass

from pybluehost.hci.constants import OGF, make_opcode

# Vendor opcodes
# OGF=0x3F, OCF=0x05 → 0xFC05
HCI_VS_INTEL_READ_VERSION: int = make_opcode(OGF.VENDOR, 0x05)
# OGF=0x3F, OCF=0x20 → 0xFC20
HCI_VS_INTEL_WRITE_FIRMWARE: int = make_opcode(OGF.VENDOR, 0x20)

# TLV type constants used in Intel firmware secure boot packets
INTEL_TLV_TYPE_CNV: int = 0x10        # Connectivity Version (CNVi/CNVr)
INTEL_TLV_TYPE_TIMESTAMP: int = 0x18  # Firmware build timestamp


@dataclass
class IntelReadVersionResponse:
    """Parsed return parameters of HCI_VS_Intel_Read_Version (0xFC05).

    The 10-byte return parameter layout (after stripping the H4/HCI header)
    matches the format documented in the Intel ibt-firmware project and the
    Linux kernel drivers/bluetooth/btintel.h IntelVersion struct.

    Fields
    ------
    status        : HCI error code (0x00 = success)
    hw_platform   : Hardware platform ID (e.g. 0x37 = ThunderPeak)
    hw_variant    : Hardware variant
    hw_revision   : Hardware revision
    fw_variant    : Firmware variant (0x06 = bootloader, 0x23 = operational)
    fw_revision   : Firmware revision
    fw_build_num  : Firmware build number
    fw_build_week : Firmware build week (BCD)
    fw_build_year : Firmware build year (BCD, relative to 2000)
    fw_patch_num  : Applied patch number
    """
    status: int
    hw_platform: int
    hw_variant: int
    hw_revision: int
    fw_variant: int
    fw_revision: int
    fw_build_num: int
    fw_build_week: int
    fw_build_year: int
    fw_patch_num: int

    # Wire format: 10 bytes, all uint8
    _FORMAT = "<BBBBBBBBBB"
    _SIZE = struct.calcsize(_FORMAT)  # 10

    @classmethod
    def from_bytes(cls, data: bytes) -> "IntelReadVersionResponse":
        """Parse raw return_parameters bytes from a Command Complete event."""
        if len(data) < cls._SIZE:
            raise ValueError(
                f"IntelReadVersionResponse requires {cls._SIZE} bytes, got {len(data)}"
            )
        fields = struct.unpack_from(cls._FORMAT, data)
        return cls(
            status=fields[0],
            hw_platform=fields[1],
            hw_variant=fields[2],
            hw_revision=fields[3],
            fw_variant=fields[4],
            fw_revision=fields[5],
            fw_build_num=fields[6],
            fw_build_week=fields[7],
            fw_build_year=fields[8],
            fw_patch_num=fields[9],
        )

    def to_bytes(self) -> bytes:
        """Serialize back to wire format (useful for VirtualController stubs)."""
        return struct.pack(
            self._FORMAT,
            self.status,
            self.hw_platform,
            self.hw_variant,
            self.hw_revision,
            self.fw_variant,
            self.fw_revision,
            self.fw_build_num,
            self.fw_build_week,
            self.fw_build_year,
            self.fw_patch_num,
        )
```

- [ ] **Step 5: Implement `pybluehost/hci/vendor/realtek.py`**

```python
# pybluehost/hci/vendor/realtek.py
"""Realtek Bluetooth vendor-specific HCI constants and response parsers.

These opcodes are used by USBTransport during firmware loading (Plan 2.5).
All opcodes use OGF=0x3F (VENDOR) as per Bluetooth Core Spec Vol 4, Part E §7.6.
"""
from __future__ import annotations
import struct
from dataclasses import dataclass

from pybluehost.hci.constants import OGF, make_opcode

# Vendor opcodes
# OGF=0x3F, OCF=0x6D → 0xFC6D
HCI_VS_REALTEK_READ_ROM_VERSION: int = make_opcode(OGF.VENDOR, 0x6D)
# OGF=0x3F, OCF=0x20 → 0xFC20  (chunk-based firmware upload)
HCI_VS_REALTEK_WRITE_FIRMWARE: int = make_opcode(OGF.VENDOR, 0x20)


@dataclass
class RealtekROMVersion:
    """Parsed return parameters of HCI_VS_Realtek_Read_ROM_Version (0xFC6D).

    The 3-byte return parameter layout matches the format documented in
    the Linux kernel drivers/bluetooth/btrtl.h rtl_rom_version_evt struct.

    Fields
    ------
    status      : HCI error code (0x00 = success)
    rom_version : ROM version number (uint16 LE), e.g. 0x000E for RTL8761B
    """
    status: int
    rom_version: int  # uint16 LE

    _FORMAT = "<BH"
    _SIZE = struct.calcsize(_FORMAT)  # 3

    @classmethod
    def from_bytes(cls, data: bytes) -> "RealtekROMVersion":
        """Parse raw return_parameters bytes from a Command Complete event."""
        if len(data) < cls._SIZE:
            raise ValueError(
                f"RealtekROMVersion requires {cls._SIZE} bytes, got {len(data)}"
            )
        status, rom_version = struct.unpack_from(cls._FORMAT, data)
        return cls(status=status, rom_version=rom_version)

    def to_bytes(self) -> bytes:
        """Serialize back to wire format (useful for VirtualController stubs)."""
        return struct.pack(self._FORMAT, self.status, self.rom_version)
```

- [ ] **Step 6: Run tests — verify they pass**
```bash
uv run pytest tests/unit/hci/test_vendor.py -v
```

- [ ] **Step 7: Commit**
```bash
git add pybluehost/hci/vendor/ tests/unit/hci/test_vendor.py
git commit -m "feat(hci): add vendor subpackage with Intel and Realtek constants"
```

---

## Task 8: HCI Init Sequence Integration Test

**Files:** Create `tests/integration/__init__.py` (if absent), `tests/integration/test_hci_init.py`

This test wires a real `HCIController` to a `VirtualController` via a `LoopbackTransport`
and verifies that `controller.initialize()` issues all 16 mandatory init commands.
It serves as a smoke test that the full HCI stack can come up without errors.

- [ ] **Step 1: Write the integration test**

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

- [ ] **Step 2: Run the integration test — verify it fails (initialize() not yet implemented)**
```bash
uv run pytest tests/integration/test_hci_init.py -v
```

- [ ] **Step 3: Implement `HCIController.initialize()` in `controller.py`**

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

- [ ] **Step 4: Run the integration test — verify it passes**
```bash
uv run pytest tests/integration/test_hci_init.py -v
```

- [ ] **Step 5: Run the full test suite — no regressions**
```bash
uv run pytest tests/ -v --tb=short
```

- [ ] **Step 6: Commit**
```bash
git add tests/integration/ pybluehost/hci/controller.py
git commit -m "test(hci): add integration test for HCI init sequence (16 commands)"
```

- [ ] **Step 7: Update STATUS.md — mark Plan 3 complete**

Edit `docs/superpowers/STATUS.md`: change Plan 3 from 🔄 to ✅, set Plan 4 as current.

```bash
git add docs/superpowers/STATUS.md
git commit -m "docs: mark Plan 3 (HCI) complete in STATUS.md"
```

---

## 审查补充事项 (2026-04-18 审查后追加)

以下事项在深度审查中发现遗漏，需要在执行时补充到对应 Task 中。

### 补充 1: HCI ISO Data 解析（PRD §5.2, 架构 07-hci.md §7.3）

需要在 packets.py 中增加 `HCIISOData` 数据类：

```python
@dataclass
class HCIISOData:
    handle: int        # 12 bits
    pb_flag: int       # 2 bits
    ts_flag: int       # 1 bit
    data_length: int   # 14 bits
    timestamp: int | None  # optional, 4 bytes if ts_flag=1
    sequence_number: int | None  # optional
    payload: bytes
```

v1.0 不实现上层 ISO 逻辑，但需要：
- 在 `on_transport_data` 中识别 indicator 0x05 并解析
- emit TraceEvent 记录
- 增加 ISO 数据包的 encode/decode 往返测试

### 补充 2: SCO 数据路由测试（架构 07-hci.md §7.4）

`HCIController.on_transport_data` 的 `case 0x03` 分支需要测试：
- SCO 数据能正确路由到 `HCIUpstream.on_sco_data()` 回调
- connection handle 匹配/不匹配时的行为

### 补充 3: Vendor 子包实现和测试

`hci/vendor/intel.py` 和 `hci/vendor/realtek.py` 在文件结构中列出但无对应 Task。需要补充：
- Intel Vendor Event 解析（用于固件加载响应）
- Realtek Vendor Event 解析
- Vendor event 路由机制（VendorEventRouter 或 EventRouter 的扩展）

### 补充 4: TransportSource 引用修正

Plan 中 `HCIController.__init__` 签名使用 `transport: TransportSource`，但 `TransportSource` 类不存在于实际代码中。应改为：

```python
def __init__(self, transport: Transport, trace: TraceSystem) -> None:
```

其中 `Transport` 从 `pybluehost.transport.base` 导入。HCIController 同时作为 TransportSink（实现 `on_transport_data` 和 `on_transport_error`）。

### 补充 5: TransportSink 接口已更新

**注意**：TransportSink 方法已从 `on_data` 重命名为 `on_transport_data`（2026-04-18）。Plan 中实现 TransportSink 的类需使用新名称。同时 TransportSink 新增了 `on_transport_error(error: TransportError)` 方法。

### 补充 6: HCI_LE_Meta_Event struct.pack 格式修正

测试代码中 `struct.pack("<BBHBBBBBBHHHBx", ...)` 的地址字段应使用 `6s` 格式而非 6 个独立 `B`，以匹配 `bytes(6)` 参数：

```python
struct.pack("<BBH6sHHHBx", subevent, num_reports, event_type, addr_bytes, ...)
```

### 补充 7: 拆分建议

建议将本 Plan 拆分为：
- **Plan 4a — HCI Packet Codec + Flow Control**: constants.py, packets.py（全部 packet 类型 + PacketRegistry + HCIISOData）, flow.py, vendor/intel.py, vendor/realtek.py。纯数据处理，无 asyncio 依赖。
- **Plan 4b — HCI Controller + VirtualController**: controller.py（HCIController + EventRouter + ConnectionManager + 16 步初始化序列）, virtual.py。有状态逻辑 + asyncio。

拆分依据：Packet Codec 是纯 bytes↔dataclass 转换，Controller 涉及状态机和异步 IO，技术风险不同。
