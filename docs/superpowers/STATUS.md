# PyBlueHost — 项目任务状态

> **上下文恢复锚点**：读完此文件即可重建全部上下文，然后打开对应 Plan 文档从第一个 `- [ ]` 继续。

---

## 快速定位

**当前进行中**：Plan 2 遗漏项已补充完成，准备进入 Plan 3a  
**下一步**：读 [Plan 3a 文档](plans/plan3-usb-transport.md)（原 Plan 2.5，待拆分），从第一个未勾选步骤开始执行

> **注意（2026-04-16 深度审查后更新）**：
> - Plan 编号已重映射（2.5→3，3→4，…，旧 plan10 删除，新 plan10→11）
> - 原 Plans 3/5/6/8/9 建议拆分为更细粒度（详见下方）
> - 新增 Plan 10a（PcapngSink + Stack.from_btsnoop 回放模式）
> - Plan 1/2 有补充遗漏项，见各 Plan 文档末尾"补充遗漏项"章节

---

## Plan 总览

| 编号 | 名称 | 状态 | 文档 | 代码路径 |
|------|------|------|------|---------|
| Plan 1 | Core Infrastructure | ✅ 完成（有遗漏项待补） | [plan1](plans/plan1-core-infrastructure.md) | `pybluehost/core/` |
| Plan 2 | Transport Foundation | ✅ 完成（有遗漏项待补） | [plan2](plans/plan2-transport-foundation.md) | `pybluehost/transport/` |
| Plan 3a | USB Transport 核心 | ⬜ 待实现 | [plan3](plans/plan3-usb-transport.md)（拆分前） | `transport/usb.py`, `transport/hci_user_channel.py` |
| Plan 3b | 固件管理系统 | ⬜ 待实现 | 📝 待编写 | `transport/firmware/` |
| Plan 4a | HCI Packet Codec + Flow Control | ⬜ 待实现 | [plan4](plans/plan4-hci.md)（拆分前） | `hci/constants.py`, `hci/packets.py`, `hci/flow.py`, `hci/vendor/` |
| Plan 4b | HCI Controller + VirtualController | ⬜ 待实现 | 📝 待编写 | `hci/controller.py`, `hci/virtual.py` |
| Plan 5 | L2CAP Layer | ⬜ 待实现 | [plan5](plans/plan5-l2cap.md) | `pybluehost/l2cap/` |
| Plan 6a | ATT + GATT | ⬜ 待实现 | [plan6](plans/plan6-ble-stack.md)（拆分前） | `ble/att.py`, `ble/gatt.py` |
| Plan 6b | SMP + SecurityConfig | ⬜ 待实现 | 📝 待编写 | `ble/smp.py`, `ble/security.py` |
| Plan 7 | Classic Stack (SDP/RFCOMM/SPP) | ⬜ 待实现 | [plan7](plans/plan7-classic-stack.md) | `pybluehost/classic/` |
| Plan 8a | BLE GAP | ⬜ 待实现 | [plan8](plans/plan8-gap.md)（拆分前） | `ble/gap.py` |
| Plan 8b | Classic GAP + 统一 GAP 入口 | ⬜ 待实现 | 📝 待编写 | `classic/gap.py`, `pybluehost/gap.py` |
| Plan 9a | BLE Profile 框架 | ⬜ 待实现 | [plan9](plans/plan9-ble-profiles.md)（拆分前） | `profiles/ble/base.py`, `decorators.py`, `yaml_loader.py` |
| Plan 9b | 内置 BLE Profile 实现 | ⬜ 待实现 | 📝 待编写 | `profiles/ble/*.py`, `profiles/classic/spp.py` |
| Plan 10a | PcapngSink + Stack 回放模式 | ⬜ 待实现 | 📝 待编写（**新增**） | `core/trace.py`（PcapngSink）, `stack.py`（from_btsnoop/replay） |
| Plan 10 | Stack 工厂 + E2E 集成测试 | ⬜ 待实现 | [plan10](plans/plan10-stack-integration.md) | `pybluehost/stack.py` |
| Plan 11 | 测试基础设施 | ⬜ 待实现 | [plan11](plans/plan11-test-infrastructure.md) | `tests/fakes/`, `.github/workflows/` |

**总计：17 个 Plan（原 10 个 → 拆分 6 次 + 新增 1 个 = 17 个）**

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
                                                         Plan 10a ◄───────────┤
                                                              │               │
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

### ⬜ Plan 3a — USB Transport 核心
- 状态：待实现（文档需从原 plan3 文档拆分）
- 目标文件：`transport/usb.py`（ChipInfo/KNOWN_CHIPS/USBTransport/auto_detect/端点路由/WinUSB 验证）、`transport/hci_user_channel.py`
- 注意：`ReconnectConfig` 和 `on_transport_error` 已在 Plan 2 补充完成，无需再修改 base.py

### ⬜ Plan 3b — 固件管理系统
- 状态：待编写文档，可与 Plan 3a 并行
- 目标文件：`transport/firmware/__init__.py`、`transport/firmware/intel.py`、`transport/firmware/realtek.py`
- 包含：FirmwareManager（搜索+下载+完整性校验）、6 步 Intel 初始化序列、5 步 Realtek 初始化序列、CLI 工具（`pybluehost fw ...`）

### ⬜ Plan 4a — HCI Packet Codec + Flow Control
- 状态：待实现（文档需从原 plan4 文档拆分）
- 目标文件：`hci/constants.py`、`hci/packets.py`（全部 mandatory HCI packet + PacketRegistry）、`hci/flow.py`（CommandFlowController + ACLFlowController）、`hci/vendor/intel.py`、`hci/vendor/realtek.py`
- 特别注意：所有 mandatory HCI 命令/事件的完整 encode/decode 往返测试

### ⬜ Plan 4b — HCI Controller + VirtualController
- 状态：待编写文档，依赖 Plan 4a
- 目标文件：`hci/controller.py`（HCIController + EventRouter + ConnectionManager + 16 步初始化序列）、`hci/virtual.py`（VirtualController）
- 特别注意：HCI 初始化序列超时测试、Vendor event 路由、SCO 数据路由

### ⬜ Plan 5 — L2CAP Layer
- 状态：待实现
- 目标文件：`l2cap/constants.py`、`l2cap/sar.py`、`l2cap/channel.py`、`l2cap/ble.py`（含 Connection Parameter Update）、`l2cap/classic.py`（Basic/ERTM/Streaming 三种模式）、`l2cap/signaling.py`、`l2cap/manager.py`（含 LE 连接自动注册 ATT+SMP 固定信道）

### ⬜ Plan 6a — ATT + GATT
- 状态：待实现（文档需从原 plan6 文档拆分）
- 目标文件：`ble/att.py`（全部 opcode 0x01-0x1D、0x52、0xD2 + ATTBearer 客户端和服务端）、`ble/gatt.py`（AttributeDatabase + GATTServer + GATTClient + Service Changed indication）
- 特别注意：ATT MTU 协商测试、PrepareWrite/ExecuteWrite Long Attribute 测试

### ⬜ Plan 6b — SMP + SecurityConfig
- 状态：待编写文档，可与 Plan 6a 并行
- 目标文件：`ble/smp.py`（SMPManager + 9 个 SMP 加密函数含 Spec 测试向量 + BondStorage Protocol + JsonBondStorage + 全 IO Capability 矩阵 + OOB 配对）、`ble/security.py`（SecurityConfig + CTKDManager）
- 特别注意：c1/s1/f4/f5/f6/g2/ah/h6/h7 全部 9 个函数的 Spec 附录 D 测试向量

### ⬜ Plan 7 — Classic Stack
- 状态：待实现
- 目标文件：`classic/sdp.py`（DataElement + ServiceRecord + SDPServer + SDPClient + ServiceSearchAttribute）、`classic/rfcomm.py`（含 PN/MSC/RPN/RLS 全部控制命令）、`classic/spp.py`（协议层）

### ⬜ Plan 8a — BLE GAP
- 状态：待实现（文档需从原 plan8 文档拆分）
- 目标文件：`core/gap_common.py`（AdvertisingData、ClassOfDevice、Appearance、FilterPolicy、DeviceInfo）、`ble/gap.py`（BLEAdvertiser + **ExtendedAdvertiser/AE** + BLEScanner + BLEConnectionManager + PrivacyManager + **WhiteList**）

### ⬜ Plan 8b — Classic GAP + 统一 GAP 入口
- 状态：待编写文档，可与 Plan 8a 并行
- 目标文件：`classic/gap.py`（ClassicDiscovery + ClassicDiscoverability + ClassicConnectionManager + SSPManager + EIR）、`pybluehost/gap.py`（GAP 统一入口，含 set_pairing_delegate()）

### ⬜ Plan 9a — BLE Profile 框架
- 状态：待实现（文档需从原 plan9 文档拆分）
- 目标文件：`profiles/ble/base.py`、`profiles/ble/decorators.py`、`profiles/ble/yaml_loader.py`（含 validate 方法）、9 个服务 YAML 定义文件

### ⬜ Plan 9b — 内置 BLE Profile 实现 + Classic Profile 封装
- 状态：待编写文档，依赖 Plan 9a
- 目标文件：9 个 BLE Profile `.py`（GAPService/GATTService/DIS/BAS/HRS/BLS/HIDS/RSCS/CSCS）+ Client 类 + `profiles/classic/spp.py`（Profile 层封装）
- 包含：完整 E2E Loopback 测试（双角色 Server+Client 交互）

### ⬜ Plan 10a — PcapngSink + Stack 回放模式（新增）
- 状态：待编写文档（新增 Plan）
- 目标文件：`core/trace.py`（追加 `PcapngSink`）、`stack.py`（`Stack.from_btsnoop()`、`Stack.replay()`、`StackMode.REPLAY`、`ReplayModeError`）

### ⬜ Plan 10 — Stack 工厂 + E2E 集成测试
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

---

## Git 分支说明

- `master`：稳定代码，每个 Plan 完成后合并
- 每个 Plan 在独立 worktree 执行：`git worktree add .claude/worktrees/<name> -b claude/<name>`
- Plan 完成后：worktree 提交 → 切到 master → `git merge --ff-only` → push
