# Plan 3b: Firmware Management System

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement firmware management system — FirmwarePolicy, FirmwareManager (search+download+integrity verification), Intel 6-step and Realtek 5-step firmware loading sequences, and CLI tools (`pybluehost fw ...`).

**Architecture reference:** `docs/architecture/06-transport.md` sections 6.2–6.8

**Dependencies:** `pybluehost/transport/base.py` (Transport ABC), Plan 3a (USBTransport base classes)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/transport/firmware/__init__.py` | `FirmwareManager`, `FirmwarePolicy`, `FirmwareNotFoundError` |
| `pybluehost/transport/usb.py` | `IntelUSBTransport._initialize()`, `RealtekUSBTransport._initialize()` (firmware loading sequences) |
| `pybluehost/cli/__init__.py` | CLI entry point |
| `pybluehost/cli/fw.py` | `pybluehost fw` subcommands |
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

---

## Task 2: Intel Firmware Loading Sequence

**Files:** `pybluehost/transport/usb.py` (IntelUSBTransport), tests

This task implements the firmware loading logic inside `IntelUSBTransport._initialize()` (the transport class shell is created in Plan 3a).

## Task 2: IntelUSBTransport — Firmware Loading

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

---

## Task 3: CLI Tools (`pybluehost fw ...`)

**Files:** `pybluehost/cli/__init__.py`, `pybluehost/cli/fw.py`, `pyproject.toml`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/cli/test_fw.py
import pytest
from unittest.mock import patch, MagicMock
from pybluehost.cli.fw import fw_list, fw_download, fw_info

def test_fw_list_empty(tmp_path):
    with patch("pybluehost.cli.fw.FirmwareManager") as MockFM:
        MockFM.return_value.list_installed.return_value = []
        result = fw_list(fw_dir=tmp_path)
        assert result == []

def test_fw_download_intel(tmp_path):
    with patch("pybluehost.cli.fw.FirmwareManager") as MockFM:
        fw_download(vendor="intel", fw_dir=tmp_path)
        MockFM.return_value.download.assert_called_once()
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement CLI commands**

CLI 命令列表（架构文档 §6.4 定义）:
- `pybluehost fw download intel` — 下载 Intel 固件
- `pybluehost fw download realtek` — 下载 Realtek 固件
- `pybluehost fw list` — 列出已安装的固件
- `pybluehost fw info <path>` — 显示固件文件信息
- `pybluehost fw auto` — 自动检测芯片并下载对应固件
- `pybluehost fw clean` — 清理固件缓存

- [ ] **Step 4: Add `[project.scripts]` to pyproject.toml**

```toml
[project.scripts]
pybluehost = "pybluehost.cli:main"
```

- [ ] **Step 5: Run tests — verify they pass**

- [ ] **Step 6: Commit**
```bash
git add pybluehost/cli/ tests/unit/cli/ pyproject.toml
git commit -m "feat(cli): add pybluehost fw CLI tools for firmware management"
```

---

## Task 4: Full Test Run + STATUS.md

- [ ] **Step 1: Run all firmware + USB tests**
```bash
uv run pytest tests/unit/transport/test_firmware.py tests/unit/transport/test_usb.py -v
```

- [ ] **Step 2: Run full suite**
```bash
uv run pytest tests/ -v --tb=short
```

- [ ] **Step 3: Update STATUS.md — mark Plan 3b complete**

---

## 审查补充事项 (from Plan 3 review)

### 补充 1: FirmwarePolicy.AUTO_DOWNLOAD 实现细节

当前 Plan 只测试了 PROMPT 和 ERROR 策略。AUTO_DOWNLOAD 需要：
- HTTP 下载逻辑（使用 urllib 或可选 httpx 依赖）
- 下载后完整性校验（文件大小 + magic signature）
- 网络超时配置（默认 30s）
- 失败后 fallback 到 PROMPT 策略

### 补充 2: TransportSink 接口已更新

**注意**：TransportSink.on_data 已重命名为 `on_transport_data`（2026-04-18 接口修复）。Plan 中所有引用 `on_data` 的地方需要改为 `on_transport_data`。
