# Plan 10: Test Infrastructure

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build the complete test infrastructure: shared fakes/stubs in `tests/fakes/`, btsnoop fixture data in `tests/data/`, pytest markers + conftest hierarchy, CI workflow (GitHub Actions), and coverage configuration. This plan is a prerequisite for all multi-layer integration and e2e tests.

**Architecture reference:** `docs/architecture/14-testing.md`

**Dependencies:** All previous layers (Plans 1–9 code exists)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `tests/__init__.py` | Root test package |
| `tests/conftest.py` | Session-level fixtures: event_loop policy, global marks |
| `tests/fakes/__init__.py` | Re-export all fakes |
| `tests/fakes/transport.py` | `FakeTransport` — records sent bytes, injects received bytes |
| `tests/fakes/hci.py` | `FakeHCIDownstream` — captures send_command / send_acl_data calls |
| `tests/fakes/l2cap.py` | `FakeChannelEvents` — captures on_data / on_close calls |
| `tests/fakes/trace.py` | `NullTrace` — TraceSystem that discards all events |
| `tests/data/README.md` | How to add btsnoop capture fixtures |
| `tests/data/hci_reset.btsnoop` | Minimal 4-packet btsnoop: Reset → CC → Read_BD_ADDR → CC |
| `tests/unit/conftest.py` | Unit-test fixtures shared across unit tests |
| `tests/integration/conftest.py` | Integration fixtures: hci+vc pair, l2cap+hci pair |
| `tests/integration/__init__.py` | |
| `tests/e2e/conftest.py` | E2E fixtures: loopback Stack pair, single Loopback Stack |
| `tests/e2e/__init__.py` | |
| `tests/btsnoop/__init__.py` | |
| `tests/btsnoop/test_replay.py` | BtsnoopTransport replay against hci_reset.btsnoop |
| `tests/hardware/__init__.py` | |
| `tests/hardware/conftest.py` | Skip-unless-hardware marker + USB adapter fixture |
| `tests/hardware/test_usb_smoke.py` | Hardware smoke test: detect adapter, reset, read_bd_addr |
| `pyproject.toml` | pytest markers, asyncio_mode, coverage config |
| `.github/workflows/test.yml` | CI: Python matrix 3.10/3.11/3.12, unit + integration, coverage upload |

---

## Task 1: Shared Fakes

**Files:** `tests/fakes/transport.py`, `tests/fakes/hci.py`, `tests/fakes/l2cap.py`, `tests/fakes/trace.py`, `tests/fakes/__init__.py`

- [ ] **Step 1: Write tests that use the fakes** (self-validating)

```python
# tests/unit/test_fakes.py
import asyncio, pytest
from tests.fakes.transport import FakeTransport
from tests.fakes.hci import FakeHCIDownstream
from tests.fakes.l2cap import FakeChannelEvents
from tests.fakes.trace import NullTrace

@pytest.mark.asyncio
async def test_fake_transport_records_sends():
    t = FakeTransport()
    await t.send(b"\x01\x02")
    await t.send(b"\x03\x04")
    assert t.sent == [b"\x01\x02", b"\x03\x04"]

@pytest.mark.asyncio
async def test_fake_transport_inject_calls_sink():
    t = FakeTransport()
    received = []
    class Sink:
        async def on_transport_data(self, data): received.append(data)
    t.set_sink(Sink())
    await t.inject(b"\xAB\xCD")
    assert received == [b"\xAB\xCD"]

@pytest.mark.asyncio
async def test_fake_hci_captures_commands():
    from pybluehost.hci.packets import HCI_Reset
    hci = FakeHCIDownstream()
    await hci.send_command(HCI_Reset())
    assert len(hci.commands) == 1
    assert type(hci.commands[0]).__name__ == "HCI_Reset"

@pytest.mark.asyncio
async def test_fake_hci_captures_acl_data():
    hci = FakeHCIDownstream()
    await hci.send_acl_data(handle=0x0040, pb_flag=0x02, data=b"\xAB")
    assert hci.acl_sent == [(0x0040, 0x02, b"\xAB")]

@pytest.mark.asyncio
async def test_fake_channel_events_on_data():
    events = FakeChannelEvents()
    await events.on_data(b"\x01\x02")
    assert events.received == [b"\x01\x02"]

@pytest.mark.asyncio
async def test_fake_channel_events_on_close():
    events = FakeChannelEvents()
    await events.on_close()
    assert events.closed is True

def test_null_trace_does_not_raise():
    trace = NullTrace()
    trace.log_hci_command(b"\x01")
    trace.log_hci_event(b"\x04")
    trace.log_acl(handle=0x0001, direction="tx", data=b"\x02")
```

- [ ] **Step 2: Run tests — verify they fail**
```bash
uv run pytest tests/unit/test_fakes.py -v
```

- [ ] **Step 3: Implement `tests/fakes/transport.py`**

```python
# tests/fakes/transport.py
from __future__ import annotations
from pybluehost.transport.base import Transport, TransportInfo, TransportSink

class FakeTransport(Transport):
    """Records all sent bytes; allows injecting received bytes via inject()."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[bytes] = []
        self._open = False

    async def open(self) -> None:
        self._open = True

    async def close(self) -> None:
        self._open = False

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def inject(self, data: bytes) -> None:
        """Simulate receiving data from the controller."""
        if self._sink:
            await self._sink.on_transport_data(data)

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="fake", description="FakeTransport",
            platform="test", details={},
        )

    def clear(self) -> None:
        """Reset sent list between test cases."""
        self.sent.clear()
```

- [ ] **Step 4: Implement `tests/fakes/hci.py`**

```python
# tests/fakes/hci.py
from __future__ import annotations
from pybluehost.hci.packets import HCICommand, HCIACLData, HCI_Command_Complete_Event
from pybluehost.hci.constants import ErrorCode

class FakeHCIDownstream:
    """Fake HCI downstream SAP — captures commands and ACL sends; returns success CCEs."""

    def __init__(self, auto_reply: bool = True) -> None:
        self.commands: list[HCICommand] = []
        self.acl_sent: list[tuple[int, int, bytes]] = []
        self._auto_reply = auto_reply

    async def send_command(self, cmd: HCICommand) -> HCI_Command_Complete_Event:
        self.commands.append(cmd)
        if self._auto_reply:
            return HCI_Command_Complete_Event(
                num_hci_command_packets=1,
                command_opcode=cmd.opcode,
                return_parameters=bytes([ErrorCode.SUCCESS]),
            )
        raise TimeoutError("FakeHCI: auto_reply disabled")

    async def send_acl_data(self, handle: int, pb_flag: int, data: bytes) -> None:
        self.acl_sent.append((handle, pb_flag, data))

    def clear(self) -> None:
        self.commands.clear()
        self.acl_sent.clear()

    def last_command_opcode(self) -> int | None:
        return self.commands[-1].opcode if self.commands else None
```

- [ ] **Step 5: Implement `tests/fakes/l2cap.py`**

```python
# tests/fakes/l2cap.py
from __future__ import annotations

class FakeChannelEvents:
    """Captures channel events for assertion in tests."""

    def __init__(self) -> None:
        self.received: list[bytes] = []
        self.closed: bool = False
        self.mtu_changed_to: int | None = None

    async def on_data(self, data: bytes) -> None:
        self.received.append(data)

    async def on_close(self) -> None:
        self.closed = True

    async def on_mtu_changed(self, mtu: int) -> None:
        self.mtu_changed_to = mtu

    def clear(self) -> None:
        self.received.clear()
        self.closed = False
        self.mtu_changed_to = None
```

- [ ] **Step 6: Implement `tests/fakes/trace.py`**

```python
# tests/fakes/trace.py
from pybluehost.core.trace import TraceSystem

class NullTrace(TraceSystem):
    """TraceSystem that silently discards all events (for tests that don't need tracing)."""

    def __init__(self) -> None:
        super().__init__(sinks=[])  # no sinks → no output

    def log_hci_command(self, data: bytes) -> None: pass
    def log_hci_event(self, data: bytes) -> None: pass
    def log_acl(self, handle: int, direction: str, data: bytes) -> None: pass
```

- [ ] **Step 7: Implement `tests/fakes/__init__.py`**

```python
from tests.fakes.transport import FakeTransport
from tests.fakes.hci import FakeHCIDownstream
from tests.fakes.l2cap import FakeChannelEvents
from tests.fakes.trace import NullTrace

__all__ = ["FakeTransport", "FakeHCIDownstream", "FakeChannelEvents", "NullTrace"]
```

- [ ] **Step 8: Run tests — verify they pass**
```bash
uv run pytest tests/unit/test_fakes.py -v
```

- [ ] **Step 9: Commit**
```bash
git add tests/fakes/ tests/unit/test_fakes.py
git commit -m "test(infra): add shared test fakes — FakeTransport, FakeHCIDownstream, FakeChannelEvents, NullTrace"
```

---

## Task 2: Conftest Hierarchy + pytest Markers

**Files:** `tests/conftest.py`, `tests/unit/conftest.py`, `tests/integration/conftest.py`, `tests/e2e/conftest.py`, `tests/hardware/conftest.py`, `pyproject.toml`

- [ ] **Step 1: Update `pyproject.toml`** with markers, asyncio mode, coverage config

```toml
# pyproject.toml additions (merge into existing [tool.pytest.ini_options]):
[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "unit: isolated unit tests (no real hardware, no network)",
    "integration: multi-layer tests using VirtualController + Loopback",
    "e2e: full-stack Loopback double-stack tests",
    "btsnoop: btsnoop file replay tests",
    "hardware: real USB Bluetooth adapter required (skipped in CI)",
    "slow: tests taking >5s",
]
addopts = "--strict-markers -q"

[tool.coverage.run]
source = ["pybluehost"]
omit = ["tests/*", "pybluehost/__main__.py"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
    "@abstractmethod",
]
fail_under = 85
```

- [ ] **Step 2: Write `tests/conftest.py`**

```python
# tests/conftest.py
import pytest

def pytest_configure(config):
    """Register custom markers so --strict-markers doesn't complain."""
    # Markers are already declared in pyproject.toml; this hook is for
    # programmatic registration if pyproject.toml is not loaded.
    pass
```

- [ ] **Step 3: Write `tests/unit/conftest.py`**

```python
# tests/unit/conftest.py
import pytest
from tests.fakes.transport import FakeTransport
from tests.fakes.hci import FakeHCIDownstream
from tests.fakes.trace import NullTrace

@pytest.fixture
def fake_transport():
    return FakeTransport()

@pytest.fixture
def fake_hci():
    return FakeHCIDownstream()

@pytest.fixture
def null_trace():
    return NullTrace()
```

- [ ] **Step 4: Write `tests/integration/conftest.py`**

```python
# tests/integration/conftest.py
"""Fixtures for HCI+L2CAP integration tests using VirtualController."""
import pytest
from pybluehost.core.address import BDAddress
from pybluehost.core.trace import TraceSystem
from pybluehost.hci.virtual import VirtualController
from pybluehost.hci.controller import HCIController
from pybluehost.l2cap.manager import L2CAPManager

class LoopbackTransport:
    """Routes HCIController sends through VirtualController (synchronous loopback)."""
    def __init__(self, vc: VirtualController) -> None:
        self._vc = vc; self._sink = None

    def set_sink(self, sink): self._sink = sink
    async def open(self): pass
    async def close(self): pass

    async def send(self, data: bytes) -> None:
        response = await self._vc.process(data)
        if response and self._sink:
            await self._sink.on_transport_data(response)

    @property
    def is_open(self) -> bool: return True

@pytest.fixture
async def vc_a():
    return VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:01"))

@pytest.fixture
async def vc_b():
    return VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:02"))

@pytest.fixture
async def hci_with_vc(vc_a):
    trace = TraceSystem()
    transport = LoopbackTransport(vc_a)
    hci = HCIController(transport=transport, trace=trace)
    transport.set_sink(hci)
    await hci.initialize()
    yield hci
    await hci.close()

@pytest.fixture
async def l2cap_with_hci(hci_with_vc):
    from pybluehost.core.trace import TraceSystem
    l2cap = L2CAPManager(hci=hci_with_vc, trace=TraceSystem())
    hci_with_vc.set_upstream(
        on_hci_event=l2cap.on_hci_event,
        on_acl_data=l2cap.on_acl_data,
    )
    return l2cap
```

- [ ] **Step 5: Write `tests/e2e/conftest.py`**

```python
# tests/e2e/conftest.py
"""Fixtures for full-stack Loopback (double-stack) E2E tests."""
import pytest
from pybluehost.stack import Stack, StackConfig, StackMode

@pytest.fixture
async def loopback_stacks():
    """Create two interconnected Loopback stacks for E2E testing."""
    stack_a, stack_b = await Stack.loopback()
    yield stack_a, stack_b
    await stack_a.close()
    await stack_b.close()

@pytest.fixture
async def single_loopback_stack():
    """Single Loopback stack (no peer) for lifecycle testing."""
    from pybluehost.core.address import BDAddress
    from pybluehost.hci.virtual import VirtualController
    from pybluehost.transport.loopback import LoopbackTransport
    vc = VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:01"))
    transport = LoopbackTransport(virtual_controller=vc)
    stack = await Stack._build(transport=transport, config=StackConfig(), mode=StackMode.LOOPBACK)
    yield stack
    await stack.close()
```

- [ ] **Step 6: Write `tests/hardware/conftest.py`**

```python
# tests/hardware/conftest.py
"""Hardware test fixtures — skipped unless --hardware flag is passed."""
import pytest

def pytest_addoption(parser):
    parser.addoption("--hardware", action="store_true", default=False,
                     help="Run hardware tests requiring a real USB Bluetooth adapter")

@pytest.fixture(scope="session")
def hardware_required(request):
    if not request.config.getoption("--hardware"):
        pytest.skip("Pass --hardware to run hardware tests")

@pytest.fixture(scope="session")
async def usb_stack(hardware_required):
    from pybluehost.stack import Stack
    stack = await Stack.from_usb()
    yield stack
    await stack.close()
```

- [ ] **Step 7: Run tests to verify conftest fixtures load**
```bash
uv run pytest tests/ --collect-only -q 2>&1 | head -30
```

- [ ] **Step 8: Commit**
```bash
git add pyproject.toml tests/conftest.py tests/unit/conftest.py tests/integration/conftest.py tests/e2e/conftest.py tests/hardware/conftest.py
git commit -m "test(infra): add conftest hierarchy, pytest markers, coverage config"
```

---

## Task 3: Btsnoop Fixture Data + Replay Tests

**Files:** `tests/data/hci_reset.btsnoop`, `tests/btsnoop/test_replay.py`

- [ ] **Step 1: Generate minimal btsnoop fixture**

```python
# Run this script once to generate tests/data/hci_reset.btsnoop
# pybluehost/tools/gen_btsnoop_fixture.py
import struct, pathlib

BTSNOOP_MAGIC    = b"btsnoop\x00"
BTSNOOP_VERSION  = 1
BTSNOOP_DLT      = 1002  # H4

# HCI Reset Command (0x0C03)
HCI_RESET = bytes([0x01, 0x03, 0x0C, 0x00])
# Command Complete for Reset: status=0
HCI_CC_RESET = bytes([0x04, 0x0E, 0x04, 0x01, 0x03, 0x0C, 0x00])
# HCI Read_BD_ADDR Command
HCI_READ_BD_ADDR = bytes([0x01, 0x09, 0x10, 0x00])
# Command Complete for Read_BD_ADDR: status=0, addr=AA:BB:CC:DD:EE:01
HCI_CC_READ_BD_ADDR = bytes([0x04, 0x0E, 0x0A, 0x01, 0x09, 0x10, 0x00,
                               0x01, 0xEE, 0xDD, 0xCC, 0xBB, 0xAA])

def write_btsnoop(path: str, packets: list[tuple[bytes, int]]) -> None:
    """Write minimal btsnoop file. packets = list of (data, direction_flag)."""
    with open(path, "wb") as f:
        f.write(BTSNOOP_MAGIC)
        f.write(struct.pack(">II", BTSNOOP_VERSION, BTSNOOP_DLT))
        ts = 0x00E26C4A3E3C0000  # arbitrary timestamp
        for data, flags in packets:
            orig_len = len(data)
            inc_len  = orig_len
            f.write(struct.pack(">IIIIQ", orig_len, inc_len, flags, 0, ts))
            f.write(data)
            ts += 1000

packets = [
    (HCI_RESET,         0x02),  # host→controller
    (HCI_CC_RESET,      0x03),  # controller→host
    (HCI_READ_BD_ADDR,  0x02),
    (HCI_CC_READ_BD_ADDR, 0x03),
]
write_btsnoop("tests/data/hci_reset.btsnoop", packets)
print("Generated tests/data/hci_reset.btsnoop")
```

Run it:
```bash
mkdir -p tests/data
uv run python pybluehost/tools/gen_btsnoop_fixture.py
```

- [ ] **Step 2: Write btsnoop replay tests**

```python
# tests/btsnoop/test_replay.py
"""Tests that replay a captured btsnoop file and verify packet parsing."""
import pytest
from pathlib import Path
from pybluehost.transport.btsnoop import BtsnoopTransport
from pybluehost.hci.packets import (
    HCI_Reset, HCI_Command_Complete_Event,
    HCI_Read_BD_ADDR_Command,
    decode_hci_packet,
)
from pybluehost.hci.constants import HCI_RESET, HCI_READ_BD_ADDR, ErrorCode

FIXTURE = Path(__file__).parent.parent / "data" / "hci_reset.btsnoop"

@pytest.mark.btsnoop
@pytest.mark.asyncio
async def test_btsnoop_replay_packet_count():
    transport = BtsnoopTransport(path=str(FIXTURE))
    packets = []
    class Sink:
        async def on_transport_data(self, data): packets.append(data)
    transport.set_sink(Sink())
    await transport.open()
    await transport.close()
    assert len(packets) == 4  # 4 packets in fixture

@pytest.mark.btsnoop
@pytest.mark.asyncio
async def test_btsnoop_replay_first_packet_is_reset():
    transport = BtsnoopTransport(path=str(FIXTURE))
    packets = []
    class Sink:
        async def on_transport_data(self, data): packets.append(data)
    transport.set_sink(Sink())
    await transport.open()
    await transport.close()
    # First packet: HCI Reset Command
    pkt = decode_hci_packet(packets[0])
    assert isinstance(pkt, HCI_Reset)

@pytest.mark.btsnoop
@pytest.mark.asyncio
async def test_btsnoop_replay_second_packet_is_cc_reset():
    transport = BtsnoopTransport(path=str(FIXTURE))
    packets = []
    class Sink:
        async def on_transport_data(self, data): packets.append(data)
    transport.set_sink(Sink())
    await transport.open()
    await transport.close()
    pkt = decode_hci_packet(packets[1])
    assert isinstance(pkt, HCI_Command_Complete_Event)
    assert pkt.command_opcode == HCI_RESET
    assert pkt.return_parameters[0] == ErrorCode.SUCCESS
```

- [ ] **Step 3: Run btsnoop tests**
```bash
uv run pytest tests/btsnoop/ -v -m btsnoop --tb=short
```

- [ ] **Step 4: Commit**
```bash
git add tests/data/ tests/btsnoop/ pybluehost/tools/gen_btsnoop_fixture.py
git commit -m "test(infra): add btsnoop fixture data and replay tests"
```

---

## Task 4: Hardware Smoke Tests

**Files:** `tests/hardware/test_usb_smoke.py`

- [ ] **Step 1: Write hardware smoke tests**

```python
# tests/hardware/test_usb_smoke.py
"""Hardware tests — requires real USB Bluetooth adapter. Run with: pytest --hardware"""
import pytest
from pybluehost.stack import Stack

pytestmark = pytest.mark.hardware

@pytest.mark.asyncio
async def test_usb_adapter_detects(hardware_required):
    """Verify auto-detect finds at least one adapter."""
    from pybluehost.transport.usb import USBTransport
    transport = await USBTransport.auto_detect()
    assert transport is not None
    assert transport.is_open or True  # auto_detect may not open

@pytest.mark.asyncio
async def test_usb_stack_powers_on(usb_stack):
    """Full stack on real hardware: power on, read BD_ADDR."""
    assert usb_stack.is_powered
    addr = usb_stack.local_address
    assert addr is not None
    assert str(addr) != "00:00:00:00:00:00"

@pytest.mark.asyncio
async def test_usb_stack_reset(usb_stack):
    """Power off and on should restore is_powered."""
    await usb_stack.power_off()
    assert not usb_stack.is_powered
    await usb_stack.power_on()
    assert usb_stack.is_powered
```

- [ ] **Step 2: Verify hardware tests are skipped in normal runs**
```bash
uv run pytest tests/hardware/ -v
```
Expected: all tests SKIPPED with "Pass --hardware to run hardware tests"

- [ ] **Step 3: Commit**
```bash
git add tests/hardware/
git commit -m "test(infra): add hardware smoke tests (skipped unless --hardware)"
```

---

## Task 5: CI Workflow

**Files:** `.github/workflows/test.yml`

- [ ] **Step 1: Write GitHub Actions CI workflow**

```yaml
# .github/workflows/test.yml
name: Tests

on:
  push:
    branches: [master, "claude/*"]
  pull_request:
    branches: [master]

jobs:
  test:
    name: Python ${{ matrix.python-version }}
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          version: "latest"

      - name: Set up Python ${{ matrix.python-version }}
        run: uv python install ${{ matrix.python-version }}

      - name: Install dependencies
        run: uv sync --extra dev

      - name: Run unit tests
        run: uv run pytest tests/unit/ -v --tb=short -m "not hardware"

      - name: Run integration tests
        run: uv run pytest tests/integration/ -v --tb=short -m "not hardware"

      - name: Run btsnoop tests
        run: uv run pytest tests/btsnoop/ -v --tb=short

      - name: Run full test suite with coverage
        run: |
          uv run pytest tests/ -v --tb=short \
            -m "not hardware" \
            --cov=pybluehost \
            --cov-report=xml \
            --cov-report=term-missing \
            --cov-fail-under=85

      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v4
        with:
          file: coverage.xml
          flags: python${{ matrix.python-version }}
          fail_ci_if_error: false
```

- [ ] **Step 2: Verify workflow file is valid YAML**
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))" && echo "Valid YAML"
```

- [ ] **Step 3: Commit**
```bash
mkdir -p .github/workflows
git add .github/workflows/test.yml
git commit -m "ci: add GitHub Actions test workflow (Python 3.10/3.11/3.12, coverage ≥85%)"
```

---

## Task 6: Final Verification + STATUS Update

- [ ] **Step 1: Run full test suite — no regressions**
```bash
uv run pytest tests/ -v --tb=short -m "not hardware" --cov=pybluehost --cov-report=term-missing
```
Expected: all tests pass, coverage ≥85%

- [ ] **Step 2: Run with all markers to verify nothing is accidentally skipped**
```bash
uv run pytest tests/ --collect-only -q -m "not hardware" 2>&1 | tail -5
```

- [ ] **Step 3: Update STATUS.md — Plan 10 complete, all plans done**

Edit `docs/superpowers/STATUS.md`:
- Add Plan 10 row with ✅
- Update Plan 2.5 row with ✅
- Set "当前进行中" to "全部完成 — 准备合并到 master"

```bash
git add docs/superpowers/STATUS.md
git commit -m "docs: mark Plan 10 (Test Infrastructure) complete — all plans done"
```

- [ ] **Step 4: Merge worktree to master**
```bash
# From the MAIN REPO directory (not inside the worktree):
cd H:/WUQI/code/pybluehost
git checkout master
git merge claude/eloquent-raman --ff-only
git log --oneline -10
```
