# BR/EDR MITM 测试方案 — 手机 ↔ 双 BE200 ↔ TWS 耳机

> **状态**：待用户审核（审过才执行）
> **日期**：2026-08-31
> **目标设备**：TWS 耳机 `98:1D:F9:90:11:1E`（Wuqi/Beetle 平台，固件可经 MCP 控制）
> **范围**：仅 BR/EDR（Classic）；**BLE 广播与连接推迟到下一阶段测试**。SCO/eSCO（HFP 通话音频）不做（非 ACL，透传不了）；**HFP profile 连接（SLC）要做**——RFCOMM over ACL，透传天然携带。

---

## 1. 测试目标与成功判据

四项全部达成才算整体 PASS：

| 目标 | 判据 |
|---|---|
| **链路透传打通** | 手机经 MITM 两跳连上耳机，SDP/L2CAP 双向透传正常，btsnoop 抓到完整流量 |
| **A2DP 音乐无丢包无卡顿** | adb 播音乐，**听感与手机直连基线一致**；capture 里 AVDTP 媒体流（RTP 序列号）**无丢包/乱序**，包速率与基线 trace 相当（量化分析见 G5） |
| **AVRCP + HFP profile 连接** | play/pause/next 经 AVRCP 生效；HFP SLC（RFCOMM AT 握手 BRSF→BAC→CIND→CMER）完成、手机显示通话音频已连接（**不测 SCO 通话**） |
| **配对/密钥捕获** | 两条链路（手机↔BE200#1、BE200#2↔耳机）的 link key 各自捕获并落盘；**链路 2 的 key 与耳机固件 log 里的 key 逐字节一致**（密码学级交叉验证） |

明确不做：篡改/注入实验、BLE（下一阶段）、SCO/eSCO 通话音频。

## 2. 技术路线（已定）

**纯 ACL/L2CAP 透传中继**（复用 `pybluehost/cli/app/mitm/` 现有 `AclRelay`），**不做 profile 层终结**。

关键依据：SDP、AVDTP（信令+媒体）、AVCTP、**RFCOMM（HFP SLC 的 AT 握手）**全部是 L2CAP over ACL；透明转发即可端到端打通，手机和耳机等效于"隔着一根线"直接协商（L2CAP signaling 也透传，CID 端到端一致无需翻译）。A2DP 媒体流不解码重编码，音质无损。配对在两条链路上各自独立 SSP（`SspTermination`），天然拿到两个独立 link key。**唯一透传不了的是 SCO/eSCO（独立物理链路，非 ACL）——本方案只要求 HFP profile 连接（SLC），不要求通话音频，恰好避开。**

备选退路（仅当透传实测撞墙，如 ACL 流控崩溃）：方案 B —— 两侧各跑完整 A2DP profile、SBC 解码重编码。工作量大一个数量级，非必要不动。

## 3. 拓扑与角色

```
手机(adb 控制) ⇄ BR/EDR ⇄ BE200#1 [downstream·伪装耳机] ═ PyBlueHost AclRelay ═ BE200#2 [upstream·主动连耳机] ⇄ BR/EDR ⇄ TWS 耳机 98:1D:F9:90:11:1E
                                                        ↑ 全程 btsnoop 抓包
```

- **BE200#1（downstream，对手机）**：套用耳机的 名字/CoD/EIR，开 inquiry+page scan 等手机来连。地址是 BE200#1 自己的 —— **Intel BD_ADDR OTP 锁死无法克隆**（`mitm/address.py` 只有 Broadcom 支持）；手机是全新配对（G0 会清旧 bond），不受影响。
- **BE200#2（upstream，对耳机）**：initiator，主动 `HCI_Create_Connection` 连耳机。
- **dongle↔角色映射**：G0 时先读两颗 BD_ADDR 确认 occurrence（现有记录：`94:53FF1E6AEE` / `5C67830704EE`），transport 用 `usb:8087:0036#N`。
- **耳机侧**：经 MCP server（`localhost:57666`，Wuqi.Beetle）控制：UART RTS 上下电复位（`connect` 自带时序）、CLI 进配对、log+HCI 抓取。COM 口执行时确认（当前可见 COM22/COM23，疑为 L/R 双耳）。

## 4. 观测点（四方对时）

| # | 观测点 | 来源 | 覆盖 |
|---|---|---|---|
| 1 | 手机侧 | adb pull btsnoop | phone↔#1 链路空口 |
| 2 | MITM | 我们的 `BtsnoopCaptureTap` | 两跳全部转发流量 |
| 3 | 耳机侧 | MCP `start_log_capture`（**log 流自带 HCI**） | #2↔耳机链路 + 固件内部状态 |
| 4 | 基线参考 | G0 直连时抓的手机 btsnoop | 无 MITM 的"正确行为"参照 |

定位问题时的看板顺序：先看 MITM capture 流量断在哪一跳 → 再用手机/耳机两侧 trace 对时确认是哪端没发/没收 → 耳机固件 log 看内部状态。

## 5. 递进关卡

任一关失败即停，按关卡边界定位，不带病往后走。

### G0 环境冒烟 + 直连基线
- 两颗 BE200 `tools usb diagnose` HCI Reset 通；读 BD_ADDR 确认角色映射。
- `adb devices` 通；手机开 BT、开 HCI snoop log（手动一次性）；**忽略耳机的旧配对**（全新配对前提）。
- MCP `connect` 耳机（RTS 复位）；~~确认进配对 CLI~~ —— **固件已配置开机自动进配对 + 断连自动回配对，无需 CLI**；只需保持 log capture 常开做固件 HCI 分析。
- **基线**：耳机自动进配对 → 手机**直连**耳机（不经 MITM）配对 + adb 播音乐 60s（T7 量化记录媒体流参照）→ adb pull btsnoop 存为参考 trace。
- **PASS**：基线音乐可听；参考 trace + 量化参照到手。

> **G0 环境探测结果（2026-08-31 已实测，全部 ✅）**：
> - 手机：一加 11 (PHB110)，adb 通，BT ON
> - BE200#1 (downstream) = `usb:8087:0036#1` = `94:53:FF:1E:6A:EE`；BE200#2 (upstream) = `usb:8087:0036#2` = `5C:67:83:07:04:EE`，均 HCI Reset OK、固件 OPERATIONAL
> - 耳机：COM22 = 目标耳 `98:1D:F9:90:11:1E`（log 里 `Local_Address` 确认）；CLI 通（fw=v1.0.0.0）；wpk 符号表已上传，Stream log + HCI 解码正常；文件捕获正常
> - **RTS 极性：高=芯片上电，低=掉电**（直接读串口时务必注意，别用自定义 RTS 操作时序干扰 MCP）

### G1 recon
- BE200#2 inquiry 找到 `98:1D:F9:90:11:1E`，抓 CoD/EIR/name（`bredr_recon.inquiry_for_target`，已有单测）。
- **PASS**：ClonedIdentity 的 address+CoD+name 三字段完整，name 与耳机一致。

### G2 impersonation 可见性
- BE200#1 写 CoD/EIR/name + 开 scan（`bredr_impersonate`，已有单测）；手机 adb 扫描。
- **PASS**：手机扫到同名设备且地址 = BE200#1 自己的地址（区别于真耳机地址）。

### G3 链路 + 配对 + 密钥捕获（核心关）
依赖代码任务 T1/T2/T4 完成。时序（全自动化）：
1. MCP RTS 复位耳机 → **固件自动进配对模式**（开机自进，无需 CLI）
2. BE200#2 发 `HCI_Create_Connection` 连耳机（T1）→ SSP → 拿 link key #2
3. 手机（adb）扫描 → 按地址选 BE200#1 → page → `Connection_Request` → accept（T2）→ SSP（对话框用 adb UI 自动化确认）→ 拿 link key #1
4. 两个 link key 落盘（T4）；与耳机固件 log 里的 key 比对
- **PASS**：两条 ACL up；两个 link key 落盘且 **key#2 与固件 log 逐字节一致**；手机显示已连接。
- **注意**：耳机被 #2 连上后通常自动退出 discoverable，手机只能看到 MITM —— 这规避了"两个同名设备"歧义；若耳机仍可见，adb 按地址精确选 #1。

### G4 SDP 透传
- 手机配对后自动 service discovery（或 adb 触发）；MITM capture 里看 SDP 请求穿两跳到耳机、响应返回。
- **PASS**：SDP 往返与 G0 基线 trace 语义一致；手机识别出 A2DP Sink。

### G5 A2DP 音乐质量（验收关，硬指标）
- adb 播音乐 ≥60s：`input keyevent 126`(play)/`127`(pause)。
- **量化判据（T7 分析脚本，对 capture 做）**：
  - AVDTP 媒体包的 **RTP 序列号连续、无丢包、无乱序**；
  - 媒体包速率（包/秒）与 G0 基线 trace 相当（容差 ±5%）；
  - 包间隔抖动：无超过基线 p99 的突发大间隔（卡顿的直接前兆）。
- **听感判据**：操作员听耳机，与基线无差异、无卡顿。
- **PASS**：量化三项全过 + 听感无异常。
- **流控观察项**：~328kbps SBC 码流下 relay 的 HCI ACL 流控（Number_of_Completed_Packets）行为——这是"无丢包"能否达成的物理基础，挂了先查这里。

### G6 AVRCP + HFP profile 连接
- AVRCP：adb `input keyevent 87`(next)/`88`(prev)/`127`(pause)；capture 见 AVCTP 流量、手机 UI 播放状态同步。
- HFP SLC：手机配对后自动向耳机 HFP AG 发起 RFCOMM 连接 + AT 握手；capture 里确认 `BRSF→BAC→CIND→CMER` 序列完成、手机显示"通话音频已连接"。**不发起通话、不测 SCO。**
- **PASS**：AVRCP 三键生效；SLC 四步 AT 序列在 capture 里完整可见。

### G7 四方对时（可选加固）
- adb pull 手机 btsnoop + MITM capture + 耳机 log/HCI + G0 基线，逐段比对。
- **PASS**：MITM 转发无丢包/无注入，三方流量与基线语义一致。

## 6. 执行前必须完成的代码任务

| # | 任务 | 位置/说明 |
|---|---|---|
| T1 | upstream 连接发起 | `orchestrator._run_relay_bredr` 等待前对 upstream 发 `HCI_Create_Connection`（page_scan_rep_mode/clock_offset 用 G1 recon 抓的值），失败重试 |
| T2 | downstream 连接接受 | 挂 `Connection_Request(0x04)` → 回 `HCI_Accept_Connection_Request`（常量 `HCI_ACCEPT_CONNECTION_REQ` 已有，`classic/gap.py:251` 有先例） |
| T3 | 断链联动 | 一侧 `Disconnection_Complete` → 另一侧发 `HCI_Disconnect`，避免半开链路（当前 `on_teardown=None`） |
| T4 | link key 落盘 | `SspTermination._on_lkn` 已存内存 dict，加导出 JSON（addr+key+key_type，双侧分文件） |
| T5 | adb 辅助脚本 | `scripts/mitm_phone.py`：BT 开关、扫描、配对对话框确认（input tap/uiautomator）、media keyevent、pull btsnoop |
| T6 | runbook | `docs/MITM_BREDR_RUNBOOK.md` 操作员手册（含本方案的时序编排和占位 CLI 的回填值） |
| T7 | 媒体流质量分析脚本 | `scripts/mitm_media_analyze.py`：解析 btsnoop 里的 AVDTP media channel，校验 RTP 序列号连续性（丢包/乱序）、统计包速率与间隔抖动，支持两个 trace（基线 vs MITM）对比——G5 量化判据的工具 |

T1–T3 是纯 HCI 接线，遵守 mitm 层 HARD RULE（不 import l2cap/ble/classic/gap/profiles/stack），各配 fake 单测。T7 是纯离线解析，单测用合成的 AVDTP 媒体流。TDD：先写失败测试再实现。

## 7. adb 自动化分级

- **adb 直接可做**：BT 开关（`cmd bluetooth_manager enable/disable`）、media 控制（keyevent 126/127/87/88）、`dumpsys bluetooth_manager` 状态查询、pull btsnoop
- **UI 自动化**（input tap / uiautomator dump）：配对确认对话框、点选设备连接
- **手动一次性**（无 root adb 做不到）：开发者选项开 HCI snoop log、"忽略设备"清旧 bond —— G0 做一次即可

## 8. 风险与已知限制

| 风险 | 缓解 |
|---|---|
| **BE200 被 page（BR peripheral 角色）可靠性未知** —— PTS 经验里 BE200/CSR 在 BLE peripheral 有缺陷（0x3E），BR page-accept 是首次验证 | G3 若挂先查这里；备选：换 CSR8510 当 downstream（能改地址还能顺带克隆） |
| **ACL 流控** ~328kbps 持续码流下 relay 的 buffer/Num_Completed_Packets 未实测——**"无丢包无卡顿"是硬指标，这是最大技术风险** | G0 基线 trace 里就量化记录媒体包速率/间隔作参照；G5 用 T7 脚本量化判定而非只凭听感；relay 侧若 buffer 不足，优先加发送侧流控排队，撞墙再退方案 B |
| 耳机 pairing mode 时效 | **固件已改：开机自动进配对 + 断连自动回配对，无超时关闭**（2026-08-31 用户确认）——此风险已消除 |
| 手机同时看到真耳机和 MITM 两个同名设备 | 时序规避（先连耳机后开手机扫描）+ adb 按地址精确选择 |
| 耳机 UART 静默 | **RTS 极性：高=上电、低=掉电**；MCP `connect` 自带正确时序，别绕过 MCP 直接操作 RTS |
| MCP server 中途不可用（服务崩溃/lease 卡死） | **备选路径：wquart-1.2.220 脚本直接抓 COM22 log**（2026-08-31 用户指定）；log 分析不受影响，仅失去 RTS 复位/CLI 能力（固件已自动进配对，不依赖 CLI） |
| SCO/eSCO 不可透传 | 明确出范围（HFP 只测 SLC profile 连接，不测通话音频） |

## 9. 交付物清单

- 本方案文档（评审用）
- T1–T4、T7 代码 + 单测（`tests/unit/mitm/`、`tests/unit/scripts/`）
- `scripts/mitm_phone.py`（adb 自动化）、`scripts/mitm_media_analyze.py`（媒体质量分析）
- `docs/MITM_BREDR_RUNBOOK.md`（操作员 runbook）
- 抓包产物：G0 基线 trace（含量化媒体流参照）、MITM btsnoop、耳机固件 log、手机 btsnoop、双侧 link key JSON、T7 分析报告
- 结果记录：每关 PASS/FAIL + 证据链接，录入 STATUS.md
