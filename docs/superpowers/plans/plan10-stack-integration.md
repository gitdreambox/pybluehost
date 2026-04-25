# Plan 9: Stack Factory + Integration Tests

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement `pybluehost/stack.py` �?the `Stack` factory that assembles all layers, manages lifecycle, and exposes the top-level API. Add Loopback integration tests that exercise the full stack with `VirtualController`.

**Architecture reference:** `docs/architecture/13-stack-api.md`

**Dependencies:** All previous layers (core, transport, hci, l2cap, ble, classic, gap, profiles)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/stack.py` | `Stack` class + `StackConfig` + assembly logic |
| `pybluehost/__init__.py` | Top-level exports: `Stack`, `StackConfig` |
| `tests/e2e/__init__.py` | |
| `tests/e2e/test_loopback.py` | Full-stack Loopback tests using VirtualController |
| `tests/e2e/test_stack_lifecycle.py` | Stack open/close/power_on/power_off |

---

## Task 1: StackConfig

**Files:** `pybluehost/stack.py` (StackConfig only), tests

- [x] **Step 1: Write failing StackConfig tests**

```python
# tests/unit/test_stack_config.py
from pybluehost.stack import StackConfig, StackMode
from pybluehost.core.types import IOCapability

def test_default_config():
    config = StackConfig()
    assert config.device_name == "PyBlueHost"
    assert config.command_timeout == 5.0
    assert config.le_io_capability == IOCapability.NO_INPUT_NO_OUTPUT

def test_custom_config():
    config = StackConfig(device_name="MyDevice", command_timeout=10.0)
    assert config.device_name == "MyDevice"
    assert config.command_timeout == 10.0

def test_stack_mode_enum():
    assert StackMode.LIVE == "live"
    assert StackMode.LOOPBACK == "loopback"
    assert StackMode.REPLAY == "replay"
```

- [x] **Step 2: Run tests �?verify they fail**

- [x] **Step 3: Implement `StackConfig` + `StackMode`**

```python
from dataclasses import dataclass, field
from enum import Enum

class StackMode(str, Enum):
    LIVE     = "live"
    LOOPBACK = "loopback"
    REPLAY   = "replay"

@dataclass
class StackConfig:
    # Transport
    firmware_policy: "FirmwarePolicy" = None   # FirmwarePolicy.AUTO_DOWNLOAD
    reconnect_policy: "ReconnectPolicy" = None  # ReconnectPolicy.NONE

    # Security
    security: SecurityConfig = field(default_factory=SecurityConfig)
    pairing_delegate: Any = None   # AutoAcceptDelegate()
    bond_storage: Any = None       # JsonBondStorage(default_path)

    # GAP
    device_name: str = "PyBlueHost"
    appearance: int = 0x0000
    le_io_capability: IOCapability = IOCapability.NO_INPUT_NO_OUTPUT
    classic_io_capability: IOCapability = IOCapability.DISPLAY_YES_NO

    # Trace
    trace_sinks: list = field(default_factory=list)

    # HCI
    command_timeout: float = 5.0
```

Also add this test to `tests/unit/test_stack_config.py`:

```python
def test_stack_config_security_field():
    from pybluehost.ble.smp import SecurityConfig
    config = StackConfig()
    assert isinstance(config.security, SecurityConfig)
```

- [x] **Step 4: Run tests — verify they pass**�?from pybluehost.ble.security
- [x] **Step 4: Run tests — verify they pass** �?verify they pass**

- [x] **Step 5: Commit**
```bash
git add pybluehost/stack.py tests/unit/test_stack_config.py
git commit -m "feat(stack): add StackConfig and StackMode"
```

---

## Task 2: Stack Assembly + Lifecycle

**Files:** `pybluehost/stack.py` (Stack class), tests

- [x] **Step 1: Write failing Stack lifecycle tests**

```python
# tests/unit/test_stack_lifecycle.py
import asyncio, pytest
from pybluehost.stack import Stack, StackConfig, StackMode
from pybluehost.hci.virtual import VirtualController
from pybluehost.transport.loopback import LoopbackTransport
from pybluehost.core.address import BDAddress

@pytest.fixture
def vc():
    return VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:01"))

@pytest.mark.asyncio
async def test_stack_build_from_loopback(vc):
    transport = LoopbackTransport(virtual_controller=vc)
    stack = await Stack._build(transport=transport, config=StackConfig(), mode=StackMode.LOOPBACK)
    assert stack.is_powered
    await stack.close()

@pytest.mark.asyncio
async def test_stack_power_off_on(vc):
    transport = LoopbackTransport(virtual_controller=vc)
    stack = await Stack._build(transport=transport, config=StackConfig(), mode=StackMode.LOOPBACK)
    await stack.power_off()
    assert not stack.is_powered
    await stack.power_on()
    assert stack.is_powered
    await stack.close()

@pytest.mark.asyncio
async def test_stack_context_manager(vc):
    transport = LoopbackTransport(virtual_controller=vc)
    async with await Stack._build(transport, StackConfig(), StackMode.LOOPBACK) as stack:
        assert stack.is_powered
    # After context exit, stack should be closed

@pytest.mark.asyncio
async def test_stack_exposes_layers(vc):
    transport = LoopbackTransport(virtual_controller=vc)
    stack = await Stack._build(transport=transport, config=StackConfig(), mode=StackMode.LOOPBACK)
    assert stack.hci is not None
    assert stack.l2cap is not None
    assert stack.gap is not None
    assert stack.gatt_server is not None
    assert stack.trace is not None
    await stack.close()
```

- [x] **Step 2: Run tests �?verify they fail**

- [x] **Step 3: Implement `Stack._build()` and public factory methods**

Assembly order (per architecture doc 13.5):
1. `TraceSystem(config.trace_sinks)`
2. `HCIController(transport, trace)`
3. HCI init sequence (Reset �?Read_Local_Version �?... �?Write_SSP_Mode)
4. `L2CAPManager(hci, trace)`
5. BLE layers: `ATTBearer`, `GATTServer`, `GATTClient`, `SMPManager`
6. Classic layers: `SDPServer`, `RFCOMMManager`
7. `GAP(ble_advertiser, ble_scanner, ble_connections, ..., classic_discovery, ...)`
8. Security setup

```python
class Stack:
    @classmethod
    async def _build(cls, transport: Transport, config: StackConfig,
                      mode: StackMode = StackMode.LIVE) -> "Stack": ...

    @classmethod
    async def loopback(cls, config_a=StackConfig(), config_b=StackConfig()) -> tuple["Stack", "Stack"]:
        """Create two interconnected stacks via VirtualController."""
        from pybluehost.hci.virtual import VirtualController
        from pybluehost.transport.loopback import LoopbackTransport
        from pybluehost.core.address import BDAddress
        vc_a = VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:01"))
        vc_b = VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:02"))
        vc_a.connect_to(vc_b)
        t_a = LoopbackTransport(vc_a)
        t_b = LoopbackTransport(vc_b)
        stack_a = await cls._build(t_a, config_a, StackMode.LOOPBACK)
        stack_b = await cls._build(t_b, config_b, StackMode.LOOPBACK)
        return stack_a, stack_b

    @classmethod
    async def from_uart(cls, port: str, baudrate: int = 115200,
                         config: StackConfig = None) -> "Stack":
        """Connect via UART/H4 (pyserial-asyncio). Requires Plan 2 UARTTransport."""
        from pybluehost.transport.uart import UARTTransport
        t = UARTTransport(port=port, baudrate=baudrate)
        return await cls._build(t, config or StackConfig(), StackMode.LIVE)

    @classmethod
    async def from_tcp(cls, host: str, port: int,
                        config: StackConfig = None) -> "Stack":
        """Connect via TCP (e.g. QEMU or nRF52 modem). Requires Plan 2 TCPTransport."""
        from pybluehost.transport.tcp import TCPTransport
        t = TCPTransport(host=host, port=port)
        return await cls._build(t, config or StackConfig(), StackMode.LIVE)

    @classmethod
    async def from_usb(cls, vid: int | None = None, pid: int | None = None,
                        config: StackConfig = None) -> "Stack":
        """Auto-detect USB Bluetooth adapter and load firmware if needed.
        Requires Plan 2.5 USBTransport (pybluehost.transport.usb).
        Raises ImportError if usb extra not installed (pip install pybluehost[usb])."""
        from pybluehost.transport.usb import USBTransport
        t = await USBTransport.auto_detect(vid=vid, pid=pid,
                                            firmware_policy=(config or StackConfig()).firmware_policy)
        return await cls._build(t, config or StackConfig(), StackMode.LIVE)

    @classmethod
    async def from_btsnoop(cls, path: str) -> "Stack":
        """Open a btsnoop/HCI log file for offline replay/analysis."""
        from pybluehost.transport.btsnoop import BtsnoopTransport
        t = BtsnoopTransport(path=path)
        return await cls._build(t, StackConfig(), StackMode.REPLAY)

    @classmethod
    async def replay(cls, path: str) -> "Stack":
        """Alias for from_btsnoop() �?open a btsnoop file for offline analysis.

        Usage:
            async with await Stack.replay("capture.btsnoop") as stack:
                events = await stack.trace.collect(duration=0)  # all events
        """
        return await cls.from_btsnoop(path)

    async def power_on(self) -> None: ...
    async def power_off(self) -> None: ...
    async def close(self) -> None: ...
    async def __aenter__(self) -> "Stack": return self
    async def __aexit__(self, *exc) -> None: await self.close()

    @property
    def hci(self) -> HCIController: ...
    @property
    def l2cap(self) -> L2CAPManager: ...
    @property
    def gap(self) -> GAP: ...
    @property
    def gatt_server(self) -> GATTServer: ...
    def gatt_client_for(self, conn_handle: int) -> GATTClient: ...
    @property
    def sdp(self) -> SDPServer: ...
    @property
    def rfcomm(self) -> RFCOMMManager: ...
    @property
    def trace(self) -> TraceSystem: ...
    @property
    def local_address(self) -> BDAddress: ...
    @property
    def is_powered(self) -> bool: ...
    @property
    def mode(self) -> StackMode: ...
```

- [x] **Step 4: Run tests — verify they pass** �?verify they pass**

- [x] **Step 5: Commit**
```bash
git add pybluehost/stack.py tests/unit/test_stack_lifecycle.py
git commit -m "feat(stack): add Stack factory and lifecycle management"
```

---

## Task 3: Integration Tests �?Loopback Full Stack

**Files:** `tests/e2e/test_loopback.py`

- [x] **Step 1: Write integration tests**

```python
# tests/e2e/test_loopback.py
import asyncio, pytest
from pybluehost.stack import Stack
from pybluehost.core.gap_common import AdvertisingData
from pybluehost.ble.gap import AdvertisingConfig
from pybluehost.profiles.ble.hrs import HeartRateServer

@pytest.mark.asyncio
async def test_loopback_stack_pair_creates_two_stacks():
    stack_a, stack_b = await Stack.loopback()
    assert stack_a.is_powered
    assert stack_b.is_powered
    assert stack_a.local_address != stack_b.local_address
    await stack_a.close()
    await stack_b.close()

@pytest.mark.asyncio
async def test_loopback_advertise_and_scan():
    stack_a, stack_b = await Stack.loopback()

    # stack_a advertises
    ad = AdvertisingData()
    ad.set_flags(0x06)
    ad.set_complete_local_name("LoopbackTest")
    await stack_a.gap.ble_advertiser.start(AdvertisingConfig(), ad)

    # stack_b scans and finds stack_a
    results = await stack_b.gap.ble_scanner.scan_for(duration=1.0)
    names = [r.advertising_data.get_complete_local_name() for r in results]
    assert "LoopbackTest" in names

    await stack_a.close()
    await stack_b.close()

@pytest.mark.asyncio
async def test_loopback_gatt_read():
    stack_a, stack_b = await Stack.loopback()

    # stack_b is a GATT Server (HRS)
    hrs = HeartRateServer(sensor_location=0x01)
    await hrs.register(stack_b.gatt_server)

    ad = AdvertisingData()
    ad.set_flags(0x06)
    await stack_b.gap.ble_advertiser.start(AdvertisingConfig(), ad)

    # stack_a connects and reads Body Sensor Location
    results = await stack_a.gap.ble_scanner.scan_for(1.0)
    assert len(results) > 0
    conn = await stack_a.gap.ble_connections.connect(results[0].address)

    gatt_client = stack_a.gatt_client_for(conn.handle)
    services = await gatt_client.discover_all_services()
    hr_service = next(s for s in services if str(s.uuid) == "0x180D")
    chars = await gatt_client.discover_characteristics(hr_service)
    body_loc = next(c for c in chars if str(c.uuid) == "0x2A38")
    value = await gatt_client.read_characteristic(body_loc)
    assert value == bytes([0x01])  # Chest

    await stack_a.close()
    await stack_b.close()
```

- [x] **Step 2: Run integration tests**
```bash
uv run pytest tests/e2e/ -v --tb=short
```

- [x] **Step 3: Run full test suite �?no regressions**
```bash
uv run pytest tests/ -v --tb=short --cov=pybluehost --cov-report=term-missing
```

- [x] **Step 4: Update `pybluehost/__init__.py`**

```python
from pybluehost.stack import Stack, StackConfig, StackMode

__all__ = ["Stack", "StackConfig", "StackMode"]
```

- [x] **Step 5: Commit**
```bash
git add tests/e2e/ pybluehost/__init__.py
git commit -m "test(integration): add Loopback full-stack integration tests"
```

---

## Task 4: Final Polish + STATUS Update

- [x] **Step 1: Ensure all tests pass**
```bash
uv run pytest tests/ -v
```

- [x] **Step 2: Check test coverage**
```bash
uv run pytest tests/ --cov=pybluehost --cov-report=html
```

- [x] **Step 3: Update STATUS.md �?all plans complete**

Edit `docs/superpowers/STATUS.md`: all plans �?

```bash
git add docs/superpowers/STATUS.md
git commit -m "docs: mark Plan 9 (Stack integration) complete �?all plans done"
```

- [x] **Step 4: Merge worktree to master**
```bash
# From main repo (not worktree)
git checkout master
git merge claude/eloquent-raman --ff-only
```

---

## 审查补充事项 (2026-04-18 审查后追加)

### 补充 1: 合并 Plan 10a (PcapngSink + 回放模式) 进本 Plan

原计划单独的 Plan 10a 现合并进本 Plan，因为文件集高度重叠（core/trace.py + stack.py）。

**新增内容**：

1. **PcapngSink** — 在 `core/trace.py` 中追加：
```python
class PcapngSink(TraceSink):
    """输出 pcapng 格式，可用 Wireshark 直接打开。"""
    def __init__(self, path: str) -> None: ...
    async def on_trace(self, event: TraceEvent) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...
```

2. **Stack.from_btsnoop()** — 回放模式工厂方法：
```python
class StackMode(Enum):
    LIVE = "live"
    REPLAY = "replay"

class ReplayModeError(PyBlueHostError):
    """Raised when attempting write operations in replay mode."""

@classmethod
async def from_btsnoop(cls, path: str) -> "Stack":
    """Create a Stack in replay mode from a btsnoop capture file."""
    ...
```

3. **Stack.replay()** — 回放控制：
```python
async def replay(self, speed: float = 1.0) -> None:
    """Replay the btsnoop file. speed=1.0 is realtime, speed=0 is as-fast-as-possible."""
    ...
```

### 补充 2: Stack.build() 公开工厂方法（PRD §5.7, 架构 13-stack-api.md §13.3）

```python
@classmethod
async def build(
    cls,
    transport: Transport,
    *,
    trace_sinks: list[TraceSink] | None = None,
    config: StackConfig | None = None,
) -> "Stack":
    """Custom assembly — for advanced use cases."""
    ...
```

### 补充 3: 断线重连后 HCI 重初始化（架构 13-stack-api.md §13.4）

Transport 重连后需要：
1. 自动重跑 HCI 16 步初始化序列
2. 通过 disconnect 回调通知上层所有连接已失效
3. 清空 ConnectionManager 状态

需要补充测试：模拟 Transport 断线 → 重连 → 验证 HCI 重初始化 → 验证上层收到 disconnect 通知。

### 补充 4: Stack.sig_db 属性（架构 13-stack-api.md §13.3）

```python
@property
def sig_db(self) -> SIGDatabase:
    return self._sig_db
```

### 补充 5: LoopbackTransport 接口修正

Plan 中使用 `LoopbackTransport(virtual_controller=vc)` 但实际 LoopbackTransport 无此构造器。应改为：

```python
# 创建 Loopback 对
host_transport, controller_transport = LoopbackTransport.pair()
# VirtualController 连接到 controller 端
vc = VirtualController()
controller_transport.set_sink(vc)
vc.set_transport(controller_transport)
# Stack 使用 host 端
stack = await Stack._build(host_transport, ...)
```

### 补充 6: Stack.power_off() vs close() 语义（架构 13-stack-api.md §13.4）

- `power_off()`: 关闭连接和广播，保留 Transport（可再次 power_on）
- `close()`: 释放全部资源（Transport.close() + 清理所有状态）

需要分别测试两种行为。
