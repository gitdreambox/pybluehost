# SMP 配对状态机 — Sub-Plan 1: Legacy Just Works + 绑定 + 加密恢复

**日期**：2026-05-13
**范围**：PRD §5.4 SMP 全状态机的第 1/3 子项目
**前置 Plan**：[PRD 1.0 收尾](../plans/2026-05-12-prd-v1-closure.md)（SMP 装配 + L2CAP CID_SMP 通道绑定已完成）

---

## 1. 目标与范围

### 1.1 In scope

- LE Legacy Pairing — **Just Works** association model
- 配对双方角色：**Initiator** + **Responder**
- 阶段 1（Feature Exchange）+ 阶段 2（STK 生成 via Confirm/Random）+ 阶段 3（Key Distribution）
- LTK / EDIV / RAND / IRK / CSRK 通过 key distribution 阶段交换并持久化到 `BondStorage`
- 加密恢复：重连已绑定设备时自动启动加密（`HCI_LE_Start_Encryption` / `HCI_LE_LTK_Request_Reply`）
- 公共 API：
  - `await stack.pair(handle, *, bondable=True, timeout=30.0)` — Initiator 显式触发
  - `await stack.encrypt(handle)` — 显式调用加密恢复（默认行为是自动）
  - `StackConfig.auto_encrypt_on_bonded_reconnect: bool = True`
  - `StackConfig.bondable: bool = True`（控制 Pairing Request 的 Bonding flag）
- GATT client 自动重试：收到 ATT Error_Response `Insufficient_Encryption (0x0F)` 时调 `stack.pair(handle)` → retry 原请求一次
- 验收：loopback E2E + 真机（Android 手机）Just Works 配对成功

### 1.2 Out of scope（推迟到 Sub-Plan 2/3）

| 缺失项 | 推迟到 |
|--------|-------|
| LE Secure Connections（ECDH P-256、f4/f5/f6）| Sub-Plan 2 |
| Passkey Entry、Numeric Comparison、OOB 关联模型 | Sub-Plan 3 |
| 5 个 IO Capability 组合完整矩阵（Sub-Plan 1 只走 Just Works 路径，但保留 IO Caps 字段交换） | Sub-Plan 3 |
| ATT server 侧加密强制（`Permissions.ENCRYPTED_READ` 等） | Sub-Plan 4 |
| CTKD（BR/EDR ↔ LE 互推 keys）| 待 Classic SSP 完成后单立 |
| Privacy / RPA Resolving on reconnect | 独立 Plan |

---

## 2. 架构决策

### 2.1 状态机表示：显式 `StateMachine[S, E]`

使用现有 `pybluehost/core/statemachine.py:StateMachine[S, E]` 框架。理由：

- 与 PRD §5.7 "显式 StateMachine[StateEnum, EventEnum]" 原则一致
- 框架已有 `add_transition / fire / set_timeout / add_observer` API，复用现成基础设施
- 自带 `StateMachineTraceBridge` → 每次 transition 自动 emit trace event
- 调试时可读 `state_machine.history` 看完整序列

**备选已拒**：单 async coroutine 顺序 await PDU（状态隐式、难观察）、每 PDU 大 switch 派发（一样不可观察、不符合 PRD §5.7）。

### 2.2 状态枚举 `SMPState`

```
IDLE
  ↓ LOCAL_PAIR_REQUEST / PAIRING_REQ_RX
FEATURE_EXCHANGE
  ↓ PAIRING_RSP_RX (Initiator) / LOCAL_PAIRING_RSP_SENT (Responder)
CONFIRMING
  ↓ PAIRING_CONFIRM_RX (twice for both sides)
RANDOM_EXCHANGE
  ↓ PAIRING_RANDOM_RX (verifies confirm matches, derives STK)
STK_ENCRYPTING
  ↓ ENCRYPTION_CHANGE_SUCCESS
KEY_DISTRIBUTION
  ↓ all expected keys received per distribution masks
BONDED → IDLE (procedure complete; context destroyed)
```

任何状态收到 `PAIRING_FAILED_RX`、`TIMEOUT`、`DISCONNECTED`、`ENCRYPTION_CHANGE_FAILED` → `FAILED` 状态 → cleanup → IDLE。

状态机超时：30 秒覆盖从 IDLE 离开起到 BONDED 的全过程（Core 5.4 Vol 3 Part H §3.4）。

### 2.3 SMPPairingContext — per-connection 配对上下文

```python
@dataclass
class SMPPairingContext:
    connection_handle: int
    peer_address: BDAddress
    role: PairingRole  # INITIATOR | RESPONDER
    state_machine: StateMachine[SMPState, SMPEvent]

    # Feature exchange (filled during FEATURE_EXCHANGE state)
    local_io_caps: IOCapability
    peer_io_caps: IOCapability | None = None
    local_auth_req: int = 0  # Bondable + MITM bits
    peer_auth_req: int = 0
    local_max_key_size: int = 16
    peer_max_key_size: int = 16
    local_init_key_dist: int = 0  # LTK + IRK + CSRK bits
    peer_init_key_dist: int = 0
    local_resp_key_dist: int = 0
    peer_resp_key_dist: int = 0

    # Phase 2 working state
    tk: bytes = b"\x00" * 16            # Just Works → 0; other modes Sub-Plan 3
    local_random: bytes = b""           # 16-byte Mrand or Srand
    peer_random: bytes = b""
    local_confirm: bytes = b""          # c1(TK, rand, p1, p2)
    peer_confirm: bytes = b""
    stk: bytes = b""

    # Phase 3 collected keys (from peer)
    received_ltk: bytes = b""
    received_ediv: int = 0
    received_rand: bytes = b""
    received_irk: bytes = b""
    received_identity_address: tuple[int, bytes] = (0, b"")
    received_csrk: bytes = b""

    bondable: bool = True
    pairing_complete: asyncio.Future[None] | None = None
```

每条 LE 连接最多一个活动 context；并发 pair 请求拒绝（fire 时 `InvalidTransitionError`）。

### 2.4 角色差异

| 阶段 | Initiator（Central） | Responder（Peripheral） |
|------|---------------------|------------------------|
| 阶段 1 启动 | 主动发 `SMPPairingRequest` | 收到 Request 后回 `SMPPairingResponse` |
| 阶段 2 Confirm 顺序 | 先发本侧 Confirm，收到对方 Confirm 后发 Random | 收到 Initiator Confirm 后再发本侧 Confirm，再回 Random |
| 阶段 2 STK 派生 | `s1(TK, Srand, Mrand)`（M=initiator） | 同公式（双方算结果应一致） |
| 阶段 3 加密启动 | 调 `HCI_LE_Start_Encryption(handle, EDIV=0, RAND=0, LTK=STK)` | 等 `HCI_LE_LTK_Request` 事件，回 `HCI_LE_LTK_Request_Reply(handle, STK)` |
| 重连加密恢复 | 调 `HCI_LE_Start_Encryption(handle, EDIV, RAND, LTK)`（存的 EDIV/RAND/LTK）| 等 `LTK_Request` 事件，回 LTK_Request_Reply(handle, LTK) |

共享同一套 transition 表，每个 transition 的 action 通过 `if ctx.role == Initiator` 分支处理顺序差异。

### 2.5 加密自动恢复路径

```
LE_Connection_Complete → Stack._on_le_connection_complete(handle, peer_addr)
  → if not cfg.auto_encrypt_on_bonded_reconnect: return
  → bond = bond_storage.load(peer_addr)
  → if bond is None: return  # no prior bond
  → if role == Initiator: hci.send_command(HCI_LE_Start_Encryption(handle, bond.ediv, bond.rand, bond.ltk))
  → if role == Responder: register handle in _expected_ltk_requests[handle] = bond.ltk
                          (handled later when LE_LTK_Request arrives)
```

```
LE_LTK_Request event (Peripheral side only) → Stack._on_le_ltk_request(handle, ediv, rand)
  → if ediv == 0 and rand == b"\x00"*8: pairing-time STK; from active SMPPairingContext
  → else: bonded reconnect; look up bond.ltk where bond.ediv == ediv and bond.rand == rand
  → if found: hci.send_command(HCI_LE_LTK_Request_Reply(handle, ltk))
  → else: hci.send_command(HCI_LE_LTK_Request_Negative_Reply(handle))
```

### 2.6 GATT client 自动 pair-and-retry

```python
# In ATTBearer.request(req) or GATTClient.read/write:
try:
    return await bearer.request(req)
except ATTError as e:
    if e.code != ATT_ERROR_INSUFFICIENT_ENCRYPTION:
        raise
    await stack.pair(handle)  # blocks until BONDED or raises
    return await bearer.request(req)  # one retry
```

只在 client 侧实现；server 侧 enforcement 推迟。

### 2.7 PairingDelegate 扩展

```python
class PairingDelegate(Protocol):
    async def confirm_just_works(self, peer_addr: BDAddress) -> bool: ...
    # 已有 / 后续 Plan 的方法...

class AutoAcceptDelegate:
    async def confirm_just_works(self, peer_addr: BDAddress) -> bool:
        return True
```

仅 Just Works 一个回调；其他模式（Passkey/NC/OOB）的 delegate 方法 Sub-Plan 3 加。

---

## 3. 关键数据流

### 3.1 Initiator 发起配对（loopback E2E 典型流）

```
Test → stack_a.pair(handle=0x40)
  → SMPManager.start_initiator(handle, peer_addr)
  → SMPPairingContext(role=INITIATOR, state=IDLE)
  → fire(LOCAL_PAIR_REQUEST)
  → action: build SMPPairingRequest(io_caps=NIO, auth_req=Bond, key_dist=LTK|IRK)
            send via CID_SMP channel
  → state = FEATURE_EXCHANGE
  → ← (peer responds) SMPPairingResponse → on_pdu → fire(PAIRING_RSP_RX, rsp=...)
  → action: store peer caps; select Just Works; generate local random;
            compute local_confirm = c1(tk=0, rand, preq, pres, ia/ra types & addrs);
            send SMPPairingConfirm
  → state = CONFIRMING
  → ← SMPPairingConfirm → fire(PAIRING_CONFIRM_RX, conf=...)
  → action: store peer confirm; send local SMPPairingRandom
  → state = RANDOM_EXCHANGE
  → ← SMPPairingRandom → fire(PAIRING_RANDOM_RX, rand=...)
  → action: verify peer_confirm == c1(tk, peer_rand, ...) → mismatch=FAIL
            derive stk = s1(tk, peer_rand, local_rand)
            HCI_LE_Start_Encryption(handle, ediv=0, rand=0, ltk=stk)
  → state = STK_ENCRYPTING
  → ← HCI_Encryption_Change(success) → fire(ENCRYPTION_CHANGE_SUCCESS)
  → action: start phase 3 — generate local LTK/EDIV/RAND/IRK/CSRK per key_dist
            send SMPEncryptionInformation + SMPMasterIdentification + SMPIdentityInformation + ...
  → state = KEY_DISTRIBUTION
  → ← peer sends its keys → collect in context
  → when all expected (per peer's resp_key_dist mask): fire(KEYS_RECEIVED)
  → action: bond_storage.save(peer_addr, BondInfo(ltk=peer_ltk, ediv=peer_ediv, rand=peer_rand, irk=peer_irk, csrk=peer_csrk, peer_addr=...))
            pairing_complete.set_result(None)
  → state = BONDED → IDLE (cleanup context)
```

### 3.2 重连加密恢复（公共/静态随机地址）

```
HCI_Connection_Complete(handle, peer_addr=02:11:22:33:44:55)
  → Stack._handle_le_connection_event(handle)
  → if auto_encrypt: bond = bond_storage.load(peer_addr)
  → if bond and role == Central:
      hci.send_command(HCI_LE_Start_Encryption(handle, bond.ediv, bond.rand, bond.ltk))
      → ← HCI_Encryption_Change(handle, status=0, encryption_enabled=1)
      → emit StackConnectionEvent(state="encrypted", handle=handle)
  → if bond and role == Peripheral:
      stack._expected_ltk[handle] = bond
      → wait for LE_LTK_Request_event(handle, ediv, rand)
      → match against bond.ediv/rand → reply LTK
      → ← HCI_Encryption_Change(success) → emit "encrypted" event
```

---

## 4. 测试策略

### 4.1 单元测试（~25 新）

| 测试文件 | 测试 |
|---------|------|
| `tests/unit/ble/test_smp_state_machine.py` | 状态枚举完整性；每条 transition 单测；非法 transition 抛 `InvalidTransitionError`；30s 超时进入 FAILED |
| `tests/unit/ble/test_smp_association_model.py` | IO Caps × OOB × MITM → 选 Just Works 的逻辑表（Sub-Plan 1 限定）|
| `tests/unit/ble/test_smp_legacy_jw_responder.py` | 模拟 Initiator 发包，验证 Responder 状态机走完整路径 |
| `tests/unit/ble/test_smp_legacy_jw_initiator.py` | 模拟 Responder 回包，验证 Initiator 路径 |
| `tests/unit/ble/test_smp_phase3_key_distribution.py` | 按不同 key_dist mask 验证 LTK/IRK/CSRK 收发 |
| `tests/unit/ble/test_bond_storage_roundtrip.py` | JsonBondStorage 增字段后 round-trip |
| `tests/unit/test_stack_auto_encrypt.py` | LE_Connection_Complete + bond 命中 → 自动 start_encryption；未命中 → 不动 |
| `tests/unit/ble/test_gatt_auto_pair_retry.py` | ATT Error 0x0F → stack.pair → retry 原 request |

### 4.2 Loopback 集成（~6 新）

`tests/integration/test_pairing_loopback.py`：

- 完整 E2E：两个 `Stack.virtual()` 实例通过新增的 ACL bridge 配对 → 双方 BONDED → encryption on → bond 持久化 → disconnect → reconnect → 自动恢复加密
- 失败：peer 发 `SMPPairingFailed(reason=AUTH_REQUIREMENTS)` → state=FAILED → `pair()` raises
- 失败：30s 超时 → FAILED
- 角色对称：A→B vs B→A 都跑通

ACL bridge 是这个 Plan 的子任务（详见 Files 段）。

### 4.3 真机（手动验收）

`tests/hardware/test_pairing_real.py`，`real_hardware_only(transport="usb")`：

- 连接 Android 手机（预设广播一个可连接 BLE 服务），调 `stack.pair(handle)`，验证 BondInfo 写入；
- 断开后重连，验证加密自动恢复。

不在 CI 跑。文档化为 `uv run --frozen pytest tests/hardware/test_pairing_real.py --transport=usb`，需要操作者在手机端确认配对。

---

## 5. 文件改动清单

| 类型 | 路径 | 责任 |
|------|------|------|
| Modify | `pybluehost/ble/smp.py` | `SMPState`、`SMPEvent` enums；`PairingRole` enum；`SMPPairingContext` dataclass；扩展 `SMPManager` 持有 `dict[handle, SMPPairingContext]`、提供 `start_initiator/handle_pairing_request` 入口；删除占位 `on_pdu` 的 PAIRING_FAILED 返回 |
| Create | `pybluehost/ble/_smp_state.py` | 状态机 transition 表 + action callbacks（避免 smp.py 超 1000 行）|
| Modify | `pybluehost/ble/security.py` | `SecurityConfig.bondable: bool = True`；`SecurityConfig.auto_encrypt_on_bonded_reconnect: bool = True`（在 `StackConfig` 引用前先在 `SecurityConfig` 落地，避免 Stack 改动过大）|
| Modify | `pybluehost/ble/att.py` | `ATTBearer.request` 在收到 ATT 0x0F 时调 `on_security_required(handle)` 回调；提供注入点 |
| Modify | `pybluehost/ble/gatt.py` | `GATTClient.read/write` 接 ATT 重试钩子 |
| Modify | `pybluehost/stack.py` | `Stack.pair(handle)` + `Stack.encrypt(handle)` 公共 API；`StackConfig.auto_encrypt_on_bonded_reconnect / bondable` 字段；`_on_le_connection_complete` 钩子；`_on_le_ltk_request` 处理；ATT bearer 安全回调注入 |
| Modify | `pybluehost/hci/controller.py` | 派发 `LE_LTK_Request` subevent；监听 `Encryption_Change` 事件路由给 SMP / Stack 监听者 |
| Modify | `pybluehost/hci/packets.py` | 缺什么补什么：`HCI_LE_Start_Encryption_Command`、`HCI_LE_LTK_Request_Reply_Command`、`HCI_LE_LTK_Request_Negative_Reply_Command`、`HCI_LE_LTK_Request_Event`（subevent 0x05）|
| Modify | `pybluehost/hci/virtual.py` | VirtualController 支持 `HCI_LE_Start_Encryption`（设置 encryption_enabled bit、回 Encryption_Change 事件、为 peripheral 端模拟 LTK_Request）；ACL 加密标记仅供测试观察用，**不做真实 AES-CCM 加密**（仿真，不影响 PDU 内容）|
| Create | `pybluehost/hci/virtual_link.py` | 两台 VirtualController 之间的 LE 连接桥接（loopback E2E 用）：A 的 outbound ACL → B 的 inbound ACL，反之亦然；Connection_Complete 事件双向同步 |
| Modify | `pybluehost/ble/__init__.py` | 导出新符号（`SMPState`, `SMPEvent`, `PairingRole`, `SMPPairingContext`）|
| Create | `tests/unit/ble/test_smp_state_machine.py` | 状态机单测 |
| Create | `tests/unit/ble/test_smp_association_model.py` | 关联模型选择 |
| Create | `tests/unit/ble/test_smp_legacy_jw_responder.py` | Responder 路径 |
| Create | `tests/unit/ble/test_smp_legacy_jw_initiator.py` | Initiator 路径 |
| Create | `tests/unit/ble/test_smp_phase3_key_distribution.py` | Key Distribution |
| Create | `tests/unit/ble/test_bond_storage_roundtrip.py` | BondStorage round-trip 含新字段 |
| Create | `tests/unit/test_stack_auto_encrypt.py` | Auto-reconnect encryption |
| Create | `tests/unit/ble/test_gatt_auto_pair_retry.py` | GATT 自动重试 |
| Create | `tests/integration/test_pairing_loopback.py` | E2E loopback |
| Create | `tests/hardware/test_pairing_real.py` | 手动真机验收 |
| Modify | `tests/unit/ble/test_smp_manager_assembly.py` | 旧的 PAIRING_FAILED 占位测试需要更新或删除 |

---

## 6. 验收清单

- [ ] Loopback E2E：两个 `Stack.virtual()` 实例完整走完 Just Works → BONDED → encryption on → 双方 BondStorage 持久化 → 重连自动加密恢复
- [ ] 真机：Android 手机与 PyBlueHost Central 之间 Just Works 配对成功，重连恢复加密
- [ ] `stack.pair(handle)` 在 timeout / peer reject / disconnect 下抛对应异常
- [ ] GATT client 读加密 attribute 时遇 0x0F 自动 pair + retry，成功读取
- [ ] 全套测试：除 3 个 pre-existing USB diagnostics 失败外全绿；coverage ≥ 85%
- [ ] STATUS.md 更新

## 7. 后续 Plan 钩子

Sub-Plan 1 完成后留出的扩展点：

- `SMPState` 枚举：Sub-Plan 2 新增 `PUBLIC_KEY_EXCHANGE`、`DHKEY_CHECK` 状态用于 LE SC
- `SMPEvent` 枚举：Sub-Plan 3 新增 `PASSKEY_ENTERED`、`NUMERIC_COMPARE_CONFIRMED` 事件
- `PairingDelegate` Protocol：Sub-Plan 3 加 `display_passkey`、`request_passkey`、`numeric_comparison_confirm`
- `select_association_model()` 函数：Sub-Plan 3 扩展为完整 IO Cap matrix
- `BondInfo`：Sub-Plan 2 加 `key_size`、`authenticated`、`secure_connections` 字段

## 8. 已知风险

1. **VirtualController 加密仿真**：仅模拟 encryption_enabled 标记，不做真 AES-CCM。这意味着 loopback 测试不能验证 PDU 加密保密性，只能验证状态机流程。可接受 —— PRD 没有要求仿真层加密真实性。
2. **Privacy address**：本 Plan 只支持公共/静态随机地址。RPA 出现在 reconnect 时 bond 匹配失败 → fallback 到 normal pair。完整 RPA Resolving 单立 Plan。
3. **ATT MTU 与配对**：配对期间 MTU exchange 可能仍在进行；状态机 IDLE→FEATURE_EXCHANGE 不依赖 ATT MTU，互不阻塞。需要测试覆盖。
4. **Re-pair after disconnect**：如果两侧重新 pair 之前未 disconnect → context 残留。靠 `DISCONNECTED` 事件清 context。
5. **`HCI_LE_Start_Encryption` 在 Initiator 状态机里调用** vs Stack 顶层调用：选 SMP 状态机内调用以保持状态机自包含；Stack 仅做 reconnect 路径的加密启动。
