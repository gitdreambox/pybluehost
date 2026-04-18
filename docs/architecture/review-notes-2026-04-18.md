# PyBlueHost Plan 文档深度审查报告

**审查日期**：2026-04-18
**审查范围**：PRD v0.1、14 篇架构文档、11 篇 Plan 文档（Plan 1-2 已实现）

---

## 一、严重接口问题（P0 — 必须在下个 Plan 执行前修复）

### 1. TransportSink.on_data vs on_transport_data 命名不一致

| 文件/文档 | 使用的名称 | 来源 |
|-----------|-----------|------|
| 架构 02-sap.md §2.2 | `on_transport_data` | 规范定义 |
| 实现 transport/base.py:14 | `on_data` | Plan 2 实现 |
| 所有 5 个 Transport 实现 | `self._sink.on_data(packet)` | Plan 2 实现 |
| Plan 4 HCI 文档 | `on_transport_data` | 按架构文档 |
| Plan 11 FakeTransport | `on_transport_data` | 按架构文档 |

**影响**：Plan 4 (HCI) 实现时 HCIController 需实现 TransportSink，如按架构文档实现 `on_transport_data`，与 Transport 实际调用的 `on_data` 不兼容。

**建议**：统一为 `on_transport_data`，修改 base.py Protocol 和所有 Transport 实现。

### 2. Plan 10 使用不存在的 LoopbackTransport 构造器

Plan 10 代码：`LoopbackTransport(virtual_controller=vc)`
实际实现：`LoopbackTransport()` + `LoopbackTransport.pair()`

### 3. Plan 11 NullTrace API 与 TraceSystem 不匹配

Plan 11 NullTrace 有 `log_hci_command`, `log_hci_event`, `log_acl`
实际 TraceSystem API 是 `emit(TraceEvent)`, `add_sink()`, `start()`/`stop()`

---

## 二、19 项全局遗漏清单

| # | 遗漏功能 | 来源 | 建议归属 |
|---|---------|------|---------|
| 1 | TracingProxy 类 | arch 04-trace.md §4.5 | 新建 Plan 1.5 |
| 2 | core/gap_common.py（AdvertisingData 等）| arch 01-layering.md §1.2, 11-gap.md §11.2 | 新建 Plan 1.5 |
| 3 | CLI 工具 `pybluehost fw ...` | arch 06-transport.md §6.4 | 新建 Plan 3c 或并入 Plan 3 |
| 4 | HCI ISO Data 解析 | PRD §5.2, arch 07-hci.md §7.3 | 并入 Plan 4a |
| 5 | SCO 数据路由测试 | arch 07-hci.md §7.4 | 并入 Plan 4a/4b |
| 6 | Vendor 子包(intel/realtek)测试 | arch 07-hci.md | 并入 Plan 4a |
| 7 | L2CAP Streaming Mode | PRD §5.3, arch 08-l2cap.md §8.8 | 并入 Plan 5 |
| 8 | L2CAP Connection Parameter Update | arch 08-l2cap.md §8.9 | 并入 Plan 5 |
| 9 | L2CAPManager 自动注册 ATT+SMP 固定信道 | arch 08-l2cap.md §8.5 | 并入 Plan 5 |
| 10 | GATT Service Changed indication | PRD §5.4, arch 09-ble-stack.md §9.3 | 并入 Plan 6a |
| 11 | GATT Client Discovery 完整流程测试 | arch 09-ble-stack.md §9.3 | 并入 Plan 6a |
| 12 | SMP IO Capability 25 种组合矩阵测试 | arch 09-ble-stack.md §9.4 | 并入 Plan 6b |
| 13 | SecurityConfig + CTKDManager | arch 09-ble-stack.md §9.4 | 并入 Plan 6b |
| 14 | RFCOMM RPN/RLS 控制命令 | arch 10-classic-stack.md §10.3 | 并入 Plan 7 |
| 15 | Extended Advertising (AE) | PRD §5.6, arch 11-gap.md §11.3 | 并入 Plan 8a |
| 16 | WhiteList / 过滤策略 | PRD §5.6, arch 11-gap.md §11.5 | 并入 Plan 8a/8b |
| 17 | ServiceYAMLLoader.validate() | arch 12-ble-profiles.md §12.4 | 并入 Plan 9a |
| 18 | Stack.build() 公开工厂方法 | PRD §5.7, arch 13-stack-api.md §13.3 | 并入 Plan 10 |
| 19 | 覆盖率逐模块门槛配置 | arch 14-testing.md §14.6 | 并入 Plan 11 |

---

## 三、代码片段 Bug

1. **Plan 5 ERTMEngine 序列号 wraparound**：`s < req_seq or (req_seq < 32 and s > 32)` 不正确，应用模运算
2. **Plan 6 SMP c1 测试**：只检查 `len(result) == 16`，应对比 Spec 附录精确值
3. **Plan 6 SMP f5 测试**：`A2 = bytes.fromhex("00a713702dcfc1")[:6]` 截断逻辑未说明
4. **Plan 4 HCI_LE_Meta_Event**：struct.pack 格式串中 `6s` vs `BBBBBB` 需确认

---

## 四、拆分/合并建议

- **合并** Plan 10a → Plan 10（文件集重叠：core/trace.py + stack.py）
- **确认拆分** Plan 3 → 3a + 3b（STATUS.md 已标注但文档未拆）
- **新增** Plan 1.5（core 补丁：gap_common + TracingProxy）

---

## 五、建议 Plan 列表与优先级

| 优先级 | Plan | 名称 | 关键路径 |
|--------|------|------|---------|
| P0 | 接口修复 | on_data → on_transport_data | 是 |
| P0 | Plan 1.5 | Core 补丁 (gap_common + TracingProxy) | 是 |
| P0 | Plan 3 | USB Transport + Firmware | 是 |
| P0 | Plan 4a | HCI Packet Codec + Flow Control | 是 |
| P0 | Plan 4b | HCI Controller + VirtualController | 是 |
| P1 | Plan 5 | L2CAP (+Streaming, +ConnParam) | 是 |
| P1 | Plan 6a | ATT + GATT (+Service Changed) | 是 |
| P1 | Plan 6b | SMP + Security + CTKD | 并行 |
| P1 | Plan 7 | Classic (SDP/RFCOMM/SPP +RPN/RLS) | 并行 |
| P2 | Plan 8a | BLE GAP (+AE +WhiteList +Privacy) | 是 |
| P2 | Plan 8b | Classic GAP + 统一 GAP | 并行 |
| P2 | Plan 9a | Profile 框架 (+validate) | 是 |
| P2 | Plan 9b | 内置 Profile + Classic SPP Profile | 是 |
| P3 | Plan 10 | Stack 工厂 + PcapngSink + E2E | 是 |
| P3 | Plan 11 | 测试基础设施 + CI | 是 |
