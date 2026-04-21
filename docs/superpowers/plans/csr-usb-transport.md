# CSR USB Transport 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 CSR8510（`0x0A12:0x0001`）增加一等 USB Transport 支持，使 `USBTransport.auto_detect()` 返回 `CSRUSBTransport`

**Architecture:** 沿用现有 `USBTransport` 的标准 Bluetooth USB HCI 路径，不引入 CSR 私有固件或厂商初始化流程。通过新增一个轻量的 `CSRUSBTransport` 子类、补充 `KNOWN_CHIPS` 注册表、更新公共导出与检测测试，完成最小可维护扩展。

**Tech Stack:** Python 3.10+, asyncio, pytest, unittest.mock, pyusb

---

## 文件结构

| 文件 | 责任 |
|------|------|
| `pybluehost/transport/usb.py` | 新增 `CSRUSBTransport`，扩展 `KNOWN_CHIPS` 注册表 |
| `pybluehost/transport/__init__.py` | 导出 `CSRUSBTransport` |
| `tests/unit/transport/test_usb.py` | 为 CSR 检测和类型分流补充单元测试 |

---

### Task 1: 先写 CSR 检测失败测试

**Files:**
- Modify: `tests/unit/transport/test_usb.py`
- Test: `tests/unit/transport/test_usb.py`

- [ ] **Step 1: 添加 CSR 注册表与自动检测测试**

```python
def test_known_chips_CSR8510():
    csr = next((c for c in KNOWN_CHIPS if c.name == "CSR8510"), None)
    assert csr is not None
    assert csr.vid == 0x0A12
    assert csr.pid == 0x0001
    assert csr.vendor == "csr"


@patch("pybluehost.transport.usb.usb")
def test_auto_detect_known_csr_chip(mock_usb):
    mock_device = MagicMock()
    mock_device.idVendor = 0x0A12
    mock_device.idProduct = 0x0001
    mock_usb.core.find.return_value = [mock_device]
    transport = USBTransport.auto_detect()
    from pybluehost.transport.usb import CSRUSBTransport
    assert isinstance(transport, CSRUSBTransport)


def test_csr_transport_is_usb_transport():
    from pybluehost.transport.usb import CSRUSBTransport

    chip = ChipInfo("csr", "CSR8510", 0x0A12, 0x0001, "", CSRUSBTransport)
    transport = CSRUSBTransport(device=MagicMock(), chip_info=chip)
    assert isinstance(transport, USBTransport)
```

- [ ] **Step 2: 运行聚焦测试，确认先失败**

Run:

```bash
uv run pytest tests/unit/transport/test_usb.py -v
```

Expected:

```text
FAIL tests for missing CSR8510 registry entry and/or missing CSRUSBTransport import
```

- [ ] **Step 3: 提交测试进度快照**

```bash
git add tests/unit/transport/test_usb.py
git commit -m "test(transport): add failing tests for CSR USB detection"
```

---

### Task 2: 以最小实现补齐 CSR Transport

**Files:**
- Modify: `pybluehost/transport/usb.py`
- Modify: `pybluehost/transport/__init__.py`
- Test: `tests/unit/transport/test_usb.py`

- [ ] **Step 1: 在 `usb.py` 中新增 `CSRUSBTransport`**

```python
class CSRUSBTransport(USBTransport):
    """CSR Bluetooth USB transport.

    CSR8510 currently uses the standard Bluetooth USB HCI path, so no
    vendor-specific initialization is required here.
    """
```

- [ ] **Step 2: 在 `KNOWN_CHIPS` 中注册 CSR8510**

```python
    # CSR
    ChipInfo("csr", "CSR8510", 0x0A12, 0x0001, "", CSRUSBTransport),
```

- [ ] **Step 3: 更新 `transport/__init__.py` 导出**

```python
from pybluehost.transport.usb import (
    CSRUSBTransport,
    ChipInfo,
    IntelUSBTransport,
    KNOWN_CHIPS,
    NoBluetoothDeviceError,
    RealtekUSBTransport,
    USBTransport,
)
```

```python
    "CSRUSBTransport",
```

- [ ] **Step 4: 运行聚焦测试，确认转绿**

Run:

```bash
uv run pytest tests/unit/transport/test_usb.py -v
```

Expected:

```text
PASS all USB transport unit tests including CSR8510 detection
```

- [ ] **Step 5: 运行 transport 子集回归**

Run:

```bash
uv run pytest tests/unit/transport/ -v --tb=short
```

Expected:

```text
PASS with 0 failures
```

- [ ] **Step 6: 提交最小实现**

```bash
git add pybluehost/transport/usb.py pybluehost/transport/__init__.py tests/unit/transport/test_usb.py
git commit -m "feat(transport): add CSR USB transport detection"
```

---

### Task 3: 做最小硬件冒烟验证

**Files:**
- Verify only: local CSR8510 hardware on this machine

- [ ] **Step 1: 验证 auto_detect 返回 CSRTransport**

Run:

```bash
@'
from pybluehost.transport.usb import USBTransport, CSRUSBTransport
transport = USBTransport.auto_detect()
print(type(transport).__name__)
assert isinstance(transport, CSRUSBTransport)
'@ | uv run python -
```

Expected:

```text
prints CSRUSBTransport and exits 0
```

- [ ] **Step 2: 验证设备可以 open / close**

Run:

```bash
@'
import asyncio
from pybluehost.transport.usb import USBTransport

async def main():
    transport = USBTransport.auto_detect()
    await transport.open()
    print("opened", type(transport).__name__)
    await transport.close()
    print("closed")

asyncio.run(main())
'@ | uv run python -
```

Expected:

```text
prints opened CSRUSBTransport and closed without endpoint discovery failures
```

- [ ] **Step 3: 记录验证结果并提交**

```bash
git status --short
```

Expected:

```text
No uncommitted code changes introduced by smoke verification
```

---

### Task 4: 最终验证

**Files:**
- Verify only

- [ ] **Step 1: 运行最终验证命令**

```bash
uv run pytest tests/unit/transport/test_usb.py tests/unit/transport/ -q
```

- [ ] **Step 2: 检查结果并确认没有回归**

Expected:

```text
All selected tests pass with exit code 0
```

- [ ] **Step 3: 准备收尾说明**

```bash
git log --oneline -5
```

Expected:

```text
contains the CSR test commit and CSR implementation commit
```
