# PyBlueHost PRD 1.0 验收 + 代码 Review 报告

**审查日期**：2026-05-12
**审查范围**：PRD v0.1、`pybluehost/` 全部 97 个源文件（~16.5K LoC）、133 个测试文件
**测试基线**：`uv run --frozen pytest tests/ -q --transport=virtual`
  - 836 passed / 4 failed / sssss skipped；coverage 86.32%（STATUS 记录值）
  - 4 个 pre-existing 失败（rfcomm dispatch × 1 + usb diagnostics × 3）

---

## 摘要

实现层质量高（826+ 测试、86% 覆盖率、完整 Trace/Logging、9 个 Profile、3 个 USB 厂商子类），但 **PRD 1.0 在 8 个"已声明完成"项上存在可验证缺口**，其中最严重的两条会直接打破 PRD §9 的验收指标：

1. **SMP 未被 Stack 装配**（P0 功能闭环）—— 528 行 SMPManager 代码"漂浮"在 `ble/smp.py`，`Stack._build` 完全不构造它，BLE 配对走不通。
2. **PcapngSink 缺失 + Stack 回放/TCP/build/loopback 工厂缺失** —— 直接打破 PRD §9 "Wireshark 可打开 pcapng" / "btsnoop 文件回放复现场景" 两个验收指标。

建议把"PRD 1.0 收尾"独立成一个 Plan，先做下方"立即可做"5 项，再决定中期重构节奏。

---

## 一、PRD 验收（功能完成度）

### ✅ 已完成且符合 PRD
| 范围 | 证据 |
|------|------|
| Transport: UART/USB/TCP/UDP/btsnoop/hci_user_channel | `pybluehost/transport/__init__.py` |
| HCI: Command/Event/ACL/SCO/ISO framing + VirtualController + Intel/Realtek vendor | `hci/packets.py`、`hci/virtual.py` |
| L2CAP: BLE fixed + LE CoC + Classic ERTM/Streaming + SAR | `l2cap/` |
| BLE: ATT 28 opcodes、GATT、SMP 14 opcodes + crypto + JsonBondStorage、9 Profile | `ble/`, `profiles/ble/` |
| Classic: SDP/RFCOMM/SPP | `classic/` |
| GAP: BLE + Classic + 统一 `pybluehost.gap.GAP` | `gap.py` |
| 状态机框架、Trace 系统、结构化彩色日志 | `core/statemachine.py`, `core/trace.py`, `core/trace_console.py` |
| CLI: 8 个 `app` + 4 个 `tools` 命名空间 | `cli/app/`, `cli/tools/` |

### ⚠️ PRD 要求但未完成 / 未对齐

| # | PRD 条目 | 现状 | 影响 |
|---|---------|------|------|
| 1 | `Stack.from_tcp / from_btsnoop / build / loopback`（PRD §5.7） | 仅 `from_usb / from_uart / virtual` 三个工厂（`stack.py:205, 238, 258`）。`TCPTransport`、`BtsnoopTransport` 已存在但无 Stack 入口 | PRD §3 P1 + §9 "btsnoop 文件回放复现场景" 走不通 |
| 2 | `StackMode.REPLAY` 语义（review-notes-rsp #5 接受方案） | 枚举存在（`stack.py:22`），无路径会赋值；写操作无 `ReplayModeError` | 模式声明形同虚设 |
| 3 | PcapngSink（PRD §5.7） | `core/trace.py` 只有 `BtsnoopSink / JsonSink / RingBufferSink / CallbackSink` + `ConsoleSink`；**无 PcapngSink** | STATUS Plan 10 声称"PcapngSink + 回放"已合并实为未合并；PRD §9 "Wireshark 可打开 pcapng" 失败 |
| 4 | **SMP 未被 Stack 装配（P0）** | `Stack._build` 装配 HCI/L2CAP/GATT/SDP/RFCOMM/GAP；**完全不构造 `SMPManager`**；L2CAP 注册了 `CID_SMP` FixedChannel（`l2cap/manager.py:142`）但无 handler 绑定；`GAP.set_pairing_delegate()`（`gap.py:99-105`）只把 delegate 存到字段，从不下发 | BLE 配对在 Stack API 层不可达 |
| 5 | 断线自动重连（PRD §5.1）| `ReconnectConfig` / `ReconnectPolicy` 在 `transport/base.py:27-38` 定义，`Transport.reset()` 是 `close+open`；但**无调用方**：HCI/Stack 不监听 `on_transport_error`、不调度重连、不重跑 init 序列 | 重连策略形同虚设 |
| 6 | Bond 持久化可插拔（PRD §5.4） | `JsonBondStorage` 已实现，但 `StackConfig` 无 `bond_storage` 字段 | 用户端到端绑定保存不可达 |
| 7 | `Stack.loopback()` 命名（PRD §5.7 + §9） | 改名为 `Stack.virtual()`（pytest-transport-selection 决议） | 与 PRD/示例直接冲突；要么改回 `loopback`，要么改 PRD |
| 8 | CLI `bridge` 命令 | `cli/app/bridge.py`（TCP/UDP H4 桥接）已实现，**不在 PRD §5.8 命令清单** | 文档缺失；进 PRD 或标 experimental |

### 已知失败测试（必须修掉才能发 1.0）
| 测试 | 性质 |
|------|------|
| `tests/unit/classic/test_rfcomm.py::test_rfcomm_inbound_handler_does_not_block_future_frames` | **真实 bug** — RFCOMM dispatch loop 在 inbound handler 内同步 await，会阻塞后续 frame |
| `tests/unit/cli/tools/test_usb_diagnostics.py::TestCmdUSBDiagnose::test_device_bthusb_driver` | USB 诊断 stub 路径 |
| `tests/unit/cli/tools/test_usb_diagnostics.py::TestCmdUSBDiagnose::test_device_access_denied` | 同上 |
| `tests/unit/transport/test_usb.py::TestUSBTransportDiagnostics::test_open_access_denied_raises_diagnostic_error` | 同上 |

---

## 二、架构与代码质量

### P0（影响功能正确性）

1. **Stack 14 个属性全是 `Any`**（`stack.py:73-90`），同时内部访问 `self._l2cap._connections`（`stack.py:322`）—— 破坏了 PRD §4 "层间仅通过 SAP 接口耦合" 与 review-notes-rsp #7 "共享类型统一归属" 的核心原则。
2. **每事件重扫所有 L2CAP 信道**：`_attach_gatt_server_to_att_channels` 被 `_on_hci_event` 和 `_on_acl_data` 双重调用（`stack.py:283, 299`），每条 HCI event / ACL frame 都遍历所有连接。应改成 L2CAP 在 LE 连接建立时事件回调。
3. **RFCOMM dispatch loop 阻塞**：上文已述，handler 内同步 `await` 卡住后续 frame。改 `asyncio.create_task` 分发。
4. **`btsnoop.py:55-56`**：`except (asyncio.CancelledError, Exception): pass` 把 replay 解析错误也吞掉。

### P1（影响维护性）

1. **`pybluehost/transport/usb.py` 2562 行 god module**
   - 内容：USBTransport base + Intel(800 行，含 `_BootParams` 嵌套 dataclass) + Realtek(470 行) + CSR + USBDeviceDiagnostics(200+ 行) + 14 个模块级 helper + 8 处 `except Exception` 静吞
   - 建议拆为 package: `transport/usb/{__init__, base, discovery, diagnostics, intel, realtek, csr}.py`
2. **`Stack._build` 24 处内联 import**（`stack.py:102-124, 306-308, 488-491`）—— 循环依赖压力的症状，应顶层 import + `TYPE_CHECKING`。
3. **`HCIController.initialize()` 16 步硬编码**：不读 `Read_Local_Supported_Commands` bitmap；spec 子集 controller 直接挂。
4. **错误处理过宽**：源代码区 19 处 `except Exception`（USB 7 处 silent），多无 `logger.exception`。
5. **3 个 stub 路径影响 SPP/RFCOMM 端到端**：`classic/rfcomm.py:207,358,371,402,413` 与 `classic/spp.py:107,109` 全部抛 `NotImplementedError`。配合 STATUS "CLI Demo 功能闭环 Task 5 未通过"，说明 RFCOMM 经由 L2CAP dynamic PSM 的真实路径未接好。

### P2（一致性 / 演化）

1. `_emit_connection_event` handler 同步调用 + 无 try/except（`stack.py:462-464`），单个第三方 handler 抛错终止后续。
2. `Stack.virtual()` vs `Stack.loopback()` 命名分歧与 PRD 不一致。
3. `hci/packets.py` 776 行手写 struct.pack，每个 command/event 一个 dataclass。v1.1 PTS 要新增 30+ 命令时维护成本上升，但当前不紧迫。
4. `tests/e2e/` 目录为空（STATUS Task 15 注释 exit 5）—— 与 PRD §9 端到端验收脱节。

---

## 三、优化重构建议（按 ROI 排序）

### 立即可做（每项 ≤ 1 PR，建议合并成一个 "PRD 1.0 收尾" Plan）

1. **补 Stack 工厂**：实现
   - `Stack.from_tcp(host, port, *, config=None)`
   - `Stack.from_btsnoop(path, *, realtime=False, config=None)` —— 设置 `_mode = StackMode.REPLAY`
   - `Stack.build(transport, *, config=None, mode=StackMode.LIVE)` —— 暴露内部 `_build`
   - `Stack.loopback()` —— `virtual()` 的别名（修复 PRD 命名分歧）
   - 在 GAP/L2CAP 写路径前置 `ReplayModeError` 守卫
2. **加 `PcapngSink`**：参考 `BtsnoopSink`（`core/trace.py:185-228`），写 pcapng v1 EPB；导出到 `pybluehost.core`。
3. **装配 SMP（P0 闭环）**：
   - `Stack._build` 实例化 `SMPManager(security=cfg.security, bond_storage=cfg.bond_storage, delegate=...)`
   - 让 `L2CAPManager` 在 LE 连接建立时把 `CID_SMP` FixedChannel `.set_events()` 绑定到 SMPManager 的 PDU 处理
   - `GAP.set_pairing_delegate()` 真正下发到 SMPManager + SSPManager
4. **`StackConfig.bond_storage` 字段**：让用户能注入 `JsonBondStorage(path)` 或自定义实现。
5. **修 RFCOMM dispatch 死锁**：handler 路径改 `asyncio.create_task`，加并发 frame 单测断言。

### 中期重构（每项 1 个 Plan）

1. **L2CAP 事件回调**：`L2CAPManager` 在 LE/Classic 连接建立时发 `on_le_connection_open(handle, channels)` / `on_classic_connection_open(...)` 事件；移除 Stack 的轮询重扫。
2. **断线重连闭环**：HCIController 监听 `Transport.on_transport_error` → 按 `ReconnectConfig` 调度 → `transport.reset()` → 重跑 `initialize()` → 对上层广播 `StackConnectionEvent(state="recovered"|"failed")`；把 `ReconnectConfig` 提到 `StackConfig`。
3. **Stack 类型化**：把 14 个 `Any` 改成具体类或 Protocol；用 `TYPE_CHECKING` 解循环。
4. **拆 `transport/usb.py`**：转 package，保留 backward shim。
5. **HCI 容错初始化**：`initialize()` 读 `Read_Local_Supported_Commands` bitmap，缺命令则 skip + 记录 `controller_capabilities` 字段。

### 长期（按需触发）

1. **声明式 HCI codec DSL**：仅当 v1.1 PTS test plan 要新增 30+ 命令时再做。
2. **GAP 显式状态机化**：BLEConnectionManager / ClassicConnectionManager 移到 `core/statemachine.py`，对齐 PRD §5.7 "显式 StateMachine[S,E]" 原则。
3. **`TraceEvent.decoded` 类型收紧**：从 `object | None` 收成 `Decodable` Protocol，sink 端不必 `hasattr/isinstance`。

---

## 四、CI / 测试缺口

1. **4 个 pre-existing failure 在 v1.0 release 前必须清掉**，特别是 RFCOMM dispatch 那条是真实 bug。
2. **`tests/e2e/` 为空**，与 PRD §9 端到端指标脱节。建议至少补：
   - loopback 全栈 BLE GATT read/write/notify e2e（10 行示例验证）
   - loopback RFCOMM 回环 SPP e2e
3. **`Stack.from_btsnoop` 实装后必须有 replay 回归测试**，覆盖 PRD §9 "离线回放与实时运行行为一致"。
4. **bridge CLI 命令**：补单元 + 集成测试，或撤回到 experimental tools 子命名空间。

---

## 五、附：本次审查未涉及的开放问题

- 真实硬件验收（PRD §9 后 4 行 "Intel AX200/Realtek RTL8852 自动识别 + HCI reset"）需要在物理设备上跑，本审查仅看代码完整性。
- LE Audio / A2DP / HFP 均为 v2.0+ 范围（PRD §6/7），本次不审查。
- macOS 平台支持本次不审查（PRD §5.1 标 v2.0 评估）。

---

## 六、建议下一步

1. 新建 `docs/superpowers/plans/2026-05-12-prd-v1-closure.md`，把"立即可做" 5 项作为 5 个 Task，串行或拆并行执行。
2. 把"中期重构"5 项作为后续独立 Plan 排进 STATUS.md 总览。
3. 更新 PRD：对齐 `Stack.virtual()` 命名 + 把 `bridge` 命令加入 §5.8 清单。
4. 更新 STATUS.md：把 Plan 10 的"PcapngSink + 回放"声明回滚为未完成（避免后续接手者被误导）。
