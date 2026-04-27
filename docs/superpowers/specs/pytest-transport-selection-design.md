# Pytest Transport 选择机制设计文档

| 项 | 值 |
|----|----|
| 状态 | 已批准 |
| 日期 | 2026-04-27 |
| 责任方 | 测试基础设施 |
| 替代 | （无） |

## 1. 目标

让所有依赖 transport controller 的测试在**真实蓝牙硬件可用时优先跑硬件**，否则回落到 `VirtualController`（软件仿真控制器）。允许用户通过 CLI flag 或环境变量显式指定 transport。消除当前 `tests/integration/`（永远虚拟）与 `tests/hardware/`（独立 `--hardware` 开关）的割裂。

**命名说明：** 用户面向的 transport 类型名为 `virtual`。原 `LoopbackTransport` 类（一个进程内双端 pipe）被**完全封装进 `VirtualController` 内部**作为私有实现细节 `_HCIPipe`，不再作为公开模块或类暴露。两个原因：
- "loopback" 在硬件语境里也可以指"两块物理适配器互联回环测试"，与"软件仿真"无关，作为公开名称容易误解。
- pipe 在本项目中**唯一**的用途就是 VC ↔ host 桥接，独立暴露增加了 mental overhead 而无收益。

双控制器测试场景的术语统一为 **"Virtual + Virtual peer"**：两个独立 `VirtualController` 实例（不共享 radio 模拟，与当前行为一致；peer 上的 GATT/SDP server 由测试代码本地配置）。

## 2. 背景

当前 pytest 基础设施分三套互不相通的体系：

- `tests/unit/` 用 `FakeTransport` / `FakeHCIDownstream` —— 纯隔离，没有 transport 对象。
- `tests/integration/` 与 `tests/e2e/` 通过 fixture（`vc_a`、`vc_b`、`hci_with_vc`、`l2cap_with_hci`、`single_loopback_stack`）硬绑定到 `VirtualController` + `LoopbackTransport`。
- `tests/hardware/` 由 `pytest --hardware` 单独门控；同一逻辑测试无法做到"虚拟或真实任选其一"。

`tests/unit/cli/test_app_*.py` 中有六个文件直接在测试体内调用 `Stack.loopback()`，完全绕开 fixture。

`tests/hardware/test_usb_smoke.py` 调用了不存在的 `Stack.from_usb()` —— 一个潜在 bug，一旦有人加 `--hardware` 就会暴露。

此外，`Stack.loopback()` / `StackMode.LOOPBACK` / `--transport=loopback` 这套命名表意不清，且 `LoopbackTransport` 作为公开类与"物理 loopback 测试"易混淆。本设计借机统一改名为 `virtual`，并把 pipe 内化为 `VirtualController` 私有实现（详见 §13 改名/重组清单）。

## 3. 范围

**范围内：** `tests/integration/`、`tests/e2e/`、`tests/hardware/`，以及 `tests/unit/cli/test_app_*.py` 中六个直接 `Stack.loopback()` 的文件。删除 `--hardware` flag；hardware 测试通过新的 `real_hardware_only` 标记并入统一体系。同时完成 `loopback` → `virtual` 全栈改名 + `LoopbackTransport` 内化为 `VirtualController` 私有实现。

**范围外：** `tests/unit/` 主体（用 fakes 的层隔离测试）、`tests/btsnoop/`（文件回放，无 transport）、`tests/unit/test_stack.py`（专测 `Stack.virtual()` 工厂本身，必须保持 transport 无关）。

## 4. 架构

### 4.1 Transport 选择流程（session 级，一次决定）

```
                ┌─────────────────────────────────────────────┐
                │        pytest 启动（session 级）            │
                └─────────────────────────────────────────────┘
                                    │
                                    ▼
                ┌─────────────────────────────────────────────┐
                │ 解析 transport spec（优先级 高→低）：       │
                │   1. --transport=...           (CLI flag)   │
                │   2. PYBLUEHOST_TEST_TRANSPORT (env var)    │
                │   3. 自动检测                  (默认)       │
                └─────────────────────────────────────────────┘
                                    │
            ┌───────────────────────┼────────────────────────┐
            ▼                       ▼                        ▼
        显式 virtual          显式 usb/uart              自动模式
            │                       │                        │
            │                       ▼                        ▼
            │             硬件可用？                   尝试 USB 自动检测
            │                  │     │                  ┌────┴─────┐
            │                Yes    No                找到       未找到
            │                  │     │                  │          │
            │                  │     └─►pytest.exit(4)  │          │
            ▼                  ▼                        ▼          ▼
        virtual            真硬件                    真硬件     virtual
                                                                 + fallback_count++
                                    │
                                    ▼
                ┌─────────────────────────────────────────────┐
                │ pytest_report_header 打印一行：             │
                │  [pybluehost-tests] transport: usb (Intel)  │
                │  [pybluehost-tests] transport: virtual      │
                │     (auto-detected — no hardware found)     │
                └─────────────────────────────────────────────┘
                                    │
                                    ▼
                            （所有测试运行）
                                    │
                                    ▼
                ┌─────────────────────────────────────────────┐
                │ pytest_terminal_summary（仅回落时显示）：   │
                │   ⚠ N tests ran on virtual (no hardware)    │
                └─────────────────────────────────────────────┘
```

Transport 选择是 **session 级一次性决定**。不支持单 session 内混用 transport（虚拟与真实控制器之间的状态污染不值得复杂度成本）。

### 4.2 组件总览

```
tests/
├── conftest.py                  ← pytest_addoption、pytest_report_header、
│                                  pytest_collection_modifyitems、
│                                  pytest_terminal_summary、fixtures
├── _transport_select.py         ← transport spec 解析、自动检测、
│                                  第二适配器查找
├── _fallback_tracker.py         ← session 级回落计数
├── unit/                        ← 不变（用 fakes）
├── integration/                 ← 改用 `stack` / `peer_stack`
├── e2e/                         ← 改用 `stack`
└── hardware/
    ├── test_intel_hw.py         ← 保留自有 raw-USB fixture，加
    │                              `real_hardware_only` 标记
    └── test_usb_smoke.py        ← 改用 `stack` fixture
```

## 5. Fixture API

### 5.1 Session 级 fixture

```python
@pytest.fixture(scope="session")
def selected_transport_spec(request) -> str:
    """Resolved transport spec: 'virtual', 'usb[:vendor=...,bus=N,address=M]', or 'uart:...'.

    Priority: --transport > $PYBLUEHOST_TEST_TRANSPORT > autodetect.
    Autodetect with no hardware -> 'virtual' (fallback_count incremented).
    Explicit but unavailable -> pytest.exit(returncode=4).
    """

@pytest.fixture(scope="session")
def selected_peer_spec(selected_transport_spec, request) -> str | None:
    """Resolved peer transport spec, or None when no peer is available.

    Priority: --transport-peer > $PYBLUEHOST_TEST_TRANSPORT_PEER > same-family autodetect.
    Constraint: peer family must match primary family (virtual/usb/uart).
    Violation -> pytest.exit(returncode=4).

    Same-family autodetect:
      primary=virtual  -> 'virtual' (a second independent VC instance)
      primary=usb      -> second USB adapter (different bus/address);
                          none found -> return None (dependent tests are skipped)
      primary=uart     -> no autodetect; explicit --transport-peer required;
                          otherwise return None.
    """

@pytest.fixture(scope="session")
def transport_mode(selected_transport_spec) -> str:
    """Coarse family: 'virtual' / 'usb' / 'uart'. Used by marker enforcement."""
```

### 5.2 测试级 fixture

```python
@pytest.fixture
async def stack(selected_transport_spec):
    """Full Stack on the selected transport. Built and torn down per test."""
    s = await _build_stack_from_spec(selected_transport_spec)
    yield s
    await s.close()

@pytest.fixture
async def peer_stack(selected_peer_spec):
    """Second Stack. Skips the test when no peer is available."""
    if selected_peer_spec is None:
        pytest.skip("peer_stack: no second adapter available; pass --transport-peer=...")
    s = await _build_stack_from_spec(selected_peer_spec)
    yield s
    await s.close()
```

### 5.3 Stack 工厂方法新增 + 改名 + VirtualController 自包含

`pybluehost/hci/virtual.py` 新增 `VirtualController.create()` async classmethod，把原本散落在 `Stack.loopback()` 里的 13 行 sink/pipe 样板代码内化：

```python
class VirtualController:
    @classmethod
    async def create(
        cls,
        address: BDAddress | None = None,
    ) -> tuple["VirtualController", Transport]:
        """Create a VirtualController and a host-side Transport ready for use.

        Internally manages a private bidirectional in-process pipe (_HCIPipe)
        between this controller and the host stack. Returns (controller, host_transport)
        where host_transport is already opened.
        """
        # Implementation detail: uses the private _HCIPipe class defined alongside
        # VirtualController; the pipe is not exposed publicly.
```

`pybluehost/stack.py` 改名 + 新增：

- 改名：`Stack.loopback()` → `Stack.virtual()`，`StackMode.LOOPBACK` → `StackMode.VIRTUAL`（枚举值 `"virtual"`）。
- `Stack.virtual()` 函数体简化为：
  ```python
  @classmethod
  async def virtual(cls, config: StackConfig | None = None) -> Stack:
      from pybluehost.hci.virtual import VirtualController
      vc, host_t = await VirtualController.create()
      stack = await cls._build(host_t, config, StackMode.VIRTUAL)
      stack._local_address = vc._address
      return stack
  ```
- 新增 `from_usb()` / `from_uart()` 兑现 docstring 承诺，并修复 `tests/hardware/test_usb_smoke.py` 的隐 bug：

```python
@classmethod
async def from_usb(cls,
                   vendor: str | None = None,
                   bus: int | None = None,
                   address: int | None = None,
                   config: StackConfig | None = None) -> Stack:
    transport = USBTransport.auto_detect(vendor=vendor, bus=bus, address=address)
    await transport.open()
    return await cls._build(transport, config, StackMode.LIVE)

@classmethod
async def from_uart(cls,
                    port: str,
                    baudrate: int = 115200,
                    config: StackConfig | None = None) -> Stack:
    transport = UARTTransport(port=port, baudrate=baudrate)
    await transport.open()
    return await cls._build(transport, config, StackMode.LIVE)
```

### 5.4 USBTransport 新增方法

`USBTransport` 已支持 `vendor=` 过滤。新增：

- `USBTransport.list_devices() -> list[DeviceCandidate]`：返回所有检测到的 Bluetooth USB 设备的 `(chip_info, bus, address)` 元组。供自动检测和 `--list-transports` 诊断使用。
- `USBTransport.auto_detect(..., bus=None, address=None)`：两者都提供时精确锁定指定适配器；第二适配器选择必须用到。

## 6. CLI 选项与环境变量

### 6.1 pytest CLI 选项

| 选项 | 作用 |
|------|------|
| `--transport=<spec>` | primary transport spec |
| `--transport-peer=<spec>` | peer transport spec（仅影响 `peer_stack`） |
| `--list-transports` | 打印所有检测到的 transport 后退出 |

### 6.2 Spec 语法（与 `pybluehost.cli._transport.parse_transport_arg` 共用）

```
virtual                                    VirtualController（软件仿真控制器，无需硬件）
usb                                        自动检测任意 USB 蓝牙适配器
usb:vendor=intel                           按 vendor 过滤
usb:vendor=intel,bus=1,address=4           精确锁定指定适配器
uart:/dev/ttyUSB0                          UART，默认 115200 baud
uart:/dev/ttyUSB0@921600                   UART，指定 baud
```

`bus=` / `address=` 是新增的 spec 键；解析后转发给 `USBTransport.auto_detect`。

### 6.3 环境变量

| 变量 | 等价 CLI |
|------|---------|
| `PYBLUEHOST_TEST_TRANSPORT` | `--transport=...` |
| `PYBLUEHOST_TEST_TRANSPORT_PEER` | `--transport-peer=...` |

### 6.4 自动检测算法

```python
def autodetect_primary() -> str:
    candidates = USBTransport.list_devices()
    if candidates:
        c = candidates[0]
        return f"usb:vendor={c.vendor},bus={c.bus},address={c.address}"
    return "virtual"
```

UART 永远不自动检测（无可靠"是蓝牙设备"的识别方式）。需要 UART 必须显式指定。

### 6.5 Session 启动横幅（`pytest_report_header`）

固定三种形式：

```
[pybluehost-tests] transport: usb (Intel AX210, bus=1 address=4) [auto-detected]
[pybluehost-tests] transport: usb:vendor=intel [explicit]
[pybluehost-tests] transport: virtual [auto-detected — no hardware found]
```

如果同时解析了 peer transport，第二行同格式打印 peer 信息。

### 6.6 Session 末尾汇总（`pytest_terminal_summary`）

仅在发生回落（自动检测因无硬件回落到 virtual）时打印：

```
==================== pybluehost transport summary ====================
⚠  Auto-detect found no hardware. <N> tests ran on virtual.
   Set --transport=usb (or PYBLUEHOST_TEST_TRANSPORT=usb) to validate
   against real hardware.
======================================================================
```

## 7. 测试级标记

### 7.1 标记列表

| 标记 | 行为 |
|------|------|
| `@pytest.mark.real_hardware_only` | 见 §7.2 决策矩阵；virtual 模式整体 skip |
| `@pytest.mark.virtual_only` | `transport_mode != 'virtual'` 时整体 skip；message: "deterministic test, runs only on virtual controller" |

旧的 `@pytest.mark.hardware` 标记**删除**，并从 `pyproject.toml` 的 markers 表移除。

### 7.2 `real_hardware_only` 的两个 kwargs：`transport` 与 `vendor`

`real_hardware_only` 接受两个**正交、必须显式声明**的 kwargs，用于细化"硬件"约束：

```python
# 任何真硬件（USB 或 UART 都接受）
@pytest.mark.real_hardware_only

# 任何 USB
@pytest.mark.real_hardware_only(transport="usb")

# 任何 UART
@pytest.mark.real_hardware_only(transport="uart")

# Intel USB —— 必须同时写 transport="usb" 和 vendor="intel"
@pytest.mark.real_hardware_only(transport="usb", vendor="intel")

# Intel 或 Realtek USB
@pytest.mark.real_hardware_only(transport="usb", vendor=("intel", "realtek"))
```

**显式声明原则**：本设计**不接受隐式约束**。即使"vendor 必然意味着 USB"，作者也必须把 `transport="usb"` 写出来。读测试代码的人不需要记忆隐含规则，IDE 也能直接看出约束全貌。

**kwargs 取值范围**：
- `transport`：`"usb"` 或 `"uart"`（与 `family_of()` 返回的家族对应；不接受 `"virtual"` —— 那是 `virtual_only` 的职责）
- `vendor`：`"intel"` / `"realtek"` / `"csr"` 之一，或它们的元组（与 `pybluehost.transport.usb.KNOWN_CHIPS` 的 vendor 集合一致）

### 7.3 决策矩阵

| 当前 spec | marker | 行为 |
|---------|--------|------|
| `virtual` | 任何 `real_hardware_only` 形式 | skip：「requires real hardware (use --transport=usb)」 |
| `usb:vendor=intel,...` | （无 kwargs） | run |
| `usb:vendor=intel,...` | `(transport="usb")` | run |
| `usb:vendor=intel,...` | `(transport="uart")` | skip：「requires 'uart' transport, got 'usb'」 |
| `usb:vendor=intel,...` | `(transport="usb", vendor="intel")` | run |
| `usb:vendor=intel,...` | `(transport="usb", vendor="realtek")` | skip：「requires vendor in ('realtek',), got 'intel'」 |
| `usb:vendor=realtek,...` | `(transport="usb", vendor=("intel", "realtek"))` | run |
| `uart:/dev/ttyUSB0` | （无 kwargs） | run |
| `uart:/dev/ttyUSB0` | `(transport="uart")` | run |
| `uart:/dev/ttyUSB0` | `(transport="usb")` | skip：「requires 'usb' transport, got 'uart'」 |

### 7.4 用法错误

如果 marker kwargs 违反约束（见下表），测试以「marker 用法错误」原因 skip，message 指出问题让作者修正：

| 错误用法 | skip message |
|---------|------|
| `vendor=` 给了但没给 `transport="usb"` | `"real_hardware_only marker error: vendor= requires transport='usb'"` |
| `transport=` 不是 `"usb"` 或 `"uart"` | `"real_hardware_only marker error: transport must be 'usb' or 'uart', got <value>"` |
| `vendor=` 不在 KNOWN_CHIPS 厂商集合 | `"real_hardware_only marker error: unsupported vendor <value>"` |

### 7.5 强制执行位置

所有标记规则统一在 `tests/conftest.py` 的 `pytest_collection_modifyitems` 钩子中实现，复用 `tests/_transport_select.py` 的 `family_of()` / `vendor_of()` 工具函数。使用 `peer_stack` fixture 的测试**无需手动加标记** —— fixture 内部会在第二适配器不可用时自动 skip。

## 8. 迁移

### 8.1 新增文件

| 路径 | 用途 |
|------|------|
| `tests/_transport_select.py` | session 级 spec 解析、自动检测、第二适配器查找 |
| `tests/_fallback_tracker.py` | session 级回落计数，供 `pytest_terminal_summary` 访问 |

### 8.2 修改文件

| 路径 | 修改 |
|------|------|
| `pybluehost/stack.py` | 改名 `Stack.loopback()` → `Stack.virtual()`、`StackMode.LOOPBACK` → `StackMode.VIRTUAL`；新增 `from_usb()`、`from_uart()`；`virtual()` 函数体简化为调用 `VirtualController.create()` |
| `pybluehost/hci/virtual.py` | 新增 `VirtualController.create()` async classmethod；新增私有内部类 `_HCIPipe`（接收原 `LoopbackTransport` 的实现，仅 VC 内部使用） |
| `pybluehost/transport/usb.py` | 新增 `list_devices()`；扩展 `auto_detect()` 支持 `bus=` / `address=` |
| `pybluehost/transport/loopback.py` | **删除整个文件**（功能内化到 `VirtualController._HCIPipe`） |
| `pybluehost/transport/__init__.py` | 移除 `LoopbackTransport` 导出 |
| `pybluehost/cli/_transport.py` | spec 值 `loopback` → `virtual`；`virtual` 分支改用 `VirtualController.create()`；扩展 `parse_transport_arg` 识别 `bus=` / `address=` |
| `pybluehost/cli/_loopback_peer.py` | **重命名**为 `pybluehost/cli/_virtual_peer.py`；`loopback_peer_with` → `virtual_peer_with` |
| `pybluehost/cli/app/gatt_browser.py` | 更新 import：`_loopback_peer` → `_virtual_peer`；`loopback_peer_with` → `virtual_peer_with` |
| `tests/conftest.py` | 注册 §5–§6 描述的 hooks 与 fixtures |
| `tests/integration/conftest.py` | 清空内容（现有 fixture `vc_a`、`vc_b`、`hci_with_vc`、`l2cap_with_hci` 均为死代码，没有测试在用；改为依赖顶层 `stack`/`peer_stack`） |
| `tests/e2e/conftest.py` | 替换内容 —— `single_loopback_stack` 移除 |
| `tests/hardware/conftest.py` | 整个删除 |
| `tests/integration/test_hci_init.py`、`test_hci_l2cap.py` | 当前在每个测试内**内联定义** `LoopbackTransport` 类并实例化 `VirtualController`。把这套样板代码替换为 `stack` fixture 参数，访问 `stack.hci`（必要时 `stack.l2cap`） |
| `tests/unit/cli/test_app_*.py`（六个文件） | 内联 `Stack.loopback()` → `stack` fixture 参数（首先随改名 task 改成 `Stack.virtual()`，迁移 task 里替换为 fixture） |
| `tests/unit/cli/test_loopback_peer.py` | **重命名**为 `tests/unit/cli/test_virtual_peer.py`；调用 `virtual_peer_with` |
| `tests/unit/transport/test_loopback.py` | **删除**（pipe 已私有化，功能覆盖通过 `tests/unit/hci/test_virtual.py` 与 `Stack.virtual()` 端到端测试） |
| `tests/unit/test_stack.py` | `Stack.loopback()` → `Stack.virtual()`；`StackMode.LOOPBACK` → `StackMode.VIRTUAL` |
| `tests/hardware/test_usb_smoke.py` | 改用 `stack` fixture；加 `pytestmark = pytest.mark.real_hardware_only` |
| `tests/hardware/test_intel_hw.py` | `pytest.mark.hardware` → `pytest.mark.real_hardware_only`；保留 raw-USB fixture |
| `pyproject.toml` | 按 §4 更新 `markers` 列表 |
| `.github/workflows/test.yml` | pytest 命令加 `--transport=virtual`；删除 `-m "not hardware"` |
| `README.md` | "运行测试"段落新增 `--transport` 选项说明；CLI 用法示例 `--transport loopback` → `--transport virtual` |
| `CLAUDE.md` | "常用测试命令"新增 `--transport` 示例 |

### 8.3 不变文件

- `tests/unit/conftest.py`（仍用 fakes）
- `tests/btsnoop/`（文件回放，无 transport）
- `tests/fakes/`（fake 实现自身）
- `pybluehost/hci/virtual.py` 中既有的 `VirtualController` 协议处理逻辑（`process()` 等）—— 仅追加 `create()` classmethod 与私有 `_HCIPipe`

## 9. 改写示例

### 9.1 集成测试

旧：
```python
async def test_l2cap_signaling(l2cap_with_hci):
    ...
```

新：
```python
async def test_l2cap_signaling(stack):
    l2cap = stack.l2cap
    ...
```

### 9.2 CLI app 测试

旧：
```python
async def test_ble_scan_command():
    stack = await Stack.loopback()
    try:
        ...
    finally:
        await stack.close()
```

新：
```python
async def test_ble_scan_command(stack):
    ...
```

### 9.3 双控制器测试（peer）

⚠ **重要边界**：本次设计中，virtual 模式下两个 `VirtualController` 实例**完全独立**——它们之间没有共享空气信道，不能互相收发广播 / inquiry / page / connection / ATT。`peer_stack` 仅适用于以下两种模式：

1. **Server 端配置 + 直接读 server 状态**（demo trick）：在 peer 上注册 GATT/SDP 服务，测试代码直接断言 peer server DB 的内容。这是当前 `gatt_browser` / `sdp_browser` loopback 模式的工作方式。
2. **真硬件 + 真硬件**：两块物理适配器通过空气信道真实通信，所有 GAP/L2CAP/ATT 协议都跑真协议栈。

跨 VC 的虚拟无线模拟是一个**独立的、范围更大的能力**（详见 §15），不在本次 plan 内。

```python
async def test_peer_server_data(stack, peer_stack):
    """Server-side configuration test (works on both virtual and hardware)."""
    # Configure peer's server side
    await register_battery_service(peer_stack.gatt_server)

    # On virtual: assert directly on peer state (no real ATT exchange)
    # On hardware: stack would actually connect+discover via real radio
    if peer_stack.mode == StackMode.VIRTUAL:
        assert _has_battery_service(peer_stack.gatt_server.db)
    else:
        await stack.gap.ble_connect(peer_stack.local_address)
        services = await stack.gatt_client.discover_services()
        assert _battery_in(services)
```

## 10. 错误处理

| 场景 | 行为 | 退出码 |
|------|------|--------|
| `--transport=usb`，找不到 USB 适配器 | collection 阶段 `pytest.exit("Transport 'usb' unavailable: no Bluetooth USB device found", returncode=4)` | 4 |
| `--transport=uart:/dev/ttyXXX`，端口打不开 | collection 阶段 `pytest.exit(...)` | 4 |
| `--transport=usb` + `--transport-peer=virtual`（异族） | collection 阶段 `pytest.exit("Peer transport must match primary family")` | 4 |
| `PYBLUEHOST_TEST_TRANSPORT=invalid_spec` | collection 阶段 `pytest.exit(f"Invalid transport spec: {spec!r}")` | 4 |
| 自动检测无硬件 | 静默回落 virtual；fallback_count++；末尾打印汇总 | 0 |
| `peer_stack` 测试 + 单适配器硬件模式 | 测试 skip：「peer_stack requires 2 hardware adapters of same family; found 1」 | 0 |
| `real_hardware_only` 测试 + virtual 模式 | 测试 skip：「requires real hardware (use --transport=usb)」 | 0 |
| `virtual_only` 测试 + 硬件模式 | 测试 skip：「deterministic test, runs only on virtual controller」 | 0 |
| `--list-transports`（诊断） | 打印每个检测到的适配器后 `pytest.exit(returncode=0)`，不进入 collection | 0 |

## 11. CI 策略

`.github/workflows/test.yml` 运行 `uv run pytest tests/ -q --transport=virtual`。GitHub-hosted runner 没有蓝牙硬件，因此 primary 模式固定为 virtual；因为是显式选择而非自动检测，回落汇总不会出现。

`fail_under = 85` 覆盖率阈值不变。如果重构在 `Stack.from_usb` / `Stack.from_uart` 引入 CI 无法执行的硬件路径，仅对 import / open 那几行用 `# pragma: no cover`，避免大范围排除。

未来通过自托管 runner 跑硬件测试**不在本次范围**；本设计前向兼容（追加一个跑 `pytest --transport=usb:vendor=intel` 的 job 即可，不需要再改架构）。

## 12. 不做的事（YAGNI）

- 单 pytest session 内多 transport。
- UART 自动检测。
- 混合：1 块真硬件 + 1 个虚拟 peer（射频介质不匹配，配对失败）。
- 参数化 fixture 让单个测试自动跑多个 transport。
- 自托管 runner 的硬件 CI job（设计上兼容，但不构建）。
- `loopback` 旧名兼容 shim（v0.0.1，按项目策略不留 shim）。
- **跨 `VirtualController` 的虚拟无线模拟**（广播路由、inquiry/page response、ATT 跨 VC 串接、connection 状态机等）—— 详见 §15，作为独立后续 plan。

## 13. `loopback` → `virtual` 改名 + pipe 内化清单

为保持术语精准，本次同步完成全栈改名，并把 pipe 抽象内化为 `VirtualController` 私有实现，让"loopback"概念彻底退出公开 API。

| 旧 | 新 | 说明 |
|------|------|------|
| `Stack.loopback()` | `Stack.virtual()` | 工厂方法 |
| `StackMode.LOOPBACK` (= `"loopback"`) | `StackMode.VIRTUAL` (= `"virtual"`) | 枚举值 + 字符串值 |
| pytest spec `loopback` | `virtual` | `--transport`、`--transport-peer`、env var |
| `@pytest.mark.loopback_only` | `@pytest.mark.virtual_only` | 测试标记 |
| CLI `pybluehost xxx --transport loopback` | `--transport virtual` | CLI 一致用法 |
| `pybluehost/cli/_loopback_peer.py` | `pybluehost/cli/_virtual_peer.py` | 文件改名 |
| `loopback_peer_with()` 函数 | `virtual_peer_with()` | 函数改名 |
| `tests/unit/cli/test_loopback_peer.py` | `tests/unit/cli/test_virtual_peer.py` | 测试文件改名 |
| `LoopbackTransport`（公开类，公开模块） | `_HCIPipe`（`VirtualController` 内部私有类） | pipe 内化 |
| `pybluehost/transport/loopback.py` | **删除** | 模块整个文件不再存在 |
| `tests/unit/transport/test_loopback.py` | **删除** | 私有实现，不再独立测试 |
| `pybluehost.transport` 公开导出 `LoopbackTransport` | **移除** | `__init__.py` 不再 re-export |
| **新增**：`VirtualController.create()` | （新 API） | 返回 `(vc, host_transport)`，封装原 13 行 sink 样板 |
| **保留**：`VirtualController`、`pybluehost/hci/virtual.py` | （不变） | 已是正确命名，仅追加 `create()` 与 `_HCIPipe` |

## 14. 验收标准

1. 在没插任何蓝牙硬件的开发机上 `uv run pytest tests/ -q` 通过，header 打印 `transport: virtual [auto-detected — no hardware found]`，末尾打印回落汇总。
2. `uv run pytest tests/ -q --transport=virtual` 通过，覆盖率不变，**无**回落汇总（显式选择）。
3. 在装有 Intel 适配器的机器上 `uv run pytest tests/ -q --transport=usb` 让所有 `stack` 相关测试都跑在真硬件上；`peer_stack` 测试在没插第二块适配器时带清晰 message 跳过。
4. **没插**适配器时跑 `uv run pytest tests/ -q --transport=usb` 在 collection 阶段以非零（4）退出，并给出清晰错误信息。
5. `pytest --list-transports` 列出所有检测到的适配器后退出。
6. `--hardware` flag 消失；`pyproject.toml` 的 markers 表不再有 `hardware` 与 `loopback_only`；`real_hardware_only`、`virtual_only` 已注册。
7. master 上 CI 用 `--transport=virtual` 通过，覆盖率 ≥ 85%。
8. README 和 CLAUDE.md 都已记录新选项。
9. `Stack.loopback()` / `StackMode.LOOPBACK` / `--transport=loopback` / `LoopbackTransport` / `loopback_peer_with` 在代码库与文档中**无残留**（grep 验证）。
10. `pybluehost/transport/` 目录下不再有 `loopback.py`；`pybluehost.transport.__init__` 不再导出任何 `Loopback*` 名称。

## 15. 后续：VirtualRadio（独立立项）

为支持真正的"Virtual + Virtual peer"端到端协议测试（central↔peripheral GATT 交换、inquiry/page、SMP pairing、跨 VC L2CAP 等），需要新增**进程内虚拟空气信道**（VirtualRadio / VirtualAirBus）：

- 全局 bus 跟踪每个 `VirtualController` 当前模式（advertising / scanning / inquiring / page-scanning / connected）；
- LE：VC A 调用 `LE_Set_Advertising_Enable` 时 bus 路由 ADV_IND 到所有处于 scanning 状态的 VC B，触发 `LE Advertising Report Event`；
- BR/EDR：inquiry / page 同理；
- Connection：`LE Create Connection` / `Create Connection` 经 bus 与 peer 协商，建立双向 ACL 通道；
- ACL/L2CAP/ATT：跨 VC 数据透传，让 `gatt_browser` 等真正经过协议栈而非读 server DB。

立项文档（待 brainstorming）：`docs/superpowers/specs/virtual-radio-design.md`。该工作完成后，本设计的 `peer_stack` fixture 即可承载跨 VC 真协议测试，gatt_browser/sdp_browser loopback 模式的"demo trick"也将被真正的协议路径替换。
