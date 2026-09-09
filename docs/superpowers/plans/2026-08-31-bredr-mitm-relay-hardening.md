# BR/EDR MITM Relay 硬件就绪化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有 BR/EDR MITM 骨架（`pybluehost/cli/app/mitm/`）补上真机运行所缺的四块 HCI 接线 + 三个配套工具，使 `pybluehost app mitm --transport-mode bredr` 能在"手机 ↔ BE200#1 ↔ BE200#2 ↔ TWS 耳机"拓扑上跑通 G1–G7 关卡。

**Architecture:** 纯 ACL/L2CAP 透传（见 spec `docs/superpowers/specs/2026-08-31-bredr-mitm-test-plan.md`）。配对由两侧控制器各自 SSP 终结（已有 `SspTermination`），本计划补：上游 `Create_Connection` 发起（T1）、下游 `Connection_Request` auto-accept（T2）、断链联动 + relay 常驻（T3）、link key JSONL 落盘（T4）、adb 手机助手（T5）、btsnoop 媒体流质量分析（T6）、runbook（T7）。

**Tech Stack:** Python 3.10+ asyncio、pytest+pytest-asyncio（`asyncio_mode=auto`）、pyusb、adb 子进程。

**关键环境事实（执行时直接用，来自 G0 实测）：**
- BE200#1 (downstream·对手机) = `usb:8087:0036#1` = `94:53:FF:1E:6A:EE`
- BE200#2 (upstream·对耳机) = `usb:8087:0036#2` = `5C:67:83:07:04:EE`
- 耳机 `98:1D:F9:90:11:1E`，COM22，MCP `localhost:57666`，固件开机自动进配对
- **pytest 用 `./.venv/Scripts/python.exe -m pytest`（不要 `uv run`，会冲掉 auto-pts editable）**
- mitm 层 HARD RULE：**不 import** `pybluehost.l2cap/.ble/.classic/.gap/.profiles/.stack`，只用 `hci.*` + `core.*` + `mitm.*`

**预存在 baseline 失败（与计划无关，勿修）：** 8 个 BTP bridge 集成测试在 master 上就挂（已验证）。

---

### Task 1: 上游 Create_Connection 发起

现状：`_run_relay_bredr` 只在两侧**等** Connection Complete，没人主动连耳机。本任务加 initiator 逻辑。

**Files:**
- Modify: `pybluehost/cli/app/mitm/orchestrator.py`（加 `build_create_connection_params()` 模块函数 + `MitmRelay._connect_bredr_target()`）
- Test: `tests/unit/mitm/test_orchestrator_bredr_connect.py`（新建）

参考先例（**只可仿写不可 import**）：`pybluehost/classic/gap.py:236-246` 的 `ClassicConnectionManager.connect`。注意先例的 packet_type=`0x0018`（仅 DM3|DH3）——**本计划刻意改用 `0xFC7E`**（DM1/3/5 + DH1/3/5 + 2-DH1/3/5 + 3-DH1/3/5），A2DP 媒体流需要 EDR 多时隙包，否则 G5 的码率不可能达标。

`HCI_CREATE_CONNECTION` 常量已在 `pybluehost/hci/constants.py:39`。Connection Complete 事件布局：`status(1) + handle(2 LE) + bd_addr(6 LE) + link_type(1) + encryption_mode(1)`。

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/mitm/test_orchestrator_bredr_connect.py`：

```python
"""T1: 上游 BR/EDR Create_Connection 发起的单元测试。"""
import asyncio

import pytest

from pybluehost.cli.app.mitm.orchestrator import (
    MitmRelay,
    build_create_connection_params,
)
from pybluehost.hci.constants import HCI_CREATE_CONNECTION, EventCode
from pybluehost.hci.packets import HCICommand, HCIEvent

TARGET = "98:1D:F9:90:11:1E"
TARGET_LE = bytes.fromhex("1E1190F91D98")  # 上述地址的小端 wire 序


class FakeConnectController:
    """捕获 set_upstream 回调 + 记录发出的命令,可注入事件。"""

    def __init__(self):
        self.on_hci_event = None
        self.sent: list[HCICommand] = []
        # 预排:每次 Create_Connection 后注入的 Connection Complete status 队列
        self.complete_statuses: list[int] = []

    def set_upstream(self, on_hci_event=None, on_acl_data=None, on_sco_data=None):
        self.on_hci_event = on_hci_event

    async def send_command(self, command):
        self.sent.append(command)
        if command.opcode == HCI_CREATE_CONNECTION and self.complete_statuses:
            status = self.complete_statuses.pop(0)
            if status == 0x00:
                params = bytes([0x00]) + (0x0011).to_bytes(2, "little") + TARGET_LE + b"\x01\x00"
            else:
                params = bytes([status]) + (0x0000).to_bytes(2, "little") + TARGET_LE + b"\x01\x00"
            self.on_hci_event(HCIEvent.from_bytes(EventCode.CONNECTION_COMPLETE, params))


def _bare_relay():
    relay = MitmRelay.__new__(MitmRelay)
    relay._connect_timeout = 2.0
    return relay


def test_build_create_connection_params_layout():
    params = build_create_connection_params(TARGET_LE)
    assert params[0:6] == TARGET_LE
    assert int.from_bytes(params[6:8], "little") == 0xFC7E  # EDR 多时隙全开
    assert params[8] == 0x01   # page_scan_repetition_mode R1
    assert params[9] == 0x00   # reserved
    assert params[10:12] == b"\x00\x00"  # clock_offset unknown
    assert params[12] == 0x01  # allow_role_switch


async def test_connect_returns_handle_on_success():
    ctl = FakeConnectController()
    ctl.complete_statuses = [0x00]
    relay = _bare_relay()
    handle = await relay._connect_bredr_target(ctl, TARGET)
    assert handle == 0x0011
    assert ctl.sent[0].opcode == HCI_CREATE_CONNECTION
    assert ctl.on_hci_event is None  # finally 恢复了上游回调


async def test_connect_retries_on_page_timeout():
    ctl = FakeConnectController()
    ctl.complete_statuses = [0x04, 0x00]  # 第一次 page timeout,第二次成功
    relay = _bare_relay()
    handle = await relay._connect_bredr_target(ctl, TARGET)
    assert handle == 0x0011
    assert len(ctl.sent) == 2  # 发了两次 Create_Connection


async def test_connect_raises_after_max_retries():
    ctl = FakeConnectController()
    ctl.complete_statuses = [0x04, 0x04, 0x04]
    relay = _bare_relay()
    with pytest.raises(RuntimeError, match="Create_Connection"):
        await relay._connect_bredr_target(ctl, TARGET, max_retries=3)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/mitm/test_orchestrator_bredr_connect.py -v
```

预期：4 个全 FAIL（`ImportError: cannot import name 'build_create_connection_params'`）。

- [ ] **Step 3: 实现**

在 `orchestrator.py` 顶部 import 区加 `HCI_CREATE_CONNECTION` 到 `from pybluehost.hci.constants import (...)` 列表，然后加：

```python
# A2DP 需要 EDR 多时隙包:DM1/3/5 + DH1/3/5 + 2-DH1/3/5 + 3-DH1/3/5。
# 刻意不用 classic/gap.py 先例的 0x0018(仅 DM3|DH3)——那会让媒体流跑不动。
_BREDR_PACKET_TYPE_ALL = 0xFC7E


def build_create_connection_params(addr_le: bytes, *, allow_role_switch: bool = True) -> bytes:
    """HCI_Create_Connection 参数体(Core Vol 4 Part E §7.1.5)。

    page_scan_repetition_mode 固定 R1、clock_offset 未知(0)——recon 目前不采
    这两个值,首次 page 略慢但可靠;后续要加速可在 ClonedIdentity 里带上。
    """
    assert len(addr_le) == 6
    return (
        addr_le
        + _BREDR_PACKET_TYPE_ALL.to_bytes(2, "little")
        + bytes([0x01])  # page_scan_repetition_mode R1
        + bytes([0x00])  # reserved
        + (0x0000).to_bytes(2, "little")  # clock_offset
        + bytes([0x01 if allow_role_switch else 0x00])
    )
```

`MitmRelay` 加方法（放在 `_await_bredr_connection` 旁）：

```python
    async def _connect_bredr_target(
        self, controller: "HCIController", target_addr: str, *, max_retries: int = 5
    ) -> int:
        """作为 initiator 连接 BR/EDR 目标,返回 connection handle。

        失败状态(如 0x04 page timeout)整轮重试;每次 attempt 等
        self._connect_timeout 秒。事件钩子在 finally 里恢复全部三个上游回调
        (set_upstream 是全量替换语义)。
        """
        addr_le = bytes(reversed(bytes.fromhex(target_addr.replace(":", ""))))
        params = build_create_connection_params(addr_le)
        loop = asyncio.get_running_loop()
        prev_hci = controller._on_hci_event   # type: ignore[attr-defined]
        prev_acl = controller._on_acl_data    # type: ignore[attr-defined]
        prev_sco = controller._on_sco_data    # type: ignore[attr-defined]
        state: dict = {"fut": loop.create_future(), "handle": None, "status": None}

        def on_event(event: HCIEvent) -> None:
            if event.event_code == EventCode.CONNECTION_COMPLETE:
                p = event.parameters
                if len(p) >= 9 and p[3:9] == addr_le:
                    state["status"] = p[0]
                    if not state["fut"].done():
                        if p[0] == 0x00:
                            state["handle"] = int.from_bytes(p[1:3], "little")
                            state["fut"].set_result(True)
                        else:
                            state["fut"].set_result(False)
            if prev_hci is not None:
                result = prev_hci(event)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)

        controller.set_upstream(on_hci_event=on_event)
        try:
            for attempt in range(1, max_retries + 1):
                state["fut"] = loop.create_future()  # send 前重置,防事件抢跑
                await controller.send_command(
                    HCICommand(opcode=HCI_CREATE_CONNECTION, parameters=params)
                )
                try:
                    ok = await asyncio.wait_for(state["fut"], timeout=self._connect_timeout)
                except asyncio.TimeoutError:
                    ok = False
                if ok:
                    logger.info("BR/EDR 已连上目标 %s handle=0x%03X", target_addr, state["handle"])
                    return state["handle"]
                logger.warning(
                    "Create_Connection 第 %d/%d 次失败 status=%s",
                    attempt, max_retries, state["status"],
                )
            raise RuntimeError(
                f"Create_Connection to {target_addr} failed after {max_retries} attempts"
            )
        finally:
            controller.set_upstream(
                on_hci_event=prev_hci, on_acl_data=prev_acl, on_sco_data=prev_sco
            )
```

`_run_relay_bredr` 的 step 1 改成上游主动连（替换原 `self._await_bredr_connection(upstream)`）：

```python
        # --- 1. 上游主动连耳机,下游等手机 page -----------------------------
        if self._identity is None:
            raise RuntimeError("_run_relay_bredr 需要先有 recon 结果(run_recon)")
        target_handle, phone_handle = await asyncio.gather(
            self._connect_bredr_target(upstream, self._identity.address),
            self._await_bredr_connection(downstream),
        )
```

- [ ] **Step 4: 跑测试确认通过**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/mitm/test_orchestrator_bredr_connect.py -v
```

预期：4 PASS。再跑 `./.venv/Scripts/python.exe -m pytest tests/unit/mitm/ -q` 确认无回归。

- [ ] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/orchestrator.py tests/unit/mitm/test_orchestrator_bredr_connect.py
git commit -m "feat(mitm): BR/EDR upstream Create_Connection with retry + EDR packet types"
```

---

### Task 2: 下游 Connection Request auto-accept

手机 page BE200#1 时控制器报 `Connection_Request(0x04)`，必须回 `HCI_Accept_Connection_Request` 否则连接超时。常量 `HCI_ACCEPT_CONNECTION_REQ` 已在 `hci/constants.py:41`。

**Files:**
- Modify: `pybluehost/cli/app/mitm/orchestrator.py`（`_await_bredr_connection` 加 `auto_accept` 参数）
- Test: `tests/unit/mitm/test_orchestrator_bredr_accept.py`（新建）

Connection_Request(0x04) 事件布局：`bd_addr(6) + class_of_device(3) + link_type(1)`；`link_type=0x01` 是 ACL（0x00=SCO 不接受——SCO 本就不在范围内）。Accept 参数：`bd_addr(6) + role(1)`，`role=0x01` = 保持 slave（手机当 master，经典角色）。

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/mitm/test_orchestrator_bredr_accept.py`：

```python
"""T2: 下游 Connection_Request auto-accept 的单元测试。"""
import asyncio

from pybluehost.cli.app.mitm.orchestrator import MitmRelay
from pybluehost.hci.constants import HCI_ACCEPT_CONNECTION_REQ, EventCode
from pybluehost.hci.packets import HCICommand, HCIEvent

PHONE_LE = bytes.fromhex("20E8AABBCCDD")  # 手机地址小端(示意)
ACL_LINK = 0x01
SCO_LINK = 0x00


class FakeAcceptController:
    def __init__(self):
        self.on_hci_event = None
        self.sent: list[HCICommand] = []

    def set_upstream(self, on_hci_event=None, on_acl_data=None, on_sco_data=None):
        self.on_hci_event = on_hci_event

    async def send_command(self, command):
        self.sent.append(command)

    def inject_conn_request(self, link_type=ACL_LINK):
        params = PHONE_LE + b"\x24\x04\x0C" + bytes([link_type])  # CoD 任意
        self.on_hci_event(HCIEvent.from_bytes(EventCode.CONNECTION_REQUEST, params))

    def inject_conn_complete(self, handle=0x0021):
        params = bytes([0x00]) + handle.to_bytes(2, "little") + PHONE_LE + b"\x01\x00"
        self.on_hci_event(HCIEvent.from_bytes(EventCode.CONNECTION_COMPLETE, params))


def _bare_relay():
    relay = MitmRelay.__new__(MitmRelay)
    relay._connect_timeout = 1.0
    return relay


async def test_auto_accept_replies_accept_for_acl():
    ctl = FakeAcceptController()
    relay = _bare_relay()
    task = asyncio.ensure_future(relay._await_bredr_connection(ctl, auto_accept=True))
    await asyncio.sleep(0)  # 让 hook 装上
    ctl.inject_conn_request(ACL_LINK)
    await asyncio.sleep(0.05)  # accept 是 ensure_future 发出的
    assert ctl.sent[0].opcode == HCI_ACCEPT_CONNECTION_REQ
    assert ctl.sent[0].parameters[0:6] == PHONE_LE
    assert ctl.sent[0].parameters[6] == 0x01  # role=slave,手机当 master
    ctl.inject_conn_complete()
    assert await asyncio.wait_for(task, 1.0) == 0x0021


async def test_auto_accept_ignores_sco_request():
    ctl = FakeAcceptController()
    relay = _bare_relay()
    task = asyncio.ensure_future(relay._await_bredr_connection(ctl, auto_accept=True))
    await asyncio.sleep(0)
    ctl.inject_conn_request(SCO_LINK)
    await asyncio.sleep(0.05)
    assert ctl.sent == []
    ctl.inject_conn_complete()
    await asyncio.wait_for(task, 1.0)


async def test_no_accept_when_auto_accept_off():
    ctl = FakeAcceptController()
    relay = _bare_relay()
    task = asyncio.ensure_future(relay._await_bredr_connection(ctl, auto_accept=False))
    await asyncio.sleep(0)
    ctl.inject_conn_request(ACL_LINK)
    await asyncio.sleep(0.05)
    assert ctl.sent == []
    ctl.inject_conn_complete()
    await asyncio.wait_for(task, 1.0)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/mitm/test_orchestrator_bredr_accept.py -v
```

预期：3 FAIL（`_await_bredr_connection() got an unexpected keyword argument 'auto_accept'`）。

- [ ] **Step 3: 实现**

`orchestrator.py` import 区加 `HCI_ACCEPT_CONNECTION_REQ`。`_await_bredr_connection` 签名改为：

```python
    async def _await_bredr_connection(
        self, controller: "HCIController", *, auto_accept: bool = True
    ) -> int:
```

在其 `on_event` 内、`CONNECTION_COMPLETE` 分支前加：

```python
            if event.event_code == EventCode.CONNECTION_REQUEST:
                # bd_addr(6) + class_of_device(3) + link_type(1);只接 ACL(0x01)。
                p = event.parameters
                if len(p) >= 10 and p[9] == 0x01 and auto_accept:
                    asyncio.ensure_future(
                        controller.send_command(
                            HCICommand(
                                opcode=HCI_ACCEPT_CONNECTION_REQ,
                                parameters=p[0:6] + bytes([0x01]),  # role=保持 slave
                            )
                        )
                    )
```

`_run_relay_bredr` 里下游调用保持 `self._await_bredr_connection(downstream)`（默认 auto_accept=True 即可）。

- [ ] **Step 4: 跑测试确认通过**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/mitm/test_orchestrator_bredr_accept.py tests/unit/mitm/test_orchestrator.py -q
```

预期：新 3 PASS + 旧 mitm 测试无回归。

- [ ] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/orchestrator.py tests/unit/mitm/test_orchestrator_bredr_accept.py
git commit -m "feat(mitm): BR/EDR downstream auto-accept Connection_Request (ACL only)"
```

---

### Task 3: 断链联动 + relay 常驻

现状两个洞：① 一侧断链另一侧成半开链路；② `_run_relay_bredr` 注册完回调就 return，CLI 的 gather 立刻走完进 finally → teardown，**relay 根本活不住**。本任务一起修。

⚠️ 关键约束：`controller.set_upstream()` 是**全量替换三个回调**（`controller.py:197-206`）。relay 已用 `set_upstream(on_acl_data=...)`，再加事件监听必须在**同一次调用**里带上 `on_acl_data`，否则 ACL 回调被清掉。

**Files:**
- Modify: `pybluehost/cli/app/mitm/orchestrator.py`（`_make_link_watch` + `_on_link_lost` + `_run_relay_bredr` 尾部）
- Test: `tests/unit/mitm/test_orchestrator_bredr_disconnect.py`（新建）

`HCI_DISCONNECT` 常量在 `hci/constants.py:40`；Disconnection_Complete(0x05) 布局：`status(1) + handle(2 LE) + reason(1)`。

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/mitm/test_orchestrator_bredr_disconnect.py`：

```python
"""T3: 断链联动(一侧断→断对侧)与 relay 常驻的单元测试。"""
import asyncio

from pybluehost.cli.app.mitm.orchestrator import MitmRelay
from pybluehost.hci.constants import HCI_DISCONNECT, EventCode
from pybluehost.hci.packets import HCICommand, HCIEvent


class FakeSide:
    def __init__(self):
        self.on_hci_event = None
        self.on_acl_data = None
        self.sent: list[HCICommand] = []

    def set_upstream(self, on_hci_event=None, on_acl_data=None, on_sco_data=None):
        self.on_hci_event = on_hci_event
        self.on_acl_data = on_acl_data

    async def send_command(self, command):
        self.sent.append(command)

    def inject_disconnect(self, handle, reason=0x13):
        params = bytes([0x00]) + handle.to_bytes(2, "little") + bytes([reason])
        self.on_hci_event(HCIEvent.from_bytes(EventCode.DISCONNECTION_COMPLETE, params))


def _bare_relay():
    relay = MitmRelay.__new__(MitmRelay)
    relay._link_lost = asyncio.Event()
    return relay


async def test_phone_disconnect_triggers_target_disconnect():
    phone, target = FakeSide(), FakeSide()
    relay = _bare_relay()
    # 模拟 _run_relay_bredr 尾部的组合注册
    phone.set_upstream(
        on_acl_data=lambda acl: None,
        on_hci_event=relay._make_link_watch("phone", 0x0021, target, 0x0011),
    )
    phone.inject_disconnect(0x0021)
    await asyncio.sleep(0.05)
    assert target.sent[0].opcode == HCI_DISCONNECT
    assert int.from_bytes(target.sent[0].parameters[0:2], "little") == 0x0011
    assert relay._link_lost.is_set()


async def test_disconnect_for_other_handle_ignored():
    phone, target = FakeSide(), FakeSide()
    relay = _bare_relay()
    phone.set_upstream(
        on_acl_data=lambda acl: None,
        on_hci_event=relay._make_link_watch("phone", 0x0021, target, 0x0011),
    )
    phone.inject_disconnect(0x0099)  # 别的 handle
    await asyncio.sleep(0.05)
    assert target.sent == []
    assert not relay._link_lost.is_set()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/mitm/test_orchestrator_bredr_disconnect.py -v
```

预期：2 FAIL（`AttributeError: 'MitmRelay' object has no attribute '_make_link_watch'`）。

- [ ] **Step 3: 实现**

`orchestrator.py` import 区加 `HCI_DISCONNECT`。`MitmRelay.__init__` 加字段：

```python
        self._link_lost: Optional[asyncio.Event] = None
```

加两个方法：

```python
    def _make_link_watch(
        self,
        side_name: str,
        my_handle: int,
        peer_controller: "HCIController",
        peer_handle: int,
    ) -> Callable[[HCIEvent], None]:
        """生成断链监听:本侧 handle 断开 → 断对侧 + 置 _link_lost。"""

        def on_event(event: HCIEvent) -> None:
            if event.event_code == EventCode.DISCONNECTION_COMPLETE:
                p = event.parameters
                if len(p) >= 4 and int.from_bytes(p[1:3], "little") == my_handle:
                    logger.warning(
                        "MITM %s 侧链路断开 handle=0x%03X reason=0x%02X,联动断对侧",
                        side_name, my_handle, p[3],
                    )
                    asyncio.ensure_future(self._on_link_lost(peer_controller, peer_handle))

        return on_event

    async def _on_link_lost(
        self, peer_controller: "HCIController", peer_handle: int
    ) -> None:
        try:
            await peer_controller.send_command(
                HCICommand(
                    opcode=HCI_DISCONNECT,
                    parameters=peer_handle.to_bytes(2, "little") + bytes([0x16]),
                )
            )
        except Exception:
            logger.exception("MITM: 对侧 disconnect 失败")
        if self._link_lost is not None:
            self._link_lost.set()
```

`_run_relay_bredr` 的 step 4/5 替换为（关键：**一次 set_upstream 同时给两个回调**）：

```python
        # --- 4. 注册 ACL 回调 + 断链监听(同一次 set_upstream,防止互相覆盖) ---
        self._link_lost = asyncio.Event()
        downstream.set_upstream(
            on_acl_data=relay.on_phone_acl,
            on_hci_event=self._make_link_watch("phone", phone_handle, upstream, target_handle),
        )
        upstream.set_upstream(
            on_acl_data=relay.on_target_acl,
            on_hci_event=self._make_link_watch("target", target_handle, downstream, phone_handle),
        )

        # --- 5. SSP 由 SspTermination 事件驱动;经典加密随 SSP 自动协商 ---
        # --- 6. 常驻:直到任一侧断链(或 Ctrl-C 由 CLI 层 finally 收尾) ------
        await self._link_lost.wait()
```

- [ ] **Step 4: 跑测试确认通过**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/mitm/ -q
```

预期：全 PASS（含旧 96 个无回归）。

- [ ] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/orchestrator.py tests/unit/mitm/test_orchestrator_bredr_disconnect.py
git commit -m "feat(mitm): BR/EDR link-loss teardown coupling + relay stays resident"
```

---

### Task 4: link key JSONL 落盘

`SspTermination._on_lkn` 已把 key 存内存 dict（`ssp.py:110-112`），本任务加 JSONL 落盘，供密钥捕获交付物 + 与耳机固件 log 交叉验证。

**Files:**
- Modify: `pybluehost/cli/app/mitm/pairing/ssp.py`（`__init__` 加 `key_log_path`、`_on_lkn` 落盘）
- Modify: `pybluehost/cli/app/mitm/orchestrator.py`（`MitmRelay.__init__` 加 `key_log`、`_build_relay_bredr` 传给两个 SspTermination）
- Modify: `pybluehost/cli/app/mitm/cli.py`（`--key-log` 参数，默认 `mitm-<ts>-keys.jsonl`）
- Test: `tests/unit/mitm/pairing/test_ssp_key_log.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/mitm/pairing/test_ssp_key_log.py`：

```python
"""T4: SSP link key JSONL 落盘的单元测试。"""
import json

from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate
from pybluehost.cli.app.mitm.pairing.ssp import SspTermination
from pybluehost.core.address import BDAddress


class _NullController:
    def on_io_capability_request(self, cb): pass
    def on_user_confirmation_request(self, cb): pass
    def on_link_key_notification(self, cb): pass
    def on_link_key_request(self, cb): pass


def _addr():
    return BDAddress.from_string("98:1D:F9:90:11:1E")


def test_link_key_written_as_jsonl(tmp_path):
    log = tmp_path / "keys.jsonl"
    ssp = SspTermination(_NullController(), delegate=AutoConfirmDelegate(),
                         side_name="target", key_log_path=log)
    key = bytes(range(16))
    ssp._on_lkn(_addr(), key, 0x04)
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["side"] == "target"
    assert rec["addr"] == "98:1D:F9:90:11:1E"
    assert rec["link_key"] == key.hex()
    assert rec["key_type"] == 0x04
    assert "ts" in rec


def test_no_log_path_no_file_io(tmp_path):
    ssp = SspTermination(_NullController(), delegate=AutoConfirmDelegate(), side_name="phone")
    ssp._on_lkn(_addr(), bytes(16), 0x04)  # 不抛异常即可
    assert list(tmp_path.iterdir()) == []


def test_both_sides_append_same_file(tmp_path):
    log = tmp_path / "keys.jsonl"
    a = SspTermination(_NullController(), delegate=AutoConfirmDelegate(),
                       side_name="phone", key_log_path=log)
    b = SspTermination(_NullController(), delegate=AutoConfirmDelegate(),
                       side_name="target", key_log_path=log)
    a._on_lkn(_addr(), b"\x01" * 16, 0x04)
    b._on_lkn(_addr(), b"\x02" * 16, 0x04)
    sides = [json.loads(l)["side"] for l in log.read_text().strip().splitlines()]
    assert sides == ["phone", "target"]
```

- [ ] **Step 2: 跑测试确认失败**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/mitm/pairing/test_ssp_key_log.py -v
```

预期：3 FAIL（`TypeError: ... unexpected keyword argument 'key_log_path'`）。

- [ ] **Step 3: 实现**

`ssp.py` 顶部加 `import json`、`from datetime import datetime, timezone`、`from pathlib import Path`；`__init__` 加参数 `key_log_path: str | Path | None = None` 存 `self._key_log_path`；`_on_lkn` 改为：

```python
    def _on_lkn(self, addr: BDAddress, key: bytes, key_type: int) -> None:
        """Store a newly-negotiated link key (sync — no HCI reply needed)."""
        self._link_keys[str(addr)] = key
        if self._key_log_path is not None:
            # key 按 HCI wire 序原样落盘;与对端 trace 比对时若顺序存疑再翻。
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "side": self._side_name,
                "addr": str(addr),
                "link_key": key.hex(),
                "key_type": key_type,
            }
            with open(self._key_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
```

`orchestrator.py`：`MitmRelay.__init__` 加参数 `key_log: Optional[str] = None` 存 `self._key_log`；`_build_relay_bredr` 里两个 `SspTermination(...)` 各加 `key_log_path=self._key_log`。

`cli.py`：`register_mitm_command` 加：

```python
    p.add_argument("--key-log", help="link key JSONL 输出路径(默认 mitm-<ts>-keys.jsonl)")
```

`_mitm_main` 里：

```python
    key_log = args.key_log or f"mitm-{datetime.now().strftime('%Y%m%d-%H%M%S')}-keys.jsonl"
```

并给每个 `MitmRelay(...)` 传 `key_log=key_log`（both 模式两个 relay 共享同一文件，side 字段区分——Step 1 第三测已锁此行为）。

- [ ] **Step 4: 跑测试确认通过**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/mitm/ -q
```

- [ ] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/pairing/ssp.py pybluehost/cli/app/mitm/orchestrator.py pybluehost/cli/app/mitm/cli.py tests/unit/mitm/pairing/test_ssp_key_log.py
git commit -m "feat(mitm): persist SSP link keys to JSONL for cross-verification"
```

---

### Task 5: adb 手机助手脚本

**Files:**
- Create: `scripts/mitm_phone.py`
- Test: `tests/unit/scripts/test_mitm_phone.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/scripts/test_mitm_phone.py`：

```python
"""T5: adb 手机助手的单元测试(subprocess 全 mock)。"""
from unittest.mock import patch, MagicMock

from scripts import mitm_phone


def _run_ok(stdout=""):
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    return m


def test_media_keyevent_mapping():
    with patch("subprocess.run", return_value=_run_ok()) as run:
        mitm_phone.media("next")
    args = run.call_args[0][0]
    assert args[:2] == ["adb", "shell"]
    assert "87" in args  # KEYCODE_MEDIA_NEXT


def test_bt_enable_disable():
    with patch("subprocess.run", return_value=_run_ok()) as run:
        mitm_phone.bt_set(True)
        mitm_phone.bt_set(False)
    cmds = [c[0][0] for c in run.call_args_list]
    assert "enable" in cmds[0] and "disable" in cmds[1]


def test_parse_uiautomator_pair_button():
    xml = ('<?xml version="1.0"?>'
           '<hierarchy><node text="配对" bounds="[100,200][300,260]"/></hierarchy>')
    assert mitm_phone.find_button_center(xml, ("配对", "Pair", "确定", "OK")) == (200, 230)


def test_parse_uiautomator_no_match_returns_none():
    xml = '<hierarchy><node text="取消" bounds="[0,0][10,10]"/></hierarchy>'
    assert mitm_phone.find_button_center(xml, ("配对", "Pair")) is None
```

- [ ] **Step 2: 跑测试确认失败**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/scripts/test_mitm_phone.py -v
```

预期：FAIL（`ModuleNotFoundError: No module named 'scripts.mitm_phone'`）。

- [ ] **Step 3: 实现**

新建 `scripts/mitm_phone.py`：

```python
"""adb 手机助手:BT 开关 / media 控制 / 配对对话框确认 / btsnoop 拉取。

无 root 前提:配对确认靠 uiautomator dump 找按钮坐标 + input tap;
btsnoop 路径随厂商变,拉不到就提示用 bugreport。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

KEYCODES = {"play": 126, "pause": 127, "next": 87, "prev": 88}
BTSNOOP_CANDIDATES = [
    "/sdcard/Android/data/btsnoop_hci.log",
    "/sdcard/btsnoop_hci.log",
]


def run_adb(*args: str, timeout: float = 15.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["adb", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def bt_set(enable: bool) -> None:
    run_adb("shell", "cmd", "bluetooth_manager", "enable" if enable else "disable")


def media(action: str) -> None:
    run_adb("shell", "input", "keyevent", str(KEYCODES[action]))


def find_button_center(xml: str, texts: tuple[str, ...]) -> tuple[int, int] | None:
    """在 uiautomator dump XML 里找第一个 text 匹配的节点,返回 bounds 中心。"""
    for node in re.finditer(
        r'<node[^>]*text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml
    ):
        text = node.group(1)
        x1, y1, x2, y2 = (int(node.group(i)) for i in range(2, 6))
        if text in texts:
            return ((x1 + x2) // 2, (y1 + y2) // 2)
    return None


def accept_pairing_dialog() -> bool:
    """dump 当前界面找配对/Pair/确定/OK 按钮并点击;找不到返回 False。"""
    dump = run_adb("shell", "uiautomator", "dump", "/dev/tty")
    # uiautomator dump /dev/tty 的 XML 直接打在 stdout
    center = find_button_center(dump.stdout, ("配对", "Pair", "确定", "OK"))
    if center is None:
        return False
    run_adb("shell", "input", "tap", str(center[0]), str(center[1]))
    return True


def pull_btsnoop(dest: str) -> bool:
    for path in BTSNOOP_CANDIDATES:
        r = run_adb("pull", path, dest)
        if r.returncode == 0:
            return True
    print("btsnoop 拉取失败:开发者选项确认已开 HCI snoop log;", file=sys.stderr)
    print("仍失败则用 adb bugreport 后从 zip 里取。", file=sys.stderr)
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bt-on")
    sub.add_parser("bt-off")
    m = sub.add_parser("media")
    m.add_argument("action", choices=KEYCODES)
    sub.add_parser("accept-pairing")
    p = sub.add_parser("pull-btsnoop")
    p.add_argument("dest")
    args = ap.parse_args()
    if args.cmd == "bt-on":
        bt_set(True)
    elif args.cmd == "bt-off":
        bt_set(False)
    elif args.cmd == "media":
        media(args.action)
    elif args.cmd == "accept-pairing":
        ok = accept_pairing_dialog()
        print("tapped" if ok else "no pairing dialog found")
        sys.exit(0 if ok else 1)
    elif args.cmd == "pull-btsnoop":
        sys.exit(0 if pull_btsnoop(args.dest) else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/scripts/test_mitm_phone.py -v
```

预期：4 PASS。

- [ ] **Step 5: Commit**

```bash
git add scripts/mitm_phone.py tests/unit/scripts/test_mitm_phone.py
git commit -m "feat(scripts): adb phone helper for MITM runs (bt/media/pair-dialog/btsnoop)"
```

---

### Task 6: btsnoop 媒体流质量分析脚本

G5 量化判据工具：解析 btsnoop（含手机侧 pull 的，同为 datalink 1002），定位 AVDTP media channel，做 RTP 序列号分析。

**文件格式**（与 `core/trace.py::BtsnoopSink` 对齐）：头 = `btsnoop\x00` + u32BE version=1 + u32BE datalink=1002；记录 = `>IIIIq`（orig_len, incl_len, flags[bit0: 0=sent/1=recv], drops, ts_us_since_2000-01-01）+ payload。payload 是 H4 ACL 帧：`0x02 + handle_flags(2 LE) + data_len(2 LE) + data`（见 `hci/packets.py::HCIACLData`）。

**AVDTP media channel 识别**：对每条 CID 统计"能解析为合法 RTP（version=2）的包数"，取最多的那条——AVDTP signaling channel 上没有 RTP 流量，天然被排除；不测 SDP/RFCOMM 因为它们同样无 RTP 指纹。若真机上启发式误识别，再升级为跟踪 CID 0x0001 signaling 的 PSM→CID 映射（AVDTP PSM=0x0019）。

**Files:**
- Create: `scripts/mitm_media_analyze.py`
- Test: `tests/unit/scripts/test_mitm_media_analyze.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/scripts/test_mitm_media_analyze.py`：

```python
"""T6: btsnoop 媒体流质量分析的单元测试(合成 trace)。"""
import struct

from scripts import mitm_media_analyze as ma

EPOCH_DELTA_US = 946684800_000_000


def _btsnoop(records: list[bytes], flags: list[int] | None = None) -> bytes:
    out = b"btsnoop\x00" + struct.pack(">II", 1, 1002)
    for i, payload in enumerate(records):
        fl = flags[i] if flags else 0
        out += struct.pack(">IIIIq", len(payload), len(payload), fl, 0, EPOCH_DELTA_US + i * 20_000)
        out += payload
    return out


def _acl_frame(handle: int, l2cap_pdu: bytes) -> bytes:
    return struct.pack("<BHH", 0x02, handle | (0x02 << 12), len(l2cap_pdu)) + l2cap_pdu


def _l2cap(cid: int, payload: bytes) -> bytes:
    return struct.pack("<HH", len(payload), cid) + payload


def _rtp(seq: int, ts: int = 0) -> bytes:
    return struct.pack(">BBHII", 0x80, 0x60, seq, ts, 0xAABBCCDD) + b"\x00" * 100


def test_parse_records_roundtrip():
    blob = _btsnoop([_acl_frame(0x11, _l2cap(0x0040, b"abc"))])
    recs = list(ma.iter_btsnoop(blob))
    assert len(recs) == 1
    assert recs[0].direction == "sent"
    assert recs[0].handle == 0x11


def test_rtp_seq_analysis_detects_gap():
    # media channel CID 0x0040:seq 1,2,4(丢 3),5
    records = [_acl_frame(0x11, _l2cap(0x0040, _rtp(s))) for s in (1, 2, 4, 5)]
    blob = _btsnoop(records)
    report = ma.analyze(blob)
    assert report.total_media_packets == 4
    assert report.lost_packets == 1
    assert report.out_of_order == 0


def test_rtp_seq_analysis_clean_stream():
    records = [_acl_frame(0x11, _l2cap(0x0040, _rtp(s, ts=s * 200))) for s in range(1, 101)]
    blob = _btsnoop(records)
    report = ma.analyze(blob)
    assert report.total_media_packets == 100
    assert report.lost_packets == 0
    assert 0 < report.packets_per_second < 200  # 间隔 20ms → ~50pps


def test_compare_reports_pass_fail():
    good = ma.MediaReport(total_media_packets=100, lost_packets=0, out_of_order=0,
                          packets_per_second=50.0, max_gap_ms=20.0, p99_gap_ms=25.0)
    bad = ma.MediaReport(total_media_packets=90, lost_packets=10, out_of_order=0,
                         packets_per_second=30.0, max_gap_ms=200.0, p99_gap_ms=180.0)
    verdicts = ma.compare(good, bad)
    assert verdicts["loss"] is True   # lost_packets==0 通过
    assert verdicts["rate"] is False  # 30 vs 50 超 ±5% 不通过
```

- [ ] **Step 2: 跑测试确认失败**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/scripts/test_mitm_media_analyze.py -v
```

预期：FAIL（模块不存在）。

- [ ] **Step 3: 实现**

新建 `scripts/mitm_media_analyze.py`：

```python
"""btsnoop 媒体流质量分析:AVDTP media channel 的 RTP 序列号/速率/抖动。

用法:
  python scripts/mitm_media_analyze.py trace.btsnoop
  python scripts/mitm_media_analyze.py mitm.btsnoop --compare baseline.btsnoop

G5 判据:丢包==0 且乱序==0 且速率与基线差 ≤5%。
"""
from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

_EPOCH_DELTA_US = 946684800_000_000


@dataclass
class AclRecord:
    direction: str  # "sent" | "recv"(记录源控制器视角)
    handle: int
    ts_us: int
    cid: int
    payload: bytes


@dataclass
class MediaReport:
    total_media_packets: int
    lost_packets: int
    out_of_order: int
    packets_per_second: float
    max_gap_ms: float
    p99_gap_ms: float


def iter_btsnoop(blob: bytes):
    """产出 AclRecord;只收完整 L2CAP 帧(每记录恰一个 ACL 首片即完整 PDU)。"""
    assert blob[:8] == b"btsnoop\x00", "not a btsnoop file"
    off = 16
    while off + 24 <= len(blob):
        orig, incl, flags, _drops, ts = struct.unpack_from(">IIIIq", blob, off)
        off += 24
        payload = blob[off:off + incl]
        off += incl
        if len(payload) < 5 or payload[0] != 0x02:
            continue  # 非 ACL H4 帧
        handle_flags, dlen = struct.unpack_from("<HH", payload, 1)
        data = payload[5:5 + dlen]
        if len(data) < 4:
            continue
        length, cid = struct.unpack_from("<HH", data, 0)
        yield AclRecord(
            direction="recv" if (flags & 1) else "sent",
            handle=handle_flags & 0x0FFF,
            ts_us=ts - _EPOCH_DELTA_US,
            cid=cid,
            payload=data[4:4 + length],
        )


def _looks_like_rtp(payload: bytes) -> bool:
    return len(payload) >= 12 and (payload[0] >> 6) == 2


def analyze(blob: bytes) -> MediaReport:
    # 1. media channel = 合法 RTP 包最多的那条 CID
    seqs: dict[int, list[tuple[int, int]]] = {}  # cid → [(ts_us, seq)]
    for rec in iter_btsnoop(blob):
        if _looks_like_rtp(rec.payload):
            seq = struct.unpack_from(">H", rec.payload, 2)[0]
            seqs.setdefault(rec.cid, []).append((rec.ts_us, seq))
    media_cid = max(seqs, key=lambda c: len(seqs[c]), default=None)
    samples = seqs.get(media_cid, []) if media_cid is not None else []
    # 2. RTP 分析(按时间序;seq 回绕用模 65536 差值)
    samples.sort()
    lost = ooo = 0
    prev = None
    gaps_ms: list[float] = []
    for ts, seq in samples:
        if prev is not None:
            pts, pseq = prev
            diff = (seq - pseq) & 0xFFFF
            if diff == 0 or diff > 0x8000:
                ooo += 1
            elif diff > 1:
                lost += diff - 1
            gaps_ms.append((ts - pts) / 1000.0)
        prev = (ts, seq)
    dur_s = (samples[-1][0] - samples[0][0]) / 1e6 if len(samples) > 1 else 0
    gaps_sorted = sorted(gaps_ms)
    p99 = gaps_sorted[min(int(len(gaps_sorted) * 0.99), len(gaps_sorted) - 1)] if gaps_sorted else 0.0
    return MediaReport(
        total_media_packets=len(samples),
        lost_packets=lost,
        out_of_order=ooo,
        packets_per_second=(len(samples) / dur_s) if dur_s > 0 else 0.0,
        max_gap_ms=max(gaps_ms) if gaps_ms else 0.0,
        p99_gap_ms=p99,
    )


def compare(baseline: MediaReport, mitm: MediaReport) -> dict[str, bool]:
    rate_ok = (
        baseline.packets_per_second > 0
        and abs(mitm.packets_per_second - baseline.packets_per_second)
        / baseline.packets_per_second <= 0.05
    )
    return {
        "loss": mitm.lost_packets == 0,
        "reorder": mitm.out_of_order == 0,
        "rate": rate_ok,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("trace")
    ap.add_argument("--compare", help="基线 trace;主参数为 MITM trace")
    args = ap.parse_args()
    mitm = analyze(Path(args.trace).read_bytes())
    print(f"MITM trace: pkts={mitm.total_media_packets} lost={mitm.lost_packets} "
          f"ooo={mitm.out_of_order} rate={mitm.packets_per_second:.1f}pps "
          f"max_gap={mitm.max_gap_ms:.1f}ms p99_gap={mitm.p99_gap_ms:.1f}ms")
    if args.compare:
        base = analyze(Path(args.compare).read_bytes())
        print(f"baseline:   pkts={base.total_media_packets} rate={base.packets_per_second:.1f}pps")
        verdicts = compare(base, mitm)
        for k, ok in verdicts.items():
            print(f"  {k}: {'PASS' if ok else 'FAIL'}")
        sys.exit(0 if all(verdicts.values()) else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/scripts/test_mitm_media_analyze.py -v
```

预期：4 PASS。

- [ ] **Step 5: Commit**

```bash
git add scripts/mitm_media_analyze.py tests/unit/scripts/test_mitm_media_analyze.py
git commit -m "feat(scripts): btsnoop AVDTP media quality analyzer (RTP seq/rate/jitter)"
```

---

### Task 7: runbook + STATUS 登记 + 全套回归

**Files:**
- Create: `docs/MITM_BREDR_RUNBOOK.md`
- Modify: `docs/superpowers/STATUS.md`（登记本计划进行中）

- [ ] **Step 1: 写 runbook**

`docs/MITM_BREDR_RUNBOOK.md`（操作步骤全部可复制执行）：

```markdown
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
G6: AVRCP 三键生效;capture 见 HFP SLC 的 BRSF→BAC→CIND→CMER。

## 故障定位(先看关卡边界)
- 手机扫不到 MITM → G2:查 impersonate 的 Write_Scan_Enable 与 CoD/name 写入
- 耳机连不上 → G3 upstream:看 Create_Connection status 重试日志;耳机是否在配对(MCP log)
- 手机连不上 → G3 downstream:看 Connection_Request/Accept 日志
- 音乐卡顿 → mitm_media_analyze 看 lost/rate;查 ACL 流控(Number_of_Completed_Packets)
```

- [ ] **Step 2: STATUS.md 登记**

在 `docs/superpowers/STATUS.md` 加一条：`### 🔄 Plan: BR/EDR MITM relay 硬件就绪化`，认领人记当前 session，链接本 plan + spec `docs/superpowers/specs/2026-08-31-bredr-mitm-test-plan.md`。

- [ ] **Step 3: 全套回归**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q --transport=virtual 2>&1 | tail -5
```

预期：除 8 个预存在 baseline 失败外全 PASS（mitm + scripts 新增 ~13 个全绿）。

- [ ] **Step 4: Commit**

```bash
git add docs/MITM_BREDR_RUNBOOK.md docs/superpowers/STATUS.md
git commit -m "docs(mitm): BR/EDR real-hardware runbook + STATUS registration"
```

---

## Self-Review 记录

- **Spec 覆盖**：spec 的 T1↔Task1、T2↔Task2、T3↔Task3、T4↔Task4、T5↔Task5、T7(分析)↔Task6、T6(runbook)↔Task7。spec §5 的 G 关卡执行属真机操作，由 runbook（Task 7）承载，不在代码任务内。
- **占位符**：无 TBD/TODO；所有代码步骤含完整可粘贴代码。
- **类型一致**：`_make_link_watch(side_name, my_handle, peer_controller, peer_handle)`、`_on_link_lost(peer_controller, peer_handle)`、`build_create_connection_params(addr_le, *, allow_role_switch=True)`、`MediaReport(total_media_packets/lost_packets/out_of_order/packets_per_second/max_gap_ms/p99_gap_ms)` 在测试与实现间逐字一致。
- **已知风险**：Task 6 的 media channel 启发式（RTP 指纹最多的 CID）若遇真机误识别，升级为 signaling PSM→CID 跟踪——已在 Task 6 注明。
