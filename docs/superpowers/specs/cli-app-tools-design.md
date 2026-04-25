# CLI: app + tools — 设计文档

**日期：** 2026-04-25
**状态：** 待审
**对应 PRD 章节：** §5.8 CLI（命令行工具）
**实施方式：** 本设计批准后由 `superpowers:writing-plans` 生成实施 plan

---

## 1. 目标

为 PyBlueHost 提供开箱即用的命令行工具，让用户**无需编写 Python 代码**即可：
1. 验证协议栈在自己的环境/适配器上能用
2. 调试外部蓝牙设备（扫描、查 GATT/SDP、广播测试）
3. 做离线工具计算（HCI 包解码、RPA / IRK 计算）

## 2. 设计原则

- **两个命名空间，单一判定标准：** `app` = 需要打开 HCI transport；`tools` = 不打开 transport
- **每条命令做一件事：** 不堆砌 flag，不做 DSL，不做配置文件
- **Loopback 双模：** 客户端类命令在 `--transport loopback` 下自动起内置对端，无硬件即可端到端跑通
- **YAGNI：** 不做 JSON 输出、shell completion、进度条、重试参数等"将来可能需要"的特性

## 3. 命令清单

### 3.1 `app/`（8 条，需 `--transport`）

| 命令 | 类型 | 行为 |
|------|------|------|
| `ble-scan` | 长跑 | 扫描周边 BLE 广播，去重打印（`addr / RSSI / local_name`），Ctrl+C 退出 |
| `ble-adv` | 长跑 | 启动广播（`--name <s>`、`--service-uuid <uuid>`、`--type {connectable,scannable,non-connectable}`），Ctrl+C 退出 |
| `classic-inquiry` | 长跑 | 循环 inquiry，去重打印（`addr / CoD / name`），Ctrl+C 退出 |
| `gatt-browser` | 一次性 | 连接 `--target`（loopback 下连本地内置 BatteryServer）→ GATT 全发现 → 缩进打印 services/chars/descrs → 退出 |
| `sdp-browser` | 一次性 | 连接 `--target`（loopback 下连本地 SDPServer）→ ServiceSearchAttribute → 打印每条 record → 退出 |
| `gatt-server` | 长跑 | 注册 `BatteryServer` + `HeartRateServer`，等连接，Ctrl+C 退出 |
| `hr-monitor` | 长跑 | HRS server，每 1s 推送随机 60-100 bpm notification，Ctrl+C 退出 |
| `spp-echo` | 长跑 | RFCOMM ch1 echo server，回显客户端字节，Ctrl+C 退出 |

### 3.2 `tools/`（4 条子族）

| 命令 | 行为 |
|------|------|
| `decode <hex>` | 自动判别 H4 type，调 `decode_hci_packet`，多行打印解码结构 |
| `rpa gen-irk` | 生成 16-byte 随机 IRK，输出 hex |
| `rpa gen-rpa --irk <hex>` | 用 `SMPCrypto.ah()` 从 IRK 生成 RPA，输出 `XX:XX:XX:XX:XX:XX/random` |
| `rpa verify --irk <hex> --addr <BD_ADDR>` | 拆 RPA 的 hash + prand，重算 ah，比对，输出 `match` / `no match` |
| `fw list / download / info / clean` | 固件管理（从 `cli/fw.py` 迁入） |
| `usb scan / probe` | USB 设备诊断（从 `cli/usb.py` 迁入） |

## 4. 统一参数语法

### `--transport`（所有 app 命令必填）

```
loopback                       → LoopbackTransport + 内部 VirtualController
usb                            → USBTransport.auto_detect()
usb:vendor=intel               → USBTransport.auto_detect(vendor="intel")
uart:/dev/ttyUSB0              → UARTTransport(port=..., baudrate=115200)
uart:/dev/ttyUSB0@921600       → UARTTransport(port=..., baudrate=921600)
```

非法格式 → argparse 报错，exit 2。

### `--target`（client 类命令需要；loopback 下自动忽略）

```
AA:BB:CC:DD:EE:FF              → (BDAddress, AddressType.PUBLIC)
AA:BB:CC:DD:EE:FF/random       → (BDAddress, AddressType.RANDOM)
AA:BB:CC:DD:EE:FF/public       → (BDAddress, AddressType.PUBLIC)
```

Client 类命令在非 loopback transport 下未提供 `--target` → `parser.error()`，exit 2。

## 5. 文件结构

```
pybluehost/cli/
├── __init__.py            # 主入口：注册 app + tools 两个 namespace
├── _transport.py          # parse_transport_arg(s) -> Transport
├── _target.py             # parse_target_arg(s) -> (BDAddress, AddressType)
├── _lifecycle.py          # run_app_command()：长跑 SIGINT/SIGTERM 处理
├── _loopback_peer.py      # @asynccontextmanager loopback_peer_with(server_factory)
│
├── app/
│   ├── __init__.py        # register_app_commands(subparsers)
│   ├── ble_scan.py
│   ├── ble_adv.py
│   ├── classic_inquiry.py
│   ├── gatt_browser.py
│   ├── sdp_browser.py
│   ├── gatt_server.py
│   ├── hr_monitor.py
│   └── spp_echo.py
│
└── tools/
    ├── __init__.py        # register_tools_commands(subparsers)
    ├── fw.py              # 从 cli/fw.py 迁入
    ├── usb.py             # 从 cli/usb.py 迁入
    ├── decode.py
    └── rpa.py             # 含 gen-irk / gen-rpa / verify 三子命令
```

**迁移影响：** `pybluehost fw list` → `pybluehost tools fw list`。v0.0.1 + 无外部用户，破坏性变更可接受，不做向后兼容 shim。

## 6. 共享辅助模块

### 6.1 `_transport.py`

```python
def parse_transport_arg(s: str) -> Transport:
    """解析 --transport 字符串为 Transport 实例。"""
    if s == "loopback":
        return LoopbackTransport.with_virtual_controller(...)
    if s == "usb" or s.startswith("usb:"):
        vendor = _extract_kv(s, "vendor")
        return USBTransport.auto_detect(vendor=vendor)
    if s.startswith("uart:"):
        port, baud = _split_uart(s[5:])
        return UARTTransport(port=port, baudrate=baud)
    raise ValueError(f"Unknown transport: {s!r}")
```

### 6.2 `_target.py`

```python
def parse_target_arg(s: str) -> tuple[BDAddress, AddressType]:
    """解析 --target 字符串。"""
    parts = s.split("/", 1)
    addr = BDAddress.from_string(parts[0])
    type_str = parts[1] if len(parts) > 1 else "public"
    return (addr, AddressType[type_str.upper()])
```

### 6.3 `_lifecycle.py`

```python
async def run_app_command(
    transport_arg: str,
    main_coro: Callable[[Stack, asyncio.Event], Awaitable[None]],
) -> int:
    """长跑命令统一骨架。

    流程：解析 transport → 构建 Stack → 注册 SIGINT/SIGTERM →
          跑 main_coro 直到完成或收信号 → 优雅 close → 返回 exit code

    Exit code:
        0   → 正常完成
        130 → Ctrl+C
        1   → 异常
    """
```

### 6.4 `_loopback_peer.py`

```python
@asynccontextmanager
async def loopback_peer_with(server_factory: Callable) -> AsyncIterator[Stack]:
    """同进程起一个 VirtualController-backed Stack 作为对端。

    用于 client 类命令在 loopback 模式下的端到端闭环。
    yield 出对端 Stack，调用方可以读 stack.local_address 作为 --target。
    """
```

## 7. 错误处理

| 场景 | 处理 | Exit code |
|------|------|-----------|
| `--transport` 解析失败 | argparse 报错 | 2 |
| Transport open 失败（USB 找不到、串口不存在、权限不足） | 打印 `Error: <message>` 到 stderr | 1 |
| Client 命令缺 `--target` 且非 loopback | `parser.error()` | 2 |
| HCI 命令超时（`CommandTimeoutError`） | 打印 `Error: HCI command timeout` | 1 |
| `Ctrl+C` | `_lifecycle` 捕获信号，优雅 close | 130 |
| `--target` 格式错误 | argparse 报错 | 2 |
| 工具命令的 hex 字符串非法（`decode`、`rpa`） | argparse 报错 | 2 |

## 8. 输出格式

**默认 human-readable，不提供 `--json`。** 若将来有脚本化需求，再加 `--json`，符合 YAGNI。

### `gatt-browser` 输出范例

```
Connected to AA:BB:CC:DD:EE:FF (random)
─ Service 0x1800 (Generic Access)
   ├─ Char 0x2A00 (Device Name) handle=0x0003 props=READ value="MyDevice"
   └─ Char 0x2A01 (Appearance) handle=0x0005 props=READ value=0x0341
─ Service 0x180F (Battery)
   └─ Char 0x2A19 (Battery Level) handle=0x0008 props=READ,NOTIFY value=0x55
       └─ Descr 0x2902 (CCCD) handle=0x0009 value=0x0000
```

### `tools decode 01030c00` 输出范例

```
HCI_Reset
  packet_type:  HCI_COMMAND_PACKET (0x01)
  opcode:       0x0C03 (OGF=Controller_Baseband, OCF=Reset)
  parameters:   (empty)
```

### `tools rpa gen-rpa --irk <hex>` 输出范例

```
IRK:    aabbccddeeff00112233445566778899
RPA:    7E:1A:B3:C2:D4:E5/random
prand:  7E1AB3
hash:   C2D4E5
```

## 9. 测试策略

### 9.1 单元测试（无 transport）

| 文件 | 范围 |
|------|------|
| `tests/unit/cli/test_transport.py` | 5 种合法 transport 字符串 + 3 种错误格式 |
| `tests/unit/cli/test_target.py` | public/random 地址 + 错误格式 |
| `tests/unit/cli/test_tools_decode.py` | 10 个常见 HCI 包的 hex → 解码结构断言 |
| `tests/unit/cli/test_tools_rpa.py` | BT Spec 测试向量验证 IRK→RPA→verify 全流程 |
| `tests/unit/cli/test_tools_fw.py` | 保留现有 fw mock 测试（路径变更） |
| `tests/unit/cli/test_tools_usb.py` | 保留现有 usb mock 测试（路径变更） |

### 9.2 集成测试（loopback transport）

每条 app 命令一个测试文件，全部用 `--transport loopback`：

- **一次性命令**（`gatt-browser` / `sdp-browser`）：调 entry function，捕获 stdout，断言含关键字（如 `Service 0x1800`）
- **长跑命令**（`ble-scan` / `ble-adv` / `gatt-server` / `hr-monitor` / `spp-echo` / `classic-inquiry`）：
  - 用 `asyncio.create_task` 跑命令
  - 等 100ms（让命令初始化）
  - 触发 `stop_event.set()` 或注入模拟 SIGINT
  - 断言任务干净退出（exit code 0 或 130）+ 输出含预期关键字

### 9.3 不测的事

- 真实 USB / UART transport 的命令路径（属于 `tests/hardware/`，已有 marker）
- 跨进程信号处理（asyncio loop 内部模拟即可）
- Stdin / TTY 交互（无 REPL 命令）

## 10. 与现有代码的兼容性

| 现有调用 | 迁移后 | 备注 |
|---------|--------|------|
| `pybluehost fw list` | `pybluehost tools fw list` | 破坏性变更，无 shim |
| `pybluehost usb scan` | `pybluehost tools usb scan` | 同上 |
| `register_fw_commands(subparsers)` | `register_tools_commands(subparsers)` 内部调用 | API 变更，但 `cli/__init__.py` 是唯一调用方 |
| `tests/unit/cli/test_fw.py` | 路径不变，import 改为 `pybluehost.cli.tools.fw` | 测试代码同步更新 |

## 11. 实施步骤概要（详细 plan 由 `writing-plans` 生成）

1. **辅助模块**：`_transport.py` / `_target.py` / `_lifecycle.py` / `_loopback_peer.py` + 各自单测
2. **tools/ 子包**：迁移 `fw.py` / `usb.py`，新增 `decode.py` / `rpa.py`
3. **app/ 子包**：8 条命令逐个实现
4. **`cli/__init__.py`**：移除 fw/usb 顶层注册，改为注册 app + tools 两个 namespace
5. **README**：在「命令行工具」章节列出新命令清单（替换原 fw/usb 三行）
6. **覆盖率验证**：保持 ≥85%

## 12. 非目标（v1.0 明确不做）

- ❌ `--json` 输出格式
- ❌ 配置文件 / 环境变量配置
- ❌ shell completion 脚本
- ❌ 进度条
- ❌ HCI 命令超时 / 重试参数（用默认值）
- ❌ 交互 REPL 模式（被 `gatt-browser` 一次性方案替代）
- ❌ 顶层 `pybluehost fw` / `pybluehost usb` 兼容 shim
- ❌ Sub-namespace 的 `--help` 中文翻译（保持英文）

## 13. 成功标准

| 指标 | 验收方式 |
|------|---------|
| 12 条命令全部可用 | `pybluehost --help` 显示完整树；每条 `--help` 文档完整 |
| Loopback 模式无硬件可跑 | `pybluehost app gatt-browser --transport loopback` 输出 GATT 树 |
| 长跑命令优雅退出 | Ctrl+C 后无未关闭的 transport / 任务，exit 130 |
| `tools decode` 覆盖常见 10 个 HCI 包 | 单元测试 PASS |
| `tools rpa` 通过 BT Spec 测试向量 | 单元测试 PASS |
| 全部新增测试 + 覆盖率 ≥85% | `uv run pytest tests/ -m "not hardware" --cov-fail-under=85` |
