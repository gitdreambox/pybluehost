# Plan 8b: Classic GAP + Unified GAP Entry

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement Classic GAP (Inquiry, Page, SSP, Discoverability) and unified GAP entry class with `set_pairing_delegate()`.

**Architecture reference:** `docs/architecture/11-gap.md` §11.4

**Dependencies:** `pybluehost/core/`, `pybluehost/hci/`, `pybluehost/classic/`, Plan 8a (BLE GAP + gap_common)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/classic/gap.py` | `ClassicDiscovery`, `ClassicDiscoverability`, `ClassicConnectionManager`, `SSPManager`, EIR |
| `pybluehost/gap.py` | Unified `GAP` entry point (combines BLE + Classic) + `set_pairing_delegate()` |
| `tests/unit/classic/test_gap.py` | Classic GAP unit tests |

---

## Task 1: Classic GAP + Unified GAP Entry Point

## Task 1: Classic GAP + Unified GAP Entry Point

**Files:** `pybluehost/classic/gap.py`, `tests/unit/classic/test_gap.py`

- [ ] **Step 1: Write failing Classic GAP tests**

```python
# tests/unit/classic/test_gap.py
import asyncio, pytest
from pybluehost.classic.gap import ClassicDiscovery, ClassicDiscoverability, InquiryConfig

class FakeHCI:
    def __init__(self): self.commands = []
    async def send_command(self, cmd):
        self.commands.append(cmd)
        from pybluehost.hci.packets import HCI_Command_Complete_Event
        from pybluehost.hci.constants import ErrorCode
        return HCI_Command_Complete_Event(
            num_hci_command_packets=1, command_opcode=cmd.opcode,
            return_parameters=bytes([ErrorCode.SUCCESS]),
        )

@pytest.mark.asyncio
async def test_set_discoverable(hci=None):
    hci = FakeHCI()
    d = ClassicDiscoverability(hci=hci)
    await d.set_discoverable(True)
    from pybluehost.hci.constants import HCI_WRITE_SCAN_ENABLE
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_WRITE_SCAN_ENABLE in opcodes

@pytest.mark.asyncio
async def test_set_device_name():
    hci = FakeHCI()
    d = ClassicDiscoverability(hci=hci)
    await d.set_device_name("PyBH-Device")
    from pybluehost.hci.constants import HCI_WRITE_LOCAL_NAME
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_WRITE_LOCAL_NAME in opcodes
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `classic/gap.py`**

`ClassicDiscovery`, `ClassicDiscoverability`, `ClassicConnectionManager`, `SSPManager` — each wraps the relevant HCI commands and handles the corresponding HCI events.

- [ ] **Step 4: Implement unified `GAP` class** (can live in `ble/gap.py` or a top-level `gap.py`)

```python
class GAP:
    """Unified GAP entry point — combines BLE + Classic."""
    def __init__(self, ble_advertiser, ble_scanner, ble_connections,
                 ble_privacy, classic_discovery, classic_discoverability,
                 classic_connections, classic_ssp,
                 whitelist: "WhiteList | None" = None,
                 ble_extended_advertiser: "ExtendedAdvertiser | None" = None) -> None: ...

    @property
    def ble_advertiser(self) -> BLEAdvertiser: ...
    @property
    def ble_scanner(self) -> BLEScanner: ...
    @property
    def ble_connections(self) -> BLEConnectionManager: ...
    @property
    def whitelist(self) -> "WhiteList": ...
    @property
    def ble_extended_advertiser(self) -> "ExtendedAdvertiser | None": ...
    @property
    def classic_discovery(self) -> ClassicDiscovery: ...
    @property
    def classic_discoverability(self) -> ClassicDiscoverability: ...
    @property
    def classic_connections(self) -> ClassicConnectionManager: ...
    def set_pairing_delegate(self, delegate) -> None: ...
```

- [ ] **Step 5: Run all GAP tests + full suite**
```bash
uv run pytest tests/unit/ble/test_gap.py tests/unit/classic/test_gap.py tests/unit/core/test_gap_common.py -v
uv run pytest tests/ -v --tb=short
```

- [ ] **Step 6: Commit + update STATUS.md**
```bash
git add pybluehost/classic/gap.py pybluehost/ble/gap.py pybluehost/core/gap_common.py tests/
git commit -m "feat(gap): add unified GAP layer — BLE Advertising/Scan/Connect + Classic Inquiry/SSP"

git add docs/superpowers/STATUS.md
git commit -m "docs: mark Plan 7 (GAP) complete in STATUS.md"
```

---

---

## 审查补充事项 (from Plan 8 review)

### 补充 1: Classic GAP 完整功能（架构 11-gap.md §11.4）

以下功能需要在本 Plan 中完整实现：
- ClassicDiscovery（Inquiry + Remote Name Request）
- ClassicDiscoverability（Write_Scan_Enable + EIR 设置）
- ClassicConnectionManager（Create_Connection / Accept_Connection）
- SSPManager（IO Capability Exchange + Numeric Comparison / Passkey / Just Works / OOB）
- 统一 GAP 入口类 + set_pairing_delegate()
