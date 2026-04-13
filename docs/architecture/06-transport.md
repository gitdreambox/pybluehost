# 第六节：Transport 层详细设计

## 6.1 Transport 类继承体系

```
Transport (ABC)
├── UARTTransport          # H4 framing over serial (pyserial)
├── USBTransport           # USB HCI via pyusb (WinUSB / libusb)
│   ├── IntelUSBTransport  # Intel 芯片固件加载 + 特殊初始化
│   └── RealtekUSBTransport # Realtek 芯片固件加载 + 特殊初始化
├── HCIUserChannelTransport # Linux 专用：hci_user_channel socket
├── TCPTransport           # TCP socket
├── UDPTransport           # UDP socket
├── LoopbackTransport      # 纯软件回环，接 VirtualController
└── BtsnoopTransport       # 读取 btsnoop 文件，按时间戳回放
```

`IntelUSBTransport` 和 `RealtekUSBTransport` 是 `USBTransport` 的子类，仅覆写 `_initialize()` 方法来处理固件加载。用户不直接选择——`USBTransport.auto_detect()` 根据 VID/PID 自动返回正确的子类实例。

## 6.2 Transport ABC

```python
class Transport(ABC):
    """所有 transport 的基类"""

    @abstractmethod
    async def open(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def send(self, data: bytes) -> None: ...

    def set_sink(self, sink: TransportSink) -> None: ...

    async def reset(self) -> None:
        """断线重连。默认实现：close + open"""
        await self.close()
        await self.open()

    @property
    def is_open(self) -> bool: ...

    @property
    def info(self) -> TransportInfo: ...

@dataclass(frozen=True)
class TransportInfo:
    type: str              # "uart" | "usb" | "tcp" | ...
    description: str       # 人读描述 "Intel AX210 on USB 0x8087:0x0032"
    platform: str          # "windows" | "linux"
    details: dict[str, Any]  # 具体参数（baudrate, vid/pid, host/port 等）
```

## 6.3 USB Transport 与芯片自动识别

### VID/PID 注册表

```python
@dataclass(frozen=True)
class ChipInfo:
    vendor: str            # "intel" | "realtek"
    name: str              # "AX210" | "RTL8852BE"
    vid: int
    pid: int
    firmware_pattern: str  # 固件文件名模式
    transport_class: type  # IntelUSBTransport | RealtekUSBTransport

KNOWN_CHIPS: list[ChipInfo] = [
    # Intel
    ChipInfo("intel", "AX200",  0x8087, 0x0029, "ibt-20-*", IntelUSBTransport),
    ChipInfo("intel", "AX201",  0x8087, 0x0026, "ibt-20-*", IntelUSBTransport),
    ChipInfo("intel", "AX210",  0x8087, 0x0032, "ibt-0040-*", IntelUSBTransport),
    ChipInfo("intel", "AX211",  0x8087, 0x0033, "ibt-0040-*", IntelUSBTransport),
    ChipInfo("intel", "AC9560", 0x8087, 0x0025, "ibt-18-*", IntelUSBTransport),
    ChipInfo("intel", "AC8265", 0x8087, 0x0a2b, "ibt-12-*", IntelUSBTransport),
    # Realtek
    ChipInfo("realtek", "RTL8761B",  0x0BDA, 0x8771, "rtl8761b_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852AE", 0x0BDA, 0x2852, "rtl8852au_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852BE", 0x0BDA, 0x887B, "rtl8852bu_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852CE", 0x0BDA, 0x4853, "rtl8852cu_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8723DE", 0x0BDA, 0xB009, "rtl8723d_fw", RealtekUSBTransport),
    # ... 可扩展
]
```

### 自动检测流程

```python
class USBTransport(Transport):
    @classmethod
    def auto_detect(cls) -> "USBTransport":
        """扫描系统 USB 设备，匹配已知蓝牙芯片，返回对应子类实例"""
        # 1. pyusb 枚举所有 USB 设备
        # 2. 遍历 KNOWN_CHIPS，匹配 VID/PID
        # 3. 找到第一个匹配 → 返回 chip_info.transport_class(device, chip_info)
        # 4. 找不到 → 尝试 bDeviceClass=0xE0 (Wireless Controller)
        #             bDeviceSubClass=0x01 (RF Controller)
        #             bDeviceProtocol=0x01 (Bluetooth)
        #             作为 generic USBTransport 返回
        # 5. 仍找不到 → 抛出 NoBluetoothDeviceError（附带已扫描的 USB 设备列表）
```

### USB HCI 端点映射

```
Endpoint          传输类型     方向    HCI 数据类型
─────────         ─────────   ────    ────────────
Control (EP0)     Control     OUT     HCI Command
Interrupt IN      Interrupt   IN      HCI Event
Bulk OUT          Bulk        OUT     HCI ACL Data (host → controller)
Bulk IN           Bulk        IN      HCI ACL Data (controller → host)
Isoch OUT         Isochronous OUT     HCI SCO Data (host → controller)
Isoch IN          Isochronous IN      HCI SCO Data (controller → host)
```

```python
class USBTransport(Transport):
    async def open(self) -> None:
        # 1. 获取 USB device handle
        # 2. 在 Windows 上验证 WinUSB 驱动已绑定
        # 3. Claim interface 0 (BT HCI)，interface 1 (SCO，可选)
        # 4. 定位各 endpoint
        # 5. 调用 _initialize()（子类覆写做固件加载）
        # 6. 启动 3 个并行读取 task:
        #    - _read_interrupt() → HCI Event
        #    - _read_bulk_in()   → HCI ACL Data
        #    - _read_isoch_in()  → HCI SCO Data（可选）

    async def send(self, data: bytes) -> None:
        packet_type = data[0]
        match packet_type:
            case 0x01:  # HCI Command → Control transfer
                await self._control_out(data[1:])
            case 0x02:  # ACL Data → Bulk OUT
                await self._bulk_out(data[1:])
            case 0x03:  # SCO Data → Isochronous OUT
                await self._isoch_out(data[1:])

    async def _initialize(self) -> None:
        """子类覆写。默认无操作。"""
        pass
```

## 6.4 固件管理系统

### 固件查找优先级

```
1. 环境变量（最高优先级，排他）
   PYBLUEHOST_INTEL_FW_DIR / PYBLUEHOST_RTK_FW_DIR

2. 项目数据目录（跨平台）
   Windows: %APPDATA%\pybluehost\firmware\{intel|realtek}\
   Linux:   ~/.local/share/pybluehost/firmware/{intel|realtek}/
   macOS:   ~/Library/Application Support/pybluehost/firmware/{intel|realtek}/

3. 包内置目录
   {pybluehost_package}/drivers/intel_fw/
   {pybluehost_package}/drivers/rtk_fw/

4. 系统固件目录（Linux only）
   /lib/firmware/intel/
   /lib/firmware/rtl_bt/

5. 当前工作目录（最终兜底）
```

### 固件缺失处理（三级策略）

```python
class FirmwarePolicy(Enum):
    AUTO_DOWNLOAD = "auto"    # 自动从网上下载（默认）
    PROMPT = "prompt"         # 提示用户手动下载，给出完整指引
    ERROR = "error"           # 直接报错

Stack.from_usb(firmware_policy=FirmwarePolicy.AUTO_DOWNLOAD)
```

**Level 1 — AUTO_DOWNLOAD（默认）：**

```
固件查找失败
    │
    ▼
自动从 linux-firmware 仓库下载
    源: https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/
    Intel: intel/ibt-{hw}-{fw}.sfi + .ddc
    Realtek: rtl_bt/rtl{chip}_fw.bin + rtl{chip}_config.bin
    │
    ▼
保存到项目数据目录（上述优先级 2）
    │
    ▼
验证完整性（文件大小 + magic signature）
    │
    ▼
继续初始化
```

**Level 2 — PROMPT（网络不可用或用户选择）：**

```
FirmwareNotFoundError:
  Intel AX210 (0x8087:0x0032) 需要固件文件: ibt-0040-0041.sfi

  请通过以下任一方式获取固件：

  方式一：使用内置工具自动下载
    pybluehost fw download intel

  方式二：手动下载
    URL: https://git.kernel.org/pub/scm/linux/.../intel/ibt-0040-0041.sfi
    存放到: C:\Users\xxx\AppData\Roaming\pybluehost\firmware\intel\

  方式三：从 Linux 系统复制
    Linux 固件路径: /lib/firmware/intel/ibt-0040-0041.sfi

  方式四：设置环境变量指向已有固件目录
    set PYBLUEHOST_INTEL_FW_DIR=D:\my_firmware\intel
```

**Level 3 — ERROR：** 直接抛出 `FirmwareNotFoundError`，不做额外引导。

### 下载源

```python
FIRMWARE_SOURCES: dict[str, list[str]] = {
    "intel": [
        "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/intel",
    ],
    "realtek": [
        "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/rtl_bt",
        "https://github.com/Realtek-OpenSource/android_hardware_realtek/raw/rtk1395/bt/rtkbt/Firmware/BT",
    ],
}
```

### CLI 工具

```bash
pybluehost fw download intel          # 下载所有已知 Intel 固件
pybluehost fw download realtek        # 下载所有已知 Realtek 固件
pybluehost fw download intel --name ibt-0040-0041  # 指定固件
pybluehost fw list                    # 查看已安装固件
pybluehost fw info ibt-0040-0041.sfi # 查看固件信息
pybluehost fw auto                   # 检测当前芯片并下载对应固件
pybluehost fw clean                  # 清理已下载固件
```

## 6.5 Intel 固件加载

```
IntelUSBTransport._initialize() 流程:

1. HCI_Intel_Read_Version（vendor command 0xFC05）
   → 获取 hw_variant, hw_revision, fw_variant, fw_build_type

2. 查找固件文件（按 5.4 优先级），找不到 → 按 FirmwarePolicy 处理

3. HCI_Intel_Enter_Mfg_Mode（进入制造模式）

4. 分片发送固件（每片 ~252 bytes，通过 vendor command）
   → 每片等待 Command Complete event 确认

5. HCI_Intel_Reset（vendor reset）
   → 等待 Vendor Specific Event 确认固件启动

6. HCI_Intel_Read_Version（验证固件版本）
```

## 6.6 Realtek 固件加载

```
RealtekUSBTransport._initialize() 流程:

1. HCI_Realtek_Read_ROM_Version（vendor command 0xFC6D）
   → 获取 lmp_subversion, hci_revision, rom_version

2. 匹配固件和配置文件，找不到 → 按 FirmwarePolicy 处理

3. 下载固件（HCI vendor command 0xFC20 分片下载）

4. 下载配置文件（如有）

5. HCI_Reset → 等待 Command Complete → 验证 lmp_subversion 更新
```

## 6.7 平台差异处理

### Windows WinUSB

```python
class USBTransport(Transport):
    def _verify_winusb_driver(self) -> None:
        """检查目标设备是否绑定到 WinUSB 驱动"""
        # 如果仍绑定在 Microsoft Bluetooth driver：
        #   → 抛出 WinUSBDriverError，消息包含：
        #     1. 当前驱动名
        #     2. 用 Zadig 切换到 WinUSB 的步骤
        #     3. 切换后 Windows 原生蓝牙将不可用的警告
```

### Linux hci_user_channel

```python
class HCIUserChannelTransport(Transport):
    """Linux 专用：通过内核 hci_user_channel socket 直接访问 HCI"""

    def __init__(self, hci_index: int = 0) -> None: ...

    async def open(self) -> None:
        # 1. down the interface: hciconfig hci{index} down
        # 2. socket(AF_BLUETOOTH, SOCK_RAW, BTPROTO_HCI)
        # 3. bind(hci_index, HCI_CHANNEL_USER)
        # → 独占 HCI，BlueZ 放手
```

`Stack.from_usb()` 在 Linux 上优先尝试 `HCIUserChannelTransport`。

## 6.8 其他 Transport

### UART Transport

```python
class UARTTransport(Transport):
    """H4 framing over serial port（pyserial-asyncio）"""
    # H4 状态机：读 indicator → 读 header → 解析 length → 读 payload
```

### TCP / UDP Transport

```python
class TCPTransport(Transport):
    """H4 framing over TCP stream"""

class UDPTransport(Transport):
    """每个 UDP datagram = 一个完整 HCI packet"""
```

### Btsnoop Transport（回放模式）

```python
class BtsnoopTransport(Transport):
    """读取 btsnoop 文件，按原始时间间隔回放 HCI 包"""
    # realtime=True:  按原始 timestamp 间隔 asyncio.sleep
    # realtime=False: 尽快投递（快速回归测试）
    # send() → 静默丢弃（回放模式下 host → controller 方向被忽略）
```

### Loopback Transport

```python
class LoopbackTransport(Transport):
    """纯软件回环，发出的数据直接交给 VirtualController 处理"""
```

## 6.9 断线重连策略

```python
class ReconnectPolicy:
    NONE = "none"
    IMMEDIATE = "immediate"
    EXPONENTIAL = "exponential"  # 1s, 2s, 4s, ... max 60s

class ReconnectConfig:
    policy: ReconnectPolicy = ReconnectPolicy.NONE
    max_attempts: int = 5
    base_delay: float = 1.0
    max_delay: float = 60.0

Stack.from_uart("/dev/ttyUSB0",
    reconnect=ReconnectConfig(policy=ReconnectPolicy.EXPONENTIAL))
```
