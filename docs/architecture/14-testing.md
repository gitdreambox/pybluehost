# 第十四节：测试策略与框架

## 14.1 测试原则

PyBlueHost 的核心竞争力之一是可测试性。SAP 隔离 + 依赖注入的架构使得每一层都可以在不依赖真实硬件的情况下独立测试。测试设计遵循以下原则：

1. **TDD 强制执行**：所有开发必须遵循严格的 TDD（Test-Driven Development）流程——先写失败测试，再写最小实现，最后重构
2. **无硬件依赖**：所有自动化测试必须在无蓝牙硬件的环境下运行
3. **分层隔离**：每层通过 Fake SAP 替换上下层，单独验证本层逻辑
4. **真实数据验证**：使用 btsnoop 真实抓包数据作为测试输入，验证解析正确性
5. **端到端覆盖**：通过 Loopback 双栈验证完整协议交互流程

### 14.1.1 TDD 工作流

所有功能开发严格遵循 Red → Green → Refactor 循环：

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│   Red    │────▶│  Green   │────▶│ Refactor │──┐
│ 写失败测试│     │ 最小实现  │     │ 清理代码  │  │
└──────────┘     └──────────┘     └──────────┘  │
     ▲                                          │
     └──────────────────────────────────────────┘
```

**Red**：编写一个描述预期行为的测试，运行并确认它失败（且失败原因是功能缺失，而非语法错误）。

**Green**：编写刚好足够让测试通过的生产代码，不多写一行。

**Refactor**：在所有测试保持绿色的前提下，清理代码结构、消除重复。

**规则**：
- 没有失败测试，不写生产代码
- 每次只写一个失败测试，使其通过后再写下一个
- 每次修改后运行 `uv run pytest` 验证状态

## 14.2 测试分层

```
┌─────────────────────────────────────────────────────────┐
│  端到端测试（E2E）                                       │
│  Loopback 双栈：完整 Profile 交互验证                     │
├─────────────────────────────────────────────────────────┤
│  集成测试（Integration）                                 │
│  多层组合：HCI + L2CAP、L2CAP + ATT + GATT 等           │
├─────────────────────────────────────────────────────────┤
│  单元测试（Unit）                                        │
│  单层隔离：每层通过 Fake SAP 独立测试                     │
├─────────────────────────────────────────────────────────┤
│  数据测试（Data）                                        │
│  Packet encode/decode、PDU 解析、状态机转换               │
└─────────────────────────────────────────────────────────┘
```

### 14.2.1 数据测试

最底层，验证各种 Packet/PDU 的编解码正确性，无需任何 Fake 对象。

```python
# HCI Packet encode/decode
def test_hci_reset_encode():
    cmd = HCI_Reset()
    assert cmd.to_bytes() == bytes.fromhex("01 0300 00".replace(" ", ""))

def test_hci_event_decode():
    data = bytes.fromhex("04 0e 04 01 0300 00")
    event = PacketRegistry.decode_event(data)
    assert isinstance(event, HCI_Command_Complete_Event)
    assert event.opcode == 0x0C03

# L2CAP PDU
def test_l2cap_basic_header():
    pdu = L2CAPBasicHeader(length=5, cid=0x0004)
    assert pdu.to_bytes() == b"\x05\x00\x04\x00"

# ATT PDU
def test_att_read_request():
    pdu = ATT_Read_Request(handle=0x0003)
    assert pdu.to_bytes() == b"\x0a\x03\x00"

# SDP DataElement
def test_data_element_uint16():
    de = DataElement.uint16(0x1234)
    encoded = de.to_bytes()
    decoded = DataElement.from_bytes(encoded)
    assert decoded.value == 0x1234
```

### 14.2.2 单元测试

每层通过 Fake SAP 隔离测试，只验证本层逻辑。

```python
# ── L2CAP 重组测试 ──
async def test_l2cap_reassembly():
    fake_hci = FakeHCIDownstream()
    l2cap = L2CAPManager(hci=fake_hci, trace=NullTrace())

    received = []
    events = SimpleChannelEvents(on_data=lambda d: received.append(d))
    l2cap.register_fixed_channel(handle=0x40, cid=0x0004, events=events)

    # 模拟分段 ACL 数据
    await l2cap.on_acl_data(0x40, pb_flag=0x02, data=first_fragment)
    await l2cap.on_acl_data(0x40, pb_flag=0x01, data=second_fragment)

    assert received == [complete_pdu]

# ── HCI Command Flow Control 测试 ──
async def test_hci_command_credit():
    fake_transport = FakeTransport()
    hci = HCIController(transport=fake_transport, trace=NullTrace())

    # 初始 credit = 1，第一条命令立即发出
    task1 = asyncio.create_task(hci.send_command(HCI_Reset()))
    await asyncio.sleep(0)
    assert fake_transport.sent_count == 1

    # 第二条命令阻塞等待 credit
    task2 = asyncio.create_task(hci.send_command(HCI_Read_BD_ADDR()))
    await asyncio.sleep(0)
    assert fake_transport.sent_count == 1  # 仍然是 1

    # 回复第一条命令，释放 credit
    await fake_transport.inject_event(command_complete_for_reset)
    await asyncio.sleep(0)
    assert fake_transport.sent_count == 2  # 第二条命令已发出

# ── GATT Server 测试 ──
async def test_gatt_server_add_service():
    server = GATTServer()
    service = ServiceDefinition(
        uuid=UUID16(0x180D),
        characteristics=[
            CharacteristicDefinition(
                uuid=UUID16(0x2A37),
                properties=CharProperties.NOTIFY,
                permissions=Permissions.READABLE,
            ),
        ],
    )
    handle = server.add_service(service)
    # 验证 attribute 展开：Service Decl + Char Decl + Char Value + CCCD
    assert server.attribute_count >= 4

# ── SMP 加密函数测试 ──
def test_smp_f4():
    # Bluetooth Core Spec Vol 3 Part H Appendix D.2 测试向量
    u = bytes.fromhex("20b003d2 f297be2c 5e2c83a7 e9f9a5b9 eff49111 acf4fddb cc030148 0e359de6")
    v = bytes.fromhex("55188b3d 32f6bb9a 900afcfb eed4e72a 59cb9ac2 f19d7cfb 6b4fdd49 f47fc5fd")
    x = bytes.fromhex("d5cb8454 d177733e ffffb2ec 712baeab")
    z = 0x00
    expected = bytes.fromhex("f2c916f1 07a9bd1c f1eda1be a974872d")
    assert SMPCrypto.f4(u, v, x, z) == expected
```

### 14.2.3 集成测试

多层组合测试，验证层间交互是否正确。

```python
# ── HCI + L2CAP 集成 ──
async def test_hci_l2cap_acl_flow():
    """验证 HCI ACL 数据正确路由到 L2CAP 信道"""
    fake_transport = FakeTransport()
    hci = HCIController(transport=fake_transport, trace=NullTrace())
    l2cap = L2CAPManager(hci=hci, trace=NullTrace())

    # 模拟连接建立
    await fake_transport.inject_event(connection_complete_event(handle=0x40))

    # 注册 ATT 固定信道
    received = []
    events = SimpleChannelEvents(on_data=lambda d: received.append(d))
    channel = l2cap.register_fixed_channel(handle=0x40, cid=0x0004, events=events)

    # 从 transport 注入 ACL 数据（含 L2CAP header）
    await fake_transport.inject_acl(handle=0x40, l2cap_cid=0x0004, payload=att_read_rsp)

    assert received == [att_read_rsp]

# ── L2CAP + ATT + GATT 集成 ──
async def test_gatt_read_via_att():
    """验证 GATT Read 经由 ATT → L2CAP 的完整路径"""
    fake_hci = FakeHCIDownstream()
    l2cap = L2CAPManager(hci=fake_hci, trace=NullTrace())
    att = ATTBearer(l2cap=l2cap, connection_handle=0x40)
    gatt_server = GATTServer(att_bearer=att)

    # 注册服务
    gatt_server.add_service(battery_service_definition)

    # 模拟远端发来 ATT Read Request
    await fake_hci.inject_acl_with_att(handle=0x40, pdu=ATT_Read_Request(handle=0x0003))

    # 验证 HCI 层发出了 ATT Read Response
    sent = fake_hci.get_sent_acl()
    assert len(sent) == 1
    assert ATT_Read_Response in sent[0]
```

### 14.2.4 端到端测试（Loopback）

通过 VirtualController 互联的双栈，验证完整 Profile 交互。

```python
async def test_heart_rate_profile_e2e():
    """Heart Rate Profile 端到端：广播 → 扫描 → 连接 → GATT 交互"""
    stack_a, stack_b = await Stack.loopback()

    # ── Server 侧 (stack_b) ──
    hrs = HeartRateServer()
    await hrs.register(stack_b.gatt_server)

    ad = AdvertisingData()
    ad.set_flags(0x06)
    ad.add_service_uuid16(0x180D)
    await stack_b.gap.ble_advertiser.start(AdvertisingConfig(), ad)

    # ── Client 侧 (stack_a) ──
    results = await stack_a.gap.ble_scanner.scan_for(1.0)
    assert len(results) >= 1
    assert results[0].advertising_data.has_service(0x180D)

    conn = await stack_a.gap.ble_connections.connect(results[0].address)
    assert conn is not None

    client = HeartRateClient()
    await client.discover(conn.gatt_client)

    # 读取 Body Sensor Location
    location = await client.read_sensor_location()
    assert location == 0x01  # Chest

    # 订阅 Heart Rate Measurement
    measurements = []
    await client.subscribe_measurement(lambda bpm: measurements.append(bpm))

    # 触发通知
    await hrs.update_measurement(bpm=72)
    await asyncio.sleep(0.1)
    assert 72 in measurements

    await stack_a.close()
    await stack_b.close()

async def test_spp_e2e():
    """SPP 端到端：SDP 查询 → RFCOMM 连接 → 数据收发"""
    stack_a, stack_b = await Stack.loopback()

    # Server
    spp = SPPService(stack_b.rfcomm, stack_b.sdp)
    await spp.register(channel=1, name="Test SPP")
    received = []
    spp.on_connection(lambda conn: _echo_handler(conn, received))

    # Client
    client = SPPClient(stack_a.rfcomm, SDPClient(stack_a))
    async with await client.connect(stack_b.local_address) as conn:
        await conn.send(b"Hello")
        resp = await conn.recv()
        assert resp == b"Echo: Hello"

    await stack_a.close()
    await stack_b.close()

async def test_smp_pairing_e2e():
    """SMP 配对端到端：Just Works 配对 → 加密连接"""
    config_a = StackConfig(
        security=SecurityConfig(le_sc_enabled=True),
        pairing_delegate=AutoAcceptDelegate(),
    )
    config_b = StackConfig(
        security=SecurityConfig(le_sc_enabled=True),
        pairing_delegate=AutoAcceptDelegate(),
    )
    stack_a, stack_b = await Stack.loopback(config_a, config_b)

    # 建立连接
    await stack_b.gap.ble_advertiser.start(AdvertisingConfig(), ad_data)
    results = await stack_a.gap.ble_scanner.scan_for(1.0)
    conn = await stack_a.gap.ble_connections.connect(results[0].address)

    # 发起配对
    result = await conn.smp.pair(conn.handle, sc=True)
    assert result.success
    assert result.sc  # Secure Connections
    assert result.bonded

    await stack_a.close()
    await stack_b.close()
```

## 14.3 Test Fixtures 与辅助工具

### 14.3.1 Fake SAP 实现

每个 SAP 接口提供对应的 Fake 实现，用于隔离测试。

```python
class FakeTransport(TransportSource):
    """Fake Transport：记录发出的数据，支持注入接收数据"""
    def __init__(self) -> None:
        self._sent: list[bytes] = []
        self._sink: TransportSink | None = None

    async def send(self, data: bytes) -> None:
        self._sent.append(data)

    async def inject(self, data: bytes) -> None:
        await self._sink.on_transport_data(data)

    @property
    def sent(self) -> list[bytes]: return self._sent

class FakeHCIDownstream(HCIDownstream):
    """Fake HCI：模拟 Controller 响应，支持注入事件"""
    def __init__(self) -> None:
        self._sent_commands: list[HCICommand] = []
        self._sent_acl: list[tuple[int, bytes]] = []
        self._auto_replies: dict[int, HCIEvent] = {}

    async def send_command(self, cmd: HCICommand) -> HCIEvent:
        self._sent_commands.append(cmd)
        if cmd.opcode in self._auto_replies:
            return self._auto_replies[cmd.opcode]
        return HCI_Command_Complete_Event(opcode=cmd.opcode, status=0)

    async def send_acl_data(self, handle: int, pb_flag: int, data: bytes) -> None:
        self._sent_acl.append((handle, data))

    def set_auto_reply(self, opcode: int, event: HCIEvent) -> None:
        self._auto_replies[opcode] = event

class SimpleChannelEvents(ChannelEvents):
    """简单 Channel 事件收集器"""
    def __init__(self, on_data=None, on_close=None) -> None:
        self._on_data = on_data
        self._on_close = on_close

    async def on_data(self, data: bytes) -> None:
        if self._on_data: self._on_data(data)

    async def on_close(self, reason: int) -> None:
        if self._on_close: self._on_close(reason)

    async def on_mtu_changed(self, mtu: int) -> None:
        pass

class NullTrace(TraceSystem):
    """空 Trace：丢弃所有事件，用于测试中消除 Trace 噪音"""
    async def emit(self, event: TraceEvent) -> None:
        pass
```

### 14.3.2 Btsnoop 测试数据

```python
class BtsnoopTestData:
    """从 btsnoop 文件加载真实 HCI 数据作为测试输入"""

    @staticmethod
    def load_packets(path: str) -> list[HCIPacket]:
        """加载 btsnoop 文件中的所有 HCI packet"""

    @staticmethod
    def load_commands(path: str) -> list[HCICommand]:
        """仅加载 HCI Command"""

    @staticmethod
    def load_events(path: str) -> list[HCIEvent]:
        """仅加载 HCI Event"""

    @staticmethod
    def load_acl(path: str) -> list[HCIACLData]:
        """仅加载 ACL 数据"""
```

```python
# 使用真实抓包数据测试 HCI 解析
def test_hci_decode_real_capture():
    packets = BtsnoopTestData.load_packets("tests/data/android_ble_scan.btsnoop")
    for pkt in packets:
        # 验证每个 packet 都能正确解码，不抛异常
        assert pkt is not None
        # 验证 encode/decode 往返一致
        assert type(pkt).from_bytes(pkt.to_bytes()) == pkt
```

### 14.3.3 pytest Fixtures

```python
# conftest.py

@pytest.fixture
def fake_transport():
    return FakeTransport()

@pytest.fixture
def fake_hci():
    return FakeHCIDownstream()

@pytest.fixture
def null_trace():
    return NullTrace()

@pytest.fixture
async def loopback_stacks():
    stack_a, stack_b = await Stack.loopback()
    yield stack_a, stack_b
    await stack_a.close()
    await stack_b.close()

@pytest.fixture
async def hci_controller(fake_transport, null_trace):
    hci = HCIController(transport=fake_transport, trace=null_trace)
    return hci

@pytest.fixture
async def l2cap_manager(fake_hci, null_trace):
    l2cap = L2CAPManager(hci=fake_hci, trace=null_trace)
    return l2cap
```

## 14.4 测试目录结构

```
tests/
├── conftest.py                  # 全局 fixtures
├── data/                        # btsnoop 测试数据
│   ├── android_ble_scan.btsnoop
│   ├── classic_spp_session.btsnoop
│   └── smp_pairing_sc.btsnoop
├── fakes/                       # Fake SAP 实现
│   ├── __init__.py
│   ├── transport.py             # FakeTransport
│   ├── hci.py                   # FakeHCIDownstream
│   ├── l2cap.py                 # SimpleChannelEvents
│   └── trace.py                 # NullTrace
├── unit/                        # 单元测试
│   ├── test_hci_packets.py      # HCI encode/decode
│   ├── test_hci_controller.py   # HCI flow control、event routing
│   ├── test_l2cap_sar.py        # L2CAP 分段重组
│   ├── test_l2cap_signaling.py  # L2CAP 信令
│   ├── test_att_pdu.py          # ATT PDU encode/decode
│   ├── test_gatt_server.py      # GATT attribute 展开、request handling
│   ├── test_gatt_client.py      # GATT discovery、read/write
│   ├── test_smp_crypto.py       # SMP 加密函数（含 Spec 测试向量）
│   ├── test_smp_pairing.py      # SMP 配对状态机
│   ├── test_sdp.py              # SDP DataElement、ServiceRecord
│   ├── test_rfcomm.py           # RFCOMM 帧编解码、MUX 状态机
│   ├── test_gap_advertising.py  # AdvertisingData encode/decode
│   ├── test_statemachine.py     # StateMachine 转换、超时
│   ├── test_sig_db.py           # SIGDatabase 查表
│   └── test_yaml_loader.py      # YAML Service 加载
├── integration/                 # 集成测试
│   ├── test_hci_l2cap.py        # HCI + L2CAP 联动
│   ├── test_l2cap_att_gatt.py   # L2CAP + ATT + GATT 联动
│   ├── test_rfcomm_l2cap.py     # RFCOMM + L2CAP 联动
│   └── test_virtual_controller.py  # VirtualController 双向通信
├── e2e/                         # 端到端测试（Loopback 双栈）
│   ├── test_ble_scan_connect.py # BLE 扫描 → 连接
│   ├── test_gatt_profile.py     # GATT Profile 交互（HRS/BAS/DIS）
│   ├── test_smp_pairing.py      # SMP 配对 → 加密
│   ├── test_spp.py              # SPP 端到端
│   └── test_classic_discovery.py # Classic Inquiry → 连接
├── btsnoop/                     # Btsnoop 回放测试
│   ├── test_hci_decode.py       # 真实数据解码验证
│   └── test_protocol_replay.py  # 协议流程回放
└── hardware/                    # 硬件测试（需物理蓝牙适配器）
    ├── conftest.py              # 硬件 fixtures
    ├── test_transport_usb.py    # USB 打开/固件加载
    ├── test_ble_scan.py         # 真实 BLE 扫描
    ├── test_ble_connect.py      # 真实连接 + GATT
    ├── test_smp_pairing.py      # 真实配对
    ├── test_spp.py              # 真实 SPP
    ├── test_dual_adapter.py     # 双适配器对测
    └── test_interop/            # 互操作性（手机/PC）
```

## 14.5 各层测试要点

### Transport 层

| 测试项 | 方法 |
|--------|------|
| H4 帧解析 | 数据测试：各种 packet type indicator + 边界长度 |
| USB endpoint 路由 | 单元测试：验证 Command/Event/ACL/SCO 走正确 endpoint |
| 固件加载流程 | 单元测试：FakeTransport 模拟 vendor command 响应序列 |
| 断线重连 | 单元测试：模拟连接断开 → 验证重连策略触发 |

### HCI 层

| 测试项 | 方法 |
|--------|------|
| 所有 Packet encode/decode | 数据测试：每种 opcode/event code 往返验证 |
| Command credit 管理 | 单元测试：并发发送 → 验证排队和释放 |
| ACL buffer flow control | 单元测试：发送超过 buffer 数量 → 验证阻塞和恢复 |
| Event routing | 单元测试：注入各种 event → 验证路由到正确 handler |
| 初始化序列 | 单元测试：FakeTransport 按序回复 → 验证 16 步完成 |
| VirtualController | 集成测试：发送 command → 验证返回正确 event |
| 超时处理 | 单元测试：command 不回复 → 验证超时异常 |

### L2CAP 层

| 测试项 | 方法 |
|--------|------|
| 分段重组（SAR） | 单元测试：多种分段模式 → 验证完整 PDU 重组 |
| 固定信道路由 | 单元测试：CID=0x0004/0x0006 → 验证路由到正确 handler |
| LE CoC 信用流控 | 单元测试：发送数据消耗 credit → credit 耗尽阻塞 → 归还恢复 |
| Classic 信道建立 | 单元测试：Connection_Request → Response → Configure 状态机 |
| ERTM 重传 | 单元测试：模拟丢帧 → 验证重传触发和序号管理 |
| Signaling 解析 | 数据测试：各种 signaling command encode/decode |

### BLE 协议层（ATT/GATT/SMP）

| 测试项 | 方法 |
|--------|------|
| ATT PDU 编解码 | 数据测试：所有 opcode 往返验证 |
| ATT MTU 协商 | 单元测试：Exchange MTU 请求/响应 |
| GATT Service 展开 | 单元测试：ServiceDefinition → attribute 序列验证 |
| GATT Client Discovery | 单元测试：模拟 ATT 响应 → 验证 service/characteristic 发现 |
| GATT Notify/Indicate | 集成测试：Server 发通知 → 验证 Client 收到 |
| SMP 加密函数 | 数据测试：Spec 附录 D 测试向量，c1/s1/f4/f5/f6/g2/ah/h6/h7 |
| SMP 配对状态机 | 单元测试：各种 IO Capability 组合 → 验证配对模型选择 |
| SMP SC 流程 | 单元测试：Public Key → Confirm → Random → DHKey Check 全流程 |
| Bond 持久化 | 单元测试：save → load → delete → list |

### Classic 协议层（SDP/RFCOMM/SPP）

| 测试项 | 方法 |
|--------|------|
| DataElement 编解码 | 数据测试：各种 type（uint/uuid/text/sequence）往返验证 |
| SDP ServiceRecord | 单元测试：注册/查询/反注册 |
| SDP Client 查询 | 单元测试：模拟 SDP 响应 → 验证 find_rfcomm_channel |
| RFCOMM 帧编解码 | 数据测试：SABM/UA/DM/DISC/UIH 往返验证 |
| RFCOMM MUX 建立 | 单元测试：SABM on DLCI 0 → UA → PN → MSC 状态机 |
| RFCOMM 信用流控 | 单元测试：发送消耗 credit → 补充恢复 |
| SPP 端到端 | E2E 测试：SDP 注册 → RFCOMM 连接 → 数据收发 |

### GAP 层

| 测试项 | 方法 |
|--------|------|
| AdvertisingData 编解码 | 数据测试：各种 AD Structure 往返验证 |
| BLE 扫描 | 单元测试：模拟 LE_Advertising_Report → 验证 ScanResult |
| BLE 连接 | 单元测试：Create_Connection → Connection_Complete 状态机 |
| RPA 生成/解析 | 单元测试：IRK → RPA → resolve 验证 |
| Classic Inquiry | 单元测试：模拟 Inquiry_Result → 验证 InquiryResult |
| SSP 配对 | 单元测试：IO_Capability 交换 → User_Confirmation 状态机 |

### Profile 层

| 测试项 | 方法 |
|--------|------|
| YAML 加载 | 单元测试：加载内置 YAML → 验证 ServiceDefinition 结构 |
| 装饰器绑定 | 单元测试：@ble_service + @on_read → 验证回调注册 |
| Profile Server 注册 | 单元测试：register → 验证 GATT attribute 创建 |
| Profile E2E | E2E 测试：9 个内置 Profile 逐一 Loopback 验证 |

## 14.6 覆盖率要求

| 层 | 最低行覆盖率 | 说明 |
|----|-------------|------|
| `core/` | 95% | 基础设施，所有上层依赖 |
| `hci/packets.py` | 100% | encode/decode 必须全覆盖 |
| `hci/controller.py` | 90% | 状态机和 flow control |
| `l2cap/` | 90% | 信道管理和 SAR |
| `ble/att.py` | 95% | PDU 编解码 + Bearer 逻辑 |
| `ble/gatt.py` | 90% | Server/Client 逻辑 |
| `ble/smp.py` | 85% | 配对状态机复杂，部分分支难触发 |
| `classic/` | 85% | SDP/RFCOMM/SPP |
| `profiles/` | 80% | Profile 行为逻辑 |
| `transport/` | 70% | 依赖硬件的部分用 Fake 测试，平台特定代码难覆盖 |
| **整体** | **85%** | |

## 14.7 CI 集成

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: true  # SIG 仓库
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run pytest tests/ -v --cov=pybluehost --cov-report=xml
      - uses: codecov/codecov-action@v4
```

### pytest 配置

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "e2e: end-to-end tests using loopback stacks",
    "btsnoop: tests using real btsnoop capture data",
    "hardware: requires physical Bluetooth adapter",
    "dual_adapter: requires two physical adapters",
    "slow: tests that take more than 5 seconds",
]

[tool.coverage.run]
source = ["pybluehost"]
omit = [
    "pybluehost/lib/*",       # SIG 仓库数据不计入覆盖率
    "pybluehost/transport/usb.py",  # 平台特定，CI 无法测试
]
```

### 测试命令

```bash
# 运行全部测试
uv run pytest

# 仅运行单元测试
uv run pytest tests/unit/

# 仅运行端到端测试
uv run pytest tests/e2e/ -m e2e

# 运行特定层的测试
uv run pytest tests/unit/test_hci_packets.py

# 带覆盖率报告
uv run pytest --cov=pybluehost --cov-report=html

# 跳过慢速测试
uv run pytest -m "not slow"
```

## 14.8 Btsnoop 回放测试

利用真实蓝牙抓包数据验证协议解析的正确性。

```python
async def test_replay_ble_connection():
    """回放真实 BLE 连接过程，验证各层解析无异常"""
    stack = await Stack.from_btsnoop("tests/data/android_ble_scan.btsnoop")

    events_received = []
    stack.hci.register_event_handler(
        HCI_LE_Meta_Event.event_code,
        lambda e: events_received.append(e)
    )

    await stack.replay()  # 按时间戳回放所有 packet

    # 验证成功解析了预期数量的事件
    assert len(events_received) > 0
    # 验证无解析异常（如果有，replay 会抛出）
```

### 测试数据来源

| 数据文件 | 来源 | 覆盖场景 |
|----------|------|----------|
| `android_ble_scan.btsnoop` | Android HCI snoop log | BLE 扫描、广播解析 |
| `classic_spp_session.btsnoop` | 手动抓取 | SDP 查询、RFCOMM 连接、SPP 数据 |
| `smp_pairing_sc.btsnoop` | 手动抓取 | SMP SC 配对全流程 |
| `l2cap_coc.btsnoop` | 手动抓取 | LE CoC 信道建立和数据传输 |

测试数据应脱敏（去除真实 BD_ADDR），提交到 `tests/data/` 目录。

## 14.9 硬件测试

软件测试（单元/集成/Loopback）验证协议逻辑的正确性，但无法覆盖真实硬件环境中的问题：固件兼容性、时序约束、射频信号质量、跨设备互操作性等。硬件测试是发现实际问题不可替代的手段。

### 14.9.1 测试矩阵

#### Controller 硬件矩阵

| 芯片 | Transport | 平台 | 测试重点 |
|------|-----------|------|----------|
| Intel AX200/AX210 | USB (WinUSB) | Windows | 固件加载、HCI 初始化、BLE + Classic |
| Intel AC 7260/8265 | USB (WinUSB) | Windows | 旧固件兼容性 |
| Realtek RTL8761B | USB (WinUSB) | Windows | Realtek 固件加载流程 |
| Realtek RTL8852AE | USB (WinUSB) | Windows | BT 5.2 特性 |
| Intel AX200 | USB (hci_user_channel) | Linux | Linux 平台验证 |
| 通用 HCI UART | UART H4 | Linux | 嵌入式场景验证 |
| 任意 Controller | TCP | 跨平台 | 远程 Controller 场景 |

#### 对端设备矩阵

| 对端 | 用途 |
|------|------|
| Android 手机 | BLE 扫描/连接/GATT/配对 互操作性 |
| iOS 设备 | BLE 扫描/连接/GATT/配对 互操作性 |
| Windows PC | Classic SPP/配对 互操作性 |
| 另一套 PyBlueHost | 双端可控的精确测试 |
| Bluetooth PTS | 协议一致性认证测试（v2.0） |

### 14.9.2 硬件测试用例

#### Transport + 固件加载

```python
@pytest.mark.hardware
@pytest.mark.parametrize("vid_pid", [
    (0x8087, 0x0029),  # Intel AX200
    (0x8087, 0x0032),  # Intel AX210
    (0x0BDA, 0xB009),  # Realtek RTL8761B
])
async def test_usb_open_and_init(vid_pid):
    """真实 USB 适配器：打开 → 固件加载 → HCI 初始化 → 读取 BD_ADDR"""
    stack = await Stack.from_usb(vid_pid=vid_pid)
    assert stack.is_powered
    assert stack.local_address != BDAddress.EMPTY
    await stack.close()

@pytest.mark.hardware
async def test_uart_open(uart_port):
    """真实 UART 适配器：打开 → HCI Reset → 读取版本"""
    stack = await Stack.from_uart(port=uart_port)
    assert stack.is_powered
    await stack.close()
```

#### BLE 广播与扫描

```python
@pytest.mark.hardware
async def test_ble_scan_real():
    """真实硬件扫描：验证能发现周围 BLE 设备"""
    async with await Stack.from_usb() as stack:
        results = await stack.gap.ble_scanner.scan_for(5.0)
        assert len(results) > 0
        for r in results:
            assert r.address is not None
            assert r.rssi < 0  # RSSI 应为负值

@pytest.mark.hardware
async def test_ble_advertise_real():
    """真实硬件广播：启动广播 → 手机可发现"""
    async with await Stack.from_usb() as stack:
        ad = AdvertisingData()
        ad.set_flags(0x06)
        ad.set_complete_local_name("PyBH-Test")
        await stack.gap.ble_advertiser.start(AdvertisingConfig(), ad)

        # 广播 10 秒，期间用手机验证可见性
        await asyncio.sleep(10.0)
        await stack.gap.ble_advertiser.stop()
```

#### BLE 连接与 GATT 交互

```python
@pytest.mark.hardware
async def test_ble_connect_and_gatt(target_address):
    """真实连接：连接目标设备 → 发现服务 → 读取 Characteristic"""
    async with await Stack.from_usb() as stack:
        conn = await stack.gap.ble_connections.connect(
            BDAddress.from_string(target_address)
        )
        assert conn is not None

        client = GATTClient(conn)
        services = await client.discover_all_services()
        assert len(services) > 0

        # 读取 Device Name (通常所有 BLE 设备都有)
        for svc in services:
            chars = await client.discover_characteristics(svc)
            for c in chars:
                if c.uuid == UUID16(0x2A00):  # Device Name
                    name = await client.read_characteristic(c)
                    assert len(name) > 0

        await stack.gap.ble_connections.disconnect(conn.handle)
```

#### SMP 配对（与手机）

```python
@pytest.mark.hardware
async def test_smp_pairing_with_phone(target_address):
    """与手机配对：Just Works 或 Numeric Comparison"""
    config = StackConfig(
        security=SecurityConfig(le_sc_enabled=True),
        pairing_delegate=ConsoleDelegate(),  # 终端交互式确认
    )
    async with await Stack.from_usb(config=config) as stack:
        conn = await stack.gap.ble_connections.connect(
            BDAddress.from_string(target_address)
        )
        result = await conn.smp.pair(conn.handle, sc=True)
        assert result.success
        assert result.encrypted
```

#### Classic SPP（与手机/PC）

```python
@pytest.mark.hardware
async def test_spp_with_phone():
    """SPP Server：注册服务 → 等待手机连接 → 数据收发"""
    async with await Stack.from_usb() as stack:
        await stack.gap.classic_discoverability.set_discoverable(True)
        await stack.gap.classic_discoverability.set_connectable(True)
        await stack.gap.classic_discoverability.set_device_name("PyBH-SPP")

        spp = SPPService(stack.rfcomm, stack.sdp)
        await spp.register(channel=1, name="Test Port")

        connected = asyncio.Event()
        async def handle(conn: SPPConnection):
            connected.set()
            async with conn:
                while data := await conn.recv():
                    await conn.send(b"Echo: " + data)
        spp.on_connection(handle)

        # 等待手机通过蓝牙串口 App 连接
        await asyncio.wait_for(connected.wait(), timeout=60.0)
```

#### 双 PyBlueHost 硬件对测

```python
@pytest.mark.hardware
@pytest.mark.dual_adapter
async def test_dual_adapter_ble_e2e():
    """两个物理 USB 适配器：完整 BLE 流程"""
    stack_a = await Stack.from_usb(vid_pid=(0x8087, 0x0029))  # Intel #1
    stack_b = await Stack.from_usb(vid_pid=(0x0BDA, 0xB009))  # Realtek #2

    # stack_b 广播
    hrs = HeartRateServer()
    await hrs.register(stack_b.gatt_server)
    ad = AdvertisingData()
    ad.set_flags(0x06)
    ad.add_service_uuid16(0x180D)
    await stack_b.gap.ble_advertiser.start(AdvertisingConfig(), ad)

    # stack_a 扫描 → 连接 → GATT 交互
    results = await stack_a.gap.ble_scanner.scan_for(5.0)
    target = next(r for r in results if r.address == stack_b.local_address)
    conn = await stack_a.gap.ble_connections.connect(target.address)

    client = HeartRateClient()
    await client.discover(conn.gatt_client)
    location = await client.read_sensor_location()
    assert location == 0x01

    await stack_a.close()
    await stack_b.close()
```

### 14.9.3 PTS 一致性测试（v1.1）

PTS（Profile Tuning Suite）是 Bluetooth SIG 官方的协议一致性测试工具。v1.1 版本将支持 PyBlueHost 作为 IUT（Implementation Under Test）接入 PTS。

```
┌──────────┐         ┌──────────┐
│   PTS    │ ◄─BT──► │ PyBH IUT │
│ (Tester) │         │ (Stack)  │
└──────────┘         └──────────┘
      │
      │ COM / Automation API
      ▼
┌──────────────┐
│  PTS Client  │  ← PyBlueHost PTS 自动化脚本
└──────────────┘
```

PTS 测试覆盖的协议一致性项：
- GAP：广播、扫描、连接、配对、安全等级
- GATT：Service Discovery、Read/Write/Notify/Indicate
- SMP：所有配对模型（Just Works/Numeric Comparison/Passkey/OOB）
- L2CAP：信道建立、CoC、流控
- SDP/RFCOMM/SPP：Classic 协议栈一致性

### 14.9.4 硬件测试配置

```toml
# pyproject.toml
[tool.pytest.ini_options]
markers = [
    "hardware: requires physical Bluetooth adapter",
    "dual_adapter: requires two physical adapters",
    "phone: requires phone/tablet for interop testing",
    "pts: requires Bluetooth PTS (v2.0)",
]
```

```bash
# 仅运行硬件测试
uv run pytest tests/ -m hardware

# 运行硬件 + 指定适配器
uv run pytest tests/ -m hardware --adapter-vid-pid=8087:0029

# 运行双适配器测试
uv run pytest tests/ -m dual_adapter

# 跳过硬件测试（CI 默认）
uv run pytest tests/ -m "not hardware"
```

### 14.9.5 硬件测试目录

```
tests/
├── hardware/                        # 硬件测试
│   ├── conftest.py                  # 硬件 fixtures（adapter 发现、跳过逻辑）
│   ├── test_transport_usb.py        # USB Transport 打开/固件加载
│   ├── test_transport_uart.py       # UART Transport 打开
│   ├── test_ble_scan.py             # 真实 BLE 扫描
│   ├── test_ble_advertise.py        # 真实 BLE 广播
│   ├── test_ble_connect.py          # 真实 BLE 连接 + GATT
│   ├── test_smp_pairing.py          # 真实 SMP 配对
│   ├── test_classic_inquiry.py      # 真实 Classic 设备发现
│   ├── test_spp.py                  # 真实 SPP 连接
│   ├── test_dual_adapter.py         # 双适配器对测
│   └── test_interop/               # 互操作性测试
│       ├── test_android.py          # Android 互操作
│       ├── test_ios.py              # iOS 互操作
│       └── test_windows.py          # Windows 互操作
└── ...
```

### 14.9.6 硬件测试 Fixtures

```python
# tests/hardware/conftest.py

def pytest_addoption(parser):
    parser.addoption("--adapter-vid-pid", default=None,
                     help="USB adapter VID:PID (e.g. 8087:0029)")
    parser.addoption("--uart-port", default=None,
                     help="UART port (e.g. /dev/ttyUSB0)")
    parser.addoption("--target-address", default=None,
                     help="Target device BD_ADDR for connection tests")

@pytest.fixture
def adapter_vid_pid(request):
    vid_pid = request.config.getoption("--adapter-vid-pid")
    if vid_pid is None:
        pytest.skip("No USB adapter specified (use --adapter-vid-pid)")
    vid, pid = vid_pid.split(":")
    return (int(vid, 16), int(pid, 16))

@pytest.fixture
def uart_port(request):
    port = request.config.getoption("--uart-port")
    if port is None:
        pytest.skip("No UART port specified (use --uart-port)")
    return port

@pytest.fixture
def target_address(request):
    addr = request.config.getoption("--target-address")
    if addr is None:
        pytest.skip("No target address specified (use --target-address)")
    return addr

@pytest.fixture
async def usb_stack(adapter_vid_pid):
    stack = await Stack.from_usb(vid_pid=adapter_vid_pid)
    yield stack
    await stack.close()
```
