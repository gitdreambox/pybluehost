# 第七节：HCI 层详细设计

## 7.1 HCI 层职责

- HCI packet 的 encode/decode（Command / Event / ACL / SCO / ISO）
- Command flow control（command credit 管理）
- ACL data flow control（Host_Num_Completed_Packets）
- 将 HCI event 路由给正确的上层消费者
- 管理 connection handle 生命周期

## 7.2 模块划分

```
hci/
├── packets.py       # 所有 HCI packet 类型定义和 encode/decode
├── constants.py     # Opcode、Event Code、Error Code、OGF/OCF 常量
├── controller.py    # HCIController 主类（状态机、flow control、路由）
├── flow.py          # Command credit + ACL buffer 管理
├── virtual.py       # VirtualController（纯软件仿真）
└── vendor/
    ├── intel.py     # Intel vendor command/event 定义
    └── realtek.py   # Realtek vendor command/event 定义
```

## 7.3 Packet 系统设计

### 基础类型层次

```python
@dataclass
class HCIPacket:
    @classmethod
    def from_bytes(cls, data: bytes) -> "HCIPacket": ...
    def to_bytes(self) -> bytes: ...

@dataclass
class HCICommand(HCIPacket):
    opcode: int                  # OGF << 10 | OCF
    parameters: bytes = b""

@dataclass
class HCIEvent(HCIPacket):
    event_code: int
    parameters: bytes = b""

@dataclass
class HCIACLData(HCIPacket):
    handle: int                  # 12 bits
    pb_flag: int                 # 2 bits
    bc_flag: int                 # 2 bits
    data: bytes = b""

@dataclass
class HCISCOData(HCIPacket):
    handle: int
    packet_status: int
    data: bytes = b""

@dataclass
class HCIISOData(HCIPacket):
    """v1.0 仅解析，不实现上层逻辑"""
    handle: int
    pb_flag: int
    ts_flag: int
    data: bytes = b""
```

### 结构化 Command/Event（自动生成）

```python
@dataclass
class HCI_Reset(HCICommand):
    opcode: int = 0x0C03

@dataclass
class HCI_LE_Set_Scan_Enable(HCICommand):
    opcode: int = 0x200C
    le_scan_enable: int = 0
    filter_duplicates: int = 0

@dataclass
class HCI_Connection_Complete_Event(HCIEvent):
    event_code: int = 0x03
    status: int = 0
    connection_handle: int = 0
    bd_addr: BDAddress = BDAddress.EMPTY
    link_type: int = 0
    encryption_enabled: int = 0
```

### Packet 注册表

```python
class PacketRegistry:
    """Opcode/EventCode 到具体类的映射，支持 vendor extension"""
    _commands: dict[int, type[HCICommand]] = {}
    _events: dict[int, type[HCIEvent]] = {}

    @classmethod
    def register_command(cls, packet_class: type[HCICommand]) -> type[HCICommand]: ...
    @classmethod
    def register_event(cls, packet_class: type[HCIEvent]) -> type[HCIEvent]: ...
    @classmethod
    def decode_command(cls, data: bytes) -> HCICommand: ...
    @classmethod
    def decode_event(cls, data: bytes) -> HCIEvent: ...

# 使用装饰器自动注册
@PacketRegistry.register_command
@dataclass
class HCI_Reset(HCICommand):
    opcode: int = 0x0C03
```

## 7.4 HCIController 主类

```python
class HCIController:
    def __init__(self, transport: TransportSource, trace: TraceSystem) -> None: ...

    # ── HCIDownstream SAP ──
    async def send_command(self, cmd: HCICommand) -> HCIEvent:
        # 1. 等待 command credit > 0
        # 2. 编码 → transport.send()
        # 3. 创建 Future，注册到 _pending_commands[opcode]
        # 4. await future → 返回 event（超时 → CommandTimeoutError）

    async def send_acl_data(self, handle: int, pb_flag: int, data: bytes) -> None:
        # 受 ACL buffer flow control 约束，自动分段

    async def send_sco_data(self, handle: int, data: bytes) -> None: ...

    # ── TransportSink ──
    async def on_transport_data(self, data: bytes) -> None:
        packet_type = data[0]
        match packet_type:
            case 0x02: await self._route_acl(...)
            case 0x03: await self._route_sco(...)
            case 0x04: await self._handle_event(...)
            case 0x05: pass  # ISO: v1.0 仅 trace
```

## 7.5 Command Flow Control

```python
class CommandFlowController:
    def __init__(self, initial_credits: int = 1) -> None:
        self._credits = asyncio.Semaphore(initial_credits)
        self._pending: dict[int, asyncio.Future[HCIEvent]] = {}

    async def acquire(self) -> None: ...
    def release(self, num: int = 1) -> None: ...
    def register(self, opcode: int) -> asyncio.Future[HCIEvent]: ...
    def resolve(self, opcode: int, event: HCIEvent) -> None: ...
```

## 7.6 ACL Data Flow Control

```python
class ACLFlowController:
    def configure(self, num_buffers: int, buffer_size: int) -> None: ...
    async def acquire(self, handle: int) -> None: ...
    def on_num_completed(self, completed: dict[int, int]) -> None: ...
    def segment(self, data: bytes) -> list[bytes]: ...
```

## 7.7 Event 路由

```python
class EventRouter:
    async def route(self, event: HCIEvent) -> None:
        match event:
            case HCI_Command_Complete_Event():
                # resolve pending Future + release credit
            case HCI_Command_Status_Event():
                # resolve pending Future + release credit
            case HCI_Connection_Complete_Event():
                # 更新连接状态机 + 通知上层
            case HCI_Disconnection_Complete_Event():
                # 清理连接
            case HCI_Number_Of_Completed_Packets_Event():
                # 归还 ACL buffer credit
            case HCI_LE_Meta_Event():
                # 解包子事件后路由
            case _:
                # 分发给已注册的 handler

    def register_event_handler(self, event_code: int, handler: ...) -> None: ...
    def unregister_event_handler(self, event_code: int, handler: ...) -> None: ...
```

## 7.8 连接管理

```python
@dataclass
class HCIConnection:
    handle: int
    peer_address: BDAddress
    link_type: LinkType              # ACL | SCO | LE
    state_machine: StateMachine[ConnState, ConnEvent]
    role: ConnectionRole             # CENTRAL | PERIPHERAL

class ConnectionManager:
    _connections: dict[int, HCIConnection] = {}
    def add(self, handle: int, event: ...) -> HCIConnection: ...
    def remove(self, handle: int) -> None: ...
    def get(self, handle: int) -> HCIConnection | None: ...
```

## 7.9 HCI 初始化序列

```
 1. Transport.open()（含固件加载）
 2. HCI_Reset
 3. HCI_Read_Local_Version_Information
 4. HCI_Read_Local_Supported_Commands
 5. HCI_Read_Local_Supported_Features
 6. HCI_Read_BD_ADDR
 7. HCI_Read_Buffer_Size → 配置 ACLFlowController
 8. HCI_LE_Read_Buffer_Size
 9. HCI_LE_Read_Local_Supported_Features
10. HCI_LE_Read_Supported_States
11. HCI_Set_Event_Mask / HCI_LE_Set_Event_Mask
12. HCI_Write_LE_Host_Supported
13. HCI_Read_Local_Extended_Features (page 1) → 检查 SC 支持
14. HCI_Write_Simple_Pairing_Mode(enabled=0x01)
15. HCI_Write_Secure_Connections_Host_Support(enabled=0x01)（如支持且配置开启）
16. HCI_Write_Authentication_Enable / HCI_Write_Encryption_Mode
```

每一步都有 StateMachine 守护：超时自动报错，失败可重试或中止。

## 7.10 VirtualController

```python
class VirtualController:
    """纯软件 Controller 仿真"""

    async def process(self, data: bytes) -> bytes | None: ...

    # 已实现的命令：
    # 基础：Reset, Read_Local_Version, Read_BD_ADDR, Read_Buffer_Size, ...
    # LE:   LE_Read_Buffer_Size, LE_Set_Advertising_*, LE_Set_Scan_Enable,
    #       LE_Create_Connection, LE_Set_Event_Mask, ...
    # Classic: Inquiry, Create_Connection, Write_Scan_Enable, ...

    def connect_to(self, other: "VirtualController") -> None:
        """两个 VirtualController 互联，模拟空口连接"""
```

### VirtualController 互联

```python
vc_a = VirtualController(address=BDAddress("AA:BB:CC:DD:EE:01"))
vc_b = VirtualController(address=BDAddress("AA:BB:CC:DD:EE:02"))
vc_a.connect_to(vc_b)

stack_a = Stack.build(transport=LoopbackTransport(vc_a))
stack_b = Stack.build(transport=LoopbackTransport(vc_b))
# ACL 数据双向流通，完整模拟两端 Host 交互
```
