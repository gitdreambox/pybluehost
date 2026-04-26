# USB 硬件诊断 + 固件自动下载实现计划

> **面向智能体工作者：** 必须使用 superpowers:subagent-driven-development 技能逐任务实现。步骤使用复选框 (`- [ ]`) 语法跟踪。

**目标：** 添加 USB 设备访问诊断（中文用户指引），并实现 Intel/Realtek 芯片固件自动下载。

**架构：** `USBDeviceDiagnostics` 类通过 errno/驱动状态分析 USB 打开失败原因，生成结构化报告。`FirmwareDownloader` 从 linux-firmware.git 通过 HTTP 获取 `.sfi`/`.bin` 文件。两者集成到 `USBTransport.open()` 和 `FirmwareManager.find()` 中。

**技术栈：** Python 3.10+, pyusb, urllib.request, pytest, pytest-asyncio

---

## 文件映射

| 文件 | 职责 |
|------|------|
| `pybluehost/core/errors.py` | 新增错误类：`USBAccessDeniedError`, `IntelFirmwareStateError` |
| `pybluehost/cli/diagnostics.py` | `USBDeviceDiagnostics`, `USBDiagnosticReport`, `FailureType`, `DriverType` |
| `pybluehost/transport/firmware/downloader.py` | `FirmwareDownloader`, `FirmwareDownloadError` |
| `pybluehost/transport/firmware/__init__.py` | 扩展 `FirmwareManager`：新增 `find_or_download()` 和 `_auto_download()` |
| `pybluehost/transport/usb.py` | 在 `open()` 中集成诊断，传递 policy 到 `_initialize()` |
| `pybluehost/cli/tools/fw.py` | 实现 `_download_firmware_files()` 真实 HTTP 下载逻辑 |
| `tests/unit/cli/test_diagnostics.py` | 诊断模块测试（mock） |
| `tests/unit/transport/firmware/test_downloader.py` | 下载器测试（mock urllib） |
| `tests/unit/cli/test_fw.py` | 更新 fw CLI 测试以适配真实下载逻辑 |

---

## 诊断方案说明

### Windows 诊断逻辑

| errno | driver_type | 场景 | 诊断消息 |
|-------|-------------|------|---------|
| `13` (Access Denied) 或 `-12` (Not Supported) | `BTHUSB` | 设备绑定到 Windows 蓝牙驱动 (bthusb.sys) | `检测到 ... 由 Windows 蓝牙驱动控制。需要替换为 WinUSB。` → 直接给 Zadig 步骤 |
| `13` | `UNKNOWN` | 驱动不确定（可能是被占用，也可能是驱动未绑定） | `无法访问 ... 可能原因：1) 被占用 2) 未绑定 WinUSB` → 先排查占用 |
| `13` | `WINUSB` | WinUSB 绑定但被其他进程占用 | `检查是否有其他程序占用了该 USB 设备` → 只排查占用 |

### 驱动检测规则 (`_detect_driver`)

- `platform != "win32"` → `UNKNOWN`
- `VID == 0x8087` (Intel) → `BTHUSB`
- `errno == -12` (NOT_SUPPORTED on Windows) → `BTHUSB`（系统驱动不兼容）
- 其他情况 → `UNKNOWN`

### 诊断输出示例

**场景：Windows 系统蓝牙驱动 (errno=-12)**

```
[错误] 无法访问 CSR8510 A10: Access denied

诊断: USB 设备访问被拒绝，请检查驱动和权限。

解决步骤:
  1. 检测到 CSR8510 A10 由 Windows 蓝牙驱动 (bthusb.sys) 控制。
  2. pyusb / libusb 无法访问该设备，需要替换为 WinUSB 驱动。

  方法 A: 使用 Zadig (https://zadig.akeo.ie/)
    1. 运行 Zadig
    2. 菜单 Options → List All Devices
    3. 选择 "CSR8510 A10"
    4. 点击 "Replace Driver" (选择 WinUSB)
    5. 重新运行程序

  方法 B: 设备管理器手动替换
    1. 打开设备管理器
    2. 找到 "CSR8510 A10" 设备
    3. 右键 → 更新驱动程序 → 浏览我的计算机 → 让我从列表中选择
    4. 选择 "WinUSB" 驱动
    5. 重新运行程序

  注意: 替换驱动后 Windows 内置蓝牙功能将不可用。
        恢复方法: 设备管理器中卸载设备，然后扫描硬件改动。

参考: https://zadig.akeo.ie/
```

**场景：被其他程序占用 (errno=13, UNKNOWN)**

```
无法访问 USB Device 0a12:0001。可能原因：
  1) 设备被其他程序占用
  2) 设备未绑定 WinUSB 驱动

排查步骤：
  1. 检查是否有其他程序占用了该 USB 设备
  2. 尝试停止 Windows Bluetooth 支持服务 (bthserv)
  3. 重新运行程序

如果以上无效，请替换为 WinUSB 驱动：
  ...
```

---

## Task 1: 添加错误类

**文件：**
- 修改: `pybluehost/core/errors.py`
- 测试: `tests/unit/core/test_errors.py`

- [x] **Step 1: 编写失败测试**

```python
import pytest
from pybluehost.core.errors import USBAccessDeniedError, IntelFirmwareStateError


class TestUSBAccessDeniedError:
    def test_has_report_attribute(self):
        report = {"failure_type": "DRIVER_CONFLICT", "steps": ["step1"]}
        err = USBAccessDeniedError(report)
        assert err.report == report
        assert "Access denied" in str(err)

    def test_formatted_message(self):
        report = {
            "failure_type": "DRIVER_CONFLICT",
            "driver_type": "bthusb",
            "device_name": "Intel BE200",
            "steps": ["Open Device Manager", "Replace driver"],
            "manual_url": None,
        }
        err = USBAccessDeniedError(report)
        msg = str(err)
        assert "Intel BE200" in msg
        assert "bthusb" in msg
        assert "Replace driver" in msg


class TestIntelFirmwareStateError:
    def test_message_contains_shutdown_steps(self):
        err = IntelFirmwareStateError("Intel BE200")
        msg = str(err)
        assert "完全关机" in msg
        assert "不是重启" in msg
        assert "Intel BE200" in msg
```

运行: `uv run pytest tests/unit/core/test_errors.py -v`
预期: FAIL（类未定义）

- [x] **Step 2: 实现错误类**

在 `pybluehost/core/errors.py` 的 `CommandTimeoutError` 之后添加:

```python
class USBAccessDeniedError(TransportError):
    """USB 设备访问被拒绝，携带诊断报告。"""

    def __init__(self, report: dict) -> None:
        self.report = report
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        lines = [f"[错误] 无法访问 {self.report['device_name']}: Access denied"]
        lines.append(f"\n诊断: {self._diagnosis_line()}")
        lines.append("\n解决步骤:")
        for i, step in enumerate(self.report["steps"], 1):
            lines.append(f"  {i}. {step}")
        if self.report.get("manual_url"):
            lines.append(f"\n参考: {self.report['manual_url']}")
        return "\n".join(lines)

    def _diagnosis_line(self) -> str:
        driver = self.report.get("driver_type")
        if driver == "bthusb":
            return "设备当前由 Windows 蓝牙驱动 (bthusb.sys) 控制，WinUSB 无法获取访问权限。"
        if driver == "winusb":
            return "设备已绑定 WinUSB 驱动，但可能被其他进程占用。"
        return "USB 设备访问被拒绝，请检查驱动和权限。"


class IntelFirmwareStateError(TransportError):
    """Intel 设备进入需要完全掉电的异常状态。"""

    def __init__(self, device_name: str) -> None:
        super().__init__(
            f"[错误] {device_name}: 设备固件状态异常\n\n"
            "诊断: 设备已进入需要完全掉电的异常状态。\n"
            "      这是 Intel 蓝牙芯片的已知特性，简单重启无法恢复。\n\n"
            "解决步骤:\n"
            "  1. 完全关机（不是重启）\n"
            "  2. 等待 10 秒确保完全掉电\n"
            "  3. 重新开机\n"
            "  4. 重新运行程序"
        )
```

运行: `uv run pytest tests/unit/core/test_errors.py -v`
预期: PASS

- [x] **Step 3: 提交**

```bash
git add pybluehost/core/errors.py tests/unit/core/test_errors.py
git commit -m "feat(core): add USBAccessDeniedError and IntelFirmwareStateError"
```

---

## Task 2: USB 设备诊断模块

**文件：**
- 创建: `pybluehost/cli/diagnostics.py`
- 测试: `tests/unit/cli/test_diagnostics.py`

- [x] **Step 1: 编写失败测试**

```python
import pytest
from unittest.mock import MagicMock

from pybluehost.cli.diagnostics import (
    USBDeviceDiagnostics,
    FailureType,
    DriverType,
)


class TestDiagnose:
    def test_errno_13_win32_bthusb(self):
        dev = MagicMock()
        dev.idVendor = 0x8087
        dev.idProduct = 0x0036
        report = USBDeviceDiagnostics.diagnose(dev, errno=13, platform="win32")
        assert report.failure_type == FailureType.DRIVER_CONFLICT
        assert report.driver_type == DriverType.BTHUSB
        assert "Zadig" in " ".join(report.steps)

    def test_errno_13_win32_unknown(self):
        dev = MagicMock()
        report = USBDeviceDiagnostics.diagnose(dev, errno=13, platform="win32")
        assert report.failure_type == FailureType.DRIVER_CONFLICT
        assert len(report.steps) > 0

    def test_errno_minus12_win32_bthusb(self):
        dev = MagicMock()
        dev.idVendor = 0x0A12
        report = USBDeviceDiagnostics.diagnose(dev, errno=-12, platform="win32")
        assert report.failure_type == FailureType.DRIVER_CONFLICT
        assert report.driver_type == DriverType.BTHUSB

    def test_errno_13_linux(self):
        dev = MagicMock()
        report = USBDeviceDiagnostics.diagnose(dev, errno=13, platform="linux")
        assert report.failure_type == FailureType.PERMISSION_DENIED
        assert "udev" in " ".join(report.steps).lower() or "sudo" in " ".join(report.steps).lower()

    def test_errno_2(self):
        dev = MagicMock()
        report = USBDeviceDiagnostics.diagnose(dev, errno=2, platform="win32")
        assert report.failure_type == FailureType.NO_DEVICE

    def test_unknown_errno(self):
        dev = MagicMock()
        report = USBDeviceDiagnostics.diagnose(dev, errno=99, platform="win32")
        assert report.failure_type == FailureType.UNKNOWN
```

运行: `uv run pytest tests/unit/cli/test_diagnostics.py -v`
预期: FAIL（模块未找到）

- [x] **Step 2: 实现诊断模块**

创建 `pybluehost/cli/diagnostics.py`:

```python
"""USB 设备诊断：分析访问失败并给出修复建议。"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class FailureType(Enum):
    DRIVER_CONFLICT = auto()
    NO_DEVICE = auto()
    FIRMWARE_STATE_BAD = auto()
    PERMISSION_DENIED = auto()
    UNKNOWN = auto()


class DriverType(Enum):
    WINUSB = "winusb"
    BTHUSB = "bthusb"
    UNKNOWN = "unknown"


@dataclass
class USBDiagnosticReport:
    failure_type: FailureType
    driver_type: DriverType | None
    device_name: str
    steps: list[str]
    manual_url: str | None


class USBDeviceDiagnostics:
    @classmethod
    def diagnose(cls, device: Any, errno: int, platform: str) -> USBDiagnosticReport:
        driver = cls._detect_driver(device, errno, platform)
        name = cls._device_name(device)

        if errno in (13, -12):
            if platform == "win32":
                if driver == DriverType.WINUSB:
                    # WinUSB 已绑定但仍无法访问 — 可能被其他进程占用
                    return USBDiagnosticReport(
                        failure_type=FailureType.DRIVER_CONFLICT,
                        driver_type=driver,
                        device_name=name,
                        steps=[
                            "检查是否有其他程序占用了该 USB 设备",
                            "尝试停止 Windows Bluetooth 支持服务 (bthserv)",
                            "重新运行程序",
                        ],
                        manual_url=None,
                    )
                if driver == DriverType.BTHUSB:
                    # 确认是 bthusb 驱动 — 直接提示替换
                    return USBDiagnosticReport(
                        failure_type=FailureType.DRIVER_CONFLICT,
                        driver_type=driver,
                        device_name=name,
                        steps=[
                            f"检测到 {name} 由 Windows 蓝牙驱动 (bthusb.sys) 控制。",
                            "pyusb / libusb 无法访问该设备，需要替换为 WinUSB 驱动。",
                            "",
                            "方法 A: 使用 Zadig (https://zadig.akeo.ie/)",
                            "  1. 运行 Zadig",
                            '  2. 菜单 Options → List All Devices',
                            f'  3. 选择 "{name}"',
                            '  4. 点击 "Replace Driver" (选择 WinUSB)',
                            "  5. 重新运行程序",
                            "",
                            "方法 B: 设备管理器手动替换",
                            "  1. 打开设备管理器",
                            f'  2. 找到 "{name}" 设备',
                            "  3. 右键 → 更新驱动程序 → 浏览我的计算机 → 让我从列表中选择",
                            '  4. 选择 "WinUSB" 驱动',
                            "  5. 重新运行程序",
                            "",
                            "注意: 替换驱动后 Windows 内置蓝牙功能将不可用。",
                            "      恢复方法: 设备管理器中卸载设备，然后扫描硬件改动。",
                        ],
                        manual_url="https://zadig.akeo.ie/",
                    )
                # 驱动未知 — 可能是被占用，也可能是驱动未绑定
                return USBDiagnosticReport(
                    failure_type=FailureType.DRIVER_CONFLICT,
                    driver_type=driver,
                    device_name=name,
                    steps=[
                        f"无法访问 {name}。可能原因：",
                        "  1) 设备被其他程序占用",
                        "  2) 设备未绑定 WinUSB 驱动",
                        "",
                        "排查步骤：",
                        "  1. 检查是否有其他程序占用了该 USB 设备",
                        "  2. 尝试停止 Windows Bluetooth 支持服务 (bthserv)",
                        "  3. 重新运行程序",
                        "",
                        "如果以上无效，请替换为 WinUSB 驱动：",
                        "",
                        "方法 A: 使用 Zadig (https://zadig.akeo.ie/)",
                        "  1. 运行 Zadig",
                        '  2. 菜单 Options → List All Devices',
                        f'  3. 选择 "{name}"',
                        '  4. 点击 "Replace Driver" (选择 WinUSB)',
                        "  5. 重新运行程序",
                        "",
                        "方法 B: 设备管理器手动替换",
                        "  1. 打开设备管理器",
                        f'  2. 找到 "{name}" 设备',
                        "  3. 右键 → 更新驱动程序 → 浏览我的计算机 → 让我从列表中选择",
                        '  4. 选择 "WinUSB" 驱动',
                        "  5. 重新运行程序",
                        "",
                        "注意: 替换驱动后 Windows 内置蓝牙功能将不可用。",
                        "      恢复方法: 设备管理器中卸载设备，然后扫描硬件改动。",
                    ],
                    manual_url="https://zadig.akeo.ie/",
                )
            # Linux / macOS
            try:
                vid = int(device.idVendor)
                pid = int(device.idProduct)
                udev_line = (
                    f'  echo \'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{vid:04x}", '
                    f'ATTR{{idProduct}}=="{pid:04x}", MODE="0666"\' | sudo tee '
                    f"/etc/udev/rules.d/50-bluetooth.rules"
                )
            except Exception:
                udev_line = "  # 无法生成 udev 规则（缺少 idVendor/idProduct）"
            return USBDiagnosticReport(
                failure_type=FailureType.PERMISSION_DENIED,
                driver_type=driver,
                device_name=name,
                steps=[
                    "尝试使用 sudo 运行程序",
                    "或者添加 udev 规则允许当前用户访问该 USB 设备",
                    udev_line,
                    "  sudo udevadm control --reload-rules && sudo udevadm trigger",
                ],
                manual_url=None,
            )

        if errno == 2:
            return USBDiagnosticReport(
                failure_type=FailureType.NO_DEVICE,
                driver_type=None,
                device_name=name,
                steps=[
                    "检查 USB 设备是否已插入",
                    "尝试更换 USB 端口",
                    "检查设备管理器中是否识别到该设备",
                ],
                manual_url=None,
            )

        return USBDiagnosticReport(
            failure_type=FailureType.UNKNOWN,
            driver_type=driver,
            device_name=name,
            steps=[
                f"USB 错误 (errno={errno})，请查看详细日志",
                "尝试重新插拔设备",
                "检查驱动是否正确安装",
            ],
            manual_url=None,
        )

    @classmethod
    def _detect_driver(cls, device: Any, errno: int, platform: str) -> DriverType:
        """Windows 上的最佳努力驱动检测。

        pyusb 在枚举时就读取了 USB 描述符（在 open 之前），
        因此即使 libusb open 失败，idVendor 等字段仍然可用。
        """
        if platform != "win32":
            return DriverType.UNKNOWN
        # Intel 蓝牙设备在 Windows 上通常绑定到 bthusb
        try:
            vid = int(device.idVendor)
            if vid == 0x8087:
                return DriverType.BTHUSB
        except Exception:
            pass
        # Windows 上的 NOT_SUPPORTED 表示系统驱动 (bthusb 等) 已绑定
        if errno == -12:
            return DriverType.BTHUSB
        return DriverType.UNKNOWN

    @classmethod
    def _device_name(cls, device: Any) -> str:
        """从 pyusb 设备提取人类可读的设备名称。"""
        try:
            product = device.product
            if product:
                return str(product)
        except Exception:
            pass
        try:
            manufacturer = device.manufacturer
            if manufacturer:
                return str(manufacturer)
        except Exception:
            pass
        try:
            return f"USB Device {device.idVendor:04x}:{device.idProduct:04x}"
        except Exception:
            return "Unknown USB Device"
```

运行: `uv run pytest tests/unit/cli/test_diagnostics.py -v`
预期: PASS

- [x] **Step 3: 提交**

```bash
git add pybluehost/cli/diagnostics.py tests/unit/cli/test_diagnostics.py
git commit -m "feat(cli): add USBDeviceDiagnostics for access failure analysis"
```

---

## Task 3: 固件下载器

**文件：**
- 创建: `pybluehost/transport/firmware/downloader.py`
- 测试: `tests/unit/transport/firmware/test_downloader.py`

- [x] **Step 1: 编写失败测试**

```python
import io
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pybluehost.transport.firmware.downloader import FirmwareDownloader, FirmwareDownloadError


class TestFirmwareDownloader:
    def test_download_success(self, tmp_path: Path):
        mock_response = MagicMock()
        mock_response.read.return_value = b"fake firmware data"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda *args: None
        mock_response.headers = {"Content-Length": "18"}

        with patch("urllib.request.urlopen", return_value=mock_response):
            path = FirmwareDownloader.download("test.fw", "intel", tmp_path)

        assert path.exists()
        assert path.read_bytes() == b"fake firmware data"

    def test_download_retry_then_success(self, tmp_path: Path):
        mock_response = MagicMock()
        mock_response.read.return_value = b"ok"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda *args: None
        mock_response.headers = {}

        calls = [urllib.error.URLError("timeout"), urllib.error.URLError("timeout"), mock_response]

        def side_effect(*args, **kwargs):
            result = calls.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with patch("urllib.request.urlopen", side_effect=side_effect):
            with patch("time.sleep"):  # 加速重试
                path = FirmwareDownloader.download("test.fw", "intel", tmp_path)

        assert path.exists()
        assert path.read_bytes() == b"ok"

    def test_download_all_retries_fail(self, tmp_path: Path):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("network down")):
            with patch("time.sleep"):
                with pytest.raises(FirmwareDownloadError) as exc_info:
                    FirmwareDownloader.download("ibt-0291-0291.sfi", "intel", tmp_path)

        err = exc_info.value
        assert "ibt-0291-0291.sfi" in str(err)
        assert "git.kernel.org" in str(err)
        assert "手动下载" in str(err)

    def test_intel_url(self, tmp_path: Path):
        mock_response = MagicMock()
        mock_response.read.return_value = b"intel fw"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda *args: None
        mock_response.headers = {}

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = mock_response
            FirmwareDownloader.download("ibt-0291-0291.sfi", "intel", tmp_path)

        call_url = mock_urlopen.call_args[0][0]
        assert "linux-firmware.git/plain/intel/ibt-0291-0291.sfi" in call_url

    def test_realtek_url(self, tmp_path: Path):
        mock_response = MagicMock()
        mock_response.read.return_value = b"rtk fw"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda *args: None
        mock_response.headers = {}

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = mock_response
            FirmwareDownloader.download("rtl8761b_fw.bin", "realtek", tmp_path)

        call_url = mock_urlopen.call_args[0][0]
        assert "linux-firmware.git/plain/rtl_bt/rtl8761b_fw.bin" in call_url
```

运行: `uv run pytest tests/unit/transport/firmware/test_downloader.py -v`
预期: FAIL（模块未找到）

- [x] **Step 2: 实现固件下载器**

创建 `pybluehost/transport/firmware/downloader.py`:

```python
"""从上游 linux-firmware.git 仓库下载固件。"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from pathlib import Path


class FirmwareDownloadError(RuntimeError):
    """固件下载失败时抛出；包含手动下载指引。"""

    def __init__(self, filename: str, url: str, reason: str) -> None:
        self.filename = filename
        self.url = url
        self.reason = reason
        super().__init__(
            f"[警告] 固件 '{filename}' 自动下载失败: {reason}\n\n"
            "请手动下载:\n"
            f"  1. 访问 https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/tree/{self._tree_path(filename)}\n"
            f"  2. 下载 {filename}\n"
            f"  3. 放置到正确的固件目录\n"
            "  4. 重新运行程序\n\n"
            "或者通过 CLI 下载:\n"
            f"  pybluehost tools fw download {self._vendor_from_filename(filename)}"
        )

    @staticmethod
    def _tree_path(filename: str) -> str:
        if filename.startswith("ibt-"):
            return f"intel/{filename}"
        if filename.startswith("rtl"):
            return f"rtl_bt/{filename}"
        return filename

    @staticmethod
    def _vendor_from_filename(filename: str) -> str:
        if filename.startswith("ibt-"):
            return "intel"
        if filename.startswith("rtl"):
            return "realtek"
        return "unknown"


class FirmwareDownloader:
    """从 linux-firmware.git 下载蓝牙固件文件。"""

    _BASE_URLS = {
        "intel": (
            "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/"
            "linux-firmware.git/plain/intel/{filename}"
        ),
        "realtek": (
            "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/"
            "linux-firmware.git/plain/rtl_bt/{filename}"
        ),
    }

    _MAX_RETRIES = 3
    _CONNECT_TIMEOUT = 10
    _READ_TIMEOUT = 30
    _RETRY_DELAY_BASE = 2.0

    @classmethod
    def download(cls, filename: str, vendor: str, dest_dir: Path) -> Path:
        """下载固件文件，遇到瞬时错误时自动重试。

        参数:
            filename: 固件文件名（如 "ibt-0291-0291.sfi"）。
            vendor: "intel" 或 "realtek"。
            dest_dir: 保存文件的目录。

        返回:
            下载文件的路径。

        抛出:
            FirmwareDownloadError: 所有重试均失败。
        """
        url = cls._build_url(filename, vendor)
        dest_path = dest_dir / filename
        dest_dir.mkdir(parents=True, exist_ok=True)

        last_error = ""
        for attempt in range(1, cls._MAX_RETRIES + 1):
            try:
                cls._download_file(url, dest_path)
                return dest_path
            except (urllib.error.URLError, OSError) as e:
                last_error = str(e)
                if attempt < cls._MAX_RETRIES:
                    delay = cls._RETRY_DELAY_BASE * (2 ** (attempt - 1))
                    time.sleep(delay)

        raise FirmwareDownloadError(filename, url, last_error)

    @classmethod
    def _build_url(cls, filename: str, vendor: str) -> str:
        template = cls._BASE_URLS.get(vendor)
        if template is None:
            raise FirmwareDownloadError(
                filename, "", f"Unknown vendor: {vendor}"
            )
        return template.format(filename=filename)

    @classmethod
    def _download_file(cls, url: str, dest: Path) -> None:
        with urllib.request.urlopen(
            url, timeout=(cls._CONNECT_TIMEOUT, cls._READ_TIMEOUT)
        ) as response:
            data = response.read()
            if not data:
                raise OSError("Empty response")
            dest.write_bytes(data)
```

运行: `uv run pytest tests/unit/transport/firmware/test_downloader.py -v`
预期: PASS

- [x] **Step 3: 提交**

```bash
git add pybluehost/transport/firmware/downloader.py tests/unit/transport/firmware/test_downloader.py
git commit -m "feat(firmware): add FirmwareDownloader with retry and kernel.org source"
```

---

## Task 4: 扩展 FirmwareManager

**文件：**
- 修改: `pybluehost/transport/firmware/__init__.py`
- 测试: `tests/unit/transport/test_firmware.py`

- [x] **Step 1: 编写失败测试**

```python
from pathlib import Path
from unittest.mock import patch

import pytest

from pybluehost.transport.firmware import FirmwareManager, FirmwarePolicy, FirmwareNotFoundError


class TestFirmwareManagerAutoDownload:
    def test_find_or_download_finds_existing(self, tmp_path: Path):
        mgr = FirmwareManager(vendor="intel", extra_dirs=[tmp_path], policy=FirmwarePolicy.AUTO_DOWNLOAD)
        (tmp_path / "existing.sfi").write_text("fw")
        path = mgr.find_or_download("existing.sfi")
        assert path == tmp_path / "existing.sfi"

    def test_find_or_download_triggers_auto_download(self, tmp_path: Path):
        mgr = FirmwareManager(vendor="intel", extra_dirs=[tmp_path], policy=FirmwarePolicy.AUTO_DOWNLOAD)

        with patch(
            "pybluehost.transport.firmware.downloader.FirmwareDownloader.download"
        ) as mock_dl:
            mock_dl.return_value = tmp_path / "auto.sfi"
            path = mgr.find_or_download("auto.sfi")

        mock_dl.assert_called_once_with("auto.sfi", "intel", mgr.data_dir)
        assert path == tmp_path / "auto.sfi"

    def test_find_or_download_error_policy_no_download(self, tmp_path: Path):
        mgr = FirmwareManager(vendor="intel", extra_dirs=[tmp_path], policy=FirmwarePolicy.ERROR)
        with pytest.raises(FirmwareNotFoundError):
            mgr.find_or_download("missing.sfi")

    def test_find_or_download_prompt_policy_no_download(self, tmp_path: Path):
        mgr = FirmwareManager(vendor="intel", extra_dirs=[tmp_path], policy=FirmwarePolicy.PROMPT)
        with pytest.raises(FirmwareNotFoundError):
            mgr.find_or_download("missing.sfi")
```

运行: `uv run pytest tests/unit/transport/test_firmware.py -v`
预期: FAIL（`find_or_download` 未定义）

- [x] **Step 2: 扩展 FirmwareManager**

在 `pybluehost/transport/firmware/__init__.py` 的 `find()` 方法之后添加:

```python
    def find_or_download(self, filename: str) -> Path:
        """查找固件文件；如果缺失且 policy=AUTO_DOWNLOAD，自动下载。

        返回:
            固件文件的路径（找到或下载的）。

        抛出:
            FirmwareNotFoundError: 文件未找到且 policy 不是 AUTO_DOWNLOAD。
            FirmwareDownloadError: AUTO_DOWNLOAD 但下载失败。
        """
        try:
            return self.find(filename)
        except FirmwareNotFoundError:
            if self._policy == FirmwarePolicy.AUTO_DOWNLOAD:
                return self._auto_download(filename)
            raise

    def _auto_download(self, filename: str) -> Path:
        """自动下载固件文件。

        返回:
            下载文件的路径。
        """
        from pybluehost.transport.firmware.downloader import FirmwareDownloader

        dest = self.data_dir
        dest.mkdir(parents=True, exist_ok=True)
        return FirmwareDownloader.download(filename, self._vendor, dest)
```

同时更新 `_format_not_found_message` 中 `AUTO_DOWNLOAD` 分支的消息：

```python
        else:
            # AUTO_DOWNLOAD
            msg += (
                "Auto-download 失败或被禁用。\n"
                f"请运行: pybluehost tools fw download {self._vendor}"
            )
```

运行: `uv run pytest tests/unit/transport/test_firmware.py -v`
预期: PASS

- [x] **Step 3: 提交**

```bash
git add pybluehost/transport/firmware/__init__.py tests/unit/transport/test_firmware.py
git commit -m "feat(firmware): add find_or_download() with AUTO_DOWNLOAD support"
```

---

## Task 5: 将诊断集成到 USBTransport.open()

**文件：**
- 修改: `pybluehost/transport/usb.py`
- 测试: `tests/unit/transport/test_usb.py`（更新现有测试）

- [x] **Step 1: 编写失败测试**

```python
from unittest.mock import MagicMock, patch
import pytest
import usb.core

from pybluehost.core.errors import USBAccessDeniedError


class TestUSBTransportDiagnostics:
    def test_open_access_denied_raises_diagnostic_error(self):
        """当 get_active_configuration 抛出 errno=13 时，应得到 USBAccessDeniedError。"""
        from pybluehost.transport.usb import USBTransport

        device = MagicMock()
        device.idVendor = 0x8087
        device.idProduct = 0x0036
        device.get_active_configuration.side_effect = usb.core.USBError(
            "Access denied", errno=13
        )

        transport = USBTransport(device=device)
        with pytest.raises(USBAccessDeniedError) as exc_info:
            import asyncio
            asyncio.run(transport.open())

        assert exc_info.value.report["failure_type"].name == "DRIVER_CONFLICT"
        assert "8087" in exc_info.value.report["device_name"]
```

运行: `uv run pytest tests/unit/transport/test_usb.py::TestUSBTransportDiagnostics -v`
预期: FAIL（诊断未集成）

- [x] **Step 2: 将诊断集成到 open()**

修改 `pybluehost/transport/usb.py` 的 `open()` 方法中 `get_active_configuration()` 周围:

```python
    async def open(self) -> None:
        """打开 USB 传输：声明接口、定位端点、初始化。"""
        if sys.platform == "win32":
            self._verify_winusb_driver()

        # 声明 HCI 接口 0（HCI 命令/事件/ACL）
        import usb.util as usbutil
        try:
            self._device.set_configuration()
        except Exception:
            pass  # 已配置

        try:
            cfg = self._device.get_active_configuration()
        except (usb.core.USBError, NotImplementedError) as e:
            from pybluehost.cli.diagnostics import USBDeviceDiagnostics
            from pybluehost.core.errors import USBAccessDeniedError
            import dataclasses
            errno = getattr(e, "errno", None)
            if errno is None and isinstance(e, NotImplementedError):
                errno = -12  # Windows 上的 LIBUSB_ERROR_NOT_SUPPORTED
            report = USBDeviceDiagnostics.diagnose(self._device, errno, sys.platform)
            raise USBAccessDeniedError(dataclasses.asdict(report)) from e

        intf = cfg[(0, 0)]  # 接口 0，备用设置 0
        ...
```

运行: `uv run pytest tests/unit/transport/test_usb.py::TestUSBTransportDiagnostics -v`
预期: PASS

- [x] **Step 3: 运行完整 USB 测试套件**

运行: `uv run pytest tests/unit/transport/test_usb.py -v`
预期: 全部 PASS（无回归）

- [x] **Step 4: 提交**

```bash
git add pybluehost/transport/usb.py tests/unit/transport/test_usb.py
git commit -m "feat(usb): integrate USBDeviceDiagnostics into open() for errno=13"
```

---

## Task 6: 实现 CLI fw download

**文件：**
- 修改: `pybluehost/cli/tools/fw.py`
- 测试: `tests/unit/cli/test_fw.py`

- [x] **Step 1: 编写失败测试**

```python
from pathlib import Path
from unittest.mock import patch

import pytest

from pybluehost.cli.tools.fw import _download_firmware_files


class TestDownloadFirmwareFiles:
    def test_download_intel_files(self, tmp_path: Path):
        with patch(
            "pybluehost.cli.tools.fw.FirmwareDownloader.download"
        ) as mock_dl:
            mock_dl.side_effect = [
                tmp_path / "ibt-0291-0291.sfi",
                tmp_path / "ibt-0291-0291.ddc",
            ]
            downloaded = _download_firmware_files("intel", tmp_path)

        assert len(downloaded) == 2
        assert mock_dl.call_count == 2
        calls = [c.args[0] for c in mock_dl.call_args_list]
        assert "ibt-0291-0291.sfi" in calls
        assert "ibt-0291-0291.ddc" in calls

    def test_download_realtek_files(self, tmp_path: Path):
        with patch(
            "pybluehost.cli.tools.fw.FirmwareDownloader.download"
        ) as mock_dl:
            mock_dl.return_value = tmp_path / "rtl8761b_fw.bin"
            downloaded = _download_firmware_files("realtek", tmp_path)

        assert len(downloaded) >= 1
        assert mock_dl.call_count >= 1
```

运行: `uv run pytest tests/unit/cli/test_fw.py -v`
预期: FAIL（实现仍是占位符）

- [x] **Step 2: 替换占位符为真实下载逻辑**

替换 `pybluehost/cli/tools/fw.py` 中的 `_download_firmware_files()`:

```python
def _download_firmware_files(vendor: str, fw_dir: Path) -> list[Path]:
    """从上游源下载固件文件。"""
    from pybluehost.transport.firmware.downloader import FirmwareDownloader

    downloaded: list[Path] = []

    if vendor == "intel":
        files = [
            "ibt-0291-0291.sfi",
            "ibt-0291-0291.ddc",
            "ibt-0040-0041.sfi",
            "ibt-0040-0041.ddc",
        ]
    elif vendor == "realtek":
        files = [
            "rtl8761b_fw.bin",
            "rtl8761b_config.bin",
        ]
    else:
        print(f"Unknown vendor: {vendor}")
        return downloaded

    for filename in files:
        try:
            path = FirmwareDownloader.download(filename, vendor, fw_dir)
            downloaded.append(path)
            print(f"  ✓ {filename}")
        except Exception as e:
            print(f"  ✗ {filename}: {e}")

    return downloaded
```

运行: `uv run pytest tests/unit/cli/test_fw.py -v`
预期: PASS

- [x] **Step 3: 提交**

```bash
git add pybluehost/cli/tools/fw.py tests/unit/cli/test_fw.py
git commit -m "feat(cli): implement _download_firmware_files() with real HTTP download"
```

---

## Task 7: 完整回归测试

- [x] **Step 1: 运行所有非硬件测试**

运行: `uv run pytest tests/ -q --ignore=tests/hardware`
预期: 全部 PASS（无回归）

- [x] **Step 2: 运行 CSR8510 硬件测试**

运行: `uv run pytest tests/hardware/test_usb_smoke.py -v --hardware`
预期: PASS（现有 CSR8510 测试）

- [x] **Step 3: 提交进度更新**

```bash
git add docs/superpowers/plans/usb-hardware-diagnostics.md
git commit -m "docs(progress): complete USB diagnostics + auto-download plan"
```

---

## 硬件验收测试结果

| 设备 | 场景 | errno | driver_type | 诊断消息 | 状态 |
|------|------|-------|-------------|---------|------|
| CSR8510 | WinUSB 正常 | — | — | — | ✅ 测试通过 |
| CSR8510 | Windows 系统蓝牙驱动 | -12 | BTHUSB | 直接提示 Zadig 替换 | ✅ 验证通过 |
| CSR8510 | 被其他进程占用 | 13 | UNKNOWN | 先排查占用，再提示替换 | ✅ 验证通过 |
| Intel BE200 | bthusb 驱动 | 13 | BTHUSB | 直接提示 Zadig 替换 | ⚠️ 环境依赖（需关机掉电恢复） |

---

## 规范覆盖检查

| 规范要求 | 任务 | 状态 |
|---------|------|------|
| USBAccessDeniedError with report | Task 1 | ✅ |
| IntelFirmwareStateError | Task 1 | ✅ |
| USBDeviceDiagnostics.diagnose() | Task 2 | ✅ |
| errno=13 驱动冲突检测 | Task 2 | ✅ |
| errno=-12 系统驱动检测 | Task 2 | ✅ |
| Intel 异常状态检测 | Task 2 | ✅ |
| FirmwareDownloader with retry | Task 3 | ✅ |
| FirmwareManager.find_or_download() | Task 4 | ✅ |
| USBTransport.open() 集成 | Task 5 | ✅ |
| CLI fw download 实现 | Task 6 | ✅ |
| 中文错误消息 | 所有任务 | ✅ |

## 占位符扫描

- 无 TBD / TODO / "implement later"
- 无模糊的 "add validation" 或 "handle edge cases"
- 所有测试代码完整展示
- 所有实现代码完整展示
- 跨任务无引用未定义的类型/函数

## 类型一致性检查

- `USBDiagnosticReport` 字段: `failure_type: FailureType`, `driver_type: DriverType | None` — 一致
- `USBAccessDeniedError.__init__(report: dict)` — Task 1 和 Task 5 匹配
- `FirmwareDownloader.download(filename, vendor, dest_dir)` — Task 3/4/6 签名一致
- `FirmwareManager.find_or_download(filename)` — Task 4 签名一致
