# PyBlueHost — 项目任务状态

> **上下文恢复锚点**：读完此文件即可重建全部上下文，然后打开对应 Plan 文档从第一个 `- [ ]` 继续。

---

## 快速定位

**当前进行中**：Plan 7 已完成（2026-04-21），491 tests all pass  
**下一步**：读 [Plan 8a 文档](plans/plan8a-ble-gap.md)，从第一个未勾选步骤开始执行

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
| Plan 8a | BLE GAP | ⬜ 待实现 | [plan8a](plans/plan8a-ble-gap.md) | `core/gap_common.py`, `ble/gap.py` |
| Plan 8b | Classic GAP + 统一 GAP 入口 | ⬜ 待实现 | [plan8b](plans/plan8b-classic-gap.md) | `classic/gap.py`, `pybluehost/gap.py` |
| Plan 9a | BLE Profile 框架 | ⬜ 待实现 | [plan9a](plans/plan9a-profile-framework.md) | `profiles/ble/base.py`, `decorators.py`, `yaml_loader.py` |
| Plan 9b | 内置 BLE Profile 实现 | ⬜ 待实现 | [plan9b](plans/plan9b-builtin-profiles.md) | `profiles/ble/*.py`, `profiles/classic/spp.py` |
| Plan 10 | Stack 工厂 + PcapngSink + 回放 + E2E | ⬜ 待实现 | [plan10](plans/plan10-stack-integration.md) | `pybluehost/stack.py`, `core/trace.py` |
| Plan 11 | 测试基础设施 | ⬜ 待实现 | [plan11](plans/plan11-test-infrastructure.md) | `tests/fakes/`, `.github/workflows/` |

**总计：16 个 Plan（原 10 个 → 拆分 6 次 = 16 个，Plan 10a 已合并进 Plan 10）**

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

### ⬜ Plan 8a — BLE GAP
- 状态：待实现，文档已就绪 → [plan8a-ble-gap.md](plans/plan8a-ble-gap.md)
- 目标文件：`core/gap_common.py`（AdvertisingData、ClassOfDevice、Appearance、FilterPolicy、DeviceInfo）、`ble/gap.py`（BLEAdvertiser + **ExtendedAdvertiser/AE** + BLEScanner + BLEConnectionManager + PrivacyManager + **WhiteList**）

### ⬜ Plan 8b — Classic GAP + 统一 GAP 入口
- 状态：待实现，文档已就绪 → [plan8b-classic-gap.md](plans/plan8b-classic-gap.md)，可与 Plan 8a 并行
- 目标文件：`classic/gap.py`（ClassicDiscovery + ClassicDiscoverability + ClassicConnectionManager + SSPManager + EIR）、`pybluehost/gap.py`（GAP 统一入口，含 set_pairing_delegate()）

### ⬜ Plan 9a — BLE Profile 框架
- 状态：待实现，文档已就绪 → [plan9a-profile-framework.md](plans/plan9a-profile-framework.md)
- 目标文件：`profiles/ble/base.py`、`profiles/ble/decorators.py`、`profiles/ble/yaml_loader.py`（含 validate 方法）、9 个服务 YAML 定义文件

### ⬜ Plan 9b — 内置 BLE Profile 实现 + Classic Profile 封装
- 状态：待实现，文档已就绪 → [plan9b-builtin-profiles.md](plans/plan9b-builtin-profiles.md)，依赖 Plan 9a
- 目标文件：9 个 BLE Profile `.py`（GAPService/GATTService/DIS/BAS/HRS/BLS/HIDS/RSCS/CSCS）+ Client 类 + `profiles/classic/spp.py`（Profile 层封装）
- 包含：完整 E2E Loopback 测试（双角色 Server+Client 交互）

### ⬜ Plan 10 — Stack 工厂 + PcapngSink + 回放 + E2E 集成测试（含原 Plan 10a）
- 状态：待实现
- 目标文件：`pybluehost/stack.py`（全部工厂方法含 `from_btsnoop()`/`build()`/`power_on()`/`power_off()`、断线重连后 HCI 重初始化、`sig_db` 属性）、`pybluehost/__init__.py`
- 包含：E2E Loopback 测试（BLE GATT read/write/notify + SMP 配对 + SPP）

### ⬜ Plan 11 — 测试基础设施
- 状态：待实现
- 目标文件：`tests/fakes/`（FakeTransport/FakeHCIDownstream/FakeChannelEvents/NullTrace）、`BtsnoopTestData`、`tests/data/`（4 个 btsnoop 文件）、全局 conftest、CI 工作流、覆盖率逐模块门槛配置、hardware/conftest.py fixtures

---

## 问题日志

| 日期 | Plan | 问题描述 | 解决方案 | 状态 |
|------|------|----------|----------|------|
| 2026-04-15 | 全局 | /clear 清除上下文后 worktree 未同步 master 的 transport 代码 | `git merge master --ff-only` 同步 worktree | ✅ 已解决 |
| 2026-04-15 | 全局 | USB transport 未在任何 plan 中 | 从 session JSONL 发现 USB 被明确 defer，新建 Plan 2.5（现 Plan 3） | ✅ 已解决 |
| 2026-04-16 | Plans 4-10 | 首版 Plans 3-9 审查发现 25 处遗漏（ERTMEngine stub、SMP crypto 不完整等） | 逐一修订所有 plan 文档 | ✅ 已解决 |
| 2026-04-16 | Plan 4 | FakeTransport.inject() 错误调用 on_transport_data，应为 on_data | 修订 Plan 4 文档，全局替换 | ✅ 已解决 |
| 2026-04-16 | 全局 | 深度审查发现 8 处全局遗漏（gap_common、TracingProxy、PcapngSink、CLI、from_btsnoop、AE、WhiteList、profiles/classic/spp.py） | 更新 STATUS.md，新增 Plan 10a，拆分 Plan 3/4/6/8/9 | ✅ 已记录，待实现 |
| 2026-04-18 | 全局 | 二次深度审查：3 处 P0 接口问题 + 19 项全局遗漏 + 4 处代码 Bug | on_data→on_transport_data 已修复；19 项遗漏分配到各 Plan 审查补充事项；Plan 10a 合并进 Plan 10 | ✅ 已解决 |

---

## Git 分支说明

- `master`：稳定代码，每个 Plan 完成后合并
- 每个 Plan 在独立 worktree 执行：`git worktree add .claude/worktrees/<name> -b claude/<name>`
- Plan 完成后：worktree 提交 → 切到 master → `git merge --ff-only` → push
