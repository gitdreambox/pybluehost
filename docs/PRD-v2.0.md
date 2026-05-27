# PyBlueHost PRD v2.0 — Classic Audio Profiles

**版本**：v2.0
**日期**：2026-05-27
**状态**：草案（brainstorm 已确认主线，待评审）
**前置版本**：[PRD v1.0](PRD.md)（已完成 31 个 Plan，BLE 全栈 + Classic 基础设施已就位）

---

## 1. v2.0 主线

补齐 **Bluetooth Classic 音频协议**栈，让 PyBlueHost 能与蓝牙耳机、音箱、手机做音频互联——包括音乐流（A2DP）+ 远程控制（AVRCP）+ 通话协议层（HFP/HSP）。

### 与 v1.0 的关系

v1.0 已经把 Classic baseband（HCI / L2CAP / RFCOMM / SDP / GAP / Secure Connections / SPP）做完。v2.0 在这之上加 **应用层音频 profile**，不动 baseband。

### 不动 v1.0 的承诺

- 现有 BLE 全栈、Classic baseband、Profile 框架、CLI、Trace、状态机框架不修改公开 API
- v2.0 的新代码全部加在 `pybluehost/profiles/classic/` + `pybluehost/audio/` + 新 CLI 命令
- v1.0 的 `Stack.from_usb()` / `Stack.virtual()` 等工厂保持不变，新 profile 注册走 `Stack.register_profile()` 现有机制

---

## 2. 目标用户与场景

继承 v1.0 用户画像，新增场景：

| 场景 | 用户 |
|---|---|
| 用 PyBlueHost 当蓝牙音箱接手机推送音乐 | 蓝牙音频学习者、音频协议测试工程师 |
| 用 PyBlueHost 模拟蓝牙耳机连手机听音乐 | 同上 |
| AVRCP 控制：从 PyBlueHost 远程控制手机播放/暂停/音量 | 测试工程师 |
| 从 PyBlueHost 把电脑本地音频流到真蓝牙耳机 | 一般开发者、demo 场景 |
| HFP 协议状态机验证（不需真打电话，看 AT 交互） | 协议测试工程师、嵌入式开发 |
| HFP/HSP SDP discovery + SLC 建立的一致性测试 | PTS 准备工作（v2.x） |

---

## 3. v2.0 功能范围

### 3.1 A2DP（Advanced Audio Distribution Profile）

**协议层（AVDTP）**：
- AVDTP signaling channel（PSM 0x0019）：DISCOVER / GET_CAPABILITIES / SET_CONFIGURATION / OPEN / START / SUSPEND / CLOSE / ABORT
- AVDTP streaming channel：Media packet 帧化（RTP-like header + codec payload）
- SEID（Stream Endpoint ID）管理

**Profile 层（A2DP）**：
- **Source + Sink 双角色**
- SDP record 注册（A2DP Source UUID 0x110A / Sink UUID 0x110B）
- Codec capability 协商（Mandatory SBC + Optional AAC）
- 流控（基于 L2CAP credit）

**支持的 codec**：
- SBC（Sub-Band Coding，A2DP Mandatory）—— 编码 + 解码，纯 Python
- **AAC 推 v2.x 单独子项目**（A2DP Optional；Apple/Android 高品质音乐场景需要；libfdk-aac 跨平台分发头痛，单独评估）

**用户场景 CLI**：
- `pybluehost app a2dp-source <wav-file>` —— 模拟手机，把 WAV 文件推到对端
- `pybluehost app a2dp-sink --output=<wav-file>` —— 模拟耳机，接对端流写入文件
- 装了 `extras=audio` 后追加 `--play` / `--mic` 参数支持 OS 音频设备直通

### 3.2 AVRCP（Audio/Video Remote Control Profile）

**协议层（AVCTP）**：
- AVCTP signaling channel（PSM 0x0017）
- Packet framing：IPID / Profile ID / message body
- Continuation 处理（large message fragmentation）

**Profile 层（AVRCP）**：
- **Controller + Target 双角色**
- AVRCP 1.6 (v1.6.x) PASS-THROUGH commands：PLAY / PAUSE / STOP / VOLUME_UP / VOLUME_DOWN / NEXT / PREVIOUS / FAST_FORWARD / REWIND
- AVRCP 1.6 Browsing channel（可选）—— Optional Sub-Plan
- Notifications：TRACK_CHANGED / VOLUME_CHANGED / PLAY_STATUS_CHANGED

**用户场景 CLI**：
- `pybluehost app avrcp-control --target=<addr> --cmd=play`
- `pybluehost app avrcp-target` —— 长跑，接受 controller 控制并打印事件

### 3.3 HFP（Hands-Free Profile）—— 协议层，**不含 SCO 音频**

**协议层（RFCOMM + AT command）**：
- RFCOMM 通道（HFP server channel 由 SDP 协商）
- AT command parser / formatter（AT+BRSF, AT+CIND, AT+CMER, AT+VGS, AT+VGM, RING, +CIEV, +CLIP, …）
- HFP 1.7+ feature negotiation
- Service Level Connection (SLC) 三阶段建立流程
- 通话状态机（idle / incoming / outgoing / active / held）

**Profile 层（HFP）**：
- **AG (Audio Gateway) + HF (Hands-Free) 双角色**
- SDP record 注册（AG UUID 0x111F / HF UUID 0x111E）
- SCO **link setup/teardown**（HCI `Setup_Synchronous_Connection`）—— 信道建立完，**不做音频 PCM 流**
- Codec negotiation 协议路径（CVSD / mSBC）—— **协议层完成，编解码 binary frame 接到 mock buffer**

**用户场景 CLI**：
- `pybluehost app hfp-test --role=HF --target=<phone-addr>` —— 跟手机建立 SLC、模拟接电话、看 AT 交互日志、SCO 建联成功后立即关
- `pybluehost app hfp-test --role=AG` —— 长跑，接受 HF 设备（headset）连入

**显式 NON-Goal**：
- 实时音频通路（麦克风采样 → CVSD/mSBC 编码 → SCO 帧；反向同理）
- 跨平台音频后端集成（WASAPI / PulseAudio / CoreAudio）
- SCO over HCI 适配器 quirk 适配（Intel/CSR/Realtek alt setting）

→ 这些全部 defer 到 v2.1（独立子项目，预计 ~6-7 周额外工作量）

### 3.4 HSP（Headset Profile）

**协议层**：
- HFP 的简化版本，复用 HFP 实现的大部分（AT command parser、RFCOMM 通道、SCO setup）
- 简化 AT 命令集：仅 AT+VGS / AT+VGM / RING / +CKPD

**Profile 层**：
- **AG + HS 双角色**
- SDP record（AG UUID 0x1112 / HS UUID 0x1108）

**用户场景**：
- 跟老款 headset 互联（HSP-only 设备已经不多，但 PTS 测试要求）

### 3.5 Codec 模块

独立模块 `pybluehost/audio/codec/`，与蓝牙协议解耦：

| Codec | 用途 | 实现 | 工作量 |
|---|---|---|---|
| **SBC** | A2DP mandatory（A2DP spec 强制） | 纯 Python（~500 行，参考 ETSI / BlueZ libsbc） | ~1 周 |
| **CVSD** | HFP/HSP narrow-band（HFP spec 强制；HSP 唯一 codec） | 纯 Python（~120 行 delta modulation） | ~3 天 |
| **mSBC** | HFP wide-band 16 kHz（HFP 1.6+ 可选；现代设备默认） | 纯 Python（SBC 配置成 wide-band，~150 行追加） | ~3 天 |

每个 codec 独立可测：用 ETSI test vectors 做单元测试。

**AAC 推 v2.x**：A2DP 协商时如对端要求 AAC 但本地未实现，自动降级 SBC。

### 3.6 sounddevice 集成（optional extras）

- 新增 `[project.optional-dependencies] audio = ["sounddevice>=0.4", "numpy>=1.24"]`
- `pip install pybluehost[audio]` 后激活 OS 音频设备直通
- A2DP source CLI 加 `--mic`（采集麦克风实时编码推送）和 `--play`（解码后扬声器播放）参数
- 未装 extras 时这些参数报清晰错误："audio extras not installed, use `pip install pybluehost[audio]` or use `--play=<file>`"

### 3.7 Profile/Codec 之外的小改进

| 项目 | 范围 |
|---|---|
| `pybluehost/profiles/classic/` 包结构 | 新建，沿用 `profiles/ble/` 的 YAML loader + decorator 模式 |
| SDP record 自动注册 | 每个 profile YAML 包含 SDP entry，由 Stack 启动时自动注册 |
| Tests/e2e Classic Audio 端到端场景 | A2DP source→sink、AVRCP control、HFP SLC，~6 个新 e2e 场景 |
| VirtualClassicLink 扩展 | 加 AVDTP / AVCTP / SCO setup signaling 透传（v1.0 只透传 ACL） |

---

## 4. v2.0 不做（显式 Non-Goal）

| 项目 | 推迟到 |
|---|---|
| HFP / HSP 实时 SCO 音频通路（PCM ↔ codec ↔ SCO 帧 实时） | **v2.1** |
| LE Audio (BAP / CIS / BIS / LC3) | 原 v4.0 计划，时间另议 |
| macOS 原生 HCI transport | v2.x 子项目，独立评估 |
| PTS IUT 一致性测试 | v2.x 子项目 |
| Ellisys / Teledyne LeCroy 分析仪集成 | v2.x 子项目 |
| 蓝牙 Mesh | 不规划 |
| AMP / PAL（BR+EDR 共存） | 不规划 |
| 多 codec 并行支持（同时跑 SBC + AAC 两条流） | 不规划 |

---

## 5. 架构

```
┌──────────────────────────────────────────────────────────────────┐
│  v2.0 Classic Audio Profiles (new)                               │
│                                                                  │
│   ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐│
│   │   A2DP     │  │   AVRCP    │  │    HFP     │  │    HSP     ││
│   │ Source+Sink│  │ Ctrl+Target│  │  AG + HF   │  │  AG + HS   ││
│   │            │  │            │  │ (AT cmds,  │  │ (subset of ││
│   │            │  │            │  │ no audio)  │  │  HFP)      ││
│   └─────┬──────┘  └──────┬─────┘  └─────┬──────┘  └─────┬──────┘│
│         │                │              │               │       │
├─────────▼────────────────▼──────────────▼───────────────▼───────┤
│  Transport protocols                                             │
│                                                                  │
│   ┌────────────┐    ┌────────────┐         ┌──────────────────┐ │
│   │   AVDTP    │    │   AVCTP    │         │  RFCOMM          │ │
│   │ (A2DP用)   │    │ (AVRCP用)  │         │  (existing v1.0, │ │
│   │ Signaling+ │    │  Control   │         │  used by HFP/HSP)│ │
│   │ Streaming  │    │            │         │                  │ │
│   └─────┬──────┘    └─────┬──────┘         └────────┬─────────┘ │
│         │                 │                          │           │
├─────────▼─────────────────▼──────────────────────────▼──────────┤
│  L2CAP (v1.0) ─── ACL (v1.0) ─── HCI (v1.0)                     │
├──────────────────────────────────────────────────────────────────┤
│  Codec library (new, independent, NO Bluetooth glue)             │
│                                                                  │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐│
│   │   SBC    │  │   CVSD   │  │   mSBC   │  │      AAC         ││
│   │ encode/  │  │ encode/  │  │ encode/  │  │ ctypes binding   ││
│   │ decode   │  │ decode   │  │ decode   │  │ (libfdk-aac)     ││
│   │ (pure py)│  │ (pure py)│  │ (pure py)│  │                  ││
│   └──────────┘  └──────────┘  └──────────┘  └──────────────────┘│
└──────────────────────────────────────────────────────────────────┘

Side-channel:  sounddevice (extras=audio) ── used only by CLI for A2DP
                                              play/record real-time
```

### 关键架构决策

1. **Codec 模块独立**：`pybluehost/audio/codec/` 不 import 任何蓝牙代码。能用作离线工具（ETSI vector 测试），也能让其他 Python 项目独立引用。
2. **HFP/HSP 不写 SCO 音频路径**：SCO link 建立 + tear-down + codec negotiation 信令做完，但 PCM ↔ codec ↔ SCO 帧的实时通路不实现。v2.1 单独做。
3. **AAC 用 ctypes 绑定 libfdk-aac**：纯 Python AAC 不现实。decoder-only 也接受（Source 端宣告支持 AAC 但发送时 fallback 到 SBC）。
4. **sounddevice 是 optional extras**：主代码 lazy import，CI 全套不依赖。
5. **复用 v1.0 RFCOMM**：HFP/HSP 跑在 RFCOMM 上，不重写。
6. **Profile YAML 注册**：沿用 v1.0 `profiles/ble/` 的 YAML loader + decorator 模式，新增 `profiles/classic/` 目录。

---

## 6. 角色与对应实现

每个 profile 实现 **双角色**：

| Profile | 角色 1（受控端 / 耳机侧） | 角色 2（控制端 / 手机侧） |
|---|---|---|
| A2DP | Sink（接收音频流） | Source（发送音频流） |
| AVRCP | Controller（发命令） | Target（接命令） |
| HFP | HF（Hands-Free，无线耳机） | AG（Audio Gateway，手机/车载） |
| HSP | HS（Headset） | AG（Audio Gateway） |

注意 A2DP Sink ↔ AVRCP Controller ↔ HFP HF ↔ HSP HS 通常组合在同一设备（耳机），反之亦然（手机）。CLI 提供组合 profile 启动选项。

---

## 7. CLI 命令清单（追加）

继承 v1.0 `pybluehost app` + `pybluehost tools` 两命名空间。v2.0 新增（仅 `app/`，`tools/` 不动）：

| 命令 | 角色 | 行为 |
|---|---|---|
| `app a2dp-source <wav>` | Source | 长跑，注册 SDP record，等连接，把 WAV 文件流到对端 |
| `app a2dp-sink --output=<wav>` | Sink | 长跑，注册 SDP record，接受 source 连接，写流到文件 |
| `app avrcp-control --target=<addr> --cmd=<play\|pause\|...>` | Controller | 一次性，发命令到对端 target |
| `app avrcp-target` | Target | 长跑，注册 SDP，接受 controller 命令并打印 |
| `app hfp-test --role=HF --target=<addr>` | HF | 一次性，建 SLC + setup SCO link + dump AT 交互 + 拆链 |
| `app hfp-test --role=AG` | AG | 长跑，接 HF 设备 |
| `app hsp-test --role=HS --target=<addr>` | HS | 一次性，类似 HFP-test 但 HSP 路径 |
| `app hsp-test --role=AG` | AG | 长跑，HSP gateway |

`--extras-audio` 装了后 a2dp-source/sink 加 `--mic` / `--play` 参数；未装时这些参数报清晰错误。

---

## 8. 技术约束（v1.0 之上的增量）

继承 v1.0 全部约束（Python 3.10+、asyncio、`uv` + `hatchling`），新增：

### 8.1 新依赖

```toml
[project.optional-dependencies]
audio = [
    "sounddevice>=0.4",   # OS audio device, A2DP play/record
    "numpy>=1.24",        # PCM buffer manipulation
]
# AAC codec: extra-extra
aac = [
    # libfdk-aac via ctypes; system lib required, no pip wheel
]
```

主代码 `import sounddevice as sd` 全部 lazy（在函数内 / try-except）。

### 8.2 AAC 外部依赖

`libfdk-aac` 通过 ctypes 加载：
- Linux：`apt install libfdk-aac2`
- macOS：`brew install fdk-aac`
- Windows：用户提供 DLL，文档说明放置路径

PyBlueHost 不预绑定 AAC 库（licensing 顾虑 + cross-platform 分发难）。

### 8.3 平台支持

- **Linux**（主开发平台）：已支持 v1.0 全栈；v2.0 不需要额外内核组件
- **Windows**：已支持 v1.0；v2.0 sounddevice 走 WASAPI 后端开箱即用
- **macOS**：仍为 v2.x 评估（与 v1.0 一致）

---

## 9. 成功标准（v2.0 收尾验收）

| 指标 | 目标 | 验证方式 |
|---|---|---|
| 跟真蓝牙音箱（如 JBL、小米、AirPods）互通 A2DP 音乐流 | 把 WAV 文件推过去能听到声音 | 手动测试，hardware survey 记录 |
| 跟真手机互通 A2DP（PyBlueHost 当 sink）| PyBlueHost 当蓝牙音箱接手机播放音乐，能听到 | 手动测试 |
| AVRCP 控制真手机播放 | 手机播放音乐时，PyBlueHost 发 PAUSE 能暂停 | 手动测试 |
| HFP SLC + SCO setup 跟真手机/真耳机一致 | 看到完整 AT 交互日志，SCO link Connect 成功 | 手动 + e2e |
| 全套 e2e 在 virtual 上通过 | 5+ e2e 场景在 `--transport=virtual` 下全 PASS | CI |
| SBC encoder/decoder ETSI vector 通过 | 标准测试向量编码/解码正确 | 单元测试 |
| CVSD / mSBC 编码与 BlueZ libfreebt 互通 | 同一段 PCM 编码后用 BlueZ 解码能还原 | 单元测试 + 手动 cross-check |
| Wireshark 能解码 PyBlueHost 生成的 btsnoop 中的 AVDTP / AVCTP / RFCOMM AT command | 手动用 Wireshark 打开看 | 手动 |
| Stack.virtual() 跑完整 A2DP source→sink 流程 | 10 行 Python 完成 SBC encode + AVDTP signaling + streaming + SBC decode | API 易用性 |

---

## 10. 时间估计

| 阶段 | 内容 | 工作量 |
|---|---|---|
| Plan A.1 | Codec 模块（SBC + CVSD + mSBC，纯 Python） | ~2 周 |
| Plan A.2 | A2DP + AVDTP + SBC 集成 + virtual link extensions | ~3-4 周 |
| Plan A.3 | AVRCP + AVCTP | ~2-3 周 |
| Plan A.4 | HFP 协议层 + SCO file loopback（含 HCI SCO Data Packet + WAV 读写 worker，含 CVSD/mSBC encode/decode） | ~4.5 周 |
| Plan A.5 | HSP 协议层（含 SCO loopback；HSP 用 CVSD） | ~1 周 |
| Plan A.6 | sounddevice 集成 + CLI + 文档 + 收尾 | ~1.5 周 |
| **合计** | | **~14-17 周（~3.5-4 个月）** |

按 vertical slice 排，每个 Plan 落地都给用户可见的 milestone（A2DP 跑通约 5-6 周后；AVRCP 约 8 周；HFP 协议 + SCO loopback 约 12.5 周；HSP + CLI 约 14-17 周）。

**v2.0 不含**实时 OS 音频接入 + USB Alt Setting/vendor 命令 quirk 适配 + AAC codec——见 design spec §12，留 v2.1+。

---

## 11. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| HFP AT command 兼容性（不同厂商手机/车载有非标扩展） | SLC 建立失败或 corner case | v2.0 只覆盖 HFP 1.7 spec 强制 + 主流 OEM 通用扩展；非主流扩展看到 unknown AT 命令记日志不中断 |
| AVDTP signaling state machine 复杂 | 状态机 bug 难复现 | 沿用 v1.0 `StateMachine[S, E]` 框架，状态转换有日志；e2e 多组合场景覆盖 |
| 真硬件互通验收依赖手动测试 | 没法 CI 自动验证 | v2.0 收尾要求手工跑过至少 1 套：手机 + PyBlueHost；记录到 docs/hardware/audio-interop.md |
| Sub-Plan A.2 工作量可能 > 4 周（AVDTP signaling 复杂度被低估） | 时间表后移 | 第一个 Plan 完成时复盘估算；如果超 4 周，剩余 Plan 同比缩放或 ship "A2DP only + delay everything else" |

---

## 12. 跨 v2.0 与未来版本的关系

- **v2.1**：HFP/HSP 实时 SCO 音频通路（PCM ↔ codec ↔ SCO 帧）。需要 SCO over HCI 适配器兼容性工作 + sounddevice 实时音频后端。预计 6-7 周。
- **v2.x 子项目**（任何时间）：PTS IUT 测试集成、Ellisys/Teledyne 分析仪集成、macOS 原生 HCI、自托管硬件 CI。各自独立 brainstorm + Plan。
- **v3.0**：LE Audio (BAP / CIS / BIS / LC3)。原 PRD 路线图列为 v4.0，可按需提前。

---

## 13. 评审清单

- [ ] 主线方向（Classic Audio）是否正确？
- [ ] Profile 范围（全 4 个 dual-role）是否符合预期？
- [ ] Codec 范围（SBC + CVSD + mSBC，无 AAC）是否合适？
- [ ] HFP/HSP 不含 SCO 音频路径的 scope 边界是否清晰？
- [ ] 工作量估计（3.5-4 个月）是否合理？
- [ ] 14-17 周里程碑节奏是否符合期望？
- [ ] 显式 Non-Goal 是否覆盖到位？
- [ ] 与 v1.0 公开 API 不破坏的承诺是否够明确？
