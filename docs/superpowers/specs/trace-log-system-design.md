# Trace / Log 系统结构化输出设计文档

| 项 | 值 |
|----|----|
| 状态 | 已批准 |
| 日期 | 2026-05-02 |
| 责任方 | 调试基础设施 |
| 替代 | （无） |

## 1. 目标

让"出问题时根据 log 找到是哪一层、哪一步出问题"成为可能：

1. **HCI 层结构化显示** —— 不再是裸 hex 数组；每个命令/事件显示名字、参数、字段（含 SIG DB 查表后的人读名）。
2. **协议层（L2CAP/ATT/GATT/SMP/SDP/RFCOMM/Classic GAP+SSP）有 log 可查** —— 当前几乎没有；目标在每层关键决策点加约 5–8 个 logger 调用。
3. **彩色、防刷屏的实时控制台输出** —— 默认零开销；启用后单行紧凑、错误自动展开。
4. **统一控制（CLI flag + env var）** —— 与现有 `--transport` 选项体系一致。

非目标：vendor 命令深度解码、配置文件、网络转发、JSON 控制台、运行时热更新。

## 2. 背景

### 2.1 现状盘点

`pybluehost/core/trace.py` 已有完善的 `TraceSystem`（asyncio queue + 多 sink）+ `RingBufferSink` / `JsonSink` / `BtsnoopSink` / `CallbackSink`。但：

- **`HCIController._emit_trace` 总是写 `decoded=None`** —— 解码信息有但被丢弃。
- **`RingBufferSink.dump()` 输出 `[layer] DIR hex_str`** —— 完全不可读。
- **没有 `ConsoleSink`** —— 跑起来时无法实时看 trace 流。
- **`pybluehost/hci/packets.py` 的 `decode_hci_packet()` 已能解出强类型 packet** —— 但没有 `format_hci_packet()` 做人读字符串。
- **`pybluehost/core/sig_db.py:company_name(id)` 已就绪**（来自 SIG 官方 yaml） —— 但 trace 链路没用它。
- **协议层（`l2cap/`、`ble/`、`classic/`）几乎零 logger 使用** —— 当 SMP/GATT/SDP 出问题时除堆栈 trace 外无线索。

### 2.2 问题域

调试 Bluetooth 协议栈通常需要回答：
- 这条 HCI 命令/事件是什么？参数对吗？
- 状态机现在在哪一步？为什么停住了？
- 上层（GATT 客户端等）发了什么请求？对端怎么响应？
- 失败时具体的 reason / error code 是什么？

裸 hex + 缺失日志让以上问题都需要查规范 + 翻代码才能回答。

## 3. 范围

**范围内：**
- HCI 层结构化格式化器（`pybluehost/hci/format.py` + 字段格式化器约 20 个）
- 新 `ConsoleSink`（`pybluehost/core/trace_console.py`）含彩色、anti-flood、TTY 检测
- Trace 控制入口（`pybluehost/core/trace_control.py`）含 spec 解析与 install
- CLI / pytest 共用的 `--trace` 选项
- 协议层 logger 注入约 40 个决策点（L2CAP / ATT / GATT / SMP / HCI Conn / SDP / RFCOMM / Classic GAP+SSP / SSP）
- 测试：HCI formatter golden / ConsoleSink anti-flood / 控制 spec 解析 / 协议层 logger（caplog）/ 集成 subprocess

**范围外（YAGNI）：**
- Vendor 命令深度解码
- 配置文件（YAML / TOML）驱动 trace 偏好
- L2CAP 以上层接 TraceSystem（统一一套机制）
- 运行时信号热更新
- 网络转发（syslog / Loki / 远程）
- HTML / Web UI
- 控制台输出 JSON（JSON 仍走 `JsonSink` 文件）

## 4. 架构

### 4.1 数据流

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Protocol layers (L2CAP / ATT / GATT / SMP / SDP / RFCOMM / Classic)    │
│  ├─ logger.info / debug / warn   ← Phase 3 注入约 40 个决策点            │
│  └─ no trace.emit (上层走 logging)                                       │
└─────────────────────────────────────────────────────────────────────────┘
                              │ stdlib logging (level/filter)
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  HCIController._emit_trace                                              │
│    raw_bytes  →  decode_hci_packet()  →  TraceEvent(decoded=packet)     │
│    (旧: decoded=None;新: 总是带上解码好的 packet 对象)                  │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    TraceSystem.emit (asyncio queue)
                              │
              ┌───────────────┼─────────────┬──────────────┐
              ▼               ▼             ▼              ▼
       RingBufferSink     JsonSink      BtsnoopSink   ConsoleSink (新)
       (内存最近 N 条)   (jsonl 文件)  (.cfa)        (彩色 stderr)
                                                        │
                                                        ▼
                                       format_hci_packet(packet) (新)
                                          │
                                          ├─ SIG DB 查 company_id 等
                                          ├─ 字段格式化器(PHY/Address/UUID/...)
                                          ├─ 紧凑模式 → 单行
                                          └─ status≠0 / 异常 → 多行展开
```

**两条独立通道：**

1. **HCI / transport 层** → `TraceSystem` → 多 sink（含新 `ConsoleSink` 渲染彩色 HCI）
2. **协议层（L2CAP 及以上）** → 标准 `logging` → 走现有 `log_config.yaml`

设计取舍：HCI 是字节流，需要解码 + 结构化，TraceSystem 已为此设计（含 btsnoop / pcapng 需求）；L2CAP 以上是状态机+对象，logger 调用足够，无须把每个 PDU 序列化进 sink 系统，统一会过度设计。

### 4.2 组件总览

```
pybluehost/
├── hci/
│   ├── format.py             ← format_hci_packet() 主入口
│   └── format_fields.py      ← 字段格式化器实现(BD_ADDR/UUID/PHY/...)
├── core/
│   ├── trace.py              ← (已有) TraceSystem, RingBuffer, Json, Btsnoop
│   ├── trace_console.py      ← ConsoleSink, anti-flood, TTY/color detection
│   └── trace_control.py      ← parse_trace_spec(), trace_install()
└── cli/
    └── __init__.py           ← 顶层 --trace 选项,调 trace_install()

tests/
├── conftest.py               ← pytest --trace 选项
└── unit/
    ├── hci/test_format.py
    ├── core/test_trace_console.py
    └── core/test_trace_control.py
```

## 5. HCI 格式化器

### 5.1 公共 API

```python
def format_hci_packet(
    packet: HCIPacket,
    *,
    direction: Direction,
    color: bool = False,
    expand: bool = False,   # True = multi-line; False = single line
) -> str:
    """Render an HCIPacket as a human-readable string for console / log output."""
```

### 5.2 字段格式化器（约 20 个）

实现于 `pybluehost/hci/format_fields.py`，每个返回字符串。覆盖：

| 类别 | 输出示例 |
|------|---------|
| BD_ADDR + type | `Public 6E:1A:9C:81:5C:24` / `Random_Static C2:34:...` |
| UUID16/32/128 | `0x180D (Heart_Rate)` / `0x1101 (SerialPort)` / `f0d...` |
| company_id | `0x000F (Broadcom)` 通过 SIG DB |
| Status / Error code | `Success` / `Connection_Timeout(0x08)` |
| LE PHY | `1M` / `2M` / `Coded_S8` |
| Adv / Scan interval | `0x0040 (40.0 ms)` |
| RSSI | `-65 dBm` |
| Role | `Central` / `Peripheral` |
| AD type byte | `Flags=0x06 (LE_GENERAL_DISCOVERABLE \| BR_EDR_NOT_SUPPORTED)` |
| Class of Device | `0x080414 (Phone, Smartphone)` |

**Vendor 命令**：保留 `Vendor (Intel)` + `opcode=0xfc04 plen=8 raw=01 02 ...`，不深度解码。

### 5.3 紧凑模式（默认）

```
HH:MM:SS.mmm  ↓ HCI Cmd  LE_Set_Scan_Params         type=ACTIVE intvl=10.0ms wnd=10.0ms own=PUBLIC filter=ALL
```

固定列宽：
- 时间戳 12 字符（`HH:MM:SS.mmm`）
- 方向 4 字符（`↓ HCI` / `↑ HCI`）
- 类型 4 字符（`Cmd ` / `Evt ` / `ACL ` / `SCO ` / `ISO `）
- 名字字段 ≥ 28 字符（左对齐填充，超长不截断）
- 参数字段：键=值 用空格分隔，每行一个事件

### 5.4 展开模式

错误 / 异常 / 显式 debug 级时切换：

```
HH:MM:SS.mmm  ↑ HCI Evt  Command_Complete           op=LE_Set_Scan_Params status=Invalid_HCI_Command_Parameters(0x12)
                         ├─ num_hci_command_packets = 1
                         ├─ command_opcode          = 0x200B (LE_Set_Scan_Params)
                         └─ status                  = 0x12 (Invalid_HCI_Command_Parameters)
```

**触发条件：**
- `Command_Complete` / `Command_Status` 的 `status != Success`
- `Disconnection_Complete` 的 `reason != Connection_Terminated_By_Local_Host`
- 解码失败（异常）
- 用户显式 `--trace=hci=debug`（debug 级别全部展开）

### 5.5 SIG DB 集成

通过 `pybluehost/core/sig_db.py`（已有）：
- `sig_db.company_name(id)` —— manufacturer specific data 的 company_id
- 假设其他 lookup 已有；若缺则在格式化器内做小型常量映射（如 LE PHY、role、address type）

## 6. ConsoleSink

```python
class ConsoleSink:
    """Live trace to stderr with optional ANSI colors and anti-flood."""
    def __init__(
        self,
        *,
        color: bool | None = None,        # None = auto from TTY/NO_COLOR/FORCE_COLOR
        layers: set[str] | None = None,   # None = all (e.g. {"hci","sm"})
        level: str = "info",              # info / debug
        max_acl_payload: int = 24,        # bytes shown before truncation
        suppress: set[str] | None = None, # default: {"Number_Of_Completed_Packets"}
        adv_collapse_window: float = 5.0, # collapse repeat adv reports for N seconds
    ): ...

    async def on_trace(self, event: TraceEvent) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...
```

### 6.1 颜色

| 元素 | ANSI |
|------|------|
| ↓ DOWN（host→ctrl） | cyan |
| ↑ UP（ctrl→host） | green |
| Cmd / Req | yellow |
| Evt / Rsp | magenta |
| Error / status≠0 | red bold |
| Layer 标签 | dim |
| 解析名字 | bright |

**TTY / 环境变量探测**（业界标准，与 git/grep/bat 一致）：
- `color=None`（默认）：`sys.stderr.isatty()` 且无 `NO_COLOR` 环境变量 → 上色
- `NO_COLOR=1` 强关
- `FORCE_COLOR=1` 强开
- `color=True` / `color=False` 显式覆盖一切

### 6.2 防刷屏

| 事件 | 默认行为 | 显式打开 |
|------|---------|---------|
| `Number_Of_Completed_Packets` | 完全 silence | `--trace=hci,include=Number_Of_Completed_Packets` |
| `LE_Advertising_Report` | 折叠相同 `(addr, addr_type)`，5 秒窗口结束/新地址出现时打 `... ×N` | 默认就好 |
| ACL data | header + 前 24 字节 hex | `--trace=full-acl` 全打 |

**实现细节：**
- ConsoleSink 内部维护 dict `_recent_adv: dict[(addr, addr_type), (count, last_ts)]`
- 每收到 LE_Adv_Report：若该 key 不存在 → 立刻打 + count=1；存在 → count++ 不打
- 每隔 5 秒（或新地址来时）扫一次 _recent_adv，把 count>1 的 key 输出 `... ×N from <addr>`

## 7. 控制机制

### 7.1 优先级（高 → 低）

1. CLI flag `--trace=...`
2. 环境变量 `PYBLUEHOST_TRACE=...`
3. 默认：关闭（不挂 ConsoleSink，零开销）

### 7.2 Spec 语法

```
PYBLUEHOST_TRACE=hci                      # hci 层 info 级
PYBLUEHOST_TRACE=hci=debug                # hci 层 debug 级（含字段全展开）
PYBLUEHOST_TRACE=hci,l2cap=debug,sm       # 多层独立级别
PYBLUEHOST_TRACE=*                        # 全部层 info
PYBLUEHOST_TRACE=*=debug                  # 全部层 debug
PYBLUEHOST_TRACE=hci,full-acl             # 选项式：full-acl
PYBLUEHOST_TRACE=                         # 显式关闭（覆盖更早设置）
```

**合法 layer 名字：** `hci`, `sm`, `transport`, `l2cap`, `att`, `gatt`, `smp`, `sdp`, `rfcomm`, `gap`

**合法选项（不是 layer，不能带级别）：** `full-acl`, `include=<event_name>`

**解析规则：** 用户传入的逗号分隔 token 中，凡是以选项名前缀（`full-acl`、`include=`）出现的归入 options；其余按 layer 解析（含可选 `=level`）。Layer 名字与选项名字不冲突。

### 7.3 顶层入口

```python
# pybluehost/core/trace_control.py

@dataclass
class TraceSpec:
    layers: dict[str, str]      # layer -> level ("info" | "debug")
    full_acl: bool = False
    include: set[str] = field(default_factory=set)


def parse_trace_spec(s: str) -> TraceSpec:
    """Parse a --trace / PYBLUEHOST_TRACE string. Empty / None means disabled."""


def trace_install(spec: TraceSpec, trace_system: TraceSystem) -> None:
    """Apply spec: configure stdlib logging levels for protocol layers + attach
    ConsoleSink to the given TraceSystem if hci layer enabled.
    """
```

### 7.4 集成点

`trace_install(spec, trace_system)` 取 TraceSystem 实例（per-Stack）。安装策略：

| 入口 | 调用 |
|------|------|
| `pybluehost/cli/__init__.py:main()` | 解析 `--trace`；env var fallback；调 `trace_install` 在 Stack 创建后（每条命令一个 Stack） |
| `tests/conftest.py` | pytest `--trace` 选项 + session-level 解析一次 `parse_trace_spec`，调 `apply_logging_levels(spec)` 调整 stdlib logging；`stack` fixture 构建 Stack 后再调 `attach_console_sink(spec, stack.trace)` 把 ConsoleSink 挂到该 Stack 的 TraceSystem |

注：`trace_install` = `apply_logging_levels` + `attach_console_sink`；后两者也作为公开 API 暴露，便于 CLI / pytest 各自取所需。

## 8. Phase 3 — 协议层 logger 注入清单

`logger = logging.getLogger(__name__)` 每个文件用，全部继承 `pybluehost` 顶层 logger，由 `log_config.yaml` 控制。

| 模块 | logger 名字 | 注入点 | 总数 |
|------|-----------|--------|------|
| `pybluehost.l2cap.manager` + `signaling` | `pybluehost.l2cap` | INFO: 信道开/关、配置完成；WARN: config reject/timeout；DEBUG: signaling PDU 摘要 | 5 |
| `pybluehost.ble.att` | `pybluehost.ble.att` | INFO: MTU exchange；WARN: Error Response；DEBUG: ReadByType/Read/Write 摘要 | 4 |
| `pybluehost.ble.gatt` | `pybluehost.ble.gatt` | INFO: service discovery 完成、CCCD 订阅；DEBUG: notification 到达 | 3 |
| `pybluehost.ble.smp` | `pybluehost.ble.smp` | INFO: pairing 启动 / phase 转换 / complete；WARN: pairing failure | 4 |
| `pybluehost.hci.controller` | `pybluehost.hci.connection` | INFO: LE_Connection_Complete / Disconnection_Complete | 2 |
| `pybluehost.classic.sdp` | `pybluehost.classic.sdp` | INFO: service search 完成；WARN: timeout / invalid response | 2 |
| `pybluehost.classic.rfcomm` | `pybluehost.classic.rfcomm` | INFO: 信道开/关；WARN: 异常断开 | 2 |
| `pybluehost.classic.gap` | `pybluehost.classic.gap` | INFO: inquiry 启动 / 完成 | 2 |
| `pybluehost.ble.security` (SSP) | `pybluehost.ble.smp` 复用 | INFO: SSP 阶段、user_confirmation 数字 | 2 |

**约 26 个 INFO + 14 个 DEBUG/WARN ≈ 40 个注入点**，跨 9 个文件。

**消息格式约定：**
- 每条 INFO 自包含上下文（含 connection handle / address）
- 不打字节流（字节流走 trace 系统）
- 错误带 SIG DB 解出的人读名字（如 `Connection_Timeout(0x08)` 而非裸 `0x08`）

**示例：**
```
INFO  pybluehost.hci.connection  HCI LE_Connection_Complete handle=0x0040 peer=Public 6E:1A:9C:81:5C:24 role=Central interval=30.0ms
INFO  pybluehost.l2cap            L2CAP CID=0x0040 PSM=0x0001(SDP) opened (MTU=672)
INFO  pybluehost.ble.smp          SMP pairing started: io_caps=DisplayYesNo, bonding=YES, mitm=YES
WARN  pybluehost.ble.att          ATT Error_Response handle=0x002A error=Insufficient_Authentication(0x05)
```

## 9. 文件清单

### 9.1 新增

| 路径 | 职责 |
|------|------|
| `pybluehost/hci/format.py` | `format_hci_packet()` 主入口 |
| `pybluehost/hci/format_fields.py` | 字段格式化器（约 20 个） |
| `pybluehost/core/trace_console.py` | `ConsoleSink` 类、anti-flood、TTY/color |
| `pybluehost/core/trace_control.py` | `parse_trace_spec()` + `trace_install()` |
| `tests/unit/hci/test_format.py` | format 输出 golden tests |
| `tests/unit/core/test_trace_console.py` | ConsoleSink 测试 |
| `tests/unit/core/test_trace_control.py` | spec 解析 + install 测试 |
| `tests/integration/test_trace_console_e2e.py` | subprocess 跑 CLI 验证彩色 stderr |

### 9.2 修改

| 路径 | 改动 |
|------|------|
| `pybluehost/hci/controller.py` | `_emit_trace` 增加 `decoded` 参数（解码失败时传 None） |
| `pybluehost/cli/__init__.py` | 顶层 `--trace` 选项 + 调 `trace_install` |
| `tests/conftest.py` | pytest `--trace` 选项 + session install |
| `pybluehost/l2cap/manager.py` | Phase 3 注入 |
| `pybluehost/l2cap/signaling.py` | Phase 3 注入 |
| `pybluehost/ble/att.py` | Phase 3 注入 |
| `pybluehost/ble/gatt.py` | Phase 3 注入 |
| `pybluehost/ble/smp.py` | Phase 3 注入 |
| `pybluehost/ble/security.py` | Phase 3 注入（SSP） |
| `pybluehost/classic/sdp.py` | Phase 3 注入 |
| `pybluehost/classic/rfcomm.py` | Phase 3 注入 |
| `pybluehost/classic/gap.py` | Phase 3 注入 |
| `pybluehost/core/__init__.py` | re-export `ConsoleSink` 与 `trace_install` |
| `README.md` | 加 "Trace / Debug" 段落 |
| `AGENTS.md` | 加 "调试 trace" 命令示例 |

### 9.3 不变

- 现有 `pybluehost/core/trace.py`（TraceSystem / 现有 sinks）
- 现有 `pybluehost/config/log_config.yaml`（仍是默认 logging 配置；trace_install 只调 `setLevel`）

## 10. 测试策略

### 10.1 HCI formatter (`tests/unit/hci/test_format.py`)

- 每个字段格式化器至少 1 个 golden（输入 → 期望字符串）
- 每个常用 opcode/event 一个 round-trip
- 紧凑模式 + 展开模式 + 错误状态自动展开
- `color=False`（去掉 ANSI 影响断言）

### 10.2 ConsoleSink (`tests/unit/core/test_trace_console.py`)

- 用 `io.StringIO` 替 stderr 抓输出
- 50 条相同 LE_Adv_Report → 只看到 1 条 + ×N
- 100 字节 ACL → 输出含 24 字节 + `...`
- `color=True` 时含 ANSI 转义码
- `NO_COLOR=1` 强关
- `layers={"hci"}` 时 sm 事件不打

### 10.3 Trace control (`tests/unit/core/test_trace_control.py`)

- `parse_trace_spec`：所有合法 / 非法形式
- `trace_install` 真挂 sink 到 TraceSystem 并验证

### 10.4 协议层 logger (`caplog` 散布在各层测试)

- 每个注入点 1 个测试：触发协议事件后断言 logger 输出含期望文本

### 10.5 集成 (`tests/integration/test_trace_console_e2e.py`)

- subprocess 跑 `pybluehost app gatt-browser --transport=virtual --trace=hci`，断言 stderr 含彩色 HCI 行
- `--trace=hci,l2cap=debug` 验证多层级别独立

## 11. 错误处理

| 场景 | 行为 |
|------|------|
| `--trace=invalid_layer` | `pytest.exit` / CLI 错误退出 4：`Unknown layer: invalid_layer` |
| `--trace=hci=invalid_level` | 同上：`Invalid level: invalid_level (must be info or debug)` |
| `--trace=hci=debug,full-acl,extra=garbage` | 同上：`Unknown trace option: extra=garbage` |
| `format_hci_packet(packet)` 抛异常 | ConsoleSink 捕获，回退到 `<format error: {exc}> raw={hex}` 单行；不让 trace 流崩溃 |
| `ConsoleSink.on_trace` 抛异常 | TraceSystem 已有 sink 错误隔离（不影响其他 sink） |
| SIG DB 查不到 company_id | 输出 `0x1234` 不带名字（不要假"Unknown"标签） |

## 12. 性能与开销

- **默认状态（无 trace 启用）**：`ConsoleSink` 不挂载；`HCIController._emit_trace` 仍调 `decode_hci_packet`，但解码很轻；新协议层 logger 调用走 stdlib `logger.isEnabledFor()` 短路（INFO 级别下一次 attribute lookup ≤ 1µs）
- **`--trace=hci`**：每 HCI 包多一次 `format_hci_packet` 调用 + stderr 写。稳态下 < 100µs/包
- **大 ACL 流量**：靠 `max_acl_payload=24` 截断 + ConsoleSink 内部 `flush` 节流
- **持续 LE_Adv_Report 风暴**：靠 `adv_collapse_window` 折叠

## 13. 验收标准

1. 默认 `pybluehost app gatt-browser --transport=virtual` 无新 trace 输出（行为不变）
2. `pybluehost app gatt-browser --transport=virtual --trace=hci` 在 stderr 看到彩色单行 HCI 流
3. `--trace=hci=debug` 看到每条 HCI 包多行展开
4. `NO_COLOR=1 ... --trace=hci` 输出去色但其他不变
5. `--trace=hci` + 触发 status≠0 的命令 → 该事件自动展开多行
6. `--trace=hci,l2cap` 同时看 HCI + L2CAP（INFO 级）
7. `--trace=l2cap=debug` 触发 L2CAP 信道开关时看到 INFO；触发 signaling 时看到 DEBUG
8. `--trace=invalid_layer` 退出码 4 + 清晰错误
9. `pytest tests/ --trace=hci` 跑测试时看到 HCI trace（功能与 CLI 一致）
10. SMP / SDP / GATT 等触发对应事件后 caplog 能抓到 INFO 输出
11. 全套测试覆盖率 ≥ 85%
12. README + AGENTS.md 文档化新选项
