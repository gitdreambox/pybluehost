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

适合**完整自动化 + CI 接入**：

```bash
# IUT host 上起 BTP TCP 服务
pybluehost app pts-tester -t usb --listen=127.0.0.1:65103

# 另一台机器（或同机）跑 autoptsclient，--project-path 指向我们的 IUT 模块
autoptsclient --project pybluehost \
    --project-path /path/to/pybluehost/auto_pts_project \
    --server <windows-host>:65000 \
    --workspace /path/to/PTS-workspace \
    --test-cases GAP/
```

- BTP 协议层：`pybluehost/pts/btp/`（`protocol.py` 帧编解码 + `services/{base,core,gap,gatt,l2cap}.py` 四个 service + `tester.py` asyncio TCP server）
- IUT 模块（autoptsclient 加载的入口）：`auto_pts_project/pybluehost/`
  - `iutctl.py` — `iut_init()` spawn `pybluehost app pts-tester` 子进程 + 等 BTP READY；`iut_cleanup()` 拆掉。**子进程用 `sys.executable -m pybluehost` 起，所以 autoptsclient 和 PyBlueHost 必须装在同一 Python 环境**（或 PYTHONPATH 覆盖 PyBlueHost）；隔离 venv 的话子进程 `ModuleNotFoundError: pybluehost` 直接挂
  - `pics.py` — 按组从 `docs/pts/pics/*.draft.yaml` 加载 → `PICS_GAP / PICS_GATT / PICS_L2CAP / PICS_SMP / PICS_HCI` 等扁平 dict
  - `ixit.py` — 手写 IXIT_* 参数 dict；**operator 改这里的 `TSPX_bd_addr_iut`**
  - `wid/{gap,gatt,l2cap,sm}.py` — WID handler 适配器，默认继承上游 `wid.<group>` dispatch 字典；通过 `PYBLUEHOST_OVERRIDES` 列表加 PyBlueHost 特有覆盖（baseline 空）
- 操作员 README：[`auto_pts_project/pybluehost/README.md`](auto_pts_project/pybluehost/README.md)（含 quickstart + 真机 step-by-step + troubleshooting 表）
- BTP upstream 校准：曾多次发现 plan 跟 upstream auto-pts 的 opcode 编号有出入（详见 plan 顶部 banner）；**未来加新 BTP service 之前先 WebFetch 一遍 `https://raw.githubusercontent.com/auto-pts/auto-pts/master/doc/btp_<service>.txt` 对齐**。WebFetch 受限时备选：`gh api repos/auto-pts/auto-pts/contents/doc/btp_<service>.txt --jq .content | base64 -d`，或本地 `git clone https://github.com/auto-pts/auto-pts /tmp/auto-pts && cat /tmp/auto-pts/doc/btp_<service>.txt`

#### Phase 2 状态矩阵 + CI

- `scripts/pts_matrix.py`：管理 `docs/pts/results/matrix/<group>.yaml` 的 verdict（pass/fail/inconc/blocked/untested）+ 渲染 `docs/pts/results/SUMMARY.md`
- `scripts/ci_btp_smoke.py`：spawn pts-tester → 走 Core/GAP/GATT 命令序列做 plumbing 自检（不需要 PTS dongle）
- `.github/workflows/pts-virtual.yml`：每 push/PR 跑上面的 smoke + PTS 单测
- **真机 pass-rate** 留 operator：跑完一个 case 用 `python scripts/pts_matrix.py update docs/pts/results/matrix/<group>.yaml <case_id> --verdict=pass --last-run=YYYY-MM-DD --notes='…'` 录入

### v2.0 Classic Audio + v2.1 SCO 适配

A2DP / AVRCP / HFP / HSP 全实装。`pybluehost/profiles/classic/` 下：

- `a2dp.py` — A2DPSource / A2DPSink，用 `pybluehost/classic/avdtp/`（线协议）+ `pybluehost/audio/codec/sbc`（SBC 编解码，基于 BlueZ libsbc ctypes 绑定）
- `avrcp.py` — AVRCPController / AVRCPTarget，用 `pybluehost/classic/avctp/` + `pybluehost/classic/avrcp/`（**注意**：profile facade 在 `profiles/classic/avrcp.py`，线协议在 `classic/avrcp/` —— Plan C.3 把 AV* 三个包从顶层搬到 `classic/` 下）
- `hfp.py` / `hsp.py` — SLC + SCO link setup + CVSD/mSBC codec
- `_sco_loopback.py` — WAV-based SCO send/receive；`_sco_realtime.py`（v2.1 B.2 加）—— sounddevice 实时 mic/speaker
- `pybluehost/transport/usb/` 里的 Intel/Realtek 子类（v2.1 B.1）实现了 `prepare_for_sco(codec)` 自动切换 USB Alt Setting / 发 Realtek vendor cmd `0xFC8B`，所以 SCO 数据在 USB 上跑得通
- 集成 demo：`pybluehost app demo-phone` / `app demo-headphone` 在单进程里把 A2DP+AVRCP+HFP 三个 profile 串起来，配 `tests/e2e/test_integrated_demo.py`
- 操作员手册：[`docs/CLASSIC_AUDIO_E2E.md`](docs/CLASSIC_AUDIO_E2E.md)（含 adapter SCO quirk 矩阵）

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

---

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
