# PyBlueHost PRD v1.1 — Virtual Sniffer

**版本**：v1.1
**日期**：2026-05-28
**状态**：草案（brainstorm 已确认）
**前置版本**：[PRD v1.0](PRD.md)（已完成 31 个 Plan）
**同期版本**：[PRD v1.2 — PTS IUT](PRD-v1.2.md)（独立，无依赖）

---

## 1. 主线

让 PyBlueHost 运行时的 **live HCI 流量**实时显示在 Ellisys Bluetooth Analyzer 或 Teledyne LeCroy Wireless Protocol Suite (WPS) 的专业分析仪 UI 里——借用它们成熟的协议解码、过滤、时间线视图，而不需要空中射频抓包硬件。

"virtual sniffer" 指数据源是软件注入的（PyBlueHost 把自己的 HCI 流通过 Remote API 送给分析仪软件），不是空中射频捕获。

### 与 v1.0 的关系

v1.0 已有完整 Trace 系统（`core/trace.py`：`TraceEvent` + btsnoop/pcapng/console/ring-buffer 多 sink）。virtual sniffer 是**在这之上加一个新的 TraceSink**——不写文件，而是把 HCI-layer 的 TraceEvent 实时注入分析仪软件。不动现有 Trace 架构和其他 sink。

### 已有原型

`pybluehost/tools/` 下已有两家分析仪的 **working demo**（已实测跑通）：
- `Ellisys_live_virtual_sniffer.py`：实测 Ellisys "HCI Injection Overview" 显示 2 条 HCI Reset
- `WirelessProtocolSuite_live_virtual_sniffer.py`：实测 WPS 显示 "4 frames analyzed"（command×2 + event×2）
- `test_live_virtual_sniffer.py`：mock 服务器单元测试
- 分析文档：`PTS_Sniffer_Remote_Control_Analysis.md`

本版本 = **把这些 demo 产品化进 PyBlueHost**：从"发固定 HCI Reset 帧"升级为"实时流式注入所有 HCI 流量"，封装成正式 TraceSink + CLI flag。

---

## 2. 目标用户与场景

| 场景 | 用户 |
|---|---|
| 调试 PyBlueHost 时在 Ellisys/WPS UI 里 live 看 HCI 交互（专业解码 + 过滤 + 时间线） | 协议测试工程师、嵌入式开发 |
| 不买空中抓包仪硬件，纯软件得到分析仪级 HCI 视图 | 一般开发者、学习者 |
| PyBlueHost 跑 e2e/profile 场景时，同步在分析仪里观察协议流 | 测试工程师 |
| PTS 测试失败时（见 [PRD v1.2](PRD-v1.2.md)），结合分析仪抓包 debug | 认证测试工程师 |

---

## 3. 功能范围

### 3.1 核心：实时 VirtualSnifferSink

- 新增 `TraceSink` 子类型，挂进 v1.0 Trace 系统
- 接收 HCI-layer 的 `TraceEvent`（filter `source_layer == 'hci'`）
- 把 `raw_bytes` + `direction` 映射成分析仪注入格式
- 实时流式注入——PyBlueHost 跑任意场景时 HCI 流自动出现在分析仪 UI
- **注入包类型范围**：HCI Command / Event / **ACL** / **SCO** 四种全做（每种映射到 Ellisys packet type / WPS Drf 的对应值）
  - ACL 是看 L2CAP/ATT/GATT 交互的关键，分析仪价值最大
  - SCO 格式编码 + 单测在 v1.1 完成；但 v1.0 还没音频路径，**真实 SCO 流要到 v2.0 才有得跑**，v1.1 的 SCO 路径只能用构造帧验证编码正确性

### 3.2 Ellisys 后端

- **HCI 注入**：纯 UDP（Ellisys HCI Injection 协议，Service ID 0x0002）
  - UDP 包结构：Service ID + Version + DateTimeNs + ControllerIndex + Bitrate + HCI Packet Type + HCI Packet Data（所有整数 little-endian）
  - HCI Packet Type：0x01=Command，0x84=Event（ACL/SCO 另有 type）
  - HCI data **不带 H4 packet type 前缀**
- **最小 setup**（注入帧能显示的必需步骤）：通过 Ice/.NET（PowerShell subprocess 加载 `Ice.dll` + `EllisysAnalyzerBluetoothRemoteControlPlugin.dll`）调：
  - `SelectDataSource('injection')`
  - `StartRecording()`
- 启动分析仪：`Ellisys.BluetoothAnalyzer.exe /remote_control_port=<tcp> /injection_api_port=<udp> /suffix=PTS`（若未运行）
- 默认端口：TCP 46148（remote control）/ UDP 24352（injection）

### 3.3 Teledyne WPS 后端

- **HCI 注入**：ctypes 调 `LiveImportAPI.dll` 的 `SendFrame3`
  - `SendFrame3` timestamp 是 Unix epoch nanoseconds
  - Drf（data flow）：1=Command，8=Event（ACL/SCO 另有值）
  - Side：0=Host，1=Controller
  - HCI payload **不带 H4 packet type 前缀**
- **最小 setup**：
  - 启动 `Fts.exe /ComProbe Protocol Analysis System=Generic /oemkey=Virtual`
  - `InitializeLiveImport`（connection string 用产品根目录 `liveimport.ini` 的 `[General]`，`[Configuration]` 用开发包版本——实测这个组合才能让 HCI 帧显示）
  - `SendNotification(eStartCaptureToFile=6)` 启动 capture
- WPS Live Import Developer Kit 参考：`Live Import Developers Kit/h/LiveImportAPI.h`、`csample.c`

### 3.4 激活方式

- **CLI flag**：`--virtual-sniffer=ellisys|wps`，任意 `pybluehost app` 命令可加
  - 例：`pybluehost app ble-scan --transport=usb --virtual-sniffer=ellisys`
  - 例：`pybluehost app gatt-server --transport=usb --virtual-sniffer=wps`
  - 沿用现有 `--pybluehost-trace=hci` 的 trace control 机制
- **编程接口**：`Stack(..., trace_sinks=[EllisysVirtualSnifferSink(...)])` 或通过 trace 注册
- flag 带可选参数覆盖默认端口/路径，例：`--virtual-sniffer=ellisys:tcp=46148,udp=24352`

### 3.5 显式 NON-Goal

| 项目 | 原因 / 推迟到 |
|---|---|
| 录制控制（save trace 文件 .btt/.cfax、markers、comments、link keys、device filter） | 超出 "live 显示" 范围；用户在分析仪 UI 里手动操作；后续可选加 |
| 抓**系统蓝牙栈**（Windows bthusb / Linux BlueZ）的 HCI | 本项目只注入 PyBlueHost **自己**的 HCI 流；旁观系统栈是另一个独立想法 |
| OTA 空中射频抓包控制（触发 Ellisys/WPS 硬件抓包 + 取包） | 需要抓包仪硬件；virtual sniffer 是纯软件注入路线，不碰硬件 OTA |
| C# helper EXE / pythonnet（Ellisys .NET 接入） | 第一版用 PowerShell subprocess（demo 已验证）；后续如需稳定性再评估 |
| macOS / Linux 上的 virtual sniffer | Ellisys/WPS 分析仪软件只有 Windows；本功能 Windows-only |

---

## 4. 架构

```
┌────────────────────────────────────────────────────────────────┐
│  PyBlueHost (any session: ble-scan / gatt-server / a2dp / ...)  │
│                                                                 │
│  HCI Controller ──emit──► Trace System (v1.0)                  │
│                              │                                  │
│                              ├─► BtsnoopSink   (v1.0)          │
│                              ├─► PcapngSink    (v1.0)          │
│                              ├─► ConsoleSink   (v1.0)          │
│                              └─► VirtualSnifferSink (v1.1 NEW)  │
│                                    │ filter source_layer=='hci'│
│                                    │ map raw_bytes + direction │
│                                    ▼                           │
│                          ┌──────────────────┐                  │
│                          │ backend dispatch │                  │
│                          └────┬────────┬────┘                  │
│                               │        │                       │
│              ┌────────────────▼──┐  ┌──▼─────────────────────┐ │
│              │ EllisysBackend    │  │ WpsBackend             │ │
│              │ - launch analyzer │  │ - launch Fts.exe       │ │
│              │ - PowerShell Ice  │  │ - ctypes LiveImport    │ │
│              │   SelectSource +  │  │   InitializeLiveImport │ │
│              │   StartRecording  │  │   + SendNotification   │ │
│              │ - UDP inject      │  │ - SendFrame3 inject    │ │
│              └────────┬──────────┘  └──────────┬─────────────┘ │
└───────────────────────│────────────────────────│──────────────┘
                        │ UDP 24352              │ ctypes call
                        ▼                        ▼
              ┌──────────────────┐    ┌────────────────────────┐
              │ Ellisys Bluetooth│    │ Teledyne WPS           │
              │ Analyzer.exe     │    │ Fts.exe                │
              │ (Windows)        │    │ (Windows)              │
              │ HCI Injection    │    │ Live Import display    │
              │ Overview 显示    │    │ frames analyzed        │
              └──────────────────┘    └────────────────────────┘
```

### 关键架构决策

1. **VirtualSnifferSink 是 TraceSink 子类**：复用 v1.0 Trace dispatch loop，不动现有架构。`on_trace(event)` 里 filter HCI 层 + map + 注入。
2. **两后端共用抽象**：`VirtualSnifferSink` 基类定义 `_inject_hci(packet_type, direction, raw_bytes, timestamp)`；`EllisysBackend` / `WpsBackend` 各自实现。类似 codec 模块的多后端。
3. **注入非阻塞**：TraceEvent 来自 asyncio dispatch loop。UDP send（Ellisys）很快可直接发；ctypes `SendFrame3`（WPS）可能短暂阻塞，用 `run_in_executor` 隔离。分析仪启动 + 最小 setup 是一次性（sink 构造/首帧时），不在每帧路径。
4. **Ellisys .NET 走 PowerShell subprocess**：沿用 demo，生成 .ps1 加载 Ice.dll + Plugin.dll 调 Remote Control。一次性 setup，不在每帧路径。
5. **HCI data 不带 H4 type**：两家注入格式的 HCI payload 都剥掉 H4 packet type 字节；packet type 通过各自的字段（Ellisys packet type / WPS Drf+Side）表达。
6. **Windows-only**：sink 在非 Windows 上构造即报清晰错误（"virtual sniffer requires Windows + Ellisys/WPS software"）。

---

## 5. 技术约束

继承 v1.0 全部约束，新增：

- **平台**：**Windows-only**（Ellisys/WPS 分析仪软件只有 Windows）。非 Windows 上 `--virtual-sniffer` flag 报清晰错误。
- **Ellisys 依赖**：
  - Ellisys Bluetooth Analyzer 软件（用户已装）
  - Remote Control Plugin（`bta_remote_api.zip` 解压到 analyzer 目录）
  - HCI Injection API（`bex400a_injection_api.zip` 参考；注入本身是裸 UDP，不需 SDK 库）
  - PowerShell（Windows 自带）做 Ice/.NET 调用
- **WPS 依赖**：
  - Teledyne LeCroy WPS 软件（用户已装，4.60+）
  - `LiveImportAPI.dll`（WPS 自带）via ctypes
  - Live Import Developer Kit 的 `liveimport.ini [Configuration]`（实测必需）
- **不预绑定 vendor SDK**：PyBlueHost 不随包分发 Ellisys/WPS 的 DLL（licensing）；运行时定位用户已装路径。
- 主代码对 ctypes / PowerShell 调用全部 lazy + try-except，非 Windows / 软件未装时不影响其他功能。

---

## 6. 成功标准

| 指标 | 目标 | 验证方式 |
|---|---|---|
| `pybluehost app ble-scan --virtual-sniffer=ellisys` live HCI 出现在 Ellisys UI | scan 期间 HCI Command/Event 实时显示在 HCI Injection Overview | 手动（真分析仪） |
| `pybluehost app ble-scan --virtual-sniffer=wps` live HCI 出现在 WPS UI | 同上，WPS frames analyzed 实时增长 | 手动 |
| GATT/SDP/A2DP 等长场景全程 HCI 不丢帧 | 高频 HCI 流量下注入稳定，无明显丢包 | 手动 + 计数比对 |
| ACL 数据帧也能注入（不只 Command/Event） | L2CAP/ATT 流量的 ACL HCI 包在分析仪里可见 | 手动 |
| SCO 帧注入格式编码正确 | 构造 SCO 帧的 Ellisys/WPS 注入参数与 spec 一致（真实 SCO 流待 v2.0） | 单元测试（mock） |
| 非 Windows 上 flag 报清晰错误 | Linux/macOS 跑 `--virtual-sniffer=ellisys` 提示 Windows-only | 单元测试 |
| 注入格式编码正确（mock 验证） | Ellisys UDP 包 / WPS SendFrame 参数与 spec 一致 | 单元测试（mock 服务器/DLL） |
| 不影响现有 trace sink | 同时开 `--pybluehost-trace=hci` + `--virtual-sniffer` 两者都正常 | e2e |

---

## 7. 时间估计

| Plan | 内容 | 工作量 |
|---|---|---|
| Plan V.1 | VirtualSnifferSink 基类 + HCI 注入格式编码（Ellisys UDP + WPS SendFrame 格式，纯软件可单测） | ~1 周 |
| Plan V.2 | Ellisys 后端：analyzer 启动 + PowerShell Ice 最小 setup + UDP 注入 + 真机验证 | ~1.5 周 |
| Plan V.3 | WPS 后端：Fts.exe 启动 + ctypes LiveImport + SendFrame3 注入 + 真机验证 | ~1.5 周 |
| Plan V.4 | CLI `--virtual-sniffer` flag 集成 + trace control wiring + 文档 + 收尾 | ~1 周 |
| **合计** | | **~5 周** |

按 vertical slice 排：V.1 格式编码（纯软件，CI 可测）→ V.2 Ellisys 真机跑通 → V.3 WPS 真机跑通 → V.4 CLI 收尾。V.2/V.3 可并行（不同后端）。

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| Ellisys 注入帧不显示（StartRecording 没正确选 injection 源） | live 看不到数据 | demo 已验证正确序列：SelectDataSource('injection') + StartRecording 后 UDP 注入显示；沿用 demo 逻辑 |
| WPS LiveImport connection string / Configuration 组合敏感 | API 成功但 UI 0 frames | demo 实测确认：产品根目录 connection string + 开发包 [Configuration] 才显示；固化这个组合 |
| 高频 HCI 流量下 ctypes SendFrame 阻塞 asyncio loop | 卡顿/丢帧 | WPS 注入走 `run_in_executor` 隔离；加内部队列缓冲 |
| 真机验证依赖 Windows + 已装分析仪软件 | CI 无法自动验证注入显示 | 格式编码层用 mock 单测（mock UDP 服务器 / mock DLL）；真机显示作为手动验收，记录到 docs |
| PowerShell Ice 调用脆弱（端口占用、版本不匹配） | Ellisys setup 失败 | 沿用 demo 的 retry + IsRecording 检查逻辑；错误时清晰报告端口/版本问题 |
| vendor SDK 再分发许可 | 不能随包带 DLL | 不预绑定；运行时定位用户已装路径；文档说明依赖 |

---

## 9. 评审清单

- [x] 主线：virtual sniffer = 实时把 PyBlueHost HCI 注入 Ellisys/WPS 软件显示
- [x] 核心形态：实时 TraceSink（不是文件回放）
- [x] 后端：Ellisys + WPS 都做
- [x] 范围：只 live 注入显示 + 必需的最小 start capture；不做 save trace / markers / link keys 等 trace 管理
- [x] Ellisys .NET：PowerShell subprocess（沿用 demo）
- [x] 激活：`--virtual-sniffer=ellisys|wps` flag，任意 app 命令可加
- [x] Windows-only
- [x] 工作量估计 ~5 周（4 个 Plan）合理，照此（确认 2026-05-29）
- [x] 注入范围 = HCI Command + Event + ACL + SCO 四种全做（确认 2026-05-29）；SCO 格式编码可单测，真实 SCO 流待 v2.0 音频路径
