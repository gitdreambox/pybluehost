# PRD 1.0 收尾 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 PRD v1.0 §5.7 / §9 验收指标中 8 项可验证缺口里的"立即可做" 5 项 + 1 个真实 dispatch bug，让 1.0 真正可发版。

**Architecture:** 不改变现有分层。所有改动局限在 `pybluehost/core`、`pybluehost/stack.py`、`pybluehost/classic/rfcomm.py`、`pybluehost/l2cap/manager.py`、`pybluehost/gap.py` 五个文件 + 一个新 trace sink。SMP 装配只完成"通道 + delegate 装配"的物理路径，不做配对状态机本体（这是单独的 Plan 11+ 范围，会在最后一节注明）。

**Tech Stack:** Python 3.10+、asyncio、pytest（带 `--transport=virtual`）、struct（pcapng 二进制）。

**评审报告基线**：[review-notes-2026-05-12.md](../../architecture/review-notes-2026-05-12.md)

---

## 范围声明

本 Plan **包含**：

1. PcapngSink（PRD §5.7）
2. `ReplayModeError` 新错误类型
3. `Stack.loopback()` 别名 + `Stack.build()` 通用工厂
4. `Stack.from_tcp(host, port)`
5. `Stack.from_btsnoop(path)` + `StackMode.REPLAY` 守卫
6. 修 `RFCOMMSession._on_frame` 阻塞 dispatch 的真实 bug
7. `StackConfig.bond_storage` 字段
8. `L2CAPManager.on_le_connection_open(callback)` 钩子
9. `Stack._build` 装配 SMPManager + 绑定 `CID_SMP` 通道 + 最小 `on_pdu` 占位（PAIRING_FAILED 反馈）

本 Plan **不包含**（明确推迟）：

- 完整的 SMP 配对状态机（Legacy / Secure Connections / Passkey / Numeric Comparison）—— 单独立 Plan。
- HCI 容错初始化（`Read_Local_Supported_Commands` bitmap 跳过逻辑）—— 单独 Plan。
- 断线自动重连闭环 —— 单独 Plan。
- 拆 `transport/usb.py` god module —— 单独 Plan。
- `tests/e2e/` 端到端覆盖 —— 单独 Plan。

---

## 文件改动清单

| 类型 | 路径 | 责任 |
|------|------|------|
| Modify | `pybluehost/core/errors.py` | 新增 `ReplayModeError` |
| Modify | `pybluehost/core/trace.py` | 新增 `PcapngSink` |
| Modify | `pybluehost/core/__init__.py` | 导出 `PcapngSink`、`ReplayModeError` |
| Modify | `pybluehost/ble/smp.py` | 给 `SMPManager` 补 `on_pdu()` 占位方法 |
| Modify | `pybluehost/l2cap/manager.py` | 增加 `on_le_connection_open(callback)` 钩子 |
| Modify | `pybluehost/stack.py` | 4 个工厂方法、REPLAY 守卫、SMP 装配、bond_storage 字段 |
| Modify | `pybluehost/gap.py` | `set_pairing_delegate` 真正下发 |
| Modify | `pybluehost/classic/rfcomm.py` | 修 dispatch 阻塞 |
| Create | `tests/unit/core/test_pcapng_sink.py` | PcapngSink 单测 |
| Modify | `tests/unit/test_stack_factories.py` | 新工厂方法测试 |
| Modify | `tests/unit/test_stack.py` | REPLAY 模式守卫测试、bond_storage 字段测试 |
| Create | `tests/unit/ble/test_smp_manager_assembly.py` | SMP 装配单测 |
| Create | `tests/unit/l2cap/test_manager_le_connection_callback.py` | L2CAP 钩子单测 |
| Modify | `tests/unit/classic/test_rfcomm.py` | 已有的 `test_rfcomm_inbound_handler_does_not_block_future_frames` 改为绿 |
| Modify | `docs/superpowers/STATUS.md` | 标记 Plan 10 PcapngSink/回放声明回滚，新增本 Plan 入条目 |

---

## 任务依赖图

```
Task 1 (PcapngSink) ─────────────────────┐
Task 2 (ReplayModeError) ─► Task 5 ─────┐ │
Task 3 (loopback alias + build) ────────┤ │
Task 4 (from_tcp) ──────────────────────┤ │
Task 5 (from_btsnoop + REPLAY 守卫) ────┤ │
                                         ├─┴─► Task 10 (全量回归)
Task 6 (RFCOMM dispatch fix) ───────────┤
Task 7 (StackConfig.bond_storage) ──┐   │
Task 8 (L2CAP LE callback) ──┐      │   │
                              ├─► Task 9 (SMP 装配)
                                  │   │
                                  └───┘
```

Task 1/3/4/6 完全独立；Task 5 依赖 Task 2；Task 9 依赖 Task 7+8。可按编号顺序串行，也可让 1/3/4/6 并行后再做 5/7/8/9。

---

## Task 1: PcapngSink

**Files:**
- Modify: `pybluehost/core/trace.py`（在 `BtsnoopSink` 之后追加 `PcapngSink`）
- Modify: `pybluehost/core/__init__.py`（导出 `PcapngSink`）
- Create: `tests/unit/core/test_pcapng_sink.py`

### Step 1.1: 写失败测试

- [ ] **Create `tests/unit/core/test_pcapng_sink.py`:**

```python
"""PcapngSink unit tests."""
from __future__ import annotations

import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pybluehost.core import Direction, PcapngSink, TraceEvent


def _evt(layer: str, direction: Direction, payload: bytes) -> TraceEvent:
    return TraceEvent(
        timestamp=0.0,
        wall_clock=datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc),
        source_layer=layer,
        direction=direction,
        raw_bytes=payload,
        decoded=None,
        connection_handle=None,
        metadata={},
    )


async def test_pcapng_sink_writes_shb_idb_and_epb(tmp_path: Path) -> None:
    path = tmp_path / "trace.pcapng"
    sink = PcapngSink(path)

    await sink.on_trace(_evt("hci", Direction.DOWN, b"\x01\x03\x0c\x00"))
    await sink.on_trace(_evt("hci", Direction.UP, b"\x04\x0e\x04\x05\x03\x0c\x00"))
    await sink.close()

    data = path.read_bytes()

    # Section Header Block (SHB): type 0x0A0D0D0A
    shb_type, shb_total_len, byte_order_magic = struct.unpack_from("<IIi", data, 0)
    assert shb_type == 0x0A0D0D0A
    # Byte order magic in little-endian SHB
    assert byte_order_magic == 0x1A2B3C4D

    # Next block should be Interface Description Block (IDB): type 0x00000001
    idb_offset = shb_total_len
    idb_type, idb_total_len = struct.unpack_from("<II", data, idb_offset)
    assert idb_type == 0x00000001
    # LinkType field at offset+8: BLUETOOTH_HCI_H4_WITH_PHDR = 201
    linktype = struct.unpack_from("<H", data, idb_offset + 8)[0]
    assert linktype == 201

    # Two Enhanced Packet Blocks (EPB): type 0x00000006
    epb1_offset = idb_offset + idb_total_len
    epb1_type, epb1_total_len = struct.unpack_from("<II", data, epb1_offset)
    assert epb1_type == 0x00000006

    epb2_offset = epb1_offset + epb1_total_len
    epb2_type, _ = struct.unpack_from("<II", data, epb2_offset)
    assert epb2_type == 0x00000006


async def test_pcapng_sink_skips_non_hci_layers(tmp_path: Path) -> None:
    path = tmp_path / "trace.pcapng"
    sink = PcapngSink(path)
    await sink.on_trace(_evt("att", Direction.DOWN, b"\x02\x01"))
    await sink.close()

    data = path.read_bytes()
    # No EPB written (only SHB + IDB present)
    assert data.count(struct.pack("<I", 0x00000006)) == 0


async def test_pcapng_sink_skips_empty_raw_bytes(tmp_path: Path) -> None:
    path = tmp_path / "trace.pcapng"
    sink = PcapngSink(path)
    await sink.on_trace(_evt("hci", Direction.DOWN, b""))
    await sink.close()

    data = path.read_bytes()
    assert data.count(struct.pack("<I", 0x00000006)) == 0
```

### Step 1.2: 运行测试确认失败

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/core/test_pcapng_sink.py -v --transport=virtual
```

Expected: FAIL —— `ImportError: cannot import name 'PcapngSink'`.

### Step 1.3: 实现 PcapngSink

- [ ] **Modify `pybluehost/core/trace.py`**: 在 `BtsnoopSink` 类（约 line 228）之后、`StateMachineTraceBridge` 之前追加：

```python
# ---------------------------------------------------------------------------
# PcapngSink — pcapng (PCAP-NG v1.0) format, LinkType BLUETOOTH_HCI_H4_WITH_PHDR
# ---------------------------------------------------------------------------

# pcapng block types
_PCAPNG_SHB = 0x0A0D0D0A   # Section Header Block
_PCAPNG_IDB = 0x00000001   # Interface Description Block
_PCAPNG_EPB = 0x00000006   # Enhanced Packet Block
# LinkType: see https://www.tcpdump.org/linktypes.html
_PCAPNG_LINKTYPE_BLUETOOTH_HCI_H4_WITH_PHDR = 201
# pcapng EPB timestamp resolution is microseconds (if_tsresol option absent → 10^-6)


class PcapngSink:
    """pcapng file sink — Wireshark-native format, complements BtsnoopSink."""

    _HCI_LAYERS = {"transport", "hci"}

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._file = open(self._path, "wb")
        self._write_shb()
        self._write_idb()

    def _write_shb(self) -> None:
        # Section Header Block: type + total_length + byte_order_magic
        # + major_version + minor_version + section_length (-1) + total_length(end)
        body = _struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1)
        total_length = 8 + len(body) + 4
        self._file.write(_struct.pack("<II", _PCAPNG_SHB, total_length))
        self._file.write(body)
        self._file.write(_struct.pack("<I", total_length))

    def _write_idb(self) -> None:
        # Interface Description Block: type + total_length + linktype + reserved
        # + snaplen + (no options) + total_length(end)
        body = _struct.pack(
            "<HHI",
            _PCAPNG_LINKTYPE_BLUETOOTH_HCI_H4_WITH_PHDR,
            0,           # reserved
            0,           # snaplen 0 = no limit
        )
        total_length = 8 + len(body) + 4
        self._file.write(_struct.pack("<II", _PCAPNG_IDB, total_length))
        self._file.write(body)
        self._file.write(_struct.pack("<I", total_length))

    async def on_trace(self, event: TraceEvent) -> None:
        if event.source_layer not in self._HCI_LAYERS:
            return
        if not event.raw_bytes:
            return

        # Per LINKTYPE_BLUETOOTH_HCI_H4_WITH_PHDR: 4-byte pseudo-header
        # (big-endian uint32: 0=sent, 1=received) followed by H4 packet.
        direction_flag = 1 if event.direction == Direction.UP else 0
        phdr = _struct.pack(">I", direction_flag)
        payload = phdr + event.raw_bytes
        captured_len = len(payload)
        original_len = captured_len

        # pad payload to 4-byte boundary
        pad = (-captured_len) % 4
        payload_padded = payload + b"\x00" * pad

        # Timestamp in microseconds since epoch, split into high/low 32-bit words
        ts_us = int(event.wall_clock.timestamp() * 1_000_000)
        ts_high = (ts_us >> 32) & 0xFFFFFFFF
        ts_low = ts_us & 0xFFFFFFFF

        body = (
            _struct.pack("<IIIII", 0, ts_high, ts_low, captured_len, original_len)
            + payload_padded
        )
        total_length = 8 + len(body) + 4

        self._file.write(_struct.pack("<II", _PCAPNG_EPB, total_length))
        self._file.write(body)
        self._file.write(_struct.pack("<I", total_length))
        self._file.flush()

    async def flush(self) -> None:
        if not self._file.closed:
            self._file.flush()

    async def close(self) -> None:
        if not self._file.closed:
            self._file.close()
```

### Step 1.4: 导出符号

- [ ] **Modify `pybluehost/core/__init__.py`**: 在 `from pybluehost.core.trace import (...)` 列表中加 `PcapngSink`，在 `__all__` 中加 `"PcapngSink"`（按字母序）：

```python
from pybluehost.core.trace import (
    BtsnoopSink,
    CallbackSink,
    Direction,
    JsonSink,
    PcapngSink,
    RingBufferSink,
    StateMachineTraceBridge,
    TraceEvent,
    TraceSystem,
)
```

并在 `__all__` 列表插入 `"PcapngSink",`（保持字母序，在 `"PyBlueHostError"` 之前 / `"JsonSink"` 之后）。

### Step 1.5: 跑测试确认绿

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/core/test_pcapng_sink.py -v --transport=virtual
```

Expected: 3 passed.

### Step 1.6: 提交

- [ ] **Commit:**

```bash
git add pybluehost/core/trace.py pybluehost/core/__init__.py tests/unit/core/test_pcapng_sink.py
git commit -m "feat(core): add PcapngSink for pcapng trace output

Closes PRD §5.7 pcapng requirement and §9 'Wireshark 可直接打开 pcapng'
acceptance indicator. Uses LinkType 201 (BLUETOOTH_HCI_H4_WITH_PHDR)
with 4-byte direction pseudo-header."
```

---

## Task 2: ReplayModeError

**Files:**
- Modify: `pybluehost/core/errors.py`
- Modify: `pybluehost/core/__init__.py`

### Step 2.1: 加错误类

- [ ] **Modify `pybluehost/core/errors.py`**: 在 `TimeoutError` 类之后、`CommandTimeoutError` 之前追加：

```python
class ReplayModeError(PyBlueHostError):
    """Raised when a write/transmit operation is attempted on a REPLAY-mode Stack."""
```

### Step 2.2: 导出

- [ ] **Modify `pybluehost/core/__init__.py`**:
  - 在 `from pybluehost.core.errors import (...)` 中加 `ReplayModeError`
  - 在 `__all__` 中加 `"ReplayModeError",`（字母序）

### Step 2.3: 验证 import

- [ ] **Run:**

```bash
uv run --frozen python -c "from pybluehost.core import ReplayModeError; print(ReplayModeError.__mro__)"
```

Expected: 打印 MRO 含 `PyBlueHostError`、`Exception`、`BaseException`。

### Step 2.4: 提交

- [ ] **Commit:**

```bash
git add pybluehost/core/errors.py pybluehost/core/__init__.py
git commit -m "feat(core): add ReplayModeError for REPLAY-mode write guard"
```

---

## Task 3: Stack.loopback() 别名 + Stack.build() 通用工厂

**Files:**
- Modify: `pybluehost/stack.py`
- Modify: `tests/unit/test_stack_factories.py`

### Step 3.1: 写失败测试

- [ ] **Modify `tests/unit/test_stack_factories.py`**: 在文件末尾追加：

```python
async def test_loopback_is_alias_for_virtual():
    """PRD §5.7 reserves the name Stack.loopback(); virtual() is the impl."""
    from pybluehost.stack import Stack, StackMode

    stack = await Stack.loopback()
    try:
        assert stack.mode == StackMode.VIRTUAL
        assert stack.is_powered is True
    finally:
        await stack.close()


async def test_build_factory_uses_provided_transport():
    """Stack.build(transport) wires arbitrary transport through _build."""
    from pybluehost.hci.virtual import VirtualController
    from pybluehost.stack import Stack, StackMode

    vc, host_transport = await VirtualController.create()
    stack = await Stack.build(host_transport, mode=StackMode.VIRTUAL)
    try:
        assert stack.mode == StackMode.VIRTUAL
        assert stack._transport is host_transport
    finally:
        await stack.close()
```

### Step 3.2: 运行测试确认失败

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/test_stack_factories.py::test_loopback_is_alias_for_virtual tests/unit/test_stack_factories.py::test_build_factory_uses_provided_transport -v --transport=virtual
```

Expected: 2 failed —— `AttributeError: type object 'Stack' has no attribute 'loopback'` / `'build'`.

### Step 3.3: 实现 loopback() 别名 + build()

- [ ] **Modify `pybluehost/stack.py`**: 在 `virtual` classmethod 之后（约 line 279，紧接 `return stack` 之后空行）追加：

```python
    @classmethod
    async def loopback(cls, config: StackConfig | None = None) -> Stack:
        """PRD §5.7-compatible alias for :meth:`virtual`.

        Provided so user code following PRD documentation (Stack.loopback())
        continues to work after the internal rename to virtual().
        """
        return await cls.virtual(config=config)

    @classmethod
    async def build(
        cls,
        transport: Any,
        *,
        config: StackConfig | None = None,
        mode: StackMode = StackMode.LIVE,
    ) -> Stack:
        """Generic factory: assemble a Stack on a caller-provided transport.

        The transport must already be opened. On build failure the transport
        is left open (the caller owns it). For one-shot use prefer
        ``from_usb`` / ``from_uart`` / ``from_tcp`` / ``from_btsnoop``.
        """
        return await cls._build(transport, config, mode)
```

### Step 3.4: 跑测试确认绿

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/test_stack_factories.py -v --transport=virtual
```

Expected: all passed (含原有 5 个 + 新 2 个).

### Step 3.5: 提交

- [ ] **Commit:**

```bash
git add pybluehost/stack.py tests/unit/test_stack_factories.py
git commit -m "feat(stack): add Stack.loopback() alias and Stack.build() factory

Closes PRD §5.7 factory list gap. loopback() preserves the documented
public name; build() exposes the internal assembly path for callers that
construct their own transport."
```

---

## Task 4: Stack.from_tcp()

**Files:**
- Modify: `pybluehost/stack.py`
- Modify: `tests/unit/test_stack_factories.py`

### Step 4.1: 写失败测试

- [ ] **Modify `tests/unit/test_stack_factories.py`**: 在末尾追加：

```python
async def test_from_tcp_constructs_tcp_transport(monkeypatch):
    """Stack.from_tcp(host, port) instantiates TCPTransport with the args."""
    from pybluehost import stack as stack_module
    from pybluehost.stack import Stack, StackMode

    captured = {}

    class FakeTCPTransport:
        def __init__(self, host: str, port: int) -> None:
            captured["host"] = host
            captured["port"] = port

        async def open(self) -> None:
            captured["opened"] = True

        async def close(self) -> None:
            captured["closed"] = True

    async def fake_build(cls, transport, config, mode):
        captured["transport"] = transport
        captured["mode"] = mode
        return Stack()

    monkeypatch.setattr(
        "pybluehost.transport.tcp.TCPTransport", FakeTCPTransport
    )
    monkeypatch.setattr(Stack, "_build", classmethod(fake_build))

    await Stack.from_tcp("localhost", 9000)

    assert captured["host"] == "localhost"
    assert captured["port"] == 9000
    assert captured["opened"] is True
    assert captured["mode"] == StackMode.LIVE


async def test_from_tcp_closes_transport_when_build_fails(monkeypatch):
    from pybluehost.stack import Stack

    closed = {"value": False}

    class FakeTCPTransport:
        def __init__(self, host: str, port: int) -> None:
            pass

        async def open(self) -> None:
            return None

        async def close(self) -> None:
            closed["value"] = True

    async def fake_build_raises(cls, transport, config, mode):
        raise RuntimeError("init failed")

    monkeypatch.setattr(
        "pybluehost.transport.tcp.TCPTransport", FakeTCPTransport
    )
    monkeypatch.setattr(Stack, "_build", classmethod(fake_build_raises))

    with pytest.raises(RuntimeError, match="init failed"):
        await Stack.from_tcp("localhost", 9000)
    assert closed["value"] is True
```

并确保文件顶部已有 `import pytest`（若无则添加）。

### Step 4.2: 运行测试确认失败

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/test_stack_factories.py::test_from_tcp_constructs_tcp_transport tests/unit/test_stack_factories.py::test_from_tcp_closes_transport_when_build_fails -v --transport=virtual
```

Expected: 2 failed —— `AttributeError: type object 'Stack' has no attribute 'from_tcp'`.

### Step 4.3: 实现 from_tcp

- [ ] **Modify `pybluehost/stack.py`**: 在 `from_uart` classmethod 之后、`virtual` classmethod 之前追加：

```python
    @classmethod
    async def from_tcp(
        cls,
        host: str,
        port: int,
        config: StackConfig | None = None,
    ) -> Stack:
        """Build a live Stack on a TCP HCI link (commonly btvirt/QEMU)."""
        from pybluehost.transport.tcp import TCPTransport

        transport = TCPTransport(host, port)
        await transport.open()
        try:
            return await cls._build(transport, config, StackMode.LIVE)
        except Exception:
            close = getattr(transport, "close", None)
            if close is not None:
                await close()
            raise
```

### Step 4.4: 跑测试确认绿

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/test_stack_factories.py -v --transport=virtual
```

Expected: all passed.

### Step 4.5: 提交

- [ ] **Commit:**

```bash
git add pybluehost/stack.py tests/unit/test_stack_factories.py
git commit -m "feat(stack): add Stack.from_tcp(host, port) factory

Closes PRD §5.7 from_tcp gap. Mirrors the existing from_uart pattern:
construct, open, _build, close on failure."
```

---

## Task 5: Stack.from_btsnoop() + REPLAY 守卫

**Depends on:** Task 2 (`ReplayModeError`)

**Files:**
- Modify: `pybluehost/stack.py`
- Modify: `tests/unit/test_stack_factories.py`
- Modify: `tests/unit/test_stack.py`

### Step 5.1: 写失败测试

- [ ] **Modify `tests/unit/test_stack_factories.py`**: 在末尾追加：

```python
async def test_from_btsnoop_sets_replay_mode(tmp_path, monkeypatch):
    from pybluehost.stack import Stack, StackMode

    # minimal valid btsnoop file (header only, no records)
    snoop_path = tmp_path / "trace.cfa"
    snoop_path.write_bytes(b"btsnoop\x00" + b"\x00" * 8)

    captured = {}

    async def fake_build(cls, transport, config, mode):
        captured["mode"] = mode
        captured["transport"] = transport
        stack = Stack()
        stack._mode = mode
        return stack

    monkeypatch.setattr(Stack, "_build", classmethod(fake_build))

    stack = await Stack.from_btsnoop(str(snoop_path))
    assert captured["mode"] == StackMode.REPLAY
    assert stack.mode == StackMode.REPLAY
```

- [ ] **Modify `tests/unit/test_stack.py`**: 在文件末尾追加（必要时 import 调整）：

```python
async def test_replay_mode_rejects_connect_gatt():
    from pybluehost.core.address import BDAddress
    from pybluehost.core.errors import ReplayModeError
    from pybluehost.stack import Stack, StackMode

    stack = Stack()
    stack._mode = StackMode.REPLAY
    stack._gap = object()
    stack._l2cap = object()

    with pytest.raises(ReplayModeError):
        await stack.connect_gatt(BDAddress(b"\x01\x02\x03\x04\x05\x06"))


async def test_replay_mode_rejects_connect_classic():
    from pybluehost.core.address import BDAddress
    from pybluehost.core.errors import ReplayModeError
    from pybluehost.stack import Stack, StackMode

    stack = Stack()
    stack._mode = StackMode.REPLAY
    stack._gap = object()
    stack._l2cap = object()

    with pytest.raises(ReplayModeError):
        await stack.connect_classic(BDAddress(b"\x01\x02\x03\x04\x05\x06"))
```

### Step 5.2: 运行测试确认失败

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/test_stack_factories.py::test_from_btsnoop_sets_replay_mode tests/unit/test_stack.py::test_replay_mode_rejects_connect_gatt tests/unit/test_stack.py::test_replay_mode_rejects_connect_classic -v --transport=virtual
```

Expected: 3 failed —— missing `from_btsnoop`, no REPLAY guard.

### Step 5.3: 实现 from_btsnoop + 守卫

- [ ] **Modify `pybluehost/stack.py`**: 在 `from_tcp` 之后、`virtual` 之前追加：

```python
    @classmethod
    async def from_btsnoop(
        cls,
        path: str,
        *,
        realtime: bool = False,
        config: StackConfig | None = None,
    ) -> Stack:
        """Build a REPLAY-mode Stack that consumes a btsnoop capture file.

        Write operations (advertising, scanning, connecting, sending) raise
        :class:`ReplayModeError`. Use for offline reproduction of recorded
        sessions (PRD §3 P1, §9 acceptance indicator).
        """
        from pybluehost.transport.btsnoop import BtsnoopTransport

        transport = BtsnoopTransport(path, realtime=realtime)
        await transport.open()
        try:
            return await cls._build(transport, config, StackMode.REPLAY)
        except Exception:
            close = getattr(transport, "close", None)
            if close is not None:
                await close()
            raise
```

- [ ] **Modify `pybluehost/stack.py`**: 在 `Stack` 类定义中（约 line 67 类开头之后、`def __init__` 之前）增加私有守卫方法。把以下方法放在 `_emit_connection_event` 之后、`connect_gatt` 之前：

```python
    def _check_writable(self) -> None:
        """Raise ReplayModeError if Stack is in REPLAY mode."""
        if self._mode == StackMode.REPLAY:
            from pybluehost.core.errors import ReplayModeError
            raise ReplayModeError(
                f"Operation not permitted in REPLAY mode (transport: "
                f"{type(self._transport).__name__})"
            )
```

- [ ] **Modify `pybluehost/stack.py`**: 在以下四个公有写方法的第一行（紧跟方法体起始 `"""docstring"""` 之后）插入 `self._check_writable()`：
  - `connect_gatt`（约 line 466）
  - `connect_classic`（约 line 501）
  - `authenticate_classic`（约 line 523）
  - `enable_classic_encryption`（约 line 549）

例如 `connect_gatt`：

```python
    async def connect_gatt(
        self,
        target: BDAddress,
        *,
        timeout: float = 10.0,
    ) -> Any:
        """Connect to a BLE peer and return a GATT client bound to ATT CID."""
        self._check_writable()
        if self._gap is None or self._l2cap is None:
            raise RuntimeError("Stack is not initialized")
```

四处同样模式。

### Step 5.4: 跑测试确认绿

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/test_stack_factories.py tests/unit/test_stack.py -v --transport=virtual
```

Expected: all passed.

### Step 5.5: 提交

- [ ] **Commit:**

```bash
git add pybluehost/stack.py tests/unit/test_stack_factories.py tests/unit/test_stack.py
git commit -m "feat(stack): add Stack.from_btsnoop() and REPLAY write guard

Closes PRD §3 P1 and §9 acceptance indicator (btsnoop offline replay).
StackMode.REPLAY now actually enforced: connect_gatt / connect_classic /
authenticate_classic / enable_classic_encryption raise ReplayModeError."
```

---

## Task 6: 修 RFCOMM dispatch 阻塞 bug

**Files:**
- Modify: `pybluehost/classic/rfcomm.py`
- 既有失败测试 `tests/unit/classic/test_rfcomm.py::test_rfcomm_inbound_handler_does_not_block_future_frames` 作为回归

### Step 6.1: 复现失败

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/classic/test_rfcomm.py::test_rfcomm_inbound_handler_does_not_block_future_frames -v --transport=virtual
```

Expected: FAIL（前述 STATUS 已知失败）。

### Step 6.2: 诊断

- [ ] **打开 `pybluehost/classic/rfcomm.py:226-264`**（`RFCOMMSession._on_frame`），通读 SABM 分支的现有代码。

预期发现：handler 已经被 `asyncio.create_task` 包装（line 252），但 SABM 路径在 `await self._send_modem_status(frame.dlci)`（line 255）之前有 `await self._send_ua(frame.dlci)`，而 UIH 分支对 dlci 的查找 `self._dlcs.get(frame.dlci)` 在 SABM 处理**之后**才被注册。

若调度顺序导致 UIH frame 到达时 channel 未注册，handler 永远等不到数据 → 0.1s 超时。

实际根因（确认方法）：

```bash
uv run --frozen python -c "
import asyncio
from pybluehost.classic.rfcomm import RFCOMMSession, RFCOMMFrameType, RFCOMMFrame, encode_frame

class FakeChannel:
    def __init__(self): self.events = None; self.sent = []
    def set_events(self, e): self.events = e
    async def send(self, d): self.sent.append(d)

async def main():
    ch = FakeChannel()
    received = []
    async def h(c):
        c.on_data(lambda d: received.append(d))
        await asyncio.sleep(0)  # yield once so registration completes
    RFCOMMSession(l2cap_channel=ch, server_handlers={1: h})
    await ch.events.on_data(encode_frame(RFCOMMFrame(dlci=2, frame_type=RFCOMMFrameType.SABM, pf=True, data=b'')))
    await ch.events.on_data(encode_frame(RFCOMMFrame(dlci=2, frame_type=RFCOMMFrameType.UIH, pf=False, data=b'hi')))
    print('received=', received)
asyncio.run(main())
"
```

如果 `received=[b'hi']`，说明问题在于"handler 不让出控制权"——`channel.on_data(callback)` 只是赋值，task 第一次 `await` 才会真正运行。当前测试的 handler 是 `await asyncio.Event().wait()`，task 在被 `create_task` 时只是被排进 ready 队列，**直到 dispatch coroutine 让出**才会运行；UIH 到达时若 task 尚未跑过 `on_data` 行，`self._data_handler` 仍为 `None`。

### Step 6.3: 修复

- [ ] **Modify `pybluehost/classic/rfcomm.py:250-255`**: SABM 分支在 schedule handler task 后、`await self._send_modem_status` 之前，主动让出一次事件循环，确保 handler 的同步初始化部分（`channel.on_data(...)`）跑完。

将：

```python
                    result = handler(channel)
                    if asyncio.iscoroutine(result):
                        task = asyncio.create_task(result)
                        self._handler_tasks.add(task)
                        task.add_done_callback(self._handler_tasks.discard)
                    await self._send_modem_status(frame.dlci)
```

替换为：

```python
                    result = handler(channel)
                    if asyncio.iscoroutine(result):
                        task = asyncio.create_task(result)
                        self._handler_tasks.add(task)
                        task.add_done_callback(self._handler_tasks.discard)
                        # Yield once so the handler's synchronous setup
                        # (e.g. channel.on_data(...)) runs before subsequent
                        # frames are dispatched to the channel.
                        await asyncio.sleep(0)
                    await self._send_modem_status(frame.dlci)
```

### Step 6.4: 跑测试确认绿

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/classic/test_rfcomm.py -v --transport=virtual
```

Expected: all passed，包括 `test_rfcomm_inbound_handler_does_not_block_future_frames`。

### Step 6.5: 全 classic 回归

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/classic/ -q --transport=virtual
```

Expected: all passed。

### Step 6.6: 提交

- [ ] **Commit:**

```bash
git add pybluehost/classic/rfcomm.py
git commit -m "fix(classic/rfcomm): yield after scheduling SABM handler task

Handler coroutines registered via create_task don't begin executing until
the dispatcher yields, so a UIH frame arriving immediately after SABM
could be dispatched to a channel whose on_data() callback was not yet
set. Inserting asyncio.sleep(0) after task creation lets the handler's
synchronous setup run before subsequent frames flow.

Fixes test_rfcomm_inbound_handler_does_not_block_future_frames."
```

---

## Task 7: StackConfig.bond_storage 字段

**Files:**
- Modify: `pybluehost/stack.py`
- Modify: `tests/unit/test_stack.py`

### Step 7.1: 写失败测试

- [ ] **Modify `tests/unit/test_stack.py`**: 在末尾追加：

```python
async def test_stack_config_accepts_bond_storage():
    from pybluehost.ble.smp import JsonBondStorage
    from pybluehost.stack import StackConfig

    storage = JsonBondStorage(path=":memory:")
    cfg = StackConfig(bond_storage=storage)
    assert cfg.bond_storage is storage


async def test_stack_config_bond_storage_defaults_to_none():
    from pybluehost.stack import StackConfig

    cfg = StackConfig()
    assert cfg.bond_storage is None
```

### Step 7.2: 跑测试确认失败

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/test_stack.py::test_stack_config_accepts_bond_storage tests/unit/test_stack.py::test_stack_config_bond_storage_defaults_to_none -v --transport=virtual
```

Expected: 2 failed —— `TypeError: ... unexpected keyword argument 'bond_storage'`。

### Step 7.3: 实现

- [ ] **Modify `pybluehost/stack.py:25-43`** (`StackConfig`)：

在 import 行追加：

```python
from typing import Any, Callable
```

下面增加：

```python
from pybluehost.ble.smp import BondStorage
```

放在 `from pybluehost.ble.security import SecurityConfig` 之后。

然后在 `StackConfig` dataclass 中（约 line 42 `trace_sinks` 之后）追加：

```python
    # Bond persistence — pluggable backend (PRD §5.4)
    bond_storage: BondStorage | None = None
```

### Step 7.4: 跑测试确认绿

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/test_stack.py -v --transport=virtual
```

Expected: all passed.

### Step 7.5: 提交

- [ ] **Commit:**

```bash
git add pybluehost/stack.py tests/unit/test_stack.py
git commit -m "feat(stack): add StackConfig.bond_storage field

Closes PRD §5.4 'Bond 持久化（本地存储，可插拔后端）'. The field is
plumbed through to SMPManager in the SMP assembly task."
```

---

## Task 8: L2CAPManager LE 连接事件回调

**Files:**
- Modify: `pybluehost/l2cap/manager.py`
- Create: `tests/unit/l2cap/test_manager_le_connection_callback.py`

### Step 8.1: 写失败测试

- [ ] **Create `tests/unit/l2cap/test_manager_le_connection_callback.py`:**

```python
"""L2CAPManager.on_le_connection_open callback hook tests."""
from __future__ import annotations

from pybluehost.core.types import LinkType
from pybluehost.l2cap.constants import CID_ATT, CID_SMP
from pybluehost.l2cap.manager import L2CAPManager


async def test_on_le_connection_open_fires_when_le_connection_registered():
    manager = L2CAPManager(hci=None)
    seen: list[tuple[int, dict]] = []

    def listener(handle: int, channels: dict) -> None:
        seen.append((handle, channels))

    manager.on_le_connection_open(listener)
    await manager.on_connection(
        handle=0x0040, link_type=LinkType.LE, peer_address=None, role=None,
    )

    assert len(seen) == 1
    handle, channels = seen[0]
    assert handle == 0x0040
    assert CID_ATT in channels
    assert CID_SMP in channels


async def test_on_le_connection_open_does_not_fire_for_classic():
    manager = L2CAPManager(hci=None)
    seen: list[int] = []
    manager.on_le_connection_open(lambda h, c: seen.append(h))

    await manager.on_connection(
        handle=0x0080, link_type=LinkType.ACL, peer_address=None, role=None,
    )
    assert seen == []


async def test_on_le_connection_open_supports_multiple_listeners():
    manager = L2CAPManager(hci=None)
    seen_a: list[int] = []
    seen_b: list[int] = []
    manager.on_le_connection_open(lambda h, c: seen_a.append(h))
    manager.on_le_connection_open(lambda h, c: seen_b.append(h))

    await manager.on_connection(
        handle=0x0041, link_type=LinkType.LE, peer_address=None, role=None,
    )

    assert seen_a == [0x0041]
    assert seen_b == [0x0041]
```

### Step 8.2: 跑测试确认失败

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/l2cap/test_manager_le_connection_callback.py -v --transport=virtual
```

Expected: 3 failed —— `AttributeError: ... no attribute 'on_le_connection_open'`.

### Step 8.3: 实现钩子

- [ ] **Modify `pybluehost/l2cap/manager.py`**:

1) 在 `L2CAPManager.__init__` 中（构造各字段处）追加：

```python
        self._le_connection_open_listeners: list[Callable[[int, dict[int, "Channel"]], None]] = []
```

`Callable` 已 import；`Channel` 需要在文件顶部 `TYPE_CHECKING` block 或直接 forward ref（保持 `"Channel"` 字符串即可）。

2) 在类中、`get_fixed_channel` 之前增加方法：

```python
    def on_le_connection_open(
        self,
        listener: Callable[[int, dict[int, "Channel"]], None],
    ) -> None:
        """Register a listener invoked once when an LE connection's fixed
        channels (ATT/SMP/LE signaling) are created.

        Listeners are called synchronously inside on_connection(); they must
        not block. Use this hook to bind upper-layer handlers (e.g. attach
        SMPManager to the CID_SMP channel) instead of polling.
        """
        self._le_connection_open_listeners.append(listener)
```

3) 在 `on_connection` 方法内、`self._connections[handle] = channels` **后**（约 line 159）、`logger.info(...)` **前**，追加：

```python
        if link_type == LinkType.LE:
            for listener in list(self._le_connection_open_listeners):
                try:
                    listener(handle, channels)
                except Exception:
                    logger.exception("LE connection listener raised")
```

### Step 8.4: 跑测试确认绿

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/l2cap/test_manager_le_connection_callback.py tests/unit/l2cap/ -v --transport=virtual
```

Expected: all passed.

### Step 8.5: 提交

- [ ] **Commit:**

```bash
git add pybluehost/l2cap/manager.py tests/unit/l2cap/test_manager_le_connection_callback.py
git commit -m "feat(l2cap): add on_le_connection_open hook

Lets upper layers (Stack, SMPManager binding) react to LE connection
fixed-channel creation without polling. Replaces stack.py's repeated
_attach_gatt_server_to_att_channels scan pattern for future cleanup."
```

---

## Task 9: 装配 SMP 到 Stack

**Depends on:** Task 7 (`StackConfig.bond_storage`) + Task 8 (`on_le_connection_open`)

**Files:**
- Modify: `pybluehost/ble/smp.py`（给 `SMPManager` 加 `on_pdu` 占位方法）
- Modify: `pybluehost/stack.py`
- Modify: `pybluehost/gap.py`
- Create: `tests/unit/ble/test_smp_manager_assembly.py`

### Step 9.1: 写失败测试

- [ ] **Create `tests/unit/ble/test_smp_manager_assembly.py`:**

```python
"""SMPManager assembly + Stack binding tests."""
from __future__ import annotations

import pytest

from pybluehost.ble.smp import (
    PAIRING_FAILED_REASON_UNSPECIFIED,
    SMPCode,
    SMPManager,
)


async def test_smp_manager_on_pdu_responds_pairing_failed_when_no_state_machine():
    """Minimal assembly proof: SMP channel binding works end-to-end.

    Full pairing state machine is a follow-up Plan; for now, on_pdu() replies
    with PAIRING_FAILED(UNSPECIFIED) to any incoming PDU.
    """
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager()
    mgr.bind_channel(connection_handle=0x0040, send=send)

    # Send a PAIRING_REQUEST: opcode 0x01 + IO/OOB/Authreq/MaxKey/IK/RK
    await mgr.on_pdu(b"\x01\x03\x00\x05\x10\x07\x07", connection_handle=0x0040)

    assert len(sent) == 1
    assert sent[0][0] == SMPCode.PAIRING_FAILED
    assert sent[0][1] == PAIRING_FAILED_REASON_UNSPECIFIED


async def test_stack_virtual_assembles_smp_manager():
    """Stack._build constructs SMPManager and exposes it on stack.smp."""
    from pybluehost.stack import Stack

    stack = await Stack.virtual()
    try:
        assert stack.smp is not None
        assert isinstance(stack.smp, SMPManager)
    finally:
        await stack.close()


async def test_stack_virtual_propagates_bond_storage_to_smp():
    from pybluehost.ble.smp import JsonBondStorage
    from pybluehost.stack import Stack, StackConfig

    storage = JsonBondStorage(path=":memory:")
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        assert stack.smp._bond_storage is storage
    finally:
        await stack.close()


async def test_unified_gap_set_pairing_delegate_downstreams_to_smp():
    """gap.set_pairing_delegate must actually reach SMPManager."""
    from pybluehost.ble.smp import AutoAcceptDelegate
    from pybluehost.stack import Stack

    stack = await Stack.virtual()
    try:
        delegate = AutoAcceptDelegate()
        stack.gap.set_pairing_delegate(delegate)
        assert stack.smp._delegate is delegate
    finally:
        await stack.close()
```

### Step 9.2: 跑测试确认失败

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/ble/test_smp_manager_assembly.py -v --transport=virtual
```

Expected: 4 failed —— missing constants, methods, property.

### Step 9.3: 实现 SMPManager.on_pdu / bind_channel + 常量

- [ ] **Modify `pybluehost/ble/smp.py`**: 在文件顶部 `SMPCode` 枚举所在 region 之后（搜索 `class SMPCode`，定位它的尾部）追加模块级常量：

```python
# Pairing Failed reasons (Core 5.4 Vol 3 Part H 3.5.5)
PAIRING_FAILED_REASON_PASSKEY_ENTRY_FAILED = 0x01
PAIRING_FAILED_REASON_OOB_NOT_AVAILABLE     = 0x02
PAIRING_FAILED_REASON_AUTH_REQUIREMENTS     = 0x03
PAIRING_FAILED_REASON_CONFIRM_VALUE_FAILED  = 0x04
PAIRING_FAILED_REASON_PAIRING_NOT_SUPPORTED = 0x05
PAIRING_FAILED_REASON_UNSPECIFIED           = 0x08
```

如果上述名称已存在则跳过；若已有部分常量（grep `PAIRING_FAILED_REASON_`）请只补差额。

然后将 `SMPManager` 类体（替换现有 stub）改为：

```python
class SMPManager:
    """SMP pairing state machine manager.

    Current scope (PRD 1.0 closure): channel binding + delegate plumbing
    works end-to-end. Incoming PDUs are answered with PAIRING_FAILED
    (UNSPECIFIED) until the full state machine ships in a follow-up Plan.
    """

    def __init__(
        self,
        hci: object | None = None,
        bond_storage: BondStorage | None = None,
        delegate: PairingDelegate | AutoAcceptDelegate | None = None,
    ) -> None:
        self._hci = hci
        self._bond_storage = bond_storage
        self._delegate = delegate or AutoAcceptDelegate()
        self._senders: dict[int, Callable[[bytes], Awaitable[None]]] = {}

    def bind_channel(
        self,
        connection_handle: int,
        send: Callable[[bytes], Awaitable[None]],
    ) -> None:
        """Bind an L2CAP CID_SMP channel send-callable to a connection handle."""
        self._senders[connection_handle] = send

    def unbind_channel(self, connection_handle: int) -> None:
        self._senders.pop(connection_handle, None)

    def set_delegate(
        self,
        delegate: PairingDelegate | AutoAcceptDelegate,
    ) -> None:
        self._delegate = delegate

    async def on_pdu(self, data: bytes, *, connection_handle: int) -> None:
        """Handle an inbound SMP PDU.

        Until the full pairing state machine lands, answer with
        PAIRING_FAILED(UNSPECIFIED). This still proves the L2CAP→SMP
        binding works end-to-end and surfaces protocol-level errors.
        """
        send = self._senders.get(connection_handle)
        if send is None:
            return
        if not data:
            return
        response = bytes(
            [SMPCode.PAIRING_FAILED, PAIRING_FAILED_REASON_UNSPECIFIED]
        )
        await send(response)
```

在 `smp.py` 顶部 imports 追加（若未存在）：

```python
from typing import Awaitable, Callable
```

### Step 9.4: 实现 GAP.set_pairing_delegate 下发

- [ ] **Modify `pybluehost/gap.py:28-51`** —— 把现有 `GAP.__init__`（含 body）整段替换为：

```python
    def __init__(
        self,
        ble_advertiser: BLEAdvertiser | None = None,
        ble_scanner: BLEScanner | None = None,
        ble_connections: BLEConnectionManager | None = None,
        ble_privacy: PrivacyManager | None = None,
        classic_discovery: ClassicDiscovery | None = None,
        classic_discoverability: ClassicDiscoverability | None = None,
        classic_connections: ClassicConnectionManager | None = None,
        classic_ssp: SSPManager | None = None,
        whitelist: WhiteList | None = None,
        ble_extended_advertiser: ExtendedAdvertiser | None = None,
        smp: object | None = None,
    ) -> None:
        self._ble_advertiser = ble_advertiser
        self._ble_scanner = ble_scanner
        self._ble_connections = ble_connections
        self._ble_privacy = ble_privacy
        self._classic_discovery = classic_discovery
        self._classic_discoverability = classic_discoverability
        self._classic_connections = classic_connections
        self._classic_ssp = classic_ssp
        self._whitelist = whitelist
        self._ble_extended_advertiser = ble_extended_advertiser
        self._smp = smp
        self._pairing_delegate: object | None = None
```

- [ ] **Modify `pybluehost/gap.py:99-105`** —— 把现有 `set_pairing_delegate` 整段替换为：

```python
    def set_pairing_delegate(self, delegate: object) -> None:
        """Set a common pairing delegate for both BLE SMP and Classic SSP.

        The delegate object can implement methods expected by SMPManager
        (PairingDelegate protocol) and/or SSPManager confirmation handlers.
        Downstreams to SMPManager.set_delegate() and SSPManager.set_delegate()
        when those subsystems are present.
        """
        self._pairing_delegate = delegate
        smp = self._smp
        if smp is not None and hasattr(smp, "set_delegate"):
            smp.set_delegate(delegate)
        ssp = self._classic_ssp
        if ssp is not None and hasattr(ssp, "set_delegate"):
            ssp.set_delegate(delegate)
```

注：`SSPManager.set_delegate` 当前可能不存在；`hasattr` 守卫确保不破。本 Plan 不主动给 SSPManager 加 `set_delegate`——那是 Classic SSP 工作的范围。

### Step 9.5: Stack._build 装配 SMP

- [ ] **Modify `pybluehost/stack.py`**:

1) `Stack.__init__` 中（约 line 81 `self._sdp = None` 之后）追加：

```python
        self._smp: Any = None
```

2) `_build` 方法中，在创建 GATTServer 之后、创建 SDPServer 之前（约 line 167），追加：

```python
        # 5b. SMP — bind to each LE connection's CID_SMP fixed channel.
        from pybluehost.ble.smp import SMPManager
        smp = SMPManager(hci=hci, bond_storage=cfg.bond_storage)
        stack._smp = smp

        def _bind_smp_to_le_connection(handle: int, channels: dict) -> None:
            from pybluehost.l2cap.channel import SimpleChannelEvents
            from pybluehost.l2cap.constants import CID_SMP

            smp_channel = channels.get(CID_SMP)
            if smp_channel is None:
                return

            async def _send(data: bytes) -> None:
                await smp_channel.send(data)

            smp.bind_channel(handle, _send)

            async def _on_data(data: bytes) -> None:
                await smp.on_pdu(data, connection_handle=handle)

            smp_channel.set_events(SimpleChannelEvents(on_data=_on_data))

        l2cap.on_le_connection_open(_bind_smp_to_le_connection)
```

3) GAP 构造（约 line 183 `gap = GAP(...)`）追加 `smp=smp` 形参：

```python
        gap = GAP(
            ble_advertiser=BLEAdvertiser(hci=hci),
            ...
            ble_extended_advertiser=ExtendedAdvertiser(hci=hci),
            smp=smp,
        )
```

4) 在类底部 properties 区，追加：

```python
    @property
    def smp(self) -> Any:
        return self._smp
```

### Step 9.6: 跑测试确认绿

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/ble/test_smp_manager_assembly.py tests/unit/ble/ tests/unit/test_stack.py -v --transport=virtual
```

Expected: all passed。

如果 `tests/unit/ble/test_smp.py` 原有测试受 SMPManager 改动影响而失败：复核失败点，确认这些测试是否仍假设 SMPManager 是空壳；若是，按新接口更新。改动只能是替换断言对象（如 `mgr._senders`）或新增 `bind_channel` 调用，不应放松业务逻辑。

### Step 9.7: 提交

- [ ] **Commit:**

```bash
git add pybluehost/ble/smp.py pybluehost/stack.py pybluehost/gap.py tests/unit/ble/test_smp_manager_assembly.py
git commit -m "feat(stack): assemble SMPManager and bind CID_SMP channels

Closes the P0 SMP assembly gap in PRD §5.4. Stack._build now constructs
SMPManager(bond_storage=cfg.bond_storage), and uses the new
L2CAPManager.on_le_connection_open hook to bind each LE connection's
CID_SMP fixed channel to SMPManager.on_pdu(). GAP.set_pairing_delegate
now downstreams to SMPManager.

SMPManager.on_pdu() responds PAIRING_FAILED(UNSPECIFIED) until the full
pairing state machine ships in a follow-up Plan; this proves the L2CAP→
SMP binding is functional end-to-end."
```

---

## Task 10: 全量回归 + STATUS.md 更新

**Files:**
- Modify: `docs/superpowers/STATUS.md`

### Step 10.1: 全套测试

- [ ] **Run:**

```bash
uv run --frozen pytest tests/ -q --transport=virtual --cov=pybluehost --cov-fail-under=85
```

Expected: all passed（含本 Plan 新增的 ~16 个测试 + 既有 826）。Coverage ≥ 85%。

如果有新失败（非 4 个 pre-existing 中除 RFCOMM 之外的 3 个 USB diagnostics），定位并修复，不要 mask。

### Step 10.2: USB diagnostics 3 个 pre-existing 失败的处置

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/cli/tools/test_usb_diagnostics.py tests/unit/transport/test_usb.py::TestUSBTransportDiagnostics -v --transport=virtual --tb=short
```

预期：与 Plan 开始前一致的 3 个失败。

- [ ] **不在本 Plan 范围内修复 USB diagnostics 失败。**只确认它们仍然只有 3 个、且与本 Plan 的改动无关。若本 Plan 改动后失败数变多，必须排查并修复（差量回归）。

### Step 10.3: 更新 STATUS.md

- [ ] **Modify `docs/superpowers/STATUS.md`**:

1) 在 "快速定位" 段把当前进行中改为：

```markdown
**当前进行中**：PRD 1.0 收尾 — 全部完成
**下一步**：选择下一个 Plan（SMP 配对状态机 / HCI 容错初始化 / 断线重连 / transport/usb 拆包 / e2e 覆盖）
```

2) 在 Plan 总览表追加一行（新 Plan）：

```markdown
| PRD 1.0 收尾 | PcapngSink + Stack 工厂补全 + SMP 装配 + RFCOMM dispatch fix + bond_storage | ✅ 完成 | [2026-05-12-prd-v1-closure](plans/2026-05-12-prd-v1-closure.md) | `core/trace.py`, `stack.py`, `l2cap/manager.py`, `ble/smp.py`, `gap.py`, `classic/rfcomm.py` |
```

3) 在 "详细进度" 章节追加：

```markdown
### ✅ PRD 1.0 收尾
- 完成时间：2026-05-12
- Plan 文档：[2026-05-12-prd-v1-closure.md](plans/2026-05-12-prd-v1-closure.md)
- 关键变化：
  - `core/trace.py` 新增 `PcapngSink`（LinkType 201 BLUETOOTH_HCI_H4_WITH_PHDR）
  - `core/errors.py` 新增 `ReplayModeError`
  - `Stack` 新增 `from_tcp / from_btsnoop / build / loopback` 四个工厂方法
  - `StackMode.REPLAY` 现在被 `_check_writable()` 守卫真正强制
  - `StackConfig.bond_storage` 字段
  - `L2CAPManager.on_le_connection_open` 钩子
  - `SMPManager.bind_channel / on_pdu` 最小占位（PAIRING_FAILED 响应）+ Stack 装配
  - `gap.set_pairing_delegate` 真正下发到 SMPManager
  - `RFCOMMSession._on_frame` 修复 SABM→UIH 调度阻塞
- 验收：`uv run --frozen pytest tests/ -q --transport=virtual` 仅余 3 个 pre-existing USB diagnostics 失败
```

4) 修订 "问题日志" 一行（Plan 10 的 PcapngSink 声明回滚）：

```markdown
| 2026-05-12 | Plan 10 | Plan 10 STATUS 误标 PcapngSink 已完成 | 本 Plan（2026-05-12 PRD 收尾）实装 | ✅ 已解决 |
```

### Step 10.4: 提交

- [ ] **Commit:**

```bash
git add docs/superpowers/STATUS.md
git commit -m "docs(progress): PRD 1.0 收尾 Plan completed"
```

---

## 验收清单（Plan 完成定义）

完成本 Plan 后，对照 PRD 1.0 §9 验收指标：

- [x] PRD §5.7 pcapng sink —— `PcapngSink` 已实装，Wireshark 可直接打开输出文件
- [x] PRD §5.7 `Stack.from_tcp / from_btsnoop / build / loopback` —— 4 个工厂全部到位
- [x] PRD §3 P1 "btsnoop 文件回放复现场景" —— `from_btsnoop` + REPLAY 守卫已就位
- [x] PRD §5.4 "Bond 持久化（本地存储，可插拔后端）" —— `StackConfig.bond_storage` 可注入，传到 SMPManager
- [x] BLE SMP CID 0x0006 通道 → SMPManager 的物理路径打通；`gap.set_pairing_delegate` 真正下发
- [x] `test_rfcomm_inbound_handler_does_not_block_future_frames` 转绿
- [ ] **后续 Plan**：完整 SMP 配对状态机（Legacy / Secure Connections / Passkey / Numeric Comparison / OOB）
- [ ] **后续 Plan**：HCI 容错初始化（按 `Read_Local_Supported_Commands` bitmap 跳过命令）
- [ ] **后续 Plan**：断线自动重连闭环
- [ ] **后续 Plan**：`transport/usb.py` 拆包重构
- [ ] **后续 Plan**：`tests/e2e/` 端到端覆盖（loopback GATT、loopback RFCOMM）

---

## 常见问题 / Troubleshooting

### Q: Task 1 的 pcapng 文件用 Wireshark 打开看不到方向
- **现象**：`text2pcap` / Wireshark 把 H4 byte 0x01/0x04 解析对了，但 "Sent/Received" 列全是 Sent
- **原因**：LinkType 201 (BLUETOOTH_HCI_H4_WITH_PHDR) 要求方向字段是 4-byte **big-endian** 整型（`0` = sent, `1` = received），不是 little-endian
- **解决方案**：检查 `phdr = _struct.pack(">I", direction_flag)`——must be `>I`

### Q: Task 5 守卫挡住了 close()
- **现象**：REPLAY 模式 stack 的 `await stack.close()` 抛 `ReplayModeError`
- **原因**：误把 `_check_writable()` 加到了 `close()` 或 `power_off()`
- **解决方案**：`_check_writable()` 只能加在 `connect_gatt / connect_classic / authenticate_classic / enable_classic_encryption` 四处。`close` / `power_off` / `power_on` 一定要让 REPLAY 模式也能调用——它们是生命周期，不是写操作

### Q: Task 6 修复后 RFCOMM E2E 测试变慢
- **现象**：每次 SABM 都多 1 次 event loop tick，inquiry 多设备时累计延迟
- **原因**：`asyncio.sleep(0)` 是 yield，不是 sleep，单次代价微秒级
- **解决方案**：如果实测真有感知延迟，把 yield 改成在 handler task 中 `await asyncio.sleep(0)`（让出权给 dispatch）；当前实现已经是开销最小的形式

### Q: Task 9 stack.gap 没有 smp 形参
- **现象**：`TypeError: GAP.__init__() got an unexpected keyword argument 'smp'`
- **原因**：Task 9 步骤 9.4 未执行
- **解决方案**：补 `GAP.__init__` 的 `smp` 形参；用 `=None` 默认值确保现有调用方不破

Self-review 结果：本 Plan 覆盖了 review-notes-2026-05-12.md "立即可做" 5 项 + 真实 RFCOMM bug，无 TBD/TODO 占位符，所有签名一致（`SMPManager.bind_channel` / `SMPManager.on_pdu` / `L2CAPManager.on_le_connection_open` 在多个 Task 中引用形式一致），文件路径全部为绝对路径。已知留待后续 Plan 的 5 项已在"范围声明"和"验收清单"中显式列出。
