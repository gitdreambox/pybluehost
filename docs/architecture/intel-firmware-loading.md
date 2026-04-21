# Intel Bluetooth USB 固件加载协议

> **PyBlueHost** — Intel BE200 / AX210 / AX211 新一代平台固件加载实现  
> 经 Intel BE200 (VID=0x8087, PID=0x0036) 实物硬件验证通过  
> 参考实现：[Google Bumble `bumble/drivers/intel.py`](https://github.com/google/bumble)

---

## 目录

1. [协议概述](#1-协议概述)
2. [平台检测：Legacy vs New-Gen](#2-平台检测legacy-vs-new-gen)
3. [TLV 协议详解](#3-tlv-协议详解)
4. [固件文件名计算](#4-固件文件名计算)
5. [Secure Boot Engine：RSA vs ECDSA](#5-secure-boot-enginersa-vs-ecdsa)
6. [固件下载序列](#6-固件下载序列)
7. [USB 端点路由（关键发现）](#7-usb-端点路由关键发现)
8. [Intel Reset 与启动确认](#8-intel-reset-与启动确认)
9. [硬件验证结果](#9-硬件验证结果)
10. [调试经验与陷阱](#10-调试经验与陷阱)

---

## 1. 协议概述

Intel Bluetooth USB 控制器在上电时处于 **Bootloader 模式**（无固件），需要 Host 通过 USB 加载固件后才能进入 **Operational 模式**。

Intel 有两代协议：

| 协议 | 适用芯片 | hw_variant | 检测方式 |
|------|---------|------------|---------|
| **Legacy** | AX200, AX201, AC9560, AC8265 | < 0x17 | `0xFC05` 无参数，固定格式响应 |
| **New-Gen (TLV)** | AX210, AX211, **BE200** | ≥ 0x17 | `0xFC05` + 参数 `0xFF`，TLV 格式响应 |

### 自动检测流程

```
_initialize()
  ├─ 发送 Read Version V2 (0xFC05 + param 0xFF)
  │   ├─ status=0x00 且响应 >10 字节 → New-Gen 路径
  │   └─ status≠0x00 (如 0x12 Unknown Command) → Legacy 路径
  ├─ New-Gen: _initialize_newgen(tlv)
  └─ Legacy:  _initialize_legacy(hw_variant, fw_variant)
```

---

## 2. 平台检测：Legacy vs New-Gen

### Legacy 检测

```
HCI Command: OGF=0x3F OCF=0x05, 无参数
→ Command Complete (0x0E):
  [0] event_code = 0x0E
  [1] param_total_len
  [2] num_hci_cmds
  [3:5] opcode echo (0xFC05 LE)
  [5] status
  [6] hw_platform
  [7] hw_variant      ← 判断平台
  [8] hw_revision
  [9] fw_variant      ← 0x03=operational, 0x06=bootloader
```

### New-Gen 检测 (TLV)

```
HCI Command: OGF=0x3F OCF=0x05, param_len=1, param=0xFF
→ Command Complete (0x0E):
  [0:6] 标准 Command Complete 头
  [6:]  TLV 数据流（Type-Length-Value 序列）
```

---

## 3. TLV 协议详解

### TLV 编码格式

```
+------+--------+-------------------+
| Type | Length | Value (Length 字节) |
| 1B   | 1B     | N bytes            |
+------+--------+-------------------+
```

### 关键 TLV 字段

| Type | 名称 | 大小 | 说明 |
|------|------|------|------|
| `0x10` | CNVI_TOP | 4B | CNVi 顶层版本（用于计算固件名） |
| `0x11` | CNVR_TOP | 4B | CNVr 顶层版本（用于计算固件名） |
| `0x12` | CNVI_BT | 4B | CNVi 蓝牙版本 |
| `0x17` | USB_VENDOR_ID | 2B | USB VID |
| `0x18` | USB_PRODUCT_ID | 2B | USB PID |
| `0x1C` | **IMAGE_TYPE** | 1B | **0x01=Bootloader, 0x03=Operational** |
| `0x1D` | TIME_STAMP | 2B | 构建时间戳 |
| `0x27` | SECURE_BOOT | 1B | 安全启动标志 |
| `0x2F` | **SBE_TYPE** | 1B | **Secure Boot Engine: 0x00=RSA, 0x01=ECDSA** |
| `0x30` | OTP_BDADDR | 6B | OTP 蓝牙地址 |

### 实际 BE200 TLV 响应示例

```
0e 5e 20 05 fc 00    ← Command Complete, status=0x00
10 04 10 19 00 02    ← CNVI_TOP = 0x02001910
11 04 10 19 00 02    ← CNVR_TOP = 0x02001910
12 04 00 37 1c 00    ← CNVI_BT  = 0x001C3700
17 02 87 80          ← USB VID  = 0x8087
18 02 36 00          ← USB PID  = 0x0036
1c 01 01             ← IMAGE_TYPE = 0x01 (BOOTLOADER)
2f 01 01             ← SBE_TYPE = 0x01 (ECDSA)
30 06 5f 5f 6d 9a 8a c8  ← BD_ADDR
```

---

## 4. 固件文件名计算

### 算法（来自 Linux kernel v6.12 `btintel.h`）

```python
def _compute_fw_name(cnvi_top: int, cnvr_top: int) -> str:
    def pack(val: int) -> int:
        t = val & 0x00000FFF           # TYPE: 低 12 位
        s = (val & 0x0F000000) >> 24   # STEP: 第 24-27 位
        v = (t << 4) | s
        return ((v >> 8) & 0xFF) | ((v & 0xFF) << 8)  # swab16

    return f"ibt-{pack(cnvi_top):04x}-{pack(cnvr_top):04x}"
```

### BE200 计算示例

```
cnvi_top = 0x02001910
  TYPE = 0x910, STEP = 0x2
  (0x910 << 4) | 0x2 = 0x9102
  swab16(0x9102) = 0x0291

cnvr_top = 0x02001910  (同上)

固件名: ibt-0291-0291.sfi
```

> **注意**：早期实现错误地使用了 `(val & 0xF000) >> 12` 作为 STEP 掩码，导致计算出 `ibt-0191-0191.sfi`（不存在）。正确掩码为 `(val & 0x0F000000) >> 24`。

---

## 5. Secure Boot Engine：RSA vs ECDSA

TLV 字段 `0x2F` (SBE_TYPE) 决定固件文件的内部布局：

### RSA 布局 (SBE_TYPE = 0x00)

```
Offset 0     ┌──────────────────┐
             │  CSS Header      │ 128 字节  → type=0x00
Offset 128   ├──────────────────┤
             │  PKI Key (RSA)   │ 256 字节  → type=0x03
Offset 384   ├──────────────────┤
             │  RSA Signature   │ 256 字节  → type=0x02  (注意偏移 388)
Offset 644   ├──────────────────┤
             │  ... padding ... │
Offset 964   ├──────────────────┤
             │  HCI Commands    │ 剩余全部  → type=0x01
             └──────────────────┘
```

### ECDSA 布局 (SBE_TYPE = 0x01) — BE200 使用此布局

```
Offset 0     ┌──────────────────┐
             │  Firmware Header │ 644 字节（不发送到设备）
Offset 644   ├──────────────────┤
             │  CSS Header      │ 128 字节  → type=0x00
Offset 772   ├──────────────────┤
             │  PKI Key (ECDSA) │  96 字节  → type=0x03
Offset 868   ├──────────────────┤
             │  ECDSA Signature │  96 字节  → type=0x02
Offset 964   ├──────────────────┤
             │  HCI Commands    │ 剩余全部  → type=0x01
             └──────────────────┘
```

### BootParams 数据结构

```python
@dataclass(frozen=True)
class _BootParams:
    css_offset: int      # CSS 头在固件文件中的偏移
    css_size: int        # CSS 头大小
    pki_offset: int      # PKI 密钥偏移
    pki_size: int        # PKI 密钥大小
    sig_offset: int      # 签名偏移
    sig_size: int        # 签名大小
    write_offset: int    # Payload 起始偏移

_BOOT_PARAMS_RSA   = _BootParams(  0, 128, 128, 256, 388, 256, 964)
_BOOT_PARAMS_ECDSA = _BootParams(644, 128, 772,  96, 868,  96, 964)
```

> **这是导致第一次固件加载失败的根本原因**：我们最初使用 RSA 偏移（CSS 在 offset 0）发送数据到 ECDSA 设备，导致 bootloader 返回 status=0x1F (Unspecified Error)。

---

## 6. 固件下载序列

### 完整 New-Gen 固件加载流程

```
Host                                              Controller (Bootloader)
  │                                                       │
  │  ① HCI_Intel_Read_Version (0xFC05 + 0xFF)             │
  │──────────────────────────────────────────────────────→│
  │                          Command Complete + TLV       │
  │←──────────────────────────────────────────────────────│
  │  (解析 image_type=0x01, sbe_type, cnvi/cnvr)          │
  │                                                       │
  │  ② Secure Send CSS Header (type=0x00)                 │
  │──────────────────────────────────────────────────────→│
  │                          Command Complete (Bulk IN)   │
  │←──────────────────────────────────────────────────────│
  │                                                       │
  │  ③ Secure Send PKI Key (type=0x03)                    │
  │──────────────────────────────────────────────────────→│
  │                          Command Complete (Bulk IN)   │
  │←──────────────────────────────────────────────────────│
  │                                                       │
  │  ④ Secure Send Signature (type=0x02)                  │
  │──────────────────────────────────────────────────────→│
  │                          Command Complete (Bulk IN)   │
  │←──────────────────────────────────────────────────────│
  │                                                       │
  │  ⑤ Secure Send Payload (type=0x01) × N chunks        │
  │  (4 字节对齐，HCI 命令边界分割，≤252B/chunk)            │
  │──────────────────────────────────────────────────────→│
  │                          Command Complete × N         │
  │←──────────────────────────────────────────────────────│
  │                                                       │
  │                          ⑥ Vendor Event (0xFF)        │
  │                          sub_type=0x06 下载完成        │
  │←──────────────────────────────────────────────────────│
  │                                                       │
  │  ⑦ Intel Reset (0xFC01 + boot_address)                │
  │──────────────────────────────────────────────────────→│
  │                          (设备重启)                    │
  │                                                       │
  │                          ⑧ Vendor Event (0xFF)        │
  │                          sub_type=0x02 启动完成        │
  │←──────────────────────────────────────────────────────│
  │                                                       │
  │  设备进入 Operational 模式 ✓                            │
```

### Secure Send (0xFC09) 命令格式

```
HCI Command via USB Control Transfer (EP0):
  bmRequestType = 0x20 (Class | Interface | Host-to-Device)
  bRequest      = 0x00
  wValue        = 0x0000
  wIndex        = 0x0000

  Data:
    [0:2]   Opcode = 0xFC09 (little-endian: 09 FC)
    [2]     Param Length = 1 + fragment_size
    [3]     Fragment Type: 0x00=CSS, 0x01=Data, 0x02=Signature, 0x03=PKI
    [4:]    Fragment Data (≤252 bytes)
```

### Payload 分割规则

Payload（从 `write_offset=964` 开始）是 HCI 命令序列。分割规则：

1. 按 HCI 命令边界累积：`opcode(2B) + plen(1B) + params(plen B)`
2. 当累积长度是 **4 字节的倍数** 时，发送一个 Secure Send
3. 扫描 opcode `0xFC0E` (Write Boot Params) 提取 `boot_address`

```python
while offset + frag_size + 3 <= len(fw_data):
    cmd_opcode = int.from_bytes(fw_data[offset + frag_size:offset + frag_size + 2], "little")
    cmd_plen = fw_data[offset + frag_size + 2]

    if cmd_opcode == 0xFC0E:  # Boot address command
        boot_address = int.from_bytes(fw_data[offset + frag_size + 3:...], "little")

    frag_size += 3 + cmd_plen

    if frag_size % 4 == 0:    # 4 字节对齐时发送
        await self._secure_send(0x01, fw_data[offset:offset + frag_size])
        offset += frag_size
        frag_size = 0
```

---

## 7. USB 端点路由（关键发现）

**标准 HCI USB 规范**：HCI Events 通过 Interrupt IN 端点传输。

**Intel Bootloader 的实际行为**：

| 阶段 | 响应端点 |
|------|---------|
| Read Version V2 | **Interrupt IN** (标准) |
| Secure Send (CSS/PKI/Sig/Payload) | **Bulk IN** (非标准！) |
| Vendor Events (0x06, 0x02) | **Interrupt IN** 或 **Bulk IN** |

### 解决方案

`_wait_for_event()` 实现三级 fallback：

```python
async def _wait_for_event(self, timeout=5.0):
    # 1. 快速检查 Interrupt IN (50ms)
    try: return self.read_interrupt_sync(255, 50)
    except: pass

    # 2. 检查 Bulk IN (完整超时)
    try: return self._ep_bulk_in.read(1024, timeout=timeout_ms)
    except: pass

    # 3. 最终尝试 Interrupt IN (完整超时)
    try: return self.read_interrupt_sync(255, timeout_ms)
    except: pass

    raise TimeoutError(...)
```

> **性能影响**：如果所有响应都走 Bulk IN，每个 chunk 只浪费 50ms（Interrupt IN 快速超时），~3900 个 chunk 额外 ~195 秒。实测全量加载 **3 分 35 秒**。

---

## 8. Intel Reset 与启动确认

### Intel Reset 命令结构

```python
# 0xFC01: Intel Reset
params = struct.pack("<BBBBI",
    0x00,           # reset_type: 0x00=normal, 0x01=reboot-to-bootloader
    0x01,           # patch_enable
    0x00,           # ddc_reload
    0x01,           # boot_option
    boot_address,   # 从固件中 0xFC0E 命令提取的启动地址
)
```

### Reboot to Bootloader（反向操作）

```python
# 从 Operational 切回 Bootloader（用于测试）
params = struct.pack("<BBBBI",
    0x01,  # reset_type=0x01 → 重启到 bootloader
    0x01, 0x01, 0x00, 0x00000000
)
```

### 启动确认

固件加载完成后，设备发送两个 Vendor Specific Event (0xFF)：

| 事件 | sub_type | 含义 |
|------|----------|------|
| 固件下载完成 | `0x06` | 所有 payload chunk 已接收并验证 |
| 启动完成 | `0x02` | 设备已从 bootloader 切换到 operational |

---

## 9. 硬件验证结果

### 测试环境

- **设备**: Intel BE200 (VID=0x8087, PID=0x0036, WiFi 7 / BT 5.4)
- **驱动**: WinUSB (通过 Zadig 替换 Intel 原生驱动)
- **固件**: `ibt-0291-0291.sfi` (989,892 bytes, 来自 linux-firmware)
- **平台**: Windows Server 2025, Python 3.11, pyusb + libusb

### 测试结果（8/8 PASS）

| # | 测试 | 耗时 | 验证内容 |
|---|------|------|---------|
| 1 | `test_auto_detect_finds_intel_device` | <1s | auto_detect 返回 IntelUSBTransport |
| 2 | `test_device_vid_pid_in_known_chips` | <1s | VID/PID 在 KNOWN_CHIPS 中注册 |
| 3 | `test_transport_info` | <1s | TransportInfo 字段正确 |
| 4 | `test_open_claims_interface` | <1s | USB interface 0 可 claim, 3 个 HCI 端点 |
| 5 | `test_hci_intel_read_version_v2` | <1s | Read Version V2 返回有效 TLV |
| 6 | `test_tlv_parsing_bootloader_detection` | <1s | 解析 22+ TLV 条目, 正确检测 image_type |
| 7 | `test_firmware_name_computation` | <1s | 计算 `ibt-0291-0291.sfi` 且文件存在 |
| 8 | **`test_intel_firmware_loading`** | **215s** | **完整固件加载端到端验证** |

### 固件加载日志

```
Intel new-gen platform detected (TLV response)
Intel TLV: image_type=0x01 sbe_type=0x01 cnvi_top=0x02001910 cnvr_top=0x02001910
Intel: ECDSA secure boot engine
Intel: bootloader mode — firmware needed: ibt-0291-0291.sfi
Intel: firmware file ibt-0291-0291.sfi (989892 bytes)
Intel: sending CSS header (type=0x00, offset=644, 128B)
Intel: sending PKI (type=0x03, offset=772, 96B)
Intel: sending Signature (type=0x02, offset=868, 96B)
Intel: found boot_address=0x00100800 at offset 989877
Intel: payload sent (988928 bytes total)
Intel: firmware download complete, boot_address=0x00100800
Intel: waiting for firmware load complete event...
Intel: firmware load complete
Intel: reset command sent (boot_address=0x00100800)
Intel: waiting for boot complete event...
Intel: boot complete — device is now operational
```

---

## 10. 调试经验与陷阱

### 陷阱 1：ECDSA vs RSA 偏移

**现象**: CSS header 发送返回 status=0x1F (Unspecified Error)  
**原因**: BE200 使用 ECDSA (SBE_TYPE=0x01)，CSS 在 offset 644 而非 0  
**修复**: 检查 TLV 字段 `0x2F`，选择对应的 BootParams

### 陷阱 2：固件名 STEP 掩码

**现象**: 计算出 `ibt-0191-0191.sfi`（不存在于 linux-firmware）  
**原因**: STEP 掩码错误使用 `(val & 0xF000) >> 12`（取第 12-15 位）  
**修复**: 正确掩码为 `(val & 0x0F000000) >> 24`（取第 24-27 位），得到 `ibt-0291-0291.sfi`

### 陷阱 3：Secure Send 响应走 Bulk IN

**现象**: 发送 CSS 后 Interrupt IN 超时（5 秒无响应）  
**原因**: Intel bootloader 将 Secure Send 的 Command Complete 路由到 Bulk IN 端点  
**修复**: `_wait_for_event` 先快速检查 Interrupt IN (50ms)，再检查 Bulk IN

### 陷阱 4：缺少 Signature 发送步骤

**现象**: 参考 Linux kernel 代码时遗漏了 type=0x02 签名发送  
**原因**: Bumble 实现明确发送 CSS(0x00) + PKI(0x03) + Signature(0x02) + Payload(0x01)  
**修复**: 在 PKI 和 Payload 之间增加 Signature 发送步骤

### 陷阱 5：Bootloader 状态机不可逆

**现象**: 部分固件下载中断后，设备不再响应 Read Version  
**原因**: Bootloader 收到部分固件数据后进入等待状态，忽略其他命令  
**修复**: 物理拔插 USB 适配器重置。软件级 `dev.reset()` 可能不够

### 陷阱 6：Payload 需要 4 字节对齐

**现象**: 随机分割 252 字节可能导致 bootloader 拒绝数据  
**原因**: 固件 payload 是 HCI 命令序列，需要按命令边界 + 4 字节对齐分割  
**修复**: 累积 HCI 命令直到总长度是 4 的倍数再发送

---

## 附录：文件清单

| 文件 | 说明 |
|------|------|
| `pybluehost/transport/usb.py` | IntelUSBTransport 实现 |
| `pybluehost/transport/firmware/__init__.py` | FirmwareManager 固件搜索 |
| `tests/hardware/test_intel_hw.py` | 8 个硬件验证测试 |
| `tests/hardware/firmware/intel/` | 固件文件目录（.gitignore 排除二进制） |
| `tests/unit/transport/test_intel_fw.py` | 6 个 Intel 固件 mock 单元测试 |
| `tests/unit/transport/test_usb.py` | 23 个 USB transport 单元测试 |
