# PyBlueHost PRD — Product Requirements Document

**版本**：v0.1  
**日期**：2026-04-11  
**状态**：待确认

---

## 1. 产品定位

PyBlueHost 是一个面向**开发者和研究者**的专业级 Python Bluetooth Host 协议栈，目标是成为蓝牙协议测试、调试和教育领域的首选 Python 工具。

### 与 Bumble 的核心差异

| 维度 | Bumble | PyBlueHost |
|------|--------|------------|
| 可测试性 | 层间强耦合，测试需启动完整栈 | 任意单层可独立 pytest，无需硬件 |
| 状态机 | 状态散落在回调中，不透明 | 显式 `StateMachine[S,E]`，转换有日志和超时守卫 |
| Transport 抽象 | 薄层封装，无统一流控/重连语义 | 统一接口，含背压、断线重连策略 |
| 日志与 Trace | 人读字符串，无结构化 trace | 结构化 PDU trace，输出 btsnoop/pcap/JSON |
| 并发模型 | 纯 asyncio | 纯 asyncio（同向，但实现更干净） |

---

## 2. 目标用户

| 用户 | 典型场景 |
|------|---------|
| 嵌入式 / 固件工程师 | 连接真实蓝牙芯片，验证 Host 行为，抓包分析 |
| 协议测试工程师 | 用 VirtualController 对 DUT 做自动化测试 |
| 蓝牙协议学习者 | 逐层观察 PDU，理解协议状态机流转 |
| 安全研究员 | 构造非标准包，测试对端鲁棒性 |

---

## 3. 使用场景（按优先级）

**P0 — 连接真实硬件（主要使用场景）**  
用户无需额外硬件，直接使用笔记本/台式机内置的 Intel / Realtek 网卡蓝牙芯片，在 Windows 或 Linux 上创建 `Stack`，发起 BLE scan、建立连接、读写 GATT characteristic，或建立 Classic RFCOMM / SPP 通道。

**P1 — 协议教育与调试**  
运行任意场景时，结构化 trace 自动记录所有层间 PDU，输出 `.cfa`（btsnoop）或 pcapng，可在 Wireshark 中逐包分析。

**P2 — 纯软件测试 / 仿真**  
不需要任何硬件，用 `Stack.loopback()` 启动内置 VirtualController，运行协议逻辑，用 pytest 覆盖每个协议层。

**P3 — 协议一致性 / Fault Injection**  
构造合法或非法 PDU 发给对端，验证其合规性。v1.0 提供 API 支持，不提供预置测试用例集。

---

## 4. 架构原则

采用**显式分层 + SAP 接口 + 依赖注入**架构（方案三）：

- 每层实现上行 SAP（接收下层数据/事件）和下行 SAP（向下层发命令），层间仅通过接口耦合
- 测试时可将任意层替换为 Fake 实现，只测目标层逻辑
- 显式 `StateMachine[StateEnum, EventEnum]`：状态转换有日志、超时守卫、非法转换报错
- `Stack` 工厂负责组装：`Stack.from_uart()` / `Stack.from_usb()` / `Stack.from_tcp()` / `Stack.loopback()`
- 所有 SAP 调用点自动发出结构化 `TraceEvent`，无侵入

```
┌─────────────────────────────────────────────────────┐
│  Profiles（HRP / BAS / DIS / HOGP / SPP / …）       │
├──────────────────────┬──────────────────────────────┤
│  GATT / ATT / SMP    │  SDP / RFCOMM                │
│  （BLE）             │  （Classic）                  │
├──────────────────────┴──────────────────────────────┤
│  L2CAP（共享信道抽象，BLE / Classic 分实现）          │
├─────────────────────────────────────────────────────┤
│  HCI（Command / Event / ACL / SCO / ISO framing）   │
├─────────────────────────────────────────────────────┤
│  Transport（UART / USB / TCP / UDP / Loopback）      │
└─────────────────────────────────────────────────────┘
```

---

## 5. 功能范围

### 5.1 Transport 层

- **支持接口**：UART（H4 framing）、USB / WinUSB（`pyusb`）、TCP、UDP
- **内置 Transport**：`LoopbackTransport`（纯软件测试用）
- **统一接口**：`open()` / `close()` / `send(bytes)` / `on_data_received(cb)` / `on_error(cb)`
- **流控**：基于 asyncio 背压机制；断线自动重连（可配置策略：立即/指数退避/不重连）

#### 平台支持

| 平台 | 方式 | 备注 |
|------|------|------|
| **Windows（主要）** | WinUSB + `libusb`（via `pyusb`） | 需用 Zadig 将蓝牙设备绑定至 WinUSB 驱动，文档提供详细步骤 |
| **Linux** | `libusb`（via `pyusb`）或 `hci_user_channel`（内核 socket） | `hci_user_channel` 绕过 BlueZ 独占 HCI，无需额外依赖 |
| **macOS** | v2.0 评估 | — |

#### Intel / Realtek 内置蓝牙芯片支持（主要目标硬件）

大多数用户笔记本/台式机的内置蓝牙为 Intel 或 Realtek 网卡蓝牙组合芯片，无需额外购买硬件：

- **内置 VID/PID 常量表**，自动识别主流芯片：
  - Intel：AX200、AX201、AX210、AX211、AC9560、AC8265 等
  - Realtek：RTL8761A/B、RTL8852A/B/C、RTL8723 系列等
- **固件上传**：Intel 和部分 Realtek 芯片在初始化时需通过 HCI vendor command 上传固件，`USBTransport` 内置固件加载流程（固件文件由用户提供或从系统驱动目录自动检测）
- **自动选择**：`Stack.from_usb()` 无参数调用时自动扫描已知兼容芯片，找到即用

#### btsnoop 支持

- **写入**：运行时实时输出符合 btsnoop 规范的 `.cfa` / `.log` 文件，与 Android HCI snoop log、`btmon` 格式兼容，可直接用 Wireshark 打开
- **回放**：`Stack.from_btsnoop("file.cfa")` 将已有 btsnoop 文件作为 transport 回放，用于离线复现和回归测试

### 5.2 HCI 层

- **Packet 类型**：Command / Event / ACL / SCO / ISO（完整 framing，HCI v5.4 core spec）
- **Flow control**：Host_Num_Completed_Packets，Command credit 管理
- **VirtualController**：纯软件 Controller 实现，响应基本 HCI 命令，支持多连接仿真，无需真实硬件
- **ISO 帧解析**：解析 HCI ISO 数据包类型（为 LE Audio v3.0 铺路，v1.0 不实现上层逻辑）
- **结构化解析**：所有 mandatory HCI 命令/事件的完整 encode/decode

### 5.3 L2CAP 层

- **共享信道抽象**：`Channel` 接口，BLE 和 Classic 各自实现，上层统一使用
- **BLE L2CAP**：
  - Fixed channels（ATT CID 0x0004、SMP CID 0x0006）
  - LE Credit-based Connection Oriented Channels（CoC）
- **Classic L2CAP**：
  - Connection-oriented channels，信道配置协商（MTU / flush timeout / QoS）
  - Retransmission and Flow Control Mode（ERTM）
  - Streaming Mode
- **SAR**：分段与重组（Segmentation and Reassembly）

### 5.4 BLE 协议栈

#### ATT（Attribute Protocol）
- 读 / 写 / 通知 / 指示
- PrepareWrite / ExecuteWrite（Long Attribute）
- MTU 协商（Exchange MTU）
- Error response 完整处理

#### GATT（Generic Attribute Profile）
- Server 和 Client 双角色
- Service / Characteristic / Descriptor 定义与注册
- Primary / Secondary / Included Services
- Service Changed indication
- 描述符：CCCD / CPFD / CUDD / Extended Properties

#### SMP（Security Manager Protocol）
- Legacy Pairing 和 Secure Connections（LE）
- 全部 IO Capability 组合（DisplayOnly / DisplayYesNo / KeyboardOnly / NoInputNoOutput / KeyboardDisplay）
- Passkey Entry / Numeric Comparison / Just Works / OOB
- Bond 持久化（本地存储，可插拔后端）

#### BLE 常用 Profile（Server + Client 双角色）
| Profile | 规范 |
|---------|------|
| Generic Access Profile（GAP service） | — |
| Generic Attribute Profile（GATT service） | — |
| Device Information Service（DIS） | 0x180A |
| Battery Service（BAS） | 0x180F |
| Heart Rate Profile / Service（HRP/HRS） | 0x180D |
| Blood Pressure Profile（BLP） | 0x1810 |
| HID over GATT Profile（HOGP） | 0x1812 |
| Running Speed and Cadence（RSC） | 0x1814 |
| Cycling Speed and Cadence（CSC） | 0x1816 |

### 5.5 Classic 协议栈

#### SDP（Service Discovery Protocol）
- Server：ServiceRecord 注册，UUID / AttributeID 索引
- Client：ServiceSearch / AttributeRequest / ServiceSearchAttribute
- 常用 UUID 常量库

#### RFCOMM
- 多路复用信道（多个 DLC）
- 串口仿真语义（RLS / RPN / MSC）
- 流控（Credit-based）

#### SPP（Serial Port Profile）
- RFCOMM 上层封装
- SDP 自动注册 SPP record
- 作为 Classic Profile 框架的第一个示例实现

### 5.6 GAP（Generic Access Profile）

**BLE：**
- Advertising：Legacy（ADV_IND / ADV_NONCONN_IND / ADV_DIRECT_IND）+ Extended Advertising（AE）
- Scanning：Passive / Active，重复过滤，RSSI 上报
- Connection parameter update（L2CAP signaling）
- Privacy：Resolvable Private Address（RPA），IRK 管理

**Classic：**
- Inquiry（GIAC / LIAC）和 Inquiry Scan
- Page 和 Page Scan
- Remote Name Request
- Authentication（PIN / SSP）
- Encryption（E0 / AES-CCM）

**共享：**
- 设备名称、Class of Device / Appearance
- 白名单 / 拒绝列表 / 过滤策略
- 连接事件回调统一接口

### 5.7 基础设施

#### 显式状态机框架
- `StateMachine[S: Enum, E: Enum]` 泛型基类
- 状态转换注册（`on(state, event) → new_state`）
- 非法转换：抛出 `InvalidTransitionError`，记录当前状态和触发事件
- 超时守卫：进入状态时可注册 timeout（asyncio），超时自动触发指定事件
- 转换日志：每次转换自动写入结构化日志

#### 结构化 Trace 系统
- 每个 SAP 调用点自动发出 `TraceEvent(layer, direction, pdu_bytes, timestamp, decoded)`
- 输出 Sink（可同时启用多个）：
  - **btsnoop**（`.cfa`）：Android / Wireshark 兼容
  - **pcapng**：通用抓包格式
  - **JSON**：程序化分析
  - **In-memory ring buffer**：REPL / 实时调试
- 完全无侵入，不需要在业务代码中手动加日志

#### Stack 工厂
```python
Stack.from_usb()                             # 自动检测 Intel/Realtek 内置芯片（推荐，无需参数）
Stack.from_usb(vendor_id=0x8087, product_id=0x0032)  # 指定 VID/PID
Stack.from_uart("/dev/ttyUSB0", baudrate=115200)
Stack.from_tcp("localhost", 9000)
Stack.from_btsnoop("hci_snoop.cfa")          # 回放模式
Stack.loopback()                             # 纯软件，含 VirtualController
Stack.build(transport=..., trace_sink=...)   # 自定义组装
```

#### pytest 支持
- `loopback_stack` fixture：开箱即用的纯软件栈
- `hci_pair` fixture：两个互联的 VirtualController，模拟两端设备
- 每层提供独立可用的 Fake SAP 实现，用于单层测试

---

## 6. 版本路线图

| 版本 | 内容 |
|------|------|
| **v1.0** | Transport（UART/USB WinUSB/TCP/UDP + Intel/Realtek 自动识别 + 固件上传 + btsnoop + Loopback）+ HCI（含 ISO 帧解析）+ L2CAP（BLE + Classic）+ BLE 栈（ATT/GATT/SMP + 9 个 Profile）+ Classic 栈（SDP/RFCOMM/SPP）+ GAP（BLE + Classic）+ 状态机框架 + Trace 系统；平台：Windows + Linux |
| **v1.1** | PTS IUT 支持（HCI/L2CAP/GAP/ATT/GATT/SMP test group ≥90% 通过）+ 分析仪集成（Ellisys Remote API + Teledyne LeCroy WPS Automation API）|
| **v2.0** | A2DP / AVRCP / HFP / HSP + AVDTP / AVCTP + SCO 音频路径 |
| **v3.0** | SBC / AAC 解码 + 音频播放（sounddevice / pyaudio）|
| **v4.0** | LE Audio（BAP / CIS / BIS / LC3） |

---

## 7. 非目标（v1.0 明确不做）

- A2DP / AVRCP / HFP / HSP → v2.0
- PTS IUT 测试 → v2.0
- Ellisys / Teledyne LeCroy 分析仪集成 → v2.0
- SBC / AAC 解码与音频播放 → v3.0
- LE Audio（BAP / CIS / BIS / LC3）→ v3.0
- AMP / BR+EDR 共存策略（PAL）
- macOS 原生 HCI transport → v2.0 评估
- Mesh

---

## 8. 技术约束

- Python 3.10+（使用 `match/case`、`TypeAlias`、`ParamSpec` 等新特性）
- 并发模型：纯 `asyncio`，无线程（阻塞 IO 在 transport 层用 `run_in_executor` 隔离）
- **平台**：Windows（主要）+ Linux；macOS v2.0 评估
- **外部依赖**：
  - 核心栈：无强制第三方依赖
  - USB transport：`pyusb`（可选，Windows 需 WinUSB 驱动；Linux 可选 `hci_user_channel` 零依赖路径）
  - v2.0 分析仪集成：`pywin32` / `comtypes`（Windows only，可选）
- 构建工具：`uv` + `hatchling`
- 测试：`pytest`，CI 全绿不依赖真实硬件
- 代码风格：`snake_case` 函数/模块，`PascalCase` 类，`UPPER_SNAKE_CASE` 常量，4 空格缩进

---

## 9. 成功标准

| 指标 | 目标 |
|------|------|
| 任意单层可独立 pytest 覆盖 | CI 全绿，无需真实硬件 |
| BLE 连接真实 Android/iOS 手机 | GATT read/write/notify 通过 |
| HRM Profile 与真实心率带互通 | 数据正确读取并解析 |
| Classic RFCOMM / SPP 与 Linux `rfcomm` / Windows 互通 | 双向数据传输正常 |
| Wireshark 可直接打开生成的 btsnoop / pcapng | 所有层 PDU 正确解析 |
| btsnoop 文件回放复现场景 | 离线回放与实时运行行为一致 |
| `Stack.loopback()` 10 行内完成 BLE GATT 读写 | API 易用性验证 |
| VirtualController 支持 2+ 并发连接仿真 | 多连接场景测试通过 |
| Intel AX200/AX210 在 Windows 上自动识别并初始化 | 固件加载成功，HCI reset 正常响应 |
| Realtek RTL8852 在 Windows 上自动识别并初始化 | 固件加载成功，HCI reset 正常响应 |
