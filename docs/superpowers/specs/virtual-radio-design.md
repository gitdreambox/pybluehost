# VirtualRadio 设计文档

| 项 | 值 |
|----|----|
| 状态 | **待 brainstorming**（立项占位文档，尚未设计） |
| 立项日期 | 2026-04-27 |
| 立项来源 | [pytest-transport-selection-design.md §15](./pytest-transport-selection-design.md) |
| 责任方 | （待认领） |

> 这是一个**占位文档**，记录问题域与目标范围，等待正式的 brainstorming 流程产出完整设计。
> 在没有完成 brainstorming 之前，不应基于此文档编写实施 plan。

## 1. 背景与问题陈述

当前 PyBlueHost 在不接真硬件的情况下，**无法做端到端协议测试**：

- `Stack.virtual()` 创建一个 `VirtualController`，host 端通过内部 pipe 与之通信——但**两个 `VirtualController` 实例之间没有任何共享空气信道**。
- 现有 `gatt_browser` / `sdp_browser` 的 loopback 模式是 demo trick：client 端不真正"连接"peer，而是直接读 peer server 的内部 DB 并打印。
- 无法验证 GAP（advertising/scan/inquiry/page）、L2CAP、ATT、SMP 等需要双控制器协作的逻辑路径。

随着以下需求出现，缺位将更明显：

- PRD 中对 PTS IUT 的支持要求（HCI/L2CAP/GAP/ATT/GATT/SMP test group ≥90% 通过）
- `peer_stack` fixture 需要承载真正的双 VC 协议测试，而不仅仅是 server 端配置断言
- 教学/演示场景需要观察完整的协议交换 trace，而不是一头读自己 server 的快捷方式

## 2. 目标范围（待 brainstorming 收敛）

引入 **VirtualRadio**（暂名，可改 `VirtualAirBus` / `VirtualPHY` 等），让多个 `VirtualController` 在同一进程内通过共享 bus 模拟空气信道：

候选支持矩阵：

| 协议层 / 角色 | 必须 | 可选 |
|---------------|------|------|
| LE Advertising / Scanning（ADV_IND → ADV Report） | ✓ | |
| LE Connection（Create Connection ↔ Connectable Adv） | ✓ | |
| LE ACL + L2CAP Signaling | ✓ | |
| ATT / GATT 跨 VC | ✓ | |
| SMP pairing（LE Legacy + SC） | ✓ | |
| BR/EDR Inquiry / Inquiry Scan | ✓ | |
| BR/EDR Paging / Page Scan | ✓ | |
| BR/EDR ACL + L2CAP | ✓ | |
| RFCOMM / SDP / SPP | ✓ | |
| 多设备拓扑（>2 个 VC） | | ✓（YAGNI 候选） |
| 物理层时序模拟（jitter / loss） | | ✓（教学价值，但非必要） |
| 2 Mbps PHY、LE Coded、Extended Advertising | | ✓（按需） |

## 3. 与本次 pytest plan 的关系

- 本次 [pytest-transport-selection-design](./pytest-transport-selection-design.md) **不依赖** VirtualRadio；它只决定测试用哪个 transport。
- VirtualRadio 落地后，本次设计中的 `peer_stack` fixture **不需要修改接口**——只是行为升级：从"两个独立 VC，仅适合 server 端断言"升级为"两个 VC 通过 VirtualRadio 真正交换协议"。
- 现有 demo trick 测试（如 `gatt_browser` loopback）届时可保留作为一种简化路径，也可改写为真协议路径。

## 4. 待 brainstorming 决定的关键设计点

1. **VirtualRadio 是单例还是按 session 实例化？** test isolation vs 共享状态。
2. **如何把 bus 注入 VirtualController？** 构造参数 / 全局注册 / fixture 注入。
3. **协议状态机放在 VC 内还是 bus 内？** 例如 connection 状态：每个 VC 维护自己角色的状态机，bus 只做 PDU 路由；还是 bus 维护连接表？
4. **错误注入与故障模拟**：是否提供 API 让测试主动丢包、注入错误响应？
5. **多设备拓扑**：是否支持 3+ VC 同时存在（central + 多 peripheral），bus 如何路由？
6. **时序模型**：纯事件驱动（瞬时投递）还是引入虚拟时钟？
7. **与真实硬件路径的等价性验证**：如何确保 VirtualRadio 路径与真硬件行为对齐？

## 5. 下一步

1. 与项目所有者讨论优先级与人力预算。
2. 用 `superpowers:brainstorming` 走完整 brainstorming 流程产出正式设计。
3. 用 `superpowers:writing-plans` 拆解实施 plan。
4. 用 `superpowers:subagent-driven-development` 执行。

在以上三步未完成前，本文件**不应**被引用为正式设计依据。
