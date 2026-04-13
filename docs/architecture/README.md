# PyBlueHost 架构设计文档

**版本**：v0.1  
**日期**：2026-04-13  
**对应 PRD**：[PRD.md](../PRD.md)  
**架构方案**：显式分层 + SAP 接口 + 依赖注入（方案三）

---

## 目录

| 章节 | 文件 | 简介 |
|------|------|------|
| 第一节 | [01-layering.md](01-layering.md) | 整体分层与模块边界——包结构、层间依赖规则 |
| 第二节 | [02-sap.md](02-sap.md) | SAP 接口设计与层间通信——各层 Protocol 定义、数据流示例、测试替换 |
| 第三节 | [03-statemachine.md](03-statemachine.md) | 状态机框架——StateMachine 泛型基类、超时守卫、非法转换处理 |
| 第四节 | [04-trace.md](04-trace.md) | 结构化 Trace 系统——TraceEvent 模型、管道架构、btsnoop/pcapng/JSON/RingBuffer Sink |
| 第五节 | [05-sig-database.md](05-sig-database.md) | SIG 数据库——官方 YAML 仓库集成、全栈查表 API、UUID/Company ID/常量查询 |
| 第六节 | [06-transport.md](06-transport.md) | Transport 层详细设计——USB/WinUSB/UART/TCP/UDP、Intel/Realtek 固件管理、平台差异 |
| 第七节 | [07-hci.md](07-hci.md) | HCI 层详细设计——Packet 系统、Command/ACL flow control、EventRouter、VirtualController |
| 第八节 | [08-l2cap.md](08-l2cap.md) | L2CAP 层详细设计——共享 Channel 抽象、BLE CoC、Classic ERTM/Streaming、SAR、Signaling |
| 第九节 | [09-ble-stack.md](09-ble-stack.md) | BLE 协议栈——ATT Bearer、GATT Server/Client、SMP 配对/SC/CTKD、Bond 持久化 |
| 第十节 | [10-classic-stack.md](10-classic-stack.md) | Classic 协议栈——SDP Server/Client、RFCOMM MUX/DLC、SPP Profile |
| 第十一节 | [11-gap.md](11-gap.md) | GAP 详细设计——BLE Advertising/Scanning/Connection/Privacy + Classic Inquiry/Page/SSP |
| 第十二节 | [12-ble-profiles.md](12-ble-profiles.md) | BLE Profile 框架——三种定义方式对比（Python/YAML/混合）、内置 9 Profile、自定义扩展 |
| 第十三节 | [13-stack-api.md](13-stack-api.md) | Stack 工厂与顶层 API——工厂方法、StackConfig、组装流程、Loopback 双栈、使用示例 |
| 第十四节 | [14-testing.md](14-testing.md) | 测试策略与框架——测试分层、Fake SAP、Loopback E2E、Btsnoop 回放、覆盖率要求、CI |

---

## 核心设计原则

1. **SAP 隔离**：层间仅通过 `typing.Protocol` 接口通信，不直接访问内部状态
2. **显式状态机**：所有有状态实体使用 `StateMachine[S, E]`，转换有日志、超时守卫
3. **依赖注入**：测试时替换任意层为 Fake 实现，无需真实硬件
4. **结构化 Trace**：SAP 调用点自动发出 `TraceEvent`，零手动埋点
5. **Stack 工厂**：`Stack.from_usb()` / `Stack.loopback()` 等一行代码完成组装

## 层次结构概览

```
┌─────────────────────────────────────────────────────────────┐
│  Profiles（HRP / BAS / DIS / HOGP / SPP / …）               │
├──────────────────────┬──────────────────────────────────────┤
│  GATT / ATT / SMP    │  SDP / RFCOMM                        │
│  （BLE）              │  （Classic）                          │
├──────────────────────┴──────────────────────────────────────┤
│  L2CAP（共享信道抽象，BLE / Classic 分实现）                   │
├─────────────────────────────────────────────────────────────┤
│  HCI（Command / Event / ACL / SCO / ISO framing）            │
├─────────────────────────────────────────────────────────────┤
│  Transport（UART / USB WinUSB / TCP / UDP / Loopback）       │
└─────────────────────────────────────────────────────────────┘
```
