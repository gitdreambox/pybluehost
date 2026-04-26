# USB Hardware Diagnostics + Firmware Auto-Download Design Spec

> **日期**: 2026-04-26  
> **范围**: `pybluehost/transport/usb.py`, `pybluehost/transport/firmware/`, `pybluehost/core/errors.py`, `pybluehost/cli/tools/fw.py`  
> **相关**: Plan 3a (USB Transport), Plan 3b (Firmware)

---

## 背景与动机

物理 USB 蓝牙适配器在 Windows 上使用时，常遇到三类问题：

1. **Access Denied** — 设备被 Windows 蓝牙驱动 (bthusb) 占用，WinUSB 无法打开
2. **固件未加载** — Intel 设备上电后处于 bootloader 模式，需要 `.sfi` 固件
3. **设备进入异常状态** — Intel BE200 等芯片在固件加载中断后，必须完全掉电（非重启）才能恢复

当前代码缺少：
- 诊断失败原因的工具
- 清晰的错误信息和解决步骤
- 固件自动下载（`AUTO_DOWNLOAD` policy 是 placeholder）

---

## 设计目标

| # | 目标 | 验收标准 |
|---|------|---------|
| 1 | 检测 USB 设备访问失败原因 | `USBAccessDeniedError` 包含诊断报告 |
| 2 | 检测驱动状态 | 能区分 WinUSB / bthusb / 未知驱动 |
| 3 | 检测 Intel 异常固件状态 | 能识别需要完全掉电的状态 |
| 4 | 自动下载固件 | `AUTO_DOWNLOAD` policy 实际工作 |
| 5 | 清晰的错误提示 | 每种失败场景都有中英文解决步骤 |
| 6 | CLI 下载命令可用 | `pybluehost tools fw download intel` 实际下载 |

---

## 架构设计

### 新增模块

```
pybluehost/transport/
├── diagnostics.py          # USB 设备诊断（新增）
├── firmware/
│   ├── __init__.py         # FirmwareManager（已有，扩展）
│   └── downloader.py       # 固件下载器（新增）
```

### 修改模块

```
pybluehost/
├── core/errors.py          # 新增 USBAccessDeniedError, IntelFirmwareStateError
├── transport/usb.py        # open() 集成诊断，_initialize() 集成自动下载
└── cli/tools/fw.py         # 实现 _download_firmware_files()
```

---

## 组件详细设计

### 1. USBDeviceDiagnostics (`transport/diagnostics.py`)

```python
from dataclasses import dataclass
from enum import Enum, auto

class FailureType(Enum):
    DRIVER_CONFLICT = auto()      # bthusb 占用
    NO_DEVICE = auto()            # 设备未连接
    FIRMWARE_STATE_BAD = auto()   # Intel 需完全掉电
    PERMISSION_DENIED = auto()    # 权限不足（非 Windows）
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
    steps: list[str]           # 按优先级排序的解决步骤
    manual_url: str | None     # 手动下载/解决链接

class USBDeviceDiagnostics:
    @classmethod
    def diagnose(cls, device, errno: int, platform: str) -> USBDiagnosticReport:
        """根据 errno 和设备信息生成诊断报告。"""

    @classmethod
    def _detect_driver(cls, device, platform: str) -> DriverType:
        """Windows: 通过设备管理器/注册表检测驱动类型。"""

    @classmethod
    def _is_intel_bad_state(cls, device) -> bool:
        """Intel 特有：设备枚举正常但 claim 后 HCI 命令无响应。"""
```

**诊断逻辑：**

| errno | platform | failure_type | 解决步骤 |
|-------|----------|--------------|---------|
| 13 (Access denied) | win32 | DRIVER_CONFLICT 或 PERMISSION_DENIED | 1. 检测驱动类型 2. 若是 bthusb → 提示替换为 WinUSB 3. 若是 WinUSB → 提示停止蓝牙服务 |
| 13 | !win32 | PERMISSION_DENIED | 提示 sudo / udev 规则 |
| 2 (Entity not found) | any | NO_DEVICE | 提示检查 USB 连接 |
| other | any | UNKNOWN | 通用 USB 错误，提示查看日志 |

**Intel 异常状态检测：**
- 条件：设备能枚举、能 claim、但 `set_configuration()` 或首次 HCI 命令超时
- 原因：固件加载中断后设备进入死锁状态
- 解决：必须完全关机（非重启）后重新开机

---

### 2. 新增错误类 (`core/errors.py`)

```python
class USBAccessDeniedError(TransportError):
    """USB 设备访问被拒绝，包含诊断报告。"""
    def __init__(self, report: "USBDiagnosticReport"):
        self.report = report
        super().__init__(self._format_message())

class IntelFirmwareStateError(TransportError):
    """Intel 设备进入需要完全掉电的异常状态。"""
    def __init__(self, device_name: str):
        super().__init__(
            f"{device_name}: 设备固件状态异常，需要完全关机后重新开机。"
            f"\n解决步骤:\n"
            f"  1. 完全关机（不是重启）\n"
            f"  2. 等待 10 秒确保完全掉电\n"
            f"  3. 重新开机\n"
            f"  4. 重新运行程序"
        )
```

---

### 3. FirmwareDownloader (`transport/firmware/downloader.py`)

```python
import urllib.request
from pathlib import Path

class FirmwareDownloadError(RuntimeError):
    """固件下载失败，包含手动下载信息。"""
    def __init__(self, filename: str, url: str, reason: str):
        self.filename = filename
        self.url = url
        self.reason = reason
        super().__init__(
            f"固件 '{filename}' 下载失败: {reason}\n"
            f"请手动下载: {url}\n"
            f"放置到: {FirmwareManager('intel').data_dir}"
        )

class FirmwareDownloader:
    _INTEL_BASE = (
        "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/intel/"
    )
    _REALTEK_BASE = (
        "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/rtl_bt/"
    )

    @classmethod
    def download(cls, filename: str, vendor: str, dest_dir: Path) -> Path:
        """下载固件文件到 dest_dir。
        
        Args:
            filename: 固件文件名 (如 "ibt-0291-0291.sfi")
            vendor: "intel" 或 "realtek"
            dest_dir: 目标目录
            
        Returns:
            本地文件路径
            
        Raises:
            FirmwareDownloadError: 下载失败
        """

    @classmethod
    def _download_file(cls, url: str, dest: Path) -> None:
        """使用 urllib 下载文件，带重试和进度回调。"""
```

**下载策略：**
- 源：Linux firmware git 的 raw plain 视图
- 重试：最多 3 次，指数退避
- 超时：连接 10s，读取 30s
- 校验：文件大小 > 0（暂不做 checksum）

---

### 4. FirmwareManager 扩展 (`transport/firmware/__init__.py`)

```python
class FirmwareManager:
    def find_or_download(self, filename: str) -> Path:
        """查找固件，找不到时若 policy=AUTO_DOWNLOAD 则自动下载。
        
        Returns:
            固件路径
            
        Raises:
            FirmwareNotFoundError: 找不到且 policy!=AUTO_DOWNLOAD
            FirmwareDownloadError: AUTO_DOWNLOAD 但下载失败
        """
        try:
            return self.find(filename)
        except FirmwareNotFoundError:
            if self._policy == FirmwarePolicy.AUTO_DOWNLOAD:
                return self._auto_download(filename)
            raise

    def _auto_download(self, filename: str) -> Path:
        """自动下载固件并返回路径。"""
        from .downloader import FirmwareDownloader
        dest = self.data_dir
        dest.mkdir(parents=True, exist_ok=True)
        return FirmwareDownloader.download(filename, self._vendor, dest)
```

---

### 5. USBTransport 集成 (`transport/usb.py`)

**open() 诊断集成：**

```python
async def open(self) -> None:
    try:
        # 现有配置逻辑...
        cfg = self._device.get_active_configuration()
    except usb.core.USBError as e:
        from pybluehost.transport.diagnostics import USBDeviceDiagnostics
        report = USBDeviceDiagnostics.diagnose(self._device, e.errno, sys.platform)
        from pybluehost.core.errors import USBAccessDeniedError
        raise USBAccessDeniedError(report) from e
    
    # 现有逻辑...
    
    # Intel 特有：检测异常固件状态
    if isinstance(self, IntelUSBTransport) and self._chip_info:
        # _initialize() 会处理，但如果 open 后立刻无响应...
```

**close() 增强：**
- 保持不变（已修复）

---

### 6. CLI fw download 实现 (`cli/tools/fw.py`)

```python
def _download_firmware_files(vendor: str, fw_dir: Path) -> list[Path]:
    """实际下载逻辑：根据 vendor 下载常用固件文件列表。"""
    from pybluehost.transport.firmware.downloader import FirmwareDownloader
    
    downloaded = []
    
    if vendor == "intel":
        # Intel BE200 固件（当前测试设备）
        files = ["ibt-0291-0291.sfi", "ibt-0291-0291.ddc"]
        for f in files:
            try:
                path = FirmwareDownloader.download(f, vendor, fw_dir)
                downloaded.append(path)
                print(f"  ✓ {f}")
            except Exception as e:
                print(f"  ✗ {f}: {e}")
    
    elif vendor == "realtek":
        # Realtek 常用固件（示例）
        files = ["rtl8761b_fw.bin", "rtl8761b_config.bin"]
        for f in files:
            try:
                path = FirmwareDownloader.download(f, vendor, fw_dir)
                downloaded.append(path)
                print(f"  ✓ {f}")
            except Exception as e:
                print(f"  ✗ {f}: {e}")
    
    return downloaded
```

---

## 错误提示文本规范

### USBAccessDeniedError（驱动冲突）

```
[错误] 无法访问 {device_name}: Access denied

诊断: 设备当前由 {driver_type} 驱动控制，WinUSB 无法获取访问权限。

解决步骤:
  1. 打开设备管理器
  2. 找到 "Intel Wireless Bluetooth" 或 "CSR Bluetooth Radio"
  3. 右键 → 更新驱动程序 → 浏览我的计算机 → 让我从列表中选择
  4. 选择 "WinUSB" 驱动
  5. 重新运行程序

或者使用 Zadig (https://zadig.akeo.ie/):
  1. 运行 Zadig
  2. 菜单 Options → List All Devices
  3. 选择 "Intel Bluetooth" 或 "CSR8510"
  4. 点击 "Replace Driver" (选择 WinUSB)
  5. 重新运行程序

注意: 替换驱动后 Windows 内置蓝牙功能将不可用。
      恢复方法: 设备管理器中卸载设备，然后扫描硬件改动。
```

### IntelFirmwareStateError

```
[错误] {device_name}: 设备固件状态异常

诊断: 设备已进入需要完全掉电的异常状态。
      这是 Intel 蓝牙芯片的已知特性，简单重启无法恢复。

解决步骤:
  1. 完全关机（不是重启）
  2. 等待 10 秒确保完全掉电
  3. 重新开机
  4. 重新运行程序
```

### FirmwareDownloadError

```
[警告] 固件 {filename} 自动下载失败: {reason}

请手动下载:
  1. 访问 https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/tree/intel/
  2. 下载 {filename}
  3. 放置到: {dest_dir}
  4. 重新运行程序

或者通过 CLI 下载:
  pybluehost tools fw download {vendor}
```

---

## 测试计划

| 测试 | 类型 | 内容 |
|------|------|------|
| test_diagnostics_driver_conflict | 单元 | 模拟 errno=13，验证报告包含驱动替换步骤 |
| test_diagnostics_intel_bad_state | 单元 | 模拟 Intel 设备 claim 后无响应，验证 IntelFirmwareStateError |
| test_downloader_success | 单元 | Mock urllib，验证下载文件写入正确位置 |
| test_downloader_retry | 单元 | Mock urllib 前两次失败，验证第3次成功 |
| test_downloader_fail | 单元 | Mock urllib 全部失败，验证 FirmwareDownloadError 包含手动 URL |
| test_firmware_manager_auto_download | 单元 | policy=AUTO_DOWNLOAD，验证找不到时自动调用 downloader |
| test_usb_transport_access_denied | 单元 | Mock open() 抛 errno=13，验证 USBAccessDeniedError |
| test_cli_fw_download_intel | 集成 | `pybluehost tools fw download intel` 实际下载 (可选，网络依赖) |

---

## 实现顺序

1. `core/errors.py` — 新增错误类（无依赖）
2. `transport/firmware/downloader.py` — 固件下载器（无依赖）
3. `transport/diagnostics.py` — USB 诊断（依赖 errors）
4. `transport/firmware/__init__.py` — 扩展 FirmwareManager（依赖 downloader）
5. `transport/usb.py` — 集成诊断到 open()（依赖 diagnostics, errors）
6. `cli/tools/fw.py` — 实现 CLI 下载（依赖 downloader）
7. 测试文件（按上述测试计划）

---

## 风险与限制

| 风险 | 缓解措施 |
|------|---------|
| Intel BE200 在 WinUSB 下 bootloader 不响应 | 已在设计中包含 `IntelFirmwareStateError` 提示完全关机 |
| Linux firmware git 下载慢/失败 | 3 次重试 + 清晰的降级提示 |
| Windows 驱动检测不可靠 | 通过多个信号交叉验证（注册表 + 错误码 + 设备状态） |
| urllib 在受限网络环境不可用 | 提供手动下载链接和 CLI 备用方案 |
