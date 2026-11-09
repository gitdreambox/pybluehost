# EATT 多 Bearer（Enhanced ATT）设计 — GATT server 侧

> **日期**：2026-09-17　**分支**：`claude/eatt-multi-bearer`（worktree `.claude/worktrees/eatt-multi-bearer`，基线 master@7bed880，即 pts-testing squash 合入后）
> **范围**：**仅 LE、仅 GATT server 侧**。CL 侧（IUT 在指定 bearer 上主动发 ATT 请求）auto-pts master 无对应 BTP 命令（`btp_gatt_client.txt` 无 bearer 参数），无法被驱动，不做。BR/EDR EATT 不做（本机 LE-only 测试座架）。

## 1. 目标与背景

为 PTS GATT/SR 的 EATT 多 bearer 用例解锁（矩阵当前 verdict）：

| 用例 | 现状 | 测试内容（GATT.TS p26） |
|---|---|---|
| GATT/SR/GAR/BV-11-C | fail | Unenhanced ATT + EATT 混合：两条 bearer 上并发 Read Multiple Variable，各自回各自 bearer |
| GATT/SR/GAR/BV-12-C | fail | 纯 EATT：同上，两条都是 EATT bearer |
| GATT/SR/GAW/BV-12-C | fail | 多 bearer 轮发 Prepare Write + 单次 Execute Write 全部生效（prepare 队列跨 bearer 共享） |
| GATT/SR/GPM/BV-05-C | inconc | CCCD per-client：bearer 2 写的 CCCD 在 bearer 1 上读得到（跨 bearer 一致） |
| GATT/SR/GAC/BI-01-C | （矩阵未收） | EATT bearer 上的 Exchange MTU 必须拒 0x06 Request Not Supported |

另有 L2CAP/TIM/BV-03-C（EATT 碰撞回退）——initiator 侧 L2CAP 已实装，本设计补齐 server 侧后顺带获得真机验证机会。

## 2. 已核实的 spec / auto-pts 事实（设计依据）

1. **EATT 信道 = Enhanced Credit-Based 信道，固定 SPSM 0x0027**（Core Vol 3 Part A；已实装 `connect_eatt_channels()`，含 TIM/BV-03 碰撞回退）。
2. **EATT bearer 上不做 Exchange MTU**（GATT.TS §4.2.5：「not applicable over the Enhanced ATT bearer on LE transport since the MTU size is negotiated using L2CAP channel configuration procedures」）。server 收到 EATT bearer 上的 Exchange MTU Request 必须回 `ATT_ERROR_RSP(Request=0x02, Handle=0x0000, Error=0x06)`（GATT/SR/GAC/BI-01-C 的 Pass 判据）。
3. **EATT bearer 的 ATT_MTU = L2CAP 信道协商 MTU**（≥64，LE_MTU 下限已由 `LE_MIN_CREDIT_BASED_MTU` 强制）。
4. **EATT 只在加密链路上建立**（Core Vol 3 Part G §5.2）。入向侧由 listener `required_security=4`（encryption → 拒 0x0008）承载，复用 `_LE_SECURITY_CHECK` 既有映射。
5. **响应必须回到请求所在的 bearer**；不同 bearer 上的请求可并发（GAR/BV-11/12 的 MSC 明确"concurrently"）。
6. **Prepare Write 队列按 client（连接）共享**，单次 Execute Write 执行全部（GAW/BV-12 MSC：多信道轮发 prepare，一次 execute）。
7. **CCCD 按 client（连接）共享**，与 bearer 数无关（GPM/BV-05，Core [11] 3.3.3）。
8. **Robust Caching 的 "Database Out Of Sync sent once" 标记是 per-BEARER**（Core Vol 3 Part G Figure 2.7；代码注释已预见，`synced_pending` 目前按连接存 bool）。
9. **SSF（Server Supported Features, 0x2B3A）EATT supported = octet 0 bit 0（0x01，Core Vol 3 Part G Table 7.11）**；GAW/BV-12 与 GAC/BI-01 的 Initial Condition 都要求置 1。当前 PTS 标准服务里写死 `0x00`。
10. **CSF（Client Supported Features, 0x2B29）EATT 位 0x02**：preamble 4.2.3.1 由 PTS 写入，server 侧只需正确存储/读取（已具备）。
11. **BTP 线格式**：GATT `EATT_CONNECT(0x1f)` body = `addr_type(1)+addr(6,LE)+num(1)`；L2CAP `DISCONNECT_EATT_CHANS(0x09)` body = `addr_type(1)+addr(6,LE)+channel_count(1)`（auto-pts `l2cap_disconn_eatt_chans` packer 逐字节核对）。两者响应均无参数。WID 144 用 0x09。

## 3. 架构（方案 A：bearer 键控 + mux 复用）

```
PTS ──ECFC 0x17 (SPSM 0x0027)──► L2CAPManager._handle_incoming_ecfc_request
                                     │ listener PSM_EATT, required_security=4 (enc)
                                     ▼
                                Stack._on_inbound_eatt(channel)
                                     │ _bind_gatt_server_to_channel(channel)
                                     ▼
每个 EATT LECoCChannel: install_att_channel_mux + _att_server_handler
                                     │ on_att_data(data, conn_handle, bearer_cid=channel.cid)
                                     ▼
                GATTServer.handle_request(conn_handle, pdu, *, bearer_cid)
                                     │ per-bearer:  ATT_MTU、DoS 标记  ← 键 (conn_handle, bearer_cid)
                                     │ per-conn 共享: prepare queue、CCCD、security、robust 其余
                                     ▼
                响应由 closure 从【同一信道】发回
```

出向（BTP `EATT_CONNECT`）：`connect_eatt_channels()` 成功后对每个信道做同一个 `_bind_gatt_server_to_channel`，然后回 SUCCESS。

### 为何不新建抽象（方案 B/C 否决记录）

- `GATTServer` 全部 per-connection 状态按 `conn_handle` 键控，恰好就是 TS 要求的「per-client 共享」语义——prepare 队列、CCCD、安全状态、robust caching 主状态**一行不用动**。
- 唯一的新状态轴是 bearer（ATT_MTU、DoS 标记）。用 `(conn_handle, bearer_cid)` 元组键控是最小增量；固定通道 `CID_ATT=0x0004` 作为默认 bearer 键，`handle_request` 加带默认值的 `bearer_cid` 参数 → 现有全部调用点与 ~120 个已 PASS 的 GATT/SR 用例行为零变化。
- 并发不需要额外工作：每条 EATT 信道有独立 ACL 读任务 → 独立 dispatch；共享 db 只读 + asyncio 单线程，无锁。

## 4. 改动清单（按层）

### 4.1 L2CAP（`pybluehost/l2cap/manager.py`）

- 无协议改动。仅由 Stack 注册 EATT listener（见 4.3）。
- 确认 listener handler 对多信道 ECFC 请求逐信道回调（实现时核对 `_handle_incoming_ecfc_request` 的 handler 调用点；若不是逐信道回调则修正为逐信道）。

### 4.2 ATT/GATT（`pybluehost/ble/gatt.py`）

- `handle_request(conn_handle, pdu, *, bearer_cid: int = CID_ATT)`。
- `_conn_mtu: dict[tuple[int, int], int]`，键 `(conn_handle, bearer_cid)`：
  - 固定通道：默认 23，Exchange MTU 更新（现状不变）；
  - EATT bearer：attach 时初始化为**信道 L2CAP MTU**（≥64）；其上的 Exchange MTU Request 回 `0x06 Request Not Supported`（GAC/BI-01），不更新。
- `_RobustClientState.synced_pending: bool → set[int]`（bearer_cid 集合）。固定通道行为等价（集合里只会有 0x0004）。
- `remove_connection`：清掉该连接全部 `(conn_handle, *)` MTU 键（防 handle 复用读陈旧状态——`_le_conn_security` 同族教训）。bearer attach 时重置该 bearer 的 MTU 条目（防 CID 复用）。
- 响应截断、Read Blob 等所有用 `_att_mtu` 的地方透传 `bearer_cid`。
- SSF 值 `0x00 → 0x01`（见 4.4，在 PTS 标准服务侧改）。

### 4.3 Stack（`pybluehost/stack.py`）

- 从 `_attach_gatt_server_to_att_channels` 抽出 `_bind_gatt_server_to_channel(channel, *, bearer_cid)`：mux 安装 + `_att_server_handler`（closure 捕获 conn_handle 与 bearer_cid）+ `_att_confirmation_handler` + `_gatt_server_bound` 幂等位 + `on_connection_opened` flush 保持只在固定通道路径触发一次。
- `_attach_gatt_server_to_att_channels` 末尾注册 EATT listener（幂等）：`l2cap.listen_le_coc_channel(PSM_EATT, self._on_inbound_eatt, required_security=4)`；`_on_inbound_eatt(channel)` → `_bind_gatt_server_to_channel(channel, bearer_cid=channel.cid)`。
- BTP EATT_CONNECT 成功后走同一 `_bind`（见 4.4）。

### 4.4 BTP（`pybluehost/pts/btp/services/gatt.py` + `services/l2cap.py`）

- `_handle_op_1f`（EATT_CONNECT）：connect 成功后对每个返回信道 `_bind_gatt_server_to_channel`；行为对 TIM/BV-03 的容错语义不变（失败仍回 FAILED，WID 255 容忍）。
- `_standard_gap_gatt_services`：SSF `0x2B3A` value `b"\x00" → b"\x02"`。
- L2CAP service 新增 `_handle_op_09`（DISCONNECT_EATT_CHANS）：解析 `addr_type+addr+count`，按 peer 解析连接，按 CID 升序断开该连接上前 `count` 条 EATT 信道（`disconnect_le_coc_channel`；`count` 超过现存数则全部断开），回 SUCCESS。

### 4.5 显式不做（YAGNI 边界）

- CL 侧 per-bearer 发起 ATT 请求（无 BTP 驱动入口）。
- 通知/指示经 EATT bearer 发送（目标用例不需要；维持固定通道发送）。
- EATT opcode 禁令的完整 enforcement（如 Signed Write 上 EATT 的处理）——目标用例不测。
- BR/EDR EATT（GPM/BV-02/03/04/06、GAC/BI-03 等）。
- 出向 EATT 的加密硬门（TIM/BV-03 容错路径依赖"尽量发出去"；入向已有加密门）。

## 5. 错误处理

| 场景 | 行为 |
|---|---|
| 未加密链路上的入向 EATT 请求 | listener 拒 `0x0008`（Insufficient Encryption），复用 `_LE_SECURITY_CHECK` |
| EATT bearer 上收 Exchange MTU | 回 `0x06 Request Not Supported`（GAC/BI-01 判据） |
| 双 bearer 并发请求 | 各自信道的 handler 并发处理，各回各道 |
| bearer 信道中途断开 | 响应 send 失败 → log + 丢弃；连接断开时清全部 per-bearer 状态 |
| handle/CID 复用 | attach 重置该 bearer MTU；remove_connection 清 `(conn_handle, *)` |

## 6. 测试策略

- **TDD**（项目强制）：每步先写失败测试。
- `tests/unit/ble/test_gatt_eatt.py`：
  - 双 EATT bearer 并发 Read Multiple Variable，各自 bearer 上收响应（GAR/BV-12）
  - 混合 fixed+EATT（GAR/BV-11）
  - per-bearer MTU：EATT bearer 初始 MTU=信道 MTU；Exchange MTU 在 EATT bearer 拒 0x06 且不影响固定通道 MTU（GAC/BI-01）
  - 跨 bearer Prepare Write 轮发 + 单 Execute 全提交（GAW/BV-12）
  - bearer 2 写 CCCD、bearer 1 读回（GPM/BV-05）
  - DoS 标记 per-bearer：change-unaware client 在每条 bearer 上各拿一次 0x12
  - SSF 报 EATT 位
- `tests/unit/l2cap/`：EATT listener 加密门（未加密拒 0x0008）、入向信道 attach 回调。
- `tests/unit/pts/btp/`：0x1f 连接后 server 在 EATT 信道端到端应答（fake 信道）；0x09 断连指定数目的 EATT 信道。
- **集成**：`tests/e2e/test_le_coc_lifecycle.py` 加 VirtualLELink 双 EATT 信道 loopback。
- **真机收割**：`scripts/pts_harvest.sh` 跑 GAR/BV-11、GAR/BV-12、GAW/BV-12、GPM/BV-05（+ GAC/BI-01），`scripts/pts_import_verdicts.py` 录矩阵。
- **回归守卫**：`tests/unit/ble/`、`tests/unit/pts/`、`tests/unit/l2cap/` 全绿；真机抽跑 GATT/SR/GAR/BV-01-C（固定通道路径）确认零回归。

## 7. 完成标准

1. 全套单测/集成测试绿（除 3 个既有 e2e 环境失败：test_le_lifecycle 的 StopIteration，master 上同样失败，与本特性无关）。
2. 目标用例真机 verdict 收割并录入矩阵（PASS，或定性为硬件/PTS 侧限制并记录 notes）。
3. AGENTS.md「已交付子系统」更新（EATT 小节 + 若踩新坑补「已知问题与经验」），README 无需改（无新 CLI）。
4. 合并回 master（`--ff-only` 或 merge commit，视届时 master 进展）。
