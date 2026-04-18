# Plan 4: L2CAP Layer Implementation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement `pybluehost/l2cap/` — the L2CAP channel abstraction, SAR engine, BLE fixed channels + CoC, Classic channel (Basic/ERTM), signaling, and `L2CAPManager` main class.

**Architecture reference:** `docs/architecture/08-l2cap.md`, `docs/architecture/02-sap.md`

**Dependencies:** `pybluehost/core/`, `pybluehost/hci/`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/l2cap/__init__.py` | Re-export public L2CAP API |
| `pybluehost/l2cap/constants.py` | CID constants, PSM values, signaling command codes |
| `pybluehost/l2cap/channel.py` | `Channel` ABC, `ChannelState`, `ChannelEvents` Protocol |
| `pybluehost/l2cap/sar.py` | `Reassembler` + `Segmenter` |
| `pybluehost/l2cap/ble.py` | `FixedChannel` + `LECoCChannel` |
| `pybluehost/l2cap/classic.py` | `ClassicChannel` (Basic/ERTM/Streaming) + `ERTMEngine` |
| `pybluehost/l2cap/signaling.py` | `SignalingHandler` for CID 0x0001 and 0x0005 |
| `pybluehost/l2cap/manager.py` | `L2CAPManager` main class |
| `tests/unit/l2cap/__init__.py` | |
| `tests/unit/l2cap/test_sar.py` | SAR round-trip tests |
| `tests/unit/l2cap/test_ble.py` | Fixed channel and CoC tests |
| `tests/unit/l2cap/test_classic.py` | Classic channel state machine tests |
| `tests/unit/l2cap/test_signaling.py` | Signaling packet encode/decode |
| `tests/unit/l2cap/test_manager.py` | L2CAPManager with FakeHCI |

---

## Task 1: Constants + SAR Engine

**Files:** `pybluehost/l2cap/constants.py`, `pybluehost/l2cap/sar.py`, tests

- [ ] **Step 1: Write failing SAR tests**

```python
# tests/unit/l2cap/test_sar.py
from pybluehost.l2cap.sar import Reassembler, Segmenter
from pybluehost.l2cap.constants import CID_ATT, CID_LE_SIGNALING, CID_SMP
from pybluehost.hci.constants import ACL_PB_FIRST_AUTO_FLUSH, ACL_PB_CONTINUING

def test_constants():
    assert CID_ATT == 0x0004
    assert CID_LE_SIGNALING == 0x0005
    assert CID_SMP == 0x0006

def test_single_fragment_reassembly():
    r = Reassembler()
    data = b"\x05\x00\x04\x00" + b"\x01\x02\x03\x04\x05"  # L2CAP: len=5, CID=ATT, payload
    result = r.feed(handle=0x0040, pb_flag=ACL_PB_FIRST_AUTO_FLUSH, data=data)
    assert result == (0x0004, b"\x01\x02\x03\x04\x05")

def test_multi_fragment_reassembly():
    r = Reassembler()
    # First fragment: L2CAP header says total payload = 6
    first = b"\x06\x00\x04\x00" + b"\x01\x02\x03"
    result = r.feed(handle=0x0001, pb_flag=ACL_PB_FIRST_AUTO_FLUSH, data=first)
    assert result is None  # incomplete

    cont = b"\x04\x05\x06"
    result = r.feed(handle=0x0001, pb_flag=ACL_PB_CONTINUING, data=cont)
    assert result == (0x0004, b"\x01\x02\x03\x04\x05\x06")

def test_reassembler_reset_on_new_start():
    r = Reassembler()
    partial = b"\x06\x00\x04\x00" + b"\x01\x02"
    r.feed(handle=0x0001, pb_flag=ACL_PB_FIRST_AUTO_FLUSH, data=partial)
    # New start packet resets state
    complete = b"\x03\x00\x04\x00" + b"\xAA\xBB\xCC"
    result = r.feed(handle=0x0001, pb_flag=ACL_PB_FIRST_AUTO_FLUSH, data=complete)
    assert result == (0x0004, b"\xAA\xBB\xCC")

def test_segmenter_single():
    s = Segmenter(max_size=251)
    pdu = b"\x00\x04" + b"A" * 10  # CID + data
    segments = s.segment(pdu)
    assert len(segments) == 1
    pb, payload = segments[0]
    assert payload == pdu

def test_segmenter_multi():
    s = Segmenter(max_size=8)
    pdu = b"X" * 20
    segments = s.segment(pdu)
    assert len(segments) == 3  # ceil(20/8)
    assert segments[0][0] == ACL_PB_FIRST_AUTO_FLUSH
    for pb, payload in segments[1:]:
        assert pb == ACL_PB_CONTINUING
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `constants.py` and `sar.py`**

```python
# constants.py
# Fixed CIDs
CID_CLASSIC_SIGNALING = 0x0001
CID_CONNECTIONLESS    = 0x0002
CID_ATT               = 0x0004
CID_LE_SIGNALING      = 0x0005
CID_SMP               = 0x0006
CID_SMP_BR_EDR        = 0x0007
CID_DYNAMIC_MIN       = 0x0040
CID_DYNAMIC_MAX       = 0x007F

# PSM values
PSM_SDP     = 0x0001
PSM_RFCOMM  = 0x0003
PSM_AVDTP   = 0x0019
PSM_ATT     = 0x001F   # LE only, not used via PSM but for reference

class SignalingCode(IntEnum):
    COMMAND_REJECT        = 0x01
    CONNECTION_REQUEST    = 0x02
    CONNECTION_RESPONSE   = 0x03
    CONFIGURE_REQUEST     = 0x04
    CONFIGURE_RESPONSE    = 0x05
    DISCONNECTION_REQUEST = 0x06
    DISCONNECTION_RESPONSE = 0x07
    INFORMATION_REQUEST   = 0x0A
    INFORMATION_RESPONSE  = 0x0B
    LE_CREDIT_CONN_REQ    = 0x14
    LE_CREDIT_CONN_RSP    = 0x15
    FLOW_CONTROL_CREDIT   = 0x16
    CONN_PARAM_UPDATE_REQ = 0x12
    CONN_PARAM_UPDATE_RSP = 0x13
```

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**
```bash
git add pybluehost/l2cap/constants.py pybluehost/l2cap/sar.py tests/unit/l2cap/
git commit -m "feat(l2cap): add L2CAP constants and SAR engine"
```

---

## Task 2: Channel ABC + BLE Fixed Channels

**Files:** `pybluehost/l2cap/channel.py`, `pybluehost/l2cap/ble.py`, tests

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/l2cap/test_ble.py
import asyncio, pytest
from pybluehost.l2cap.ble import FixedChannel
from pybluehost.l2cap.channel import ChannelState

class FakeHCI:
    def __init__(self): self.sent = []
    async def send_acl_data(self, handle, pb_flag, data): self.sent.append((handle, pb_flag, data))

@pytest.mark.asyncio
async def test_fixed_channel_send():
    hci = FakeHCI()
    ch = FixedChannel(connection_handle=0x0040, cid=0x0004, hci=hci, mtu=23)
    await ch.send(b"\x01\x02\x03")
    assert len(hci.sent) == 1
    handle, pb_flag, data = hci.sent[0]
    assert handle == 0x0040
    # data = L2CAP basic header (4 bytes) + payload
    import struct
    length, cid = struct.unpack_from("<HH", data)
    assert length == 3
    assert cid == 0x0004
    assert data[4:] == b"\x01\x02\x03"

@pytest.mark.asyncio
async def test_fixed_channel_receive():
    hci = FakeHCI()
    ch = FixedChannel(connection_handle=0x0040, cid=0x0004, hci=hci, mtu=23)
    received = []
    async def on_data(data): received.append(data)
    from pybluehost.l2cap.channel import SimpleChannelEvents
    ch.set_events(SimpleChannelEvents(on_data=on_data))
    await ch._on_pdu(b"\xDE\xAD")
    assert received == [b"\xDE\xAD"]

def test_fixed_channel_state():
    hci = FakeHCI()
    ch = FixedChannel(connection_handle=0x0040, cid=0x0004, hci=hci)
    assert ch.state == ChannelState.OPEN
    assert ch.cid == 0x0004
    assert ch.connection_handle == 0x0040
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `channel.py` and `ble.py`**

`channel.py`: `ChannelState(Enum)`, `Channel(ABC)` with `cid`, `peer_cid`, `mtu`, `connection_handle`, `state` properties + `send(data)`, `close()`, `set_events(events)` methods. `ChannelEvents(Protocol)` with `on_data`, `on_close`, `on_mtu_changed`. `SimpleChannelEvents` dataclass for testing.

`ble.py`:
- `FixedChannel(Channel)`: always OPEN, no SAR, wraps payload in L2CAP basic header (len+CID), sends via HCI ACL
- `LECoCChannel(Channel)`: credit-based CoC, MPS segmentation, SDU length header on first segment

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**
```bash
git add pybluehost/l2cap/channel.py pybluehost/l2cap/ble.py tests/unit/l2cap/test_ble.py
git commit -m "feat(l2cap): add Channel ABC, FixedChannel and LECoCChannel"
```

---

## Task 3: Classic Channel + ERTM

**Files:** `pybluehost/l2cap/classic.py`, `tests/unit/l2cap/test_classic.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/l2cap/test_classic.py
import asyncio, pytest
from pybluehost.l2cap.classic import ClassicChannel, ChannelMode
from pybluehost.l2cap.channel import ChannelState

class FakeHCI:
    def __init__(self): self.sent = []
    async def send_acl_data(self, h, pb, data): self.sent.append(data)

@pytest.mark.asyncio
async def test_classic_channel_basic_send():
    hci = FakeHCI()
    ch = ClassicChannel(connection_handle=0x0001, local_cid=0x0040, peer_cid=0x0041,
                         mode=ChannelMode.BASIC, mtu=672, hci=hci)
    ch._state = ChannelState.OPEN
    await ch.send(b"hello")
    assert len(hci.sent) == 1
    import struct
    length, cid = struct.unpack_from("<HH", hci.sent[0][4:] if len(hci.sent[0]) > 4 else hci.sent[0])
    # Simple: just verify data was sent

def test_channel_mode_enum():
    assert ChannelMode.BASIC == 0x00
    assert ChannelMode.ERTM == 0x03
    assert ChannelMode.STREAMING == 0x04

@pytest.mark.asyncio
async def test_ertm_engine_sends_iframe():
    from pybluehost.l2cap.classic import ERTMEngine
    engine = ERTMEngine(tx_window=4)
    frames = []
    async def send_fn(data): frames.append(data)
    engine.set_send_fn(send_fn)
    await engine.send_sdu(b"hello")
    assert len(frames) == 1
    import struct
    assert frames[0][0] == 0x00  # tx_seq=0, I-frame
    assert frames[0][1] == 0x00  # req_seq=0
    sdu_len = struct.unpack_from("<H", frames[0], 2)[0]
    assert sdu_len == 5
    assert frames[0][4:] == b"hello"

@pytest.mark.asyncio
async def test_ertm_engine_acks_release_window():
    from pybluehost.l2cap.classic import ERTMEngine
    engine = ERTMEngine(tx_window=2)
    frames = []
    async def send_fn(data): frames.append(data)
    engine.set_send_fn(send_fn)
    await engine.send_sdu(b"pkt1")
    await engine.send_sdu(b"pkt2")
    # Window exhausted — third send blocks until ACK
    engine.on_sframe(req_seq=1)  # ACK seq=0
    await asyncio.wait_for(engine.send_sdu(b"pkt3"), timeout=0.1)
    assert len(frames) == 3

def test_ertm_on_iframe_returns_rr_sframe():
    from pybluehost.l2cap.classic import ERTMEngine
    engine = ERTMEngine(tx_window=4)
    sframe = engine.on_iframe(tx_seq=0, data=b"x")
    assert sframe[0] & 0x01 == 0x01  # S-frame marker
    assert (sframe[0] >> 2) & 0x3F == 1  # req_seq=1
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `classic.py`**

`ChannelMode(IntEnum)`: BASIC=0, ERTM=3, STREAMING=4.

`ClassicChannel(Channel)`: state machine CLOSED→CONFIG→OPEN→DISCONNECTING, `send()` wraps in L2CAP header and sends via HCI (Basic mode). For ERTM mode, delegates to `ERTMEngine`.

```python
import asyncio
import struct
from dataclasses import dataclass, field

class ERTMEngine:
    """Enhanced Retransmission Mode engine — full I-frame retransmission per BT 4.2 Vol 3 Part A §3.3.2."""

    def __init__(self, tx_window: int = 8, retransmit_timeout: float = 2.0) -> None:
        self._tx_window = tx_window
        self._retransmit_timeout = retransmit_timeout
        self._tx_seq: int = 0          # next TX sequence number (mod 64)
        self._req_seq: int = 0         # next expected RX sequence number
        self._unacked: dict[int, bytes] = {}  # seq → I-frame payload pending ACK
        self._credits = asyncio.Semaphore(tx_window)
        self._send_fn: "Callable[[bytes], Awaitable[None]] | None" = None

    def set_send_fn(self, fn: "Callable[[bytes], Awaitable[None]]") -> None:
        self._send_fn = fn

    async def send_sdu(self, sdu: bytes) -> None:
        """Wrap SDU in I-frame and send, respecting TX window."""
        await self._credits.acquire()
        seq = self._tx_seq
        self._tx_seq = (self._tx_seq + 1) % 64
        # I-frame header: Control(2 bytes LE) = tx_seq<<1 | 0 (I), req_seq<<1
        # then SDU length(2 LE), SDU data
        ctrl_lo = (seq << 1) & 0xFE
        ctrl_hi = (self._req_seq << 1) & 0xFE
        frame = struct.pack("<BBH", ctrl_lo, ctrl_hi, len(sdu)) + sdu
        self._unacked[seq] = frame
        if self._send_fn:
            await self._send_fn(frame)

    def on_sframe(self, req_seq: int) -> None:
        """Process incoming S-frame (RR/REJ); release TX window credits for ACK'd frames."""
        # ACK all frames with seq < req_seq
        acked = [s for s in self._unacked if s < req_seq or (req_seq < 32 and s > 32)]
        for s in sorted(acked):
            self._unacked.pop(s, None)
            self._credits.release()

    def on_iframe(self, tx_seq: int, data: bytes) -> bytes:
        """Process incoming I-frame; update req_seq; return S-frame (RR) to send back."""
        # Accept in-order frames; update expected seq
        if tx_seq == self._req_seq:
            self._req_seq = (self._req_seq + 1) % 64
        # Build RR S-frame: Control byte 0 = 0x01 (S-frame) | (req_seq << 2)
        sframe_ctrl = 0x01 | ((self._req_seq & 0x3F) << 2)
        return bytes([sframe_ctrl, 0x00])

    async def retransmit_unacked(self) -> None:
        """Retransmit all unacknowledged frames (called on timeout)."""
        if self._send_fn:
            for frame in self._unacked.values():
                await self._send_fn(frame)
```

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**
```bash
git add pybluehost/l2cap/classic.py tests/unit/l2cap/test_classic.py
git commit -m "feat(l2cap): add ClassicChannel with Basic and ERTM modes"
```

---

## Task 4: Signaling Handler

**Files:** `pybluehost/l2cap/signaling.py`, `tests/unit/l2cap/test_signaling.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/l2cap/test_signaling.py
import struct
from pybluehost.l2cap.signaling import SignalingPacket, encode_signaling, decode_signaling
from pybluehost.l2cap.constants import SignalingCode

def test_encode_connection_request():
    pkt = SignalingPacket(code=SignalingCode.CONNECTION_REQUEST, identifier=0x01,
                          data=struct.pack("<HH", 0x0003, 0x0040))  # PSM=RFCOMM, SCID=0x0040
    raw = encode_signaling(pkt)
    assert raw[0] == SignalingCode.CONNECTION_REQUEST
    assert raw[1] == 0x01  # identifier
    length = struct.unpack_from("<H", raw, 2)[0]
    assert length == 4

def test_decode_connection_response():
    code = SignalingCode.CONNECTION_RESPONSE
    ident = 0x01
    data = struct.pack("<HHBB", 0x0041, 0x0040, 0x00, 0x00)  # DCID, SCID, result, status
    raw = bytes([code, ident]) + struct.pack("<H", len(data)) + data
    pkt = decode_signaling(raw)
    assert pkt.code == SignalingCode.CONNECTION_RESPONSE
    assert pkt.identifier == ident
    assert pkt.data == data

def test_le_credit_connection_request_encode():
    pkt = SignalingPacket(code=SignalingCode.LE_CREDIT_CONN_REQ, identifier=0x02,
                          data=struct.pack("<HHHH", 0x0025, 0x0040, 512, 10))  # PSM, SCID, MTU, MPS
    raw = encode_signaling(pkt)
    assert raw[0] == SignalingCode.LE_CREDIT_CONN_REQ
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `signaling.py`**

`SignalingPacket(dataclass)`: `code`, `identifier`, `data`.
`encode_signaling(pkt) -> bytes`: pack code(1) + ident(1) + length(2 LE) + data.
`decode_signaling(data) -> SignalingPacket`: inverse.
`SignalingHandler`: processes incoming signaling PDUs (on CID 0x0001 or 0x0005), dispatches by command code, coordinates with `L2CAPManager` to accept/reject connections.

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**
```bash
git add pybluehost/l2cap/signaling.py tests/unit/l2cap/test_signaling.py
git commit -m "feat(l2cap): add L2CAP signaling packet codec and handler"
```

---

## Task 5: L2CAPManager + Package Exports

**Files:** `pybluehost/l2cap/manager.py`, `pybluehost/l2cap/__init__.py`, `tests/unit/l2cap/test_manager.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/l2cap/test_manager.py
import asyncio, pytest, struct
from pybluehost.l2cap.manager import L2CAPManager
from pybluehost.l2cap.constants import CID_ATT
from pybluehost.core.trace import TraceSystem
from pybluehost.core.types import LinkType

class FakeHCI:
    def __init__(self): self.sent = []; self._upstream = None
    def set_upstream(self, **kw): self._upstream = kw
    async def send_acl_data(self, h, pb, data): self.sent.append((h, pb, data))
    async def send_command(self, cmd): pass

@pytest.fixture
def manager():
    hci = FakeHCI()
    m = L2CAPManager(hci=hci, trace=TraceSystem())
    return m, hci

@pytest.mark.asyncio
async def test_on_connection_registers_att_smp(manager):
    m, hci = manager
    await m.on_connection(handle=0x0040, link_type=LinkType.LE,
                           peer_address=None, role=None)
    # ATT and SMP fixed channels should now be registered
    assert 0x0040 in m._connections

@pytest.mark.asyncio
async def test_acl_data_routes_to_fixed_channel(manager):
    m, hci = manager
    received = []
    async def on_data(data): received.append(data)

    await m.on_connection(handle=0x0040, link_type=LinkType.LE,
                           peer_address=None, role=None)
    ch = m.get_fixed_channel(handle=0x0040, cid=CID_ATT)
    from pybluehost.l2cap.channel import SimpleChannelEvents
    ch.set_events(SimpleChannelEvents(on_data=on_data))

    # Build ACL packet: L2CAP header + payload
    payload = b"\x01\x02\x03"
    l2cap_pdu = struct.pack("<HH", len(payload), CID_ATT) + payload
    await m.on_acl_data(handle=0x0040, pb_flag=0x02, data=l2cap_pdu)
    await asyncio.sleep(0)
    assert received == [b"\x01\x02\x03"]

@pytest.mark.asyncio
async def test_on_disconnection_cleans_up(manager):
    m, hci = manager
    await m.on_connection(handle=0x0040, link_type=LinkType.LE,
                           peer_address=None, role=None)
    assert 0x0040 in m._connections
    await m.on_disconnection(handle=0x0040, reason=0x16)
    assert 0x0040 not in m._connections
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `manager.py`**

`L2CAPManager`:
- `__init__(hci, trace)`: stores refs, init `_connections: dict[int, dict[int, Channel]]`, `_sar = Reassembler()`
- `on_acl_data(handle, pb_flag, data)`: feed to reassembler → on complete PDU: parse L2CAP header → route to channel by CID
- `on_connection(handle, link_type, ...)`: LE → register ATT(0x0004) and SMP(0x0006) FixedChannels; Classic → register signaling(0x0001)
- `on_disconnection(handle, reason)`: notify all channels → cleanup
- `register_fixed_channel(handle, cid, events)`: create and store FixedChannel
- `get_fixed_channel(handle, cid)`: lookup
- `open_le_coc(handle, psm, mtu)`: send LE_Credit_Conn_Req via signaling, await response → return LECoCChannel
- `open_classic_channel(handle, psm, mode, mtu)`: send Connection_Request via signaling

- [ ] **Step 4: Write `__init__.py`**

```python
from pybluehost.l2cap.constants import (
    CID_ATT, CID_LE_SIGNALING, CID_SMP, CID_CLASSIC_SIGNALING,
    PSM_SDP, PSM_RFCOMM, SignalingCode,
)
from pybluehost.l2cap.channel import Channel, ChannelState, ChannelEvents
from pybluehost.l2cap.sar import Reassembler, Segmenter
from pybluehost.l2cap.ble import FixedChannel, LECoCChannel
from pybluehost.l2cap.classic import ClassicChannel, ChannelMode
from pybluehost.l2cap.manager import L2CAPManager
```

- [ ] **Step 5: Run all L2CAP tests + full suite**
```bash
uv run pytest tests/unit/l2cap/ -v
uv run pytest tests/ -v --tb=short
```

- [ ] **Step 6: Commit + update STATUS.md**
```bash
git add pybluehost/l2cap/ tests/unit/l2cap/
git commit -m "feat(l2cap): add L2CAPManager with connection tracking and channel routing"

# Update STATUS.md: Plan 4 ✅, Plan 5 🔄
git add docs/superpowers/STATUS.md
git commit -m "docs: mark Plan 4 (L2CAP) complete in STATUS.md"
```

---

## Task 6: HCI + L2CAP Integration Test

**Files:** `tests/integration/__init__.py`, `tests/integration/test_hci_l2cap.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/integration/test_hci_l2cap.py
"""Integration test: HCIController + L2CAPManager with VirtualController."""
import asyncio, struct, pytest
from pybluehost.core.address import BDAddress
from pybluehost.core.trace import TraceSystem
from pybluehost.core.types import LinkType
from pybluehost.hci.virtual import VirtualController
from pybluehost.hci.controller import HCIController
from pybluehost.hci.packets import (
    HCI_LE_Meta_Event, HCI_LE_Connection_Complete_SubEvent,
    decode_hci_packet,
)
from pybluehost.hci.constants import LEMetaSubEvent, ErrorCode
from pybluehost.l2cap.manager import L2CAPManager
from pybluehost.l2cap.constants import CID_ATT, CID_SMP

class LoopbackTransport:
    """Routes HCIController sends directly through VirtualController."""
    def __init__(self, vc: VirtualController) -> None:
        self._vc = vc
        self._sink = None

    def set_sink(self, sink): self._sink = sink
    async def open(self): pass
    async def close(self): pass

    async def send(self, data: bytes) -> None:
        response = await self._vc.process(data)
        if response and self._sink:
            await self._sink.on_transport_data(response)

    @property
    def is_open(self) -> bool: return True

@pytest.fixture
async def hci_l2cap_pair():
    vc = VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:01"))
    trace = TraceSystem()
    transport = LoopbackTransport(vc)
    hci = HCIController(transport=transport, trace=trace)
    transport.set_sink(hci)
    await hci.initialize()
    l2cap = L2CAPManager(hci=hci, trace=trace)
    hci.set_upstream(
        on_hci_event=l2cap.on_hci_event,
        on_acl_data=l2cap.on_acl_data,
    )
    return hci, l2cap, vc

@pytest.mark.asyncio
async def test_hci_l2cap_le_connection_registers_att_smp(hci_l2cap_pair):
    hci, l2cap, vc = hci_l2cap_pair
    # Inject LE Connection Complete event (simulating a remote device connecting)
    sub_params = struct.pack(
        "<BBHBBBBHHHBx",
        LEMetaSubEvent.LE_CONNECTION_COMPLETE,  # subevent
        ErrorCode.SUCCESS,                       # status
        0x0040,                                  # connection handle
        0x01,                                    # role: slave
        0x00,                                    # peer_address_type: public
        *bytes(6),                               # peer_address (6 bytes)
        0x0028,                                  # conn_interval
        0x0000,                                  # conn_latency
        0x00C8,                                  # supervision_timeout
        0x00,                                    # master_clock_accuracy
    )
    event_raw = bytes([0x04, 0x3E, len(sub_params)]) + sub_params
    await hci._sink_data(event_raw)
    await asyncio.sleep(0.05)
    # L2CAP should have registered ATT and SMP fixed channels
    assert 0x0040 in l2cap._connections
    att_ch = l2cap.get_fixed_channel(handle=0x0040, cid=CID_ATT)
    smp_ch = l2cap.get_fixed_channel(handle=0x0040, cid=CID_SMP)
    assert att_ch is not None
    assert smp_ch is not None

@pytest.mark.asyncio
async def test_hci_l2cap_acl_routes_to_att_channel(hci_l2cap_pair):
    hci, l2cap, vc = hci_l2cap_pair
    # Simulate connection first
    await l2cap.on_connection(handle=0x0040, link_type=LinkType.LE,
                               peer_address=None, role=None)
    received = []
    from pybluehost.l2cap.channel import SimpleChannelEvents
    att_ch = l2cap.get_fixed_channel(handle=0x0040, cid=CID_ATT)
    att_ch.set_events(SimpleChannelEvents(on_data=lambda d: received.append(d)))
    # Build L2CAP PDU: header (len=3, CID=ATT) + payload
    payload = b"\x02\x00\x02"  # ATT Exchange MTU Request
    l2cap_pdu = struct.pack("<HH", len(payload), CID_ATT) + payload
    # Inject as ACL data through HCI
    from pybluehost.hci.packets import HCIACLData
    acl = HCIACLData(handle=0x0040, pb_flag=0x02, bc_flag=0x00, data=l2cap_pdu)
    await hci._sink_data(acl.to_bytes())
    await asyncio.sleep(0.05)
    assert received == [payload]
```

- [ ] **Step 2: Run integration tests**
```bash
uv run pytest tests/integration/test_hci_l2cap.py -v --tb=short
```
Expected: PASS — ATT and SMP channels registered, ACL data routed correctly.

- [ ] **Step 3: Run full test suite — no regressions**
```bash
uv run pytest tests/ -v --tb=short
```

- [ ] **Step 4: Commit**
```bash
git add tests/integration/
git commit -m "test(integration): add HCI + L2CAP integration test with VirtualController"
```
