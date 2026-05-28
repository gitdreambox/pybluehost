# PyBlueHost PRD v1.1 — Virtual Sniffer + PTS IUT

**版本**：v1.1
**日期**：2026-05-28
**状态**：草案（brainstorm 进行中——virtual sniffer 子项目已确认，PTS IUT 子项目待 brainstorm）
**前置版本**：[PRD v1.0](PRD.md)（已完成 31 个 Plan）

---

## 0. v1.1 范围概述

v1.1 包含**两个相互独立的子项目**（各自一份 spec → plan → 实现，互不依赖）：

| 子项目 | 内容 | 状态 |
|---|---|---|
| **A. Virtual Sniffer** | 把 PyBlueHost 的 live HCI 流通过 Remote API 注入 Ellisys / Teledyne WPS 分析仪软件实时显示 | **本 PRD 覆盖**（已 brainstorm） |
| **B. PTS IUT 支持** | PyBlueHost 当 Implementation Under Test 跑 SIG 官方一致性测试 | 待单独 brainstorm + spec |

本 PRD 主体描述**子项目 A（Virtual Sniffer）**。PTS IUT 在 §9 简述，详细 spec 后续单独写。

原 PRD 路线图把 v1.1 定为 "PTS IUT + 分析仪集成"。实际演进后，"分析仪集成" 重新定义为 **virtual sniffer**——不是跟分析仪硬件做 OTA 抓包控制，而是把 PyBlueHost 自己的 HCI 流注入分析仪软件借其 UI 解码显示。

---

## 1. 子项目 A：Virtual Sniffer 主线

让 PyBlueHost 运行时的 **live HCI 流量**实时显示在 Ellisys Bluetooth Analyzer 或 Teledyne LeCroy Wireless Protocol Suite (WPS) 的专业分析仪 UI 里——借用它们成熟的协议解码、过滤、时间线视图，而不需要空中射频抓包硬件。

### 与 v1.0 的关系

v1.0 已有完整 Trace 系统（`core/trace.py`：`TraceEvent` + btsnoop/pcapng/console/ring-buffer 多 sink）。virtual sniffer 是**在这之上加一个新的 TraceSink**——不写文件，而是把 HCI-layer 的 TraceEvent 实时注入分析仪软件。不动现有 Trace 架构和其他 sink。

### 已有原型

`pybluehost/tools/` 下已有两家分析仪的 **working demo**（已实测跑通）：
- `Ellisys_live_virtual_sniffer.py`：实测 Ellisys "HCI Injection Overview" 显示 2 条 HCI Reset
- `WirelessProtocolSuite_live_virtual_sniffer.py`：实测 WPS 显示 "4 frames analyzed"（command×2 + event×2）
- `test_live_virtual_sniffer.py`：mock 服务器单元测试
- 分析文档：`PTS_Sniffer_Remote_Control_Analysis.md`

子项目 A 的工作是**把这些 demo 产品化进 PyBlueHost**：从"发固定 HCI Reset 帧"升级为"实时流式注入所有 HCI 流量"，封装成正式 TraceSink + CLI flag。

---

## 2. 目标用户与场景

| 场景 | 用户 |
|---|---|
| 调试 PyBlueHost 时在 Ellisys/WPS UI 里 live 看 HCI 交互（专业解码 + 过滤 + 时间线） | 协议测试工程师、嵌入式开发 |
| 不买空中抓包仪硬件，纯软件得到分析仪级 HCI 视图 | 一般开发者、学习者 |
| PyBlueHost 跑 e2e/profile 场景时，同步在分析仪里观察协议流 | 测试工程师 |
| 后续（子项目 B）PTS 测试失败时，结合分析仪抓包 debug | 认证测试工程师 |

---

## 3. 子项目 A 功能范围

### 3.1 核心：实时 VirtualSnifferSink

- 新增 `TraceSink` 子类型，挂进 v1.0 Trace 系统
- 接收 HCI-layer 的 `TraceEvent`（filter `source_layer == 'hci'`）
- 把 `raw_bytes` + `direction` 映射成分析仪注入格式
- 实时流式注入——PyBlueHost 跑任意场景时 HCI 流自动出现在分析仪 UI

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

### 3.5 显式 NON-Goal（子项目 A）

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

## 6. 成功标准（子项目 A 验收）

| 指标 | 目标 | 验证方式 |
|---|---|---|
| `pybluehost app ble-scan --virtual-sniffer=ellisys` live HCI 出现在 Ellisys UI | scan 期间 HCI Command/Event 实时显示在 HCI Injection Overview | 手动（真分析仪） |
| `pybluehost app ble-scan --virtual-sniffer=wps` live HCI 出现在 WPS UI | 同上，WPS frames analyzed 实时增长 | 手动 |
| GATT/SDP/A2DP 等长场景全程 HCI 不丢帧 | 高频 HCI 流量下注入稳定，无明显丢包 | 手动 + 计数比对 |
| ACL 数据帧也能注入（不只 Command/Event） | L2CAP/ATT 流量的 ACL HCI 包在分析仪里可见 | 手动 |
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

## 9. 子项目 B：PTS IUT 支持

### 9.1 主线

让 PyBlueHost 当 **Implementation Under Test (IUT)**，跑 Bluetooth SIG 官方 PTS（Profile Tuning Suite）一致性测试。

需要：PTS dongle + SIG license（用户已有）。

### 9.2 两种 PTS 测试哲学（参考调研）

调研了两个标杆做法：

| | **Android Fluoride** ([pts_guide.md](https://android.googlesource.com/platform/system/bt/+/master/doc/pts_guide.md)) | **auto-pts** ([github](https://github.com/auto-pts/auto-pts)) |
|---|---|---|
| 核心机制 | `persist.bluetooth.pts` 属性 + `bt_stack.conf` 的 **"PTS mode" 开关** | **BTP tester 接口** + 完整自动化 |
| PTS mode 干什么 | 调整栈行为让它**可测**：`PTS_SecurePairOnly` / `PTS_DisableConnUpdates` / `PTS_DisableSDPOnLEPair` / `PTS_SmpOptions` / `PTS_SmpFailureCase` / `PTS_AvrcpTest` | — |
| 驱动 IUT | **手动**：人用正常 UI/app 操作 + 人点 PTS MMI | **自动**：auto-pts WID handlers 通过 BTP 程序化驱动；server 包 PTSControl COM 暴露 XML-RPC |
| 工作量 | 极小（几个 config flag） | 大（BTP tester 后端，但复用 630+ test case） |

**两者是分层的**，不是二选一。Fluoride 的 "PTS mode" flags 无论自动还是手动都需要——某些正常栈行为会干扰一致性测试（自动 conn param update、LE pair 后自动 SDP 等）。

### 9.3 PyBlueHost 采取分阶段路线

```
Phase 1 (v1.1)  — Layer 1: PTS mode 配置 + 手动驱动
                  让 PyBlueHost 可测 + 人工 MMI 驱动跑 PTS 一致性
Phase 2 (后续)  — Layer 2: BTP tester 后端接入 auto-pts
                  复用 auto-pts server (PTSControl COM 封装) + WID handlers
                  + 630+ test case，CI 自动化
```

### 9.4 Phase 1 范围（v1.1）

**(1) PTS mode 配置 flags**（Fluoride 启发）——调整栈行为让它可测：

| Flag | 作用 |
|---|---|
| `pts_disable_conn_updates` | 抑制 LE 连接参数自动更新（干扰 GAP 测试） |
| `pts_secure_pair_only` | 强制 Secure Connections only 配对 |
| `pts_disable_sdp_on_le_pair` | LE pair 后不自动 SDP（避免 cross-key derivation 错误） |
| `pts_smp_options` | 覆盖 SMP 配对选项（hex bytes，特定 test case 需要） |
| `pts_smp_failure` | 注入 SMP 失败（测异常路径 test case） |
| 其它按 test group 需要追加 | — |

激活方式：config / CLI flag / 环境变量（沿用 v1.0 配置机制）。

**(2) 交互式 PTS IUT 控制台**：`pybluehost pts-iut`

- 常驻 session 的 REPL，保持连接/配对状态跨 MMI 提示
- 操作员随 PTS MMI 提示敲命令驱动 PyBlueHost：

```text
advertise [--type=...] [--data=...]    # 开始广播
scan [--active]                         # 开始扫描
connect <addr>                          # 发起连接
disconnect [handle]                     # 断开
pair [--io-cap=...] [--mitm]            # 发起配对
notify <handle> <value>                 # 发 GATT 通知
indicate <handle> <value>               # 发 GATT 指示
read <handle>                           # GATT 读
write <handle> <value>                  # GATT 写
sdp-browse <addr>                       # Classic SDP 浏览
rfcomm-open <addr> <channel>            # 开 RFCOMM 通道
l2cap-connect <addr> <psm>              # 开 L2CAP 通道
set-io-cap <cap>                        # 设 IO capability
status                                  # 当前连接/配对状态
```

**(3) PICS / IXIT**

- 为目标 test group 编写 PICS（Protocol Implementation Conformance Statement）——声明 PyBlueHost 支持哪些 feature，PTS 据此选适用 test case
- IXIT（Implementation eXtra Information for Testing）——测试参数（IUT 地址、key 等）
- 放在 `docs/pts/pics/` + `docs/pts/ixit/`，PTS UI 导入或文档说明

**(4) 目标 test group**（全 host 栈）：

- HCI
- L2CAP
- GAP
- GATT (含 ATT)
- SMP
- Classic SDP
- Classic RFCOMM

每个 group 手动跑通 + 记录通过率 + 修 PTS 暴露的栈 bug。

### 9.5 Phase 2（后续，不在 v1.1）

- BTP tester 后端：PyBlueHost 监听 serial/socket 收 BTP 命令 → 驱动栈
- 注册成 auto-pts 的 IUT project（workspace + PICS）
- auto-pts 自动驱动跑 630+ test case，CI 集成
- 复用 auto-pts 已有的 server (PTSControl COM 封装) + WID/MMI handlers，**不自己写 MMI 应答**

### 9.6 架构（Phase 1）

```
┌──────────────────┐       人工 MMI         ┌────────────────────────┐
│ PTS.exe + dongle │◄─── 操作员看提示 ────►│ 操作员                 │
│ (Lower Tester)   │       人点 OK           │ 敲 REPL 命令           │
└────────┬─────────┘                         └──────────┬─────────────┘
         │ OTA (空中) / HCI                              │
         │                                    ┌──────────▼─────────────┐
         └───────────────────────────────────►│ pybluehost pts-iut REPL│
                          IUT 被测            │  (常驻 session)        │
                                              │   │ 命令 → 栈动作       │
                                              │   ▼                    │
                                              │ Stack (PTS mode 开)    │
                                              │  - conn updates 抑制   │
                                              │  - secure pair only    │
                                              │  - SMP options 覆盖    │
                                              └────────────────────────┘
```

### 9.7 Phase 1 成功标准

| 指标 | 目标 |
|---|---|
| 每个目标 test group 能通过 PTS 手动跑 | 操作员用 REPL 驱动，完整跑完该 group 的适用 test case |
| PTS mode flags 行为正确 | 单元测试验证每个 flag 改变栈行为（conn update 抑制、secure-only 等） |
| 控制台覆盖所有需要的 MMI 动作 | advertise/connect/pair/notify/write/sdp/rfcomm/l2cap 等都能按需触发 |
| PICS 准确反映 PyBlueHost 能力 | PTS 据 PICS 选出的 test case 都适用，无"声明支持但跑不了"的 |
| 各 group 通过率记录 | 记录到 docs/pts/results/，PTS 暴露的栈 bug 归档 + 修复 |

### 9.8 Phase 1 时间估计

| Plan | 内容 | 工作量 |
|---|---|---|
| Plan P.1 | PTS mode 配置 flags（栈行为调整 + 单元测试） | ~1.5 周 |
| Plan P.2 | 交互式 PTS IUT 控制台 REPL（命令集 + 常驻 session 状态） | ~2 周 |
| Plan P.3 | PICS / IXIT 编写（全 host 栈 7 个 group） | ~1 周 |
| Plan P.4 | 手动跑 PTS 各 group + 修栈 bug + 记录（迭代，开放式） | ~3-4 周（取决于 PTS 暴露多少 bug） |
| **Phase 1 合计** | | **~7.5-8.5 周** |

Plan P.4 是开放式——真正的一致性工作量取决于 PTS 暴露多少 bug。框架部分（P.1-P.3）~4.5 周确定。

### 9.9 显式 NON-Goal（Phase 1）

| 项目 | 推迟到 |
|---|---|
| BTP tester 后端 / auto-pts 自动化 | Phase 2 |
| MMI 自动应答 | Phase 2（auto-pts WID handlers 负责） |
| BLE profile test groups（HRP/HOGP 等） | 后续（先做 host 栈 group） |
| Classic 音频 profile（A2DP/AVRCP/HFP）test group | v2.0 做完音频 profile 后 |
| Mesh test group | 不规划 |

---

## 10. 跨版本关系

- **v1.0**：已完成（31 Plans）
- **v1.1 子项目 A**：virtual sniffer（§1-8，~5 周）
- **v1.1 子项目 B**：PTS IUT Phase 1（§9，~7.5-8.5 周）；Phase 2 (BTP+auto-pts) 后续
- **v2.0**：Classic Audio（已 brainstorm，[PRD-v2.0](PRD-v2.0.md)）
- 两个 v1.1 子项目互不依赖，可任意顺序/并行；A 做完后 PTS 测试失败可结合 virtual sniffer 抓包 debug
- v1.1 与 v2.0 无强依赖

---

## 11. 评审清单

### 子项目 A（Virtual Sniffer）

- [x] 主线：virtual sniffer = 实时把 PyBlueHost HCI 注入 Ellisys/WPS 软件显示
- [x] 核心形态：实时 TraceSink（不是文件回放）
- [x] 后端：Ellisys + WPS 都做
- [x] 范围：只 live 注入显示 + 必需的最小 start capture；不做 save trace / markers / link keys 等 trace 管理
- [x] Ellisys .NET：PowerShell subprocess（沿用 demo）
- [x] 激活：`--virtual-sniffer=ellisys|wps` flag，任意 app 命令可加
- [x] Windows-only
- [ ] 工作量估计 ~5 周（4 个 Plan）是否合理？
- [ ] 注入范围是否要含 ACL/SCO（不只 HCI Command/Event）？

### 子项目 B（PTS IUT）

- [x] 路线：分阶段——Phase 1 (Fluoride 式 PTS mode + 手动驱动) 先做，Phase 2 (auto-pts BTP tester) 后续
- [x] Phase 1 测试范围：全 host 栈（HCI / L2CAP / GAP / GATT / SMP / Classic SDP / RFCOMM）
- [x] 手动驱动接口：交互式 PTS IUT 控制台（REPL，常驻 session）
- [x] PTS mode flags 参考 Fluoride（DisableConnUpdates / SecurePairOnly / DisableSDPOnLEPair / SmpOptions / SmpFailure）
- [ ] PICS/IXIT 是手写 vs 从 PyBlueHost capability 半自动生成？
- [ ] Phase 1 时间估计 ~7.5-8.5 周（含开放式 P.4 修 bug）是否可接受？
- [ ] 通过率目标——原 PRD 说 ≥90%，Phase 1 是否设硬指标还是"尽量跑通 + 记录"？
