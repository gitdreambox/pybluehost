# Plan 4a: HCI Packet Codec + Flow Control

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement `pybluehost/hci/` — HCI constants, packet encode/decode, PacketRegistry, flow control, and vendor constants. Pure data processing, no asyncio state machines. This layer sits between `transport/` and `l2cap/`, providing the codec and flow primitives consumed by Plan 4b's HCIController.

**Architecture reference:** `docs/architecture/07-hci.md`, `docs/architecture/02-sap.md`

**Dependencies:** `pybluehost/core/`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/hci/__init__.py` | Re-export public HCI API |
| `pybluehost/hci/constants.py` | OGF/OCF opcodes, event codes, error codes, LE meta sub-event codes |
| `pybluehost/hci/packets.py` | `HCIPacket` hierarchy + `PacketRegistry` decode |
| `pybluehost/hci/flow.py` | `CommandFlowController` + `ACLFlowController` |
| `pybluehost/hci/vendor/__init__.py` | Re-export vendor subpackage |
| `pybluehost/hci/vendor/intel.py` | Intel vendor opcodes, TLV constants, `IntelReadVersionResponse` |
| `pybluehost/hci/vendor/realtek.py` | Realtek vendor opcodes, `RealtekROMVersion` |
| `tests/unit/hci/__init__.py` | |
| `tests/unit/hci/test_constants.py` | Opcode construction, error code values |
| `tests/unit/hci/test_packets.py` | Encode/decode round-trips for all packet types |
| `tests/unit/hci/test_flow.py` | Command credit semaphore, ACL flow control |

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
- `HCIISOData(HCIPacket)`: H4 type=0x05 (see 补充 1 below)
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

## Task 4: Vendor Constants

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

## 审查补充事项 (applicable to Plan 4a)

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

### 补充 5: TransportSink 接口已更新

**注意**：TransportSink 方法已从 `on_data` 重命名为 `on_transport_data`（2026-04-18）。Plan 中实现 TransportSink 的类需使用新名称。同时 TransportSink 新增了 `on_transport_error(error: TransportError)` 方法。

### 补充 6: HCI_LE_Meta_Event struct.pack 格式修正

测试代码中 `struct.pack("<BBHBBBBBBHHHBx", ...)` 的地址字段应使用 `6s` 格式而非 6 个独立 `B`，以匹配 `bytes(6)` 参数：

```python
struct.pack("<BBH6sHHHBx", subevent, num_reports, event_type, addr_bytes, ...)
```
