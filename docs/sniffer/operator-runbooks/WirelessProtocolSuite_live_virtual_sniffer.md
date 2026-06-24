# WirelessProtocolSuite_live_virtual_sniffer.py 设计实现文档

## 目标

`WirelessProtocolSuite_live_virtual_sniffer.py` 是一个最小可运行的 WPS LiveImport HCI 注入 demo。

它用于启动 Teledyne LeCroy Wireless Protocol Suite 的 Virtual Sniffing 模式，并向 WPS 写入可见的 HCI Reset Command / Command Complete Event。

验收标准：

- WPS 自动启动到 Virtual Sniffing。
- Capture 自动开始。
- WPS Summary 中能看到 HCI Reset Command 和 HCI Reset Command Complete Event。
- 可保存 `.cfax` 抓包文件。

## 参考来源

本实现参考了以下资料和本地文件：

```text
Bluetooth SIG PTS download / sniffer integration 入口:
https://pts.bluetooth.com/download

Teledyne LeCroy WPS 安装说明:
https://support.bluetooth.com/hc/en-us/articles/37036623059085-How-to-Install-the-Teledyne-LeCroy-Wireless-Protocol-Suite-Software

WPS Live Import Developer Kit:
C:\Program Files (x86)\Teledyne LeCroy Wireless\Wireless Protocol Suite 4.60\Help and Tools\Live Import Developer Kit.exe

WPS LiveImport manual:
C:\Program Files (x86)\Teledyne LeCroy Wireless\Wireless Protocol Suite 4.60\Live Import Developers Kit\UserManualLiveImport.pdf

WPS LiveImport headers:
C:\Program Files (x86)\Teledyne LeCroy Wireless\Wireless Protocol Suite 4.60\Live Import Developers Kit\h\LiveImportAPI.h
C:\Program Files (x86)\Teledyne LeCroy Wireless\Wireless Protocol Suite 4.60\Live Import Developers Kit\h\drivernotifications.h

WPS LiveImport GUI sample:
C:\Program Files (x86)\Teledyne LeCroy Wireless\Wireless Protocol Suite 4.60\Live Import Developers Kit\GUI Sample\maindialog.cpp
C:\Program Files (x86)\Teledyne LeCroy Wireless\Wireless Protocol Suite 4.60\Live Import Developers Kit\GUI Sample\guisample.ini

WPS product liveimport.ini:
C:\Program Files (x86)\Teledyne LeCroy Wireless\Wireless Protocol Suite 4.60\liveimport.ini
```

## 设计结论

WPS HCI 注入不能只靠 Automation Server 的 ASCII TCP 命令完成。Automation Server 可用于启动/控制 WPS，但真正写入 HCI frame 的有效路径是 LiveImportAPI。

当前实现采用单文件设计：`WirelessProtocolSuite_live_virtual_sniffer.py` 内部包含启动 WPS、读取 `liveimport.ini`、配置 LiveImportAPI、发送 HCI Reset、保存 `.cfax` 的全部逻辑，不再依赖 `hci_reset_visibility_demo.py` 或 `wps_automation_demo.py`。

实测有效链路：

1. 启动 `Fts.exe /ComProbe Protocol Analysis System=Generic /oemkey=Virtual`。
2. 从 WPS product root `liveimport.ini` 读取 `ConnectionString`。
3. 从 Developer Kit `liveimport.ini` 读取 `[Configuration]`。
4. 调用 `InitializeLiveImportEx()` 初始化 LiveImport。
5. 调用 `SendNotification(eStartCaptureToFile)` 启动 Capture。
6. 调用 `SendFrame3()` 写入 HCI Reset command/event。
7. 调用 `SaveCapture()` 保存 `.cfax`。

关键点：Developer Kit 的 `ConnectionString=FTS4BT Live Import.` 在当前 Virtual Sniffing 实例上不会 ready；必须使用 product root 的 `Wireless Protocol Suite Live Import...` 连接串。但 Developer Kit 的 `[Configuration]` 包含 `SdeName=Octets` 等字段，实测对正确显示 HCI 数据有帮助。

## 脚本结构

`WirelessProtocolSuite_live_virtual_sniffer.py` 是自包含脚本，只有 WPS Virtual Sniffing + LiveImport 这条链路，不包含 Ellisys 逻辑，也不包含 WPS Automation Server 的非 Virtual 分支。

```text
WirelessProtocolSuite_live_virtual_sniffer.py
  常量:
    DEFAULT_WPS_PATH
    LIVEIMPORT_CONNECTION_STRING
    HCI_RESET_COMMAND / HCI_RESET_COMMAND_COMPLETE

  LiveImport 配置:
    default_wps_liveimport_ini()
    default_developer_kit_liveimport_ini()
    read_liveimport_settings_from_ini()
    build_liveimport_config()

  WPS 启动:
    launch_wps_liveimport_mode()

  HCI 注入:
    WpsLiveImportInjector.initialize()
    WpsLiveImportInjector.wait_until_ready()
    WpsLiveImportInjector.start_capture()
    WpsLiveImportInjector.send_hci_reset()
    WpsLiveImportInjector.save_capture()

  运行入口:
    run_wps_live_virtual_sniffer()
  parse_args()
  main()
```

脚本固定选择 Virtual 模式：

```text
Fts.exe /ComProbe Protocol Analysis System=Generic /oemkey=Virtual
ConnectionString = product root liveimport.ini
Configuration = Developer Kit liveimport.ini
keep_open = not --close-after-run
```

脚本不提供 comment fallback。`SendFrame3()` 失败时应直接报错，因为只写 Message/Comment 不能证明 HCI frame 注入成功。

## 本机依赖

```text
WPS:
C:\Program Files (x86)\Teledyne LeCroy Wireless\Wireless Protocol Suite 4.60

Fts.exe:
C:\Program Files (x86)\Teledyne LeCroy Wireless\Wireless Protocol Suite 4.60\Executables\Core\Fts.exe

LiveImport DLL:
C:\Program Files (x86)\Teledyne LeCroy Wireless\Wireless Protocol Suite 4.60\Executables\Core\LiveImportAPI_x64.dll

Product liveimport.ini:
C:\Program Files (x86)\Teledyne LeCroy Wireless\Wireless Protocol Suite 4.60\liveimport.ini

Developer Kit liveimport.ini:
C:\Program Files (x86)\Teledyne LeCroy Wireless\Wireless Protocol Suite 4.60\Live Import Developers Kit\liveimport.ini
```

## HCI 数据格式

LiveImport `SendFrame3()` 传入的是 HCI payload，不带 H4 packet type。

```text
HCI Reset Command:
03 0C 00

HCI Reset Command Complete Event:
0E 04 01 03 0C 00
```

frame 参数：

```text
Command:
drf = Command
stream = Host

Event:
drf = Event
stream = Controller
```

## 使用说明

```powershell
Set-Location "H:\github\bluetooth\pybluehost\pybluehost\tools"
python -u .\WirelessProtocolSuite_live_virtual_sniffer.py `
  --wps-path "C:\Program Files (x86)\Teledyne LeCroy Wireless\Wireless Protocol Suite 4.60" `
  --record-seconds 5 `
  --pre-send-delay 5 `
  --repeat-count 2 `
  --repeat-interval 1 `
  --save-capture-path "wps_hci_reset_live_demo.cfax"
```

参数说明：

```text
--wps-path
  WPS 安装目录。

--record-seconds
  发送 HCI frame 后继续等待的秒数。

--pre-send-delay
  Start Capture 后、发送 HCI frame 前等待的秒数。

--repeat-count
  注入 HCI Reset command/event 的组数。

--repeat-interval
  多组 HCI Reset 之间的间隔。

--save-capture-path
  保存 .cfax 的路径。传空字符串可跳过保存。

--close-after-run
  默认不关闭 WPS，便于人工检查；加该参数后先等待 WPS flush 已保存抓包，再停止脚本启动的 WPS 进程。
```

## 实测记录

2026-05-24 使用独立入口实测：

```powershell
Set-Location "H:\github\bluetooth\pybluehost\pybluehost\tools"
python -u .\WirelessProtocolSuite_live_virtual_sniffer.py `
  --record-seconds 5 `
  --pre-send-delay 5 `
  --repeat-count 2 `
  --repeat-interval 1 `
  --save-capture-path "wps_live_script_actual_test.cfax"
```

关键输出：

```text
LiveImport IsAppReady=true initialization_status=0
Start Capture via LiveImport SendNotification(eStartCaptureToFile)
Send HCI Reset command/event frames (1/2)
Send HCI Reset command/event frames (2/2)
SaveCapture: wps_live_script_actual_test.cfax
```

单文件版在 `--close-after-run` 模式下会在 `SaveCapture()` 后额外等待几秒再关闭 WPS；实测如果保存后立即结束 FTS，可能出现 API 返回成功但 `.cfax` 尚未落盘或未包含 HCI frame 的情况。

产物：

```text
wps_live_script_actual_test.cfax
wps_live_script_actual_test.fsc
```

`wps_live_script_actual_test.cfax` 大小为 `98304` 字节，文件内能找到 HCI Reset Event payload `0E 04 01 03 0C 00`。

## 常见问题

### WPS 打开了但没有 HCI Reset

优先检查 Capture 是否真的启动。当前脚本使用 `SendNotification(eStartCaptureToFile)`，如果 WPS UI 仍显示 `Start Capture` 按钮，说明 Capture 没有进入运行状态。

### LiveImport 一直不 ready

检查连接串来源。当前有效组合是：

```text
ConnectionString: product root liveimport.ini
Configuration:    Developer Kit liveimport.ini
```

不要直接使用 Developer Kit 的 `ConnectionString=FTS4BT Live Import.` 连接当前 Virtual Sniffing 实例。

### 只有注释，没有 HCI frame

说明走到了旧的 `SendComment()` fallback。当前独立脚本默认禁用 fallback，如果 `SendFrame3()` 失败应直接报错，而不是伪装成注释成功。
