# PTS Baseline Regression — 2026-08-18

回归验证当前 V1.2 CSR8510 manual campaign 的 8 个 active case(7 SDP + 1 L2CAP)。
驱动方式：PTS COM automation(`RunTestCase` + `TSPX_use_implicit_send=TRUE`)+
JSON IUT controller(`scripts/pts_iut_controller.py`,127.0.0.1:18766)。

## 环境

| 项目 | 值 |
|---|---|
| IUT | CSR8510 `usb:0A12:0001#1`,BD_ADDR `00:1A:7D:DA:71:11` |
| PTS dongle | Intel,本次 `GetPTSBluetoothAddress()` 返回 `5C67830704EE`(**与 runbook 记录的 `C88A9A6D5F5F` 不同——dongle 地址变了或换了 dongle**) |
| PTS version | 8.13.0.4 |
| run 目录 | `runs/pts_baseline_20260818_202100/` |

## 最终结果:8/8 PASS

| Test Case | Verdict | XML |
|---|---|---|
| `SDP/SR/SA/BI-01-C` | PASS | `runs\pts_sdp_20260622_181637\...\SDP_SR_SA_BI_01_C_2026_08_18_20_23_36.xml` |
| `SDP/SR/SA/BI-02-C` | PASS | `...\SDP_SR_SA_BI_02_C_2026_08_18_20_24_03.xml` |
| `SDP/SR/SA/BI-03-C` | PASS | `...\SDP_SR_SA_BI_03_C_2026_08_18_20_24_16.xml` |
| `SDP/SR/SS/BI-01-C` | PASS | `...\SDP_SR_SS_BI_01_C_2026_08_18_20_25_07.xml` |
| `SDP/SR/SS/BI-02-C` | PASS | `...\SDP_SR_SS_BI_02_C_2026_08_18_20_41_14.xml`(修复后) |
| `SDP/SR/SSA/BI-01-C` | PASS | `...\SDP_SR_SSA_BI_01_C_2026_08_18_20_26_28.xml` |
| `SDP/SR/SSA/BI-02-C` | PASS | `...\SDP_SR_SSA_BI_02_C_2026_08_18_20_26_45.xml` |
| `L2CAP/COS/CID/BI-01-C` | PASS | `runs\pts_iut_multi_20260622_175950\...\L2CAP_COS_CID_BI_01_C_2026_08_18_21_02_50.xml`(修复后) |

`scripts/pts_completion_check.py` 对 `docs/pts/results/v1.2-current-expected.yaml`
返回 `Status: PASS / 8/8 PASS`,exit 0。`docs/pts/results/SUMMARY.md` 已由
`pts_post_run_update.py` 重生成。

## 本次暴露并修复的两个真实 bug

### 1. SDP UINT128/SINT128 解码 `KeyError: 16` → `SDP/SR/SS/BI-02-C` INDCSV

- **现象**:PTS 连发三个非法 ServiceSearchPattern(UINT16 `09` / UINT32 `0A` /
  UINT128 `0C`),前两个正常回 `0x0003`,UINT128 直接不回 → PTS `Did not receive
  SDP_ERROR_RSP` → INDCSV。
- **根因**:`decode_data_element()` 对 UINT/SINT 用 `fmt_map = {1,2,4,8}` 查 struct
  格式,**没有 16 这个 key**。`0x0C` = UINT size_idx 4 → size 16 → `fmt_map[16]`
  抛 `KeyError: 16`,逃出 `_handle_search` 的 `except (IndexError, struct.error,
  ValueError)`,整个 L2CAP callback 吞掉、不发任何 SDP 响应。
- **历史**:`docs/PTS/results/2026-06-24-sdp.md` 记载此 fix 曾于 06-25 通过,但
  **当前工作区/HEAD 里并没有**——疑似在 branch rewrite 中丢失。本次重新实装。
- **修复**:`decode_data_element()` 对非 `{1,2,4,8}` 宽度(含 128-bit)改用
  `int.from_bytes(payload,'big',signed=...)`,UINT128/SINT128 解码成合法 Python int;
  随后 `_extract_search_uuids` 按"非 UUID 元素"拒为 `0x0003`。
- **测试**:`test_decode_data_element_supports_uint128_and_sint128` +
  `test_sdp_server_rejects_service_search_request_with_uint128_pattern`。

### 2. `l2cap-connect` 找不到 PTS 发起的入向链路 → `L2CAP/COS/CID/BI-01-C` 超时

- **现象**:MMI_263「Please send L2CAP Connection REQ to PTS」时,后台 job 发
  `l2cap-connect`,controller 一律 `TimeoutError`,PTS 始终收不到 Connection
  Request → 130s 超时 INDCSV(COM `HRESULT:0x849C0017`)。
- **根因**:`IutActions._on_connection_event` 把 PTS 发起的**入向** ACL 连接登记为
  `ConnInfo(peer=None, transport="le")`(连接事件不带对端地址,且 transport 写死
  "le")。于是 `_find_classic_handle()` 按地址+`transport="classic"` 永远匹配不到,
  落到 `actions.connect()` 试图向 PTS 发起**新的出向** ACL——PTS 测试中不会接受,
  5s 超时。SDP 能过是因为 SDP 由 PTS 主动开 PSM 1 信道、IUT 只在已建信道上回包,
  根本不走 IUT 出向 Connection Request 这条路。
- **修复**:`l2cap-connect` 在地址匹配失败时,回退到**当前唯一活跃链路**
  (`_any_active_handle()`,优先真实 classic,否则取任一在连链路 = PTS 入向链路),
  仅在完全无连接时才发起出向 `connect()`。与 `l2cap-le-connect` 已有的
  `_last_handle` 回退对齐。
- **测试**:`test_l2cap_connect_reuses_active_pts_initiated_link`。
- **验证**:修复后首次 `l2cap-connect` 即 `{"ok":true,"handle":72,"cid":64}`,
  PTS XML 出现 `Received CMD:Connection Request`,8.3s 完成 PASS。

## 操作要点(下次复用)

- PTS COM 自动化全程需**单一 COM session**:`RunTestCase` 阻塞,且 dongle 被
  PTS.exe 独占。每个 runner 开头先 `Stop-Process PTS.exe` 再 `New-Object` 重新
  select dongle,否则 `GetDeviceList()` 显示 `USB_INTEL:InUse` → 选不到。
- PowerShell 通过 TCP 给 JSON controller 发命令时,`StreamWriter` 必须用
  **无 BOM 的 UTF-8**(`New-Object System.Text.UTF8Encoding($false)`),否则
  controller 端 `json.loads` 报 `Unexpected UTF-8 BOM`。
- SDP server 侧 7 个 case 全靠 implicit send,无需 IUT 动作;L2CAP `BI-01-C` 需要
  在 PTS 建好 ACL 后由后台 job 发 `l2cap-connect`(现由修复 #2 保证落到正确链路)。
- runner 脚本在 `pybluehost/tools/*.ps1`(gitignore 的 operator scratch 区):
  `pts_cleanup.ps1` / `pts_start_controller.ps1` / `pts_probe.ps1` /
  `pts_select_dongle.ps1` / `pts_baseline_runner.ps1` / `pts_fixup_runner.ps1` /
  `pts_l2cap_runner.ps1`。
