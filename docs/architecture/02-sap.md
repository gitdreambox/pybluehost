# 第二节：SAP 接口设计与层间通信

## 2.1 SAP 概念模型

蓝牙规范用 SAP（Service Access Point）定义层间合同。PyBlueHost 将其具化为 Python `Protocol`（typing.Protocol），每层提供两个接口：

```
上层（Consumer）
    │
    │ 调用下行 SAP（发命令/数据）
    ▼
┌─────────────┐
│   某一层     │
└─────────────┘
    │
    │ 通过上行 SAP 回调（事件/数据上报）
    ▼
上层的回调实现
```

**关键原则**：下行是方法调用，上行是回调注册。层间不共享内部状态。

## 2.2 各层 SAP 接口定义

### Transport SAP

```python
class TransportSink(Protocol):
    """上行 SAP — Transport 向 HCI 交付数据"""
    async def on_transport_data(self, data: bytes) -> None: ...
    async def on_transport_error(self, error: TransportError) -> None: ...

class TransportSource(Protocol):
    """下行 SAP — HCI 向 Transport 发数据"""
    async def open(self) -> None: ...
    async def close(self) -> None: ...
    async def send(self, data: bytes) -> None: ...
    def set_sink(self, sink: TransportSink) -> None: ...
```

### HCI SAP

```python
class HCIUpstream(Protocol):
    """上行 SAP — HCI 向 L2CAP/上层 交付数据和事件"""
    async def on_hci_event(self, event: HCIEvent) -> None: ...
    async def on_acl_data(self, handle: int, pb_flag: int, data: bytes) -> None: ...
    async def on_sco_data(self, handle: int, data: bytes) -> None: ...

class HCIDownstream(Protocol):
    """下行 SAP — L2CAP/上层 向 HCI 发命令和数据"""
    async def send_command(self, cmd: HCICommand) -> HCIEvent: ...
    async def send_acl_data(self, handle: int, pb_flag: int, data: bytes) -> None: ...
    async def send_sco_data(self, handle: int, data: bytes) -> None: ...
```

`send_command` 返回对应的 Command Complete / Command Status event（内部用 `asyncio.Future` 匹配 opcode），调用方用 `await` 拿结果，不需要手动管理回调。

### L2CAP SAP

```python
class ChannelEvents(Protocol):
    """上行 SAP — L2CAP 通道向上层交付数据"""
    async def on_data(self, data: bytes) -> None: ...
    async def on_close(self, reason: int) -> None: ...
    async def on_mtu_changed(self, mtu: int) -> None: ...

class Channel(Protocol):
    """下行 SAP — 上层操作 L2CAP 通道"""
    @property
    def cid(self) -> int: ...
    @property
    def peer_cid(self) -> int: ...
    @property
    def mtu(self) -> int: ...
    @property
    def connection_handle(self) -> int: ...
    async def send(self, data: bytes) -> None: ...
    async def close(self) -> None: ...
    def set_events(self, events: ChannelEvents) -> None: ...

class L2CAPManager(Protocol):
    """L2CAP 管理接口 — 信道创建、固定信道注册"""
    def register_fixed_channel(self, handle: int, cid: int, events: ChannelEvents) -> Channel: ...
    async def open_le_coc(self, handle: int, psm: int, mtu: int = 512) -> Channel: ...
    async def listen_le_coc(self, psm: int, handler: Callable[[Channel], Awaitable]) -> None: ...
    async def open_classic_channel(self, handle: int, psm: int, mtu: int = 672) -> Channel: ...
    async def listen_classic(self, psm: int, handler: Callable[[Channel], Awaitable]) -> None: ...
```

### ATT / GATT SAP

```python
class ATTBearer(Protocol):
    """ATT 层向 GATT 暴露的接口"""
    async def exchange_mtu(self, mtu: int) -> int: ...
    async def read(self, handle: int) -> bytes: ...
    async def read_blob(self, handle: int, offset: int) -> bytes: ...
    async def read_by_type(self, start: int, end: int, uuid: UUID) -> list: ...
    async def read_by_group_type(self, start: int, end: int, uuid: UUID) -> list: ...
    async def write(self, handle: int, value: bytes) -> None: ...
    async def write_without_response(self, handle: int, value: bytes) -> None: ...
    async def prepare_write(self, handle: int, offset: int, value: bytes) -> bytes: ...
    async def execute_write(self, flags: int) -> None: ...
    async def read_long(self, handle: int) -> bytes: ...
    async def write_long(self, handle: int, value: bytes) -> None: ...
    def on_notification(self, handler: Callable[[int, bytes], Awaitable]) -> None: ...
    def on_indication(self, handler: Callable[[int, bytes], Awaitable]) -> None: ...

class GATTServer(Protocol):
    """GATT Server 向 Profile 暴露的接口"""
    def add_service(self, service: ServiceDefinition) -> ServiceHandle: ...
    async def notify(self, handle: int, value: bytes, connections: list[int] | None = None) -> None: ...
    async def indicate(self, handle: int, value: bytes, connection: int) -> None: ...
```

### SMP SAP

```python
class SMPManager(Protocol):
    """SMP 向 GAP/上层暴露的配对接口"""
    async def pair(self, connection: int, io_capability: IOCapability) -> PairingResult: ...
    async def encrypt(self, connection: int, ltk: LTK) -> bool: ...
    def on_pairing_request(self, handler: Callable[[int, PairingParams], Awaitable[bool]]) -> None: ...
    def set_bond_storage(self, storage: BondStorage) -> None: ...
```

### SDP / RFCOMM SAP

```python
class SDPClient(Protocol):
    async def search(self, target: BDAddress, uuid: UUID) -> list[ServiceRecord]: ...
    async def get_attributes(self, target: BDAddress, handle: int, attrs: list[int]) -> dict[int, Any]: ...

class SDPServer(Protocol):
    def register(self, record: ServiceRecord) -> int: ...
    def unregister(self, handle: int) -> None: ...

class RFCOMMChannel(Protocol):
    @property
    def dlci(self) -> int: ...
    async def send(self, data: bytes) -> None: ...
    async def close(self) -> None: ...
    def on_data(self, handler: Callable[[bytes], Awaitable]) -> None: ...

class RFCOMMManager(Protocol):
    async def connect(self, target: BDAddress, channel: int) -> RFCOMMChannel: ...
    async def listen(self, channel: int, handler: Callable[[RFCOMMChannel], Awaitable]) -> None: ...
```

## 2.3 层间数据流示例

**BLE GATT Read（从上到下再从下到上）：**

```
用户代码:  await gatt_client.read_characteristic(char_handle)
               │
 GATT:         │ await att_bearer.read(handle=0x0003)
               │
  ATT:         │ 构造 ATT_READ_REQ PDU → l2cap_channel.send(pdu)
               │
 L2CAP:        │ 添加 L2CAP header (CID=0x0004) → hci.send_acl_data(conn, data)
               │
  HCI:         │ 添加 HCI ACL header → transport.send(packet)
               │
Transport:     │ 物理发送到 Controller
               ▼
           Controller 返回 ATT_READ_RSP
               │
Transport:     │ on_transport_data(raw_bytes)
               │
  HCI:         │ 解析 ACL header → upstream.on_acl_data(handle, data)
               │
 L2CAP:        │ 解析 L2CAP header，路由到 CID=0x0004 → channel_events.on_data(pdu)
               │
  ATT:         │ 解析 ATT_READ_RSP → resolve Future
               │
 GATT:         │ 返回 characteristic 值给调用方
               ▼
用户代码:  收到 bytes
```

每个 `→` 箭头处都有一个自动 `TraceEvent` 发出，无需手动埋点。

## 2.4 测试替换示例

```python
# 只测 L2CAP 重组逻辑，不需要 HCI 以下任何东西
fake_hci = FakeHCIDownstream()   # 实现 HCIDownstream protocol
fake_hci.set_upstream(l2cap)     # L2CAP 实现了 HCIUpstream

l2cap = L2CAPManagerImpl(hci=fake_hci)

# 模拟 Controller 发来分段 ACL 数据
await fake_hci.inject_acl_data(handle=0x40, pb_flag=0x02, data=first_fragment)
await fake_hci.inject_acl_data(handle=0x40, pb_flag=0x01, data=second_fragment)

# 验证 L2CAP 正确重组
assert channel.received == [complete_pdu]
```

任何层都可以这样替换——只需 Fake 实现对应 SAP。
