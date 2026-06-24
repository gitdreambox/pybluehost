# Ellisys_live_virtual_sniffer.py 设计实现文档

## 目标

`Ellisys_live_virtual_sniffer.py` 是一个最小可运行的 Ellisys HCI Injection demo。它用于启动 Ellisys Bluetooth Analyzer，选择 `Ellisys Injection API` 数据源，并通过 UDP HCI Injection API 写入可见的 HCI Reset Command / Command Complete Event。

验收标准：

- Ellisys 自动启动并开始 Recording。
- 数据源选择为 `Ellisys Injection API`。
- HCI Injection Overview 能看到 HCI Reset。
- Remote Control 递归读取 trace tree 时能看到 `03 0C 00` 和 `0E 04 01 03 0C 00`。

## 参考来源

本实现参考了以下资料和本地文件：

```text
Bluetooth SIG Ellisys Remote Control Plugin 安装说明:
https://support.bluetooth.com/hc/en-us/articles/15810974858253-Ellisys-Analysis-Software-Installing-the-Remote-Control-Plugin

Ellisys Remote Control API:
https://downloads.ellisys.com/bta_remote_api.zip
C:\Users\Administrator\Downloads\bta_remote_api.zip
E:\Bluetooth PTS\work\sniffer_remote\bta_remote_api

Ellisys HCI Injection API:
https://www.ellisys.com/better_analysis/bex400a_injection_api.zip
E:\Bluetooth PTS\work\sniffer_remote\bex400a_injection_api.zip
E:\Bluetooth PTS\work\sniffer_remote\bex400a_injection_api

Ellisys Injection API 文档:
E:\Bluetooth PTS\work\sniffer_remote\bex400a_injection_api\Ellisys Injection API.pdf
E:\Bluetooth PTS\work\sniffer_remote\bex400a_injection_api\Ellisys Bluetooth Analyzer Injection API.pdf

Ellisys sample:
E:\Bluetooth PTS\work\sniffer_remote\bex400a_injection_api\Samples\Ellisys.Injection\EllisysInjectionUtil.cs
E:\Bluetooth PTS\work\sniffer_remote\bex400a_injection_api\Samples\BtSnoopHciClient\Program.cs

PTS sniffer 分析文档:
E:\Bluetooth PTS\PTS_Sniffer_Remote_Control_Analysis.md
```

补充参考：

```text
Android btsnoop live 思路参考:
https://android.googlesource.com/platform/system/bt/+/ea7ab70a711e642653dd5922b83aa04a53af9e0e/tools/scripts/btsnoop_live.py

HCI logging tool 思路参考:
https://github.com/xihua13104/HCI_Logging_tool
```

这些 btsnoop/HCI logging 参考用于理解 HCI command/event 数据和 live stream 场景；最终 Ellisys 实现没有直接发送 btsnoop 文件格式，而是按 Ellisys HCI Injection API 的 UDP packet 格式发送。

## 设计结论

Ellisys 需要区分两套 API：

- Remote Control API：负责启动/停止 recording、选择 data source、保存 trace、插入 message/comment、读取 trace tree。
- HCI Injection API：负责通过 UDP 发送真正的 HCI packet，让 Ellisys 解码成 HCI Injection 数据。

只使用 `bta_remote_api.zip` 的 Remote Control API，只能插入 Message Log，不能产生 HCI Injection frame。要在 HCI Injection Overview 中看到 HCI Reset，必须启动 `/injection_api_port` 并向该 UDP 端口发送 HCI Injection API packet。

当前实现采用单文件设计：`Ellisys_live_virtual_sniffer.py` 内部包含启动 Ellisys、Remote Control 选择 injection 数据源、开始 recording、生成 HCI Injection UDP packet、停止并保存 trace 的全部逻辑，不再依赖 `hci_reset_visibility_demo.py`。

## 脚本结构

`Ellisys_live_virtual_sniffer.py` 是自包含脚本，只有 Ellisys Remote Control + HCI Injection 这条链路，不包含 WPS 逻辑。

```text
Ellisys_live_virtual_sniffer.py
  常量:
    DEFAULT_ELLISYS_PATH
    DEFAULT_ELLISYS_TCP_PORT / DEFAULT_ELLISYS_UDP_PORT
    HCI_RESET_COMMAND / HCI_RESET_COMMAND_COMPLETE

  HCI Injection packet:
    utc_datetime_ns_fields()
    prepare_ellisys_hci_injection_packet()
    send_ellisys_hci_reset_over_udp()

  Remote Control:
    wait_for_tcp_port()
    run_powershell()
    start_ellisys_hci_injection_recording()
    stop_ellisys_recording()

  运行入口:
    run_ellisys_live_virtual_sniffer()
    parse_args()
    main()
```

入口脚本默认参数：

```text
ellisys_path = DEFAULT_ELLISYS_PATH
tcp_port = 46148
udp_port = 24352
injection_host = 127.0.0.1
trace_path = 脚本同目录\ellisys_hci_reset_live_demo.btt
record_seconds = 3
pre_send_delay = 2
repeat_count = 2
repeat_interval = 1
keep_open = not args.close_after_run
```

## 本机依赖

```text
Ellisys:
C:\ProgramData\Ellisys\Ellisys Bluetooth Analyzer\Updates\current

Analyzer exe:
C:\ProgramData\Ellisys\Ellisys Bluetooth Analyzer\Updates\current\Ellisys.BluetoothAnalyzer.exe

Remote Control Plugin:
C:\ProgramData\Ellisys\Ellisys Bluetooth Analyzer\Updates\current\RemoteControl\EllisysAnalyzerBluetoothRemoteControlPlugin.dll

Ice runtime:
C:\ProgramData\Ellisys\Ellisys Bluetooth Analyzer\Updates\current\RemoteControl\Ice.dll
```

## 控制流程

启动 Ellisys：

```text
Ellisys.BluetoothAnalyzer.exe /remote_control_port=46148 /injection_api_port=24352 /suffix=PTS
```

Remote Control 连接：

```text
Ellisys.AnalyzerRemoteControl.Bluetooth:tcp -h localhost -p 46148
```

Remote Control 操作：

```text
GetAvailableDataSources()
SelectDataSource("injection")
GetSelectedDataSource()
CancelUserInteraction()
StartRecording()
InsertMessage()
```

然后 Python 通过 UDP 向 `127.0.0.1:24352` 发送 HCI Injection packet。

## HCI Injection UDP 包格式

UDP payload 不是 btsnoop 文件，也不是裸 H4。它是 Ellisys Injection API 的对象序列：

```text
ServiceId      0x0002
Version        0x01
DateTimeNs     object 0x02
Controller     object 0x83
Bitrate        object 0x80
PacketType     object 0x81
PacketData     object 0x82
```

当前 demo 写入两类 packet：

```text
HCI Reset Command:
PacketType = 0x01
PacketData = 03 0C 00

HCI Reset Command Complete Event:
PacketType = 0x84
PacketData = 0E 04 01 03 0C 00
```

注意：`PacketData` 不带 H4 packet type。Command 不加 `01`，Event 不加 `04`。

## 使用说明

推荐在脚本目录运行：

```powershell
Set-Location "H:\github\bluetooth\pybluehost\pybluehost\tools"
python -u .\Ellisys_live_virtual_sniffer.py
```

完整参数示例：

```powershell
Set-Location "H:\github\bluetooth\pybluehost\pybluehost\tools"
python -u .\Ellisys_live_virtual_sniffer.py `
  --ellisys-path "C:\ProgramData\Ellisys\Ellisys Bluetooth Analyzer\Updates\current" `
  --tcp-port 46148 `
  --udp-port 24352 `
  --injection-host 127.0.0.1 `
  --record-seconds 3 `
  --pre-send-delay 2 `
  --repeat-count 2 `
  --repeat-interval 1
```

参数说明：

```text
--ellisys-path
  Ellisys 安装目录。

--tcp-port
  Remote Control TCP 端口。

--udp-port
  HCI Injection API UDP 端口。

--injection-host
  HCI Injection API UDP 目标地址。

--trace-path
  使用 --close-after-run 时保存 .btt 的路径。

--record-seconds
  发送 HCI packet 后继续等待的秒数。

--pre-send-delay
  StartRecording 后、发送 UDP packet 前等待的秒数。

--repeat-count
  注入 HCI Reset command/event 的组数。

--repeat-interval
  多组 HCI Reset 之间的间隔。

--close-after-run
  默认保留 Ellisys recording，便于人工检查；加该参数后停止 recording 并保存 trace。
```

## 实测记录

2026-05-24 使用独立入口实测：

```powershell
Set-Location "H:\github\bluetooth\pybluehost\pybluehost\tools"
python -u .\Ellisys_live_virtual_sniffer.py `
  --record-seconds 3 `
  --pre-send-delay 2 `
  --repeat-count 2 `
  --repeat-interval 1
```

关键输出：

```text
Available data sources: Ellisys Injection API
Selected data source: injection
Current data source: Ellisys Injection API
StartRecording reported an error, but Ellisys is already recording; continuing.
sent HCI Reset UDP injection (1/2): command 27 bytes, event 30 bytes
sent HCI Reset UDP injection (2/2): command 27 bytes, event 30 bytes
```

Remote Control 读取 trace tree 验证：

```text
SelectedDataSource=Ellisys Injection API
IsRecording=True
RootChildCount=2
- HCI Reset DATA=03 0C 00
  - HCI Reset DATA=03 0C 00
  - HCI Command Complete (Command=Reset, Success) DATA=0E 04 01 03 0C 00
- HCI Reset DATA=03 0C 00
  - HCI Reset DATA=03 0C 00
  - HCI Command Complete (Command=Reset, Success) DATA=0E 04 01 03 0C 00
```

保存的 trace：

```text
E:\Bluetooth PTS\work\sniffer_remote\ellisys_live_script_actual_test.btt
```

该文件大小为 `43522` 字节。

## 常见问题

### 只有 Message Log，没有 HCI Injection

这是只用了 Remote Control 的 `InsertMessage()` 或 `InsertComment()`。它们只能写日志，不能注入 HCI frame。必须启动 `/injection_api_port=24352` 并向该 UDP 端口发送 HCI Injection API packet。

### StartRecording 报 UserInteractionPending

实测 Ellisys 可能在 `StartRecording()` 抛出 `UserInteractionPending`，但 `IsRecording()` 已经变成 true。当前实现会再次检查 recording 状态；如果已经 recording，就继续发送 UDP HCI packet。

### InsertComment 失败

`InsertComment()` 可能返回 `OperationFailed`。这不影响 HCI Injection，因为注释和 HCI packet 是两条不同路径。验证时以 HCI Injection Overview 或 Remote Control 读回的 HCI payload 为准。

### HCI Reset Event 显示为子节点

Ellisys UI/trace tree 会把 Command Complete Event 作为 HCI Reset 的子节点显示，这是正常现象。验证时要展开 HCI Reset 节点，或者用 Remote Control 递归读取子节点。

### 端口冲突

默认端口：

```text
Remote Control TCP: 46148
Injection API UDP: 24352
```

如果已有 Ellisys 实例占用端口，脚本会复用 TCP Remote Control 端口；但 UDP injection port 必须和 Ellisys 启动参数一致。
