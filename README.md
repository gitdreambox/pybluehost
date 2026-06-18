# PyBlueHost

面向测试、仿真和协议教学的专业级 Python 蓝牙 Host 协议栈。

PyBlueHost 用纯 Python 实现完整的 Bluetooth Host 协议栈：HCI、L2CAP、ATT/GATT、SMP、SDP、RFCOMM，以及 BLE 与 Classic 双模 GAP —— 全部基于 `asyncio` 构建。  
适用于快速原型开发、协议学习、无硬件集成测试，以及编写自定义 BLE/Classic profile 服务端与客户端。

- **纯 Python 3.10+，asyncio 原生**
- **支持虚拟硬件** —— 内置 `VirtualController`，可在单元测试中跑完整协议栈
- **多种 Transport** —— UART、USB（PyUSB）、TCP、UDP、btsnoop replay、Linux HCI user-channel
- **YAML-driven service definitions** —— 声明式定义自定义服务，无需手写 handler 样板
- **结构化 Trace** —— HCI 包按命令/事件名展开（带 SIG 查表），可彩色实时输出，也可录制为 btsnoop / JSON Lines
- **MITM 透传**（⚠ 授权测试）—— 双 radio 在目标与手机间透传 BLE/BR ACL 并抓 btsnoop，见 [`docs/MITM.md`](docs/MITM.md)

---

## 我属于哪一类用户？

PyBlueHost 服务三类不同需求的用户。先确定自己属于哪类，直接跳到对应章节：

| 你的目标 | 你属于 | 跳到 |
|---------|-------|------|
| 验证适配器、抓 trace、跑 demo —— **不写代码** | 协议测试/分析用户 | [一、CLI 用户篇](#一cli-用户篇协议测试与分析) |
| 写自己的 BLE/Classic 应用：自定义 GATT service、SPP 私有协议、自动化脚本 —— **`pip install pybluehost` 当依赖，不改 PyBlueHost 源码** | 应用开发用户 | [二、应用开发者篇](#二应用开发者篇基于-pybluehost-写蓝牙应用) |
| 修协议 bug、加 LE Audio / A2DP、加新 vendor / 新 transport —— **git clone 后做二次开发** | 协议栈贡献者 | [三、协议栈贡献者篇](#三协议栈贡献者篇修改-pybluehost-源码) |

## 已测试硬件

| 芯片型号 | VID | PID | Transport | 协议版本 | 类型 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| RTL8852BE    | `0x0BDA` | `0x4853` | USB  | 5.2 | BR/EDR + BLE | `rtl8852bu_fw.bin` |
| CSR8510      | `0x0A12` | `0x0001` | USB  | 4.0 | BR/EDR + BLE | 只支持BT 4.0 |
| Intel BE200  | `0x8087` | `0x0036` | USB  | 5.4 | BR/EDR + BLE | `ibt-0291-0291.sfi` |
| Intel AX201  | `0x8087` | `0x0026` | USB  | 5.2 | BR/EDR + BLE | `ibt-19-0-4.sfi` |
| BARROT BT6.0 | `0x33FA` | `0x0012` | USB  | 6.0 | BR/EDR + BLE | UGREEN BT6.0 Adapter；当前仅验证 USB/HCI 基础访问，LE RF e2e 不通过 |
| nRF52840     | `0x1915` | `0x521F` | UART | 5.4 | BLE          | PTS FW |

> 2026-06-18 Windows + WinUSB 实测：Barrot BR8654A02 (`usb:33FA:0012#1`) 可以枚举、打开、执行 `HCI_Reset`、读取能力信息，且 `LE_Set_Advertising_*` / `LE_Set_Scan_*` 命令返回 Success。但交叉验证中，Intel AX201 和 CSR8510 都无法扫描到 Barrot 发出的 `PBH-E2E` legacy advertising；Barrot 作为 central 也无法扫描到近距离 Intel AX201 发出的同名测试广告。因此当前不要把 Barrot 用作 LE e2e 的 central 或 peripheral 基准设备；它的问题应作为硬件/厂商初始化兼容问题暴露，而不是通过 role swap 规避。

CSR、其他 Intel 系列芯片在代码中已支持但未在本仓库做完整回归。欢迎提 PR 补 hardware 矩阵。

---

# 一、CLI 用户篇（协议测试与分析）

> 适合：拿到适配器想验证蓝牙功能、跑 demo、抓 trace、用 PyBlueHost 当临时 host 验证场景的人。
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
# 列出所有的USB transport(仅USB transport, 不包括UART/TCP/UDP...)
pybluehost --list-transport

# USB 设备探测和驱动诊断（不打开设备，只读 USB 描述符）
pybluehost tools usb probe
pybluehost tools usb probe --verbose

# 完整诊断（尝试打开设备/检查驱动/检查是否需要load fw/测试hci reset，给出"为什么打不开"的具体原因）
pybluehost tools usb diagnose
```

## 1.3 BLE 验证（CLI）

`--transport` 接受 `virtual`、`usb:VID:PID`、`uart:COM5[@115200]`、`uart:/dev/ttyUSB0[@921600]`。USB 请直接使用 `pybluehost tools usb probe` 输出的 Transport Names，例如 `usb:33FA:0012`；同一电脑上有两个相同 VID/PID 设备时使用 `#1`、`#2` 区分,例如 `usb:8087:0036#1`。
`--btsnoop` 使用btsnoop格式记录hci log。  
`--hci-log` 终端中实时显示hci raw log。 

```bash
# 扫描周围 BLE 设备（长跑，Ctrl+C 结束）
pybluehost app ble-scan --transport usb
pybluehost app ble-scan --transport usb:8087:0036#1
pybluehost app ble-scan --transport uart:COM5@115200
# 添加 HCI btsnoop log
pybluehost app ble-scan --transport usb --btsnoop btsnoop.cfa
# 添加 HCI raw log
pybluehost app ble-scan --transport usb --hci-log

# 自己也广播让别的设备看到
pybluehost app ble-adv --transport usb --name MyDevice

# 起一个 GATT server，让手机能连过来
pybluehost app gatt-server --transport usb

# Heart Rate Sensor demo（带 notification 推送）
pybluehost app hr-monitor --transport usb

# 一次性：浏览远端 GATT 数据库（services / characteristics / descriptors / properties）
# 地址格式：`A0:90:B5:10:40:82` 或 `A090B5104082` 都接受。
pybluehost app gatt-browser --transport usb --addr A0:90:B5:10:40:82
```


## 1.4 Classic 蓝牙验证（CLI）

```bash
# 经典蓝牙设备发现
pybluehost app classic-inquiry --transport usb

# SPP 服务（手机蓝牙串口终端连过来发字符串，会原样 echo 回去）
pybluehost app spp-echo --transport usb

# 一次性：浏览远端 SDP records
pybluehost app sdp-browser --transport usb --addr 1A:8D:8D:1B:F5:6B
pybluehost app sdp-browser --transport usb --addr 1A8D8D1BF56B --uuid 0x1101
```

## 1.5 本地 UART/USB HCI transport 转接成网络 TCP/UDP H4 前端
pybluehost app bridge --transport usb --btsnoop test.cfa
pybluehost app bridge --transport uart:/dev/ttyUSB0@921600 --protocol udp --port 57123

UART 使用统一 transport 规则 `uart:<port>[@baud]`；Windows 串口可写作 `uart:COM5@921600`。

## 1.6 中间人（MITM）透传（⚠ 授权测试专用）

在**目标设备**与**手机**之间插入中间人，双向透传 BLE 与 BR/EDR ACL，并把两侧明文抓成 btsnoop。
需要**两个 USB 适配器**（上游连目标、下游对手机伪装）。仅用于授权安全研究/教学。

```bash
# 默认:自身地址 + 克隆应用层身份, Just Works, both(LE+BR)
pybluehost app mitm --upstream usb:8087:0036 --downstream usb:0a12:0001 --target AA:BB:CC:DD:EE:FF

# 只做 BLE + Numeric Comparison(两侧终端确认)
pybluehost app mitm --upstream usb --downstream usb:0a12:0001 --target-name "Watch" --transport-mode le --pairing numeric

# 地址锁定的重连场景:克隆目标 BD_ADDR(下游需 Broadcom dongle)
pybluehost app mitm --upstream usb --downstream usb:0a12:0001 --target AA:BB:CC:DD:EE:FF --clone-address
```

默认输出 `mitm-<时间戳>.btsnoop`，用 Wireshark/Ellisys 打开。完整说明（硬件选型、删旧 bond、
Numeric 操作、限制、真机验证事项）见 **[docs/MITM.md](docs/MITM.md)**。

## 1.7 离线工具（不需要硬件）

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

## 1.8 出问题怎么调试（trace）

最常用的三个命令：

```bash
# 看 HCI 包的实时人读输出（彩色单行）
pybluehost --trace=hci app hr-monitor --transport=usb

# 出现握手失败 / 配对失败时 → 全层 debug，看协议层每一步
pybluehost --trace=*=debug app hr-monitor --transport=usb 2> trace.log

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

需要更细的控制（按层独立级别、ACL payload 不截断、把默认抑制的事件加回来）见 [§3.4](#34-trace-系统深度定制) 「Trace 系统深度定制」。

## 1.9 安装 / 硬件常见问题

**Windows：必须装 WinUSB 驱动**

USB transport 在 Windows 上需要把目标适配器替换为 WinUSB 驱动。`libusb-package` 解决了 DLL 查找问题，但驱动绑定无法绕过 —— 用 [Zadig](https://zadig.akeo.ie/) 替换。


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


**macOS：Apple 的蓝牙栈占着内置控制器**

macOS 上系统蓝牙 daemon 排他持有内置控制器；外接 USB 适配器才能让 PyBlueHost 用上。

**SIG 名字显示成 hex 而不是名字**

git clone 安装时漏了 submodule。跑：

```bash
git submodule update --init
```

`pip install pybluehost` 包里已经把 SIG 数据打进去了，不会有这个问题。

---

# 二、应用开发者篇（基于 PyBlueHost 写蓝牙应用）

> 适合：在 PyBlueHost 上写自己的 BLE/Classic 应用 —— 自定义 GATT service、SPP 私有协议、自动化测试脚本。
> `pip install pybluehost` 当依赖，**不改 PyBlueHost 源码**；大部分时候你只在最上层写代码。

## 2.1 安装 + 第一行代码

```bash
pip install pybluehost
```

```python
# hello_pybluehost.py
import asyncio
from pybluehost import Stack

async def main():
    async with await Stack.virtual() as stack:
        print(f"Local address: {stack.local_address}")
        # stack.gap, stack.gatt_server, stack.l2cap, stack.hci, stack.trace 全部就绪

asyncio.run(main())
```

```bash
python hello_pybluehost.py
# Local address: AA:BB:CC:XX:YY:ZZ
```

`Stack.virtual()` 基于 `VirtualController` 构建一个完整协议栈 —— 不需要任何蓝牙硬件，所有 HCI 命令都在进程内仿真器中流转，方便起步和写自动化测试。

## 2.2 启动协议栈（virtual / 真硬件）

```python
from pybluehost import Stack

# 虚拟环境（无硬件）—— 写测试 / 起步首选
async with await Stack.virtual() as stack:
    ...

# USB 自动探测（按 vendor 过滤可避免多块适配器选错）
async with await Stack.from_usb(vendor="intel") as stack:
    ...

# UART
async with await Stack.from_uart(port="/dev/ttyUSB0", baudrate=921600) as stack:
    ...
```

`StackConfig` 控制设备级默认值：

```python
from pybluehost import StackConfig
from pybluehost.core.types import IOCapability
from pybluehost.ble.security import SecurityConfig

config = StackConfig(
    device_name="MyDevice",
    appearance=0x0341, # Heart Rate Sensor
    le_io_capability=IOCapability.DISPLAY_YES_NO,
    security=SecurityConfig(
        bondable=True, mitm_required=True, secure_connections=True,
    ),
    command_timeout=5.0,
)
async with await Stack.virtual(config=config) as stack:
    ...
```

**你写代码主要用到的 stack 入口**：

| 属性 | 干什么的 |
|------|---------|
| `stack.gap` | BLE + Classic 统一 GAP（广播/扫描/inquiry/连接/可发现性/SSP） |
| `stack.gatt_server` | 注册自定义 GATT service / 内置 profile |
| `stack.gatt_client` | 服务发现 / 读写 / 订阅 notification |
| `stack.sdp` | Classic SDP records 注册 + 查询 |
| `stack.rfcomm` | RFCOMM channel listen / connect（SPP 基础） |
| `stack.l2cap` | L2CAP CoC（应用一般不直接用） |
| `stack.trace` | 挂自定义 sink 录 trace（见 §2.6） |
| `stack.local_address` | 本机 BD_ADDR |

## 2.3 写一个 BLE GATT Server

**自定义 service**（用装饰器驱动的 profile 框架，省略 imports）：

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

**用现成的内置 profile**：

```python
from pybluehost.profiles.ble import BatteryServer, HeartRateServer

battery = BatteryServer(initial_level=85)
hrs = HeartRateServer(sensor_location=0x02)  # 手腕
await battery.register(stack.gatt_server)
await hrs.register(stack.gatt_server)

await hrs.update_measurement(bpm=72)   # 推送一次 notification
```

可用的内置 Profile：`BatteryServer`/`Client`、`HeartRateServer`/`Client`、`DeviceInformationServer`/`Client`、`BloodPressureServer`、`HIDServer`、`RSCServer`、`CSCServer`、`GAPServiceServer`、`GATTServiceServer`。

参考真实代码：`pybluehost/profiles/ble/battery.py`、`heart_rate.py`、`hids.py`（每个文件 < 50 行，照抄改造即可）。

## 2.4 写一个 BLE 客户端

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

## 2.5 写一个 Classic 应用（SDP/RFCOMM/SPP）

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

## 2.6 在自己的代码里挂 trace

PyBlueHost 内置结构化 trace 系统，所有 HCI/L2CAP 包都流经 `stack.trace`。挂接 sink 即可录制成文件：

```python
from pybluehost import Stack, StackConfig
from pybluehost.core.trace import BtsnoopSink, JsonSink

config = StackConfig(
    trace_sinks=[
        BtsnoopSink("session.btsnoop"),   # Wireshark 兼容
        JsonSink("session.jsonl"),        # 每行一个 JSON 对象
    ],
)
async with await Stack.virtual(config=config) as stack:
    # ... 业务代码 ...
    pass  # close() 会自动 flush 所有 sink
```

**回放已抓取的 btsnoop**：

```python
from pybluehost.transport.btsnoop import BtsnoopTransport

transport = BtsnoopTransport(path="capture.btsnoop", realtime=False)
# 与普通 transport 一样使用 —— 包从文件中按序注入
```

需要更深的定制（自定义 sink、按层级别精细控制、防刷屏配置）见 [§3.4](#34-trace-系统深度定制)。

## 2.7 给自己的应用写测试

应用开发者最常用 `Stack.virtual()` 写无硬件单元测试。基本模板：

```python
# tests/test_my_app.py
import pytest
from pybluehost import Stack
from my_app import MyTemperatureService

@pytest.mark.asyncio
async def test_temperature_service_reads_correctly():
    async with await Stack.virtual() as stack:
        svc = MyTemperatureService()
        await svc.register(stack.gatt_server)

        # 通过 stack.gatt_server.db 直接查 attribute（白盒）
        # 或起 peer_stack 真连过来读（端到端）
        ...
```

```bash
pip install pytest pytest-asyncio
pytest tests/
```

**配置**（你自己 `pyproject.toml`）：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

## 2.8 应用开发常见入口速查

| 我想做的事 | 看这里 |
|-----------|------|
| 加一个新 BLE Service / Profile | `pybluehost/profiles/ble/`（参考 `battery.py` / `heart_rate.py` 这些短文件） |
| 写一个客户端浏览远端 GATT | `pybluehost/cli/app/gatt_browser.py`（约 100 行，完整可运行） |
| 起 SPP echo server | `pybluehost/cli/app/spp_echo.py` |
| 起 Heart Rate notification 服务 | `pybluehost/cli/app/hr_monitor.py` |
| 自定义事件 callback / 录 trace | [§2.6 在自己的代码里挂 trace](#26-在自己的代码里挂-trace) |
| 想改协议栈本身（HCI / L2CAP / GATT 内部） | 你不属于这一篇，去看 [三、协议栈贡献者篇](#三协议栈贡献者篇修改-pybluehost-源码) |

---

# 三、协议栈贡献者篇（修改 PyBlueHost 源码）

> 适合：修协议 bug、加 LE Audio / A2DP、加新 vendor / 新 transport、加 SMP 高级特性等需要改 PyBlueHost 源码的人。
> 全程在 git clone 出来的源码树里干活，跑测试用 `uv run pytest`。

## 3.1 开发环境安装

PyBlueHost 用 [`uv`](https://github.com/astral-sh/uv) 管理依赖。

```bash
# 1. 克隆仓库 + 拉 submodule
git clone https://github.com/gitdreambox/pybluehost.git
cd pybluehost
git submodule update --init   # SIG assigned-numbers 数据库

# 2. 安装开发依赖（含 pytest、pytest-asyncio、pytest-cov）
uv sync --extra dev

# 3. 验证开发环境
uv run pytest tests/ --transport=virtual
```

## 3.2 架构与代码导航

### 分层

```
┌─────────────────── Profiles (Battery, HRS, HID, ...) ───────────────────┐
│  ↑ 应用开发用户的代码大多在这一层                                         │
├──── GAP (BLE + Classic 统一入口) ──┬── GATT ────┬── SDP ─── RFCOMM ─────┤
│                                     │            │                       │
│           ATT ─ SMP                 │            │                       │
├─────────────────────────── L2CAP ───────────────────────────────────────┤
├─────────────────────── HCI（命令、事件、ACL、流控）──────────────────────┤
└─────────────── Transport (UART, USB, TCP, UDP, btsnoop, virtual) ───────┘
```

调用方向：应用代码调 `stack.gap` / `stack.gatt_server` / `stack.sdp` / `stack.rfcomm`，下层一直传到 transport；事件反向上来，HCI controller 解码后通过 callback / channel 上送到对应层。

### 目录树

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

### 二次开发常见入口

| 我想做的事 | 看哪儿 |
|-----------|------|
| 改 HCI 命令处理 / vendor 命令 | `pybluehost/hci/` |
| 加新 transport（BlueZ 内核 socket、TCP-over-WebSocket 等） | `pybluehost.transport.base.Transport` 接口（参考 `udp.py` 最短） |
| 加新 vendor 固件加载流程 | `pybluehost/transport/usb.py`（已有 Intel / Realtek / CSR 三家可参考） |
| L2CAP 改 ERTM / Streaming mode | `pybluehost/l2cap/` |
| ATT/GATT 协议变化（spec 更新） | `pybluehost/ble/att.py` / `gatt.py` |
| SMP 新加密算法 / Secure Connections 变体 | `pybluehost/ble/smp/` |
| Classic 加 A2DP / AVRCP / HFP profile | 新建 `pybluehost/classic/<profile>.py` + `pybluehost/profiles/classic/` |

### 详细文档

- [docs/PRD.md](docs/PRD.md) —— 产品需求与设计取舍
- [docs/architecture/](docs/architecture/) —— 逐层设计文档
- [docs/superpowers/STATUS.md](docs/superpowers/STATUS.md) —— 实现进度 / 各 plan 状态
- [docs/superpowers/specs/](docs/superpowers/specs/) —— 已批准的功能 spec
- [docs/superpowers/plans/](docs/superpowers/plans/) —— 实施 plan（任务级粒度）

## 3.3 跑测试套件（完整版）

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
uv run pytest tests/ --transport=usb:0A12:0001#1

# UART
uv run pytest tests/ --transport=uart:/dev/ttyUSB0@921600

# 双适配器测试（peer 自动找第二块；找不到则跳过）
uv run pytest tests/ --transport=usb:0A12:0001#1 --transport-peer=usb:0A12:0001#2

# pytest 内打开 trace（注意：pytest 选项叫 --pybluehost-trace 不叫 --trace）
uv run pytest tests/ --pybluehost-trace=hci --transport=virtual

# 通过环境变量
PYBLUEHOST_TEST_TRANSPORT=usb:0A12:0001#1 uv run pytest tests/

# 列出所有检测到的适配器
uv run pytest --list-transports
```

测试可以用 `@pytest.mark.real_hardware_only` 或 `@pytest.mark.virtual_only` 限制运行环境。Marker 分组：`unit` / `integration` / `e2e` / `btsnoop` / `slow` / `real_hardware_only` / `virtual_only`。

## 3.4 Trace 系统深度定制

PyBlueHost 内置结构化 trace 系统：HCI 包按命令/事件名展开（含字段、SIG company name 等查表），按层独立可控，彩色实时输出到 stderr。默认零开销 —— 不指定 `--trace` / 不挂 sink 时不做任何额外工作。

应用开发用户的基本用法见 [§2.6](#26-在自己的代码里挂-trace)；本节是协议栈贡献者级别的深定制。

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

### 写自定义 sink

实现 `pybluehost.core.trace.TraceSink` 协议（一个 `async def consume(event: TraceEvent)` 方法）：

```python
from pybluehost.core.trace import TraceSink, TraceEvent

class MyMetricsSink(TraceSink):
    async def consume(self, event: TraceEvent) -> None:
        # 把每个 HCI 包统计到 prometheus / push 到 Kafka 等等
        if event.layer == "hci":
            metrics.counter(f"hci.{event.kind}").inc()

config = StackConfig(trace_sinks=[MyMetricsSink()])
```

## 3.5 Plan 驱动开发流程

PyBlueHost 用 plan 驱动的实施模式：每个新功能先写 spec → 评审 → 写 plan → 一个 task 一个 task 跑 → 状态更新到 `STATUS.md`。

完整流程见 [CLAUDE.md](CLAUDE.md)。关键文件：

- [CLAUDE.md](CLAUDE.md) —— 协作流程、commit 规范、状态更新协议
- [docs/superpowers/STATUS.md](docs/superpowers/STATUS.md) —— 任务看板（哪些 plan 进行中、谁在做、卡在哪）
- [docs/superpowers/specs/](docs/superpowers/specs/) —— 已批准的设计 spec
- [docs/superpowers/plans/](docs/superpowers/plans/) —— 实施 plan（带 checkbox 的 task 列表）

提 PR 前最少跑：

```bash
uv run pytest tests/ --transport=virtual --cov=pybluehost --cov-fail-under=85
```

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
