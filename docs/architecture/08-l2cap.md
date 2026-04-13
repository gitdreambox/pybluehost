# 第八节：L2CAP 层详细设计

## 8.1 L2CAP 层职责

- 在单条 ACL 链路上提供多个逻辑信道
- 分段与重组（SAR）
- 信道建立/配置/释放的信令协商
- BLE 和 Classic 各自的信道实现，对上层暴露统一 `Channel` 接口

## 8.2 模块划分

```
l2cap/
├── channel.py       # Channel ABC + ChannelEvents
├── manager.py       # L2CAPManager 主类
├── ble.py           # BLE 固定信道 + LE Credit-based CoC
├── classic.py       # Classic 连接导向信道（Basic/ERTM/Streaming）
├── signaling.py     # L2CAP Signaling Channel (CID 0x0001 / 0x0005)
├── sar.py           # 分段重组引擎
└── constants.py     # CID、PSM、Signaling Command Code
```

## 8.3 CID 规划

```
CID         用途                  类型
0x0001      Classic Signaling     固定
0x0002      Connectionless        固定（v1.0 不实现）
0x0003      AMP Manager           固定（不实现）
0x0004      ATT                   BLE 固定
0x0005      LE Signaling          BLE 固定
0x0006      SMP                   BLE 固定
0x0007      SMP (BR/EDR)          固定
0x0040-0x007F  Dynamic            动态分配（Classic + LE CoC）
```

## 8.4 Channel 抽象

```python
class ChannelState(Enum):
    CLOSED = auto()
    CONFIG = auto()          # Classic only
    OPEN = auto()
    DISCONNECTING = auto()

class Channel(ABC):
    @property
    def cid(self) -> int: ...
    @property
    def peer_cid(self) -> int: ...
    @property
    def mtu(self) -> int: ...
    @property
    def connection_handle(self) -> int: ...
    @property
    def state(self) -> ChannelState: ...
    async def send(self, data: bytes) -> None: ...
    async def close(self) -> None: ...
    def set_events(self, events: ChannelEvents) -> None: ...

class ChannelEvents(Protocol):
    async def on_data(self, data: bytes) -> None: ...
    async def on_close(self, reason: int) -> None: ...
    async def on_mtu_changed(self, mtu: int) -> None: ...
```

## 8.5 L2CAPManager 主类

```python
class L2CAPManager:
    def __init__(self, hci: HCIDownstream, trace: TraceSystem) -> None: ...

    # ── HCIUpstream SAP ──
    async def on_acl_data(self, handle: int, pb_flag: int, data: bytes) -> None:
        # 1. 重组（分段 PDU）
        # 2. 解析 L2CAP basic header: length(2) + CID(2)
        # 3. 路由到目标 Channel

    # ── 信道管理 ──
    def register_fixed_channel(self, handle: int, cid: int, events: ChannelEvents) -> Channel: ...
    async def open_le_coc(self, handle: int, psm: int, mtu: int = 512) -> Channel: ...
    async def listen_le_coc(self, psm: int, handler: ...) -> None: ...
    async def open_classic_channel(self, handle: int, psm: int,
                                    mode: ChannelMode = ChannelMode.BASIC, mtu: int = 672) -> Channel: ...
    async def listen_classic(self, psm: int, handler: ...) -> None: ...

    # ── 连接事件联动 ──
    async def on_connection(self, handle: int, link_type: LinkType, ...) -> None:
        # LE 连接：自动注册 ATT + SMP 固定信道
    async def on_disconnection(self, handle: int, reason: int) -> None:
        # 清理所有信道
```

## 8.6 BLE 固定信道

```python
class FixedChannel(Channel):
    """BLE 固定信道（ATT CID=0x0004, SMP CID=0x0006）"""
    # 无 SAR，直接添加 L2CAP header → HCI ACL
```

## 8.7 BLE LE Credit-based CoC

```python
class LECoCChannel(Channel):
    """LE Credit-based Connection Oriented Channel"""

    async def send(self, data: bytes) -> None:
        # 按 MPS 分段，消耗 credit，第一段带 SDU length header

    async def _on_pdu(self, payload: bytes) -> None:
        # 重组 SDU，归还 credit
```

## 8.8 Classic L2CAP 信道

### 信道模式

```python
class ChannelMode(Enum):
    BASIC = 0x00
    ERTM = 0x03       # Enhanced Retransmission Mode
    STREAMING = 0x04
```

### Classic 信道状态机

```
    CLOSED ─── CONNECT_REQ ──► W4_CONFIG
       ▲                          │ CONFIG done
       │ DISCONNECT_RSP           ▼
  DISCONNECTING ◄──── OPEN ──► CONFIG（重配）
```

### ERTM 引擎

```python
class ERTMEngine:
    """ERTM 收发引擎：I-frame with sequence number + selective ack"""
    # TxSeq / ReqSeq 管理
    # Retransmission queue
    # S-frame (RR/REJ/SREJ) 处理
    # 重传超时
```

## 8.9 L2CAP Signaling

### Classic Signaling（CID 0x0001）

```
Connection_Request → Connection_Response → Configure_Request/Response（双向）→ OPEN
```

### LE Signaling（CID 0x0005）

```
LE_Credit_Based_Connection_Request → Response
Flow_Control_Credit
Connection_Parameter_Update_Request → Response
```

## 8.10 分段与重组（SAR）

```python
class Reassembler:
    """ACL → L2CAP 重组：处理 PB_FLAG 分段"""
    def feed(self, handle: int, pb_flag: int, data: bytes) -> bytes | None: ...
    def reset(self, handle: int | None = None) -> None: ...

class Segmenter:
    """L2CAP → ACL 分段：按 HCI ACL buffer size 切分"""
    def segment(self, pdu: bytes) -> list[tuple[int, bytes]]: ...
```
