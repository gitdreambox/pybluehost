# 2026-11-04 BlueZ / WSL 对照实验：USB 移交阶段受阻

## 判定边界

用户要求将 IUT 经 usbipd 挂入 WSL，以最新 BlueZ 对照当前 27 个 blocked 用例。本次已构建 BlueZ 和准备 auto-pts 环境，但 **BlueZ 实际运行用例数为 0**：WSL 没有 Bluetooth HCI 设备，USB attach 在 Windows 代理启动阶段失败。

因此没有 BlueZ PASS/FAIL，也没有跨实现证据能确认或推翻 PyBlueHost 的 blocked 分类。原矩阵保持不变。用例清单与优先顺序见 [分诊记录](2026-11-04-triage.md)。

## 已准备的环境

| 项目 | 本次值 |
|---|---|
| BlueZ checkout | `14bd6ab65f4a647302edbd6df27f6faa91bee8a8`，btpclient `--version` = `5.87` |
| auto-pts checkout | `39d07081dbbe814418a17c0bac38de774b9d4eae` |
| WSL distribution / kernel | Ubuntu / `6.18.54.1-microsoft-standard-WSL2` |
| 工作目录 | `/home/wwdeng/bluez-ab` |
| btpclient | `/home/wwdeng/bluez-ab/bluez/client/btpclient/btpclient` |
| Python 环境 | `/home/wwdeng/bluez-ab/venv`，已安装 auto-pts client requirements |
| workspace | `runs/phase2/workspace/zephyr-master/zephyr-master.pqw6` |
| USB/IP | usbipd-win 5.3.0 |

auto-pts client 必须在 WSL 内运行：BlueZ 的 IUT 控制器启动 btpclient 并使用 `/tmp/bt-stack-tester` Unix socket。网络已验证为 WSL mirrored 模式，可达 Windows PTS XML-RPC 服务。

WSL 临时 `run-case.sh` 尚未执行，其中 server/callback 端口仍是本次探测值。恢复后先改为读取 Windows auto-pts 的 `.pts_ports` 并重新检查 WSL callback 端口可绑定；不能把本次端口复制成永久默认值。Windows 重启可能改变端口保留区。

## USB 移交证据

本次枚举位置（仅供追溯，恢复时必须重新按 BD_ADDR 定位）：

- BE200 IUT：`A0:85:27:2F:60:15`，bus `5-2`。
- BE200 PTS：`FC:9E:53:D5:8D:EB`，bus `5-3`。
- AX201 备用验证：bus `1-14`，`8087:0026`。换它仅用于区分 USB/IP 故障，不可视作相同硬件的 BlueZ 对照。

BE200 和 AX201 attach 均返回：

```text
WSL usbip: error: Attach Request ... failed - Device in error state
System.IO.FileNotFoundException: Unable to find the specified file.
    at Usbipd.VBoxUsb.ClaimDeviceOnce ...
```

Windows System 日志中 `VBoxUSBMon` Event ID 4 的 EventData 指向：

```text
\Device\VBoxUSBMon
INTERNAL_IOCTL_PROXY_STARTUP
```

该日志定位的是 USB 代理启动失败，尚不能确定更底层原因。不能仅凭 `VBoxUSB` 名称就认定安装了冲突的 VirtualBox：

- 正在运行的 `VBoxUSBMon` 路径是 `C:\Program Files\usbipd-win\Drivers\VBoxUSBMon.sys`（usbipd 自己提供）。
- 系统目录与 usbipd 目录的 `VBoxUSB.sys` 文件版本均为 `7.2.2.170484`。
- 系统 `VBoxUSB.sys` 的 Authenticode 状态为 `Valid`。
- usbipd 另报告 `hrdevmon` 未知过滤器与 `TsUsbFlt` 已知不兼容过滤器；强制绑定仍未解决 attach。未删除这些过滤器。

上游 [issue #458](https://github.com/dorssel/usbipd-win/issues/458) 包含同类异常，但不是本机版本冲突的证明。其讨论涉及驱动加载、修复安装和重启；不能直接据此卸载 VirtualBox 或关闭安全功能。

## 清理与遗留设备状态

已撤销 AX201 的强制绑定。最终 usbipd 中 `1-14`、`5-2`、`5-3` 都是 `Not shared`。

**撤销共享不等于设备恢复健康**：AX201 和 BE200 IUT 回到 Windows Intel Bluetooth 驱动后仍是 Code 31（`CM_PROB_FAILED_ADD`）；AX201 的服务为 `BTHUSB`、LowerFilter 为 `ibtusb`。定向 restart，以及随后各一次 disable/enable，均未清除错误。BE200 PTS 设备仍为 `OK / CM_PROB_NONE`。未卸载软件、删除驱动、改变驱动启动类型或重启 Windows。

本机原始恢复日志（临时文件，不作为长期唯一证据）：

- `C:\Users\admin\AppData\Local\Temp\claude\restore-ax201-after-usbip.log`
- `C:\Users\admin\AppData\Local\Temp\claude\recover-iut-pnp.log`

## 恢复后的执行入口

1. 先安排 Windows 重启并复查设备状态；这是下一项恢复实验，尚未证明能解决本机故障。若仍 Code 31，继续查驱动加载/过滤器日志，不直接跑 PTS。
2. 按地址重新定位两颗 BE200。只共享 IUT；attach 成功的最低证据是 WSL `/sys/class/bluetooth` 出现 HCI 设备并能读取控制器信息。
3. 记录 Linux 实际加载后的 firmware/version/features。Linux 固件加载可能改变能力，同一物理 dongle 也不保证与 Windows 固件相同。
4. 更新 runner 端口来源，确认只有一个 PTS server 和一个 client 会话，先跑已知可通过的 GAP sibling，验证 BlueZ、BTP、回调和 PTS 的整条链。
5. 先跑 GAP/SM 的 blocked 用例；本次 auto-pts BlueZ 项目只导入 `bap/gap/sm`，GAP/SM 有遍历 PTS 用例列表的默认注册。L2CAP/GATT 必须先核对 btpclient 支持的 BTP 服务，再补参考注册或走人工规程；`NOT_IMPLEMENTED` 不记为 BlueZ 协议失败。
6. 每例保留 PTS 版本、PIXIT、WID、两侧 HCI 和 FINAL_VERDICT。单独记录 BlueZ 结果，不对整个日志树强制导入，不覆盖人工 blocked。
