# Pytest Transport 选择机制实施计划

> **For agentic workers:** REQUIRED SUB-SKILL — Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Fresh subagent per task with two-stage review (spec + code quality). Steps use `- [ ]` syntax for tracking.
>
> **状态更新协议（强制）**：每完成一个 Step 后勾选 checkbox，每完成一个 Task 后更新 `docs/superpowers/STATUS.md`，并以 `docs(progress): ...` commit 提交（参考 `CLAUDE.md` 的"状态更新协议"）。
>
> **代码风格**：所有代码、docstring、注释使用英文；本计划的描述性文字使用中文。

| 项 | 值 |
|----|----|
| 状态 | 待执行 |
| 日期 | 2026-04-27 |
| 设计文档 | [pytest-transport-selection-design.md](../specs/pytest-transport-selection-design.md) |
| 任务数 | 23 |
| 预计耗时 | 8–10 小时 |

**Goal:** 让所有依赖 transport 的测试既能跑真硬件也能跑虚拟控制器；session 级 transport 选择统一通过 `--transport` / 环境变量 / 自动检测决定；同步完成 `loopback` → `virtual` 改名 + `LoopbackTransport` 内化为 `VirtualController` 私有实现，让"loopback"概念彻底退出公开 API。

**Architecture:** 在 `tests/conftest.py` 注册 session 级 fixture（`selected_transport_spec`、`selected_peer_spec`）一次性决定 transport；测试级 fixture（`stack`、`peer_stack`）按 spec 构造 `Stack`。新增 `Stack.from_usb()` / `Stack.from_uart()` 工厂、`USBTransport.list_devices()` 列举接口、`real_hardware_only` / `virtual_only` 标记。Task 1 先做表层改名（公开 API），Task 2 把 `LoopbackTransport` 内化为 `VirtualController._HCIPipe` 并新增 `VirtualController.create()`，后续 Task 全部基于新结构实现。

**Tech Stack:** Python 3.10+、pytest 8、pytest-asyncio (auto mode)、`pybluehost.stack.Stack`、`pybluehost.transport.usb.USBTransport`。

---

## 文件结构概览

**新增**

| 路径 | 职责 |
|------|------|
| `tests/_transport_select.py` | spec 解析、autodetect、第二适配器查找；`pytest.exit` 错误路径在此抛出 |
| `tests/_fallback_tracker.py` | session 级回落计数（提供 `mark_fallback()` / `count` / `is_fallback()`） |

**重命名**

| 旧路径 | 新路径 |
|--------|--------|
| `pybluehost/cli/_loopback_peer.py` | `pybluehost/cli/_virtual_peer.py` |
| `tests/unit/cli/test_loopback_peer.py` | `tests/unit/cli/test_virtual_peer.py` |

**删除**

| 路径 | 原因 |
|------|------|
| `pybluehost/transport/loopback.py` | pipe 内化到 `VirtualController._HCIPipe` |
| `tests/unit/transport/test_loopback.py` | 类已私有化，覆盖通过 `VirtualController` 测试与 e2e |

**修改**

| 路径 | 修改要点 |
|------|---------|
| `pybluehost/stack.py` | `Stack.loopback()` → `Stack.virtual()`；`StackMode.LOOPBACK` → `StackMode.VIRTUAL`；`virtual()` 函数体改用 `VirtualController.create()`；新增 `from_usb()` / `from_uart()` |
| `pybluehost/hci/virtual.py` | 新增 `VirtualController.create()` async classmethod；新增私有 `_HCIPipe` 类（接收原 `LoopbackTransport` 实现） |
| `pybluehost/transport/usb.py` | `auto_detect` 增加 `bus`/`address` 参数；新增 `list_devices()` 与 `DeviceCandidate` |
| `pybluehost/transport/__init__.py` | 移除 `LoopbackTransport` 导出 |
| `pybluehost/cli/_transport.py` | spec 值 `loopback` → `virtual`；`virtual` 分支改用 `VirtualController.create()`；`parse_transport_arg` 识别 `bus=` / `address=` |
| `pybluehost/cli/_virtual_peer.py` | 函数 `loopback_peer_with` → `virtual_peer_with`；docstring/字符串改名 |
| `pybluehost/cli/app/gatt_browser.py` | import + 函数名改名 |
| `tests/conftest.py` | 注册 hooks 与 fixtures |
| `tests/integration/conftest.py` | 清空（旧 fixture 是死代码） |
| `tests/e2e/conftest.py` | 替换为简单转发到顶层 `stack` |
| `tests/hardware/conftest.py` | 删除整个文件 |
| `tests/integration/test_hci_init.py` | 删 inline LoopbackTransport，使用 `stack` fixture |
| `tests/integration/test_hci_l2cap.py` | 同上 |
| `tests/unit/cli/test_app_*.py` （6 个） | 改名 + inline `Stack.virtual()` → `stack` fixture |
| `tests/unit/test_stack.py` | `Stack.loopback()` → `Stack.virtual()`；`StackMode.LOOPBACK` → `StackMode.VIRTUAL` |
| `tests/unit/cli/test_virtual_peer.py` | 函数引用更新 |
| `tests/hardware/test_usb_smoke.py` | 用 `stack` fixture + `real_hardware_only(transport="usb")` 标记 |
| `tests/hardware/test_intel_hw.py` | `pytest.mark.hardware` → `pytest.mark.real_hardware_only(transport="usb", vendor="intel")` |
| `pyproject.toml` | `markers` 列表替换 |
| `.github/workflows/test.yml` | 加 `--transport=virtual`；删除 `-m "not hardware"` |
| `README.md` | 加 transport 选项段落；CLI 用法 `--transport loopback` → `--transport virtual` |
| `CLAUDE.md` | 更新"常用测试命令" |

---

## Task 1: `loopback` → `virtual` 全栈改名

**Files:**
- Modify: `pybluehost/stack.py`
- Modify: `pybluehost/cli/_transport.py`
- Rename: `pybluehost/cli/_loopback_peer.py` → `pybluehost/cli/_virtual_peer.py`
- Modify: `pybluehost/cli/app/gatt_browser.py`
- Modify: `tests/unit/test_stack.py`
- Rename: `tests/unit/cli/test_loopback_peer.py` → `tests/unit/cli/test_virtual_peer.py`
- Modify: 6 个 `tests/unit/cli/test_app_*.py`
- Modify: `tests/e2e/conftest.py`

- [x] **Step 1.1: 改 `pybluehost/stack.py`**

替换 `StackMode` 枚举：
```python
class StackMode(str, Enum):
    LIVE = "live"
    VIRTUAL = "virtual"
    REPLAY = "replay"
```

把 `Stack` docstring 里的 `loopback()` 改为 `virtual()`：
```python
class Stack:
    """Top-level Bluetooth stack — assembles HCI, L2CAP, BLE, Classic, GAP.

    Use factory methods (``virtual()``, ``from_uart()``, etc.) to create.
    """
```

把 `Stack.loopback` classmethod 改名 + 函数体内枚举值更新：
```python
    @classmethod
    async def virtual(
        cls,
        config: StackConfig | None = None,
    ) -> Stack:
        """Create a single Stack backed by a software-emulated VirtualController.

        The host side talks to a VirtualController over an in-process
        LoopbackTransport pair. Use this when no real Bluetooth hardware
        is available.
        """
        from pybluehost.core.address import BDAddress
        from pybluehost.hci.virtual import VirtualController
        from pybluehost.transport.loopback import LoopbackTransport

        vc = VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:01"))
        host_t, ctrl_t = LoopbackTransport.pair()

        class _VCSink:
            async def on_transport_data(self, data: bytes) -> None:
                response = await vc.process(data)
                if response is not None and host_t._sink is not None:
                    await host_t._sink.on_transport_data(response)

        ctrl_t.set_sink(_VCSink())
        await host_t.open()
        await ctrl_t.open()

        stack = await cls._build(host_t, config, StackMode.VIRTUAL)
        stack._local_address = vc._address
        return stack
```

- [x] **Step 1.2: 改 `pybluehost/cli/_transport.py`**

替换 docstring 里的 `loopback` 描述为 `virtual`，并把分支条件改为 `s == "virtual"`：
```python
async def parse_transport_arg(s: str) -> Transport:
    """Parse a --transport CLI argument into a Transport instance.

    Formats:
        virtual                        → VirtualController + LoopbackTransport pair
        usb                            → USBTransport.auto_detect()
        usb:vendor=intel               → USBTransport.auto_detect(vendor="intel")
        uart:/dev/ttyUSB0              → UARTTransport(port=..., baudrate=115200)
        uart:/dev/ttyUSB0@921600       → UARTTransport(port=..., baudrate=921600)
    """
    if s == "virtual":
        from pybluehost.core.address import BDAddress
        from pybluehost.hci.virtual import VirtualController
        from pybluehost.transport.loopback import LoopbackTransport

        vc = VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:01"))
        host_t, ctrl_t = LoopbackTransport.pair()

        class _VCSink:
            async def on_transport_data(self, data: bytes) -> None:
                response = await vc.process(data)
                if response is not None and host_t._sink is not None:
                    await host_t._sink.on_transport_data(response)

        ctrl_t.set_sink(_VCSink())
        await host_t.open()
        await ctrl_t.open()
        return host_t

    # ... usb branch unchanged for now (Task 3 will extend it) ...

    raise ValueError(f"Unknown transport: {s!r}")
```

- [x] **Step 1.3: 重命名 `_loopback_peer.py` → `_virtual_peer.py` 并改函数名**

```bash
git mv pybluehost/cli/_loopback_peer.py pybluehost/cli/_virtual_peer.py
```

编辑 `pybluehost/cli/_virtual_peer.py`：把 `loopback_peer_with` 改名为 `virtual_peer_with`，模块 docstring 与函数 docstring 把 "loopback" 替换为 "virtual"，函数体里 `Stack.loopback()` 改为 `Stack.virtual()`：
```python
"""Virtual peer Stack for client-side commands without real hardware."""
from __future__ import annotations

from contextlib import asynccontextmanager

from pybluehost.stack import Stack


@asynccontextmanager
async def virtual_peer_with(server_factory):
    """Spin up a second Stack on a virtual controller to act as a peer.

    The yielded peer has its server objects populated by ``server_factory(peer)``.
    Use this for client-side CLI commands when no second hardware adapter is
    available.
    """
    peer = await Stack.virtual()
    try:
        await server_factory(peer)
        yield peer
    finally:
        await peer.close()
```

- [x] **Step 1.4: 更新 `pybluehost/cli/app/gatt_browser.py`**

```python
# old: from pybluehost.cli._loopback_peer import loopback_peer_with
from pybluehost.cli._virtual_peer import virtual_peer_with
```
搜索 `loopback_peer_with(` 并替换为 `virtual_peer_with(`。

- [x] **Step 1.5: 改 6 个 `tests/unit/cli/test_app_*.py`**

对每个文件替换：
```python
stack = await Stack.loopback()
```
为：
```python
stack = await Stack.virtual()
```

（Task 18 会进一步把它们改成 `stack` fixture，本步只做命名同步。）

- [x] **Step 1.6: 改 `tests/unit/test_stack.py`**

替换：
```python
StackMode.LOOPBACK == "loopback"     →  StackMode.VIRTUAL == "virtual"
Stack.loopback()                     →  Stack.virtual()
```

应同步更新断言：`stack.mode == StackMode.LOOPBACK` → `stack.mode == StackMode.VIRTUAL`。

- [x] **Step 1.7: 重命名 `test_loopback_peer.py` → `test_virtual_peer.py`**

```bash
git mv tests/unit/cli/test_loopback_peer.py tests/unit/cli/test_virtual_peer.py
```

编辑文件：替换所有 `loopback_peer_with` → `virtual_peer_with`；import 来源 `_loopback_peer` → `_virtual_peer`。

- [x] **Step 1.8: 改 `tests/e2e/conftest.py`**

```python
stack = await Stack.loopback(...)  →  stack = await Stack.virtual(...)
```

（Task 15 会清空此文件，但本步保持中间状态可运行。）

- [x] **Step 1.9: 全仓 grep 验证无残留**

```bash
grep -rn "Stack.loopback\|StackMode.LOOPBACK\|loopback_peer_with\|_loopback_peer" pybluehost/ tests/ --include="*.py"
```

Expected: 0 matches。

```bash
grep -rn '"loopback"' pybluehost/ tests/ --include="*.py"
```

Expected: 0 matches in production / test code (字符串字面量也已替换)。

- [x] **Step 1.10: 运行全套测试**

```bash
uv run pytest tests/ -q
```

Expected: 全部 PASS（与改名前等价行为）。

- [x] **Step 1.11: Commit**

```bash
git add -A
git commit -m "refactor: rename loopback -> virtual at the public API surface

- Stack.loopback() -> Stack.virtual()
- StackMode.LOOPBACK -> StackMode.VIRTUAL
- pybluehost/cli/_loopback_peer.py -> _virtual_peer.py
- loopback_peer_with -> virtual_peer_with
- CLI spec value 'loopback' -> 'virtual'
- Test file/usage rename

LoopbackTransport class still imported internally by Stack.virtual();
Task 2 will internalize it as VirtualController._HCIPipe."
```

---

## Task 2: 把 `LoopbackTransport` 内化为 `VirtualController._HCIPipe`

**Files:**
- Modify: `pybluehost/hci/virtual.py`
- Modify: `pybluehost/stack.py`
- Modify: `pybluehost/cli/_transport.py`
- Modify: `pybluehost/transport/__init__.py`
- Delete: `pybluehost/transport/loopback.py`
- Delete: `tests/unit/transport/test_loopback.py`
- Test: `tests/unit/hci/test_virtual_create.py`

- [x] **Step 2.1: Write failing test for `VirtualController.create()`**

```python
# tests/unit/hci/test_virtual_create.py
"""Tests for VirtualController.create() factory."""
from __future__ import annotations

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.hci.virtual import VirtualController
from pybluehost.transport.base import Transport


@pytest.mark.asyncio
async def test_create_returns_vc_and_open_host_transport():
    vc, host_t = await VirtualController.create()
    assert isinstance(vc, VirtualController)
    assert isinstance(host_t, Transport)
    assert host_t.is_open


@pytest.mark.asyncio
async def test_create_accepts_explicit_address():
    addr = BDAddress.from_string("11:22:33:44:55:66")
    vc, _ = await VirtualController.create(address=addr)
    assert vc._address == addr


@pytest.mark.asyncio
async def test_create_default_address_when_none():
    vc, _ = await VirtualController.create()
    assert vc._address is not None
    assert str(vc._address) != "00:00:00:00:00:00"


@pytest.mark.asyncio
async def test_host_transport_round_trip_through_vc():
    """Sending an HCI Reset command via host transport gets a Command Complete back."""
    vc, host_t = await VirtualController.create()

    received: list[bytes] = []

    class _Sink:
        async def on_transport_data(self, data: bytes) -> None:
            received.append(data)

    host_t.set_sink(_Sink())

    # HCI Reset: H4 type=0x01, opcode=0x0C03, param_len=0
    await host_t.send(b"\x01\x03\x0c\x00")

    # Allow the VC bridge to process and respond.
    import asyncio
    await asyncio.sleep(0.05)

    assert len(received) >= 1
    # Event packet (H4 type 0x04), Command Complete event code 0x0E
    assert received[0][0] == 0x04
    assert received[0][1] == 0x0E
```

- [x] **Step 2.2: Run test (FAIL expected)**

```bash
uv run pytest tests/unit/hci/test_virtual_create.py -v
```

Expected: `AttributeError: type object 'VirtualController' has no attribute 'create'`.

- [x] **Step 2.3: Add private `_HCIPipe` class + `create()` to `pybluehost/hci/virtual.py`**

Add at the bottom of `pybluehost/hci/virtual.py` (after the existing `VirtualController` class definition):

```python
# ---------------------------------------------------------------------------
# Private in-process pipe — VirtualController internals only.
# ---------------------------------------------------------------------------

from pybluehost.transport.base import Transport, TransportInfo


class _HCIPipe(Transport):
    """In-memory bidirectional pipe between VirtualController and host stack.

    Private — instantiate via VirtualController.create() instead.
    Bytes sent on one instance are delivered to its peer's sink.
    """

    def __init__(self) -> None:
        super().__init__()
        self._peer: "_HCIPipe | None" = None
        self._open = False

    @classmethod
    def pair(cls) -> tuple["_HCIPipe", "_HCIPipe"]:
        a = cls()
        b = cls()
        a._peer = b
        b._peer = a
        return a, b

    async def open(self) -> None:
        self._open = True

    async def close(self) -> None:
        self._open = False

    async def send(self, data: bytes) -> None:
        if not self._open:
            raise RuntimeError("_HCIPipe not open")
        if self._peer is None or self._peer._sink is None:
            return
        await self._peer._sink.on_transport_data(data)

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(type="virtual", description="VirtualController pipe")
```

(If the actual `pybluehost/transport/loopback.py` has additional methods beyond what's shown above, copy those too — `_HCIPipe` must be functionally equivalent.)

Then add the `create` classmethod inside `class VirtualController`:

```python
    @classmethod
    async def create(
        cls,
        address: BDAddress | None = None,
    ) -> tuple["VirtualController", Transport]:
        """Create a VirtualController and a paired host-side Transport.

        Returns (controller, host_transport). The host_transport is already
        opened and wired to forward host->controller bytes through this VC's
        process() method, returning responses to the host sink.
        """
        if address is None:
            address = BDAddress.from_string("AA:BB:CC:DD:EE:01")
        vc = cls(address=address)
        host_t, ctrl_t = _HCIPipe.pair()

        class _VCSink:
            async def on_transport_data(self, data: bytes) -> None:
                response = await vc.process(data)
                if response is not None and host_t._sink is not None:
                    await host_t._sink.on_transport_data(response)

        ctrl_t.set_sink(_VCSink())
        await host_t.open()
        await ctrl_t.open()
        return vc, host_t
```

- [x] **Step 2.4: Simplify `Stack.virtual()` in `pybluehost/stack.py`**

Replace the current `virtual` classmethod body:

```python
    @classmethod
    async def virtual(
        cls,
        config: StackConfig | None = None,
    ) -> Stack:
        """Create a single Stack backed by a software-emulated VirtualController.

        No real Bluetooth hardware required; suitable for unit/integration tests
        and CLI experimentation.
        """
        from pybluehost.hci.virtual import VirtualController

        vc, host_t = await VirtualController.create()
        stack = await cls._build(host_t, config, StackMode.VIRTUAL)
        stack._local_address = vc._address
        return stack
```

- [x] **Step 2.5: Simplify `parse_transport_arg("virtual")` in `pybluehost/cli/_transport.py`**

Replace the `if s == "virtual":` branch:

```python
    if s == "virtual":
        from pybluehost.hci.virtual import VirtualController
        _vc, host_t = await VirtualController.create()
        return host_t
```

(Note: drop the `LoopbackTransport` import; `BDAddress` import is no longer needed in this branch.)

- [x] **Step 2.6: Remove `LoopbackTransport` from `pybluehost/transport/__init__.py`**

Open `pybluehost/transport/__init__.py` and delete the line(s) that import or re-export `LoopbackTransport`. Run:

```bash
grep -n "Loopback" pybluehost/transport/__init__.py
```

Expected after fix: 0 matches.

- [x] **Step 2.7: Delete the obsolete files**

```bash
git rm pybluehost/transport/loopback.py
git rm tests/unit/transport/test_loopback.py
```

- [x] **Step 2.8: Confirm no caller references the old class**

```bash
grep -rn "LoopbackTransport\|from pybluehost.transport.loopback\|pybluehost.transport import.*Loopback" pybluehost/ tests/ --include="*.py"
```

Expected: 0 matches.

- [x] **Step 2.9: Run the new VC test + broad non-hardware verification; full suite deferred**

```bash
uv run pytest tests/unit/hci/test_virtual_create.py -v
uv run pytest tests/ -q
```

Actual Task 2 verification:

```bash
uv run pytest tests/unit/hci/test_virtual_create.py tests/unit/test_stack.py tests/unit/cli/test_transport.py -q
# 22 passed

uv run pytest tests/ -q -m "not hardware"
# Failed: tests/hardware/test_intel_hw.py still ran and hit pre-existing Intel USB timeout paths.

uv run pytest tests/ -q --ignore=tests/hardware
# Passed.
```

Full-suite `uv run pytest tests/ -q` is blocked/deferred for Task 2 because existing hardware tests can run against the local Intel BE200 and time out before the later transport marker-selection tasks isolate hardware-only tests. The previously-existing `tests/integration/test_hci_init.py` and `test_hci_l2cap.py` define their **own inline** `LoopbackTransport` class so they are unaffected; they will be migrated in Tasks 16–17.

- [x] **Step 2.10: Commit**

```bash
git add -A
git commit -m "refactor: internalize LoopbackTransport into VirtualController._HCIPipe

- Add VirtualController.create() async classmethod returning (vc, host_transport)
- Move pipe class as private _HCIPipe inside pybluehost/hci/virtual.py
- Simplify Stack.virtual() and parse_transport_arg('virtual') call sites
- Delete pybluehost/transport/loopback.py and tests/unit/transport/test_loopback.py
- Drop LoopbackTransport from pybluehost/transport/__init__.py exports

The pipe is no longer a public concept; users see only VirtualController."
```

---

## Task 3: USBTransport `list_devices()` + 扩展 `auto_detect`

**Files:**
- Modify: `pybluehost/transport/usb.py`
- Test: `tests/unit/transport/test_usb_list_devices.py`

- [x] **Step 3.1: Write failing test**

```python
# tests/unit/transport/test_usb_list_devices.py
"""Tests for USBTransport.list_devices() and auto_detect bus/address filtering."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pybluehost.transport.usb import (
    DeviceCandidate,
    NoBluetoothDeviceError,
    USBTransport,
)


def _make_dev(vid: int, pid: int, bus: int, address: int) -> MagicMock:
    dev = MagicMock()
    dev.idVendor = vid
    dev.idProduct = pid
    dev.bus = bus
    dev.address = address
    return dev


def test_list_devices_returns_known_chips_only():
    intel = _make_dev(0x8087, 0x0032, bus=1, address=4)   # AX210
    other = _make_dev(0x1234, 0x5678, bus=1, address=5)   # not in KNOWN_CHIPS

    with patch("pybluehost.transport.usb.usb") as usb_mod:
        usb_mod.core.find.return_value = [intel, other]
        with patch.object(USBTransport, "_get_usb_backend", return_value=None):
            candidates = USBTransport.list_devices()

    assert len(candidates) == 1
    cand = candidates[0]
    assert isinstance(cand, DeviceCandidate)
    assert cand.vendor == "intel"
    assert cand.bus == 1
    assert cand.address == 4
    assert cand.chip_info.name == "AX210"


def test_list_devices_returns_empty_when_no_devices():
    with patch("pybluehost.transport.usb.usb") as usb_mod:
        usb_mod.core.find.return_value = []
        with patch.object(USBTransport, "_get_usb_backend", return_value=None):
            assert USBTransport.list_devices() == []


def test_auto_detect_bus_address_filters_to_specific_adapter():
    intel_a = _make_dev(0x8087, 0x0032, bus=1, address=4)
    intel_b = _make_dev(0x8087, 0x0032, bus=2, address=5)

    with patch("pybluehost.transport.usb.usb") as usb_mod:
        usb_mod.core.find.return_value = [intel_a, intel_b]
        with patch.object(USBTransport, "_get_usb_backend", return_value=None):
            t = USBTransport.auto_detect(vendor="intel", bus=2, address=5)

    assert t._device is intel_b


def test_auto_detect_bus_address_no_match_raises():
    intel = _make_dev(0x8087, 0x0032, bus=1, address=4)
    with patch("pybluehost.transport.usb.usb") as usb_mod:
        usb_mod.core.find.return_value = [intel]
        with patch.object(USBTransport, "_get_usb_backend", return_value=None):
            with pytest.raises(NoBluetoothDeviceError):
                USBTransport.auto_detect(vendor="intel", bus=9, address=9)
```

- [x] **Step 3.2: Run test (FAIL expected)**

```bash
uv run pytest tests/unit/transport/test_usb_list_devices.py -v
```

Expected: `ImportError: cannot import name 'DeviceCandidate'` or similar.

- [x] **Step 3.3: Implement `DeviceCandidate` and `list_devices()`**

Add near the existing `ChipInfo` definition in `pybluehost/transport/usb.py`:

```python
@dataclass(frozen=True)
class DeviceCandidate:
    """One enumerated Bluetooth USB device with location metadata."""

    chip_info: ChipInfo
    bus: int
    address: int

    @property
    def vendor(self) -> str:
        return self.chip_info.vendor

    @property
    def name(self) -> str:
        return self.chip_info.name
```

Add the classmethod inside `USBTransport`:

```python
    @classmethod
    def list_devices(cls) -> list["DeviceCandidate"]:
        """Enumerate every plugged-in Bluetooth USB device known to KNOWN_CHIPS.

        Returns an empty list when pyusb is unavailable or no devices match.
        Used by autodetect and by the diagnostic --list-transports option.
        """
        if usb is None:
            return []
        backend = cls._get_usb_backend()
        try:
            all_devices = list(usb.core.find(find_all=True, backend=backend))
        except Exception:
            return []
        result: list[DeviceCandidate] = []
        for dev in all_devices:
            for chip in KNOWN_CHIPS:
                if dev.idVendor == chip.vid and dev.idProduct == chip.pid:
                    result.append(
                        DeviceCandidate(
                            chip_info=chip,
                            bus=int(getattr(dev, "bus", 0) or 0),
                            address=int(getattr(dev, "address", 0) or 0),
                        )
                    )
                    break
        return result
```

- [x] **Step 3.4: Extend `auto_detect` signature with `bus` / `address`**

Replace the existing `auto_detect` signature and matching loop:

```python
    @classmethod
    def auto_detect(
        cls,
        firmware_policy: FirmwarePolicy = FirmwarePolicy.PROMPT,
        vendor: str | None = None,
        bus: int | None = None,
        address: int | None = None,
    ) -> "USBTransport":
        """Enumerate USB devices, match KNOWN_CHIPS, return the correct subclass instance.

        bus/address narrow to a single adapter when both are provided.
        """
        if usb is None:
            raise RuntimeError("pyusb not installed. Run: pip install pyusb")

        selected_vendor = vendor.lower() if vendor is not None else None
        if selected_vendor is not None and selected_vendor not in {"intel", "realtek", "csr"}:
            raise ValueError(
                "Unsupported USB vendor filter: "
                f"{vendor!r}. Expected one of: intel, realtek, csr."
            )

        backend = cls._get_usb_backend()
        chips = [
            chip for chip in KNOWN_CHIPS
            if selected_vendor is None or chip.vendor == selected_vendor
        ]

        all_devices = list(usb.core.find(find_all=True, backend=backend))
        for dev in all_devices:
            if bus is not None and int(getattr(dev, "bus", 0) or 0) != bus:
                continue
            if address is not None and int(getattr(dev, "address", 0) or 0) != address:
                continue
            for chip in chips:
                if dev.idVendor == chip.vid and dev.idProduct == chip.pid:
                    transport_cls = chip.transport_class or cls
                    return transport_cls(
                        device=dev,
                        chip_info=chip,
                        firmware_policy=firmware_policy,
                    )

        # Fallback: generic Bluetooth USB device only when no vendor/bus/address filter
        if selected_vendor is None and bus is None and address is None:
            bt_devices = list(
                usb.core.find(
                    find_all=True,
                    backend=backend,
                    bDeviceClass=0xE0,
                    bDeviceSubClass=0x01,
                    bDeviceProtocol=0x01,
                )
            )
            if bt_devices:
                dev = bt_devices[0]
                return cls(device=dev, firmware_policy=firmware_policy)

        target = f" {selected_vendor}" if selected_vendor is not None else ""
        loc = ""
        if bus is not None or address is not None:
            loc = f" at bus={bus} address={address}"
        raise NoBluetoothDeviceError(
            f"No supported{target} Bluetooth USB device found{loc}. "
            "Ensure your adapter is plugged in and (on Windows) has the WinUSB driver."
        )
```

- [x] **Step 3.5: Run tests (PASS expected)**

```bash
uv run pytest tests/unit/transport/test_usb_list_devices.py -v
uv run pytest tests/unit/transport/ -q          # ensure no regression
```

- [x] **Step 3.6: Commit**

```bash
git add pybluehost/transport/usb.py tests/unit/transport/test_usb_list_devices.py
git commit -m "feat(transport): add USBTransport.list_devices and bus/address filter"
```

---

## Task 4: `Stack.from_usb()` 与 `Stack.from_uart()` 工厂

**Files:**
- Modify: `pybluehost/stack.py`
- Test: `tests/unit/test_stack_factories.py`

- [x] **Step 4.1: Write failing test**

```python
# tests/unit/test_stack_factories.py
"""Stack.from_usb() and Stack.from_uart() factory methods."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pybluehost.stack import Stack, StackMode


@pytest.mark.asyncio
async def test_from_usb_calls_auto_detect_with_filters():
    fake_transport = MagicMock()
    fake_transport.open = AsyncMock()

    with patch("pybluehost.transport.usb.USBTransport.auto_detect", return_value=fake_transport) as ad:
        with patch.object(Stack, "_build", new=AsyncMock(return_value=MagicMock(spec=Stack))) as build:
            await Stack.from_usb(vendor="intel", bus=1, address=4)

    ad.assert_called_once_with(vendor="intel", bus=1, address=4)
    fake_transport.open.assert_awaited_once()
    args, kwargs = build.call_args
    assert args[0] is fake_transport
    assert args[2] == StackMode.LIVE


@pytest.mark.asyncio
async def test_from_uart_constructs_uart_transport():
    fake_transport = MagicMock()
    fake_transport.open = AsyncMock()

    with patch("pybluehost.transport.uart.UARTTransport", return_value=fake_transport) as ctor:
        with patch.object(Stack, "_build", new=AsyncMock(return_value=MagicMock(spec=Stack))) as build:
            await Stack.from_uart(port="/dev/ttyUSB0", baudrate=921600)

    ctor.assert_called_once_with(port="/dev/ttyUSB0", baudrate=921600)
    fake_transport.open.assert_awaited_once()
    args, kwargs = build.call_args
    assert args[0] is fake_transport
    assert args[2] == StackMode.LIVE
```

- [x] **Step 4.2: Run test (FAIL expected)**

```bash
uv run pytest tests/unit/test_stack_factories.py -v
```

Expected: `AttributeError: type object 'Stack' has no attribute 'from_usb'`.

- [x] **Step 4.3: Implement factories**

Add inside `class Stack` in `pybluehost/stack.py`, immediately after the existing `virtual` classmethod:

```python
    @classmethod
    async def from_usb(
        cls,
        vendor: str | None = None,
        bus: int | None = None,
        address: int | None = None,
        config: StackConfig | None = None,
    ) -> Stack:
        """Build a live Stack on a USB Bluetooth adapter."""
        from pybluehost.transport.usb import USBTransport

        transport = USBTransport.auto_detect(vendor=vendor, bus=bus, address=address)
        await transport.open()
        return await cls._build(transport, config, StackMode.LIVE)

    @classmethod
    async def from_uart(
        cls,
        port: str,
        baudrate: int = 115200,
        config: StackConfig | None = None,
    ) -> Stack:
        """Build a live Stack on a UART HCI link."""
        from pybluehost.transport.uart import UARTTransport

        transport = UARTTransport(port=port, baudrate=baudrate)
        await transport.open()
        return await cls._build(transport, config, StackMode.LIVE)
```

- [x] **Step 4.4: Run test (PASS expected)**

```bash
uv run pytest tests/unit/test_stack_factories.py -v
uv run pytest tests/unit/test_stack.py -q
```

- [x] **Step 4.5: Commit**

```bash
git add pybluehost/stack.py tests/unit/test_stack_factories.py
git commit -m "feat(stack): add Stack.from_usb and Stack.from_uart factories"
```

---

## Task 5: `parse_transport_arg` 识别 `bus=` / `address=`

**Files:**
- Modify: `pybluehost/cli/_transport.py`
- Test: `tests/unit/cli/test_transport_parse_bus_address.py`

- [x] **Step 5.1: Write failing test**

```python
# tests/unit/cli/test_transport_parse_bus_address.py
"""parse_transport_arg recognizes bus= and address= keys."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pybluehost.cli._transport import parse_transport_arg


@pytest.mark.asyncio
async def test_parse_usb_with_bus_and_address_passes_kwargs():
    fake_transport = MagicMock()
    fake_transport.open = AsyncMock()
    with patch("pybluehost.transport.usb.USBTransport.auto_detect", return_value=fake_transport) as ad:
        result = await parse_transport_arg("usb:vendor=intel,bus=1,address=4")
    assert result is fake_transport
    ad.assert_called_once_with(vendor="intel", bus=1, address=4)


@pytest.mark.asyncio
async def test_parse_usb_without_bus_address_omits_kwargs():
    fake_transport = MagicMock()
    fake_transport.open = AsyncMock()
    with patch("pybluehost.transport.usb.USBTransport.auto_detect", return_value=fake_transport) as ad:
        await parse_transport_arg("usb:vendor=intel")
    ad.assert_called_once_with(vendor="intel", bus=None, address=None)
```

- [x] **Step 5.2: Run test (FAIL expected)**

```bash
uv run pytest tests/unit/cli/test_transport_parse_bus_address.py -v
```

- [x] **Step 5.3: Update `parse_transport_arg`**

In `pybluehost/cli/_transport.py`, replace the `usb` branch:

```python
    if s == "usb" or s.startswith("usb:"):
        from pybluehost.transport.usb import USBTransport
        vendor: str | None = None
        bus: int | None = None
        address: int | None = None
        if s.startswith("usb:"):
            for kv in s[4:].split(","):
                if "=" not in kv:
                    continue
                k, v = kv.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k == "vendor":
                    vendor = v
                elif k == "bus":
                    bus = int(v)
                elif k == "address":
                    address = int(v)
                else:
                    raise ValueError(f"Unknown usb spec key: {k!r}")
        return USBTransport.auto_detect(vendor=vendor, bus=bus, address=address)
```

- [x] **Step 5.4: Run test (PASS expected)**

```bash
uv run pytest tests/unit/cli/test_transport_parse_bus_address.py -v
uv run pytest tests/unit/cli/test_transport.py -q
```

- [x] **Step 5.5: Commit**

```bash
git add pybluehost/cli/_transport.py tests/unit/cli/test_transport_parse_bus_address.py
git commit -m "feat(cli): parse_transport_arg accepts bus= and address= keys"
```

---

## Task 6: `tests/_transport_select.py` — spec 解析 + autodetect

**Files:**
- Create: `tests/_transport_select.py`
- Test: `tests/unit/test_transport_select.py`

- [x] **Step 6.1: Write failing test**

```python
# tests/unit/test_transport_select.py
"""Unit tests for the test-transport selection helper module."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests._transport_select import (
    InvalidSpec,
    SameFamilyError,
    autodetect_primary,
    family_of,
    find_second_usb_adapter,
    parse_spec,
)


def test_family_of_classifies_specs():
    assert family_of("virtual") == "virtual"
    assert family_of("usb") == "usb"
    assert family_of("usb:vendor=intel") == "usb"
    assert family_of("uart:/dev/ttyUSB0") == "uart"
    assert family_of("uart:/dev/ttyUSB0@921600") == "uart"


def test_parse_spec_accepts_supported_forms():
    parse_spec("virtual")
    parse_spec("usb")
    parse_spec("usb:vendor=intel,bus=1,address=4")
    parse_spec("uart:/dev/ttyUSB0@921600")


def test_parse_spec_rejects_garbage():
    with pytest.raises(InvalidSpec):
        parse_spec("garbage")
    with pytest.raises(InvalidSpec):
        parse_spec("usb:vendor=qualcomm")  # not in vendor allowlist


def test_autodetect_returns_virtual_when_no_devices():
    with patch("pybluehost.transport.usb.USBTransport.list_devices", return_value=[]):
        assert autodetect_primary() == "virtual"


def test_autodetect_returns_usb_spec_with_bus_address():
    cand = MagicMock()
    cand.vendor = "intel"
    cand.bus = 1
    cand.address = 4
    with patch("pybluehost.transport.usb.USBTransport.list_devices", return_value=[cand]):
        assert autodetect_primary() == "usb:vendor=intel,bus=1,address=4"


def test_find_second_usb_adapter_excludes_primary():
    a = MagicMock(); a.vendor = "intel"; a.bus = 1; a.address = 4
    b = MagicMock(); b.vendor = "intel"; b.bus = 2; b.address = 5
    with patch("pybluehost.transport.usb.USBTransport.list_devices", return_value=[a, b]):
        peer = find_second_usb_adapter(primary_bus=1, primary_address=4)
    assert peer == "usb:vendor=intel,bus=2,address=5"


def test_find_second_usb_adapter_returns_none_when_only_primary():
    a = MagicMock(); a.vendor = "intel"; a.bus = 1; a.address = 4
    with patch("pybluehost.transport.usb.USBTransport.list_devices", return_value=[a]):
        assert find_second_usb_adapter(primary_bus=1, primary_address=4) is None


def test_same_family_check():
    from tests._transport_select import enforce_same_family
    enforce_same_family(primary="usb:vendor=intel", peer="usb")           # ok
    enforce_same_family(primary="virtual", peer="virtual")                # ok
    with pytest.raises(SameFamilyError):
        enforce_same_family(primary="usb", peer="virtual")


def test_vendor_of_extracts_vendor_from_usb_spec():
    from tests._transport_select import vendor_of
    assert vendor_of("virtual") is None
    assert vendor_of("usb") is None
    assert vendor_of("uart:/dev/ttyUSB0") is None
    assert vendor_of("usb:vendor=intel") == "intel"
    assert vendor_of("usb:vendor=Intel,bus=1,address=4") == "intel"
    assert vendor_of("usb:bus=1,address=4") is None  # no vendor key
```

- [x] **Step 6.2: Run test (FAIL expected)**

```bash
uv run pytest tests/unit/test_transport_select.py -v
```

- [x] **Step 6.3: Implement `tests/_transport_select.py`**

```python
# tests/_transport_select.py
"""Transport selection helper used by tests/conftest.py.

Resolves a transport spec from CLI/env/autodetect and provides supporting
helpers for peer adapter discovery and family checks. Pure helpers — no
pytest dependency, no I/O beyond USB enumeration.
"""
from __future__ import annotations

_VALID_VENDORS = {"intel", "realtek", "csr"}


class InvalidSpec(ValueError):
    """Raised when a transport spec string is malformed."""


class SameFamilyError(ValueError):
    """Raised when peer transport family does not match primary."""


def family_of(spec: str) -> str:
    """Return 'virtual' / 'usb' / 'uart' for any valid spec."""
    if spec == "virtual":
        return "virtual"
    if spec == "usb" or spec.startswith("usb:"):
        return "usb"
    if spec.startswith("uart:"):
        return "uart"
    raise InvalidSpec(f"Unknown transport family: {spec!r}")


def parse_spec(spec: str) -> tuple[str, dict[str, str]]:
    """Validate spec syntax. Returns (family, key/value dict).

    Raises InvalidSpec for malformed input. Does not open any device.
    """
    if spec == "virtual":
        return ("virtual", {})
    if spec == "usb":
        return ("usb", {})
    if spec.startswith("usb:"):
        params: dict[str, str] = {}
        for kv in spec[4:].split(","):
            if "=" not in kv:
                raise InvalidSpec(f"USB spec part missing '=': {kv!r}")
            k, v = kv.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k not in {"vendor", "bus", "address"}:
                raise InvalidSpec(f"Unknown usb spec key: {k!r}")
            if k == "vendor" and v.lower() not in _VALID_VENDORS:
                raise InvalidSpec(f"Unsupported vendor: {v!r}")
            params[k] = v
        return ("usb", params)
    if spec.startswith("uart:"):
        rest = spec[5:]
        if not rest:
            raise InvalidSpec("UART spec missing port")
        return ("uart", {"raw": rest})
    raise InvalidSpec(f"Unknown transport spec: {spec!r}")


def autodetect_primary() -> str:
    """Return a usb:... spec for the first detected adapter, or 'virtual'."""
    from pybluehost.transport.usb import USBTransport

    candidates = USBTransport.list_devices()
    if not candidates:
        return "virtual"
    c = candidates[0]
    return f"usb:vendor={c.vendor},bus={c.bus},address={c.address}"


def find_second_usb_adapter(primary_bus: int, primary_address: int) -> str | None:
    """Return a usb:... spec for a USB adapter other than the primary, or None."""
    from pybluehost.transport.usb import USBTransport

    for cand in USBTransport.list_devices():
        if cand.bus == primary_bus and cand.address == primary_address:
            continue
        return f"usb:vendor={cand.vendor},bus={cand.bus},address={cand.address}"
    return None


def enforce_same_family(primary: str, peer: str) -> None:
    """Raise SameFamilyError if peer family differs from primary."""
    p_fam = family_of(primary)
    q_fam = family_of(peer)
    if p_fam != q_fam:
        raise SameFamilyError(
            f"Peer transport must match primary family ({p_fam} vs {q_fam})"
        )


def usb_spec_bus_address(spec: str) -> tuple[int | None, int | None]:
    """Extract (bus, address) from a usb:... spec, or (None, None) if absent."""
    if not spec.startswith("usb:"):
        return (None, None)
    bus = address = None
    for kv in spec[4:].split(","):
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k == "bus":
            bus = int(v)
        elif k == "address":
            address = int(v)
    return (bus, address)


def vendor_of(spec: str) -> str | None:
    """Return 'intel' / 'realtek' / 'csr' for usb specs with vendor=, else None.

    Used by real_hardware_only marker enforcement to decide vendor-constrained skips.
    """
    if not spec.startswith("usb:"):
        return None
    for kv in spec[4:].split(","):
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        if k.strip() == "vendor":
            return v.strip().lower()
    return None
```

- [x] **Step 6.4: Run test (PASS expected)**

```bash
uv run pytest tests/unit/test_transport_select.py -v
```

- [x] **Step 6.5: Commit**

```bash
git add tests/_transport_select.py tests/unit/test_transport_select.py
git commit -m "feat(tests): add _transport_select helper for spec/autodetect"
```

---

## Task 7: `tests/_fallback_tracker.py` — session 级回落计数

**Files:**
- Create: `tests/_fallback_tracker.py`
- Test: `tests/unit/test_fallback_tracker.py`

- [x] **Step 7.1: Write failing test**

```python
# tests/unit/test_fallback_tracker.py
from tests._fallback_tracker import FallbackTracker


def test_fallback_tracker_initial_state():
    t = FallbackTracker()
    assert not t.is_fallback()
    assert t.count == 0


def test_fallback_tracker_mark_and_increment():
    t = FallbackTracker()
    t.mark_fallback()
    assert t.is_fallback()
    t.increment()
    t.increment()
    assert t.count == 2
```

- [x] **Step 7.2: Run test (FAIL expected)**

```bash
uv run pytest tests/unit/test_fallback_tracker.py -v
```

- [x] **Step 7.3: Implement `tests/_fallback_tracker.py`**

```python
# tests/_fallback_tracker.py
"""Session-scoped counter for tests that ran on the virtual controller because
hardware was not detected during autodetect. Read by pytest_terminal_summary."""
from __future__ import annotations


class FallbackTracker:
    """Tracks whether autodetect fell back to virtual and how many tests ran."""

    def __init__(self) -> None:
        self._fallback = False
        self._count = 0

    def mark_fallback(self) -> None:
        self._fallback = True

    def is_fallback(self) -> bool:
        return self._fallback

    def increment(self) -> None:
        self._count += 1

    @property
    def count(self) -> int:
        return self._count
```

- [x] **Step 7.4: Run test (PASS expected)**

```bash
uv run pytest tests/unit/test_fallback_tracker.py -v
```

- [x] **Step 7.5: Commit**

```bash
git add tests/_fallback_tracker.py tests/unit/test_fallback_tracker.py
git commit -m "feat(tests): add FallbackTracker for transport autodetect summary"
```

---

## Task 8: `tests/conftest.py` — `pytest_addoption` + `--list-transports` 处理

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/unit/test_conftest_options.py`

- [x] **Step 8.1: Write failing test**

```python
# tests/unit/test_conftest_options.py
"""pytest CLI options registered by tests/conftest.py."""
from __future__ import annotations

import subprocess
import sys


def test_help_shows_transport_options():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--help"],
        capture_output=True, text=True,
    )
    assert "--transport" in result.stdout
    assert "--transport-peer" in result.stdout
    assert "--list-transports" in result.stdout
```

- [x] **Step 8.2: Run test (FAIL expected)**

```bash
uv run pytest tests/unit/test_conftest_options.py -v
```

- [x] **Step 8.3: Replace `tests/conftest.py`**

```python
"""Shared pytest fixtures and hooks for PyBlueHost test suite."""
from __future__ import annotations

import os

import pytest

from tests._fallback_tracker import FallbackTracker
from tests._transport_select import (
    InvalidSpec,
    SameFamilyError,
    autodetect_primary,
    enforce_same_family,
    family_of,
    find_second_usb_adapter,
    parse_spec,
    usb_spec_bus_address,
)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register transport-selection CLI options."""
    parser.addoption(
        "--transport",
        action="store",
        default=None,
        help="Primary transport spec: virtual | usb[:vendor=...,bus=N,address=M] | uart:/dev/...",
    )
    parser.addoption(
        "--transport-peer",
        action="store",
        default=None,
        help="Peer transport spec (only affects peer_stack fixture). Same family as --transport.",
    )
    parser.addoption(
        "--list-transports",
        action="store_true",
        default=False,
        help="Print every detected Bluetooth transport adapter, then exit.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """If --list-transports was passed, print and exit before collection."""
    if config.getoption("--list-transports"):
        from pybluehost.transport.usb import USBTransport

        candidates = USBTransport.list_devices()
        if not candidates:
            print("[pybluehost-tests] No Bluetooth USB adapters detected.")
        else:
            print("[pybluehost-tests] Detected Bluetooth USB adapters:")
            for c in candidates:
                spec = f"usb:vendor={c.vendor},bus={c.bus},address={c.address}"
                print(f"  {c.vendor:8s} {c.name:10s} bus={c.bus} address={c.address}  ({spec})")
        pytest.exit("--list-transports done", returncode=0)
```

- [x] **Step 8.4: Run test (PASS expected)**

```bash
uv run pytest tests/unit/test_conftest_options.py -v
uv run pytest tests/ -q --co | head -5
```

- [x] **Step 8.5: Commit**

```bash
git add tests/conftest.py tests/unit/test_conftest_options.py
git commit -m "feat(tests): add --transport/--transport-peer/--list-transports options"
```

---

## Task 9: Session fixtures `selected_transport_spec` / `selected_peer_spec` / `transport_mode`

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/unit/test_session_fixtures.py`

- [x] **Step 9.1: Write failing test**

```python
# tests/unit/test_session_fixtures.py
"""Session-scoped transport-selection fixtures."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def _run_inline(tmp_path: Path, body: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run pytest on an inline test file."""
    test_file = tmp_path / "test_inline.py"
    test_file.write_text(textwrap.dedent(body))
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-q", "--no-header", *args],
        capture_output=True, text=True, cwd=Path(__file__).parents[2],
    )


def test_explicit_virtual(tmp_path: Path):
    body = """
    def test_check(selected_transport_spec, transport_mode):
        assert selected_transport_spec == "virtual"
        assert transport_mode == "virtual"
    """
    r = _run_inline(tmp_path, body, "--transport=virtual")
    assert r.returncode == 0, r.stdout + r.stderr


def test_invalid_spec_exits_with_4(tmp_path: Path):
    body = """
    def test_dummy(selected_transport_spec):
        pass
    """
    r = _run_inline(tmp_path, body, "--transport=garbage")
    assert r.returncode == 4, r.stdout + r.stderr
    assert "Invalid transport spec" in (r.stdout + r.stderr)


def test_env_var_used_when_no_flag(tmp_path: Path, monkeypatch):
    body = """
    def test_check(selected_transport_spec):
        assert selected_transport_spec == "virtual"
    """
    monkeypatch.setenv("PYBLUEHOST_TEST_TRANSPORT", "virtual")
    r = _run_inline(tmp_path, body)
    assert r.returncode == 0, r.stdout + r.stderr


def test_cross_family_peer_exits_with_4(tmp_path: Path):
    body = """
    def test_dummy(selected_peer_spec):
        pass
    """
    r = _run_inline(
        tmp_path, body,
        "--transport=usb", "--transport-peer=virtual",
    )
    # Either family error (exit 4) or "transport unavailable" if no USB on host —
    # both are acceptable rejections; we just need non-zero exit.
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "Peer transport must match primary family" in out or "unavailable" in out
```

- [x] **Step 9.2: Run test (FAIL expected)**

```bash
uv run pytest tests/unit/test_session_fixtures.py -v
```

- [x] **Step 9.3: Append session fixtures to `tests/conftest.py`**

```python
# Append to tests/conftest.py


_FALLBACK_TRACKER = FallbackTracker()


def _resolve_primary_spec(config: pytest.Config) -> str:
    """Resolve primary transport spec from --transport, env, or autodetect."""
    spec = config.getoption("--transport")
    if spec is None:
        spec = os.environ.get("PYBLUEHOST_TEST_TRANSPORT")
    autodetected = False
    if spec is None:
        spec = autodetect_primary()
        autodetected = True

    try:
        parse_spec(spec)
    except InvalidSpec as exc:
        pytest.exit(f"Invalid transport spec: {spec!r} — {exc}", returncode=4)

    # Verify hardware availability for explicit usb/uart specs.
    if not autodetected and family_of(spec) in {"usb", "uart"}:
        try:
            _verify_spec_available(spec)
        except RuntimeError as exc:
            pytest.exit(f"Transport {spec!r} unavailable: {exc}", returncode=4)

    if autodetected and spec == "virtual":
        _FALLBACK_TRACKER.mark_fallback()

    return spec


def _verify_spec_available(spec: str) -> None:
    """Raise RuntimeError if the explicit spec cannot currently be opened.

    Cheap pre-flight check; full open happens later inside fixtures.
    """
    fam = family_of(spec)
    if fam == "usb":
        from pybluehost.transport.usb import NoBluetoothDeviceError, USBTransport

        bus, address = usb_spec_bus_address(spec)
        vendor = None
        if spec.startswith("usb:"):
            for kv in spec[4:].split(","):
                if kv.startswith("vendor="):
                    vendor = kv.split("=", 1)[1].strip()
        try:
            USBTransport.auto_detect(vendor=vendor, bus=bus, address=address)
        except NoBluetoothDeviceError as e:
            raise RuntimeError(str(e)) from None
    elif fam == "uart":
        port = spec[5:].split("@", 1)[0]
        if not os.path.exists(port):
            raise RuntimeError(f"UART port not found: {port}")


def _resolve_peer_spec(config: pytest.Config, primary: str) -> str | None:
    """Resolve peer spec; None means dependent tests are skipped."""
    peer = config.getoption("--transport-peer") or os.environ.get("PYBLUEHOST_TEST_TRANSPORT_PEER")

    if peer is not None:
        try:
            parse_spec(peer)
            enforce_same_family(primary, peer)
        except (InvalidSpec, SameFamilyError) as exc:
            pytest.exit(str(exc), returncode=4)
        return peer

    fam = family_of(primary)
    if fam == "virtual":
        return "virtual"
    if fam == "usb":
        bus, address = usb_spec_bus_address(primary)
        return find_second_usb_adapter(primary_bus=bus or 0, primary_address=address or 0)
    return None  # uart needs explicit peer


@pytest.fixture(scope="session")
def selected_transport_spec(request: pytest.FixtureRequest) -> str:
    return _resolve_primary_spec(request.config)


@pytest.fixture(scope="session")
def selected_peer_spec(selected_transport_spec, request: pytest.FixtureRequest) -> str | None:
    return _resolve_peer_spec(request.config, selected_transport_spec)


@pytest.fixture(scope="session")
def transport_mode(selected_transport_spec) -> str:
    return family_of(selected_transport_spec)
```

- [x] **Step 9.4: Run test (PASS expected)**

```bash
uv run pytest tests/unit/test_session_fixtures.py -v
uv run pytest tests/ -q --co | head -5
```

- [x] **Step 9.5: Commit**

```bash
git add tests/conftest.py tests/unit/test_session_fixtures.py
git commit -m "feat(tests): add session transport-selection fixtures"
```

---

## Task 10: 测试级 fixtures `stack` / `peer_stack` + `_build_stack_from_spec`

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/integration/test_stack_fixture.py`

- [x] **Step 10.1: Write failing test**

```python
# tests/integration/test_stack_fixture.py
"""Smoke tests for stack / peer_stack fixtures."""
from __future__ import annotations

import pytest

from pybluehost.stack import Stack, StackMode


@pytest.mark.asyncio
async def test_stack_fixture_yields_powered_stack(stack):
    assert isinstance(stack, Stack)
    assert stack.is_powered


@pytest.mark.asyncio
async def test_peer_stack_in_virtual_mode(stack, peer_stack, transport_mode):
    if transport_mode != "virtual":
        pytest.skip("This assertion is virtual-specific")
    assert peer_stack is not stack
    assert peer_stack.is_powered
    assert stack.mode == StackMode.VIRTUAL
    assert peer_stack.mode == StackMode.VIRTUAL
```

- [x] **Step 10.2: Run test (FAIL expected)**

```bash
uv run pytest tests/integration/test_stack_fixture.py -v --transport=virtual
```

- [x] **Step 10.3: Append fixtures to `tests/conftest.py`**

```python
# Append to tests/conftest.py


async def _build_stack_from_spec(spec: str):
    """Construct a powered Stack matching the spec."""
    from pybluehost.stack import Stack

    if spec == "virtual":
        return await Stack.virtual()
    if spec == "usb" or spec.startswith("usb:"):
        vendor = bus = address = None
        if spec.startswith("usb:"):
            for kv in spec[4:].split(","):
                if "=" not in kv:
                    continue
                k, v = kv.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k == "vendor":
                    vendor = v
                elif k == "bus":
                    bus = int(v)
                elif k == "address":
                    address = int(v)
        return await Stack.from_usb(vendor=vendor, bus=bus, address=address)
    if spec.startswith("uart:"):
        rest = spec[5:]
        if "@" in rest:
            port, baud_s = rest.rsplit("@", 1)
            return await Stack.from_uart(port=port, baudrate=int(baud_s))
        return await Stack.from_uart(port=rest)
    raise InvalidSpec(f"Cannot build stack from spec: {spec!r}")


@pytest.fixture
async def stack(selected_transport_spec):
    """Full Stack on the selected transport. Built and torn down per test."""
    s = await _build_stack_from_spec(selected_transport_spec)
    if _FALLBACK_TRACKER.is_fallback():
        _FALLBACK_TRACKER.increment()
    yield s
    await s.close()


@pytest.fixture
async def peer_stack(selected_peer_spec):
    """Second Stack. Skips the test when no peer is available."""
    if selected_peer_spec is None:
        pytest.skip(
            "peer_stack: no second adapter available; pass --transport-peer=..."
        )
    s = await _build_stack_from_spec(selected_peer_spec)
    yield s
    await s.close()
```

- [x] **Step 10.4: Run test (PASS expected)**

```bash
uv run pytest tests/integration/test_stack_fixture.py -v --transport=virtual
```

- [x] **Step 10.5: Commit**

```bash
git add tests/conftest.py tests/integration/test_stack_fixture.py
git commit -m "feat(tests): add stack and peer_stack fixtures"
```

---

## Task 11: 标记强制执行 (`pytest_collection_modifyitems`) + 注册 markers

**Files:**
- Modify: `tests/conftest.py`
- Modify: `pyproject.toml`
- Test: `tests/unit/test_marker_enforcement.py`

- [x] **Step 11.1: Write failing tests covering all matrix rows from spec §7.3 / §7.4**

```python
# tests/unit/test_marker_enforcement.py
"""real_hardware_only / virtual_only marker enforcement."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def _run_inline(tmp_path: Path, body: str, *args: str) -> subprocess.CompletedProcess[str]:
    test_file = tmp_path / "test_inline.py"
    test_file.write_text(textwrap.dedent(body))
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-q", *args],
        capture_output=True, text=True, cwd=Path(__file__).parents[2],
    )


# --- Bare real_hardware_only (no kwargs) ---

def test_real_hardware_only_bare_skipped_on_virtual(tmp_path: Path):
    body = """
    import pytest
    @pytest.mark.real_hardware_only
    def test_marked():
        assert True
    """
    r = _run_inline(tmp_path, body, "--transport=virtual")
    assert r.returncode == 0
    assert "1 skipped" in r.stdout


# --- virtual_only ---

def test_virtual_only_runs_on_virtual(tmp_path: Path):
    body = """
    import pytest
    @pytest.mark.virtual_only
    def test_marked():
        assert True
    """
    r = _run_inline(tmp_path, body, "--transport=virtual")
    assert r.returncode == 0
    assert "1 passed" in r.stdout


# --- transport= constraint ---

def test_transport_uart_marker_skipped_on_virtual(tmp_path: Path):
    body = """
    import pytest
    @pytest.mark.real_hardware_only(transport="uart")
    def test_marked():
        assert True
    """
    r = _run_inline(tmp_path, body, "--transport=virtual")
    assert r.returncode == 0
    assert "1 skipped" in r.stdout


# --- Marker error: vendor= without transport="usb" ---

def test_vendor_without_transport_is_marker_error(tmp_path: Path):
    body = """
    import pytest
    @pytest.mark.real_hardware_only(vendor="intel")
    def test_marked():
        assert True
    """
    r = _run_inline(tmp_path, body, "--transport=virtual")
    out = r.stdout + r.stderr
    assert "1 skipped" in out
    assert "marker error" in out
    assert "vendor= requires transport='usb'" in out


def test_invalid_transport_value_is_marker_error(tmp_path: Path):
    body = """
    import pytest
    @pytest.mark.real_hardware_only(transport="bluetooth")
    def test_marked():
        assert True
    """
    r = _run_inline(tmp_path, body, "--transport=virtual")
    out = r.stdout + r.stderr
    assert "1 skipped" in out
    assert "marker error" in out
    assert "transport must be 'usb' or 'uart'" in out


def test_invalid_vendor_value_is_marker_error(tmp_path: Path):
    body = """
    import pytest
    @pytest.mark.real_hardware_only(transport="usb", vendor="qualcomm")
    def test_marked():
        assert True
    """
    r = _run_inline(tmp_path, body, "--transport=virtual")
    out = r.stdout + r.stderr
    assert "1 skipped" in out
    assert "marker error" in out
    assert "unsupported vendor" in out
```

- [x] **Step 11.2: Run tests (FAIL expected)**

```bash
uv run pytest tests/unit/test_marker_enforcement.py -v
```

- [x] **Step 11.3: Update `pyproject.toml` markers list**

Replace the `[tool.pytest.ini_options].markers` block:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "unit: isolated unit tests (no real hardware, no transport)",
    "integration: layered tests using stack fixture (transport-bound)",
    "e2e: full-stack tests (transport-bound)",
    "btsnoop: btsnoop file replay tests",
    "real_hardware_only(transport=..., vendor=...): requires real hardware; see spec §7",
    "virtual_only: deterministic test, only valid on virtual controller",
    "slow: tests taking >5s",
]
addopts = "--strict-markers -q"
```

- [x] **Step 11.4: Append marker enforcement to `tests/conftest.py`**

```python
# Append to tests/conftest.py

from tests._transport_select import vendor_of  # add to existing imports


_VALID_TRANSPORTS = {"usb", "uart"}
_VALID_VENDORS = {"intel", "realtek", "csr"}


def _real_hw_skip_reason(marker, fam: str, current_vendor: str | None) -> str | None:
    """Return a skip reason string, or None if the test should run.

    Implements spec §7.3 (decision matrix) and §7.4 (marker errors).
    All constraints must be explicitly declared (no implicit transport=usb when
    only vendor= is given).
    """
    required_transport = marker.kwargs.get("transport")
    required_vendor = marker.kwargs.get("vendor")

    # §7.4 marker errors take precedence so authors notice misuse before
    # transport-based skips hide the bug.
    if required_transport is not None and required_transport not in _VALID_TRANSPORTS:
        return (f"real_hardware_only marker error: transport must be 'usb' or 'uart', "
                f"got {required_transport!r}")
    if required_vendor is not None:
        vendors = (required_vendor,) if isinstance(required_vendor, str) else tuple(required_vendor)
        for v in vendors:
            if v not in _VALID_VENDORS:
                return f"real_hardware_only marker error: unsupported vendor {v!r}"
        if required_transport != "usb":
            return "real_hardware_only marker error: vendor= requires transport='usb'"

    # §7.3 normal decision matrix.
    if fam == "virtual":
        return "requires real hardware (use --transport=usb)"
    if required_transport is not None and fam != required_transport:
        return f"requires {required_transport!r} transport, got {fam!r}"
    if required_vendor is not None:
        vendors = (required_vendor,) if isinstance(required_vendor, str) else tuple(required_vendor)
        if current_vendor not in vendors:
            return f"requires vendor in {vendors}, got {current_vendor!r}"
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Enforce real_hardware_only(transport=, vendor=) and virtual_only markers."""
    spec = _resolve_primary_spec(config)
    fam = family_of(spec)
    current_vendor = vendor_of(spec)

    skip_v = pytest.mark.skip(reason="deterministic test, runs only on virtual controller")
    for item in items:
        marker = item.get_closest_marker("real_hardware_only")
        if marker is not None:
            reason = _real_hw_skip_reason(marker, fam, current_vendor)
            if reason is not None:
                item.add_marker(pytest.mark.skip(reason=reason))
        if "virtual_only" in item.keywords and fam != "virtual":
            item.add_marker(skip_v)
```

- [x] **Step 11.5: Run test (PASS expected)**

```bash
uv run pytest tests/unit/test_marker_enforcement.py -v
```

- [x] **Step 11.6: Commit**

```bash
git add tests/conftest.py pyproject.toml tests/unit/test_marker_enforcement.py
git commit -m "feat(tests): enforce real_hardware_only and virtual_only markers"
```

---

## Task 12: `pytest_report_header` 与 `pytest_terminal_summary`

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/unit/test_report_header.py`

- [x] **Step 12.1: Write failing test**

```python
# tests/unit/test_report_header.py
"""Session header and terminal summary."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def _run_inline(tmp_path: Path, body: str, *args: str) -> subprocess.CompletedProcess[str]:
    test_file = tmp_path / "test_inline.py"
    test_file.write_text(textwrap.dedent(body))
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-v", *args],
        capture_output=True, text=True, cwd=Path(__file__).parents[2],
    )


def test_header_shows_explicit_virtual(tmp_path: Path):
    body = "def test_dummy(): pass"
    r = _run_inline(tmp_path, body, "--transport=virtual")
    out = r.stdout + r.stderr
    assert "[pybluehost-tests] transport: virtual" in out
    assert "[explicit]" in out


def test_no_fallback_summary_when_explicit(tmp_path: Path):
    body = "def test_dummy(): pass"
    r = _run_inline(tmp_path, body, "--transport=virtual")
    out = r.stdout + r.stderr
    assert "Auto-detect found no hardware" not in out
```

- [x] **Step 12.2: Run test (FAIL expected)**

```bash
uv run pytest tests/unit/test_report_header.py -v
```

- [x] **Step 12.3: Append hooks to `tests/conftest.py`**

```python
# Append to tests/conftest.py


def _header_source_label(config: pytest.Config) -> str:
    if config.getoption("--transport") is not None:
        return "explicit"
    if os.environ.get("PYBLUEHOST_TEST_TRANSPORT") is not None:
        return "explicit"
    if _FALLBACK_TRACKER.is_fallback():
        return "auto-detected — no hardware found"
    return "auto-detected"


def pytest_report_header(config: pytest.Config) -> list[str]:
    if config.getoption("--list-transports"):
        return []
    primary = _resolve_primary_spec(config)
    label = _header_source_label(config)
    lines = [f"[pybluehost-tests] transport: {primary} [{label}]"]
    peer = _resolve_peer_spec(config, primary)
    if peer is not None and peer != primary:
        lines.append(f"[pybluehost-tests] peer transport: {peer}")
    return lines


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    if not _FALLBACK_TRACKER.is_fallback():
        return
    n = _FALLBACK_TRACKER.count
    terminalreporter.write_sep("=", "pybluehost transport summary")
    terminalreporter.write_line(
        f"⚠  Auto-detect found no hardware. {n} tests ran on virtual."
    )
    terminalreporter.write_line(
        "   Set --transport=usb (or PYBLUEHOST_TEST_TRANSPORT=usb) to validate"
    )
    terminalreporter.write_line(
        "   against real hardware."
    )
    terminalreporter.write_sep("=")
```

- [x] **Step 12.4: Run test (PASS expected)**

```bash
uv run pytest tests/unit/test_report_header.py -v
uv run pytest tests/ -q --transport=virtual --co | head -10
```

- [x] **Step 12.5: Commit**

```bash
git add tests/conftest.py tests/unit/test_report_header.py
git commit -m "feat(tests): add transport report_header and fallback summary"
```

---

## Task 13: 删除 `tests/integration/conftest.py` 死代码

**Files:**
- Modify: `tests/integration/conftest.py`

- [x] **Step 13.1: Verify the fixtures are unused**

```bash
grep -rn "vc_a\|vc_b\|hci_with_vc\|l2cap_with_hci" tests/ --include="*.py" | grep -v "tests/integration/conftest.py"
```

Expected: no matches. (If something turns up, stop and update the plan.)

- [x] **Step 13.2: Replace `tests/integration/conftest.py` with a one-line note**

```python
# tests/integration/conftest.py
"""Integration tests rely on top-level stack/peer_stack fixtures from tests/conftest.py."""
```

- [x] **Step 13.3: Run integration suite**

```bash
uv run pytest tests/integration/ -v --transport=virtual
```

Expected: still passes (the existing tests use their own inline `LoopbackTransport`; they will be migrated in Tasks 16–17).

- [x] **Step 13.4: Commit**

```bash
git add tests/integration/conftest.py
git commit -m "refactor(tests): remove unused vc_a/hci_with_vc/l2cap_with_hci fixtures"
```

---

## Task 14: 删除 `tests/hardware/conftest.py`

**Files:**
- Delete: `tests/hardware/conftest.py`

- [x] **Step 14.1: Verify --hardware flag isn't required by any current test**

```bash
grep -rn "hardware_required\|--hardware\|getoption.\"--hardware\"" tests/ pybluehost/ --include="*.py"
```

Expected: only matches inside `tests/hardware/conftest.py` itself.

Actual: `tests/hardware/test_usb_smoke.py` still used `hardware_required`; Task 19 was executed before deleting this file so the old fixture is no longer required.

- [x] **Step 14.2: Delete the file**

```bash
rm tests/hardware/conftest.py
```

- [x] **Step 14.3: Confirm pytest still collects**

```bash
uv run pytest tests/ -q --co --transport=virtual | tail -5
```

- [x] **Step 14.4: Commit**

```bash
git add tests/hardware/conftest.py
git commit -m "refactor(tests): drop --hardware flag and hardware_required fixture"
```

---

## Task 15: 替换 `tests/e2e/conftest.py`

**Files:**
- Modify: `tests/e2e/conftest.py`

- [x] **Step 15.1: Verify nobody else uses `single_loopback_stack`**

```bash
grep -rn "single_loopback_stack" tests/ --include="*.py" | grep -v "tests/e2e/conftest.py"
```

Expected: no matches.

Actual: current code used `single_virtual_stack`; no matches existed outside `tests/e2e/conftest.py`.

- [x] **Step 15.2: Replace contents**

```python
# tests/e2e/conftest.py
"""E2E tests rely on the top-level stack fixture from tests/conftest.py."""
```

- [x] **Step 15.3: Confirm**

```bash
uv run pytest tests/e2e/ -q --transport=virtual
```

Expected: 0 tests run, 0 errors.

Actual: `tests/e2e/` contains no tests, so pytest returned exit 5 with no errors. Full-suite collection with `--transport=virtual` passed.

- [x] **Step 15.4: Commit**

```bash
git add tests/e2e/conftest.py
git commit -m "refactor(tests): drop single_loopback_stack from e2e conftest"
```

---

## Task 16: 重写 `tests/integration/test_hci_init.py`

**Files:**
- Modify: `tests/integration/test_hci_init.py`

- [x] **Step 16.1: Read current tests to understand intent**

```bash
cat tests/integration/test_hci_init.py
uv run pytest tests/integration/test_hci_init.py -v --transport=virtual
```

Inventory the existing test functions and their assertions. The migration must preserve **every existing test name and every assertion**. Only the per-test setup boilerplate changes.

- [x] **Step 16.2: Translate each test to the `stack` fixture**

For each existing test, apply this transformation:

Before:
```python
async def test_xxx():
    vc = VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:FF"))
    transport = LoopbackTransport(vc)
    hci = HCIController(transport=transport, trace=...)
    await hci.initialize()
    # ... assertions on hci ...
```

After:
```python
async def test_xxx(stack):
    hci = stack.hci
    # ... same assertions on hci ...
```

Delete the inline `class LoopbackTransport: ...` definition at the top of the file (it duplicates `pybluehost.transport.loopback.LoopbackTransport`).

Drop now-unused imports of `VirtualController`, `BDAddress`, `HCIController`, `TraceSystem`.

Keep every test function name and every assertion exactly as before.

- [x] **Step 16.3: Run**

```bash
uv run pytest tests/integration/test_hci_init.py -v --transport=virtual
```

- [x] **Step 16.4: Commit**

```bash
git add tests/integration/test_hci_init.py
git commit -m "refactor(tests): hci init tests use stack fixture"
```

---

## Task 17: 重写 `tests/integration/test_hci_l2cap.py`

**Files:**
- Modify: `tests/integration/test_hci_l2cap.py`

- [ ] **Step 17.1: Inspect current tests**

```bash
uv run pytest tests/integration/test_hci_l2cap.py -v --transport=virtual
```

- [ ] **Step 17.2: Translate each test to use `stack` fixture**

Pattern: replace
```python
vc = VirtualController(address=BDAddress.from_string(...))
transport = LoopbackTransport(vc)
hci = HCIController(transport=transport, trace=...)
await hci.initialize()
l2cap = L2CAPManager(hci=hci)
```
with
```python
async def test_xxx(stack):
    l2cap = stack.l2cap
    hci = stack.hci
```

Remove the local `LoopbackTransport` helper class entirely (the production class is now internalized as `VirtualController._HCIPipe` after Task 2; tests should just use the `stack` fixture).

If a test claims to operate on two controllers, **read the test carefully first**: in virtual mode the two `VirtualController` instances are completely independent (no shared radio — see spec §9.3 / §15). If the original test was actually doing cross-controller protocol work (e.g. asserting that adv from VC A is received by VC B), it cannot be migrated as-is — flag the test, mark it `@pytest.mark.real_hardware_only`, and leave a TODO referencing the future VirtualRadio work. If the original test only configures both VCs but does not assert cross-VC traffic (the common case in this codebase), accept `(stack, peer_stack)` and migrate normally.

Keep every test function name and every assertion exactly as before.

- [ ] **Step 17.3: Run**

```bash
uv run pytest tests/integration/test_hci_l2cap.py -v --transport=virtual
```

- [ ] **Step 17.4: Commit**

```bash
git add tests/integration/test_hci_l2cap.py
git commit -m "refactor(tests): use stack fixture in test_hci_l2cap"
```

---

## Task 18: 重写 6 个 `tests/unit/cli/test_app_*.py` 用 `stack` fixture

**Files:**
- Modify: `tests/unit/cli/test_app_ble_scan.py`
- Modify: `tests/unit/cli/test_app_ble_adv.py`
- Modify: `tests/unit/cli/test_app_classic_inquiry.py`
- Modify: `tests/unit/cli/test_app_gatt_server.py`
- Modify: `tests/unit/cli/test_app_hr_monitor.py`
- Modify: `tests/unit/cli/test_app_spp_echo.py`

- [ ] **Step 18.1: Identify all inline `Stack.virtual()` call sites (Task 1 already renamed from `Stack.loopback()`)**

```bash
grep -n "Stack.virtual()" tests/unit/cli/test_app_*.py
```

- [ ] **Step 18.2: For each file, do the same transformation**

Pattern (apply to every test that calls `await Stack.virtual()`):

Before:
```python
from pybluehost.stack import Stack

async def test_xyz():
    stack = await Stack.virtual()
    try:
        # ... existing body that uses `stack` ...
    finally:
        await stack.close()
```

After:
```python
async def test_xyz(stack):
    # ... existing body that uses `stack` ...
```

Drop the `from pybluehost.stack import Stack` import if `Stack` is no longer referenced anywhere in the file.

- [ ] **Step 18.3: Run all six files**

```bash
uv run pytest tests/unit/cli/test_app_ble_scan.py \
              tests/unit/cli/test_app_ble_adv.py \
              tests/unit/cli/test_app_classic_inquiry.py \
              tests/unit/cli/test_app_gatt_server.py \
              tests/unit/cli/test_app_hr_monitor.py \
              tests/unit/cli/test_app_spp_echo.py \
              -v --transport=virtual
```

Expected: all PASS, no `Stack.virtual()` calls remain.

- [ ] **Step 18.4: Commit**

```bash
git add tests/unit/cli/test_app_*.py
git commit -m "refactor(tests): cli app tests use stack fixture"
```

---

## Task 19: 重写 `tests/hardware/test_usb_smoke.py` + `real_hardware_only(transport="usb")`

**Files:**
- Modify: `tests/hardware/test_usb_smoke.py`

- [x] **Step 19.1: Replace file content**

```python
# tests/hardware/test_usb_smoke.py
"""Smoke tests on real USB hardware (any vendor) via the stack fixture."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.real_hardware_only(transport="usb")


@pytest.mark.asyncio
async def test_usb_stack_powers_on(stack):
    """Full stack on real hardware: powered, has BD_ADDR."""
    assert stack.is_powered
    assert stack.local_address is not None
    assert str(stack.local_address) != "00:00:00:00:00:00"


@pytest.mark.asyncio
async def test_usb_stack_reset(stack):
    """power_off / power_on round-trip restores is_powered."""
    await stack.power_off()
    assert not stack.is_powered
    await stack.power_on()
    assert stack.is_powered
```

- [x] **Step 19.2: Run on virtual (must skip)**

```bash
uv run pytest tests/hardware/test_usb_smoke.py -v --transport=virtual
```

Expected: 2 skipped, 0 failed.

- [x] **Step 19.3: Run on UART spec (must skip — wrong transport family)**

```bash
uv run pytest tests/hardware/test_usb_smoke.py -v --transport=uart:/dev/null
```

Expected: collection-phase exit 4 (UART port doesn't open) — confirming the explicit-transport pre-flight rejects bad UART specs before tests run.

- [x] **Step 19.4: Commit**

```bash
git add tests/hardware/test_usb_smoke.py
git commit -m "refactor(tests): test_usb_smoke uses real_hardware_only(transport='usb')"
```

---

## Task 20: 切换 `tests/hardware/test_intel_hw.py` 标记

**Files:**
- Modify: `tests/hardware/test_intel_hw.py`

- [ ] **Step 20.1: Replace `pytestmark`**

In `tests/hardware/test_intel_hw.py`, replace the `pytestmark` block with the explicit-vendor marker:

```python
pytestmark = pytest.mark.real_hardware_only(transport="usb", vendor="intel")
```

Drop the previous `pytest.mark.skipif(_HW is None, ...)` line — when the user explicitly passes `--transport=usb:vendor=intel` and no Intel device is plugged in, `_resolve_primary_spec` already exits with code 4 at collection time. When the user does anything else (autodetect, virtual, non-Intel USB), the new marker handles the skip with a precise reason.

The module-level `_detect_intel_device()` helper and the raw-USB fixtures (`hw_device`, `hw_chip`) remain unchanged — they are still needed for the raw HCI tests in this file (which bypass `Stack` and operate at endpoint level).

- [ ] **Step 20.2: Run on virtual (must skip)**

```bash
uv run pytest tests/hardware/test_intel_hw.py -v --transport=virtual
```

Expected: all tests skipped with reason "requires real hardware".

- [ ] **Step 20.3: Run on a non-Intel USB spec (must skip with vendor reason)**

```bash
uv run pytest tests/hardware/test_intel_hw.py -v --transport=usb:vendor=realtek 2>&1 | head -20
```

Expected: either exit 4 (no Realtek device on host) or all tests skipped with reason "requires vendor in ('intel',), got 'realtek'". Either is correct; what must NOT happen is the tests running against the wrong adapter.

- [ ] **Step 20.4: Commit**

```bash
git add tests/hardware/test_intel_hw.py
git commit -m "refactor(tests): test_intel_hw uses real_hardware_only(transport='usb', vendor='intel')"
```

---

## Task 21: 更新 CI workflow

**Files:**
- Modify: `.github/workflows/test.yml`

- [ ] **Step 21.1: Replace pytest invocations**

Change the four `Run *` steps in `.github/workflows/test.yml` to use `--transport=virtual` and remove the `-m "not hardware"` filter:

```yaml
      - name: Run unit tests
        run: uv run pytest tests/unit/ -v --tb=short --transport=virtual

      - name: Run integration tests
        run: uv run pytest tests/integration/ -v --tb=short --transport=virtual

      - name: Run btsnoop tests
        run: uv run pytest tests/btsnoop/ -v --tb=short

      - name: Run full test suite with coverage
        run: |
          uv run pytest tests/ -v --tb=short \
            --transport=virtual \
            --cov=pybluehost \
            --cov-report=xml \
            --cov-report=term-missing \
            --cov-fail-under=85
```

- [ ] **Step 21.2: Validate locally with the same command**

```bash
uv run pytest tests/ -v --tb=short \
  --transport=virtual \
  --cov=pybluehost \
  --cov-report=term-missing \
  --cov-fail-under=85
```

Expected: all PASS, coverage ≥ 85%.

If coverage drops below 85% because of newly-added hardware-only branches, add narrow `# pragma: no cover` to the import / open lines in `Stack.from_usb` / `Stack.from_uart` (NOT to logic — only to the unconditional construction lines that depend on hardware).

- [ ] **Step 21.3: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "ci: switch test suite to --transport=virtual"
```

---

## Task 22: 更新 `README.md` 与 `CLAUDE.md`

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 22.1: Update README.md "运行测试" section**

Locate the "运行测试" or equivalent section in `README.md` and add:

```markdown
### 选择 transport

测试默认自动检测 USB 蓝牙适配器；找不到时回落到 virtual（软件仿真控制器）。

```bash
# 默认（自动检测）
uv run pytest tests/

# 强制 virtual（CI 用）
uv run pytest tests/ --transport=virtual

# 真硬件
uv run pytest tests/ --transport=usb
uv run pytest tests/ --transport=usb:vendor=intel
uv run pytest tests/ --transport=usb:vendor=intel,bus=1,address=4

# UART
uv run pytest tests/ --transport=uart:/dev/ttyUSB0@921600

# 双适配器测试（peer 自动找第二块；找不到则跳过）
uv run pytest tests/ --transport=usb --transport-peer=usb:vendor=intel,bus=2,address=5

# 通过环境变量
PYBLUEHOST_TEST_TRANSPORT=usb uv run pytest tests/

# 列出所有检测到的适配器
uv run pytest --list-transports
```

测试可以用 `@pytest.mark.real_hardware_only` 或 `@pytest.mark.virtual_only` 限制运行环境。
```

同时检查 README 中已有的 CLI 用法示例，把任何 `--transport loopback` 替换为 `--transport virtual`。

- [ ] **Step 22.2: Update CLAUDE.md "常用测试命令"**

Append to the "常用测试命令" section:

```markdown
# Transport 选择
uv run pytest tests/ --transport=virtual            # 强制虚拟控制器
uv run pytest tests/ --transport=usb                # 真硬件（自动检测）
uv run pytest tests/ --transport=usb:vendor=intel   # 限定厂商
uv run pytest --list-transports                     # 诊断
```

- [ ] **Step 22.3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document --transport pytest options"
```

---

## Task 23: 最终验证 + STATUS.md 更新

**Files:**
- Modify: `docs/superpowers/STATUS.md`

- [ ] **Step 23.1: Run full suite in default mode (autodetect → virtual on dev box)**

```bash
uv run pytest tests/ -q
```

Expected:
- Header line: `[pybluehost-tests] transport: virtual [auto-detected — no hardware found]`
- All tests pass or skip cleanly (no errors)
- Terminal summary at end shows the fallback warning with non-zero count

- [ ] **Step 23.2: Run full suite explicitly on virtual (CI scenario)**

```bash
uv run pytest tests/ -q --transport=virtual --cov=pybluehost --cov-fail-under=85
```

Expected: PASS, coverage ≥ 85%, **no** fallback summary.

- [ ] **Step 23.3: Verify error paths**

```bash
uv run pytest tests/ -q --transport=garbage
```

Expected: exit code 4, message containing "Invalid transport spec".

```bash
uv run pytest tests/ -q --transport=usb --transport-peer=virtual
```

Expected: exit code != 0; message either "Peer transport must match primary family" or "Transport 'usb' unavailable".

- [ ] **Step 23.4: Verify --list-transports**

```bash
uv run pytest --list-transports
```

Expected: prints either "No Bluetooth USB adapters detected." or a list of adapters; exit code 0.

- [ ] **Step 23.5: Verify rename leaves no residue**

```bash
grep -rn "Stack.loopback\|StackMode.LOOPBACK\|loopback_peer_with\|_loopback_peer" pybluehost/ tests/ --include="*.py"
grep -rn "loopback_only" tests/ pyproject.toml
grep -rn -- "--transport=loopback\|--transport loopback" . --include="*.md" --include="*.yml" --include="*.py"
```

Expected: 0 matches across all three.

- [ ] **Step 23.6: Update `docs/superpowers/STATUS.md`**

Add a row to the "Plan 总览" table for "Pytest Transport Selection" with status ✅, and append a detail block at the end:

```markdown
### ✅ Pytest Transport Selection
- 设计文档：`docs/superpowers/specs/pytest-transport-selection-design.md`
- 实施计划：`docs/superpowers/plans/pytest-transport-selection.md`
- 完成时间：YYYY-MM-DD
- 关键变化：
  - `loopback` → `virtual` 全栈改名（`Stack.virtual()`、`StackMode.VIRTUAL`、CLI `--transport=virtual`、marker `virtual_only`、`pybluehost/cli/_virtual_peer.py`）
  - 删除 `--hardware` flag、`hardware_required` fixture、`pytest.mark.hardware`
  - 新增 `--transport` / `--transport-peer` / `--list-transports` 选项
  - 新增 `stack` / `peer_stack` 测试 fixture 与 `Stack.from_usb()` / `Stack.from_uart()` 工厂
  - 新增 `real_hardware_only` / `virtual_only` 标记
  - CI 切换为 `--transport=virtual`
```

- [ ] **Step 23.7: Final commit**

```bash
git add docs/superpowers/STATUS.md docs/superpowers/plans/pytest-transport-selection.md
git commit -m "docs(progress): mark pytest transport selection plan complete"
```

---

## 常见问题 / Troubleshooting

（执行过程中发现的问题在这里追加，格式见 `CLAUDE.md` 的"遇到问题时必须记录"。）

### Q: Task 2 full-suite verification is blocked by pre-existing hardware tests
- **现象**：`uv run pytest tests/ -q -m "not hardware"` still executes `tests/hardware/test_intel_hw.py` on this worktree and fails in Intel BE200 USB timeout paths. Full-suite `uv run pytest tests/ -q` is therefore not a valid Task 2 completion claim yet.
- **原因**：The later transport-selection marker tasks have not yet isolated hardware-only tests, so current marker filtering does not reliably exclude all hardware tests.
- **解决方案**：For Task 2, verify the new virtual-controller behavior with targeted tests and broad non-hardware collection/run using `uv run pytest tests/ -q --ignore=tests/hardware`. Re-run full-suite verification after the later marker enforcement tasks land.
- **记录人**：Codex session，2026-04-27
