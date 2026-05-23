# Hardware Survey on macOS

> **适用范围**：在 macOS 上跑 PyBlueHost 的 hardware E2E + `pybluehost tools info` adapter survey。
>
> **⚠️ 实验状态**：PyBlueHost 目前主开发在 Linux，macOS 路径**尚未由项目组验证过**。本文档基于 libusb 在 macOS 上的常规做法 + Apple Bluetooth 子系统的已知行为推断，可能有未覆盖的坑。第一次跑通的同学请把实际命令、报错、解决方案记到 §9，作为后续 macOS 用户的参考。

Linux/Windows 等价流程见 [`HARDWARE_SURVEY_LINUX.md`](HARDWARE_SURVEY_LINUX.md) / [`HARDWARE_SURVEY_WINDOWS.md`](HARDWARE_SURVEY_WINDOWS.md)。

---

## 0. macOS 的核心难点：IOBluetooth 抢占 + SIP

macOS 上 USB 蓝牙适配器的所有权由 **IOBluetoothHostControllerUSBTransport.kext**（内核扩展）持有，PyBlueHost 要走 libusb 直接发 HCI 命令必须先让它松手。难点是：

1. **IOBluetooth 子系统抓得非常死**：跟 Linux 的 `systemctl stop bluetooth` 类似，但 macOS 没有那么干净的开关。
2. **SIP（System Integrity Protection）**：现代 macOS（10.11+）禁止用户卸载 Apple 自带 kext。要禁用 SIP 必须进 Recovery Mode。
3. **Apple Silicon vs Intel Mac 差别**：Intel Mac 有内置 + 外置 USB 蓝牙的概念；Apple Silicon Mac 的内置蓝牙是 SoC 一部分（不走 USB），你**必须用外置 USB 适配器**。
4. **macOS 11 Big Sur+ 用 System Extensions 取代 kext**：策略更严，需要"降低安全等级"才能加载第三方扩展。

**我的判断**：如果你的目标只是填 `docs/HARDWARE_E2E.md` §2 的兼容性矩阵，建议**优先在 Linux 跑**——同样的适配器，Linux 路径成熟得多，结果更可信。macOS 上跑通主要价值是验证 PyBlueHost 的 Python 层在 macOS 上没 bug。

如果你坚持要在 macOS 上跑硬件，往下读。

### 0a. 关掉 macOS 自带蓝牙

**最简单的方式（GUI）**：System Settings → Bluetooth → 关闭蓝牙。

**命令行（不一定每个 macOS 版本都好使）**：

```bash
# 关闭蓝牙电源
sudo defaults write /Library/Preferences/com.apple.Bluetooth ControllerPowerState -int 0
sudo killall -HUP bluetoothd
```

注意：关掉系统蓝牙**不一定**会让 IOBluetooth 释放 USB 适配器。`bluetoothd` 重启时可能立刻重新 claim。

### 0b. 让 IOBluetooth 放手（最难的一步）

**方法 1：拔掉 USB 适配器，关掉系统蓝牙，再插回来，立刻跑测试**

时序很关键：拔掉之后系统蓝牙关掉（让 IOBluetooth 不要 monitor 新设备），再插上去，**在 IOBluetooth 重新 attach 之前** PyBlueHost 抢先 open。窗口很短（几百毫秒），脚本化跑更稳：

```bash
# 拔掉适配器
echo "拔掉 USB 适配器，按 Enter 继续..."
read

# 关蓝牙
sudo defaults write /Library/Preferences/com.apple.Bluetooth ControllerPowerState -int 0
sudo killall -HUP bluetoothd

echo "现在插回适配器，按 Enter 继续..."
read

# 立刻跑 info
uv run pybluehost tools info --transport=usb:VID:PID
```

**方法 2：禁用 IOBluetoothHostControllerUSBTransport kext（高风险，会让系统蓝牙失能）**

需要进 Recovery Mode 关 SIP，然后：

```bash
# 在正常启动后跑（SIP 已关）
sudo kextunload -b com.apple.iokit.IOBluetoothHostControllerUSBTransport
sudo kextunload -b com.apple.iokit.IOBluetoothFamily
```

之后系统蓝牙完全不能用直到下次 reboot 或 `kextload`。Apple Silicon Mac 上 kext 已经 deprecated（用 dext / System Extensions 替代），这条路可能完全走不通。

**方法 3：Apple Silicon Mac 上的 hack——dext 旁路**

未验证。理论上可以写一个 DriverKit 扩展声明对特定 VID:PID 的所有权，让 IOBluetooth 不去 attach。但写 dext 需要 Apple Developer 账号 + 公证流程，不现实。

**最现实的方案**：用方法 1（拔插窗口期）+ 用一张专门做测试的便宜适配器（CSR8510 几十块），插上后**永远不开系统蓝牙**，避免 IOBluetooth 来 attach。

---

## 1. 装 Python + uv + git

```bash
# 装 Homebrew（如果还没装）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python 3.10+
brew install python@3.12

# uv 包管理器
curl -LsSf https://astral.sh/uv/install.sh | sh
# 或 brew install uv

# git（macOS 自带 Apple 版 git；想用更新的：brew install git）
git --version
```

### libusb runtime（macOS 不自带）

```bash
brew install libusb
```

如果 `uv run pybluehost tools usb probe` 报 `pyusb backend not available`，几乎都是 libusb runtime 缺失。`brew install libusb` 把 `.dylib` 装到 `/opt/homebrew/lib/`（Apple Silicon）或 `/usr/local/lib/`（Intel Mac），pyusb 会自动找。

---

## 2. 克隆仓库

```bash
git clone <仓库 URL> pybluehost
cd pybluehost

git submodule update --init
uv sync --extra dev
```

跟 Linux 完全一样。SIG submodule 拉不到不影响 hardware 套件。

---

## 3. 烟雾测试：先确认环境对

```bash
uv run pytest tests/ -q --transport=virtual
```

期望：`3 failed, 1353 passed, 20 skipped`。

**macOS 第一次跑可能暴露虚拟模式都没碰过的问题**——例如某个测试依赖 Linux-specific path（`/dev/random`、`/proc/...`）。如果发现了，记下来，这是 PyBlueHost 项目的 macOS 兼容性问题，需要单独修。**先把这一步过了再动硬件**。

---

## 4. 识别 USB 适配器

```bash
# 等价 lsusb
system_profiler SPUSBDataType | grep -A 5 -iE "bluetooth|intel|realtek|csr"

# 或者 ioreg
ioreg -p IOUSB -l | grep -A 5 -iE "bluetooth"

# 简洁列表（需要 brew install lsusb）
brew install lsusb
lsusb
```

记下 VID:PID，例如 `Intel BE200 = 8087:0033`。

或者用 PyBlueHost probe（如果 IOBluetooth 还抓着，这里可能返回空列表）：

```bash
uv run pybluehost tools usb probe
```

---

## 5. 单适配器 info dump

跟 Linux 一样的命令，假设你已经通过 §0b 让 IOBluetooth 松手了：

```bash
mkdir -p docs/hardware

uv run pybluehost tools info --transport=usb:8087:0033 --json \
    > docs/hardware/intel-be200-macos.json

# 人类可读版
uv run pybluehost tools info --transport=usb:8087:0033
```

**注意**：建议 macOS 上的 JSON 文件名加 `-macos` 后缀（如 `intel-be200-macos.json`），跟 Linux 版区分开。后续如果发现同款适配器在 macOS 上能力被 IOBluetooth 中间层影响过滤，矩阵需要分平台记录。

---

## 6. 双适配器 e2e 跑套件

```bash
uv run pytest tests/e2e/ -v \
    --transport=usb:vendor=intel#1 \
    --transport-peer=usb:vendor=intel#2 \
    2>&1 | tee docs/hardware/intel-be200-macos-e2e.log
```

**macOS 上第一次跑的预期是会撞到一些 Linux 上没见过的问题**——例如 IOBluetooth 在某个测试中间介入了 USB 总线、libusb 在 macOS 上对 `clear_halt` 的实现不同等等。每个失败都值得单独记录到 §9。

---

## 7. 把结果带回主开发机

跟 Linux 一样：

```bash
git checkout -b hw/<adapter>-macos-survey
git add docs/hardware/ docs/HARDWARE_SURVEY_MACOS.md   # 顺便把 §9 的发现写进去
git commit -m "docs(hardware): <adapter> macOS survey + known issues"
git push -u origin hw/<adapter>-macos-survey
```

---

## 8. 更新兼容矩阵

`docs/HARDWARE_E2E.md` §2 的矩阵目前不区分 Linux/macOS/Windows——填的时候**仅填同款适配器在 Linux 上的实测**，因为那是 PyBlueHost 的 reference platform。macOS 实测结果如果跟 Linux 不同，单独记到本文档 §9。

如果三个平台跑出来差异大到需要分列展示，未来可以把矩阵扩成 `LE SC (Linux/macOS/Windows)` 三列。

---

## 9. macOS 上发现的问题与解法（社区贡献区）

> **第一个跑通 macOS 路径的同学请把发现写到这里**。每个问题用如下模板：
>
> ```
> ### 问题：<一句话描述>
> - **macOS 版本**：例如 13.6 (Ventura)
> - **机型**：例如 M2 MacBook Pro / Intel Mac mini 2018
> - **适配器**：例如 Intel BE200 / 8087:0033
> - **现象**：完整报错或行为
> - **解法**：步骤
> - **记录人 / 日期**：
> ```

（待填）

---

## 10. 真的不行就 fallback：Linux VM / 双系统

如果折腾 §0b 半天发现 IOBluetooth 始终抓着、kext 卸不动、或者用的是 Apple Silicon 没法降级 SIP——**最务实的方案**：

1. **UTM + Linux VM**：UTM 支持把 USB 适配器直通进 VM。在 macOS 主机上装 UTM（免费），跑 Ubuntu / Debian VM，然后按 [`HARDWARE_SURVEY_LINUX.md`](HARDWARE_SURVEY_LINUX.md) 走。VM 里没有 IOBluetooth，对 PyBlueHost 完全透明。
2. **双系统 / Boot Camp**：Intel Mac 装 Linux 双系统。Apple Silicon Mac 装 Asahi Linux。
3. **直接换台 Linux 主机**：项目的 reference platform，路径最顺。

**结论**：macOS 上的硬件 survey 主要是为了证明"PyBlueHost 在 macOS 上能跑"。如果你只是想填兼容性矩阵，**Linux 仍然是首选**——同样的适配器，Linux 测出来的结果更可信，因为 IOBluetooth 中间层不会过滤任何 HCI 行为。
