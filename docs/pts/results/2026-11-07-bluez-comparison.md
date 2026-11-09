# 2026-11-07 BlueZ / WSL 对照实验：blocked 用例实测

> 承接 [2026-11-04-bluez-comparison.md](2026-11-04-bluez-comparison.md)（当时 USB 移交在 `VBoxUSBMon` 启动阶段失败，BlueZ 实跑用例数为 0）。本日 usbipd attach 已可用，BlueZ 首次真正跑 blocked 用例。
>
> **状态：已完成（2026-11-07 17:12）** —— 22 例全部跑完，**零 PASS**。

## 结论

**BlueZ 没有通过任何一个 blocked 用例，也没有任何一条 PyBlueHost `blocked` 判定被推翻。**

27 个 blocked 用例分三类：

| 类别 | 数量 | 含义 |
|---|---|---|
| **可对照，blocked 确认** | 8 | BlueZ 到达同一阶段并同样失败，签名吻合（LT 死空气 / 无 WID 406 / passkey `int(None)`） |
| **不可对照：btpclient 能力缺失** | 14 | BlueZ 在 pre_condition 或首个用例步骤就 BTP ERROR，到不了签名所在阶段 |
| **不可对照：未入批次** | 5 | L2CAP 2 + GATT 3（同上，btpclient 无该 service） |

**没有「BlueZ PASS」**，因此 `docs/pts/results/matrix/*.yaml` 里 27 条 `blocked` 全部维持原样，无需 `--force` 重开。

> ⚠️ 最直接的确认：`SM/PER/SCPK/BI-05-C` 在 BlueZ 上复现出与 PyBlueHost 笔记**逐字相同**的签名——`Timeout after 5 seconds while waiting for event ... self.passkey.data` → `TypeError: int() argument must be ... not 'NoneType'` → FATAL ERROR。同一 auto-pts 侧缺陷，两个独立 IUT 都踩到。

## 环境（本日实测值）

| 项目 | 值 |
|---|---|
| BlueZ checkout | `14bd6ab65f4a647302edbd6df27f6faa91bee8a8`，btpclient `--version` = `5.87` |
| auto-pts checkout | `39d07081dbbe814418a17c0bac38de774b9d4eae` |
| 工作目录（WSL） | `/home/wwdeng/bluez-ab` |
| btpclient | `/home/wwdeng/bluez-ab/bluez/client/btpclient/btpclient` |
| Python 环境 | `/home/wwdeng/bluez-ab/venv` |
| PTS server 端口 | `64874`（Windows，PID 见 `Get-NetTCPConnection`） |
| client callback 端口 | `59970` |
| workspace | `runs/phase2/workspace/zephyr-master/zephyr-master.pqw6`（传给 PTS.exe 须用 Windows 路径 `H:\...`） |
| PTS dongle | `FC:9E:53:D5:8D:EB` → per-case 日志根 `_FC9E53D58DEB` |
| BlueZ IUT 地址 | public `5C:67:83:02:42:D3`（btpclient 报告的 `'random'` 是上报怪癖，`hciconfig`/`bluetoothctl show` 均为 public） |

## 复现性补丁（相对 upstream auto-pts）

1. `autopts/ptsprojects/bluez/__init__.py` 移除 `bap` import（本机未装 BAP 依赖）。
2. `bluez/gap.py` / `bluez/sm.py` 加 `_safe_set_pixit` / `_safe_update_pixit_param` 守卫：本 PTS 构建丢弃了 `TSPX_iut_privacy_enabled` 等若干 PIXIT，`set_pixit`/`update_pixit_param` 会 server 端抛 `BadPixitException … PIXIT_PARAM_NOT_FOUND`，必须在调用方 catch（不在 `ptscontrol.py`）。守卫 helper 用 `getattr(pts, "update_pixit_param")(...)` 避免自递归。
3. `run-case.sh`：每例跑完把 `autoptsclient-bluez_<cli>.log`（每例被截断覆盖的 DEBUG trace）`cp` 成 `results/<case>.client.log`，保留 per-case 签名。
4. `run-blocked.sh` / `launch-batch.sh` / `summary-batch.sh` / `watch-batch.sh`：22 例顺序批次 + 结果汇总 + 逐例 verdict 监视。

## btpclient 能力边界（本次实验最重要的结构性发现）

BlueZ 5.87 的 `client/btpclient/gap.c`（2779 行）只注册了约 20 个 GAP BTP opcode：

```text
CONNECT, DISCONNECT, PAIR, PASSKEY_CONFIRM_RSP, PASSKEY_ENTRY_RSP,
READ_CONTROLLER_INDEX_LIST, READ_CONTROLLER_INFO, READ_SUPPORTED_COMMANDS,
RESET, SET_BONDABLE, SET_CONNECTABLE, SET_DISCOVERABLE,
SET_EXTENDED_ADVERTISING, SET_IO_CAPA, SET_POWERED,
START_ADVERTISING, START_DISCOVERY, STOP_ADVERTISING, STOP_DISCOVERY, UNPAIR
```

`grep -rniE "padv|periodic|create_sync" gap.c` **零命中**：没有周期广播（PADV）、没有 BIS/BIG、没有 privacy、没有 conn-param-update、没有 subrate。`gatt.c` 只有 8 个 client opcode，**没有任何 GATT server opcode**；`core.c` 不注册 L2CAP service。

因此下列 blocked 用例在 BlueZ 上**结构性不可对照**——不是 BlueZ 协议失败，而是 btpclient 没有对应 BTP 入口，命令一律回 `BTP_STATUS_FAILED` → auto-pts client 抛 `BTPError("Error opcode in response!")`：

| 用例 | btpclient 缺什么 |
|---|---|
| L2CAP/COS/CED/BI-29-C | 无 L2CAP BTP service |
| L2CAP/COS/ECFC/BV-04-C | 同上 |
| GATT/CL/GAD/BV-03-C | gatt.c 无 FIND_INCLUDED_SVCS |
| GATT/SR/GAN/BV-02-C | gatt.c 无 server opcode（另需 LT2） |
| GATT/SR/GAW/BV-01-C | gatt.c 无 server opcode |
| GAP/PADV/PASE/BV-01..06-C（6 例） | gap.c 无 PADV create_sync 等 |
| GAP/PADV/PAM/BV-01-C | 同上 |
| GAP/PADV/PASM/BV-01-C | 同上 |
| GAP/PADV/PAST/BV-01-C、BV-02-C | 同上 |
| GAP/BIS/BBM/BV-01-C、BSE/BV-01-C | gap.c 无 BIS/BIG |
| GAP/SEC/SEM/BV-23-C | pre_condition GATT 发现需 server db，btpclient 没有 |
| GAP/SEC/AUT/BV-13-C、BV-14-C | 同上（ES-28650 阶段根本到不了） |

共 **20 例**。这些用例的 PyBlueHost `blocked` 判定既未被 BlueZ 确认、也未被推翻——BlueZ 只是跑不到签名所在阶段。

## 逐例结果

> 判定列：
> - **与 blocked 一致** —— BlueZ 也超时/挂死/FAIL，签名同 PyBlueHost 笔记（LT 死空气 / 用例脚本缺陷），blocked 判定成立。
> - **BlueZ 早失败，不可复现 blocked 签名** —— BlueZ btpclient 在 pre_condition（多为 GATT 发现，因 btpclient 是 GATT-client-only）就 BTP ERROR，到不了 PyBlueHost 笔记记录的 LT 交互阶段；blocked 既未被确认也未被推翻，但 BlueZ 确实也过不了。
> - **BlueZ PASS** —— 说明 PyBlueHost 的 blocked 属实现/固件 bug，应 `--force` 重开。

| 用例 | BlueZ verdict | 签名 | 判定 |
|---|---|---|---|
| GAP/SEC/AUT/BV-27-C | PTS TIMEOUT 346.536 | WID 78 → GAP_CONNECT → is_connected 30s 超时 | 与 blocked 一致 |
| GAP/SEC/SEM/BV-45-C | PTS TIMEOUT 349.636 | 同上 | 与 blocked 一致 |
| GAP/BROB/OBSV/BV-06-C | PTS TIMEOUT 349.619 | 同上 | 与 blocked 一致 |
| GAP/CONN/DCON/BV-04-C | FAIL 37.611 | 仅 WID 20001，无 406/407（LT 从不要求 directed adv） | 与 blocked 一致（FAIL 而非 TIMEOUT，但同根因） |
| GAP/SEC/SEM/BV-23-C | BTP ERROR 18.648 | pre_condition 未到 WID 550；btpclient 无 GATT server | BlueZ 早失败，不可复现（blocked=MissingWIDError@WID 550） |
| GAP/SEC/AUT/BV-13-C | BTP ERROR 4.205 | GATT disc_prim_uuid(0xAA51) → btpclient 回 FAILED | BlueZ 早失败，不可复现（blocked=ES-28650） |
| GAP/SEC/AUT/BV-14-C | BTP ERROR 4.182 | 同上 | BlueZ 早失败，不可复现（blocked=ES-28650） |
| GAP/PADV/PASE/BV-01-C | BTP ERROR 9.172 | `gap_padv_create_sync` → btpclient 回 FAILED | 不可对照（btpclient 无 PADV） |
| GAP/PADV/PASE/BV-02-C | BTP ERROR 9.121 | 同上 | 不可对照（btpclient 无 PADV） |
| GAP/PADV/PASE/BV-03-C | BTP ERROR 18.219 | 同上 | 不可对照（btpclient 无 PADV） |
| GAP/PADV/PASE/BV-04-C | BTP ERROR 20.533 | 同上 | 不可对照（btpclient 无 PADV） |
| GAP/PADV/PASE/BV-05-C | PTS TIMEOUT 346.529 | WID 20100 答 OK 后 LT 死空气 6 分钟 | 与 blocked 一致（BlueZ 也过不了） |
| GAP/PADV/PASE/BV-06-C | 无 verdict（`timeout 420` 杀，exit=124） | 挂死 | 与 blocked 一致（BlueZ 也过不了） |
| GAP/PADV/PAM/BV-01-C | BTP ERROR 8.116 | no PADV（btpclient 无该 opcode） | 不可对照（btpclient 无 PADV） |
| GAP/PADV/PASM/BV-01-C | BTP ERROR 9.211 | 同上 | 不可对照（btpclient 无 PADV） |
| GAP/PADV/PAST/BV-01-C | BTP ERROR 15.613 | 同上 | 不可对照（btpclient 无 PADV） |
| GAP/PADV/PAST/BV-02-C | PTS TIMEOUT 347.626 | WID 20100 答 OK 后 LT 死空气 | 与 blocked 一致（BlueZ 也过不了） |
| GAP/BIS/BBM/BV-01-C | BTP ERROR 9.368 | no BIS（btpclient 无该 opcode） | 不可对照（btpclient 无 BIS） |
| GAP/BIS/BSE/BV-01-C | BTP ERROR 9.216 | 同上 | 不可对照（btpclient 无 BIS） |
| GAP/SEC/SEM/BI-13-C | BTP ERROR 11.403 | WID 301 → error opcode | BlueZ 早失败，不可复现 |
| SM/CEN/SCPK/BI-03-C | BTP ERROR 68.56 | WID 100 connect → error opcode | BlueZ 早失败，不可复现（blocked=passkey `int(None)`，BlueZ 到不了那一步） |
| SM/PER/SCPK/BI-05-C | **FATAL ERROR** | `Timeout ... self.passkey.data` → `TypeError: int() ... not 'NoneType'` | 与 blocked 一致（**逐字相同签名**） |

## 后续

- **27 条 `blocked` 全部维持原样，不 `--force` 重开**（BlueZ 零 PASS，无一条被推翻）。
- 批次总耗时 16:15:02 → 17:12:06（约 57 分钟），单例单 autoptsclient 会话顺序执行。
- btpclient 能力边界（PADV / BIS / L2CAP / GATT server）是**结构性**结论：即使换更新的 BlueZ，只要 `gap.c`/`gatt.c` 不扩这些 BTP opcode，这 19 例就永远无法用 auto-pts 方式对照；要真正复核它们需换参考实现（如 zephyr 的 `ptsprojects/zephyr`）或 PTS 手动 workspace。
- 若要对 8 例「与 blocked 一致」的做进一步取证（尤其 `SM/PER/SCPK/BI-05` 的逐字 FATAL 签名，以及 LT 死空气簇），可复用本日 `run-case.sh` + per-case `.client.log` 保留。
