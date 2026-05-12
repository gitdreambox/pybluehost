# Transport USB God Module 拆包 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `pybluehost/transport/usb.py`（2562 行 god module）拆成职责清晰的 package，保持外部 import 路径完全不变（`from pybluehost.transport.usb import IntelUSBTransport` 等所有现有 import 站点照常工作）。

**Architecture:** 纯文件结构重构、零行为变更。通过 `git mv usb.py usb/__init__.py` 保留 git history，然后逐个抽出符号到兄弟模块，`__init__.py` 收尾时只剩 re-export + `KNOWN_CHIPS` 表。后续每次 commit 都跑全套测试，确保只有 3 个 pre-existing USB diagnostics 失败保留（同合并前状态）。

**Tech Stack:** Python 3.10+ package mechanics、git mv、pytest（`--transport=virtual`）。

**评审报告基线**：[review-notes-2026-05-12.md](../../architecture/review-notes-2026-05-12.md) §三 中期重构 #4

---

## 范围声明

本 Plan **包含**：

1. 把 `pybluehost/transport/usb.py` 转成 `pybluehost/transport/usb/` package
2. 按职责拆分为 8 个 sibling 模块：`chips.py`, `errors.py`, `discovery.py`, `diagnostics.py`, `base.py`, `intel.py`, `realtek.py`, `csr.py`
3. `__init__.py` 保留所有现有公开符号的 re-export
4. 全套测试在每个 commit 后保持绿（只允许 3 个 pre-existing USB diagnostics 失败）

本 Plan **不包含**（明确推迟）：

- 任何行为改动 —— 这是纯重构 Plan
- 修复 3 个 pre-existing USB diagnostics 失败 —— 单独 Plan
- USB transport 错误处理改进 / log 清理 / `except Exception` 收紧 —— 单独 Plan
- 把 `usb/` 之外的其它 god module 拆包（无别的 god module 待拆）

---

## 拆分映射表

当前 `usb.py` 2562 行的符号分布：

| 符号 | 当前行（约） | 目标文件 |
|------|-------------|---------|
| `ChipInfo` dataclass | 34-44 | `chips.py` |
| `DeviceCandidate` dataclass | 46-70 | `discovery.py` |
| `RealtekLocalVersion` dataclass | 72-80 | `realtek.py` |
| `FailureType`, `DriverType` enums | 82-94 | `diagnostics.py` |
| `USBDiagnosticReport` / `USBDeviceCheck` / `USBDeviceDiagnosis` | 96-125 | `diagnostics.py` |
| `USBDeviceDiagnostics` class | 127-281 | `diagnostics.py` |
| `NoBluetoothDeviceError`, `WinUSBDriverError` | 282-288 | `errors.py` |
| `known_chip_for`, `known_usb_vendors` | 290-301 | `discovery.py` |
| `usb_class_tuple`, `is_bluetooth_usb_class`, `iter_usb_interfaces`, `is_bluetooth_usb_device`, `format_usb_class` | 302-350 | `discovery.py` |
| `_descriptor_string`, `_bluetooth_usb_occurrence_indexes`, `_matches_usb_selection` | 351-398 | `discovery.py` |
| `get_usb_endpoints`, `_bumble_transport_names` | 399-440 | `discovery.py` |
| `parse_hci_reset_status` | 441-446 | `base.py` |
| `_find_interrupt_in_endpoint` | 447-461 | `diagnostics.py` |
| `_diagnostic_report_checks` | 462-475 | `diagnostics.py` |
| `_flush_interrupt_endpoint`, `_send_hci_command_direct` | 476-489 | `diagnostics.py` |
| `_diagnose_intel_version_direct`, `_diagnose_realtek_version_direct` | 490-587 | `diagnostics.py` |
| `USBTransport` base class | 588-1284 | `base.py` |
| `IntelUSBTransport` (含 `_BootParams` 嵌套) | 1285-2065 | `intel.py` |
| `RealtekUSBTransport` | 2066-2531 | `realtek.py` |
| `CSRUSBTransport` | 2532-2541 | `csr.py` |
| `KNOWN_CHIPS` table | 2543-2563 | `__init__.py`（必须在 transport 类 import 后） |

## 依赖图（确保无循环）

```
chips.py        — 无内部依赖
errors.py       — 无内部依赖
discovery.py    — chips, errors
diagnostics.py  — chips, errors, discovery
base.py         — chips, errors, discovery, diagnostics
intel.py        — base, diagnostics
realtek.py      — base, diagnostics
csr.py          — base
__init__.py     — 全部（含 KNOWN_CHIPS 表）
```

## 任务依赖图

```
Task 1 (rename) ─► Task 2 (chips+errors) ─► Task 3 (discovery) ─►
Task 4 (diagnostics) ─► Task 5 (base) ─► Task 6 (intel) ─►
Task 7 (realtek) ─► Task 8 (csr) ─► Task 9 (__init__ shim + STATUS)
```

严格串行 —— 每个任务都依赖上一个任务把符号正确抽出。

---

## Task 1: 改名 `usb.py` → `usb/__init__.py`

**Files:**
- Rename: `pybluehost/transport/usb.py` → `pybluehost/transport/usb/__init__.py`

### Step 1.1: 用 git mv 重命名

- [ ] **Run:**

```bash
cd pybluehost/transport
mkdir usb_tmp
git mv usb.py usb_tmp/__init__.py
mv usb_tmp usb
git status
```

说明：先 `mkdir usb_tmp` 是为了避免 `mkdir usb` 与现存 `usb.py` 文件名冲突；`git mv` 完成后 `usb_tmp` 改回 `usb`。

预期 `git status` 显示：`renamed: pybluehost/transport/usb.py -> pybluehost/transport/usb/__init__.py`

### Step 1.2: 验证导入仍生效

- [ ] **Run:**

```bash
uv run --frozen python -c "
from pybluehost.transport.usb import USBTransport, IntelUSBTransport, RealtekUSBTransport, CSRUSBTransport, KNOWN_CHIPS, ChipInfo, NoBluetoothDeviceError, WinUSBDriverError, known_chip_for, known_usb_vendors, usb_class_tuple, is_bluetooth_usb_class, iter_usb_interfaces, is_bluetooth_usb_device, format_usb_class, get_usb_endpoints
print('all imports OK')
print('USBTransport:', USBTransport.__name__)
print('KNOWN_CHIPS count:', len(KNOWN_CHIPS))
"
```

预期：`all imports OK` + `USBTransport: USBTransport` + `KNOWN_CHIPS count: 14`（KNOWN_CHIPS 现有 14 行条目）。

### Step 1.3: 跑全套测试确认无回归

- [ ] **Run:**

```bash
cd ../..   # 回到项目根
uv run --frozen pytest tests/ -q --transport=virtual --tb=no 2>&1 | tail -10
```

预期：只有 3 个 pre-existing USB diagnostics 失败：
- `tests/unit/cli/tools/test_usb_diagnostics.py::TestCmdUSBDiagnose::test_device_bthusb_driver`
- `tests/unit/cli/tools/test_usb_diagnostics.py::TestCmdUSBDiagnose::test_device_access_denied`
- `tests/unit/transport/test_usb.py::TestUSBTransportDiagnostics::test_open_access_denied_raises_diagnostic_error`

如果有任何其它新失败，**STOP**：rename 不该改变任何行为，多出的失败是 import 路径残留问题，必须先排查。

### Step 1.4: 提交

- [ ] **Run:**

```bash
git add -A pybluehost/transport
git commit -m "refactor(transport/usb): convert module to package (no content change)

Step 1 of usb.py god module split. Rename usb.py to usb/__init__.py so
subsequent commits can extract sibling modules without breaking the
existing 'from pybluehost.transport.usb import X' callers."
```

---

## Task 2: 抽出 `chips.py` + `errors.py`

**Files:**
- Create: `pybluehost/transport/usb/chips.py`
- Create: `pybluehost/transport/usb/errors.py`
- Modify: `pybluehost/transport/usb/__init__.py`（删除已抽出的定义，加 import）

### Step 2.1: 创建 `chips.py`

- [ ] **Create `pybluehost/transport/usb/chips.py`** with the `ChipInfo` dataclass:

```python
"""USB chip identification dataclass.

ChipInfo identifies a known Bluetooth USB chip by VID/PID and links it to
the concrete Transport subclass that knows how to initialize it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChipInfo:
    """Known Bluetooth USB chip metadata.

    Fields:
        vendor: vendor family slug (e.g. "intel", "realtek", "csr", "barrot")
        name: human-readable chip name (e.g. "AX200", "RTL8852BE")
        vid: USB vendor ID
        pid: USB product ID
        firmware_pattern: glob pattern matching firmware files this chip needs
            (empty string for chips that need no firmware load)
        transport_class: Transport subclass to instantiate for this chip
    """
    vendor: str
    name: str
    vid: int
    pid: int
    firmware_pattern: str
    transport_class: type | None  # filled by KNOWN_CHIPS in __init__.py after subclass imports
```

### Step 2.2: 创建 `errors.py`

- [ ] **Create `pybluehost/transport/usb/errors.py`**:

```python
"""USB-transport-specific exception types."""
from __future__ import annotations


class NoBluetoothDeviceError(RuntimeError):
    """Raised when no Bluetooth USB device is found matching the selection criteria."""


class WinUSBDriverError(RuntimeError):
    """Raised when a Windows device is bound to the wrong driver (bthusb.sys
    instead of WinUSB).
    """
```

### Step 2.3: 修改 `__init__.py` — 删除原 ChipInfo 和异常定义，改成 import

- [ ] **In `pybluehost/transport/usb/__init__.py`:**

Delete the original `@dataclass(frozen=True) class ChipInfo:` block (the dataclass definition that was around line 34-44 of the original file, look for the comment `# ChipInfo: known USB chip identifying info` or just search for `class ChipInfo`).

Delete the original `class NoBluetoothDeviceError(RuntimeError):` and `class WinUSBDriverError(RuntimeError):` definitions (around the original line 282-288, look for the `# Custom exceptions` comment block if present, otherwise search for the class names).

Add the imports at the TOP of `__init__.py`, after the existing `import` block (e.g. after `from pybluehost.transport.base import Transport, TransportInfo`):

```python
from pybluehost.transport.usb.chips import ChipInfo
from pybluehost.transport.usb.errors import NoBluetoothDeviceError, WinUSBDriverError
```

### Step 2.4: 验证导入

- [ ] **Run:**

```bash
uv run --frozen python -c "
from pybluehost.transport.usb import ChipInfo, NoBluetoothDeviceError, WinUSBDriverError
from pybluehost.transport.usb.chips import ChipInfo as ChipInfo2
from pybluehost.transport.usb.errors import NoBluetoothDeviceError as NB2
assert ChipInfo is ChipInfo2
assert NoBluetoothDeviceError is NB2
print('all OK')
"
```

预期：`all OK`。

### Step 2.5: 跑全套测试

- [ ] **Run:**

```bash
uv run --frozen pytest tests/ -q --transport=virtual --tb=no 2>&1 | tail -10
```

预期：只有 3 个 pre-existing USB diagnostics 失败。

### Step 2.6: 提交

- [ ] **Run:**

```bash
git add pybluehost/transport/usb/
git commit -m "refactor(transport/usb): extract ChipInfo and errors into sibling modules

Step 2 of usb.py split. Move ChipInfo to chips.py and NoBluetoothDeviceError/
WinUSBDriverError to errors.py. __init__.py re-exports preserve public API."
```

---

## Task 3: 抽出 `discovery.py`

**Files:**
- Create: `pybluehost/transport/usb/discovery.py`
- Modify: `pybluehost/transport/usb/__init__.py`

### Step 3.1: 创建 `discovery.py`

- [ ] **Create `pybluehost/transport/usb/discovery.py`** with the following symbols. Open the current `__init__.py`, copy the **entire** content of each of these definitions (function bodies + decorators) and assemble:

Symbols to move (search by name in `__init__.py`):

1. `DeviceCandidate` (dataclass)
2. `known_chip_for(dev)`
3. `known_usb_vendors()`
4. `usb_class_tuple(obj, prefix)`
5. `is_bluetooth_usb_class(values)`
6. `iter_usb_interfaces(dev)`
7. `is_bluetooth_usb_device(dev)`
8. `format_usb_class(values)`
9. `_descriptor_string(dev, attr)`
10. `_bluetooth_usb_occurrence_indexes(devices)`
11. `_matches_usb_selection(...)`
12. `get_usb_endpoints(dev)`
13. `_bumble_transport_names(dev, occurrence=None)`

Header for the new file:

```python
"""USB device discovery and selection helpers.

Pure-function helpers for enumerating USB devices, identifying Bluetooth
adapters, and matching them against caller-supplied selection criteria.
None of these helpers open a transport; that is base.py's job.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pybluehost.transport.usb.chips import ChipInfo

logger = logging.getLogger(__name__)

# Lazy import: pyusb is optional
try:
    import usb
    import usb.core
    import usb.util
except ImportError:
    usb = None  # type: ignore[assignment]


# --- paste the 13 symbols here ---
```

The 13 symbols include both `KNOWN_CHIPS` references and `ChipInfo` usage — that's fine because `chips.py` is already split out, and `KNOWN_CHIPS` is read via `from pybluehost.transport.usb import KNOWN_CHIPS` (lazy, only inside the functions that need it — search the original code; `known_chip_for` does `for chip in KNOWN_CHIPS:` so it needs a local import to avoid circular dep with `__init__.py`).

For `known_chip_for`, replace the top-level `for chip in KNOWN_CHIPS:` with a local import:

```python
def known_chip_for(dev: Any) -> ChipInfo | None:
    """Return the ChipInfo matching this device, or None if not in the registry."""
    from pybluehost.transport.usb import KNOWN_CHIPS  # local to avoid circular import
    for chip in KNOWN_CHIPS:
        if dev.idVendor == chip.vid and dev.idProduct == chip.pid:
            return chip
    return None
```

For `known_usb_vendors`, same treatment:

```python
def known_usb_vendors() -> frozenset[str]:
    """Return the set of vendor slugs in KNOWN_CHIPS."""
    from pybluehost.transport.usb import KNOWN_CHIPS
    return frozenset(chip.vendor for chip in KNOWN_CHIPS)
```

The other 11 symbols don't reference KNOWN_CHIPS and should be moved verbatim.

### Step 3.2: 删除 `__init__.py` 中的对应定义

- [ ] **In `pybluehost/transport/usb/__init__.py`**, delete the original definitions of the 13 symbols listed in Step 3.1 (search by name to locate; they're consecutively grouped around the original line 46-440).

### Step 3.3: 在 `__init__.py` 顶部添加 re-export

- [ ] **In `pybluehost/transport/usb/__init__.py`**, near the top (after the existing `from pybluehost.transport.usb.chips import ChipInfo` line), add:

```python
from pybluehost.transport.usb.discovery import (
    DeviceCandidate,
    known_chip_for,
    known_usb_vendors,
    usb_class_tuple,
    is_bluetooth_usb_class,
    iter_usb_interfaces,
    is_bluetooth_usb_device,
    format_usb_class,
    get_usb_endpoints,
)
```

Note: the underscore-prefixed `_descriptor_string`, `_bluetooth_usb_occurrence_indexes`, `_matches_usb_selection`, `_bumble_transport_names` are not re-exported (they're private to the package). If `USBTransport` in `__init__.py` (still there at this step) calls them, change those call sites to `from pybluehost.transport.usb.discovery import _name_` lazily at the call site, OR add a `_private` re-import at the top of `__init__.py`:

```python
from pybluehost.transport.usb.discovery import (
    _descriptor_string,
    _bluetooth_usb_occurrence_indexes,
    _matches_usb_selection,
    _bumble_transport_names,
)
```

(The underscore symbols are still callable from `__init__.py` body this way.)

### Step 3.4: 验证 + 提交

- [ ] **Run:**

```bash
uv run --frozen python -c "
from pybluehost.transport.usb import DeviceCandidate, known_chip_for, known_usb_vendors, usb_class_tuple, is_bluetooth_usb_class, iter_usb_interfaces, is_bluetooth_usb_device, format_usb_class, get_usb_endpoints
print('discovery imports OK')
print('vendors:', sorted(known_usb_vendors()))
"
```

预期：`discovery imports OK` + 一个排序后的 vendor 列表（包含 `barrot`, `csr`, `intel`, `realtek`）。

- [ ] **Run:**

```bash
uv run --frozen pytest tests/ -q --transport=virtual --tb=no 2>&1 | tail -10
```

预期：只有 3 个 pre-existing USB diagnostics 失败。

- [ ] **Commit:**

```bash
git add pybluehost/transport/usb/
git commit -m "refactor(transport/usb): extract discovery helpers into discovery.py

Step 3 of usb.py split. Move 13 device-discovery symbols (DeviceCandidate,
known_chip_for, known_usb_vendors, usb_class_tuple, is_bluetooth_usb_class,
iter_usb_interfaces, is_bluetooth_usb_device, format_usb_class,
_descriptor_string, _bluetooth_usb_occurrence_indexes, _matches_usb_selection,
get_usb_endpoints, _bumble_transport_names) to discovery.py."
```

---

## Task 4: 抽出 `diagnostics.py`

**Files:**
- Create: `pybluehost/transport/usb/diagnostics.py`
- Modify: `pybluehost/transport/usb/__init__.py`

### Step 4.1: 创建 `diagnostics.py`

- [ ] **Create `pybluehost/transport/usb/diagnostics.py`**. Header:

```python
"""USB transport diagnostic helpers.

USBDeviceDiagnostics inspects a device that failed to open and produces
a structured report (driver state, endpoint availability, firmware health)
that the CLI uses to print actionable remediation steps.
"""
from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pybluehost.transport.usb.chips import ChipInfo
from pybluehost.transport.usb.discovery import (
    format_usb_class,
    get_usb_endpoints,
    is_bluetooth_usb_device,
    iter_usb_interfaces,
    known_chip_for,
    usb_class_tuple,
)

logger = logging.getLogger(__name__)

# Lazy import: pyusb is optional
try:
    import usb
    import usb.core
    import usb.util
except ImportError:
    usb = None  # type: ignore[assignment]


# --- paste the symbols below ---
```

Move these from `__init__.py` (search by name):

1. `FailureType` enum
2. `DriverType` enum
3. `USBDiagnosticReport` dataclass
4. `USBDeviceCheck` dataclass
5. `USBDeviceDiagnosis` dataclass
6. `USBDeviceDiagnostics` class
7. `_diagnostic_report_checks(report)`
8. `_find_interrupt_in_endpoint(intf)`
9. `_flush_interrupt_endpoint(ep_intr)`
10. `_send_hci_command_direct(dev, ep_intr, opcode, params)`
11. `_diagnose_intel_version_direct(dev, ep_intr)`
12. `_diagnose_realtek_version_direct(dev, ep_intr)`

If any of those functions internally reference `_descriptor_string` / `_bluetooth_usb_occurrence_indexes` from discovery, add them to the top imports (or call them via `from pybluehost.transport.usb.discovery import _descriptor_string` lazily at call site — your choice; lazy is safer).

### Step 4.2: 删除 `__init__.py` 中的对应定义 + 添加 re-export

- [ ] In `__init__.py`, delete the 12 symbols above (their definitions are still there from the rename).

- [ ] In `__init__.py`, add near the top (after the discovery imports):

```python
from pybluehost.transport.usb.diagnostics import (
    FailureType,
    DriverType,
    USBDiagnosticReport,
    USBDeviceCheck,
    USBDeviceDiagnosis,
    USBDeviceDiagnostics,
)
# Private helpers needed by USBTransport (still in __init__.py at this step)
from pybluehost.transport.usb.diagnostics import (
    _diagnostic_report_checks,
    _find_interrupt_in_endpoint,
    _flush_interrupt_endpoint,
    _send_hci_command_direct,
    _diagnose_intel_version_direct,
    _diagnose_realtek_version_direct,
)
```

### Step 4.3: 验证 + 提交

- [ ] **Run:**

```bash
uv run --frozen python -c "
from pybluehost.transport.usb import USBDeviceDiagnostics, USBDiagnosticReport, FailureType, DriverType
print('diagnostics imports OK')
"
```

- [ ] **Run:**

```bash
uv run --frozen pytest tests/ -q --transport=virtual --tb=no 2>&1 | tail -10
```

预期：3 个 pre-existing 失败。

特别注意：`tests/unit/cli/tools/test_usb_diagnostics.py` 这 2 个失败本来就是 pre-existing。如果失败数变成 4 或更多 → 排查。

- [ ] **Commit:**

```bash
git add pybluehost/transport/usb/
git commit -m "refactor(transport/usb): extract diagnostics into diagnostics.py

Step 4 of usb.py split. Move USBDeviceDiagnostics + supporting dataclasses
(USBDiagnosticReport/Check/Diagnosis), enums (FailureType, DriverType),
and direct USB probe helpers (_diagnose_intel_version_direct etc.) to
diagnostics.py."
```

---

## Task 5: 抽出 `base.py`（USBTransport 基类）

**Files:**
- Create: `pybluehost/transport/usb/base.py`
- Modify: `pybluehost/transport/usb/__init__.py`

### Step 5.1: 创建 `base.py`

- [ ] **Create `pybluehost/transport/usb/base.py`**. Header:

```python
"""USBTransport base class.

Provides USB device enumeration (auto_detect, list_devices), endpoint
routing, and the abstract initialize() hook that vendor-specific subclasses
override for firmware upload. Subclasses (Intel/Realtek/CSR) live in
sibling modules.
"""
from __future__ import annotations

import asyncio
import logging
import struct
import sys
from typing import Any

from pybluehost.transport.base import Transport, TransportInfo
from pybluehost.transport.firmware import FirmwarePolicy
from pybluehost.transport.usb.chips import ChipInfo
from pybluehost.transport.usb.discovery import (
    _bluetooth_usb_occurrence_indexes,
    _bumble_transport_names,
    _descriptor_string,
    _matches_usb_selection,
    format_usb_class,
    get_usb_endpoints,
    is_bluetooth_usb_class,
    is_bluetooth_usb_device,
    iter_usb_interfaces,
    usb_class_tuple,
)
from pybluehost.transport.usb.diagnostics import (
    USBDeviceDiagnostics,
    USBDiagnosticReport,
    _diagnostic_report_checks,
    _find_interrupt_in_endpoint,
    _flush_interrupt_endpoint,
    _send_hci_command_direct,
)
from pybluehost.transport.usb.errors import (
    NoBluetoothDeviceError,
    WinUSBDriverError,
)

logger = logging.getLogger(__name__)

# Lazy import: pyusb is optional
try:
    import usb
    import usb.core
    import usb.util
except ImportError:
    usb = None  # type: ignore[assignment]


def parse_hci_reset_status(event: bytes) -> int | None:
    """Parse the status byte from an HCI Command Complete event for HCI_Reset.

    Returns the status code, or None if the event is not a Command Complete
    for HCI_Reset (0x0C03).
    """
    # --- paste the body from __init__.py ---


# --- paste USBTransport class body here ---
```

Move from `__init__.py`:
1. `parse_hci_reset_status(event)` — small util, was at original line 441-446
2. `USBTransport` class — the entire ~700-line body

If the `USBTransport` class body references any other module-level symbols that haven't been moved yet (e.g. forward references to `IntelUSBTransport`/`RealtekUSBTransport`/`CSRUSBTransport`/`KNOWN_CHIPS`), use lazy imports inside the methods that need them. The known cases:

- `USBTransport.auto_detect(...)` references `KNOWN_CHIPS` and the subclasses. Add at the top of the method body:
  ```python
  from pybluehost.transport.usb import KNOWN_CHIPS
  ```
  The subclasses are already referenced via `chip.transport_class`, no direct name needed.

### Step 5.2: 修改 `__init__.py`

- [ ] In `__init__.py`, delete `parse_hci_reset_status` and the `USBTransport` class body.

- [ ] In `__init__.py`, add re-export near the top (after diagnostics imports):

```python
from pybluehost.transport.usb.base import USBTransport, parse_hci_reset_status
```

### Step 5.3: 验证 + 提交

- [ ] **Run:**

```bash
uv run --frozen python -c "
from pybluehost.transport.usb import USBTransport, parse_hci_reset_status
print('USBTransport:', USBTransport)
print('parse_hci_reset_status:', parse_hci_reset_status)
"
```

- [ ] **Run:**

```bash
uv run --frozen pytest tests/ -q --transport=virtual --tb=no 2>&1 | tail -10
```

预期：3 个 pre-existing 失败。

- [ ] **Commit:**

```bash
git add pybluehost/transport/usb/
git commit -m "refactor(transport/usb): extract USBTransport base into base.py

Step 5 of usb.py split. Move USBTransport + parse_hci_reset_status to
base.py. The Intel/Realtek/CSR subclasses still live in __init__.py and
will move in subsequent commits."
```

---

## Task 6: 抽出 `intel.py`（IntelUSBTransport）

**Files:**
- Create: `pybluehost/transport/usb/intel.py`
- Modify: `pybluehost/transport/usb/__init__.py`

### Step 6.1: 创建 `intel.py`

- [ ] **Create `pybluehost/transport/usb/intel.py`**. Header:

```python
"""IntelUSBTransport — initializes Intel Bluetooth chips (AX2xx series, BE200, etc).

Implements the 6-step Intel firmware upload sequence: Read Version → Enter
Manufacturer Mode (legacy) → Secure Send firmware chunks → Reset → verify.
"""
from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass
from typing import Any

from pybluehost.transport.usb.base import USBTransport
from pybluehost.transport.usb.chips import ChipInfo
from pybluehost.transport.usb.diagnostics import _diagnose_intel_version_direct

logger = logging.getLogger(__name__)

# Lazy import: pyusb is optional
try:
    import usb
    import usb.core
    import usb.util
except ImportError:
    usb = None  # type: ignore[assignment]


# --- paste IntelUSBTransport class body here (including nested _BootParams) ---
```

Move the entire `IntelUSBTransport` class from `__init__.py` to `intel.py`. The class contains a nested `@dataclass(frozen=True) class _BootParams` — keep it nested inside `IntelUSBTransport` (do NOT promote to module level).

### Step 6.2: 修改 `__init__.py`

- [ ] In `__init__.py`, delete the `IntelUSBTransport` class body.

- [ ] In `__init__.py`, add re-export:

```python
from pybluehost.transport.usb.intel import IntelUSBTransport
```

### Step 6.3: 验证 + 提交

- [ ] **Run:**

```bash
uv run --frozen python -c "
from pybluehost.transport.usb import IntelUSBTransport, USBTransport
assert issubclass(IntelUSBTransport, USBTransport)
print('IntelUSBTransport OK')
"
```

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/transport/test_intel_fw.py tests/unit/transport/test_usb.py -v --transport=virtual --tb=short 2>&1 | tail -20
```

预期：Intel firmware 测试全绿（除 test_usb.py 中那 1 个 pre-existing diagnostic 失败）。

- [ ] **Run:**

```bash
uv run --frozen pytest tests/ -q --transport=virtual --tb=no 2>&1 | tail -10
```

预期：3 个 pre-existing 失败。

- [ ] **Commit:**

```bash
git add pybluehost/transport/usb/
git commit -m "refactor(transport/usb): extract IntelUSBTransport into intel.py

Step 6 of usb.py split. Move IntelUSBTransport (incl. nested _BootParams)
to intel.py. Imports diagnostics._diagnose_intel_version_direct for the
hardware diagnostic probe path."
```

---

## Task 7: 抽出 `realtek.py`（RealtekUSBTransport + RealtekLocalVersion）

**Files:**
- Create: `pybluehost/transport/usb/realtek.py`
- Modify: `pybluehost/transport/usb/__init__.py`

### Step 7.1: 创建 `realtek.py`

- [ ] **Create `pybluehost/transport/usb/realtek.py`**. Header:

```python
"""RealtekUSBTransport — initializes Realtek Bluetooth chips (RTL87xx series).

Implements the 5-step Realtek firmware upload sequence: Read Local Version →
Identify chip variant → Upload firmware blob → Reset → verify.
"""
from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass
from typing import Any

from pybluehost.transport.usb.base import USBTransport
from pybluehost.transport.usb.chips import ChipInfo
from pybluehost.transport.usb.diagnostics import _diagnose_realtek_version_direct

logger = logging.getLogger(__name__)

# Lazy import: pyusb is optional
try:
    import usb
    import usb.core
    import usb.util
except ImportError:
    usb = None  # type: ignore[assignment]


@dataclass(frozen=True)
class RealtekLocalVersion:
    """Realtek HCI_Read_Local_Version_Information response parsed fields."""
    hci_version: int
    hci_revision: int
    lmp_version: int
    manufacturer: int
    lmp_subversion: int


# --- paste RealtekUSBTransport class body here ---
```

Move `RealtekLocalVersion` dataclass + `RealtekUSBTransport` class from `__init__.py` to `realtek.py`.

### Step 7.2: 修改 `__init__.py`

- [ ] In `__init__.py`, delete `RealtekLocalVersion` dataclass and `RealtekUSBTransport` class body.

- [ ] In `__init__.py`, add re-export:

```python
from pybluehost.transport.usb.realtek import RealtekUSBTransport, RealtekLocalVersion
```

### Step 7.3: 验证 + 提交

- [ ] **Run:**

```bash
uv run --frozen python -c "
from pybluehost.transport.usb import RealtekUSBTransport, USBTransport
assert issubclass(RealtekUSBTransport, USBTransport)
print('RealtekUSBTransport OK')
"
```

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/transport/test_realtek_fw.py tests/unit/transport/test_usb.py -v --transport=virtual --tb=short 2>&1 | tail -20
```

- [ ] **Run:**

```bash
uv run --frozen pytest tests/ -q --transport=virtual --tb=no 2>&1 | tail -10
```

预期：3 个 pre-existing 失败。

- [ ] **Commit:**

```bash
git add pybluehost/transport/usb/
git commit -m "refactor(transport/usb): extract RealtekUSBTransport into realtek.py

Step 7 of usb.py split. Move RealtekUSBTransport + RealtekLocalVersion
dataclass to realtek.py."
```

---

## Task 8: 抽出 `csr.py`（CSRUSBTransport）

**Files:**
- Create: `pybluehost/transport/usb/csr.py`
- Modify: `pybluehost/transport/usb/__init__.py`

### Step 8.1: 创建 `csr.py`

- [ ] **Create `pybluehost/transport/usb/csr.py`**:

```python
"""CSRUSBTransport — initializes CSR8510 / Cambridge Silicon Radio Bluetooth dongles.

CSR8510 is a popular legacy USB Bluetooth dongle that needs no firmware
upload — open + standard HCI reset is enough. The subclass exists so
KNOWN_CHIPS can route to a class that's explicit about that property.
"""
from __future__ import annotations

from pybluehost.transport.usb.base import USBTransport


# --- paste CSRUSBTransport class body here ---
```

Move the `CSRUSBTransport` class from `__init__.py` (it's tiny, ~10 lines).

### Step 8.2: 修改 `__init__.py`

- [ ] In `__init__.py`, delete the `CSRUSBTransport` class body.

- [ ] In `__init__.py`, add re-export:

```python
from pybluehost.transport.usb.csr import CSRUSBTransport
```

### Step 8.3: 验证 + 提交

- [ ] **Run:**

```bash
uv run --frozen python -c "
from pybluehost.transport.usb import CSRUSBTransport, USBTransport
assert issubclass(CSRUSBTransport, USBTransport)
print('CSRUSBTransport OK')
"
```

- [ ] **Run:**

```bash
uv run --frozen pytest tests/ -q --transport=virtual --tb=no 2>&1 | tail -10
```

预期：3 个 pre-existing 失败。

- [ ] **Commit:**

```bash
git add pybluehost/transport/usb/
git commit -m "refactor(transport/usb): extract CSRUSBTransport into csr.py

Step 8 of usb.py split. Move CSRUSBTransport (last subclass) to csr.py.
__init__.py is now ~80 lines of re-exports + KNOWN_CHIPS table."
```

---

## Task 9: 清理 `__init__.py` + 更新 STATUS.md

**Files:**
- Modify: `pybluehost/transport/usb/__init__.py`
- Modify: `docs/superpowers/STATUS.md`

### Step 9.1: 重写 `__init__.py` 为干净的 re-export shim

- [ ] **Replace the entire content of `pybluehost/transport/usb/__init__.py`** with:

```python
"""USB HCI transport package.

This is a thin re-export shim. The implementation lives in sibling modules:

- ``chips``       : ChipInfo dataclass identifying known USB chips
- ``errors``      : Package-specific exception types
- ``discovery``   : Pure-function helpers for enumerating Bluetooth USB devices
- ``diagnostics`` : Diagnostic probes used when a device fails to open
- ``base``        : USBTransport abstract base class
- ``intel``       : IntelUSBTransport (AX200/AX201/AX210/BE200/...)
- ``realtek``     : RealtekUSBTransport (RTL8761/RTL8852/...)
- ``csr``         : CSRUSBTransport (CSR8510 and similar firmware-less dongles)

External callers should ``from pybluehost.transport.usb import <symbol>`` —
the layout above is an implementation detail and may change.
"""
from __future__ import annotations

from pybluehost.transport.usb.base import USBTransport, parse_hci_reset_status
from pybluehost.transport.usb.chips import ChipInfo
from pybluehost.transport.usb.csr import CSRUSBTransport
from pybluehost.transport.usb.diagnostics import (
    DriverType,
    FailureType,
    USBDeviceCheck,
    USBDeviceDiagnosis,
    USBDeviceDiagnostics,
    USBDiagnosticReport,
)
from pybluehost.transport.usb.discovery import (
    DeviceCandidate,
    format_usb_class,
    get_usb_endpoints,
    is_bluetooth_usb_class,
    is_bluetooth_usb_device,
    iter_usb_interfaces,
    known_chip_for,
    known_usb_vendors,
    usb_class_tuple,
)
from pybluehost.transport.usb.errors import (
    NoBluetoothDeviceError,
    WinUSBDriverError,
)
from pybluehost.transport.usb.intel import IntelUSBTransport
from pybluehost.transport.usb.realtek import RealtekLocalVersion, RealtekUSBTransport

# KNOWN_CHIPS must be defined AFTER subclass imports so chip.transport_class
# fields can reference real classes.
KNOWN_CHIPS: list[ChipInfo] = [
    # Intel
    ChipInfo("intel", "AX200",  0x8087, 0x0029, "ibt-20-*",   IntelUSBTransport),
    ChipInfo("intel", "AX201",  0x8087, 0x0026, "ibt-20-*",   IntelUSBTransport),
    ChipInfo("intel", "AX210",  0x8087, 0x0032, "ibt-0040-*", IntelUSBTransport),
    ChipInfo("intel", "AX211",  0x8087, 0x0033, "ibt-0040-*", IntelUSBTransport),
    ChipInfo("intel", "AC9560", 0x8087, 0x0025, "ibt-18-*",   IntelUSBTransport),
    ChipInfo("intel", "AC8265", 0x8087, 0x0A2B, "ibt-12-*",   IntelUSBTransport),
    ChipInfo("intel", "BE200",  0x8087, 0x0036, "ibt-0040-*", IntelUSBTransport),
    # Realtek
    ChipInfo("realtek", "RTL8761B",  0x0BDA, 0x8771, "rtl8761bu_fw.bin", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852AE", 0x0BDA, 0x2852, "rtl8852au_fw.bin", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852BE", 0x0BDA, 0x887B, "rtl8852bu_fw.bin", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852BE", 0x0BDA, 0x4853, "rtl8852bu_fw.bin", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8723DE", 0x0BDA, 0xB009, "rtl8723d_fw.bin",  RealtekUSBTransport),
    # CSR
    ChipInfo("csr", "CSR8510", 0x0A12, 0x0001, "", CSRUSBTransport),
    # BARROT (no firmware, uses generic USBTransport)
    ChipInfo("barrot", "BT6.0", 0x33FA, 0x0011, "", USBTransport),
]

__all__ = [
    # Core types
    "ChipInfo",
    "DeviceCandidate",
    # Transport classes
    "USBTransport",
    "IntelUSBTransport",
    "RealtekUSBTransport",
    "CSRUSBTransport",
    # Diagnostics
    "DriverType",
    "FailureType",
    "RealtekLocalVersion",
    "USBDeviceCheck",
    "USBDeviceDiagnosis",
    "USBDeviceDiagnostics",
    "USBDiagnosticReport",
    # Discovery helpers
    "format_usb_class",
    "get_usb_endpoints",
    "is_bluetooth_usb_class",
    "is_bluetooth_usb_device",
    "iter_usb_interfaces",
    "known_chip_for",
    "known_usb_vendors",
    "usb_class_tuple",
    # Utilities
    "parse_hci_reset_status",
    # Exceptions
    "NoBluetoothDeviceError",
    "WinUSBDriverError",
    # Chip registry
    "KNOWN_CHIPS",
]
```

This replaces whatever residual content was in `__init__.py` after Task 8 (mostly already-removed definitions and any remaining `from __future__` / `import` / leftover comments).

### Step 9.2: 验证完整 import 表面

- [ ] **Run:**

```bash
uv run --frozen python -c "
import pybluehost.transport.usb as m
expected = {
    'ChipInfo', 'DeviceCandidate',
    'USBTransport', 'IntelUSBTransport', 'RealtekUSBTransport', 'CSRUSBTransport',
    'DriverType', 'FailureType', 'RealtekLocalVersion',
    'USBDeviceCheck', 'USBDeviceDiagnosis', 'USBDeviceDiagnostics', 'USBDiagnosticReport',
    'format_usb_class', 'get_usb_endpoints', 'is_bluetooth_usb_class',
    'is_bluetooth_usb_device', 'iter_usb_interfaces', 'known_chip_for',
    'known_usb_vendors', 'usb_class_tuple',
    'parse_hci_reset_status',
    'NoBluetoothDeviceError', 'WinUSBDriverError',
    'KNOWN_CHIPS',
}
missing = expected - set(dir(m))
assert not missing, f'missing exports: {missing}'
assert len(m.KNOWN_CHIPS) == 14, f'expected 14 chips, got {len(m.KNOWN_CHIPS)}'
print('all', len(expected), 'public symbols present, KNOWN_CHIPS has', len(m.KNOWN_CHIPS), 'entries')
"
```

预期：`all 25 public symbols present, KNOWN_CHIPS has 14 entries`。

### Step 9.3: 跑全套测试 + coverage

- [ ] **Run:**

```bash
uv run --frozen pytest tests/ -q --transport=virtual --cov=pybluehost --cov-fail-under=85 --tb=no 2>&1 | tail -15
```

预期：只有 3 个 pre-existing USB diagnostics 失败；coverage ≥ 85%。

### Step 9.4: 更新 STATUS.md

- [ ] **Modify `docs/superpowers/STATUS.md`**:

(a) 在"快速定位"段更新：

```markdown
**当前进行中**：transport/usb 拆包 — ✅ 全部完成
**下一步**：选择下一个 Plan（完整 SMP 配对状态机 / HCI 容错初始化 / 断线重连闭环 / e2e 覆盖）
```

(b) 在 Plan 总览表追加一行：

```markdown
| transport/usb 拆包 | 2562 行 god module 拆成 8 个职责清晰的 sibling 模块 | ✅ 完成 | [2026-05-12-transport-usb-split](plans/2026-05-12-transport-usb-split.md) | `pybluehost/transport/usb/{__init__,chips,errors,discovery,diagnostics,base,intel,realtek,csr}.py` |
```

并把"总计：19 个 Plan"改成"总计：20 个 Plan"。

(c) 在"详细进度"章节追加：

```markdown
### ✅ transport/usb 拆包
- 完成时间：2026-05-12
- Plan 文档：[2026-05-12-transport-usb-split.md](plans/2026-05-12-transport-usb-split.md)
- 关键变化：纯结构重构、零行为变更
  - `transport/usb.py`（2562 行）→ `transport/usb/` package（8 模块）
  - 拆分映射：chips（ChipInfo）/ errors（异常类型）/ discovery（13 个 device-discovery helper）/ diagnostics（USBDeviceDiagnostics + 直接 USB 探针）/ base（USBTransport + parse_hci_reset_status）/ intel（IntelUSBTransport + _BootParams）/ realtek（RealtekUSBTransport + RealtekLocalVersion）/ csr（CSRUSBTransport）
  - `__init__.py` 仅 ~110 行：re-export + KNOWN_CHIPS 表
  - 外部 import 路径完全不变（`from pybluehost.transport.usb import X` 全部仍工作）
- 已知遗留：仅 3 个 pre-existing USB diagnostics 失败
- 验收：`uv run --frozen pytest tests/ -q --transport=virtual --cov-fail-under=85` PASS
```

(d) 在"问题日志"末尾追加一行：

```markdown
| 2026-05-12 | transport/usb 拆包 | usb.py 2562 行 god module 影响新加 vendor 的可维护性 | 按职责拆成 8 个 sibling 模块，__init__ 仅做 re-export；外部 import API 不变 | ✅ 已解决 |
```

### Step 9.5: 提交

- [ ] **Run:**

```bash
git add pybluehost/transport/usb/__init__.py docs/superpowers/STATUS.md
git commit -m "refactor(transport/usb): finish split — __init__.py is now a re-export shim

Step 9 (final) of usb.py split. __init__.py reduced to ~110 lines of
re-exports + KNOWN_CHIPS table. Public API surface unchanged:
'from pybluehost.transport.usb import X' continues to work for all 25
public symbols.

usb.py: 2562 lines → 8 focused sibling modules + thin __init__.py.

STATUS.md updated to mark the Plan complete."
```

---

## 验收清单（Plan 完成定义）

- [ ] `pybluehost/transport/usb.py` 不再存在（已转 package）
- [ ] 8 个 sibling 模块全部就位：`chips.py`, `errors.py`, `discovery.py`, `diagnostics.py`, `base.py`, `intel.py`, `realtek.py`, `csr.py`
- [ ] `__init__.py` ≤ 200 行
- [ ] 25 个公共符号 + `KNOWN_CHIPS` 全部可从 `pybluehost.transport.usb` 直接 import
- [ ] 全套测试只剩 3 个 pre-existing USB diagnostics 失败
- [ ] Coverage ≥ 85%
- [ ] STATUS.md 已更新

---

## 常见问题 / Troubleshooting

### Q: Task 1 `git mv usb.py usb/__init__.py` 报错 "destination directory does not exist"
- **现象**：直接跑 `git mv pybluehost/transport/usb.py pybluehost/transport/usb/__init__.py`，git 不允许在不存在的目录创建新文件
- **解决方案**：Task 1 Step 1.1 用了 `usb_tmp` 中转：先 `mkdir usb_tmp` → `git mv usb.py usb_tmp/__init__.py` → `mv usb_tmp usb`。后两步是文件系统操作不通过 git，所以可以工作

### Q: 抽出某个模块后 `ImportError: cannot import name 'X'` from `pybluehost.transport.usb`
- **现象**：移走某个符号后没在 `__init__.py` 加 re-export
- **解决方案**：每个 Task 的"修改 `__init__.py`"步骤都包含两件事：删除老定义 + 加 re-export。两个动作必须配对。如果忘了 re-export，回到对应 Task 把 re-export 补上

### Q: `KNOWN_CHIPS` 引用 `IntelUSBTransport`/`RealtekUSBTransport`/`CSRUSBTransport`，怎么避免循环依赖
- **现象**：把 `KNOWN_CHIPS` 放进 `chips.py` 会让 `chips.py` 反向依赖 `intel.py/realtek.py/csr.py`
- **解决方案**：`KNOWN_CHIPS` 留在 `__init__.py`（package init 时计算）。其它模块如 `discovery.py` 通过 `from pybluehost.transport.usb import KNOWN_CHIPS` 在函数内 lazy import 避免循环

### Q: Task N 后跑全套测试失败数 > 3
- **现象**：抽出某模块后，原 USB 测试出现新失败
- **可能原因**：
  1. 私有 helper 函数（如 `_descriptor_string`）被移走但 `__init__.py` 里还有代码依赖它
  2. 某个模块顶层 import 时没把可选依赖 `usb`（pyusb）按 `try/except ImportError` 包好
  3. 私有 helper 移动时改了签名
- **解决方案**：`git diff HEAD~1` 看上一个 commit 的变更，定位是哪个符号缺失。优先 lazy import 而不是顶层 import

Self-review 结果：本 Plan 9 个任务覆盖完整的 usb.py 2562 行拆分，每个任务都有 TDD-style 验证 + 完整测试回归，无 TBD 占位符，符号签名在跨任务中一致（`ChipInfo`、`USBTransport`、`KNOWN_CHIPS` 等），所有文件路径绝对化。
