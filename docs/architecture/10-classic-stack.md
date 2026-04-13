# 第十节：Classic 协议栈详细设计（SDP / RFCOMM / SPP）

## 10.1 模块划分

```
classic/
├── sdp.py           # SDP Client + Server + ServiceRecord 定义
├── rfcomm.py        # RFCOMM 多路复用 + DLC 管理
├── spp.py           # SPP Profile（RFCOMM 上层封装）
└── gap.py           # Classic GAP（见第十一节）
```

## 10.2 SDP

### 数据模型

```python
class DataElementType(IntEnum):
    NIL = 0
    UINT = 1; SINT = 2; UUID = 3; TEXT = 4
    BOOLEAN = 5; SEQUENCE = 6; ALTERNATIVE = 7; URL = 8

@dataclass
class DataElement:
    type: DataElementType
    value: Any
    # 便捷构造: uint8(), uint16(), uuid16(), uuid128(), text(), sequence(), ...

@dataclass
class ServiceRecord:
    handle: int = 0
    attributes: dict[int, DataElement] = field(default_factory=dict)
```

### SDP Server

```python
class SDPServer:
    """SDP Server：管理本地 Service Record，响应远端查询（L2CAP PSM=0x0001）"""
    def register(self, record: ServiceRecord) -> int: ...
    def unregister(self, handle: int) -> None: ...
    # 处理：ServiceSearchRequest / ServiceAttributeRequest / ServiceSearchAttributeRequest
```

### SDP Client

```python
class SDPClient:
    async def search(self, target: BDAddress, uuid: UUID) -> list[int]: ...
    async def get_attributes(self, target: BDAddress, record_handle: int, attr_ids: ...) -> dict: ...
    async def search_attributes(self, target: BDAddress, uuid: UUID, attr_ids: ...) -> list[ServiceRecord]: ...
    async def find_rfcomm_channel(self, target: BDAddress, service_uuid: UUID) -> int | None: ...
```

`find_rfcomm_channel` 是常用快捷方法：查找服务的 RFCOMM channel number。

## 10.3 RFCOMM

### 架构

```
应用 A    应用 B    应用 C
   │         │         │
 DLC 2     DLC 4     DLC 6      ← 每个 DLC = 一个虚拟串口
   │         │         │
┌──┴─────────┴─────────┴──┐
│       RFCOMM MUX         │     ← 单条 L2CAP 连接上多路复用
│    (L2CAP PSM=0x0003)    │
└──────────┬───────────────┘
           │
        L2CAP
```

### 帧类型

```python
class RFCOMMFrameType(IntEnum):
    SABM = 0x2F   # 建立连接
    UA   = 0x63   # 确认
    DM   = 0x0F   # 拒绝/断开
    DISC = 0x43   # 断开请求
    UIH  = 0xEF   # 数据帧
```

### MUX 控制命令

PN（Parameter Negotiation）、MSC（Modem Status）、RPN（Remote Port Negotiation）、RLS（Remote Line Status）等。

### RFCOMM Session（Multiplexer）

```python
class RFCOMMSession:
    """一条 L2CAP 连接上的 RFCOMM 多路复用会话"""
    async def open(self) -> None:      # SABM on DLCI 0
    async def open_dlc(self, server_channel: int) -> RFCOMMChannel:
        # 1. Parameter Negotiation
        # 2. SABM on target DLCI
        # 3. MSC 交换
```

### RFCOMM Channel（虚拟串口）

```python
class RFCOMMChannel:
    @property
    def dlci(self) -> int: ...
    @property
    def server_channel(self) -> int: ...

    async def send(self, data: bytes) -> None:
        # 按 max_frame_size 分帧，消耗 credit

    async def set_modem_status(self, rtc: bool, rtr: bool, dv: bool) -> None: ...
    async def send_break(self, duration: int = 0) -> None: ...
    async def close(self) -> None: ...
```

### RFCOMM Manager

```python
class RFCOMMManager:
    async def connect(self, acl_handle: int, server_channel: int) -> RFCOMMChannel: ...
    async def listen(self, server_channel: int, handler: ...) -> None: ...
```

## 10.4 SPP

```python
class SPPService:
    """SPP Server：注册 SDP record + 监听 RFCOMM channel"""
    async def register(self, channel: int = 1, name: str = "Serial Port") -> None: ...
    def on_connection(self, handler: ...) -> None: ...

class SPPClient:
    """SPP Client：SDP 查找 + RFCOMM 连接"""
    async def connect(self, target: BDAddress) -> SPPConnection: ...

class SPPConnection:
    """串口语义的双向字节流"""
    async def send(self, data: bytes) -> None: ...
    async def recv(self, max_bytes: int = 4096) -> bytes: ...
    async def close(self) -> None: ...
    async def __aenter__(self) -> "SPPConnection": ...
    async def __aexit__(self, *exc) -> None: ...
```

### 使用示例

```python
# Server
stack = await Stack.from_usb()
spp = SPPService(stack.rfcomm, stack.sdp)
await spp.register(channel=1, name="My Serial Port")

async def handle(conn: SPPConnection):
    async with conn:
        while data := await conn.recv():
            await conn.send(b"Echo: " + data)
spp.on_connection(handle)

# Client
async with await client.connect(BDAddress("AA:BB:CC:DD:EE:FF")) as conn:
    await conn.send(b"Hello")
    resp = await conn.recv()  # b"Echo: Hello"
```
