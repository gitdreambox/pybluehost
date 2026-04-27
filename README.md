# PyBlueHost

面向测试、仿真和协议教学的专业级 Python 蓝牙 Host 协议栈。

PyBlueHost 用纯 Python 实现完整的 Bluetooth Host 协议栈。  
HCI、L2CAP、ATT/GATT、SMP、SDP、RFCOMM，以及 BLE 与 Classic 双模 GAP —— 全部基于 `asyncio` 构建。  
适用于快速原型开发、协议学习、无硬件集成测试，以及编写自定义 BLE/Classic profile 服务端与客户端。

- **纯 Python 3.10+，asyncio 原生**
- **无需真实硬件** —— 内置 `VirtualController` 与 `LoopbackTransport`，可在单元测试中跑完整协议栈
- **多种 Transport** —— UART、USB（PyUSB）、TCP、UDP、btsnoop replay、Linux HCI user-channel
- **9 个内置 BLE Profile** —— Battery、Heart Rate、DIS、GAP、GATT、Blood Pressure、HID、RSCS、CSCS
- **YAML-driven service definitions** —— 声明式定义自定义服务，无需手写 handler 样板
- **Trace and replay** —— 所有 HCI/L2CAP 包都流经 `TraceSystem`，可录制为 btsnoop 或 JSON Lines

---

## 安装

PyBlueHost 使用 [`uv`](https://github.com/astral-sh/uv) 管理依赖。

```bash
# 克隆
git clone https://github.com/gitdreambox/pybluehost.git
cd pybluehost
git submodule update --init   # SIG assigned-numbers 数据库

# 仅作为用户使用
uv sync

# 开发模式（追加 pytest 等测试工具）
uv sync --extra dev

# 验证
uv run pytest tests/ -m "not hardware"
```

依赖说明：

| 组别 | 包 | 用途 |
|------|-----|------|
| 默认 | `cryptography` | SMP 配对加密（AES/CMAC/ECDH） |
| 默认 | `pyserial-asyncio` | UARTTransport |
| 默认 | `pyusb` + `libusb-package` | USBTransport（Windows 自带 libusb-1.0.dll） |
| 默认 | `pyyaml` | Profile YAML 服务定义 |
| `dev` | `pytest` / `pytest-asyncio` / `pytest-cov` | 测试与覆盖率 |

> **Windows USB 用户**：仍需用 [Zadig](https://zadig.akeo.ie/) 把目标适配器替换为 WinUSB 驱动。
> `libusb-package` 解决了 DLL 查找问题，但驱动绑定无法绕过。

---

## 快速开始

### 在单进程内运行完整 BLE 协议栈

```python
import asyncio
from pybluehost import Stack

async def main():
    async with await Stack.virtual() as stack:
        print(f"Local address: {stack.local_address}")
        print(f"Powered: {stack.is_powered}")
        # stack.gap, stack.gatt_server, stack.l2cap, stack.hci 全部就绪

asyncio.run(main())
```

`Stack.virtual()` 基于 `VirtualController` 构建一个完整协议栈 —— 不需要任何蓝牙硬件，所有 HCI 命令都在进程内仿真器中流转。

### 连接真实硬件

```python
from pybluehost import Stack
from pybluehost.transport.uart import UARTTransport

async def main():
    transport = UARTTransport(port="/dev/ttyUSB0", baudrate=115200)
    stack = await Stack._build(transport=transport)
    # ... 使用 stack.gap, stack.gatt_server 等
    await stack.close()
```

### 连接 USB 蓝牙适配器

```python
from pybluehost import Stack
from pybluehost.transport.usb import USBTransport
from pybluehost.transport.firmware import FirmwarePolicy

async def main():
    # 自动枚举 USB 设备，匹配已知 Intel/Realtek/CSR 芯片
    transport = USBTransport.auto_detect(
        firmware_policy=FirmwarePolicy.LOAD_IF_NEEDED,
    )
    stack = await Stack._build(transport=transport)
    try:
        print(f"Local address: {stack.local_address}")
        # ... 使用 stack.gap, stack.gatt_server 等
    finally:
        await stack.close()
```

按厂商过滤（仅 Intel）：

```python
transport = USBTransport.auto_detect(vendor="intel")
```

需要直接通过 Linux 内核 HCI socket 时（绕过 BlueZ daemon），使用 `pybluehost.transport.hci_user_channel.HCIUserChannelTransport(hci_index=0)`。

---

## 构建 BLE GATT 服务端

使用装饰器驱动的 profile 框架：

```python
from pybluehost import Stack
from pybluehost.core.uuid import UUID16
from pybluehost.profiles.ble import BLEProfileServer
from pybluehost.profiles.ble.decorators import on_read, on_write, on_notify

class MyTemperatureService(BLEProfileServer):
    service_uuid = UUID16(0x1809)  # Health Thermometer

    def __init__(self):
        self._temp = 250  # 25.0°C，单位 0.1°C

    @on_read(UUID16(0x2A1C))
    async def read_temp(self) -> bytes:
        return self._temp.to_bytes(2, "little")

    @on_write(UUID16(0x2A1C))
    async def write_temp(self, value: bytes) -> None:
        self._temp = int.from_bytes(value, "little")

    @on_notify(UUID16(0x2A1C))
    async def notify_temp(self) -> bytes:
        return self._temp.to_bytes(2, "little")

async def main():
    async with await Stack.virtual() as stack:
        service = MyTemperatureService()
        await service.register(stack.gatt_server)
        # 服务已上线 —— 客户端可读、可写、可订阅
```

### 使用内置 Profile

```python
from pybluehost.profiles.ble import BatteryServer, HeartRateServer

async def main():
    async with await Stack.virtual() as stack:
        battery = BatteryServer(initial_level=85)
        hrs = HeartRateServer(sensor_location=0x02)  # 手腕
        await battery.register(stack.gatt_server)
        await hrs.register(stack.gatt_server)

        # 推送一次 notification
        await hrs.update_measurement(bpm=72)
```

可用的内置 Profile：`BatteryServer`/`Client`、`HeartRateServer`/`Client`、
`DeviceInformationServer`/`Client`、`BloodPressureServer`、`HIDServer`、`RSCServer`、
`CSCServer`、`GAPServiceServer`、`GATTServiceServer`。

---

## BLE 客户端

```python
from pybluehost.profiles.ble import BatteryClient

async def main():
    async with await Stack.virtual() as stack:
        # ... 通过 stack.gap.ble_connections.connect(...) 建立连接
        gatt_client = ...  # 从已连接的 GATTClient 获得

        battery = BatteryClient()
        await battery.discover(gatt_client)
        level = await battery.read_battery_level()
        print(f"Remote battery: {level}%")
```

---

## Classic 蓝牙（BR/EDR）

```python
from pybluehost import Stack
from pybluehost.classic.gap import InquiryConfig

async def main():
    async with await Stack.virtual() as stack:
        # 设备发现
        await stack.gap.classic_discovery.start(InquiryConfig(duration=8))

        # 设置可发现 + 可连接
        await stack.gap.classic_discoverability.set_discoverable(True)
        await stack.gap.classic_discoverability.set_device_name("MyDevice")

        # SDP 服务（自动注册）和 RFCOMM 通过下列入口访问：
        # stack.sdp, stack.rfcomm
```

---

## 追踪与回放

所有 HCI/L2CAP 包都流经 `stack.trace`。挂接 sink 即可录制：

```python
from pybluehost import Stack, StackConfig
from pybluehost.core.trace import BtsnoopSink, JsonSink

config = StackConfig(
    trace_sinks=[
        BtsnoopSink("session.btsnoop"),   # Wireshark 兼容
        JsonSink("session.jsonl"),         # 每行一个 JSON 对象
    ],
)
async with await Stack.virtual(config=config) as stack:
    await stack.trace.start()
    # ... 业务代码 ...
    await stack.trace.stop()  # flush 所有 sink
```

回放已抓取的 btsnoop 文件作为 transport：

```python
from pybluehost.transport.btsnoop import BtsnoopTransport

transport = BtsnoopTransport(path="capture.btsnoop", realtime=False)
# 与普通 transport 一样使用 —— 包从文件中按序注入
```

---

## 配置

`StackConfig` 控制设备级默认值：

```python
from pybluehost import StackConfig
from pybluehost.core.types import IOCapability
from pybluehost.ble.security import SecurityConfig

config = StackConfig(
    device_name="MyDevice",
    appearance=0x0341,                                 # Heart Rate Sensor
    le_io_capability=IOCapability.DISPLAY_YES_NO,
    classic_io_capability=IOCapability.DISPLAY_YES_NO,
    security=SecurityConfig(
        bondable=True,
        mitm_required=True,
        secure_connections=True,
    ),
    command_timeout=5.0,
)
```

---

## 命令行工具

PyBlueHost CLI 分为两个命名空间：

- `pybluehost app <cmd>` — 需要打开 HCI transport，跑真实蓝牙功能
- `pybluehost tools <cmd>` — 离线工具，不需要 transport

### app（蓝牙功能，必填 `--transport`）

```bash
# 长跑命令（Ctrl+C 结束）
uv run pybluehost app ble-scan --transport usb
uv run pybluehost app ble-adv --transport usb --name MyDevice
uv run pybluehost app classic-inquiry --transport usb
uv run pybluehost app gatt-server --transport virtual
uv run pybluehost app hr-monitor --transport virtual
uv run pybluehost app spp-echo --transport usb

# 一次性命令
uv run pybluehost app gatt-browser --transport virtual
uv run pybluehost app sdp-browser --transport virtual
```

`--transport` 接受 `virtual` / `usb` / `usb:vendor=intel` / `uart:/dev/ttyUSB0[@115200]`。

### tools（离线工具）

```bash
# HCI 包解码
uv run pybluehost tools decode 01030c00

# RPA 计算
uv run pybluehost tools rpa gen-irk
uv run pybluehost tools rpa gen-rpa --irk <32-hex>
uv run pybluehost tools rpa verify --irk <32-hex> --addr AA:BB:CC:DD:EE:FF

# 固件管理
uv run pybluehost tools fw list
uv run pybluehost tools fw download <chip>

# USB 诊断
uv run pybluehost tools usb scan
```

---

## 测试

```bash
# 全套（排除硬件测试）
uv run pytest tests/ -m "not hardware"

# 指定层
uv run pytest tests/unit/ble/ -v
uv run pytest tests/unit/profiles/ -v

# 仅 btsnoop 回放测试
uv run pytest -m btsnoop

# 带覆盖率
uv run pytest tests/ --cov=pybluehost --cov-report=term-missing

# 真实硬件（需要 USB 蓝牙适配器）
uv run pytest tests/hardware/ --hardware
```

Marker 分组：`unit`、`integration`、`e2e`、`btsnoop`、`hardware`、`slow`。

---

## 架构

```
┌─────────────────── Profiles (Battery, HRS, HID, ...) ───────────────────┐
│                                                                          │
├──── GAP (BLE + Classic 统一入口) ──┬── GATT ────┬── SDP ─── RFCOMM ─────┤
│                                     │            │                       │
│           ATT ─ SMP                 │            │                       │
│                                                                          │
├─────────────────────────── L2CAP ───────────────────────────────────────┤
│                                                                          │
├─────────────────────── HCI（命令、事件、ACL、流控）──────────────────────┤
│                                                                          │
└─────────────── Transport (UART, USB, TCP, UDP, btsnoop, loopback) ──────┘
```

详细文档：
- [docs/PRD.md](docs/PRD.md) —— 产品需求
- [docs/architecture/](docs/architecture/) —— 逐层设计
- [docs/superpowers/STATUS.md](docs/superpowers/STATUS.md) —— 实现进度

---

## 项目状态

全部 16 个实施 Plan 均已完成：

- **Core 层** —— address、UUID、errors、状态机、trace、SIG 数据库
- **Transport 层** —— UART、USB、TCP、UDP、loopback、btsnoop 回放、HCI user-channel
- **HCI 层** —— packet codec、流控、controller、virtual controller、vendor（Intel/Realtek）
- **L2CAP 层** —— SAR、固定/CoC 通道、ERTM、信令、manager
- **BLE** —— ATT、GATT（server + client）、SMP、SecurityConfig、GAP（广播/扫描/连接/隐私/白名单）
- **Classic** —— SDP、RFCOMM、SPP、GAP（inquiry/SSP/可发现性）
- **Profiles** —— 9 个内置 BLE Profile + 装饰器驱动的自定义 Profile 框架
- **Stack 装配** —— `Stack` 工厂，支持 virtual 模式与 async 上下文管理器
- **测试基础设施** —— 600+ 测试，覆盖率 88%，btsnoop 回放，CI 矩阵（Python 3.10/3.11/3.12）

---

## 许可证

MIT —— 详见 [LICENSE](LICENSE)（如存在）或 `pyproject.toml`。

---

## 贡献

开发流程基于 plan 驱动的实施模式。贡献者指南见 [CLAUDE.md](CLAUDE.md)，任务看板见 [docs/superpowers/STATUS.md](docs/superpowers/STATUS.md)。
