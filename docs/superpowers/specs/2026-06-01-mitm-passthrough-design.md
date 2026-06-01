# Design Spec — MITM 透传应用（BLE + BR/EDR，B 式 HCI-ACL 透传）

**版本**：design v0.2
**日期**：2026-06-01
**前置版本**：PRD v1.0 已完成 31 个 Plan，BLE 全栈（HCI/L2CAP/ATT/GATT/SMP/GAP）+ Classic baseband（含 VirtualClassicLink、SSP）已就位
**适用场景**：**授权**安全测试 / 漏洞研究 / 教学。两端设备（手机 + 目标）均在测试者掌控下。

---

## 1. 目标摘要

在**目标设备**与**手机**之间插入一个中间人（MITM），**双向透传 BLE 与 BR/EDR ACL 数据**：对手机冒充目标设备（BLE 广播克隆 / BR inquiry scan 响应），对目标设备冒充手机（central/initiator 连接）。中间拿到两侧各自解密后的明文，**v1 只做透传 + 抓包（btsnoop）**。

- **v1 范围**：BLE **和** BR/EDR 透传（同期交付）。**改写（YAML 规则 + Python hook）= 后续阶段**，本 spec 只预留 seam，不实现。
- **核心中继层**：**B 式 HCI-ACL 透传**——HCI ACL 层重组/重分片 + 按 L2CAP CID 分流。BLE 与 BR/EDR **共用同一套 acl_relay 核心**。
- **硬件**：两个 USB 适配器（真双 radio，两侧同时维持加密连接）。

### 1.1 需求决策表（brainstorming 结论）

| 维度 | 决定 |
|------|------|
| 首要目标 | 授权安全研究 —— **v1 透传 + 抓包**；改写后续 |
| 硬件拓扑 | 两个 USB 适配器（真双 radio） |
| 加密处理 | **逐链路本地终结**（两侧各自配对，中间拿明文） |
| 身份获取 | 自动侦查并克隆目标（BLE：扫描 address+adv+scan-rsp；BR：inquiry 抓 CoD+EIR+name） |
| 范围 | **BLE + BR/EDR 同期透传**；改写后续 |
| 抓包机制 | btsnoop 默认 sink（两侧明文）+ trace |
| 中继层 | **B 式 HCI-ACL 透传**（重组/重分片 + CID 分流），BLE/BR 共用 |
| v1 配对范围 | **Just Works + Numeric Comparison**（两边都确认的 delegate）；Passkey Entry / OOB 后续 |

---

## 2. 为什么选 B 式透传（决策依据）

A（复用 L2CAPManager 做 SDU 级中继）与 B（HCI-ACL 透传）对比，选 B：

- **B 不依赖** L2CAPManager 数据通道、GATT server、GATT 发现、ATT handle 复刻。ATT PDU 透明转发 → 手机直接发现目标真实 handle 布局，本栈上层 bug 无从波及克隆。
- **动态 channel 零 CID 逻辑**：signaling（CID 0x01 BR / 0x05 LE）原样转发 → L2CAP 在手机↔目标间**端到端透明协商**，双方直接学到对方 CID，中间不需要 CID 翻译表。对 BR 的 RFCOMM/SDP（动态 channel）尤其省事——当不透明字节流过。
- **BLE/BR 共用**：acl_relay 核心只认 HCI 分片边界 + L2CAP basic header（length+CID），与是 BLE 还是 BR **无关** → BR 透传增量极小。
- **B 唯一新依赖**：一段 **ACL 重组 + 重分片**代码（两侧控制器 buffer 大小不同，不能盲拷贝分片）。小且极易单测。

**共同依赖**（B 没省）：逐链路本地终结 SMP/SSP、GAP（BLE 广播/扫描 + BR inquiry/page scan）、HCI raw ACL 收发。

**已确认本栈能力**（`pybluehost/hci/controller.py`）：
- `set_upstream(on_acl_data=...)` 收原始 ACL；`acl_packet_length`/`le_acl_packet_length` 读 buffer 供重分片。
- `on_encryption_change`/`on_le_ltk_request`/`on_io_capability_request`/`on_user_confirmation_request`/`on_link_key_*` 全套配对钩子，支撑逐链路 SMP（BLE）与 SSP（BR）终结。
- BR 侧可复用 `hci/virtual_classic_link.py`（Inquiry/Connection/ACL/Auth/Encryption/Disconnect 六桥）做虚拟测试。

---

## 3. 加密终结与 SC 抗 MITM（前提）

加密由**控制器逐链路**完成，密钥逐链路独立。**SMP（0x06）/ SSP 信令绝不转发**——否则密钥在手机↔目标间协商，MITM 本侧控制器拿不到 LTK/link-key，无法对本侧链路开加密。两侧必须各自作为真实配对端点。

**SC 抗 MITM 的本质**：靠把人拉进来验证——

| 关联模型 | 抗 MITM | 两端都在测试者手上时 |
|---|---|---|
| Just Works | ❌ 无认证 | ✅ 协议层完全透明 |
| Numeric Comparison（仅 SC） | ✅ | ✅ 两侧数字不同（公钥不同 → g2 不同），但测试者两端都点确认 |
| Passkey Entry | ✅ | ✅ 测试者读出 passkey 桥接两侧（v1 不做） |
| OOB | ✅ | ⚠️ 读不到带外数据则卡住（罕见，v1 不做） |

**v1 实现范围**：Just Works + Numeric Comparison（`PairingDelegate.confirm_numeric` 两侧都确认）。BLE 用 SMP，BR 用 SSP，association 模型同名同理。

**操作前提**（写入 runbook）：手机若曾与真目标绑定，需**先删旧配对记录**（避免缓存 LTK/IRK/link-key 冲突）。

---

## 4. 架构

### 4.1 拓扑与角色

```
   ┌────────┐  link 1 (加密)   ┌──────────────── MITM ────────────────┐  link 2 (加密)  ┌────────┐
   │  手机  │◄════════════════►│ radio B (下游)         radio A (上游) │◄═══════════════►│ 目标   │
   │ Phone  │ MITM=peripheral/ │  广播/inquiry-scan      central/init  │ MITM=central/   │ Target │
   └────────┘  page-scan(BR)   │         │                    │        │  page-init(BR)  └────────┘
              (本地配对终结)    │         └── ACL relay 双向 ──┘        │ (本地配对终结)
                               │   (重组 → CID 分流 → 抓包 → 重分片)    │
                               └───────────────────────────────────────┘
```

- **上游（TARGET 侧 / radio A）**：BLE central+initiator / BR initiator(page)，连真目标；作 SMP/SSP **initiator** 配对。
- **下游（PHONE 侧 / radio B）**：BLE peripheral+advertiser / BR 可被 inquiry + page scan，套克隆身份等手机连入；作 SMP/SSP **responder** 配对。

### 4.2 模块布局

```
pybluehost/mitm/
  __init__.py       # 导出公共 API
  relay.py          # MitmRelay 编排:双 controller、三阶段、断链传播；BLE/BR 共用骨架
  clone.py          # recon + ClonedIdentity:BLE(address/adv/scan-rsp) + BR(bd_addr/CoD/EIR/name)
  acl_relay.py      # ★ ACL 重组(PB flag) → CID 分流 → 重分片到对侧 buffer；BLE/BR 共用
  capture.py        # 抓包 tap:btsnoop(复用 BtsnoopSink) + trace；v1 只观测不改写
  # —— 后续阶段（v1 不实现，仅预留 seam）——
  # interceptor.py  # InterceptionPipeline + InterceptedPdu（改写用）
  # rules.py        # YAML 规则引擎
  # hooks.py        # Python hook 加载
pybluehost/cli/app/
  mitm.py           # CLI 入口:`pybluehost app mitm`（--bredr / --le 选择或同时）
docs/
  MITM.md           # runbook:双 adapter、删旧 bond、SC 操作、btsnoop 查看
```

> 每侧构造一个轻量 `Stack`/`HCIController` 处理 SMP/SSP/signaling；数据通道 ACL 在到达本侧 L2CAPManager 前被 acl_relay 截走，仅需本地终结的 CID 回注本侧栈。

---

## 5. ★ ACL Relay 核心（acl_relay.py，BLE/BR 共用）

挂在每侧 controller 的 `on_acl_data`。对每个 `HCIACLData`：

1. **重组**：按 PB flag + L2CAP basic header 2 字节 length，拼成完整 L2CAP PDU（length+CID+payload）。
2. **按 CID 分流**：

   | CID | 处理 | 说明 |
   |-----|------|------|
   | `SMP (0x06)` | **本地终结** | 回注本侧栈；各链路独立 SMP；不转发 |
   | `signaling (0x01 BR / 0x05 LE)` | **原样转发** | L2CAP 端到端透明 → 动态 channel(含 BR RFCOMM/SDP) 手机↔目标直接协商 |
   | `ATT (0x04)` | **转发** | v1 观测 + 转发 |
   | 动态 CID（≥0x0040 / LE CoC / BR PSM 通道） | **转发** | 当不透明字节流；CID 已端到端一致 |

3. **抓包**：被转发 PDU → `capture.py` tap（btsnoop + trace），v1 只观测。
4. **重分片**：按**对侧** controller 的 `acl_packet_length`/`le_acl_packet_length` 重新切 HCI ACL 分片（首片 + continuation），经对侧 `send_acl_data` 发出。
5. **断链传播**：监听 HCI Disconnection Complete，一侧断 → 拆另一侧 + 结束 relay。

> **改写 seam（后续）**：第 3 步的 tap 点未来替换为 `InterceptionPipeline`，返回 PASS(可改 payload)/DROP/INJECT 后再进第 4 步。v1 tap 只读不改。

### 5.1 已知限制

- 透传/抓包粒度 = 重组后的 **L2CAP PDU**。LE CoC / BR L2CAP 跨多帧的完整 SDU 不重组（透传不受影响；将来深度改写时再补 SDU 重组）。
- public 地址 / BR BD_ADDR 改址依芯片 vendor 命令，**best-effort**；BLE random 地址克隆可靠。

---

## 6. 三阶段编排（relay.py）

`MitmRelay` 拥有上下游两套 controller（两个 `Stack.build(...)` 各绑一个 USB 适配器），骨架 BLE/BR 共用，按 transport 注入差异：

1. **recon**：上游侦查目标 → `ClonedIdentity`。
   - BLE：扫描抓 `address/address_type/adv_data/scan_response/name?`。
   - BR：inquiry 抓 `bd_addr/class_of_device/eir/name`。
2. **impersonate**：下游套 `ClonedIdentity`。
   - BLE：设地址（random 可靠 / public best-effort）→ 写 adv+scan-rsp → 开广播。
   - BR：写 CoD + EIR + 本地名 → 开 inquiry scan + page scan（应答手机的 inquiry/page）。
3. **relay**：
   - 手机连入下游 → MITM 作 responder 配对（Just Works 自动 / Numeric 经 delegate 两边确认）。
   - 上游连目标（BLE connect / BR page）→ MITM 作 initiator 配对。
   - 两链路加密就绪 → 武装双向 ACL relay（§5）→ 透传。
   - 任一链路断 → 干净拆链。

---

## 7. 抓包（capture.py）

v1 **只观测不改写**。被中继的每条 L2CAP PDU 经 tap：

- `BtsnoopInterceptor`（**默认开**）：复用 `core/trace.BtsnoopSink`，两侧明文写一个 btsnoop，Wireshark/Ellisys/PTS 可看；方向标注 PHONE↔TARGET。
- `TraceInterceptor`：复用现有 trace 彩色输出（可 `--pybluehost-trace` 控制）。

**改写（YAML 规则 + Python hook）= 后续阶段**，本 spec 不实现，seam 见 §5 注。

---

## 8. CLI（cli/app/mitm.py）

```
pybluehost app mitm \
  --upstream   usb:vendor=intel       # radio A → 连目标 \
  --downstream usb:index=1            # radio B → 对手机冒充 \
  --target     AA:BB:CC:DD:EE:FF      # 目标地址(或 --target-name 扫描匹配) \
  --transport-mode le|bredr|both      # 默认 both \
  --btsnoop    capture.btsnoop        # 默认按时间戳自动命名 \
  --pairing    just-works|numeric     # v1 支持
```

复用 `cli/_lifecycle.add_common_arguments` + `cli/_transport.parse_transport_arg`（上下游各一次）。

---

## 9. 测试策略（TDD，符合 CLAUDE.md）

**虚拟三角**：3 个 `Stack` —— `target` / `mitm`（双虚拟控制器）/ `phone`。
- BLE：用 `hci/virtual_link.py` 对接 target↔mitm-upstream、mitm-downstream↔phone。
- BR：用 `hci/virtual_classic_link.py`（Inquiry/Connection/ACL/Auth/Encryption/Disconnect 六桥）。

- **单元测试**
  - `acl_relay`：HCI 分片重组、PB flag、跨不同 buffer 重分片、CID 分流策略表、SMP/signaling/ATT/动态 各分支、断链传播。（BLE/BR 共用，参数化两种 transport。）
  - `capture`：btsnoop 写入正确、方向标注、PDU 不被篡改（透传保真）。
  - `clone`：BLE 扫描抓取 / BR inquiry 抓取 → ClonedIdentity 保真。
- **e2e**（`tests/e2e/`，transport-agnostic）
  - BLE 透传：phone 经 MITM 对 target 跑 scan→connect→pair(Just Works)→ATT 读写，数据原样到达 + btsnoop 落盘。
  - BR 透传：phone 经 MITM 对 target 跑 inquiry→connect→SSP(JW)→SDP browse + RFCOMM echo，数据原样到达。
  - Numeric Comparison：两侧 delegate 都确认，配对完成、透传贯通（BLE + BR 各一）。
  - 断链：一侧断 → 另一侧干净拆链，无悬挂 task。

**完成标准**：上述单测 + e2e 全 PASS（virtual 自动跑）；真硬件用双 `--transport=usb` 适配器手动验证（adapter 到货后）。

---

## 10. 分期与 Plan 拆分（细化留给 writing-plans）

**v1 = BLE + BR/EDR 透传 + 抓包**，预计 4 个 Plan（顺序依赖）：

1. **MITM-1 acl_relay 核心 + capture**：重组/重分片 + CID 分流策略表 + 断链传播 + btsnoop/trace tap。BLE/BR 共用，独立单测，不依赖编排。
2. **MITM-2 BLE 路径**：MitmRelay 三阶段骨架 + BLE clone(扫描) + BLE connect/advertise + 逐链路 SMP 终结 + 虚拟三角 e2e（Just Works）。
3. **MITM-3 BR/EDR 路径**：BR clone(inquiry/CoD/EIR) + page/inquiry-scan 装配 + 逐链路 SSP 终结 + VirtualClassicLink 三角 e2e。
4. **MITM-4 CLI + Numeric + 文档**：`app mitm`（le/bredr/both）+ Numeric Comparison delegate（BLE+BR）+ `docs/MITM.md` runbook。

**后续阶段（不在 v1 范围）**：改写能力（InterceptionPipeline + YAML 规则引擎 + Python hook）、Passkey Entry / OOB、CoC/BR 完整 SDU 重组以支持深度改写。

---

## 11. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 重分片实现 bug（B 唯一新依赖） | 单测覆盖跨 buffer 大小、首/续分片、边界长度；BLE/BR 参数化 |
| public/BD_ADDR 改址芯片不支持 | random 优先；public/BR 标 best-effort，runbook 说明芯片要求 |
| 手机缓存旧 bond | runbook 要求先删手机侧配对记录 |
| Numeric Comparison 需人工两侧确认 | delegate 钩子；CLI `--pairing numeric` 交互提示 |
| 仅限授权场景 | spec/CLI/runbook 显著标注"授权测试专用" |
