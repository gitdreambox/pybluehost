# MITM 透传应用 Runbook（授权测试专用）

> ⚠ **仅限授权场景**：使用前确保你对**目标设备**与**手机**均有合法测试授权。本工具用于
> 授权安全研究 / 漏洞研究 / 教学。

## 用途

在目标设备与手机之间插入中间人（MITM），双向透传 BLE 与 BR/EDR ACL 数据，并把两侧明文
抓成 btsnoop。设计细节见
[`docs/superpowers/specs/2026-06-01-mitm-passthrough-design.md`](superpowers/specs/2026-06-01-mitm-passthrough-design.md)。

**定位**：独立应用（`pybluehost/cli/app/mitm/`），仅复用 `transport` + `hci`，不依赖协议栈上层。

## 架构

```
   手机  ◄═══ link1(加密) ═══►  下游 radio │ MITM │ 上游 radio  ◄═══ link2(加密) ═══►  目标
        MITM=peripheral/被inquiry          (重组→CID分流→抓包→重分片)         MITM=central/page
        (本地配对终结 SMP/SSP)                                              (本地配对终结 SMP/SSP)
```

- **上游**连真目标（BLE central / BR page）；**下游**对手机伪装（BLE 广播 / BR inquiry+page scan）。
- 加密**逐链路本地终结**：BLE 用 app 内最小 SMP（SC Just Works/Numeric），BR 用控制器 SSP（HCI 事件）。
- 数据通道（ATT / RFCOMM / SDP / 动态 channel）按 L2CAP PDU 透明转发；SMP（CID 0x06）本地终结不转发。

## 硬件

- **两个 USB 适配器**。默认模式下**任意两个**即可——上游不改址；下游用自身地址，只克隆
  应用层身份（名字 / service UUID / CoD / EIR），手机按内容发现并连接。
- **仅当 `--clone-address` 且涉及 BR/EDR 重连**时，下游（伪装侧）才需能写 BD_ADDR：

  | 芯片 | 写 BD_ADDR | 备注 |
  |------|-----------|------|
  | **Broadcom/Cypress (BCM20702A0/A1)** | ✅ 推荐 | vendor `0xFC01`，临时(掉电还原)。Asus USB-BT400 / Plugable USB-BT4LE / IOGEAR GBU521 |
  | **CSR8510 (CSR 4.0)** | ⚠️ | PSKEY 写(暂未实现)，假货多 |
  | **Intel (AX200/AX210/8260…)** | ❌ | OTP 锁死,不能做伪装侧 |
  | **Realtek (RTL8761B/BU)** | ⚠️ | 写址不稳定 |

  当前实现的可写厂商为 **Broadcom（0xFC01）**；Intel/未知厂商会 fail-fast 报错并建议改用 Broadcom。

## 操作前提

- 手机若曾与真目标绑定过，**先在手机上删除旧配对记录**，避免缓存的 LTK / IRK / link-key 冲突，
  让手机重新按名字发现 MITM（默认模式下无需克隆地址）。

## 运行

```bash
# 默认:自身地址 + 克隆应用层身份, Just Works, both(LE+BR)
pybluehost app mitm \
  --upstream  usb:vendor=intel \
  --downstream usb:index=1 \
  --target AA:BB:CC:DD:EE:FF

# 只做 BLE + Numeric Comparison(两侧终端确认)
pybluehost app mitm --upstream usb --downstream usb:index=1 \
  --target-name "Watch" --transport-mode le --pairing numeric

# 只做 BR/EDR
pybluehost app mitm --upstream usb --downstream usb:index=1 \
  --target AA:BB:CC:DD:EE:FF --transport-mode bredr

# 地址锁定的重连场景:克隆目标 BD_ADDR(下游需 Broadcom dongle)
pybluehost app mitm --upstream usb --downstream usb:index=1 \
  --target AA:BB:CC:DD:EE:FF --clone-address
```

参数：

| 参数 | 说明 |
|------|------|
| `--upstream` | 连目标侧 transport（如 `usb:vendor=intel`） |
| `--downstream` | 对手机伪装侧 transport（如 `usb:index=1`） |
| `--target` / `--target-name` | 目标地址 / 按名字匹配（至少一个） |
| `--transport-mode` | `le` / `bredr` / `both`（默认 both） |
| `--clone-address` | 套用目标地址（BR 需可写芯片）；默认用自身地址 |
| `--btsnoop` | btsnoop 输出路径（默认 `mitm-<时间戳>.btsnoop`；both 模式分 `le-` / `bredr-` 前缀） |
| `--pairing` | `just-works`（默认） / `numeric` |

## Numeric Comparison

`--pairing numeric` 时，每一侧会在终端打印 6 位数字并要求确认。授权测试中两端都在你手上，
即使两侧数字不同也可分别按 `y` 接受（原理见 spec §3.1：SC 的抗 MITM 依赖人对数字一致性的
检查，你作为两端的"用户"可主动接受）。

## 查看抓包

默认输出 `mitm-<时间戳>.btsnoop`（both 模式分 `le-` / `bredr-` 前缀）。用 Wireshark 打开，
或导入 Ellisys / PTS。方向标注 PHONE↔TARGET。

## v1 限制

- 当前只做**透传 + 抓包**；**改写（YAML 规则 / Python hook）为后续阶段**。
- 配对仅 **Just Works + Numeric Comparison（SC）**；Passkey Entry / OOB / BLE legacy 为后续。
- 抓包粒度 = L2CAP PDU；LE CoC / BR 跨多帧的完整 SDU 不重组。
- **`both` 模式**两条链路共用同一对 controller，`run_relay` 并发接线存在 `set_upstream` 覆盖，
  待真机验证时改为单 relay 同时处理 LE+BR 或分立 radio；LE / BR 单模式不受影响。
- recon / impersonate / 连接建立 / 逐链路加密的 HCI 时序为**结构性实现**，需在真硬件（双适配器）
  上验证；虚拟控制器不支持真实广播 / inquiry scan。

## 测试

```bash
uv run pytest tests/unit/mitm/ -v          # MITM 应用单元测试(全 PASS)
```

虚拟三角端到端（phone / MITM / target 三 Stack）e2e 因虚拟控制器不支持真实广播 / SSP 桥接而
**延后到真机**；单元测试覆盖了 ACL relay、SMP 密码学与状态机、SSP 事件终结、recon/impersonate
纯逻辑、CLI 与编排桥接。
