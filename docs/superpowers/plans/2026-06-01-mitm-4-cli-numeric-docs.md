# MITM-4: CLI 完善 + Numeric Comparison 交互 + 文档 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完善 `pybluehost app mitm` CLI（le/bredr/both、默认 btsnoop 命名、授权告警），实现 **Numeric Comparison 交互 delegate**（测试者在两侧确认），补全 `--clone-address` 在 LE/BR 的接线，并写 `docs/MITM.md` runbook（硬件选型、删旧 bond、SC 操作、btsnoop 查看）。

**Architecture:** 在 MITM-1/2/3 之上收口。`InteractiveNumericDelegate` 实现 `PairingDelegate.confirm_numeric`，从终端读 y/n，BLE 经 `ScPairing`、BR 经 `SspTermination(numeric=True)` 两条路径注入。`both` 模式同时跑 LE + BR 两套 `MitmRelay`（或一个支持双 mode 的编排）。仍**不导入**协议栈上层。

**Tech Stack:** MITM-1/2/3 全部模块、`pybluehost.cli._lifecycle`、argparse、asyncio。

**依赖前提（MITM-3 契约）：** `MitmRelay(pair, *, mode, target_addr, target_name, btsnoop, clone_address, delegate)`；`PairingDelegate.confirm_numeric(side_name, value)`；`AutoConfirmDelegate`。

---

## File Structure

| 文件 | 职责 |
|------|------|
| `pybluehost/cli/app/mitm/pairing/delegate.py` | 增 `InteractiveNumericDelegate`（终端确认） |
| `pybluehost/cli/app/mitm/cli.py` | 完善:both 模式、默认 btsnoop 名、pairing 选 delegate、授权告警 |
| `docs/MITM.md` | runbook |
| `tests/unit/mitm/pairing/test_delegate_interactive.py` | 交互 delegate（注入 fake input） |
| `tests/unit/mitm/test_cli_main.py` | CLI 参数 → MitmRelay 装配（mock 编排） |

---

## Task 1: Numeric Comparison 交互 delegate

**Files:**
- Modify: `pybluehost/cli/app/mitm/pairing/delegate.py`
- Test: `tests/unit/mitm/pairing/test_delegate_interactive.py`

- [ ] **Step 1: 写失败测试 —— 注入 input 回调,验证 y/n**

Create `tests/unit/mitm/pairing/test_delegate_interactive.py`:

```python
from pybluehost.cli.app.mitm.pairing.delegate import InteractiveNumericDelegate


async def test_interactive_accepts_yes():
    prompts = []

    async def fake_ask(prompt: str) -> str:
        prompts.append(prompt)
        return "y"

    d = InteractiveNumericDelegate(ask=fake_ask)
    assert await d.confirm_numeric("phone", 123456) is True
    assert "123456" in prompts[0]      # 数字展示给测试者
    assert "phone" in prompts[0]        # 标明哪一侧


async def test_interactive_rejects_no():
    async def fake_ask(prompt: str) -> str:
        return "n"

    d = InteractiveNumericDelegate(ask=fake_ask)
    assert await d.confirm_numeric("target", 654321) is False
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/unit/mitm/pairing/test_delegate_interactive.py -v`
Expected: FAIL — `ImportError: cannot import name 'InteractiveNumericDelegate'`

- [ ] **Step 3: 写实现 —— 追加到 `delegate.py`**

```python
import asyncio
from collections.abc import Awaitable, Callable


async def _default_ask(prompt: str) -> str:
    # 在 executor 线程读 stdin,避免阻塞 event loop
    return await asyncio.to_thread(input, prompt)


class InteractiveNumericDelegate:
    """Numeric Comparison:把数字打给测试者,在两侧分别确认 y/n。

    授权测试里两端都在你手上,即使两侧数字不同也可分别接受(见 spec §3.1)。
    """

    def __init__(self, ask: Callable[[str], Awaitable[str]] = _default_ask) -> None:
        self._ask = ask

    async def confirm_numeric(self, side_name: str, value: int) -> bool:
        answer = await self._ask(
            f"[MITM] {side_name} 侧数字比较值 = {value:06d}，确认配对? [y/N] "
        )
        return answer.strip().lower() in ("y", "yes")
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/unit/mitm/pairing/test_delegate_interactive.py -v`
Expected: PASS（2 个）

- [ ] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/pairing/delegate.py tests/unit/mitm/pairing/test_delegate_interactive.py
git commit -m "feat(mitm): InteractiveNumericDelegate —— Numeric Comparison 两侧确认"
```

---

## Task 2: CLI 完善（both 模式 + 默认 btsnoop 名 + delegate 选择 + 授权告警）

**Files:**
- Modify: `pybluehost/cli/app/mitm/cli.py`
- Test: `tests/unit/mitm/test_cli_main.py`

- [ ] **Step 1: 写失败测试 —— 参数装配出正确的 MitmRelay**

Create `tests/unit/mitm/test_cli_main.py`:

```python
import argparse

from pybluehost.cli.app.mitm.cli import build_relays_from_args, default_btsnoop_name
from pybluehost.cli.app.mitm.pairing.delegate import (
    AutoConfirmDelegate,
    InteractiveNumericDelegate,
)


def _args(**kw):
    base = dict(
        upstream="virtual", downstream="virtual", target="AA:BB:CC:DD:EE:FF",
        target_name=None, transport_mode="both", clone_address=False,
        btsnoop=None, pairing="just-works",
    )
    base.update(kw)
    return argparse.Namespace(**base)


def test_default_btsnoop_name_has_timestamp_and_ext():
    name = default_btsnoop_name()
    assert name.endswith(".btsnoop")
    assert "mitm" in name


def test_pairing_just_works_uses_auto_delegate():
    delegate = _select_delegate("just-works")  # 见实现导出
    assert isinstance(delegate, AutoConfirmDelegate)


def test_pairing_numeric_uses_interactive_delegate():
    delegate = _select_delegate("numeric")
    assert isinstance(delegate, InteractiveNumericDelegate)


def test_both_mode_builds_le_and_bredr_specs():
    specs = build_relays_from_args(_args(transport_mode="both"))
    modes = {s.mode for s in specs}
    assert modes == {"le", "bredr"}


def test_le_mode_builds_one():
    specs = build_relays_from_args(_args(transport_mode="le"))
    assert [s.mode for s in specs] == ["le"]
```

补充 import（实现里导出 `_select_delegate`）：在测试顶部加
`from pybluehost.cli.app.mitm.cli import _select_delegate`。

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/unit/mitm/test_cli_main.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: 写实现 —— 重构 `cli.py`**

在 `pybluehost/cli/app/mitm/cli.py` 增（保留 Task 1/MITM-2 的 `register_mitm_command`，扩展 `_mitm_main`）：

```python
from dataclasses import dataclass
from datetime import datetime

from pybluehost.cli.app.mitm.pairing.delegate import (
    AutoConfirmDelegate,
    InteractiveNumericDelegate,
)


@dataclass
class RelaySpec:
    mode: str  # "le" | "bredr"


def default_btsnoop_name() -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"mitm-{ts}.btsnoop"


def _select_delegate(pairing: str):
    if pairing == "numeric":
        return InteractiveNumericDelegate()
    return AutoConfirmDelegate()


def build_relays_from_args(args) -> list[RelaySpec]:
    if args.transport_mode == "both":
        return [RelaySpec("le"), RelaySpec("bredr")]
    return [RelaySpec(args.transport_mode)]
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/unit/mitm/test_cli_main.py -v`
Expected: PASS（5 个）

- [ ] **Step 5: 接 `_mitm_main`（both = 跑两套 MitmRelay）**

Replace `_mitm_main`:

```python
async def _mitm_main(args: argparse.Namespace) -> None:
    import asyncio as _asyncio

    from pybluehost.cli.app.mitm.controllers import open_controller_pair
    from pybluehost.cli.app.mitm.orchestrator import MitmRelay

    logger.warning("⚠ MITM 仅限授权测试:确保你对目标设备与手机均有合法授权。")
    btsnoop = args.btsnoop or default_btsnoop_name()
    delegate = _select_delegate(args.pairing)
    specs = build_relays_from_args(args)

    pair = await open_controller_pair(args.upstream, args.downstream)
    relays = [
        MitmRelay(
            pair, mode=s.mode, target_addr=args.target, target_name=args.target_name,
            btsnoop=btsnoop if len(specs) == 1 else f"{s.mode}-{btsnoop}",
            clone_address=args.clone_address, delegate=delegate,
        )
        for s in specs
    ]
    try:
        for r in relays:
            await r.run_recon()
            await r.run_impersonate()
        await _asyncio.gather(*(r.run_relay() for r in relays))
    finally:
        for r in relays:
            await r.teardown()
        await pair.close()
```

> 注：`both` 模式下 LE 与 BR 共用同一对 controller（一块芯片通常同时支持 LE+BR）。若实际需要分立 radio，可在执行时扩展为按 mode 各开一对 pair——本计划默认共用。

- [ ] **Step 6: 验证 CLI**

Run: `uv run pybluehost app mitm --help`
Expected: 帮助含 `--transport-mode {le,bredr,both}`、`--clone-address`、`--pairing`

- [ ] **Step 7: Commit**

```bash
git add pybluehost/cli/app/mitm/cli.py tests/unit/mitm/test_cli_main.py
git commit -m "feat(mitm): CLI both 模式 + 默认 btsnoop 名 + delegate 选择 + 授权告警"
```

---

## Task 3: runbook 文档 `docs/MITM.md`

**Files:**
- Create: `docs/MITM.md`

- [ ] **Step 1: 写 runbook**

Create `docs/MITM.md`:

```markdown
# MITM 透传应用 Runbook（授权测试专用）

> ⚠ **仅限授权场景**：使用前确保你对目标设备与手机均有合法测试授权。

## 用途
在目标设备与手机之间插入中间人，双向透传 BLE/BR ACL，抓包到 btsnoop。
详见设计 spec：`docs/superpowers/specs/2026-06-01-mitm-passthrough-design.md`。

## 硬件
- **两个 USB 适配器**：上游（连目标）任意；下游（伪装侧）默认任意。
- **仅当 `--clone-address` 且含 BR** 时，下游需可写 BD_ADDR：
  - 推荐 Broadcom BT4.0（Asus USB-BT400 / Plugable USB-BT4LE / IOGEAR GBU521），临时改址、掉电还原。
  - 备选正品 CSR8510（PSKEY，持久；假货多）。
  - Intel（OTP 锁死）、Realtek（不稳）不适合做伪装侧。

## 操作前提
- 手机若曾与真目标绑定，**先删手机上的旧配对记录**（避免缓存 LTK/IRK/link-key 冲突）。

## 运行
\`\`\`bash
# 默认:用自身地址 + 克隆应用层身份,Just Works,both(LE+BR)
pybluehost app mitm --upstream usb:vendor=intel --downstream usb:index=1 \
  --target AA:BB:CC:DD:EE:FF

# 只做 BLE + Numeric Comparison(两侧终端确认)
pybluehost app mitm --upstream usb --downstream usb:index=1 \
  --target-name "Watch" --transport-mode le --pairing numeric

# 地址锁定的重连场景:克隆目标地址(BR 需 Broadcom/CSR 下游)
pybluehost app mitm --upstream usb --downstream usb:index=1 \
  --target AA:BB:CC:DD:EE:FF --clone-address
\`\`\`

## Numeric Comparison
`--pairing numeric` 时，每侧会在终端打印 6 位数字并要求确认。授权测试中两端都在你手上，
即使两侧数字不同也可分别按 `y` 接受（原理见 spec §3.1）。

## 查看抓包
默认输出 `mitm-<时间戳>.btsnoop`（both 模式分 `le-` / `bredr-` 前缀）。用 Wireshark 打开，
或导入 Ellisys/PTS。方向标注 PHONE↔TARGET。

## 限制（v1）
- 只做透传 + 抓包；**改写（规则/hook）为后续阶段**。
- 配对仅 Just Works + Numeric Comparison（SC）；Passkey Entry / OOB / BLE legacy 后续。
- 抓包粒度 = L2CAP PDU；CoC 跨多帧的完整 SDU 不重组。
```

- [ ] **Step 2: 校验 markdown 渲染无明显错误**

Run: `uv run python -c "import pathlib; print('docs/MITM.md', pathlib.Path('docs/MITM.md').stat().st_size, 'bytes')"`
Expected: 打印文件大小 > 0

- [ ] **Step 3: Commit**

```bash
git add docs/MITM.md
git commit -m "docs(mitm): MITM 透传 runbook(硬件/删 bond/Numeric/btsnoop)"
```

---

## Task 4: 收尾 —— 全套测试 + STATUS.md + 系列完结

- [ ] **Step 1: 全套测试**

Run: `uv run pytest tests/ -q --transport=virtual`
Expected: 全部 PASS

- [ ] **Step 2: 确认协议栈零改动**

Run: `git diff --name-only $(git merge-base HEAD master)..HEAD | grep -E "pybluehost/(l2cap|ble|classic|gap\.py|profiles|stack\.py)" || echo "OK: 协议栈零改动"`
Expected: `OK: 协议栈零改动`

- [ ] **Step 3: 更新 STATUS.md（标记 MITM 系列完成）并 Commit**

追加表行：

```markdown
| MITM-4 | CLI 完善 + Numeric Comparison + 文档 | ✅ 完成 | [mitm-4](plans/2026-06-01-mitm-4-cli-numeric-docs.md) | `pybluehost/cli/app/mitm/cli.py`, `docs/MITM.md` |
```

并在 STATUS.md "快速定位" 区注明：MITM 透传应用（4 Plan）已完成，独立应用、协议栈零改动。

```bash
git add docs/superpowers/STATUS.md docs/superpowers/plans/2026-06-01-mitm-4-cli-numeric-docs.md
git commit -m "docs(progress): complete MITM-4 —— CLI + Numeric + runbook;MITM 系列完结"
```

---

## 完成标准

- `tests/unit/mitm/pairing/test_delegate_interactive.py`、`test_cli_main.py` PASS。
- `pybluehost app mitm --help` 显示完整选项；`--pairing numeric` 走交互 delegate。
- `docs/MITM.md` runbook 就位。
- `uv run pytest tests/ -q --transport=virtual` 全 PASS；协议栈层零改动。

## MITM 系列总结（4 Plan）

| Plan | 交付 |
|------|------|
| MITM-1 | 应用骨架 + ACL relay 核心（重组/分流/重分片）+ btsnoop capture |
| MITM-2 | BLE 路径 + app 内最小 SMP（SC Just Works）+ 虚拟三角 e2e |
| MITM-3 | BR/EDR 路径 + SSP 终结（HCI 事件）+ 可选改址 + VirtualClassicLink e2e |
| MITM-4 | CLI（le/bredr/both）+ Numeric Comparison 交互 + runbook |

**后续阶段**：改写能力（InterceptionPipeline + 规则 + hook）、Passkey Entry / OOB / BLE legacy、CoC/BR 完整 SDU 重组、真硬件双适配器验证。
