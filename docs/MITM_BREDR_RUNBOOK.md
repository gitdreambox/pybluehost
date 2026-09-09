# BR/EDR MITM 真机 Runbook

## 拓扑
手机(adb) ⇄ BE200#1(usb:8087:0036#1, 94:53:FF:1E:6A:EE, downstream)
         ⇄ BE200#2(usb:8087:0036#2, 5C:67:83:07:04:EE, upstream) ⇄ 耳机 98:1D:F9:90:11:1E

## 前置检查
1. 耳机: MCP localhost:57666 在线; connect COM22(wpk 已上传) 开 log capture。
   固件开机自动进配对,无需 CLI。**RTS 高=上电,别绕过 MCP 动 RTS。**
   MCP 不可用时 fallback: wquart-1.2.220 脚本直抓 COM22 log。
2. 手机: adb devices 通;开发者选项开 HCI snoop log;忽略耳机的旧配对(全新配对前提)。
3. dongle: ./.venv/Scripts/python.exe -m pybluehost tools usb diagnose 两颗 BE200 全 OK;
   无残留进程(Get-CimInstance Win32_Process | ? CommandLine -match 'pts-tester|mitm')。

## 关卡执行
G0 基线: 手机直连耳机配对 → python scripts/mitm_phone.py media play → 60s →
  media pause → python scripts/mitm_phone.py pull-btsnoop baseline.btsnoop
G1/G2: mitm 启动日志里确认 recon identity 三字段(address/CoD/name)齐全。
G3: ./.venv/Scripts/python.exe -m pybluehost app mitm \
    --upstream usb:8087:0036#2 --downstream usb:8087:0036#1 \
    --target 98:1D:F9:90:11:1E --transport-mode bredr \
    --btsnoop mitm-bredr.btsnoop --key-log mitm-keys.jsonl
  手机配对弹窗: python scripts/mitm_phone.py accept-pairing
  PASS: mitm-keys.jsonl 有 phone+target 两条;target key 与耳机固件 log 逐字节一致。
G4: 手机配对后自动 service discovery;capture 见 SDP 往返。
G5: media play 60s+ → 听感无卡顿;python scripts/mitm_media_analyze.py mitm-bredr.btsnoop \
    --compare baseline.btsnoop 三项 PASS(loss/reorder/rate)。
  ⚠ 分片风险: mitm_media_analyze 不重组跨 ACL 分片。A2DP 大包(高码率)会分片,
  若 lost/rate 异常先确认是否分片所致(看 ACL PB flag),必要时给 analyze 补重组再判。
  RTP 指纹启发式若误识别 media CID,升级为跟踪 AVDTP signaling(PSM 0x0019)的 CID 映射。
G6: AVRCP 三键生效;capture 见 HFP SLC 的 BRSF→BAC→CIND→CMER。

## 故障定位(先看关卡边界)
- 手机扫不到 MITM → G2:查 impersonate 的 Write_Scan_Enable 与 CoD/name 写入
- 耳机连不上 → G3 upstream:看 Create_Connection status 重试日志;耳机是否在配对(MCP log)
- 手机连不上 → G3 downstream:看 Connection_Request/Accept 日志
- 音乐卡顿 → mitm_media_analyze 看 lost/rate;查 ACL 流控(Number_of_Completed_Packets)
