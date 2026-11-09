# PyBlueHost

> **适用对象**：接手本项目的任何开发者或 AI Agent，无论是否有历史上下文。

---

## 第一步：快速定位当前任务

**任何人接手时，按顺序执行以下命令：**

```bash
# 1. 查看项目整体状态
cat docs/superpowers/STATUS.md

# 2. 查看最近提交，了解进展
git log --oneline -10

# 3. 定位当前 Plan 文档，找到第一个未勾选步骤
# STATUS.md 的"快速定位"区块会告诉你当前 Plan 是哪个
# 打开对应 Plan 文档，搜索第一个 `- [ ]`，从那里继续
```

**状态符号说明：**
| 符号 | 含义 |
|------|------|
| ✅ | Plan 全部完成，代码已合并到 master |
| 🔄 | Plan 进行中，有人正在执行 |
| ⬜ | Plan 待执行，文档已就绪 |
| 📝 | Plan 文档待编写 |

---

## 项目概览

**PyBlueHost** — 面向开发者和研究者的专业级 Python Bluetooth Host 协议栈。

- **PRD**：[docs/PRD.md](docs/PRD.md)
- **架构设计**：[docs/architecture/README.md](docs/architecture/README.md)
- **任务状态**：[docs/superpowers/STATUS.md](docs/superpowers/STATUS.md)
- **Python 3.10+，asyncio，pytest，pyyaml**

### 协议栈层次（bottom-up）

```
core/ → transport/ → hci/ → l2cap/ → ble/ + classic/ → profiles/ → stack.py
```

协议栈按层次实现，但 **Plan 不必与层一一对应**。一个层可以拆成多个 Plan，只要各 Plan 之间没有代码冲突，就可以并行执行。拆分原则见下方"Plan 拆分原则"。

---

## 环境初始化（新开发者必读）

```bash
# 1. 安装 uv（如未安装）
pip install uv

# 2. 安装依赖（含开发依赖）
uv sync --extra dev

# 3. 初始化 SIG 数据 submodule（sig_db 测试依赖）
git submodule update --init

# 4. 运行全套测试验证环境
uv run pytest tests/ -q

# 预期输出：全部 PASS，sig_db 相关测试需要 submodule 才不会 skip
```

---

## 文档自维护规则（强制要求）

> **AGENTS.md（与 symlink CLAUDE.md 共用一份）和 README.md 是项目对未来 AI agent / 新接手者的承诺。让承诺过期的改动，必须在同一个 commit 里把对应文档刷新——不接受"以后再补"。**

### 何时必须改本文件（AGENTS.md）

| 触发 | 改哪里 |
|---|---|
| 新增 PRD 或大特性（v1.x / v2.x 等） | "已交付子系统"加一个 `###` 小节：是什么 / 入口在哪 / 怎么扩展 / runbook 链接 |
| Refactor 搬迁文件（如 Plan C.2/C.3 类的） | 改对应路径；**保留一行历史脚注**（"早期在 X，现已在 Y"），下次接手者搜旧路径也能定位 |
| 加 stack-level 公共 API（如 LE CoC manager 那批） | 加最少 3 行代码示例 + 测试位置 |
| 踩到 upstream / 项目隐含约定的坑 | 写进对应小节的"纪律"提示。**这种总结比技术指南更值钱**——用 session 时间换的 |
| 引入新术语 / 缩写 | 加小注解释（参考已有 BTP / WID / MMI / SLC 写法） |
| 发现 AGENTS.md 自己有错（路径搬过没改、类重名、命令删了） | **同一 commit 修掉**，commit message：`docs(agents): purge stale ref to X (now Y)` |

### 何时必须改 README.md

| 触发 | 改哪里 |
|---|---|
| 增 / 删 / 改名 `app` 或 `tools` 命令 | §1.3–1.10 对应小节的使用例 + "关键 CLI 命令一览"表 |
| 加新用户场景（如 Mesh / LE Audio） | 加 `## 1.X` 小节，按用途分组插在最匹配位置 |
| 改命令必填参数 / 默认值 | 修对应 `pybluehost app <cmd>` 代码块 |
| 真机硬件矩阵变化 | "已测试硬件"表 + "真机验证状态"表两处都改 |
| PRD 状态变化（草案 → 已交付 / 含真机 ✅） | "项目状态"小节 + 对应 PRD 文件头 `**状态**:` 字段 |

### 自动总结遇到的问题

任何 AI agent 在 session 中：

- 修了**根因非显然**的 bug → 在 "已知问题与经验" 章节加一行：`### Q: <现象> → A: <根因> / <commit-sha>`
- 一次 refactor 改了 ≥ 5 个文件 → 在对应子系统的 `###` 小节加"踩坑/约定"附注
- 上游文档跟项目内 plan 文档对不上 → 改 plan 顶部加 upstream-drift banner（参照 P.5/P.7/P.8 范式）；同时在 AGENTS.md 对应小节加"加新 X 前先 WebFetch upstream"
- 解决了非平凡的环境问题（如 `pybluehost/lib/sig` symlink workaround）→ 加进 "已知问题与经验" 章节

### Commit 前自查（改完文档跑一遍）

```bash
# 1. AGENTS.md 提到的所有路径都真实存在
grep -oE '[A-Za-z_/.][A-Za-z0-9_/.-]+\.(py|md|yml|yaml|toml)|pybluehost/[A-Za-z_/.-]+/?' AGENTS.md \
  | sort -u | xargs -I{} sh -c '[ -e "{}" ] || echo MISSING: {}'

# 2. README 引用的 CLI 命令都还活着
for cmd in $(grep -oE "pybluehost (app|tools) [a-z-]+" README.md | awk '{print $3}' | sort -u); do
  uv run pybluehost --help 2>&1 | grep -qE "[[:space:]]$cmd\b" || \
    uv run pybluehost app --help 2>&1 | grep -qE "[[:space:]]$cmd\b" || \
    uv run pybluehost tools --help 2>&1 | grep -qE "[[:space:]]$cmd\b" || \
    echo "stale CLI in README: $cmd"
done

# 3. 版本号 / pyproject / __init__ 一致
uv run pytest tests/unit/test_version_sync.py
```

任何一条报错 → 修完再 commit。

### 反例（❌ 不要这么干）

- 留 `TODO: 更新` 标记 → 上线即忘
- 用 `~~strikethrough~~` 保留旧内容 → 噪音；直接删
- 让 "v1.x 草案" 标签悬空 → PRD 真交付了立刻改 "已交付"
- 把会话过程（"试了 A 再试 B 最后用 C"）写进文档 → 只留最终决定，过程在 git log
- 在 STATUS.md 之外另抄一份 Plan 进度表 → 单一来源；AGENTS.md / README 引用即可
- 描述只用一次的 session 临时状态 → 只写永久结论

---

## 已交付子系统 — AI Agent 上手指南

> v1.0 PRD 之后又交付了 v1.1 / v1.2 Phase 1+2 / v2.0 / v2.1 等若干 PRD，下面是接手时必须知道的入口。详细命令使用例见 [`README.md`](README.md) §1.7–1.10；本节只讲"是什么、入口在哪、怎么扩展"。

### v1.1 Virtual Sniffer — live HCI 注入 Ellisys / WPS

`pybluehost.sniffer.*` 包 + CLI flag `--virtual-sniffer={ellisys,wps}`。Windows-only。代码已合并 master 并真机实测通过（CSR8510 + 真分析仪）。要改注入字节布局或加新分析仪后端：

- 后端 ABC：`pybluehost/sniffer/backend.py::SnifferBackend`
- 现成实现：`ellisys.py`、`wps.py`（用 ctypes 调 Live Import DLL）
- Spec 字段：`SnifferSpec` 在 `pybluehost/sniffer/spec.py`（注意：早期版本在 `cli/_sniffer_arg.py`，已在 Plan C.2 时反向依赖修复中搬迁）
- 操作员 runbook：[`docs/VIRTUAL_SNIFFER_VERIFY.md`](docs/VIRTUAL_SNIFFER_VERIFY.md)
- 分析仪集成笔记 + PowerShell 自动化 + Ellisys 烟测 trace：[`docs/sniffer/operator-runbooks/`](docs/sniffer/operator-runbooks/)（Ellisys/WPS 字节布局抓的原始 reverse 笔记，加新分析仪后端先读）
- **`pybluehost/tools/` 是 operator 本地 scratch 区**——`.gitignore` 显式排除（见 `.gitignore` 注释行）。用于堆 vendor SDK ZIP / EXE / 探索脚本，不进 wheel、不进 git。**别把 tracked 代码或 runbook 内容放这里**——runbook 进 `docs/sniffer/operator-runbooks/`、tracked CLI 进 `pybluehost/cli/tools/`、dev 脚本进 `scripts/`。

### v1.2 PTS IUT — 两阶段并存

PyBlueHost 当 PTS（Profile Tuning Suite）的 IUT。两条路径**都已实装、可以并存**：

#### Phase 1：手动 REPL（`pybluehost app pts-iut`）

适合**无 autoptsclient / 不想搭自动框架**的快速排查：

```bash
pybluehost app pts-iut -t usb
# 进 REPL：advertise / scan / connect <addr> / pair / notify / write / status …
# 操作员看 PTS MMI 提示 → 在 REPL 敲对应命令。
```

- 动作层：`pybluehost/pts/actions.py::IutActions`（async 方法集，**Phase 2 BTP 服务也复用同一层**）
- REPL：`pybluehost/pts/repl.py`（`parse_repl_command` + `run_repl`）
- PTS-mode 行为开关：`pybluehost/pts/config.py::PTSModeConfig` 5 个 opt-in flag（`disable_conn_updates` / `secure_pair_only` / `disable_sdp_on_le_pair` / `smp_options` / `smp_failure_at`）通过 `StackConfig.pts=` 启用，默认 `None` 时零影响
- PICS 生成：`pybluehost tools pics-gen -c <adapter>.json -o docs/pts/pics`
- 操作员 runbook：[`docs/PTS_RUNBOOK.md`](docs/PTS_RUNBOOK.md)

#### Phase 2：autoptsclient 自动驱动（`pybluehost app pts-tester`）

> **术语速查**：**BTP** = Bluetooth Test Protocol，autoptsclient ↔ IUT 之间的二进制 TCP 协议（5-byte frame header + payload）。**MMI** = Man-Machine Interface，PTS 弹给操作员的"请让 IUT 做 X"提示。**WID** = 每个 PTS test case 的 MMI 提示用 WID 编号标识（例如 WID 42）；upstream `wid/<group>.py` 已经把"WID 编号 → BTP 命令序列"的标准映射写好了，PyBlueHost 默认全套继承，只在行为偏差处覆盖（baseline 无覆盖）。**SLC** = Service Level Connection（HFP 三阶段握手 BRSF→BAC→CIND→CMER）。

适合**完整自动化 + CI 接入**。IUT 模块已对齐**当前 auto-pts master** 的 custom-IUT 契约（同步 iutctl + per-profile `set_pixits`/`test_cases` + BTP client 模式）。**BTP socket 方向：auto-pts 是 server（监听），PyBlueHost pts-tester 主动 `--connect` 连出**。

```bash
# 仓库根，装同一 Python 环境：auto-pts(autoptsclient) + pybluehost 都可 import
python autoptsclient-pybluehost.py \
    -i <pts-server-ip> -l <local-ip> \
    --pybluehost-transport usb:0A12:0001#1 \
    -c GAP/CONN/UCON/BV-06-C
# autoptsclient 内部:init(args) 建 Stack;每个 test case start() 开 BTPSocketSrv、
# spawn `pybluehost app pts-tester --connect <host>:<port>`、接受 dial-out、等 READY。
```

- BTP 协议层：`pybluehost/pts/btp/`（`protocol.py` 帧编解码 + `services/{base,core,gap,gatt,l2cap}.py` + `tester.py`）。`BtpTester` 支持两种模式：`--listen`（server，默认）与 `--connect host:port`（client，连 auto-pts BTPSocketSrv，**auto-pts 驱动走这条**）。
- **BTP 帧约定（已与上游逐字节对齐）**：成功响应 **echo 请求 opcode**、payload 只有数据；失败才用 opcode `0x00`(BTP_STATUS)+ 单字节 status。`tester.py::_dispatch` 里实现。⚠️ 早期版本对所有响应都回 `0x00`+status，会被 `send_wait_rsp` 当成 error——已修（commit 见 git log）。supported_commands 位图 **bit n = opcode n**;GAP settings 位 **LE=9 / ADVERTISING=10**;GATT chrc 发现顺序 **handle|value_handle|props|uuid_len|uuid**。
- IUT 模块（autoptsclient 加载的入口）：`auto_pts_project/pybluehost_iut/`
  - `iutctl.py` — **同步** `init(args)`/`cleanup()`/`get_iut()` + `PyBlueHostIutCtl` 类。`start(test_case)` 开 `BTPSocketSrv`、win32 下读 `getsockname()` 得 ephemeral port、spawn `sys.executable -m pybluehost app pts-tester -t <transport> --connect <host>:<port>`、`BTPWorker.accept()`;`wait_iut_ready_event()`(**无参数**,READY 事件须先于此被 BTPWorker 排队，**别在此前调 stack.core_init()**)。autopts import 全部延迟到方法内，CI 无 autoptsclient 也能 import。
  - `testcase.py` — `PyBlueHostTestCase(TestCaseLT1)`，仿 bluez `BTestCase`:cmds 前插 `iut.start`+`wait_iut_ready_event`，尾插 `stack.cleanup`+`iut.stop`。
  - `gap.py`/`gatt.py`/`l2cap.py`/`sm.py` — 各暴露 `set_pixits(ptses)`（遍历 `ixit.py` 的 `IXIT_<G>`)+ `test_cases(ptses)`(pre_conditions 用上游 `btp.*` helper + `stack.gap_init/gatt_init/l2cap_init`)。`sm.py` 已实装并接进 `__init__`（SM 无独立 BTP service，pairing 走 GAP service，但仍需注册用例）。
  - `__init__.py` — 用 **PEP 562 `__getattr__` 惰性**解析 `gap/gatt/l2cap/sm`(autoptsclient 靠 `getattr(autoprojects,'<profile>')` 找 profile 模块）；懒加载让 `import pybluehost_iut` 不依赖 autoptsclient。
  - `pics.py` — 对接口而言冗余（PICS 由 PTS workspace 提供），保留但 test_cases 不再读它。
  - `ixit.py` — 手写 IXIT_* 参数 dict;**operator 改这里的 `TSPX_bd_addr_iut`**(CSR8510 = `001A7DDA7111`)。
  - `wid/{gap,gatt,l2cap,sm}.py` — **函数式** WID 适配器 `<profile>_wid_hdl(wid, description, test_case_name)`，内部 `generic_wid_hdl(..., [__name__, 'autopts.wid.<profile>'])`:override 就在本模块写 `hdl_wid_<N>`（本模块在搜索路径最前，覆盖上游）。baseline 无覆盖。
- 入口脚本：仓库根 `autoptsclient-pybluehost.py`(`PyBlueHostClient(autoptsclient.Client)` + `PyBlueHostCliParser` 加 `--pybluehost-transport`)。
- 操作员 README：[`auto_pts_project/pybluehost_iut/README.md`](auto_pts_project/pybluehost_iut/README.md)（含 quickstart + 真机 step-by-step + troubleshooting 表）
- BTP upstream 校准：曾多次发现 plan 跟 upstream auto-pts 的 opcode 编号有出入（详见 plan 顶部 banner）；**未来加新 BTP service 之前先 WebFetch 一遍 `https://raw.githubusercontent.com/auto-pts/auto-pts/master/doc/btp_<service>.txt` 对齐**。WebFetch 受限时备选：`gh api repos/auto-pts/auto-pts/contents/doc/btp_<service>.txt --jq .content | base64 -d`，或本地 clone（本机已 clone 到 `%TEMP%/auto-pts`，只读参考）。

#### Phase 2 状态矩阵 + CI

- `scripts/pts_matrix.py`：管理 `docs/pts/results/matrix/<group>.yaml` 的 verdict（pass/fail/inconc/blocked/untested）+ 渲染 `docs/pts/results/SUMMARY.md`
- `scripts/ci_btp_smoke.py`：spawn pts-tester → 走 Core/GAP/GATT 命令序列做 plumbing 自检（不需要 PTS dongle）
- `.github/workflows/pts-virtual.yml`：每 push/PR 跑上面的 smoke + PTS 单测
- **真机 pass-rate** 留 operator：跑完一个 case 用 `python scripts/pts_matrix.py update docs/pts/results/matrix/<group>.yaml <case_id> --verdict=pass --last-run=YYYY-MM-DD --notes='…'` 录入

### v2.0 Classic Audio + v2.1 SCO 适配

A2DP / AVRCP / HFP / HSP 全实装。`pybluehost/profiles/classic/` 下：

- `a2dp.py` — A2DPSource / A2DPSink，用 `pybluehost/classic/avdtp/`（线协议）+ `pybluehost/audio/codec/sbc.py`（SBC 编解码，基于 BlueZ libsbc ctypes 绑定）
- `avrcp.py` — AVRCPController / AVRCPTarget，用 `pybluehost/classic/avctp/` + `pybluehost/classic/avrcp/`（**注意**：profile facade 在 `profiles/classic/avrcp.py`，线协议在 `classic/avrcp/` —— Plan C.3 把 AV* 三个包从顶层搬到 `classic/` 下）
- `hfp.py` / `hsp.py` — SLC + SCO link setup + CVSD/mSBC codec
- `_sco_loopback.py` — WAV-based SCO send/receive；`_sco_realtime.py`（v2.1 B.2 加）—— sounddevice 实时 mic/speaker
- `pybluehost/transport/usb/` 里的 Intel/Realtek 子类（v2.1 B.1）实现了 `prepare_for_sco(codec)` 自动切换 USB Alt Setting / 发 Realtek vendor cmd `0xFC8B`，所以 SCO 数据在 USB 上跑得通
- 集成 demo：`pybluehost app demo-phone` / `app demo-headphone` 在单进程里把 A2DP+AVRCP+HFP 三个 profile 串起来，配 `tests/e2e/test_integrated_demo.py`
- 操作员手册：[`docs/CLASSIC_AUDIO_E2E.md`](docs/CLASSIC_AUDIO_E2E.md)（含 adapter SCO quirk 矩阵）

### PHY / EDR 控制 + 双设备 throughput 基线

PHY 切换（BLE LE 1M ↔ LE 2M ↔ LE Coded）+ Classic EDR 包类型约束（2-DH / 3-DH）是为了双设备 throughput 基线测试加的，**也是任何想衡量"换 PHY 之后速度差多少"的工具的前提**。

```python
# BLE: 把活跃 LE 连接切到 LE 2M PHY
from pybluehost.hci.constants import LEPhyMask
result = await stack.gap.ble_connections.set_phy(
    handle, tx_phys=LEPhyMask.LE_2M, rx_phys=LEPhyMask.LE_2M,
)
# result.status == 0 → 成功；result.tx_phy/rx_phy 是协商后真用的 PHY

# Classic: 强制只能用 2-Mbps EDR（2-DH 包类型）
pt = await stack.gap.classic_connections.set_acl_packet_types(
    handle, allow_br=False, allow_2dh=True, allow_3dh=False,
)
# pt.status == 0 → 成功；pt.packet_type 是新生效的 mask
```

- **LE PHY**：`pybluehost/hci/packets.py::HCI_LE_Set_PHY` + `parse_le_phy_update_complete` + `LEPhyUpdateComplete`；controller listener `on_le_phy_update`；stack API `BLEConnectionManager.set_phy`
- **Classic EDR**：`pybluehost/hci/packets.py::HCI_Change_Connection_Packet_Type` + `parse_connection_packet_type_changed` + `ConnectionPacketTypeChanged`；controller listener `on_connection_packet_type_changed`；stack API `ClassicConnectionManager.set_acl_packet_types`
- **Spec 坑**：`ClassicPacketType` 的 BR 位是"set=允许"，但 EDR 位（2-DH/3-DH）是 **"set=禁止"**——`stack.gap.classic_connections.set_acl_packet_types` 把这个反转封装好了；底层 mask 构造看 `pybluehost/classic/gap.py::set_acl_packet_types`
- **测试位置**：`tests/unit/hci/test_le_set_phy.py`（11）+ `tests/unit/ble/test_set_phy.py`（6）+ `tests/unit/hci/test_change_connection_packet_type.py`（10）+ `tests/unit/classic/test_set_acl_packet_types.py`（6）= 33 unit
- **双设备 throughput**：`tests/hardware/test_throughput_real.py`——BLE LE CoC + SPP × {1M/2M} 或 {2-DH/3-DH} × {uplink/downlink} = 8 parametrized cells。需要两块 USB adapter + `--transport-peer=usb:...`，operator runbook 在 [`docs/THROUGHPUT_VERIFY.md`](docs/THROUGHPUT_VERIFY.md)
- **加新 PHY API（LE Coded / S=2 / S=8）**：参照 `LE_Set_PHY` 同样的命令 + 事件 + listener + manager method 四件套；`LEPhyMask.LE_CODED=0x04` 已经定义好了，stack-level method 直接传它就行

### LE CoC manager（L2CAP LE Credit-Based Channel）

v1.0 协议栈原本只有 Classic L2CAP signaling；v1.2 Phase 2 P.8 之前为了让 BTP L2CAP service 能跑，**专门加了 LE CoC manager 扩展**（独立 Plan，6 Task），现在 v1.0 协议栈原生支持 LE CoC：

```python
# 出向
ch = await stack.l2cap.connect_le_coc_channel(handle=h, psm=0x0080, mtu=512, mps=247, initial_credits=10)
await ch.send(b"…")
await stack.l2cap.disconnect_le_coc_channel(ch)

# 入向
def on_incoming(channel):
    channel.set_events(SimpleChannelEvents(on_data=lambda d: ..., on_close=lambda r: ...))
stack.l2cap.listen_le_coc_channel(psm=0x0080, handler=on_incoming)
```

- 信令 PDU 编解码：`pybluehost/l2cap/le_signaling.py`（0x06/0x07/0x14/0x15/0x16）
- 管理器扩展：`pybluehost/l2cap/manager.py::L2CAPManager._on_le_signaling` + 三个 public 方法
- 端到端测试：`tests/e2e/test_le_coc_lifecycle.py`（VirtualLELink loopback）
- **加新 BLE profile 跑 over LE CoC** 直接复用这层，不需要再动 stack

### EATT 多 bearer（GATT server 侧）

GATT server 支持 Enhanced ATT bearer（Enhanced Credit-Based 信道，固定 SPSM 0x0027）：

```python
# 入向：Stack 自动在 PSM_EATT 上监听（required_security=4，未加密拒 0x0008），
#       inbound ECFC 信道自动绑 GATT server。
# 出向（BTP EATT_CONNECT 已自动 attach）；手动场景：
stack.attach_eatt_bearer(channel)  # channel = LECoCChannel（psm==PSM_EATT）
```

- 语义：`GATTServer.handle_request(conn, pdu, *, bearer_cid=CID_ATT)`；ATT_MTU 与 robust-caching "DoS sent once" 标记按 `(conn_handle, bearer_cid)` 键控，prepare queue / CCCD / security 按 `conn_handle`（per-client 共享，符合 GATT.TS GAW/BV-12、GPM/BV-05）。
- EATT bearer 上 Exchange MTU 回 `0x06 Request Not Supported`（GAC/BI-01）；bearer MTU = 信道 L2CAP MTU（`add_eatt_bearer(conn, cid, mtu=...)`）。
- BTP：GATT `EATT_CONNECT(0x1f)` 建 bearer 并 attach；L2CAP `DISCONNECT_EATT_CHANS(0x09)` 按 CID 升序断前 N 条。SSF 0x2B3A 报 EATT 位（0x01，octet 0 bit 0）。
- 测试：`tests/unit/ble/test_gatt_eatt.py`、`tests/unit/test_stack_eatt.py`、`tests/unit/pts/btp/test_gatt_eatt_btp.py`、`test_l2cap_disconnect_eatt.py`、`tests/e2e/test_le_coc_lifecycle.py`（EATT loopback）。
- **不做**：CL 侧 per-bearer 发起（auto-pts 无 BTP 驱动入口）、通知经 EATT 发送、BR/EDR EATT。

### 28 个 CLI 命令一览

`app`（需要 transport）21 个 + `tools`（离线）7 个。完整使用例在 [`README.md`](README.md) §1.3–1.10。如果你（AI agent）需要加一个新 CLI 子命令：

- 加到 `pybluehost/cli/app/<name>.py` 或 `pybluehost/cli/tools/<name>.py`
- 在 `pybluehost/cli/app/__init__.py` 或 `cli/tools/__init__.py` 里 `register_<name>_command()`
- 测试模式：参照 `tests/unit/cli/app/test_*.py`（argparse 烟测）+ 如果是 transport-driven 命令再加 `tests/e2e/test_*_lifecycle.py`
- 更新 README §1.x 里加一段使用例
- 跑 `pybluehost <namespace> --help` 自查

### 版本号同步

唯一可改的版本字符串在 `pybluehost/__init__.py::__version__`。`pyproject.toml` 用 `dynamic = ["version"]` + `[tool.hatch.version]` 自动从 `__init__.py` 读取。**改版本只动 `__init__.py`**；`tests/unit/test_version_sync.py` 守卫两边不漂移。当前 `0.99`，真机验证完成后 bump `1.0.0`。

### 真机验证状态（哪些 ✅ / 哪些 ⏳）

[`README.md`](README.md) 末尾 `## 项目状态` 有"真机验证状态"小表，列每个 PRD 是 ✅（已验证）还是 ⏳（待 operator）。**接手时先看那张表**，不要在已 ✅ 的部分二次造轮子。

---

## Plan 拆分原则

### 核心约束：只要不冲突，就可以拆

Plan 的边界不是"层"，而是**代码冲突域**。判断两个 Plan 能否并行：

> 如果 Plan A 和 Plan B 修改的文件集合没有交集，它们就可以同时执行。

### 好的拆分方式

| 拆分维度 | 示例 |
|---------|------|
| 同层不同模块 | `hci/packets.py` 和 `hci/flow.py` 拆成两个 Plan |
| 同层不同子功能 | HCI 常量 + 数据包解析 / HCI 控制器逻辑 / HCI Vendor 扩展 |
| 独立工具类 | `tests/fakes/` 可以独立于业务层并行编写 |
| 纯文档 Plan | 只写架构文档、Plan 文档，零代码冲突 |

### 拆分目标

- **每个 Plan 在 1–2 小时内可完成**（步骤数 10–30 个）
- **每个 Plan 的测试可以独立运行**（不依赖同批未完成的 Plan）
- **每个 Plan 有清晰的"完成标准"**：明确的测试数量和 PASS 要求

### 不应拆分的情况

- 两个模块存在循环依赖，必须同时修改
- 拆开后任意一半无法独立测试（只能验证整体）

### 层间依赖仍然适用

上层依赖下层的 **public API**。下层的 API 接口稳定后，上层 Plan 就可以开始，不必等下层全部完成。可以用 `Protocol` / ABC 或 Fake 实现先占位。

---

## 多人协作规范

### 认领机制

开始一个 Plan 前，先在 `docs/superpowers/STATUS.md` 中更新认领信息：

```markdown
### 🔄 Plan N — XXX Layer
- **认领人**：你的名字 / AI session ID
- **认领时间**：YYYY-MM-DD HH:MM
- 状态：正在执行 Task N（Step N）
```

完成或中断时，**必须**将状态更新到 STATUS.md 并 commit，让下一个人能无缝接手。

### 并行开发规则

- **同一 Plan 不允许两人同时执行**（Plan 内有顺序依赖）
- **不同 Plan 可以并行**，但必须满足层次依赖（上层依赖下层完成）
- 每个 Plan 建议在独立 worktree 中执行，完成后合并到 master

```bash
# 为新 Plan 创建 worktree
git worktree add .claude/worktrees/<plan-name> -b claude/<plan-name>

# 完成后合并
cd /path/to/main/repo
git merge --ff-only claude/<plan-name>
```

---

## 状态更新协议（强制要求）

> **核心原则：状态必须持久化到 git，不能只存在于对话中。**

### 每完成一个 Step 后必须执行

1. **在 Plan 文档中勾选该 Step**：`- [ ]` → `- [x]`
2. **在 STATUS.md 中更新进度**（见模板）
3. **提交到 git**：

```bash
git add docs/superpowers/plans/<current-plan>.md docs/superpowers/STATUS.md
git commit -m "docs(progress): complete Plan N Task M Step K — <简短描述>"
```

### STATUS.md 进度更新模板

每个 Plan 的详细进度区块应保持如下格式：

```markdown
### 🔄 Plan N — Layer Name
- **认领人**：张三
- **开始时间**：2026-04-16
- **当前进度**：Task 2 Step 3 / Task 5 Step 4（共 N 步）
- **最后更新**：2026-04-16 14:30
- 已完成 Task：Task 1（errors）、Task 2（address）
- 进行中 Task：Task 3（uuid）— Step 2 已完成，Step 3 进行中
```

### 遇到问题时必须记录

问题发现时，**立即**在当前 Plan 文档末尾的"常见问题"区块追加记录，并同步到 STATUS.md 问题日志：

**Plan 文档中（追加到文档末尾）：**

```markdown
## 常见问题 / Troubleshooting

### Q: <问题简述>
- **现象**：...
- **原因**：...
- **解决方案**：...
- **记录人**：张三，2026-04-16
```

**STATUS.md 问题日志中（追加一行）：**

```markdown
| YYYY-MM-DD | Plan N | 问题描述 | 解决方案 | ✅ 已解决 / ⚠️ 待确认 |
```

---

## Plan 执行流程

### 标准执行顺序

```
读 Plan 文档 → 认领（更新 STATUS.md）→ 按 Task 顺序执行
  ↓ 每个 Step 完成后
勾选 checkbox → 更新 STATUS.md → git commit
  ↓ 每个 Task 完成后
运行该 Task 的测试（全部 PASS 才继续）→ git commit
  ↓ Plan 全部完成后
运行全套测试（uv run pytest tests/ -q）→ 合并到 master → 更新 STATUS.md 状态为 ✅
```

### 使用 Superpowers 技能

| 场景 | 推荐技能 |
|------|---------|
| 编写新 Plan 文档 | `superpowers:writing-plans` |
| 执行 Plan（有子 Agent 时） | `superpowers:subagent-driven-development` |
| 执行 Plan（单 Agent） | `superpowers:executing-plans` |
| 遇到 bug | `superpowers:systematic-debugging` |
| 完成一个 Plan 后 | `superpowers:verification-before-completion` |
| 代码审查 | `superpowers:requesting-code-review` |

---

## 开发规范

### TDD 强制要求

每个模块必须先写失败测试，再写实现：

```bash
# Step 1: 写测试
uv run pytest tests/unit/<layer>/test_<module>.py -v   # 预期 FAIL

# Step 2: 写实现
# Step 3: 验证
uv run pytest tests/unit/<layer>/test_<module>.py -v   # 预期全部 PASS
```

### 提交规范

```
feat(<layer>): add <module> — <功能描述>
fix(<layer>): <问题描述>
docs(plans): <plan 文档变更>
docs(progress): complete Plan N Task M Step K
refactor(<layer>): <重构描述>
test(<layer>): add tests for <module>
```

### 代码规范

- **层间隔离**：仅通过 SAP Protocol 接口通信，测试用 Fake 替换真实实现
- **asyncio**：所有 IO 操作 async，测试使用 `pytest-asyncio`，`asyncio_mode = "auto"`
- **类型注解**：所有公共 API 必须有完整类型注解
- **`__init__.py`**：每层导出该层全部公共 API，上层只从 `__init__` import

### 常用测试命令

```bash
uv run pytest tests/ -q                          # 全套（快速）
uv run pytest tests/ -v                          # 全套（详细）
uv run pytest tests/unit/core/ -v               # 只跑 core
uv run pytest tests/unit/transport/ -v          # 只跑 transport
uv run pytest tests/ -v --tb=short -x           # 遇到第一个失败即停止
uv run pytest tests/ --cov=pybluehost -q        # 带覆盖率

# Transport 选择
uv run pytest tests/ --transport=virtual            # 强制虚拟控制器
uv run pytest tests/ --transport=usb                # 真硬件（自动检测）
uv run pytest tests/ --transport=usb:vendor=intel   # 限定厂商
uv run pytest --list-transports                     # 诊断

# Trace / debug
uv run --frozen pytest tests/ --pybluehost-trace=hci --transport=virtual    # pytest 内打开 HCI trace
uv run --frozen pytest tests/ --pybluehost-trace=*=debug --transport=virtual # 全部层 debug
PYBLUEHOST_TRACE=hci=debug uv run --frozen pytest tests/                    # 通过环境变量
```

---

## 已知问题与经验（持续更新）

### pytest-asyncio 注意事项

- `pyproject.toml` 必须设置 `asyncio_mode = "auto"`，否则 async 测试不会自动运行
- async fixture 必须用 `@pytest_asyncio.fixture`，不能用普通 `@pytest.fixture`
- Server handler 测试结束后需要主动 cleanup，否则会有 `Task was destroyed but it is pending` 警告

### git submodule（SIG 数据）

- `pybluehost/lib/sig` 是 Bluetooth SIG 官方数据 submodule，来自 bitbucket.org
- 新 clone 后必须运行 `git submodule update --init` 才能使 sig_db 测试不 skip
- 网络受限环境可以手动将主仓库的 sig 目录 junction link 到 worktree

### worktree 同步

- worktree 分支需要主动 `git merge master --ff-only` 才能获取 master 最新代码
- 合并前检查是否有未提交的本地修改（`git status`）

### pyserial-asyncio

- UARTTransport 依赖 `pyserial-asyncio>=0.6`，`uv sync --extra dev` 会自动安装
- 在没有串口设备的环境中，UART 相关测试使用 mock，不需要真实硬件

### Q: `app sdp-browser` 对真机报 `IndexError: index out of range` → A: SDPClient 未实现 continuation-state 协议 / 修复提交 54719d2

- **现象**：连上耳机/音箱等多 profile 设备（SDP record 大）后，`sdp-browser` 在解码响应时抛 `IndexError: index out of range`；边界落点不同时也可能静默返回被截断的属性（不报错但数据残缺）。
- **根因**：`SDPClient.search_attributes` 请求里写死 `ContinuationState=0x00` 且完全不读响应的 ContinuationState。当协商 MTU（如 672）装不下完整 record 时，服务器按 spec 分片并返回非空 ContinuationState，客户端却只解码第一片（被截断的 AttributeLists），`decode_data_element` 走到缓冲区末尾越界。MTU < 请求的 MaxAttributeByteCount（默认 0x03F0）时必然触发。
- **解决**：`search_attributes` 改为循环跟进 ContinuationState——把响应里的 state 原样回填到下一个请求，拼齐所有分片后再一次性 decode；decode 外加 `except (IndexError, ValueError)` 兜底，CLI 再也不因坏/截断 PDU 崩溃。`_MAX_CONTINUATION_ROUNDS=1024` 防恶意服务器死循环。
- **回归测试**：`tests/unit/classic/test_sdp.py::test_sdp_client_follows_continuation_state_for_fragmented_response`（用 `_FragmentingChannel` 模拟分片服务器）。

### Q: PTS DISC/CONN 广告用例大面积 FAIL / 真机 AD 数据错乱 → A: BTP 广告数据是 type-first，需翻译成 on-air len-first / 修复提交 09f58bc

- **现象**：跑 auto-pts GAP DISC 用例时，discoverable mode 用例 FAIL；抓包发现 IUT 广播的 AD 结构损坏（length/type 颠倒，名字被截断）。
- **根因**：auto-pts 的 BTP `START_ADVERTISING` 载荷里 AD 结构是 **`{AD_Type, AD_Len, AD_DATA}`（type 在前，AD_Len=len(data)）**——见 `auto-pts/doc/btp_gap.txt`。而 HCI `LE_Set_Advertising_Data` 要的是标准 on-air 格式 **`[len][type][data]`（len=1+len(data)，len 在前）**。直接把 BTP 字节喂给控制器 = 广播损坏。故加一层翻译：`pts/btp/services/gap.py::_parse_btp_ad`（拆 type-first）→ `_apply_mode_to_adv`（注入/覆盖 AD Flags 的 discoverable mode + BR/EDR-not-supported）→ `_ad_to_hci`（重排成 len-first）。
- **附带**：`set_connectable`/`set_discoverable` 原本只翻 BTP bookkeeping bit，不落到真实广播；现在 START_ADVERTISING 时按当前 mode 选 adv PDU type（ADV_IND/ADV_SCAN_IND/ADV_NONCONN_IND）+ 注入 AD Flags。
- **同类坑**：auto-pts 的 `stack.gap.ad` 默认只有 name，**不含 flags**，所以要靠 IUT 按 set_discoverable 注入，不能指望上游带。

### Q: PTS BROB/OBSV 及部分 DISC 用例 INCONC/FAIL，DEVICE_FOUND 事件明明在刷 → A: DEVICE_FOUND/DEVICE_CONNECTED 的地址字节序错了 / 修复提交 34e4926

- **现象**：OBSV 观察用例里 IUT 扫描正常（log 里 `BTP_GAP_EV_DEVICE_FOUND` 事件刷屏），但 WID 4「请确认 IUT 收到 Advertising Event」handler 返回 Cancel → PTS 判 INCONC。CONN 类地址匹配也可能连锁失败。
- **根因**：auto-pts 解析 DEVICE_FOUND / DEVICE_CONNECTED 事件的 BD_ADDR 用 `le_bytes_to_hex_str`（= `data[::-1].hex()`，**期望小端**）。而 `pts/btp/services/gap.py::_on_scan_result` 和 `cli/app/pts_tester.py` 的连接 hook 都直接发 `BDAddress.address`（**大端/显示序**），被上游一反转就成了反向地址，永远匹配不上 `TSPX_bd_addr_iut`。`read_controller_info`(op_03) 早就用了 `to_hci()`，这两个事件路径漏了。
- **解决**：两处都改成优先 `to_hci()`（小端），无 `to_hci` 的测试 fake 回退 `.bytes`/`.address`。
- **回归测试**：`tests/unit/pts/btp/test_gap_events.py::test_device_found_event_address_is_little_endian`（用真 `BDAddress.from_string` 锁字节序）。
- **经验**：凡是发进 auto-pts 的 BD_ADDR，先想清楚对端是 `le_bytes_to_hex_str`（小端）还是别的——controller-info / DEVICE_FOUND / DEVICE_CONNECTED / IDENTITY_RESOLVED 全是小端，别用显示序 `.address`。

### Q: SM 用例全部 `NOT_IMPLEMENTED`（connect 都不试）→ A: `sm.py` 骨架没接进 `__init__` / 修复提交 cb5ffbe

- **现象**：跑 `SM` 批，74 个用例清一色 `NOT_IMPLEMENTED 0.0`，连 BTP 都不发。
- **根因**：autoptsclient 靠 `getattr(autoprojects,'sm')` 找 profile 模块，我们的 `__init__.py` 用 PEP 562 `__getattr__` 只惰性解析 `gap/gatt/l2cap`，`sm` 被故意排除（注释「SMP 走 GAP service」）→ `getattr` 抛 AttributeError → `mod is None` → `sm.test_cases()` 从不被调 → `test_case_lookup_name` 找不到实例记 NOT_IMPLEMENTED。上游 SM **确实没有独立 BTP service**（pairing 走 GAP service），但仍需要一个 sm profile 模块把用例注册进 autoptsclient。
- **解决**：`sm.py` 实现 `set_pixits`/`test_cases`（仿 bluez sm.py，pre_conditions 用 `core_reg_svc_gap`+`gap_set_bondable_on`+`gap_set_io_capability`），并把 `'sm'` 加进 `_PROFILE_MODULES`。SM WID 全套继承上游 `autopts.wid.sm`。

### Q: SM/CEN 配对一连上就被 PTS 断（0x13）或回 Pairing Failed 0x04 → A: SET_BONDABLE 没到 SMP + legacy c1 地址字节序错 / 修复提交 c014f2f

- **现象**：SM/CEN 用例 connect 成功（DEVICE_CONNECTED 正常），一发 pairing 就被 PTS 以 0x13 断连；把 bonding 修对后又变成 Pairing Failed reason=0x04（Confirm Value Failed）。
- **根因（两个独立 bug）**：
  1. **SET_BONDABLE/SET_MITM 悬空**：BTP GAP `_handle_op_09`(SET_BONDABLE) 只翻 GAP settings 位图，从不传到 SMP 层；`ctx.bondable` 永远是 stack 初始值 True → Pairing Request AuthReq 永远 bonding ON。而 `SM/CEN/JW/BV-01-C` 的 WID 108 会先 `gap_set_bondable_off()`（要求 AuthReq bonding=0x00），PTS 脚本看到不匹配就断连。SET_MITM(0x1b) 同样是 no-op。
  2. **legacy c1 地址字节序错**：`_build_c1_params` 用 `to_hci()`（小端 wire 序）喂 c1 的 p2 块。但被真机 Android↔CSR8510 抓包验证的 `test_c1_matches_android_legacy_confirm_capture` 证明 c1 要的是**大端显示序**（`BDAddress.address`，如 CSR8510 的 `001a7dda7111`）。喂小端导致 confirm 算错，PTS 在 random 交换后核对不上 → Pairing Failed 0x04。
- **解决**：加 `SMPManager.set_bondable` + `IutActions.set_bondable/set_mitm` 并接通两个 handler；加 `_c1_address_bytes`（大端）专供 legacy c1（SC 的 `_local_sc_address`/`_peer_sc_address` 不动）。两个 `_build_c1_params` 单测原本把错误的小端序当预期，已改正。
- **验证**：改后 `SM/CEN/JW/BV-01-C` 完整跑完 confirm+random 握手，PTS Final Verdict **PASS**。
- **经验**：① legacy c1/s1 的地址/随机数一律用**大端显示序**（`.address`），别用 `to_hci()`——和 BTP 事件方向**相反**，是本栈最易踩的字节序坑；② `pts/actions.py` 加了原语（pair/encrypt/set_bondable/...）后，BTP service 要用 `getattr` 防御 + 同步补 `tests/unit/pts/btp/test_gap_service.py::_FakeActions`，否则别的用例测试挂。

### Q: SM PKE（passkey entry）用例全 INCONC，IUT 从不显示/输入 passkey → A: io_cap 没到 SMP + 无 passkey delegate + 默认 MITM 关 / 修复提交（本 session，feature 提交）

- **现象**：`SM/CEN/PKE/*` 全 INCONC；IUT 配对走 Just Works，从不上报 passkey。client 记 BTP TIMEOUT/ERROR。
- **根因（三个叠加）**：
  1. **io_cap 悬空**：`IutActions.set_io_cap` 只写 `config.security.io_capability`，但 `_initiator_send_pairing_request` 读的是 `ctx.local_io_caps ← smp._local_io_caps`（**构造期**固化）。BTP `SET_IO_CAP` 改了配置却不改 on-air Pairing Request → 永远 NoInputNoOutput → `_association_model` 恒 `just_works`。
  2. **无 passkey delegate**：SMP 默认 `AutoAcceptDelegate.get_passkey()` 返回 0、`display_passkey` 是 no-op → passkey 要么 000000、要么根本不发给 auto-pts。
  3. **默认 MITM 关**：legacy passkey_entry 要求 `both_mitm`（双方 auth_req 都带 0x04）。上游 bluez 默认 MITM **开**，JW 用例由 WID 108/110 显式 `gap_set_mitm_off` 关掉；我们默认关，PKE 永远凑不齐 both_mitm。
- **解决**（对齐 bluez `ptsprojects/bluez/sm.py`）：① `set_io_cap` 同步写 `smp._local_io_caps`；② `pts_tester.py` 装 `_PtsSmpDelegate`——`display_passkey` 发 BTP `PASSKEY_DISPLAY`(ev 0x84, **小端** addr, `to_hci()`) 让 auto-pts `stack.gap.passkey.data` 有值，`get_passkey` 阻塞等 `IutActions.submit_passkey`（future）；③ `sm.py` io_cap 改 `display_only` + pre_conditions 加 `gap_set_mitm_on`，IXIT `TSPX_io_capability` 同步改 `DisplayOnly`。
- **关键认知**：legacy passkey 握手长度和 JW 一样（单轮 confirm/random，只是 TK=passkey≠0），所以 JW 能过的方向 PKE 也能过——之前 INCONC 纯粹是上面三个接线缺失，不是协议能力问题。DisplayOnly 方向是**事件驱动**（display_passkey→0x84），比 input 方向（get_passkey 阻塞 future）干净，优先用。
- **回归测试**：`tests/unit/pts/test_actions_passkey.py`（submit_passkey future/stash、io_cap 传播、display_passkey 小端、confirm_* auto-accept）。真机 `SM/CEN/PKE/BV-04-C` PTS **PASS**（2026-08-20）。
- **配套**：`confirm_passkey`(op 0x14) 对 legacy 是 no-op ack（legacy 无 numeric-comparison 步骤，那是 SC 专属，BT4.0 跑不了）。

### Q: PTS 真机跑 autoptsclient 报 `USBAccessDeniedError: Access denied` 开 CSR8510 失败 → A: 有残留进程占着 dongle

- **现象**：autoptsclient 起 pts-tester 子进程，IUT log 报 `USB Access denied`，case 直接 FATAL ERROR。
- **根因**：之前的 `scripts/pts_iut_controller.py`（或上一个 pts-tester）进程没退干净，还占着 CSR8510 的 WinUSB handle。Windows 上 USB 独占。
- **解决**：跑 PTS 前先 `Get-CimInstance Win32_Process | ? CommandLine -match 'pts_iut_controller|pts-tester'` 杀掉残留；用 `pybluehost tools usb diagnose` 确认 CSR8510 (0a12:0001) `HCI Reset` 能通再跑。

### Q: BE200 IUT 加密狗固件锁死（HCI Reset 命令发得出但中断端点永不回事件）→ A: 软件复位无效，只能物理拔插 + 重启 autoptsserver（dongle 名前缀 `USB_INTEL:Free:`）

- **现象**：跑批中 IUT 突然所有 case `FATAL ERROR`（pts-tester 连不上 BTP socket）。`tools usb diagnose` 显示该 BE200 `HCI Reset command sent: success` 但 `HCI Reset event received: USBTimeoutError`——命令能发出去、控制器却不回任何事件（连 vendor firmware 命令都 timeout）。另一颗 BE200（PTS dongle）正常。
- **根因**：BE200 控制器固件层面锁死（疑因 PTS 测试某些 RF/连接异常触发）。**不是** 残留进程占 handle（那是 `Access denied`，这是 `timeout`）——`libusb d.reset()`、`clear_halt`、deconfigure/reconfigure、长 settle 全无效；Windows `Disable-PnpDevice`/`pnputil /restart-device` 需要 admin（本机非 admin，`sudo` 被禁用）→ **只能物理拔插**。
- **恢复流程**（拔插/重启后，2026-08-25 实测）：
  1. `usb diagnose` 确认两颗 BE200 都 `HCI Reset status: 0x00`。
  2. **PTS dongle / IUT 辨认**：`Stack.from_usb(vid=0x8087, pid=0x0036, occurrence=N)` 读 BD addr——occurrence 1 = PTS dongle(`94:53FF1E6AEE`)、occurrence 2 = IUT(`5C67830704EE`)，重插后索引稳定，所以 `--pybluehost-transport usb:8087:0036#2` 不用改。
  3. **autoptsserver 重启**（系统重启会杀掉它和 PTS.exe）：`cd /tmp/auto-pts && .venv/Scripts/python.exe autoptsserver.py -S 65000 --dongle "USB_INTEL:Free:<实例路径>"`。**不能以 admin 跑**（`exit_if_admin`）。dongle 名从 server log 的 `GetDeviceList:` 行读——**前缀是 `USB_INTEL:Free:` 不是文档写的 `USB:Free:`**，写错会 `Failed to connect dongle after 4 iterations`。实例路径重插后会变（用 `Stack.from_usb(address=<物理addr>)` 读 `port_numbers` 映射到 `&0&<port>`）。连对会看到 `PTS Bluetooth Address: 9453FF1E6AEE`。
  4. 确认 `Get-NetTCPConnection -LocalPort 65000 -State Listen` 有监听再起 client。重启后**首个 case 可能冷启动 INCONC**，重跑即过。

### Q: PTS verdict 跟 autoptsclient summary 对不上（PTS 说 PASS，client 记 BTP ERROR）→ A: 以 PTS verdict 为准 / scripts/pts_collect_verdicts.py

- **现象**：`autoptsclient` 结尾 summary 记 `BTP ERROR`，但 PTS 自己 `Final Verdict PASS`（如 GAP/IDLE/NAMP）。
- **根因**：auto-pts 的 WID handler 有时做的比 PTS 严格需要的多（如 name discovery 既走 scan-rsp 又额外尝试 connection+GATT read）；额外那步超时/出错就让 client 抛 BTPError 记成 ERROR，但 PTS 早已判定 PASS。auto-pts 的 `tmp/tc_stats_results.xml` 记的是 **client 侧** status，不是 PTS verdict。
- **解决**：地面真相看每个 case log 里的 `PTS_LOGTYPE_FINAL_VERDICT`；`scripts/pts_collect_verdicts.py` 扫 `auto-pts/logs/**` 提取 per-case PTS verdict（同名多次跑取最新）。

### Q: 批量跑 PTS（一个 autoptsclient 会话跑一整组）跑几例后整批卡死 / 之后连单例也卡 → A: **PTS 侧状态退化，重启 autoptsserver（先杀 PTS.exe）即可恢复** / 2026-09-13 实测

- **现象（两层）**:① **整组批量**（`pts_run_batch.sh "<group>"`，一个会话跑 N 例）：前 2-3 例正常（~20-45s），第 3-4 例起 case log **不再更新**、PTS 也不判 verdict，整批无限期卡住（远超 `TSPX_time_guard`）。此时 autoptsclient 还在、pts-tester 也活着、IUT log 里连接反复 open→close(0x13)。② 更糟的是**退化成全局**：之后连单例跑（`pts_retry_cases.sh`）也卡在 `Starting PTS ... OK` 之后**连用例列表都取不到**。
- **判别**:`tools usb diagnose` 显示两颗 BE200 + AX201 **全部健康**（HCI Reset 0x00 / 固件 OPERATIONAL）→ **不是 dongle 问题**；autoptsserver log 无异常、`Get-NetTCPConnection -LocalPort 65000` 仍在监听 → 不是 server 崩。
- **恢复**:杀 PTS.exe → 重启 autoptsserver（**这条就够，不用重启系统**）:
  ```bash
  powershell -NoProfile -Command "Get-Process PTS -EA SilentlyContinue | Stop-Process -Force"
  cd /tmp/auto-pts && nohup <repo>/.venv/Scripts/python.exe -u autoptsserver.py -S 65000 \
      --dongle "USB_INTEL:Free:6&1687A1FD&0&3" > /tmp/aps3.log 2>&1 &
  ```
  重启后**首个 case 可能冷启动慢**，但能跑。
- **工程结论**:① **不要用超长批次**——超过 ~3-5 例就有退化风险，收益（省 ~25s 启动）远小于卡死代价；**用 `pts_retry_cases.sh` 的「每例一个会话」**，或把批次切成 ≤5 例并在批间重启 server；② 出现「卡死在 1/N」时**先重启 server 再怀疑代码**，别去改协议栈；③ `pts_batch_sequence.sh` 可以做「多组串行」，但同样要遵守 ≤5 例/批 + 批间 restart 的节奏；④ **`pts_retry_cases.sh` 已自带 server 自愈**（2026-09-16 加 `ensure_server`）——某例中途 stall 会把 server 本身弄死，之后每例都在 `init_pts` 挂 `ConnectionRefusedError [WinError 10061]`，而该脚本原先**没有**任何 server 重启，一例 stall 就废掉整轮重试。现在每次 attempt 前探一下 65000 端口，掉线才重启（含 PTS.exe 清理 + 22s settle），健康时不付代价。


### Q: PTS 每个要断连的 case 都 BTP ERROR（connect/read 全成功，最后 DISCONNECT 翻车）→ A: GAP facade 没有 disconnect 方法 / 修复提交 2a794b5

- **现象**：GATT/CL 用例 connect→read 都 OK，最后 `BTP_GAP_CMD_DISCONNECT (0x0f)` 一律回 `BTP_ERROR`。
- **根因**：`pts/actions.py::disconnect` 调 `stack.gap.disconnect(handle)`，但 `pybluehost/gap.py::GAP` 是个组合 facade，**自身没有 disconnect**——它在 `ble_connections`（BLEConnectionManager）/ `classic_connections`（ClassicConnectionManager）上。`AttributeError: 'GAP' object has no attribute 'disconnect'`。
- **解决**：按 `ConnInfo.transport` 路由到 `ble_connections.disconnect` / `classic_connections.disconnect`。
- **经验**：`stack.gap` 是 namespace facade，具体动作基本都在子 manager（ble_connections / classic_connections / ble_advertiser …）上，别假设 facade 直接有。

### Q: GATT 长写用例（GAC/GAR/GAW）connect+MTU 全 OK，IUT 也回了 WID，PTS 却干等到 time_guard 超时 → A: WRITE_LONG 走了单发 Write Request，没走 Prepare/Execute / 修复提交 e446cc2

- **现象**：GAC/BV-01-C 之类，IUT 把 WID 2(connect)/12(MTU)/69(prepare write) 都答 OK，13s 就完事，PTS 却卡 300+s 判 PTS TIMEOUT。
- **根因**：BTP `WRITE_LONG (0x18)` handler 直接 delegate 到 `_handle_op_17`（普通 `write_characteristic` = 单发 ATT Write Request）。但 MMI 明确要「send **prepare write** request」，PTS 测的是长写**规程**（Prepare+Execute）。IUT 发了普通写，PTS 一直没等到 prepare write → 干等到 `TSPX_time_guard` 超时。代码里那句注释「GATTClient transparently prepares/executes」是**错的**。
- **解决**：加 `GATTClient.write_long_characteristic`（包 `bearer.write_long` = prepare 分片 + execute commit），`_handle_op_18` 改走它。
- **根因 2（更深）**：就算修了规程，`_handle_op_18` 的 body 解析还**漏了 offset 字段**——上游 `WRITE_LONG (0x18)` / `WRITE_RELIABLE (0x19)` 的 body 是 `addr_type+addr+handle(2)+**offset(2)**+data_len(2)+data`，我们按无 offset 解析 → `value_len` 读到的是 offset(=0) → 写了**空值** prepare → PTS 等不到预期的 N 字节数据 → 干等 time_guard。修复 af8c41a 给两个 opcode 加了 offset 解析 + `write_long` 加 offset 参数。`WRITE (0x17)` / `WRITE_WITHOUT_RSP (0x15)` 的 body **没有** offset，别搞混。
- **配套**：`TSPX_time_guard` 必须显式设大（bluez 用 300000ms）——`auto_pts_project/pybluehost_iut/ixit.py` 四个 profile 都加了。不设的话 PTS 用短默认 (~200s)，慢/重连规程直接「UNKNOWN VERDICT: Timeout」。改 ixit.py 要**重启 autoptsclient** 才生效（它是常驻进程，启动时 import）；BTP service 改动则 per-case 新 spawn 的 pts-tester 自动生效（editable install 指向工作区）。
- **回归测试**：`test_gatt_client.py::test_write_long_uses_prepare_execute_path`。

### Q: GATT/CL 用例要连 2-3 次（PTS 中途改 GATT DB 测重发现），第 N 次 connect 经常 BTP ERROR → A: CSR8510 发起连接 ~50% 掉 0x3E，是硬件限制 / 缓解提交 7d5cca1

- **现象**：GAD/GAR 用例 flow 是 connect→discover→disconnect→（PTS 换 DB）→connect→再 discover。前面connect 都成，第 2/3 次 connect 偶发 `RuntimeError: LE connection ... failed to establish` → BTP ERROR。
- **根因**：CSR8510 当 initiator 连 PTS dongle，HCI 报 LE Connection Complete（分到 handle）后约一半概率立刻以 reason `0x3E`（Connection Failed to be Established）掉线。`connect_gatt` 在 optimistic complete 就返回，得靠 ATT fixed channel 是否还在来判断链接活没活。每个 case 要连多次，把单次 ~50% 掉线率放大成 case 级高失败率。**这是 CSR8510 硬件/RF 限制，软件无法根治。**
- **缓解**（`pts/actions.py::connect`）：5 次重试；每次重试前 `_cancel_pending_le_connect()`（上次 0x3E/超时会把 controller 卡在 initiate 态，不 cancel 下次 LE_Create_Connection 直接 Command Disallowed）；`connect_gatt` 用 100% duty 扫描窗（60/60ms）。
- **经验**：判 IUT-central connect 类 case 的 verdict 时，掉 0x3E 导致的 FAIL/ERROR 别当成协议栈 bug 反复查——先确认是不是这条硬件限制。

### Q: GATT/SR、GAP/SEC、GAP/BOND 全部 UNKNOWN VERDICT / 快 FAIL → A: CSR8510 **peripheral（被连）角色 100% 掉 0x3E**，收不到入向连接，是硬件限制 / 2026-08-19 实测

- **现象**：跑 GATT/SR 全矩阵 ~28/28 全 `UNKNOWN VERDICT: NONE`（每个 ~20s），case log 卡在 WID 1「prepare connectable mode」→ `wait_for_connection` 10s 超时；GAP/SEC/SEM、GAP/BOND 全 ~17s 快 FAIL。IUT BTP trace 里 START_ADVERTISING 成功后再无任何 DEVICE_CONNECTED。
- **根因（实测定论）**：CSR8510 当 **peripheral/advertiser** 收入向连接时，central（无论 Intel BE200 还是 PTS firmware）报 LE Connection Complete 后立刻以 `0x3E` 掉线，**peripheral 侧永远收不到已建立的连接 → 不发 DEVICE_CONNECTED**。隔离复现（两进程、CSR8510 advertiser + BE200 central）：**12/12 全 0x3E**，换连接参数（interval 100–200ms、100% scan duty）、换 AD data、分开进程，全一样。把 `wait_for_connection` 加到 120s 跑 SR case 依然 0 连接。**这是 CSR8510 固件 peripheral link-layer 缺陷，软件/参数无法根治。**
- **方向不对称**：CSR8510 当 **central/initiator**（IUT 主动连 PTS）能用（~50% 0x3E，重试可成，GATT/CL 大量 PASS）；当 **peripheral**（PTS 连 IUT）基本全废。所以 GATT/CL 可测、GATT/SR 硬件卡死。
- **⚠️ 纠正旧结论**：上一条曾说「反向 PTS→IUT 连接是稳的」——**那是错的**，今天实测推翻。GAP/CONN/TERM 当年 PASS 是 WID 74 不强制 `wait_for_connection`（advertise-only）的侥幸，不代表 PTS→CSR8510 真能稳定连上。
- **替代 IUT 硬件排查**：AX201(8087:0026) 被 Windows 独占开不了；Broadcom(33fa:0012) 能 init 但**广播根本不上空口**（BE200 scan 8s 看不到它）——都不可用。**结论：当前手上只有 CSR8510 能当 IUT，peripheral 角色用例（GATT/SR、GAP/SEC/BOND/peripheral-responder）系统性地跑不过，属硬件 blocked，不是协议栈 bug。**
- **经验**：看到「prepare connectable mode → wait_for_connection 超时」一律先想这条，别再查 advertising 代码（`BLEAdvertiser.start` 的 HCI 序列已逐字节核对无误）。要真正覆盖 SR/peripheral 矩阵，得换一块 peripheral 可靠的 dongle 当 IUT。
- **✅ 后续（2026-08-21 推翻「只有 CSR8510 能当 IUT」）**：「AX201 被 Windows 独占开不了」这条**已不成立**——用户换过 PTS/IUT 驱动后 AX201(`usb:8087:0026#1`, public addr `D4548BBA70A1`) 能被 PyBlueHost 直接打开，且 **peripheral 角色实测可靠**（BE200↔AX201 RF 链路正常收发入向连接）。当前 IUT 已整体迁到 AX201（见 `git log` 的 IUT-migration 提交；`ixit.py`/`iutctl.py`/`pts_run_batch.sh` 的 addr/transport 都已改 AX201）。CSR8510 退位只当 PTS dongle 候选。**结论更新：peripheral 用例（GATT/SR、GAP/SEC/BOND）现在用 AX201 可跑，不再是硬件 blocked。** 排查这类 case 时先确认当前 IUT 是 AX201 还是 CSR8510——两者 peripheral 能力天差地别。

### Q: PTS GATT/SR 读/发现用例（GAR/GAW/GAD）connect 后干等到 time_guard（~321s PTS TIMEOUT）→ A: ATT 列表/读响应没按 ATT_MTU 截断 + 缺 Read Blob / 修复提交 5684b98

- **现象**：`GATT/SR/GAR/BV-01-C` 等，IUT 收到 `ATT_Read_By_Type_Request` 也正常回，但 PTS 卡住 ~321s 判 `PTS TIMEOUT`。本地复现：BTP init_server 建好的 SR db 一次 `Read By Type(0x2803)` 返回 **79 字节**响应。
- **根因**：这些 PTS 用例 connect 后**直接发 Read By Type，从不先 Exchange MTU** → 用默认 `ATT_MTU=23`。SR db 服务多、一次命中一堆特征 → 响应远超 23 字节 = **协议违规**，PTS 当它非法一直等到 `TSPX_time_guard`。`GATTServer` 原本**完全不按连接 MTU 截断**：`_handle_read_by_type`/`_handle_read_by_group_type`/`_handle_find_information` 把所有命中项全塞进响应，`_handle_read` 把整个 value（SR db 有 512 字节 `long_6` 特征）一次性返回。
- **解决**：`GATTServer` 新增 per-connection MTU 跟踪（`_conn_mtu`，默认 23，Exchange MTU 时更新为 `min(client_rx, server_rx=512)`，需把 `conn_handle` 串进各 handler）；三个列表类 handler 累积到「再加一条就超 `ATT_MTU-2`」即停；`_handle_read` 把 value 截到 `ATT_MTU-1`；新增 `_handle_read_blob`(0x0C) 按 offset 切片返长值（带 Invalid Offset 检查）。
- **关键认知**：ATT「读/发现响应必须装进当前连接 ATT_MTU」是**发送方义务**，不能指望对端先 Exchange MTU。PTS 很多 SR 用例故意不换 MTU 就是在测这条。列表截断的预算是 `ATT_MTU - 2`（opcode+length 头），单值读是 `ATT_MTU - 1`（只有 opcode）。
- **回归测试**：`tests/unit/ble/test_gatt.py::test_read_by_type_truncates_to_default_mtu` / `..._uses_negotiated_mtu_after_exchange` / `test_read_response_truncates_long_value_to_default_mtu` / `test_read_blob_*`。真机 `GATT/SR/GAR/BV-01-C` PTS **PASS**（31.5s，原 ~321s timeout，2026-08-21）。

### Q: PTS GATT/SR GAR/GAW 安全 BI 用例（BI-03/04/09/10/11…）全 FAIL，IUT 对安全特征一律回 0x02/0x03 → A: BTP 权限位是「独立安全级别位」、不含 plain read/write 位 / 修复提交 a309104

- **现象**：GATT/SR 的 Insufficient Authorization(0x08)/Authentication(0x05)/Encryption(0x0F)/KeySize(0x0C) 类 BI 用例全 FAIL；诊断发现 IUT 对需要安全级别的特征一律回 `0x02`(Read Not Permitted)，而不是对应的具体错误码。
- **根因**：BTP `ADD_CHAR`/`ADD_DESC` 的权限字节把读/写的**安全级别**编码成**相互独立的位**（read_enc=0x04 / read_authn=0x10 / read_authz=0x40），**不**置 plain read(0x01)/write(0x02) 位（见 `auto-pts/doc/btp_gatt.txt` opcode 0x03 的 Permissions 表）。而 `_read_error`/`_write_error` 只测 plain 位（`perms & PERM_READ`）→ 所有安全特征被判「不可读」回 0x02。zephyr 语义里 `read_enc` 单独即表示「可读但需加密」。
- **解决**：加 `_PERM_READ_ANY/_PERM_WRITE_ANY` 并集（4 个级别位 OR）判「是否可读/写」，再按级别位选 0x05/0x08/0x0F/0x0C。连带三处：① `_handle_read_by_type` 加安全检查——「Read Using Characteristic UUID」复用 0x08 opcode 以特征值 UUID 为 type 时，命中受门控的特征要回安全错误（declaration 恒可读所以 discovery 不受影响）→ BI-09/10/11；② 新增 `_handle_read_multiple_variable`(0x20)——之前没实装，PTS 干等 325s TIMEOUT，响应是 `[len(u8)][value]` 元组列表（无 handle）；③ `add_service` 不再对**已显式提供** CCC 的 notify 特征重复自动加 CCC（BTP init_server 用 ADD_DESCRIPTOR 显式加 CCC，双 CCC 会把之后所有 handle 移位）。
- **关键认知**：① 「是否允许读/写」要按 4 个级别位的并集判，不能只看 plain 位；② 特征的**安全要求（enc/authn/authz）无法经 ATT 发现**（characteristic properties 字节没有安全位），PTS 靠预定义 db / WID 选 handle——所以 SR db 的 handle 布局必须和参考 db（zephyr `init_server`）逐位一致，双 CCC、漏 include 都会移位；③ WID 123/124「enter handle that will satisfy the test case」要按 `WIDParams.test_case_name` 分流——普通 Read Multiple 回 plain 可读特征，安全 BI 用例（BI-20/21/22、BI-40/42/44）回对应安全级别门控的特征 handle。
- **遗留 gap**：「Read Not Permitted」簇（GAR/BI-01/06/12/18/36）需要一个**完全不可读**的特征值，但 zephyr `init_server` db 里所有特征都带某个 read 级别位 → 参考 IUT 同样过不了，属参考实现 gap，不是我们的 bug。BI-05(Insufficient Enc Key Size) 需要 SMP 以 <15 字节密钥完成配对（取决于对端 max_key_size 协商），遗留。BV-11/12（EATT 多 bearer）已于 2026-09-18 PASS（见下方 GAR/BV-11+BV-12 条目——需 bond 持久化 + mux/sec_level 两修复）。
- **回归测试**：`tests/unit/ble/test_gatt.py::test_standalone_*`（0x0C/0x30/0xC0 独立安全位）、`test_read_multiple_variable_*`、`test_read_using_uuid_*`、`test_add_service_does_not_duplicate_explicit_ccc`。真机 GATT/SR/GAR 18 PASS（原 ~9）。
- **⚠️ 操作坑**：`Stop-Process -Force` 强杀 autoptsclient 会留下占着 AX201 USB handle 的 pts-tester 僵尸 → 下一批全 `USBAccessDeniedError: 8087:0026 Access denied` / FATAL ERROR。杀 client 后必须 `Get-CimInstance Win32_Process | ? CommandLine -match 'pts-tester'` 清掉残留，用 `tools usb diagnose` 确认 AX201 HCI Reset 通再跑。

### Q: PTS L2CAP 全组（99 例）大面积 INCONC/BTP ERROR，LE/CFC 连 WID 41 都连不上 → A: 三个叠加 bug——CONNECT 地址字节序、缺 LISTEN、LISTEN  body 长度 / 修复提交（本 session）

- **现象**：AX201 上重跑 L2CAP（2026-08-19 的 CSR8510 旧 verdict 全因 peripheral 0x3E 失效，不是真失败），LE/CFC 仍 63 INCONC + 一批 BTP ERROR。ACL 能连上（DEVICE_CONNECTED 正常），但 L2CAP CoC 信道建不起来。
- **根因（三个独立 bug）**：
  1. **CONNECT 地址字节序**：BTP `L2CAP_CONNECT (0x02)` 的 addr 是 auto-pts `addr_str_to_le_bytes` 发的**小端**（HCI 序），而 `_resolve_le_connection_handle` 拿 `BDAddress.address`（**大端显示序**）比 → 永不匹配 → `handle=None` → BTP_ERROR。和 GAP DEVICE_FOUND 是**同一类**字节序坑，方向一致（BTP wire = 小端）。
  2. **出向 connect 不发 0x81 Connected 事件**：`_do_connect` 成功只回 response，不发 `BTP_L2CAP_EV_CONNECTED`。但 auto-pts 的 stack 模型靠**事件**驱动 `l2cap.connected()` 标记信道 up（hdl_wid_41 的默认路径只调 `btp.l2cap_conn` 不回填 model）→ 后续 data/confirm WID `wait_for_connection` 超时 → INCONC。
  3. **test_cases 没挂 listener**：上游 zephyr 的 L2CAP **默认** precondition 是 `pre_conditions_success`（common + `btp.l2cap_le_listen(success)`）——IUT 在 PSM 上**监听**，才能**应答** PTS 主动发起的 CoC 连接。我们只 `l2cap_init` 没 listen → 所有「IUT 当被连方/responder」的用例（多数 LE/CFC、ECFC）INCONC。
  4. **LISTEN body 长度漂移**：`_handle_op_05` 按 spec 要 ≥9 字节（含 Security_Type/Key_Size），但 auto-pts master 的 `l2cap_listen` 实际只 pack **7 字节**（PSM+Transport+MTU+Response，没跟上 spec 加的两个字段）→ 真 LISTEN 被当 short body 拒。改为接受 ≥7。
- **解决**：`_resolve_le_connection_handle` 优先 `peer.to_hci()`（小端）；抽出 `_register_connected_channel`（存信道 + 接 data/close 事件 + 发 0x81）供出/入向共用；`pybluehost_iut/l2cap.py` 默认 precondition 加 `btp.l2cap_le_listen(LE_PSM, LE_INITIAL_MTU, success)`；`_handle_op_05` 接受 7 字节。
- **回归测试**：`tests/unit/pts/btp/test_l2cap_connect.py`（真 BDAddress fake：BE `.address` / LE `to_hci()`，wire addr 发 LE；`test_connect_wire_address_is_little_endian`、`test_connect_emits_connected_event`）；`test_l2cap_listen.py::test_listen_accepts_seven_byte_autopts_body`。真机 LE/CFC BV-02、BV-05 PTS **PASS**（2026-08-21）。
- **遗留 gap**：① **CoC 安全**——auth PSM 用例（LE/CFC BV-11/13/15/25、ECFC 若干）需要「LISTEN/CONNECT 带 response 拒绝码 + 链路加密/认证判定」，目前 listener 一律 SUCCESS 接受、connect 被拒（如 BV-01 收 `result=0x0005` insufficient_auth）后不重试配对 → 这批会 319s PTS TIMEOUT。要实装得让 L2CAP manager 查 per-connection 加密/认证状态（GATT 侧已有 `_ConnSecurity`，需打通）。② 多数「only WID 56 → INCONC」的行为用例（BV-03/06/07/08/09…）：WID 56 + listener + ACL 全对，但 PTS 观察的 on-air 行为不符预期，需 L2CAP.TS 逐例对 purpose（本地无 TS 文本）。③ ECFC（45 例，最大子组）跑在 Enhanced Credit-Based 连接（CONNECT_V2 mode/options）上，我们只按普通单信道 CoC 处理 mode/options=ignore，可能需专门实装。

### Q: L2CAP 收尾（86→91/100）——七个独立 bug / 修复提交 ec0927d…fa19dce（本 session，2026-09-14）

> 上面 `遗留 gap` ①②③ 中的①（CoC 安全）已全部落地；②③ 的两个 0x12/ECFC 缺口也已关闭。剩下 9 例见文末「遗留」。

- **① `LE/CPU/BV-01-C` 从不发 0x12**：CPU 规程是 **peripheral→central 单向**（Core Vol 3 Part A §4.20），所以 IUT 当 peripheral 时**不能**用 HCI `LE_Connection_Update`（那是 central 的 LL 规程），只能走 L2CAP 信令 0x12。原先 `conn_param_update` 一律发 HCI 命令 → PTS 等 0x12 等到超时。修法：加 `L2CAPManager.request_le_conn_param_update()`（发 0x12、等 0x13）+ `le_role()`，`IutActions.conn_param_update` **按 LE 角色分流**（central 走 HCI 老路，peripheral 走 L2CAP）。**判方向**：任何「谁可以发这个命令」的问题先查 Core 的 direction 说明，别按「两个方向都能发」想当然。
- **② `LE/CFC/BV-25` + `ECFC/BV-32` 监听等级写成 authen**：这两个是 Table 4.65 的 **Insufficient Encryption** 对（Result **0x0008**），不是认证对（0x0005）。BV-25 映射成了 `pre_conditions_authen`，ECFC/BV-32 干脆没映射（跑 success listener 直接接受）→ PTS 等不到拒绝码。修法：加 `pre_conditions_encryption` 并把两例映射过去。**Initiator 双胞胎（LE/CFC/BV-24、ECFC/BV-31）本来就 PASS**，正是这一点把问题钉在「responder 侧 listener 配置」而非 manager 的拒绝码映射上。
- **③ `ECFC/BV-24`（Renegotiate MPS – Initiator）无法用 BTP 驱动**：auto-pts 的 `l2cap_reconfigure` body **只带 MTU、不带 MPS**，所以 MPS 重协商根本没有 BTP 入口。TS 4.9.1.18 step 1 明说「`TSPX_l2ca_cbmps_min == TSPX_l2ca_cbmps_max` 则直接 Pass」——**只能走这条捷径**（zephyr 正是如此）。修法：`IXIT_L2CAP` 补 `TSPX_l2ca_cbmps_{min,max}` / `TSPX_l2ca_cbmtu_{min,max}`（zephyr 同值），BV-24 逐例把 cbmps 折成同一个值。**⚠️ PIXIT 必须先存在**：`update_pixit` 对未定义的 PIXIT **静默跳过**，覆盖会看起来生效其实没做——回归测试因此专门断言这四个名字存在。
- **④ connection handle 复用读到陈旧的「已加密」状态（影响面最大）**：`_le_conn_security` 只写不删，控制器**复用 handle**（实测恒 0x0E01）。BV-25/BV-32 的流程正是「连上→配对→断→**用同一 handle 重连**→加密重建之前就发 CoC 请求」，于是 listener 以为链路已加密而**接受**了未加密请求（空口 TX `0x15` len=14 = 接受体）。修法：`on_disconnection` 清表 + `on_connection` 显式置 `(False, False, 0)`。**凡 per-handle 状态都必须在断连时清**——这是第二次踩（`_le_peer_addrs` 那次同族）。
- **⑤ SAR 一个 ACL 包只处理第一个 L2CAP 帧**：`Reassembler.feed` 在「完整 PDU + 尾巴」时只返回第一个 PDU、**丢掉尾巴**（且不留状态）。PTS 把两个响应 PDU 打进同一个 ACL 包 → 第二个（正是我们在等的拒绝）被吞 → 5s 超时 → `BTP_ERROR`。空口：`TX 0x14 id=2`、`RX 0x15 id=3`、然后什么都没有。修法：`feed` 改为**返回该 fragment 完成的全部 PDU 列表**，并把「完整 PDU + 半个 PDU」的尾巴留进重组状态；`on_acl_data` 逐个投递。**这是通用 bug**，不止 PTS——任何会合并 L2CAP 帧的对端都会踩。
- **⑥ ECFC 入向请求缺两条校验**：`ECFC/BV-26-C` 发 **MTU<64**（超出 §4.22 的 LE_MTU 64..65535）→ 必须回 **0x000C**；`ECFC/BV-20-C` **重复 Source CID** → 必须回 **0x000A**。修法：加 `LE_MIN_CREDIT_BASED_MTU` + 两条判断。**「Source CID 重复」要比对既有信道的 `_peer_cid`**（请求里的 SCID 是**对端**的端点），我第一版拿 `_le_channels` 的键（我方 DCID）比，被单测当场抓住。**而且 0x0009/0x000A 是「*Some* connections refused」**——不能把所有 DCID 槽清零，新鲜 SCID 仍要分配 DCID（全零 = all-refused，PTS 收到就断链）。这一条和 BV-26 的 MTU<64 都已真机 PASS。
- **⑦ Reconfigure 把「增大」当非法**：responder 原先 `req.mtu > cur_mtu or req.mps > cur_mps → 0x0004`。但 **0x0004 在 TS 里是 BI-06 的「MPS < MPSMIN」**，而 **增大是 BV-22/BV-23 的核心目的**。空口：BV-23 请求 MTU 64→65，我们回 `0x1A result=0x0004`，PTS 直接断 ACL。修法：判定顺序改为 `MTU 缩减(0x0001) → 单信道以上 MPS 缩减(0x0002) → MPS < 64(0x0004) → 接受`——**每个已过用例都由更早的分支决定，所以零回归**。**ECFC(0x18) 的完整 Result 表已从 Core 5.4 §4.25 Table 4.17 抄录**（0x0002 SPSM / 0x0004 insufficient resources / 0x0005 authn / 0x0006 authz / 0x0007 key size / 0x0008 enc / 0x0009 invalid SCID / 0x000A SCID allocated / 0x000B unacceptable params / 0x000C invalid params），和 legacy 0x15 表**不是同一张**，别再混用。
- **⑧ `send()` 在 credit 上阻塞把 BTP 命令挂死**：`LECoCChannel.send` 每段 `await _tx_credits.acquire()`。空口实证 BV-23：`tx stalled on credits ... queued=1 offset=64/66`——SDU 66 字节 / MPS 64 需要 2 个 credit，只给到 1 个就卡住，BTP SEND_DATA 永不返回 → `BTP TIMEOUT`。**这和 RFCOMM credit 那次是同一个坑**：改成「入队 + drain」——`send()` 入队后**只发到 credit 用尽就返回**（保留半段 offset），`add_credits` 时唤醒 drain。credit 充足时行为不变（整条 SDU 仍在 `send()` 返回前发完）。**经验：凡是「BTP 命令 → 会等待外部资源」的路径，都不能阻塞命令处理，否则 auto-pts 必超时。**
- **⑨ 缺 `BTP_L2CAP_EV_RECONFIGURED`(0x84)**：auto-pts 的 `l2cap.reconfigured()` 只是把四个尺寸存进它的 channel model，而**后续 WID 会读这些值决定发多大的 SDU**。我们实现了 reconfigure 却从不发这个事件 → auto-pts 一直按旧 MTU/MPS 判。修法：`L2CAPManager.on_le_channel_reconfigured(cb)` 钩子（responder 与 initiator 两条成功路径都触发）+ L2CAP BTP service 订阅并 emit `chan_id(u8)+peer_mtu(u16)+peer_mps(u16)+our_mtu(u16)+our_mps(u16)`。**经验：BTP spec 里定义了的事件都是 auto-pts model 的输入，实现了动作却不发事件 = model 与现实漂移。**
- **⑩ TIM/BV-03 的 EATT 支持**：`btp.eatt_conn` = **BTP GATT `EATT_CONNECT`(0x1f)**，body `addr_type(1)+addr(6)+num(1)`；EATT 走**固定 SPSM 0x0027**（Core Vol 3 Part F §5.2 "the EATT fixed PSM"，实测确认）。TIM/BV-03 考的是**碰撞退回**：IUT 发 0x17 期间 LT 也发 0x17 → IUT 必须回 **0x0004**（Table 4.17 "Some connections refused – insufficient resources"），然后**等 back-off 再重试**（LE 的 back-off = `max(100ms, 2×(latency+1)×interval)`，Table 4.72）。修法：`_outgoing_ecfc` 标记出向请求在飞 → 入向请求优先判碰撞回 0x0004；`connect_eatt_channels()` 遇 0x0004 退避后换新 identifier 重试一次；`set_le_conn_params_provider` 由 Stack 喂 `_le_conn_params` 算退避时长。**注意判碰撞要排在 listener/PSM 检查之前**——EATT PSM 没有 listener，否则会先落进「SPSM not supported」。
- **回归测试**：`test_actions_conn_param_update.py`（peripheral 走 L2CAP / central 走 HCI）、`test_profile_modules.py::test_l2cap_security_responder_listener_levels` 与 `..._ixit_defines_the_ecfc_mtu_mps_ranges`、`test_le_ecfc_manager.py::test_recycled_handle_starts_unencrypted` / `..._mtu_below_64_is_refused` / `..._reusing_an_allocated_scid_is_refused` / `..._mps_below_minimum_refused_0x0004` / `..._mtu_increase_accepted_0x0000` / `..._during_our_own_request_is_a_collision` / `test_connect_eatt_channels_retries_after_a_collision`、`test_ble.py::test_le_coc_send_queues_instead_of_blocking_on_credits` / `..._close_drops_queued_sdus`、`test_sar.py`（两 PDU 同包 / 完整+半包）、`test_le_signaling_codec.py::..._decodes_dcid_less_refusal`、`test_l2cap_disconnect_send.py::test_reconfigured_event_tells_autopts_the_new_channel_sizes`。
- **真机收割**：`LE/CPU/BV-01`、`LE/CFC/BV-25`、`ECFC/BV-32`、`ECFC/BV-24`、`ECFC/BV-20`、`ECFC/BV-26` 全部 **PASS**；`COS/ECFC/BV-03` 重跑翻 PASS → L2CAP **91/100 (91.0%)**，总 **382/479 (79.7%)**。
- **遗留（本 session 未能翻正，均已定性）**：① `COS/CED/BI-29`——PTS 在第二轮发完「非法 identifier 的响应」后**30s 内不再发任何东西**（我们已把 connect 超时提到协议 RTX 的 30s、逐帧核对空口、并修掉「一个 ACL 包只处理首帧」的 SAR bug），从 IUT 侧已无更多信息；② `ECFC/BV-22` 与 `TIM/BV-03`——**同一现象**：PTS 连上 ACL 后 0.3s **自己断链**（无我方 disconnect 调用日志），WID 只到 56（BV-22 多一个 256），BV-22 的 MSC 要求的「LT 先发 SDU」从未发生；TIM/BV-03 连 WID 255（EATT_CONNECT）都没走到，所以本 session 新加的 EATT 路径**尚未在真机被触发过**（只有单测覆盖）；③ `ECFC/BV-23`/`BV-80`、`LE/CFC/BV-32`、`COS/ECFC/BV-04` INDCSV——数据面用例，已排除 credit 阻塞与缺失 0x84 事件两条，剩余需逐例对 TS purpose 或重跑收割。

### Q: GAP/SEC（AUT+SEM）整簇 `<no verdict>` / FAIL → A: ① **harvest 冷启动必须暖机** ② BI-10 漏映射 ③ BV-24 漏 SC-Only ④ SC **Numeric Comparison 从不上报数字** / 修复提交 6455226…ce1767f（本 session，2026-09-14；GAP 97→100/144）

- **① 首要问题在工具链，不在协议栈**：连续 3 例 `<no verdict>`（PTS 侧连用例都没跑完）。根因是**每次重启 autoptsserver 后 PTS.exe 是冷的**——PTS workspace 还带着上一个用例的状态、PTS.exe 不应答自己控制器的密钥请求，配对用例必在 `Encryption_Change` 以 **reason=0x08** 挂掉（AGENTS.md 早先那条「PTS workspace 状态泄漏」的同一现象）。修法：`scripts/pts_harvest.sh` 支持 `PYBLUEHOST_HARVEST_WARMUP=<已知 PASS 的用例>`，**重启后先跑一个丢弃用的暖机用例**再跑真用例。加了这个之后同一批用例立刻从 `<no verdict>` 变成可判定的 FAIL/INDCSV。**排查 GAP/SEC 前先确认暖机开了**——否则会白查一轮。
- **② `GAP/SEC/SEM/BI-10-C` 漏了 key-size 下限映射**：它是 GAP.TS Table 4.19 里 Central 侧的 level-4 条目，和 BI-09/20/21/22/23（已修）同族，需要同一句 `TestFunc(btp.gap_set_min_enc_key_size, 16)`——**同一张表里唯一漏掉的一个**。修后真机 **PASS**。回归测试把 6 个一起钉住。
- **③ `GAP/SEC/SEM/BV-24-C` 漏了 SC-Only 模式**：它是 BV-28（Central）的 **Peripheral 双胞胎**，step 1 要求 IUT 处于 Secure Connections Only 模式，而它的 LT **不支持 LE SC**、会发起 legacy 配对 → IUT 必须拒绝。没给模式时我们**老老实实走完 legacy 配对并存储 LTK**（空口可见完整 confirm/random/key-distribution，`ltk_stored`，无 Pairing Failed）。修法：把 BV-24 加进已有的 `sc_only_extra`（只加它，BV-23/25 本来就 PASS，不动）。修后 **PASS**。
- **④ SC Numeric Comparison 从不把 6 位数字上报（影响 4 例）**：`_sc_compute_and_await_nc` 只调了本地 `delegate.confirm_numeric`，**从不调 `display_passkey`** → auto-pts 的 `stack.gap.passkey.data` 永远是空 → PTS 侧 WID 等不到数字 → 用例挂住、连 verdict 都没有。`_PtsSmpDelegate` 的注释还写着「SC NC 不可达（BT4.0）」——**已过时**：WID 241 把 io_cap 设成 KeyboardDisplay，双方都是 KeyboardDisplay + SC 就**正好选中 Numeric Comparison**。修法：NC 路径在等待确认前 `await delegate.display_passkey(peer, numeric_value)`（auto-pts 复用同一个 PASSKEY_DISPLAY 事件读这个值）。**真机 `SEM/BV-57-C` PASS**。
- **⑤ Central 侧还要单独开 MITM（角色不对称的根因）**：Central 用例里**我们**发 Pairing Request，而 GAP profile 从不打开 MITM（SM 有 precondition、GAP 没有）→ 我们的请求带 `auth=0x09`（无 MITM），PTS 回 `0x0d`（带 MITM）→ **双方选的关联模型不同**：PTS 按双方 KeyboardDisplay 选 **Numeric Comparison**，我们因为 `both_mitm=False` 选 **Just Works** → PTS 直接以 **Pairing Failed 0x0C（Numeric Comparison Failed）** 中止。空口逐字节可证：`TX 01040009...` / `RX 0204000d...`。修法：加 `hdl_wid_241` override，**除了设 io_cap 还调 `btp.gap_set_mitm_on()`**（同 `hdl_wid_208` 对 Level 4 的做法；**Level 3 就是 authenticated，MITM 必须置位**）。**只影响 initiator**——responder 已改成 mirror 对端请求而非读 config，这正是 Peripheral 双胞胎 BV-57 一直能过的原因。修后 **BV-63 真机 PASS**。
- **⑤bis 加密前的 IND 仍然被转发（Central 的最后一块）**：MITM 修好后 BV-63 仍 INDCSV，空口是 `GATT notif rx handle=0x000b type=2 enc=False pend=False -> forward`。按 TS step 9A.4/9B.4，**加密完成前收到的 IND#1 只能 CFM、不得上报**（gate 靠 `enc or not pend` 判）。根因是 **`_auto_encrypt_on_reconnect` 的 SC-bond 分支把 `_le_encrypt_pending` 清掉了**——那个分支为 SM/*/SCOB 故意不自动恢复加密（会和显式重配对打架），但顺手清 pending 是错的：链路**仍然预期被加密**（只是由对端发起），gate 因此以为「没有待加密」就转发了。**Peripheral 分支一直保持 pending 置位**（它的 Security Request 在飞），这正是 BV-57 能过而 Central 三例不过的来源。修法：SC 分支**不清 pending**，真正的清理交给 `Encryption_Change`。SCOB 不受影响（无 indication）。**修后 BV-63 PASS；回归守卫 BV-56/57/62 仍 PASS。**
- **⑤ter BV-64/67 还要 SC-Only 模式**：这两例是「LE Secure Connections Only – Incoming GATT indication/notification, Central」，step 1 明确「puts the IUT into the Secure Connections Only mode」。补进 `sc_only_extra`（只加失败的这两个，Peripheral 双胞胎 BV-58 等本来就过，不动）。**BV-67 PASS**；BV-64 后移到 **LL 加密超时 0x08**（PTS 控制器不应答，本 session 反复出现的环境症状），需重跑收割。
- **⑥ `BOND_LOST` 事件实装（BV-21/22）**：这两个用例的**全部判定**就是「IUT 有没有把 bond 丢失上报给 upper tester」。我们有 `OP_GAP_EVENT_BOND_LOST`(0x8B) 常量却**从不发**。修法：Stack 在 `Encryption_Change` 状态为 **0x06（PIN or Key Missing）** 时删掉本地 bond 并触发 `on_bond_lost(handle, peer)`，pts-tester 转成 GAP BTP **0x8B**（`addr_type(1)+addr(6, LE)`，对齐 auto-pts 的 `'<B6s'`）。**⚠️ 真机实测拿到的是 `status=0x08`（LL 超时）而不是 TS 要求的 0x06**——PTS/控制器侧没按预期回 PIN-or-Key-Missing，所以新路径**尚未被真机触发**（单测覆盖）。这是正确的规范行为，保留。
- **⑦ 已持有 bond 时收到 Security Request 不该重新配对**：bonded 重连上对端发 Security Request，意思是「**用已有 LTK 加密链路**」，不是「重新配对」。我们一律 `start_initiator` → PTS 没准备再配 → 对我们发出去的 Pairing Request **完全不应答** → 我方 30s 超时（空口：`SMP TX 01000009100707` 之后什么都没有）。影响 `GAP/BROB/BCST/BV-03`、`GAP/BOND/BON/BV-04`（修好后这两例的**重配对消失**，但用例仍卡在后续 WID）。修法：加 `SMPManager._bond_covers(bond, auth_req)`——**只比对 bond 真能提供的位**（unauth bond 满足不了 MITM、legacy bond 满足不了 SC），覆盖得到就**不重新配对**；覆盖不到才配（`GAP/SEC/AUT/BV-13` 正是 JW bond + MITM 请求 → 仍然要重配）。peer 地址经 `set_peer_address_provider` 由 Stack 的 `_le_peer_addrs` 喂。**后续（2026-09-16）**：「已覆盖」时**不能只是不重配**——Security Request 的语义是「用那个 LTK **加密**链路」，还得真的发 `LE_Start_Encryption`，见下文 ES-28650 那条。
- **⑧ `GAP/ADV/BV-21` + `GAP/SCN/BV-01` = 加密广播数据（EAD），已实装核心**：`btp.gap_create_encrypted_adv_data` → **BTP GAP `ENCRYPT_EAD_DATA (0x32)`**（另有 `SET_EAD_KEY_MATERIAL 0x31` / `DECRYPT_EAD_DATA 0x33`）。算法是 **AES-CCM**（不是 SIV）——CSS v15 §1.23.3：nonce = **Randomizer（原样，非反转）‖ IV（反转）**、AAD = 单字节 `0xEA`、MIC 4 字节、输出 = `Randomizer ‖ 密文 ‖ MIC`；key/IV 来自 Encrypted Data Key Material 特征（0x2B88 = key(16)+IV(8)）。`pybluehost/ble/ead.py` 用 `cryptography` 的 `AESCCM` 实现，**测试直接回放 CSS §2.3.1/§2.3.2 的官方样例（逐字节吻合）**——`0xEA` 与两个字段的字节序都是从样例里反推钉死的，不要凭直觉改。***✅ 定案（2026-10-29，两例全 PASS——根因是密钥共享模式，不是 IV 也不是 PTS 黑盒）**：**`set_pixits` 必须 push `TSPX_ead_keys_sharing_method=keys_shared_via_ixit` + `TSPX_encrypted_data_key`/`TSPX_initialization_vector`（zephyr 参考实现同款，常量从 `autopts.pybtp.btp.gap` 单源导入，提交 b88b94c）**。workspace 默认 connection 模式时 LT 经 GATT 读 0x2B88 特征拿密钥，两侧密钥永远对不齐 → `ADV/BV-21` 长期 FAIL（当时误判为「PTS 侧判负需 btsnoop 视角」）、`SCN/BV-01` 的 LT 密文我们无从解。切 IXIT 模式后两侧用同一组字面密钥：`ADV/BV-21` attempt 1 PASS（此前 7 连 FAIL）、`SCN/BV-01` PASS×2。**旧「遗留」前提作废更正**：① 刷新后的 auto-pts 树里 `SCN/BV-01` 只发 **WID 502**（upstream `hdl_wid_502`：passive scan 5s → `decrypt_ead_from_devices()` 经 BTP `DECRYPT_EAD_DATA (0x33)` 客户端解密 → 比对期望明文），根本不会发 WID 505——解密在 auto-pts 客户端做，IUT 只需上报原始 EIR（DEVICE_FOUND 早已是 raw path）+ 0x33 响应 `len(1)+plaintext`（upstream 读 `[1:]`，已兼容）；我们此前还已实装了 BTP `READ_UUID (0x12)` + `GATTClient.read_using_characteristic_uuid`（这条 case 用不上，但工具已就位），且 upstream 的 `gattc_read_uuid` **既发也等响应**（`autopts/pybtp/btp/gatt.py:846/1667`）——旧笔记「不发也不等」有误。② IV 字节序的修复保留（op_31 收到小端 IV 要翻回 CSS 大端形式），它仍然必要。**教训：EAD/新 PIXIT 族 case FAIL 时，先核对 workspace 的行为开关 PIXIT（参考实现在 `set_pixits` 推了什么）再谈协议——「IUT 正确 + PTS 黑盒」往往是「LT 行为模式不同」的误标。**
- **⑨ `PADV/PAST` 的根因是「OCF 写错」（本 session 已修）+ 硬件能力澄清**：
  - **真 bug #1（决定性，已修）**：**PAST 族的 OCF 整体错位**。对照 Zephyr 权威表 `BT_HCI_OP_LE_*`：`0x2059` = Set PA Receive Enable、**`0x205A` = PA Sync Transfer**、**`0x205C` = Set PA Sync Transfer Parameters**、`0x205D` = Set Default PAST Parameters。我们的常量却是 `SYNC_TRANSFER = 0x49`、`SET_..._PARAMS = 0x5A` —— 于是「设置 PAST 参数」实际在空口发的是 **`0x205A`（Sync Transfer）**，那是条 6 字节、第三个字段是 **Sync_Handle** 的命令：我们的 8 字节 body 把 `0x01F4` 塞进 Sync_Handle → 控制器回 **`0x42 Unknown Advertising Identifier`**。**这个错误码本身就是线索**——它属于「按广告/同步句柄寻址」的命令族，而不是按连接句柄。修后空口确认 `opcode=0x205C`、状态由 `0x42` 变成 **`0x0C Command Disallowed`**（命令认了，只是当前状态不允许），回归测试钉死四个 OCF。
  - **真 bug #2（已修）**：`LE_Set_Periodic_Advertising_Sync_Transfer_Parameters` 的 HCI body 之前是 6 字节（`<BHHB`，从 Mode 开始、漏 `Connection_Handle`），正确是 8 字节 `<HBHHB`。`IutActions` 现在从活连接解析句柄。
  - **诊断盲区（已修）**：HCI 状态在 **`event.return_parameters[0]`**，不是 `.status`——读错只会打印 `?`。参数命令已改走 `_send`/`_check_status`，被拒会打 WARNING（**正是这条日志把 0x42/0x0C 揪出来的**）。
  - **⚠️ 我一度误判「两颗 BE200 固件不同」——那是伪影，已推翻**。干净环境下连测两次，**两颗 8087:0036 对 `0x205A` 都回 `0x02`**（命令已知、句柄无连接），且 `Read_Local_Version_Information` 完全一致（`hci_rev=0x550D / lmp_subver=0x5500 / manufacturer=0x020D / lmp_palver=68`）。当时拿到的 `0x01` 是**瞬时状态**造成的（疑似与另一个进程刚释放 dongle 有关）。**教训：单次裸探测的否定结论不足以下硬件判决，必须复测 + 交叉核对版本信息。**
  - **当前座架**：IUT = `usb:8087:0036#2`（`94:53:FF:1E:6A:EE`）、PTS dongle = `USB_INTEL:Free:6&1687A1FD&0&1`（`5C:67`）。⚠️ `8087:0036` **枚举顺序随拔插/重启互换**，跑前用读地址的方式核对 MAC↔序号（`ixit.py` 顶部有说明）。
  - **遗留**：`PASE/BV-03..06`、`PAST/*` 仍卡在 `0x0C Command Disallowed`，需查「控制器在什么状态下才允许这条命令」。`PASE/BV-01/02`（create_sync 方向）是独立线索。**⚠️ 这两条线索已分别结案，而且是两个不同的根因**：`PASE/BV-01` 的 create_sync 方向 = **LE Event Mask 只开 bit 0-4**（同步确实建立了，事件被挡在控制器里，见上面那条 PADV 条目）；`PAST/BV-02` 的 0x0C = **存在 extended advertising set 时 legacy `LE_Create_Connection` 被拒**，改用 `LE_Extended_Create_Connection (0x2043)` 后整条序列回到 `0x00`（见下面那条 PAST 条目）。**「同一个错误码 = 同一个根因」是不成立的假设**。
- **⑩ HCI 常量全量审计（发现 PAST 之后做的系统性核对）**：把 `pybluehost/hci/constants.py` 里**全部 78 条** `make_opcode(OGF.X, 0xYY)` 与 Zephyr 权威表 `BT_HCI_OP_* → BT_OP(OGF, OCF)` 逐条对照，按 opcode 反查名字。**结论：修完 PAST 四条之后，其余全部吻合**（名字只是缩写风格不同，如 `HCI_LE_SET_ADVERTISING_PARAMS` ↔ `LE_SET_ADV_PARAM`）——说明没有别的静默 OCF bug。**方法可复用**：抓一份参考实现的 HCI 头（Zephyr `include/zephyr/bluetooth/hci_types.h` 就够），按 opcode 建反查表，再和我们的常量对拍；比逐个人肉读 spec 快得多。
- **⑪ GAP/BIS 可用裸探测先判可行性（省下大量时间）**：两份用例考的是**不同方向**——
  - `GAP/BIS/BBM/BV-01`「Broadcasting mode」= IUT **广播** BIS → 需要 `LE_Create_BIG`；
  - `GAP/BIS/BSE/BV-01`「Synchronization Establishment」= IUT **同步**到 BIG → 需要 `LE_Big_Create_Sync`。
  对 BE200 逐个发命令探测（OCF 0x2061–0x206F）：**`LE_CREATE_BIG (0x2068)` 等广播/ISO 命令全部已知**（回 CmdStatus 或 0x02），而 **`LE_BIG_CREATE_SYNC (0x206B)` / `LE_BIG_TERMINATE_SYNC (0x206C)` 回 `0x01 Unknown HCI Command`** → **`BBM/BV-01` 在 BE200 上可做，`BSE/BV-01` 在这块硬件上不可能通过**。BTP 侧对应的 opcode：`CREATE_BIG = 0x2d`、`BIS_BROADCAST = 0x2e`（广播侧）；`BIG_CREATE_SYNC = 0x2c`（接收侧）。**经验：动辄几小时的新特性，先花两分钟用裸探测确认控制器到底认不认这条命令。**
  - **⚠️ 定案（2026-10-29，AX201 现座架）**：裸探测换到当前 IUT **AX201 (`usb:8087:0026#1`)** 复测两轮，三重独立证据一致——`0x2068` → `0x01 Unknown Command`、`LE_Read_Buffer_Size_V2 (0x2060)` → `0x01`、LE features `ff59000800000000` **bit 30 ISO_Broadcaster=0**（bit 13 Periodic 也是 0）→ **`BBM/BV-01` 与 `BSE/BV-01` 在 AX201 上同为 controller-blocked**，矩阵已记 blocked。**此前笔记里「AX201 bit30=1」的 `fff9017fae000000` 是 BE200 的 feature set，张冠李戴**——换座架/换 dongle 后，凡引用旧 feature-set/能力结论必须重新探测。解锁路径 = BE200 当 IUT 的整座架互换（它 0x2068 已知），但为单例换座架不值（全矩阵回归面），放弃。
- **⑫ `GAP/BROB/OBSV/BV-05` PASS——「主动扫描」被读成了「受限发现」（一条链五个坑）**：这一例最终翻正，靠的是一条链，每一环都有空口证据，值得整体记住：
  1. **`START_DISCOVERY` 的 flags 用错了位**（决定性）：auto-pts 的常量是 `GAP_DISCOVERY_FLAG_LE=0x01 / BREDR=0x02 / **LIMITED=0x04** / **LE_ACTIVE_SCAN=0x08** / LE_OBSERVE=0x10`，我们测的是 `flags & 0x04`（**受限发现**位）→ **所有「主动扫描」用例实际都跑成了被动扫描**，不发 SCAN_REQ、拿不到扫描响应。**别凭「第 2 位大概是 active」猜——去 `autopts/pybtp/defs.py` 抄 `GAP_DISCOVERY_FLAG_*`。**
  2. **扫描响应要并进同一条报告**：主动扫描会把同一设备报**两次**（事件类型 0x00/0x01/0x03 与 **0x04**），而 auto-pts 是**每个 DEVICE_FOUND 事件 append 一个 LeAdv**、校验「广告数据 + 扫描响应」时按**一个设备一条完整 EIR** 比 → 分开转发必然对不上。`BLEScanner` 现在把广告那半**缓存一个合并窗口**（扫描响应到了立即冲刷），每设备只发一条合并 EIR。
  3. **EIR 要发原始字节**：DEVICE_FOUND 的载荷原本走 `AdvertisingData.to_bytes()`——它**只建模少数 AD type、重新序列化会丢掉其余**（URI/服务数据/厂商数据）。BV-05/06 的扫描响应正是 **URI AD 结构(0x24)**，于是「收到了却报不上去」。`ScanResult.raw_advertising_data` 现在带原始字节，BTP 适配器优先用它。
  4. **停止扫描时要冲刷待发表**：合并窗口内的报表若在 `stop()` 时被丢，表现和「IUT 从来没看见」一模一样。
  5. **扫描器此前完全没有日志**——加上 `BLEScanner: report <addr> ad=N rsp=N type=0xNN` 之后，**一眼看出每一条 `rsp=0`**，前四个坑才得以定位。**「看不到就修不动」：任何一类事件先加一行摘要日志。**
  - 真机：`GAP/BROB/OBSV/BV-05` **PASS**；`BV-06`（双方都用 RPA）仍 INDCSV，属 RPA 簇。回归守卫 `GAP/SEC/AUT/BV-11` PASS。
- **GAP 全量分诊结论（105/144）**：剩余 39 例按下述分类，**不能靠「重跑」解决**——① **12 例是明确的新特性**：`PADV/*` 10 例（周期广播同步；**座架已换成 IUT=`94:53` BE200（唯一支持 PAST 的那颗）**，但 `0x205A` 仍被控制器以 0x42 拒绝，见 ⑨；create_sync 子簇同样 INDCSV，是独立线索）+ `BIS/*` 2 例（BIG/BIS，未开工）；② **~13 例 WID 卡死**：WID 1002（"Please enter Secure Id"）等 `stack.gap.get_passkey()` 返回 None → 用例挂到无判定（`BCST/BV-03`、`BCST/BV-05` 的 WID 80 RPA 广播同族）；③ **~8 例 INDCSV/FAIL 的 SEC/AUT**：多是「已加密链路上再配对/再加密」的细节（BV-13/14 在第二次 `LE_Start_Encryption` 拿 `status=0x08`——控制器接受命令但 LL 握手超时）。**这三类都还需要逐例做**，不存在一次性开关。
  - **⚠️ 修订（2026-09-16）**：① 里的 PADV 那一半**已结案，且是两个独立根因**——create_sync 子簇 = LE Event Mask 只开 bit 0-4（见上面 PADV 条目，`PASE/BV-01-C` PASS）；PAST 子簇的 `0x0C` = **存在 extended advertising set 时 legacy initiator 被拒**，改用 `LE_Extended_Create_Connection (0x2043)`（见下面 PAST 条目，`PAST/BV-02-C` PASS）。不是「新特性缺口」也不是控制器状态问题。分诊表里凡是「命令成功但事件不来」的判词都应当先过一遍 mask；凡是 `0x0C Command Disallowed` 都要先问「**是哪条命令把我带进这个状态的**」。

- **经验**：① GAP/SEC 这一簇**必须先排除环境因素**再读协议——`<no verdict>` 十有八九是冷启动；② 「IUT 该某处上报但从不报」是 auto-pts 用例挂死的典型形态（`passkey.data` 空、`bond_lost_ev_data` 空），排查时先看用例卡在哪个 `wait_for_*`；③ 和 L2CAP 那批一样，**同一张 TS 表里的用例要么全映射要么全漏**——BI-10、BV-24 都是「表里其他条目已处理、独漏一个」；④ 用例里「IUT 该做某个动作但没做」时，先看 **auto-pts 那边有没有这个 WID 的实现**——`MissingWIDError`（如 WID 505）说明连参考实现都没写，不是我们的行为不对。

### Q: PTS L2CAP BV-26/27（K-frame SDU>MTU / payload>MPS）跑满 ~320s PTS TIMEOUT → A: 违规检测在 `_on_pdu`（SAR 重组后），但 PTS 只发首片就等断连 / 修复提交（本 session）

- **现象**：`L2CAP/LE/CFC/BV-26-C`、`BV-27-C` 跑满 ~320s `TSPX_time_guard` 判 PTS TIMEOUT。btsnoop 显示 PTS connect 后**只发首片 ACL fragment**（声明 L2CAP length=259 / SDU length=257，实际只发 3 字节），然后干等 ~303s 才断 ACL。
- **根因**：K-frame 违规检测（SDU length > MTU、Information Payload > MPS）写在 `LECoCChannel._on_pdu`，它在 **SAR 重组完成后**才被调。而 BV-26/27 里 PTS 只发首片（违规已能从 L2CAP length 字段 + SDU-length 前缀判定），SAR 永远组不齐 → `_on_pdu` 从不跑 → 违规检测不到 → 干等超时。
- **关键认知**：L2CAP.TS 明确违规是**相对 IUT 自己 advertise 的 MTU/MPS**（"greater than the MTU/MPS of the IUT"），所以**不用改 advertise 值**（512/247 保持）——PTS 会按你 advertise 的值造超限帧。缺的只是**首片即判**。
- **解决**：`L2CAPManager.on_acl_data` 加首片 fast-path——`ACL_PB_FIRST_AUTO_FLUSH` 时先解析 L2CAP header，对 LE CoC channel 调 `LECoCChannel.check_first_fragment_violation(declared_len, payload_prefix)`：`declared_len > rx_mps` → BV-27；首 K-frame（`_rx_sdu_expected_len==0`）的 SDU length > `rx_mtu` → BV-26。命中即 `_signal_violation` 断信道 + `_sar.reset(handle)`，**不再 feed SAR**。FixedChannel/ClassicChannel 无此方法，`getattr` 跳过不受影响（ATT/SMP/signaling 不被误伤）。
- **回归测试**：`test_le_coc_credits.py::test_first_fragment_*`（BV-26/27 首片断连、合法首片不误判、fixed channel 跳过）。真机 BV-26/27 PASS（~14s，原 ~320s timeout，2026-08-24）；控制例 BV-07（合法帧不误判）、BV-28（全帧路径无回归）同批 PASS。

### Q: PTS SM 全系（尤其 SC）BTP ERROR / auto-pts `wait_for_disconnection` 30s 超时 → A: ① IUT 无 bond storage ② "disconnected" 事件丢 peer_address 致 DEVICE_DISCONNECTED 被丢弃 / 修复提交 ff51a72

- **现象**：`SM/CEN/SCJW/BV-01-C` 等 BTP ERROR。抓包+日志还原 flow：WID 100(connect)→WID 108(pair，**成功**，ENC_CHANGE en=1)→WID 102(disconnect)→**auto-pts 等 30s 都没等到断连**→WID 100(reconnect)→WID 108(再 pair)→BTP ERROR。
- **根因（两个独立 bug 叠加）**：
  1. **无 bond storage**：`StackConfig.bond_storage` 默认 `None`，pts-tester 从不设置 → 配对完 LTK 不落盘（日志 "no bond storage configured"），断连重连后无密钥可恢复加密。
  2. **"disconnected" 事件丢 peer_address（更关键、影响面更大）**：`stack._on_hci_event` 发 `StackConnectionEvent(state="disconnected")` 时**不带 peer_address** → pts-tester `_on_conn` 的 `if peer is None: return` 把 **DEVICE_DISCONNECTED BTP 事件整个丢弃** → auto-pts 的 `wait_for_disconnection()` 永远等不到（30s 超时），后续 reconnect/re-pair 全乱。**凡是 auto-pts 要等断连的 case（WID 102 及大量 SM/GAP/L2CAP）都会踩这条**，不止 SC。
- **解决**：① 加 `InMemoryBondStorage`（内存版，per-pts-tester 进程干净 slate，不跨 case 泄漏），在 `_pts_tester_main` 同时设 `stack.config.bond_storage` 和 `stack._smp._bond_storage`（SMP 配对时读后者、`stack.encrypt` 读前者），并激活 `auto_encrypt_on_bonded_reconnect`（重连自动用 bond 恢复加密）。② stack 新增 `_le_peer_addrs` 句柄→peer 映射（LE 连接建立时填；**不能用 SMP 的 `_peer_addrs`**——它在 channel-unbind 时先被 pop，等 disconnected 事件发出时已空），disconnected 事件带上并 pop。
- **关键认知**：① auto-pts 的 `wait_for_disconnection`/`is_connected` 靠 DEVICE_CONNECTED/DISCONNECTED **事件**更新 model，事件丢了它不是等不到而是**永远判已连接**；② SC 配对本身（P-256 软件 crypto、f5/f6）是好的——首连加密 ENC_CHANGE st=0x00 成功，问题全在断连/重连的**外围接线**（bond 持久化 + 断连事件）。
- **回归测试**：`test_stack.py::test_stack_reports_disconnection_peer_address`。真机 `SM/CEN/SCJW/BV-01-C` PASS（原 BTP ERROR）；无回归（SM/CEN/JW/BV-01、SM/PER/JW/BV-02、SM/CEN/PKE/BV-04 仍 PASS，2026-08-24）。

### Q: PTS SM/CEN 所有 passkey 用例（PKE/SCPK/SCOB）BTP TIMEOUT 或 Pairing Failed 0x04，JW 却全过 → A: ① PAIR 响应死锁 ② legacy c1/s1 没在 AES 边界翻 TK 密钥 / 修复提交 f0a3f2f + 1da9cda + 63a1831

- **现象**：`SM/CEN/PKE/BV-01-C` 等发起方+passkey 用例批量挂，而 `SM/CEN/JW/*`、`SM/PER/*` 大多能过。先是 BTP TIMEOUT；修掉死锁后变 Pairing Failed reason=0x04（Confirm Value Failed）。
- **根因 1（死锁，f0a3f2f）**：`GAP _handle_op_11`(PAIR) 原本 `await actions.pair()` 等整个配对跑完才回响应。但上游 `btp_gap.txt 0x11` 契约是「**发起**即回响应，完成走事件」。passkey 流程里 auto-pts 主线程堵在 `gap_pair()` 等响应，永远跑不到 WID 104（enter passkey）那条 MMI → PTS 拿不到 passkey → 循环等待超时。修法：`_handle_op_11` 把 pair 丢后台 task、立即回 SUCCESS，完成/失败经 `SEC_LEVEL_CHANGED`/`PAIRING_FAILED` 事件上报。JW 不回归是因为 MMI 序列由 PTS **按空口观察驱动**（看到加密完成才发下一条），不是 auto-pts 抢跑。
- **根因 2（更隐蔽，1da9cda）**：修完死锁后 PKE 仍 Confirm Value Failed。逐字节核算：IUT 的 confirm 能用 `(tk=显示值, mrand, preq, pres, iat=0, rat=0, ia/ra=大端)` 被**精确复现**，且 JW(tk=0) 的 confirm 用**同一套参数**也复现 → 参数 100% 正确。唯一未测变量是 **TK 本身**：legacy c1/s1 调 `_aes_ecb(k, …)` 时翻了数据块（`r[::-1]`/`p1[::-1]`）但**没翻密钥 k**。SMP 安全函数 `e()` 对 key/plaintext/ciphertext **三者都**小端翻转（tinycrypt/zephyr `aes_128` 如此）；tk=0 时翻不翻一样（所以 JW 和全部现存 c1 向量——全是 k=0——测不出），**非零 passkey TK 时密钥字节序就反了** → PTS 拒 confirm。修法：c1/s1 里 `_aes_ecb(k[::-1], …)`。**经验：给 c1/s1 这类「翻转在 AES 边界」的函数加测试向量时，必须包含非零 key，否则翻没翻 key 永远测不出。**
- **附带（63a1831）**：BTP GAP 事件 opcode 表漏了 `PAIRING_CONSENT_REQ(0x8A)`，导致 `BOND_LOST`/`PAIRING_FAILED` 整体错一位；PAIRING_FAILED 发成 0x8B 被 auto-pts 当 BOND_LOST 解析报 `BTPError(Invalid data length)` → FATAL ERROR。对齐上游 defs.py（0x8A/0x8B/0x8C）。
- **调试方法（值得复用）**：① 抓 `PYBLUEHOST_IUT_LOG_LEVEL=DEBUG` 的 `SMP TX/RX` 原始字节；② 用项目 `SMPCrypto.c1` 以真实空口值（tk/mrand/preq/pres/地址）手算，看能否复现 IUT 实际发的 confirm——能复现说明 IUT 自洽、问题在 PTS 侧用的某个输入；③ 拿一个**能过**的同族用例（JW）复现其 confirm 来锁定参数正确性，把变量收敛到只剩 TK。
- **回归测试**：`test_smp.py::test_c1_flips_nonzero_key_at_aes_boundary` / `test_s1_flips_nonzero_key_at_aes_boundary`（非零 key 向量）；`test_gap_service.py::test_pair_responds_immediately_without_waiting_for_completion` / `test_pair_async_failure_emits_pairing_failed_event`。真机 SM/CEN/{JW,PKE}/BV-01、PKE/BV-05、PKE/BI-01 PASS（2026-08-25）。
- **遗留**：SCPK/SCOB 走 SC crypto（f4/f5/f6，**不**经 c1），c1 修复对它们无效，是独立的下一跳；EKS/KDU/OOB 另查。

### Q: PTS SM/*/SCPK 全系 INDCSV——round-1 被 PTS 回 0x04（Confirm Value Failed），过了 20 轮又在 DHKey Check 回 0x0B → A: ① SC passkey round 位序写反（MSB-first，应 LSB-first）② f6 的 r 输入硬编码 0（passkey 应用 passkey 值） / 修复提交 322797f

- **现象**：`SM/CEN/SCPK/BV-01-C` INDCSV。抓 `SMP TX/RX`：IUT 发完 round-1 的 Ca_1(0x03)+Na_1(0x04) 后，PTS 回 `05 04`(Confirm Value Failed)。而 `SM/CEN/SCJW/BV-01-C`（同角色、同 `_sc_f4`，只是 Z=0）却 PASS。
- **排查关键（收敛法）**：① 用 `_sc_f4(iut_x_le, pts_x_le, na1, 0x81)` **完整复现** IUT 实际发的 Ca_1 → IUT 自洽，confirm 按 spec 算对；② SCJW PASS 证明公钥字节序、`_sc_f4`/`_sc_aes_cmac` 反转、DHKey 都对——**唯一与 JW 的差异就是 Z 字节**(JW Z=0x00,SCPK Z=0x80|bit)；③ 于是变量只剩 round 用的那个 bit。
- **根因 1（位序反了）**：IUT 用 `(passkey >> (20 - i)) & 1`(i=1 → bit19 = **MSB-first**)。但 zephyr（参考 IUT，能过 PTS）是 `r = (passkey >> passkey_round) & 1`,`passkey_round` **0-based 递增** → round 1 用 **bit 0 = LSB-first**。passkey=665370 时 bit19=1/bit0=0,IUT 错用 Z=0x81,PTS 期望 Z=0x80 → 0x04。修法：三处 `_sc_passkey_*` 改 `(passkey >> (i-1)) & 1`。**注意 spec 图 `ra = ra1|ra2|...ra20` 有歧义，别凭它猜——以 zephyr `passkey >> passkey_round` 为准。**
- **根因 2（f6 r 值）**：修完位序后 20 轮全过，IUT 发 DHKey Check(0x0d) 后 PTS 回 `05 0b`(DHKey Check Failed)。查得 `_sc_f6` 的 `r` 参数**四处全硬编码 `b"\x00"*16`**——这对 JW/NC 对（ra=rb=0)，但 passkey entry 要 `r = passkey`（20-bit 值，zephyr `memcpy(r, &passkey, sizeof(passkey))` 进清零的 16 字节 buffer = `passkey.to_bytes(16,'little')`)。修法：加 `_sc_f6_r(ctx)` 按 `_association_model` 分流，passkey_entry 用 passkey 值，JW/NC 用 0。
- **⚠️ loopback 测不出这类 bug**：`tests/integration/test_pairing_sc_passkey_loopback.py` 两端同栈，MSB 错序/r=0 两端一致也能自洽过——只有对**真实参考实现**(PTS/zephyr）才暴露。凡是「两端约定必须匹配第三方」的协议常量（位序、填充、字段顺序），loopback 绿≠对，必须真机或对 spec/参考源码核对。
- **回归测试**：`test_smp_passkey_sc.py` 的 round-1/round-20/responder 三处改为断言 LSB-first（round i 用 bit i-1)；新增 `test_sc_f6_r_zero_for_just_works_and_numeric_comparison` / `test_sc_f6_r_passkey_little_endian_for_passkey_entry`。真机 SCPK 8/11 PASS（原 2/11):CEN BV-01/04/05+BI-01/02、PER BV-02/03+BI-03（2026-08-25）。
- **遗留**：`SM/CEN/SCPK/BI-03` + `SM/PER/SCPK/BI-05`("enter invalid pin" 负例）FATAL ERROR——auto-pts WID handler 拿 `stack.gap.passkey.data` 算错误 passkey 时为 None(`int(None)`),**输入方向的 io_cap/WID 流程问题**，非 crypto；`SM/PER/SCPK/BI-04` 是 peripheral flaky PTS TIMEOUT。SCOB（全部 INDCSV）需 OOB 数据供给，是下一跳。

### Q: PTS GAP/SEC(AUT/SEM)整簇 INDCSV——PTS 读 IUT 保护特征后链路 0x13 断、IUT 全程无 ATT 响应 → A: ① ATT fixed channel 单 on_data,GATT client bearer `set_events` 把 GATT server 顶掉 ② SMP 不处理 peripheral 发来的 Security Request / 修复提交 cf314e4

- **现象**：`GAP/SEC/AUT/BV-12-C` INDCSV。btsnoop 全程只有一条 `PTS->IUT ATT ReadReq 0a0300`,**IUT 一条 ATT 响应都没发**，随后 PTS 断连。iut log 收到 `ATT PDU opcode=0x0A` 却无下文。
- **根因 1(client 顶掉 server)**:`_attach_gatt_server_to_att_channels`(stack.py)用 `set_events(on_att_data)` 绑 GATT server，但 ATT fixed channel 只有**一个** on_data。GAP/SEC 里 IUT 是 central,`connect_gatt`(stack.py)/`_resolve_gatt_client`(pts/actions.py)建 GATT client bearer 时又 `set_events(bearer._on_pdu)` **整体覆盖** server handler，且 `_gatt_server_bound` 已置位永不重绑。于是 PTS 一读保护特征，请求进了 client bearer 的 response 分发器（不匹配任何 pending future）被丢弃 → server 永不响应。
- **修法 1**：加 `pybluehost/l2cap/channel.py::install_att_channel_mux`——在 ATT channel 上装一个**按 opcode 分流**的稳定 dispatcher:request/command(0x02/04/06/08/0A/0C/10/12/16/18/52/D2)→ server handler,response/ntf/ind/cfm → client bearer。server/client 各自注册进 mux 的 `_att_server_handler`/`_att_client_handler`（晚绑定、顺序无关、缺一即丢该侧），不再互踩。**GATT/SR（纯 server）与 GATT/CL（纯 client）行为不变**(request/response opcode 天然不相交）。
- **根因 2(Security Request 被丢）**：修完 mux 后 server 正确回 `ErrRsp 0x05`(Insufficient Auth),PTS 回 `SMP SecurityReq 0b0d`,IUT 却 `SMP PDU dropped: no context` → PTS PairingFailed 断连。我们的 SMP 只在「自己 pair()」或「收到 Pairing Request」时建 context,**不处理 peripheral 发来的 Security Request(0x0B)**。
- **修法 2**：按 Core Vol 3 Part H §3.6.1,central 收到 Security Request 应发起配对——`SMPManager.on_pdu` 对 0x0B 调 `start_initiator`，并把 Security Request 的 **MITM 位**(`peer_sec_req_auth_req`)OR 进 Pairing Request（否则 Just Works → unauthenticated → read_authn 特征配完仍读不了）。bluez 用 `TSPX_iut_mandates_mitm=FALSE` 即此义：不强制 MITM，由对端 Security Request 驱动。
- **空口验证**(BV-12):ReadReq→ErrRsp 0x05→SecurityReq(0x0D)→**IUT PairingReq(auth_req=0x0D)**→SC passkey entry 20 轮→PASS（原 INDCSV,29.9s)。
- **回归测试**:`tests/unit/l2cap/test_att_channel_mux.py`(request→server/response→client、server 在 client 后 attach 仍存活、纯 server 丢 response、幂等）；`tests/unit/ble/test_smp_security_request.py`(SecurityReq→initiator 配对、MITM 位传播、无 MITM 不强设、unbound handle 不抛）。

### Q: PTS GAP/SEC peripheral 用例（IUT 广播被连）PTS TIMEOUT + BV-24/29/39/43 INDCSV → A: ① `stack.pair` 不分角色，peripheral 也发 Pairing Request（协议违规被 central 忽略）② init_gatt_db 缺 write_enc 特征 / 修复提交 3a595ef

- **根因 1(peripheral 发 Pairing Request)**:`stack.pair` 恒调 `start_initiator`（发 Pairing Request)。但 IUT 当 peripheral(PTS 连入）时按 spec §3.2 **不能**发 Pairing Request，只能发 Security Request 请 central 配对。BTP GAP PAIR 在 peripheral 链路上因此从不配对。修法：stack 存 per-connection LE 角色(`_le_conn_roles`),`pair()` 按角色分流——peripheral → `request_security_and_wait`（发 Security Request，等 central 驱动的 responder 配对完成）;central → `start_initiator`。
- **根因 2（缺 write_enc 特征）**:`hdl_wid_139` 按用例所需权限在 IUT db 里找特征——BV-24/29/39/43 要 `Perm.write_enc`，但 zephyr 参考 db（和我们原先）只有 read_authn(VND16_2)/read_enc(VND16_3)/write_authn(VND16_5)三个 → 找不到返回 handle 0 → INDCSV。修法：init_gatt_db 追加 write_enc 特征(VND16_4,**append 在 VND16_5 后**,handle 3/7 不动，零回归）。
- **空口验证**(BV-24):WriteReq(0x0009)→ErrRsp **0x0F**(Insufficient Encryption)→legacy 配对→LTK 加密→重写 WriteRsp 成功——write_enc 强制+加密升级功能打通（INDCSV→FAIL，剩余 FAIL 为更细断言待 TS 文本核对）。

### Q: PTS SM/*/OOB（legacy OOB 配对）全 INDCSV——WID 147 配 OOB 数据后配对从不成功 → A: BTP OOB_LEGACY_SET_DATA(0x18) 是空 stub,OOB TK 没到 SMP / 修复提交（本 session）

- **现象**：`SM/CEN/OOB/BV-01-C` 等，WID 147「enter 16 bytes IUT's OOB Data」→ auto-pts 用 `gap_oob_legacy_set_data`(**BTP cmd 0x18**）把 OOB 数据**推进** IUT，然后 WID 100 connect + WID 108 pair → 配对失败 INDCSV（`SMP pairing failed reason=None`）。
- **根因**：GAP BTP service 的 `_handle_op_18` 原本只 ack 不存 → OOB TK 从没到 SMP；且 legacy 配对路径 `oob_data_flag` 硬编码 0、`ctx.tk` 恒 0(Just Works)→ IUT 从不声明有 OOB 数据、也不用 OOB TK,PTS 按 OOB 配对自然对不上。
- **修法（legacy OOB / Sub-Plan 3c)**:① `_handle_op_18` 存 16 字节 TK 并经 `IutActions.set_oob_legacy_data` → `SMPManager.set_oob_legacy_data`；② `SMPPairingContext` 加 `oob_tk` 字段，两个 ctx 创建点（initiator/responder）传播；③ `_smp_state.py` 双方 Pairing Request/Response 的 `oob_data_flag = 1 if oob_tk else 0`;④ legacy 路径在 model 选择**之前**加 OOB 分支——`ctx.tk = oob_tk`，走 Just Works 的 confirm/random 流程（OOB 优先级高于 passkey/JW)。**字节序：auto-pts 已用 `hex_str_to_le_bytes` 转好，IUT 直接用收到的 16 字节当 TK，别再翻。**
- **验证**：真机 `SM/CEN/OOB/BV-01-C`、`BV-10-C` PTS **PASS**(2026-08-26)——Pairing Request `oob_data_flag=0x01`,confirm/random 全过、EncryptChange enabled。
- **遗留（SM/PER/OOB responder 方向，2026-08-26 实测定性）**:BV-02 等 responder 用例 PTS 做 **4 轮**(WID 147→115 循环）OOB 配对。**空口逐字节确认协议完全正确**：每轮 PairReq(oob=1)→PairRsp(oob=1)→Confirm→Random→EncChange(status=0x00,enabled=1)→Disconnect(0x13)，全 4 轮的 OOB 配对+加密都成功。INDCSV 的真因是 **peripheral 多轮连接 flaky**——4 轮里只有 3 轮 `DEVICE_CONNECTED`（第 4 轮 START_ADVERTISING 有发且 ACK、NEW_SETTINGS 也正常推，但 PTS 的 connect 没完成）。**不是协议 bug**：① 曾怀疑的「auth_req bonding 位 0x05 vs PTS 0x04」已做成 mirror 修复（提交 ddcb364,TDD 测试 `test_responder_mirrors_bonding_bit_from_peer_request`)——修后仍 INDCSV，排除 bonding 假说，但 mirror 本身 spec-正确故保留（SM/PER/JW/BV-02 回归 PASS)。② 多轮重广播 NEW_SETTINGS 修复（3958e82）正常工作。**结论：协议层已尽力，剩下的是 dongle peripheral 连接可靠性，重跑有机会翻 PASS，不作为协议栈 bug 继续查。**
- **⚠️ 环境坑（2026-08-26 踩）**:**`uv run <cmd>` 会把 editable 安装的 `auto-pts` 从 venv 里冲掉**（它按 pyproject.toml re-sync,auto-pts 不是声明依赖）→ autoptsclient 起不来报 `ModuleNotFoundError: No module named 'autopts'`。跑单测**别用 `uv run pytest`，改用 `./.venv/Scripts/python.exe -m pytest`**。若已冲掉：`./.venv/Scripts/python.exe -m pip install -e "C:/Users/admin/AppData/Local/Temp/auto-pts" --no-deps` 重装（注意：`--no-deps` 单独装可能生成空 MAPPING 的 broken finder，需先 `pip uninstall autopts` + 删 `__editable__.autopts*` 再重装）；若 `import autopts` 仍失败，查 `/tmp/auto-pts` 的 `autopts/__init__.py` 是否被误删（`git status` 看 ` D `,`git checkout -- autopts/__init__.py` 恢复）。pts_run_batch.sh 本身用 `.venv/Scripts/python.exe` 直调，不受 uv 影响。
- **回归测试**：`tests/unit/ble/test_smp_oob_legacy.py`(initiator/responder oob_data_flag=1 + 用 OOB TK；无 OOB 时 flag=0/TK=0)。

### Q: PTS SM/*/SCOB（Secure Connections OOB）全 INDCSV——配对在 Public Key 交换后被 PTS 断连 → A: ① SC OOB 全实装（本 session，feature）② IUT Pairing Request 带 MITM=1 偏离测试要求 / 修复提交（本 session）

- **现象**：`SM/CEN/SCOB/*`、`SM/PER/SCOB/*` 全 INDCSV。SC OOB 与 legacy OOB 完全不同——**不**共享 TK，而是各自把 OOB 数据 `{addr, r, C}` 带外交换，`C = f4(PKx, PKx, r, 0)` 提交到**自己的** P-256 公钥 X；空口**省掉 Pairing Confirm**（只发 Public Key + Random）;f5 用**新鲜** Na/Nb，但 f6 的 r 输入用 **OOB random**(EA 用 responder 的、EB 用 initiator 的）。
- **实装（Core Vol 3 Part H §2.3.5.6.4,Figure 2.5/2.6）**:BTP `OOB_SC_GET_LOCAL_DATA(0x19)` 回 `(r, C)`(WID 148→r、147→C)、`OOB_SC_SET_REMOTE_DATA(0x1a)` 存对端 `(r, C)`(WID 149)。`SMPManager.get_oob_sc_local_data` **惰性生成 P-256 keypair + rand + conf 并缓存**（幂等，WID 147/148 一致，且**空口配对必须复用同一 keypair**，否则 PTS 拿我们的 conf 核对公钥对不上）；`set_oob_sc_remote_data` 存对端块。`_apply_oob_sc` 在两个 ctx 创建点（initiator/responder）把它们拷到 ctx。`_association_model` SC 分支顶部加 `_sc_oob_present → "oob"`(OOB 优先于 NC/passkey/JW);f6 的 r 输入按 EA/EB 分流（`_sc_f6_r_for_ea/_for_eb`);io_cap 中间字节用**真实 OOB flag**（不再硬编码 0)。收到对端公钥时 `_sc_oob_verify_peer_confirm` 核对 `f4(peer_x, peer_x, peer_oob_rand, 0) == peer_oob_conf`，不符则 abort(BI 用例）。**字节序：BTP 收发都是 LE,auto-pts `le_bytes_to_hex_str` 显示才反转，f4/f6 内部全程 LE,别翻。**
- **关键认知（OOB data flag 语义，曾写反）**:flag = 「**对端**的 OOB 数据已就绪」，只有**收到**对端 OOB 块（WID 149/set_remote）时才置 1,**不是**因为我们生成了本地块。写反会导致 PTS 每轮 Pairing Not Supported(0x05) abort。
- **关键认知（SC bond 重连）**:`auto_encrypt_on_bonded_reconnect`(Central 角色）对 **SC bond(EDIV=0/RAND=0）必须跳过**——SC 测试每轮**重新**配对，若用旧 bond 抢先 LE_Start_Encryption,PTS 已不共享该密钥，所有帧 MIC 失败 → 链路 0x08 掉，第 2 轮配对前就死。`stack._auto_encrypt_on_reconnect` 加载 bond 后查 `bond.sc` 则 `return`。
- **根因（BV-04 等，最隐蔽）**：实装+上述全对后，`SM/CEN/SCOB/BV-04-C`(Handle AuthReq Flag RFU）仍 INDCSV——PTS 在**收到我们合法的 Public Key 后**（确认 conf 与公钥逐字节匹配）直接 0x13 断连、从不发自己的公钥。逐字节比对 BV-01（能过）发现**唯一差异是 PTS 自己回的 auth_req**(BV-01=0x0c,BV-04=0xc8 带 reserved 位）。但真正的触发点是 **IUT 的 Pairing Request 带了 MITM=1**(`01 00 01 0d`）——BV-04 的 Test Procedure step 1c **明确要求 IUT 请求 MITM=0**。我们的 `sm.py` precondition 全局 `gap_set_mitm_on`（为 PKE/NC 所设）泄漏进了 SCOB;**bluez 参考 IUT 从不调 `gap_set_mitm_on`**，故它发 MITM=0 能过。修法：`auto_pts_project/pybluehost_iut/wid/sm.py` 加 `hdl_wid_108` override——**仅 `/SCOB/` 用例**在 pair 前 `gap_set_mitm_off()`（其余用例 delegate 上游；legacy `/OOB/` 带 MITM=1 本就能过，不动）。**经验：SM 各子簇对 IUT auth_req 的 MITM/bonding 位有不同硬要求（JW 要 0、PKE/NC 要 MITM、OOB 要 MITM=0），别用一个全局值；以 bluez 「从不 set_mitm_on、靠 WID 按需开关」为准。**
- **调试方法（值得复用）**：判「conf 是否提交到空口公钥」时，必须拿**同一次运行**的 `(r, C, pubkey)` 三元组核对——iut log 每次跑会被覆盖、case log 的 r/c 是另一次运行的话必 MISMATCH（假象）。用 `_sc_f4(pub_x, pub_x, r, 0) == c` 全字节序组合试（本栈正确组合：BTP 原始值即 LE，asis)。
- **回归测试**：`tests/unit/ble/test_smp_oob_sc.py`(get_local 幂等且提交到己公钥、association model 需 remote/flag、initiator/responder 全流程对独立 spec 计算的对端校验、responder 拒错 conf);`tests/unit/test_stack_auto_encrypt.py::test_central_reconnect_skips_resume_for_sc_bond`。全套 2266 passed。
- **验证**：真机 SCOB **8/8 PASS**(2026-08-27):CEN BV-01/BI-01/BV-04/BI-04、PER BV-02/BV-03/BI-02/BI-03。PER 多轮用例（BV-02）有 peripheral flaky，重跑翻 PASS。

### Q: PTS SM/*/EKS/BI（Encryption Key Size 负例）+ SM/CEN/JW/BI-06（反射）INDCSV → A: ① 缺「协商密钥长 < 7 字节即 abort」② 缺 JW 反射检测 + BI-06 的 auth_req 硬要求 / 修复提交（本 session）

- **EKS/BI-01(CEN,initiator)/BI-02(PER,responder)**:PTS 在 Pairing Response/Request 里把 `max_key_size` 压到 6/5(< spec 下限 7 字节，Core Vol 3 Part H §2.3.4)，要求 IUT 中止并发 Pairing Failed **0x06**(Encryption Key Size)。我们原先不检查密钥长直接继续。修法：`_smp_state.py` 加 `_reject_undersized_key(ctx)`——`negotiated = min(local_max_key_size, peer_max_key_size)`，若 < 7 调 `_on_failed(reason=0x06)`；在 `_initiator_recv_pairing_response` 和 `_responder_recv_pairing_request` 捕获对端字段后各调一次。常量 `PAIRING_FAILED_REASON_ENCRYPTION_KEY_SIZE=0x06` 进 `smp.py`。⚠️ ctx stub 可能没 `local_max_key_size`,**用 `getattr(..., 16)` 兜底**（否则 4 个 legacy passkey 测试 AttributeError)。
- **SM/CEN/JW/BI-06-C（反射 + auth_req 双重根因）**:Test Procedure 让 PTS(responder)把 IUT 自己发的 confirm 原样回（`LP_CONFIRM_R == LP_CONFIRM_I`，反射攻击）,IUT(initiator)必须中止发 Pairing Failed **0x04**(Confirm Value Failed)。**两个独立问题**:① 缺反射检测——`_initiator_recv_peer_confirm` 加 `if peer_confirm == local_confirm: _on_failed(0x04); return`（不发 Random)。② **auth_req 硬要求（和 SCOB BV-04 同族）**:step 1c 要求 IUT Pairing Request **Bonding_Flags=00 且 MITM=0**；我们全局 mitm_on+bondable 发 `auth=0x0d`,PTS 在**收到我们 confirm 后立即 0x13 断连、从不发反射 confirm**——所以反射检测根本轮不到。修法：`wid/sm.py hdl_wid_108` 对 `JW/BI-06`（仅此，其他 JW 容忍 0x0d)`gap_set_bondable_off()+gap_set_mitm_off()` → 请求变 `auth=0x08`(SC-only)。修后空口确认：TX Req 0x08 → TX/RX confirm **逐字节相同（反射）** → TX `0504`。
- **关键认知**：SM 负例（BI）常**叠加**两层——①协议检测逻辑缺失（EKS 长度/JW 反射）②auth_req 位偏离 step 1 硬要求导致 PTS 在到达被测行为**之前**就断连。判 INDCSV 时先抓 `SMP TX/RX` 看流程走到哪一步：若 PTS 在我们某个 PDU 后立即 0x13、根本不发它该发的下一个 PDU，多半是 auth_req/格式偏离（参考 SCOB BV-04)，不是检测逻辑没触发。
- **回归测试**:`tests/unit/ble/test_smp_eks.py`(initiator/responder 拒 <7 发 0x06、接受 16 继续发公钥）;`tests/unit/ble/test_smp_jw_reflection.py`(反射 confirm 中止 0x04 不发 Random、正常 confirm 继续）。全套 310 BLE 通过。
- **验证**：真机 `SM/CEN/EKS/BI-01-C`、`SM/PER/EKS/BI-02-C`、`SM/CEN/JW/BI-06-C` PTS **PASS**(2026-08-27,JW/BI-06 第 2 次重跑过、首跑 flaky 连接）。

### Q: PTS SM/CEN/OOB 非对称用例（BV-03/09「只 IUT 有 OOB」、BI-01「双方 OOB 不同」）INDCSV——IUT 请求 oob flag=0 → PTS 在 step 1 就判负 → A: ① OOB TK 用法没门控对端 flag（单边有 OOB 也硬用）② 这些用例**根本不发 WID 147**,IUT 要从 precondition 自带 OOB TK / 修复提交（本 session）

- **现象**：`SM/CEN/OOB/BV-03-C`、`BV-09-C`、`BI-01-C` INDCSV。抓 `SMP TX`：IUT Pairing Request 是 `01 00 00 0d`——**oob_data_flag=0x00**，但三个用例的 Test Procedure step 1 都明确要求 IUT 发 **flag=0x01**（"Only IUT has OOB data" / "Both sides have OOB data")。PTS 一看 step 1 不符就中断（BV-03 日志里 IUT 其实正确显示了 passkey `429960`,PTS 却**从不发 WID 104 让它输入**——因为 step 1 已判负，后续流程不走了）。
- **根因 1(OOB TK 用法没门控对端 flag)**:Sub-Plan 3c 的 legacy OOB 分支是 `if oob_tk: ctx.tk = oob_tk`——**只要本地有 OOB TK 就用**，不管对端有没有。但 Core §2.3.5.3:OOB 方法**只在双方都有 OOB 数据时**采用；单边有（对端 flag=0）必须**回落到 IO-cap 模型**(BV-03 MITM=1→passkey、BV-09 MITM=0→Just Works)。修法：`_smp_state.py` 两个 OOB 分支（initiator/responder）都改成 `if oob_tk and ctx.peer_oob_data_flag:`。**注意我们仍在请求里发 flag=1**（那是 step 1 的硬要求），只是不用 OOB TK 算 confirm。
- **根因 2（这些用例不发 WID 147，IUT 要自带 OOB TK）**：抓 BV-03 的 case log,WID 序列只有 `100(connect)+108(pair)`,**没有 147**(OOB 数据供给）。即"只 IUT 有 OOB"的用例里 PTS 从不推 OOB 数据给 IUT——IUT 必须**自己预先持有** OOB TK 才能发 flag=1。bluez 参考的做法是设死 `TSPX_OOB_Data` pixit(`0000000000000000FE12036E5A889F4D`)。修法：`auto_pts_project/pybluehost_iut/sm.py` 对 `/OOB/` 用例（`/SCOB/` 不含 `/OOB/`，不误伤）在 precondition 追加 `TestFunc(btp.gap_oob_legacy_set_data, _LEGACY_OOB_DATA)`。双方都有 OOB 的用例（BV-01/02/10/11）会被 WID 147 用新鲜 random **覆盖**(`set_oob_legacy_data` 直接赋值、WID 147 先于 pair)，不受影响；BI-01/02 靠对端 OOB 数据与我们不同 → confirm mismatch → IUT 检出 abort。
- **关键认知**:① OOB 的「发 flag」和「用 TK」是两回事——flag 永远按「我有没有 OOB 数据」发（step 1 硬要求）,TK 只在「双方都有」时用；② auto-pts 的 WID 147 只对「双方都有 OOB」的用例（hdl_wid_147 的硬编码名单 BV-01/02/10/11）生成 random 并 `gap_oob_legacy_set_data`,**单边 OOB 用例不在名单里、也不发 WID 147**，所以单边用例的 OOB TK 只能走 precondition 预供给；③ 判「IUT 该不该发 flag=1」看 Test Procedure step 1,别看 WID 有没有推数据。
- **回归测试**:`tests/unit/ble/test_smp_oob_legacy.py` 新增 3 例（initiator 对端无 OOB+MITM→回落 passkey 不用 OOB TK；对端无 OOB+无 MITM→Just Works tk=0;responder 对端无 OOB→回落）。全套 310 BLE 通过。
- **验证**：真机 `SM/CEN/OOB/BV-03-C`、`BV-09-C`、`BI-01-C` PTS **PASS**(2026-08-27);回归 `SM/CEN/OOB/BV-01-C`、`SM/PER/OOB/BV-02-C` 仍 PASS。PER 单边用例 `SM/PER/OOB/BV-04-C`、`BV-10-C`、`BI-02-C` 同批重跑收割后全部 **PASS**(BI-02 第 3 次、BV-02 第 4 次——peripheral flaky，非协议问题）。**至此 legacy OOB 全簇（CEN+PER 8 例）全 PASS。**

### Q: PTS SM/PER/KDU/BI-02+BI-03（Key Rejected）INDCSV——IUT 分完密钥收到 Pairing Failed(0x0F) 却不报 Upper Tester → A: responder 收到对端 Pairing Failed 时没有 BTP PAIRING_FAILED 事件通路 / 修复提交（本 session）

- **现象**：`SM/PER/KDU/BI-02-C`(legacy)/`BI-03-C`(SC）配对成功、IUT 也按 mask 分完密钥（LTK/EDIV/IRK/IdAddr/CSRK),PTS 回 `Pairing Failed(0x0F Key Rejected)`,IUT 日志显示 `pairing failed reason=None`——**检测到了但没上报**。case log 里 PTS WID 173「Please confirm that IUT reports the Pairing Failed to the Upper Tester」→ auto-pts `wait_for_event(stack.gap.pairing_failed_rcvd.data)` **30s 超时** → INDCSV。
- **根因**：`PAIRING_FAILED_RX` 转移的 action 是 `_on_failed(send_failed=False)`——只把 `ctx.pairing_complete` 置异常。但 **responder 是被 PTS 发起配对的，没有 `_spawn_pair._run` 那个 await pair() 的 waiter**（那是 initiator/central 路径）,exception 被 `_consume_future_exception` 静默吞掉，**从不发 BTP PAIRING_FAILED 事件** → auto-pts 等不到。且 reason 也丢了（transition 没把 PDU 的 reason 传下去）。
- **修法（三段接线）**:① `SMPManager` 加 `_pairing_failed_cbs` + `on_pairing_failed(cb)` + `_emit_pairing_failed(handle, reason)`；两个 ctx 创建点（initiator/responder）设 `ctx._smp_manager = self`。② `_smp_state.py` 新增 `_recv_peer_pairing_failed(ctx, pdu)`——取 `pdu.reason`、调 `mgr._emit_pairing_failed`、再 `_on_failed(send_failed=False)`（不回显 Pairing Failed);`PAIRING_FAILED_RX` transition 改走它。③ `pts_tester.py` 订阅 `_smp.on_pairing_failed` → `gap.on_pairing_failed(addr=peer.to_hci(), addr_type, reason)`（复用 `_conn_peers` 的 LE 字节 + addr_type)。**只在对端主动 Pairing Failed(PAIRING_FAILED_RX）时发事件**——我们自己 abort 的负例（反射/EKS）走 initiator 的 `_spawn_pair` 已有通路，不重复发。
- **关键认知**：凡是「responder 侧发生、需要报给 auto-pts 的事件」，都得显式铺一条到 BTP service 的路——responder 没有 initiator 那种 `await pair()` 的天然上报点。这和「DEVICE_DISCONNECTED 丢 peer_address」(ff51a72)、「NEW_SETTINGS 没推」(3958e82）是同一家族：**IUT 状态变了但没推 event,auto-pts model 陈旧/等不到**。
- **回归测试**:`tests/unit/ble/test_smp_pairing_failed_rx.py`（对端 Pairing Failed→listener 拿到 handle/peer/reason 且不回显；无 listener 不抛）。全套 BLE+pts 通过。
- **验证**：真机 `SM/PER/KDU/BI-02-C`、`BI-03-C` PTS **PASS**(2026-08-27，各重跑 1-2 次过——peripheral flaky)。

### Q: PTS SM/CEN/PIS/BV-03（Peripheral Initiates Encryption）INDCSV——Security Request 触发的配对带上全局 MITM=1,PTS on-air 走 JW 而我们准备 passkey → A: initiator 的 MITM 位应 **mirror 对端 Security Request 的 MITM 位**，不被全局 `mitm_required` 强制 / 修复提交 4f9aa7c

- **现象**：`SM/CEN/PIS/BV-03-C` INDCSV。SecReq 触发的配对里 IUT 发 `auth=0x0d`(bonding+**MITM**+SC)——SM profile 的 `gap_set_mitm_on` 是全局的，而 PIS 走 Security Request 触发（**不经 WID 108**,MITM 从没人关）。
- **根因（已修的部分）**:`_initiator_send_pairing_request` 原先「config mitm_required 置 MITM」+「SecReq MITM 位 OR 进来」两条并列——只要 config 有 MITM 就恒置。但 SecReq 触发的配对，安全级别应由**对端 SecReq** 决定（Core §3.6.1):PIS/BV-03 的 SecReq 是 `0x08`(SC-only,**无 MITM**)→ 应 Just Works;GAP/SEC/AUT 的 SecReq 带 MITM → 应认证。**修法**:`start_initiator` 的 `peer_sec_req_auth_req` 默认改 `None`(None=本地 pair(),MITM 取 config；非 None=SecReq 触发，MITM **mirror** SecReq 的位，忽略 config)。真机确认 BV-02(SecReq=`0x0c` 带 MITM）仍走 passkey **PASS 无回归**,BV-03(SecReq=`0x08`）改发 `auth=0x09`。
- **⚠️ 推翻的猜想（勿再走）**：曾把 `_association_model` 的 SC 分支改成「去掉 both_mitm 门、纯 io_cap 驱动（DisplayOnly+KeyboardDisplay→passkey)」。真机证明 **PTS 在 auth 无 MITM 时 on-air 就走 JW**（收到我们 passkey confirm 后直接 Pairing Failed)——**原 both_mitm 门才匹配 PTS 行为，已回退**。即：SC 关联模型里 both_mitm 门是对的，别按「Table 2.8 io_cap 驱动」字面改。
- **加密使能阶段 reason=8 追查（已结案，环境假象）**：MITM 修对后 JW 能完整跑完双方 DHKey Check,挂在 `LE_Start_Encryption` 后 `Encryption_Change status=0x08/0x16`。逐层排查（f5/f6 数学上同一 CMAC 链、Eb 验证通过即证 LTK 一致；legacy 同命令加密正常；100ms 延迟无效；重启+重插+git bisect 到 SCOB 8/8 PASS 的 `1b58030` 仍复现）后**定论为 PTS workspace 状态泄漏**：跑过 SCOB 之后，PTS 的 SCJW/PIS 测试规程被残留的 SCOB responder 配置污染——Pairing Response 从干净的 `io=01/oob=0/auth=08` 变成 `io=04(KeyboardDisplay)/oob=1/auth=0c`(SCOB 配置),PTS.exe 不应答自己控制器的 LTK_Request → LL 加密握手超时 0x08。**重启后首个 case（PTS.exe 冷启动）最严重**（set_pixits 的 pixit 重置不完整）；暖环境 + 新 autoptsclient 推干净 pixit 后同代码一次通过。
- **判别方法（值得复用）**：SC 加密 `status=0x08` 时，先看 **PTS 的 Pairing Response 字节**——`oob=1`/`io=KeyboardDisplay`/带 MITM 出现在 JW/PIS 用例里 = workspace 泄漏，重跑即可，别查代码。判 SC 加密失败前确认当次 run 的 PTS response 是否符合该用例的预期配置。
- **回归测试**:`tests/unit/ble/test_smp_security_request.py::test_security_request_sc_only_overrides_config_mitm`(config mitm_on + SecReq=0x08 → 请求无 MITM；原 mitm 传播/无 MITM 测试不动）。全套 320 BLE 通过。
- **验证**：真机 `SM/CEN/PIS/BV-03-C` **PASS**(2026-08-28,首次即过）——请求 `auth=0x09`(mirror SecReq),SC JW 配对 + `Encryption_Change status=0x00`。`SM/CEN/PIS/BV-02-C` 无回归仍 PASS。

### Q: PTS SM/PER/KDU/BV-08 + PKE/BV-06 INDCSV——SC 配对 confirm/random 乱序后 PTS 发 0508 → A: responder 响应的 MITM 位被全局 `mitm_required` 强制置 1,应纯 mirror 对端请求 / 修复提交（本 session）

- **现象**：`SM/PER/KDU/BV-08-C`(SC,Table 4.6 IdKey-only):PTS 请求 `auth=0x09`(bonding+SC,**无 MITM**),我们的响应却带 `auth=0x0d`(全局 `gap_set_mitm_on` 泄漏）→ PTS 按「双方 MITM」选 passkey entry(收到我们 JW 的 Cb 后发 Ca),我们按 JW 走 → 模型分裂 → confirm/random 乱序 → PTS `0508` abort。`SM/PER/PKE/BV-06-C` 同根因。
- **根因**:`_responder_recv_pairing_request` 的 MITM 位是 `if (peer & 0x04) or config.mitm_required`——config 强制把本应 mirror 的位打开。**zephyr/bluez 参考 IUT 从不 set_mitm_on**;responder 是被配对方,对端请求没要 MITM 就不该置。
- **修法**:去掉 config 回退,responder 响应 MITM **严格 mirror** 对端请求（`peer_auth & 0x04` 才置）。**initiator 的 REQUEST 仍走 config**(CEN/PKE/NC 用例需要我们主动带 MITM)——方向不对称,别统一改。
- **关键认知**:SM 负例/行为用例里 PTS 请求的 auth_req 位就是「这个配对该是什么模型」的契约;响应偏离(尤其多出 MITM)会让 PTS 选另一个关联模型,空口 PDU 序列立即分裂。排查此类「confirm/random 乱序 + PTS abort」先逐字节比对双方 feature exchange 的 auth_req。
- **回归测试**:`tests/unit/ble/test_smp_responder_mitm_mirror.py`(config mitm_on + 请求无 MITM → 响应无 MITM;请求带 MITM → 响应带）。全套 325 BLE 通过。
- **验证**：真机 `SM/PER/KDU/BV-08-C`(响应 `02000009`、密钥只发 IRK+Identity Address)、`SM/PER/PKE/BV-06-C` 均 **PASS**(2026-08-29,KDU/BV-08 首次即过）。

### Q: PTS SM/PER/EKS/BV-02（7 字节 key)配对完成即断链(0x3D) → A: STK/分发 LTK 没按协商 key size 缩短(§2.3.4 高位字节置零),LL MIC 失败 / 修复提交（本 session）

- **现象**：PTS 请求 `max_key_size=0x07`,confirm/random 全过,**STK 加密一启动链路就掉**。
- **根因**:Core Vol 3 Part H §2.3.4:协商 key size < 16 时,STK/LTK **必须只保留最低有效 size 字节、其余高位字节置零**。我们 s1 派生完 STK、phase-3 生成 LTK 都是原始 128-bit 直接用/发 → PTS 用缩减 key、我们用全量 key → LL 加密 MIC 不匹配 → 链路掉。zephyr 对应实现是 `memset(stk + enc_key_size, 0, 16 - enc_key_size)`。
- **修法**:`_negotiated_key_size(ctx)`(= min 双方 max,复用 EKS/BI 的检查)+ `_reduce_key(key, size)`(保留 `key[:size]` + 高位补零);应用于两处 STK 派生(initiator/responder)和 phase-3 的 LTK 生成(同时 bond 存的 local_ltk 天然一致）。SC 不受影响（SC 禁止 <16 密钥）。
- **回归测试**:`tests/unit/ble/test_smp_eks.py::test_stk_reduced_to_negotiated_key_size` / `test_distributed_ltk_reduced_to_negotiated_key_size`。全套 327 BLE 通过。
- **验证**：真机 `SM/PER/EKS/BV-02-C` **PASS**(2026-08-29,首次即过）——空口 LTK 精确 `7字节+9零`,重连重加密成功。

### Q: GATT/SR/GAS/BV-02（Database Hash）PTS 算的 hash 与我们不一致判 FAIL——本地已证明自洽 → A: 已排除 IUT 侧全部可验证假设；PTS 重构规则黑盒待 btsnoop 级取证 / 2026-08-30 取证记录

- **已验证为正确的**：① 算法对 Core 5.4 附录 B 官方向量逐字节一致（`F1CA...A990`）；② 真机 serve 的 hash 与本地重建 db（从 iutctl 日志重放全部 BTP 建库命令）计算完全一致；③ **完整模拟 PTS 发现视图**（Read By Group 0x2800/0x2801 + Read By Type 0x2803/0x2900 + Find Information 的全部响应逐轮重构属性表）计算出的 hash 也一致——发现层暴露的内容与哈希覆盖的内容完全对应。
- **顺带修掉的真 bug**：`find_by_group_type` 的组 end 只找**同类型**下一个服务声明 → 独苗 secondary 服务报成跨全库（0x0001-0x003D）,与后续 primary 范围重叠、PTS 逐服务发现特征会重复统计。修复后 `0x0001-0x001C`（26b2915）——但修复后真机 BV-02 仍 FAIL,故这不是（唯一）根因。
- **排查脚本的坑（勿再踩）**：① Read By Group/Read By Type Response 的 `length` 字段**已含 handle**（esz = length,别再 +2/+4 双计）；② `ATT_Find_Information_Response` 的数据字段名是 `information_data`（不是 `attribute_data_list`）;③ iutctl 日志的多行 `raw data` 要合并续行（128-bit UUID 的 ADD_CHARACTERISTIC body 跨行）。
- **下一步**（需要 btsnoop/PTS dongle 空口日志）：抓 PTS 实际读到的 hash 字节 + PTS 内部计算的期望值比对；或对照 zephyr 同 db 的 hash 值。

### Q: GATT/SR key-size 负例簇（GAR/BI-05、BI-17、BI-22、GAW/BI-06）SC+短key 配对完成后即断链(0x3D) → A: `ltk_sc` 也要按协商 key size 缩短——PTS 的 GATT preamble 用 **SC + max_key_size=7** 配对 / 修复提交（本 session）

- **现象**：GATT/SR 的 Insufficient Encryption Key Size 负例(TS §4.2.4 preamble = EKS 式短 key 加密)全部在配对加密一步断链(0x3D)。抓 `SMP TX/RX`:PTS 请求 `01040009070707`——**auth=0x09(SC!) + max_key_size=0x07**。公钥交换、confirm/random、双方 DHKey Check 全过,`Encryption_Change` 前链路掉。
- **根因**:PTS 在 **SC 模式下也用协商 key size 缩减 LTK** 来造「加密 key 不足」的链路(尽管 Core spec 说 SC 恒 16 字节)。我们的 `ltk_sc` 是 f5 原始输出(16 字节),PTS 用 7 字节缩减版 → LL session key 不一致 → MIC 失败 → 断链。与 legacy STK 的缩减(§2.3.4)同一法则,只是 SC 路径漏了。
- **修法**:四处 `ctx.ltk_sc = ltk`(initiator/responder × 公钥后/DHKey 后)统一改 `ctx.ltk_sc = _reduce_key(ltk, _negotiated_key_size(ctx))`——对端正常 offer 16 时是 no-op,零回归。
- **验证**:真机 `GATT/SR/GAR/BI-05-C`、`BI-17-C`、`GAW/BI-06-C` 全 **PASS**(2026-08-29,改后首跑);`BI-22` 的修复同样被空口验证(SC+7字节key 配对、`Encryption_Change status=0x00`、密钥分发、ATT 读流程全通过)但该例自身被 PTS dongle RF flaky 卡 verdict(见下条)。
- **回归测试**:`tests/unit/ble/test_smp_eks.py::test_sc_ltk_reduced_to_negotiated_key_size`。全套 328 BLE 通过。

### Q: BE200 当 PTS dongle 的两类死亡模式 + 无 admin 时的恢复决策 / 2026-08-29 实测

- **死亡模式 1(PTS.exe COM 孤儿)**:autoptsserver 因 COM 空闲故障死掉后,它经 COM 拉起的 **PTS.exe 以 svchost 为父进程存活**,继续独占 dongle 的 WinUSB 句柄 → 后续 server 重启全部卡在 dongle init(`GetPTSBluetoothAddress` 报 `0x849C0043`)。**诊断分层**:`Dispatch('ProfileTuningSuite_6.PTSControlServer')` 1.4s OK + `GetPTSVersion()` OK + `GetPTSBluetoothAddress()` 挂/报错 = dongle 层;而非 COM 层。**恢复 = 杀 PTS.exe**(句柄即释放),不需要重启系统。
- **死亡模式 2(BE200 固件/设备态锁死)**:libusb 侧 `HCI Reset` 仍 0x00(命令能发、地址能读),但 PTS.exe 打不开它。此时另一颗 BE200 若 libusb 健康,可直接换它当 PTS dongle——server 用它的实例路径启动(`USB_INTEL:Free:6&2DE8F518&0&2` = ports=(5,2) 那颗)。**换 dongle 后 IXIT/TSPX_bd_addr_iut 不用改**(那是 IUT 的地址);PTS 侧地址从 controller info 动态读。
- **BE200#2(5C67830704EE) 当 PTS dongle 的连接可靠性差**:IUT 广播被连方向(PTS 当 central)成功率低(~25%),常 0x3E 秒断或根本不发 CONNECT_IND;IUT 主动连(central)方向未测。多阶段 SR 用例(要 pairing+ATT 全程活着)在其上很难收 verdict——**修复已空口验证的用例可先记 flaky,等 BE200#1 恢复再收割**。
- **教训**:①「重启电脑」不是这类故障的必需解——先分层(COM→PTS.exe→dongle→RF),多数层有更便宜的恢复;② `pts_retry_cases.sh` 的 verdict 匹配**曾漏 `UNKNOWN VERDICT: NONE`**(PTS 对 0x3E 秒断的判词),这类 attempt 显示 `<no verdict>` 且不重试,只能手动多次跑——**已修(2026-09-16)**,现在是重试集里的一员。凡给 `wait_verdict`/`pts_harvest.sh` 加 token 时,两处匹配集要同步,漏一个就静默降级成「不重试」。

### Q: GATT/CL 一波流修复（BV-04 长读、GAW/BI-09 延迟错误、CL key-size 族）/ 修复提交 bfd08af + adeef6e + 915af0f

- **BV-04(BTP READ 只读一次)**:zephyr `bt_gatt_read` 内部透明补完 Read Blob 链;我们 op 0x0e... 实为 op 0x11 只发单次 Read,MTU-1 截断后 PTS 等不到剩余 blob 序列 → INDCSV。修法:op 0x11 改调 `read_long_characteristic`(read+blob 循环;值装得下时不发 blob,零回归)。
- **GAW/BI-09(execute_write 吞错)**:PTS 接受全部 Prepare Write、把 Invalid Offset 拒绝**延迟到 Execute Write 的 Error Response**;`ATTBearer.execute_write` 丢弃响应 → 长写看起来成功 → BTP 回 att=0x00 → WID 66 `verify_att_error` 空 verify_values → INDCSV。修法:execute_write 像 read/write 一样检查 `ATT_Error_Response` 并 raise。**同坑普查**:read/write/read_blob/prepare_write 都查了,唯 execute_write 漏——给 bearer 加方法时逐一核对响应处理。
- **CL key-size 族(BI-05/11/17/22)**:`ltk_sc` 缩减(915af0f)直接解锁,4 例首跑全 PASS。
- **验证**:BV-04、GAW/BI-09、GAW/BI-06、GAW/BI-13、GAR/BI-13、CL/GAR/BI-09 全 PASS;GATT 101/144(70.1%)。

### Q: L2CAP/ECFC 安全 responder 三例(BV-11/13/15)5 分钟 PTS TIMEOUT → A: ECFC 变体没挂安全 LISTEN 前置(只有 LE/CFC 变体挂了) / 修复提交 5429485;发起侧 Reconfigure(0x19)实装待硬件验证

- **根因**:安全前置(`l2cap_le_listen(psm, mtu, response=insufficient_authentication)`)只映射到 `L2CAP/LE/CFC/BV-11/13/15`,**ECFC 双胞胎用默认 success listen** → 我们接受 PTS 的 0x17 而非拒绝 → PTS 等 0x0005 拒绝码等到超时。修法:补 `custom` 映射(BTP LISTEN 的 response 字段即安全等级:1=authn/2=authz/3=keysize/4=enc,manager 的 `_LE_SECURITY_CHECK` 映射到 0x0005/6/7/8 拒绝码)。
- **遗留(硬件 blocked)**:修复后 9 次尝试里 8 次根本没连上(BE200#2 的 PTS-central 连接率退化到 ~0),唯一一次连接的 attempt 仍是 FAIL——PTS 发了 0x17 且我们疑似没回 0x18(需 IUT trace 定位,`_le_security_met` 链路待真机复验)。**BE200#1 恢复后优先重跑此三例。**
- **发起侧 Reconfigure 实装**:`L2CAPManager.reconfigure_le_coc_channels(handle, mtu, channels)`(发 0x19 列对端 DCID、等 0x1A、成功更新 `_rx_mtu/_mtu`)+ dispatch `_pending_le_reconfigure` + BTP `RECONFIGURE(0x07)`(body: addr_type+addr+mtu+count+chan_ids,auto-pts WID 103 `l2cap_reconfigure` 驱动)。单测 2 例(成功应用/拒绝抛错)。**BV-22/23/24 硬件验证被 dongle blocked**(BV-22 的 ACL 也是 PTS 发起——WID 56 connectable,别按"Initiator=IUT连ACL"想当然)。

### Q: PTS L2CAP/ECFC 多例 BTP ERROR（~14s 快挂），IUT 发了合法 0x17 但 5s 超时 → A: PTS 在**拒绝**的 ECFC 响应里也补零 DCID，严格解码器抛错被吞 → connect future 永不解析 / 修复提交 009fe17

- **现象**：`L2CAP/ECFC/BV-10-C` 等，IUT 发出格式正确的 `0x17`(Enhanced CB Conn Req,2 个 SCID),PTS 5s 内无响应 → `_do_connect` 超时 → BTP_STATUS_FAILED → auto-pts `BTPError: Error opcode in response!`。
- **根因**：PTS **确实**回了 `0x18`(ECFC Conn Rsp)，但字节是 `MTU+MPS+credits+result(=0x0005 Insufficient Authentication)+**2 个零 DCID**`——按 Core spec「refused 响应不带 DCID」，但 PTS 为了对齐请求的通道数**补了零 DCID**。我们的 `ECFCConnectionResponse.decode` 严格校验「refused 且有 DCID → 抛 ValueError」，而 `_on_le_signaling` 的 `except ValueError` 把它吞掉（只 log「decode failed」)→ pending connect future **永远不被 set** → `connect_le_coc_channels` 干等 5s 超时。
- **修法**：解码器对 refused 响应**容忍并丢弃**补齐的 DCID（只保留 result 码），不再抛错。于是 future 解析 → `connect_le_coc_channels` 抛 `LECoCConnectError(result=5)` → `_do_connect` 走「优雅拒绝」路径回 SUCCESS+num=0 → auto-pts 的安全拒绝 WID 通过。
- **经验**：① 「strict decode 抛错 + dispatch 吞异常」是比直接 crash 更隐蔽的坑——表面是「对端不响应」，实际是「我们解码拒了对端的响应」。对 PTS 这类会「补零对齐」的对端，解码要 liberal。② ECFC 的 BTP CONNECT 触发 enhanced(0x17）目前按 `num>1` 判（auto-pts `l2cap_conn` 默认 `num_channels=2`)，也能跑；但严格说触发条件应是 options 字节的 `L2CAP_CONNECT_OPT_ECFC(0x01)` 位，遇到 num=1 但 ecfc=1 的用例要改这里。
- **回归测试**：`tests/unit/l2cap/test_le_ecfc_signaling.py::test_ecfc_response_decode_tolerates_refused_with_padding_dcids`。真机 `L2CAP/ECFC/BV-10-C` PASS（原 BTP ERROR，2026-08-26)。
- **⚠️ 基础设施坑**：autoptsserver 在长 idle 用例（~900s time_guard）后 PTS COM 丢 `GetSelectedDevice` → `AttributeError: NoneType` 中断整批；且**勿并发跑两个 autoptsclient**（共享 dongle 必崩）。`pts_run_batch.sh` 是 nohup 后台 spawn，串行跑要靠轮询进程数等待，不能 `A && B`(会并发）。

### Q: PTS L2CAP/ECFC/BV-80（K-frame SDU = MPS）稳定 INDCSV——IUT 发 0x17、PTS 回 0x18 接受，250ms 后 PTS 主动断 ACL / 2026-09-13 取证（**未结案**）

- **现象**:`L2CAP/ECFC/BV-80-C` 三次重跑全 INDCSV（不是 flaky）。auto-pts 侧日志显示**两个信道都 connected 了**（`l2cap_connected_ev id:0/id:1`），但 **~95ms 后双双 disconnected**，随后 `wait_for_connection` 5s 超时 → WID 255 返回 OK → INDCSV。
- **IUT 侧空口取证**（加了 LE signaling RX/TX 日志后）:
  ```
  L2CAP connection handle=0x0E01 link_type=LE opened
  LE signaling TX handle=0x0E01 code=0x17 id=1 len=16      ← IUT 发 ECFC Connection Request（2 个 SCID）
  LE signaling RX handle=0x0E01 code=0x18 id=1 len=16      ← PTS 回 ECFC Connection Response
  L2CAP connection handle=0x0E01 closed (reason=0x13)      ← 250ms 后 ACL 被断
  ```
- **已排除**:① **不是 PTS 拒绝**——`connect_le_coc_channels` 只在 `resp.result != 0` 或 `len(dcids) != num` 时抛错；我们不但没抛，还发了 2 个 Connected 事件，且 auto-pts 解出的 `our_mtu/our_mps` 合理（64/64，= min(我们 120/247, PTS 的)）→ 响应是**成功**、DCID 数也对。② **不是我们的 framing violation**（`_signal_violation` 会打 WARNING，日志里没有），而且断链发生在 PTS 发任何 K-frame **之前**。③ **不是连接 flakiness**（3/3 复现）。
- **待查**:断开方到底是 PTS 还是我们自己。`reason=0x13` 在 HCI 里是**双向**都能出现（本地发起 HCI_Disconnect 时默认 reason 也是 0x13），所以不能只看 reason 判断方向。
- **✅ 已定（加了调用点日志后）**:**不是我们断的**。给 `BLEConnectionManager.disconnect` 加了 `caller=` 日志（打印调用点文件:行号）后重跑，出现 `L2CAP connection ... closed (reason=0x13)` 时**没有任何** `BLEConnectionManager.disconnect` 日志，且全栈只有这一个 BLE ACL 断开入口（另一个是 `classic/gap.py`）→ **是 PTS 主动断的**。同一次运行里 PTS 甚至连 0x17 都不发就断了（连接存活 378ms）。
- **结论/影响**:`ECFC/BV-80` 的现象与同组大量用例一致——**PTS 侧连上后很快自行放弃**，属 LT 行为，不是 IUT 协议错。**继续查它需要 PTS 侧视角**（PTS 的 case log/btsnoop 里 LT 为什么放弃），从 IUT 侧已无更多信息可挖；建议先把它归入「PTS/LT 侧行为」一类，改用**重跑收割**（同组其它例已见重跑翻正）而不是继续从协议栈侧找 bug。
- **顺带**:该组其它用例（ECFC/BV-20/22/26、COS/ECFC/BV-01/03/04、LE/CFC/BV-25/32、TIM/BV-03）大量 INDCSV，**多例已确认是 LT 根本没连上来**（IUT 只广播、无 `L2CAP connection ... opened`）→ 属 peripheral 连接 flakiness，重跑可翻。ECFC 组本轮**翻正**：`L2CAP/COS/CFC/BV-04-C`、`L2CAP/COS/ECFC/BV-02-C` → L2CAP 85/100。

### Q: PTS L2CAP/ECFC/BI-03..07 + BV-23/25 全 INDCSV（~215s time_guard）→ A: 没实装 ECFC Credit-Based Reconfigure(0x19/0x1A) responder + 结果码基线判错 / 修复提交 09693f1

- **现象**：ECFC 重配置用例（BI-03..07、BV-23/25）connect 成功后 PTS 发 `0x19`(Reconfigure Req)，IUT 不应答（旧代码根本没 dispatch 0x19）→ PTS 干等 `TSPX_time_guard` ~215s 判 INDCSV。
- **根因（两层）**：① 缺 0x19/0x1A 编解码 + manager dispatch（初版 0x1A 结果码常返回 `0x000C`，越出 spec 保留域，PTS 报「Field named Result is incorrect」）。② **结果码基线判错**——这是反复迭代 3 次才对的点。正确基线（对 bluez issue #1865 逐例核对）：**MTU 基线 = 协商后信道 MTU（`ch._mtu` = PTS 在 ENH_REQ 里 advertise 的值，BI-03=65/BI-04=264/BI-07=84）；MPS 基线 = IUT 自己 advertise 的接收 MPS（=247），且必须是不可变的 `_reconfig_base_mps`**。
- **结果码矩阵**（Core 5.2 Vol 3 Part A §4.25）：`0x0003`=无效 DCID；`0x0004`=MTU/MPS **增加**；`0x0001`=**任何**对协商 MTU 的缩减（不分通道数，BI-03 单通道 MTU 65→64 也是 0x0001）；`0x0002`=MPS 缩减覆盖 **>1 通道**（BI-04/BI-07）；`0x0000`=合法单通道 MPS 缩减（BV-23/25，应用到 `_rx_mps`）。
- **最隐蔽的坑**：判「是否缩减」的 MPS 基线**不能用会被成功路径改写的 `_rx_mps`**。BI-07 流：id=2(mps=68,单通道)→0x0000 成功并把 `_rx_mps` 改成 68；接着 id=3(mps=71,双通道）——若拿被改写的 68 当基线，71>68 误判「增加」→错回 0x0004；拿不可变的 advertise 值 247 当基线，71<247 仍是缩减→正确 0x0002。故在 `LECoCChannel.__init__` 存 `_reconfig_base_mps = _rx_mps`（建信道时的 advertise 值，之后不随 enforcement 变）。
- **经验**：① ECFC reconfigure 的 MTU/MPS 基线**方向不对称**——MTU 比对端值（`ch._mtu`）、MPS 比己方 advertise 值（247），别统一用 `_rx_*` 或统一用 `_mtu/_mps`；② 「成功路径就地改状态」会污染后续判断的基线，凡是要和历史值比较的都存一份不可变快照；③ 硬件 flaky 会让已 PASS 的用例偶发 INDCSV(peripheral 0x3E），判 regression 前先重跑确认——本批 BI-05/BI-06 两次运行结果互换，实属 dongle 抽风。
- **回归测试**：`tests/unit/l2cap/test_le_ecfc_manager.py::test_reconfigure_*`（6 例锁定 0x0000/0x0001/0x0002/0x0003/0x0004 + 基线不可变）。真机 BI-02/03/04/06/07 + BV-21/25/27/29 PASS（原 INDCSV/FAIL，2026-08-26）。

### Q: PTS GAP/SEC/SEM/BI-09/20/21/22/23（Invalid Encryption Key Size，Peripheral）稳定 FAIL → A: IUT 缺「安全级别」配置通道；用已有但**是空 stub** 的 BTP `SET_MIN_ENC_KEY_SIZE`(0x20) 驱动 SMP key-size 下限，GAP IUT 模块为这 5 例设成 16 / 修复提交 8ba2855（**5/5 PASS**）

- **TS 原文**（GAP.TS §4.7.5，Figure 4.36）:LT(Central) 用 **SC=1 + Maximum Encryption Key Size = KS** 发 Pairing Request，KS 遍历 **[7,15]**，IUT(Peripheral) 每一轮都必须回 **Pairing Failed reason=0x06**。Pass verdict：「fails pairing for **any key size value less than 16** while in the specified security mode and level」——即 IUT 被配成 **security mode 1 level 2/3/4**（level 越高允许的 key size 下限越高，3/4 实际就是必须 16）。
- **找通道的过程（值得复用）**:去翻**哪个参考 IUT 注册了这些用例**——`grep SEM/BI-20 */*/gap.py` 发现 **zephyr 不注册、mynewt 注册**，而 mynewt 的前置只有 `btp.gap_set_io_capability(IOCap.display_only)`。也就是说这层「安全级别」是 IUT **带外配置**的，auto-pts 不提供 BTP/PIXIT 入口。**我们自己的 IUT 模块就是那个带外配置点**。
- **修法（配置驱动，不能一刀切）**:① `SecurityConfig.min_encryption_key_size`（默认 7 = Core 下限）;② `_reject_undersized_key` 的阈值 = `max(7, 配置值)`;③ BTP GAP **`SET_MIN_ENC_KEY_SIZE`(0x20) 原本是个只存不用的空 stub**，现在真正写进 `config.security.min_encryption_key_size`;④ `pybluehost_iut/gap.py` 的 per-case `custom` 里给这 5 个用例加 `TestFunc(btp.gap_set_min_enc_key_size, 16)`（同文件已有 `sc_only_extra` 的同类先例）。
- **⚠️ 不能改成「SC 一律要求 16」**:先试过无条件「SC 协商时 <16 即失败」，**当场打破 `tests/unit/ble/test_smp_eks.py::test_sc_ltk_reduced_to_negotiated_key_size`** —— GATT/SR 的 key-size preamble 恰恰用 **SC + max_key_size=7** 配对并且**必须成功**（然后按协商长度缩减 LTK，见另一条）。两个簇需求相反，**只有配置项能同时满足**。所以默认必须留 7。
- **真机**:`GAP/SEC/SEM/BI-09-C`/`BI-20-C`/`BI-21-C`/`BI-22-C`/`BI-23-C` **全 PASS**(2026-09-14;BI-20 首次是 FATAL ERROR/FAIL 的抖动，重跑即过）→ GAP 90→**95/144**，总 **375/479 (78.3%)**。
- **回归测试**:`tests/unit/ble/test_smp_eks.py::test_configured_min_key_size_16_rejects_sc_short_keys`（7/12/15 全回 0x06）与 `test_default_min_key_size_still_accepts_seven`（默认仍接受 7，锁死「不能一刀切」这条）。

### Q: PTS GAP/SEC/SEM 多轮用例（BV-56 等）~364s PTS TIMEOUT，第二轮 PTS 不重连 → A: ① 没发 BTP_GAP_EV_NEW_SETTINGS 致 auto-pts 模型 ADVERTISING 位不清、重广播被短路 ② 缺 bonded-reconnect Security Request / 修复提交 3958e82 + dcd34b7 + 7e7f212

- **现象**：`GAP/SEC/SEM/BV-56-C` 等「advertise→connect→pair→write→disconnect→**再 advertise→再 connect**」多轮用例，第一轮全 OK，第二轮 PTS 始终不重连 → 干等 ~364s PTS TIMEOUT。btsnoop 只有 1 次 `Adv_Enable`、1 次连接。
- **根因 1（NEW_SETTINGS，主因）**：auto-pts 的 `btp.gap_start_advertising()` **先查本地 GAP model 的 ADVERTISING 位，已置位就直接 return 不发 BTP 命令**。该 model 靠 ①BTP 命令响应里的 current_settings、②IUT 主动推的 `BTP_GAP_EV_NEW_SETTINGS`(ev 0x80) 两个途径同步。peripheral 连接建立时控制器自动停广播，但我们从不清 ADVERTISING 位也不推 NEW_SETTINGS → 第一轮连上后 auto-pts 模型还停在「advertising」→ 第二轮 `gap_start_advertising` 短路（BTP trace 里第二轮 WID 91 后**根本没发 START_ADVERTISING**)→ PTS 等不到广播无法重连。bluez 靠监听 adapter 的 Advertising D-Bus property 变化推 NEW_SETTINGS 避开。
- **修法 1**：`on_connection_state_change` 在 `connected=True` 且 ADVERTISING 位置位时，清位并 `_emit_event(OP_GAP_EVENT_NEW_SETTINGS, current_settings)`。第二轮重广播恢复。
- **根因 2（Security Request）**：第二轮是 bonded 重连，central(PTS) 等 **peripheral 发 SMP Security Request** 才重加密（bluez 自动发）。原 auto-encrypt 只做了 Central 角色（注释「Peripheral waits for LTK_Request」），peripheral 从不触发 → 第二轮不加密。加 `_auto_security_request_on_reconnect`：bonded peripheral 重连（有 LTK）时发 SMP Security Request 让 central 重加密。
- **根因 3（auth_req 过强）**：Security Request 的 auth_req 别用 blanket `auth_requirements=0x0D`（含 MITM)。Level 2(Just Works) bond 满足不了 MITM 位（要不重新配对）,central 直接忽略该请求 → 不加密。改为按 flag 拼：bonding 恒置 + SC(enable_secure_connections 时） + MITM(**仅** mitm_required 时） = 默认 0x09。
- **关键认知**：① auto-pts 的「幂等短路」（`gap_set_connectable`/`gap_start_advertising` 查 model 已置位就 skip）意味着 **IUT 必须主动推 NEW_SETTINGS 报状态变化**，否则 model 与现实漂移、后续命令被静默跳过——这类「IUT 没推 event 导致 auto-pts model 陈旧」和 DEVICE_DISCONNECTED 丢 peer_address（见 ff51a72）是同一家族的坑；② 判「central 为何不理 Security Request」先看 auth_req 是否要了 bond 给不了的级别。
- **回归测试**：`tests/unit/pts/btp/test_gap_events.py::test_new_settings_pushed_when_connection_stops_advertising`(+ 未广播不推）；`tests/unit/test_stack_auto_encrypt.py::test_peripheral_bonded_reconnect_sends_security_request`（锁 MITM 不置位）。真机 BV-56 从 PTS TIMEOUT(364s)→流程跑完（57s),SEC/AUT/BV-23 inconc→PASS(2026-08-26)。
- **遗留**：SEC/SEM 仍有 ~18 FAIL + SEC/AUT 若干——多为 per-case security-level 细节（哪一轮该加密到什么级别、SecReq 时机）,**需要 GAP.TS 文本逐例对 purpose**（本地无 TS)。BV-56 修通流程后仍 FAIL，根因在「某轮加密级别不符预期」，待 TS 到位再攻。

### Q: PTS peripheral 用例（IUT 被连）verdict 不稳定——同一用例这次 INDCSV 下次 PASS，批次里全挂、单跑能过 → A: **dongle 间 RF/链路层连接 flaky**，非协议 bug；用 `scripts/pts_retry_cases.sh` 单例重跑收割 PASS / 2026-08-26 实测

- **现象**：SM/PER/{KDU,OOB,JW,PIS,SCJW} 等 peripheral 用例（PTS 当 central 连 IUT)，批次连跑时**整批 INDCSV**，但同一用例**单独跑能 PASS**（实证：`SM/PER/KDU/BV-01-C` 单跑 PASS(23s)，进批次就 INDCSV；`SM/CEN/KDU/BV-10-C` 重跑一次 INDCSV→PASS)。
- **实测定性**：抓失败例的 btsnoop——IUT 完整走完 init + `LE_Set_Adv_Enable(enable=1, status=0)`，广播确认上了空口，但 **PTS(central) 从不发 CONNECT_IND**（无 ConnComplete、无 connect 尝试）。adv interval 已是 100ms（够快，非间隔问题）。**即：广播正常、对端没来连，是两颗 dongle(PTS=BE200 ↔ IUT=AX201）之间的 RF/链路层可靠性问题，软件改不动。** 叠加已知的「server 重启后首个 case 冷启动 INCONC，重跑即过」。
- **后果**：peripheral 多轮用例（OOB 4 轮、SEC/SEM 多轮）把单轮 ~50-70% 连接成功率放大成 case 级高 INDCSV 率；单连接用例也随机挂。**判这类 verdict 前必须先重跑确认是 flaky 还是真 bug**——真 bug（如 EKS/BI、OOB/BI 的负例）重跑 N 次仍 INDCSV,flaky 的重跑会翻 PASS。
- **工具**:`scripts/pts_retry_cases.sh <max_attempts> <case-id...>`——每个用例**独立 autoptsclient session**（单例跑比批次跑可靠）重跑到 PASS 或达上限，PASS 短路、PTS TIMEOUT/FATAL 不重试。跑完 `uv run python scripts/pts_import_verdicts.py /tmp/auto-pts/logs --date <date>` 录入。⚠️ 脚本 verdict 匹配要含 **INDCSV**(PTS 日志写的是 INDCSV 不是 INCONC，初版漏了导致每例干等 360s)。
- **经验**:① 收割 flaky PASS 用单例重跑，别在批次里反复跑（批次首例叠加冷启动更易挂）;② 要真正提通过率，得换 peripheral 更可靠的 IUT dongle 或改善 RF（距离/干扰），不是协议栈能管的。

### Q: PTS GATT/SR/GAR/BV-11+BV-12（EATT 多 bearer 读簇）确定性 FAIL → 修复后 PTS TIMEOUT → A: ① 用例 preamble 假设既有 bond，需 `PYBLUEHOST_PTS_BOND_STORE` 持久化 LTK ② ATT mux 漏 0x0E/0x20，Read Multiple (Variable) 被静默丢弃 ③ bond-resume 加密从不发 SEC_LEVEL_CHANGED，auto-pts 的 sec_level 模型停在 0 / 修复提交（本 session，2026-09-18 双双 PASS）

- **根因 0（确定性 FAIL，零代码修复）**：这两例的 PTS 脚本 preamble **假设 IUT↔LT 已有 bond**——不配对、直接发 LL_ENC_REQUEST（rand/ediv=0）。pts-tester 每用例新 spawn，默认 `InMemoryBondStorage` 是空 slate → `0x201B` LTK_Negative_Reply → PTS 在未加密链路上发 EATT ECFC（SPSM 0x0027，required_sec=4）被拒 0x0008 → 断连。**修法：在跑这批用例的 shell 里 `export PYBLUEHOST_PTS_BOND_STORE=<path>`（`pts_tester.py::_make_bond_storage` 切 JsonBondStorage），并先跑一个 preamble 现配对的用例（如 `GATT/SR/GAW/BV-12-C`）把 LTK 写盘、与 PTS 的 bond DB 同步。**⚠️ 默认 in-memory 是有意设计（用例间 clean slate），别全局开；⚠️ PTS.exe/autoptsserver 重启后 PTS 侧 bond 可能丢，需重跑配对用例再收割。
- **Bug A（bond 修好后暴露，PTS TIMEOUT）**：EATT bearer 上 PTS 发 **Read Multiple Variable Length(0x20)**，IUT 从不应答 → PTS 干等 300s time_guard。根因：ATT mux 的 `ATT_SERVER_REQUEST_OPCODES`（`l2cap/channel.py`）**缺 0x0E/0x20**——mux 把它们路由到不存在的 client handler 静默丢弃；GATT server 的 `_handle_read_multiple_variable` 其实早已实装（a309104），从未被 mux 放行（单测都直调 `handle_request` 绕过 mux，所以测不出）。**经验：mux/分发表新增 handler 时要同步查路由表；「handler 存在却像没实装」先查分派层。**
- **Bug B（BV-12 的 FATAL）**：wid 400（EATT listen）里 auto-pts 等 `conn.sec_level >= min_level` 恒 30s 超时——bond-resume 加密**不经配对**，而 SEC_LEVEL_CHANGED(0x89) 原来只在配对完成时发，auto-pts model 的 sec_level 停在 0。BV-11 超时后仍 OK 继续（能过），BV-12 被 PTS 直接 abort（FATAL）。修法：stack 的 "encrypted" connection event 带上 `peer_address` + `sec_level`（3=authenticated/2=unauth，复用 `_spawn_pair` 的约定），`pts_tester._on_conn` 转发 0x89（`_forward_sec_level`）。**与「DEVICE_DISCONNECTED 丢 peer_address」(ff51a72) 同族：状态事件不带全字段 = auto-pts model 陈旧。**
- **工具**：`pts_retry_cases.sh` 的 verdict 等待窗口默认 240s，这两例多 bearer 全库遍历要 3-5 分钟（case log 冻结但 ATT 流量在走，**不是 stall**——判 stall 前看 `iut-pybluehost.log` 是否还在长）；已加 `PYBLUEHOST_RETRY_WAIT_ITERS`（iter×4s，本批用 200）。窗口要比 PTS 自己的 `TSPX_time_guard`(300s) 长才有意义。
- **回归测试**：`tests/unit/l2cap/test_att_channel_mux.py::test_mux_routes_all_request_opcodes_to_server`（0x0E/0x20→server）；`tests/unit/test_stack_auto_encrypt.py::test_encryption_change_event_carries_peer_and_sec_level`；`tests/unit/pts/test_pts_tester_sec_level.py`（转发 0x89 载荷）。真机：BV-11 PASS（attempt 1）、BV-12 PASS（attempt 2，att1 是 peripheral flaky 的 UNKNOWN VERDICT: NONE）。

### Q: 重启 Windows 后 PTS 全 case 超时（client TimeoutError,server XML-RPC 却 200)→ A: **winNAT/Hyper-V 保留了 client callback 端口**(WinError 10013)/ 修复提交 bf23662

- **现象**：系统重启后 autoptsclient 每个 case 都 `TimeoutError` 挂掉。autoptsserver 日志显示 XML-RPC `POST / 200`(client→server 调用成功），但 client 的 `LT1-callback` 线程报 `PermissionError: [WinError 10013]`(socket 访问被拒）→ PTS 永远回调不到 client → client 干等超时。**PTS.exe 此时也没起**（重启杀了它）。
- **根因**:① autoptsserver 是懒启动 PTS.exe 的——client 首次连接经 COM 拉起 PTS.exe(~8s)，重启后首次连接超时属正常冷启动，重跑即可。② 更隐蔽：Windows 重启后 **Hyper-V/winNAT 随机保留一段 ephemeral TCP 端口**,autoptsclient 的 callback 端口（`-C`,原 65110）恰好落进保留区 `65108-65207` → bind 被拒（10013)。server 端口 65000 在另一空隙所以没事。
- **诊断**:`netsh int ipv4 show excludedportrange protocol=tcp` 看保留区；若 `-C` 端口落在某保留段内，换一个空隙里的空闲端口。
- **解决**:`pts_run_batch.sh` 的 `-C 65110` 改 `-C 60000`（当前在空隙 55438-60206)。**下次重启若又全超时，先查这个端口是否又被保留。**
- **复发（2026-11-02，插拔/重启后）**：这次连 **server 端口 65000 也被保留**（`64975-65074`），而 `-C 60000` 落进 `59972-60071`——两个都废。新症状比 callback 那次更隐蔽：autoptsserver 打印 `Serving on port 65000 ...` 之后**立即以 exit code 0 退出**，stdout 里一个错误字都没有（traceback 只写进 `/tmp/auto-pts/autoptsserver_65000.log`，末尾是 `PermissionError: [WinError 10013]` 紧跟 `Server 65000 finished`），看起来像「服务器起来又莫名死了」，极易误判成 dongle 故障往 USB/RF 方向查。**判据：`Get-NetTCPConnection -LocalPort <port> -State Listen` 为空 + stdout 有 `Serving on port` → 先读 `autoptsserver_<port>.log` 的最后一次 traceback**（`server_init()` 在 while 循环**之外**调用，异常直接穿出 `main`，所以循环一次都没跑）。
- **解决（端口已去硬编码）**：新增 `scripts/pts_pick_port.py`——**直接试 bind** 判定可用性，不解析本地化（中文标题）的 `netsh` 输出；先向上再向下搜索 ±1000（Windows 会连成片保留，本次 64975 到 65274 整段都没了，只向上找会扑空）。三个脚本（`pts_run_batch.sh` / `pts_retry_cases.sh` / `pts_harvest.sh`）的 65000 / 60000 全部改为读 `$AUTOPTS/.pts_ports`，server 端口在 `ensure_server` 处自愈、callback 端口在 `pts_run_batch` 处自愈，仍保留 `PYBLUEHOST_PTS_PORT` / `PYBLUEHOST_PTS_CLI_PORT` 显式覆盖。**别再往脚本里写死端口**，写死一次就够。本次实测自动选出 `64874` / `59970`。
- **附带**:BE200 IUT 固件锁死（不应 HCI Reset）经**系统重启恢复**；重启后 autoptsserver 要重启（它会自动拉起 PTS.exe)。AX201 重启后 `tools usb diagnose` 报 `Reset status 0x01 firmware load required`，但走完整 stack init(自动固件下载）能恢复，别担心。

### Q: PTS GAP/CONN/CPUP 全 FAIL——WID 46「start Connection Update」后 `AttributeError: 'NoneType' object has no attribute 'conn_latency'`（或请求 itvl=0 的非法更新）→ A: ① `IutActions.conn_param_update` 不存在，BTP 0x16 空 ack 不干活 ② DEVICE_CONNECTED 事件的 conn-params 字段恒为 0 / 修复提交（本 session）

- **现象**：`GAP/CONN/CPUP/*` 全 FAIL。CSR8510 时代是 WID 46 直接 `AttributeError: 'NoneType' ... 'conn_latency'`（auto-pts 的 `stack.gap.conn_params` 是 None）；BE200 上则是 DEVICE_CONNECTED 带了 conn params 但**全为 0** → WID 46 以 itvl=0/latency=1/timeout=0 当基线算出新参数 → IUT 请求一个非法更新 → PTS 判 FAIL。
- **根因（两个独立 bug）**：
  1. **`conn_param_update` action 缺失**：BTP GAP `_handle_op_16`(CONN_PARAM_UPDATE) 用 `getattr(actions, "conn_param_update", None)` 拿不到 → 只回 SUCCESS 不发任何 on-air 命令 → IUT 从不真的发起连接参数更新。
  2. **DEVICE_CONNECTED 的 conn-params 是占位零**：`GapService.on_connection_state_change` 在 DEVICE_CONNECTED payload 的 conn_interval/latency/timeout 字段（bytes 7-12）写死 `b"\x00"*6`（注释「Task 8 待接线」）。而 auto-pts 的 `gap_connected_ev_` 正好用这三个字段 `set_conn_params(...)` 当 CPUP 的基线——全 0 → WID 46 算出非法目标参数。
- **修法**：① 加 `HCI_LE_CONNECTION_UPDATE = make_opcode(OGF.LE, 0x13)`(0x2013) + `BLEConnectionManager.connection_update(handle, itvl_min, itvl_max, latency, timeout)`（发 HCI LE_Connection_Update,peripheral 时控制器转成 LL Connection Param Request）+ `IutActions.conn_param_update(addr_bytes, params)`（按 peer 解析 LE handle 转发；无 LE 连接则 ValueError→BTP_STATUS_FAILED）。② stack 在 LE Connection Complete 时把 (interval, latency, supervision_timeout) 存进 `_le_conn_params[handle]`（注意 **0x01 与 0x0A Enhanced 布局不同**——Enhanced 在 peer_addr 后多插 local+peer RPA 共 12 字节，params 偏移 11 vs 23),pts-tester `_on_conn` 把它传给 `on_connection_state_change` 写进 DEVICE_CONNECTED。
- **⚠️ 最易踩的坑**：`_le_conn_params[handle]` 必须在 **`_emit_connection_event` 之前**赋值——emit 是**同步**调 listener 的，pts-tester 的 DEVICE_CONNECTED 合成在回调里读 `_le_conn_params`，先 emit 后赋值就读到 None（=带零）。回归测试 `test_conn_params_available_during_connected_event` 锁这个顺序。
- **单位**：DEVICE_CONNECTED 报的 itvl/latency/timeout 用**原始 HCI 单位**(interval N*1.25ms、timeout N*10ms)。auto-pts `gap_update_connection_parameters` 不做单位换算，原样回填 0x16 →  echoed 回来还是 HCI 单位 → 直接喂 HCI,**全程无需换算**。
- **验证**：真机 `GAP/CONN/CPUP/BV-06-C`、`BV-10-C` PTS **PASS**(2026-08-26)。
- **后续（responder 方向，本 session 修复）**：BV-04/BV-05 是 **PTS(peripheral)经 L2CAP 发 `0x12` Connection Parameter Update Request、IUT(central)应答**的方向。btsnoop 证实 PTS 发了 `0x12`(itvl_min=8, itvl_max=0xaa, timeout=0x800）而 IUT 从不应答 → PTS 干等超时。修法：`L2CAPManager._on_le_signaling` 加 `_handle_le_conn_param_update_request`——回 `0x13`(result=0x0000 accept)+ 用 HCI LE_Connection_Update 把参数应用到链路。真机 **BV-04 PASS**；控制器实际把 itvl 更新到 168(status=0x00)。**BV-05 仍 FAIL**——responder 机制本身正常（应答+应用+更新完成），但 PTS 对更新结果有更具体的断言（需 GAP.TS 文本逐句核对，本地无）。
- **✅ 后续 2（BV-05 定案，「更具体的断言」= 拒绝不合法参数，2026-10-28）**：BV-05 是 CPUP/BV-04 的**负例双胞胎**——PTS(peripheral) 经 L2CAP 发一条**违反 Core 有效性规则**的 `0x12`（取值来自 `TSPX_iut_invalid_connection_*` IXIT），考的是 IUT(central) 必须回 **`0x13 result=0x0001`（Rejected）且不下发 HCI 更新**；原 responder 一律接受并应用。修法：`L2CAPManager._le_cpu_params_valid(itvl_min, itvl_max, latency, timeout)`——镜像 zephyr `bt_le_conn_param_valid`：interval 各自 `0x0006..0x0C80`、timeout `0x000A..0x3E80`、`itvl_max >= itvl_min`、`latency <= 500`（即 TGAP(conn_param_latency) 上限，CPU/BI-01 那条）、最后关系式 `timeout*4 > (1+latency)*itvl_max*2`；非法→reject 分支。合法路径零变化（BV-04 照旧接受）。**经验：L2CAP 0x12 的 responder 校验「参数合法性」与「角色合法性」（CPU/BI-02）是两个独立的门——负例 BI-01 考 latency 上限、BV-05 考全字段有效性，别只做一个。** 真机 **BV-05 PASS**（2026-10-29，暖机后首跑即过）：PIXIT 推送生效，LT 用非法参数发 `0x12`、IUT 回 `0x0001`，verdict 翻正。注意 `TSPX_iut_invalid_*` 这四个 PIXIT 推送必须走 per-case `custom` 前置（BV-04 共用 pre_conditions 不受影响，其请求按构造合法）。
- **回归测试**：`tests/unit/l2cap/test_le_signaling_dispatch.py` 新增 6 例（`_cpu_reject_case` 共享 harness：below-min/above-max interval、max<min、below-min timeout、relation violation、boundary accept）。
- **回归测试**:`tests/unit/pts/test_actions_conn_param_update.py`(manager 发 0x2013、action 解析 handle/拒 unknown-peer/忽略 classic、stack 抓 0x01+0x0A params、capture-before-emit 顺序）+ `test_gap_events.py::test_device_connected_event_carries_real_conn_params` + `tests/unit/l2cap/test_le_signaling_dispatch.py::test_conn_param_update_request_accepted_and_applied`/`_malformed_rejected`。

### Q: PTS GATT/CL/GAD/BV-03（发现 include services)`Error opcode in response!`（后转 INDCSV)→ A: BTP FIND_INCLUDED_SVCS(0x0d）是 stub 恒返 FAILED / 修复提交（本 session)

- **现象**：`GATT/CL/GAD/BV-03-C` 在 WID 15「send discover all include services」抛 `BTPError: Error opcode in response!`。
- **根因**:GATT BTP service 的 `_handle_op_0d`(FIND_INCLUDED_SVCS）是 stub「not implemented in v1.0」恒回 `BTP_STATUS_FAILED`。
- **修法**:`GATTClient.discover_included_services(start, end)`(ATT Read By Type,type=**Include 0x2802**，新增 `UUID_INCLUDE`)——解析 entry `incl_handle(2)+inc_start(2)+inc_end(2)+uuid`；加 `_encode_includes`（计数 + 每项 `incl_handle+inc_start+inc_end+uuid_len+uuid`,LE 序），接进 `_handle_op_0d`。**格式对齐 auto-pts `gatt_dec_incl_attr`/`gatt_dec_svc_attr`。**
- **验证**:btsnoop 证实 IUT 现在能正确逐轮回报 PTS db 里的 include——round 2 的 WID 24「confirm includes」答 **Yes**（发现的 0002/0041/0121 与期望逐位一致）。
- **遗留（非 IUT bug)**:GAD/BV-03 是 **3 轮**用例，round 3 的 WID 24 答 No → INDCSV。根因是 **auto-pts 侧**:`gattc_find_included_rsp(store_rsp=True)` 每轮先 `clear_verify_values()` 再存当轮值，而 round-3 的 `verify_description` 期望里仍含 round-2 的 handle(0002/0041)——被清了导致 verify 失败。IUT 每轮都如实上报了 PTS 实际 db(btsnoop 逐字节吻合）,**这是 auto-pts verify_values 跨轮累计的怪癖，不是我们的协议错**。要过需 auto-pts 侧改 verify 逻辑，或换单轮 include 用例。
- **回归测试**:`tests/unit/ble/test_gatt.py::test_gatt_client_discovers_included_services` + `tests/unit/pts/btp/test_gatt_client.py::test_find_included_returns_encoded_list`/`_wrong_length_fails`。

### Q: PTS GAP/CONN/ACEP（Auto Connection Establishment）全 BTP ERROR——`gap_connect('000000000000')` 永远连不上 → A: all-zero connect 地址 = 走 filter accept list，我们却字面当目标地址连 / 修复提交（本 session）

- **现象**：`GAP/CONN/ACEP/BV-01/03/04` 全 BTP ERROR。case log 显示 WID 400 先 `gap_set_filter_accept_list`(**BTP op 0x1c**)推进 PTS 地址，再 `gap_connect('000000000000')` → IUT 的 `_handle_op_0e` 把全零地址字面喂 `actions.connect` → `RuntimeError: LE connection to 00:00:00:00:00:00 failed to establish` → BTP_STATUS_FAILED → auto-pts `BTPError`。
- **根因**:ACEP 流程里 connect 目标地址**全零**是「**用 filter accept list 连**」的约定（等价 HCI LE_Create_Connection 的 `initiator_filter_policy=0x01`)。PTS 已先用 0x1c 把自己的地址推进 accept list，期望 IUT 连那个地址；我们的 connect handler 不认识这个约定。
- **修法**:`_handle_op_0e` 在 `addr_bytes` 全零且 `self._filter_accept_list` 非空时，替换成 accept list 第一项（addr_type+addr）再走正常 connect。**这是 direct-connect 捷径**（filtpol=0 直连解析出的地址），不是真·controller filter-list 自动连接，但对单地址的 BV-01 已够用。
- **验证**：真机 `GAP/CONN/ACEP/BV-01-C` **PASS**（原 BTP ERROR,2026-08-26);BV-03/BV-04 从 BTP ERROR 转 FAIL(connect 不再炸、流程跑通，但 PTS 对连接本身有更具体断言）。
- **遗留**:BV-03/04 FAIL 需 GAP.TS 文本逐句核对（本地无）。若它们真在测 controller-side Auto Connection Establishment(filter list 驱动、后台自动连），则需实装 HCI `LE_Add/Clear_Device_To_Filter_Accept_List` + connect 用 `filter_policy=0x01`——当前 `BLEConnectionManager.connect` 把 filter policy 写死 0x00，是投机性投入，未做。
- **回归测试**:`tests/unit/pts/btp/test_gap_service.py::test_connect_all_zero_addr_uses_filter_accept_list`（全零→替换 accept-list 地址）/ `test_connect_all_zero_addr_without_filter_list_stays_zero`（无 list 时透传）。
- **✅ 后续（2026-10-28/29，BV-04 翻正 + BV-03 两道门定案）**：BV-03/04 是 **RPA auto-connection** 用例（GAP.TS p194-197，本地 PDF 已有）：双方都用 RPA 且互发过 IRK，LT 分别用 **Directed（BV-03）/Undirected（BV-04）** connectable 广播；pass 判据是「IUT 用 RPA 当 initiator address 自主建立连接」。修法：per-case 注册 `acep_rpa_extra=[TestFunc(btp.gap_set_privacy_on)]`（BV-03/BV-04）+ `IutActions.prepare_auto_connection(peer)`（钉住本地 IRK=`PTS_IUT_IRK`、resolving list 进 peer identity、开地址解析、host 预铸本地 RPA）+ `_handle_op_0e` 全零地址分支在 privacy 开时调它并以 **filter_policy=0x01 + own_address_type=0x01** 发起。**真机 `GAP/CONN/ACEP/BV-04-C` PASS×2**（2026-10-28）。**⚠️ Own_Address_Type=0x02（controller-generatable RPA）已试并回退（2026-10-29）**：AX201 在 resolving list 的 Local_IRK=全零时对 0x02 **回落 identity address**——LT 侧 Enhanced Connection Complete 显示 `peer_rpa=0` + public InitA → LT 判「initiator 不是 RPA」→ 0.33s 秒断 → 无后续 MMI → client 60s FATAL（BV-04 从 PASS 回归 FATAL 的完整链条，server log 逐帧核对）。**教训：controller 的 own=0x02/0x03 RPA 生成依赖 resolving list 条目里有「可用」的 Local_IRK，全零 IRK 被当「无」处理；PIXIT 全零 IRK 的一致性只能靠 host 预铸（0x01）保住。** **BV-03 的 preamble 还有第二道门（2026-10-29 server log 定案）**：LT 在 preamble 连接里读我们 GATT GAP 服务的 **Central Address Resolution(0x2AA6)**，读到 0x00 直接判 "doesn't enable address resolution" → 断链 → INDCSV，**WID 400 从未下发**。已把 0x2AA6 值改 0x01（BV-18 只查 schema 不查值，不受影响）。**第三道门 = IRK 全零（2026-10-29 定案，`PTS_IUT_IRK = b"\xAB" * 16`）**：LT 铸 directed TargetA 用的就是 PIXIT 下发的 IRK——全零时 Intel resolving list 当「无密钥」，TargetA 永远解不出来。AB×16（十六个等值字节）= 非零可被 controller 使用 + 回文对任何 hex 解析字节序免疫；单一来源 `pybluehost.pts.actions.PTS_IUT_IRK`，PIXIT（`pybluehost_iut/gap.py::IUT_IRK_HEX`）+ `smp.set_local_irk` + resolving list local_irk 三处同值。**真机 `BV-03-C` PASS×3（确定性）**：LT 测试阶段 directed adv `peerAddrType=0x02`（TargetA=RPA(PIXIT IRK)），IUT 第一次 create（filter=0x01/own=0x01）即连上，LE Connection Complete 报 **peer_type=0x02（resolved public identity）+ peer=LT identity**——AdvA（对端 RPA 经 peer_irk）与 TargetA（我方 RPA 经 local_irk）双双由 controller 解析；LT 判完即秒断，connect() 重试耗尽才让 client 记 BTP ERROR，**PTS verdict 已在先（三次 set_result 全 PASS）**——ACEP 类的 BTP ERROR 必须查 case log 的 set_result 再定性。**`BV-04-C` 换 AB×16 后重跑 PASS（attempt 1 首跑）**——own=0x01 回退 + AB×16 无回归。**经验：directed 广播的匹配有两半——AdvA（对端）解析与 TargetA（自己）解析；BV-04 只考前者，BV-03 两个都考。** 诊断配套：`actions.connect` 重试耗尽后可做 2s 被动扫描空口窥视（`PYBLUEHOST_DEBUG_CONNECT_SCAN=1` 门控，`_peek_air_after_connect_failure`）——「对端没在广播」和「在广播但地址匹配不上」在 HCI log 里长得一模一样，peek 能区分；**autoptsserver 的 per-case log（`ptscontrol.py Log` 行）是 flush-at-end 批量到达的，wall-clock 不可信，要以行内的 `+N ms` 相对时序为准**——BV-03 的 0x2AA6 门与 INDCSV 隔 4 秒 wall-clock，实际在同一个被缓冲的 trace 里相邻。回归：`test_connect_all_zero_addr_uses_filter_accept_list` 断言 own_address_type=0x01 + `tests/unit/auto_pts_project/test_profile_modules.py::test_gap_acep_rpa_cases_enable_privacy_before_wid_400` + `tests/unit/pts/test_actions_acep.py`（顺序 rpa→list→resolution、peer IRK 全零、无 privacy 抛错）+ `test_start_server_hosts_standard_gap_gatt_services`（0x2AA6 ∈ {0x00,0x01}）。

### Q: PTS GAP/SEC/SEM BV-56..67（重连后收 GATT indication/notification）全 PTS TIMEOUT/FATAL——IUT 收到 IND/NTF 但不回 Upper Tester → A: ① 加密前收到的 IND 要**丢弃**（CFM 但不上报），加密后 PTS 发的第二条才上报 ② encrypt_pending 要**同步**在 ConnComplete 置位（否则竞态漏第一条）③ attach 时机 / 修复提交（本 session)

- **现象**：`GAP/SEC/SEM/BV-56-C` 等「pair→写 CCCD 使能 indication→disconnect→**未加密重连**→PTS 发 IND#1→（IUT 应 CFM 但**不**上报 Upper Tester)→加密完成→PTS 发 IND#2→IUT CFM **并**上报」用例，跑满 time_guard PTS TIMEOUT，或 auto-pts `wait_for_disconnection`/读 passkey FATAL ERROR。**关键认知：这里 IUT 全是 GATT Client**(Central/Peripheral 只是链路层角色）,PTS 是 GATT Server 发 IND/NTF,BTP 侧要把收到的 IND/NTF 译成 `OP_GATT_EVENT_NOTIFICATION` 事件喂回 auto-pts。
- **根因 1（没有加密门控 + 后来门控做错）**:TS(GAP.TS Table 4.20 step 9A.4/9B.4）明确「**加密完成前**收到的 IND#1,IUT 只 CFM、**不得**上报 Upper Tester；**加密后 PTS 会再发一条 IND#2**(step 10）才上报（step 12)」。正确做法是 **DROP IND#1**（不是 hold-then-flush)——初版做成「拦住+加密后 flush」，结果 flush 把 IND#1 也上报了，正中 WID 236「确认 IUT **没**上报 IND」的检查 → FAIL。**PTS 发的是两条不同的 IND，不是同一条重投**，所以 DROP#1、forward#2 才对；hold+flush 只是 Peripheral 情形靠时序侥幸蒙过。
- **修法 1（DROP 门控 + 同步 pending)**:`stack.py` 加 `_le_encrypted: dict[handle,bool]`(`_on_encryption_change` 置 True、LE ConnComplete 置 False)+ `_le_encrypt_pending: set[handle]` + 访问器 `is_le_encrypted`/`is_le_encrypt_pending`。`gatt.py::attach_to_att_bearer` 的 `_emit` 门控：`enc or not pend` → 立即发，否则 **DROP**(plain GAN 无 bond → pend=False → 照样立即发，不受影响）。
- **根因 2（encrypt_pending 竞态，Central 才暴露）**:`_le_encrypt_pending.add(handle)` 原本在 `_auto_encrypt_on_reconnect`/`_auto_security_request_on_reconnect` 里、`await _load_bond_for_peer` **之后**才置位。而这两个是 `asyncio.create_task` 出去的——LE ConnComplete 处理返回后、task 跑完 bond 查询前有个窗口，PTS 重连后**立刻**发的 IND#1 若落进窗口，gate 看到 `pend=False` → 误 forward → 漏。Peripheral 情形 PTS 等 SecReq 时序刚好不踩，Central(IUT 自己立即 auto-encrypt）必踩。
- **修法 2（同步置位 + 空 bond 清除）**:LE ConnComplete 的 Central/Peripheral auto-encrypt 分支里，**先同步 `add(handle)` 再 create_task**;task 里若 `_load_bond_for_peer` 返回空（非 bonded peer,plain GAN)，`discard(handle)` 清掉，避免误扣非 bonded 连接的通知。
- **根因 3（attach 时机/bearer 错配）**:`attach_to_gatt_client` 原在 conn-up 时跑，但 GATT client 是**懒建**的（首个 BTP GATT 命令才建 bearer)→ passive reconnect（无前置 BTP 命令）时 bearer 不存在、IND 来了没人接；且曾有「handler 接到旧 bearer、PTS 的 IND 进新 bearer」的双 bearer 错配。
- **修法 3（bearer-creation hook)**:`stack.py` 加 `on_att_client_bearer` hook(`connect_gatt` 建 bearer 后同步触发、`pts/actions.py::gatt_client_for_handle` 同样触发）;`pts_tester.py` 设 `stack.on_att_client_bearer = _on_att_bearer`，在 bearer **诞生那一刻**就 `attach_to_att_bearer`（带 `is_le_encrypted`/`encrypt_pending` callable,**emit 时**才读实时状态）。`connected` 时存 `_conn_peers[handle]` 并 spawn `_ensure_bearer`(peripheral/被动情形兜底）。attach 落 `bearer.set_notification_handler/set_indication_handler`（不走 `client.on_notification`)，幂等位 `bearer._btp_notif_wired`。
- **关键认知**:① GATT 通知事件格式要含 `notification_type` 字节（1=notification/2=indication,auto-pts WID 90 查 `==1`)——payload = `addr_type(1)+addr(6,LE)+notif_type(1)+handle(2LE)+len(2LE)+data`，对 `gattc_dec_notification_ev_data`(`<B6sBHH`);② indication 要 auto-CFM(bearer `_on_pdu` 已有）+ 走 `set_indication_handler`(type=2);③ 「encrypted 事件无 peer_address」和「DEVICE_DISCONNECTED 丢 peer_address」(ff51a72）同族——处理 state 前先看这个 state 带不带 peer;④ **「两端约定必须匹配第三方」的时序/门控，loopback 测不出**——hold+flush 在单测里自洽，只有真机对 PTS 的 WID-236 才暴露 DROP 才对。
- **验证**：真机 lvl2 全过——Peripheral BV-56/59 + Central BV-62/65 PASS;SC-only Peripheral BV-58/61 + lvl3 Peripheral BV-60 PASS(2026-08-26，原 PTS TIMEOUT/FATAL/INDCSV)。BV-62 gate log:IND#1 `DROP(pre-encrypt)`、IND#2 `forward`，逐字节符合 TS。
- **遗留（lvl3/SC **Central** 角色，BV-63/64/67 INDCSV + BV-57 lvl3-Peripheral FAIL)**:**和 notification 机制无关，是 SMP pairing 层**。WID 241 把 io_cap 设成 `keyboard_display`(lvl3 要 MITM/authenticated),Lower Tester SC=1 → 是 **SC + MITM** 配对。auto-pts 卡在 `wait_for_event(lambda: stack.gap.passkey.data)` 5s 超时 → IUT 从没 display passkey → PAIRING_FAILED reason=0x05。即 **KeyboardDisplay + SC 的 association model 没解析到「IUT display」**(IUT 该 display passkey 让 auto-pts 经 PASSKEY_DISPLAY ev 读到，但没触发）。Central lvl2(JW）能过是因为不要 MITM。要攻这块得把 SC + keyboard_display 的 association model/passkey display 路径弄对（和已知 SCPK/SCOB gap 同族）。**TS 已本地化** `docs/spec_download/.../gap_ts_p46_pdf.pdf`(BV-56..67 在 Table 4.20-4.25)。
- **回归测试**:`tests/unit/pts/btp/test_gatt_cfg_notify.py::test_incoming_indication_emits_btp_event_with_type_2` / `test_attach_to_gatt_client_is_idempotent` / `test_notification_dropped_while_encrypt_pending` / `test_notification_forwarded_immediately_when_{no_encryption_expected,encrypted}`;`tests/unit/test_stack_auto_encrypt.py::test_central_bonded_reconnect_marks_encrypt_pending_synchronously` / `test_central_reconnect_no_bond_clears_optimistic_pending`。

### Q: PTS GAP/SEC/AUT 大批 INDCSV(9/16:BV-11/18/19/20/21/22/25/27/28)——连接成功、WID 139 也解析对 handle，但 PTS 读完保护特征就断连 → A: 未配对链路对 read_enc 特征回 0x0F(PTS 无 LTK 可加密→放弃），应回 0x05 驱动配对 / 修复提交 abf091a

- **现象**：SEC/AUT 16 例跑完 PASS 3(BV-12/17/26)、FAIL 4(BV-13/14/23/24)、**INDCSV 9**。以 `GAP/SEC/AUT/BV-11-C`(Service Response Insufficient Authentication,Peripheral,IUT 当 GATT server）为例逐层定位：
  - WID 91 advertise → PTS 连上；WID 139 经 BTP `GATT_GET_ATTRS`/`GET_ATTR_VALUE` 正确解析出保护特征 handle `0005`(perm=0x05=read|read_enc)。
  - btsnoop 实证：`PTS->IUT ATT ReadReq hdl=0x0005` → `IUT->PTS ATT ErrRsp code=0x0f`(Insufficient Encryption)→ **PTS 直接 0x13 断连，不配对** → INDCSV。
- **根因**：`_read_error`/`_write_error` 的 enc 分支对**未加密**链路一律回 `0x0F`。但按 **GAP Vol 3 Part C §10.3**：未配对链路应回 **`0x05`(Insufficient Authentication)** 驱动 central 去**配对**;`0x0F`(Insufficient Encryption）只在**已 bonded/authenticated** 时有意义（让 central 用已有 LTK 直接加密）。对无 bond 的 PTS 回 0x0F，它没有 LTK 可加密 → 判无可操作 → 断连放弃。
- **修复**：enc 分支按 `sec.authenticated` 分流——未认证→`0x05`，已认证（bonded)→`0x0F`(key_size 不足仍 0x0C)。`_read_error`/`_write_error` 同步改。**套件安全**:GATT/SR 无「未配对期望 0x0F」的用例（其 enc BI 用例都先 bonded，走 `authenticated=True` 分支仍回 0x0F)。
- **回归测试**:`tests/unit/ble/test_gatt.py`——`test_read_enc_required_unpaired_unencrypted_returns_insufficient_authentication`(0x05)、`test_read_enc_required_bonded_unencrypted_returns_insufficient_encryption`(0x0F)、`test_standalone_read_enc_*`(0x05 unpaired / 0x0F bonded)、`test_standalone_write_enc_*`、`test_read_multiple_variable_security_char_returns_its_error`(0x05)、`test_read_using_uuid_security_char_returns_error_not_value`(0x05)。全套 2253 passed。
- **真机**:`GAP/SEC/AUT/BV-11-C` PTS **PASS**(2026-08-27，第 2 次跑；第 1 次 PTS 根本没连上是 peripheral flaky)。
- **⚠️ 干扰项（判 verdict 前必看）**:SEC/AUT 是 peripheral 用例（PTS 当 central 连 IUT),**peripheral flaky connect** 会让一次跑里 PTS 从不发 CONNECT_IND(btsnoop 只有 IUT 广播 setup、0 个 ATT 包）→ PTS TIMEOUT/INDCSV。BV-11 第 1 次就踩这个，重跑才连上。**别把 flaky TIMEOUT 当修复无效或回归**——先解 btsnoop 确认 PTS 到底连没连。

### Q: PTS RFCOMM BV-13/14（RLS）死活不应答、BV-25（Non-Supported Command）FAIL → A: ① RLS MCC type 是 0x53/0x51（不是 0xA3——0xA3 是 FCON!）② 未知 MCC 要回 NSC，但**响应类** type 必须静默消费 / 修复提交（本 session)

- **根因 1（RLS type 值）**：第一版把 RLS 命令/响应当成 `0xA3/0xA1`(= type 0x28<<2，实际是 FCON)。空口实证 PTS 发的 RLS 命令是 `53 05 2b 05`——**RLS type value = 0x14** → 命令字节 0x53、响应 0x51。GSM 07.10 type 值速查（字节 = type<<2 | CR<<1 | EA):PN=0x20(0x83/0x81)、TEST=0x08(0x23/0x21)、MSC=0x38(0xE3/0xE1)、RPN=0x24(0x93/0x91)、**RLS=0x14(0x53/0x51)**、NSC=0x04(rsp 0x11)。**别凭直觉编 type 值——以空口或 zephyr `rfcomm_internal.h` 为准。**
- **根因 2（NSC 误伤响应）**：加 NSC(RFCOMM/DEVA-DEVB/RFC/BV-25 要求对不支持的命令回 `11 03 <type>`）时把所有未识别的 MCC type 都回了 NSC——包括 PTS 发来的 **MSC 响应 0xE1**（我们主动 MSC 的应答），协议瞬间污染。响应类 type(PN/MSC/RPN/RLS/TEST-RSP + NSC-RSP）必须显式静默消费，**只对真正的未知命令**回 NSC。
- **BV-13/14（RLS 指示）**：收到 RLS 命令原样回 RLS 响应（echo payload）即可；BV-14 由 BTP `SEND_RLS`(op 0x08)→ `RFCOMMSession.send_rls(dlci, line_status)` 真发 MCC 命令（line_status 字节 BTP 已编好 L 位+错误码：framing=0x09/parity=0x05/overrun=0x03)。
- **BV-17/19（RPN）**:RPN 命令 echo 回 0x91 即过 BV-17;**BV-19** 是「payload 只有 1 字节（DLCI)= 请求当前 port 值」→ 必须回全 8 字节当前设置（baud 0x07/8N1 0x03/flow 0/xon 0x11/xoff 0x13/mask 0x3EFF——bit8 保留位必须 0)。BTP `SEND_RPN`(op 0x06)→ `send_rpn(...)`。
- **回归测试**:`tests/unit/classic/test_rfcomm.py::test_rfcomm_session_sends_rls_command` / `..._sends_rpn_command` / `..._responds_to_inbound_rls_and_rpn` / `..._answers_unknown_mcc_with_nsc` / `..._answers_rpn_value_request_with_current_settings`。

### Q: PTS RFCOMM BV-15（PN 协商）FAIL + BV-21/22（Credit 流控）INDCSV → A: ① PN 响应要接受 credit（回 PN_CFC_RESP=**0xE0**——TS 说的「CL-bits=0x0E」是 0xE0 的**高半字节**!)② credit 是 PN body 第 8 字节（不是第 9 字节）③ credit 模式 TX 要排队异步 drain / 修复提交（本 session)

- **根因 1（PN 响应 flow 字节）**:PTS 的 PN 命令 flow=**0xF0**(PN_CFC_CMD，提议 credit 流控）且 body 第 8 字节 K=它给我们的初始 credit。之前按「回声口抓包形状」回 flow=0x00（拒绝 credit),BV-06/13/14 能过但 BV-15（专测 PN 协商）FAIL。TS 原文「CL-bits must be set to 0x0E」指的是 **0xE0 的高半字节**——即回 PN_CFC_RESP=0xE0 **接受** credit(zephyr `rfcomm_send_pn` 对 cfc 就回 0xE0 + 自己的 K)。曾误入歧途回 0x0E（把 0x0E 当整字节）→ BV-06/13/14 全 FAIL，因为 0x0E 对 PTS 的解析器是无意义值。
- **根因 2(credit 位置）**:zephyr `struct bt_rfcomm_pn` 是 **8 字节定长**——dlci/flow/priority/ack/mtu(2)/retrans/**credits（第 8 字节）**。不存在「9 字节带 K」的形式；credit 永远在第 8 字节（无 credit 协商时为 0)。曾按 9 字节判别导致真 PN 被当畸形静默丢弃。
- **实装（zephyr 对齐）**:responder 收 0xF0 → 回 `dlci, 0xE0, 0, 0, mtu=min(peer,127), 0, K=7` 并把对端的 K 存 `_pending_credits[dlci]`(SABM 建信道时灌进 `channel._tx_credits`);initiator 的 PN 命令也改 0xF0+K=7，收 0xE0 响应同样取 K。收 data UIH P/F=1 → 首字节是给我们的 credit 累加；credit 模式收到用户数据后每帧回赠 1 credit(`grant_credits`,P/F=1 UIH 带 credit 字节）。
- **根因 3(TX 阻塞）**:credit 模式下 `channel.send()` 最初在 credit=0 时**阻塞等 credit**——但 PTS 的 top-up 可能在几十秒后才来，BTP 命令先超时。改成**队列+异步 drain**:send() 入队即返回，drainer 按 credit 发送、耗尽即停（BV-21 正是验证「发够 K 帧即停、收到 credit UIH 再续」)。
- **回归测试**:`test_rfcomm_credit_negotiation_and_send_accounting`(0xF0→0xE0+K7、credit 入账、停发/续发）。

### Q: PTS RFCOMM BV-04/07（会话/DLC 关闭）长年 INDCSV + BV-21/22 数据帧明明发了 PTS 却当没看见 → A: **数据 DLCI 上我们发起的帧 C/R 位恒为 1，但 session acceptor 发起的 UIH/DISC 必须 C/R=0**(zephyr `BT_RFCOMM_UIH_CR(role)=(role==INITIATOR)`) / 修复提交（本 session)

- **根因**:`encode_frame` 原来「dlci≠0 一律 C/R=1」。但 TS 07.10/zephyr 的规则是**方向性**的：命令帧和数据 UIH 的 C/R = 会话角色（initiator=1/acceptor=0)，只有 UA/DM 复制被答命令的 C/R。我们作为 acceptor(PTS 发起的会话）发出的数据 UIH、DISC 全带着 C/R=1 → **PTS 视为方向非法直接丢弃**——抓我们自己 log 帧发出去了、PTS 那边像没收到。这一条同时锁死三类用例：BV-21/22（数据帧被丢）、BV-07(IUT 发 DISC 关 DLC 被丢）、BV-04（关会话流程里的 DLC DISC)。
- **修法**:`encode_frame` 统一用 `frame.cr`;`RFCOMMChannel._cr()` = session initiator?1:0，数据帧/grant_credits/DISC 全走它；`_send_ua` 保持 C/R=1（答 initiator 命令）;MCC on DLCI 0 保持原「responder 方向 C/R=0」规则不变。
- **教训**:RFCOMM 的 C/R 有三套语境别混——① 会话方向（initiator/acceptor，决定命令+数据 UIH 的位）② 命令/响应（UA/DM 复制命令的位）③ MCC type 字节内部的 C/R(0x83→0x81 那种，和地址字节无关）。之前 DLCI-0 的 C/R 坑（09c1069）是②③，这次数据 DLCI 是①。
- **回归测试**:`test_rfcomm_acceptor_session_data_frames_use_cr_clear`(acceptor 数据帧+DISC 地址字节 C/R=0)。
- **真机**：修后 RFCOMM **17/17 全 PASS**(2026-09-09):DEVA BV-01/05、DEVB BV-02/06、DEVA-DEVB BV-03/04/07/08/11/13/14/15/17/19/21/22/25。

### Q: PTS SDP/SR/SA/BV-01（Service Attribute Request,server 角色）FAIL——IUT 对 search pattern 0x0100 返回 0 条记录 → A: IUT 的 SDPServer 没有强制要求的 ServiceDiscoveryServer record / 修复提交（本 session)

- **现象**:`SDP/SR/SA/BV-01-C` FAIL。IUT 当 SDP **server**,PTS(Lower Tester）连上 PSM_SDP 后先用 `TSPX_sdp_service_search_pattern`(=0x0100,ServiceDiscoveryServerServiceClassID）做 Service Search 找记录，再对其发 Service Attribute Request。我们返回 `TotalServiceRecordCount=0` → PTS 拿不到记录 handle → FAIL。
- **根因**:`SDPServer()` 启动时 `_records` 为空。但 Core Vol 3 Part B 规定**每个 SDP server 必须**在保留 handle **0x00000000** 上 host 一条 ServiceDiscoveryServer record(ServiceClassIDList=0x0100 + ProtocolDescriptorList=L2CAP/PSM_SDP + BrowseGroupList=PublicBrowseRoot 等）。SDP BTP service 只有 client 侧命令（SEARCH/ATTR/SEARCH_ATTR),**没有**「注册 server 记录」的 BTP 命令，所以 SR 用例期间 server 一直是空的。
- **修法**:`pybluehost/classic/sdp.py::make_service_discovery_server_record()` 造这条记录，在 `SDPServer.__init__` 里**固定注册到 handle 0x00000000**（**不消耗** `_next_handle` 0x00010000 起的动态空间——e2e 的 SPP record 仍拿 0x00010000，零回归）。
- **回归测试**:`tests/unit/classic/test_sdp.py::test_sdp_server_hosts_service_discovery_server_record_at_handle_zero` / `..._search_for_service_discovery_server_finds_record` / `..._attribute_request_on_discovery_server_record_returns_attributes`。真机 `SDP/SR/SA/BV-01-C` **PASS**(2026-09-09,19s，首跑即过）→ SDP **3/3**。
- **⚠️ 配套坑（务必记住）**:SDP/RFCOMM 等 BR/EDR profile 的 PTS 用例**不在**默认的 LE workspace(`runs/phase2/workspace/zephyr-master/zephyr-master.pqw6`，其 `get_project_list` 是 AICS/ASCS/BAP/.../TMAP 那套 LE audio,**没有 SDP/RFCOMM**)。必须用 `PYBLUEHOST_WORKSPACE=<repo>/runs/pts_sdp/pybluehost-all2/pybluehost-all2.pqw6`(`get_project_list` = GAP/GATT/L2CAP/SM/SDP/RFCOMM)。**注意 `pybluehost-all.pqw6`（无 2）是个陷阱**——名字像 all-profiles，实际 project list 也是那套 LE audio（不含 SDP)；**用 `pybluehost-all2.pqw6`**。症状：跑 SDP 全组 `Number of test cases to run: 0`、无 traceback，就是 workspace 不对。

### Q: PTS GAP/CONN/CPUP/BV-01（Peripheral Initiator over L2CAP)BTP ERROR「no LE connection」，连接明明在 → A: ① LE Connection Complete 事件从不带 `transport` 字段 ② IUT 会话表用「handle≥0x0100 → classic」的句柄阈值猜，AX201 的 LE handle 是 0x0E01 被误判成 classic / 修复提交（本 session)

- **现象**:peripheral 角色下 PTS 连入（DEVICE_CONNECTED 正常）,WID 46 `gap_update_connection_parameters`(BTP op 0x16）一到，`conn_param_update` 在 `_session.connections` 里按 `transport=="le"` 过滤找不到 → 抛 `ValueError: no LE connection` → BTP_ERROR。打日志看到 `connections={3585: ('classic', '94:53:FF:1E:6A:EE')}`——连接在、peer 也对，但 transport 被标成 **classic**(handle 3585=0x0E01)。
- **根因（两层）**:① `stack.py` 的 LE Connection Complete 处理在 emit `StackConnectionEvent(state="connected")` 时**从不设 `transport`**（约定「None=LE」)。② `pts/actions.py::_on_connection_event` 的兜底是 `transport = "classic" if handle >= 0x0100 else "le"`——假设 LE handle 恒 <0x0100。但 **AX201 的 LE 连接 handle 是 0x0E01**(≥0x0100)→ 被误判 classic → LE 过滤落空。BV-06(central）能过是因为 central 走 `connect()` action 显式存 `transport="le"`，不经这个兜底。
- **修法（源头显式标注，别再猜句柄）**:① `stack.py` LE Connection Complete 事件显式 `transport="le"`;② classic `HCI_Connection_Complete` 事件**无条件** `transport="classic"`（顺带修了原 `link_type==0` 的 bug——HCI link_type **0x00=SCO、0x01=ACL**，原代码把 ACL 判成非 classic 靠句柄兜底掩盖）;③ `actions.py` 兜底简化为 `transport or "le"`（两个源头都显式标了，None 只剩异常路径）。**经验：连接句柄值不能用来推断 link type——LE/classic 都可能是任意 handle;link type 必须在事件源（HCI 事件种类）处显式标注。**
- **回归测试**:`tests/unit/pts/test_actions_conn_param_update.py::test_le_connected_event_marks_transport_le_even_for_high_handle`(handle=0x0E01 → "le")。
- **真机**:BV-01 从 BTP ERROR → FAIL（流程跑通、conn_param_update 成功发到空口）。**遗留 FAIL** 是另一层：BV-01 是「Peripheral Initiator **over L2CAP**」,PTS 期望 IUT 发 **L2CAP Connection Parameter Update Request(0x12)**，而我们的 `connection_update` 走 HCI LE_Connection_Update(over LL，那是 BV-10 的路径）。要过 BV-01/02/03(peripheral-over-L2CAP 簇）需实装 L2CAP 0x12 **请求方**（现有只有 0x12→0x13 应答方），留作下一跳。

### Q: PTS GAP/GAT 全系（Discover/Writeable GAP Characteristic)+ GATT/SR/GAS 大批 FAIL——IUT 的 GATT db 里没有标准 GAP(0x1800)/GATT(0x1801) 服务 → A: BTP START_SERVER 时原生 host 这两个标准服务 / 修复提交 fff352e

- **现象**：GAP/GAT 6 例全 FAIL（发现不到 Device Name/Appearance/PPCP/Central Address Resolution);GATT/SR/GAS 一批 FAIL（发现不到 Service Changed)。auto-pts 的 GATT/SR `init_server` 只 BTP 建 vendor 服务，**不会**替 IUT 加标准 GAP/GATT 服务——参考 IUT(zephyr/bluez）是原生 host 的。
- **根因**：我们的 PTS server db 只装 BTP 下发的 vendor 服务，缺标准 GAP(0x1800)/GATT(0x1801)。PTS 发现不到这些 mandatory characteristic → FAIL。
- **修复**：`pts/btp/services/gatt.py::_standard_gap_gatt_services()`——GAP(0x1800):Device Name(0x2A00,RW)、Appearance(0x2A01,RW)、PPCP(0x2A04,R)、**Central Address Resolution(0x2AA6,R,value=0x00=不支持 RPA 解析，BV-18)**;GATT(0x1801):Service Changed(0x2A05,INDICATE)。在 `_handle_op_07`(START_SERVER)**末尾、vendor 服务之后** add（保持 vendor handle 布局不变）。**安全**:auto-pts 的 handle 发现是动态自洽的（WID handler 用 `gatts_get_attrs(type_uuid='2800'/'2803')` 按 UUID 匹配服务再算 handle)，加标准服务会移位 vendor handle 但 auto-pts 会重新发现 → 零回归。
- **回归测试**:`tests/unit/pts/btp/test_gatt_server.py::test_start_server_hosts_standard_gap_gatt_services`;`test_gatt_service.py::test_gatt_get_attributes_reads_committed_db`(count 1→3,vendor 先 commit 占最低 handle)。真机 GAP/GAT/BV-16(Discover Device Name)PASS——直接证明 GAP 服务+Device Name 可发现（2026-08-27)。

### Q: PTS GAP/GAT/BV-05(Writeable Device Name)8 连 FAIL，BV-06(Writeable Appearance）却能过 → A: ATT Write Command(0x52) 根本没 dispatch,PTS 第一步写不进值、read-back 拿到旧值 / 修复提交（本 session）

- **现象**：BV-05/BV-06 都是「Writeable GAP Characteristic」用例，流程相同（PTS 写→读回校验）。BV-06 重跑 3 次内 PASS,BV-05 却 8 连 FAIL（确定性，不是 flaky)。
- **根因**：测试规程第一步是 PTS 发 **ATT_WRITE_CMD(0x52,Write Without Response)** 写新 Device Name，然后 READ_REQ 读回，**值一致才 PASS**。但 `GATTServer._dispatch` 只处理 `ATT_Write_Request`(0x12),**没有 `ATT_Write_Command`(0x52) 分支**——0x52 落到末尾「Request Not Supported(0x06)」错误且**值从不写入**;read-back 返回旧的 "PyBlueHost" → 永远 FAIL。BV-06 能过纯属 Appearance 的写恰好走了别的路径/运气。**这是协议栈通用 bug**，不止 PTS——任何用 Write Without Response 的 GATT client 都写不进我们的 server。
- **修复**:① `_dispatch` 加 `ATT_Write_Command` 分支 → 新 `_handle_write_command`：属性存在且当前安全级别可写则 `_apply_write` 提交值，**返回 `None`**(command 永不应答，连错误也不回——Core Vol 3 Part F §3.4.5);② `handle_request` 返回类型改 `ATTPdu | None`;③ `stack.py::on_att_data` 只在 response 非 None 时 `channel.send`。mux 本就路由 0x52→server，无需动。
- **回归测试**:`tests/unit/ble/test_gatt.py::test_gatt_server_write_command_stores_value_without_response`(写值+无响应）、`test_gatt_server_write_command_not_writable_drops_silently`(不可写则静默丢、值不变）。真机 BV-05 第 3 次跑 **PASS**(前 2 次是 peripheral flaky 没连上，2026-08-27)。

### Q: PTS GAP/BROB/BCST（广播模式）全系 INDCSV——IUT 确实在广播、PTS 却扫 36s 判 INDCSV → A: 我们从不在 pre_conditions 设 `TSPX_advertising_data`,PTS 拿 workspace 陈旧默认值去比对，永远匹配不上 / 修复提交（本 session）

- **现象**：BCST/BV-01..05(IUT 当 broadcaster 非连接广播，PTS 被动扫描）全 INDCSV。IUT 的 START_ADVERTISING 成功、广播也上了空口（OBSV 方向 PTS↔IUT RF 正常），但 PTS 扫 ~36s(`TSPX_time_guard`）后判 INDCSV 而非 PASS/FAIL——即「没观察到期望的广播」。
- **根因**：测试规程要求「Lower Tester 收到 **TSPX_advertising_data** 指定的广播数据」。PTS 把扫到的广播跟 **TSPX_advertising_data** 这个 IXIT 比对。参考 IUT(zephyr `ptsprojects/zephyr/gap.py`、bluez）在 pre_conditions 里 `update_pixit_param("GAP","TSPX_advertising_data", ad_pixit)`——`ad_pixit = flags(BR/EDR-not-supp) + complete_local_name`，正好等于它们广播的内容。**我们的 `pybluehost_iut/gap.py` 从不设这个 PIXIT** → PTS 用 workspace 里的陈旧默认值去比，跟我们广播的 `Tester_XXXXXX` 名字永远对不上 → INDCSV。
- **修复**:`pybluehost_iut/gap.py::test_cases` 复刻 zephyr 的 `ad_pixit` 计算（`AdType.flags`+`AdFlags.br_edr_not_supp` + `AdType.name_full`+`bytes.hex(iut_device_name)`，即「len type data」hex AD-string)，加 `TestFunc(update_pixit(pts,"GAP","TSPX_advertising_data", ad_pixit))`。我们 START_ADVERTISING 的 `_apply_mode_to_adv` 注入的 Flags(0x04)+name 跟它逐字节一致，所以 PTS 一比就中。**注意**:`gap.py`/`ixit.py` 是 autoptsclient 启动时 import 的常驻模块，改动要**重启 autoptsclient** 才生效（pts_retry_cases.sh / pts_run_batch.sh 每次都新 spawn，自动生效）。
- **关键认知**:「IUT 广播/扫描类用例 INDCSV 但 RF 正常」先查 **IXIT/PIXIT 对齐**——PTS 很多 verdict 是拿空口数据跟某个 `TSPX_*` 值比对，参考 IUT 在 pre_conditions 里把这些 PIXIT 推成和自己行为一致的值，漏推就是「IUT 明明做对了却 INDCSV」。这类 bug btsnoop 看不出（广播确实上了空口），要对 auto-pts 参考实现的 pre_conditions 逐项核对。
- **真机**:BCST/BV-01 改后首跑 **PASS**(2026-08-27);BV-02..05 同根因，随同批验证。

### Q: PTS L2CAP/LE/CPU/BI-01+BI-02、LE/REJ/BI-02、LE/CFC/BI-01 四例 —— 都是「响应/校验缺失」类,不是协议栈能力问题 → A: ① CPU 请求要按角色+参数校验 ② credit 计数 16-bit 上限 ③ 未知 signaling code 要回 Command Reject / 修复提交 ee622c4

- **现象与根因（四例各自的缺口）**:
  1. **L2CAP/LE/CPU/BI-02（Peripheral 收到 CPU Request 必须 Command Reject）**:`_handle_le_conn_param_update_request` 无条件回 `0x13 accept`。但 Connection Parameter Update 规程是**peripheral→central 单向**的（Core Vol 3 Part A §4.20);IUT 当 **peripheral** 时收到 CPU Request 属「该方向不支持的命令」→ 必须回 `COMMAND_REJECT_RSP` reason **0x0000**（Command not understood），**不是** `0x13`。判角色要拿真实 LE role,manager 原本没有——加 `set_le_role_provider(cb)` 由 `Stack` 注入 `lambda h: stack._le_conn_roles.get(h, 0x00)`。
  2. **L2CAP/LE/CPU/BI-01（Latency>500 必须 reject）**:同函数只判了 payload 长度,**没有参数合法性校验**。TGAP(conn_param_latency) 上限 500,超过要回 `0x13` result=**0x0001**(rejected) 且**不得**下发 HCI LE_Connection_Update。
  3. **L2CAP/LE/CFC/BI-01（credit 溢出必须断信道）**:credit 计数是 16-bit 字段（§4.24),对端发一个超大的 Flow Control Credit 使总量 >65535 时必须**断掉 LE Data Channel**。原 `add_credits` 只 `semaphore.release()`,无累计、无上限 → 改成维护 `_tx_credits_total`,超限则 `add_credits` 返回 False 且不生效,manager 收到 False 后 `disconnect_le_coc_channel(ch)`。
  4. **L2CAP/LE/REJ/BI-02（未知/RFU code 必须 Command Reject）**:`_on_le_signaling` 的 `else` 分支**只打了一条 debug log、从不回包** → PTS 干等到 time guard。按 §4.1 + TS Table 4.26,未知/RFU code 要回 `COMMAND_REJECT_RSP` reason 0x0000 且**无 Reason Data 字段**（响应类 code 允许回或不回,统一都回更省事且不违规）。
- **关键认知**:① 这四例没有一个是「实现不了」,全是**响应缺失/校验缺失**——TS 里 `Pass verdict` 一句「IUT sends X」就是需求,没实现对端就干等或判负;② **响应类 vs 命令类**的分流:同一条 LE signaling 通道上,「谁可以发这个命令」是有方向的,判错方向要么该拒的没拒、要么该收的被当命令答;③ 16-bit 计数字段（credit/长度）一律要防溢出,`semaphore` 这类抽象**不替你记账**。
- **回归测试**:`tests/unit/l2cap/test_le_signaling_dispatch.py::test_conn_param_update_request_rejects_latency_above_500` / `..._as_peripheral_sends_command_reject` / `..._unknown_signaling_code_gets_command_reject`;`tests/unit/l2cap/test_le_coc_credits.py::test_credit_overflow_disconnects_channel` / `..._credit_exactly_at_ceiling_is_accepted`（65535 恰好合法,上限含）。
- **真机**:四例全部**首跑 PASS**(2026-09-09)→ L2CAP 73→**78/100 (78.0%)**。

### Q: PTS L2CAP/ECFC/BV-11+13（Security responder）PTS 挂到 time guard——IUT 明明按 spec 回了 0x18 result=0x0005 → A: 拒绝响应必须**带 N 个全零 DCID 槽**（N = 请求里的 SCID 数，zephyr `l2cap_ecred_conn_rsp` 就是这么编的）/ 修复提交 e6a89b0

- **现象**:`L2CAP/ECFC/BV-11-C`（Insufficient Authentication responder）跑满 time guard 无 verdict。**等价 legacy 版 `L2CAP/LE/CFC/BV-11-C` 却 PASS**。加了 LE signaling RX/TX 日志后空口真相一目了然:
  ```
  LE signaling RX handle=0x0E01 code=0x17 id=1 len=14
  ECFC request psm=0x0080 scids=(64,) listener=True required_sec=1 -> result=0x0005
  LE signaling TX handle=0x0E01 code=0x18 id=1 len=12
  ```
  即：**我们收到了请求、选对了 PSM、算对了 result=0x0005、也把 0x18 发出去了**——行为逐项符合 spec，PTS 仍然干等。
- **根因**:`ECFCConnectionResponse.encode` 对「拒绝」强制 `len(dcids)==0`（照 Core 5.2 §4.25 字面「拒绝不带 DCID」）。但 **zephyr（参考 IUT，PTS 认）的 `l2cap_ecred_conn_rsp` 是反的**：
  ```c
  /* set dcid to zeros here, in case of all connections refused error */
  memset(dcid, 0, sizeof(dcid));
  buf = l2cap_create_le_sig_pdu(BT_L2CAP_ECRED_CONN_RSP, ident,
                                sizeof(*rsp) + (sizeof(scid) * req_cid_count));
  rsp->result = sys_cpu_to_le16(result);
  net_buf_add_mem(buf, dcid, sizeof(scid) * req_cid_count);   /* 总是补满 */
  ```
  **响应体的 DCID 槽数恒等于请求的 SCID 数，拒绝时全零。** 我们少发那两字节 → PTS 解析器认为响应不完整 → 一直等。
- **修法**:`ECFCConnectionResponse` 允许拒绝时带 DCID，但要求**全零**（`any(d != 0)` 才报错）；manager 的拒绝分支改 `dcids=(0,) * len(req.scids)`。
- **关键认知**:① **「按 spec 字面写」在这个用例上会输给「按参考实现写」**——PTS 的解析器是照 zephyr/bluez 的实际字节训出来的，遇到 spec 与参考实现分歧（这里是拒绝响应要不要带零 DCID），**以参考实现为准**；② 这正是我们早就见过的**对称现象**：`ECFCConnectionResponse.decode` 当初就得「容忍 PTS 补零 DCID」（提交 009fe17）——既然 PTS 当 responder 时会补零，它当 initiator 时自然**也期望对端补零**；③ **`LE signaling` 之前完全没有 RX/TX 日志**（classic 的 `signaling.py` 有），本次加上后一眼定位——加这类「空口两侧对称日志」比反复猜协议便宜得多。
- **附带（本 session 同 commit）**:① `_on_le_signaling_safe` 兜底——handler 抛异常原会顺着 ACL read task 蒸发，对端等到 time guard（正是本次「明明发了还挂」之外的另一种静默失败模式）；② `ECFC request psm=... listener=... result=...` debug 行，判 PSM 选错/listener 没挂/result 算错一目了然。
- **回归测试**:`tests/unit/l2cap/test_le_ecfc_manager.py::test_ecfc_refusal_pads_zero_dcids_matching_scid_count` / `..._with_single_scid_pads_one_dcid`（断言**原始字节**长度与尾部零，因为 decoder 按设计会丢弃拒绝时的 padding）。
- **真机**:`L2CAP/ECFC/BV-11-C`、`BV-13-C` **PASS**(2026-09-13)→ L2CAP 78→**81/100 (81.0%)**，**0 fail**。**遗留**:`L2CAP/ECFC/BV-15-C`（Insufficient Encryption **Key Size** responder）PTS 连上约 2s 后自己 `0x13` 断连、**从不发 0x17**——与 BV-11/13 的根因不同，疑需先建立**加密链路**（短 key）才发请求，留作下一跳。

### Q: PTS GAP/PRIV + 私有地址类全系 INDCSV/timeout——auto-pts 直接跳过、什么都没做 → A: ① `SET_PRIVACY` 不回 settings 位图，`iut_has_privacy()` 恒 False ② controller-info 的 supported_settings 没报 Privacy 位 / 修复提交 8004084 + 2544b12（**仍进行中**）

- **根因（两个「门」）**:auto-pts 的所有私有地址用例（GAP/PRIV/CONN/BV-10/11、GAP/DISC/RPA、GAP/BROB/BCST/BV-03/05）开头都有 `if not stack.gap.iut_has_privacy(): return False`。而 `iut_has_privacy()` 读的是 **current_settings 的 "Privacy" 位 = bit 13**。我们的 `_handle_op_1d`(SET_PRIVACY) 只把值存进 `self._privacy`、**返回空 body** → 位永远不置 → WID handler 直接 `return False` → Cancel → INDCSV。同时 `READ_CONTROLLER_INFO` 的 **supported_settings 也没报 Privacy 位**。
- **修法**:SET_PRIVACY 走 `_set_settings_bit` 返回位图（bit 13）+ 驱动 PrivacyManager；supported_settings 加 bit 13。
- **同时实装（2544b12）**:`PrivacyManager` 补全——`generate_nrpa()`（46 随机位、最高两位置 00）、`generate_rpa(irk)`（`hash=ah(IRK,prand) || prand`，prand 最高两位 01）、`set_random_address`（LE_Set_Random_Address + status 检查）、`set_address_resolution`、`add_to_resolving_list`；`AdvertisingConfig.own_address_type`（0x01=random），BTP advertise 路径在 privacy 打开后改用随机地址。
- **附带查出并修掉自己引入的 bug**:上一版 PADV 提交里我把 `PADV_START` 的 settings 位设成 **bit 13**，注释写的是「periodic advertising」——但 auto-pts **根本没有周期广播 settings 位**，bit 13 是 **Privacy**。等于每次跑 PADV 都会让 auto-pts 以为隐私打开了。已改为不动位图，并留了回归测试（`test_padv_start_leaves_settings_bitmap_untouched`）。**教训：GAP settings 位序号必须去 auto-pts `defs.py` 的 `GAP_SETTINGS_*` 查，别照 settings 名字表猜顺序**（Advertising=10 与 Privacy=13 之间还夹着 SC/Debug Keys）。
- **现状**:位图修好后用例**确实往下走了**（不再被短路），但 RPA 用例仍 INDCSV——RPA **必须用对端能解析的 IRK**，而 IRK 目前没有从 IXIT/配对结果接进 `PrivacyManager`（`stack._iut_privacy_irk` 只是预留钩子，无人写）。BCST/BV-04 的 NRPA 路径不需要 IRK，是下一个最可能翻的用例。
- **下一步**:① NRPA 轮换（按 `TSPX_iut_private_address_interval` 定时重设随机地址，BCST/BV-04 明确要求「TGAP(private_addr_int) 后地址要变」）；② 把 IRK 从 ixit/配对结果接进 PrivacyManager 再攻 RPA 类；③ GAP/PRIV 用例本身耗时长（带 TGAP 定时器），跑一次动辄 >4 分钟，判 verdict 要有耐心。

### Q: PTS GAP/BROB/BCST/BV-04（广播用 NRPA 且要按 TGAP 轮换）持续 FAIL → A: ① PTS 把 `own_addr_type` 放在 START_ADVERTISING body **尾部**、我们丢掉了 ② `LE_Set_Random_Address` 在**广播使能中/地址解析开启时**回 0x0C，必须在停广播 + 关解析的窗口里改地址 / 修复提交 52e0ef6 + f784f0e + 8f4a834

- **现象**:BCST/BV-04（非可解析私有地址广播）稳定 FAIL。WID 79 描述「send non-connectable undirected advertising report with **non-resolvable private address**」。
- **根因 1（丢掉 own_addr_type）**:auto-pts 的 `gap_start_advertising(ad, sd, duration, own_addr_type)` 把 `own_addr_type` 作为 **body 最后一个字节**发出去（`OwnAddrType`: 0=identity / 1=resolvable / 2=non-resolvable）。我们的 `_handle_op_0a` 注释写着「duration + own_addr_type tail present but **not used** in P.6」直接丢弃 → 永远用公开地址广播。WID 79/80 正是靠这个字段点单要私有地址的。
- **根因 2（0x0C × 2）**:即使传了地址，`LE_Set_Random_Address` 也回 **0x0C (Command Disallowed)**，两种触发条件**都要处理**:
  1. **地址解析已开启时**不许设随机地址 → 设地址前先 `LE_Set_Address_Resolution_Enable(0)`，设完再恢复。不这么做的话，**第二次**编程（下一个用例、或轮换循环）会静默失败并继续用旧地址。
  2. **广播使能中**不许设随机地址 → 轮换必须「**停广播 → 改地址 → 用原参数重开广播**」。`BLEAdvertiser` 因此记住上次 `start()` 的参数（`pause_for_address_change()` / `resume_after_address_change()`），`PrivacyManager.set_random_address` 在改地址窗口自动调用它们。**注意**：不是在轮换循环里显式调，而是在 `set_random_address` 内部——这样任何调用点（SET_PRIVACY、WID 79/80、轮换）都自动安全。
- **附带**:`TSPX_iut_private_address_interval` 我们**从没设过** → PTS 用 workspace 默认值（TGAP 的 15 分钟），BCST/BV-04 根本等不到地址变化。已钉成 `5000`（bluez 的取值），并以此为轮换周期。
- **关键认知**:① 「控制器 status≠0x00」这类回绝**必须打日志**——本次两个 0x0C 都是靠 `PrivacyManager: LE_Set_Random_Address rejected, status=0x0C` 才定位到的，之前一律是「用例 FAIL 但看不出为什么」；② **一条 HCI 命令可能有多个互不相关的 disallowed 条件**，修一个不代表够（先修解析、再修广播，两次都还是 0x0C）；③ auto-pts 的 BTP body **尾部字段**（duration/own_addr_type 之类「暂时用不上」的）最容易在移植时被丢掉，而它们往往是这类用例唯一的行为开关。
- **回归测试**:`tests/unit/ble/test_gap.py::test_set_random_address_disables_resolution_first` / `..._pauses_advertising_around_the_swap` / `..._while_not_advertising_skips_pause` / `test_private_address_rotates_on_the_configured_cadence`;`tests/unit/pts/btp/test_gap_service.py::test_start_advertising_forwards_own_address_type`。
- **真机**:`GAP/BROB/BCST/BV-04-C` **PASS**(2026-09-13)→ GAP 89→90，总 364/479 (76.0%)。
- **遗留（RPA 类仍未过）**:`GAP/BROB/BCST/BV-03-C` INDCSV、`GAP/PRIV/CONN/BV-10-C` FAIL。**已确认到位的三件事**：① WID 80 的 START_ADVERTISING body 尾部确实带 `own_addr_type=01`（raw: `…ff ff ff ff **01**`）；② 我们真的编程并**按 5s 轮换**了合法 RPA（`PrivacyManager: programmed private address bc2c3b13af55` → `rotated … 160d319ee665`，末字节高两位 = 01）；③ `TSPX_iut_device_IRK_...` PIXIT 已在 server log 确认下发（`set_pixit GAP TSPX_iut_device_IRK_... 0000…`，值取 zephyr 参考的全零；`PTS_IUT_IRK` 单一来源在 `pybluehost/pts/actions.py`，`auto_pts_project/…/gap.py` 发布）。 **✅ 后续（2026-10-31）：BV-10-C 已 PASS**——根因是地址解析开关与广播的先后顺序、以及 phase-3 断连的 identity↔RPA 寻址，详见本文档末尾同名 Q 条。
- **剩下一个未决点（已定性，非本簇专属）**:**配对前置没满足**。BCST/BV-03 的 WID 序列是 `91(connectable 广播) → 1002(Please enter Secure Id) → 77(disconnect) → 80(RPA 广播)`，其中 **WID 1002 的处理是 `hdl_wid_1002` 返回 `stack.gap.get_passkey()`** —— 也就是要走「IUT 显示 passkey、PTS 输入」的 SC 关联模型。case log 里 WID 1002 **没有 'Sending response'**，说明这个 passkey 从没被显示出来。这**正是 AGENTS.md 里那条已知遗留**（「KeyboardDisplay + SC 的 association model 没解析到 IUT display」，与 SCPK/SCOB 同族）——不是隐私本身的 bug。**判 RPA 类 verdict 前先确认 WID 1002 的 passkey 有没有走通**。
- **`ah` 字节序已按 spec 定案（提交 d29527b）**：Core Spec **Vol 3 Part H §2.2.2** 原文——`r' = padding || r`，**r 的最低有效字节成为 r' 的最低有效字节**（例：24-bit `0x423456` → `r' = 0x00000000000000000000000000423456`，即 **r 的最高有效字节在前**）；输出取 `e(k,r') mod 2^24`（最低 24 位）。而空口地址是**小端**。所以 `ah()` 收到的 prand 和它返回的 hash **都要相对 wire 形式翻转一次**——我们原来**两处都漏**（先前只补了输入那处仍然不过）。定点测试见 `tests/unit/ble/test_gap.py::test_ah_pads_the_prand_most_significant_octet_first` / `test_rpa_wire_order_matches_ah_convention`。**顺带修掉** `stack._load_bond_for_peer` 里把 `BDAddress.address`（显示序）喂给 `resolve_rpa`（要 on-air 序）的错——否则 RPA 重连根本匹配不上 bond。**经验：凡「谁是 MSB」的问题，去 Core Spec 原文查公式 + 例子（§2.2.x 都带数值例子），别靠试。**

### Q: PTS GAP/PADV 全簇（Periodic Advertising，10 例）——① 协议栈**完全没有**周期广播支持 ② 实装后事件仍永不到达，因为 **LE Event Mask 只开了 bit 0-4** → A: 实装 BTP GAP 0x22-0x29 + HCI 命令/事件全套；真正的拦路虎是 `LE_EVENT_MASK = 0x1F` 把周期广播整族事件挡在控制器里 / 提交 af511f5 + 17e2318 +（本 session）

- **背景**:`GAP/PADV/{PASE,PAM,PASM,PAST}` 共 10 例（GAP 里最大的一块未实现簇）。原先栈里**一行周期广播代码都没有**——没有 HCI 常量、没有 BTP opcode、没有 WID handler 能用的原语。**✅ 现已 10/10 全 PASS**（2026-09-16）——两个根因分两步解开：create_sync 子簇是下文的 LE Event Mask，PAST 子簇是**存在 extended advertising set 时 legacy initiator 被拒 0x0C**（见下面单独那条 PAST 条目，改用 `LE_Extended_Create_Connection (0x2043)`）。
  - **⚠️ 但那 10/10 绑定在特定固件上（2026-11-02 复核）**：换到当前的 BE200 之后 PADV 全簇不可跑——`scripts/_padv_cap_probe.py` 裸探测显示整段周期广播 OCF（`0x203E/203F/2040/2044/2045/2046/2059/205A/205C/205D`）**全部回 `0x01 Unknown HCI Command`**，10 个 PADV 用例的 IUT 日志逐条印证。关键证据：这颗 dongle 的 `Read_Local_Version` 是 `hci_rev=0x4455 / lmp_palver=13 / manufacturer=0x0002`，与当年跑通 PADV 的那批（`hci_rev=0x550D / lmp_palver=68 / manufacturer=0x020D`）**不是同一款固件**——同是 `8087:0036`，能力天差地别。矩阵里这 10 例已改 `blocked` 并在 notes 保留了「旧固件 PASS 是真的」这一事实。**教训：凡引用「某芯片/某型号 PASS 过」的能力结论，都要带上当时的 `hci_rev`/`lmp_palver`；同一 VID:PID 换批次 = 换固件，能力必须重新裸探测，不能沿用。**
- **已实装**:
  - `pybluehost/hci/constants.py`:LE_Set_Periodic_Advertising_Parameters/Data/Enable(0x203E/F/40)、Periodic_Advertising_Create_Sync/Terminate_Sync/Sync_Transfer(0x2044/46/49)、Set_Periodic_Advertising_Receive_Enable/Sync_Transfer_Parameters(0x2059/5A) + LE Meta 子事件 0x0F/10/11/19。
  - `pybluehost/ble/gap.py::PeriodicAdvertising`:configure/set_data/start/stop/create_sync/terminate_sync/set_receive_enable/set_sync_transfer_parameters/sync_transfer + `on_hci_event` 解析 sync-established/report/lost/transfer-received。
  - `pybluehost/pts/btp/opcodes.py` + `services/gap.py`:BTP opcode **0x22-0x29**（逐字节对齐 auto-pts client 的 pack 布局）+ 事件 **0x8D-0x90**（`gap_padv_*_ev_` 的解析格式，report 用 `<HBBBBB`+data）。
  - `IutActions.padv_*` 原语 + `stack.gap.periodic_advertising` facade + `pts_tester.py` 里 `wire_periodic_advertising()` 挂事件。
- **附带修掉的真 bug（重要，独立价值）**:`ExtendedAdvertiser.create_set` 只发 **5 字节**，而 LE_Set_Extended_Advertising_Parameters 是 **25 字节**（Core §7.8.53）——控制器直接拒。周期广播**必须**建立在 extended-PDU 的 advertising set 上（legacy set 上 configure 会被拒），所以这条不改 PADV 根本走不动。`ExtAdvertisingConfig` 已补全字段（properties/interval(3B)/channel_map/own+peer addr type/peer addr/filter policy/tx power/phys/SID 等），并有 25 字节布局的回归测试。
- **根因（本 session 定案，一条解释全部现象）**:`pybluehost/hci/controller.py::initialize()` 里 `LE_EVENT_MASK = b"\x1F\x00\x00\x00\x00\x00\x00\x00"`——**只置了 bit 0-4**。§7.8.1 原文:*"This command is used to control which LE events are generated by the HCI for the Host. If the bit in the LE_Event_Mask is set to a one, then the event associated with that bit will be enabled."* —— 位是 0 的事件**控制器根本不生成**，于是 bit 12(Extended Advertising Report)、bit 13/14/15(Periodic Advertising Sync Established/Report/Sync Lost)、bit 23(PA Sync Transfer Received)**全部被挡在控制器内部**。这**一条**同时解释了此前所有「诡异」现象:① `Create_Sync` 回 CommandStatus 0x00（命令确实被接受）② 之后 IUT log 里**零个 LE Meta 事件、零个广告报告**，100% duty 的 extended scan 也扫不到任何东西 ③ 之前据此怀疑「控制器/固件/RF 有问题」全是误判。修法:新增 `LEEventMaskBit(IntFlag)`（§7.8.1 全表，bit 0-28 带名字）+ `DEFAULT_LE_EVENT_MASK`（= bit {0,1,2,3,4,12,13,14,15,23} → `b"\x1F\xF0\x80\x00\x00\x00\x00\x00"`），`controller.py` 改用它。**真机取证**:改后 `HCI cmd 0x2001 params=1ff0800000000000` → extended adv report(0x0D) 立刻刷屏 → `LE Meta subevent 0x0E len=15 params=0040000000ee040783675c01780001`（**Sync Established**,status=0x00,SID=0,PHY=LE 1M,地址 = PTS LT `5C:67:83:07:04:EE`）→ `GAP/PADV/PASE/BV-01-C` **首跑 PASS**(26.9s)。
- **同时纠正的错误先验（上一 session 的误判）**:`LE_Periodic_Advertising_Create_Sync` 的 `Sync_Timeout` **不是建立超时**。§7.8.67 原文:*"The Sync_Timeout parameter specifies the maximum permitted time between successful receives. If this time is exceeded, synchronization is lost."* —— 它是**同步建立之后**的「两次成功接收之间的最大间隔」，控制器会一直重试到 `Create_Sync_Cancel` 为止（同节:*"This command may be issued whether or not scanning is enabled... While scanning is disabled, no attempt to synchronize will take place."*）。所以「5s 后什么都没有」**是预期行为**，不能据此推断控制器有 bug——当时整个「控制器静默」的排查方向就是这么走偏的。
- **关键认知**:① **`LE_EVENT_MASK` 是「事件的开关」，不是「事件的过滤器」**——位清零时事件**不存在**，命令照样成功。凡是「HCI 命令 status=0x00 但对应事件永远不来」，先回去数这个 mask，别先怀疑控制器/固件/射频。② **新事件族上线必须同步扩 mask**：`LEMetaSubEvent` 有 0x0D-0x18 的常量、`BLEAdvertiser`/`PeriodicAdvertising` 也写好了消费者，但没人记得放开 mask，于是整族静默——「消费者写好了」不等于「事件会来」。③ **不变式:LE Event Mask 的 bit *n* ↔ LE Meta 子事件码 *n + 1***（bit 12↔0x0D、13↔0x0E、14↔0x0F、15↔0x10、23↔0x18），两张表错开一位，手工维护极易错，已用 `test_le_event_mask_bit_n_is_le_meta_subevent_n_plus_1` 钉住。④ 这一次是**全新子系统**，不是「修 bug」——BTP/HCI 两层的线格式必须逐字节对齐 auto-pts client packer（`gap_padv_configure` 是 `BHK` 而 create_sync 是 `B6sBHHB`，各不相同）；⑤ **extended advertising 是周期广播的前置**，检查顺序是「set 建了没 → 25 字节对不对 → ext adv enable 了没 → periodic configure/enable → **event mask 开了没**」。
- **回归测试**:`tests/unit/hci/test_constants.py::test_default_le_event_mask_unmasks_the_periodic_advertising_family`（逐个断言 10 个必需位 + 线上字节 `1F F0 80 00 00 00 00 00`）、`test_default_le_event_mask_omits_the_events_we_cannot_answer`（bit 5 与 bit 9 必须**保持清零**，各有理由，见测试注释）、`test_le_event_mask_bit_n_is_le_meta_subevent_n_plus_1`；`tests/integration/test_hci_init.py::test_hci_init_programs_the_full_le_event_mask`（断言**实际发到线上的 8 字节**，而不是回读常量——回读常量在「命令被跳过/body 截断/顺序放错」时照样绿）。

### Q: PTS `GAP/PADV/PAST/BV-02-C` 恒 FAIL（其余 PADV 已过）——Set PAST 参数回 `0x0C Command Disallowed` → A: **扩展广播集与 legacy initiator 互斥**，必须改用 `LE_Extended_Create_Connection (0x2043)` / 修复提交（本 session）

- **现象**:`GAP/PADV/PAST/BV-02-C` 的 WID 序列是「建 extended advertising set → 设置 PAST 参数 → 发起连接」。前两条命令 `status=0x00`，第三条 `LE_Set_Periodic_Advertising_Sync_Transfer_Parameters (0x205C)` 回 **`0x0C Command Disallowed`**，而且**此后所有 PADV 用例都回 0x0C 直到 `HCI_Reset`**。上一条 AGENTS.md 记录把这个 0x0C 挂账成「需查控制器在什么状态下才允许这条命令」——**本 session 用一组 A/B 探针把「状态」问出来了**。
- **探针设计（可复用）**：写一个脚本，固定「先建 extended advertising set 并 enable」，然后分别用 **legacy `LE_Create_Connection (0x200D)`** 和 **extended `LE_Extended_Create_Connection (0x2043)`** 两种 initiator 各跑一遍同一段 PAST 序列，打印每条命令的 status：
  ```
  initiator=0x200D : 0x205C -> 0x0C   0x205D -> 0x0C   ... 共 5 条 0x0C，随后 0x42
  initiator=0x2043 : 0x205C -> 0x00   0x205D -> 0x00   ... 全 0x00，连接建立
  ```
  **一行结论**：只要**存在** extended advertising set，legacy `0x200D` 就被拒 `0x0C`，而 `0x2043` 被接受并能建立连接。所以这不是「PAST 参数命令的状态问题」，是**我们自己的 initiator 选错了命令**。
- **根因（Core Vol 4 Part E）**：`LE_Create_Connection` 与 extended advertising set **互斥**——§7.8.53 明确 *"the Controller shall not be able to use the legacy advertising commands"* 之类约束，实测表现为 `0x0C`。而 `LE_Extended_Create_Connection` 没有这条互斥（它就是给「同时广播+发起」的场景用的）。**PAST 用例恰恰要求 IUT 一边维持 advertising set（供 PAST 关联）一边发起连接**，所以只有 0x2043 能过。
- **修法**：`pybluehost/ble/gap.py::BLEConnectionManager.connect` **优先走 0x2043、能力不足再回落 0x200D**：
  - 新增常量 `HCI_LE_EXTENDED_CREATE_CONNECTION = make_opcode(OGF.LE, 0x43)`；body **26 字节** `"<BBB6sBHHHHHHHH"` = Initiator_Filter_Policy(1) Own_Address_Type(1) Peer_Address_Type(1) Peer_Address(6) Initiating_PHYs(1, `0x01`=LE 1M) + **八个 u16**（Scan_Interval/Scan_Window/Conn_Interval_Min/Conn_Interval_Max/Latency/Supervision_Timeout/Min_CE/Max_CE）。别和 legacy 的 25 字节 `"<HHBB6sBHHHHHH"` 混——**两者字段顺序也不同**（legacy 是 scan 在前、filter policy 在后；extended 是 filter policy 在最前）。
  - **`0x2043` 必须能被能力门选中**:`SupportedCommands.has()` 对**未注册进 `_OPCODE_BIT_POSITIONS` 的 opcode 一律返回 False**，所以光加常量不够，还在 `hci/capabilities.py` 注册 `(38, 4)`（Supported_Commands octet 38 bit 4，BE200 实测该 octet 读 `0xFF`）。**否则门永远打不开、静默走 legacy、0x0C 照旧**——这是本次最容易漏的一环。
  - **legacy 回落是硬要求**：BT 4.0/4.1 控制器（CSR8510 一类）**不实现 0x2043**，`connect()` 必须在 `supported_commands` 缺该位时照旧发 0x200D——否则换回老 dongle 时**所有连接**都会失败（`connect` 是全栈唯一的发起连接入口）。
- **真机**:`PYBLUEHOST_HARVEST_WARMUP=GAP/CSUB/CSU/BV-01-C bash scripts/pts_harvest.sh GAP/PADV/PAST/BV-02-C` → **PASS**（原 FAIL）。随后整簇重收割，**`GAP/PADV` 10/10 全 PASS**：`PASE/BV-01..06`、`PAM/BV-01`、`PASM/BV-01`、`PAST/BV-01`、`PAST/BV-02`（2026-09-16）→ GAP 108→**118/144 (81.9%)**，总 **405/479 (84.6%)**。同批回归（`connect()` 是全栈唯一发起连接入口，扩展 initiator 影响所有连接）：`GAP/CONN/CPUP/BV-06-C`、`GAP/CSUB/CSU/BV-01-C`、`GATT/CL/GAR/BV-01-C` 全 **PASS**，无回归。**注意**：这条同时也把 AGENTS.md 早先「PADV/PAST 仍 INDCSV——命令已正确，卡在 `0x0C Command Disallowed`」的判词**推翻**：命令当时并不「正确」，是 initiator 选错命令导致后续参数命令全被连坐拒绝。
- **关键认知**:① **`0x0C Command Disallowed` 是「当前控制器状态不允许」，不是「命令不认识」**（那才是 `0x01`）。它能被**别的命令**打破——所以看到 0x0C 先问「我现在处于什么状态、谁把我推进去的」，而不是只盯着被拒的那条命令查。② **一条 HCI 命令的合法性可能依赖「哪条命令把它带进来的」**：同一个 PAST 参数命令在 legacy-connect 之后必拒、在 extended-connect 之后必过——排查这类问题要做 **A/B 探针**（只改一个自变量、打印每一步 status），比读 spec 猜状态机快得多。③ **能力位不注册 = 门恒假**：`_OPCODE_BIT_POSITIONS` 是「提问表」，忘了注册会让新特性**永远走不到**，且失败方式是完全静默的（回落路径正常工作，看不出异常）。
- **回归测试**:`tests/unit/ble/test_gap.py::test_connection_manager_connect_prefers_extended_initiator`（逐字节断言 26 字节 body：filter policy/own addr type/peer addr type/peer addr(小端)/PHYs=0x01/scan 96/48 与 24/40/0/500 六个 u16）、`test_connection_manager_connect_falls_back_without_extended_initiator`（`capabilities=set()` → 必须发 25 字节 legacy）、`tests/unit/test_capabilities_opcodes.py::test_le_extended_create_connection_sits_at_octet_38_bit_4`（**门必须能选中**，未注册则该测试直接 KeyError）。

### Q: Intel 网卡（BE200/AX2xx）偶发打不开——`RuntimeError: Intel: firmware too small (9 bytes, need at least 644)` → A: 固件 `glob` pattern 少了扩展名，选到了同目录的 `.ddc` 设备配置文件 / 修复提交（本 session）

- **现象**:同样是 BE200，有时能开、有时直接 `RuntimeError: Intel: firmware too small (9 bytes, need at least 644)`，dangle 从未打开。**不是硬件坏了**——同一个 dongle 换个环境就能起。
- **根因**:Intel 固件目录里**每个 `.sfi` 旁边都躺着一个同名的 `.ddc`**（device config，实测 `ibt-0040-0041.ddc` 只有 **9 字节**，而 `ibt-0040-0041.sfi` 有 720988 字节）。`transport/usb/base.py::_find_firmware` 选文件用 `sorted(search_dir.glob(pattern))[0]`——**按字典序取第一个**。而 `KNOWN_CHIPS` 里 Intel 的 `firmware_pattern` 原本写成 `"ibt-0040-*"`（**无扩展名**）→ 字典序里 `.ddc` < `.sfi` → 选中 9 字节的设备配置文件 → 大小校验直接抛错。`intel.py` 的 bootloader 回退路径同样把 pattern 缺省成 `"ibt-*"`，一个毛病。**这个 bug 依赖目录里有什么文件**，所以「同一颗 dongle 在别人机器上能跑」——别人的固件目录里可能只有 `.sfi`。
- **修法**:`KNOWN_CHIPS` 六个 Intel 条目的 pattern 全部补 `.sfi`（`ibt-20-*.sfi` / `ibt-0040-*.sfi` / `ibt-18-*.sfi` / `ibt-12-*.sfi`），`intel.py` 的缺省 pattern 同步改 `"ibt-*.sfi"`。注意 `_legacy_firmware_name`（按 hw_variant 拼精确文件名）本就会补 `.sfi`，且在版本信息可得时**先于** pattern 路径命中——**被咬的是 bootloader 回退那条路**。
- **关键认知**:凡「按 glob + sorted 取第一个」选文件，**pattern 必须收窄到唯一可接受的类型**——同目录里存在「同前缀、别的用途」的文件（设备配置、签名、校验和、`.txt`）是常态，字典序又恰好把它们排在前面。补扩展名是最小且自解释的修法。
- **回归测试**:`tests/unit/transport/test_intel_fw.py::test_intel_find_firmware_ignores_the_device_config_file`——**用真 `KNOWN_CHIPS` 里的 BE200 条目**建 transport，目录里同时放 9 字节 `.ddc` 和 644 字节 `.sfi`，断言选中的是 `.sfi`。用真条目是关键：把扩展名从芯片表里去掉，这个测试就会红。

### Q: PTS GAP/ADV（AD type）全系 FAIL/INDCSV——IUT 广播里只有 flags+name，没有目标 AD type → A: `stack.gap_init` 只传了 name，没传 appearance/svc_data/uri/svcs/manufacturer，ADV WID handler 取不到值 / 修复提交（本 session）

- **现象**：GAP/ADV/BV-01(Service UUID)/04(Manufacturer)/09(Service Solicitation)/10(Service Data)/11(Appearance)/17(URI)/19(LE Supp Features) 全 FAIL/INDCSV。这些是「IUT 广播里必须含指定 AD type」的用例。
- **根因**：每个 ADV 用例的 WID handler(`autopts/wid/gap.py`）在广播前往 `stack.gap.ad` 塞一个特定 AD type，值取自 `stack.gap.<attr>`——如 `hdl_wid_1040: ad[gap_appearance]=stack.gap.appearance`、`hdl_wid_1221: ad[uri]=stack.gap.uri`、`hdl_wid_35: ad[uuid16_some]=stack.gap.svcs`。这些 attr 由 `stack.gap_init(...)` 填充。**我们只调 `stack.gap_init(iut_device_name)`(光秃一个 name)** → `appearance/svc_data/uri/svcs/manufacturer_data/flags` 全 None → WID handler 要么 skip 要么塞空 → 广播只有 flags+name → PTS 扫不到目标 AD type。zephyr 是把一整套都传给 `gap_init`。
- **修复**:`pybluehost_iut/gap.py::test_cases` 复刻 zephyr 的字段集，`stack.gap_init(iut_device_name, manufacturer_data='ABCD', appearance='1111', svc_data='1111', flags='11', svcs='1111', uri=UriScheme.https+b'github.com/auto-pts', periodic_data=(0x08,"PADV_Tester"), le_supp_feat='FF')`。**一个改动解锁一整簇**(ADV 多例 + 潜在的 PADV)。`Gap.__init__` 默认只把 name→ad、manufacturer→sd，每个 case pre_conditions 重新 `gap_init` 重置 ad/sd，所以 BCST 等已过的用例不回归（实测 BCST/BV-01 仍 PASS)。
- **关键认知**:auto-pts 的很多「行为」其实是 **WID handler 读 `stack.gap`/model 的字段**拼出来的；参考 IUT 在 `gap_init`/`pre_conditions` 里把模型字段喂满，我们喂一半 → handler 拿到 None 就静默降级。碰到「某 AD type/某 feature 缺失」先看 `gap_init` 参数是不是比参考 IUT 少传了。
- **真机**:ADV/BV-01/04/11 改后首跑全 **PASS**(2026-08-27)。

### Q: PTS GATT/SR/GAS 全 7 例 FAIL——Service Changed/Database Hash/Client Supported Features/Robust Caching 全缺 → A: 已实装 Service Changed indication + CHANGE_DATABASE 基元（commit ebe5e2d);BV-01 真机还要 robust-caching「重连补发」才过，留作下一跳

- **现状（2026-08-27)**：已实装并通过单测的**基元**——① `GATTServer` 分开跟踪 CCCD indication 订阅（0x0002，原只处理 notification 0x0001);② `indicate()` 改走独立 indication bridge 发 `ATT_Handle_Value_Indication`(0x1D，原先错用 notification 0x1B);③ `indicate_service_changed(start,end)` 给已订阅连接推 affected range;④ BTP `CHANGE_DATABASE`(0x1e)handler 触发它（auto-pts `gatts_change_database(0,0,0x02)` = IUT 自选 range，用全 db)。
- **剩余 gap（按子用例）**:BV-01 的 auto-pts 实际流程是「连上→订 CCCD→**断连→改 db→重连→补发 indication**」(WID 96 no-op),**不是** TS 图 4.164 的纯连接内 change_database→indicate——所以要过 BV-01 得实装 **robust caching**：断连期间改 db 要标记 bonded client 为 change-unaware，重连时补发 Service Changed indication（或先回 `0x12 Database Out of Sync`)。BV-02 要 Database Hash(AES-CMAC 全 db)。BV-03/04 要 Client Supported Features(per-client instance)。BV-05/06/07 是 robust caching 主体。
- **⚠️ 测试难点**:GAS 是 peripheral 用例，**peripheral flaky connect** 频发（抓到「Timeout 10s waiting for is_connected」即 PTS 根本没连上）；判 protocol bug 前先重跑确认连上了。robust caching 还要可靠的跨连接 bond 持久化才能测。
- **结论（2026-08-27）**：基元已就位、方向正确，但 GAS 7 例是一个「robust caching + database hash + per-client state」的大块 feature，不是单点 bug，留作专门一跳。
- **完成（2026-09-17）**：robust-caching 簇落地——① CSF 已使能时写 RC=0 回 `Value Not Allowed(0x13)` 且值不变（609bbb6，BV-05 step 11 / BV-07 step 7）；② `ATT_Handle_Value_Confirmation(0x1E)` 经 mux 专属 hook 路由到 `GATTServer.on_confirmation()` 清 change-unaware（609bbb6，BV-06 step 7，之前 0x1E 被路由到 client bearer 丢弃）；③ SC CCCD(`_indications_enabled`) 跨断连保留，`indicate_service_changed()` 对断连 client 记 `_service_changed_pending`，`on_connection_opened()` 在重连时补发（d201fe1，BV-01/BV-07 的 LT 重连后不发任何 ATT 请求、干等 indication，flush 必须由连接建立驱动，不能挂在首个 ATT 请求上）；④ BV-01 挂 `TestFunc(gap_wait_for_disconnection+gatts_change_database, post_wid=96)`（a2cb618，auto-pts 默认 hdl_wid_96 是 no-op，zephyr 参考正是用 post_wid=96 触发 db change，否则 db 永不变、indication 永不发）。
- **真机（2026-09-17）**：**6/7 PASS**（BV-01/03/04/05/06/07）——BV-07 最后一块是「DoS-once 标记必须 per-bearer 重置」（`remove_connection` 清 `synced_pending`，2d20a4a）：新连接的第一读要再拿一次 0x12，之前跨断连残留导致 BV-07 step 9 拿 value 而非 DoS；另「收到 SC indication 即 change-aware」（`on_connection_opened` flush 后清 change_unaware）+ `handle_request` 同步 flush（防 `create_task` 竞态，客户端重连后立刻读）。BV-02 仍 FAIL——hash 已逐字节自证与 Core 5.4 附录 B 一致，PTS 侧算的期望值对不上（见上文 821 行取证记录），需 btsnoop/PTS 视角。
- **经验**：① GAS 是 peripheral 多轮用例，peripheral flaky connect（单轮 ~50-70%）把 case 级成功率压得很低，判 protocol bug 前先重跑确认连上了；② 「LT 重连后不发请求干等事件」的用例（SC indication、bond_lost、passkey）都要求 IUT **由连接建立/状态变化主动推**，不能等对端来取；③ 每次 `kill_iut` force-kill 会留 WinUSB 残句柄 → 下一例 `USBAccessDeniedError`，多轮用例配 `pts_retry_cases.sh` 单例重跑比批次可靠。

### Q: PTS GAP/CSUB（Connection Subrating，2 例）——协议栈完全没有 subrating 支持 → A: 已实装 BTP `SUBRATE_REQUEST (0x2b)` + 事件 `SUBRATE_CHANGE (0x92)` + HCI `LE_Subrate_Request (0x207E)` / LE Meta 子事件 `0x23` / 修复提交（本 session）

- **背景**：`GAP/CSUB/CSR/BV-01-C`（IUT 当 **Peripheral**）与 `GAP/CSUB/CSU/BV-01-C`（IUT 当 **Central**），由 WID 450/451 驱动，两个 WID 都调 `btp.gap_subrate_request(...)` 并读 `stack.gap.conn_params.data`（latency/supervision_timeout）+ `stack.gap.subrate_min`(10)/`subrate_max`(20)/`continuation_number`(5)。auto-pts 里 **CSUB 没有注册在任何 `.py`**——我们的 `pybluehost_iut/gap.py::test_cases` 遍历 `pts.get_test_case_list('GAP')` 自动捞到，不需要改 `/tmp/auto-pts`。
- **关键认知 ①（一条命令覆盖两个角色）**：Core Vol 4 Part E **§7.8.124** 原文 —— `LE_Subrate_Request` "used by a **Central or a Peripheral**"。所以「Central 的 Subrate Update」和「Peripheral 的 Subrate Request」是**同一条 HCI 命令**，BTP 侧也只需**一个 opcode**。**别按角色拆两个 handler**——`LE_Set_Default_Subrate (0x7D)` 才是 Central-only 且只影响**未来**连接，两个 CSR/CSU 用例都不用它。
- **关键认知 ②（事件必须带对端地址）**：auto-pts 的 `gap_subrate_change_ev_` 解 `'<B6sBHHHHH'`（18 字节）后会 `le_bytes_to_hex_str(_addr)` 再和 `pts_addr_get()` 比对，**不等就 `BTPError("Received data mismatch")`**。即地址必须是**对端(PTS)的**、且是 **HCI 小端序**（同 DEVICE_CONNECTED/DEVICE_FOUND 那条字节序纪律）。`pts_tester.py` 用 `_conn_peers[handle]` 反查对端，天然满足。
- **HCI 线格式**：命令 body = `Connection_Handle(2) + Subrate_Min(2) + Subrate_Max(2) + Max_Latency(2) + Continuation_Number(2) + Supervision_Timeout(2)`（全 u16 LE，共 12 字节）；事件 body（去掉 subevent code）= `Status(1) + Connection_Handle(2) + Subrate_Factor(2) + Peripheral_Latency(2) + Continuation_Number(2) + Supervision_Timeout(2)` = **11 字节**。事件里报的 `Subrate_Factor` 是**控制器实际选的值**（≤ 请求的 Subrate_Max），不是请求值。
- **全链路接线**（六段，缺一段就卡死）：`BLEConnectionManager.subrate_request()`（`ble/gap.py`）→ `IutActions.subrate_request(addr_bytes, params)`（按 peer 解析 LE handle；无连接抛 ValueError→BTP FAILED）→ `GapService._handle_op_2b`（拆 17 字节 body：`addr_type(1)+addr(6)+5×u16`）→ `Stack._handle_subrate_change`（解析 LE Meta 0x23 并 fan-out）→ `pts_tester._on_subrate_change`（handle→peer 映射）→ `GapService.on_subrate_change`（发 BTP 0x92）。
- **等价的既有范式**：CSUB 和 CPUP（连接参数更新）是同一形状——**IUT 发命令、控制器异步回事件、BTP 事件才是 auto-pts 判定的依据**。碰到新簇先找同形状的已过簇抄接线，比从头读 TS 快。
- **回归测试**：`tests/unit/pts/test_actions_subrate.py`（14 例：HCI 0x207E 的 body 字节、handle 解析/未知 peer 抛错/忽略 classic/短 params、`_handle_op_2b` 转发与两种失败路径、Stack 解析 0x23 并忽略别的子事件与截断体、BTP 0x92 事件的 `<B6sBHHHHH` 布局与小端地址）。

### Q: PTS GAP/CSUB 实装完仍全 FAIL——`LE_Subrate_Request` 本地校验 `status=0x00`、LL 规程却永不完成、LE Subrate Change 事件从不来 → A: LE FeatureSet **bit 38 是 Host-owned**，Host 不发 `LE_Set_Host_Feature` 声明它，空口上就等于「本机 Host 不支持 Connection Subrating」，对端按 spec 拒绝整个规程 / 修复提交（本 session）

- **现象**：上一条把 CSUB 全链路接好后，两个用例仍是 FAIL（~40s，不是 time_guard 超时）。IUT log 显示 `LE_Subrate_Request handle=0x0800 min=10 max=20 latency=0 cont=5 timeout=500 -> status=0x00`——**命令被控制器接受了**（那个 `status` 只是 Command Status），然后**什么都没有**：没有 LE Subrate Change 事件，所以 BTP 0x92 永不发。看上去像「控制器不支持 subrating」，但 BE200 **支持**（`LE_Set_Default_Subrate`/`LE_Subrate_Request` 都认）。
- **根因（spec 链）**：LE FeatureSet 的 bit 0..63 是**空口 Feature Exchange 交换的那一份**，其中有些位由 **Host** 拥有、控制器自己设不了。**bit 38 = Connection Subrating (Host Support)** 就是其中之一。
  1. **Vol 6 Part B §5.1.19**：Central "shall not initiate this procedure until it has performed a Feature Exchange procedure to determine that the **Connection Subrating (Host Support) bit is set in the Peripheral's FeatureSet**"；
  2. **§5.1.20**：Central 侧 Host 未置位时，**Central 的 Link Layer 必须拒绝该请求**；
  3. **§7.8.124**：Central 的 `LE_Subrate_Request` 在对端 bit 38 为空时返回 **0x1A Unsupported Remote Feature**。
  所以我们的空口 FeatureSet 告诉对端「Host 不支持 subrating」→ 对端**合法地**不跑规程。而 HCI 命令本身的参数校验是本地的、过得去 → `status=0x00`。**两个症状（status=0 成功 + 事件永不来）由此一次性解释完**，不需要怀疑控制器能力。
- **实测确认（两颗 BE200 都测过，改之前）**：`LE features = fff9017fae000000` → bit 37 **SET**（控制器自有的 Connection Subrating 能力位）、**bit 38 clear**。逐个试置：`Set_Host_Feature(37,1)` → **0x11**（不是 Host 拥有的位）、`Set_Host_Feature(38,1)` → **0x00**，再读 features 变 **`fff9017fee000000`**（byte 4 `0xae → 0xee`，bit 6 of byte 4 = bit 38）。**「哪一位是 Host 拥有的」用 `Set_Host_Feature` 的返回码直接问控制器**，比翻 spec 表快且不会错。
- **HCI 命令**：`LE_Set_Host_Feature` = OCF **0x0074**（`make_opcode(OGF.LE, 0x74)`），参数 `Bit_Number(1) + Bit_Value(1)`，Command Complete 回单字节 status。两种「不是 bug 的失败」：**0x11** = 该位不是 Host 拥有 / 需要控制器不具备的特性；**0x0C Command Disallowed** = "the Controller has a connection to another device"——**所以它必须在 init 序列里、任何连接建立之前跑**。
- **修法**：`HCIController.set_host_feature(bit, enabled)`（**返回 status 而不抛**——0x11/0x0C 都是可预期的拒绝，由调用方决定多大声）+ `initialize()` 里在可选命令循环之后、BR/EDR extended features 之前加一步声明 bit 38。代码里 `HCI_LE_SET_HOST_FEATURE` / `LE_FEATURE_BIT_CONNECTION_SUBRATING_HOST_SUPPORT` 进 `hci/constants.py`。
- **关键认知 ①**：「HCI 命令 status=0 但空口行为不发生」有一类专门根因是 **Host 拥有的 FeatureSet 位没声明**——这些位**不走控制器**，控制器也无从替你设。碰到「命令认了、对端不理」先怀疑 **Host Feature**（`LE_Set_Host_Feature`）和 **Host Supported Features**（`HCI_Write_LE_Host_Supported`）这两个「Host 声明面」。
- **关键认知 ②**：`send_command` 对错误状态**从不抛异常**，它把事件原样返回——**调用方必须自己读 `event.return_parameters[0]`**。本次漏读让「控制器拒绝」伪装成「控制器接受、链路不出声」，白绕了一大圈。（`ble/gap.py` 里 `subrate_request` 已补上该状态的 DEBUG/WARNING 日志——**正是这行日志把 `status=0x00` 钉死，从而排除「控制器拒绝」这条错路**。）
- **回归测试**：`tests/unit/hci/test_set_host_feature.py`（5 例：body 字节 `bit+value`、`enabled=False` 发 0x00、0x01/0x0C/0x11 三种拒绝**返回而不抛**、`initialize()` 确实发过这条命令、控制器不认这条命令（VirtualController 回 UNKNOWN_COMMAND，模拟 5.2 以前）时 init 仍成功）。全套 hci/pts/ble 单元测试 exit=0。
- **真机**：`GAP/CSUB/CSR/BV-01-C` PASS(11.6s)、`GAP/CSUB/CSU/BV-01-C` PASS(9.3s)（2026-09-15）→ GAP 106→**108/144**，总 **395/479 (82.5%)**。
- **⚠️ 座架坑（本次浪费一轮）**：`pts_harvest.sh` 不读 `PYBLUEHOST_IUT_TRANSPORT`，spawn pts-tester 用的 transport 来自**autoptsclient 的 `--pybluehost-transport`**；而当时**有一个上一轮的 autoptsclient 还活着**（`-t usb:8087:0036#1`，即 **PTS dongle**），新 client 起来后两个 client 交替跑，头两个用例全 `FATAL ERROR: IUT (pts-tester) did not connect to BTP socket`。**判 FATAL 前先 `Get-CimInstance Win32_Process` 数一下 autoptsclient 是不是只有一个**（AGENTS.md 早有「勿并发两个 client」的告诫，这次是残留进程而不是我显式开的）。另：`usb:8087:0036#N` 的 N 随拔插/重启互换，**别硬编码**。
- **已修（本 session，同一个坑不再复发）**：新增 `scripts/pybluehost_pts_dongle.py`，按 **IUT 的 BD_ADDR** 现场解析两个角色（libusb occurrence ← 读地址；PTS dongle ← 由另一颗的 hub port 映射到 PnP 实例路径），输出 `IUT_TRANSPORT=` / `PTS_DONGLE=`。`pts_harvest.sh` 现在**先 `kill_iut` 再解析**（IUT 必须空闲才能开）、把 transport **export** 出去并在解析失败时**直接报错退出**；`pts_run_batch.sh` 在环境变量缺失时才自行解析、解析不到也**不再回退到硬编码**，而是报错退出。两处仍保留 `PYBLUEHOST_IUT_TRANSPORT` / `PYBLUEHOST_PTS_DONGLE` 覆盖（覆盖优先）。**别再往这两个脚本里写死角色**——写死过一次就够。

---

### Q: PTS GAP/SEC/AUT/BV-13/14（Insufficient Authentication，Central/Peripheral）无论如何都 INDCSV → A: **用例被 PTS 侧缺陷阻塞（SIG errata ES-28650）**，不是 IUT 问题；顺带把「bond 已覆盖 Security Request 时真正开始加密」补上 / 2026-09-16 定案

- **GAP.TS 的 Initial Condition**：BV-13/14 都要求「**IUT 与 Lower Tester 之间存在一个未认证的既有 bond**」，Procedure A step 2 是「**IUT 发起并完成链路加密**（用那个既有 LTK）」——注意 step 2 **不是**配对，配对要到 step 7（LT 发 MITM=1 的 Security Request 之后）才发生。所以这两例天然和别的 GAP case 不同：它**需要**一个跨 case 的 bond。
- **但 Lower Tester 从不建立那个 bond（这是判定的关键）**：
  - PTS 在每个 case 开头删掉自己的 host LTK——case log 里 `Log_sec - Delete Host LTK for the following BD address: 9453FF1E6AEE`（打两遍），PTS 的 LE bond 库 `le_security_info.txt` 是 **0 字节**。在 `Log_sec` 里 grep 只有 Delete、**0 个 Add**。
  - BV-13 的 MMI 脚本**只有一条**（WID 78「send an LE connect request」）——没有任何一步让 LT 建立或注入 LTK。
  - PTS 在断连时**丢弃 per-connection 密钥材料**：BV-12（能 PASS）里 PTS 用 `HCI_LE_LONG_TERM_KEY_REQUESTED_REPLY{ltk=0x88F5…F76D}` 应答，那串 **byte-reverse 后正是它在本 case 内刚算出来的 SC LTK**（`6DF7D641…BF588`）——不是持久化，是本 case 的产物。所以**即使把 BV-12 排在 BV-13 前面同一个 autoptsclient 会话里跑**，BV-13 拿到的也还是 `HCI_LONG_TERM_KEY_REQUESTED_NEGATIVE_REPLY`。
- **因此 IUT 做对了反而被判 INDCSV**：我们正确地用既有 bond 恢复加密 → PTS 的控制器向它的 host 要 LTK → host 没有 → `NEGATIVE_REPLY` → `Security Failed. result = 8` → INDCSV。**空口逐条**（`/tmp/bv13_oneshot_trace.txt`）：`MMI_78` → `Connection established` → `Start Security` → `HCI_LE_LONG_TERM_KEY_REQUESTED_EVENT{rand=0,ediv=0}` → `HCI_LONG_TERM_KEY_REQUESTED_NEGATIVE_REPLY` → `Security Failed. result = 8` → `INDCSV`。
- **三条独立佐证**：① auto-pts 自己把这两例登记为 **errata**——`errata/common.yaml:35-36` = `GAP/SEC/AUT/BV-13-C: ES-28650` / `BV-14-C: ES-28650`（SIG 的 errata 工单号；该文件只被 `bot/common.py` + `common_features/report.py` 用来标注报告，**不会跳过用例**）；② bluez 参考 IUT 用**和所有其它 GAP case 一样的**前置注册这两例（`ptsprojects/bluez/gap.py:249,253`，含 `btp.gap_unpair`）——即参考实现也**没有**为它们造 bond；③ zephyr 的 per-case `TSPX_delete_ltk=TRUE` 同样把 PTS 侧 LTK 删掉。
- **做法（已实施）**：`auto_pts_project/pybluehost_iut/gap.py` **不给这两例开特例**——曾经写过一个 `pre_conditions_keep_bond`（跳过 `gap_unpair`）版本，实测**同样 INDCSV**（bond 在 IUT 侧不等于 LT 侧有），而且偏离参考实现。改回 bluez parity，并在 `docs/pts/results/matrix/gap.yaml` 里记为 **`blocked`**（带 errata 说明）。回归测试 `test_profile_modules.py::test_gap_every_case_drops_the_previous_pts_bond` 锁住「这三例（BV-12/13/14）配置完全一致、都 drop 掉 PTS bond」，防止以后有人再"修"成特例。
- **经验（可复用）**：① 判「IUT 行为对不对」前先看 **auto-pts 的 `errata/common.yaml`**——它列的是参考实现也过不了的用例，省一整轮排查；② 「用例的 Initial Condition 需要某个既有状态」时，先确认 **LT 到底会不会造那个状态**（数 MMI 条数最快），别假定它存在；③ PTS 的「PASS 例子里对端回复了密钥」**不代表它持久化了密钥**——把回复值拿去和同一 case 里它自己算出来的值比对，能区分「本 case 产物」和「跨 case 状态」。
- **顺带补上的真实缺陷（保留，独立价值）**：`_bond_covers` 判定「既有 bond 已覆盖这次 Security Request」时原本只是 `return`（不重配）——**链路仍然没加密**，LT 后续的受保护访问拿不到 Insufficient-Authentication 响应。按 GAP.TS 的语义（Security Request = 「请**加密**链路」），补了 `SMPManager.set_bond_resume_handler` → `Stack._resume_encryption_with_bond`（发 `HCI_LE_Start_Encryption_Command`，用 bond 的 rand/ediv/ltk），并把 SC bond 也纳入（`_auto_encrypt_on_reconnect` 里的 SC 豁免是因为**我们**在连接时抢跑会和对方的新配对打架，而 Security Request 是对方主动要求的，没有这个竞态）。另修：SMP 终态（BONDED/FAILED）收到迟到的 `PAIRING_FAILED_RX`/`DISCONNECTED`/`TIMEOUT` 会抛 `InvalidTransitionError`——对端在 bond 已落盘后发 Pairing Failed 收尾是**常规**行为（不止 BV-13），补了吸收这些事件的转移。回归测试：`test_smp_security_request.py::test_security_request_met_by_existing_bond_does_not_repair`（断言加密真的发出）、`test_stack_auto_encrypt.py::test_security_request_resumes_encryption_from_{a_legacy,an_sc}_bond` / `..._does_not_re_encrypt_an_encrypted_link`。

### Q: PTS GAP/SEC/AUT 断连后 bond 簇（BV-19..28）整簇 INDCSV → A: 三个独立根因——① PIXIT=FALSE 分支会插断连而 PTS 在断连时丢自己的密钥材料 ② BV-22 的 Bond Lost 触发点（SecReq→PairingReq）没实装 ③ 配对在飞时 peripheral 的 pair() 又插了一条 Security Request / 修复提交（本 session，2026-10-28；BV-22 PASS；PIXIT=TRUE 批 BV-25 PASS）

- **背景**：BV-20..28 全是「bond 先存在 → 服务请求被拒/加密失败 → 重新加密或重新配对」族。BE200 新座架上 BV-19 PASS，BV-22/24/25/27/28 全 INDCSV，BV-21 早前已 PASS（Key Missing→Bond Lost 路径，0x06 触发）。- **根因 ①（BV-24/25/27/28，决定性）**：workspace 的 `TSPX_encryption_before_service_request=FALSE`（zephyr workspace 默认）会让 LT 脚本走「前导配对 → **断连** → 重连 → LT 发 Security Request」分支，而 **PTS 只在配对发生的那条连接内保留密钥材料**——断连即丢（与 ES-28650 同一行为）。于是 phase-2 的 Security Request 对**任何 IUT** 都注定 Key Missing；我们补的「Key Missing+central→重新配对」（spec BV-27 step 8 要求的行为）也会被 LT 无视（重配不在它的脚本里）。**mynewt 给这四例全部注册 `PIXIT=TRUE`**——TRUE 分支整条规程跑在**一条连接**上（配对同链路，LT host 还有 LTK），Security Request 用新 bond 就能答上。修法：`pybluehost_iut/gap.py` 加 per-case 注册 `aut_central_extra`（PIXIT TRUE + `gap_set_pair_user_interaction(False)`——后者是 **client 模型 flag** 不是 BTP 命令，门控 WID 267「支持用户交互配对吗」答 No；BV-27/28 另加 `gap_set_mitm_on`，新鲜配对须 authenticated）。**zephyr 不注册这四例，mynewt 的注册就是唯一参考；workspace PIXIT 是 case 级行为开关，别只盯 IUT 代码。**
- **根因 ②（BV-22 的判定路径）**：BV-22 全部判定 = WID 143 等 `bond_lost_ev_data`（BTP 0x8B）。触发点是 MSC 的「Security Request → **Pairing Request** → Bond Lost」：bonded peripheral 发出 SecReq 后，**central 用 Pairing Request 回答（而不是加密）就是丢 bond 的信号**——有 bond 的 central 会直接加密（Core Vol 3 Part H §3.6.1）。原代码只有 0x06（Key Missing）会发 bond-lost，这条信号路径整个缺失。修法：`SMPManager._secreq_sent` 记录发过 SecReq 的 handle（`unbind_channel` 清除）；responder 收到 Pairing Request 时若 mark 在且有存储 bond → `_emit_bond_lost` → Stack 桥进 `on_bond_lost`（清 bond + BTP 0x8B，**不再 spawn re-pair**——responder 配对已经在飞）。
- **根因 ③（bond-lost 之后的重配对被打断）**：WID 143 过了之后 client 会调 `gap_pair`（WID 108），而此时 **LT 自己发起的配对还在飞**（它的 Pairing Request 刚到）；peripheral 的 `pair()` 原本无条件再发一条 Security Request → LT 视为协议违例回 Pairing Failed 0x08/0x05。修法：`request_security_and_wait` 先查 `_contexts`——已有**非 FAILED** 的在飞上下文就**不发 SecReq、直接等它完成**。
- **配套（WID 143 的 5s 窗口）**：上游 `hdl_wid_143` 只等 5s，而这条链要求 LT 在窗口内**重连**（本座架 peripheral 连接 flaky，重连经常 >5s）→ 事件永远进不了窗口。override `hdl_wid_143` 把窗口拉到 20s（`btp.gap_wait_for_lost_bond(20)`，纯 client 侧等待，语义不变）。
- **空口验证（BV-22 attempt 2 全链）**：phase1 配对→0x13 断；phase2 重连→我方 SecReq→LT 回 Pairing Request→`Bond lost (peer answered our Security Request with a Pairing Request)`→0x8B 到 auto-pts→**新鲜配对完成**（`SMP paired ... ltk_stored=YES`）→0x13→**PASS**。
- **经验**：① 「Initial Condition 要求既有 bond」的用例，先数它**到底断不断连**——PIXIT=FALSE 的脚本分支插断连、而 PTS 密钥材料随连接生死，整个用例就数学上不可过；换 PIXIT=TRUE 分支比在 IUT 侧想任何办法都有效。② 对「IUT 该上报某事件」类判定（bond-lost/passkey/pairing-failed），先确认**触发点**在不在——BV-22 的触发点（SecReq→PairingReq）和 BV-21 的（0x06）是不同信号，缺一个判定就是永远 Cancel。③ 「BTP 命令到达时配对已经在飞」要查上下文而不是再发请求——双重发起（SecReq 打断 LT 的配对）在 LT 看来是违例。④ auto-pts 的 per-case 注册（PIXIT/mitm/io_cap/`gap_set_pair_user_interaction`）是 IUT 模块的职责，**注册差异就是行为差异**——排查 SEC/AUT 簇先 diff 一遍 mynewt 的 per-case 块。
- **✅ 后续（2026-10-28 PIXIT=TRUE 真机批，IUT=AX201）**：
  - **BV-25 首次 PASS**（308s 全程）。决定性的一步是 `gap_set_pair_user_interaction(False)` 注册让 WID 267（「IUT 支持用户交互配对吗」）答 **No**——LT 据此走免交互分支自主跑完配对/加密/读（case log 里 phase-2 之后 5 分钟 IUT 侧零 SMP 事件，全是 LT 在空口自驱）。**per-case 注册的两行配置，顶得上几百行协议栈代码。**
  - **BV-24 是另一个规程（别和 25/27/28 混）**：TS p248 原文——BV-24（Insufficient Encryption, Central）的 phase-2 **没有重配对步骤**：LT(peripheral) 发 SecReq → IUT 用 bond **恢复加密必须成功** → LT 重读 → PASS。但用例自己的 WID 77 断连照样让 **LT 丢掉它的 LTK**（同 ① 的 PTS 行为），恢复加密注定失败。修法：`_resume_encryption_with_bond` 加**结果监视器**——恢复失败（**任意**非零 Encryption_Change status；本座架发 **0x08 LL 超时**，不是 TS 叙事里的 0x06）或**静默卡死**（LT 对 LL_START_ENC_REQ 不应答，窗口超时链路还活着）→ 立刻用 SecReq 的 auth_req 发起**带 MITM 的新鲜配对**（`_repair_pairing(handle, auth_req)` → `start_initiator(peer_sec_req_auth_req=hint)`，Just-Works 重配过不了这族）。
  - **`start_initiator` 改为替换已完成上下文**：原来对任何既有 ctx 抛 `RuntimeError`——但 BV-25/27 的加密失败恰好落在**前导配对完成（ctx=BONDED）之后**，repair 直接炸。现在只在**非终态**（真正在飞）时抛，BONDED/FAILED 一律替换（SecReq 路径早就这么干）。**「修复动作可能落在配对刚完成的时刻」——终态 ctx 是资产不是障碍。**
  - **BV-19 首次 PASS（最简变体，全程无 resume）**：PIXIT=TRUE 后 LT 走「connect → IUT 读保护特征 → ErrRsp(0x05) → **IUT 自己发起配对**（legacy JW，auth=0x09，双方都无 MITM）→ STK 加密 → `ltk_stored=YES` → 重读成功」，WID 序列 78/112/227/112/44。之前怀疑的「LT 静默不应答杀链路」没有出现——那是 workspace 冷态（见「加密使能阶段 reason=8」条）混进来的形状，不是 BV-19 的固有签名。**判这类 INDCSV 前先把 LT 的实际分支跑出来看，别按 TS 叙事假设它一定走 resume。**
  - **BV-24 首次 PASS（attempt 2）**：完整链路终于落通——WID 78（0x3E 抖一次，重试连上）→ WID 1002（SecReq `bond=none` → SC passkey 配对 → 加密 0x00 → `ltk_stored=YES`）→ WID 77 断（reason=0x16，IUT 挂断）→ WID 78 重连 → SecReq `bond=yes covers=True` → **resume 加密成功（0x00 enabled=1）** → WID 144 重读 0x0003 **拿到值**（gate 从 bond stash 回落标记 authenticated——正是 gate bug 修的那条路径）→ LT 收尾断 0x13 → **PASS**。
  - **attempt 1 的 FAIL 是 LT 读竞态，不是协议错**：resume 加密**同样成功**，但 LT 在 `Encryption_Change` 到达**之前**就发了重读（`ATT_Read_Request 0x0003` 落在加密握手在飞时）→ 门按当下未加密状态拒绝 → LT 拿到错误后**放弃不再重试**，直接断链。attempt 2 的读落在加密完成之后 → 拿到值 → PASS。**同一 LT、同一密钥、同一 IUT 代码，成败只取决于 LT 自己的读时机**——又一个「LT 非确定性，重跑收割」的实证。（若将来想把竞态也吃掉：server 对「门会拒 + 加密在飞」的请求 hold 到加密完成再答，协议上合法——未实装，先记录。）
  - **BV-27 的 deterministic 形状（×6）与正解**：preamble 配对成功 + 加密 → LT 发 `Pairing Failed 0x08`（SMP abort）→ LT 主动断 0x13（**peer-initiated**，无 caller= 日志可证）→ 之后**静默**。TS Table 4.32 step 5：PIXIT=TRUE 时 IUT（Central）要在**自己重建的物理链路上**发起加密规程——即 LT 在等 IUT 重连，而此前栈里**没有任何机制**会做这件事（reconnect-and-repair 只在「resume 被拒」后触发，这里根本没有 resume）。修法三件套：① 断连 handler 区分「自己挂断 vs peer 掉线」——`BLEConnectionManager.disconnect`（所有 IUT 主动断的唯一咽喉）经 `on_local_disconnect` 回调把 handle 记进 `_self_initiated_disconnects`；**peer-initiated + central + 有 bond** → `_reconnect_bonded_peer`（预算沿用 `_resume_reconnects` 上限 2，`_load_bond_for_peer` 无 bond 不重连——GATT/CL 的多轮发现是 WID 驱动的，不归我们管）。② `_le_resume_intents`（peer 键）：自主重连的下一跳**必须**发起 resume，**即使 bond 是 SC**——step 5 就是「IUT 发起加密」，LT 随后故意弄失败它（step 6A）来逼出 7-9 的新鲜配对；SC 豁免（防 SM/SCOB 抢跑）只该管「被动重连」，intent 一到即消费、豁免绕过。③ **顺带修掉一个潜伏 bug**：断连 handler 里两个重连分支读 `_le_conn_roles.get(...)` 都在 `pop` **之后**——role 检查恒真（默认值 0x00=central），peripheral 的 resume 被拒也会错误地触发 central 重连；改为 pop 前先捕获 role。
  - **BV-27 定案（2026-10-28，IUT 侧已穷尽）**：重连机制上线后 3/3 仍 INDCSV，但**重连本身工作正常**（断连后 ~1s 内 `LE_Create_Connection` 发出、命令被接受）。LT 侧的事实链：配对**完整成功**（密钥双向分发含 IRK/CSRK 逐字节核对）→ LT 发 `0508`（Pairing Failed **0x08 Pairing Not Supported**——在双方密钥分发**全部完成之后**， unsolicited、scripted）→ 断 0x13 → **从不重新广播**（我们的 initiator 扫描 10s 内 0 个 Connection Complete）→ 15s 后自判 INDCSV。per-case 注册与 mynewt 逐条一致（PIXIT TRUE + mitm_on + user_interaction False）。**结论：与 ECFC/BV-80 同类——LT 脚本行为，IUT 侧无更多信息可挖**；重连特性保留（spec 正确、unit-tested、门控严格：central+bonded+peer-initiated+预算），LT 若在别的 workspace/版本配合即可解锁。
  - **BV-28 PASS ×2**（BV-27 的 Peripheral 双胞胎，同 `aut_central_extra` 注册 + mitm_on，最简规程）。**BV-25 PASS 复现**（首跑即过，308s 批次的 flaky 已排除）。
  - **回归测试**：`tests/unit/test_stack_auto_encrypt.py` 新增 6 例（任意 status 触发带 hint 的 repair / 成功不 repair / 断链不 repair 且清 pending / 静默卡死超时 repair / watcher 与 0x06 分支不双发 / BONDED ctx 不阻塞 repair）；`tests/unit/ble/test_smp_security_request.py` 的 resume fake 签名加 `auth_req`。
- **✅ 后续 2（2026-10-28 第二轮，BV-24 专攻 + BV-27）**：
  - **BV-24 gate bug（resume 成功但 GATT 门没认，v2 收尾时发现）**：LT 重读 0x0003 得 **ErrRsp 0x05** → abort。根因：`_on_encryption_change` 成功分支从 SMP ctx 推导 `authenticated/key_size`，但 **bond-resume 加密不产生 SMP ctx**（SecReq → 直接 `LE_Start_Encryption` 用存量 LTK）→ ctx=None 时走默认 `(False, 16)` → 门标 unauthenticated → 对已认证的读回 0x05。修法：ctx 缺失时**回落 `_le_resume_bonds` 里 stash 的 bond**（authenticated/key_size 从 bond 取），事后照常清 stash。测试锁两条：authenticated bond → 门 `(True, 16)` + sec_level 3；`key_size=7` 的 bond → 门保持 `(False, 7)`（key-size 约束不丢）。
  - **resume 去重（双发是真实发生过的 bug）**：BV-24 重连时 `_auto_encrypt_on_reconnect`（有 bond 抢跑）和 LT SecReq 触发的 `_resume_encryption_with_bond` 会对**同一条链路**各发一次 `LE_Start_Encryption` 并各 arm 一个 watcher → 两个 watcher 都超时 → **双 repair**。修法：两条路径入口都加 `if handle in self._resume_watch or self._pairing_in_flight(handle): return`——**第一个 resume 尝试拥有该 handle**，后到者让路。
  - **拒绝后的 reconnect-and-repair（无链内修复窗口的正解）**：本座架 LT「拒绝恢复」= Encryption_Change **0x08 + 数秒内断链**——repair-pairing 需要链路活着，链内 repair **永远来不及**。修法三层：① 失败分支只记 `_le_encryption_failures[handle]`（**stash 不 pop**，留给断连 handler 判定）；② 断连 handler 发现「resume stash 在 + 我们是 central + auto_encrypt 配置开」→ `_reconnect_and_repair(peer, hint)`：置 `_le_repair_pending[peer]`、`connect_gatt` 重连，`_auto_encrypt_on_reconnect` 顶部读到 repair-pending 就**不再 resume**，直接带 SecReq hint 的新鲜配对；③ 每 peer 上限 2 次防死循环。watcher 若发现链路已随失败死亡则不插手（断连 handler 拥有后续）。
  - **关键认知（BV-24 的残余不可控性）**：resume 成败是 **LT 非确定性**——两阶段 LTK 字节一致（日志核对）仍出现 v2 连续 2 次 resume 成功、v3 之后连续拒绝的分裂；且 LT 拒绝后必然杀链，IUT 无从区分「密钥错」和「LT 想耍赖」。BV-24 verdict 天然 ~50/50，**重跑收割是正路**，别为单次失败改协议。另注意区分两种 0x08 死法：**preamble 配对后的首次加密**就 0x08（SecReq `bond=none`）= PTS.exe 冷态（重跑），**phase-2 resume** 的 0x08 = LT 拒绝（本条机制处理）。
  - **回归测试（第二轮）**：`tests/unit/test_stack_auto_encrypt.py` 新增 gate 回落 2 例（authenticated bond → 门 `(True,16)`+sec_level 3 / `key_size=7` bond → `(False,7)`）+ stash 生命周期（失败**保留**、断连清、成功清）+ SC/legacy resume（`test_security_request_resumes_encryption_from_*`）+ 双发去重 + 拒绝重连修复（`test_rejected_resume_reconnects_and_pairs_afresh`）+ 每 peer 上限 + **自主重连四件套**（**已废弃的回归测试（随 2026-11-04 删除该重连机制一并移除）**：`test_central_peer_drop_of_bonded_link_reconnects_with_intent`、`test_connection_manager_disconnect_marks_own_initiation`、`test_resume_intent_lets_an_sc_bond_resume_on_reconnect`。）；`tests/unit/ble/test_smp_security_request.py` 的 resume fake 加 `auth_req`。

### Q: PTS GAP/SEC/SEM/BV-45（加密失败后 Re-pair or stop，Central）BTP ERROR——LT 脚本化重连与 IUT 自主重连抢跑，楔死控制器唯一 initiator 槽 → A: 自主重连加「peer 主动 abort 配对」指纹门控（BV-27 要、BV-45 不要）/ 修复提交（本 session）

- **TS 定位（GAP.TS p118-120，Figure 4.64，本地 PDF 已有）**：BV-45 =「**已 bond** 的 Central 在连接的**加密阶段失败**时，IUT 要么 6A 向 UT 报连接失败、要么 6B 发起重新配对（SC=1 的新鲜 Pairing Request）后完成」。auto-pts 脚本流程：WID 78 connect → pair（**造 bond 的 preamble**，非被测步骤）→ Secure Id → **WID 77 断连**（回到 Initial Condition 的 LL Standby）→ WID 78 重连 → resume 加密 → **LT 让加密失败**（MSC step 5）→ IUT 走 6A/6B。这与 bond 簇的 BV-27（断连后**等 IUT** 重连）是镜像场景——**同一个「断连」动作，两个用例对「谁来重连」的期望相反**。
- **根因（修前的 BTP ERROR）**：BV-27 家族的「peer 掉线自主重连」对 BV-45 **误触发**——它的 LT 断连后**自己脚本化**安排重连（WID 78 ~1.7s 后到达）。IUT 的自主 `LE_Create_Connection` 先占住控制器**唯一的 initiator 槽**，LT 的 gap_connect 到达时 `0x200D` 全回 `0x0C Command Disallowed`，连坐拒掉 resolving-list 命令（0x2027/0x202D 也 0x0C——**initiating 状态下 resolving list 系列都被拒**）；cancel 后 Connection Complete status=0x02（Unknown Connection）。三条证据（0x0C 簇 + CC 0x02 + 「caller= 日志证明不是我们断的」）与 ECFC/BV-80 那条的方法论一致。
- **修法（指纹门控）**：`Stack._peer_aborted_pairings: set[handle]`——`smp.on_pairing_failed(cb)` 把**对端主动 abort 配对**的 handle 记进来（`_recv_peer_pairing_failed` 与 bond 后的 `_bonded_peer_pairing_failed` 都会 emit）；断连 handler 的自主重连分支加 `and peer_aborted_pairing` 才触发。**⚠️ 实现坑：marker 必须「捕获进局部变量 → 再 discard → 用局部判定」**——先 discard 后判定会把 marker 抹掉、重连永远不触发（单测当场抓住）。marker 是 **per-connection** 的：LE ConnComplete 与断连都要清。**BV-27 的 abort 特征**：双方密钥分发全部完成后 unsolicited Pairing Failed（0x0508）；**BV-45 的特征**：配对+加密干净完成（`Encryption_Change status=0x00`、`ltk_stored=YES`）→ 干净断连。两者都断连，只有前者该自主重连。
- **真机（2026-10-28/29）**：门控后楔死消失（BTP ERROR 不再由 0x0C 簇产生），但重连 create 扫 18s（3×6s 超时→cancel→CC 0x02）**0 条 Connection Complete**——LT 以 bonded 身份的广播行为变了，initiator 匹配不上（疑似与 ACEP/BV-03 的 directed-TargetA 同族；`PYBLUEHOST_DEBUG_CONNECT_SCAN=1` 空口窥视已加，待捕获）。另一次跑踩**独立的已知坑**：preamble 首次加密就 `Encryption_Change 0x08`（PTS.exe 冷态，重跑即过）——且 repair 分支标记原 ctx FAILED 后，**op-0x11 的 pair() waiter 在 LT 秒杀链路、repair 的新配对无法完成前就抛 RuntimeError** → BTP ERROR → auto-pts 弃案。**「preamble 0x08 冷态」与「重连匹配」是两个独立故障，别混查；BTP ERROR 的败因要看当次 log 里死在哪一段。**
- **✅ 定案（2026-10-29，IUT 侧已穷尽，剩 PTS 侧两个独立故障模式）**：
  - **模式 ①：preamble 加密 `Encryption_Change status=0x08`（PTS.exe workspace 状态退化，非冷态）**。曾连续 6 次出现，而 90 秒前的暖机用例（BV-12）加密干净 PASS——「冷态」解释被推翻，是 **PTS.exe 连续跑配对用例后的 workspace 退化**。恢复 = 杀 PTS.exe + 重启 autoptsserver（`nohup python autoptsserver.py -S 65000 --dongle "USB_INTEL:Free:<实例>"`），重启后实测加密干净。**与「首个 case 冷启动」是同族不同因：冷态重跑即过，退化必须重启 server。**
  - **模式 ②：脚本化重连的 LT 死空气（preamble 干净时 6/6 确定）**。干净的 WID-77 断连后，LT **从不重新开广播**：IUT 3×6s initiator 扫描 0 条 Connection Complete，空口窥视（air-peek）2s 也是 "nothing on air"。唯一一次重连成功发生在**非干净死亡**（0x08 杀链）之后——**LT 只在意外死亡后重新武装广播，脚本化断连后不重开**。这是 LT 脚本行为，IUT 侧无更多信息可挖（与 ECFC/BV-80 同类）；要进展需 btsnoop 抓 PTS dongle 或对照参考 IUT。`gap_set_pair_user_interaction(False)` 的 BV-45 注册（对齐 mynewt）保留但**已证明与死空气无关**（BV-45 流程从不问 WID 267）。
  - **判别口诀**：BV-45 跑挂先看死在哪段——preamble 加密 0x08 = 模式①（重启 server）；WID 78 重连扫 18s 死空气 = 模式②（PTS 侧行为，重跑大概率仍挂，别改协议栈）。
- **回归测试**：`tests/unit/test_stack_auto_encrypt.py`——`test_central_peer_drop_of_bonded_link_reconnects_with_intent`（BV-27 形状：`_emit_pairing_failed` 后断连→`connect_gatt` 被调）、`test_peer_drop_after_a_clean_pairing_does_not_autoreconnect`（BV-45 形状：干净配对断连→`connect_gatt.assert_not_awaited()`）、`test_pairing_abort_marker_is_per_connection`（marker 随 ConnComplete/断连清）。

### Q: `BLEScanner` 用 legacy `LE_Set_Scan_Parameters` 后，PADV / 扩展广播命令一律回 `0x0C Command Disallowed` → A: **legacy ⇄ extended LE 广告/扫描家族是单向门，且对称，只有 `HCI_Reset` 能清**；扫描器整体迁到扩展家族（0x2041/0x2042）/ 修复提交（本 session）

- **现象**：BLEScanner（`ble/gap.py`）一直发 legacy 的 `LE_Set_Scan_Parameters`(0x200B) + `LE_Set_Scan_Enable`(0x200C)，而栈的其余部分（扩展广播者、扩展发起者、周期广播）全部依赖 **extended** 家族。单独跑 PADV 用例能过，但只要同一个 pts-tester 进程里先扫过描，之后的扩展命令就全线 0x0C。
- **为什么 PADV 之前「看着是好的」**：`HCIController.initialize()` 的 **Step 1 是无条件 `HCI_Reset`**，所以每个 pts-tester 进程开局都是干净的。毒只在一个用例内部先扫（legacy）又要扩展家族时才发作——不是「偶尔」，是确定性。
- **硬件实测（BE200 8087:0036，逐条发命令读状态）**：
  ```
  [A] 13B phys=0x01                0x00
  [B] 8B  phys=0x01                0x00
  [C] 13B phys=0x03                0x11   <== REJECTED（不支持 Coded PHY 扫描）
  [D] ext params/enable            0x00 / 0x00
  [E] legacy 0x200B -> ext enable  0x0C   <== DISALLOWED（BLEScanner 原来走的就是这条）
  [F] ext params -> legacy 0x200B  0x0C   <== DISALLOWED（对称）
  [G] legacy -> ext params/enable  0x0C / 0x0C
  ```
  `_AdvReport` 布局与命令体长度都由这张表钉死；`LE_Set_Extended_Scan_Parameters` 采 **13 字节**（`Own_Address_Type + Scanning_Filter_Policy + Scanning_PHYs` 之后每个 PHY 一组 `Scan_Type/Interval/Window`），**`Scanning_PHYs=0x01`**——BE200 对 Coded 位（0x02/0x03）回 0x11。
- **另一条独立 bug（同一批修掉）**：扩展报告的 Event_Type 是**位域**（bit 0 connectable / bit 1 scannable / **bit 2 directed** / **bit 3 scan response** / bit 4 legacy PDU），而 legacy 报告是**序号**（0x00 ADV_IND … 0x04 SCAN_RSP）。原代码对两种布局都用 `event_type & 0x04` 判 scan response——在扩展布局里 **0x04 是 directed**：一条 legacy ADV_DIRECT_IND（0x15）会被误判成扫描响应，把一个设备的 EIR 劈成两半（`GAP/BROB/OBSV/BV-05/06` 正是靠合并后的单条 EIR 才判对）。现在 `_AdvReport` 带 `is_scan_response` 字段，两种布局各自解析，`_merge_report` 只读这个字段。
- **关键认知**：① 「扩展 vs legacy」这类互斥是**双向**的——只验证「A 之后再发 B」不够，要两个方向都测（本次 F 组就是反向）；② 这类「命令被拒」的探针要读**正确的状态字节偏移**——Command Complete 的 status 在 `[3]`、Command Status 在 `[0]`，读 `[2]` 会拿到 opcode 的高字节（所有 LE 命令都是 0x20，一个很像样的错答案）；③ 报告布局的位含义别靠「都是第 3 位吧」猜——去参考实现（BlueZ `hci.h` 的 `LE_EXT_ADV_SCAN_RSP 0x0008` / `ext_evt_type_to_legacy()`）抄。
- **回归测试**：`tests/unit/ble/test_gap.py::test_scanner_parses_the_extended_advertising_report` / `..._merges_the_extended_scan_response` / `..._does_not_mistake_directed_advertising_for_a_scan_response` / `test_extended_report_parser_bails_out_on_truncation` / `test_scanner_uses_the_configured_own_address_type`（自身地址类型必须落到 0x2041，`BV-05/06` 要求以私有地址观察）。

### Q: PTS GAP/DISC/LIMM/BV-04 FAIL（双胞胎 BV-03 却 PASS）→ A: **TGAP(lim_adv_timeout) 之后 IUT 仍在广播 Limited=1**——LIMM 的 Pass 判据明确要求超时后 LT 收不到任何带 Limited flag 的广播，我们从不停广播 / 修复提交（本 session，2026-10-28）

- **现象**：BV-04（Limited Discoverable + Undirected Connectable – LE Only）3 连 FAIL。取证先推翻了两个想当然：① case log 的 WID 序列是 **59→50**（不是猜的 49/76）；② upstream `hdl_wid_50` 其实调了 `gap_set_connectable`，我们的第二轮也确实是标准 ADV_IND——WID 行为没毛病。
- **WID 编号跨用例复用（重要）**：upstream `hdl_wid_59` 的 docstring 是「advertising report with **Service Data**」，但 LIMM/BV-04 里 MMI 发的 59 文本是「**limited discoverable mode** and send an advertising report」——handler 里顺带的 `gap_set_non_connectable()` 对 LIMM 是 upstream 固有行为，且测试正式观察窗在 WID 序列之后才开始，第一轮非连接广告**不脏判据**。**看 upstream handler 的 docstring 猜某用例的行为会跑偏，以 case log 里 `wid:` + `description:` 的配对为准。**
- **真正的根因（GAP.TS p166 原文）**：Pass 判据最后一条——*“**After TGAP(lim_adv_timeout)** from the time the IUT enters Limited Discoverable mode, the Lower Tester does not receive any advertising data from the IUT containing the Flags AD type with the Limited Discoverable Flag set to 1.”* 我们的 advertising 一旦 start 就永远不停，30.72s 后 LT 仍看到 Limited=1 → FAIL。workspace `TSPX_lim_adv_timeout` 默认 **30720 ms**（zephyr/bluez 参考 IUT 也显式设 30720）。BV-03 能过大概率是 LT 在窗口内连上了 IUT（连接自动停广播替我们收尾），BV-04 的 MSC 没有连接——**「LT 收不到 X」型判据要求 IUT 自己停止行为，不能指望用例结束或对端动作来收尾**。
- **修法**：BTP GapService 在 **SET_DISCOVERABLE(0x08) 值=2 的那一刻**（= 进入 Limited Discoverable mode；不是 start_advertising 时——WID 50 的 stop→set_limited→set_connectable→start 会重进 limited，deadline 必须锚定在首次进入）arm 一个 30.72s 的 asyncio 任务，到点 `actions.stop_advertising()` + 清 ADVERTISING settings 位 + **推 NEW_SETTINGS 事件**（BV-56 的 model-drift 家族：不推的话 auto-pts 的 `gap_start_advertising` 幂等短路会咬后续用例）。离开 limited mode 取消任务；显式 STOP 之后任务到点是 no-op（不二次 stop）。**已进入过一次后重复 set_limited 不 re-arm**（否则 deadline 被推出 3s，LT 在 (30.72, 33.7] 的窗口里又能看到 Limited=1）。
- **回归测试**：`tests/unit/pts/btp/test_gap_service.py::test_limited_discoverable_advertising_stops_after_tgap_timeout` / `..._leaving_limited_mode_cancels_the_tgap_stop` / `..._tgap_stop_is_a_noop_when_advertising_already_stopped`（monkeypatch `_LIM_ADV_TIMEOUT_S` 控制时长）。

### Q: PTS GATT/SR/GAR/BI-09+BI-11（read authorization / Insufficient Enc Key Size）稳定挂死，IUT 明明查得到特征却回 `0000` → A: BTP `GET_ATTRIBUTE_VALUE`(0x1d) 必须回**真实 ATT 读会产生的错误码**，auto-pts 拿这个码当**选择器**用 / 修复提交（本 session）

- **现象**：`GATT/SR/GAR/BI-09-C`（Lookup characteristic handle/UUID **that requires read authorization**）与 `BI-11-C`（…**that returns Insufficient Encryption Key Size**）反复 `UNKNOWN VERDICT: NONE` / INDCSV，PTS 拿到的 handle 是 `'0000'`。
- **根因**：`_handle_op_1d` 原来无论如何都回 `att_response = 0x00` + 真值。但 auto-pts 的这两个 WID 家族是**靠 att_rsp 选目标特征**的（`autopts/wid/gatt.py:1598-1660`）：先 `gatts_get_attrs(type_uuid='2803')` 遍历特征声明、解出 value handle，再对该 value handle 调 `gatts_get_attr_val`，**要求 `att_rsp == 0x0c`**（WID 121/122）或 **`== 0x08`**（WID 112/113）才认账；都不匹配就返回字符串 `'0000'`。我们恒回 0x00 → 没有任何候选 → 用例拿不到 handle → 空转。
- **修法**：`_handle_op_1d` 改走 `GATTServer._read_error(attr, sec)`——**真实 ATT 读用的同一道门**（就是 `pybluehost/ble/gatt.py` 里那套 0x02/0x05/0x08/0x0F/0x0C 映射），非 None 就 `bytes([err]) + (0).to_bytes(2,"little")`。链路安全状态由新增 `_link_security(server, addr)` 从 BTP wire 地址解出（复用已有 `_resolve_le_handle`）。
- **关键认知 ①（本条的真正价值）**：**`GET_ATTRIBUTE_VALUE` 不是「数据库裸读」，是按「一次真实 ATT 读」建模的**。auto-pts 把这个 API 的错误码当**选择器**用（「哪个特征会回 0x0C」），所以「永远报成功」不是保守做法，而是**静默地把所有受安全门控的特征从候选集里删掉了**。碰到「某个查找类 WID 找不到目标」先怀疑被调用的能力接口**返回值语义被简化**。这和「IUT 状态变了但不推事件，auto-pts model 陈旧」是同一家族——**接口的返回契约携带的信息比显式载荷更多**。
- **关键认知 ②（链路安全状态的默认值）**：`GET_ATTRIBUTE_VALUE` 是纯 db 查询，PTS 会在**对端根本没连着**的时刻调它，所以解析不到 peer 时必须回落 `_ConnSecurity()`（未加密/未认证/key_size 0）——`read_authz` 特征在这个默认态下正好给 **0x08**（WID 112/113 要的就是它）。反过来说，WID 121/122 要的 **0x0C** 还需要一条**活的、已加密但 key 长度不足**的链路，而那要靠 `SET_ENC_KEY_SIZE (0x09)`：它的 body 是 `u16 handle + u8 key_size` = **3 字节**（`Attribute_ID 0x0000` 表示「最后加的那个属性」），写的是 **BTP 侧** `_DynamicAttribute`，到 `START_SERVER (0x07)` 才随 `enc_key_size=getattr(val_attr,"enc_key_size",0)` 落进真库——所以建库顺序必须是 **ADD_CHARACTERISTIC → SET_ENC_KEY_SIZE → START_SERVER**。
- **为什么不会回归**：门控只在特征**带安全权限位**时生效。① **声明恒为 `Permissions.READABLE`**（`ble/gatt.py:438/446`，只有 value 属性拿 `char_def.permissions`），所以发现类 WID 不受影响；② 把 auto-pts 全部 ~40 处 `gatts_get_attr_val` 调用点过了一遍：gap.py 9 处 + gatt.py 的 service/include 读（182/272/327/402/535）全部读 **0x2800/0x2802 声明**；1942/1983 读声明后再筛 `if not perm & Perm.read: continue` 的**明文可读** value；1733/1882（`hdl_wid_138/139`）是**同一 handle 两次读相比**，门控前后两次同时变、比较结果不变；2023（`hdl_wid_304`）被门控时 `data` 变 `''`，而 `'' in val` 恒真——**只会 fail-open，不会把已过的用例判负**。
- **回归测试**：`tests/unit/pts/btp/test_gatt_service.py`（5 例：`read_authz` → 0x08；无连接 peer 回落未安全态 → 0x08；加密链路 key_size 7 < 声明 15 → 0x0C；key_size 16 满足 → 回真值；未配对 enc 链路 → **0x05** 而非 0x0F，即 GAP Vol 3 Part C §10.3 那条「未配对要告诉 central 去配对」）。`tests/unit/pts` + `tests/unit/ble` 全绿（719 passed）。
- **真机**：`GATT/SR/GAR/BI-09-C`、`BI-11-C` 重跑 **双双 PASS**（原 `UNKNOWN VERDICT: NONE`）→ GATT 107→**109/144 (75.7%)**，总 407→**408/479 (85.2%)**（2026-09-16,d1570ab）。

### Q: 每次 `scripts/pts_import_verdicts.py` 都把人手判的 `blocked` 冲掉（errata 结论被当次日志覆盖）→ A: 导入器新增「**`blocked` 不覆盖**」守卫，要改需显式 `--force` / 修复提交（本 session）

- **现象**：跑完 `GATT/SR/GAR/BI-09-C`/`BI-11-C` 后按流程 `scripts/pts_import_verdicts.py /tmp/auto-pts/logs --date 2026-09-16` 收割 verdict，`updated=131`；render 出来却只 **+1 pass**（应为 +2）。逐条 diff 发现 6 处变化，其中**两处是想要的 pass**，**一处是真实的新 fail**，**三处是被人手标注的 `blocked` 被冲掉**：`GAP/SEC/AUT/BV-13-C`(blocked→inconc)、`GAP/SEC/AUT/BV-14-C`(blocked→fail)、`GATT/SR/GAW/BV-01-C`(blocked→inconc)。
- **根因**：导入器**不按日志龄过滤**——它把 `logs_root` 下**所有**（跨多天、按 `cli_port_60000/<YYYY_MM_DD_HH_MM_SS>/` 分目录）日志都读出来，并按传入的 `--date` **统一盖章**（`pm.update_case(..., last_run=date)`，`--date` 默认今天）。于是「今天跑一次」会把**任何**历史日志重新写进矩阵。而 `blocked` 是**关于用例本身的判断**（PTS errata 让某用例永远不可能过 / 硬件限制），**一次重跑根本无法推翻它**——`GAP/SEC/AUT/BV-13/14` 之所以 blocked 是 PTS 在 case 开头就删掉自己的 host LTK（errata ES-28650），重跑多少次都还是 INDCSV。**「日志」和「人手结论」混在同一个字段里被同一条写路径覆盖，是这里的结构性问题。**
- **修法**：`import_verdicts(..., force=False)` 新增 `force` 形参——`existing["verdict"] == "blocked"` 且未 `force` 时**跳过并计入新的 summary 键 `preserved`**（CLI 打印 `preserved=N` + 一行提示）。要重开某个 blocked 用例必须**显式** `--force`。`--force` 是给「errata 已修复 / 误判了」这种真需要翻案的时刻用的。
- **关键认知**：**导入是「机器产物覆盖人手结论」的单向管道，所以只要有一类 verdict 是「人的判断」，就必须在导入层显式保护它**。此处 `untested/pass/fail/inconc` 是「最近一次跑成什么样」（机器可言），`blocked` 是「这个用例能不能跑」（只有人能言）——**语义不同就该有不同写权限**。同类风险：若将来有别的「非运行得出」的 verdict（如 `not-applicable`），沿用同一守卫。
- **配套**：被冲掉的三个条目已从 `HEAD` 逐条恢复（`notes` 原文含 errata 编号一字未改）；`GAP/ADV/BV-01-C` 的 `pass→fail` 是 2026-09-16 的**真实新跑**（`logs/cli_port_60000/2026_09_16_00_34_56/`），**保留**。恢复后矩阵与 `HEAD` 的全部差异只剩三处：`GAR/BI-09-C`/`BI-11-C` → pass、`GAP/ADV/BV-01-C` → fail。
- **⚠️ 一处我自己制造又修掉的坑**：第一次恢复时用 `yaml.safe_dump(..., width=100)` + `newline=""` 整文件重写，把 CRLF 变成 LF、并把整个文件重新折行（`git diff --numstat` 738/742）。**`scripts/pts_matrix.py::save_matrix` 用的是 `Path.write_text(...)`——Windows 上默认 `newline=None` 会把 `\n` 翻成 `\r\n`，且宽度取默认 80**，所以矩阵 YAML 的正确写法就是「走 `save_matrix`」，不要自己 `yaml.safe_dump`。重跑一次导入即回到规范形态（diff 降到 17/17）。**要改矩阵内容，优先重跑导入或用 `scripts/pts_matrix.py update`，别手写 YAML。**
- **回归测试**：`tests/unit/scripts/test_pts_import_verdicts.py`（3 例：blocked 被保留且 `notes` 不变 + `preserved==1`/`updated==0`；`force=True` 才覆盖并把 `last_run` 推新；非 blocked 条目照常更新，`summary` 精确等于 `{updated:1,created:0,skipped:0,preserved:0}`）。`tests/unit/scripts` + `tests/unit/pts` + `tests/unit/ble` 全绿。

### Q: PTS GATT/SR/GAR/BV-03（Read using Characteristic UUID）FAIL → A: ① 128-bit UUID 在声明/Find Info 里写成了大端（ATT 线上要小端）② Read By Type 对超长值返回**空**列表（应截断）/ 修复提交 1a0a23b + 452fd21

- **现象**：`GAR/BV-03` FAIL，PTS 发现不到 128-bit 特征，且 Read By Type 读 32/512 字节长值时响应为空。
- **根因 ①（128-bit UUID 字节序）**：`UUID128` 内部存大端（RFC 4122 字符串序），但 ATT 线上是**小端**。`add_service` 写服务/特征声明值、`_handle_find_information` 都用 `uuid.to_bytes()`（大端），PTS 发现到的 128-bit UUID 字节反了。`UUID16.to_bytes()` 恰好是小端所以 16-bit 一直没暴露。修法：加 `_uuid_le_bytes()`（16-bit 原样、128-bit 反转），声明值/Find Info 都用它；Read By Type 的 128-bit 查询也反转回大端再匹配。
- **根因 ②（Read By Type 长值）**：匹配特征值超过 `ATT_MTU-4` 时，`entry_len` 装不下单个 tuple，旧代码直接 break 返回**空** `attribute_data_list`。ATT 语义是截断到 `MTU-4`、客户端用 Read Blob 补余下。修法：`value_len = min(full_len, max_data-2)`，`attr.value[:value_len]`。
- **回归测试**：`tests/unit/ble/test_gatt.py::test_characteristic_declaration_uses_le_uuid_on_the_wire` / `::test_read_by_type_truncates_a_long_value_to_the_mtu`。真机 `GAR/BV-03` **PASS**。
- **后续（2026-10-31，消费端同样踩这个坑）**：`UUID128` 新增 `to_bytes_le()`（`_uuid_le_bytes` 改用它）；**GATT 客户端发现接口（`discover_all_services` / `discover_characteristics` / `discover_included_services` / `DiscoveredCharacteristic.uuid`）返回的是 ATT 线上字节（128-bit 小端）**——任何拿它和 `UUID128.to_bytes()`（RFC 大端）比对的代码都会静默失配（`tests/e2e/_helpers.py::resolve_handles`、`cli/app/gatt_browser._format_uuid` 都因此改走 `to_bytes_le()`/反转）。16-bit 恰好小端一致，所以这个坑只在 128-bit UUID 上暴露。

### Q: PTS GATT/SR/GAR BI-01/06/18/36（Read Not Permitted 簇）FAIL → A: 参考 db 缺一个**完全不可读**的特征；新增 write-only 特征并放到安全门控特征之前 / 修复提交 1d9f3cf + ab3f0f8 + 766e96e

- **根因**：这些用例需要一个「无任何 read 位」的特征值（读它回 0x02）。上游 zephyr `init_server` 的 db 里每个特征都带某个 read 级别位，所以参考 IUT 也过不了（参考实现 gap）。auto-pts 的 `hdl_wid_110/111` 谓词是 `not perm & Perm.read or not prop & Prop.read`，而 `read_enc/authn/authz` **也不含 plain `Perm.read`**，所以它们也会被误匹配。
- **修法**：① 加一个 `Prop.write + Perm.write`（无任何 read 位）的特征 `AA70`；② **必须放在安全门控特征（read_enc 等）之前**——`hdl_wid_110/111` 按 handle 序扫描取第一个匹配，放后面会被 read_enc 特征抢先（返回 0x05/0x08/0x0F 而非 0x02）。③ `_read_multiple_handles` 给 BI-18/36 加分支，返回这个 write-only 特征（`not (v & (read|read_enc|read_authn|read_authz))`）。
- **真机**：BI-01、BI-06 **PASS**（BI-18/36 修复已提交，验证被 peripheral flaky / BTP socket 重置卡住）。

### Q: PTS GATT/SR GAN/BV-02、GPM/BV-05（Multiple Handle Value Notification）→ A: 实装 ATT 0x23 PDU + BTP NOTIFY_MULTIPLE(0x21) + GATTServer.notify_multiple / 提交 b4e04e5

- **实装**：`ATT_Multiple_Handle_Value_Notification`(0x23，Handle+Length+Value 元组)；`GATTServer.notify_multiple(conn, handles)` 只在客户端 CSF 的 MHNV 位（bit 2）置位时发 0x23、否则忽略（GAN/BV-02 step 7 语义）；BTP `NOTIFY_MULTIPLE`(0x21) handler 解析 addr+cnt+handles 并路由；stack 的 `on_multiple_notification_sent` 桥接到 ATT channel。
- **⚠️ 这两个用例本身仍测不过**：GAN/BV-02 需要 **LT2（第二个 PTS）**，GPM/BV-05 需要 **EATT（多 bearer）**——都不是 MHNV 本身的问题。特性已交付（单测全绿），等 LT2/EATT 就位即可解锁。

### Q: PTS GAP/DISC/RPA/BV-01（发现时用 RPA）INDCSV → A: ① PAIR 没等 passkey display 就回响应，WID 1002 竞态拿 None ② resolving list 在配对前（connect 时）编程，bond/IRK 还不存在 → 修了这两块，**最后一步「控制器解析 RPA」仍卡在固件层** / 提交 7547808 + 5a887ec

- **根因 ①（passkey 竞态）**：`_spawn_pair` 把配对丢后台，`display_passkey`（display 角色）只在 PTS 的 Pairing Response 到达后才触发；而 auto-pts 的 WID 1002「enter Secure Id」在 PAIR 响应后**立刻**读 `stack.gap.passkey.data` → 竞态拿 None。修法：`_handle_op_11` 在 spawn 后 `await wait_for(passkey_displayed.wait(), 0.5s)`——display 角色 ~20-200ms 内触发、input 角色无 display 直接超时（不回归 passkey-entry 死锁修复）。真机确认 WID 1002 现在返回 passkey。
- **根因 ②（resolving list 时机）**：`_prepare_rpa_resolution` 原来在 `connect()` 里（配对前）编程 resolving list，此时 bond/IRK 不存在。修法：`pair()` 在 `stack.pair()` 完成后（bond 已存）再 `_prepare_rpa_resolution(peer)`。真机确认 `LE_Add_Device_To_Resolving_List`(0x2027, peer IRK=6cf0d45f...) + `LE_Set_Address_Resolution_Enable`(0x202D) 现在配对后正确下发。
- **⚠️ 最后一步仍卡**：resolving list + 地址解析都正确使能了，但扫描时 Extended Advertising Report 里 PTS 的 RPA 仍是 `addr_type=0x00`（public）+ 旋转的 RPA 地址（不是 identity `94:53:FF:1E:6A:EE`），即**控制器没真正解析 RPA**。报告解析偏移已核对无误（23 字节字段，addr_type@1）。最可能是 Intel 固件对「public own address + 地址解析」或「被动扫描 + 解析」的组合不做解析——下一步试 `scan()` 强制 random own address（`own_addr_type=0x01`）。

### Q: BR/EDR MITM relay 播放一段时间后无声（约 41s 后）→ A: ① init 时 LE ACL 缓冲池覆盖 BR/EDR 池致超发打爆耳机侧 dongle ② relay 出站内联 await 把一侧楔死放大成全链路断流 / 修复提交 b42da27 + 4dd7121

> BR/EDR MITM 授权测试环境：`手机(ColorOS) ⇄ phone侧BE200 ⇄ earbud侧BE200 ⇄ TWS耳机`，relay 代码在 `pybluehost/cli/app/mitm/`（本 worktree 分支，未并 master）。

- **现象**：手机连 `WQ7035_MITM` 播音乐，前 ~41s 正常（A2DP 媒体 43 帧/s），随后无声；链路逻辑上还「连着」（无 Disconnection_Complete），relay 不触发重连。
- **鉴别三种「无声」（看 per-dongle trace，`scripts/mitm_traced.py --trace-prefix hci` 录 `hci-earbud/hci-phone-*.btsnoop`）**：
  - **A. 手机停发**（ColorOS 音频焦点/外放切换）：媒体**平滑**降到 0，链路/事件正常。dongle 不挂。
  - **B. phone 侧 dongle ACL bulk 腿楔死**（BE200 固件 bug）：媒体 **43/s 断崖**到 ~1/s 再归 0；全程 0 个 Disconnection；**interrupt（事件）腿仍活**、冻结后每 30.000s 准点一个 `0x57` 事件（固件卡死报警）；bulk(ACL) 腿彻底死。带存活 ACL 退出会让固件挂死、重启不响应 HCI Reset，只能拔插（或 `scripts/dongle_reset.py` 软复位）。
  - **C. earbud 侧 dongle Data_Buffer_Overflow**（本次主 bug，**已修**）：earbud 侧 trace 抛 `0x1A` 事件 → 其 NCP(Number_Of_Completed_Packets)从 43/s 断崖到 ~4/s。
- **根因 C-1（主 bug，b42da27）**：`HCIController._initialize` 先 `Read_Buffer_Size`（BR/EDR 池 4×1021）后 `LE_Read_Buffer_Size`（LE 池 6×251），**两者写进同一个 `_acl_flow`，LE 把 BR/EDR 覆盖成 6**。BR/EDR 中继于是以为有 6 个 TX credit，而 BR/EDR 控制器实际只有 4 个 buffer → 超发 → earbud 侧 dongle 抛 `Data_Buffer_Overflow(0x1A)` → TX 楔死。**关键认知：BR/EDR 与 LE 的 ACL buffer 池是否共享是实现定义（响应里没有标志位），这批 Intel dongle 是分离的**（BR/EDR=4×1021、LE=6×251，数量/长度都不同，不可能是同一物理池）。修法：拆成独立 `_acl_flow`/`_le_acl_flow`，新增 `_conn_link_type` 按 handle 记连接类型（Connection_Complete 0x03 / LE_ConnComplete 0x01/0x0A 登记、Disconnection 0x05 移除），`send_acl_data` 与 NCP 按 handle 路由到对应池；LE 报 0（共用池）时 `_acl_flow_for` 回落 BR/EDR 池。**附带（Option A）**：init 不再发 `Host_Buffer_Size`——原代码声明了 host buffer（512/20）却既不开 0x0C31 流控也不回 0x0C35 credit，是个坏半态；移除后回 spec 默认关，控制器用原生 1021 MTU，不再被切成 512 碎片。
- **根因 C-2（放大器，4dd7121）**：`AclRelay._handle` 里 `await dst.send_acl(...)` **内联**在 `on_phone_acl`/`on_target_acl`（= 对侧 controller 的 bulk 读循环回调）里。earbud 侧一楔死，send 卡在 `acl_flow.acquire` → 回压 stall **phone 侧** `_read_bulk_loop` → phone 侧 dongle 的 bulk-IN 不被 drain → 手机媒体在 USB 层被静默丢。**修法：出站解耦**——每个目的侧挂一个有界 `asyncio.Queue` + 后台 drain 任务，`_handle` 只 `put_nowait` 完整 L2CAP PDU 即返回；分片+send+抓包移到 drain。dst 楔死只堵它自己的队列（满则丢最旧保新鲜、`dropped` 计数+限速告警），绝不回压 src 读循环。队列元素是完整 PDU（fragment 在 drain 侧做），丢弃是整条原子丢弃。`stop()`（重连断链时调，不关共享 capture）/ `flush()`（测试等排空）/ `teardown()`=stop+钩子+关capture。
- **dongle  teardown 纪律（c7044ee/7e02d08/aa561a6 等）**：带存活 ACL 直接关 USB/杀进程会让 BE200 固件挂死只能拔插。`ControllerPair.close()` 关 USB 前对两侧**并发**发 HCI_Reset 清干净态；`_run_relay_bredr` 收尾**并发** graceful disconnect（`return_exceptions=True`）+ 先 `relay.stop()`；并发是关键——一只楔死的 dongle 吃超时不能拖累另一只的清理。**永不强杀 relay 进程**（TerminateProcess 拦不住 finally）。
- **btsnoop 纪元（4530292）**：标准 btsnoop（Android/Wireshark/Frontline WPS）用 **0-AD 纪元**（常量 `62167219200_000_000` µs），不是 2000-01-01。误用后者会在 WPS 里减完纪元变负数、时间全显示 -1。`pybluehost/core/trace.py::_BTSNOOP_EPOCH_DELTA_US`。
- **回归测试**：`tests/unit/hci/test_controller.py::test_le_buffer_size_configures_separate_le_pool`（分池不互覆）/`test_acl_flow_for_*`（按 link_type 路由、共用池回落）；`tests/unit/mitm/test_relay.py::test_blocking_peer_does_not_stall_source_read` / `test_queue_full_drops_oldest_and_counts` / `test_stop_cancels_drain_and_drops_further_input`。
- **真机验证（2026-09-03）**：535s 全程 0 次 `0x1A`、earbud 侧 NCP 稳定 43.4/s，播 5 分钟正常。

### Q: BR/EDR MITM 换耳机/换手机后三连失败 → A: ① 耳机对 L2CAP 回 authorization pending 等本端主动认证 ② Intel ACL 期间暂停 inquiry scan 不恢复 ③ 耳机被释放后自动回连 dongle，对它发 page 永远超时 / 修复提交（本 session）

> 注：本条为已删除的 orchestrator.py 时代的记录——「prev-forward 纪律」及 `_install_bredr_conn_tracker`/`_await_bredr_connection`/`_make_link_watch` 均已随重构废除，现行结构见下条「MITM 模块重构(session.py)后的结构」。

> 承接上一条环境（`手机 ⇄ phone侧BE200 ⇄ earbud侧BE200 ⇄ TWS耳机`，目标 JBL Live Beam 4）。

- **根因 1（无声主根因，~30-60s 后 0x05 断链）**：TWS 耳机对 AVDTP/RFCOMM 的 L2CAP Connection Request 一律回 `result=0x0001(pending)+status=0x0002(authorization pending)`，**等本端发起认证**——SspTermination 只被动应答 SSP 事件（IO_Capability/User_Confirmation/Link_Key），没人发 `HCI_Authentication_Requested` 耳机就一直 pending，超时后以 0x05(Authentication Failure) 断链（两次真机 trace 实证）。修法 `orchestrator.py::_secure_target_link`：relay 建立即 AUTH_REQUESTED →（本端无 bond 时 Link_Key_Request→negative reply→SSP 配对，新 key 落盘 key_log；有 bond 直接过）→ AUTH_COMPLETE status=0 → `HCI_Set_Connection_Encryption`。**关键认知： initiator 侧的 SSP 完成不等于认证完成——耳机要 host 显式请求认证才放行 profile 连接。**
- **根因 2（WQ7035_MITM 搜不到/搜得慢）**：Intel 控制器在 ACL 建立期间自动暂停 inquiry scan，断链后**不恢复**；且默认 scan window 小（~11-18ms/1.28s）。修法：① impersonate 写 `Write_Inquiry/Page_Scan_Activity` interval==window=0x0028（25ms ≈ 常开）；② 重连循环每轮 `_ensure_phone_visible()` 重发 `Write_Scan_Enable=0x03`。
- **根因 3（换手机场景）**：TWS 耳机被手机释放后，会把**最近配对设备**（= earbud 侧 dongle，已有 bond）当手机**自动回连**；relay 不知道，继续对已连接设备发 page → 5×connect_timeout 全超时，新手机等不及断开。耳机还会反过来 page 下游伪装设备（当另一台已配对手机）。修法：① `_install_bredr_conn_tracker` 在 upstream 维护连接表（addr_le_hex→handle，Connection/Disconnection_Complete 增删）；② `_connect_bredr_target` 每轮迭代开头查表——有记录直接复用现有连接不发 page；page 间隙（非 in_flight）到达的成功 Connection_Complete 从「当 stale 丢弃」改为**记入连接表下轮采纳**；③ `_await_bredr_connection` 对与伪装身份相同的 page 回 `HCI_Reject_Connection_Request(0x0D)`（不 accept、不解析 future），Connection_Complete 地址=伪装身份的也不当手机。
- **纪律：所有 hci_event hook 必须 prev-forward**：`set_upstream` 是全量替换语义——新 hook 处理完必须转发给进入前保存的 `_on_hci_event`（`result = prev(event); if asyncio.iscoroutine(result): ensure_future(result)`），否则前置 hook（tracker/SspTermination）在整个连接期失明。本 session 顺带修了 `_make_link_watch` 不转发导致 SspTermination 连接期失明的老 bug（新增 `controller=` 可选参数）。
- **配套**：耳机非配对模式时 inquiry 扫不到——`inquiry_for_target(total_timeout=90)` 多轮重扫（每轮 HCI_Inquiry ~10.24s，超时 cancel 后继续），预算耗尽才 TimeoutError；`scripts/mitm_traced.py`（operator scratch，不入库）recon 超时后无限重试——等的是人的操作，别退进程。
- **回归测试**：`tests/unit/mitm/test_session_bredr.py`（认证成功→加密/失败不加密/scan 重开）；`test_session_bredr.py::test_connect_reuses_tracked_earbud_connection_without_paging`/`test_connect_adopts_earbud_connection_arriving_between_attempts`；`test_session_bredr.py::test_auto_accept_rejects_target_earbud_page`；`test_bredr_recon_rnr.py`（多轮重扫/总超时）；`test_bredr_impersonate.py::test_impersonation_sets_fast_scan_activity`。
- **真机验证（2026-09-05）**：换手机场景全链路打通——第 1 轮 relay 服务一加（38:6F:6B:A5:E8:20）期间耳机放弃断开（0x13）→ 循环重启 → 第 2 轮新手机（14:C1:4E:FE:BE:61）page 1ms 内被 accept（handle=0x200）→ 连接表复用耳机回连（handle=0x100）→ A2DP 媒体 45 帧/s / 165 kb/s 1:1 转发，听歌正常。
- **遗留（占线不接管）**：relay 服务一台手机期间，第二台手机的 page **无人应答**（`_await_bredr_connection` 的 auto-accept 已随连接退出；`_make_link_watch` 只看 DISCONNECT）→ 对方 page 超时显示"连接不上"，要等耳机先放弃断链、循环重启后重试才成功（真机 11:48 首次失败/11:54 重试成功的实证）。修法方向：connected 态检测到非当前手机的 Connection_Request → 立即断旧链触发重连循环（后连的顶掉先连的，与真耳机行为一致）。

### Q: MITM 模块重构(session.py)后的结构? → A: orchestrator.py(1114 行 god-class)已删,改 `session.py` 的 MitmSession

- 每 controller 的 set_upstream **唯一属主**：HCI 事件 subscribe/unsubscribe 多点订阅，ACL 按 handle 的 if/else 分发到各链路 AclRelay（prev-forward 链式 hook 从此不存在）；
- BR 的 SspTermination 在 run() 启动段 attach（等手机之前，G3 时序）；
- _run_link 一份骨架，LE/BR 各一个；两链独立重连互不联动；
- LE 补真：LE_Create_Connection、连接事件真实地址喂 SMP（f5/f6）、LTK JSONL 持久化；
- CLI 两步式：`mitm scan`（全发现+列表选设备→ mitm-targets.json，按段合并）→ `mitm relay`（默认读 mitm-targets.json / mitm-keys.jsonl，秒起）；
- transform：transform.py 的 DEMO_RULES 正则替换（用户改规则），AclRelay 唯一新增钩子。
设计稿：docs/superpowers/specs/2026-09-03-mitm-redesign-design.md

### Q: GATT/SR 长写三负例（GAR/BI-08、GAW/BI-08、GAW/BI-09）→ A: ① Read By Type 非法区间要回 0x01 不是 0x0A ② prepare 对 write_enc-only 属性回 0x03 而 plain write 回 0x05/0x0F（不对称是两套套件各自要求的）③ offset 校验必须延迟到 Execute Write / 修复提交（本 session，2026-10-28）

- **GAR/BI-08（Read By Type Invalid Handle）**：`start > end`（或 `start == 0x0000`）是**畸形**请求 → `Error(0x08, starting_handle, 0x01 Invalid Handle)`；`start <= end` 但无命中的**合法空**区间才回 0x0A（GAR/BI-07）。GATT.TS PDF 页码教训：BI-07 的 MSC（0x0A）在 p71、BI-08 的（0x01）在 p72，**图和标题跨页错位**，别拿相邻页的图当依据。
- **GAW/BI-08（Write Long – Write Not Permitted）**：WID 120 选中的 handle 是谓词 `not perm & Perm.write` 命中的**第一个**属性——在我们的 db 上是 VND16_1（`read_enc|write_enc`，无 plain write 位），不是 read-only 的 VND16_3。TS p162 要求 prepare → **0x03**。而 plain Write Request 打同一属性必须回 **0x05/0x0F**（GAP/SEC/SEM/BV-24 靠这个驱动配对，正在 PASS）。**所以 0x03 只能加在 `_handle_prepare_write`、且必须限定「enc 位 + 无 plain 位 + 未加密链路」三条件**——authn/authz 属性 prepare 要保持 0x05/0x08（BI-12/BI-11 加密前也走 plain 链路），加密链路要落回 key-size 门给 0x0C（BI-13）。放 `_write_error` 里一刀切会同时打破这三类。
- **GAW/BI-09（Write Long – Invalid Offset）**：TS p163 明确「prepare 回 **echo**（Prepare_Write_Response），Execute Write 才回 `Error(0x18, handle, 0x07)`」——**offset 校验的时机是 Execute 而不是 Prepare**。实现用「contiguous running end」规则：片段 offset 超过「当前值长度 + 已排队片段」的连续末端才算非法（合法追加每片恰好顶到末端 BV-05，整值重写允许重叠 BV-10 嵌套写）。BI-33 的 0x0D（值超长）同样留在 Execute，互不干扰。
- **方法**：三例的期望错误码/时序全部以 GATT.TS 原文（`docs/spec_download/Core Test Suites/gatt_ts_p26_pdf.pdf` p71-72/p159-166）逐图核对后再动代码——「同族负例共享一种错误形状」在这里不成立（BI-08 回 0x03、BI-11/12 回 0x08/0x05、BI-13 回 0x0C，选中的属性不同、链路状态不同）。
- **回归测试**：`tests/unit/ble/test_gatt.py::test_read_by_type_invalid_handle_range_returns_invalid_handle` / `::test_prepare_write_defers_invalid_offset_to_execute` / `::test_prepare_write_on_write_enc_only_attr_returns_write_not_permitted`。全套 `tests/unit/ble` 零回归（含 BI-33 的 execute-0x0D、BV-05/10 的合法分片路径、GAR/BI-07 的 0x0A 路径）。
- **真机验证（2026-10-28，新 BE200 rig）**：GAR/BI-08-C、GAW/BI-08-C、GAW/BI-09-C **首跑即 PASS**；回归 GAR/BI-07-C（0x0A）、GAW/BI-13-C（短 key 0x0C）、GAW/BI-33-C（execute 0x0D）、GAW/BV-05-C（合法长写）全 PASS；GAR/BV-08-C 前一日 FATAL 系「PTS 没重连」flaky，重跑 PASS。GATT 132→**135/144 (93.8%)**，总 438/479 (**91.4%**)。
- **GAC/BV-01-C（Exchange MTU of Server）遗留 FAIL——IUT 侧已排除**：DEBUG 跑逐字节验证合规（Exchange MTU Response 恒回 server Rx MTU=512、内部记 min、读响应截到 MTU-1、plain 链路读 read_enc 特征正确回 0x05 且 LT 继续遍历）。两轮迭代（LT MTU 23 → 重连 → 512）遍历都完整走完仍 FAIL。已排除：① `TSPX_iut_rx_mtu` PIXIT——PTS 的 GATT 项目根本没定义（`BadPixitException`，apply_pixits 按设计跳过）；② 双 autoptsserver 孤儿进程（杀掉后无变化）。事实：同代码旧 rig PASS（09-18）、新 rig 6/6 确定性 FAIL、孪生例 GAC/BI-01-C PASS。**定性为 PTS 内部 MTU 验证黑盒，下一跳是 btsnoop/WPS 抓 PTS 侧期望**。教训：`set_pixit` 对 GATT 项目不存在的 PIXIT 名会 BadPixit（我们 apply_pixits 有守卫，但要知道 GATT 没有 GAP 那个 `TSPX_iut_rx_mtu`）。

### Q: PTS L2CAP/COS/CED/BI-29-C（255 轮 Identifier 压力测试）三轮硬件共 7 次尝试全 BTP ERROR，IUT 每次跑到第 ~65 轮就被断链 → A: **LT（PTS）自己的 LE DCID 分配器只有 64 个值（0x0040-0x007F），耗尽即静默 + Abort ACL——LT 结构性 blocked，已在矩阵记录**；IUT 侧四批修复保留（99e6e95/9bc3fc4/b3f1b20）/ 2026-10-29 定案

- **TS 规程**（L2CAP.TS §4.4.1.7，`docs/spec_download/Core Test Suites/l2cap_ts_p38_pdf.pdf` idx 43-46）：LT 循环 253+ 轮「IUT 发 request → LT 回故意**错误 identifier** 的 SUCCESS（id=0）」，最后 2 轮才回正确 id；**test fails if the IUT reuses an Identifier**——即 IUT 每轮必须全新 identifier、**永不重发**（重发 = 直接 Fail 条件）。
- **IUT 侧修复（全部保留）**：① 连接请求**只发一次、不重传**；RTX 窗口（`LE_CONNECT_RTX_INTERVAL=1.0`）内无有效响应即放弃，报 `LECoCConnectError.RESULT_NO_RESPONSE`（zephyr `l2cap_rtx_timeout` 同语义）——`tests/unit/l2cap/test_le_connect_rtx.py` 8 例（99e6e95）。② **BTP 层不得覆盖事务窗口超过 auto-pts client 的 20 s read timeout**：原 `_CONNECT_TIMEOUT_S=30` 让每个放弃都发生在 client 超时之后 → 全员 BTP TIMEOUT；manager 的 `connect_le_coc_channel(timeout=None)` 默认改用 RTX 窗口、BTP 覆盖删除（9bc3fc4）。③ 0.1 s 快速 per-round 窗口（`_CONNECT_WINDOW_S`，b3f1b20）把单轮压到 ~0.22 s——证明卡点与 pacing 无关后，保留它是因为它正确且对真实 peer 无影响（LT 应答本来就只要 10-50 ms）。
- **定案证据（空口 dcid 序列）**：LT 每轮 step-3 响应带的 DCID 严格递增：`0x0040 → 0x0054（round-1 双响应 +20）→ … → 0x007F → wrap 回 0x0040 → … → 0x0053`——**恰好 [0x40,0x7F] 共 64 个值一个循环**；循环完成后的第一个请求永远无响应、紧接 ACL `0x13`。三次独立复现：1.2 s/轮（65 轮/80 s 处死）、0.22 s/轮（66 轮/21 s 处死——**count-based 不是 time-based**）、0.1 s/轮 + **跳过 SCID 0x0080**（见下）。用例需要单条 ACL 上 255 轮，LT 发到第 64 个 DCID 就死——**数学上不可满足**。
- **共线假设要用一次硬件实验解耦**：第 65 轮同时是（a）我们 SCID 升序首次撞上 PSM 值 0x0080 和（b）LT DCID 循环耗尽——两个假设完美共线。做了一次 `_allocate_le_cid` 跳过 0x0080 的实验（round 65 用 0x0081）：终态 dcid 仍 0x0053、照死——**SCID/PSM 碰撞假设证伪，实验改动已回退**（结论留在本条，别再试）。判「LT 数到 N 就死」类问题的通用方法：把响应里的资源标识符（DCID/identifier/handle）序列全部提出来看周期；快慢两档 pacing 各跑一次即可判 count/time。
- **同 commit 的独立真 bug（BV-04 的修复，正确但尚未被真机触发）**：LE CoC **首个 K-frame 的 L2CAP length 字段包含 2 字节 SDU-length 前缀**（Core Vol 3 Part A §3.4.2）——满 MPS 的合法 K-frame 声明的是 **MPS+2**；`check_first_fragment_violation` 和 `_on_pdu` 的违规检查都要在 `_rx_sdu_expected_len==0` 时用 `declared - 2` 当 payload 数，否则合法帧被误判违规断信道。回归：`test_le_coc_credits.py::test_first_fragment_*`。
- **遗留**：`COS/ECFC/BV-04-C`（Reassembling）持续 INDCSV——空口签名与 BV-80 完全同形：LT 完成 ECFC 连接（接受我方 512/247/10 响应）后 ~95-250 ms **自己断 ACL、从不发 K-frame**（3×4 次尝试 0 中）。BV-80 先例是纯重试最终翻 PASS；~~BV-04 继续重跑收割，IUT 侧无可挖~~ **BV-04 已于 2026-10-29 定案 blocked（见下一条，重跑救不了它，与 BV-80 不同）**。
- **经验**：① 凡「HCI/信令命令成功但对端不再理」的挂死，先提**对端响应里的序列号/资源标识符序列**看有没有周期，再谈协议；② 两个变量恰好同步共线时，别推理——设计一次只改一个自变量的硬件实验；③ 矩阵里 `blocked`（带证据 notes）是这类「LT/环境结构性不可满足」的正确归宿——pass-rate 不虚高，后人不再重查。

### Q: PTS L2CAP/COS/ECFC/BV-04-C（Reassembling，MTU=MPS）19+ 次确定性 INDCSV——LT 接受我方响应后 ~325ms 自己 abort → A: **LT 侧单信道 ECFC data-phase 脚本结构性缺陷，IUT 侧已穷尽**；三次响应形状硬件实验全部证伪 + 同日兄弟例全 PASS 定案 / 2026-10-29 定案（矩阵 blocked）

- **签名（19+ 次，跨三种我方响应形状完全一致）**：LT 发 `0x17`（psm/scid/mtu=mps/credits=2）→ 我方回 `0x18 result=0` → WID 256（wait_for_connection）OK → **~325 ms 后 LT abort ACL**（BTP case-log 事件 `0x81` connected → `0x82` disconnected），全程**零 K-frame、零 0x16 credit、无更多 WID** → INDCSV。TS 规程（L2CAP.TS §4.9.1.19）本应是 LT 用我方给的 credits 发一条长度 X=MTU=MPS 的 SDU——「LT 先发数据」这一步从未发生。
- **三次响应形状实验（每次只改一个自变量，全部证伪）**：① 默认 512/247/10；② `TSPX_l2ca_inmtu=0078` PIXIT + listener MTU=120 → 响应 120；③ echo 请求 MTU（64）。全部同签名 abort。**结论：我方响应的 MTU/MPS/credits 形状不是触发条件。**
- **兄弟例判别法（本条的定案武器）**：同一天同一座架同一段代码，`COS/ECFC/BV-01-C`（Segmentation，IUT→LT 发数据）、`BV-02-C`（Reassembling，LT→IUT 发 K-frame）、`BV-03-C`（Interleaved 双信道，LT 只用响应 credits 就在 accept 后 152ms 发完 64 字节 SDU）、legacy `COS/CFC/BV-04-C` 全 **PASS**——**LT 引擎的数据面 + 响应 credit 记账都是好的**，缺陷只在「LT 主动发起的单信道 ECFC data-phase」这条脚本路径。此前怀疑过的「MPS/MTU 要对称」「要显式 0x16」两个假设都被 BV-03 直接杀死。
- **BV-02 假回归教训（别再犯）**：echo 实验期间 BV-02 连吃 2 次 INDCSV，看似 echo 代码打崩了它；HEAD 代码下 attempt 1 就 PASS。复盘：那 2 次是 **PTS.exe 退化态**（一次请求了越界 mtu=320、一次全程没发信令）。**判「我的改动造成回归」前，必须用 A/B（旧代码重跑同例）把环境退化摘出去**——AGENTS.md「PTS 侧状态退化重启 server」条的同族。
- **回退决定（已执行 `git checkout --`）**：echo/listener-MTU/inmtu-PIXIT 三套实验代码全部回 HEAD。理由：① echo 没修好任何东西；② BV-22/23 在旧 512 接受路径下照 PASS，listener-MTU 管道是死代码；③ inmtu PIXIT 未验证有效。**实验失败的代码不留库——结论进文档，代码回 HEAD。**
- **方法（可复用）**：① **BTP case-log 事件时间戳**（`Header(svc_id=3, op=0x81/0x82/0x83…)` 行）给出精确的连接→数据→断链时序，iut log 无时间戳时用它做 ms 级对齐；② 「同族兄弟例当天全 PASS」是判 LT 脚本缺陷的最强判别——比逐帧对 spec 快一个数量级；③ 与 BI-29-C 同判词：`blocked` + 证据 notes 进矩阵，后人不再重查。

### Q: PTS GATT/CL/GAR/BV-08-C（Read Multiple Variable Length，by Client）13 连 INDCSV——IUT 收到了值、WID 55 却答 No → A: ① BTP 响应带了 {len,value} 前缀而 upstream 要**裸拼接** ② **这版 PTS 把 Core-5.3 RMVL 响应元组的长度字段编成 16-bit LE**，按 spec 的 u8 解析器第一元组就失步 / 修复提交 ad6c82b（2026-10-29 PASS）

- **现象**：GAR/BV-08-C 自 09-18 起 13 连 INDCSV（AX201 时代 09-17 曾 PASS）。流程：WID 140（发 RMVL 请求，两 handle）→ IUT 发 0x20、收到 0x21 响应 → WID 55「IUT 收到的值匹配吗」→ auto-pts **答 No** → INDCSV。TS MSC（GATT.TS p116 Figure 4.90）是**成功路径**，不该有错误响应——问题纯在「值对不上」。
- **判定链（值是怎么比的）**：`hdl_wid_140` → `gattc_read_multiple_var_rsp` 读**命令响应**（不看任何事件），`gatt_dec_read_rsp` 按 `<BH`（att_rsp + 数据长 + **裸数据**）解出整块数据 → `hexlify().upper()` 塞进 verify_values；WID 55 的 `verify_multiple_read_description` 把 MMI 描述里的值裸拼接（如 `6400C8000000D007546F6F7468313233`）当**子串**去匹配。所以 ① 我们 `_handle_op_20` 响应里的每个 `{len(u8), value}` 前缀都会污染 hex——**永远不可能匹配**；这条一开始就是把**事件解析器**（`gatt_cl_read_mult_var_rsp_ev_`，确有元组）的格式错安到**命令响应**头上了。
- **最隐蔽的一层（别再上当）**：修掉 ① 后仍 3 连 INDCSV。verify 串 `00130300010203` vs 描述 `139C`+`010203`——值里「看着眼熟但错位」。给 `decode_att_pdu` 加一行 **raw hex 日志**后抓到空口字节 `21 01 00 7F 07 00 07 00 00 01 00 5E 01`：按 spec u8 长度解析=（1,`00`）+（127 截断垃圾）；**按 16-bit LE 长度解析=（1,`7F`）+（7,`07000001005E01`）——与 MMI 描述逐字节一致**。即**这版 PTS 把 Core-5.3 新增的 RMVL 响应元组长度字段编成了 u16 LE**（两轮不同随机 db 的抓包都能完美对上，存于测试 `test_att_parses_rmvl_response_with_u16_length_tuples`）。**「值眼熟但错位」= 长度字段宽度错了的签名：别信第一眼的『损坏』，先拿描述值当地纹找对齐。**
- **修法（liberal 解码）**：`ATT_Read_Multiple_Variable_Response.from_bytes` **先按 u16-LE 走元组链、不精确耗尽 PDU 时才退回 spec 的 u8 形式**，两条都不精确才报 malformed。⚠️ 顺序不能反：BV-10 的抓包 `21 01 00 05 03 00 65 05 34` 按 u8 走会**恰好耗尽**成假元组 (1,`00`),(5,`03 00 65 05 34`)，没有空元组可当 tell——真实 u8 PDU 只有在值字节恰为 0x00 且整条链仍对齐时才会被 u16 错误吞掉，概率远低于反向，所以 u16 优先。**服务端 0x20 响应编码保持 u8 不动**——SR 侧 BI-20/21/22 用 u8 响应 PTS 是收的（已 PASS），别动活路。BTP 响应改为**裸拼接**。
- **配套**：`decode_att_pdu` 的 debug 行带上 `data=<hex>`——这次若没有这行，空口字节问题要靠 btsnoop 才能定；一行日志省一轮取证。
- **回归测试**：`tests/unit/ble/test_gatt.py::test_att_parses_rmvl_response_with_u16_length_tuples`（两轮真机抓包 + spec u8 形式 + 往返）；`tests/unit/pts/btp/test_gatt_client.py::test_read_multiple_var_returns_raw_concatenated_values`（裸拼接响应）。真机 attempt 1 **PASS**（2026-10-29，BE200 rig）。
- **⚠️ 矩阵考古教训**：AGENTS 旧条目「GAR/BV-08-C 重跑 PASS（2026-10-28）」是**张冠李戴**——和同日首跑 PASS 的 **GAR/BI-08-C**（Invalid Handle 负例）混了；真 GAR/BV-08-C 自 09-18 起从无 PASS 记录（11 连日志俱在）。**读旧结论时先核对 case 全名，BI/BV 一字之差。**

### Q: BE200 迁到扩展扫描家族后扫描类用例（DISC/RPA 等）INDCSV，DEVICE_FOUND 刷屏但地址全乱 → A: **扩展广播报告的 Event_Type 是 2 字节（§7.7.65.13），解析器按 1 字节读、23 字节固定步长——所有字段错位一字节** / 修复提交 e7fa940（2026-10-29，DISC/RPA/BV-01-C 首跑 PASS）

- **现象**：BLEScanner 发出的每条报告 `ad=0 rsp=0`、地址形如 `xx:…:01`（吞了 addr_type 字节）；`GAP/DISC/RPA/BV-01-C` 里 LT 的 RPA 广播「收到了但零报告」，整簇 INDCSV。此前把根因一路误判成「RF 没收到」→「控制器解析抑制报告」，全是解析器错位制造的假象。
- **根因**：§7.7.65.13 每报告 = **Event_Type(u16 LE)** + Addr_Type + Address(6) + Primary_PHY + Secondary_PHY + SID + TX_Power(0x7F=不可用) + RSSI + Periodic_Interval(2) + DirectAT + DirectAddr(6) + Data_Length = **24 字节固定** + Data（RSSI 在头部；legacy 报告是尾部）。旧解析器 `event_type=data[offset]` 只读 1 字节 → 地址吞掉 addr_type 字节、`data_len` 落在 Direct_Address 里（恒 0 → `ad=0`）、越界 report 被静默 `return` 丢弃。**单测也是按同一错误布局构造的字节——测试和实现一致地错，绿了三个月。**
- **定位方法（可复用）**：① iut log 的 HCI debug 行在 **16 字节截断** params，看不到完整事件——写探针脚本（`scripts/_ext_report_dump.py`）挂 `set_upstream` 打印完整 `event.parameters`；② 用环境设备做**语义校验**钉死布局：WQ_7035/JBL/追踪器的 RSSI（-33..-90）、TX_Power=0x7F、SID 按设备族、JBL 的 60ms 周期间隔（Auracast）只有在 24 字节布局下全部讲得通；③ 修好后加**真机捕获回放测试**（LT 事件逐字节）防止再错。
- **RPA 解析的正解（配套实装，保留）**：bond 后把对端 IRK 编进 resolving list，**控制器**把 LT 的 RPA 解析成 identity 上报（PASS 那次空口证据：`LeAdv(addr_type=0, addr='fc9e53d58deb', eir=flags+"PTS-GAP-")`，`check_discovery_results` 对比 `TSPX_peer_addr`=identity，bluez 的 pre_conditions 每例 `set_pts_addr` 重置）。另实装 host 兜底 `_resolve_rpa_identity`（用 bond IRK 在主机侧解析，服务不支持 resolving list 的 dongle 用）+ `PYBLUEHOST_SCAN_RESOLUTION=off` 实验开关——真机 PASS 走的是控制器路径，兜底未触发但保留。
- **两个配套基础设施坑（同 session 修）**：① `pts_retry_cases.sh` 的 `wait_verdict` 读 stale 日志秒回幻影 verdict、而 `pts_run_batch.sh` 的 transport 守卫因 dongle 解析器默认地址指旧座架而根本没起 client——现在起跑前 `rm -f` 日志 + 15s 存在性检查，`pybluehost_pts_dongle.py` 默认 IUT 地址更新为新 BE200；② 收割会把人手 `blocked` 冲掉的老问题已有导入守卫，但**丢弃用的 warmup 日志目录要删掉**，否则每次收割都把已恢复的 pass 再冲成 INDCSV（CSUB/CSU/BV-01-C 本次又中招）。
- **OBSV/BV-06 与解析器无关，仍 LT-structural**：修后 3 连 INDCSV，WID 序列依旧只有 78/208/1002——LT 在 SC bond 完整完成后自己 60s stall → `0508` → 从不广播，IUT 扫描器根本轮不到上场（早前结构性定案维持）。
- **经验**：① **「单测绿」≠「线格式对」——测试和实现可以一致地错**；凡协议字段布局必须用真机捕获逐字节回放（本次正是回放测试在改布局后当场变红）；② 判「没收到」之前先抓原始事件字节——log 截断 + 解析器丢弃叠在一起时，「零报告」和「没收到」长得一模一样；③ RSSI/TX_Power/PHY 这类「每设备讲不讲得通」的语义校验比数偏移快得多。

### Q: PTS GAP/SEC/SEM 重连簇（BV-56..67）在 2026-10 BE200 新批上全 BTP ERROR——重连 0x2043 永不完成（3× Connection Complete 0x02）→ A: `_prepare_rpa_resolution` 在**任何**分发 IRK 的配对后无条件开启控制器地址解析，而该固件对「地址解析开启 + 对端用**公开身份**广播」的发起连接永不完成（与 `_maybe_disable_controller_resolution` 的扫描侧「解析即丢报告」是同一族固件怪癖） / 修复提交 8c2e983（2026-11-01，BV-64 真机 PASS）

- **现象**：`GAP/SEC/SEM/BV-64-C` 等「配对→断连→重连→收 indication」用例，首连+配对+indication+断连全成功，第二次 WID 78 重连的 3 次 `LE_Extended_Create_Connection (0x2043)` 各 CommandStatus 0x00 后**永不回 Connection Complete**，超时后 cancel → 0x02，`actions.connect` 抛 `RuntimeError: LE connection ... failed to establish` → BTP ERROR。LT 侧 HciLogs 铁证：断连后 `LE_Set_Advertising_Enable=1`（status 0x00）用**公开地址**（`Own_Address_Type=0x00`）广播 ~17s 直到放弃，IUT 却一次都连不上。
- **根因**：`IutActions._prepare_rpa_resolution` 在 `connect()`（连前）和 `pair()`（配后）两处被调用，配完 bond 后把对端 IRK 编进 resolving list（0x2027）并 `set_address_resolution(True)`（0x202D）。首连时地址解析是关的所以成功；配完后解析被打开，重连到对端**公开身份**地址时 2026-10 BE200 固件的 initiator 永远不完成（连接侧孪生问题，扫描侧就是已知的「解析即丢报告」）。重连时第二次 0x2027 回 0x12（重复条目，良性）是红鲛鱼——真正有害的是 0x202D 把解析打开。
- **修法**：`_prepare_rpa_resolution` 在 `privacy.enabled` 为假时直接 return（不编 resolving list、不开解析）。隐私用例（GAP/PRIV/CONN、GAP/DISC/RPA）都先经 `SET_PRIVACY`→`program_private_address`→`privacy.enable()` 把 `enabled` 置真才走到这里，所以不回归；ACEP 走 `prepare_auto_connection` 自己编程，不经此路径。
- **判别**：① 首连成功、重连失败，且 LT 侧 HciLogs 确认对端用公开地址在广播 → 先查 IUT 侧 0x202D 是不是被 `_prepare_rpa_resolution` 打开了；② 「0x2027 回 0x12」= 重复加条目，是良性的，别当根因；③ 控制器地址解析只在隐私用例该开——「对端用公开身份」时开解析是纯有害（连接侧）+ 纯无用。
- **回归测试**：`tests/unit/pts/test_actions_rpa_resolution.py`（privacy 未激活跳过、激活才编程、无 storage/privacy 不抛）。


### Q: PTS GATT/CL/GAR/BV-10-C（Read Multiple Variable Length over multiple bearers）PTS TIMEOUT → A: ① EATT_CONNECT 只 attach 了 GATT **server**，EATT 信道上没有 client bearer ② BTP 串行分发下必须「首条命令即并发两个 RMVL」，否则 ATT 腿 30s 超时 ③ upstream `hdl_wid_147` 从不存 verify 值，WID 55 结构性必答 No / 修复提交（本 session，2026-10-29 PASS）

- **TS 规程（GATT.TS §4.6.1，p116-117 Figure 4.91）**：Test Case Bearer =「Unenhanced ATT + EATT」。MSC 的次序是 IUT 在 **CID01 发 0x20 → UT 发第二条命令 → IUT 在 CID02 再发 0x20 → 此时 LT 才先答 CID01、再答 CID02**——即**两条请求必须同时在飞**，先等第一条的响应再发第二条必死锁（真机两次 30s ATT 超时、PTS 判 INDCSV）。BTP `READ_MULTIPLE_VAR (0x20)` **没有 bearer 字段**，选哪条 bearer 是 IUT 内部策略。（BV-11 是 EATT-only 的双胞胎，由 `hdl_wid_148` 驱动，走同一套管线。）
- **根因 ①（client bearer 缺失）**：`GATT EATT_CONNECT (0x1f)` 原本只调 `stack.attach_eatt_bearer(ch)`（server 侧），EATT 信道上没有 GATT **client** 的 ATT bearer → 第二条请求无处可发。修法：`IutActions.attach_eatt_client_bearer(handle, channel)`——`install_att_channel_mux(channel)` 后给该信道挂 `ATTBearer` 的 `_on_pdu` 作为 `_att_client_handler`，按 handle 记进 `_eatt_client_bearers`；`_handle_op_1f` 在 server attach 之后对每条新信道调它。**ATT mux 按 opcode 分流（request→server / response→client），同一条 EATT 信道上 client 与 server 可以共存**——GAP/SEC 那条修复的同一机制。
- **根因 ②（串行分发 vs 并发请求）**：`tester.py::_run_client` 逐帧 `await _dispatch()`，BTP 命令严格串行；若 `_handle_op_20` 直接 `await` 第一次读，第二次请求永远发不出去，LT 按 MSC 也不答第一条。修法：per-handle 轮转序号 `_rmvl_bearer_seq`（偶数=ATT / 奇数=EATT）+ `_rmvl_pending`（`{"att": fut, "eatt": fut}`）。**第一条命令（seq=0）同时 `ensure_future` 两条事务**——ATT bearer 用 `client.default_bearer`，EATT bearer 用 `eatt_bearers_for_handle(handle)[0]`——然后 await ATT 的 future；**第二条命令（seq=1）取走 EATT 的 future**。没有 EATT bearer 时（如 BV-08 单 bearer）整段是 no-op，行为不变。`GATTClient.read_multiple_variable_characteristic(handles, *, bearer=…)` 新增 bearer 覆盖参数（默认仍是 `self._bearer`）。
- **根因 ③（WID 55 结构性不可过）**：upstream `hdl_wid_147` 发完两条 `btp.gattc_read_multiple_var()` 就 `return True`，**不存任何 verify 值**（无参考项目注册 BV-10，这个 gap 从未被 upstream 发现）→ WID 55 `verify_multiple_read_description` 拿空 `verify_values` 做子串匹配，**永远答 No**。修法：`pybluehost_iut/wid/gatt.py` 加 `hdl_wid_147` override——发两条命令后 `gattc_read_multiple_var_rsp(store_rsp=False, store_val=True)` 存**一次**值 blob（两条请求的 handle 集相同，值相同），再 `get_iut().btp_socket.read()` 把第二条响应帧排掉，不留 stale frame 给后续 `read()`。
- **附带（解码器顺序翻转，同时修正 BV-08 条目）**：BV-10 的抓包再次确认这版 PTS 的 RMVL 响应元组长度是 **u16 LE**，且 `21 01 00 05 03 00 65 05 34` 按 u8 解析**恰好耗尽**成假元组、无空元组可用作 tell → `from_bytes` 改为 **u16-first、u8 fallback**（详见上一条 BV-08 的修法）。
- **真机**：WID 序列 2（connect）→142（CSF=0x02 EATT on）→402（EATT_CONNECT，~90ms）→147（两条 RMVL）→55（值匹配 Yes）→3（disconnect），2026-10-29 15:09:51 `set_result ... PASS`。warmup BV-08 仍 PASS（单 bearer 路径无回归），L2CAP/ATT 全链路无回归。
- **回归测试**：`tests/unit/pts/btp/test_gatt_read_multiplex.py`（首条命令同时发 ATT+EATT、第二条命令收 EATT future、四条命令交替、无 EATT 时全走 ATT、EATT_CONNECT 经 actions hook 注册 client bearer）；`tests/unit/ble/test_gatt.py::test_att_parses_rmvl_response_with_u16_length_tuples`（BV-10 抓包解析为 0x05 与 0x650534 两个值）；`tests/unit/auto_pts_project/test_wid_handlers.py::test_gatt_hdl_wid_147_stores_the_read_multiple_values`；`tests/unit/pts/btp/test_gatt_client.py` 的 fake 签名加 `bearer=`。
- **经验**：① **BTP 命令串行、TS 规程要求「同时在飞」时，必须把并发塞进单个命令处理里**（首条命令熔合两条事务、后续命令收割 future），不能让 auto-pts 的调用顺序去表达并发；② 「某 WID 的 upstream handler 只 return True 不存值」是 **WID 55 类校验用例的静默死因**——参考实现从不注册该 case，就没人发现；③ 多 bearer 用例的 bearer 选择是 **IUT 内部策略**（BTP 无字段），把它写成 per-handle 轮转序号即可，不用改协议。


### Q: PTS GAP/CONN/DCON/BV-04-C（Directed Connectable + Privacy，RPA）恒定 PTS TIMEOUT → A: ① 这版 PTS 的用例脚本**从不要求 directed advertising**（全程只有 WID 118 + 两次 WID 20001，没有 406/407）② phase-1 的 LT 扫描是 accept-list-only 且不开地址解析，RPA 广播被控制器丢弃；公开地址 A/B 实验给出了因果证明 / 2026-10-31 定案（矩阵记 blocked）

- **TS 要求**（`docs/spec_download/Core Test Suites/gap_ts_p46_pdf.pdf` p188-189）：IUT 在 Privacy 模式下先做 General Connectable（步骤 2-5）再用 **Direct Connectable 指向 LT 的 identity**（步骤 6-7）；Pass verdict 要求**每个 directed 广播的 AdvA = IUT 的 RPA、InitA = 用 LT IRK 生成的 RPA**。auto-pts 里对应的 MMI 是 **WID 406**（`hdl_wid_406` → `btp.gap_start_direct_adv(..., peer_rpa=1)`），BV-05 的「拒绝该指令」是 WID 407。
- **PTS 侧实际 MMI 序列**（case log `wid:` 字段）：`118`（读 CAR）→ `20001`（"Please prepare IUT into a connectable mode"，第一次 = 步骤 2）→ 连接 → 断链 → 再次 `20001`（本该是步骤 6 的 directed 指令）。**406/407 一次都没发**——auto-pts 的 `hdl_wid_20001` 只会起**无向**广播，所以由 auto-pts 驱动的任何 IUT 都不可能进入 directed 模式。**参考实现佐证**：zephyr/bluez/mynewt 的 `ptsprojects/*/gap.py` 里都**没有注册** DCON/BV-04/05（`grep DCON autopts/ptsprojects/*/gap.py` 为空）。
- **phase-1 为何连接不上（正常配置下）**：PTS 侧 HCI 日志（`runs/phase2/workspace/<ws>/_<PTS地址>/logfiles/HciLogs.txt`，行格式 `SIG_DT:<ms>,<dir>,<flag>,<len>,<hex>`，hex = opcode(2,LE) + 参数长(1) + 参数；`SIG_ST` = 用例开始，`SIG_LG` = PTS 自己的日志/MMI）显示 LT：`0x2011 Add_Device_To_Accept_List(peer=我们的 identity)` 两次（public/random 两个地址类型）→ `0x2041 LE_Set_Extended_Scan_Parameters` 参数 `00 01 01 01 1e00 1e00`（**filter_policy=0x01 = 仅 accept list**）→ `0x2042` 开扫描；**全程没有 `0x2027 Add_Device_To_Resolving_List`、没有 `0x202D LE_Set_Address_Resolution_Enable`**。于是我们广播的 RPA 既不匹配 accept list、又没有解析机会 → 控制器直接丢弃 → 0 个广播报告 → PTS 干等 TIMEOUT。
- **因果实验（决定性，代码已回退）**：同一段代码、只把 `IutActions.advertise` 的 own address 强制成 public identity（`PYBLUEHOST_EXP_ADV_PUBLIC=1` 临时开关），LT 立刻在 t=1337 记录到我们的广播（`SIG_DT:1337,...,0d0113000015602f2785a0...`，AD = flags + "Tester_D58DEB"）并发起 `0x2043 LE_Extended_Create_Connection`，`Enhanced Connection Complete status=0x00`——**证明广播/射频路径完全正常，唯一差别就是 RPA 能不能被 LT 接受/解析**。（实验开关按「实验失败的代码不留库」已移除；结论留在此条。）
- **工具/接线事实**（排查时反复用到，值得记住）：
  1. **PIXIT 推送是真实生效的**：`PyPTS.set_pixit` 在 PTS 回 `PTSCONTROL_E_PIXIT_PARAM_NOT_CHANGED` 时会抛异常，所以「没抛」= 值确实变了；case XML（`<ws>/_<PTS>/GAP/<CASE>_<ts>/<CASE>_<ts>.xml`）里记录的是**本用例实际用的 PIXIT**，可用来核对。`.pqw6` 工作区文件里的 `TSPX_iut_device_IRK...` 仍显示 `0000…` 且 mtime 不更新——那是 PTS 从不回写的陈旧副本，**别拿它判断推送是否成功**。`pybluehost_iut/gap.py` 的 `set_pixits` 对推送失败现在打 `logger.warning`（原先是裸 `except: pass`，白丢了一整轮排查）。
  2. **PTS 侧 HCI 日志就是「LT 的空口真相」**：`logfiles/HciLogs.txt` 每会话覆盖，per-case 也有 `GAP/<CASE>_<ts>/HciLogs.txt`。判定「对端看到/没看到我们」先看这个，比 btsnoop 便宜。
  3. **`IutActions.advertise` 的 `else` 分支**：只要 `ble_privacy._current_address` 非空（SET_PRIVACY / 之前的用例编过程序过 RPA），即使 BTP 传 `own_addr_type=0` 也会**沿用已编排的私密地址**广播（`config.own_address_type=0x01` + `set_random_address(current)`）。想让 IUT 用公开地址广播，必须同时绕过这个分支——这是上面实验一开始「改了但空口没变」的原因。

### Q: PTS GAP/PRIV/CONN/BV-10-C（Privacy – Connection：RPA 广播 → 定时轮换 → 被 LT 连接 → 断连）长期 INCONC → A: ① 轮换 RPA 必须在**先停广播**的窗口里改地址，而 `LE_Set_Address_Resolution_Enable` 在 Intel 上是「advertising set 使能时**两个方向都回 0x0C**」② phase-3 的断连按 **LT identity** 寻址，而 LT 的连接事件里是它**自己的 RPA**（由 PTS 内部一个从不经 SMP 下发的 IRK 生成，任何我们持有的密钥都解不开）/ 2026-10-31 定案（真机 PASS）

- **用例流程（case log 的 WID 序列）**：`91`（connectable 广播）→ `77`（按 TSPX_peer_addr 断连）→ `90`（以 RPA 广播）→ `405`（换私密地址；upstream 是 no-op）→ `20001`（start）→ LT 连入 → `77`（断连）。判定要求：每个广播事件里 AdvA 是**可解析** RPA（LT 用 `TSPX_iut_device_IRK_...` 解析）、`TGAP(private_addr_int)`（PIXIT=5000ms）后地址变化、连接能建立、连接能**终止**。
- **根因 ①（地址编程被控制器拒绝，轮换静默失败）**：`LE_Set_Random_Address` 在**广播使能中**、或**地址解析使能中**都回 `0x0C Command Disallowed`。更严的是 **`LE_Set_Address_Resolution_Enable` 本身**：只要 advertising set 还开着，**打开和关闭两个方向**在 Intel 上都回 0x0C。所以正确顺序是「**停广播 → 关解析 → 写随机地址（+ 更新 adv set 地址）→ 开解析 → 恢复广播**」，而早期实现是「先关解析、再停广播」——关那一步被拒，后面的写必然失败（DEBUG 日志里能直接看到 `LE_Set_Address_Resolution_Enable(False) ... status=0x0C`）。修法：`PrivacyManager.set_random_address` 把 `pause_for_address_change()` 提到最前，所有解析开关都在停广播窗口内完成（`pybluehost/ble/gap.py`）。**注意 `LE_Set_Advertising_Set_Random_Address`（0x2035）在没有 set 时回 `0x42 Unknown Advertising Identifier`——轮换循环跑在首次 `start()` 之前，属良性**：`BLEAdvertiser.set_random_address` 记住地址，`start()` 建好 set 后再补一次。
- **根因 ②（断连目标对不上，用例卡到 time_guard）**：phase-3 的 WID 77 用 `TSPX_peer_addr`（LT 的 **identity**）寻址，而我们的会话表里存的是 **LT 连接时用的 RPA**（空口 `LE Connection Complete` 里 addr_type=0x01 + RPA）。尝试用 bond 里的 IRK 反解该 RPA 全部失败——把 PTS 在配对时分发的 IRK 和 `PTS_IUT_IRK`（AB×16）的各种字节序组合都试过，`ah()` 本身已用 Core 规范向量（k=ec0234a3…, r=0x708194 → 0x0dfbaa）验证过；结论是 **PTS 生成 LT 侧 RPA 用的 IRK 从不经 SMP 下发**，主机侧无解。
- **修法（三段式匹配，`pts/btp/services/gap.py::_handle_op_0f`）**：① 精确匹配会话表里的 peer；② 用 bond IRK 把 RPA 解析成 identity 再比（`IutActions.peer_identity` → `stack._load_bond_for_peer`，将来对端真是用已下发 IRK 铸的 RPA 时自动生效）；③ **只剩一条连接时按唯一连接断**——auto-pts 的 GAP DISCONNECT 永远指向 LT，单连接时请求语义无歧义，与其让用例坐等 `TSPX_time_guard`，不如终止它。歧义（≥2 条连接）时仍然回 FAILED，并把实际连接列表打进 WARNING（正是这条日志把「connected: ['4e:04:1a:38:0d:a7'] vs 请求 fc:9e:...」的真相揪出来的）。
- **真机**：`PYBLUEHOST_RETRY_WAIT_ITERS=100 bash scripts/pts_retry_cases.sh 2 GAP/PRIV/CONN/BV-10-C` attempt 1 **PASS**（2026-10-31）。修前的对照跑（旧代码 + DEBUG + btsnoop）逐条命令 status=0x00 但 WID 77 回 FAILED、随后 PTS TIMEOUT，两相对照即证明「地址轮换修复」与「断连匹配修复」缺一不可。
- **回归测试**：`tests/unit/ble/test_gap.py::test_set_random_address_restores_resolution_before_resuming_advertising`（断言「停广播 < 首次关解析」「最后一次开解析 < 恢复广播」且写地址落在停广播窗口内）；`tests/unit/pts/btp/test_gap_service.py` 的 `test_disconnect_matches_a_peer_that_connected_under_its_rpa`（bond IRK 解析命中）、`test_disconnect_uses_the_only_connection_when_the_peer_is_unresolvable`（单连接兜底）、`test_disconnect_over_rpa_without_a_bond_still_fails` / `test_disconnect_tolerates_actions_without_peer_identity`（两条连接时仍 FAILED）。
- **经验**：① 「一条 HCI 命令被 0x0C 拒绝」时，**要问的不是这条命令的状态，而是「谁把控制器带进了这个状态」**——本条的关解析在广播使能中被拒，而修法是把*广播*关掉；② 有些对端密钥**根本不下发**（PTS 的 LT 侧 RPA IRK），主机侧解析是死路，此时「单连接时按唯一连接执行」是既合法又不虚高的收敛方式——把结论和证据写进矩阵/文档，别反复重跑；③ 排查这类多阶段用例，**先跑一次旧代码 + DEBUG + btsnoop 的对照**，把「命令成功但用例仍挂」的阶段钉死，再改代码，省掉大量猜测。

### Q: PTS GATT/SR/GAC/BV-01-C 稳定 FAIL（Cannot find characteristic value with size equal to MTU-1）→ A: **Intel BE200 静默丢弃 PB=0b11（automatically flushable continuation）的 ACL 续片**——多片 L2CAP PDU 只有首片上了空口 / 修复提交（本 session，2026-10-31 PASS）

- **现象**：`GATT/SR/GAC/BV-01-C`（Exchange MTU of Server）连续 FAIL。MTU 协商到 512 后 PTS 读 511 字节的特征值，其 HCI 日志（`HciLogs.txt` 的 `SIG_DT:` 行）显示 IUT 只上了 **251 字节**（首个 ACL 分片），之后直到 `TSPX_time_guard` 什么都没有 → PTS 判 "Cannot find characteristic value with size equal to MTU-1"。
- **根因**：`send_acl_data` 把后续分片的 PB 位写成 `pb_flag | 0x01`（= **0b11 continuing fragment, automatically flushable**）。Intel BE200 固件对 0b11 续片**发出首片后静默丢弃其余分片**，同时照样在 `Num_Completed_Packets` 里报告它们已完成——主机侧 credit 记账一切正常，IUT 日志只看到「三个分片都交给了 transport」。
- **取证（两颗 BE200 互连探针）**：`scripts/_acl_frag_probe.py` 让 peripheral 发一条 516 字节 L2CAP PDU（251/251/14），central 侧挂 `_on_acl_data` 统计实收：`0b10+0b11` → **251/516**（加 20 ms 片间间隔也一样）；`0b10+0b01` → 516/516；`0b00+0b01` → 516/516。生产路径改用 0b01 后同一探针 516/516。
- **修法**：续片统一用 **PB 0b01（continuing fragment, not automatically flushable）**（`ACL_PB_CONTINUING`），首片保持调用方给的 PB（0b10/0b00）。**凡是超过控制器 LE buffer（BE200 为 251 字节）的出向 PDU 都走这条路**——ATT 读响应、L2CAP SDU、通知，不止 GAC。
- **经验**：① 「对端只收到首片、我方日志显示全发了」时先查控制器 PB 语义，别查 L2CAP/ATT——`Num_Completed_Packets` 正常会制造「已发送」的假象；② 0b11 在规范里只是「对端可直接刷新」的提示，控制器丢弃是合法实现，所以在别的 dongle 上不复现（旧座架 CSR8510/AX201 一直 PASS 就是没踩到）；③ 验证时只改一个自变量：同一 PDU、同一对 dongle，只切 PB 位。
- **回归测试**：`tests/unit/hci/test_controller.py::test_send_acl_data_fragments_to_the_le_buffer_size`（断言连续片 PB = `[0x02, 0x01, 0x01]`）。真机 `GATT/SR/GAC/BV-01-C` attempt 1 **PASS**（2026-10-31）。

### Q: PTS GATT/SR/GAS/BV-02-C（Database Hash）稳定 FAIL——verdict 里 "Received 2B2A-…" 与 "calculated 3968-…" 恰好互为字节反转 → A: ① BTP ADD_INCLUDED_SERVICE 从未落成 0x2802 include（整个 secondary service 不在 PTS 的发现视图里）② Database Hash 特征值必须按 **LE 字节序**送出——AES-CMAC 输出是大端，要反转 / 修复提交（本 session，2026-10-31 PASS）

- **现象**：`GATT/SR/GAS/BV-02-C` 自 09-18 起持续 FAIL。PTS 的 verdict 行里两个值恰好互为字节反转：`Received database hash value: 2B2A-C9D3-…` vs `calculated database hash value: 3968-6A9F-…`。本地对 PTS 自己 dump 的 37 行 `Handle XXXX Data` 做 CMAC，得到的正是 `3968-6A9F-…`（318 字节）——**算法和输入集合都已自洽**，问题只在字节序。
- **校准显示约定（关键方法）**：PTS XML 的 `AttrValue=` 字段是**线上字节的反序**。用一条已知值的声明校准：include 声明线上 `01001E0040AA`，XML 写 `AttrValue=AA40001E0001`；特征声明线上 `0A220050AA`，XML 写 `AA5000220A`。据此可知哈希的线上值其实是 `3968…`（PTS 按 LE 解析 128 位值、再按 BE 显示，才出现 `2B2A…`）。
- **根因 1（include 缺失）**：`ADD_INCLUDED_SERVICE` 只记录、不落库 → 线上 db 里没有 0x2802 include → 客户端只能经 include 到达 secondary service，于是整个 `0x0001–0x001D` 不在 PTS 的发现视图里，PTS 算 hash 的输入集合比我们少一截。（修复：`ServiceDefinition.includes` + `IncludeDefinition`，`GATTServer.add_service` 在服务声明之后、首个特征之前写 0x2802；BTP START_SERVER 把动态 include 目标映射成真实 handle。修后 PTS 的 37 行 dump 覆盖全部 66 个属性。）
- **根因 2（字节序，决定性）**：Core Vol 3 Part F §3.3.1 —— 多字节特征值除特别声明外一律 **LE**；而 AES-CMAC 输出是 **BE**。zephyr 的实现直接把结论写在注释里：`sys_mem_swap(db_hash.hash, 16)`，"PTS expects hash to be in little endianness as well … so we have to swap"。我们此前把 CMAC 原样存进 0x2B2A 特征 → 线上字节反了。
- **修法**：`AttributeDatabase.database_hash_value()` = `database_hash()[::-1]`；`_refresh_database_hash()` 存前者；`database_hash()` 保持原始 CMAC 以便对 Core 附录 B 向量（`F1CA2D48…A990`）比对。
- **验证**：真机 `GATT/SR/GAS/BV-02-C` **attempt 1 PASS**（两轮 received == calculated `3968-6A9F-55E4-835B-F823-23FA-D3C9-2A2B`）；回归 `GATT/SR/GAR/BV-01-C`、`GAW/BV-05-C`、`GAS/BV-01-C`、`GAC/BI-01-C` 全 PASS（GAC/BI-01 第 2 次过，peripheral flaky）。
- **回归测试**：`tests/unit/ble/test_gatt_database_hash.py::test_database_hash_value_is_the_little_endian_form_of_the_cmac`；`tests/unit/pts/btp/test_gatt_service.py::test_gatt_add_included_service_materialises_the_include_declaration`；`tests/unit/ble/test_gatt.py::test_gatt_server_add_service_emits_include_declaration`。
- **经验**：① **两个十六进制串互为字节反转 ≈ 大小端约定问题**，不是哈希算错——先去查 Core §3.3.x + 参考实现的那一行 swap；② 读 PTS XML 的原始字节字段前，先拿一个已知值的声明校准它是否反序显示（这次若不校准，会把「我们送对了」误判成「PTS 解析错」）；③ auto-pts 的 `ADD_*` BTP 命令「回了 SUCCESS」不等于「db 里有这个属性」——include 这种由 IUT 侧构建的属性必须落库到真实 GATTServer，否则发现视图静默缺块。

### Q: PTS GATT/SR/GAN/BV-01/03（CCCD 跨断连）里 non-bonded 那一条永远 PASS 不了 → A: ① `_persist_bond` 不看 Bonding_Flags，非 bonded 配对也落盘 ② 非 bonded 断连不重置 CCCD / 修复提交（本 session，2026-10-31）

- **GAN/BV-01-C（no bonding）**：TS step 5A 要求 LT 断连重连后读 CCCD = **0x0000**。Core Vol 3 Part H §2.3.4：只有任一方 Pairing Request/Response 的 **Bonding_Flags = 0x01** 时才保存密钥，双 0 时密钥只服务本连接。我们原来无条件 `storage.save_bond(...)` → 重连被当成 bonded → CCCD 保持 0x0001 → FAIL。修法：`_persist_bond` 用 `(local_auth_req | peer_auth_req) & 0x01` 判定，为 0 时只打 debug 日志、不落盘（`pairing_complete` 照常 resolve）。
- **CCCD 重置**：`GATTServer.remove_connection(conn_handle, *, bonded=True)` 新增 `bonded=False` 分支 → `reset_unbonded_cccd(...)` 把该连接写过的 CCCD 值复位为 0x0000，并清空其 indication 订阅与待补发的 Service Changed range。**没有 Service Changed 豁免**——初版曾豁免它（担心 GAS/BV-01/07 的补发），但 GATT.TS GAI/BV-01 step 7A.1 明确要求非 bonded 客户端重连后读 SC CCCD = **0x0000**（真机曾因此稳定 FAIL：「CCCD not set to 0x0000」）；GAS/BV-01/07 的 LT 是 **bonded** 的，根本不进这条路径。
- **同步/异步时序**：`Stack._handle_connection_event` 是同步的、bond 查询是异步的，所以要在 `remove_connection` **之前**快照 `connection_cccd_handles(handle)` 与 peer 地址，再 `asyncio.create_task(_reset_gatt_cccd_if_unbonded(...))`——晚一步 CCCD 值已被清，无从复位。
- **这个用例的另一半**：BTP `SET_VALUE (0x06)` 必须真的把新值推给 CCCD 订阅者（`GATTServer.update_attribute_value`），否则 `hdl_wid_92` 等的 0x1B 永不上空口（旧实现只改内存值 → 卡到 PTS TIMEOUT）；且 **handle 要先查已提交的 `server.db`、再回落 `_all_attrs`**——`hdl_wid_98` 会把 `GET_ATTRIBUTE_VALUE` 读到的 handle 原样喂回 SET_VALUE，而提交后的 db 与 BTP 建库表会漂移（`add_service` 自动补 CCCD、GAP/GATT 标准服务提交时才追加），只查 `_all_attrs` 时 GAI/BV-01-C 的 0x003B 直接 BTP ERROR（真机上该错误修掉后才暴露出下面的 CCCD 豁免问题）。
- **验证**：真机 `GATT/SR/GAN/BV-01-C`（27.6s）与 `GATT/SR/GAN/BV-03-C`（bonded 双胞胎，验证没有过度重置）均 **PASS**；回归 GAS/BV-01、GAS/BV-05、GAS/BV-07、GAD/BV-01、GAR/BV-01、GAW/BV-05 全 PASS（其中 GAS/BV-01、GAS/BV-07 各遇到一次 peripheral 连接 flake——两次都只走到 WID 1（prepare connectable）就判负、连一条 ATT 交互都没有，重跑即过，不是 CCCD 逻辑问题）；移除豁免后同日 `GAI/BV-01-C`（非 bonded）与 `GAI/BV-02-C`（bonded 双胞胎）**均 attempt 1 PASS**（2026-10-31）。
- **回归测试**：`tests/unit/ble/test_smp_bonding_flags.py`（双方 bonded / 双方 non-bonded / 单方请求 bonding 三例）、`tests/unit/ble/test_gatt.py`（非 bonded 复位含 SC CCCD、bonded 保留 SC CCCD/订阅/pending、`update_attribute_value`）、`tests/unit/test_stack.py`（断连异步复位路径）。

### Q: PTS GAP/DISC 全部「**不应**发现」负例（GENP/BV-03/04/05 + LIMP/BV-02/03/04/05）FAIL/INDCSV——LT 明明不可发现，IUT 却报 DEVICE_FOUND → A: **discovery ≠ raw scan**：`_on_scan_result` 从不过滤 AD Flags 的 discoverable mode / 修复提交（本 session，2026-11-03，7/7 首跑 PASS）

- **根因**：GAP 的 discovery 规程不是裸扫描——IUT 只能上报「AD Flags 把它标成当前模式下可发现」的设备（Core Vol 3 Part C §9.3；DISC 组 TS 注释："Discover … means to report to the application layer and/or verify the Flags AD type presence and setting"）。我们的 `GapService._on_scan_result` 把**每一条**广告报告都转成 DEVICE_FOUND，于是负例里 LT 的「不可发现」广播（Flags 只有 BR/EDR-not-supported=0x04）也被报上去 → 「confirm PTS is NOT discovered」步骤必挂。
- **修法**：`START_DISCOVERY (0x0c)` 按 auto-pts 的 `GAP_DISCOVERY_FLAG_*` 记 `_discovery_mode`（`LE_OBSERVE=0x10`→observe / `LIMITED=0x04`→limited / 否则 general），`_on_scan_result` 在非 observe 模式下先解 on-air EIR 的 Flags AD（type 0x01）再过滤：**general 只报 0x02|0x01，limited 只报 0x01，observe 全报**。新增 `_ad_flags_from_eir` 走 `[len][type][data]` 结构，**没有 Flags 结构 = 不在任何 discoverable mode = 不上报**（返回 0）。
- **别踩**：① 过滤必须只加在 discovery 路径，**OBSV 观察用例是裸扫描、绝不能过滤**（`BROB/OBSV/BV-05` 靠合并后的完整 EIR 判，见那条）；② 改完之后 `tests/unit/pts/btp/test_gap_events.py` 里三个「地址字节序 / RPA 解析」用例会红——它们的 fake EIR 是空的，被新过滤器正当丢弃；把 fixture 补成 `b"\x02\x01\x02"`（General Discoverable）即可，**别为了保测试去放宽过滤器**。
- **真机**：7 例全部 **attempt 1 PASS**（2026-11-03，BE200 rig）。
- **回归测试**：`tests/unit/pts/btp/test_gap_discovery.py`（6 例：Flags 提取、general 丢 0x04、general 报 0x02+0x01、limited 丢 0x02、limited 报 0x01、observe 全报）。

### Q: `pts_retry_cases.sh` 把「PTS 已判 PASS、client 却记 BTP TIMEOUT/ERROR」的用例反复重跑 → A: 收割时以 per-case log 的 `PTS_LOGTYPE_FINAL_VERDICT` 覆盖 client summary / 本 session（2026-11-03）

- **现象**：`GAP/SEC/AUT/BV-17/18/26` 在矩阵里长期 inconc，实际 PTS 早判 PASS——retry 脚本只看 autoptsclient 的 summary，于是无限重试一个已经通过的用例。
- **修法**：新增 `scripts/pts_case_verdict.py`（复用 `pts_collect_verdicts._extract_verdict`），`pts_retry_cases.sh` 每次 attempt 后读当次 case log 的 FINAL_VERDICT，**非空就与 client verdict 不同时以 PTS 为准**并打一行 `PTS verdict X overrides client summary Y`。**ACEP 类尤其要看这条**：PTS 判完后 connect 重试耗尽照样让 client 记 BTP ERROR。
- **回归测试**：`tests/unit/scripts/test_pts_case_verdict.py`（FINAL_VERDICT 胜过 client abort、INDCSV→INCONC、无 FINAL_VERDICT 返回 None）。

### Q: 2026-11 BE200 上 privacy/ACEP 用例 WID 400 一串 `0x0C`（resolution 双向 + `LE_Set_Random_Address`）→ A: ① `program_private_address`/`prepare_auto_connection` 对**已开启**的 resolution 再 enable 一次（冗余 toggle 被拒）② **剩下的 FAIL 不是这个 bug** / 本 session（2026-11-03）

- **已修**：两处都改成 `if not privacy._resolution_enabled: await set_address_resolution(True)`；`prepare_auto_connection` 另外**复用已编程的同 IRK RPA**（`_current_address`/`_irk` 命中就不再写地址——写地址要先关 resolution，而这个固件两个方向都 0x0C）。回归测试 `tests/unit/pts/test_actions_privacy.py`、`test_actions_acep.py`（复用 RPA / 仅在关闭时 enable）。
- **⚠️ 但 `GAP/CONN/ACEP/BV-03/04`、`GAP/PRIV/CONN/BV-11` 修后仍 PTS FINAL_VERDICT FAIL**：签名是「connect 到 LT identity `FC:9E:53:D5:8D:EB` 永不 establish」，和 8c2e983 那条 **SEM reconnect 的连接侧固件怪癖同族**（地址解析开 + 对端用**公开身份**广播 → initiator 永不完成）。ACEP/PRIV 与 SEM 的差别在于**它们必须开 resolution 来解 RPA**，所以不能照搬「关掉解析」的修法。**候选方向（未实装）**：host 预铸 RPA + `own_address_type=0x01`（ACEP/BV-04 早就证明 0x02 会回落 identity），对端是公开身份时不开 controller resolution。
- **`GAP/BROB/BCST/BV-05` 修后不再在 WID 400 炸 BTP ERROR**，能跑到 WID 1000，但 240s 内无 verdict（LT 不认我们的 RPA 广播），仍是 RPA 簇未决项。
- **顺带定性**：`program_private_address` 在**resolving list 为空**时 enable resolution 也吃 0x0C——纯广播 RPA 用例不需要开 resolution，这条拒绝是良性的（RPA 照样编程、广播照样起来），别把它当 verdict 的根因去修。

### Q: PTS SM 自中止负例（JW/BI-06 反射、EKS、SCPK/BI 等）明明按 spec 中止了，WID 175 却答 No → A: `_spawn_pair` 把 PAIRING_FAILED 的 reason **写死成 0x05** / 修复提交（本 session，2026-11-03，JW/BI-06 首跑 PASS）

- **现象**：`SM/CEN/JW/BI-06-C` INDCSV。IUT 日志 `SMP pairing failed handle=0x0800 reason=4`（反射检测**正确**触发 Confirm Value Failed），BTP 也**发了** `BTP_GAP_EV_PAIRING_FAILED (0x8c)`，但 PTS 的 WID 175「confirm that IUT reports the **Confirm Value Failed**」仍判负。
- **根因**：`GAP _spawn_pair._run` 的 except 分支 `self.on_pairing_failed(..., reason=0x05)`——**常数**。而 auto-pts 的 `hdl_wid_175` 是 `if reason == defs.BTP_SMP_PAIR_FAIL_REASON_CONFIRM_VALUE_FAILED` 才 True；报 0x05 等于「IUT 做对了却报错了理由」。**事件发出去了 ≠ 事件内容对**——这是「IUT 状态变了但没推 event」家族的变体：推了 event 但字段被简化成常数。
- **修法**：`_on_failed` 把 reason 挂到 `RuntimeError` 的 `.reason` 属性上（`exc.reason = reason`），`_spawn_pair` 读 `getattr(exc, "reason", None)`、缺失才回落 0x05。一次修复覆盖**所有** initiator 自中止负例（反射 0x04 / EKS 0x06 / DHKey 0x0B / SC confirm 0x04…），不是只修 JW/BI-06。
- **回归测试**：`tests/unit/ble/test_smp_jw_reflection.py::test_on_failed_attaches_the_reason_to_the_pairing_exception`（异常带 reason）；`tests/unit/pts/btp/test_gap_service.py::test_pair_async_failure_reports_the_smp_reason_not_a_constant`（BTP 事件末字节 = 0x04，不是 0x05）。
- **真机**：`SM/CEN/JW/BI-06-C` **attempt 1 PASS**（2026-11-03，原 2 连 INDCSV）。

### Q: PTS `SM/PER/PKE/BV-05-C` 连上 2s 就被 LT 断（0x13）、`SMP pairing failed reason=None` → A: **TS Table 4.3 要求这一例的 Pairing Response 带 MITM=1，而我们的 responder 纯 mirror 对端的 0**；responder 改为「peer MITM OR per-case config」/ 修复已实装（2026-11-04）

- **TS 原文**（`docs/spec_download/Core Test Suites/sm_ts_p26_pdf.pdf` idx 25-26，§4.5.2.1）：BV-05 与 BV-06 是**同一 Test Purpose 的两个变体**，区别只有 Table 4.3 的一列——**BV-05（v6.1 or earlier）要求 IUT 响应 MITM=1，BV-06（v6.2 or later）要求 MITM=0**；LT 的请求两边都是 `NoInputNoOutput + bonding=00 + MITM=0`。Pass 判据就一句「In Step 2b, the IUT sets the MITM flag as specified in Table 4.3」（另允许回 Pairing Failed `Authentication Requirements`）。
- **与实测完全对上**：BV-06 在同座架 PASS（响应 mirror→0 正合要求）；BV-05 连上 ~2s 被 LT 断、IUT 无 SEC_LEVEL_CHANGED。日志里的 `SMP pairing failed handle=... reason=None` 来自 `_smp_state.py::_on_failed(send_failed=False)`——**DISCONNECTED 转移**（对端断链时没有 reason 可带），不是配对逻辑自己出错，别再拿它当 crypto bug 查。
- **为什么不能随手改回「responder 也 OR config.mitm_required」**：KDU/BV-08 + PKE/BV-06 的 mirror 修复正是靠「忽略全局 `gap_set_mitm_on`」才过的，改回去这两例立刻回归。**需要 per-case 分流**：BV-05 要 force MITM=1、BV-06/08 要 mirror。
- **修法（per-case 分流，2026-11-04 已实装）**：`sm.py` 把全局 `gap_set_mitm_on` 从共享 pre_conditions 拆成 per-case——CEN 发起方用例保留、PER 默认不给、仅 BV-05 单独给；`_smp_state.py` 的 responder 恢复「**peer MITM OR config.mitm_required**」。因此 BV-05 响应强制 MITM=1，而 BV-06/KDU-BV-08 在 config 关闭时仍纯 mirror，不会回归。不要拿 io_cap 当安全强制开关（会误伤 SEM 的 keyboard_display 用例）。
- **回归测试**：`tests/unit/ble/test_smp_responder_mitm_mirror.py`（config 关时 mirror、config 开时强制、对端置位时 mirror）；`tests/unit/auto_pts_project/test_profile_modules.py::test_sm_mitm_is_per_case_not_global`（CEN + BV-05 开，BV-06/KDU-BV-08/PER-JW 关）。
- **经验**：① 同一 Test Purpose 的「版本变体」用例（v6.1/v6.2、v6.2/v6.3）经常只差**一个 bit**，而且常常是「我们后来为另一例修的行为」正好把它打反——判 INDCSV 先翻 TS 的 Test Case Configuration 表；② 「连上 2s 被断 + reason=None」= **LT 在 feature exchange 阶段就不满意**，去比对 Pairing Request/Response 的 auth_req，而不是往 phase-2/加密里找。

### Q: PTS GAP/SEC/SEM/BV-41+BV-43（SC-only **level 2**，Central）FAIL——IUT 发完 Public Key 就被 LT 断 → A: **`sc_only_mode` 在 initiator 里无条件下 MITM**，而 level 2 的 LT 明确不要 MITM / 修复提交（本 session，2026-11-04，两例首跑 PASS）

- **空口定案**（PTS 侧 `HciLogs.txt`，比 IUT log 便宜且是 LT 视角）：IUT 的 Pairing Request = `01 00 00 0d 10 07 07`（**MITM=1**），LT 的 Pairing Response = `02 04 00 09 10 00 00`（**无 MITM**）→ 我方选 passkey display、LT 选 Just Works → LT 在收到 Public Key 后 `HCI_Disconnect(0x13)`。BTP 层其实**收到过** `SET_MITM(0)`（upstream `hdl_wid_224` 就是 `gap_set_mitm_off()`），所以问题不在 WID 接线，而在 SMP 里那段「SC-only 强制 MITM」把它覆盖了。
- **TS 结构（关键）**：GAP.TS Table 4.17/4.18 把 SC-only 用例成对给出——**BV-41/43 = level 2（unauthenticated，不得带 MITM）**，**BV-42/44 = level 3**，**BV-28/29 = level 4**（都要 MITM）。当年为 BV-42 加的「SC-only ⇒ authenticated」一刀切，正好把 level 2 的双胞胎打反。**SC-only 约束的是 SC 位，不是 MITM 位。**
- **修法**：删掉 `_initiator_send_pairing_request` 的 sc_only 强制块；`pybluehost_iut/gap.py` 新增 `sc_only_auth_extra`（= sc_only + `gap_set_mitm_on`）只给 BV-28/29/42/44/64/67，BV-41/43 保持 `sc_only_extra`（MITM 由 WID 224 关掉）。**⚠️ BV-64/67 是 level 4 且走 WID 226（upstream 不 set MITM），第一版漏了它们 → 两例立刻 INDCSV（WID 2000 等不到 passkey），补上后首跑 PASS。凡删一个「隐式强制」，先把所有靠它吃饭的用例列全。**
- **回归测试**：`tests/unit/ble/test_smp_sc_only.py::test_sc_only_initiator_request_does_not_force_mitm` / `..._honours_config_mitm`；`tests/unit/auto_pts_project/test_profile_modules.py::test_gap_sc_only_cases_enable_mitm_only_for_level_3_and_4`（per-case 注册钉死四个要 MITM、两个不要）。
- **真机**：BV-41/43/42/44 **全部首跑 PASS**（2026-11-04）；回归 BV-28/29 PASS，BV-64/67 补上 per-case MITM 后也 PASS。
- **方法**：「该过的 level 3 过了、level 2 反而挂」这种成对分裂，直接去读 TS 的 Test Case Configuration 表——两例往往只差一个 bit，而那一 bit 多半是我们为 sibling 加的强制逻辑。
### Q: PTS L2CAP/COS/CED/BI-13/16/17（畸形 C-frame 负例）FAIL——IUT 居然**接受**了畸形连接请求 → A: 解码器按 `data[4:4+length]` 切出命令体，**PDU 里剩余的垃圾字节被静默丢掉**；新增整帧校验 + 多命令拆分，畸形即整帧 COMMAND_REJECT / 修复提交（本 session，2026-11-04）

- **空口（BI-13）**：LT 发 `0x14`(LE CoC Conn Req) 头部 Data Length=**10**，但 PDU 里实际有 **11** 字节（多一个 0x00）；我们回了**合法的** `0x15 result=0` 接受 → LT 直接断 ACL 判 FAIL。TS §4.4.1.4/4.4.1.6 的合法出路是「断链 / 不回复 / **COMMAND_REJECT** / 其它响应（告警）」，而这版 PTS 把「接受了畸形请求」判成 FAIL——所以不能再靠「解码器宽容」混过去。
- **根因**：`decode_le_signaling` 取 `body = data[4:4+length]`，length 之外的余量既不校验也不报；`LECreditBasedConnectionRequest.decode` 虽然要求恰好 10 字节，但它拿到的已经是被切齐的 10 字节，**校验形同虚设**。BI-16/17 则是「一个 PDU 装两条命令、第二条被截断」，我们原本只分发第一条。
- **修法**：`L2CAPManager._on_le_signaling_frame`（`_on_le_signaling_safe` 现在调它）先把整个 C-frame 按命令边界走一遍——**任何**一条命令截断、或帧尾不是命令边界，就整帧回 `COMMAND_REJECT_RSP reason=0x0000`，一条都不执行；全部合规则**逐条分发**（合法多命令同帧不再被丢第二条，正面测试锁住）。
- **回归测试**：`tests/unit/l2cap/test_le_signaling_dispatch.py::test_extra_trailing_octet_after_a_valid_command_is_rejected` / `..._truncated_second_command_rejects_the_whole_pdu` / `..._truncated_disconnection_request_as_second_command_is_rejected` / `test_two_wellformed_commands_in_one_pdu_are_both_dispatched`。
- **真机**：BI-13/16/17 **全部 attempt 1 PASS**（2026-11-04）；同批回归 `L2CAP/LE/REJ/BI-02-C`、`L2CAP/LE/CFC/BV-02-C`、`L2CAP/ECFC/BV-11-C` 也全部 PASS，合法命令分发无回归。
- **经验**：**「decoder 内部的长度校验」只有在切片之前做才有意义**——先按对端声明的长度切齐再校验，永远测不出「多给了字节」。凡是定长命令的协议，都要在帧层校验「命令流恰好耗尽 PDU」。


### Q: PTS RPA 广播 / ACEP 在「配对后才开 privacy」或 5 秒轮换边界失败 → A: ① 保留断连前的 peer 以补编 bonded IRK ② 出向连接期间停止 host RPA 轮换 ③ 普通 privacy 连接的 InitA 也要用 RPA / 本 session（2026-11-04）

- **BCST/BV-05 的时序**：它先在公开身份链路上配对并断连，**之后**才要求 RPA 广播；`connect()`/`pair()` 当时 privacy 尚未激活，resolving list 被合理跳过。`IutSession.last_peer` 现在跨断连保留 peer，`program_private_address(resolvable=True)` 在 privacy 真正开启后补调 `_prepare_rpa_resolution(last_peer)`，否则 accept list 里的 LT identity 匹配不到它 SCAN_REQ 的 RPA，IUT 永远不回扫描响应。
- **ACEP 的 peer IRK 不能用全零占位**：当前 LT 用 preamble 配对分发的随机 IRK 铸自己的 RPA。`prepare_auto_connection()` 现在优先读 bond 的 IRK，仅无 bond 时回退全零；先写错的全零条目是有害的——后续同 identity 的 bond-aware add 会因重复条目被拒，无法纠正。
- **BE200 的轮换竞态**：`SET_PRIVACY` 启动的 5 秒 host RPA rotation 会在 resolving-list 编程或 initiating 期间改地址，整串 HCI 命令回 `0x0C`。`prepare_auto_connection()` 与普通出向 `IutActions.connect()` 现在先 `stop_rotation()`；广播用例不走这条 central-only 路径，轮换不受影响。
- **PRIV/CONN/BV-11（Central）**：补上 `rpa_observe_extra` 前置以真的执行 `SET_PRIVACY`；BTP GAP CONNECT 在 privacy 开启时统一传 `own_address_type=0x01`（使用 host 已编程 RPA），不再仅 ACEP 特例。LT 会检查 CONNECT_IND 的 **InitA** 是否为 RPA，公开身份会被静默忽略。
- **回归测试**：`tests/unit/pts/test_actions_privacy.py::test_rpa_activation_after_bonded_disconnect_programs_the_peer_irk` / `test_outgoing_connect_stops_rpa_rotation_before_resolution_setup`；`tests/unit/pts/test_actions_acep.py::test_prepare_auto_connection_programs_rpa_list_and_resolution` / `test_prepare_auto_connection_stops_rotation_before_hci_setup`；`tests/unit/pts/btp/test_gap_service.py` 的 privacy CONNECT 地址类型断言。
- **真机**：ACEP/BV-01 与 PRIV/CONN/BV-10 均 attempt 1 PASS（2026-11-04）；ACEP/BV-03/04 与 PRIV/CONN/BV-11 的本轮复验结果见矩阵。

### Q: PTS GAP/SEC/AUT/BV-25 被 IUT 自主重连抢跑 → A: 「peer abort 配对后断连」不是可靠的自主重连指纹，删除该分支，重连交回 WID 脚本 / 本 session（2026-11-04）

- **根因**：BV-27 与 BV-25 都会出现「preamble 后 LT 发 Pairing Failed → 断连」的同一空口形状。此前为 BV-27 加的 `_peer_aborted_pairings` 门控仍无法区分二者，自主重连会抢占 BV-25 的 WID connect，导致其停滞。
- **修法**：删除断连 handler 里的通用 peer-abort 自主重连；**明确由我方 bond-resume 被拒触发的 reconnect-and-repair 保留**，那是自己的恢复事务，不与这个模糊指纹混用。
- **真机**：BV-25 attempt 1 PASS（2026-11-04）。BV-27 不再借这条不可靠指纹做隐式重连，不能沿用旧条目中「重连特性保留」的结论。
- **回归测试**：`tests/unit/test_stack_auto_encrypt.py::test_central_peer_abort_drop_does_not_autoreconnect`。

### Q: PTS GAP/SEC/AUT/BV-19 legacy 重配对停在 STK_ENCRYPTING，Phase 3 密钥分发被 defer 到超时 → A: 已加密链路上重配对成功事件是 HCI **Encryption Key Refresh Complete (0x30)**，不是 Encryption Change (0x08) / 本 session（2026-11-04）

- **空口/日志**：第二轮 legacy pairing 的 confirm/random 已完成，`LE_Start_Encryption status=0` 后控制器上报 **0x30**；SMP 没收到加密成功通知，于是一直停在 `STK_ENCRYPTING`，把 ENCRYPTION_INFO / MASTER_IDENT 推迟到 Pairing Failed 0x08。
- **修法**：`HCIController` 将 0x30 路由到同一 encryption listener。其 payload 只有 `status + connection_handle`，**没有 Encryption_Enabled 字节**；成功时合成 `enabled=1`。0x08 的原有布局不变。
- **回归测试**：`tests/unit/hci/test_controller.py::test_encryption_key_refresh_complete_advances_encryption_listeners`（原始 3 字节事件参数驱动真实 listener）。
- **经验**：不要把「链路已加密时重新配对」当作只会收到 0x08；凡是 SMP 卡在 `STK_ENCRYPTING` 且 `LE_Start_Encryption` 已成功，先找 0x30。

### Q: PTS L2CAP/LE/CFC/BV-29 的合法 0x15 响应已到，却被报「no response」→ A: BTP CONNECT 的 100 ms 优化窗口在 Windows/USB 调度下提前删除 pending future；恢复 manager 的 **1 秒 RTX** 窗口 / 本 session（2026-11-04）

- **决定性对照**：PTS HciLogs 显示 LT 在 **16–18 ms** 已回合法 `0x15`；IUT log 却是先 `within 0.1s (transaction abandoned)`，随后才 `LE signaling RX ... id=1`。这不是对端不应答，而是响应到达 asyncio 分发前事务已被取消。
- **修法**：`pts/btp/services/l2cap.py::_CONNECT_WINDOW_S = 1.0`，与 `L2CAPManager.LE_CONNECT_RTX_INTERVAL` 一致；请求仍只发一次、不重传。不要为加速 COS/CED/BI-29 的无效 identifier 轮次再缩短这个公共 CONNECT 窗口——BI-29 已独立定案为 LT DCID 64 值耗尽，缩短窗口救不了它，却会误杀正常连接。
- **回归测试**：`tests/unit/pts/btp/test_l2cap_connect.py::test_connect_tolerates_a_response_delayed_beyond_100ms`（200 ms 响应仍成功）。本轮前两次硬件 FAIL 的 IUT log 都仍打印 `within 0.1s`，确认跑的是修改前代码，不能当修复无效。


### Q: PTS ACEP 配对成功后自动连接失败，LT 添加 resolving-list 条目回 0x12 → A: SMP 把连接的临时 RPA 当成 Identity Address 分发 / 2026-11-04

- **证据**：ACEP/BV-04 的 LT `HciLogs.txt` 中，IUT 发送 `Identity Address Information = 09 01 46ccf72dec5c`，正是该连接的 RPA；LT 随后以这个地址发 `LE_Add_Device_To_Resolving_List`，控制器回 **0x12 Invalid HCI Command Parameters**。RPA 不是合法的 public/static identity。
- **修法**：`SMPPairingContext.local_address` 保留连接的 on-air 地址（c1/f5/f6 需要它）；新增 `local_identity_address` 从 `SMPManager` 的稳定本机地址赋值，Phase 3 的 IdKey 地址使用它。initiator/responder 两个上下文创建点都赋值。
- **纪律**：配对计算里的地址与分发的身份地址是两种语义，不能复用一个字段。此前为隐私配对修复 f5/f6 的 RPA 输入是正确的，但把相同字段直接用在 IdKey 分发会破坏后续隐私重连。
- **回归测试**：`tests/unit/ble/test_smp_local_address.py::test_phase3_distributes_identity_instead_of_link_rpa` 覆盖 public/static identity × initiator/responder 四种组合，同时断言 f5/f6 仍用 RPA。修前四例全部失败，修后通过。

### Q: 27 个 `blocked` 用例能不能换个 IUT 实现翻正？→ A: **已用 BlueZ 5.87 + auto-pts 交叉验证：零 PASS，无一条 blocked 被推翻；且 19 例在 BlueZ 上结构性不可对照** / 2026-11-07

- **做法**：BE200 经 `usbipd attach --wsl` 交给 WSL 里的 BlueZ(`14bd6ab`, btpclient 5.87)，用 `autoptsclient-bluez.py` 跑 22 个可驱动的 blocked 用例（单例单 client 会话，顺序 16:15→17:12）。
- **结果**：**22 例零 PASS**。5 × PTS TIMEOUT、1 × FAIL、14 × BTP ERROR、1 × FATAL ERROR、1 × `timeout 420` 杀掉无 verdict。
- **8 例「与 blocked 一致」**（BlueZ 到达同一阶段并同样失败）：`AUT/BV-27`、`SEM/BV-45`、`OBSV/BV-06`、`DCON/BV-04`、`PASE/BV-05`、`PASE/BV-06`、`PAST/BV-02`、`SM/PER/SCPK/BI-05`。**其中 SCPK/BI-05 的签名与 PyBlueHost 笔记逐字相同**——`Timeout ... self.passkey.data` → `TypeError: int() ... not 'NoneType'` → FATAL，证明那是 auto-pts 侧缺陷而非本栈问题。
- **19 例不可对照（btpclient 能力边界，这是本条最有复用价值的结论）**：BlueZ 的 `client/btpclient/gap.c` 只注册约 20 个 opcode，`grep -rniE "padv|periodic|create_sync"` **零命中**；`gatt.c` 是 client-only（无 server opcode、无 `FIND_INCLUDED_SVCS`）；`core.c` 不注册 L2CAP service。因此 PADV(8)、BIS(2)、L2CAP(2)、GATT server(3)、`SEM/BV-23`、`AUT/BV-13/14`、`SEM/BI-13`、`SM/CEN/SCPK/BI-03` 都在 pre_condition 或首个用例步骤就 BTP ERROR，**跑不到签名所在阶段**——它们既未被确认也未被推翻。
- **纪律**：① **不要再花时间重跑 BlueZ** 来复核这批 blocked，结论已经定案（详细逐例表见 `docs/pts/results/2026-11-07-bluez-comparison.md`）；② 要真正复核那 19 例，得换**实现了对应 BTP service 的参考 IUT**（如 zephyr 的 `ptsprojects/zephyr`）或走 PTS 手动 workspace，BlueZ 的 btpclient 永远做不到；③ 判「换 IUT 能否翻正」之前，先查参考实现**有没有注册该用例所需的 BTP opcode**——参考实现的「跑不通」常常是能力缺失，而不是结论。

## 文件约定
| 路径 | 说明 |
|------|------|
| `pybluehost/<layer>/` | 各层实现代码 |
| `pybluehost/<layer>/__init__.py` | 导出该层公共 API |
| `tests/unit/<layer>/test_<module>.py` | 单元测试 |
| `tests/e2e/` | 端到端集成测试 |
| `tests/fakes/` | Fake SAP 实现（Plan 10 后可用） |
| `docs/superpowers/plans/` | Plan 文档，命名：`YYYY-MM-DD-planN-<name>.md` |
| `docs/superpowers/STATUS.md` | **唯一的项目状态真相来源** |

---

## 当前依赖

```toml
[project]
dependencies = ["pyyaml>=6.0"]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "pyserial-asyncio>=0.6",
]
```
