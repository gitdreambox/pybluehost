# Design Spec — MITM 透传应用（独立应用，仅复用 HCI）

**版本**：design v0.5
**日期**：2026-06-01
**前置版本**：PRD v1.0 已完成 31 个 Plan，`transport` + `hci`（含 HCIController、VirtualController/VirtualLink/VirtualClassicLink）已就位
**适用场景**：**授权**安全测试 / 漏洞研究 / 教学。两端设备（手机 + 目标）均在测试者掌控下。

---

## 1. 目标摘要

在**目标设备**与**手机**之间插入中间人（MITM），**双向透传 BLE 与 BR/EDR ACL 数据**：对手机冒充目标（克隆应用层身份），对目标冒充手机（central/initiator 连接）。中间拿两侧明文，**v1 只做透传 + 抓包**。

**本质定位：MITM 是一个独立应用，不是协议栈的一层。** 它把 `transport` + `hci` 当成驱动跟两个 dongle 对话，HCI 之上的协议栈层（l2cap/ble/classic/gap/profiles/stack）**一律不碰、不导入**，协议栈保持纯净。MITM 自己实现它需要的那一点点上层逻辑（ACL 重组、最小 SMP、SSP 事件处理）。

- **v1 范围**：BLE + BR/EDR 透传（同期）。**改写（规则 / hook）= 后续阶段**，仅预留 tap seam。
- **核心中继层**：B 式 HCI-ACL 透传——HCI ACL 层重组/重分片 + 按 L2CAP CID 分流。BLE/BR 共用。
- **硬件**：两个 USB 适配器。默认模式任意两个即可；地址克隆为可选能力（§3.1）。

### 1.1 需求决策表（brainstorming 结论）

| 维度 | 决定 |
|------|------|
| 定位 | **独立应用**，仅复用 `transport` + `hci`，协议栈零改动 |
| 首要目标 | 授权安全研究 —— v1 透传 + 抓包；改写后续 |
| 硬件 | 两个 USB 适配器（真双 radio） |
| 加密 | 逐链路本地终结（两侧各自配对，中间拿明文） |
| 身份克隆 | 自动侦查 + 克隆**应用层身份**（adv/name/CoD/EIR）；地址克隆可选 |
| 范围 | BLE + BR/EDR 同期透传；改写后续 |
| 抓包 | btsnoop 默认 sink + trace |
| 中继层 | B 式 HCI-ACL 透传（重组/CID 分流/重分片），BLE/BR 共用 |
| 配对 | **Just Works + Numeric Comparison**（均 SC）；BLE 用 app 内最小 SMP，BR 用 HCI SSP 事件 |

---

## 2. 依赖边界（核心约束）

```
┌───────────────────────────────────────────────────────────┐
│  MITM 应用  (pybluehost/cli/app/mitm/)                      │
│  relay / acl / recon / impersonate / pairing(smp,ssp) /    │
│  capture                                                    │
└───────────┬───────────────────────────────────┬───────────┘
            │ 只依赖 ↓                            │ 只依赖 ↓
   ┌────────▼────────┐                  ┌─────────▼─────────┐
   │  hci            │                  │  crypto 库         │
   │  HCIController  │  (两个实例,各绑   │  (P-256 ECDH +     │
   │  packets/const  │   一个 transport) │   AES-CMAC)        │
   └────────┬────────┘                  └───────────────────┘
   ┌────────▼────────┐
   │  transport      │  (USB / HCI 通道)
   └─────────────────┘
```

**允许依赖**：
- `transport`：开 USB / HCI 通道。
- `hci`：`HCIController`（命令/事件分发、ACL 收发、flow control、buffer 大小、连接跟踪、encryption/SSP 事件钩子）+ `packets` + `constants`。`HCIController` 本身只依赖 hci 内部，不引入上层。
- crypto 库：SC 配对所需 P-256 ECDH + AES-CMAC（项目已有的 crypto 依赖；**不导入 `ble/` 下的 SMP 代码**）。
- 可选工具：`core.trace.BtsnoopSink`（纯 btsnoop 文件写入器，I/O 工具非协议逻辑；亦可 app 内自带 ~40 行替代）。

**禁止依赖**：`l2cap`、`ble`、`classic`、`gap`、`profiles`、`stack.py`。MITM 自己做 L2CAP basic header（2 字节 len+CID）封装/解析——这是琐碎字节操作，不需要 L2CAPManager。

> **协议栈零改动**：本应用不要求修改 `pybluehost/` 任何现有协议栈层。VirtualController/VirtualLink 等测试设施已存在，直接复用。

---

## 3. 加密终结与配对

加密由**控制器逐链路**完成，密钥逐链路独立。**配对信令绝不转发**（否则 MITM 本侧控制器拿不到密钥，无法对本侧开加密）。两侧各自作为真实配对端点。

- **BR/EDR SSP**：**控制器驱动**。MITM 只需响应 HCI 事件：`IO Capability Request`（回 DisplayYesNo / NoInputNoOutput）、`User Confirmation Request`（Just Works 自动 / Numeric 经 delegate 两边确认）、`Link Key Notification`（存）、`Link Key Request`（查）。+ `Authentication Requested` / `Set Connection Encryption`。**全在 HCI 边界内，零协议栈耦合**。
- **BLE SMP**：主机层协议（L2CAP CID 0x06），控制器只做 `LE Enable Encryption` / `LE LTK Request`。MITM **自带最小 SMP**：
  - 只实现 **LE Secure Connections**（Just Works + Numeric Comparison；Numeric 本就 SC-only）。**不做 legacy pairing**（后续）。
  - 需要：Pairing PDU 编解码、P-256 ECDH、`f4`/`f5`/`f6`/`g2`（AES-CMAC，规范定义的纯函数）、DHKey check。
  - SMP PDU 经 ACL relay 的 CID 分流交给本模块；本模块自己封 L2CAP 0x06 帧 + `send_acl_data`。
  - 完成后通过 `LE Enable Encryption`/响应 `LE LTK Request` 开本侧链路加密。

### 3.1 SC 抗 MITM 与配对范围

SC 的抗 MITM 靠人验证；**两端都在测试者手上**时可配合完成：Numeric Comparison 两侧都点确认（数字不同也确认）。v1 = Just Works + Numeric Comparison（BLE SC / BR SSP）。Passkey Entry / OOB / BLE legacy 为后续。

**操作前提**（runbook）：手机若曾绑过真目标，先**删旧配对记录**。

---

## 4. 架构

### 4.1 拓扑与角色

```
   ┌────────┐  link 1 (加密)   ┌──────────────── MITM 应用 ─────────────┐  link 2 (加密)  ┌────────┐
   │  手机  │◄════════════════►│ HCIController B        HCIController A  │◄═══════════════►│ 目标   │
   │ Phone  │ 广播/page-scan   │  (下游/伪装侧)           (上游/连目标)   │ central/page    │ Target │
   └────────┘ (本地配对终结)   │       │                       │         │ (本地配对终结)  └────────┘
                               │       └──── ACL relay 双向 ────┘         │
                               │  重组 → CID 分流(SMP本地/signaling透传/   │
                               │         ATT+动态转发) → 抓包 → 重分片     │
                               └─────────────────────────────────────────┘
```

### 4.2 模块布局（全部在应用命名空间）

```
pybluehost/cli/app/mitm/
  __init__.py
  cli.py            # `pybluehost app mitm` 入口(argparse);复用 cli/_lifecycle + _transport
  relay.py          # MitmRelay 编排:两个 HCIController、三阶段、断链传播
  acl.py            # ★ ACL 重组(PB flag) → L2CAP CID 分流 → 重分片到对侧 buffer;BLE/BR 共用
  recon.py          # recon:BLE 扫描 / BR inquiry(裸 HCI) → ClonedIdentity
  impersonate.py    # 广播 / inquiry-scan+page-scan 配置(裸 HCI);可选地址克隆
  address.py        # 可选(--clone-address):BLE LE Set Random Address / BR vendor Write_BD_ADDR + 能力探测
  capture.py        # 抓包 tap:btsnoop(复用 BtsnoopSink)+ trace;v1 只观测
  pairing/
    smp.py          # 最小 BLE SMP:SC Just Works + Numeric Comparison(app 自带)
    crypto.py       # P-256 ECDH + f4/f5/f6/g2 (AES-CMAC);用项目 crypto 库,不引 ble/
    ssp.py          # BR SSP 终结:HCI 事件处理 + link key store
    delegate.py     # PairingDelegate:confirm_numeric(两侧)
  # —— 后续阶段(v1 不实现,仅在 acl.py tap 点预留 seam)——
  # intercept.py    # InterceptionPipeline(改写) / rules.py / hooks.py
docs/
  MITM.md           # runbook:伪装侧芯片选型、双 adapter、删旧 bond、SC 操作、btsnoop 查看
```

> 入口可在 `cli/app/__init__.py` 注册 `mitm` 子命令，逻辑全在 `cli/app/mitm/` 子包内，与协议栈隔离。

---

## 5. ★ ACL Relay 核心（acl.py，BLE/BR 共用）

挂在每个 `HCIController` 的 `set_upstream(on_acl_data=...)`。对每个 `HCIACLData`：

1. **重组**：按 PB flag + L2CAP basic header 2 字节 length，拼成完整 L2CAP PDU（len+CID+payload）。
2. **按 CID 分流**：

   | CID | 处理 |
   |-----|------|
   | `SMP (0x06)` | **本地终结** → 交本侧 `pairing/smp.py`；不转发（BR 无此项，SSP 走 HCI 事件） |
   | `signaling (0x01 BR / 0x05 LE)` | **原样转发**（L2CAP 端到端透明 → 动态 channel 含 RFCOMM/SDP 由两端直接协商，零 CID 逻辑） |
   | `ATT (0x04)` / 动态 CID | **抓包 + 转发** |

3. **抓包**：转发 PDU → `capture.py`（btsnoop + trace），v1 只读。**改写 seam**：未来此处替换为 InterceptionPipeline。
4. **重分片**：按**对侧** controller 的 `acl_packet_length`/`le_acl_packet_length` 重切 HCI ACL 分片（首片+continuation）→ 对侧 `send_acl_data`。
5. **断链传播**：监听 HCI Disconnection Complete，一侧断 → 拆另一侧 + 结束 relay。

> `pairing/smp.py` 发 SMP PDU 时同样经 acl.py 的封帧路径（封 L2CAP 0x06 + `send_acl_data`）。

### 5.1 已知限制
- 透传/抓包粒度 = L2CAP PDU。LE CoC / BR 跨多帧的完整 SDU 不重组（透传不受影响，深度改写时再补）。
- 地址克隆可选：默认用自身地址 + 克隆应用层身份即可；仅 BR 重连/地址锁定需 opt-in + 可写芯片（§3.1 表见下）。

---

## 6. 三阶段编排（relay.py）

`MitmRelay` 持有上下游两个 `HCIController`（各 `transport` 一个），骨架 BLE/BR 共用：

1. **recon**：上游侦查目标 → `ClonedIdentity`。
   - BLE：`LE Set Scan` + 收 adv report，抓 `address/type/adv_data/scan_rsp/name?`。
   - BR：`Inquiry` + `Remote Name Request`，抓 `bd_addr/class_of_device/eir/name`。
2. **impersonate**：下游套 `ClonedIdentity`（用自身地址）。
   - BLE：写 adv data + scan rsp → `LE Set Advertise Enable`。
   - BR：写 CoD + EIR + 本地名 → 开 inquiry scan + page scan。
   - 可选 `--clone-address`：BLE `LE Set Random Address`；BR vendor `Write_BD_ADDR`（前置探测，不支持则 fail-fast）。
3. **relay**：
   - 手机连入下游 → 作 responder 配对（BLE app SMP / BR HCI SSP；JW 自动 / Numeric 经 delegate）。
   - 上游连目标（BLE connect / BR page）→ 作 initiator 配对。
   - 两链路加密就绪 → 武装双向 ACL relay（§5）→ 透传。任一链路断 → 干净拆链。

---

## 7. 抓包（capture.py）

v1 **只观测不改写**。被中继的每条 L2CAP PDU 经 tap：
- `BtsnoopInterceptor`（默认开）：复用 `core.trace.BtsnoopSink`，两侧明文写一个 btsnoop（方向标注 PHONE↔TARGET），Wireshark/Ellisys/PTS 可看。
- `TraceInterceptor`：复用 trace 彩色输出。

改写（规则 + hook）= 后续阶段，seam 见 §5 第 3 步。

---

## 8. 地址克隆芯片对照（仅 --clone-address）

| 芯片 | 写 BD_ADDR | 备注 |
|---|---|---|
| Broadcom/Cypress (BCM20702A0/A1) | ✅ 推荐 | vendor `0xFC01`，临时(掉电还原)。Asus USB-BT400 / Plugable USB-BT4LE / IOGEAR GBU521 |
| CSR8510 (CSR 4.0) | ✅ 备选 | PSKEY `0xFC00`，持久(需还原)。⚠️ 假货多 |
| Intel (AX200/AX210/8260…) | ❌ | OTP 锁死只读 |
| Realtek (RTL8761B/BU) | ⚠️ | 写址不稳定 |

BLE 克隆地址用标准 `LE Set Random Address`（全芯片）。默认模式两个任意 dongle 即可；上游不改址。vendor 写址实现放在 app 内（`address.py`），**不污染** `hci/vendor/`。

---

## 9. CLI（cli/app/mitm/cli.py）

```
pybluehost app mitm \
  --upstream   usb:vendor=intel       # HCIController A → 连目标 \
  --downstream usb:index=1            # HCIController B → 对手机冒充 \
  --target     AA:BB:CC:DD:EE:FF      # 或 --target-name 扫描匹配 \
  --transport-mode le|bredr|both      # 默认 both \
  --clone-address                     # 可选:套用目标地址(BR 需可写芯片);默认用自身地址 \
  --btsnoop    capture.btsnoop        # 默认按时间戳命名 \
  --pairing    just-works|numeric
```

复用 `cli/_lifecycle.add_common_arguments` + `cli/_transport.parse_transport_arg`（上下游各一次）。

---

## 10. 测试策略（TDD）

**虚拟三角**（全 HCI 层）：`target` / `mitm`（两个 HCIController）/ `phone`。
- BLE：两条 `hci/virtual_link.py` 桥接 target↔mitm-upstream、mitm-downstream↔phone。
- BR：`hci/virtual_classic_link.py`。
- **target/phone 用完整 `Stack`（含真 SMP/SSP）当测试夹具**，MITM 用 app 内最小 SMP/SSP → 顺带验证 app SMP 与协议栈 SMP 的**互操作**。

- **单元测试**
  - `acl`：HCI 分片重组、PB flag、跨不同 buffer 重分片、CID 分流策略表、断链传播（BLE/BR 参数化）。
  - `pairing/smp`：SC JW + Numeric 配对流程、f4/f5/f6/g2 用 SIG 测试向量校验、DHKey check。
  - `pairing/ssp`：HCI 事件序列驱动 JW + Numeric、link key store。
  - `pairing/crypto`：f4/f5/f6/g2/ECDH 测试向量。
  - `recon`：BLE 扫描 / BR inquiry → ClonedIdentity 保真。
- **e2e**（`tests/e2e/`）
  - BLE 透传：phone 经 MITM 对 target scan→connect→pair(JW)→ATT 读写，数据原样到达 + btsnoop 落盘。
  - BR 透传：phone 经 MITM 对 target inquiry→connect→SSP(JW)→SDP browse + RFCOMM echo。
  - Numeric Comparison：两侧 delegate 确认，配对完成 + 透传贯通（BLE/BR 各一）。
  - 断链：一侧断 → 另一侧干净拆链，无悬挂 task。

**完成标准**：单测 + e2e 全 PASS（virtual 自动跑）；真硬件双 `--transport=usb` 适配器手动验证（adapter 到货后）。

---

## 11. 分期与 Plan 拆分（细化留给 writing-plans）

v1 = BLE + BR/EDR 透传 + 抓包，预计 4 个 Plan：

1. **MITM-1 应用骨架 + ACL relay 核心 + capture**：双 HCIController 装配（裸 hci，不用 Stack）+ acl.py 重组/重分片/CID 分流/断链 + btsnoop/trace tap。独立单测。
2. **MITM-2 BLE 路径**：recon 扫描 + impersonate 广播 + **app 内最小 SMP**(SC JW + Numeric) + 逐链路加密 + 虚拟三角 e2e。
3. **MITM-3 BR/EDR 路径**：inquiry recon + inquiry/page-scan impersonate + **SSP 终结(HCI 事件 + link key store)** + 可选 vendor Write_BD_ADDR + VirtualClassicLink 三角 e2e。
4. **MITM-4 CLI + Numeric delegate + 文档**：`app mitm`(le/bredr/both) + Numeric 交互 + `docs/MITM.md` runbook。

**后续阶段**：改写能力（InterceptionPipeline + 规则 + hook）、Passkey Entry / OOB / BLE legacy、CoC/BR 完整 SDU 重组。

---

## 12. 风险与缓解

| 风险 | 缓解 |
|------|------|
| app 内最小 SMP 实现 bug | f4/f5/f6/g2/ECDH 用 SIG 测试向量单测；虚拟三角与协议栈真 SMP 互操作 e2e |
| 重分片实现 bug（B 唯一新底层依赖） | 单测覆盖跨 buffer、首/续分片、边界长度；BLE/BR 参数化 |
| 需地址克隆但芯片不能写 BD_ADDR | 仅 `--clone-address` 相关;默认模式不依赖;opt-in 时探测 + fail-fast 给硬件指引（§8） |
| 手机缓存旧 bond | runbook 先删配对记录 |
| Numeric 需人工两侧确认 | delegate + CLI 交互提示 |
| 仅限授权场景 | spec/CLI/runbook 显著标注"授权测试专用" |
