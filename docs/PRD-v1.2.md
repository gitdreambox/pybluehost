# PyBlueHost PRD v1.2 — PTS IUT 支持

**版本**：v1.2
**日期**：2026-05-28
**状态**：✅ 已交付（Phase 1 ✅ 2026-06-22；Phase 2 ✅ 框架 2026-06-23，含 BTP Core/GAP/GATT/L2CAP + auto_pts_project + CI smoke；真机 pass-rate 留 operator）
**前置版本**：[PRD v1.0](PRD.md)（已完成 31 个 Plan）
**同期版本**：[PRD v1.1 — Virtual Sniffer](PRD-v1.1.md)（独立，无依赖）

---

## 1. 主线

让 PyBlueHost 当 **Implementation Under Test (IUT)**，跑 Bluetooth SIG 官方 PTS（Profile Tuning Suite）一致性测试。

需要：PTS dongle + SIG license（用户已有）。

---

## 2. 两种 PTS 测试哲学（参考调研）

调研了两个标杆做法：

| | **Android Fluoride** ([pts_guide.md](https://android.googlesource.com/platform/system/bt/+/master/doc/pts_guide.md)) | **auto-pts** ([github](https://github.com/auto-pts/auto-pts)) |
|---|---|---|
| 核心机制 | `persist.bluetooth.pts` 属性 + `bt_stack.conf` 的 **"PTS mode" 开关** | **BTP tester 接口** + 完整自动化 |
| PTS mode 干什么 | 调整栈行为让它**可测**：`PTS_SecurePairOnly` / `PTS_DisableConnUpdates` / `PTS_DisableSDPOnLEPair` / `PTS_SmpOptions` / `PTS_SmpFailureCase` / `PTS_AvrcpTest` | — |
| 驱动 IUT | **手动**：人用正常 UI/app 操作 + 人点 PTS MMI | **自动**：auto-pts WID handlers 通过 BTP 程序化驱动；server 包 PTSControl COM 暴露 XML-RPC |
| 工作量 | 极小（几个 config flag） | 大（BTP tester 后端，但复用 630+ test case） |

**两者是分层的**，不是二选一。Fluoride 的 "PTS mode" flags 无论自动还是手动都需要——某些正常栈行为会干扰一致性测试（自动 conn param update、LE pair 后自动 SDP 等）。

---

## 3. PyBlueHost 采取分阶段路线

```
Phase 1 (本版本)  — Layer 1: PTS mode 配置 + 手动驱动
                    让 PyBlueHost 可测 + 人工 MMI 驱动跑 PTS 一致性
Phase 2 (后续)    — Layer 2: BTP tester 后端接入 auto-pts
                    复用 auto-pts server (PTSControl COM 封装) + WID handlers
                    + 630+ test case，CI 自动化
```

---

## 4. Phase 1 范围（本版本）

### 4.1 PTS mode 配置 flags（Fluoride 启发）

调整栈行为让它可测：

| Flag | 作用 |
|---|---|
| `pts_disable_conn_updates` | 抑制 LE 连接参数自动更新（干扰 GAP 测试） |
| `pts_secure_pair_only` | 强制 Secure Connections only 配对 |
| `pts_disable_sdp_on_le_pair` | LE pair 后不自动 SDP（避免 cross-key derivation 错误） |
| `pts_smp_options` | 覆盖 SMP 配对选项（hex bytes，特定 test case 需要） |
| `pts_smp_failure` | 注入 SMP 失败（测异常路径 test case） |
| 其它按 test group 需要追加 | — |

激活方式：config / CLI flag / 环境变量（沿用 v1.0 配置机制）。

### 4.2 IUT action layer + 交互式控制台：`pybluehost app pts-iut`

**先抽 action layer，REPL 是它的前端。** Phase 1 把"驱动栈"的动作抽成一个内部 action API 层（advertise/connect/pair/notify/write/sdp-browse/rfcomm-open/...），REPL 只是它的命令行前端。这样 Phase 2 的 BTP tester 能复用同一层（见 §5.3），不必重写驱动逻辑。

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

### 4.3 PICS / IXIT

- 为目标 test group 编写 PICS（Protocol Implementation Conformance Statement）——声明 PyBlueHost 支持哪些 feature，PTS 据此选适用 test case
- **半自动生成**：从 PyBlueHost 已有的能力来源（`pybluehost tools info` HCI capability dump / `features_decode` feature 表 / profile 注册表 / 各层 `__init__` 公共 API）程序化生成 PICS 草稿，再人工校正
  - 目的：减少手写错误 + 让 PICS 与实际栈能力同步（栈加 feature 时 PICS 可重生成）
  - 产出一个 PICS 生成器工具（属 Plan P.3）
- IXIT（Implementation eXtra Information for Testing）——测试参数（IUT 地址、key 等），手写
- 放在 `docs/pts/pics/` + `docs/pts/ixit/`，PTS UI 导入或文档说明

### 4.4 目标 test group（全 host 栈）

- HCI
- L2CAP
- GAP
- GATT (含 ATT)
- SMP
- Classic SDP
- Classic RFCOMM

每个 group 手动跑通 + 记录通过率 + 修 PTS 暴露的栈 bug。

---

## 5. Phase 2 — auto-pts 自动化（后续，不在本版本）

Phase 2 的目标是**去掉人工**：不再靠操作员看 MMI、敲 REPL，而是让 [auto-pts](https://github.com/auto-pts/auto-pts) 程序化驱动 PyBlueHost 跑完整 test case 集，并接入 CI。

### 5.1 auto-pts 是怎么工作的

auto-pts 是 **client-server** 架构，把"控制 PTS"和"驱动 IUT"分到两端：

```
┌─────────────────────────────┐         ┌──────────────────────────────────┐
│ Windows 机器                 │         │ IUT 侧（可 Linux / 同机）          │
│                             │         │                                  │
│  PTS.exe + dongle           │         │  autoptsclient                   │
│      ▲                      │         │   - 选 test case                  │
│      │ PTSControl COM       │ XML-RPC │   - WID/MMI handlers（按 profile） │
│  autoptsserver  ◄───────────┼─────────┤   - 把 MMI → BTP 命令              │
│   - 封装 COM 成 XML-RPC      │         │            │ BTP over socket/serial│
│   - RunTestCase / 回调 MMI   │         │            ▼                      │
└─────────────────────────────┘         │  IUT 的 BTP tester               │
                                         │   - 收 BTP 命令 → 驱动协议栈      │
                                         │   - 回 BTP event                 │
                                         │            │                     │
                                         │            ▼                     │
                                         │  被测协议栈                       │
                                         └──────────────────────────────────┘
```

- **autoptsserver**（Windows，挨着 PTS.exe）：把 PTS 的 PTSControl COM API 封装成 XML-RPC 暴露出来；负责 `RunTestCase`、接收 PTS 弹的 MMI/WID 回调转发给 client。
- **autoptsclient**（IUT 侧，可以不在 Windows）：通过 XML-RPC 跟 server 说话选 test case；内置**按 profile 分的 WID handler 模块**（如 `gap_wid_hdl.py` / `gatt_wid_hdl.py`），把每个 test case 的 MMI 提示（WID 号）映射成一串 BTP 命令，自动驱动 IUT——**这就是替代人工 MMI 的部分**。
- **BTP（Bluetooth Test Protocol）**：client ↔ IUT tester 之间的二进制协议（header = Service ID + Opcode + Controller Index + Length + Data），分 Core / GAP / GATT / L2CAP / SMP 等 service。client 发 BTP 命令让 IUT "去广播 / 去连接 / 去配对 / 去写特征"，IUT 回 BTP event 报结果。

### 5.2 PyBlueHost 需要做什么

| 工作 | 说明 |
|---|---|
| **BTP tester 服务** | PyBlueHost 监听 socket/serial，解码 BTP 命令 → 调 PyBlueHost 栈 API → 编码 BTP event 回传。这是 Phase 2 的主要新代码（按 service 实现：Core/GAP/GATT/L2CAP/SMP）。 |
| **注册成 auto-pts IUT project** | 给 autoptsclient 加一个 PyBlueHost project 模块（workspace + PICS/IXIT 路径 + tester 启动方式）。 |
| **WID handler 复用/适配** | 优先复用 auto-pts 现成的 per-profile WID handlers（它们发的是标准 BTP 命令，与 IUT 无关）；只在 PyBlueHost 行为特殊处微调。**不自己从零写 MMI 应答逻辑。** |
| **CI 集成** | autoptsclient 跑 test case 集打分；可对 PyBlueHost virtual controller 自测，或接真 dongle。 |

### 5.3 与 Phase 1 的衔接

Phase 1 的交互式 REPL 和 Phase 2 的 BTP tester 是**同一组"驱动栈"原语的两个前端**：

```
                ┌──────────────────────────────┐
  Phase 1  ───► │ IUT action layer             │ ───► PyBlueHost Stack
  REPL 命令      │ (advertise/connect/pair/     │      (PTS mode flags 开)
                │  notify/write/sdp/rfcomm...) │
  Phase 2  ───► │                              │
  BTP 命令       └──────────────────────────────┘
```

所以 Phase 1 应把这些动作抽成一个**内部 action API 层**，REPL 是它的命令行前端；Phase 2 的 BTP tester 复用同一层，只是换成 BTP 协议前端。这样 Phase 2 不用重写驱动逻辑，PTS mode flags（§4.1）也对两条路径同时生效。

### 5.4 Phase 2 NON-Goal 边界

- **Classic SDP / RFCOMM 不在 Phase 2 BTP 范围**：auto-pts BTP 历史上 LE-centric（Zephyr/Mynewt 主导），上游无 SDP/RFCOMM service。Phase 2 只自动化 LE 目标 group（HCI/L2CAP/GAP/GATT/SMP）；Classic SDP/RFCOMM **永久保留 Phase 1 REPL 手动模式**，直到上游或本地扩展支持
- 不 fork auto-pts，作为外部依赖使用（贡献 PyBlueHost project 模块回上游或本地维护）
- autoptsserver 端不改动（直接用上游 + PTS.exe）
- Phase 2 不在本 PRD 排期，框架在 Phase 1 的 action layer 抽象上自然延伸；正式启动时单独 brainstorm + 出 spec

---

## 6. 架构（Phase 1）

```
┌──────────────────┐       人工 MMI         ┌────────────────────────┐
│ PTS.exe + dongle │◄─── 操作员看提示 ────►│ 操作员                 │
│ (Lower Tester)   │       人点 OK           │ 敲 REPL 命令           │
└────────┬─────────┘                         └──────────┬─────────────┘
         │ OTA (空中) / HCI                              │
         │                                    ┌──────────▼─────────────┐
         └───────────────────────────────────►│ pybluehost app pts-iut REPL│
                          IUT 被测            │  (常驻 session)        │
                                              │   │ 命令 → 栈动作       │
                                              │   ▼                    │
                                              │ Stack (PTS mode 开)    │
                                              │  - conn updates 抑制   │
                                              │  - secure pair only    │
                                              │  - SMP options 覆盖    │
                                              └────────────────────────┘
```

---

## 7. Phase 1 成功标准

| 指标 | 目标 |
|---|---|
| 每个目标 test group 能通过 PTS 手动跑 | 操作员用 REPL 驱动，完整跑完该 group 的适用 test case |
| PTS mode flags 行为正确 | 单元测试验证每个 flag 改变栈行为（conn update 抑制、secure-only 等） |
| 控制台覆盖所有需要的 MMI 动作 | advertise/connect/pair/notify/write/sdp/rfcomm/l2cap 等都能按需触发 |
| PICS 准确反映 PyBlueHost 能力 | PTS 据 PICS 选出的 test case 都适用，无"声明支持但跑不了"的 |
| 各 group 通过率记录 | 记录到 docs/pts/results/，PTS 暴露的栈 bug 归档 + 修复 |

**通过率目标**：Phase 1 **不设 ≥90% 硬指标**。目标是"能用 REPL 手动跑完适用 test case + 如实记录通过率 + 归档/修复暴露的栈 bug"。手动阶段跑多少算多少，被个别难缠 case 卡住不阻塞版本完成；90% 这类硬指标留给 Phase 2 BTP 自动化后再设。

---

## 8. Phase 1 时间估计

| Plan | 内容 | 工作量 |
|---|---|---|
| Plan P.1 | PTS mode 配置 flags（栈行为调整 + 单元测试） | ~1.5 周 |
| Plan P.2 | IUT action layer（驱动栈原语，Phase 2 BTP 复用）+ 交互式 REPL 前端（命令集 + 常驻 session 状态） | ~2 周 |
| Plan P.3 | PICS 半自动生成器（从 capability dump 出草稿）+ IXIT 手写（全 host 栈 7 个 group） | ~1 周 |
| Plan P.4 | 手动跑 PTS 各 group + 修栈 bug + 记录（迭代，开放式） | ~3-4 周（取决于 PTS 暴露多少 bug） |
| **Phase 1 合计** | | **~7.5-8.5 周** |

Plan P.4 是开放式——真正的一致性工作量取决于 PTS 暴露多少 bug。框架部分（P.1-P.3）~4.5 周确定。

---

## 9. 显式 NON-Goal（Phase 1）

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
- **v1.1**：[Virtual Sniffer](PRD-v1.1.md)（~5 周，4 Plan）
- **v1.2**：PTS IUT Phase 1（本 PRD，~7.5-8.5 周，4 Plan）；Phase 2 (BTP+auto-pts) 后续
- **v2.0**：Classic Audio（已 brainstorm，[PRD-v2.0](PRD-v2.0.md)）
- v1.1 与 v1.2 互不依赖，可任意顺序/并行；v1.1 做完后 PTS 测试失败可结合 virtual sniffer 抓包 debug
- v1.x 与 v2.0 无强依赖

---

## 11. 评审清单

- [x] 路线：分阶段——Phase 1 (Fluoride 式 PTS mode + 手动驱动) 先做，Phase 2 (auto-pts BTP tester) 后续
- [x] Phase 1 测试范围：全 host 栈（HCI / L2CAP / GAP / GATT / SMP / Classic SDP / RFCOMM）
- [x] 手动驱动接口：交互式 PTS IUT 控制台（REPL，常驻 session）
- [x] PTS mode flags 参考 Fluoride（DisableConnUpdates / SecurePairOnly / DisableSDPOnLEPair / SmpOptions / SmpFailure）
- [x] PICS 从 PyBlueHost capability 半自动生成（生成器属 Plan P.3）+ IXIT 手写（确认 2026-05-29）
- [x] Phase 1 时间估计 ~7.5-8.5 周可接受，照此；P.4 保持开放式（确认 2026-05-29）
- [x] 通过率：Phase 1 不设 ≥90% 硬指标，以"跑通适用 case + 记录 + 修 bug"为准；硬指标留 Phase 2（确认 2026-05-29）
