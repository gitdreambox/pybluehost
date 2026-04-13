# 第十三节：Stack 工厂与顶层 API

## 13.1 概述

`Stack` 是 PyBlueHost 的顶层入口，负责组装整个协议栈、管理生命周期、对外暴露各层功能。用户通过工厂方法一行代码创建完整可用的协议栈实例。

## 13.2 模块位置

```
pybluehost/
├── stack.py             # Stack 类 + StackConfig
└── __init__.py          # 导出 Stack, StackConfig
```

## 13.3 Stack 类

```python
class Stack:
    """顶层入口：组装并管理整个协议栈生命周期"""

    # ── 工厂方法 ──
    @classmethod
    async def from_usb(cls, vid_pid: tuple[int, int] | None = None,
                        config: StackConfig = StackConfig()) -> "Stack":
        """从 USB 蓝牙适配器创建（自动检测 VID/PID，含固件加载）"""

    @classmethod
    async def from_uart(cls, port: str, baudrate: int = 115200,
                         config: StackConfig = StackConfig()) -> "Stack":
        """从 UART 串口创建（H4 协议）"""

    @classmethod
    async def from_tcp(cls, host: str, port: int,
                        config: StackConfig = StackConfig()) -> "Stack":
        """从 TCP 连接创建（远程 Controller）"""

    @classmethod
    async def from_udp(cls, host: str, port: int,
                        config: StackConfig = StackConfig()) -> "Stack":
        """从 UDP 连接创建"""

    @classmethod
    async def loopback(cls, config_a: StackConfig = StackConfig(),
                        config_b: StackConfig = StackConfig()) -> tuple["Stack", "Stack"]:
        """创建互联的双栈（VirtualController 对接，用于测试和教学）"""

    @classmethod
    async def from_btsnoop(cls, path: str) -> "Stack":
        """从 btsnoop 日志文件回放"""

    # ── 生命周期 ──
    async def power_on(self) -> None:
        """执行 HCI 初始化序列，启动协议栈"""

    async def power_off(self) -> None:
        """关闭所有连接，停止广播/扫描"""

    async def close(self) -> None:
        """释放所有资源，关闭 Transport"""

    async def __aenter__(self) -> "Stack":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    # ── 层访问 ──
    @property
    def hci(self) -> HCIController: ...

    @property
    def l2cap(self) -> L2CAPManager: ...

    @property
    def gap(self) -> GAP: ...

    @property
    def gatt_server(self) -> GATTServer: ...

    def gatt_client_for(self, conn_handle: int) -> GATTClient:
        """获取指定连接的 GATT Client"""

    @property
    def sdp(self) -> SDPServer: ...

    @property
    def rfcomm(self) -> RFCOMMManager: ...

    @property
    def sig_db(self) -> SIGDatabase: ...

    @property
    def trace(self) -> TraceSystem: ...

    @property
    def config(self) -> StackConfig: ...

    # ── 状态查询 ──
    @property
    def local_address(self) -> BDAddress: ...

    @property
    def is_powered(self) -> bool: ...

    @property
    def connections(self) -> list[HCIConnection]: ...
```

## 13.4 StackConfig

```python
@dataclass
class StackConfig:
    """协议栈配置，所有选项都有合理默认值"""

    # ── Transport ──
    firmware_policy: FirmwarePolicy = FirmwarePolicy.AUTO_DOWNLOAD
    reconnect_policy: ReconnectPolicy = ReconnectPolicy.NONE

    # ── Security ──
    security: SecurityConfig = field(default_factory=SecurityConfig)
    pairing_delegate: PairingDelegate = field(default_factory=AutoAcceptDelegate)
    bond_storage: BondStorage | None = None  # None → JsonBondStorage(默认路径)

    # ── GAP ──
    device_name: str = "PyBlueHost"
    appearance: int = 0x0000
    le_io_capability: IOCapability = IOCapability.NO_INPUT_NO_OUTPUT
    classic_io_capability: IOCapability = IOCapability.DISPLAY_YES_NO

    # ── Trace ──
    trace_sinks: list[TraceSink] = field(default_factory=list)

    # ── HCI ──
    command_timeout: float = 5.0
```

## 13.5 Stack 组装流程

```
from_usb(vid_pid, config)
  │
  ├─ 1. Transport 创建
  │     USBTransport.open(vid_pid)
  │     ├─ 自动检测芯片（VID/PID → KNOWN_CHIPS）
  │     └─ 固件加载（按 FirmwarePolicy 处理）
  │
  ├─ 2. Trace 系统初始化
  │     TraceSystem(config.trace_sinks)
  │
  ├─ 3. HCI 层组装
  │     HCIController(transport, trace)
  │
  ├─ 4. HCI 初始化序列（16 步）
  │     Reset → Read_Local_Version → Read_BD_ADDR → ...
  │     → Set_Event_Mask → Write_SSP_Mode → ...
  │
  ├─ 5. L2CAP 层组装
  │     L2CAPManager(hci, trace)
  │
  ├─ 6. BLE 协议层组装
  │     ├─ ATTBearer（固定信道 CID=0x0004）
  │     ├─ GATTServer + GATTClient
  │     └─ SMPManager（固定信道 CID=0x0006）
  │
  ├─ 7. Classic 协议层组装
  │     ├─ SDPServer（PSM=0x0001）
  │     └─ RFCOMMManager（PSM=0x0003）
  │
  ├─ 8. GAP 层组装
  │     GAP(ble_advertiser, ble_scanner, ble_connections,
  │         ble_privacy, classic_discovery, classic_discoverability,
  │         classic_connections, classic_ssp, whitelist)
  │
  ├─ 9. 安全配置
  │     ├─ PairingDelegate 绑定（SMP + SSP）
  │     └─ BondStorage 初始化 + 加载已有 bond
  │
  └─ 10. 返回 Stack 实例
```

## 13.6 Loopback 双栈模式

```python
stack_a, stack_b = await Stack.loopback()

# 内部实现：
# vc_a = VirtualController(address="AA:BB:CC:DD:EE:01")
# vc_b = VirtualController(address="AA:BB:CC:DD:EE:02")
# vc_a.connect_to(vc_b)
# stack_a = Stack(transport=LoopbackTransport(vc_a), ...)
# stack_b = Stack(transport=LoopbackTransport(vc_b), ...)

# ACL 数据双向流通，完整模拟两端 Host 交互
# 适用于：单元测试、Profile 开发、协议教学
```

### Loopback 测试示例

```python
async def test_gatt_read():
    stack_a, stack_b = await Stack.loopback()

    # stack_b 作为 Server
    hrs = HeartRateServer()
    await hrs.register(stack_b.gatt_server)
    await stack_b.gap.ble_advertiser.start(AdvertisingConfig(), ad_data)

    # stack_a 作为 Client
    results = await stack_a.gap.ble_scanner.scan_for(1.0)
    conn = await stack_a.gap.ble_connections.connect(results[0].address)

    client = HeartRateClient()
    await client.discover(conn.gatt_client)
    location = await client.read_sensor_location()
    assert location == 0x01

    await stack_a.close()
    await stack_b.close()
```

## 13.7 Btsnoop 回放模式

```python
# 从 btsnoop 日志文件回放 HCI 数据
stack = await Stack.from_btsnoop("capture.log")

# 回放模式下：
# - Transport 为 BtsnoopReplayTransport，按时间戳回放 HCI packet
# - 可注册 event handler 分析协议流程
# - 不可发送命令（只读模式）
# - 配合 TraceSystem 可重新解析并输出人类可读日志
```

## 13.8 使用示例

### 最简用法

```python
from pybluehost import Stack

async with await Stack.from_usb() as stack:
    results = await stack.gap.ble_scanner.scan_for(5.0)
    for r in results:
        print(f"{r.address} RSSI={r.rssi} {r.advertising_data}")
```

### 完整配置

```python
from pybluehost import Stack, StackConfig
from pybluehost.core import SecurityConfig, IOCapability
from pybluehost.core.trace import BtsnoopSink

config = StackConfig(
    device_name="MyDevice",
    appearance=0x0341,  # Running Walking Sensor
    security=SecurityConfig(
        le_sc_enabled=True,
        ctkd_enabled=False,
    ),
    pairing_delegate=MyCustomDelegate(),
    le_io_capability=IOCapability.DISPLAY_YES_NO,
    trace_sinks=[BtsnoopSink("trace.log")],
)

async with await Stack.from_usb(config=config) as stack:
    # 注册 Profile
    hrs = HeartRateServer()
    bas = BatteryServer()
    dis = DeviceInformationServer(manufacturer="PyBlueHost", model="Demo")

    await hrs.register(stack.gatt_server)
    await bas.register(stack.gatt_server)
    await dis.register(stack.gatt_server)

    # 广播
    ad = AdvertisingData()
    ad.set_flags(0x06)
    ad.set_complete_local_name("PyBH-HRM")
    ad.add_service_uuid16(0x180D)
    await stack.gap.ble_advertiser.start(AdvertisingConfig(), ad)

    # 等待连接
    stack.gap.ble_connections.on_connection(handle_connection)
    await asyncio.Event().wait()
```

### SPP Classic 示例

```python
async with await Stack.from_usb() as stack:
    # Server
    spp = SPPService(stack.rfcomm, stack.sdp)
    await spp.register(channel=1, name="My Serial Port")

    async def handle(conn: SPPConnection):
        async with conn:
            while data := await conn.recv():
                await conn.send(b"Echo: " + data)
    spp.on_connection(handle)
```
