# 架构设计文档修改建议

**评审基线**：
- 需求文档：[PRD.md](../PRD.md)
- 评审范围：`docs/architecture/` 全部设计文档
- 评审目标：识别与 PRD 的偏差、跨文档不一致、以及可能导致后续实现返工的设计问题

## 总体结论

当前架构设计整体方向与 PRD 基本一致，覆盖范围也较完整。但存在若干高优先级问题：

1. 核心接口在多份文档中的定义不一致
2. 生命周期与运行模式语义未收敛
3. Trace、重连、回放等关键能力仍停留在概念层，尚未收敛为可实现合同
4. 部分内容已经超出 PRD v1.0 范围，容易造成范围漂移

建议先修订接口合同与运行语义，再继续细化实现文档。

## 高优先级修改建议

### 1. 统一 GATT Server / Profile 的接口合同

**问题**

- [02-sap.md](02-sap.md) 中 `GATTServer` 仅定义 `add_service()`、`notify()`、`indicate()`
- [09-ble-stack.md](09-ble-stack.md) 中 `GATTServer` 仍然只有上述能力
- [12-ble-profiles.md](12-ble-profiles.md) 中 `BLEProfileServer.register()` 却依赖 `gatt_server.on_read()`、`on_write()`、`on_notify()`、`on_indicate()`

这说明目前存在两套不同的 GATT Server 模型：

- 模型 A：`GATTServer` 只管理 attribute database，行为由更底层对象处理
- 模型 B：`GATTServer` 同时承担服务注册和 characteristic 回调分发

如果不先统一，后续 Profile 框架、GATT Server、测试文档会全部返工。

**建议修改**

- 在第 2、9、12、14 节统一 `GATTServer` 的职责边界
- 推荐明确为以下两种方案之一：

方案一：
- `GATTServer` 直接提供 `on_read/on_write/on_notify/on_indicate`
- Profile 层继续保持当前装饰器绑定方式

方案二：
- `add_service()` 时显式传入 handler / provider
- `GATTServer` 不再提供 `on_read/on_write` 这类注册接口
- `BLEProfileServer` 改为生成带行为绑定的 `ServiceDefinition` 或 `AttributeHandlerSet`

**建议输出**

- 在 `09-ble-stack.md` 新增一节“GATT Server 行为绑定模型”
- 在 `02-sap.md` 中补全最终 `GATTServer` 协议定义
- 在 `12-ble-profiles.md` 中删除与最终合同不一致的示例

### 2. 收敛 Stack 生命周期语义

**问题**

- [PRD.md](../PRD.md) 强调 `Stack.from_usb()` / `Stack.loopback()` 一行创建即可使用
- [13-stack-api.md](13-stack-api.md) 又定义了 `power_on()` / `power_off()`
- 同一文档中的组装流程已经在工厂方法里执行 HCI 初始化
- 使用示例也默认 `from_usb()` 返回后可直接扫描、广播、连接

这导致以下问题没有答案：

- 工厂方法返回的是“已初始化可用的 Stack”还是“未上电的 Stack”？
- `power_on()` 是面向普通用户还是面向高级装配场景？
- `close()` 是否隐含 `power_off()`？
- `loopback()` 和 `from_btsnoop()` 是否遵循同一生命周期？

**建议修改**

- 在 `13-stack-api.md` 明确声明单一生命周期模型
- 推荐采用：
  - `from_usb()/from_uart()/from_tcp()/loopback()/from_btsnoop()` 默认返回“已就绪”实例
  - `power_on()` 不对普通工厂暴露，或仅对 `Stack.build()` 的高级装配模式暴露
  - `close()` 负责完整清理资源

**建议输出**

- 在第 13 节新增“生命周期状态图”
- 明确 `created -> ready -> closed` 或 `created -> powered -> closed` 的单一模型
- 所有示例统一使用同一种生命周期

### 3. 重写 Trace 的自动注入方案，避免不可实现的通用代理设计

**问题**

- [PRD.md](../PRD.md) 要求每个 SAP 调用点自动产出结构化 Trace
- [04-trace.md](04-trace.md) 采用通用 `TracingProxy` 包装所有 SAP 调用
- 但并非所有 SAP 方法都天然对应“可记录的原始 PDU”

例如：

- `send_command(HCICommand)` 传的是对象，不是原始字节
- `pair()`、`open_classic_channel()`、`register_fixed_channel()` 是控制语义，不是 PDU 边界
- btsnoop/pcapng 只能稳定记录 HCI 边界的数据，不能直接复用到所有高层 SAP 调用

当前文档把“逻辑调用 trace”和“HCI 抓包 trace”混成了同一个通用代理机制，可实现性不足。

**建议修改**

- 将 Trace 明确拆成两类：
  - `PacketTraceEvent`：HCI/L2CAP/ATT 等协议数据边界
  - `RuntimeTraceEvent`：状态机转换、生命周期变化、配置动作
- btsnoop/pcapng 仅消费 HCI 边界可序列化的数据
- JSON / RingBuffer 可以同时消费 Packet 和 Runtime 事件
- 不再承诺“所有 SAP 都由通用代理自动包装”
- 改为“在明确的协议边界统一发出 trace”，并列出边界清单

**建议输出**

- 在 `04-trace.md` 中增加“可追踪边界矩阵”
- 明确以下边界是否发 trace：
  - Transport <-> HCI
  - HCI <-> L2CAP
  - L2CAP <-> ATT/SDP/RFCOMM
  - 状态机转换
  - 用户 API 调用

### 4. 补齐断线重连的整栈语义

**问题**

- PRD 把“统一流控/重连语义”作为差异化能力
- [06-transport.md](06-transport.md) 只定义了 `Transport.reset()`
- [13-stack-api.md](13-stack-api.md) 有 `reconnect_policy`，但没有定义整栈恢复行为

当前缺失的关键问题包括：

- Transport 重连后 HCI 初始化是否自动重跑
- 现有连接对象是否全部失效
- L2CAP 固定信道/动态信道如何清理
- 广播、扫描、白名单、隐私、配对代理是否自动恢复
- 回调与事件如何通知上层“断线”和“重建完成”

如果不补齐，这个能力很容易只剩“Transport 能 reopen”，无法满足 PRD 的系统级承诺。

**建议修改**

- 在 `06-transport.md` 和 `13-stack-api.md` 之间新增“重连状态机”
- 区分：
  - transport reconnect
  - controller re-init
  - stack recovery
- 明确 `ReconnectPolicy` 的策略粒度和副作用

**建议输出**

- 增加一张“断线恢复流程图”
- 明确以下行为：
  - 自动恢复哪些配置
  - 哪些连接对象必须作废
  - 上层会收到哪些事件
  - 哪些模式下禁用重连（如 btsnoop 回放）

### 5. 明确 btsnoop 回放模式的能力边界

**问题**

- PRD 仅要求 `from_btsnoop()` 支持离线回放
- [13-stack-api.md](13-stack-api.md) 让它返回普通 `Stack`
- 同文又写明“不可发送命令（只读模式）”

这会造成 API 误导：调用者看到的是正常 `Stack`，但很多操作其实不合法。

**建议修改**

- 不建议让 `from_btsnoop()` 返回与真实运行栈完全同构的对象
- 推荐以下两种方式之一：

方案一：
- 单独定义 `ReplayStack`
- 只暴露回放、遍历、事件订阅、trace 再输出等只读能力

方案二：
- 仍返回 `Stack`
- 但必须定义明确的 capability / mode 字段
- 所有不可用 API 在文档中列清，并约定抛出统一错误

**建议输出**

- 在 `13-stack-api.md` 增加“运行模式矩阵”
- 对比说明：
  - real controller mode
  - loopback simulation mode
  - replay mode

## 中优先级修改建议

### 6. 处理核心依赖与 YAML/submodule 方案之间的冲突

**问题**

- [PRD.md](../PRD.md) 写的是“核心栈无强制第三方依赖”
- [05-sig-database.md](05-sig-database.md) 依赖运行时 YAML 解析
- [12-ble-profiles.md](12-ble-profiles.md) 又把 YAML 作为推荐 Profile 定义方式

如果 YAML 是运行时必需，就意味着核心栈至少存在 YAML 解析依赖，也会引入 SIG submodule 的打包和分发问题。

**建议修改**

- 二选一并同步修订 PRD 与架构文档：

方案一：
- 承认 YAML 是正式依赖
- 在 PRD 中把其列入核心依赖

方案二：
- 改成构建时生成 Python/JSON 资源
- 运行时不依赖 YAML 库与 submodule

**建议输出**

- 在 `05-sig-database.md` 增加“打包与发布策略”
- 说明：
  - PyPI 包是否携带 SIG 数据
  - submodule 在发布时如何处理
  - 离线安装是否可用

### 7. 统一共享基础类型的归属，避免后续循环依赖

**问题**

- [01-layering.md](01-layering.md) 中地址类型在 `core/address.py`
- [11-gap.md](11-gap.md) 又定义 `core/gap_common.py`
- 安全配置、IO capability、连接角色等跨层类型目前也没有统一落点

这会导致实现时频繁改 import，甚至出现 `core`、`ble`、`classic` 互相拉扯。

**建议修改**

- 增加一份“共享类型归属表”
- 明确以下对象唯一落点：
  - `BDAddress`
  - `AddressType`
  - `IOCapability`
  - `ConnectionRole`
  - `LinkType`
  - `SecurityConfig`
  - 各类 error / event enum

**建议输出**

- 在 `01-layering.md` 增加“跨层公共类型清单”
- 所有其他章节引用该清单，不再各自重新发明位置

### 8. 为 HCI mandatory coverage 明确范围边界

**问题**

- PRD 要求“所有 mandatory HCI 命令/事件完整 encode/decode”
- [07-hci.md](07-hci.md) 只给出结构和样例，没有说明 mandatory 的判定边界

这会直接影响：

- v1.0 范围控制
- 任务拆分
- 测试覆盖率定义

**建议修改**

- 在 `07-hci.md` 增加“v1.0 HCI 覆盖矩阵”
- 按类别列出：
  - core mandatory
  - LE mandatory
  - vendor-specific
  - parse only
  - deferred

**建议输出**

- 明确哪些命令/事件：
  - 必须结构化建模
  - 允许 generic packet fallback
  - v1.0 只做 raw decode

### 9. 测试文档需要和最终接口合同同步

**问题**

- [14-testing.md](14-testing.md) 当前大量测试示例依赖尚未收敛的接口
- 尤其是 GATT、Loopback、Fake SAP、回放模式相关示例

如果前面几项接口调整后不回写测试文档，测试策略本身会和实现目标脱节。

**建议修改**

- 等接口合同收敛后，统一回写第 14 节
- 给测试文档补上“接口已冻结”的前提说明

**建议输出**

- 补充一张“测试层级 -> 对应构件 -> 对应 Fake/Fixture”映射表
- 将示例测试拆成：
  - 当前 v1.0 必测
  - 后续增强

## 低优先级修改建议

### 10. 将超出 PRD v1.0 的内容统一降级为扩展点

**问题**

多个章节出现了 v1.0 之外的内容，但没有明确标注为未来能力，例如：

- `CTKD`
- A2DP/AVRCP/HFP 相关 SIG 常量
- A2DP 高吞吐 trace 场景举例

虽然这些内容本身没有错，但放在 v1.0 设计正文里容易制造错误预期。

**建议修改**

- 在相关章节统一增加“future extensibility”或“非 v1 承诺”标记
- 只保留对当前设计有约束作用的扩展点
- 删除与 v1.0 完全无关的实现性细节

### 11. 统一命名和示例风格

**问题**

当前文档存在一些命名不统一问题，例如：

- `BtsnoopTransport` / `from_btsnoop()` / `BtsnoopReplayTransport`
- `gap_le.py` / `ble/gap.py`
- `gap_classic.py` / `classic/gap.py`

这类问题不影响方向，但会影响后续代码结构和读者理解。

**建议修改**

- 全量统一命名
- 所有示例代码只保留一种最终命名方式
- 在 `README.md` 里补充文档索引和术语约定

## 推荐修订顺序

建议按以下顺序修订架构文档：

1. 先修第 2、9、12、13 节，收敛核心接口和生命周期
2. 再修第 4、6、13 节，补齐 trace、重连、回放模式语义
3. 然后修第 1、5、11 节，统一模块边界和共享类型
4. 最后修第 14 节，回写测试策略与示例

## 建议新增的补充内容

为避免后续继续发散，建议增加以下补充章节或附录：

- `附录 A：核心接口冻结清单`
- `附录 B：运行模式矩阵（real / loopback / replay）`
- `附录 C：共享基础类型归属表`
- `附录 D：v1.0 覆盖矩阵（HCI / L2CAP / Profile）`

## 最终目标

修订后的架构文档应达到以下标准：

- 每个核心对象只有一份权威接口定义
- 每种运行模式都有清晰能力边界
- PRD 中承诺的差异化能力都能映射到可实现的设计合同
- v1.0 范围明确，不把未来版本内容混入当前交付承诺
