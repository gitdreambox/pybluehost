# 架构设计评审回复

**评审基线**：[review-notes.md](review-notes.md)
**回复日期**：2026-04-13

---

## 总体评价

评审方向基本正确，识别出了几个真实的接口一致性问题。但部分建议过度设计，将 v1.0 不需要解决的问题升级为高优先级，或建议引入不必要的新抽象（ReplayStack、PacketTraceEvent/RuntimeTraceEvent、附录 A/B/C/D）。

以下逐条回复，分为"接受并修改"、"部分接受（简化处理）"、"不接受"三类。

---

## 接受并修改

### #1 GATTServer 接口不一致

**评审结论正确。** `02-sap.md` 和 `09-ble-stack.md` 的 `GATTServer` Protocol 只有 `add_service/notify/indicate`，但 `12-ble-profiles.md` 的 `BLEProfileServer.register()` 调用了 `gatt_server.on_read()`、`on_write()`、`on_notify()`、`on_indicate()` — 这四个方法在 Protocol 中不存在。方案 A 示例也用了 `server.on_read()`。

**处理方式**：在 `GATTServer` Protocol 中补上 `on_read/on_write/on_notify/on_indicate` 四个回调注册方法。不需要评审建议的"两种方案选一个" — 装饰器绑定方案已确定，只是 Protocol 漏写了方法签名。

**修改范围**：02-sap.md、09-ble-stack.md

### #6 YAML 依赖与"无第三方依赖"矛盾

**评审结论正确。** PRD 第 8 节写"核心栈：无强制第三方依赖"，但 `SIGDatabase` 和 Profile YAML 加载都需要 `pyyaml`。

**处理方式**：修改 PRD，将 `pyyaml` 列为核心依赖。理由：
- `pyyaml` 是 Python 生态最基础的库之一
- 构建时 YAML→Python 转换增加构建复杂度但无实际收益
- PRD 原意是避免重量级依赖（GUI 框架、特定 OS 库），pyyaml 不在此列

**修改范围**：PRD.md

### #7 共享基础类型重复定义

**评审结论正确。** `01-layering.md` 有 `core/address.py`（BD_ADDR / BLE Address），`11-gap.md` 又在 `core/gap_common.py` 定义了 `BDAddress` 和 `AddressType`。存在重复。

**处理方式**：地址相关类型统一归属 `core/address.py`。`core/gap_common.py` 只保留 GAP 特有类型（`ClassOfDevice`、`ServiceClass` 等）。在 `01-layering.md` 明确各 core 文件的类型归属。

**修改范围**：01-layering.md、11-gap.md

### #11 命名不统一（部分）

`BtsnoopTransport` vs `BtsnoopReplayTransport`：需统一为 `BtsnoopTransport`。

**修改范围**：06-transport.md、13-stack-api.md（如有不一致处）

---

## 部分接受（简化处理）

### #2 Stack 生命周期语义

**评审发现了模糊点，但建议过重。** 文档其实已有答案：

- `13-stack-api.md` 组装流程步骤 4 明确写了"HCI 初始化序列（16 步）"在工厂内执行
- 所有使用示例均为 `async with await Stack.from_usb() as stack:` → 直接操作

`power_on()/power_off()` 是运行时控制无线电状态（类似手机开关蓝牙），不是初始化入口。

**处理方式**：在 13 节加一段生命周期说明（5-8 行），明确：工厂返回已就绪实例、power_on/off 是运行时控制、close 释放资源。不需要状态图或重设计。

**不采纳**：评审建议的"不对普通工厂暴露 power_on"和"增加生命周期状态图"。

**修改范围**：13-stack-api.md

### #3 TracingProxy 可实现性

**评审技术分析有误。** `TraceEvent.raw_bytes` 允许为空（`bytes` 类型），`decoded` 为 `dict | None`。控制类调用（`pair()`、`register_fixed_channel()`）完全可以 emit `raw_bytes=b""` + `decoded={"action": "pair", ...}`。btsnoop/pcapng sink 自然只消费 HCI 层有 raw_bytes 的事件 — 这是 sink 侧按 `source_layer` 过滤，不需要拆分 Event 类型。

真正需要澄清的是：哪些边界产出 PDU trace（有 raw_bytes），哪些产出 runtime trace（raw_bytes 为空）。

**处理方式**：在 04-trace.md 加一个"可追踪边界矩阵"表。

**不采纳**：拆分为 PacketTraceEvent/RuntimeTraceEvent、放弃通用 TracingProxy。

**修改范围**：04-trace.md

### #4 断线重连整栈语义

**评审提出的问题实际上有标准答案。** 蓝牙 Core Spec 规定：Controller reset = 所有连接丢失、所有 HCI 状态清零。因此重连语义很明确：

1. Transport 重连（close + reopen）
2. HCI 初始化序列重跑
3. 所有现有连接失效，上层收到 disconnect 事件
4. 广播/扫描/白名单等需用户重新启动

PRD 的"重连策略"指 Transport 层自动重连（立即/指数退避/不重连），不是整栈状态自动恢复。

**处理方式**：在 13-stack-api.md 加一段重连行为说明。

**不采纳**：评审建议的"新增重连状态机"和"断线恢复流程图"。

**修改范围**：13-stack-api.md

### #5 btsnoop 回放模式能力边界

**评审发现了需要澄清的问题，但建议方案过重。**

**处理方式**：加 `StackMode` 枚举（`LIVE/REPLAY/LOOPBACK`）和 `stack.mode` 属性。REPLAY 模式下写操作抛 `ReplayModeError`。在 13 节加简短的模式说明。

**不采纳**：单独定义 `ReplayStack` 类、运行模式矩阵。

**修改范围**：13-stack-api.md

---

## 不接受

### #8 HCI mandatory 覆盖矩阵

**不属于架构文档范围。** 架构文档定义了 PacketRegistry 框架和 decorator 注册机制。"v1.0 具体实现哪些 HCI 命令/事件"是实现规划 / 任务拆分的内容，应在 implementation plan 中列出。

### #9 测试文档需同步

**正确但是顺序依赖。** 等 #1 和 #5 修完后自然回写测试示例。不是独立问题。

### #10 超出 v1.0 内容降级

**当前处理已经足够。**
- CTKD 已标注"默认关闭，用户显式开启"
- A2DP/AVRCP/HFP 常量出现在 SIG 数据库章节，是描述 SIG 仓库目录结构，不是承诺实现这些 Profile
- 保留这些内容有助于理解架构扩展性

### 评审建议的"新增附录 A/B/C/D"

**不采纳。** 上述各项通过在现有章节中补充段落即可解决，不需要新建附录文件。核心接口定义的权威来源是 `02-sap.md`，不需要额外的"冻结清单"。

---

## 修改计划

按以下顺序执行修改：

1. **02-sap.md + 09-ble-stack.md**：GATTServer 补接口
2. **PRD.md**：pyyaml 列为核心依赖
3. **01-layering.md + 11-gap.md**：统一共享类型归属
4. **04-trace.md**：加可追踪边界矩阵
5. **13-stack-api.md**：加生命周期说明 + 重连行为 + StackMode
6. **06-transport.md**：统一 BtsnoopTransport 命名
7. **14-testing.md**：回写受影响的测试示例
