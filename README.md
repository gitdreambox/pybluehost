# PyBlueHost

面向测试、仿真和协议教学的专业级 Python 蓝牙 Host 协议栈。

PyBlueHost 用纯 Python 实现完整的 Bluetooth Host 协议栈：HCI、L2CAP、ATT/GATT、SMP、SDP、RFCOMM，以及 BLE 与 Classic 双模 GAP —— 全部基于 `asyncio` 构建。适用于快速原型开发、协议学习、无硬件集成测试，以及编写自定义 BLE/Classic profile 服务端与客户端。

- **纯 Python 3.10+，asyncio 原生**
- **无需真实硬件** —— 内置 `VirtualController`，可在单元测试中跑完整协议栈
- **多种 Transport** —— UART、USB（PyUSB）、TCP、UDP、btsnoop replay、Linux HCI user-channel
- **9 个内置 BLE Profile** —— Battery、Heart Rate、DIS、GAP、GATT、Blood Pressure、HID、RSCS、CSCS
- **YAML-driven service definitions** —— 声明式定义自定义服务，无需手写 handler 样板
- **结构化 Trace** —— HCI 包按命令/事件名展开（带 SIG 查表），可彩色实时输出，也可录制为 btsnoop / JSON Lines

---

## 已测试硬件

| 芯片型号 | VID | PID | Transport | 协议版本 | 类型 | 固件名称 |
| --- | --- | --- | --- | --- | --- | --- |
| Realtek RTL8852BE | `0x0BDA` | `0x4853` | USB | 5.2 | BR/EDR + BLE | `rtl8852bu_fw.bin` |

CSR、Intel 系列芯片在代码中已支持但未在本仓库做完整回归。欢迎提 PR 补 hardware 矩阵。

---

# 一、测试用户篇（pip 安装 + CLI 验证）

> 适合：拿到设备想验证一下蓝牙功能，或者用 PyBlueHost 当临时 host 跑各种测试场景的人。
> 全程不需要写代码，CLI 命令就够。

## 1.1 安装

```bash
pip install pybluehost      # 包含运行 CLI 所需的全部依赖
```

依赖说明：

| 包 | 用途 |
|------|------|
| `cryptography` | SMP 配对加密（AES/CMAC/ECDH） |
| `pyserial-asyncio` | UART transport |
| `pyusb` + `libusb-package` | USB transport（Windows 自带 libusb-1.0.dll） |
| `pyyaml` | Profile YAML 服务定义 |

> 如果你用的是 git clone 而不是 pip install，记得 `git submodule update --init` 拉取 SIG assigned-numbers 数据库（company_id / UUID / AD type 名字查表用）。

## 1.2 第一次跑：列出硬件 + 诊断

```bash
# 列出所有检测到的 USB 蓝牙适配器
pybluehost --list-transports
# 或
pytest --list-transports

# USB 设备探测和驱动诊断（不打开设备，只读 USB 描述符）
pybluehost tools usb probe
pybluehost tools usb probe --verbose

# 完整诊断（尝试打开设备，给出"为什么打不开"的具体原因）
pybluehost tools usb diagnose
```

如果 `pybluehost --list-transports` 看不到任何适配器，看 §1.7 安装 / 硬件常见问题。

## 1.3 BLE 验证（CLI）

`--transport` 接受 `virtual`、`usb`、`usb:vendor=intel|realtek|csr`、`uart:/dev/ttyUSB0[@921600]`。机器上多块适配器时建议固定厂商 (`usb:vendor=csr`) 避免选错。

```bash
# 扫描周围 BLE 设备（长跑，Ctrl+C 结束）
pybluehost app ble-scan --transport usb

# 自己也广播让别的设备看到
pybluehost app ble-adv --transport usb --name MyDevice

# 一次性：浏览远端 GATT 数据库（services / characteristics / descriptors / properties）
pybluehost app gatt-browser --transport usb:vendor=csr --addr A0:90:B5:10:40:82

# 起一个 GATT server，让手机能连过来
pybluehost app gatt-server --transport virtual

# Heart Rate Sensor demo（带 notification 推送）
pybluehost app hr-monitor --transport virtual
```

地址格式：`A0:90:B5:10:40:82` 或 `A090B5104082` 都接受。

## 1.4 Classic 蓝牙验证（CLI）

```bash
# 经典蓝牙设备发现
pybluehost app classic-inquiry --transport usb

# 一次性：浏览远端 SDP records
pybluehost app sdp-browser --transport usb:vendor=csr --addr 1A:8D:8D:1B:F5:6B
pybluehost app sdp-browser --transport usb:vendor=csr --addr 1A8D8D1BF56B --uuid 0x1101

# SPP 服务（手机蓝牙串口终端连过来发字符串，会原样 echo 回去）
pybluehost app spp-echo --transport usb:vendor=csr
```

## 1.5 离线工具（不需要硬件）

```bash
# HCI 包十六进制 → 解码后的命令/事件
pybluehost tools decode 01030c00

# Resolvable Private Address（IRK / RPA / 验证）
pybluehost tools rpa gen-irk
pybluehost tools rpa gen-rpa --irk <32-hex>
pybluehost tools rpa verify --irk <32-hex> --addr AA:BB:CC:DD:EE:FF

# USB 蓝牙芯片固件管理
pybluehost tools fw list
pybluehost tools fw download <chip>
```

## 1.6 出问题怎么调试

最常用的三个命令：

```bash
# 看 HCI 包的实时人读输出（彩色单行）
pybluehost --trace=hci app gatt-browser --transport=usb --addr <bd>

# 出现握手失败 / 配对失败时 → 全层 debug，看协议层每一步
pybluehost --trace=*=debug app gatt-browser --transport=usb --addr <bd> 2> trace.log

# 给 maintainer 提 issue 时，附上的两个文件
ls pybluehost.log     # 默认日志文件
ls trace.log          # 你刚才重定向的 trace
```

输出长这样（成功事件单行，错误自动展开多行）：

```
↓ HCI Cmd  HCI_LE_Set_Scan_Params
↑ HCI Evt  Command_Complete                 op=0x200B status=Success
↑ HCI Evt  LE_Advertising_Report            Random F8:1A:94:1D:5C:62 rssi=-67 dBm
↑ HCI Evt  Command_Complete                 op=0x200C status=Invalid_HCI_Command_Parameters(0x12)
                                            ├── num_hci_command_packets = 1
                                            ├── command_opcode          = 0x200C
                                            └── status                  = 0x12 (Invalid_HCI_Command_Parameters)
```

需要更细的控制（按层独立级别、ACL payload 不截断、把默认抑制的事件加回来）见 §2.7 「调试与日志（深度版）」。

## 1.7 安装 / 硬件常见问题

**Linux：USB 权限 `Operation not permitted`**

```bash
# 临时方案：sudo 跑（不推荐长期）
sudo pybluehost app ble-scan --transport=usb

# 永久方案：加 udev 规则（以 Realtek RTL8852BE 为例）
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="4853", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/99-pybluehost.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
# 拔插一次设备
```

**Linux：`bluez` 守护进程占着设备**

```bash
sudo systemctl stop bluetooth         # 临时
sudo systemctl disable bluetooth      # 长期（如果你只用 PyBlueHost）
```

或者用 HCI user-channel transport 直接通过内核 socket 而不抢 BlueZ：见 `pybluehost.transport.hci_user_channel.HCIUserChannelTransport`。

**Windows：必须装 WinUSB 驱动**

USB transport 在 Windows 上需要把目标适配器替换为 WinUSB 驱动。`libusb-package` 解决了 DLL 查找问题，但驱动绑定无法绕过 —— 用 [Zadig](https://zadig.akeo.ie/) 替换。

**macOS：Apple 的蓝牙栈占着内置控制器**

macOS 上系统蓝牙 daemon 排他持有内置控制器；外接 USB 适配器才能让 PyBlueHost 用上。

**SIG 名字显示成 hex 而不是名字**

git clone 安装时漏了 submodule。跑：

```bash
git submodule update --init
```

`pip install pybluehost` 包里已经把 SIG 数据打进去了，不会有这个问题。

---

# 二、开发者篇（基于协议栈做二次开发，不改协议栈核心）

> 适合：想在 PyBlueHost 上加自定义 BLE profile / 起一个测试 server / 写自动化脚本但不想改协议栈代码的人。
> 大部分情况下，你只需要在最上面那层（profile / 应用代码）写代码就够了。

## 2.1 1 分钟看懂架构

```
┌─────────────────── Profiles (Battery, HRS, HID, ...) ───────────────────┐
│  ↑ 你写的代码大多数时候在这一层                                          │
├──── GAP (BLE + Classic 统一入口) ──┬── GATT ────┬── SDP ─── RFCOMM ─────┤
│                                     │            │                       │
│           ATT ─ SMP                 │            │                       │
├─────────────────────────── L2CAP ───────────────────────────────────────┤
├─────────────────────── HCI（命令、事件、ACL、流控）──────────────────────┤
└─────────────── Transport (UART, USB, TCP, UDP, btsnoop, virtual) ───────┘
```

调用方向：你的代码调 `stack.gap` / `stack.gatt_server` / `stack.sdp` / `stack.rfcomm`，下层一直传到 transport；事件反向上来，HCI controller 解码后通过 callback / channel 上送到对应层。

二次开发常见入口：

| 我想做的事 | 看哪儿 |
|-----------|------|
| 加一个新 BLE Service / Profile | `pybluehost/profiles/ble/`（参考 `battery.py` / `heart_rate.py` 这些短文件） |
| 写自动化测试脚本 | `pybluehost/cli/app/*.py`（每个 CLI 命令的真实实现都是单独的 .py，可读） |
| 自定义事件 callback / 录制 trace | `pybluehost.core.trace.TraceSystem` + sink，详见 §2.7 |
| 加一种新 transport | `pybluehost.transport.base.Transport` 接口（参考 `udp.py` 最短） |
| 改 HCI 命令处理 / vendor 命令 | `pybluehost/hci/`（不属于二次开发，慎重） |

## 2.2 安装（开发模式）

PyBlueHost 用 [`uv`](https://github.com/astral-sh/uv) 管理依赖。

```bash
git clone https://github.com/gitdreambox/pybluehost.git
cd pybluehost
git submodule update --init   # SIG assigned-numbers 数据库

uv sync --extra dev           # 包含 pytest、pytest-asyncio、pytest-cov

uv run pytest tests/ --transport=virtual    # 验证开发环境
```

## 2.3 启动协议栈

```python
import asyncio
from pybluehost import Stack

async def main():
    async with await Stack.virtual() as stack:
        print(f"Local address: {stack.local_address}")
        # stack.gap, stack.gatt_server, stack.l2cap, stack.hci, stack.trace 全部就绪

asyncio.run(main())
```

`Stack.virtual()` 基于 `VirtualController` 构建一个完整协议栈 —— 不需要任何蓝牙硬件，所有 HCI 命令都在进程内仿真器中流转。

接真实硬件：

```python
from pybluehost import Stack

# USB 自动探测（按 vendor 过滤可避免多块适配器选错）
stack = await Stack.from_usb(vendor="intel")

# UART
stack = await Stack.from_uart(port="/dev/ttyUSB0", baudrate=921600)
```

`StackConfig` 控制设备级默认值：

```python
from pybluehost import StackConfig
from pybluehost.core.types import IOCapability
from pybluehost.ble.security import SecurityConfig

config = StackConfig(
    device_name="MyDevice",
    appearance=0x0341,                          # Heart Rate Sensor
    le_io_capability=IOCapability.DISPLAY_YES_NO,
    security=SecurityConfig(
        bondable=True, mitm_required=True, secure_connections=True,
    ),
    command_timeout=5.0,
)
stack = await Stack.virtual(config=config)
```

## 2.4 写一个 BLE GATT Server

用装饰器驱动的 profile 框架（最小可运行版本，省略 imports）：

```python
from pybluehost.core.uuid import UUID16
from pybluehost.profiles.ble import BLEProfileServer
from pybluehost.profiles.ble.decorators import on_read, on_write, on_notify

class MyTemperatureService(BLEProfileServer):
    service_uuid = UUID16(0x1809)  # Health Thermometer

    def __init__(self):
        self._temp = 250  # 25.0°C, units 0.1°C

    @on_read(UUID16(0x2A1C))
    async def read_temp(self) -> bytes:
        return self._temp.to_bytes(2, "little")

    @on_write(UUID16(0x2A1C))
    async def write_temp(self, value: bytes) -> None:
        self._temp = int.from_bytes(value, "little")

    @on_notify(UUID16(0x2A1C))
    async def notify_temp(self) -> bytes:
        return self._temp.to_bytes(2, "little")

# 注册：
service = MyTemperatureService()
await service.register(stack.gatt_server)
```

用现成的内置 profile：

```python
from pybluehost.profiles.ble import BatteryServer, HeartRateServer

battery = BatteryServer(initial_level=85)
hrs = HeartRateServer(sensor_location=0x02)  # 手腕
await battery.register(stack.gatt_server)
await hrs.register(stack.gatt_server)

await hrs.update_measurement(bpm=72)   # 推送一次 notification
```

可用的内置 Profile：`BatteryServer`/`Client`、`HeartRateServer`/`Client`、`DeviceInformationServer`/`Client`、`BloodPressureServer`、`HIDServer`、`RSCServer`、`CSCServer`、`GAPServiceServer`、`GATTServiceServer`。

参考真实代码：`pybluehost/profiles/ble/battery.py`、`heart_rate.py`、`hids.py`（每个文件 < 50 行）。

## 2.5 写一个 BLE 客户端

`pybluehost/cli/app/gatt_browser.py` 是完整可运行的客户端示例（约 100 行）—— 扫描、连接、发现 services、按字段格式化打印。下面是缩微版：

```python
from pybluehost.profiles.ble import BatteryClient

async with await Stack.virtual() as stack:
    # 通过 stack.gap.ble_connections.connect(...) 建立连接
    gatt_client = ...     # 从已连接的 GATTClient 获得

    battery = BatteryClient()
    await battery.discover(gatt_client)
    level = await battery.read_battery_level()
    print(f"Remote battery: {level}%")
```

## 2.6 写一个 Classic 应用（SDP/RFCOMM/SPP）

```python
from pybluehost.classic.gap import InquiryConfig

async with await Stack.virtual() as stack:
    # 设备发现
    await stack.gap.classic_discovery.start(InquiryConfig(duration=8))

    # 设置可发现 + 可连接
    await stack.gap.classic_discoverability.set_discoverable(True)
    await stack.gap.classic_discoverability.set_device_name("MyDevice")

    # SDP / RFCOMM 通过下列入口访问
    # stack.sdp, stack.rfcomm
```

完整 SPP echo server 示例：`pybluehost/cli/app/spp_echo.py`。

## 2.7 自定义 Trace Sink + 录制 / 回放（调试与日志深度版）

PyBlueHost 内置结构化 trace 系统：HCI 包按命令/事件名展开（含字段、SIG company name 等查表），按层独立可控，彩色实时输出到 stderr。默认零开销 —— 不指定 `--trace` / 不挂 sink 时不做任何额外工作。

### 录制到文件

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
    # ... 业务代码 ...
    pass  # close() 会自动 flush 所有 sink
```

### 回放已抓取的 btsnoop

```python
from pybluehost.transport.btsnoop import BtsnoopTransport

transport = BtsnoopTransport(path="capture.btsnoop", realtime=False)
# 与普通 transport 一样使用 —— 包从文件中按序注入
```

### CLI / 环境变量控制

```bash
pybluehost --trace=hci app gatt-browser --transport=virtual            # HCI 层 INFO
pybluehost --trace=hci=debug,l2cap app gatt-browser --transport=usb    # HCI debug + L2CAP info
pybluehost --trace=*=debug app gatt-browser --transport=virtual        # 全部层 debug
pybluehost --trace=hci,full-acl app spp-echo --transport=usb           # ACL 不截断
pybluehost --trace=hci,include=Number_Of_Completed_Packets ...         # 把默认静音的事件加回来

PYBLUEHOST_TRACE=hci=debug pybluehost app ...                          # env var 同样生效
```

### Spec 语法（`--trace` / `PYBLUEHOST_TRACE` 共用）

| 形式 | 含义 |
|------|------|
| `<layer>` | 该层 INFO 级 |
| `<layer>=info` / `<layer>=debug` | 显式级别 |
| `*` / `*=debug` | 通配所有层 |
| `<layer1>,<layer2>=debug,...` | 多层、各自级别，逗号分隔 |
| `,full-acl` | ACL data 不截断（默认 24 字节） |
| `,include=<EventName>` | 把默认抑制的事件加回来 |

**层名字**：`hci`、`sm`（state machine）、`transport`、`l2cap`、`att`、`gatt`、`smp`、`sdp`、`rfcomm`、`gap`

### 颜色

ANSI 颜色按业界惯例自动决定（与 `git`、`grep`、`bat` 一致）：

- **默认**：stderr 是 TTY 时上色；重定向到管道/文件自动关
- `NO_COLOR=1` 强制关闭
- `FORCE_COLOR=1` 强制开启（CI 抓彩色日志用）

### 防刷屏默认

| 事件 | 默认行为 | 关闭抑制 |
|------|---------|---------|
| `Number_Of_Completed_Packets`（HCI flow control） | 完全静默 | `--trace=hci,include=Number_Of_Completed_Packets` |
| `LE_Advertising_Report`（同地址重复） | 折叠为一行 | `--trace=hci,include=LE_Advertising_Report` |
| ACL data 长 payload | 截断为前 24 字节 | `--trace=hci,full-acl` |

### 协议层 logger

L2CAP / ATT / GATT / SMP / SDP / RFCOMM / Classic GAP+SSP / HCI Connection 共约 40 个关键决策点会输出 INFO/WARN/DEBUG（连接开关、MTU exchange、Error_Response、pairing 阶段、inquiry 等）。它们走标准 Python `logging`，由 `--trace=<layer>=<level>` 调级别。

输出会同时进 `pybluehost.log` 文件（受 `--log-file` / `--log-level` 控制）。

### 编程方式安装 trace

```python
from pybluehost.core import (
    parse_trace_spec, trace_install,    # one-shot install
    apply_logging_levels, attach_console_sink,    # 拆分版本
)

stack = await Stack.virtual()
spec = parse_trace_spec("hci=debug,l2cap")
trace_install(spec, stack.trace)        # 给该 stack 挂 ConsoleSink + 调 logger 级别
```

## 2.8 跑测试套件

测试默认自动检测 USB 蓝牙适配器；找不到时回落到 virtual（软件仿真）。

```bash
# 全套（默认自动检测）
uv run pytest tests/

# 强制 virtual（CI 用）
uv run pytest tests/ --transport=virtual

# 指定子目录
uv run pytest tests/unit/ble/ -v
uv run pytest tests/unit/profiles/ -v

# 仅 btsnoop 回放测试
uv run pytest -m btsnoop

# 带覆盖率
uv run pytest tests/ --transport=virtual --cov=pybluehost --cov-report=term-missing

# 真硬件（按 vendor 过滤）
uv run pytest tests/ --transport=usb
uv run pytest tests/ --transport=usb:vendor=intel
uv run pytest tests/ --transport=usb:vendor=intel,bus=1,address=4

# UART
uv run pytest tests/ --transport=uart:/dev/ttyUSB0@921600

# 双适配器测试（peer 自动找第二块；找不到则跳过）
uv run pytest tests/ --transport=usb --transport-peer=usb:vendor=intel,bus=2,address=5

# pytest 内打开 trace（注意：pytest 选项叫 --pybluehost-trace 不叫 --trace）
uv run pytest tests/ --pybluehost-trace=hci --transport=virtual

# 通过环境变量
PYBLUEHOST_TEST_TRANSPORT=usb uv run pytest tests/

# 列出所有检测到的适配器
uv run pytest --list-transports
```

测试可以用 `@pytest.mark.real_hardware_only` 或 `@pytest.mark.virtual_only` 限制运行环境。Marker 分组：`unit` / `integration` / `e2e` / `btsnoop` / `slow` / `real_hardware_only` / `virtual_only`。

## 2.9 协议栈代码导航

```
pybluehost/
├── core/             # 通用基础：address、UUID、errors、状态机、trace、SIG DB
├── transport/        # UART / USB / TCP / UDP / btsnoop / HCI user-channel
├── hci/              # HCI packet codec、流控、controller、virtual controller、vendor
│   ├── format.py     # HCI 包人读字符串渲染
│   └── format_fields.py
├── l2cap/            # SAR、固定/CoC channel、ERTM、信令
├── ble/              # ATT / GATT / SMP / SecurityConfig
├── classic/          # SDP / RFCOMM / SPP / Classic GAP
├── gap.py            # BLE + Classic 统一 GAP 入口
├── profiles/ble/     # 9 个内置 profile + 装饰器框架
├── stack.py          # Stack 工厂 / 生命周期 / TraceSystem 启动
└── cli/
    ├── app/          # 8 个 BT 功能命令（每个一文件，~50-150 行，可读）
    └── tools/        # 4 个离线工具（decode / rpa / fw / usb）
```

详细文档：

- [docs/PRD.md](docs/PRD.md) —— 产品需求与设计取舍
- [docs/architecture/](docs/architecture/) —— 逐层设计文档
- [docs/superpowers/STATUS.md](docs/superpowers/STATUS.md) —— 实现进度 / 各 plan 状态
- [docs/superpowers/specs/](docs/superpowers/specs/) —— 已批准的功能 spec（trace 系统等）
- [docs/superpowers/plans/](docs/superpowers/plans/) —— 实施 plan（任务级粒度）

---

## 项目状态

全部 18 个实施 Plan 均已完成：

- **Core 层** —— address、UUID、errors、状态机、trace、SIG 数据库
- **Transport 层** —— UART、USB、TCP、UDP、virtual、btsnoop 回放、HCI user-channel
- **HCI 层** —— packet codec、流控、controller、virtual controller、vendor（Intel/Realtek）
- **L2CAP 层** —— SAR、固定/CoC 通道、ERTM、信令、manager
- **BLE** —— ATT、GATT（server + client）、SMP、SecurityConfig、GAP（广播/扫描/连接/隐私/白名单）
- **Classic** —— SDP、RFCOMM、SPP、GAP（inquiry/SSP/可发现性）
- **Profiles** —— 9 个内置 BLE Profile + 装饰器驱动的自定义 Profile 框架
- **Stack 装配** —— `Stack` 工厂，支持 virtual 模式与 async 上下文管理器
- **测试基础设施** —— 1000+ 测试，覆盖率 86%+，btsnoop 回放，CI 矩阵（Python 3.10/3.11/3.12）
- **CLI 工具** —— `app` 与 `tools` 双命名空间共 12 个子命令
- **Pytest Transport 选择** —— `--transport`、`--list-transports`、自动 USB 探测 + 回落
- **结构化 Trace** —— ConsoleSink（彩色、防刷屏）、SIG 查表格式化器、协议层 logger 注入

---

## 许可证

MIT —— 详见 [LICENSE](LICENSE)（如存在）或 `pyproject.toml`。

---

## 贡献

开发流程基于 plan 驱动的实施模式。贡献者指南见 [CLAUDE.md](CLAUDE.md)，任务看板见 [docs/superpowers/STATUS.md](docs/superpowers/STATUS.md)。
