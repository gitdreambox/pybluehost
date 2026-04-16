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
