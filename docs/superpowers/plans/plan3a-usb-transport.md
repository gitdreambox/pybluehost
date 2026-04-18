# Plan 3a: USB Transport Core

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement USB transport core — ChipInfo registry, USBTransport base, auto_detect, endpoint routing, WinUSB verification, HCIUserChannelTransport. This covers the PRD P0 scenario transport skeleton: connecting to real Intel/Realtek Bluetooth hardware on Windows (WinUSB) and Linux (hci_user_channel), without firmware loading logic.

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
| `pybluehost/transport/usb.py` | `USBTransport`, `IntelUSBTransport` (shell), `RealtekUSBTransport` (shell), `ChipInfo`, `KNOWN_CHIPS` |
| `pybluehost/transport/hci_user_channel.py` | `HCIUserChannelTransport` (Linux-only) |
| `tests/unit/transport/test_usb.py` | USB Transport unit tests (with fake pyusb device) |

---

## Task 1: ChipInfo Registry + USBTransport Base

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

- [ ] **Step 4: Implement `IntelUSBTransport` and `RealtekUSBTransport` transport class shells (no firmware loading logic — that is in Plan 3b)**

```python
class IntelUSBTransport(USBTransport):
    """Intel Bluetooth USB transport. Firmware loading implemented in Plan 3b."""

    async def _initialize(self) -> None:
        """Placeholder — full firmware loading sequence implemented in Plan 3b."""

class RealtekUSBTransport(USBTransport):
    """Realtek Bluetooth USB transport. Firmware loading implemented in Plan 3b."""

    async def _initialize(self) -> None:
        """Placeholder — full firmware loading sequence implemented in Plan 3b."""
```

- [ ] **Step 5: Fill `KNOWN_CHIPS` transport_class fields after subclass definitions (補充 3)**

```python
# After IntelUSBTransport and RealtekUSBTransport are defined:
for chip in KNOWN_CHIPS:
    if chip.vendor == "intel":
        object.__setattr__(chip, "transport_class", IntelUSBTransport)
    elif chip.vendor == "realtek":
        object.__setattr__(chip, "transport_class", RealtekUSBTransport)
```

Note: Alternatively, route by `vendor` field in `auto_detect()` to avoid mutating frozen dataclass instances.

- [ ] **Step 6: Add endpoint routing tests (補充 4)**

```python
# tests/unit/transport/test_usb.py (additions)
@patch("pybluehost.transport.usb.usb")
@pytest.mark.asyncio
async def test_send_command_routes_to_control(mock_usb):
    """H4 type 0x01 (HCI Command) routes to Control endpoint."""
    mock_device = MagicMock()
    chip = ChipInfo("intel", "AX210", 0x8087, 0x0032, "ibt-0040-*", None)
    transport = USBTransport(device=mock_device, chip_info=chip)
    control_calls = []
    async def fake_control_out(data): control_calls.append(data)
    transport._control_out = fake_control_out
    await transport.send(b"\x01\xfc\x00")  # HCI Command prefix
    assert len(control_calls) == 1

@patch("pybluehost.transport.usb.usb")
@pytest.mark.asyncio
async def test_send_acl_routes_to_bulk_out(mock_usb):
    """H4 type 0x02 (ACL Data) routes to Bulk OUT endpoint."""
    mock_device = MagicMock()
    chip = ChipInfo("intel", "AX210", 0x8087, 0x0032, "ibt-0040-*", None)
    transport = USBTransport(device=mock_device, chip_info=chip)
    bulk_calls = []
    async def fake_bulk_out(data): bulk_calls.append(data)
    transport._bulk_out = fake_bulk_out
    await transport.send(b"\x02\x00\x20\x00\x00")  # ACL Data prefix
    assert len(bulk_calls) == 1

@patch("pybluehost.transport.usb.usb")
@pytest.mark.asyncio
async def test_send_sco_routes_to_isoch_out(mock_usb):
    """H4 type 0x03 (SCO Data) routes to Isochronous OUT endpoint."""
    mock_device = MagicMock()
    chip = ChipInfo("intel", "AX210", 0x8087, 0x0032, "ibt-0040-*", None)
    transport = USBTransport(device=mock_device, chip_info=chip)
    isoch_calls = []
    async def fake_isoch_out(data): isoch_calls.append(data)
    transport._isoch_out = fake_isoch_out
    await transport.send(b"\x03\x00\x00\x00")  # SCO Data prefix
    assert len(isoch_calls) == 1
```

- [ ] **Step 7: Verify TransportSink uses `on_transport_data` (補充 5)**

**Note**: TransportSink.on_data has been renamed to `on_transport_data` (2026-04-18 interface fix). All references to `on_data` in USB transport code must use `on_transport_data` instead.

- [ ] **Step 8: Run tests — verify they pass**

- [ ] **Step 9: Commit**
```bash
git add pybluehost/transport/usb.py tests/unit/transport/test_usb.py
git commit -m "feat(transport): add USBTransport base with KNOWN_CHIPS registry and auto_detect"
```

---

## Task 2: HCIUserChannelTransport (Linux)

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
from pybluehost.transport.usb import USBTransport, IntelUSBTransport, RealtekUSBTransport, ChipInfo, KNOWN_CHIPS, NoBluetoothDeviceError
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

## Task 3: pyproject.toml + Full Test Run

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

- [ ] **Step 4: Update STATUS.md — mark Plan 3a complete**
```bash
git add pyproject.toml docs/superpowers/STATUS.md
git commit -m "docs: mark Plan 3a (USB Transport Core) complete in STATUS.md"
```
