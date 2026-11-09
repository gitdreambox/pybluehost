# EATT 多 Bearer（GATT server 侧）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 PyBlueHost 的 GATT server 实现 EATT（Enhanced ATT）多 bearer，解锁 PTS GATT/SR GAR/BV-11、GAR/BV-12、GAW/BV-12、GPM/BV-05、GAC/BI-01（及 L2CAP/TIM/BV-03 真机验证机会）。

**Architecture:** 方案 A——bearer 键控状态。`GATTServer` 的 per-connection 状态（prepare queue / CCCD / security / robust caching 主状态）按 `conn_handle` 键控不动（恰好是 TS 要求的 per-client 共享语义）；仅有的 per-bearer 轴是 ATT_MTU 与 "Database Out Of Sync sent once" 标记，用 `(conn_handle, bearer_cid)` 元组键控。每条 EATT 信道（Enhanced Credit-Based，固定 SPSM 0x0027）复用 `install_att_channel_mux` 绑定 GATT server，closure 捕获 `bearer_cid=channel.cid`。

**Tech Stack:** Python 3.10+ / asyncio / pytest（pytest-asyncio, asyncio_mode=auto）。

**Spec:** [`docs/superpowers/specs/2026-09-17-eatt-multi-bearer-design.md`](../specs/2026-09-17-eatt-multi-bearer-design.md)（已提交 898e339，含 11 条 grounded spec 事实与错误处理表）

**工作环境（强制）：**
- 全部命令在 worktree `H:\github\bluetooth\pybluehost\.claude\worktrees\eatt-multi-bearer`（分支 `claude/eatt-multi-bearer`）内执行。
- 测试一律用主仓库 venv 直调（**绝不**用 `uv run`——会 re-sync 把 auto-pts editable install 冲掉）：
  `H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest <path> -v`
- 每条 commit message 末尾加 attribution 行：
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- 开始前先在 `docs/superpowers/STATUS.md` 认领（🔄 + 认领人/时间），随 Task 进度更新。

---

## 文件结构

| 文件 | 动作 | 责任 |
|---|---|---|
| `pybluehost/ble/gatt.py` | 修改 | per-bearer MTU 键控 + bearer 注册表 + Exchange MTU 0x06 拒绝 + synced_pending per-bearer set |
| `pybluehost/l2cap/ble.py` | 修改 | `LECoCChannel.psm` 字段 |
| `pybluehost/l2cap/manager.py` | 修改 | 出/入向 CoC 信道创建处传 `psm=` |
| `pybluehost/stack.py` | 修改 | `_bind_gatt_server_to_channel` 抽取 + EATT listener（PSM_EATT, security=4）+ `attach_eatt_bearer` |
| `pybluehost/pts/btp/services/gatt.py` | 修改 | SSF 0x2B3A 值 0x00→0x01；`_handle_op_1f` 连接后 attach bearer |
| `pybluehost/pts/btp/services/l2cap.py` | 修改 | `_handle_op_09` DISCONNECT_EATT_CHANS |
| `pybluehost/pts/btp/opcodes.py` | 修改 | `OP_L2CAP_DISCONNECT_EATT_CHANS = 0x09` |
| `tests/unit/ble/test_gatt_eatt.py` | 新建 | GATT server 侧 EATT 语义（T1–T4） |
| `tests/unit/test_stack_eatt.py` | 新建 | Stack 接线（T6） |
| `tests/unit/pts/btp/test_gatt_eatt_btp.py` | 新建 | BTP GATT 0x1f + SSF（T7） |
| `tests/unit/pts/btp/test_l2cap_disconnect_eatt.py` | 新建 | BTP L2CAP 0x09（T8） |
| `tests/unit/l2cap/test_le_ecfc_manager.py` | 修改 | psm 透传断言（T5） |
| `tests/e2e/test_le_coc_lifecycle.py` | 修改 | VirtualLELink 双 EATT loopback（T9） |

---

## Task 1: per-bearer ATT_MTU 键控（`_conn_mtu` 元组键 + bearer_cid 透传）

**Files:**
- Modify: `pybluehost/ble/gatt.py`（`_conn_mtu` 348、`_att_mtu` 370-371、`remove_connection` 386-404、`handle_request` 515-542、`_dispatch` 699-734、7 个读 handler）
- Test: `tests/unit/ble/test_gatt_eatt.py`（新建）

- [x] **Step 1: 写失败测试**

新建 `tests/unit/ble/test_gatt_eatt.py`：

```python
"""GATT server EATT multi-bearer semantics (PTS GATT/SR GAR/BV-11, GAR/BV-12,
GAW/BV-12, GPM/BV-05, GAC/BI-01).

 bearer 轴只有两个 per-bearer 状态：ATT_MTU 与 "Database Out Of Sync sent
 once" 标记；prepare queue / CCCD / security / robust 主状态是 per-client
 （conn_handle 键控），跨 bearer 共享。
"""
from __future__ import annotations

import pytest

from pybluehost.ble.att import (
    ATT_Error_Response,
    ATT_Exchange_MTU_Request,
    ATT_Execute_Write_Request,
    ATT_Execute_Write_Response,
    ATT_Prepare_Write_Request,
    ATT_Read_Multiple_Variable_Request,
    ATT_Read_Multiple_Variable_Response,
    ATT_Read_Request,
    ATT_Read_Response,
    ATT_Write_Request,
    ATT_Write_Response,
    ATTOpcode,
)
from pybluehost.ble.gatt import (
    CharacteristicDefinition,
    CharProperties,
    GATTServer,
    Permissions,
    ServiceDefinition,
)
from pybluehost.core.uuid import UUID16
from pybluehost.l2cap.constants import CID_ATT

pytestmark = pytest.mark.asyncio

CONN = 0x0040
BEARER1 = 0x0041  # EATT bearer CID（方向无关：我方端点 CID）
BEARER2 = 0x0042


def _server(*, long_value: bytes = b"AB" * 40) -> tuple[GATTServer, int]:
    """One readable characteristic with an 80-byte value; returns
    (server, value_handle). 80 bytes fits an EATT bearer MTU (>=64 only after
    registration — use mtu=100 in tests) but not the default 23."""
    server = GATTServer()
    handles = server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x180D),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2A38),
                    properties=CharProperties.READ,
                    permissions=Permissions.READABLE,
                    value=long_value,
                ),
            ],
        )
    )
    return server, handles.characteristic_handles[0].value_handle


async def test_exchange_mtu_is_tracked_per_bearer():
    """Exchange MTU on the fixed channel must not change an EATT bearer's MTU
    (and vice versa) — the key is (conn_handle, bearer_cid)."""
    server, value_handle = _server()
    await server.handle_request(CONN, ATT_Exchange_MTU_Request(client_rx_mtu=100))

    fixed = await server.handle_request(CONN, ATT_Read_Request(attribute_handle=value_handle))
    bearer = await server.handle_request(
        CONN, ATT_Read_Request(attribute_handle=value_handle), bearer_cid=BEARER1)

    assert isinstance(fixed, ATT_Read_Response)
    assert len(fixed.attribute_value) == 80  # negotiated 100 -> 100-1 fits all
    assert isinstance(bearer, ATT_Read_Response)
    assert len(bearer.attribute_value) == 22  # unregistered bearer -> default 23-1


async def test_handle_request_without_bearer_cid_behaves_as_fixed_channel():
    """Default bearer_cid=CID_ATT keeps the existing fixed-channel behaviour."""
    server, value_handle = _server(long_value=b"\x01\x02")
    rsp = await server.handle_request(CONN, ATT_Read_Request(attribute_handle=value_handle))
    assert isinstance(rsp, ATT_Read_Response)
    assert rsp.attribute_value == b"\x01\x02"
    assert server._att_mtu(CONN, CID_ATT) == 23
```

- [x] **Step 2: 跑测试确认失败**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/ble/test_gatt_eatt.py -v
```
预期：FAIL —— `TypeError: handle_request() got an unexpected keyword argument 'bearer_cid'`。

- [x] **Step 3: 实现 —— `_conn_mtu` 改元组键 + bearer_cid 透传**

`pybluehost/ble/gatt.py`：

① import 区加：

```python
from pybluehost.l2cap.constants import CID_ATT
```

② `GATTServer.__init__`（348 行附近）注释与声明改为：

```python
        # (conn_handle, bearer_cid) -> negotiated ATT MTU. The fixed ATT
        # channel's bearer key is CID_ATT (default 23 until Exchange MTU); an
        # EATT bearer's MTU is its L2CAP channel MTU, set at attach time by
        # add_eatt_bearer (no Exchange MTU on EATT — GATT.TS §4.2.5).
        # Responses must be truncated to this or the peer (which may never
        # exchange MTU, e.g. PTS GATT/SR reads) treats oversized PDUs as a
        # protocol violation and stalls.
        self._conn_mtu: dict[tuple[int, int], int] = {}
```

③ `_att_mtu`（370-371）改为：

```python
    def _att_mtu(self, conn_handle: int, bearer_cid: int = CID_ATT) -> int:
        return self._conn_mtu.get((conn_handle, bearer_cid), self._DEFAULT_ATT_MTU)
```

④ `remove_connection`（394 行）把 `self._conn_mtu.pop(conn_handle, None)` 改为：

```python
        for key in [k for k in self._conn_mtu if k[0] == conn_handle]:
            del self._conn_mtu[key]
```

⑤ `handle_request`（515）签名与 dispatch 调用：

```python
    async def handle_request(
        self, conn_handle: int, pdu: ATTPdu, *, bearer_cid: int = CID_ATT
    ) -> ATTPdu | None:
        """Handle an incoming ATT PDU, returning the response PDU — or ``None``
        for PDUs that must not be answered (Write Command / Signed Write
        Command). ``bearer_cid`` identifies the ATT bearer the PDU arrived on
        (CID_ATT for the fixed channel, the channel CID for an EATT bearer)."""
```

函数体最后一行改为 `return await self._dispatch(conn_handle, pdu, bearer_cid)`。（`_robust_caching_gate` 的 bearer 化在 Task 3 做，本任务不动。）

⑥ `_dispatch`（699）签名改为 `async def _dispatch(self, conn_handle: int, pdu: ATTPdu, bearer_cid: int) -> ATTPdu | None:`，分支更新：

```python
        if isinstance(pdu, ATT_Read_Request):
            return await self._handle_read(conn_handle, pdu, bearer_cid)
        elif isinstance(pdu, ATT_Read_Blob_Request):
            return await self._handle_read_blob(conn_handle, pdu, bearer_cid)
        elif isinstance(pdu, ATT_Read_Multiple_Request):
            return await self._handle_read_multiple(conn_handle, pdu, bearer_cid)
        elif isinstance(pdu, ATT_Read_Multiple_Variable_Request):
            return self._handle_read_multiple_variable(conn_handle, pdu, bearer_cid)
        elif isinstance(pdu, ATT_Write_Request):
            return await self._handle_write(conn_handle, pdu)
        elif isinstance(pdu, ATT_Write_Command):
            return await self._handle_write_command(conn_handle, pdu)
        elif isinstance(pdu, ATT_Prepare_Write_Request):
            return await self._handle_prepare_write(conn_handle, pdu)
        elif isinstance(pdu, ATT_Execute_Write_Request):
            return await self._handle_execute_write(conn_handle, pdu)
        elif isinstance(pdu, ATT_Exchange_MTU_Request):
            # Negotiated ATT MTU = min(client rx, our rx); remember it per
            # bearer so list responses are truncated to fit.
            self._conn_mtu[(conn_handle, bearer_cid)] = min(pdu.client_rx_mtu, self._SERVER_RX_MTU)
            logger.debug("GATT exchange_mtu conn=0x%04X bearer=0x%04X client_rx=%d negotiated=%d",
                         conn_handle, bearer_cid, pdu.client_rx_mtu,
                         self._conn_mtu[(conn_handle, bearer_cid)])
            return ATT_Exchange_MTU_Response(server_rx_mtu=self._SERVER_RX_MTU)
        elif isinstance(pdu, ATT_Read_By_Group_Type_Request):
            return self._handle_read_by_group_type(conn_handle, pdu, bearer_cid)
        elif isinstance(pdu, ATT_Read_By_Type_Request):
            return self._handle_read_by_type(conn_handle, pdu, bearer_cid)
        elif isinstance(pdu, ATT_Find_Information_Request):
            return self._handle_find_information(conn_handle, pdu, bearer_cid)
        elif isinstance(pdu, ATT_Find_By_Type_Value_Request):
            return self._handle_find_by_type_value(pdu)
        return ATT_Error_Response(
            request_opcode_in_error=0, attribute_handle_in_error=0,
            error_code=0x06,  # Request Not Supported
        )
```

⑦ 7 个读 handler 的机械修改（每个都是：签名加 `bearer_cid: int` 第三参 + `_att_mtu(conn_handle)` → `_att_mtu(conn_handle, bearer_cid)`）：

| handler | 签名行 | `_att_mtu` 调用行 |
|---|---|---|
| `_handle_read` | 736 | 759 |
| `_handle_read_blob` | 765 | 792 |
| `_handle_read_multiple` | 795 | 818 |
| `_handle_read_multiple_variable` | 833 | 857 |
| `_handle_read_by_group_type` | 1015 | 1030 |
| `_handle_read_by_type` | 1040 | 1067 |
| `_handle_find_information` | 1093 | 1109 |

示例（`_handle_read`，其余照此 pattern）：

```python
    async def _handle_read(self, conn_handle: int, pdu: ATT_Read_Request, bearer_cid: int) -> ATTPdu:
        ...
        mtu = self._att_mtu(conn_handle, bearer_cid)
```

（`_handle_write` / `_handle_write_command` / `_handle_prepare_write` / `_handle_execute_write` / `_handle_find_by_type_value` 不用 `_att_mtu`，签名不变。）

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/ble/test_gatt_eatt.py -v
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/ble/ -q
```
预期：新文件 2 PASS；`tests/unit/ble/` 全绿（既有 `_conn_mtu` 行为经固定通道路径不变）。

- [x] **Step 5: Commit**

```bash
git add pybluehost/ble/gatt.py tests/unit/ble/test_gatt_eatt.py
git commit -m "feat(gatt): per-bearer ATT_MTU keyed by (conn_handle, bearer_cid)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: EATT bearer 注册表 + Exchange MTU 0x06 拒绝（GAC/BI-01）

**Files:**
- Modify: `pybluehost/ble/gatt.py`（`__init__`、`remove_connection`、`_dispatch` 的 Exchange MTU 分支；新增 `add_eatt_bearer`/`remove_eatt_bearer`/`is_eatt_bearer`）
- Test: `tests/unit/ble/test_gatt_eatt.py`

- [x] **Step 1: 写失败测试（追加到 test_gatt_eatt.py）**

```python
async def test_add_eatt_bearer_sets_channel_mtu():
    """An EATT bearer's ATT_MTU is its L2CAP channel MTU (GATT.TS §4.2.5)."""
    server, value_handle = _server()
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    rsp = await server.handle_request(
        CONN, ATT_Read_Request(attribute_handle=value_handle), bearer_cid=BEARER1)
    assert isinstance(rsp, ATT_Read_Response)
    assert len(rsp.attribute_value) == 80  # 100-1 fits the whole value
    assert server.is_eatt_bearer(CONN, BEARER1)


async def test_exchange_mtu_on_eatt_bearer_is_rejected_not_supported():
    """GAC/BI-01: Exchange MTU is not applicable on an EATT bearer — the server
    must answer ATT_ERROR_RSP(0x02, handle 0x0000, 0x06 Request Not Supported)
    and leave the bearer MTU untouched."""
    server, _ = _server()
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    rsp = await server.handle_request(
        CONN, ATT_Exchange_MTU_Request(client_rx_mtu=200), bearer_cid=BEARER1)
    assert isinstance(rsp, ATT_Error_Response)
    assert rsp.error_code == 0x06  # Request Not Supported
    assert int(rsp.request_opcode_in_error) == int(ATTOpcode.EXCHANGE_MTU_REQUEST)
    assert rsp.attribute_handle_in_error == 0x0000
    assert server._att_mtu(CONN, BEARER1) == 100


async def test_exchange_mtu_rejection_does_not_touch_fixed_channel():
    server, _ = _server()
    await server.handle_request(CONN, ATT_Exchange_MTU_Request(client_rx_mtu=100))
    server.add_eatt_bearer(CONN, BEARER1, mtu=64)
    await server.handle_request(
        CONN, ATT_Exchange_MTU_Request(client_rx_mtu=200), bearer_cid=BEARER1)
    assert server._att_mtu(CONN, CID_ATT) == 100
    assert server._att_mtu(CONN, BEARER1) == 64


async def test_remove_connection_clears_all_bearer_state():
    """Handle reuse must never see a previous connection's bearer MTUs."""
    server, _ = _server()
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    server.add_eatt_bearer(CONN, BEARER2, mtu=80)
    server.remove_connection(CONN)
    assert server._att_mtu(CONN, BEARER1) == 23
    assert server._att_mtu(CONN, BEARER2) == 23
    assert not server.is_eatt_bearer(CONN, BEARER1)


async def test_add_eatt_bearer_resets_mtu_on_cid_reuse():
    server, _ = _server()
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    server.add_eatt_bearer(CONN, BEARER1, mtu=64)
    assert server._att_mtu(CONN, BEARER1) == 64


async def test_remove_eatt_bearer_drops_only_that_bearer():
    server, _ = _server()
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    server.add_eatt_bearer(CONN, BEARER2, mtu=80)
    server.remove_eatt_bearer(CONN, BEARER1)
    assert not server.is_eatt_bearer(CONN, BEARER1)
    assert server._att_mtu(CONN, BEARER1) == 23
    assert server.is_eatt_bearer(CONN, BEARER2)
    assert server._att_mtu(CONN, BEARER2) == 80
```

- [x] **Step 2: 跑测试确认失败**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/ble/test_gatt_eatt.py -v
```
预期：6 个新测试 FAIL（`AttributeError: add_eatt_bearer` / Exchange MTU 未被拒）。

- [x] **Step 3: 实现**

`pybluehost/ble/gatt.py`：

① `GATTServer.__init__` 在 `_conn_mtu` 声明之后加：

```python
        # conn_handle -> set of EATT bearer CIDs attached to this connection
        # (channels on the fixed EATT SPSM 0x0027). Registered by the stack at
        # bearer attach time; drives the Exchange-MTU rejection predicate.
        self._eatt_bearers: dict[int, set[int]] = {}
```

② `remove_connection` 在 MTU 清理循环之后加：

```python
        self._eatt_bearers.pop(conn_handle, None)
```

③ 新增三个方法（放在 `_att_mtu` 之后）：

```python
    # -- EATT bearers (Enhanced ATT over Enhanced Credit-Based channels) ------

    def add_eatt_bearer(self, conn_handle: int, bearer_cid: int, *, mtu: int) -> None:
        """Register an EATT bearer on a connection. The bearer's ATT_MTU is the
        channel's negotiated L2CAP MTU — there is no Exchange MTU on EATT
        (GATT.TS §4.2.5). Re-registering the same CID resets its MTU (CID
        reuse must not inherit a stale value)."""
        self._eatt_bearers.setdefault(conn_handle, set()).add(bearer_cid)
        self._conn_mtu[(conn_handle, bearer_cid)] = min(mtu, self._SERVER_RX_MTU)

    def remove_eatt_bearer(self, conn_handle: int, bearer_cid: int) -> None:
        bearers = self._eatt_bearers.get(conn_handle)
        if bearers is not None:
            bearers.discard(bearer_cid)
            if not bearers:
                del self._eatt_bearers[conn_handle]
        self._conn_mtu.pop((conn_handle, bearer_cid), None)

    def is_eatt_bearer(self, conn_handle: int, bearer_cid: int) -> bool:
        return bearer_cid in self._eatt_bearers.get(conn_handle, set())
```

④ `_dispatch` 的 Exchange MTU 分支最前面加拒绝：

```python
        elif isinstance(pdu, ATT_Exchange_MTU_Request):
            if bearer_cid != CID_ATT:
                # Exchange MTU is not applicable over the Enhanced ATT bearer
                # (the MTU comes from L2CAP channel configuration) — GATT.TS
                # §4.2.5; the rejection is GATT/SR/GAC/BI-01's pass criterion.
                return ATT_Error_Response(
                    request_opcode_in_error=ATTOpcode.EXCHANGE_MTU_REQUEST,
                    attribute_handle_in_error=0x0000,
                    error_code=0x06,  # Request Not Supported
                )
            # Negotiated ATT MTU = min(client rx, our rx); remember it per
            # ...（Task 1 的既有代码不动）
```

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/ble/test_gatt_eatt.py -v
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/ble/ -q
```
预期：8 个全 PASS；ble 目录全绿。

- [x] **Step 5: Commit**

```bash
git add pybluehost/ble/gatt.py tests/unit/ble/test_gatt_eatt.py
git commit -m "feat(gatt): EATT bearer registry + Exchange MTU rejected 0x06 on EATT (GAC/BI-01)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Robust Caching `synced_pending` per-bearer set

**Files:**
- Modify: `pybluehost/ble/gatt.py`（`_RobustClientState` 153-167、`handle_request` 532、`on_confirmation` 558-571、`_robust_caching_gate` 624-668、`_database_out_of_sync` 670-682、`on_connection_opened` 1292-1295）
- Test: `tests/unit/ble/test_gatt_eatt.py`

- [x] **Step 1: 写失败测试（追加）**

```python
def _robust_server() -> tuple[GATTServer, int, int]:
    """Server with a readable value characteristic + a Client Supported
    Features characteristic (0x2B29). Returns (server, value_handle, csf_handle)."""
    server, value_handle = _server(long_value=b"\x01\x02")
    server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x1801),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2B29),
                    properties=CharProperties.READ | CharProperties.WRITE,
                    permissions=Permissions.READABLE | Permissions.WRITABLE,
                    value=b"\x00",
                ),
            ],
        )
    )
    csf_handle = server._csf_value_handle()
    assert csf_handle is not None
    return server, value_handle, csf_handle


async def _enable_robust_caching(server: GATTServer, csf_handle: int) -> None:
    rsp = await server.handle_request(
        CONN, ATT_Write_Request(attribute_handle=csf_handle, attribute_value=b"\x01"))
    assert isinstance(rsp, ATT_Write_Response)


async def test_database_out_of_sync_is_sent_once_per_bearer():
    """Core Vol 3 Part G Figure 2.7: the 0x12 marker is per-BEARER — a
    change-unaware client gets one Database Out Of Sync on EACH bearer it uses
    before resyncing, not once per connection."""
    server, value_handle, csf_handle = _robust_server()
    await _enable_robust_caching(server, csf_handle)
    server.mark_database_changed()

    read = ATT_Read_Request(attribute_handle=value_handle)
    r1 = await server.handle_request(CONN, read, bearer_cid=BEARER1)
    assert isinstance(r1, ATT_Error_Response) and r1.error_code == 0x12
    # Bearer 2 hasn't had its 0x12 yet — the client is still unaware.
    r2 = await server.handle_request(CONN, read, bearer_cid=BEARER2)
    assert isinstance(r2, ATT_Error_Response) and r2.error_code == 0x12
    # The NEXT request on bearer 1 completes the resync (client now aware).
    r3 = await server.handle_request(CONN, read, bearer_cid=BEARER1)
    assert isinstance(r3, ATT_Read_Response) and r3.attribute_value == b"\x01\x02"
    # Aware is per-client: bearer 2 proceeds without another 0x12.
    r4 = await server.handle_request(CONN, read, bearer_cid=BEARER2)
    assert isinstance(r4, ATT_Read_Response) and r4.attribute_value == b"\x01\x02"


async def test_out_of_sync_once_marker_survives_on_other_bearer_after_resync():
    """ synced_pending is consumed per bearer: resync on bearer 1 must not
    discard bearer 2's pending marker bookkeeping incorrectly (no crash, and a
    fresh database change re-arms both bearers)."""
    server, value_handle, csf_handle = _robust_server()
    await _enable_robust_caching(server, csf_handle)
    read = ATT_Read_Request(attribute_handle=value_handle)
    server.mark_database_changed()
    await server.handle_request(CONN, read, bearer_cid=BEARER1)  # 0x12 on b1
    await server.handle_request(CONN, read, bearer_cid=BEARER1)  # resync via b1
    # A second db change makes the client unaware again; both bearers re-arm.
    server.mark_database_changed()
    r1 = await server.handle_request(CONN, read, bearer_cid=BEARER2)
    assert isinstance(r1, ATT_Error_Response) and r1.error_code == 0x12
```

- [x] **Step 2: 跑测试确认失败**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/ble/test_gatt_eatt.py -v
```
预期：`test_database_out_of_sync_is_sent_once_per_bearer` FAIL —— r2 拿到 value 而非 0x12（`synced_pending` 是连接级 bool，bearer1 的 0x12 已置位后 `_database_out_of_sync` 不再触发……实际现行为：b1 的 0x12 置 synced_pending=True，b2 读走 664 行 `if state.synced_pending` 分支清标记并放行 → r2 是 value，断言失败）。

- [x] **Step 3: 实现 —— bool → set[int]**

`pybluehost/ble/gatt.py`，共 8 处：

① `_RobustClientState`（157-159）：

```python
    csf: bytes = b"\x00"
    change_unaware: bool = False
    # Bearer CIDs on which the resync trigger (0x12 or a Database Hash read)
    # has already fired — "Database Out Of Sync sent once" is per-BEARER
    # (Figure 2.7). The fixed channel contributes CID_ATT at most.
    synced_pending: set[int] = field(default_factory=set)
```

② `mark_database_changed`（165-167）：`self.synced_pending = False` → `self.synced_pending.clear()`

③ `remove_connection`（404 行 `state.synced_pending = False`）→ `state.synced_pending.clear()`

④ `on_confirmation`（571 行 `state.synced_pending = False`）→ `state.synced_pending.clear()`

⑤ `handle_request`（532 行）gate 调用透传 bearer：

```python
        gated = self._robust_caching_gate(conn_handle, pdu, bearer_cid)
```

⑥ `_robust_caching_gate` 签名改为 `(self, conn_handle: int, pdu: ATTPdu, bearer_cid: int)`；Database Hash resync 分支（654 行）`state.synced_pending = True` → `state.synced_pending.add(bearer_cid)`；「next request」分支（664-667）改为：

```python
        # Any other handle-based request.
        if bearer_cid in state.synced_pending:
            state.change_unaware = False
            state.synced_pending.discard(bearer_cid)
            return None  # resync completed — process normally
        return self._database_out_of_sync(pdu, state, bearer_cid)
```

（646-656 的 READ_BY_TYPE 分支末尾 `return self._database_out_of_sync(pdu, state)` 同样加第三参 `bearer_cid`。）

⑦ `_database_out_of_sync` 签名改 `(self, pdu: ATTPdu, state: _RobustClientState, bearer_cid: int)`，677 行 `state.synced_pending = True` → `state.synced_pending.add(bearer_cid)`。

⑧ `on_connection_opened`（1295 行 `state.synced_pending = False`）→ `state.synced_pending.clear()`

- [x] **Step 4: 跑测试确认通过 + GAS 回归**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/ble/test_gatt_eatt.py -v
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/ble/ -q
```
预期：新 2 个 PASS；ble 全绿（既有 GAS robust-caching 测试固定通道行为等价——set 里最多一个 CID_ATT）。

- [x] **Step 5: Commit**

```bash
git add pybluehost/ble/gatt.py tests/unit/ble/test_gatt_eatt.py
git commit -m "feat(gatt): robust-caching DoS-once marker is per-bearer (Figure 2.7)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: TS 语义回归测试（GAR/BV-11、GAR/BV-12、GAW/BV-12、GPM/BV-05）

**Files:**
- Test: `tests/unit/ble/test_gatt_eatt.py`

这些语义大多已由 per-conn 键控天然满足——本任务用测试**钉死**它们，防未来回归。纯测试任务，预期直接 PASS；若 FAIL 说明设计与实现有偏差，先修实现再继续。

- [x] **Step 1: 追加测试**

```python
def _multi_char_server() -> tuple[GATTServer, int, int]:
    """Two readable value characteristics; returns (server, h1, h2)."""
    server = GATTServer()
    handles = server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x180D),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2A38),
                    properties=CharProperties.READ,
                    permissions=Permissions.READABLE,
                    value=b"\x11\x22",
                ),
                CharacteristicDefinition(
                    uuid=UUID16(0x2A39),
                    properties=CharProperties.READ,
                    permissions=Permissions.READABLE,
                    value=b"\x33\x44\x55",
                ),
            ],
        )
    )
    chars = handles.characteristic_handles
    return server, chars[0].value_handle, chars[1].value_handle


async def test_read_multiple_variable_answers_on_each_eatt_bearer():
    """GAR/BV-12: concurrent Read Multiple Variable on two EATT bearers — each
    bearer gets its own complete response."""
    server, h1, h2 = _multi_char_server()
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    server.add_eatt_bearer(CONN, BEARER2, mtu=100)
    pdu = ATT_Read_Multiple_Variable_Request(
        set_of_handles=h1.to_bytes(2, "little") + h2.to_bytes(2, "little"))
    r1 = await server.handle_request(CONN, pdu, bearer_cid=BEARER1)
    r2 = await server.handle_request(CONN, pdu, bearer_cid=BEARER2)
    for rsp in (r1, r2):
        assert isinstance(rsp, ATT_Read_Multiple_Variable_Response)
        assert rsp.values == [b"\x11\x22", b"\x33\x44\x55"]


async def test_mixed_fixed_and_eatt_bearer_reads():
    """GAR/BV-11: the fixed ATT channel and an EATT bearer serve reads
    concurrently, each truncated to its own bearer MTU."""
    server, value_handle = _server()  # 80-byte value
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    read = ATT_Read_Request(attribute_handle=value_handle)
    fixed = await server.handle_request(CONN, read)
    eatt = await server.handle_request(CONN, read, bearer_cid=BEARER1)
    assert len(fixed.attribute_value) == 22   # default MTU 23
    assert len(eatt.attribute_value) == 80    # bearer MTU 100


def _writable_server() -> tuple[GATTServer, int]:
    server = GATTServer()
    handles = server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x180D),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2A38),
                    properties=CharProperties.READ | CharProperties.WRITE,
                    permissions=Permissions.READABLE | Permissions.WRITABLE,
                    value=b"\x00" * 8,
                    max_length=8,
                ),
            ],
        )
    )
    return server, handles.characteristic_handles[0].value_handle


async def test_prepare_write_queue_is_shared_across_bearers():
    """GAW/BV-12: Prepare Writes issued on alternating bearers are committed by
    a single Execute Write (the queue is per-CLIENT, not per-bearer)."""
    server, value_handle = _writable_server()
    server.add_eatt_bearer(CONN, BEARER1, mtu=100)
    server.add_eatt_bearer(CONN, BEARER2, mtu=100)
    p1 = ATT_Prepare_Write_Request(
        attribute_handle=value_handle, value_offset=0, part_attribute_value=b"AAAA")
    p2 = ATT_Prepare_Write_Request(
        attribute_handle=value_handle, value_offset=4, part_attribute_value=b"BBBB")
    r1 = await server.handle_request(CONN, p1, bearer_cid=BEARER1)
    assert r1.part_attribute_value == b"AAAA"
    r2 = await server.handle_request(CONN, p2, bearer_cid=BEARER2)
    assert r2.part_attribute_value == b"BBBB"
    # One Execute Write — on the FIXED channel even — commits both fragments.
    r3 = await server.handle_request(CONN, ATT_Execute_Write_Request(flags=0x01))
    assert isinstance(r3, ATT_Execute_Write_Response)
    assert server.db.read(value_handle) == b"AAAABBBB"


def _notify_server() -> tuple[GATTServer, int, int]:
    """Notify characteristic with its CCCD; returns (server, value_handle,
    cccd_handle)."""
    server = GATTServer()
    handles = server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x180D),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2A37),
                    properties=CharProperties.READ | CharProperties.NOTIFY,
                    permissions=Permissions.READABLE,
                    value=b"\x00",
                ),
            ],
        )
    )
    char = handles.characteristic_handles[0]
    assert char.cccd_handle is not None
    return server, char.value_handle, char.cccd_handle


async def test_cccd_written_on_one_bearer_reads_back_on_another():
    """GPM/BV-05: CCCD state is per-CLIENT — a CCCD write on EATT bearer 2 is
    visible to a read on the fixed channel (and to bearer 1)."""
    server, value_handle, cccd_handle = _notify_server()
    server.add_eatt_bearer(CONN, BEARER2, mtu=100)
    w = await server.handle_request(
        CONN, ATT_Write_Request(attribute_handle=cccd_handle, attribute_value=b"\x01\x00"),
        bearer_cid=BEARER2)
    assert isinstance(w, ATT_Write_Response)
    for bearer in (CID_ATT, BEARER1):  # fixed + even an unregistered bearer key
        r = await server.handle_request(
            CONN, ATT_Read_Request(attribute_handle=cccd_handle), bearer_cid=bearer)
        assert isinstance(r, ATT_Read_Response)
        assert r.attribute_value == b"\x01\x00"
    assert server._notifications_enabled[CONN] == {value_handle}
```

（`ATT_Execute_Write_Response` 需加进文件顶部的 att import 列表。）

- [x] **Step 2: 跑测试**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/ble/test_gatt_eatt.py -v
```
预期：全 PASS（若 FAIL → 设计与实现偏差，修实现）。随后回归：

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/ble/ -q
```

- [x] **Step 3: Commit**

```bash
git add tests/unit/ble/test_gatt_eatt.py
git commit -m "test(gatt): pin EATT TS semantics — concurrent bearers, shared prepare queue/CCCD

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `LECoCChannel.psm` 字段 + manager 透传

**Files:**
- Modify: `pybluehost/l2cap/ble.py`（`LECoCChannel.__init__` 87-150、properties 区 152-177）
- Modify: `pybluehost/l2cap/manager.py`（入向 ECFC 创建 1273-1285、出向 `connect_le_coc_channels` 1117-1131、legacy `connect_le_coc_channel` 创建处 ~1040-1056）
- Test: `tests/unit/l2cap/test_le_ecfc_manager.py`

- [x] **Step 1: 写失败测试（追加到 test_le_ecfc_manager.py 尾部）**

复用该文件既有的 `m` fixture（`mgr, sig_ch = m`，handle=0x000C）与 `_ecfc_req` helper：

```python
@pytest.mark.asyncio
async def test_incoming_ecfc_channels_carry_the_request_psm(m):
    """BTP DISCONNECT_EATT_CHANS picks EATT bearers out by channel.psm — an
    inbound ECFC channel must record the PSM it was created for."""
    mgr, sig_ch = m
    seen = []
    mgr.listen_le_coc_channel(psm=0x0027, handler=seen.append)

    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_REQUEST, 0x10, _ecfc_req(psm=0x0027).encode(),
    ))

    assert len(seen) == 2
    assert [ch.psm for ch in seen] == [0x0027, 0x0027]


@pytest.mark.asyncio
async def test_outbound_ecfc_channels_carry_the_psm(m):
    mgr, sig_ch = m
    task = asyncio.create_task(mgr.connect_le_coc_channels(
        handle=0x000C, psm=0x0027, mtu=512, mps=247,
        initial_credits=10, num=2, timeout=2.0,
    ))
    await asyncio.sleep(0); await asyncio.sleep(0)

    sent = sig_ch.send.await_args.args[0]
    _, ident, _ = decode_le_signaling(sent)
    resp = ECFCConnectionResponse(
        mtu=247, mps=247, initial_credits=5, result=0x0000,
        dcids=(0x0050, 0x0051),
    )
    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_RESPONSE, ident, resp.encode(),
    ))
    chans = await task
    assert [ch.psm for ch in chans] == [0x0027, 0x0027]


def test_le_coc_channel_psm_defaults_to_none():
    from pybluehost.l2cap.ble import LECoCChannel
    ch = LECoCChannel(connection_handle=0x40, local_cid=0x41, peer_cid=0x42, hci=object())
    assert ch.psm is None
```

- [x] **Step 2: 跑测试确认失败**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/l2cap/test_le_ecfc_manager.py -v -k psm
```
预期：FAIL —— `AttributeError` / `TypeError: unexpected keyword argument 'psm'`。

- [x] **Step 3: 实现**

① `pybluehost/l2cap/ble.py` `LECoCChannel.__init__` 签名加关键字参数（放在 `rx_mps` 之后）并存储：

```python
        rx_mtu: int | None = None,
        rx_mps: int | None = None,
        psm: int | None = None,
    ) -> None:
```

在 `self._reconfig_base_mps = self._rx_mps` 之后加：

```python
        # The (S)PSM this channel was established for. EATT bearers ride the
        # fixed SPSM 0x0027 — BTP DISCONNECT_EATT_CHANS picks them out by it.
        self._psm = psm
```

properties 区（`cid` property 之后）加：

```python
    @property
    def psm(self) -> int | None:
        return self._psm
```

② `pybluehost/l2cap/manager.py` `_handle_incoming_ecfc_request` 的创建（1273-1285）加 `psm=req.le_psm`：

```python
            ch = LECoCChannel(
                connection_handle=handle, local_cid=dcid, peer_cid=scid,
                hci=self._hci,
                mtu=min(our_mtu, req.mtu), mps=min(our_mps, req.mps),
                initial_credits=req.initial_credits,
                rx_mtu=our_mtu, rx_mps=our_mps,
                psm=req.le_psm,
            )
```

③ `connect_le_coc_channels` 出向创建（1119-1125）加 `psm=psm`：

```python
            ch = LECoCChannel(
                connection_handle=handle, local_cid=scid, peer_cid=dcid,
                hci=self._hci,
                mtu=min(mtu, resp.mtu), mps=min(mps, resp.mps),
                initial_credits=resp.initial_credits,
                rx_mtu=mtu, rx_mps=mps,
                psm=psm,
            )
```

④ legacy `connect_le_coc_channel`（0x14/0x15 路径）的创建处（~1043-1053）同样加 `psm=psm`（EATT 不走此路径，此处只为一致性）：

```python
        ch = LECoCChannel(
            connection_handle=handle,
            local_cid=scid,
            peer_cid=resp.dcid,
            hci=self._hci,
            mtu=min(mtu, resp.mtu),
            mps=min(mps, resp.mps),
            initial_credits=resp.initial_credits,
            rx_mtu=mtu, rx_mps=mps,
            psm=psm,
        )
```

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/l2cap/ -q
```
预期：全绿。

- [x] **Step 5: Commit**

```bash
git add pybluehost/l2cap/ble.py pybluehost/l2cap/manager.py tests/unit/l2cap/test_le_ecfc_manager.py
git commit -m "feat(l2cap): LECoCChannel carries its PSM (EATT bearer identification)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Stack 接线 —— `_bind_gatt_server_to_channel` + EATT listener + `attach_eatt_bearer`

**Files:**
- Modify: `pybluehost/stack.py`（`__init__` ~99 行区域、`_attach_gatt_server_to_att_channels` 805-881）
- Test: `tests/unit/test_stack_eatt.py`（新建）

- [x] **Step 1: 写失败测试**

新建 `tests/unit/test_stack_eatt.py`：

```python
"""Stack EATT wiring: inbound listener on PSM_EATT (encryption-gated) and
per-channel GATT server binding with bearer identity."""
from __future__ import annotations

import pytest

from pybluehost.ble.att import ATT_Read_Request, ATT_Read_Response, decode_att_pdu
from pybluehost.ble.gatt import (
    CharacteristicDefinition,
    CharProperties,
    GATTServer,
    Permissions,
    ServiceDefinition,
)
from pybluehost.core.uuid import UUID16
from pybluehost.l2cap.constants import CID_ATT, PSM_EATT
from pybluehost.stack import Stack

pytestmark = pytest.mark.asyncio

CONN = 0x0040
EATT_CID = 0x0041


class _FakeL2CAP:
    def __init__(self) -> None:
        self._connections: dict[int, dict[int, object]] = {}
        self.listeners: list[tuple[int, object, int]] = []

    def listen_le_coc_channel(self, psm, handler, required_security=0) -> None:
        self.listeners.append((psm, handler, required_security))

    def get_fixed_channel(self, handle, cid):
        return None


class _FakeEattChannel:
    """Minimal channel double: mux needs set_events; the binder needs cid /
    connection_handle / mtu / send."""

    def __init__(self, conn_handle=CONN, cid=EATT_CID, mtu=512) -> None:
        self.connection_handle = conn_handle
        self.cid = cid
        self.mtu = mtu
        self.psm = PSM_EATT
        self.events = None
        self.sent: list[bytes] = []

    def set_events(self, events) -> None:
        self.events = events

    async def send(self, data: bytes) -> None:
        self.sent.append(bytes(data))


def _stack_with_gatt() -> tuple[Stack, GATTServer, _FakeL2CAP, int]:
    stack = Stack()
    l2cap = _FakeL2CAP()
    server = GATTServer()
    handles = server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x180D),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2A38),
                    properties=CharProperties.READ,
                    permissions=Permissions.READABLE,
                    value=b"\xAA" * 40,
                )
            ],
        )
    )
    stack._l2cap = l2cap
    stack._gatt_server = server
    return stack, server, l2cap, handles.characteristic_handles[0].value_handle


def test_attach_registers_eatt_listener_once_with_encryption_requirement():
    stack, _, l2cap, _ = _stack_with_gatt()
    stack._attach_gatt_server_to_att_channels()
    stack._attach_gatt_server_to_att_channels()  # idempotent
    assert len(l2cap.listeners) == 1
    psm, handler, required_security = l2cap.listeners[0]
    assert psm == PSM_EATT
    assert required_security == 4  # encryption — Core Vol 3 Part G §5.2


async def test_inbound_eatt_channel_gets_gatt_server_with_bearer_identity():
    stack, server, l2cap, value_handle = _stack_with_gatt()
    stack._attach_gatt_server_to_att_channels()
    _, listener, _ = l2cap.listeners[0]
    channel = _FakeEattChannel(mtu=100)
    listener(channel)

    assert server.is_eatt_bearer(CONN, EATT_CID)
    assert server._att_mtu(CONN, EATT_CID) == 100  # channel MTU, not 23

    await channel.events.on_data(ATT_Read_Request(attribute_handle=value_handle).to_bytes())
    assert len(channel.sent) == 1
    rsp = decode_att_pdu(channel.sent[0])
    assert isinstance(rsp, ATT_Read_Response)
    assert rsp.attribute_value == b"\xAA" * 40  # bearer MTU 100 fits it whole


async def test_attach_eatt_bearer_binds_outbound_channel():
    stack, server, _, value_handle = _stack_with_gatt()
    channel = _FakeEattChannel(mtu=64)
    stack.attach_eatt_bearer(channel)
    assert server.is_eatt_bearer(CONN, EATT_CID)
    assert server._att_mtu(CONN, EATT_CID) == 64
    await channel.events.on_data(ATT_Read_Request(attribute_handle=value_handle).to_bytes())
    assert channel.sent, "no ATT response on outbound EATT bearer"


async def test_attach_eatt_bearer_without_gatt_server_is_noop():
    stack = Stack()
    stack._l2cap = _FakeL2CAP()
    stack.attach_eatt_bearer(_FakeEattChannel())  # must not raise
```

- [x] **Step 2: 跑测试确认失败**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/test_stack_eatt.py -v
```
预期：FAIL —— listener 从不注册（`l2cap.listeners == []`）/ `AttributeError: attach_eatt_bearer`。

- [x] **Step 3: 实现**

`pybluehost/stack.py`：

① `Stack.__init__`（`self._classic_connection_waiters` 之后）加：

```python
        self._eatt_listener_registered = False
```

② 把 `_attach_gatt_server_to_att_channels`（805-881）重构为下述三个方法。通知回调注册部分（816-846 的 `on_notification`/`on_indication`/`on_multiple_notification` 三个 closure + 三行 `on_*_sent` 注册）**原样保留**在 `_attach_gatt_server_to_att_channels` 顶部；per-channel 部分抽出：

```python
    def _attach_gatt_server_to_att_channels(self) -> None:
        if self._l2cap is None or self._gatt_server is None:
            return

        from pybluehost.ble.att import (
            ATT_Handle_Value_Indication, ATT_Handle_Value_Notification,
            ATT_Multiple_Handle_Value_Notification,
        )
        from pybluehost.l2cap.constants import CID_ATT

        async def on_notification(handle: int, value: bytes, conn_handle: int) -> None:
            channel = self._l2cap.get_fixed_channel(conn_handle, CID_ATT)
            if channel is None:
                return
            notification = ATT_Handle_Value_Notification(
                attribute_handle=handle,
                attribute_value=value,
            )
            await channel.send(notification.to_bytes())

        async def on_indication(handle: int, value: bytes, conn_handle: int) -> bool:
            channel = self._l2cap.get_fixed_channel(conn_handle, CID_ATT)
            if channel is None:
                return False  # connection gone — the server defers the SC indication
            indication = ATT_Handle_Value_Indication(
                attribute_handle=handle,
                attribute_value=value,
            )
            await channel.send(indication.to_bytes())
            return True

        async def on_multiple_notification(hlv: list[tuple[int, bytes]], conn_handle: int) -> None:
            channel = self._l2cap.get_fixed_channel(conn_handle, CID_ATT)
            if channel is None:
                return
            notification = ATT_Multiple_Handle_Value_Notification(hlv=hlv)
            await channel.send(notification.to_bytes())

        self._gatt_server.on_notification_sent(on_notification)
        self._gatt_server.on_indication_sent(on_indication)
        self._gatt_server.on_multiple_notification_sent(on_multiple_notification)

        connections = getattr(self._l2cap, "_connections", {})
        for handle, channels in connections.items():
            channel = channels.get(CID_ATT)
            if channel is None or getattr(channel, "_gatt_server_bound", False):
                continue
            self._bind_gatt_server_to_channel(channel, conn_handle=handle, bearer_cid=CID_ATT)
            # Flush a Service Changed indication deferred while the bonded
            # client was disconnected (GAS/BV-01, BV-07): the Lower Tester
            # waits for it on reconnect without sending an ATT request first,
            # so it must be driven by the connection open. Fixed channel only —
            # EATT bearers attach after the connection is already up.
            asyncio.create_task(self._gatt_server.on_connection_opened(handle))

        self._ensure_eatt_listener()

    def _bind_gatt_server_to_channel(self, channel: Any, *, conn_handle: int, bearer_cid: int) -> None:
        """Attach the GATT server to one ATT-carrying channel (fixed ATT
        channel or EATT bearer). The ATT mux routes requests to the server with
        the bearer identity so per-bearer state (ATT_MTU, DoS marker) stays
        separate while per-client state (prepare queue, CCCD) is shared."""
        from pybluehost.ble.att import decode_att_pdu
        from pybluehost.l2cap.channel import install_att_channel_mux

        async def on_att_data(data: bytes) -> None:
            pdu = decode_att_pdu(data)
            response = await self._gatt_server.handle_request(conn_handle, pdu, bearer_cid=bearer_cid)
            if response is None:
                # Write Command / Signed Write Command — never answered.
                return
            await channel.send(response.to_bytes())

        # Register the server into the ATT mux rather than set_events() — a
        # GATT client bearer may share this channel (GAP/SEC) and must not be
        # clobbered (and vice versa).
        install_att_channel_mux(channel)
        channel._att_server_handler = on_att_data

        async def on_confirmation(data: bytes) -> None:
            # Handle Value Confirmation for the server's Service Changed
            # indication — clears the client's change-unaware flag (GAS/BV-06).
            self._gatt_server.on_confirmation(conn_handle)

        channel._att_confirmation_handler = on_confirmation
        setattr(channel, "_gatt_server_bound", True)
        logger.debug("GATT server bound conn=0x%04X bearer_cid=0x%04X", conn_handle, bearer_cid)

    def _ensure_eatt_listener(self) -> None:
        """Register the inbound EATT listener exactly once.

        EATT bearers are Enhanced Credit-Based channels on the fixed SPSM
        0x0027 and may only be established on an encrypted link (Core Vol 3
        Part G §5.2) — required_security=4 makes the L2CAP manager refuse
        unencrypted attempts with 0x0008 (Insufficient Encryption)."""
        if self._eatt_listener_registered:
            return
        listen = getattr(self._l2cap, "listen_le_coc_channel", None)
        if listen is None:
            return
        from pybluehost.l2cap.constants import PSM_EATT
        listen(PSM_EATT, self.attach_eatt_bearer, required_security=4)
        self._eatt_listener_registered = True

    def attach_eatt_bearer(self, channel: Any) -> None:
        """Attach the GATT server to an EATT channel — inbound (via the
        PSM_EATT listener) or outbound (BTP EATT_CONNECT). The bearer's ATT_MTU
        is the channel's negotiated L2CAP MTU (no Exchange MTU on EATT)."""
        if self._gatt_server is None:
            return
        self._gatt_server.add_eatt_bearer(
            channel.connection_handle, channel.cid, mtu=channel.mtu)
        self._bind_gatt_server_to_channel(
            channel, conn_handle=channel.connection_handle, bearer_cid=channel.cid)
```

（确认文件顶部有 `import asyncio`、`from typing import Any`、`logger` —— 既有代码都用到，已存在。）

> **Spec §5 对照**：「bearer 信道中途断开 → 响应 send 失败 → log + 丢弃」——`on_att_data` 里 `channel.send` 失败会让异常顺 ACL dispatch 冒泡并被信道读循环记录，与既有固定通道路径行为一致，**不**额外加 try/except（保持一致，避免吞错）。per-bearer 状态的主动清理由 BTP 0x09（Task 8）与 `remove_connection`（Task 2）覆盖。

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/test_stack_eatt.py -v
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/test_stack.py tests/unit/test_stack_auto_encrypt.py -q
```
预期：新 4 个 PASS；既有 stack 测试全绿（固定通道绑定路径行为不变——`test_stack_routes_att_request_to_gatt_server` 等）。

- [x] **Step 5: Commit**

```bash
git add pybluehost/stack.py tests/unit/test_stack_eatt.py
git commit -m "feat(stack): bind GATT server to EATT bearers — PSM_EATT listener + attach_eatt_bearer

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: BTP GATT —— `_handle_op_1f` attach bearer + SSF 0x2B3A = 0x01

**Files:**
- Modify: `pybluehost/pts/btp/services/gatt.py`（`_standard_gap_gatt_services` 151-155、`_handle_op_1f` 746-772）
- Test: `tests/unit/pts/btp/test_gatt_eatt_btp.py`（新建）

- [x] **Step 1: 写失败测试**

新建 `tests/unit/pts/btp/test_gatt_eatt_btp.py`：

```python
"""BTP GATT EATT_CONNECT (0x1f) wiring + Server Supported Features EATT bit."""
from __future__ import annotations

import pytest

from pybluehost.core.uuid import UUID16
from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.gatt import GattService, _standard_gap_gatt_services

pytestmark = pytest.mark.asyncio

WIRE_ADDR = bytes.fromhex("010203040506")
CONN = 0x0E01


class _FakePeer:
    def to_hci(self) -> bytes:
        return WIRE_ADDR


class _ConnInfo:
    transport = "le"
    peer = _FakePeer()


class _Session:
    connections = {CONN: _ConnInfo()}


class _FakeChannel:
    def __init__(self, cid: int) -> None:
        self.cid = cid
        self.connection_handle = CONN
        self.mtu = 512


class _FakeL2CAP:
    def __init__(self) -> None:
        self.eatt_calls: list[tuple[int, int]] = []
        self.channels = [_FakeChannel(0x0041), _FakeChannel(0x0042)]

    async def connect_eatt_channels(self, handle, *, num=1, timeout=5.0):
        self.eatt_calls.append((handle, num))
        return self.channels[:num]


class _FakeStack:
    def __init__(self) -> None:
        self.l2cap = _FakeL2CAP()
        self.attached: list[object] = []

    def attach_eatt_bearer(self, channel) -> None:
        self.attached.append(channel)


class _FakeActions:
    def __init__(self) -> None:
        self._stack = _FakeStack()

    def status(self):
        return _Session()


class _FakeTester:
    def emit_event(self, *args, **kwargs):
        pass


def test_server_supported_features_reports_eatt():
    """GAW/BV-12 and GAC/BI-01 initial conditions require SSF (0x2B3A) octet 0
    bit 0 set (EATT supported)."""
    services = _standard_gap_gatt_services()
    gatt = next(s for s in services if s.uuid == UUID16(0x1801))
    ssf = next(c for c in gatt.characteristics if c.uuid == UUID16(0x2B3A))
    assert ssf.value == b"\x01"


async def test_eatt_connect_attaches_each_channel_to_the_gatt_server():
    service = GattService(actions=_FakeActions(), tester=_FakeTester())
    status, payload = await service._handle_op_1f(0, bytes([0x00]) + WIRE_ADDR + bytes([2]))
    assert status == op.BTP_STATUS_SUCCESS
    assert payload == b""
    stack = service._actions._stack
    assert stack.l2cap.eatt_calls == [(CONN, 2)]
    assert stack.attached == stack.l2cap.channels


async def test_eatt_connect_unknown_peer_fails():
    service = GattService(actions=_FakeActions(), tester=_FakeTester())
    status, _ = await service._handle_op_1f(0, bytes([0x00]) + bytes(6) + bytes([1]))
    assert status == op.BTP_STATUS_FAILED
```

- [x] **Step 2: 跑测试确认失败**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/pts/btp/test_gatt_eatt_btp.py -v
```
预期：SSF 测试 FAIL（值是 `b"\x00"`）；attach 测试 FAIL（`attached == []`）。

- [x] **Step 3: 实现**

`pybluehost/pts/btp/services/gatt.py`：

① `_standard_gap_gatt_services`（151-155）SSF 值与注释：

```python
            CharacteristicDefinition(
                uuid=UUID16(0x2B3A),  # Server Supported Features
                properties=CharProperties.READ,
                permissions=Permissions.READABLE,
                value=b"\x01"),  # octet 0 bit 0: EATT supported (GAW/BV-12,
                                 # GAC/BI-01 initial conditions)
```

② `_handle_op_1f` 的成功尾部（767-772）改为：

```python
        try:
            channels = await l2cap.connect_eatt_channels(handle, num=num)
        except Exception:
            logger.exception("GATT EATT_CONNECT failed handle=0x%04X", handle)
            return op.BTP_STATUS_FAILED, b""
        # Attach the GATT server to each new bearer so the Lower Tester's ATT
        # requests on them are answered (GATT/SR GAR/BV-11/12, GAW/BV-12,
        # GPM/BV-05). TIM/BV-03 needs only the on-air request + collision
        # back-off — attaching is harmless there (no requests arrive).
        attach = getattr(stack, "attach_eatt_bearer", None)
        if callable(attach):
            for ch in channels:
                attach(ch)
        return op.BTP_STATUS_SUCCESS, b""
```

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/pts/btp/test_gatt_eatt_btp.py -v
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/pts/ -q
```
预期：新 3 个 PASS；pts 目录全绿。

- [x] **Step 5: Commit**

```bash
git add pybluehost/pts/btp/services/gatt.py tests/unit/pts/btp/test_gatt_eatt_btp.py
git commit -m "feat(pts): EATT_CONNECT attaches GATT server to bearers; SSF reports EATT

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: BTP L2CAP `DISCONNECT_EATT_CHANS (0x09)`

**Files:**
- Modify: `pybluehost/pts/btp/opcodes.py`（L2CAP 区 207-228）
- Modify: `pybluehost/pts/btp/services/l2cap.py`（新增 `_handle_op_09`，放在 `_handle_op_08` 附近）
- Test: `tests/unit/pts/btp/test_l2cap_disconnect_eatt.py`（新建）

- [x] **Step 1: 写失败测试**

新建 `tests/unit/pts/btp/test_l2cap_disconnect_eatt.py`：

```python
"""BTP L2CAP DISCONNECT_EATT_CHANS (0x09) — disconnect N EATT bearers by CID
order (auto-pts WID 144; wire format per auto-pts l2cap_disconn_eatt_chans)."""
from __future__ import annotations

import pytest

from pybluehost.ble.gatt import GATTServer
from pybluehost.l2cap.constants import PSM_EATT
from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.l2cap import LeCoCService

pytestmark = pytest.mark.asyncio

WIRE_ADDR = bytes.fromhex("010203040506")
CONN = 0x0E01


class _FakePeer:
    def to_hci(self) -> bytes:
        return WIRE_ADDR


class _ConnInfo:
    peer = _FakePeer()


class _Session:
    connections = {CONN: _ConnInfo()}


class _FakeChannel:
    def __init__(self, cid: int, psm) -> None:
        self.cid = cid
        self.psm = psm
        self.connection_handle = CONN


class _FakeL2CAP:
    def __init__(self, channels) -> None:
        self._connections = {CONN: {ch.cid: ch for ch in channels}}
        self.disconnected: list[int] = []

    async def disconnect_le_coc_channel(self, channel) -> None:
        self.disconnected.append(channel.cid)
        self._connections[CONN].pop(channel.cid, None)

    def on_le_channel_reconfigured(self, cb) -> None:
        pass


class _FakeStack:
    def __init__(self, channels) -> None:
        self.l2cap = _FakeL2CAP(channels)
        self._gatt_server = GATTServer()


class _FakeActions:
    def __init__(self, channels) -> None:
        self._stack = _FakeStack(channels)

    def status(self):
        return _Session()


class _FakeTester:
    def emit_event(self, *args, **kwargs):
        pass


def _service(*cids_and_psms) -> LeCoCService:
    channels = [_FakeChannel(cid, psm) for cid, psm in cids_and_psms]
    return LeCoCService(actions=_FakeActions(channels), tester=_FakeTester())


async def test_disconnects_first_n_eatt_channels_by_cid_order():
    service = _service((0x45, PSM_EATT), (0x41, PSM_EATT), (0x43, PSM_EATT), (0x50, 0x0080))
    status, payload = await service._handle_op_09(0, bytes([0x00]) + WIRE_ADDR + bytes([2]))
    assert status == op.BTP_STATUS_SUCCESS
    assert payload == b""
    # Lowest two EATT CIDs; the 0x0080 CoC channel is untouched.
    assert service._actions._stack.l2cap.disconnected == [0x41, 0x43]


async def test_count_beyond_available_disconnects_all_eatt():
    service = _service((0x41, PSM_EATT), (0x42, PSM_EATT))
    status, _ = await service._handle_op_09(0, bytes([0x00]) + WIRE_ADDR + bytes([5]))
    assert status == op.BTP_STATUS_SUCCESS
    assert service._actions._stack.l2cap.disconnected == [0x41, 0x42]


async def test_disconnect_drops_the_gatt_bearer_state():
    service = _service((0x41, PSM_EATT))
    server = service._actions._stack._gatt_server
    server.add_eatt_bearer(CONN, 0x41, mtu=100)
    status, _ = await service._handle_op_09(0, bytes([0x00]) + WIRE_ADDR + bytes([1]))
    assert status == op.BTP_STATUS_SUCCESS
    assert not server.is_eatt_bearer(CONN, 0x41)
    assert server._att_mtu(CONN, 0x41) == 23


async def test_unknown_peer_fails():
    service = _service((0x41, PSM_EATT))
    status, _ = await service._handle_op_09(0, bytes([0x00]) + bytes(6) + bytes([1]))
    assert status == op.BTP_STATUS_FAILED
```

- [x] **Step 2: 跑测试确认失败**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/pts/btp/test_l2cap_disconnect_eatt.py -v
```
预期：FAIL —— `AttributeError: _handle_op_09`。

- [x] **Step 3: 实现**

① `pybluehost/pts/btp/opcodes.py` L2CAP 区（`OP_L2CAP_CREDITS = 0x08` 之后）加：

```python
# 0x09 DISCONNECT_EATT_CHANS: disconnect N EATT bearers of a connection
# (auto-pts l2cap_disconn_eatt_chans; WID 144 in the GATT/SR EATT cases).
OP_L2CAP_DISCONNECT_EATT_CHANS = 0x09
```

（顶部注释行「Out of P.8 v1: …」同步把 0x09 从"out"列表语义里移除——它写的是 0x06/0x07/0x0a 等，若 0x09 不在列表则不用动。）

② `pybluehost/pts/btp/services/l2cap.py` 加 handler（放在 `_handle_op_08` 之后）：

```python
    async def _handle_op_09(self, controller_index: int, data: bytes):
        """DISCONNECT_EATT_CHANS (0x09) — body addr_type(1) + addr(6 LE) +
        channel_count(1). Response is parameterless.

        Disconnect the first `count` EATT bearers (channels on the fixed EATT
        SPSM 0x0027) of the resolved connection, lowest CID first; a count
        beyond what exists disconnects all of them. auto-pts drives this from
        WID 144 (the GATT/SR EATT multi-bearer cases tear down bearers
        mid-test).
        """
        from pybluehost.l2cap.constants import PSM_EATT

        if len(data) != 8:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        count = data[7]
        stack = getattr(self._actions, "_stack", None)
        l2cap = getattr(stack, "l2cap", None) if stack is not None else None
        if l2cap is None:
            return op.BTP_STATUS_FAILED, b""
        handle = self._resolve_le_connection_handle(addr)
        if handle is None:
            return op.BTP_STATUS_FAILED, b""
        channels = sorted(
            (ch for ch in getattr(l2cap, "_connections", {}).get(handle, {}).values()
             if getattr(ch, "psm", None) == PSM_EATT),
            key=lambda ch: ch.cid,
        )
        gatt_server = getattr(stack, "_gatt_server", None)
        for ch in channels[:count]:
            cid = ch.cid
            await l2cap.disconnect_le_coc_channel(ch)
            if gatt_server is not None:
                gatt_server.remove_eatt_bearer(handle, cid)
        return op.BTP_STATUS_SUCCESS, b""
```

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/pts/btp/test_l2cap_disconnect_eatt.py -v
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/unit/pts/ -q
```
预期：新 4 个 PASS；pts 目录全绿（`supported_commands` 位图自动含 bit 9，既有 `READ_SUPPORTED_COMMANDS` 测试若断言精确位图需同步——若 FAIL，更新该测试期望值把 bit 9 加上）。

- [x] **Step 5: Commit**

```bash
git add pybluehost/pts/btp/opcodes.py pybluehost/pts/btp/services/l2cap.py tests/unit/pts/btp/test_l2cap_disconnect_eatt.py
git commit -m "feat(pts): BTP L2CAP DISCONNECT_EATT_CHANS (0x09) — WID 144 bearer teardown

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: e2e —— VirtualLELink 双 EATT bearer loopback

**Files:**
- Modify: `tests/e2e/test_le_coc_lifecycle.py`（追加两个测试）

- [x] **Step 1: 追加测试（直接写，预期先 FAIL——EATT listener/attach 依赖 Task 6，若按序执行此处应直接 PASS；FAIL 则说明集成链路有缺口，修实现）**

文件顶部 import 已有 `VirtualLELink`、`SimpleChannelEvents`、`asyncio`、`pytest`。追加：

```python
async def test_eatt_bearers_answer_att_requests_over_virtual_link(le_pair):
    """Two EATT bearers over ECFC (SPSM 0x0027): each answers ATT requests with
    its own bearer MTU. The EATT listener requires an encrypted link, so mark
    the responder side encrypted (white-box: the security state is normally
    fed by HCI Encryption Change)."""
    from pybluehost.ble.att import ATT_Read_Request, ATT_Read_Response, decode_att_pdu
    from pybluehost.ble.gatt import (
        CharacteristicDefinition, CharProperties, Permissions, ServiceDefinition,
    )
    from pybluehost.core.uuid import UUID16

    central, peripheral, c_handle, p_handle = le_pair
    handles = peripheral.gatt_server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x180D),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2A38),
                    properties=CharProperties.READ,
                    permissions=Permissions.READABLE,
                    value=b"AB" * 40,  # 80 bytes — fits EATT MTU, not MTU 23
                )
            ],
        )
    )
    value_handle = handles.characteristic_handles[0].value_handle
    peripheral.l2cap.set_le_connection_security(
        p_handle, encrypted=True, authenticated=True, key_size=16)

    channels = await central.l2cap.connect_eatt_channels(c_handle, num=2, timeout=2.0)
    assert len(channels) == 2

    for ch in channels:
        received: list[bytes] = []
        ch.set_events(SimpleChannelEvents(on_data=lambda d, r=received: r.append(bytes(d))))
        await ch.send(ATT_Read_Request(attribute_handle=value_handle).to_bytes())
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.02)
        assert received, "no ATT response on EATT bearer"
        rsp = decode_att_pdu(received[0])
        assert isinstance(rsp, ATT_Read_Response)
        # EATT bearer ATT_MTU is the channel L2CAP MTU (512): the whole
        # 80-byte value comes back — the fixed ATT channel would give 22.
        assert rsp.attribute_value == b"AB" * 40


async def test_eatt_connect_refused_on_unencrypted_link(le_pair):
    """Core Vol 3 Part G §5.2: EATT may only be established on an encrypted
    link — the listener refuses with 0x0008 (Insufficient Encryption)."""
    from pybluehost.core.errors import LECoCConnectError

    central, peripheral, c_handle, p_handle = le_pair
    with pytest.raises(LECoCConnectError) as exc_info:
        await central.l2cap.connect_eatt_channels(c_handle, num=1, timeout=2.0)
    assert exc_info.value.result == 0x0008
```

- [x] **Step 2: 跑测试**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/e2e/test_le_coc_lifecycle.py -v --transport=virtual
```
预期：3 个全 PASS（含既有 `test_le_coc_connect_send_disconnect`）。

> ⚠️ 若 `test_eatt_connect_refused_on_unencrypted_link` 超时而非抛错：检查 `connect_eatt_channels` 的 0x0004 重试逻辑是否把 0x0008 也吞了——0x0008 应立即抛出（只有 0x0004 触发 back-off 重试）。

- [x] **Step 3: Commit**

```bash
git add tests/e2e/test_le_coc_lifecycle.py
git commit -m "test(e2e): EATT bearer loopback over VirtualLELink + encryption gate

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: 全套回归 + 文档自维护 + 真机 PTS 收割 + 合并

**Files:**
- Modify: `AGENTS.md`（"已交付子系统" LE CoC manager 小节后追加 EATT 段落）
- Modify: `docs/superpowers/STATUS.md`
- Modify: `docs/pts/results/matrix/gatt.yaml`（真机收割后由导入脚本更新）

- [x] **Step 1: 全套测试**

```bash
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe -m pytest tests/ -q --transport=virtual > /tmp/eatt_full.txt 2>&1; tail -5 /tmp/eatt_full.txt
```
预期：全绿，除 3 个既有 e2e 失败（`test_le_lifecycle` 的 StopIteration——master 基线同样失败，与本特性无关，见 spec §7）。若出现其他失败 → 修复后重跑，**不得带红合并**。

- [x] **Step 2: AGENTS.md 更新**

在 "### LE CoC manager（L2CAP LE Credit-Based Channel）" 小节末尾追加：

```markdown
### EATT 多 bearer（GATT server 侧）

GATT server 支持 Enhanced ATT bearer（Enhanced Credit-Based 信道，固定 SPSM 0x0027）：

```python
# 入向：Stack 自动在 PSM_EATT 上监听（required_security=4，未加密拒 0x0008），
#       inbound ECFC 信道自动绑 GATT server。
# 出向（BTP EATT_CONNECT 已自动 attach）；手动场景：
stack.attach_eatt_bearer(channel)  # channel = LECoCChannel（psm==PSM_EATT）
```

- 语义：`GATTServer.handle_request(conn, pdu, *, bearer_cid=CID_ATT)`；ATT_MTU 与 robust-caching "DoS sent once" 标记按 `(conn_handle, bearer_cid)` 键控，prepare queue / CCCD / security 按 `conn_handle`（per-client 共享，符合 GATT.TS GAW/BV-12、GPM/BV-05）。
- EATT bearer 上 Exchange MTU 回 `0x06 Request Not Supported`（GAC/BI-01）；bearer MTU = 信道 L2CAP MTU（`add_eatt_bearer(conn, cid, mtu=...)`）。
- BTP：GATT `EATT_CONNECT(0x1f)` 建 bearer 并 attach；L2CAP `DISCONNECT_EATT_CHANS(0x09)` 按 CID 升序断前 N 条。SSF 0x2B3A 报 EATT 位（0x01）。
- 测试：`tests/unit/ble/test_gatt_eatt.py`、`tests/unit/test_stack_eatt.py`、`tests/unit/pts/btp/test_gatt_eatt_btp.py`、`test_l2cap_disconnect_eatt.py`、`tests/e2e/test_le_coc_lifecycle.py`（EATT loopback）。
- **不做**：CL 侧 per-bearer 发起（auto-pts 无 BTP 驱动入口）、通知经 EATT 发送、BR/EDR EATT。
```

- [x] **Step 3: STATUS.md 更新**（Plan 状态 ✅ 待真机收割 → 收割后改 ✅）

- [x] **Step 4: Commit 文档**

```bash
git add AGENTS.md docs/superpowers/STATUS.md docs/superpowers/plans/2026-09-17-eatt-multi-bearer.md
git commit -m "docs: EATT multi-bearer plan complete — AGENTS/STATUS update

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [x] **Step 5: 真机 PTS 收割（需要 PTS 座架在线：autoptsserver + 双 dongle）**

```bash
# 固定通道回归守卫先跑
PYBLUEHOST_HARVEST_WARMUP=GATT/SR/GAR/BV-01-C bash scripts/pts_harvest.sh GATT/SR/GAR/BV-01-C
# 目标用例（peripheral flaky 时用 scripts/pts_retry_cases.sh 单例重跑）
bash scripts/pts_retry_cases.sh 5 \
    GATT/SR/GAR/BV-11-C GATT/SR/GAR/BV-12-C GATT/SR/GAW/BV-12-C \
    GATT/SR/GPM/BV-05-C GATT/SR/GAC/BI-01-C
# 顺带验证既有 EATT 出向路径
bash scripts/pts_retry_cases.sh 3 L2CAP/TIM/BV-03-C
# 录入矩阵（blocked 守卫已在导入器里）
H:/github/bluetooth/pybluehost/.venv/Scripts/python.exe scripts/pts_import_verdicts.py /tmp/auto-pts/logs --date 2026-09-17
```

verdict 录入后 commit 矩阵变更。若某例反复 INDCSV/FAIL：按 AGENTS.md 既有流程定性（peripheral flaky 重跑 / PTS 侧行为 / 真 bug），真 bug 回到对应 Task 修。

- [x] **Step 6: 合并回 master**

```bash
cd /h/github/bluetooth/pybluehost
git fetch . 2>/dev/null; git log --oneline -1 master
git merge --ff-only claude/eatt-multi-bearer || git merge --no-ff claude/eatt-multi-bearer -m "merge: EATT multi-bearer (GATT server side)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

合并后 STATUS.md 标记 ✅（若合并产生新 commit，在 master 上补 STATUS 更新）。

---

## 常见问题 / Troubleshooting

（执行中发现问题时按 STATUS.md 协议追加到这里。）
