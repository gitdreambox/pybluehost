# Plan 6: Classic Stack Implementation (SDP / RFCOMM / SPP)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement `pybluehost/classic/sdp.py`, `classic/rfcomm.py`, `classic/spp.py` — SDP data model + Server/Client, RFCOMM MUX/DLC, and SPP Profile.

**Architecture reference:** `docs/architecture/10-classic-stack.md`

**Dependencies:** `pybluehost/core/`, `pybluehost/l2cap/`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/classic/__init__.py` | Re-export Classic public API |
| `pybluehost/classic/sdp.py` | `DataElement`, `ServiceRecord`, `SDPServer`, `SDPClient` |
| `pybluehost/classic/rfcomm.py` | `RFCOMMSession`, `RFCOMMChannel`, `RFCOMMManager` |
| `pybluehost/classic/spp.py` | `SPPService`, `SPPClient`, `SPPConnection` |
| `tests/unit/classic/__init__.py` | |
| `tests/unit/classic/test_sdp.py` | DataElement encode/decode + ServiceRecord |
| `tests/unit/classic/test_rfcomm.py` | Frame encode/decode + session state machine |
| `tests/unit/classic/test_spp.py` | SPP integration with fake RFCOMM |

---

## Task 1: SDP Data Model + Codec

**Files:** `pybluehost/classic/sdp.py` (DataElement + codec), tests

- [x] **Step 1: Write failing SDP tests**

```python
# tests/unit/classic/test_sdp.py
from pybluehost.classic.sdp import (
    DataElement, DataElementType, encode_data_element, decode_data_element,
    ServiceRecord,
)

def test_uint8_encode():
    de = DataElement.uint8(0x42)
    raw = encode_data_element(de)
    assert raw[0] == 0x08  # type=UINT(1), size_index=0 (1 byte)
    assert raw[1] == 0x42

def test_uint16_encode():
    de = DataElement.uint16(0x0003)
    raw = encode_data_element(de)
    assert raw[0] == 0x09  # type=UINT, size_index=1 (2 bytes)
    assert raw[1:3] == b"\x00\x03"

def test_uuid16_encode():
    de = DataElement.uuid16(0x0003)
    raw = encode_data_element(de)
    assert raw[0] == 0x19  # type=UUID(3), size_index=1 (2 bytes)

def test_text_encode():
    de = DataElement.text("SPP")
    raw = encode_data_element(de)
    assert raw[0] == 0x25  # type=TEXT(4), size_index=5 (1-byte length follows)
    assert raw[1] == 3
    assert raw[2:] == b"SPP"

def test_sequence_encode():
    seq = DataElement.sequence([DataElement.uuid16(0x0003)])
    raw = encode_data_element(seq)
    assert raw[0] == 0x35  # type=SEQUENCE(6), size_index=5

def test_decode_roundtrip_uint16():
    de = DataElement.uint16(0x1234)
    raw = encode_data_element(de)
    decoded, consumed = decode_data_element(raw)
    assert decoded.type == DataElementType.UINT
    assert decoded.value == 0x1234
    assert consumed == len(raw)

def test_service_record_rfcomm_channel():
    from pybluehost.classic.sdp import make_rfcomm_service_record
    record = make_rfcomm_service_record(service_uuid=0x1101, channel=1, name="SPP")
    assert record.handle == 0
    # Should have ServiceClassIDList, ProtocolDescriptorList, ServiceName attributes
    assert 0x0001 in record.attributes  # ServiceClassIDList
    assert 0x0004 in record.attributes  # ProtocolDescriptorList

def test_sdp_server_register_and_handle_pdu():
    """SDPServer.handle_pdu() must handle ServiceSearchAttributeRequest."""
    from pybluehost.classic.sdp import (
        SDPServer, make_rfcomm_service_record,
        encode_data_element, DataElement,
    )
    import struct

    server = SDPServer()
    record = make_rfcomm_service_record(service_uuid=0x1101, channel=1, name="SPP")
    handle = server.register(record)
    assert handle >= 0x00010000  # standard first user handle

    # Craft a minimal ServiceSearchAttributeRequest PDU
    # PDU header: PDU_ID(1), TransactionID(2), ParameterLength(2)
    # ServiceSearchPattern: sequence of UUID 0x1101
    uuid_de = encode_data_element(DataElement.sequence([DataElement.uuid16(0x1101)]))
    # AttributeIDList: all attributes (range 0x0000–0xFFFF)
    attr_range = encode_data_element(DataElement.sequence([
        DataElement.uint32(0x0000FFFF)
    ]))
    continuation = b"\x00"  # no continuation state
    max_count = struct.pack(">H", 0x00FF)

    params = uuid_de + max_count + attr_range + continuation
    pdu = bytes([0x06]) + struct.pack(">HH", 0x0001, len(params)) + params

    response = server.handle_pdu(pdu)
    assert response is not None
    assert len(response) > 5
    assert response[0] == 0x07  # ServiceSearchAttributeResponse PDU_ID

def test_sdp_client_search_attributes():
    """SDPClient must expose search_attributes(target, uuid, attr_ids) convenience."""
    from pybluehost.classic.sdp import SDPClient
    import inspect
    sig = inspect.signature(SDPClient.search_attributes)
    params = list(sig.parameters)
    assert "uuid" in params
    assert "attr_ids" in params
```

- [x] **Step 2: Run tests — verify they fail**

- [x] **Step 3: Implement SDP data model**

```python
class DataElementType(IntEnum):
    NIL = 0; UINT = 1; SINT = 2; UUID = 3
    TEXT = 4; BOOLEAN = 5; SEQUENCE = 6; ALTERNATIVE = 7; URL = 8

@dataclass
class DataElement:
    type: DataElementType
    value: Any

    @classmethod
    def uint8(cls, v): ...
    @classmethod
    def uint16(cls, v): ...
    @classmethod
    def uint32(cls, v): ...
    @classmethod
    def uuid16(cls, v): ...
    @classmethod
    def uuid128(cls, v): ...
    @classmethod
    def text(cls, s): ...
    @classmethod
    def boolean(cls, v): ...
    @classmethod
    def sequence(cls, elements): ...
    @classmethod
    def alternative(cls, elements): ...

def encode_data_element(de: DataElement) -> bytes: ...
def decode_data_element(data: bytes) -> tuple[DataElement, int]: ...

def make_rfcomm_service_record(service_uuid: int, channel: int, name: str) -> ServiceRecord:
    """Build standard SPP-style SDP record for an RFCOMM service."""
```

- [x] **Step 4: Implement `SDPServer` + `SDPClient` stubs**

`SDPServer`:
- `register(record) -> int`: assign handle, store
- `unregister(handle)`: remove
- `handle_pdu(data) -> bytes`: parse ServiceSearch/ServiceAttribute/ServiceSearchAttribute request → search records → encode response

`SDPClient`:
- `search(target, uuid) -> list[int]`: send ServiceSearchRequest via L2CAP PSM=0x0001
- `get_attributes(target, handle, attr_ids) -> dict`: send ServiceAttributeRequest
- `search_attributes(target, uuid, attr_ids) -> dict`: send ServiceSearchAttributeRequest (combines search + get_attributes in one PDU); `attr_ids` is list of int attribute IDs or `(start, end)` range tuples
- `find_rfcomm_channel(target, service_uuid) -> int | None`: convenience

- [x] **Step 5: Run tests — verify they pass**

- [x] **Step 6: Commit**
```bash
git add pybluehost/classic/sdp.py tests/unit/classic/test_sdp.py
git commit -m "feat(classic): add SDP data model, encode/decode, SDPServer, SDPClient"
```

---

## Task 2: RFCOMM

**Files:** `pybluehost/classic/rfcomm.py`, `tests/unit/classic/test_rfcomm.py`

- [x] **Step 1: Write failing RFCOMM frame tests**

```python
# tests/unit/classic/test_rfcomm.py
from pybluehost.classic.rfcomm import (
    RFCOMMFrame, RFCOMMFrameType, encode_frame, decode_frame,
    calc_fcs,
)

def test_sabm_frame_encode():
    frame = RFCOMMFrame(dlci=0, frame_type=RFCOMMFrameType.SABM, pf=True, data=b"")
    raw = encode_frame(frame)
    assert raw[0] == 0x03  # address: DLCI=0, C/R=1, EA=1
    assert raw[1] == 0x2F  # SABM control
    assert raw[2] == 0x01  # length: 0 bytes, EA=1
    # Last byte: FCS
    assert len(raw) == 4

def test_uih_frame_encode():
    frame = RFCOMMFrame(dlci=2, frame_type=RFCOMMFrameType.UIH, pf=False, data=b"hello")
    raw = encode_frame(frame)
    assert raw[1] == 0xEF  # UIH control
    assert b"hello" in raw

def test_frame_decode_sabm():
    raw = bytes([0x03, 0x2F, 0x01, 0x1C])  # SABM on DLCI 0
    frame = decode_frame(raw)
    assert frame.dlci == 0
    assert frame.frame_type == RFCOMMFrameType.SABM
    assert frame.pf == True

def test_fcs_calculation():
    # FCS is calculated over address + control + length for UIH
    fcs = calc_fcs(bytes([0x03, 0x2F, 0x01]))
    assert isinstance(fcs, int)
    assert 0 <= fcs <= 255

def test_ua_frame_encode_decode():
    """UA (Unnumbered Acknowledgment) frame used to ack SABM/DISC."""
    frame = RFCOMMFrame(dlci=0, frame_type=RFCOMMFrameType.UA, pf=True, data=b"")
    raw = encode_frame(frame)
    assert raw[1] == 0x73  # UA control byte: 0111 0011
    decoded = decode_frame(raw)
    assert decoded.frame_type == RFCOMMFrameType.UA
    assert decoded.dlci == 0
    assert decoded.pf == True

def test_dm_frame_encode_decode():
    """DM (Disconnected Mode) frame sent when DLC not established."""
    frame = RFCOMMFrame(dlci=2, frame_type=RFCOMMFrameType.DM, pf=True, data=b"")
    raw = encode_frame(frame)
    assert raw[1] == 0x0F  # DM control byte: 0000 1111
    decoded = decode_frame(raw)
    assert decoded.frame_type == RFCOMMFrameType.DM
    assert decoded.dlci == 2

def test_disc_frame_encode_decode():
    """DISC (Disconnect) frame used to tear down DLCI."""
    frame = RFCOMMFrame(dlci=4, frame_type=RFCOMMFrameType.DISC, pf=True, data=b"")
    raw = encode_frame(frame)
    assert raw[1] == 0x53  # DISC control byte: 0101 0011
    decoded = decode_frame(raw)
    assert decoded.frame_type == RFCOMMFrameType.DISC
    assert decoded.dlci == 4

def test_rfcomm_frame_type_enum_completeness():
    """All standard RFCOMM frame types must be defined."""
    expected = {"SABM", "UA", "DM", "DISC", "UIH", "UI"}
    assert expected.issubset({t.name for t in RFCOMMFrameType})
```

- [x] **Step 2: Run tests — verify they fail**

- [x] **Step 3: Implement RFCOMM frame codec**

RFCOMM frame structure:
- Address byte: EA(1) | C/R(1) | DLCI(6)
- Control byte: frame type
- Length: EA(1) + length(7) or EA(1) + length_low(7) + length_high(8)
- Data (0 or more bytes)
- FCS: CRC-8 calculated over address + control (+ length for non-UIH frames)

```python
class RFCOMMFrameType(IntEnum):
    SABM = 0x2F   # Set Asynchronous Balanced Mode
    UA   = 0x73   # Unnumbered Acknowledgment
    DM   = 0x0F   # Disconnected Mode
    DISC = 0x53   # Disconnect
    UIH  = 0xEF   # Unnumbered Information with Header check
    UI   = 0x03   # Unnumbered Information

@dataclass
class RFCOMMFrame:
    dlci: int
    frame_type: RFCOMMFrameType
    pf: bool          # Poll/Final bit
    data: bytes

def encode_frame(frame: RFCOMMFrame) -> bytes: ...
def decode_frame(data: bytes) -> RFCOMMFrame: ...
```

`calc_fcs(data: bytes) -> int`: CRC-8 with polynomial 0xE0 (TS 07.10 standard table).

- [x] **Step 4: Implement `RFCOMMSession` and `RFCOMMChannel`**

`RFCOMMSession`:
- `async open()`: send SABM on DLCI 0, await UA
- `async open_dlc(server_channel) -> RFCOMMChannel`: PN negotiation + SABM + MSC

`RFCOMMChannel`:
- `dlci`, `server_channel` properties
- `async send(data)`: segment by `max_frame_size`, send UIH frames with credit
- Credit-based flow control (TS 07.10 credit extension)

`RFCOMMManager`:
- `async connect(acl_handle, server_channel) -> RFCOMMChannel`
- `async listen(server_channel, handler)`: register incoming connection handler

- [x] **Step 5: Run tests — verify they pass**

- [x] **Step 6: Commit**
```bash
git add pybluehost/classic/rfcomm.py tests/unit/classic/test_rfcomm.py
git commit -m "feat(classic): add RFCOMM frame codec, Session and Channel"
```

---

## Task 3: SPP Profile

**Files:** `pybluehost/classic/spp.py`, `tests/unit/classic/test_spp.py`

- [x] **Step 1: Write failing SPP tests**

```python
# tests/unit/classic/test_spp.py
import asyncio, pytest
from unittest.mock import AsyncMock, MagicMock
from pybluehost.classic.spp import SPPConnection

@pytest.mark.asyncio
async def test_spp_connection_send_recv():
    channel = MagicMock()
    channel.send = AsyncMock()
    received_data = bytearray()

    conn = SPPConnection(rfcomm_channel=channel)
    await conn.send(b"hello")
    channel.send.assert_called_once_with(b"hello")

@pytest.mark.asyncio
async def test_spp_connection_context_manager():
    channel = MagicMock()
    channel.send = AsyncMock()
    channel.close = AsyncMock()
    conn = SPPConnection(rfcomm_channel=channel)
    async with conn:
        await conn.send(b"test")
    channel.close.assert_called_once()
```

- [x] **Step 2: Run tests — verify they fail**

- [x] **Step 3: Implement `spp.py`**

```python
@dataclass
class SPPConnection:
    rfcomm_channel: RFCOMMChannel
    _recv_queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    async def send(self, data: bytes) -> None:
        await self.rfcomm_channel.send(data)

    async def recv(self, max_bytes: int = 4096) -> bytes:
        data = await self._recv_queue.get()
        return data[:max_bytes]

    async def close(self) -> None:
        await self.rfcomm_channel.close()

    async def __aenter__(self): return self
    async def __aexit__(self, *exc): await self.close()

class SPPService:
    def __init__(self, rfcomm: RFCOMMManager, sdp: SDPServer) -> None: ...
    async def register(self, channel: int = 1, name: str = "Serial Port") -> None:
        # Register SDP record + listen on RFCOMM channel
    def on_connection(self, handler: Callable[[SPPConnection], Awaitable]) -> None: ...

class SPPClient:
    def __init__(self, rfcomm: RFCOMMManager, sdp_client: SDPClient) -> None: ...
    async def connect(self, target: BDAddress) -> SPPConnection:
        # 1. SDP: find_rfcomm_channel(target, UUID16(0x1101))
        # 2. RFCOMM: connect(acl_handle, channel)
        # 3. Wrap in SPPConnection
```

- [x] **Step 4: Run tests — verify they pass**

- [x] **Step 5: Commit + package exports + STATUS update**
```bash
git add pybluehost/classic/ tests/unit/classic/
git commit -m "feat(classic): add SPP profile (SPPService + SPPClient + SPPConnection)"

# __init__.py exports
git add pybluehost/classic/__init__.py
git commit -m "feat(classic): finalize Classic package exports"

# Update STATUS.md: Plan 6 ✅, Plan 7 🔄
git add docs/superpowers/STATUS.md
git commit -m "docs: mark Plan 6 (Classic stack) complete in STATUS.md"
```

---

## 审查补充事项 (2026-04-18 审查后追加)

### 补充 1: RFCOMM RPN/RLS 控制命令（架构 10-classic-stack.md §10.3）

当前 Plan 只覆盖 PN（Parameter Negotiation）和 MSC（Modem Status）。需要补充：

- **RPN (Remote Port Negotiation)**: 串口参数协商（baudrate, data bits, stop bits, parity, flow control）
  - 编解码测试 + 协商流程测试
- **RLS (Remote Line Status)**: 远端线路状态通知（overrun, parity error, framing error）
  - 编解码测试 + 状态通知测试

这是 PRD §5.5 "串口仿真语义完整实现" 的要求。

### 补充 2: SDP ServiceSearchAttributeRequest 测试

`SDPClient.search_attributes()` 方法（组合 ServiceSearch + AttributeRequest）缺少专门测试。需要补充：
- 发送 ServiceSearchAttributeRequest PDU 的编解码
- 收到 Response 后的解析

### 补充 3: SPP SDP 自动注册验证

`make_rfcomm_service_record()` 注册后，需要 E2E 验证：通过 SDPClient 查询能找到该 record，且 RFCOMM channel 号正确。

### 补充 4: profiles/classic/spp.py 归属说明

架构 01-layering.md 包结构中存在 `profiles/classic/spp.py`（Profile 层封装），与本 Plan 的 `classic/spp.py`（协议层）是不同文件。Profile 层封装在 Plan 9b 中实现。
