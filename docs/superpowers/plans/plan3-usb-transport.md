# Plan 3: USB Transport + Firmware Management

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement `pybluehost/transport/usb.py` — `USBTransport`, `IntelUSBTransport`, `RealtekUSBTransport`, `HCIUserChannelTransport`, `FirmwarePolicy`, and firmware management. This is the PRD P0 scenario: connecting to real Intel/Realtek Bluetooth hardware on Windows (WinUSB) and Linux (hci_user_channel).

**Architecture reference:** `docs/architecture/06-transport.md` sections 6.2–6.8

**Dependencies:** `pybluehost/transport/base.py` (Transport ABC)

**New dependencies to add to pyproject.toml:**
```toml
[project.optional-dependencies]
usb = ["pyusb>=1.2"]
```

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/transport/usb.py` | `USBTransport`, `IntelUSBTransport`, `RealtekUSBTransport`, `ChipInfo`, `KNOWN_CHIPS`, `FirmwarePolicy`, `FirmwareManager` |
| `pybluehost/transport/hci_user_channel.py` | `HCIUserChannelTransport` (Linux-only) |
| `pybluehost/transport/firmware/` | Firmware management utilities |
| `pybluehost/transport/firmware/__init__.py` | `FirmwareManager`, `FirmwarePolicy`, `FirmwareSource` |
| `tests/unit/transport/test_usb.py` | USB Transport unit tests (with fake pyusb device) |
| `tests/unit/transport/test_firmware.py` | FirmwareManager unit tests |

---

## Task 1: FirmwarePolicy + FirmwareManager

**Files:** `pybluehost/transport/firmware/__init__.py`, `tests/unit/transport/test_firmware.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/transport/test_firmware.py
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from pybluehost.transport.firmware import (
    FirmwarePolicy, FirmwareManager, FirmwareNotFoundError,
)

def test_firmware_policy_enum():
    assert FirmwarePolicy.PROMPT == "prompt"
    assert FirmwarePolicy.ERROR == "error"
    assert FirmwarePolicy.AUTO_DOWNLOAD == "auto"

def test_firmware_manager_finds_file(tmp_path):
    fw_dir = tmp_path / "intel"
    fw_dir.mkdir()
    fw_file = fw_dir / "ibt-0040-0041.sfi"
    fw_file.write_bytes(b"\xFF" * 1024)

    mgr = FirmwareManager(vendor="intel", extra_dirs=[fw_dir])
    result = mgr.find("ibt-0040-0041.sfi")
    assert result == fw_file

def test_firmware_manager_missing_raises_on_error_policy(tmp_path):
    mgr = FirmwareManager(vendor="intel", policy=FirmwarePolicy.ERROR)
    with pytest.raises(FirmwareNotFoundError) as exc_info:
        mgr.find("ibt-0040-0041.sfi")
    assert "ibt-0040-0041.sfi" in str(exc_info.value)
    # Error message should contain download instructions
    assert "pybluehost fw download" in str(exc_info.value)

def test_firmware_manager_prompt_policy(tmp_path):
    mgr = FirmwareManager(vendor="intel", policy=FirmwarePolicy.PROMPT)
    with pytest.raises(FirmwareNotFoundError) as exc_info:
        mgr.find("ibt-0040-0041.sfi")
    msg = str(exc_info.value)
    assert "方式一" in msg or "Option 1" in msg  # contains instructions

def test_firmware_search_priority(tmp_path):
    """Extra dirs take precedence over default dirs."""
    high_prio = tmp_path / "high"
    low_prio = tmp_path / "low"
    high_prio.mkdir(); low_prio.mkdir()

    (low_prio / "fw.bin").write_bytes(b"\x01")
    (high_prio / "fw.bin").write_bytes(b"\x02")

    mgr = FirmwareManager(vendor="intel", extra_dirs=[high_prio, low_prio])
    result = mgr.find("fw.bin")
    assert result.read_bytes() == b"\x02"
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `pybluehost/transport/firmware/__init__.py`**

```python
from enum import Enum
from pathlib import Path
import os, platform

class FirmwarePolicy(str, Enum):
    AUTO_DOWNLOAD = "auto"
    PROMPT = "prompt"
    ERROR = "error"

class FirmwareNotFoundError(RuntimeError):
    """Raised when firmware file cannot be found."""

class FirmwareManager:
    """Locate firmware files using priority search order:
    1. Environment variable (PYBLUEHOST_INTEL_FW_DIR / PYBLUEHOST_RTK_FW_DIR)
    2. extra_dirs (passed by caller)
    3. Platform data dir (~/.local/share/pybluehost/firmware/ or %APPDATA%\\pybluehost\\firmware\\)
    4. Package bundled dir
    5. System firmware dir (Linux: /lib/firmware/intel/ etc.)
    """
    SEARCH_DIRS: dict[str, list[Path]]   # vendor → platform search paths

    def __init__(self, vendor: str,
                 extra_dirs: list[Path] | None = None,
                 policy: FirmwarePolicy = FirmwarePolicy.PROMPT) -> None: ...

    def find(self, filename: str) -> Path:
        """Find firmware file. Raises FirmwareNotFoundError if not found."""
        # Search in priority order
        # If not found, apply policy (raise with instructions or attempt download)

    def _data_dir(self) -> Path:
        """Platform-specific user data directory."""

    def _format_not_found_message(self, filename: str) -> str:
        """Build user-friendly message with download instructions."""
```

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**
```bash
git add pybluehost/transport/firmware/ tests/unit/transport/test_firmware.py
git commit -m "feat(transport): add FirmwarePolicy and FirmwareManager with priority search"
```

---

## Task 2: ChipInfo Registry + USBTransport Base

**Files:** `pybluehost/transport/usb.py` (ChipInfo + USBTransport base), tests

- [ ] **Step 1: Write failing tests (using fake pyusb)**

```python
# tests/unit/transport/test_usb.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from pybluehost.transport.usb import (
    ChipInfo, KNOWN_CHIPS, USBTransport,
    NoBluetoothDeviceError,
)
from pybluehost.transport.firmware import FirmwarePolicy

def test_known_chips_not_empty():
    assert len(KNOWN_CHIPS) >= 10

def test_known_chips_intel_ax210():
    ax210 = next((c for c in KNOWN_CHIPS if c.name == "AX210"), None)
    assert ax210 is not None
    assert ax210.vid == 0x8087
    assert ax210.pid == 0x0032
    assert ax210.vendor == "intel"

def test_known_chips_realtek_rtl8761b():
    rtl = next((c for c in KNOWN_CHIPS if c.name == "RTL8761B"), None)
    assert rtl is not None
    assert rtl.vid == 0x0BDA
    assert rtl.pid == 0x8771
    assert rtl.vendor == "realtek"

def test_chip_info_dataclass():
    chip = ChipInfo(
        vendor="intel", name="AX210",
        vid=0x8087, pid=0x0032,
        firmware_pattern="ibt-0040-*",
        transport_class=None,
    )
    assert chip.vid == 0x8087
    assert chip.firmware_pattern == "ibt-0040-*"

@patch("pybluehost.transport.usb.usb")
def test_auto_detect_no_device_raises(mock_usb):
    mock_usb.core.find.return_value = None
    with pytest.raises(NoBluetoothDeviceError):
        USBTransport.auto_detect()

@patch("pybluehost.transport.usb.usb")
def test_auto_detect_known_chip(mock_usb):
    # Simulate finding an Intel AX210
    mock_device = MagicMock()
    mock_device.idVendor = 0x8087
    mock_device.idProduct = 0x0032
    mock_usb.core.find.return_value = [mock_device]
    transport = USBTransport.auto_detect()
    from pybluehost.transport.usb import IntelUSBTransport
    assert isinstance(transport, IntelUSBTransport)
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `ChipInfo`, `KNOWN_CHIPS`, `USBTransport` base**

```python
# pybluehost/transport/usb.py
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from pybluehost.transport.base import Transport, TransportInfo, ReconnectPolicy
from pybluehost.transport.firmware import FirmwareManager, FirmwarePolicy

@dataclass(frozen=True)
class ChipInfo:
    vendor: str
    name: str
    vid: int
    pid: int
    firmware_pattern: str
    transport_class: type  # IntelUSBTransport | RealtekUSBTransport

KNOWN_CHIPS: list[ChipInfo] = [
    # Intel
    ChipInfo("intel", "AX200",  0x8087, 0x0029, "ibt-20-*",    None),  # filled after class defs
    ChipInfo("intel", "AX201",  0x8087, 0x0026, "ibt-20-*",    None),
    ChipInfo("intel", "AX210",  0x8087, 0x0032, "ibt-0040-*",  None),
    ChipInfo("intel", "AX211",  0x8087, 0x0033, "ibt-0040-*",  None),
    ChipInfo("intel", "AC9560", 0x8087, 0x0025, "ibt-18-*",    None),
    ChipInfo("intel", "AC8265", 0x8087, 0x0a2b, "ibt-12-*",    None),
    # Realtek
    ChipInfo("realtek", "RTL8761B",  0x0BDA, 0x8771, "rtl8761b_fw",  None),
    ChipInfo("realtek", "RTL8852AE", 0x0BDA, 0x2852, "rtl8852au_fw", None),
    ChipInfo("realtek", "RTL8852BE", 0x0BDA, 0x887B, "rtl8852bu_fw", None),
    ChipInfo("realtek", "RTL8852CE", 0x0BDA, 0x4853, "rtl8852cu_fw", None),
    ChipInfo("realtek", "RTL8723DE", 0x0BDA, 0xB009, "rtl8723d_fw",  None),
]

class NoBluetoothDeviceError(RuntimeError): ...
class WinUSBDriverError(RuntimeError): ...

class USBTransport(Transport):
    """USB HCI transport via pyusb (WinUSB on Windows, libusb on Linux)."""

    def __init__(self, device, chip_info: ChipInfo | None = None,
                 firmware_policy: FirmwarePolicy = FirmwarePolicy.PROMPT) -> None: ...

    @classmethod
    def auto_detect(cls, firmware_policy: FirmwarePolicy = FirmwarePolicy.PROMPT) -> "USBTransport":
        """Enumerate USB devices, match KNOWN_CHIPS, return correct subclass instance."""
        try:
            import usb.core
        except ImportError:
            raise RuntimeError("pyusb not installed. Run: pip install pyusb")
        # 1. usb.core.find(find_all=True) → all USB devices
        # 2. Match VID/PID against KNOWN_CHIPS
        # 3. Found → return chip.transport_class(device, chip_info)
        # 4. Not found → try bDeviceClass=0xE0, SubClass=0x01, Protocol=0x01
        # 5. Still not found → raise NoBluetoothDeviceError

    async def open(self) -> None:
        # 1. Platform check: Windows → _verify_winusb_driver()
        # 2. Claim interface 0 (HCI), optionally interface 1 (SCO)
        # 3. Locate endpoints (Control EP0, Interrupt IN, Bulk IN/OUT, Isoch IN/OUT)
        # 4. Call _initialize() (subclass overrides for firmware loading)
        # 5. Start reader tasks: _read_interrupt(), _read_bulk_in()

    async def close(self) -> None: ...

    async def send(self, data: bytes) -> None:
        """Route by H4 packet type indicator."""
        packet_type = data[0]
        match packet_type:
            case 0x01:  await self._control_out(data[1:])   # HCI Command
            case 0x02:  await self._bulk_out(data[1:])       # ACL Data
            case 0x03:  await self._isoch_out(data[1:])      # SCO Data

    async def _initialize(self) -> None:
        """Override in subclasses for firmware loading. Default: no-op."""

    def _verify_winusb_driver(self) -> None:
        """Windows: check device is bound to WinUSB, not Microsoft Bluetooth driver."""
```

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**
```bash
git add pybluehost/transport/usb.py tests/unit/transport/test_usb.py
git commit -m "feat(transport): add USBTransport base with KNOWN_CHIPS registry and auto_detect"
```

---

## Task 3: IntelUSBTransport — Firmware Loading

**Files:** `pybluehost/transport/usb.py` (IntelUSBTransport), tests

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/transport/test_usb.py (additions)
@pytest.mark.asyncio
async def test_intel_transport_initialize_sends_read_version(tmp_path):
    """IntelUSBTransport._initialize() sends HCI_Intel_Read_Version first."""
    from pybluehost.transport.usb import IntelUSBTransport
    mock_device = MagicMock()
    # Create a dummy firmware file
    fw_dir = tmp_path / "intel"
    fw_dir.mkdir()
    (fw_dir / "ibt-0040-0041.sfi").write_bytes(b"\x00" * 512)

    chip = ChipInfo("intel", "AX210", 0x8087, 0x0032, "ibt-0040-*", IntelUSBTransport)
    transport = IntelUSBTransport(device=mock_device, chip_info=chip,
                                   extra_fw_dirs=[fw_dir])
    transport._is_open = True

    sent_commands = []
    async def fake_control_out(data): sent_commands.append(data)
    transport._control_out = fake_control_out

    # Mock the event reception for Read_Version response
    # (simplified: _initialize reads version, we mock the response)
    with patch.object(transport, "_wait_for_vendor_event") as mock_wait:
        mock_wait.return_value = bytes([0x00, 0x00, 0x10, 0x00, 0x01, 0x00])
        try:
            await transport._initialize()
        except Exception:
            pass  # May fail without full USB stack — just check command was sent

    assert len(sent_commands) >= 1
    # First vendor command should be HCI_Intel_Read_Version (0xFC05)
    # vendor command payload: opcode bytes
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `IntelUSBTransport._initialize()`**

```python
class IntelUSBTransport(USBTransport):
    """Intel Bluetooth USB transport with firmware loading."""

    async def _initialize(self) -> None:
        """16-step Intel firmware load sequence:
        1. HCI_Intel_Read_Version (vendor 0xFC05) → get hw_variant, fw_variant
        2. Find firmware file (FirmwareManager)
        3. HCI_Intel_Enter_Mfg_Mode
        4. Stream firmware in ~252-byte chunks via vendor command, await CCE per chunk
        5. HCI_Intel_Reset (vendor reset)
        6. Wait for Vendor Specific Event confirming firmware boot
        7. HCI_Intel_Read_Version (verify new fw_variant)
        """

    async def _send_intel_vendor_cmd(self, ocf: int, params: bytes = b"") -> bytes:
        """Send Intel vendor command (OGF=0x3F), await Command Complete Event."""
```

- [ ] **Step 4: Implement `RealtekUSBTransport._initialize()`**

```python
class RealtekUSBTransport(USBTransport):
    """Realtek Bluetooth USB transport with firmware loading."""

    async def _initialize(self) -> None:
        """Realtek firmware load:
        1. HCI_Realtek_Read_ROM_Version (vendor 0xFC6D) → lmp_subversion, rom_version
        2. Find fw + config files (FirmwareManager)
        3. Download firmware in chunks (vendor cmd 0xFC20)
        4. Download config (if present)
        5. HCI_Reset → verify lmp_subversion updated
        """
```

- [ ] **Step 5: Run tests — verify they pass**

- [ ] **Step 6: Commit**
```bash
git add pybluehost/transport/usb.py
git commit -m "feat(transport): add IntelUSBTransport and RealtekUSBTransport with firmware loading"
```

---

## Task 4: HCIUserChannelTransport (Linux)

**Files:** `pybluehost/transport/hci_user_channel.py`, tests

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/transport/test_hci_user_channel.py
import sys, pytest
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux only")

from pybluehost.transport.hci_user_channel import HCIUserChannelTransport

def test_import_on_linux():
    transport = HCIUserChannelTransport(hci_index=0)
    assert transport is not None
    assert not transport.is_open

def test_transport_info():
    transport = HCIUserChannelTransport(hci_index=0)
    info = transport.info
    assert info.type == "hci_user_channel"
    assert "hci0" in info.description
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `HCIUserChannelTransport`**

```python
class HCIUserChannelTransport(Transport):
    """Linux-only: raw HCI access via AF_BLUETOOTH hci_user_channel socket."""

    def __init__(self, hci_index: int = 0) -> None: ...

    async def open(self) -> None:
        # 1. hciconfig hci{index} down (bring interface down)
        # 2. socket(AF_BLUETOOTH, SOCK_RAW, BTPROTO_HCI)
        # 3. bind((hci_index, HCI_CHANNEL_USER))
        # 4. Start async reader task

    async def close(self) -> None: ...
    async def send(self, data: bytes) -> None: ...
```

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Update `transport/__init__.py` and commit**

```python
# Add to __init__.py exports:
from pybluehost.transport.usb import USBTransport, IntelUSBTransport, RealtekUSBTransport, ChipInfo, KNOWN_CHIPS, FirmwarePolicy, NoBluetoothDeviceError
# HCIUserChannelTransport: only export on Linux
import sys
if sys.platform == "linux":
    from pybluehost.transport.hci_user_channel import HCIUserChannelTransport
```

```bash
git add pybluehost/transport/hci_user_channel.py pybluehost/transport/__init__.py
git commit -m "feat(transport): add HCIUserChannelTransport for Linux hci_user_channel socket"
```

---

## Task 5: pyproject.toml + Full Test Run

- [ ] **Step 1: Add USB optional dependency to pyproject.toml**

```toml
[project.optional-dependencies]
usb = ["pyusb>=1.2"]
dev = [
    "pytest>=8.0", "pytest-asyncio>=0.23", "pytest-cov>=5.0",
    "pyserial-asyncio>=0.6",
]
```

- [ ] **Step 2: Run all transport tests**
```bash
uv run pytest tests/unit/transport/ -v --tb=short
```

- [ ] **Step 3: Run full test suite**
```bash
uv run pytest tests/ -v --tb=short
```

- [ ] **Step 4: Update STATUS.md — mark Plan 3 complete**
```bash
git add pyproject.toml docs/superpowers/STATUS.md
git commit -m "docs: mark Plan 3 (USB Transport) complete in STATUS.md"
```

---

## 审查补充事项 (2026-04-18 审查后追加)

以下事项在深度审查中发现遗漏，需要在执行时补充到对应 Task 中。

### 补充 1: CLI 工具 `pybluehost fw ...`（架构 06-transport.md §6.4）

**新增 Task**: 固件 CLI 工具

**Files:**
- Create: `pybluehost/cli/__init__.py`
- Create: `pybluehost/cli/fw.py`
- Modify: `pyproject.toml` (add `[project.scripts]` entry)

CLI 命令列表（架构文档定义的 6 条）:
- `pybluehost fw download intel` — 下载 Intel 固件
- `pybluehost fw download realtek` — 下载 Realtek 固件
- `pybluehost fw list` — 列出已安装的固件
- `pybluehost fw info <path>` — 显示固件文件信息
- `pybluehost fw auto` — 自动检测芯片并下载对应固件
- `pybluehost fw clean` — 清理固件缓存

### 补充 2: FirmwarePolicy.AUTO_DOWNLOAD 实现细节

当前 Plan 只测试了 PROMPT 和 ERROR 策略。AUTO_DOWNLOAD 需要：
- HTTP 下载逻辑（使用 urllib 或可选 httpx 依赖）
- 下载后完整性校验（文件大小 + magic signature）
- 网络超时配置（默认 30s）
- 失败后 fallback 到 PROMPT 策略

### 补充 3: KNOWN_CHIPS transport_class 字段

Plan 中 `KNOWN_CHIPS` 列表的 `transport_class` 全部为 `None`，注释说 "filled after class defs"。需要在定义 `IntelUSBTransport` 和 `RealtekUSBTransport` 后，增加一个步骤填充这些值：

```python
# After IntelUSBTransport and RealtekUSBTransport are defined:
for chip in KNOWN_CHIPS:
    if chip.vendor == "intel":
        object.__setattr__(chip, "transport_class", IntelUSBTransport)
    elif chip.vendor == "realtek":
        object.__setattr__(chip, "transport_class", RealtekUSBTransport)
```

或者改为在 `auto_detect()` 中根据 vendor 字段路由，避免 frozen dataclass 修改。

### 补充 4: USB endpoint 路由测试

需要补充 `USBTransport.send()` 的三路路由测试：
- Command (0x01) → Control endpoint
- ACL (0x02) → Bulk OUT endpoint  
- SCO (0x03) → Isochronous OUT endpoint

### 补充 5: TransportSink 接口已更新

**注意**：TransportSink.on_data 已重命名为 `on_transport_data`（2026-04-18 接口修复）。Plan 中所有引用 `on_data` 的地方需要改为 `on_transport_data`。

### 补充 6: 拆分建议

建议将本 Plan 拆分为：
- **Plan 3a — USB Transport 核心**: ChipInfo 注册表、USBTransport ABC、auto_detect、端点路由、WinUSB 验证、HCIUserChannelTransport
- **Plan 3b — 固件管理系统**: FirmwarePolicy、FirmwareManager（搜索+下载+校验）、Intel/Realtek._initialize() 完整流程、CLI 工具

拆分依据：两者文件集不重叠，可并行开发。
