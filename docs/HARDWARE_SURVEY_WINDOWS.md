# Hardware Survey on Windows

> **适用范围**：在 Windows 10/11 上跑 PyBlueHost 的 hardware E2E + `pybluehost tools info` adapter survey。手上有一张或多张 USB 蓝牙适配器，希望在 Windows 主机上完成兼容性矩阵 (`docs/HARDWARE_E2E.md` §2) 的实测填写。

Linux 通用流程见 [`docs/HARDWARE_E2E.md`](HARDWARE_E2E.md)。本文档只覆盖 Windows-specific 的部分：驱动绑定、PowerShell 等价命令、常见坑。

---

## 0. Windows 的核心难点：驱动归属

这是 Windows 上做 USB HCI 的**唯一真正难题**。先理解清楚再动手。

Windows 默认会把任何蓝牙 USB 适配器自动绑定到微软自家的 `bthusb.sys` 驱动（Windows Bluetooth 协议栈），目的是让系统设置里的"蓝牙"开关能用。但 PyBlueHost 不走 Windows 协议栈——它通过 **libusb / WinUSB** 直接发 HCI 命令，需要适配器是 `WinUSB` 或 `libusbK` 驱动。

**症状**：跑 `pybluehost tools info --transport=usb:...` 会报 `Access denied (errno=13)` 或 `LIBUSB_ERROR_NOT_SUPPORTED`。

**两个解决方案**，按推荐顺序：

### 方案 A：Zadig 替换驱动（推荐，永久生效）

1. 下载 [Zadig](https://zadig.akeo.ie/)（约 5 MB，无需安装）
2. 以**管理员身份**运行 Zadig
3. 菜单 `Options → List All Devices` 打勾
4. 在下拉菜单里找到你的蓝牙适配器（按 VID/PID 认，例如 `Intel BE200` 是 `8087:0033`、`Realtek RTL8761B` 是 `0BDA:8771`）
5. 右边目标驱动选 **WinUSB**（不要选 libusbK 或 libusb-win32，会跟某些固件烧录工具冲突）
6. 点 **Replace Driver**

**风险与回退**：
- 替换后，Windows 设置 → 蓝牙开关将看不到这块适配器（这是预期，因为 PyBlueHost 接管了）。
- 想恢复给 Windows 用：设备管理器 → 找到该设备 → 右键 → 卸载设备（勾选"删除驱动程序软件"）→ 拔插一次，Windows 会重新绑定 `bthusb.sys`。
- 如果电脑只有这一块蓝牙适配器，并且日常用 Windows 蓝牙耳机/键盘，建议另买一块专用做 PyBlueHost 测试。

### 方案 B：冷启动 + 临时占用（不推荐，只在 Zadig 不能用时用）

记录里发现的现象（Intel BE200 + bthusb.sys）：**完全关机 10 秒，再开机**（不是重启），第一次开机时 Windows 还没来得及绑定 bthusb.sys，pyusb 可以抢先 open。

```powershell
# 关机前：
shutdown /s /t 0

# ★物理断电10秒★（关键，否则 Windows fast boot 会保留驱动状态）

# 开机后立刻跑（不要先打开 Windows 设置里的蓝牙）：
uv run pybluehost tools info --transport=usb:8087:0033
```

这个方案脆弱、每次重启都要重做，只适合临时验证一次。

---

## 1. 安装 Python + uv + git

以**管理员 PowerShell** 跑（避免装到 LocalLow 等奇怪位置）：

```powershell
# Python 3.10+（去 https://www.python.org/downloads/ 下安装包，勾选 "Add to PATH"）
python --version

# uv（PyBlueHost 的包管理器）
irm https://astral.sh/uv/install.ps1 | iex
# 或 winget install --id astral-sh.uv

# git（去 https://git-scm.com/download/win 下安装包）
git --version
```

装完关掉 PowerShell 再开一个，让 PATH 生效。

---

## 2. 克隆仓库

```powershell
# 选个工作目录，例如 C:\work\
cd C:\work
git clone <仓库 URL> pybluehost
cd pybluehost

# SIG 数据 submodule（用于 sig_db 单测；不装也能跑 info）
git submodule update --init

# 装依赖（含开发依赖）
uv sync --extra dev
```

**网络无法访问 bitbucket.org 拉 submodule** 时，跳过 submodule 不影响 `pybluehost tools info` 和 hardware e2e。会让 `tests/unit/core/test_sig_db.py` 等 ~10 个测试 skip，但 hardware 套件不受影响。

---

## 3. 烟雾测试：先确认环境对

**关键步骤**：在动硬件之前，先在 virtual 模式跑一次 e2e，确认 Python + uv + 仓库都对。

```powershell
uv run pytest tests/ -q --transport=virtual
```

期望：`3 failed, 1353 passed, 20 skipped` 之类（3 个 USB-diagnostics 失败是 known-issue，不影响）。如果数字差很多，先排查 Python 版本、submodule、uv sync 是否真的装齐了。

---

## 4. 识别 USB 适配器

PowerShell 里的 `lsusb` 等价命令：

```powershell
# 列出所有 USB 设备的 VID:PID
Get-PnpDevice -Class USB -PresentOnly | Select-Object FriendlyName, InstanceId | Format-Table -AutoSize

# 只看蓝牙类（注意：替换驱动后，Class 可能变成 "USBDevice"，不是 "Bluetooth"）
Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -match "Bluetooth|WinUSB" }
```

或者直接用 PyBlueHost 自带的 probe：

```powershell
uv run pybluehost tools usb probe
```

它会列出当前所有可枚举的 USB 蓝牙适配器，包括厂商、VID:PID、bus/device 路径，以及**驱动状态**（是否已替换为 WinUSB）。如果 probe 都看不到，方案 A 的 Zadig 还没生效。

记下每张卡的 VID:PID，例如：
- Intel BE200 = `8087:0033`
- Realtek RTL8761B = `0BDA:8771`
- CSR8510 A10 = `0A12:0001`
- Broadcom BCM20702 = `0A5C:21E8`

---

## 5. 单适配器 info dump

每张适配器跑一次 `info --json` 存基线：

```powershell
mkdir docs\hardware -Force

# Intel BE200（替换 VID:PID）
uv run pybluehost tools info --transport=usb:8087:0033 --json `
    | Out-File -Encoding utf8 docs\hardware\intel-be200.json

# Realtek
uv run pybluehost tools info --transport=usb:0bda:8771 --json `
    | Out-File -Encoding utf8 docs\hardware\realtek-rtl8761b.json

# 同时跑一次人类可读版，目测看 capability summary 那段
uv run pybluehost tools info --transport=usb:8087:0033
```

**反引号 `` ` `` 是 PowerShell 的续行符**，跟 Linux 的 `\` 等价。如果跑不通，把命令写一行也行：

```powershell
uv run pybluehost tools info --transport=usb:8087:0033 --json | Out-File -Encoding utf8 docs\hardware\intel-be200.json
```

`-Encoding utf8` 必须加（PowerShell 5.1 默认是 UTF-16 BOM，会让后续 `python -m json.tool` 报错）。

### 同型号两张：用 #1 / #2

```powershell
uv run pybluehost tools info --transport=usb:vendor=intel#1 --json | Out-File -Encoding utf8 docs\hardware\intel-be200-1.json
uv run pybluehost tools info --transport=usb:vendor=intel#2 --json | Out-File -Encoding utf8 docs\hardware\intel-be200-2.json
```

---

## 6. 双适配器 e2e 跑套件

```powershell
# 同型号互测
uv run pytest tests/e2e/ -v `
    --transport=usb:vendor=intel#1 `
    --transport-peer=usb:vendor=intel#2 `
    *>&1 | Tee-Object -FilePath docs\hardware\intel-be200-e2e.log

# 跨厂商互测（更能暴露 vendor quirk）
uv run pytest tests/e2e/ -v `
    --transport=usb:8087:0033 `
    --transport-peer=usb:0bda:8771 `
    *>&1 | Tee-Object -FilePath docs\hardware\intel-x-realtek-e2e.log
```

PowerShell 里 `*>&1 |` 是把 stderr 也并进管道（pytest 的部分输出走 stderr）。`Tee-Object` 等价于 Linux 的 `tee`。

预期：15 个场景大部分 PASS，少数 SKIP（适配器能力不足时按设计 skip）。哪些 FAIL 就是 vendor quirk。

---

## 7. 把结果带回主开发机

**方案 A（推荐）—— 那台 Windows 直接 push**：

```powershell
git checkout -b hw/<adapter>-survey
git add docs\hardware\ docs\HARDWARE_E2E.md   # 如果改了矩阵 §2
git commit -m "docs(hardware): <adapter> survey baseline + e2e log"
git push -u origin hw/<adapter>-survey
```

回到主开发机：

```bash
git fetch && git merge --ff-only origin/hw/<adapter>-survey
```

**方案 B —— 只拷文件**（公司网络隔离时）：

把 `docs\hardware\*.json` 和 `*.log` 拷出来（U 盘 / SCP / 邮件附件都行），到主开发机手动放进 `docs/hardware/` 后再 commit。

---

## 8. 更新兼容矩阵

回到主开发机，编辑 `docs/HARDWARE_E2E.md` §2，把对应行的 `TBD` 填实。判断依据来自 info JSON 里的 `capability_summary`：

| 矩阵列 | JSON 路径 | true → 矩阵 | false → 矩阵 |
|---|---|---|---|
| LE SC | `capability_summary.le_secure_connections` | ✓ | - |
| BR/EDR SSP | `capability_summary.bredr_ssp` | ✓ | - |
| BR/EDR SC | `capability_summary.bredr_sc_controller` | ✓ | - |
| LE Audio | `capability_summary.le_audio_host_support` | ✓ | - |

PowerShell 里快速读 JSON：

```powershell
$d = Get-Content docs\hardware\intel-be200.json | ConvertFrom-Json
$d.capability_summary
```

---

## 9. Windows 常见坑

| 现象 | 原因 | 解决 |
|---|---|---|
| `Access denied (errno=13)` 或 `LIBUSB_ERROR_NOT_SUPPORTED` | 适配器被 bthusb.sys 占着 | 走 §0 方案 A（Zadig 换 WinUSB） |
| `Could not find USB device` | VID:PID 写错；或 Zadig 替换后 Windows 还没刷新 | `Get-PnpDevice` 复核；拔插一次适配器 |
| info 跑出来 manufacturer 是 `Unknown (0xFFFF)` | 虚拟模式假数据 / 老固件没正确响应 Read_Local_Version | 确认 `--transport=usb:...` 不是 `virtual`；对老固件检查是否需要先烧录 |
| Realtek 适配器初始化失败 | RTL8761B 系列需要固件 blob | PyBlueHost 已内置加载逻辑，看 `pybluehost tools fw` 命令；参考 `tests/unit/transport/test_realtek_fw.py` |
| `uv run` 报 `pyusb backend not available` | 没装 libusb runtime DLL | 装 [libusb](https://github.com/libusb/libusb/releases) 的 `libusb-1.0.dll`，放到 `C:\Windows\System32\` 或加到 PATH |
| Out-File 出来的 JSON 用 `python -m json.tool` 报错 | PowerShell 5.1 默认 UTF-16 BOM | `Out-File` 加 `-Encoding utf8`，或用 `Set-Content -Encoding UTF8` |
| PowerShell 续行 `` ` `` 看起来没生效 | 续行符后面有空格 | 续行符必须**紧接**换行，前面可以空格但后面不行 |
| pytest 的 `--transport-peer` 找不到第二张适配器 | 两张同型号但没用 `#1` `#2` 区分 | 同型号两张必须用 `usb:vendor=intel#1` 这种语法 |
| 一段时间不操作后适配器 "消失" | Windows USB selective suspend 把端口断电了 | 设备管理器 → USB Root Hub 属性 → 电源管理 → 关掉"允许计算机关闭此设备以节省电源" |
| `info` 跑成功但 e2e 全 SKIP `adapter does not support BR/EDR SSP` | 适配器固件确实不支持，或 Read_Local_Supported_Commands 报告异常 | 看 info 的 `capability_summary.bredr_ssp` 与 `supported_commands.unknown_bits_set`；如果 unknown_bits 很多说明固件 quirky |

---

## 10. 我应该按什么顺序做？

如果你只有有限时间（比如一个晚上），最少做这三件事就够把矩阵填一行：

1. **§0 方案 A：Zadig 换 WinUSB**（10 分钟，一次性）
2. **§3 烟雾测试 + §5 单适配器 info dump**（15 分钟，验证整条链路）
3. **§6 双适配器 e2e**（5 分钟跑完，主要看 PASS/FAIL/SKIP 分布）

跑完一张就有一行矩阵数据可以填。后续每来一张新适配器，只需要重复 §5 + §6。
