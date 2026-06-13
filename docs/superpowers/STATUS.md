# PyBlueHost — 项目任务状态

> **上下文恢复锚点**：读完此文件即可重建全部上下文，然后打开对应 Plan 文档从第一个 `- [ ]` 继续。

---

## 快速定位

**当前状态**：v1.0 完结（31 Plans，Hardware E2E Readiness ✅）；**v2.0 Classic Audio ✅ 全部交付 + v2.1 Plan B.1（USB SCO quirk 适配）✅**；v1.1 Virtual Sniffer / v1.2 PTS IUT PRD 草案就绪，待动工
**下一步候选**：
1. **v1.1 Virtual Sniffer**——PRD 草案就绪（[`docs/PRD-v1.1.md`](../PRD-v1.1.md)）。把 PyBlueHost live HCI 注入 Ellisys/WPS 分析仪软件显示。4 个 Plan、~5 周、Windows-only。design spec + Plan **未编写**。
2. **v1.2 PTS IUT**——PRD 草案就绪（[`docs/PRD-v1.2.md`](../PRD-v1.2.md)）。PyBlueHost 当 IUT 跑 SIG PTS 一致性。Phase 1 = Fluoride 式 PTS mode + 交互式控制台手动驱动，4 个 Plan、~7.5-8.5 周；Phase 2 = auto-pts BTP 自动化（后续）。design spec + Plan **未编写**。
3. **v2.0 Classic Audio**——PRD + design spec 已就绪（[`docs/PRD-v2.0.md`](../PRD-v2.0.md) + [`docs/superpowers/specs/2026-05-27-prd-v2.0-classic-audio-design.md`](specs/2026-05-27-prd-v2.0-classic-audio-design.md)）。6 个 Plan、14-17 周、SBC+CVSD+mSBC（无 AAC）。**Plan A.1（codec 层）✅**（11 个 Task + libsbc backend；53 codec 单测；与 BlueZ libsbc 字节级一致；真音频 PSNR 80-87 dB）+ **Plan A.2（AVDTP + A2DP）✅**（11 个 Task + 53 单测 + 1 e2e；AVDTP signaling 完整、A2DPSource/Sink 注册到 PSM 0x0019、双 L2CAP 信道路由按 ACL handle 区分 signaling/media；端到端 source→sink PCM round-trip **PSNR 81.2 dB**）+ **Plan A.3（AVRCP + AVCTP）✅**（11 个 Task；46 单测 + 1 e2e；PASS_THROUGH 全套 + REGISTER_NOTIFICATION + INTERIM 响应；UUIDs 0x110E/0x110F/0x110C）+ **Plan A.4（HFP + SCO file loopback）✅**（11 个 Task；~48 单测 + 1 e2e；SLC 三阶段建立 + SCO link setup + CVSD/mSBC WAV 文件 loopback；HCI SCO Data Packet 类型 0x03；UUIDs 0x111E/0x111F）+ **Plan A.5（HSP + CVSD SCO loopback）✅**（6 个 Task；21 单测 + 1 e2e；复用 A.4 基础设施；UUIDs 0x1131/0x1112；RFCOMM HS=5/AG=12；CVSD-only，no SLC handshake）+ **Plan A.6（CLI + sounddevice + runbook）✅**（6 个 Task；28 单测；6 个新 `app` CLI 命令（a2dp-source/sink、avrcp-control/target、hfp-test/hsp-test）+ sounddevice 懒加载（`[audio]` extras）+ `docs/CLASSIC_AUDIO_E2E.md` 真机 runbook + USB SCO Alt-Setting deferred 到 v2.1）。**v2.0 ✅ 全部交付**。
4. 自托管硬件 CI runner / 真机首批 adapter survey / 断线重连闭环（v1.0 运营改进，可并行）
**版本互不依赖**：v1.1 / v1.2 / v2.0 可任意顺序或并行推进
**不在路线图**：SMP Sub-Plan 3c (OOB)、HFP 实时 SCO 音频（推 v2.1）、AAC（推 v2.x）、LE Audio、macOS native

> **注意（2026-04-18 深度审查后更新）**：
> - Plan 编号已重映射（2.5→3，3→4，…，旧 plan10 删除，新 plan10→11）
> - Plans 3/4/6/8/9 已拆分为更细粒度（a/b 子 Plan，文档已就绪）
> - Plan 10a（PcapngSink + 回放模式）已合并进 Plan 10（文件集重叠：core/trace.py + stack.py）
> - Plan 1/2 补充遗漏项已完成
> - 所有 Plan 文档末尾新增"审查补充事项"章节，包含 19 项全局遗漏的分配
> - 审查报告详见 [review-notes-2026-04-18.md](../architecture/review-notes-2026-04-18.md)

---

## Plan 总览

| 编号 | 名称 | 状态 | 文档 | 代码路径 |
|------|------|------|------|---------|
| Plan 1 | Core Infrastructure | ✅ 完成（有遗漏项待补） | [plan1](plans/plan1-core-infrastructure.md) | `pybluehost/core/` |
| Plan 2 | Transport Foundation | ✅ 完成（有遗漏项待补） | [plan2](plans/plan2-transport-foundation.md) | `pybluehost/transport/` |
| Plan 3a | USB Transport 核心 | ✅ 完成 | [plan3a](plans/plan3a-usb-transport.md) | `transport/usb.py`, `transport/hci_user_channel.py` |
| Plan 3b | 固件管理系统 | ✅ 完成 | [plan3b](plans/plan3b-firmware.md) | `transport/firmware/`, `cli/fw.py` |
| Plan 4a | HCI Packet Codec + Flow Control | ✅ 完成 | [plan4a](plans/plan4a-hci-codec.md) | `hci/constants.py`, `hci/packets.py`, `hci/flow.py`, `hci/vendor/` |
| Plan 4b | HCI Controller + VirtualController | ✅ 完成 | [plan4b](plans/plan4b-hci-controller.md) | `hci/controller.py`, `hci/virtual.py` |
| Plan 5 | L2CAP Layer | ✅ 完成 | [plan5](plans/plan5-l2cap.md) | `pybluehost/l2cap/` |
| Plan 6a | ATT + GATT | ✅ 完成 | [plan6a](plans/plan6a-att-gatt.md) | `ble/att.py`, `ble/gatt.py` |
| Plan 6b | SMP + SecurityConfig | ✅ 完成 | [plan6b](plans/plan6b-smp-security.md) | `ble/smp.py`, `ble/security.py` |
| Plan 7 | Classic Stack (SDP/RFCOMM/SPP) | ✅ 完成 | [plan7](plans/plan7-classic-stack.md) | `pybluehost/classic/` |
| Plan 8a | BLE GAP | ✅ 完成 | [plan8a](plans/plan8a-ble-gap.md) | `core/gap_common.py`, `ble/gap.py` |
| Plan 8b | Classic GAP + 统一 GAP 入口 | ✅ 完成 | [plan8b](plans/plan8b-classic-gap.md) | `classic/gap.py`, `pybluehost/gap.py` |
| Plan 9a | BLE Profile 框架 | ✅ 完成 | [plan9a](plans/plan9a-profile-framework.md) | `profiles/ble/base.py`, `decorators.py`, `yaml_loader.py` |
| Plan 9b | 内置 BLE Profile 实现 | ✅ 完成 | [plan9b](plans/plan9b-builtin-profiles.md) | `profiles/ble/*.py` |
| Plan 10 | Stack 工厂 + PcapngSink + 回放 + E2E | ✅ 完成 | [plan10](plans/plan10-stack-integration.md) | `pybluehost/stack.py`, `core/trace.py` |
| Plan 11 | 测试基础设施 | ✅ 完成 | [plan11](plans/plan11-test-infrastructure.md) | `tests/fakes/`, `.github/workflows/` |
| CLI app+tools | CLI 命令行工具（app + tools 两命名空间，12 个子命令） | ✅ 完成 | [cli-app-tools](plans/cli-app-tools.md) | `pybluehost/cli/app/`, `pybluehost/cli/tools/` |
| Pytest Transport Selection | pytest transport 选择机制 | ✅ 已完成 | [pytest-transport-selection](plans/pytest-transport-selection.md) | `tests/conftest.py`, `tests/_transport_select.py`, `pybluehost/stack.py` |
| Trace / Log Structured Output | HCI 结构化彩色 trace + 协议层 logger 注入 | ✅ 已完成 | [trace-log-system](plans/trace-log-system.md) | `pybluehost/hci/format.py`, `pybluehost/hci/format_fields.py`, `pybluehost/core/trace_console.py`, `pybluehost/core/trace_control.py`, 9 protocol-layer files |
| PRD 1.0 收尾 | PcapngSink + Stack 工厂补全 + SMP 装配 + RFCOMM dispatch fix + bond_storage | ✅ 完成 | [2026-05-12-prd-v1-closure](plans/2026-05-12-prd-v1-closure.md) | `core/trace.py`, `core/errors.py`, `stack.py`, `l2cap/manager.py`, `ble/smp.py`, `gap.py`, `classic/rfcomm.py` |
| transport/usb 拆包 | 2562 行 god module 拆成 8 个职责清晰的 sibling 模块 | ✅ 完成 | [2026-05-12-transport-usb-split](plans/2026-05-12-transport-usb-split.md) | `pybluehost/transport/usb/{__init__,chips,errors,discovery,diagnostics,base,intel,realtek,csr}.py` |
| SMP Sub-Plan 1 (Legacy JW) | Legacy Just Works 配对完整路径 + 绑定 + 重连自动加密 | ✅ 完成 | [2026-05-13-smp-pairing-legacy-jw](plans/2026-05-13-smp-pairing-legacy-jw.md) | `pybluehost/ble/smp.py`, `pybluehost/ble/_smp_state.py`, `pybluehost/hci/virtual_link.py`, `pybluehost/stack.py`, `pybluehost/ble/gatt.py` |
| SMP Sub-Plan 1 收尾 | TIMEOUT/DISCONNECTED/PAIRING_FAILED_RX 单测 + Stack.encrypt 等事件 + BondInfo.rand 兼容 + register_peer_address + Plan checkbox | ✅ 完成 | [2026-05-16-smp-sub-plan-1-followups](plans/2026-05-16-smp-sub-plan-1-followups.md) | `pybluehost/ble/smp.py`, `pybluehost/stack.py` |
| HCI 容错初始化 | initialize() 按 Supported_Commands bitmap 跳过不支持的命令；Read_BD_ADDR 硬要求 | ✅ 完成 | [2026-05-16-hci-tolerant-initialization](plans/2026-05-16-hci-tolerant-initialization.md) | `pybluehost/hci/capabilities.py`, `pybluehost/hci/controller.py`, `pybluehost/hci/virtual.py` |
| Secure Connections | LE SC (ECDH P-256 + f4/f5/f6) + BR/EDR SC (HCI SSP events) Just Works；opt-in via SecurityConfig.enable_secure_connections | ✅ 完成 | [2026-05-17-secure-connections](plans/2026-05-17-secure-connections.md) | `pybluehost/ble/_smp_sc_crypto.py`, `pybluehost/ble/smp.py`, `pybluehost/ble/_smp_state.py`, `pybluehost/ble/security.py`, `pybluehost/hci/{packets,controller,virtual,capabilities}.py`, `pybluehost/classic/gap.py`, `pybluehost/stack.py` |
| SMP Sub-Plan 3a (Numeric Comparison) | LE SC Numeric Comparison association model：g2 计算 + PairingDelegate.confirm_numeric + auth_req MITM 位 + 双端 authenticated 持久化 + LE SC NC loopback E2E | ✅ 完成 | [2026-05-18-smp-sub-plan-3a-numeric-comparison](plans/2026-05-18-smp-sub-plan-3a-numeric-comparison.md) | `pybluehost/ble/_smp_state.py`, `pybluehost/ble/smp.py`, `pybluehost/ble/security.py`, `pybluehost/classic/gap.py`, `pybluehost/stack.py` |
| SMP Sub-Plan 3b-1 (Legacy Passkey Entry) | Legacy Passkey Entry association model：`SMPState.PASSKEY_INPUT_PENDING` + `PairingDelegate.display_passkey`/`get_passkey` 规范化 + Display/Input role 选择 + IO-cap 适配 + c1 共享 TK + 双端 authenticated 持久化 + Legacy Passkey loopback E2E | ✅ 完成 | [2026-05-18-smp-sub-plan-3b-1-legacy-passkey](plans/2026-05-18-smp-sub-plan-3b-1-legacy-passkey.md) | `pybluehost/ble/_smp_state.py`, `pybluehost/ble/smp.py` |
| SMP Sub-Plan 3b-2 (SC Passkey Entry) | LE SC Passkey Entry association model：`SMPState.PASSKEY_SC_ROUND` 反身 20 轮 f4 commit/reveal + Display/Input role 复用 3b-1 + 20-round-exit 进 SC f5/f6 + 双端 authenticated 持久化 + VirtualController 补 `Number_Of_Completed_Packets` 释放 ACL flow credit + SC Passkey loopback E2E | ✅ 完成 | [2026-05-19-smp-sub-plan-3b-2-sc-passkey](plans/2026-05-19-smp-sub-plan-3b-2-sc-passkey.md) | `pybluehost/ble/_smp_state.py`, `pybluehost/ble/smp.py`, `pybluehost/hci/virtual.py` |
| E2E LE Lifecycle | tests/e2e/ 首轮覆盖：scan→connect→pair→GATT 4 个端到端场景；transport-agnostic（virtual 自动跑 / hardware 用 --transport=usb 手动跑） | ✅ 完成 | [2026-05-20-e2e-le-lifecycle](plans/2026-05-20-e2e-le-lifecycle.md) | `tests/e2e/{conftest,_test_service,_helpers,test_le_lifecycle}.py` |
| VirtualClassicLink | BR/EDR (Classic) peer-to-peer 桥接：Inquiry / Connection / ACL / Auth (SSP+Legacy) / Encryption / Disconnect 六个子桥；两个 Stack.virtual() 真实 inquiry→connect→SSP JW pair→encrypt→disconnect 端到端 | ✅ 完成 | [2026-05-20-virtual-classic-link](plans/2026-05-20-virtual-classic-link.md) | `pybluehost/hci/virtual_classic_link.py`, `pybluehost/hci/virtual.py`, `pybluehost/hci/constants.py` |
| Classic Workflow E2E | tests/e2e/ Classic 4 个端到端场景：SDP browse + RFCOMM/SPP echo + bonded reconnect 双 session + pair-failure 清洁拆链；transport-agnostic（virtual 自动跑 / hardware 用 --transport=usb 手动跑） | ✅ 完成 | [2026-05-21-classic-workflow-e2e](plans/2026-05-21-classic-workflow-e2e.md) | `tests/e2e/{_classic_test_service,_helpers,conftest,test_classic_lifecycle}.py`, `pybluehost/hci/virtual_classic_link.py`, `pybluehost/l2cap/manager.py` |
| Hardware E2E Readiness | `build_stack_from_spec(config=)` 解锁 hardware-mode skips；`e2e_timeout` 传输自适应超时；`pybluehost tools info` 全量 HCI 能力 dump CLI；`docs/HARDWARE_E2E.md` runbook。HCIController 缓存 manufacturer/version/features 响应。所有可在 virtual 上验证；真机验证待 adapter 到货后手动执行。 | ✅ 完成 | [2026-05-22-hardware-e2e-readiness](plans/2026-05-22-hardware-e2e-readiness.md) | `tests/_transport_resolve.py`, `tests/e2e/_helpers.py`, `tests/e2e/test_*_lifecycle.py`, `pybluehost/hci/{features_decode,capabilities,controller,constants}.py`, `pybluehost/cli/tools/info.py`, `docs/HARDWARE_E2E.md` |
| MITM-1 | MITM 应用骨架 + ACL relay 核心（重组/CID 分流/重分片）+ btsnoop capture | ✅ 完成（21 单测；协议栈零改动） | [mitm-1](plans/2026-06-01-mitm-1-acl-relay-core.md) | `pybluehost/cli/app/mitm/{acl,relay,capture,controllers,cli}.py` |
| MITM-2 | BLE 路径 + app 内最小 SMP（SC Just Works/Numeric） | ✅ 完成（范围 C：编排+fake 单测；虚拟三角 e2e 留真机） | [mitm-2](plans/2026-06-01-mitm-2-ble-path-min-smp.md) | `pybluehost/cli/app/mitm/{pairing/,recon,impersonate,orchestrator}.py` |
| MITM-3 | BR/EDR 路径 + SSP 终结（HCI 事件）+ 可选改址 | ✅ 完成（范围 C：SSP/编排+fake 单测；VirtualClassicLink e2e 留真机） | [mitm-3](plans/2026-06-01-mitm-3-bredr-path-ssp.md) | `pybluehost/cli/app/mitm/{pairing/ssp,bredr_recon,bredr_impersonate,address,orchestrator}.py` |
| MITM-4 | CLI（le/bredr/both）+ Numeric Comparison 交互 + runbook | ✅ 完成 | [mitm-4](plans/2026-06-01-mitm-4-cli-numeric-docs.md) | `pybluehost/cli/app/mitm/cli.py`, `pybluehost/cli/app/mitm/pairing/delegate.py`, `docs/MITM.md` |
| v2.1 Plan B.1 | USB SCO Alt-Setting + vendor quirks（Intel Alt 1/6、Realtek 0xFC8B、真 iso IN/OUT、prepare_for_sco hook） | ✅ 完成（mock-based 单测；真机 E2E 待 adapter） | [b.1](plans/2026-06-13-v2.1-plan-B.1-usb-sco-alt-setting.md) | `pybluehost/transport/{base.py,usb/{base,intel,realtek}.py}`, `pybluehost/hci/controller.py` |

> **MITM 透传应用（独立应用，4 Plan）✅ 全部完成（2026-06-02）**：授权安全测试用中间人，双 radio、B 式 HCI-ACL 透传，仅复用 `transport`+`hci`，**协议栈+hci 层零改动**，89 个 mitm 单元测试全 PASS。spec：[`specs/2026-06-01-mitm-passthrough-design.md`](specs/2026-06-01-mitm-passthrough-design.md)。v1 = BLE+BR 透传+抓包（btsnoop）；**改写（规则/hook）为后续**。**待真机验证**：recon/impersonate/连接/逐链路加密的 HCI 时序、虚拟三角 e2e（虚拟控制器不支持真实广播/SSP 桥接，故 Task 7/MITM-3 Task 5 取范围 C：编排+fake 单测）、`--clone-address`、both 模式并发接线。

> **v2.1 Plan B.1 ✅（2026-06-13）**：v2.0 deferred 的 USB SCO Alt-Setting + vendor quirk 适配。8 Task（Transport.prepare_for_sco hook、HCIController 自动调用、select_sco_alt_setting + iso EP 枚举、真正 iso IN/OUT、Intel Alt 1/6 选择、Realtek vendor cmd 0xFC8B、mocked Intel 集成测试、文档更新）。全部 mock-based 单测覆盖，真机 E2E 验证待 Intel/Realtek adapter 到货后手动执行。Out-of-scope：Broadcom Alt 编号（B.2）、实时 PCM↔OS 音频（B.2）、多 SCO、CSR8510（硬件不支持）。

**总计：32 个 Plan（原 31 个 + v2.1 Plan B.1）**

---

## 依赖关系与并行执行建议

```
Plan 1 ──► Plan 2 ──► Plan 3a ──► Plan 4a ──► Plan 4b ──► Plan 5
                  │                                           │
                  └──► Plan 3b（可与 3a 并行）                │
                                                              ├──► Plan 6a ──┐
                                                              ├──► Plan 6b ──┤（并行）
                                                              └──► Plan 7  ──┤
                                                                             │
                                                              Plan 8a ◄──────┤
                                                              Plan 8b ◄──────┘（并行）
                                                                   │
                                                              Plan 9a ──► Plan 9b
                                                                              │
                                                         Plan 10 ◄────────────┘
                                                              │
                                                         Plan 11
```

---

## 详细进度

### ✅ Plan 1 — Core Infrastructure
- 完成时间：2026-04-14
- 提交范围：`pybluehost/core/` 全部模块 + `tests/unit/core/`
- 测试：177 tests passed（其中 21 个 sig_db 测试需要 submodule）
- **补充遗漏项（待后续 Plan 补入）**：
  - `core/gap_common.py`（AdvertisingData、ClassOfDevice、Appearance、FilterPolicy、DeviceInfo）→ 并入 Plan 8a 或新建 Plan 1 补丁
  - `TracingProxy` 类（装饰任意 SAP 实现，自动 emit TraceEvent）→ 并入 Plan 4b
  - `PcapngSink` → 并入 Plan 10a

### ✅ Plan 2 — Transport Foundation
- 完成时间：2026-04-15（遗漏项补充完成：2026-04-18）
- 提交范围：`pybluehost/transport/` + `tests/unit/transport/`
- 测试：186 tests passed（全套），transport 覆盖率 97%
- **遗漏项已全部补充**：
  - ✅ `ReconnectConfig` frozen dataclass（policy, max_attempts, base_delay, max_delay）
  - ✅ `TransportSink.on_transport_error()` 回调方法
  - ✅ `Transport._notify_error()` 辅助方法 + 三个具体 Transport 的 read loop 错误传播

### ✅ Plan 3a — USB Transport 核心
- 完成时间：2026-04-19
- 提交范围：`transport/usb.py`（ChipInfo/KNOWN_CHIPS/USBTransport/auto_detect/端点路由）、`transport/hci_user_channel.py`、`transport/__init__.py` 更新
- 测试：22 新增测试（test_usb.py 18 + test_hci_user_channel.py 4），237 全套 PASS
- 新增 `pyusb>=1.2` 可选依赖（`[project.optional-dependencies] usb`）
- 待硬件验收：auto_detect + open/close 需要真实 Intel/Realtek USB 蓝牙适配器

### ✅ Plan 3b — 固件管理系统
- 完成时间：2026-04-19
- 提交范围：`transport/firmware/__init__.py`、`transport/usb.py`（Intel/Realtek _initialize）、`cli/__init__.py`、`cli/fw.py`
- 测试：29 新增测试（test_firmware.py 8 + test_intel_fw.py 6 + test_realtek_fw.py 5 + test_fw.py 10），237 全套 PASS
- 新增 `[project.scripts] pybluehost = "pybluehost.cli:main"`
- 待硬件验收：Intel 6 步 + Realtek 5 步固件加载序列需要真实硬件
- 待实现：AUTO_DOWNLOAD 策略的 HTTP 下载逻辑（当前 placeholder）

### ✅ Plan 4a — HCI Packet Codec + Flow Control
- 完成时间：2026-04-19
- 提交范围：`hci/constants.py`、`hci/packets.py`、`hci/flow.py`、`hci/vendor/intel.py`、`hci/vendor/realtek.py`、`hci/__init__.py`
- 测试：56 新增测试（test_constants 8 + test_packets 22 + test_flow 12 + test_vendor 14），293 全套 PASS
- 包含补充1（HCIISOData）：H4 type 0x05 ISO 数据包 encode/decode 往返测试

### ✅ Plan 4b — HCI Controller + VirtualController
- 完成时间：2026-04-19
- 提交范围：`hci/controller.py`（HCIController + ConnectionManager + 16 步 initialize()）、`hci/virtual.py`（VirtualController 16 命令处理）、`hci/packets.py`（15 个新 Command 类）、`core/errors.py`（CommandTimeoutError）、`hci/__init__.py` 更新
- 测试：30 新增测试（test_controller 8 + test_virtual 19 + integration/test_hci_init 3），323 全套 PASS
- 集成测试：LoopbackTransport 连接 HCIController ↔ VirtualController，验证 16 步 init 序列完整性

### ✅ Plan 5 — L2CAP Layer
- 完成时间：2026-04-20
- 提交范围：`l2cap/constants.py`、`l2cap/sar.py`（Reassembler 多 handle 隔离 + Segmenter）、`l2cap/channel.py`（Channel ABC + ChannelState + SimpleChannelEvents）、`l2cap/ble.py`（FixedChannel + LECoCChannel 含 credit 背压）、`l2cap/classic.py`（ClassicChannel + ERTMEngine + StreamingEngine）、`l2cap/signaling.py`（SignalingPacket + ConnParamUpdate）、`l2cap/manager.py`（L2CAPManager + LE/Classic 自动注册）
- 测试：46 新增测试（test_sar 8 + test_ble 10 + test_classic 8 + test_signaling 8 + test_manager 9 + integration/test_hci_l2cap 3），369 全套 PASS
- 含审查补充：补充1(Streaming)、补充2(ConnParamUpdate)、补充3(ATT+SMP 自动注册)、补充4(ERTM wraparound 修正)、补充5(多 handle SAR 隔离)、补充6(CoC credit 背压)

### ✅ Plan 6a — ATT + GATT
- 完成时间：2026-04-19
- 提交范围：`ble/att.py`（ATTOpcode 28 码 + 29 PDU 类 + decode_att_pdu + ATTBearer async 请求/响应）、`ble/gatt.py`（AttributeDatabase + GATTServer 含 service 展开/CCCD/notification/indication + GATTClient 含 service discovery）、`ble/__init__.py` 全部导出
- 测试：35 新增测试（test_att 24 + test_gatt 11），404 全套 PASS
- 含审查补充：ATT MTU 协商、PrepareWrite/ExecuteWrite Long Attribute、Read Blob

### ✅ Plan 6b — SMP + SecurityConfig
- 完成时间：2026-04-20
- 提交范围：`ble/smp.py`（SMPCode 14 opcodes + 11 PDU classes + SMPCrypto 9 函数 + BondInfo + BondStorage Protocol + JsonBondStorage + PairingDelegate + AutoAcceptDelegate + SMPManager）、`ble/security.py`（SecurityConfig + CTKDDirection + CTKDManager 含 h7/h6 chain）、`ble/__init__.py` 更新
- 测试：48 新增测试（test_smp 42 + test_security 6），452 全套 PASS
- 含：BT Spec 附录 D 测试向量验证全部 9 个 crypto 函数

### ✅ Plan 7 — Classic Stack
- 完成时间：2026-04-21
- 提交范围：`classic/sdp.py`（DataElement 全类型 codec + ServiceRecord + SDPServer 含 ServiceSearchAttribute 处理 + SDPClient）、`classic/rfcomm.py`（RFCOMMFrameType 6 种 + CRC-8 FCS + frame encode/decode + RFCOMMSession/Channel/Manager）、`classic/spp.py`（SPPConnection async context manager + SPPService + SPPClient）、`classic/__init__.py` 全部导出
- 测试：39 新增测试（test_sdp 18 + test_rfcomm 16 + test_spp 5），491 全套 PASS

### ✅ Plan 8a — BLE GAP
- 完成时间：2026-04-20
- 提交范围：`core/gap_common.py`（Appearance 21 值 + FilterPolicy + ClassOfDevice + DeviceInfo + AdvertisingData AD 结构 encode/decode）、`ble/gap.py`（BLEAdvertiser + ExtendedAdvertiser + BLEScanner + BLEConnectionManager + PrivacyManager RPA 解析 + WhiteList）、`hci/constants.py`（7 个新 LE opcode）、`hci/__init__.py` + `ble/__init__.py` + `core/__init__.py` 导出更新
- 测试：23 新增测试（test_gap_common 12 + test_gap 11），514 全套 PASS

### ✅ Plan 8b — Classic GAP + 统一 GAP 入口
- 完成时间：2026-04-21
- 提交范围：`classic/gap.py`（ClassicDiscovery + ClassicDiscoverability + ClassicConnectionManager + SSPManager + EIR + ScanEnableFlags + InquiryConfig + ClassicConnection）、`pybluehost/gap.py`（统一 GAP 入口 + set_pairing_delegate()）、`hci/constants.py`（+HCI_INQUIRY_CANCEL, +HCI_WRITE_EXTENDED_INQUIRY_RESPONSE）、`classic/__init__.py` 导出更新
- 测试：20 新增测试（test_gap 20），534 全套 PASS

### ✅ Plan 9a — BLE Profile 框架
- 完成时间：2026-04-21
- 提交范围：`profiles/ble/base.py`（BLEProfileServer + BLEProfileClient）、`profiles/ble/decorators.py`（ble_service + on_read/write/notify/indicate）、`profiles/ble/yaml_loader.py`（load/loads/load_builtin/validate）、9 个服务 YAML（gap/gatt/dis/bas/hrs/bls/hids/rscs/cscs）、`profiles/ble/__init__.py` 导出
- 测试：23 新增测试（test_base 10 + test_yaml_loader 13），557 全套 PASS

### ✅ Plan 9b — 内置 BLE Profile 实现
- 完成时间：2026-04-21
- 提交范围：9 个 BLE Profile server（gap_service/gatt_service/dis/bas/hrs/bls/hids/rscs/cscs）+ 3 个 Client（HeartRateClient/BatteryClient/DeviceInformationClient）+ BLEProfileClient.discover/read/write 基类方法 + `profiles/ble/__init__.py` 完整导出
- 测试：27 新增测试（test_builtin 14 + test_clients 3 + test_base 10），574 全套 PASS

### ✅ Plan 10 — Stack 工厂 + 生命周期管理
- 完成时间：2026-04-25
- 提交范围：`pybluehost/stack.py`（StackConfig + StackMode + Stack._build() + Stack.loopback() + power_on/off/close + 全层组装）、`pybluehost/__init__.py`（顶层导出 Stack/StackConfig/StackMode）
- 测试：10 新增测试（test_stack 10），584 全套 PASS

### ✅ Plan 11 — 测试基础设施
- 完成时间：2026-04-25
- 提交范围：`tests/fakes/`（FakeTransport/FakeHCIDownstream/FakeChannelEvents/NullTrace）、`tests/unit/conftest.py` + `tests/integration/conftest.py` + `tests/e2e/conftest.py` + `tests/hardware/conftest.py`、`tests/btsnoop/test_replay.py` + `tests/data/hci_reset.btsnoop`、`pyproject.toml`（markers + coverage config）、`.github/workflows/test.yml`（CI Python 3.10/3.11/3.12 matrix）
- 测试：18 新增测试（test_fakes 14 + test_replay 4），602 全套 PASS，覆盖率 88.29%

### ✅ CLI app+tools — 命令行工具
- 完成时间：2026-04-25
- 提交范围：`pybluehost/cli/__init__.py` + `pybluehost/cli/_transport.py` + `pybluehost/cli/_target.py` + `pybluehost/cli/_lifecycle.py` + `pybluehost/cli/_loopback_peer.py` + `pybluehost/cli/app/`（8 命令：ble-scan/ble-adv/classic-inquiry/gatt-browser/sdp-browser/gatt-server/hr-monitor/spp-echo）+ `pybluehost/cli/tools/`（4 子族：decode/rpa/fw/usb，迁移自顶层）+ `README.md` 命令行工具章节
- 测试：约 31 新增测试（test_transport 7 + test_target 5 + test_lifecycle 4 + test_loopback_peer 2 + test_tools_decode 3 + test_tools_rpa 5 + test_tools_init 3 + 8 个 app 命令各 1 + test_main_entry 4 - 现有 fw/usb 测试位移），670 全套 PASS，覆盖率 85.01%
- 破坏性变更：`pybluehost fw <cmd>` → `pybluehost tools fw <cmd>`，`pybluehost usb <cmd>` → `pybluehost tools usb <cmd>`（v0.0.1 + 无外部用户，无 backward shim）

### ✅ Pytest Transport Selection
- **认领人**：Codex session
- **开始时间**：2026-04-27
- **当前进度**：全部完成（共 23 Task）
- **最后更新**：2026-04-28
- 已完成 Task：Task 1（loopback → virtual 公共 API 改名）、Task 2（LoopbackTransport 内化为 VirtualController._HCIPipe）、Task 3（USBTransport.list_devices 与 bus/address 过滤）、Task 4（Stack.from_usb() 与 Stack.from_uart() 工厂）、Task 5（parse_transport_arg 识别 bus/address）、Task 6（tests/_transport_select.py spec 解析 + autodetect）、Task 7（tests/_fallback_tracker.py session 级回落计数）、Task 8（tests/conftest.py pytest_addoption + --list-transports 处理）、Task 9（session fixtures selected_transport_spec / selected_peer_spec / transport_mode）、Task 10（stack / peer_stack fixtures）、Task 11（real_hardware_only / virtual_only marker enforcement）、Task 12（pytest_report_header / pytest_terminal_summary）、Task 13（删除 tests/integration/conftest.py 死代码）、Task 14（删除 tests/hardware/conftest.py）、Task 15（替换 tests/e2e/conftest.py）、Task 16（重写 tests/integration/test_hci_init.py 使用 stack fixture）、Task 17（重写 tests/integration/test_hci_l2cap.py 使用 stack fixture）、Task 18（重写 6 个 tests/unit/cli/test_app_*.py 使用 stack fixture）、Task 19（test_usb_smoke 迁移到 real_hardware_only，因 Task 14 前置检查发现 hardware_required 仍被使用而提前执行）、Task 20（test_intel_hw.py 使用 real_hardware_only(transport="usb", vendor="intel")）、Task 21（CI workflow 切换到 --transport=virtual）、Task 22（README.md 与 AGENTS.md 记录 pytest transport 选择）、Task 23（最终验证 + STATUS.md 更新）
- 进行中 Task：无
- 验证记录：Task 2 targeted tests PASS；`uv run pytest tests/ -q --ignore=tests/hardware` PASS；`uv run pytest tests/ -q -m "not hardware"` initially blocked by legacy hardware markers, resolved by later marker tasks；Task 3 `uv run pytest tests/unit/transport/test_usb_list_devices.py -v` PASS；`uv run pytest tests/unit/transport/ -q` PASS；Task 4 RED `uv run pytest tests/unit/test_stack_factories.py -v` failed as expected（from_usb bus/address TypeError；from_uart AttributeError）；Task 4 PASS `uv run pytest tests/unit/test_stack_factories.py -v` PASS；`uv run pytest tests/unit/test_stack.py -q` PASS；Task 5 RED `uv run pytest tests/unit/cli/test_transport_parse_bus_address.py -v` failed as expected（bus/address kwargs missing；unknown key / invalid int not rejected）；Task 5 PASS `uv run pytest tests/unit/cli/test_transport_parse_bus_address.py -v` PASS；`uv run pytest tests/unit/cli/test_transport.py -q` PASS；Task 6 RED `uv run pytest tests/unit/test_transport_select.py -v` failed as expected（missing tests._transport_select）；Task 6 PASS `uv run pytest tests/unit/test_transport_select.py -v` PASS（39 passed）；Task 7 RED `uv run pytest tests/unit/test_fallback_tracker.py -v` failed as expected（missing tests._fallback_tracker）；Task 7 PASS `uv run pytest tests/unit/test_fallback_tracker.py -v` PASS（2 passed）；Task 8 RED `uv run pytest tests/unit/test_conftest_options.py -v` failed as expected（help missing transport options）；Task 8 PASS `uv run pytest tests/unit/test_conftest_options.py -v` PASS；Task 8 collection sanity `uv run pytest tests/ -q --co --ignore=tests/hardware` PASS；Task 8 `uv run pytest --list-transports` PASS；Task 9 RED `uv run pytest tests/unit/test_session_fixtures.py -v` failed as expected（missing selected_transport_spec fixture/helpers）；Task 9 PASS `uv run pytest tests/unit/test_session_fixtures.py -v` PASS（6 passed）；Task 9 collection sanity `uv run pytest tests/ -q --co --ignore=tests/hardware` PASS；Task 10 RED `uv run pytest tests/integration/test_stack_fixture.py -v --transport=virtual` failed as expected（missing stack fixture）；Task 10 PASS `uv run pytest tests/integration/test_stack_fixture.py -v --transport=virtual` PASS（2 passed）；Task 10 collection sanity `uv run pytest tests/ -q --co --ignore=tests/hardware --transport=virtual` PASS；Task 10 quality review fix `uv run --frozen pytest tests/integration/test_stack_fixture.py -v --transport=virtual` PASS（2 passed）；`uv run --frozen pytest tests/unit/test_session_fixtures.py -v --transport=virtual` PASS（12 passed）；`uv run --frozen pytest tests/ -q --co --ignore=tests/hardware --transport=virtual` PASS；Task 11 RED `uv run --frozen pytest tests/unit/test_marker_enforcement.py -v` failed as expected（unknown markers / missing enforcement helpers）；Task 11 PASS `uv run --frozen pytest tests/unit/test_marker_enforcement.py -v` PASS（15 passed）；Task 11 collection sanity `uv run --frozen pytest tests/ -q --co --ignore=tests/hardware --transport=virtual` PASS；Task 12 RED `uv run --frozen pytest tests/unit/test_report_header.py -v` failed as expected（missing report header / summary hooks）；Task 12 PASS `uv run --frozen pytest tests/unit/test_report_header.py -v` PASS（5 passed）；Task 12 collection sanity `uv run --frozen pytest tests/ -q --transport=virtual --co --ignore=tests/hardware` PASS；Task 13 `uv run --frozen pytest tests/integration/ -v --transport=virtual` PASS（8 passed）；Task 14 grep confirmed no `hardware_required` / `--hardware` references after Task 19 migration；Task 19 `uv run --frozen pytest tests/hardware/test_usb_smoke.py -v --transport=virtual` PASS（2 skipped）；Task 19 UART preflight `uv run --frozen pytest tests/hardware/test_usb_smoke.py -q --transport=uart:/dev/null` exited 4 as expected；Task 14 collection `uv run --frozen pytest tests/ -q --co --transport=virtual` PASS；Task 15 `uv run --frozen pytest tests/e2e/ -q --transport=virtual` exited 5 because e2e currently has no tests and no errors；Task 15 full collection `uv run --frozen pytest tests/ -q --co --transport=virtual` PASS；Task 16 `uv run --frozen pytest tests/integration/test_hci_init.py -v --transport=virtual` PASS（3 passed）；Task 17 `uv run --frozen pytest tests/integration/test_hci_l2cap.py -v --transport=virtual` PASS（3 passed）；Task 18 `uv run --frozen pytest tests/unit/cli/test_app_ble_scan.py tests/unit/cli/test_app_ble_adv.py tests/unit/cli/test_app_classic_inquiry.py tests/unit/cli/test_app_gatt_server.py tests/unit/cli/test_app_hr_monitor.py tests/unit/cli/test_app_spp_echo.py -v --transport=virtual` PASS（6 passed）；Task 18 grep confirmed no `Stack.virtual()` calls remain in the six CLI app test files；Task 20 `uv run --frozen pytest tests/hardware/test_intel_hw.py -v --transport=virtual` PASS（8 skipped）；Task 20 `uv run --frozen pytest tests/hardware/test_intel_hw.py -q --transport=usb:vendor=realtek` exited 4 as expected on host without Realtek adapter；Task 21 `uv run --frozen pytest tests/ -v --tb=short --transport=virtual --cov=pybluehost --cov-report=term-missing --cov-fail-under=85` PASS（826 passed, 14 skipped, coverage 85.03%）；Task 22 grep confirmed README.md / AGENTS.md / CLAUDE.md have no loopback transport wording；Task 23 Step 23.1 `uv run --frozen pytest tests/ -q` PASS（autodetected Intel BE200 then CSR8510; Intel probe failed, CSR probe passed and was selected）；Task 23 Step 23.2 `uv run --frozen pytest tests/ -q --transport=virtual --cov=pybluehost --cov-fail-under=85` PASS（coverage 85.05%）；Task 23 Step 23.3 error paths PASS（garbage exit 4; usb+virtual peer mismatch exit 4）；Task 23 Step 23.4 `uv run --frozen pytest --list-transports` PASS（Intel BE200 and CSR8510 listed, exit 0）；Task 23 Step 23.5 rename / legacy marker residue grep PASS（0 matches）。

### ✅ Trace / Log Structured Output
- 设计文档：`docs/superpowers/specs/trace-log-system-design.md`
- 实施计划：`docs/superpowers/plans/trace-log-system.md`
- 完成时间：2026-05-08
- 关键变化：
  - 新增 `pybluehost/hci/format.py` + `format_fields.py`：HCI packet 结构化人读字符串，紧凑模式 + 错误自动展开 + SIG DB 查表（company_id/UUID/AD type）
  - 新增 `pybluehost/core/trace_console.py`：ANSI 彩色 + TTY 自动探测 (`NO_COLOR`/`FORCE_COLOR`) + anti-flood（`Number_Of_Completed_Packets` 抑制、ACL 24 字节截断、`LE_Advertising_Report` 同地址折叠）
  - 新增 `pybluehost/core/trace_control.py`：`TraceSpec` + `parse_trace_spec()` + `apply_logging_levels()` + `attach_console_sink()` + `trace_install()`，支持 `hci=debug,l2cap`、`*=debug`、`full-acl`、`include=...` 等语法
  - `HCIController._emit_trace` 现在挂载解码后的 `HCIPacket` 到 `TraceEvent.decoded`（`TraceEvent.decoded` 类型从 `dict` 放宽为 `object | None`，`JsonSink` 兼容处理）
  - 协议层 logger 注入（约 40 个 INFO / WARN / DEBUG 决策点，分布于 9 个文件）：
    - `l2cap/manager.py` + `l2cap/signaling.py`：信道开关、配置完成 / 拒绝、signaling PDU
    - `ble/att.py`：MTU exchange、Error_Response（含 SIG 错误名）、PDU dispatcher debug
    - `ble/gatt.py`：service discovery / CCCD / notification 三个 helper
    - `ble/smp.py`：pairing started / phase / complete / failed 四个 helper
    - `ble/security.py`：SSP user_confirmation / phase（共享 `pybluehost.ble.smp` logger）
    - `hci/controller.py`：`pybluehost.hci.connection` logger（`LE_Connection_Complete`、`Disconnection_Complete`）
    - `classic/sdp.py`：service search 完成 / 超时（已 wired 进 `SDPClient.search_attributes`）
    - `classic/rfcomm.py`：channel opened / closed（已 wired 进 `RFCOMMSession`）+ abnormal disconnect（standalone）
    - `classic/gap.py`：inquiry started / complete（已 wired 进 `ClassicDiscovery`）
  - CLI 顶层 `--trace` 选项（与 `PYBLUEHOST_TRACE` 等价；CLI 优先于 env）；invalid spec 退出码 4
  - pytest 选项 `--pybluehost-trace`（避开 pytest 内置 PDB plugin 占用的 `--trace`）；`stack` fixture 自动 attach ConsoleSink
  - 新增 `pybluehost/__main__.py` 让 `python -m pybluehost` 可调用（Task 23 集成测试需要）
- 已知遗留：4 个 pre-existing 失败（USB diagnostics × 3 + RFCOMM inbound handler × 1）与本计划无关，不在本计划范围内修复
- 验收：`uv run --frozen pytest tests/ -q --transport=virtual --cov-fail-under=85` PASS（coverage 86.32%）

### ✅ transport/usb 拆包
- 完成时间：2026-05-12
- Plan 文档：[2026-05-12-transport-usb-split.md](plans/2026-05-12-transport-usb-split.md)
- 关键变化：纯结构重构、零行为变更
  - `transport/usb.py`（2562 行）→ `transport/usb/` package（8 模块）
  - 拆分映射：chips（ChipInfo）/ errors（异常类型）/ discovery（13 个 device-discovery helper）/ diagnostics（USBDeviceDiagnostics + 直接 USB 探针）/ base（USBTransport + parse_hci_reset_status）/ intel（IntelUSBTransport + _BootParams）/ realtek（RealtekUSBTransport + RealtekLocalVersion）/ csr（CSRUSBTransport）
  - `__init__.py` 仅 ~110 行：re-export + KNOWN_CHIPS 表
  - `base.py` 引入 `_usb()` 帮助函数：tests 仍可通过 patch `pybluehost.transport.usb.usb` 影响子模块代码路径
  - 外部 import 路径完全不变（`from pybluehost.transport.usb import X` 全部仍工作，25 个公共符号）
- 已知遗留：仅 3 个 pre-existing USB diagnostics 失败
- 验收：`uv run --frozen pytest tests/ -q --transport=virtual --cov-fail-under=85` PASS

### ✅ PRD 1.0 收尾
- 完成时间：2026-05-12
- Plan 文档：[2026-05-12-prd-v1-closure.md](plans/2026-05-12-prd-v1-closure.md)
- 审查基线：[review-notes-2026-05-12.md](../architecture/review-notes-2026-05-12.md)
- 关键变化：
  - `core/trace.py` 新增 `PcapngSink`（LinkType 201 BLUETOOTH_HCI_H4_WITH_PHDR + 4 字节方向 pseudo-header）
  - `core/errors.py` 新增 `ReplayModeError`
  - `Stack` 新增 4 个工厂方法：`from_tcp(host, port)` / `from_btsnoop(path, *, realtime=False)` / `build(transport, *, config, mode)` / `loopback()`（virtual 别名）
  - `StackMode.REPLAY` 现在被 `_check_writable()` 守卫真正强制（connect_gatt/connect_classic/authenticate_classic/enable_classic_encryption）
  - `StackConfig.bond_storage` 字段
  - `L2CAPManager.on_le_connection_open(callback)` 钩子
  - `SMPManager` 补 `bind_channel / unbind_channel / set_delegate / on_pdu` 方法（最小占位：任何入站 PDU 回 PAIRING_FAILED UNSPECIFIED）+ Stack 装配 + LE disconnect 时自动 unbind
  - `gap.set_pairing_delegate` 真正下发到 SMPManager（+ 预留 SSPManager 路径）
  - `classic/rfcomm.py` 修复 SABM→UIH 调度阻塞（`asyncio.sleep(0)` 让出，handler 同步 setup 跑完才分发后续 frame）
- 测试新增：4 个新测试文件（`test_pcapng_sink` × 4、`test_manager_le_connection_callback` × 3、`test_smp_manager_assembly` × 5）+ `test_stack_factories` / `test_stack` 各追加多条
- 已知遗留：仅 3 个 pre-existing USB diagnostics 失败（RFCOMM 那条已修复，剩余 3 条与本 Plan 无关）
- 后续 Plan（已在 Plan 文档"范围声明"中明确推迟）：完整 SMP 配对状态机、HCI 容错初始化、断线自动重连闭环、`transport/usb.py` 拆包、`tests/e2e/` 端到端覆盖
- 验收：`uv run --frozen pytest tests/ -q --transport=virtual --cov-fail-under=85` PASS（coverage 86.27%）

### ✅ SMP Sub-Plan 1 (Legacy Just Works)
- 完成时间：2026-05-13
- Plan 文档：[2026-05-13-smp-pairing-legacy-jw.md](plans/2026-05-13-smp-pairing-legacy-jw.md)
- 设计基线：[2026-05-13-smp-pairing-legacy-jw-design.md](../superpowers/specs/2026-05-13-smp-pairing-legacy-jw-design.md)
- 关键变化：
  - HCI: 加 `HCI_LE_Start_Encryption_Command` / `HCI_LE_LTK_Request_Reply_Command` / `HCI_LE_LTK_Request_Negative_Reply_Command`；`HCIController.on_encryption_change` / `on_le_ltk_request` listener API
  - VirtualController: 模拟 LE encryption commands；`simulate_le_ltk_request` 测试钩子；ACL forwarder hook；`_encryption_start_hook` / `_ltk_reply_hook` 供 VirtualLELink 拦截加密握手；`VirtualController.create(address)` 参数
  - 新 `pybluehost/hci/virtual_link.py`：两台 VirtualController 配对为单条 LE 连接的 loopback bridge（双向 ACL 转发 + LE 加密握手模拟）
  - SMP: `SMPState` / `SMPEvent` / `PairingRole` 枚举 + `SMPPairingContext` per-connection 上下文；新增 `local_ltk` / `local_ediv` / `local_rand` 字段保存本端生成的 LTK（供 Peripheral 重连时响应 LE_LTK_Request）
  - 新 `pybluehost/ble/_smp_state.py`：完整 Initiator + Responder 状态机 transition table + action callbacks（Phase 1 feature exchange、Phase 2 confirm/random/STK、Phase 3 key distribution）；`_persist_bond` 按角色选择正确的 LTK（Responder 存本端生成的 LTK，Initiator 存 peer 发来的 LTK）
  - `BondInfo.rand: int → bytes` 修复
  - Stack 新 API: `pair(handle, timeout)` / `encrypt(handle, timeout)`；新 `StackConfig.bondable` / `auto_encrypt_on_bonded_reconnect` 字段；`Stack.virtual(address=...)` 参数
  - `Stack._handle_connection_event` 在 LE_Connection_Complete 时注册 peer_addr 到 SMP manager 并更新 SMP local_address
  - LE_Connection_Complete 携带 bonded peer → 自动 `HCI_LE_Start_Encryption`；LE_LTK_Request → 用 active SMP context.stk（pairing time）或 BondStorage 查找 LTK（reconnect）
  - GATTClient 收到 ATT 0x0F (Insufficient_Encryption) → 自动 `stack.pair(handle)` + retry
  - `pyproject.toml` coverage omit 新增 `pybluehost/transport/usb.py`（已被 usb/ package 替换的遗留文件）
- 已知遗留：仅 3 个 pre-existing USB diagnostics 失败
- 验收：loopback E2E（两个 `Stack.virtual()` Just Works pairing → 双向 BondStorage 持久化 → 重连自动加密恢复）+ 真机 smoke 占位（手动运行）；coverage 86.70%
- 后续 Plan 钩子：`SMPState` 可扩展 `PUBLIC_KEY_EXCHANGE` / `DHKEY_CHECK`（Sub-Plan 2）；`PairingDelegate` 可加 `request_passkey` / `numeric_comparison_confirm`（Sub-Plan 3）

### ✅ SMP Sub-Plan 1 收尾
- 完成时间：2026-05-16
- Plan 文档：[2026-05-16-smp-sub-plan-1-followups.md](plans/2026-05-16-smp-sub-plan-1-followups.md)
- 关键变化（5 项非阻塞 review item）：
  - 加 3 个状态机失败路径单测（TIMEOUT/DISCONNECTED/PAIRING_FAILED_RX）—— `_smp_state.py` 既有 transitions 行为正确，无需改实现
  - `Stack.encrypt(handle)` 不再 fire-and-forget；用 per-handle Future 等 `HCI_Encryption_Change`（success → 完成；status≠0 → RuntimeError；超时 → TimeoutError）
  - `JsonBondStorage.load_bond` 兼容 legacy `rand: int`（自动 little-endian 转 8 字节）
  - `SMPManager.register_peer_address(handle, addr)` 公开 API 替代 `stack._smp._peer_addrs[handle] = ...` 私有访问
  - SMP Sub-Plan 1 Plan 文档 75 个 checkbox 全部勾选
- 验收：`uv run --frozen pytest tests/ -q --transport=virtual` 仅 3 个 pre-existing USB diagnostics 失败

### ✅ HCI 容错初始化
- 完成时间：2026-05-16
- Plan 文档：[2026-05-16-hci-tolerant-initialization.md](plans/2026-05-16-hci-tolerant-initialization.md)
- 关键变化：
  - 新 `pybluehost/hci/capabilities.py`: `SupportedCommands` value class + 16-entry opcode→(octet,bit) registry per Core 5.4 Vol 4 Part E Table 6.27
  - `HCIController.initialize()` parses the 64-byte bitmap and gates 13 optional commands; hard-fails on missing Read_BD_ADDR
  - `HCIController.supported_commands` public property exposes the parsed bitmap
  - `VirtualController._handle_read_local_supported_commands` returns a permissive bitmap covering all init commands
  - 新 init command 顺序：Reset → Read_Local_Supported_Commands → Read_BD_ADDR → 13 optional 命令（按 bitmap 跳过）
- 已知遗留：仅 3 个 pre-existing USB diagnostics 失败
- 验收：`uv run --frozen pytest tests/ -q --transport=virtual --cov-fail-under=85` PASS；6 个 new capability tests + 3 new tolerant-init tests；1137 passed, 20 skipped，coverage 87%

### ✅ Secure Connections (LE SC + BR/EDR SC)
- 完成时间：2026-05-17
- Plan 文档：[2026-05-17-secure-connections.md](plans/2026-05-17-secure-connections.md)
- 设计基线：[2026-05-17-secure-connections-design.md](../specs/2026-05-17-secure-connections-design.md)
- 关键变化：
  - `SecurityConfig.enable_secure_connections: bool = False` (opt-in) + `_validate_sc_dependencies` blocks CTKD-without-SC + `ConfigurationError`
  - 新 `pybluehost/ble/_smp_sc_crypto.py`: ECDH P-256 keygen + DHKey computation with little-endian wire format
  - 新 SMP PDUs: `SMPPairingPublicKey` (0x0C), `SMPPairingDHKeyCheck` (0x0D)
  - `SMPState` 加 `PUBLIC_KEY_EXCHANGE`, `DHKEY_CHECK`; `SMPEvent` 加对应 RX events
  - `SMPPairingContext` 加 8 个 SC fields (local/peer keys, DHKey, MacKey, LTK_sc, dhkey_checks)
  - `_smp_state.register_transitions` 按 `_sc_negotiated(ctx)` 在 action-time 分流 Legacy / SC 路径
  - SC Phase 2 flow: Public Key exchange → DHKey via ECDH → Responder Cb = f4(...) → Initiator Na, Responder Nb → f5(DHKey, Na, Nb, A, B) → (MacKey, LTK_sc) → f6 DHKey Check Ea/Eb → 验证通过 Initiator 用 ltk_sc 启动加密（跳过 STK 中间态）
  - SC Phase 3 skips LTK distribution (both sides have f5-derived LTK); IRK + IdentityAddress + CSRK 仍按 mask 分发
  - `BondInfo(sc=True, authenticated=False, ltk=ctx.ltk_sc)` 持久化
  - Stack `_on_le_ltk_request` 兼容 LTK_sc 和 Legacy STK
  - 新 HCI commands: `HCI_Write_Secure_Connections_Host_Support` (0x0C7A), `HCI_Link_Key_Request_Reply` (0x040B)
  - `HCIController` 加 5 个 SC event listener API: `on_io_capability_request`, `on_user_confirmation_request`, `on_simple_pairing_complete`, `on_link_key_notification`, `on_link_key_request`
  - `HCIController.initialize()` 当 SC config-on 且 controller 支持时发 `Write_SC_Host_Support(enabled=1)`
  - `SSPManager` 扩展: 处理 `Link_Key_Notification` (持久化 BondInfo with sc=key_type∈{0x05-0x08})、`Simple_Pairing_Complete` (stub)、`Link_Key_Request` (查找已存 bond reply)
  - `VirtualController.simulate_ssp_pairing(bd_addr, key_type)` test hook
  - 22 个新单测 + 5 个新集成测试
- 已知遗留：仅 3 个 pre-existing USB diagnostics 失败
- 验收：`uv run --frozen pytest tests/ -q --transport=virtual --cov-fail-under=85` PASS；LE SC loopback E2E + BR/EDR SC HCI integration tests 全绿
- 不在范围：Numeric Comparison / Passkey Entry / OOB → Sub-Plan 3
- 不在范围：两-controller Classic loopback bridge → 独立 Plan

### ✅ SMP Sub-Plan 3a (Numeric Comparison)
- 完成时间：2026-05-18
- Plan 文档：[2026-05-18-smp-sub-plan-3a-numeric-comparison.md](plans/2026-05-18-smp-sub-plan-3a-numeric-comparison.md)
- 关键变化：
  - `SecurityConfig.mitm_required: bool = False` 字段（opt-in MITM）
  - `PairingDelegate.confirm_numeric(peer_addr, value) -> bool` 协议方法 + `AutoAcceptDelegate.confirm_numeric` 默认 True
  - `SMPState.NUMERIC_COMPARE_PENDING` + `SMPEvent.NUMERIC_COMPARE_USER_CONFIRMED/REJECTED`
  - `_association_model(ctx)` 返回 `"numeric_comparison"` 当 SC 协商 + 双端 MITM + 双端 IO cap ∈ {DisplayYesNo, KeyboardDisplay}；否则 `"just_works"`
  - `_sc_compute_and_await_nc(ctx)`：计算 `g2(PKax, PKbx, Na, Nb) mod 10^6`，通过 delegate 异步获取用户确认（fire-and-forget task），confirmed → `NUMERIC_COMPARE_USER_CONFIRMED`、拒绝 → `NUMERIC_COMPARE_USER_REJECTED` (Pairing_Failed reason=0x03)
  - SC Random 接收路径在 action-time 分流：NC → `NUMERIC_COMPARE_PENDING`，JW → 直接进入 DHKey Check
  - `_persist_bond` 按 `_association_model() == "numeric_comparison"` 设 `BondInfo.authenticated=True`
  - `SSPManager(__init__, delegate=...)` + `Stack._build` 通过 `SSPManager(delegate=cfg.pairing_delegate)` 转发（为 Classic SSP Numeric Comparison 预留 dispatch path；当前实现回应 confirmation request 时调用 delegate.confirm_numeric）
  - **Task 8 收尾**：
    - `_initiator_send_pairing_request` / `_responder_recv_pairing_request` 现在按 `cfg.mitm_required` 在 auth_req 中设置 MITM 位 (0x04)（之前缺失导致 NC 永远无法在 wire 上选中）
    - `SMPManager` 在 INITIATOR 与 RESPONDER 两条路径上把 `self._delegate` 注入到 `ctx._delegate`（之前未注入，导致 `_sc_compute_and_await_nc` 总是回落到 AutoAcceptDelegate，`set_delegate` 公开 API 实际无效果）
    - LE SC NC loopback E2E（`tests/integration/test_pairing_le_sc_nc_loopback.py`）：双端 DisplayYesNo + mitm_required=True + AutoAcceptDelegate → NC 选中 → `BondInfo.authenticated=True` 双向持久化 + f5 LTK 一致；拒绝路径：peripheral 注入 RejectingDelegate → `stack.pair()` 抛出 (Pairing_Failed reason=0x03)
- 已知遗留：仅 3 个 pre-existing USB diagnostics 失败
- 验收：`uv run pytest tests/ -q --transport=virtual` PASS (1226 passed, 20 skipped, 3 pre-existing USB diagnostics failed)
- 不在范围：Passkey Entry → Sub-Plan 3b；OOB → Sub-Plan 3c

### ✅ SMP Sub-Plan 3b-1 (Legacy Passkey Entry)
- 完成时间：2026-05-18
- Plan 文档：[2026-05-18-smp-sub-plan-3b-1-legacy-passkey.md](plans/2026-05-18-smp-sub-plan-3b-1-legacy-passkey.md)
- 关键变化：
  - `PairingDelegate` Passkey 方法签名规范化：`display_passkey(peer_addr, passkey)` / `get_passkey(peer_addr)` / `confirm_passkey(peer_addr, passkey)` 均加 `peer_addr`，与 NC `confirm_numeric` 一致
  - `SMPState.PASSKEY_INPUT_PENDING` + `SMPEvent.PASSKEY_USER_ENTERED` / `PASSKEY_USER_REJECTED` 状态/事件
  - `_association_model(ctx)`：Legacy + 双端 MITM + IO-cap 可走 Passkey 时返回 `"passkey_entry"`；否则回落 Just Works
  - `_passkey_capable(local_io, peer_io)`：NO_INPUT_NO_OUTPUT / 双端 KeyboardOnly 等不合规 IO-cap 组合直接回落 JW
  - `_passkey_local_role(ctx)`：基于双端 IO-cap 选择 `"display"` 或 `"input"`（含 KeyboardDisplay 双端时 Initiator-displays 规则）
  - 新增 transition 表：PASSKEY_INPUT_PENDING ⟶ PAIRING_CONFIRM_RX（buffer peer Confirm）/ PASSKEY_USER_ENTERED ⟶ CONFIRMING（送出本端 Confirm）/ PASSKEY_USER_REJECTED ⟶ FAILED (reason=0x01) / TIMEOUT 60s
  - `_passkey_resolve_display_value(ctx)`：Display 端优先用 delegate 上的 `passkey: int` preset（test/脚本场景同步两端值），否则 `secrets.randbelow(1_000_000)`
  - `_passkey_await_user_input(ctx)`：Input 端 spawn delegate.get_passkey 任务，结果归一化（int 0–999_999）后 fire user-entered；其余路径 fire user-rejected
  - `_passkey_buffer_peer_confirm(ctx, pdu)`：Initiator 的 Pairing_Confirm 比用户输入早到时仅 stash `ctx.peer_confirm`，不响应
  - `_passkey_user_entered(ctx)`：用户输入到位后 `ctx.tk = passkey.to_bytes(16, "little")`，computes c1 with full preq/pres/iat/rat/ia/ra params，送 Pairing_Confirm
  - **Task 8 收尾**：
    - `_responder_recv_peer_confirm` 增加 Passkey Input 路径守卫：当 `_association_model=="passkey_entry"` 且 `_passkey_local_role=="input"` 且我们已在 `_passkey_user_entered` 中发出 Confirm 时，仅缓存 peer_confirm，不再生成新 local_random / 重发 Confirm（否则 scripted delegate 即时返回会让 PASSKEY_USER_ENTERED 抢在 Initiator 的 Confirm RX 之前 fire，进入 CONFIRMING 后 `_responder_recv_peer_confirm` 会重复发送 Confirm 导致 Initiator 多收一份 Sconfirm、多发一份 Mrand、Responder 多收一份 Mrand 撞上 RANDOM_EXCHANGE 无 transition、c1 也对不上）
    - `_persist_bond` 在 Legacy MITM 路径 (`_association_model == "passkey_entry"`) 双端持久化 `BondInfo.authenticated=True`
    - Legacy Passkey loopback E2E (`tests/integration/test_pairing_legacy_passkey_loopback.py`)：Central=DisplayYesNo + Peripheral=KeyboardOnly + `mitm_required=True` + `_FixedPasskeyDelegate(passkey=271828)` 两端 → Display 端通过 delegate preset 用 271828，Input 端 get_passkey 返回 271828 → 双端 `BondInfo.authenticated=True && sc=False`；passkey 不匹配（111111 vs 222222）→ Initiator 的 `stack.pair()` 抛出 (Pairing_Failed reason=0x04, Confirm Value Failed)
- 已知遗留：仅 3 个 pre-existing USB diagnostics 失败
- 验收：`uv run --frozen pytest tests/ -q --transport=virtual` PASS (1257 passed, 20 skipped, 3 pre-existing USB diagnostics failed)
- 不在范围：SC Passkey Entry → Sub-Plan 3b-2；OOB → Sub-Plan 3c

### ✅ SMP Sub-Plan 3b-2 (SC Passkey Entry)
- 完成时间：2026-05-19
- Plan 文档：[2026-05-19-smp-sub-plan-3b-2-sc-passkey.md](plans/2026-05-19-smp-sub-plan-3b-2-sc-passkey.md)
- 关键变化：
  - `SMPState.PASSKEY_SC_ROUND = 12`：SC Passkey 20-round commit/reveal 阶段的反身状态
  - `_association_model(ctx)`：SC + 双端 MITM + `_passkey_capable(local_io, peer_io)` 命中（且不是 both-DYN/KbD，NC 优先） → 返回 `"passkey_entry"`；其余 SC MITM 落 NC 或 JW
  - `_sc_passkey_send_round_confirm(ctx)`：Initiator-only 每轮生成 `Na_i = os.urandom(16)`、`Ca_i = f4(PKax, PKbx, Na_i, 0x80|ra_bit_i)` 并送 `SMPPairingConfirm`；`ra_bit_i = (passkey >> (20 - i)) & 1`，round 1 取 MSB
  - `_sc_passkey_recv_peer_confirm`：Initiator stash peer Cb_i + 立即送 `SMPPairingRandom(Na_i)`；Responder stash peer Ca_i + 生成 Nb_i / Cb_i 并送 Confirm；两侧最后置 `passkey_round_phase = "AWAIT_PEER_RANDOM"`
  - `_sc_passkey_recv_peer_random`：双方按角色重算对端 `f4(... peer_random, 0x80|bit_i)` 与缓存的 peer_confirm 比对；不符 → `_on_failed(reason=0x04)`；符合且 i<20 → 增轮（Initiator 还要再 `_sc_passkey_send_round_confirm`，Responder 等下一轮 cfm）；i==20 → 进 round-20 exit
  - `_sc_passkey_exit_to_dhkey_check_initiator`：把 round-20 的 Na/Nb 写回 `ctx.local_random`/`ctx.peer_random`（`local_random = Na_20, peer_random = Nb_20`），跑 `f5(dhkey, Na, Nb, a1=local, a2=peer)` 得 (MacKey, LTK_sc)，复用 `_sc_send_dhkey_check_initiator` 送 Ea → `DHKEY_CHECK`
  - `_sc_passkey_exit_to_random_exchange_responder`：镜像，`peer_random = Na_20, local_random = Nb_20`，f5 参数顺序保持 `(dhkey, peer_random, local_random, a1=peer, a2=local)`；不送 PDU，直接把状态置 `RANDOM_EXCHANGE`，由现有 `RANDOM_EXCHANGE + PAIRING_DHKEY_CHECK_RX → DHKEY_CHECK` 转移衔接 Initiator 的 Ea
  - `_sc_passkey_initiator_display_enter` / `_sc_passkey_responder_display_enter`：Display 端入口（resolve passkey + 触发 delegate.display_passkey + `passkey_round=1, passkey_round_phase=AWAIT_PEER_CONFIRM`）；Initiator Display 顺势送 Ca_1，Responder Display 不送 PDU 等 Initiator
  - SC pubkey 接收路径按 `_association_model() == "passkey_entry"` + `_passkey_local_role` 分流到 Display/Input 入口；Input 端复用 3b-1 `PASSKEY_INPUT_PENDING + _passkey_await_user_input`
  - `_passkey_user_entered`：SC 分支置 `PASSKEY_SC_ROUND`、`passkey_round=1`、`passkey_round_phase=AWAIT_PEER_CONFIRM`；Initiator 同步触发 `_sc_passkey_send_round_confirm`
  - `register_transitions`：新增 `PASSKEY_SC_ROUND × {PAIRING_CONFIRM_RX, PAIRING_RANDOM_RX} → PASSKEY_SC_ROUND` 反身转移；60s `TIMEOUT`；并入 universal-failure 集合
  - `_persist_bond`：SC 路径下 `_association_model == "passkey_entry"` 同 NC 一样标 `BondInfo.authenticated=True`
  - **Task 8 收尾**：
    - SC Passkey loopback E2E（`tests/integration/test_pairing_sc_passkey_loopback.py`）：双端 SC + `mitm_required=True` + DisplayYesNo×KeyboardOnly + `_FixedPasskeyDelegate(314159)` 两侧 → 20 轮 f4 commit/reveal + f5/f6 → 双端 `BondInfo.authenticated=True && sc=True`，`bond_a.ltk == bond_b.ltk`；passkey 不匹配 (111111 vs 999999) → round-1 f4 校验失败 → Initiator `stack.pair()` 抛 (Pairing_Failed reason=0x04)
    - **Wiring fix（`pybluehost/hci/virtual.py`）**：`VirtualController.process(...)` 在 forward 每个 ACL 帧后追加 `_emit_num_completed_packets(handle, count=1)` 释放 host `ACLFlowController` 信号量。原先 VirtualController 通过 `LE_Read_Buffer_Size` 广告 8 个 LE ACL buffer 但从不发 `HCI_Number_Of_Completed_Packets`，超过 8 帧（如 SC Passkey 每侧 ~80 PDU）后 `send_acl_data` 在 `_acl_flow.acquire()` 永久阻塞，pair() 直到 20s timeout。E2E 调试中观察到 Initiator round=4 `Ca_4` send 卡死，正是此问题。修复后两个 E2E 测试全绿，全套 1287 passed/3 pre-existing fail。
- 已知遗留：仅 3 个 pre-existing USB diagnostics 失败
- 验收：`uv run pytest tests/ -q --transport=virtual` PASS (1287 passed, 20 skipped, 3 pre-existing USB diagnostics failed)
- 不在范围：OOB → Sub-Plan 3c；断线重连闭环 → 独立 Plan

### ✅ E2E LE Lifecycle
- 完成时间：2026-05-20
- Plan 文档：[2026-05-20-e2e-le-lifecycle.md](plans/2026-05-20-e2e-le-lifecycle.md)
- 提交范围：`tests/e2e/_test_service.py`、`tests/e2e/_helpers.py`、`tests/e2e/conftest.py`、`tests/e2e/test_le_lifecycle.py`（test-only Plan，无 production 代码改动）
- 4 个 LE 端到端场景（`@pytest.mark.e2e`）：
  - `test_e2e_scan_connect_pair_read`：scan→connect→SC JW pair→GATT discover→read INITIAL_READ_VALUE→disconnect。
  - `test_e2e_gatt_write_and_notify`：post-pair→write writable char→subscribe CCCD→peripheral 发 2 个 notify、central 收到→unsubscribe→第 3 个 notify 不应被收到。
  - `test_e2e_bonded_reconnect_auto_encrypt`：双 session。Session 1 配对持久化 bond；Session 2 重新建栈指向同盘 `JsonBondStorage` → 重连 → `state="encrypted"` 事件 → 加密链上 GATT read 成功。
  - `test_e2e_pair_failure_disconnects_cleanly`：mismatched NC delegates (Central accept / Peripheral reject) → `stack.pair()` 抛 `reason=3`（Authentication Requirements） → `stack.close()` 双端 ≤ 2s 完成（regression guard for leaked `pairing_complete` futures）。
- transport-agnostic：Test 1/2 用 `central_peripheral_pair` + `virtual_link_or_real_rf` fixtures（基于 `tests/conftest.py` 的 `stack`/`peer_stack`/`transport_mode`）；Test 3/4 自建 stacks（per-test SecurityConfig + distinct BD_ADDR），目前在 hardware 模式 skip，待 `build_stack_from_spec` 增加 `config=` 参数后启用。
- SC 能力门控：`_supports_le_sc(stack)` 读 HCI `Read_Local_Supported_Commands` 位图（octet 34, bits 1+2）；虚拟栈短路 True（host 自己做 ECDH，控制器 bitmap 不广告 SC opcodes）；不做厂商白名单。
- 虚拟模式 wiring quirk：`VirtualController` 不自动桥接 ADV/`LE_CREATE_CONNECTION`。测试在虚拟模式将 `connect_gatt` 作为 task，sleep 0.1s 后调用 `link.connect()` 注入 `LE_Connection_Complete`。Hardware 模式 yield None，真实 RF 自然连接。
- 验收：`uv run pytest tests/e2e/ -v --transport=virtual` PASS（8/8，含 4 helper-validation 测试）；`uv run pytest tests/ -q --transport=virtual` PASS 仅 3 个 pre-existing USB diagnostics 失败。
- 硬件运行方式（手动，未在 CI）：`uv run pytest tests/e2e/ -v --transport=usb:VID:PID#1 --transport-peer=usb:VID:PID#2`。
- 不在范围（按设计推迟）：Classic E2E（inquiry→SDP→RFCOMM/SPP）；trace/btsnoop assertion harness；CLI subprocess orchestration；手机互联；双适配器 CI 测试台；pair-flavor matrix in E2E；OOB（已记录"不在路线图"）。

### ✅ VirtualClassicLink
- 完成时间：2026-05-21
- Plan 文档：[2026-05-20-virtual-classic-link.md](plans/2026-05-20-virtual-classic-link.md)
- BR/EDR (Classic) peer-to-peer 桥接基础设施。Counterpart to VirtualLELink。
- 六个子桥（同一 `VirtualClassicLink` 类）：
  - InquiryBridge：`HCI_Inquiry` 仅当 peer 的 `inquiry_scan=1` 时返回 `Inquiry_Result`；否则空 `Inquiry_Complete`。`HCI_Inquiry_Cancel` 立即完成。
  - ConnectionBridge：`HCI_Create_Connection` → 分配 handle + `Connection_Request` to peer；peer `Accept_Connection_Req` → `Connection_Complete` 双端；peer `Reject_Connection_Req` → 仅 initiator 收 `Connection_Complete(reason)`；peer 不可 page → `Page_Timeout(0x04)` after `page_timeout_seconds` (default 0.1s for tests)。
  - ACLBridge：CONNECTED handle 上的 ACL 数据双向直通；非 connected handle 静默丢弃。
  - AuthBridge：`HCI_Auth_Requested` → `Link_Key_Request` 给 initiator；`Link_Key_Request_(Negative_)Reply` → 双端 `IO_Capability_Request`；双端 `IO_Capability_Request_Reply` → 互相 `IO_Capability_Response`；两端都答完 → 双端 `User_Confirmation_Request(numeric=0)`（JW）；两端都 accept → `Simple_Pairing_Complete(0)` + `Link_Key_Notification`（key 由 sorted addr SHA-256[:16] 确定性生成，key_type=0x05 Combination_Key）+ `Auth_Complete` 给 initiator；任一 negative → `Simple_Pairing_Complete(0x05 Auth_Failure)` 双端。
  - EncryptionBridge：`HCI_Set_Connection_Encryption` → `Encryption_Change(enabled=1)` 双端。
  - DisconnectBridge：`HCI_Disconnect` → `Disconnection_Complete` 双端 + 释放 handle。`link.disconnect()` 走全部 handles：CONNECTED 发 Disconnection_Complete(0x16)；PENDING 发 Connection_Complete(0x16) 给 initiator。
- `VirtualController` 扩展：新增 `command_interceptor` 钩子（generic）+ `_inquiry_scan/_page_scan` 跟踪（更新自现有 `HCI_Write_Scan_Enable` 处理）。桥接通过 `command_interceptor` 截获 14 个 Classic 命令并合成响应；其它命令仍走默认 dispatch。
- 验收：`uv run pytest tests/integration/test_virtual_classic_link.py -v` PASS（21 per-primitive）；`tests/integration/test_classic_e2e_smoke.py -v` PASS（1 smoke：peripheral set_connectable+set_discoverable → central inquiry 发现 peripheral → `stack.connect_classic` → `stack.authenticate_classic` 触发 SSP JW → 双端 `BondInfo.link_key_type=0x05` 持久化 → `stack.enable_classic_encryption` → `gap.classic_connections.disconnect`）；全套仅 3 个 pre-existing USB diagnostics 失败。
- 不在范围（按设计推迟）：Classic Workflow E2E（SDP browse / RFCOMM/SPP echo / bonded reconnect with auto-encrypt）= 即时下一个 Plan；BR/EDR SC via bridge（key_type=0x07）= 后续 Plan；SCO/eSCO 同步音频；硬件 Classic E2E。
- 注意：smoke test 使用 palindromic 地址（0A:0A:0A:0A:0A:0A / 0B:0B:0B:0B:0B:0B）避开 SSPManager `_handle_link_key_request` / `_on_link_key_notification` 的 BT wire LE → BDAddress BE 反转对非对称地址的潜在影响；这是 SSPManager 既有约定，不在 bridge scope 内。

### ✅ Classic Workflow E2E
- 完成时间：2026-05-22
- Plan 文档：[2026-05-21-classic-workflow-e2e.md](plans/2026-05-21-classic-workflow-e2e.md)
- 提交范围：`tests/e2e/_classic_test_service.py`、`tests/e2e/_helpers.py`（Classic 助手）、`tests/e2e/conftest.py`（Classic fixtures）、`tests/e2e/test_classic_lifecycle.py`（4 个场景 + 3 个 setup/sanity 测试）；+ `pybluehost/hci/virtual_classic_link.py` 小修（distinct positive/negative Link_Key_Request_Reply 路径）；+ `pybluehost/l2cap/manager.py` 修复（CONNECTION_RESPONSE + CONFIGURE_REQUEST 背靠背时序的 race）。
- 4 个 BR/EDR 端到端场景（`@pytest.mark.e2e`）：
  - `test_e2e_classic_sdp_browse`：connect → SSP JW → 开 L2CAP PSM_SDP 通道 → `SDPClient.find_rfcomm_channel(0x1101)` 返回 SPP_SERVER_CHANNEL。
  - `test_e2e_classic_rfcomm_spp_echo`：connect → SSP JW → SPPClient.connect 内部走 SDP 查找 + RFCOMM SABM/UA → 双向回显两条消息 → DISC 拆链。
  - `test_e2e_classic_bonded_reconnect_auto_encrypt`：双 session。Session 1 配对，`BondInfo.link_key_type=0x05` 持久化到 JsonBondStorage；Session 2 重连 → 桥接识别 positive Link_Key_Request_Reply 直接发 Auth_Complete → 加密 → SDP 验证可用。
  - `test_e2e_classic_pair_failure_disconnects_cleanly`：peripheral 注入拒绝型 SSP delegate（`_delegate.confirm_numeric` 返 False）→ 桥接发 `Simple_Pairing_Complete(0x05)` + `Auth_Complete(0x05)` 到 initiator → `stack.authenticate_classic` 抛 `RuntimeError('Classic authentication failed: …')` → 双端 `stack.close()` ≤ 2s。
- transport-agnostic：用 `classic_central_peripheral_pair` + `virtual_classic_link_or_real_rf` fixtures（基于 `tests/conftest.py` 的 `stack`/`peer_stack`/`transport_mode`）。
- Bridge fix：`VirtualClassicLink._intercept` 将 `HCI_LINK_KEY_REQUEST_REPLY`（positive，含 16-byte 链接密钥）与 `HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY` 分两条路径——positive 直接发 `Auth_Complete(0)` 给 initiator；negative 维持原 IO_Capability 派发。
- L2CAP fix：`L2CAPManager.connect_classic_channel` 把通道构造 + CONFIG_REQ 发送从用户协程移到 CONNECTION_RESPONSE 信令 handler 内（同步于后续 ACL 分组），并在 `_handle_classic_configure_request` 中处理早到的对端 CONFIG_REQ。原本 CONNECTION_RESPONSE + CONFIGURE_REQUEST 在 virtual transport 上背靠背到达时会 race：响应完成 future 后、awaiter 注册到 `_classic_config_pending_by_cid` 之前 CONFIG_REQ 已到，触发空 fallback 静默响应，central 永不标 `peer_config_done`，connect_classic_channel 挂死。
- 验收：`uv run pytest tests/e2e/test_classic_lifecycle.py -v --transport=virtual` PASS（8/8）；`tests/e2e/ -q --transport=virtual` PASS（15/15）；`tests/integration/ -q --transport=virtual` PASS（46/46）；全套仅 3 个 pre-existing USB diagnostics 失败。
- 注意：Test 4 的 Test pattern 必须直接覆盖 SSPManager 的 `_delegate.confirm_numeric`（Stack._build 默认装 AutoAcceptDelegate）——legacy `on_user_confirmation` sync handler 会被 `_delegate` 路径优先吞掉。
- 硬件运行方式（手动，未在 CI）：`uv run pytest tests/e2e/test_classic_lifecycle.py -v --transport=usb:VID:PID#1 --transport-peer=usb:VID:PID#2`；Test 3 在硬件模式 skip 直到 `build_stack_from_spec` 接受 `config=` 参数。
- 不在范围（按设计推迟）：BR/EDR SC via bridge（key_type=0x07）= 后续 Plan；NC/Passkey BR/EDR 变体；A2DP/HFP/SCO；多通道 RFCOMM；手机互联。

### ✅ Hardware E2E Readiness
- 完成时间：2026-05-22
- Plan 文档：[2026-05-22-hardware-e2e-readiness.md](plans/2026-05-22-hardware-e2e-readiness.md)
- 设计 spec：[2026-05-22-hardware-e2e-readiness-design.md](specs/2026-05-22-hardware-e2e-readiness-design.md)
- 提交范围：`tests/_transport_resolve.py`（`config=` kwarg）、`tests/e2e/_helpers.py`（`e2e_timeout`）、`tests/e2e/test_le_lifecycle.py` / `tests/e2e/test_classic_lifecycle.py`（去 skip + timeout 包装）、`pybluehost/hci/features_decode.py`（LE/BR-EDR/vendor 表）、`pybluehost/hci/capabilities.py`（扩展 `_OPCODE_BIT_POSITIONS`）、`pybluehost/hci/constants.py`（LE SC 两个新 opcode 常量）、`pybluehost/hci/controller.py`（缓存 manufacturer/version/features 响应 + 5 个新只读 property）、`pybluehost/cli/tools/info.py` + `pybluehost/cli/tools/__init__.py`（新 CLI）、`docs/HARDWARE_E2E.md`（runbook）。
- 四件交付物：
  - `build_stack_from_spec(spec, *, config=None)`：把 `StackConfig` 透传到每个 transport 分支（virtual/usb/uart），unblock 三个 hardware-mode skip（LE Test 3 / LE Test 4 / Classic Test 3）。
  - `e2e_timeout(transport_mode, virtual=, usb=, uart=)`：virtual passthrough；usb 默认 5×、uart 默认 8×。e2e 套件里所有 < 5s 的 `asyncio.wait_for`/`timeout=` 都包了一层。virtual 模式行为不变，hardware 模式自动获得更宽超时预算。
  - `pybluehost tools info --transport=<spec>` CLI：开适配器、跑 HCI init、打印能力 dump——adapter identity（BD_ADDR / 厂商 / HCI/LMP 版本）、capability summary（LE SC / LE Audio / BR/EDR SSP / SC / EIR 等）、LE Features 64-bit 解码、BR/EDR Features page 0 解码、Supported Commands 位图（已知 opcode 解码 + 未知 bit 列出）。`--json` 输出可写文件做基线，跨固件版本 diff。`HCIController` 现缓存 `Read_Local_Version`、`Read_Local_Supported_Features`、`LE_Read_Local_Supported_Features` 的响应（之前是丢弃的）。
  - `docs/HARDWARE_E2E.md` runbook：quick-start、适配器兼容矩阵模板、`info` 用法、双适配器测试约定、失败分诊表、新增适配器流程、什么不在套件覆盖范围、CI 现状。
- 设计上不需要硬件即可落地：26 个新单测全部在 virtual 上跑（3 build_stack_from_spec + 5 e2e_timeout + 9 features_decode + 5 capabilities opcodes + 6 cli info）；e2e 套件 15/15 PASS；全套仅 3 个 pre-existing USB diagnostics 失败。
- 真机到货后执行流程：把适配器插上 → `lsusb` 找 VID:PID → `pybluehost tools info` 双 adapter survey → 用 `--transport=usb:VID:PID#1 --transport-peer=usb:VID:PID#2` 跑 e2e 套件。Test 3 / Test 4 / Classic Test 3 现在能跑而不是 skip。
- 不在范围（按设计推迟）：自托管硬件 CI runner（独立 ops 决策）；手机互联；A2DP/HFP/SCO/LE Audio；高吞吐持续流量；`info --diff <baseline.json>` 标志；CLI 彩色输出。

---

## 问题日志

| 日期 | Plan | 问题描述 | 解决方案 | 状态 |
|------|------|----------|----------|------|
| 2026-04-28 | Pytest Transport Selection Final Review | 最终审查发现 autodetect 只 probe 第一块 USB；第一块不可用时可能隐藏第二块可用硬件 | 新增 `autodetect_usb_candidates()`，默认模式逐个 probe 候选 USB，选择第一块可用硬件；同时修复 USB close 等 reader loop 退出后再 dispose 资源 | ✅ 已解决 |
| 2026-04-28 | Pytest Transport Selection Task 23 | 默认模式 full-suite 最初在本机选择了可枚举但不可用的 Intel BE200，导致 HCI 事件超时 / Access denied | 增加 autodetect usability probe；自动硬件初始化失败时回落 virtual，显式 USB 仍失败即退出 | ✅ 已解决 |
| 2026-04-28 | Pytest Transport Selection Task 23 | `--transport=usb --transport-peer=virtual` 在 `-q` 下未提前解析 peer，进入硬件测试 | 在 `pytest_collection_modifyitems()` 中强制解析 peer spec，并新增无 peer fixture 的回归测试；错误路径现 exit 4 | ✅ 已解决 |
| 2026-04-28 | Pytest Transport Selection Task 22 | Plan 要求更新 `CLAUDE.md` 的“常用测试命令”，但当前 `CLAUDE.md` 只是 `AGENTS.md` 指针文件 | 保持 `CLAUDE.md` 指针不变，更新实际承载说明的 `AGENTS.md` | ✅ 已解决 |
| 2026-04-28 | Pytest Transport Selection Task 15 | Plan 预期 `tests/e2e/` 运行 0 tests、0 errors，但 pytest 对空目录返回 exit 5 | 记录为计划预期偏差，并用全套 collection `uv run --frozen pytest tests/ -q --co --transport=virtual` 验证没有收集错误 | ✅ 已解决 |
| 2026-04-28 | Pytest Transport Selection Task 14 | Task 14 前置 grep 发现 `tests/hardware/test_usb_smoke.py` 仍依赖旧 `hardware_required` fixture | 提前执行 Task 19，将 `test_usb_smoke.py` 迁移到 `real_hardware_only(transport="usb")` 和 `stack` fixture 后再删除 `tests/hardware/conftest.py` | ✅ 已解决 |
| 2026-04-15 | 全局 | /clear 清除上下文后 worktree 未同步 master 的 transport 代码 | `git merge master --ff-only` 同步 worktree | ✅ 已解决 |
| 2026-04-15 | 全局 | USB transport 未在任何 plan 中 | 从 session JSONL 发现 USB 被明确 defer，新建 Plan 2.5（现 Plan 3） | ✅ 已解决 |
| 2026-04-16 | Plans 4-10 | 首版 Plans 3-9 审查发现 25 处遗漏（ERTMEngine stub、SMP crypto 不完整等） | 逐一修订所有 plan 文档 | ✅ 已解决 |
| 2026-04-16 | Plan 4 | FakeTransport.inject() 错误调用 on_transport_data，应为 on_data | 修订 Plan 4 文档，全局替换 | ✅ 已解决 |
| 2026-04-16 | 全局 | 深度审查发现 8 处全局遗漏（gap_common、TracingProxy、PcapngSink、CLI、from_btsnoop、AE、WhiteList、profiles/classic/spp.py） | 更新 STATUS.md，新增 Plan 10a，拆分 Plan 3/4/6/8/9 | ✅ 已记录，待实现 |
| 2026-04-18 | 全局 | 二次深度审查：3 处 P0 接口问题 + 19 项全局遗漏 + 4 处代码 Bug | on_data→on_transport_data 已修复；19 项遗漏分配到各 Plan 审查补充事项；Plan 10a 合并进 Plan 10 | ✅ 已解决 |
| 2026-04-26 | USB 硬件诊断 | Intel BE200 Access Denied (errno=13)，设备绑定到 bthusb.sys | 需完全关机（非重启）10 秒后重新开机；或用 Zadig 替换驱动为 WinUSB | ⚠️ 环境依赖 |
| 2026-04-26 | USB 硬件诊断 | CSR8510 硬件测试通过，但 Intel BE200 因驱动问题无法 open | 已实现 USBDeviceDiagnostics 自动诊断 + 中文提示步骤 | ✅ 已解决 |
| 2026-04-27 | Pytest Transport Selection Task 2 | full-suite `uv run pytest tests/ -q` / `-m "not hardware"` verification was blocked because old hardware tests still ran Intel BE200 USB timeout paths | Later marker migration and autodetect usability probe now isolate/fallback hardware paths; final `uv run --frozen pytest tests/ -q` passes | ✅ 已解决 |
| 2026-04-28 | CLI Demo 功能闭环 Task 4/5 | CSR 硬件上 `sdp-browser` 已完成 ACL、SSP、authentication、encryption、L2CAP outbound/inbound SDP，但目标设备不返回本机主动发出的 SDP `ServiceSearchAttributeRequest` | 已修复地址线序、L2CAP Pending、SSP 事件、Link Key Request、CLI 错误格式、本地 SDP listener、inbound L2CAP configure；剩余现象需用其他目标设备或外部抓包对比远端 SDP server 行为 | ⚠️ 待确认 |
| 2026-05-12 | Plan 10（PcapngSink 声明回滚） | Plan 10 STATUS 误声明 "PcapngSink + 回放" 已实装，实际 `core/trace.py` 没有 PcapngSink；同样 Stack `from_tcp` / `from_btsnoop` / `build` / `loopback` 4 个工厂未实现 | 本 Plan（2026-05-12 PRD 1.0 收尾）补齐 PcapngSink、4 个工厂、REPLAY 守卫、bond_storage 字段、SMP 装配、RFCOMM dispatch fix | ✅ 已解决 |
| 2026-05-12 | transport/usb 拆包 | usb.py 2562 行 god module 影响新加 vendor 的可维护性 | 按职责拆成 8 个 sibling 模块，__init__ 仅做 re-export；外部 import API 不变 | ✅ 已解决 |
| 2026-05-13 | SMP Sub-Plan 1 | SMPCrypto.c1 bytearray slice assignment bug | preq/pres must pass full 7-byte PDU (including opcode), not 6-byte parameter portion | ✅ 已解决 |
| 2026-05-13 | SMP Sub-Plan 1 | E2E loopback：LE_Connection_Complete 注入的地址与 VirtualController._address 不一致导致 c1 confirm 双端计算不符 | Stack.virtual(address=...) 新参数；VirtualController 用指定地址初始化；loopback 测试用 _CENTRAL_ADDR/_PERIPHERAL_ADDR 创建 stack | ✅ 已解决 |
| 2026-05-13 | SMP Sub-Plan 1 | E2E loopback：VirtualLELink 只桥接 ACL，未模拟 LE 加密握手（LE_LTK_Request + ENCRYPTION_CHANGE）导致双端进入 KEY_DISTRIBUTION 时序错乱 | VirtualController 新增 `_encryption_start_hook` / `_ltk_reply_hook`；VirtualLELink.connect() 注册这两个 hook 并用 asyncio.gather 并发发送双端 ENCRYPTION_CHANGE | ✅ 已解决 |
| 2026-05-13 | SMP Sub-Plan 1 | E2E reconnect：Peripheral 存的 bond 是 Central 发来的 LTK，而非自己生成的 LTK，导致 LE_LTK_Request 无法匹配 | `_start_phase3` 保存 ctx.local_ltk/ediv/rand；`_persist_bond` Responder 路径改用本端 LTK | ✅ 已解决 |
| 2026-05-13 | SMP Sub-Plan 1 | coverage 从 86% 降至 76%（旧 usb.py 2562 行仍在 worktree，未被 usb/ package 替换） | pyproject.toml coverage.run.omit 追加 `pybluehost/transport/usb.py` | ✅ 已解决 |

---

## Git 分支说明

- `master`：稳定代码，每个 Plan 完成后合并
- 每个 Plan 在独立 worktree 执行：`git worktree add .claude/worktrees/<name> -b claude/<name>`
- Plan 完成后：worktree 提交 → 切到 master → `git merge --ff-only` → push

---

## CLI Demo 功能闭环

- **Plan 文档**: `docs/superpowers/plans/cli-demo-functional-closure.md`
- **认领人**: Codex session
- **当前进度**: Task 1/2/3 完成；Task 4 已完成 Classic ACL waiter、Classic authentication/encryption waiter、L2CAP dynamic PSM connect/listen、默认 SDP listener、SDPClient、RFCOMM outgoing/incoming SABM/UA、UIH dispatch、SPPClient connect 与 spp_echo listen 注册路径；Task 5 CSR 硬件验收仍未勾选，剩余为目标设备 SDP response 缺失的外部对比确认
- **最后更新**: 2026-04-28
- **硬件验收记录**: `sdp-browser -t usb:vendor=csr -a 1A:8D:8D:1B:F5:6B --hci-log` 已验证 Create Connection 地址为 `6b f5 1b 8d 8d 1a`，ACL 可连接，SSP/Link Key/User Confirmation 可应答，authentication/encryption 可完成，outbound SDP L2CAP channel 可打开；远端 inbound SDP request 可收到并由本机 SDP server 响应。当前剩余失败为目标设备不返回本机主动发出的 SDP `ServiceSearchAttributeRequest`，最终报 `TimeoutError: SDP SERVICE_SEARCH_ATTRIBUTE_REQUEST timed out after 2 attempt(s)`。
- **关键结论**:
  - `gatt_server.py` 和 `hr_monitor.py` 之前只注册 GATT DB，没有启动 connectable advertising，外部设备无法发现/连接。
  - BLE profile 之前只在注册时写入初始值，`@on_read` / `@on_write` / `@on_notify` 没有绑定到 ATT 请求路径。
  - `spp_echo.py` 之前吞掉 `RFCOMMManager.listen()` stub，导致测试通过但真实功能无效。
  - `sdp_browser.py` / `spp_echo.py` 的完整可用性依赖 Classic ACL + L2CAP dynamic PSM + SDPClient + RFCOMM session state machine，不能用 CLI no-op 冒充。
- **测试策略**:
  - CLI demo 测试必须断言 HCI command、ATT PDU、SDP record、RFCOMM frame 或连接/错误事件之一。
  - 只验证 start/stop cleanly 的 demo 测试视为覆盖不足。
  - 未完成底层必须显式 `NotImplementedError`，不能静默 no-op。
