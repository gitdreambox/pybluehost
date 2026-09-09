# MITM 透传应用 Runbook（授权测试专用）

> ⚠ **仅限授权场景**：使用前确保你对**目标设备**与**手机**均有合法测试授权。本工具用于
> 授权安全研究 / 漏洞研究 / 教学。

## 用途

在目标设备与手机之间插入中间人（MITM），双向透传 BLE 与 BR/EDR ACL 数据，并把两侧明文
抓成 btsnoop。设计细节见
[`docs/superpowers/specs/2026-09-03-mitm-redesign-design.md`](superpowers/specs/2026-09-03-mitm-redesign-design.md)。

**定位**：独立应用（`pybluehost/cli/app/mitm/`），仅复用 `transport` + `hci`，不依赖协议栈上层。

## 架构（session.py 重构后）

```
   手机  ◄═══ link1(加密) ═══►  下游 radio │ MITM │ 上游 radio  ◄═══ link2(加密) ═══►  目标
        MITM=peripheral/被inquiry          (重组→CID分流→抓包→重分片)         MITM=central/page
        (本地配对终结 SMP/SSP)                                              (本地配对终结 SMP/SSP)
```

- **上游**连真目标（BLE central / BR page）；**下游**对手机伪装（BLE 广播 / BR inquiry+page scan）。
- 同一对 dongle **同时维持 LE + BR 两条链路**（`--mode both`），每只 controller 仅 2 个
  handle，ACL 按 handle 的 if/else 分发，无路由抽象。
- 加密**逐链路本地终结**：LE 用 `pairing/smp.py` 的 ScPairing（**仅 SC**，Just Works/Numeric）；
  BR 用控制器 SSP（`pairing/ssp.py` 的 SspTermination 处理 HCI 事件）。
- 每只 controller 的 `set_upstream` 由 session **唯一属主**：HCI 事件走 subscribe/unsubscribe
  多点订阅（旧 orchestrator 的 prev-forward 链式 hook 已废除），both 模式互不覆盖。
- 两条链路**独立重连互不联动**：断链只清理本链；LE 断不影响 BR 音频。
- accept 之后、对端建连完成之前的"两连窗口"，手机先发的 ACL 片段进**预缓冲**
  （按 handle 键控，deque maxlen=64），建链后按序灌入 relay——不重传的对端也不会卡死。

## 硬件

- **两个 USB 适配器**。默认模式下**任意两个**即可——上游不改址；下游用自身地址，只克隆
  应用层身份（名字 / service UUID / CoD / EIR / 广播数据），手机按内容发现并连接。
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
- key-log（默认 `mitm-keys.jsonl`）**不要删**：SSP link key 与 LE LTK 都在里面，跨重启复用
  才能重连零配对。首次运行文件不存在属正常。

## 运行（两步式：先 BR，再 LE，最后双链路）

### 第 0 步：确认两个适配器的 transport 名

```bash
pybluehost tools usb probe
# e.g. 输出片段:
#   ID 8087:0036
#     Transport Names:  usb:8087:0036#1
#   ID 8087:0036
#     Transport Names:  usb:8087:0036#2
```

每个在位适配器有一个 transport 名，形如 `usb:VID:PID#序号`（如 `usb:8087:0036#1`）。
任选两只：一只做**上游**（连真目标），一只做**下游**（对手机伪装）。下文用
`usb:<上游>` / `usb:<下游>` 指代（e.g. `usb:8087:0036#1` / `usb:8087:0036#2`）。
拔插后序号可能互换，`--clone-address` 模式才需要区分芯片（见「硬件」节）。

### 第 1 步：scan（探测，落盘身份 JSON；每台目标设备只需扫一次）

```bash
# BR 探测(最常用):按地址命中,不出列表
pybluehost app mitm scan --upstream usb:<上游> --mode bredr --target AA:BB:CC:DD:EE:FF
# e.g. pybluehost app mitm scan --upstream usb:8087:0036#1 --mode bredr --target AA:BB:CC:DD:EE:FF

# LE 探测:按地址命中
pybluehost app mitm scan --upstream usb:<上游> --mode le --target AA:BB:CC:DD:EE:FF
# e.g. pybluehost app mitm scan --upstream usb:8087:0036#1 --mode le --target AA:BB:CC:DD:EE:FF

# 全量发现:列表交互(编号 选定 / r 重扫一个窗口 / q 退出不保存)
pybluehost app mitm scan --upstream usb:<上游> --mode both
# e.g. pybluehost app mitm scan --upstream usb:8087:0036#1 --mode both
```

- 结果按段合并写入 `mitm-targets.json`（只更新本次扫到的段，其它段保留）。
- BR 名字拿不到时自动对选中设备补 RNR；列表空且 `r` 重扫也没用 → 让设备进配对模式，
  或改 `--mode le`（广播通常一直在发）。

### 第 2 步 A：BR 中继（最常用）

```bash
pybluehost app mitm relay --upstream usb:<上游> --downstream usb:<下游> --mode bredr
# e.g. pybluehost app mitm relay --upstream usb:8087:0036#1 --downstream usb:8087:0036#2 --mode bredr
```

手机连上伪装设备（按名字发现）→ relay 自动连真设备 → SSP 配对一次（key 存
`mitm-keys.jsonl`）→ A2DP 音频双向透传。**之后断开重连 = 零配对**（`Link_Key_Request`
直接用存储的 key 应答，不再走配对流程）。

### 第 2 步 B：LE 中继

```bash
pybluehost app mitm relay --upstream usb:<上游> --downstream usb:<下游> --mode le
# e.g. pybluehost app mitm relay --upstream usb:8087:0036#1 --downstream usb:8087:0036#2 --mode le
```

⚠ **注意：LE 广播/地址行为因设备而异**。个别 TWS 耳机只在 BR 连接建立后才发 LE 广播，
且 LE 地址 = BR 地址做固定偏移（如最高/最低 byte 各 +1）。如果你的设备 `scan --mode le`
扫不到、但 BR 正常：

1. 先把 BR 中继跑起来（第 2 步 A），让设备进入 LE 广播状态，再 `scan --mode le` 补扫；
2. 仍扫不到则手工在 `mitm-targets.json` 加 le 段（地址偏移规则从设备文档/抓包确认；
   `adv_hex` 用最小合法广播 `020106` 即可，手机按地址/名字连接）：

```json
"le": { "address": "AA:BB:CC:DD:EE:F9", "address_type": 0,
        "name": "<设备名>", "adv_hex": "020106" }
```

```text
e.g. 某设备 BR 地址 98:1D:F9:90:11:1E → LE 地址 99:1D:F9:90:11:1F
     (规则:BR 地址最高 byte 和最低 byte 各 +1)
```

3. 这类设备用 `--mode both`（见下）：BR 链路建立后设备开始 LE 广播，relay 的 LE 腿即可连上。

### 第 2 步 C：双链路 both（BR 音频 + LE GATT 同跑）

```bash
pybluehost app mitm relay --upstream usb:<上游> --downstream usb:<下游> --mode both
# e.g. pybluehost app mitm relay --upstream usb:8087:0036#1 --downstream usb:8087:0036#2 --mode both
```

手机同时可见伪装设备的 BR 与 LE；两条链**独立断连重连互不影响**（断 LE 不掉 BR 音频）。

### 退出 / 排错

- 正常退出：让手机先断开，relay 日志回到"等待手机发起连接"后 Ctrl-C（**不要带活链强杀**）。
- dongle 楔死：`scripts/dongle_reset.py` / `scripts/dongle_reset_csr.py` PnP 软复位（按芯片选）。

## ACL 内容替换（transform，可选）

`pybluehost/cli/app/mitm/transform.py` 底部 `DEMO_RULES` 加一条规则 → 重启 relay → 照常跑：

```python
DEMO_RULES = [
    # 等长替换(先验这个):把流中出现的字节串 A 换成 B,长度不变
    ReplaceRule(pattern=b"\x9c", repl=b"\x9d"),
    # 变长替换(再验长度头自动重写):3 字节换 5 字节
    # ReplaceRule(pattern=b"\x01\x02\x03", repl=b"\x01\x02\x03\x04\x05"),
]
```

验证：Wireshark 打开 btsnoop，确认空口抓包里 **A 已变 B**（btsnoop 记录的就是实际上线的
内容）；变长规则确认长度头按新 payload 重写。音频听感异常属预期（payload 被改）。
规则清空 = 恒等透传，零影响。方向/CID 过滤见 `ReplaceRule` 字段。

## 四 dongle 自闭环测试（无真机回归）

不接真手机/真耳机也能回归 relay：再取**两只额外适配器**，分别扮演 source(手机)与
sink(耳机)——角色都是普通应用，任意芯片组合皆可（注意各芯片能力差异，见下）。

```
source dongle(a2dp-source 推 WAV) ──page──► 下游(伪装 sink 身份)
                                               ⇕ relay
                                            上游 ──page──► sink dongle(a2dp-sink 收流写 WAV)
```

- **sink**：`app a2dp-sink --transport <sink> --output x.wav`（BR）或 `app gatt-server`
  （LE 外设）。
  e.g. `app a2dp-sink --transport usb:8087:0026#1 --output sink_rx.wav`
- **source**：`app a2dp-source --transport <source> --target <下游MAC> --play tone.wav`
  （BR；WAV 需 44.1k/16bit/立体声）或 `app gatt-browser --transport <source> --target <下游MAC>`（LE）。
  e.g. `app a2dp-source --transport usb:0A12:0001#1 --target 94:53:FF:1E:6A:EE --play tone.wav`
  （下游 MAC = relay 下游 dongle 自身地址,relay 启动日志里有）
- **scan 的 target = sink dongle 的地址**（e.g. `--target 80:xx:xx:xx:xx:xx` 那只 sink 的 MAC）。
- 芯片能力差异示例：CSR8510 是 BT 4.0——**不能协商 LE SC**（relay 的 LE 配对仅 SC,会被
  正确拒绝），只适合做 BR source 或 LE 无加密 GATT 场景。
- **僵尸链坑**：demo dongle 进程被杀后，controller 固件无主机仍维持 baseband 链（supervision
  不超时，relay 的 link_lost 永不触发）。唯一可靠拆法：对那只 dongle 做一次 open+HCI_Reset
  （如 `scripts/probe_dongles.py` 的 read_mac 即可），relay 会立即收到断链并优雅回收。
- 调试利器：`scripts/mitm_traced.py`——relay 同款 MitmSession + 每只 dongle 的全量 HCI
  btsnoop + 5s 流量/存活统计（`--trace-prefix` 区分文件）。

## 查看抓包

默认输出 `mitm-<时间戳>.btsnoop`（单文件含双链路，方向标注 PHONE↔TARGET）。用 Wireshark
打开，或导入 Ellisys / PTS。抓包在转发之后后台写盘，不进转发关键路径；btsnoop 内容 =
**实际上线的数据**（transform 替换后）。

## 现状与限制

- **真机已验证**：
  - 四 dongle 自闭环（2026-09-06）：scan 全发现+RNR 补名；BR golden——A2DP 300s 连续流
    90%+ 交付、无断链无楔死、断链回收多次正确；LE——伪装广播、LE_Create_Connection、
    GATT 发现穿 relay；两连窗口预缓冲使第二会话起播稳定。
  - 真 TWS 耳机（WQ7035_2223，2026-09-07）：全新 SSP 配对（key 落盘）、A2DP 真音频过
    relay、耳机自动回连被 tracker 采纳复用、**重连零配对**（存储 key 直接应答）、relay
    重启后 key 重载即恢复零配对、配对错误自愈重试、SC 能力镜像。
- **LE 配对仅 SC**（Just Works/Numeric）：对端拒绝 SC 时立即失败并日志说明（BT 4.0 设备如
  CSR8510 控制器不支持 SC，属预期）。Passkey Entry / OOB / BLE legacy 为后续。
- **LTK 按地址索引**：覆盖 public/static 地址重连；RPA（可解析随机地址）需 IRK 解析，未做。
- **真机 LE SC/LTK 重连闭环**：按当前范围暂缓（只要求无加密 GATT 可用，已验证）；单元测试
  已覆盖 LTK 存取往返与 wire-level SMP。
- transform 当前为**正则替换 demo**（改 `DEMO_RULES`）；复杂改写（YAML 规则 / Python hook）为后续。
- relay 运行中**不要强杀进程**（dongle 固件可能楔死只能拔插）：先让对端断链/停 source，
  确认 relay 日志回到"等待手机发起连接"再 Ctrl-C。异常退出后 dongle 楔死用
  `scripts/dongle_reset.py`（BE200）/`scripts/dongle_reset_csr.py`（CSR）做 PnP 软复位。

## 转发延迟

MITM 把空口路径变成 phone↔MITM↔target 两段，转发 RTT ≈ 链路1 + 主机处理 + 链路2。若目标设备
或 App 的响应超时只有几十毫秒，插入 MITM 有可能把本就接近超时的往返压过线——这是**协议物理特性**。
主机侧为降低开销已做：

- **抓包不挡转发**：`AclRelay` 先转发（`send_acl`）、后抓包；btsnoop 写盘（含 flush）在后台 drain
  任务里完成，磁盘 I/O 不计入转发关键路径。
- **数据通道无队列中转**：ATT/RFCOMM/动态 channel 在 `_handle` 内直接转发，仅 SMP 配对期走队列。
- **出站解耦 + 满则丢低水位（24/4）**：突发过载削峰不阻塞；flow control 背压按对侧控制器 buffer 发送。
- **待真机优化**：连接建立时主动协商**小 connection interval**（当前未控制），减小每跳"等下一个
  连接事件"的延迟；并加转发延迟 instrumentation。

## 测试

```bash
python -m pytest tests/unit/mitm -q        # MITM 单元测试(184,全绿)
```

单元覆盖：ACL relay（含 transform/fail-open）、SMP SC 密码学（spec KAT）与状态机、SSP 事件
终结、身份 JSON 往返、scan-all 解析、CLI 参数面、session 编排（分发/订阅/预缓冲/断链回收）。
真机回归用上面的四 dongle 自闭环流程。
