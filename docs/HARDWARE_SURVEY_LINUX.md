# Hardware Survey on Linux

> **适用范围**：在 Linux（Ubuntu/Debian/Fedora/Arch 等）上跑 PyBlueHost 的 hardware E2E + `pybluehost tools info` adapter survey。

Linux 是 PyBlueHost 的主开发平台，路径最顺。Windows 等价流程见 [`HARDWARE_SURVEY_WINDOWS.md`](HARDWARE_SURVEY_WINDOWS.md)，macOS 见 [`HARDWARE_SURVEY_MACOS.md`](HARDWARE_SURVEY_MACOS.md)。

---

## 0. Linux 的核心难点：BlueZ 抢占 + USB 权限

跟 Windows 类似但对手不同——Linux 上是 **内核 BlueZ 协议栈**通过 `btusb` 内核模块占用 USB 蓝牙适配器。PyBlueHost 走 libusb / `pyusb`，需要 BlueZ 先松手。

**症状**：
- `Access denied (errno=13)` / `LIBUSB_ERROR_ACCESS`：udev 权限不够。
- `LIBUSB_ERROR_BUSY` / `Could not claim interface`：BlueZ 还抓着。

**两个动作连着做**：

### 0a. 让 BlueZ 释放适配器

```bash
# 临时（每次重启失效，用于一次性测试）
sudo systemctl stop bluetooth

# 永久（避免每次都要 stop）
sudo systemctl disable --now bluetooth

# 如果还不放（特定内核版本会自动 rebind），把 btusb 也 unbind 一次：
sudo rmmod btusb && sudo modprobe btusb
sudo hciconfig hci0 down   # BlueZ 看到的设备号一般是 hci0
```

**注意**：BlueZ 关了之后，桌面环境的蓝牙图标会失能。如果这台机平时用蓝牙耳机/键盘，建议另买一块专用做 PyBlueHost 测试，或者只在 survey 时临时 `systemctl stop bluetooth`，跑完 `systemctl start bluetooth` 还原。

### 0b. udev 规则授权（一次性）

把当前用户加进 `plugdev` 组（多数发行版默认存在），然后写一份 udev 规则放权：

```bash
sudo usermod -aG plugdev $USER

sudo tee /etc/udev/rules.d/99-pybluehost.rules <<'EOF'
# Intel
SUBSYSTEM=="usb", ATTR{idVendor}=="8087", GROUP="plugdev", MODE="0660"
# Realtek
SUBSYSTEM=="usb", ATTR{idVendor}=="0bda", GROUP="plugdev", MODE="0660"
# CSR / Qualcomm
SUBSYSTEM=="usb", ATTR{idVendor}=="0a12", GROUP="plugdev", MODE="0660"
# Broadcom
SUBSYSTEM=="usb", ATTR{idVendor}=="0a5c", GROUP="plugdev", MODE="0660"
EOF

sudo udevadm control --reload
sudo udevadm trigger

# 注销重登一次让 group 生效（或者新开一个 shell 也行）
```

如果不愿意写规则，临时方案是直接 `sudo` 跑 `pybluehost tools info ...`——能用，但每次密码烦，而且 root 会污染 `~/.cache/uv` 权限。

### 0c. 验证适配器对 PyBlueHost 可见

```bash
uv run pybluehost tools usb probe
```

应该列出所有 USB 蓝牙适配器（VID/PID + bus/device）。如果什么都没列出来，回到 §0a 检查 BlueZ 是不是真停了。

---

## 1. 装 Python + uv + git

```bash
# Python 3.10+（发行版包通常够新；旧的用 deadsnakes PPA 或 pyenv）
python3 --version

# uv 包管理器
curl -LsSf https://astral.sh/uv/install.sh | sh
# 或 pip install uv

# git（多数发行版自带，没有的话装一下）
git --version
```

装完关掉 shell 再开，让 PATH 生效。

---

## 2. 克隆仓库

```bash
git clone <仓库 URL> pybluehost
cd pybluehost

# SIG 数据 submodule（用于 sig_db 单测；不装也能跑 info）
git submodule update --init

# 装依赖（含开发依赖）
uv sync --extra dev
```

**网络无法访问 bitbucket.org 拉 submodule** 时跳过——只让 ~10 个 sig_db 单测 skip，不影响 hardware 套件。

---

## 3. 烟雾测试：先确认环境对

```bash
uv run pytest tests/ -q --transport=virtual
```

期望：`3 failed, 1353 passed, 20 skipped`（3 个 pre-existing USB-diagnostics 失败是 known-issue）。如果数字差很多，先排查 Python 版本、submodule、`uv sync` 是否真装齐了。

---

## 4. 识别 USB 适配器

```bash
# 列所有 USB 设备
lsusb

# 只看蓝牙类
lsusb | grep -iE "bluetooth|intel|broadcom|realtek|csr|qualcomm"

# 看驱动绑定状态
ls /sys/bus/usb/drivers/btusb/    # 还绑在 btusb 的话会列在这里
```

记下每张卡的 VID:PID，例如：
- Intel BE200 = `8087:0033`
- Realtek RTL8761B = `0BDA:8771`
- CSR8510 A10 = `0A12:0001`
- Broadcom BCM20702 = `0A5C:21E8`

或者直接用 PyBlueHost 自带的 probe，输出更结构化：

```bash
uv run pybluehost tools usb probe
```

---

## 5. 单适配器 info dump

每张适配器跑一次 `info --json` 存基线：

```bash
mkdir -p docs/hardware

# Intel BE200（替换 VID:PID）
uv run pybluehost tools info --transport=usb:8087:0033 --json \
    > docs/hardware/intel-be200.json

# Realtek
uv run pybluehost tools info --transport=usb:0bda:8771 --json \
    > docs/hardware/realtek-rtl8761b.json

# 同时跑一次人类可读版，目测看 capability summary 那段
uv run pybluehost tools info --transport=usb:8087:0033
```

### 同型号两张:用 #1 / #2

```bash
uv run pybluehost tools info --transport=usb:vendor=intel#1 --json > docs/hardware/intel-be200-1.json
uv run pybluehost tools info --transport=usb:vendor=intel#2 --json > docs/hardware/intel-be200-2.json
```

---

## 6. 双适配器 e2e 跑套件

```bash
# 同型号互测
uv run pytest tests/e2e/ -v \
    --transport=usb:vendor=intel#1 \
    --transport-peer=usb:vendor=intel#2 \
    2>&1 | tee docs/hardware/intel-be200-e2e.log

# 跨厂商互测（更能暴露 vendor quirk）
uv run pytest tests/e2e/ -v \
    --transport=usb:8087:0033 \
    --transport-peer=usb:0bda:8771 \
    2>&1 | tee docs/hardware/intel-x-realtek-e2e.log
```

预期：15 个场景大部分 PASS，少数 SKIP（适配器能力不足时按设计 skip）。哪些 FAIL 就是 vendor quirk，写进 `docs/HARDWARE_E2E.md` §5 的失败分诊表。

---

## 7. 把结果带回主开发机

**方案 A（推荐）—— 直接 push**：

```bash
git checkout -b hw/<adapter>-survey
git add docs/hardware/ docs/HARDWARE_E2E.md   # 如果改了矩阵 §2
git commit -m "docs(hardware): <adapter> survey baseline + e2e log"
git push -u origin hw/<adapter>-survey
```

回到主开发机：

```bash
git fetch && git merge --ff-only origin/hw/<adapter>-survey
```

**方案 B —— 只拷文件**（公司网络隔离时）：scp / rsync / 优盘把 `docs/hardware/*.json` 和 `*.log` 拷出来。

---

## 8. 更新兼容矩阵

回到主开发机，编辑 `docs/HARDWARE_E2E.md` §2，把对应行的 `TBD` 填实。判断依据来自 info JSON 里的 `capability_summary`：

| 矩阵列 | JSON 路径 | true → 矩阵 | false → 矩阵 |
|---|---|---|---|
| LE SC | `capability_summary.le_secure_connections` | ✓ | - |
| BR/EDR SSP | `capability_summary.bredr_ssp` | ✓ | - |
| BR/EDR SC | `capability_summary.bredr_sc_controller` | ✓ | - |
| LE Audio | `capability_summary.le_audio_host_support` | ✓ | - |

shell 里快速读 JSON：

```bash
jq .capability_summary docs/hardware/intel-be200.json
# 或：python3 -c "import json;print(json.load(open('docs/hardware/intel-be200.json'))['capability_summary'])"
```

---

## 9. Linux 常见坑

| 现象 | 原因 | 解决 |
|---|---|---|
| `Access denied (errno=13)` | udev 权限或 group 不对 | 走 §0b 写规则 + `usermod -aG plugdev` + 重登 |
| `LIBUSB_ERROR_BUSY` / `Could not claim interface` | BlueZ/btusb 还占着 | `systemctl stop bluetooth`，必要时 `rmmod btusb && modprobe btusb` |
| `lsusb` 看得到但 `probe` 看不到 | udev 规则的 VID 写错或没生效 | `udevadm test /sys/bus/usb/devices/...` 看实际匹配；`udevadm control --reload && udevadm trigger` 重载 |
| `pyusb backend not available` | 缺 `libusb-1.0` 运行时 | `sudo apt install libusb-1.0-0`（Debian/Ubuntu）/ `sudo dnf install libusb1`（Fedora） |
| Realtek 适配器初始化失败 | RTL8761B 系列需要固件 blob | PyBlueHost 已内置加载逻辑；看 `pybluehost tools fw` 命令；固件文件如有缺失需从 linux-firmware repo 拷贝 |
| 跑完 e2e 后 BlueZ 启不回去 | btusb 模块没自动 rebind | `sudo systemctl start bluetooth`；还不行 `rmmod btusb && modprobe btusb` |
| WSL / WSL2 上跑不通 | WSL 默认不直通 USB | 用 [usbipd-win](https://github.com/dorssel/usbipd-win) 把适配器从 Windows 直通进 WSL2；或者直接在原生 Linux 跑 |
| 跑 e2e 偶发 `Page Timeout` | 适配器距离/干扰 | 把两张卡放近一点；或在测试时把其他蓝牙设备关掉 |

---

## 10. 我应该按什么顺序做？

1. **§0a + §0b：BlueZ + udev**（10 分钟，一次性）
2. **§3：虚拟烟雾测试**（1 分钟，验证 Python/uv/仓库都对）
3. **§5：单适配器 info dump**（5 分钟，验证 USB 这条链路 + 拿到 JSON 基线）
4. **§6：双适配器 e2e**（5 分钟跑完）

跑完一张就有一行矩阵数据可以填。后续每来一张新适配器，只需要重复 §5 + §6。
