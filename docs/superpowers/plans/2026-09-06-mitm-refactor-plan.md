# MITM 模块重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `orchestrator.py`(1114 行 god-class)替换为 `session.py`(每 controller 唯一 `set_upstream` 属主 + LE/BR 双链路独立重连),补真 LE 路径,新增 transform 正则替换与 scan/relay 两步式 CLI。

**Architecture:** 依据 `docs/superpowers/specs/2026-09-03-mitm-redesign-design.md`。session 是每 controller 的 `set_upstream` 唯一属主,HCI 事件多点订阅(订阅/退订),ACL 用每链路状态对象的 if/else 分发到 2 个 AclRelay;BR 的 `SspTermination` 在 run() 启动段 attach(等手机之前);AclRelay 出站解耦引擎原样保留,唯一新增可选 transform 钩子。工作已在 worktree `bredr-mitm-test` 中,直接在此执行。

**Tech Stack:** Python 3.11+ / asyncio(pytest `asyncio_mode = "auto"`,测试直接写裸 `async def test_`);测试命令一律 `python -m pytest`(venv 内),**不用 `uv run`**。git 提交信息中文,结尾带 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

**全局约束(每个任务都适用):**
- mitm 层禁止 import `pybluehost.l2cap/.ble/.classic/.gap/.profiles/.stack`。
- 不改 `pybluehost/hci/controller.py`(池分离是 golden)。
- 不 stash(共享 stash 栈);测试后若进程持有 dongle 不能强杀。
- 每个任务结束跑 `python -m pytest tests/unit/mitm -q` 必须全绿才提交。

**文件总览(哪些文件动、各管什么):**

| 文件 | 动作 | 职责 |
|------|------|------|
| `pybluehost/cli/app/mitm/transform.py` | 新建 | ReplaceRule/RegexReplacer + DEMO_RULES(用户改这里) |
| `pybluehost/cli/app/mitm/relay.py` | 改(唯一新增) | AclRelay 加可选 transform 钩子(默认 None 行为不变) |
| `pybluehost/cli/app/mitm/recon.py` | 增量 | `ScanEntry` + `ble_scan_all`(全部广播者) |
| `pybluehost/cli/app/mitm/bredr_recon.py` | 增量+小重构 | 提取纯解析器;`inquiry_scan_all`;`fetch_remote_name` |
| `pybluehost/cli/app/mitm/cli.py` | 重写 | scan/relay 子命令、身份 JSON 读写/按段合并、默认值 |
| `pybluehost/cli/app/mitm/session.py` | 新建 | MitmSession:编排 + 唯一属主分发 + 双链路(替代 orchestrator) |
| `pybluehost/cli/app/mitm/pairing/ltk_store.py` | 新建 | LE LTK JSONL 持久化(load/append) |
| `pybluehost/cli/app/mitm/controllers.py` | 增量 | `open_controller`(scan 单 dongle 打开) |
| `pybluehost/cli/app/mitm/orchestrator.py` | **删除**(Task 10) | 被 session.py 取代 |
| `scripts/mitm_traced.py` | 改 | MitmRelay→MitmSession 适配 |
| `tests/unit/mitm/test_transform.py` 等 | 新建 | 每个任务对应的新测试 |
| `tests/unit/mitm/test_orchestrator*.py`、`test_secure_target_link.py` | **删除**(Task 10) | 行为移植进 test_session_*.py |

---

### Task 1: transform.py — 正则替换引擎 + demo 规则

**Files:**
- Create: `pybluehost/cli/app/mitm/transform.py`
- Test: `tests/unit/mitm/test_transform.py`

- [ ] **Step 1: 写失败测试**

```python
"""transform:ACL PDU 正则替换引擎。"""
from pybluehost.cli.app.mitm.acl import RelayDirection
from pybluehost.cli.app.mitm.transform import DEMO_RULES, RegexReplacer, ReplaceRule


def test_matches_and_replaces():
    r = RegexReplacer([ReplaceRule(pattern=b"WQ7035", repl=b"MITM7035")])
    out = r(RelayDirection.PHONE_TO_TARGET, 0x0040, b"hello WQ7035!")
    assert out == b"hello MITM7035!"


def test_no_match_returns_original_bytes():
    r = RegexReplacer([ReplaceRule(pattern=b"XYZZY", repl=b"A")])
    payload = bytes(range(32))
    assert r(RelayDirection.TARGET_TO_PHONE, 0x0040, payload) == payload


def test_direction_filter():
    r = RegexReplacer([ReplaceRule(pattern=b"ab", repl=b"X",
                                   direction=RelayDirection.PHONE_TO_TARGET)])
    assert r(RelayDirection.PHONE_TO_TARGET, 0x0040, b"ab") == b"X"
    assert r(RelayDirection.TARGET_TO_PHONE, 0x0040, b"ab") == b"ab"


def test_cid_filter():
    r = RegexReplacer([ReplaceRule(pattern=b"ab", repl=b"X", cid=0x0004)])
    assert r(RelayDirection.PHONE_TO_TARGET, 0x0004, b"ab") == b"X"
    assert r(RelayDirection.PHONE_TO_TARGET, 0x0001, b"ab") == b"ab"


def test_backreference_supported():
    r = RegexReplacer([ReplaceRule(pattern=b"(ab)+", repl=b"\\g<1>!")])
    assert r(RelayDirection.PHONE_TO_TARGET, 0x0040, b"abab") == b"abab!"


def test_demo_rules_default_empty():
    """默认规则为空:session 挂上 transform 后开销≈0、行为恒等。"""
    assert DEMO_RULES == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/mitm/test_transform.py -q`
Expected: FAIL(`ModuleNotFoundError: transform`)

- [ ] **Step 3: 实现 transform.py**

```python
"""ACL PDU 正则替换 demo。改规则 → 编辑本文件底部 DEMO_RULES 即可。

替换发生在 AclRelay 内、重组后的完整 L2CAP PDU 层(不是 HCI 分片层),
替换后由 encode_l2cap_basic 按新 payload 重写 length 头,长度变化天然正确。
抓包在入队之后,capture 抓到的就是替换后实际上线的内容。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from pybluehost.cli.app.mitm.acl import RelayDirection

# AclRelay 的 transform 钩子签名:(direction, cid, payload) -> payload
PduTransform = Callable[[RelayDirection, int, bytes], bytes]


@dataclass(frozen=True)
class ReplaceRule:
    pattern: bytes                              # bytes 正则(在 L2CAP payload 上找)
    repl: bytes                                 # 替换内容(支持 \g<1> 反向引用)
    direction: Optional[RelayDirection] = None  # None = 双向都替换
    cid: Optional[int] = None                   # None = 所有 CID;指定则只替换该信道


class RegexReplacer:
    """把一组 ReplaceRule 编译成 AclRelay 的 transform 钩子。"""

    def __init__(self, rules: Sequence[ReplaceRule]) -> None:
        self._compiled = [(re.compile(r.pattern), r) for r in rules]

    def __call__(self, direction: RelayDirection, cid: int, payload: bytes) -> bytes:
        for rx, rule in self._compiled:
            if rule.direction is not None and rule.direction is not direction:
                continue
            if rule.cid is not None and rule.cid != cid:
                continue
            payload = rx.sub(rule.repl, payload)
        return payload


# ====== DEMO:后面你自己在这里加规则 ======
DEMO_RULES: list[ReplaceRule] = [
    # 例:把控制信道里出现的设备名字符串换掉。取消注释即生效:
    # ReplaceRule(pattern=b"WQ7035", repl=b"MITM7035"),
    # 例:只替换 phone→target 方向、且仅某 CID 上命中的 4 字节序列:
    # ReplaceRule(pattern=bytes.fromhex("deadbeef"), repl=bytes.fromhex("cafebabe"),
    #             direction=RelayDirection.PHONE_TO_TARGET),
]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/mitm/test_transform.py -q`
Expected: PASS(6 passed)

- [ ] **Step 5: 提交**

```bash
git add pybluehost/cli/app/mitm/transform.py tests/unit/mitm/test_transform.py
git commit -m "feat(mitm): transform.py 正则替换引擎 + DEMO_RULES"
```

---

### Task 2: AclRelay 加 transform 钩子(golden 唯一改动)

**Files:**
- Modify: `pybluehost/cli/app/mitm/relay.py`
- Test: `tests/unit/mitm/test_relay.py`(追加)

- [ ] **Step 1: 追加失败测试到 `tests/unit/mitm/test_relay.py`**

在文件 import 区加入 `from pybluehost.cli.app.mitm.transform import ReplaceRule, RegexReplacer`,文件末尾追加:

```python
# ---------------------------------------------------------------------------
# transform 钩子:PDU 级替换(fail-open),默认 None 行为与现在逐字节一致
# ---------------------------------------------------------------------------

async def test_transform_rewrites_payload_and_l2cap_length():
    """替换变长后,L2CAP length 头必须按新 payload 重写。"""
    phone, _ = _make_side("phone", 0x40, 27)
    target, target_sent = _make_side("target", 0x11, 27)
    relay = AclRelay(phone_side=phone, target_side=target,
                     transform=RegexReplacer([ReplaceRule(b"WQ7035", b"MITM!")]))
    pdu = bytes([0x06, 0x00, 0x04, 0x00]) + b"WQ7035"      # len=6, cid=0x0004
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=pdu))
    await relay.flush()
    assert len(target_sent) == 1
    out = target_sent[0][2]
    assert out == bytes([0x05, 0x00, 0x04, 0x00]) + b"MITM!"  # len 头变 5
    await relay.stop()


async def test_no_transform_is_identity():
    phone, _ = _make_side("phone", 0x40, 27)
    target, target_sent = _make_side("target", 0x11, 27)
    relay = AclRelay(phone_side=phone, target_side=target)   # 不配 transform
    pdu = bytes([0x06, 0x00, 0x04, 0x00]) + b"WQ7035"
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=pdu))
    await relay.flush()
    assert target_sent[0][2] == pdu
    await relay.stop()


async def test_transform_exception_fails_open():
    """transform 抛异常 → 记日志并转发原帧,不杀媒体流。"""
    phone, _ = _make_side("phone", 0x40, 27)
    target, target_sent = _make_side("target", 0x11, 27)

    def boom(direction, cid, payload):
        raise RuntimeError("boom")

    relay = AclRelay(phone_side=phone, target_side=target, transform=boom)
    pdu = bytes([0x01, 0x00, 0x04, 0x00, 0x2A])
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=pdu))
    await relay.flush()
    assert target_sent[0][2] == pdu
    await relay.stop()


async def test_transform_receives_direction_and_cid():
    seen = []

    def spy(direction, cid, payload):
        seen.append((direction, cid))
        return payload

    phone, _ = _make_side("phone", 0x40, 27)
    target, _ = _make_side("target", 0x11, 27)
    relay = AclRelay(phone_side=phone, target_side=target, transform=spy)
    pdu = bytes([0x01, 0x00, 0x04, 0x00, 0x2A])
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=pdu))
    await relay.flush()
    assert seen == [(RelayDirection.PHONE_TO_TARGET, 0x0004)]
    await relay.stop()
```

注意:test 文件顶部需已有 `from pybluehost.cli.app.mitm.acl import RelayDirection`(没有就加上)。

- [ ] **Step 2: 跑测试确认新测试失败**

Run: `python -m pytest tests/unit/mitm/test_relay.py -q`
Expected: 新增 4 个 FAIL(`TypeError: unexpected keyword argument 'transform'`);**既有测试全部 PASS**

- [ ] **Step 3: 改 relay.py — 加钩子**

`relay.py` 三处改动:

① import 区加:

```python
from pybluehost.cli.app.mitm.transform import PduTransform
```

② `AclRelay.__init__` 签名加参数,并保存:

```python
    def __init__(
        self,
        *,
        phone_side: RelaySide,
        target_side: RelaySide,
        capture: CaptureTap | None = None,
        smp_handler: SmpHandler | None = None,
        on_teardown: TeardownHook | None = None,
        egress_max: int = 24,
        egress_low: int = 4,
        transform: PduTransform | None = None,
    ) -> None:
```

在 `self._last_drop_log = 0.0` 之后加:

```python
        # PDU 级正则替换钩子(可选)。默认 None = 行为与没有此参数时逐字节一致。
        # 抛异常 fail-open:记日志、转发原帧,不杀媒体流。
        self._transform = transform
```

③ `_handle` 里,把 `pdu = encode_l2cap_basic(cid, payload)` 一行改为:

```python
            pdu = encode_l2cap_basic(cid, self._apply_transform(direction, cid, payload))
```

并在 `_handle` 方法后新增:

```python
    def _apply_transform(
        self, direction: RelayDirection, cid: int, payload: bytes
    ) -> bytes:
        if self._transform is None:
            return payload
        try:
            return self._transform(direction, cid, payload)
        except Exception:
            logger.exception("transform 处理失败,fail-open 转发原帧")
            return payload
```

除以上三处外 relay.py **一行都不许动**(出站解耦/丢水位/抓包顺序是 golden)。

- [ ] **Step 4: 跑全部 relay 测试确认通过**

Run: `python -m pytest tests/unit/mitm/test_relay.py tests/unit/mitm/test_transform.py -q`
Expected: PASS(全部,含既有测试零改动)

- [ ] **Step 5: 提交**

```bash
git add pybluehost/cli/app/mitm/relay.py tests/unit/mitm/test_relay.py
git commit -m "feat(mitm): AclRelay 加可选 transform 钩子(默认 None 行为不变,fail-open)"
```

---

### Task 3: recon.py 加 ble_scan_all(全量广播扫描)

**Files:**
- Modify: `pybluehost/callback`-no — `pybluehost/cli/app/mitm/recon.py`(只追加,不动 `scan_for_target`)
- Test: `tests/unit/mitm/test_recon_scan_all.py`(新建)

- [ ] **Step 1: 写失败测试**

```python
"""ble_scan_all:收集窗口内全部广播者。"""
import asyncio
import struct

from pybluehost.cli.app.mitm.recon import ScanEntry, ble_scan_all
from pybluehost.hci.constants import EventCode
from pybluehost.hci.packets import HCI_LE_Meta_Event, HCIEvent


def _adv_report(addr6: bytes, addr_type: int, data: bytes, rssi: int = -50,
                event_type: int = 0x00) -> HCIEvent:
    """构造一个只含单条 report 的 LE_Advertising_Report 事件。"""
    body = bytes([0x01, event_type, addr_type]) + addr6 \
        + bytes([len(data)]) + data + struct.pack("<b", rssi)
    evt = HCI_LE_Meta_Event.from_bytes(
        EventCode.LE_META, bytes([0x02]) + body
    )
    return evt


class FakeScanController:
    def __init__(self):
        self._on_hci_event = None
        self._on_acl_data = None
        self._on_sco_data = None
        self.commands: list = []

    def set_upstream(self, on_hci_event=None, on_acl_data=None, on_sco_data=None):
        self._on_hci_event = on_hci_event
        self._on_acl_data = on_acl_data
        self._on_sco_data = on_sco_data

    async def send_command(self, command):
        self.commands.append(command)

    def feed(self, event):
        self._on_hci_event(event)


async def test_collects_all_advertisers_and_merges_scan_rsp():
    ctl = FakeScanController()
    task = asyncio.ensure_future(ble_scan_all(ctl, window=0.2))
    await asyncio.sleep(0.05)  # 让扫描开起来
    # 设备 A:ADV(带名)
    a = bytes.fromhex("AABBCCDDEEFF")
    ctl.feed(_adv_report(a, 0, b"\x09\x05Dev-A"))
    # 设备 B:先 ADV 后 SCAN_RSP(名字在 rsp 里)
    b = bytes.fromhex("112233445566")
    ctl.feed(_adv_report(b, 1, b"\x02\x01\x05"))
    ctl.feed(_adv_report(b, 1, b"\x09\x05Dev-B", event_type=0x04))
    entries = await asyncio.wait_for(task, 2.0)

    addrs = {e.identity.address: e for e in entries}
    assert set(addrs) == {"FF:EE:DD:CC:BB:AA", "66:55:44:33:22:11"}
    assert addrs["FF:EE:DD:CC:BB:AA"].identity.name == "Dev-A"
    assert addrs["66:55:44:33:22:11"].identity.name == "Dev-B"  # ADV+RSP 合并
    assert addrs["66:55:44:33:22:11"].rssi == -50
    # 扫完会关 scan(set scan enable 参数 0,0)
    assert ctl.commands[-1].parameters == bytes([0x00, 0x00])


async def test_window_with_no_devices_returns_empty():
    ctl = FakeScanController()
    entries = await asyncio.wait_for(ble_scan_all(ctl, window=0.1), 2.0)
    assert entries == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/mitm/test_recon_scan_all.py -q`
Expected: FAIL(`ImportError: ScanEntry`)

- [ ] **Step 3: 在 recon.py 追加实现(不动 scan_for_target/ClonedIdentity)**

在 recon.py 顶部 import 区把 `dataclass` 从单导入改为:`from dataclasses import dataclass`,末尾追加:

```python
# ---------------------------------------------------------------------------
# ScanEntry / ble_scan_all — 全量广播扫描(scan 子命令用)
# ---------------------------------------------------------------------------

@dataclass
class ScanEntry:
    """一次全量扫描里的一台设备:身份 + 可选 RSSI(BR 标准 inquiry 无 RSSI)。"""
    identity: ClonedIdentity
    rssi: int | None = None


async def ble_scan_all(
    controller: "HCIController", *, window: float = 10.0
) -> list[ScanEntry]:
    """BLE 广播全量扫描:收集 window 秒内看到的所有广播者。

    与 scan_for_target 的差别:没有匹配条件、不停,收满窗口返回全部。
    按地址合并 adv_data 与 scan_response;名字取两者 parse_adv_name 首个非 None;
    RSSI 取最后一次 ADV report 的值(SCAN_RSP 不更新 RSSI)。
    """
    if window <= 0:
        raise ValueError("window 必须 > 0")

    adv_map: dict[str, bytes] = {}
    rsp_map: dict[str, bytes] = {}
    type_map: dict[str, int] = {}
    rssi_map: dict[str, int] = {}

    prev_on_hci_event = controller._on_hci_event  # type: ignore[attr-defined]
    prev_on_acl_data = controller._on_acl_data    # type: ignore[attr-defined]
    prev_on_sco_data = controller._on_sco_data    # type: ignore[attr-defined]

    def _forward(event: HCIEvent) -> None:
        if prev_on_hci_event is not None:
            result = prev_on_hci_event(event)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)

    def on_hci_event(event: HCIEvent) -> None:
        if event.event_code != EventCode.LE_META:
            _forward(event)
            return
        if isinstance(event, HCI_LE_Meta_Event):
            subevent_code = event.subevent_code
            subevent_params = event.subevent_parameters
        elif getattr(event, "parameters", b""):
            subevent_code = event.parameters[0]
            subevent_params = event.parameters[1:]
        else:
            return
        if subevent_code != LEMetaSubEvent.LE_ADVERTISING_REPORT:
            _forward(event)
            return
        for report in parse_le_advertising_reports(subevent_params):
            addr = ":".join(f"{b:02X}" for b in reversed(report.address))
            type_map[addr] = report.address_type
            if report.event_type == 0x04:
                rsp_map[addr] = report.data
            else:
                adv_map[addr] = report.data
                rssi_map[addr] = report.rssi
        # 不停:全量扫描收满窗口为止

    controller.set_upstream(on_hci_event=on_hci_event)
    try:
        scan_params = struct.pack("<BHHBB", 0x01, 0x0010, 0x0010, 0x00, 0x00)
        await controller.send_command(
            HCICommand(opcode=HCI_LE_SET_SCAN_PARAMS, parameters=scan_params)
        )
        await controller.send_command(
            HCICommand(opcode=HCI_LE_SET_SCAN_ENABLE, parameters=bytes([0x01, 0x00]))
        )
        await asyncio.sleep(window)
    finally:
        try:
            await controller.send_command(
                HCICommand(opcode=HCI_LE_SET_SCAN_ENABLE, parameters=bytes([0x00, 0x00]))
            )
        except Exception:
            pass
        controller.set_upstream(
            on_hci_event=prev_on_hci_event,
            on_acl_data=prev_on_acl_data,
            on_sco_data=prev_on_sco_data,
        )

    entries: list[ScanEntry] = []
    for addr in sorted(set(adv_map) | set(rsp_map)):
        name = parse_adv_name(adv_map.get(addr, b"")) or parse_adv_name(rsp_map.get(addr, b""))
        entries.append(ScanEntry(
            identity=ClonedIdentity(
                address=addr,
                address_type=type_map.get(addr, 0),
                adv_data=adv_map.get(addr, b""),
                scan_response=rsp_map.get(addr, b""),
                name=name,
            ),
            rssi=rssi_map.get(addr),
        ))
    return entries
```

- [ ] **Step 4: 跑测试确认通过(含既有 recon 测试)**

Run: `python -m pytest tests/unit/mitm/test_recon_scan_all.py tests/unit/mitm/test_recon.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add pybluehost/cli/app/mitm/recon.py tests/unit/mitm/test_recon_scan_all.py
git commit -m "feat(mitm): ble_scan_all 全量广播扫描(ScanEntry 含 rssi)"
```

### Task 4: bredr_recon.py — 提取纯解析器 + inquiry_scan_all + fetch_remote_name

**Files:**
- Modify: `pybluehost/cli/app/mitm/bredr_recon.py`(提取 `_parse_inquiry_result`/`_parse_extended_inquiry_result`/RNR 段为模块级函数;`inquiry_for_target` 改为复用,行为不变;新增 `inquiry_scan_all`)
- Test: `tests/unit/mitm/test_bredr_scan_all.py`(新建)

- [ ] **Step 1: 写失败测试**

```python
"""inquiry_scan_all + fetch_remote_name。"""
import asyncio

from pybluehost.cli.app.mitm.bredr_recon import (
    fetch_remote_name,
    inquiry_scan_all,
    parse_inquiry_result_entries,
    parse_extended_inquiry_result_entry,
)
from pybluehost.hci.constants import EventCode
from pybluehost.hci.packets import HCICommand, HCIEvent


def test_parse_inquiry_result_entries_layout():
    # num=1, addr(6 LE), psrm(1), reserved(2), cod(3 LE), clock(2)
    data = bytes([0x01]) + bytes.fromhex("F7F7") + b""  # 占位,下面拼完整
    raw = (
        bytes([0x01])
        + bytes.fromhex("F7 52 CD 18 D5 38".replace(" ", ""))
        + bytes([0x01]) + bytes(2)
        + (0x240404).to_bytes(3, "little")
        + bytes(2)
    )
    entries = parse_inquiry_result_entries(raw)
    assert entries == [("38:D5:18:CD:52:F7", 0x240404)]


def test_parse_extended_inquiry_result_entry_layout():
    raw = (
        bytes([0x01])
        + bytes.fromhex("F752CD18D538")
        + bytes([0x01]) + bytes([0x00])
        + (0x240404).to_bytes(3, "little")
        + bytes(2)          # clock
        + bytes([-60 & 0xFF])  # rssi
        + b"\x09\x05Dev-BR" + bytes(240 - 7)   # EIR 240B
    )
    addr, cod, eir, rssi = parse_extended_inquiry_result_entry(raw)
    assert addr == "38:D5:18:CD:52:F7"
    assert cod == 0x240404
    assert rssi == -60
    assert eir[:7] == b"\x09\x05Dev-BR"


class FakeInqController:
    def __init__(self):
        self._on_hci_event = None
        self._on_acl_data = None
        self._on_sco_data = None
        self.commands: list[HCICommand] = []
        self.reply_name = "JBL Live Beam 4"

    def set_upstream(self, on_hci_event=None, on_acl_data=None, on_sco_data=None):
        self._on_hci_event = on_hci_event

    async def send_command(self, command):
        self.commands.append(command)
        if command.opcode == 0x0402:  # REMOTE_NAME_REQUEST
            params = bytes([0x00]) + command.parameters[0:6]
            name = self.reply_name.encode()[:248]
            name = name + bytes(248 - len(name))
            self._on_hci_event(
                HCIEvent.from_bytes(EventCode.REMOTE_NAME_REQUEST_COMPLETE,
                                    params + name)
            )

    def feed_inquiry_result(self):
        raw = (
            bytes([0x01]) + bytes.fromhex("F752CD18D538")
            + bytes([0x01]) + bytes(2)
            + (0x240404).to_bytes(3, "little") + bytes(2)
        )
        self._on_hci_event(HCIEvent.from_bytes(EventCode.INQUIRY_RESULT, raw))


async def test_inquiry_scan_all_collects_devices():
    ctl = FakeInqController()
    task = asyncio.ensure_future(
        inquiry_scan_all(ctl, rounds=2, round_seconds=0.1)
    )
    await asyncio.sleep(0.03)
    ctl.feed_inquiry_result()
    entries = await asyncio.wait_for(task, 3.0)
    assert len(entries) == 1
    assert entries[0].identity.address == "38:D5:18:CD:52:F7"
    assert entries[0].identity.class_of_device == 0x240404
    assert entries[0].rssi is None  # 标准 inquiry result 无 RSSI


async def test_fetch_remote_name_roundtrip():
    ctl = FakeInqController()
    name = await asyncio.wait_for(
        fetch_remote_name(ctl, "38:D5:18:CD:52:F7", timeout=2.0), 3.0
    )
    assert name == "JBL Live Beam 4"
    # 发过 Inquiry_Cancel(先停 inquiry)和 Remote_Name_Request
    from pybluehost.hci.constants import HCI_INQUIRY_CANCEL, HCI_REMOTE_NAME_REQUEST
    opcodes = [c.opcode for c in ctl.commands]
    assert HCI_INQUIRY_CANCEL in opcodes and HCI_REMOTE_NAME_REQUEST in opcodes
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/mitm/test_bredr_scan_all.py -q`
Expected: FAIL(`ImportError: parse_inquiry_result_entries`)

- [ ] **Step 3: 改 bredr_recon.py**

① 把 `inquiry_for_target` 内的闭包 `_parse_inquiry_result`、`_parse_extended_inquiry_result`、RNR 段提取为模块级函数(放在 `parse_eir_name` 之后),`inquiry_for_target` 改为调用它们,**行为一字不差**(既有 `test_bredr_recon_rnr.py` 守护):

```python
def parse_inquiry_result_entries(data: bytes) -> list[tuple[str, int | None]]:
    """HCI_Inquiry_Result(0x02) → [(addr_str, CoD)]。每条 14 字节。"""
    if not data:
        return []
    count = data[0]
    offset = 1
    out: list[tuple[str, int | None]] = []
    for _ in range(count):
        if offset + 14 > len(data):
            return out
        addr = _bd_addr_str(data[offset: offset + 6])
        offset += 6
        offset += 3          # page_scan_rep_mode(1) + reserved(2)
        cod = int.from_bytes(data[offset: offset + 3], "little")
        offset += 3
        offset += 2          # clock_offset
        out.append((addr, cod))
    return out


def parse_extended_inquiry_result_entry(
    data: bytes,
) -> tuple[str, int | None, bytes, int | None]:
    """HCI_Extended_Inquiry_Result(0x2F) → (addr, CoD, EIR, rssi)。"""
    if len(data) < 15:
        return "", None, b"", None
    offset = 1
    addr = _bd_addr_str(data[offset: offset + 6])
    offset += 6
    offset += 1              # page_scan_rep_mode
    offset += 1              # reserved
    cod = int.from_bytes(data[offset: offset + 3], "little")
    offset += 3
    offset += 2              # clock_offset
    rssi = data[offset] if offset < len(data) else None
    if rssi is not None and rssi >= 128:
        rssi -= 256          # 有符号 byte
    offset += 1
    eir = data[offset: offset + 240] if offset + 240 <= len(data) else data[offset:]
    return addr, cod, eir, rssi


async def fetch_remote_name(
    controller: "HCIController", addr: str, *, timeout: float = 10.0
) -> str | None:
    """对单台设备 Remote_Name_Request(先 Inquiry_Cancel,Intel 真机要求)。失败返回 None。"""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str | None] = loop.create_future()
    prev_on_hci_event = controller._on_hci_event  # type: ignore[attr-defined]
    prev_on_acl_data = controller._on_acl_data    # type: ignore[attr-defined]
    prev_on_sco_data = controller._on_sco_data    # type: ignore[attr-defined]
    addr_le = bytes.fromhex(addr.replace(":", ""))[::-1]

    def on_event(event: HCIEvent) -> None:
        if event.event_code == EventCode.REMOTE_NAME_REQUEST_COMPLETE:
            p = event.parameters
            if len(p) >= 7 and p[1:7] == addr_le:
                if not fut.done():
                    if p[0] != 0x00:
                        fut.set_result(None)
                    else:
                        raw = p[7:255]
                        fut.set_result(
                            raw.rstrip(b"\x00").decode("utf-8", errors="replace") or None
                        )
        if prev_on_hci_event is not None:
            result = prev_on_hci_event(event)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)

    controller.set_upstream(on_hci_event=on_event)
    try:
        try:
            await controller.send_command(
                HCICommand(opcode=HCI_INQUIRY_CANCEL, parameters=b"")
            )
        except Exception:
            pass  # 不在 inquiry 态时 cancel 报错属正常
        try:
            await controller.send_command(
                HCICommand(
                    opcode=HCI_REMOTE_NAME_REQUEST,
                    parameters=addr_le + bytes([0x01, 0x00, 0x00, 0x00]),
                )
            )
        except Exception:
            return None
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return None
    finally:
        controller.set_upstream(
            on_hci_event=prev_on_hci_event,
            on_acl_data=prev_on_acl_data,
            on_sco_data=prev_on_sco_data,
        )


async def inquiry_scan_all(
    controller: "HCIController",
    *,
    rounds: int = 2,
    round_seconds: float = 10.24,
) -> list[ScanEntry]:
    """BR/EDR inquiry 全量扫描:rounds 轮(默认 2 轮 ≈20s),收集全部设备。

    EIR 带名字直接用;没有名字**不在扫描期做 RNR**(逐台太慢),由调用方对
    用户选中的那一台调 fetch_remote_name 补名。
    """
    from pybluehost.cli.app.mitm.recon import ScanEntry  # noqa: PLC0415

    cod_map: dict[str, int | None] = {}
    eir_map: dict[str, bytes] = {}
    rssi_map: dict[str, int | None] = {}

    prev_on_hci_event = controller._on_hci_event  # type: ignore[attr-defined]
    prev_on_acl_data = controller._on_acl_data    # type: ignore[attr-defined]
    prev_on_sco_data = controller._on_sco_data    # type: ignore[attr-defined]

    def on_event(event: HCIEvent) -> None:
        code = event.event_code
        params = getattr(event, "parameters", b"") or b""
        if code == EventCode.INQUIRY_RESULT:
            for addr, cod in parse_inquiry_result_entries(params):
                cod_map.setdefault(addr, cod)
        elif code == _EVENT_EXTENDED_INQUIRY_RESULT:
            addr, cod, eir, rssi = parse_extended_inquiry_result_entry(params)
            if addr:
                cod_map.setdefault(addr, cod)
                eir_map[addr] = eir
                rssi_map[addr] = rssi
        elif prev_on_hci_event is not None:
            result = prev_on_hci_event(event)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)

    controller.set_upstream(on_hci_event=on_event)
    try:
        for _ in range(max(1, rounds)):
            try:
                await controller.send_command(
                    HCICommand(
                        opcode=HCI_INQUIRY,
                        parameters=_GIAC_LAP + bytes([0x08, 0x00]),
                    )
                )
            except Exception:
                pass
            await asyncio.sleep(round_seconds)
            try:
                await controller.send_command(
                    HCICommand(opcode=HCI_INQUIRY_CANCEL, parameters=b"")
                )
            except Exception:
                pass
    finally:
        controller.set_upstream(
            on_hci_event=prev_on_hci_event,
            on_acl_data=prev_on_acl_data,
            on_sco_data=prev_on_sco_data,
        )

    entries: list[ScanEntry] = []
    for addr in sorted(cod_map):
        name = parse_eir_name(eir_map.get(addr, b""))
        entries.append(ScanEntry(
            identity=ClonedIdentity(
                address=addr,
                address_type=0,
                adv_data=eir_map.get(addr, b""),
                scan_response=b"",
                name=name,
                class_of_device=cod_map.get(addr),
            ),
            rssi=rssi_map.get(addr),
        ))
    return entries
```

② `inquiry_for_target` 内:删掉同名闭包 `_parse_inquiry_result`/`_parse_extended_inquiry_result`,改调模块级 `parse_inquiry_result_entries`/`parse_extended_inquiry_result_entry`;RNR 段(`name_from_eir is None` 分支)改为调用 `fetch_remote_name(controller, addr, timeout=min(timeout, 10.0))`,成功则 `matched_name.clear(); matched_name.append(name)` 后 `matched_event.set()`。**匹配/事件语义保持不变**。

③ 顶部 import 加 `from pybluehost.cli.app.mitm.recon import ClonedIdentity, ScanEntry`(替换原单导入)。

- [ ] **Step 4: 跑测试确认通过(含既有 RNR 测试)**

Run: `python -m pytest tests/unit/mitm/test_bredr_scan_all.py tests/unit/mitm/test_bredr_recon_rnr.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add pybluehost/cli/app/mitm/bredr_recon.py tests/unit/mitm/test_bredr_scan_all.py
git commit -m "feat(mitm): inquiry_scan_all 全量扫描 + fetch_remote_name 单台补名 + 纯解析器提取"
```

---

### Task 5: cli.py — 身份 JSON 读写(按段合并)

**Files:**
- Modify: `pybluehost/cli/app/mitm/cli.py`(只追加;旧命令注册逻辑 Task 10 才替换)
- Test: `tests/unit/mitm/test_identity_json.py`(新建)

- [ ] **Step 1: 写失败测试**

```python
"""身份 JSON:落盘/加载/按段合并/与 ClonedIdentity 往返。"""
import json

from pybluehost.cli.app.mitm.cli import identity_load, identity_save
from pybluehost.cli.app.mitm.recon import ClonedIdentity

BR = ClonedIdentity(address="38:D5:18:CD:52:F7", address_type=0, adv_data=b"\x01\x02",
                    scan_response=b"", name="JBL", class_of_device=0x240404)
LE = ClonedIdentity(address="38:D5:18:CD:52:F8", address_type=1, adv_data=b"\x03",
                    scan_response=b"\x04", name="JBL LE", class_of_device=None)


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "t.json"
    identity_save(path, {"bredr": BR, "le": LE})
    loaded = identity_load(path)
    assert set(loaded) == {"bredr", "le"}
    assert loaded["bredr"].address == "38:D5:18:CD:52:F7"
    assert loaded["bredr"].class_of_device == 0x240404
    assert loaded["bredr"].adv_data == b"\x01\x02"
    assert loaded["le"].address_type == 1
    assert loaded["le"].scan_response == b"\x04"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 1 and "saved_at" in raw


def test_save_merges_by_section(tmp_path):
    """bredr-only 的保存不得抹掉文件里已有的 le 段。"""
    path = tmp_path / "t.json"
    identity_save(path, {"bredr": BR})
    identity_save(path, {"le": LE})
    loaded = identity_load(path)
    assert set(loaded) == {"bredr", "le"}
    assert loaded["bredr"].name == "JBL"


def test_load_missing_file_returns_empty(tmp_path):
    assert identity_load(tmp_path / "nope.json") == {}


def test_load_corrupt_file_returns_empty(tmp_path):
    path = tmp_path / "t.json"
    path.write_text("not json{", encoding="utf-8")
    assert identity_load(path) == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/mitm/test_identity_json.py -q`
Expected: FAIL(`ImportError: identity_load`)

- [ ] **Step 3: 在 cli.py 追加实现(放在 `default_btsnoop_name` 之后)**

```python
# ---------------------------------------------------------------------------
# 身份 JSON:scan↔relay 之间的桥(按段合并)
# ---------------------------------------------------------------------------

IDENTITY_DEFAULT = "mitm-targets.json"


def _section_from_identity(ident: "ClonedIdentity", mode: str) -> dict:
    if mode == "bredr":
        return {
            "address": ident.address,
            "name": ident.name,
            "class_of_device": ident.class_of_device,
            "eir_hex": ident.adv_data.hex(),
        }
    return {
        "address": ident.address,
        "address_type": ident.address_type,
        "name": ident.name,
        "adv_hex": ident.adv_data.hex(),
        "scan_rsp_hex": ident.scan_response.hex(),
    }


def _identity_from_section(section: dict, mode: str) -> "ClonedIdentity":
    from pybluehost.cli.app.mitm.recon import ClonedIdentity  # noqa: PLC0415

    if mode == "bredr":
        return ClonedIdentity(
            address=section["address"].upper(),
            address_type=0,
            adv_data=bytes.fromhex(section.get("eir_hex", "")),
            scan_response=b"",
            name=section.get("name"),
            class_of_device=section.get("class_of_device"),
        )
    return ClonedIdentity(
        address=section["address"].upper(),
        address_type=int(section.get("address_type", 0)),
        adv_data=bytes.fromhex(section.get("adv_hex", "")),
        scan_response=bytes.fromhex(section.get("scan_rsp_hex", "")),
        name=section.get("name"),
    )


def identity_save(path: str | Path, sections: dict) -> None:
    """保存身份(按段合并:只更新给定 mode 段,文件里其它段保留)。"""
    path = Path(path)
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = {}
    data["version"] = 1
    data["saved_at"] = datetime.now(timezone.utc).isoformat()
    for mode, ident in sections.items():
        data[mode] = _section_from_identity(ident, mode)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def identity_load(path: str | Path) -> dict:
    """加载身份;文件缺失/损坏返回 {}(不抛,relay 侧负责报错提示)。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict = {}
    for mode in ("bredr", "le"):
        if isinstance(data.get(mode), dict):
            try:
                out[mode] = _identity_from_section(data[mode], mode)
            except (KeyError, ValueError, TypeError):
                continue
    return out
```

顶部 import 区补:`import json`、`from pathlib import Path`、`from datetime import datetime, timezone`(datetime 已有 `datetime`,补 `timezone`)。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/mitm/test_identity_json.py -q`
Expected: PASS(4 passed)

- [ ] **Step 5: 提交**

```bash
git add pybluehost/cli/app/mitm/cli.py tests/unit/mitm/test_identity_json.py
git commit -m "feat(mitm): 身份 JSON 读写(按段合并,scan↔relay 桥)"
```

### Task 6: session.py — MitmSession 骨架(唯一属主 + ACL if/else 分发 + 编排)

**Files:**
- Create: `pybluehost/cli/app/mitm/session.py`
- Test: `tests/unit/mitm/test_session.py`(新建)

本任务建立骨架:事件多点订阅、ACL 分发、run() 编排、`_run_link` 骨架、impersonate、teardown。BR/LE 的 accept/connect/bring_up 具体实现分别在 Task 7/8 落地;本任务里它们以 `_accept_bredr` 等方法名占位 `raise NotImplementedError`(测试只测已实现部分)。

- [ ] **Step 1: 写失败测试**

```python
"""MitmSession 骨架:事件多点订阅 + ACL if/else 分发 + impersonate 编排。"""
import asyncio
from dataclasses import dataclass, field

import pytest

from pybluehost.cli.app.mitm.recon import ClonedIdentity
from pybluehost.cli.app.mitm.relay import AclRelay, RelaySide
from pybluehost.cli.app.mitm.session import MitmSession
from pybluehost.hci.constants import EventCode
from pybluehost.hci.packets import HCIACLData, HCICommand, HCIEvent


class FakeCtl:
    """最小 controller:记录 set_upstream 与 send_command,事件手动注入。"""

    def __init__(self, name="ctl"):
        self.name = name
        self._on_hci_event = None
        self._on_acl_data = None
        self._on_sco_data = None
        self.commands: list[HCICommand] = []

    def set_upstream(self, on_hci_event=None, on_acl_data=None, on_sco_data=None):
        self._on_hci_event = on_hci_event
        self._on_acl_data = on_acl_data
        self._on_sco_data = on_sco_data

    async def send_command(self, command):
        self.commands.append(command)

    def inject_event(self, code: int, params: bytes = b""):
        self._on_hci_event(HCIEvent.from_bytes(code, params))


@dataclass
class FakePair:
    upstream: object = field(default_factory=FakeCtl)
    downstream: object = field(default_factory=FakeCtl)


IDENT = ClonedIdentity(address="38:D5:18:CD:52:F7", address_type=0, adv_data=b"",
                       scan_response=b"", name="X", class_of_device=None)


def _mk_session(identities=None):
    pair = FakePair()
    s = MitmSession(
        pair,
        identities=identities if identities is not None else {"bredr": IDENT, "le": None},
    )
    return s, pair


def _acl(handle: int, data: bytes = b"\x01\x00\x04\x00\x2A") -> HCIACLData:
    return HCIACLData(handle=handle, pb_flag=0x02, data=data)


def _recording_relay():
    sent = []

    async def send_acl(h, pb, d):
        sent.append((h, pb, d))

    side = RelaySide(name="x", handle=0, acl_max_payload=27, send_acl=send_acl)
    return AclRelay(phone_side=side, target_side=side), sent


async def test_event_dispatch_fans_out_to_all_subscribers():
    s, pair = _mk_session()
    s._install_dispatch()
    seen_down, seen_up = [], []
    s._subscribe("down", seen_down.append)
    s._subscribe("down", seen_up.append)  # 两个订阅者都该收到
    pair.downstream.inject_event(EventCode.CONNECTION_REQUEST, b"x")
    assert len(seen_down) == 1 and len(seen_up) == 1
    s._unsubscribe("down", seen_down.append)
    pair.downstream.inject_event(EventCode.CONNECTION_REQUEST, b"x")
    assert len(seen_down) == 1 and len(seen_up) == 2  # 只剩第二个订阅者


async def test_unsubscribe_missing_is_silent():
    s, pair = _mk_session()
    s._install_dispatch()
    s._unsubscribe("down", lambda e: None)  # 不存在也不抛


async def test_acl_dispatch_routes_by_handle_if_else():
    """LE/BR 各自的 handle 各进各的 relay,未知 handle 忽略。"""
    s, pair = _mk_session()
    le_relay, le_sent = _recording_relay()
    br_relay, br_sent = _recording_relay()
    s._le = s._make_link_state("le", phone_handle=0x10, earbud_handle=0x11, relay=le_relay)
    s._br = s._make_link_state("bredr", phone_handle=0x20, earbud_handle=0x21, relay=br_relay)

    s._on_down_acl(_acl(0x10))   # → LE relay
    s._on_down_acl(_acl(0x20))   # → BR relay
    s._on_down_acl(_acl(0x99))   # 未知 → 忽略
    s._on_up_acl(_acl(0x11))
    s._on_up_acl(_acl(0x21))
    await asyncio.gather(s._le.relay.flush(), s._br.relay.flush())
    assert len(le_sent) == 2   # down 0x10 + up 0x11
    assert len(br_sent) == 2
    for h, _, _ in br_sent:
        assert h in (0x20, 0x21)
    await s._le.relay.stop()
    await s._br.relay.stop()


async def test_run_requires_identity(monkeypatch):
    """没有任何身份 → 明确报错。"""
    s, pair = _mk_session(identities={"bredr": None, "le": None})
    with pytest.raises(RuntimeError):
        await s.run()


async def test_run_impersonates_each_section(monkeypatch):
    """有哪段身份就调哪个 impersonate;downstream 上发命令。"""
    s, pair = _mk_session(identities={"bredr": IDENT, "le": None})
    calls = []

    async def fake_bredr(ctl, ident, *, clone_address):
        calls.append(("bredr", ident.name))

    async def fake_le(ctl, ident, *, clone_address):
        calls.append(("le", ident.name))

    monkeypatch.setattr("pybluehost.cli.app.mitm.bredr_impersonate.start_bredr_impersonation", fake_bredr)
    monkeypatch.setattr("pybluehost.cli.app.mitm.impersonate.start_impersonation", fake_le)
    # impersonate 之后 SSP/tracker/link 全部启用;链接等待会常驻 → 跑 0.2s 就取消
    task = asyncio.ensure_future(s.run())
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == [("bredr", "X")]
    # 启动段:upstream 开 SSP(0x0418? 用常量判断更稳,见实现)
    from pybluehost.hci.constants import HCI_WRITE_SIMPLE_PAIRING_MODE
    up_opcodes = [c.opcode for c in pair.upstream.commands]
    assert HCI_WRITE_SIMPLE_PAIRING_MODE in up_opcodes


async def test_teardown_disables_scan_and_closes():
    s, pair = _mk_session()
    closed = []

    async def fake_close():
        closed.append(True)

    s._capture_close = fake_close
    await s.teardown()
    from pybluehost.hci.constants import HCI_WRITE_SCAN_ENABLE
    for ctl in (pair.upstream, pair.downstream):
        opcodes = [c.opcode for c in ctl.commands]
        assert HCI_WRITE_SCAN_ENABLE in opcodes
    assert closed == [True]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/mitm/test_session.py -q`
Expected: FAIL(`ModuleNotFoundError: session`)

- [ ] **Step 3: 创建 session.py 骨架**

```python
"""MitmSession —— MITM 编排(替代 orchestrator.MitmRelay god-class)。

结构要点:
- session 是每 controller 的 `set_upstream` **唯一属主**:HCI 事件多点订阅
  (subscribe/unsubscribe),ACL 按 handle 的 if/else 分发到各链路 AclRelay。
- BR 的 SspTermination 在 run() 启动段 attach(等手机之前,G3 时序硬约束);
  LE 的 ScPairing 是连接后才走 L2CAP SMP,可在链路内建。
- _run_link 一份骨架,LE/BR 各跑一个;两条链独立重连互不联动。
- AclRelay 出站解耦引擎原样复用;可选 transform 钩子透传。

HARD RULE:不 import pybluehost.l2cap/.ble/.classic/.gap/.profiles/.stack。
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from pybluehost.cli.app.mitm.capture import BtsnoopCaptureTap, NullTap
from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate, PairingDelegate
from pybluehost.cli.app.mitm.pairing.ssp import SspTermination
from pybluehost.cli.app.mitm.relay import AclRelay, RelaySide
from pybluehost.cli.app.mitm.transform import PduTransform
from pybluehost.hci.constants import (
    EventCode,
    HCI_DISCONNECT,
    HCI_WRITE_SCAN_ENABLE,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
)
from pybluehost.hci.packets import HCIACLData, HCICommand, HCIEvent

if TYPE_CHECKING:
    from pybluehost.cli.app.mitm.controllers import ControllerPair
    from pybluehost.cli.app.mitm.recon import ClonedIdentity
    from pybluehost.hci.controller import HCIController

logger = logging.getLogger(__name__)


@dataclass
class _LinkState:
    """一条链路(LE 或 BR)本轮连接的全部可变状态。重连一轮换一个新实例。"""
    mode: str
    phone_handle: int
    earbud_handle: int
    relay: AclRelay
    link_lost: asyncio.Event
    # LE 专用:SMP 地址(type||6B LE 序)与 ScPairing/drain 任务
    phone_addr7: bytes = b""
    target_addr7: bytes = b""
    pairings: dict = field(default_factory=dict)
    drain_tasks: list = field(default_factory=list)
    # 本轮订阅的事件回调(teardown 时统一退订)
    watches: list = field(default_factory=list)


class MitmSession:
    def __init__(
        self,
        pair: "ControllerPair",
        *,
        identities: dict,
        delegate: Optional[PairingDelegate] = None,
        numeric: bool = False,
        btsnoop: Optional[str] = None,
        clone_address: bool = False,
        key_log: Optional[str | Path] = None,
        name_override: Optional[str] = None,
        connect_timeout: float = 30.0,
        accept_timeout: Optional[float] = None,
        transform: Optional[PduTransform] = None,
    ) -> None:
        self._pair = pair
        # {"bredr": ClonedIdentity|None, "le": ClonedIdentity|None}
        self._identities = identities
        self._delegate: PairingDelegate = delegate or AutoConfirmDelegate()
        self._numeric = numeric
        self._capture = BtsnoopCaptureTap(btsnoop) if btsnoop else NullTap()
        self._clone_address = clone_address
        self._key_log = key_log
        self._name_override = name_override
        self._connect_timeout = connect_timeout
        self._accept_timeout = accept_timeout
        self._transform = transform

        self._le: Optional[_LinkState] = None
        self._br: Optional[_LinkState] = None
        self._subs: dict[str, list] = {"down": [], "up": []}
        self._ssp: dict[str, SspTermination] = {}
        self._bredr_conns: dict[str, int] = {}   # upstream 连接表(addr_le_hex→handle)
        self._installed = False
        # 任一链路活着即置位(供 stats reporter 判断 relay 已连接)
        self.connected = asyncio.Event()

    # ------------------------------------------------------- 事件分发(唯一属主)
    def _install_dispatch(self) -> None:
        if self._installed:
            return
        for side, ctl in (("down", self._pair.downstream), ("up", self._pair.upstream)):
            prev_sco = ctl._on_sco_data  # type: ignore[attr-defined]
            ctl.set_upstream(
                on_hci_event=self._make_event_dispatch(side),
                on_acl_data=self._on_down_acl if side == "down" else self._on_up_acl,
                on_sco_data=prev_sco,
            )
        self._installed = True

    def _make_event_dispatch(self, side: str) -> Callable[[HCIEvent], None]:
        def dispatch(event: HCIEvent) -> None:
            for cb in list(self._subs[side]):
                cb(event)
        return dispatch

    def _subscribe(self, side: str, cb: Callable[[HCIEvent], None]) -> None:
        self._subs[side].append(cb)

    def _unsubscribe(self, side: str, cb: Callable[[HCIEvent], None]) -> None:
        try:
            self._subs[side].remove(cb)
        except ValueError:
            pass

    def _on_down_acl(self, acl: HCIACLData) -> None:
        if self._le is not None and acl.handle == self._le.phone_handle:
            self._le.relay.on_phone_acl(acl)
        elif self._br is not None and acl.handle == self._br.phone_handle:
            self._br.relay.on_phone_acl(acl)
        # 其它 handle(未注册/已清理):忽略

    def _on_up_acl(self, acl: HCIACLData) -> None:
        if self._le is not None and acl.handle == self._le.earbud_handle:
            self._le.relay.on_target_acl(acl)
        elif self._br is not None and acl.handle == self._br.earbud_handle:
            self._br.relay.on_target_acl(acl)

    # ------------------------------------------------------------- 生命周期
    async def run(self) -> None:
        """impersonate → SSP/调度安装 → 双链路并发常驻(永不正常返回,断链内部重连)。"""
        await self._impersonate_all()
        modes = [m for m in ("bredr", "le") if self._identities.get(m) is not None]
        if not modes:
            raise RuntimeError("没有任何可用身份:先跑 `pybluehost app mitm scan`,或用 --target 指定")

        self._install_dispatch()
        if "bredr" in modes:
            # 连耳机时 upstream 作 initiator 也需 SSP;SSP 终结器必须在任何连接前
            # attach(G3 时序:手机一连上 ACL 就发起配对)。
            await self._pair.upstream.send_command(
                HCICommand(opcode=HCI_WRITE_SIMPLE_PAIRING_MODE, parameters=bytes([0x01]))
            )
            self._ensure_ssp()
            self._subscribe("up", self._tracker_on_event)

        tasks = [asyncio.ensure_future(self._run_link(m)) for m in modes]
        try:
            await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()

    async def _impersonate_all(self) -> None:
        for mode in ("bredr", "le"):
            ident = self._identities.get(mode)
            if ident is None:
                continue
            if self._name_override is not None:
                ident = dataclasses.replace(ident, name=self._name_override)
            if mode == "bredr":
                from pybluehost.cli.app.mitm.bredr_impersonate import (  # noqa: PLC0415
                    start_bredr_impersonation,
                )
                await start_bredr_impersonation(
                    self._pair.downstream, ident, clone_address=self._clone_address
                )
            else:
                from pybluehost.cli.app.mitm.impersonate import (  # noqa: PLC0415
                    start_impersonation,
                )
                await start_impersonation(
                    self._pair.downstream, ident, clone_address=self._clone_address
                )

    def _ensure_ssp(self) -> None:
        """创建并 attach 两侧 SspTermination(幂等)。时序硬约束见 run()。"""
        if self._ssp:
            return
        self._ssp = {
            "phone": SspTermination(
                self._pair.downstream, delegate=self._delegate, side_name="phone",
                numeric=self._numeric, key_log_path=self._key_log,
            ),
            "target": SspTermination(
                self._pair.upstream, delegate=self._delegate, side_name="target",
                numeric=self._numeric, key_log_path=self._key_log,
            ),
        }
        self._ssp["phone"].attach()
        self._ssp["target"].attach()

    # --------------------------------------------------------------- 链路骨架
    def _make_link_state(
        self, mode: str, *, phone_handle: int, earbud_handle: int, relay: AclRelay
    ) -> _LinkState:
        return _LinkState(
            mode=mode, phone_handle=phone_handle, earbud_handle=earbud_handle,
            relay=relay, link_lost=asyncio.Event(),
        )

    def _link_attr(self, mode: str) -> str:
        return "_br" if mode == "bredr" else "_le"

    async def _run_link(self, mode: str) -> None:
        """一份骨架,两种模式:等手机 → 连耳机 → 建中继 → 常驻 → 断链清理 → 重来。"""
        accept = self._accept_bredr if mode == "bredr" else self._accept_le
        connect = self._connect_bredr if mode == "bredr" else self._connect_le
        bring_up = self._bredr_bring_up if mode == "bredr" else self._le_bring_up
        attr = self._link_attr(mode)

        while True:
            phone_handle = await accept()
            logger.info("session[%s]: 手机已连接 handle=0x%03X,随即连目标...", mode, phone_handle)
            try:
                earbud_handle = await connect()
            except Exception as exc:
                logger.warning("session[%s]: 连目标失败(%s),断手机侧回等", mode, exc)
                await self._graceful_disconnect(self._pair.downstream, phone_handle)
                continue

            relay, link = self._build_link(mode, phone_handle, earbud_handle)
            setattr(self, attr, link)
            try:
                self.connected.set()
                await bring_up(link)
                await link.link_lost.wait()
            finally:
                setattr(self, attr, None)
                if self._br is None and self._le is None:
                    self.connected.clear()
                await relay.stop()
                await asyncio.gather(
                    self._graceful_disconnect(self._pair.downstream, phone_handle),
                    self._graceful_disconnect(self._pair.upstream, earbud_handle),
                    return_exceptions=True,
                )
                for side, cb in link.watches:
                    self._unsubscribe(side, cb)
            logger.info("session[%s]: 链路断开并清理,回等手机重连...", mode)

    def _build_link(
        self, mode: str, phone_handle: int, earbud_handle: int
    ) -> tuple[AclRelay, _LinkState]:
        """取 buffer → 建 RelaySide×2 → AclRelay → 断链监听订阅。LE 的 SMP 桥接在
        各自模式实现里通过 _le_relay_extras 挂(_LinkState.pairings 等)。"""
        downstream = self._pair.downstream
        upstream = self._pair.upstream
        if mode == "bredr":
            phone_max = downstream.acl_packet_length or 27
            target_max = upstream.acl_packet_length or 27
        else:
            phone_max = downstream.le_acl_packet_length or downstream.acl_packet_length or 27
            target_max = upstream.le_acl_packet_length or upstream.acl_packet_length or 27
        phone_side = RelaySide(name="phone", handle=phone_handle,
                               acl_max_payload=phone_max, send_acl=downstream.send_acl_data)
        target_side = RelaySide(name="target", handle=earbud_handle,
                                acl_max_payload=target_max, send_acl=upstream.send_acl_data)
        relay = AclRelay(phone_side=phone_side, target_side=target_side,
                         capture=self._capture, smp_handler=None,
                         transform=self._transform)
        link = self._make_link_state(mode, phone_handle=phone_handle,
                                     earbud_handle=earbud_handle, relay=relay)
        # 断链监听:本侧 handle 断 → 断对侧 → 置 link_lost(只清本链,不联动另一条)
        down_watch = self._make_watch(mode, phone_handle, upstream, earbud_handle)
        up_watch = self._make_watch(mode, earbud_handle, downstream, phone_handle)
        self._subscribe("down", down_watch)
        self._subscribe("up", up_watch)
        link.watches = [("down", down_watch), ("up", up_watch)]
        if mode == "le":
            self._le_relay_extras(link)
        return relay, link

    def _make_watch(
        self, mode: str, my_handle: int,
        peer_ctl: "HCIController", peer_handle: int,
    ) -> Callable[[HCIEvent], None]:
        async def _peer_down() -> None:
            link = getattr(self, self._link_attr(mode))
            if link is None or link.link_lost.is_set():
                return
            try:
                await peer_ctl.send_command(
                    HCICommand(opcode=HCI_DISCONNECT,
                               parameters=peer_handle.to_bytes(2, "little") + bytes([0x16]))
                )
            except Exception:
                logger.exception("session: 对侧 disconnect 失败")
            if link.link_lost.is_set():
                return  # 另一侧已触发,避免重复
            link.link_lost.set()

        def on_event(event: HCIEvent) -> None:
            if event.event_code == EventCode.DISCONNECTION_COMPLETE:
                p = event.parameters
                if len(p) >= 4 and int.from_bytes(p[1:3], "little") == my_handle:
                    logger.warning("session[%s]: %s 侧断开 handle=0x%03X reason=0x%02X",
                                   mode, mode, my_handle, p[3])
                    asyncio.ensure_future(_peer_down())

        return on_event

    # ---------------------------------------------------- upstream 连接表 tracker
    def _tracker_on_event(self, event: HCIEvent) -> None:
        p = getattr(event, "parameters", b"") or b""
        if event.event_code == EventCode.CONNECTION_COMPLETE:
            # status(1) handle(2,小端) bd_addr(6)
            if len(p) >= 9 and p[0] == 0x00:
                self._bredr_conns[bytes(p[3:9]).hex()] = int.from_bytes(p[1:3], "little")
        elif event.event_code == EventCode.DISCONNECTION_COMPLETE:
            if len(p) >= 4:
                gone = int.from_bytes(p[1:3], "little")
                for addr in [a for a, h in self._bredr_conns.items() if h == gone]:
                    del self._bredr_conns[addr]

    # ----------------------------------------------- 模式实现(Task 7/8 落地)
    async def _accept_bredr(self) -> int:
        raise NotImplementedError

    async def _connect_bredr(self) -> int:
        raise NotImplementedError

    async def _bredr_bring_up(self, link: _LinkState) -> None:
        raise NotImplementedError

    async def _accept_le(self) -> int:
        raise NotImplementedError

    async def _connect_le(self) -> int:
        raise NotImplementedError

    def _le_relay_extras(self, link: _LinkState) -> None:
        raise NotImplementedError

    async def _le_bring_up(self, link: _LinkState) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------- 断链/teardown
    async def _graceful_disconnect(
        self, controller: "HCIController", handle: int, *, timeout: float = 2.0
    ) -> None:
        raise NotImplementedError

    async def teardown(self) -> None:
        # 先停两条链的 relay(丢弃残留出站),再关 scan,再关 capture / pair。
        for link in (self._br, self._le):
            if link is not None:
                try:
                    await link.relay.stop()
                except Exception:
                    logger.exception("session: relay stop 失败")
        for side, ctl in (("downstream", self._pair.downstream),
                          ("upstream", self._pair.upstream)):
            try:
                await asyncio.wait_for(
                    ctl.send_command(
                        HCICommand(opcode=HCI_WRITE_SCAN_ENABLE, parameters=bytes([0x00]))
                    ),
                    timeout=2.0,
                )
            except Exception:
                logger.debug("%s 关 scan 失败(控制器可能已异常)", side)
        await self._capture_close()
        try:
            await self._pair.close()
        except Exception:
            logger.exception("session: pair close 失败")

    async def _capture_close(self) -> None:
        await self._capture.close()
```

注意两点:`_capture_close` 是给测试注入用的薄包装(生产路径就是 `self._capture.close()`);`smp_handler=None` 在 `_build_link` 里对 LE 由 `_le_relay_extras`(Task 8)补挂——Task 8 会把 `_build_link` 中 LE 分支改为传入 `smp_handler`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/mitm/test_session.py -q`
Expected: PASS(7 passed)

- [ ] **Step 5: 提交**

```bash
git add pybluehost/cli/app/mitm/session.py tests/unit/mitm/test_session.py
git commit -m "feat(mitm): MitmSession 骨架 — 唯一属主事件分发 + ACL if/else + _run_link 编排"
```

### Task 7: session.py — BR 链路(port f382b1e 全部真机行为)

**Files:**
- Modify: `pybluehost/cli/app/mitm/session.py`
- Test: `tests/unit/mitm/test_session_bredr.py`(新建,移植 test_orchestrator_bredr_* / test_secure_target_link 共 23 个用例)

移植原则:**事件解析逻辑与 orchestrator 现版逐字一致,唯一差异是接线方式**——orchestrator 用"set_upstream + prev-forward 链",session 用 `_subscribe`/`_unsubscribe`(session 是唯一属主,不存在 prev 舞步)。每处移植都是:删 `prev_hci/prev_acl/prev_sco` 三行、删 `finally: controller.set_upstream(...)` 恢复段、`controller.set_upstream(on_hci_event=on_event)` 改 `self._subscribe(<side>, on_event)`、finally 里改 `self._unsubscribe(<side>, on_event)`。

- [ ] **Step 1: 建测试文件 `tests/unit/mitm/test_session_bredr.py` — 移植 23 个用例**

以 `tests/unit/mitm/test_orchestrator_bredr_accept.py` 为底本,做以下**机械替换**(所有 4 个源文件同一配方):

| 源(test_orchestrator_*) | 改为 |
|---|---|
| `from pybluehost.cli.app.mitm.orchestrator import MitmRelay` | `from pybluehost.cli.app.mitm.session import MitmSession` |
| `_bare_relay` 里 `MitmRelay.__new__(MitmRelay)` | `MitmSession.__new__(MitmSession)` |
| `relay._bredr_conns = {}` | 不变(session 同名字段) |
| `relay._await_bredr_connection(ctl, ...)` | `relay._accept_bredr_on(ctl, ...)`(见下:方法带 ctl 参数便于单测) |
| `relay._connect_bredr_target(ctl, addr)` | `relay._connect_bredr_on(ctl, addr)` |
| `relay._make_link_watch(...)` 直接调用 | `relay._make_watch(...)`(无 controller 参数——订阅制不需要 prev) |
| `relay._graceful_disconnect(ctl, h)` | `relay._graceful_disconnect_on(ctl, h)` |
| `relay._secure_target_link(ctl, h)` | `relay._secure_target_link_on(ctl, h)` |
| 断言回调恢复 `ctl._on_hci_event is prev` | 删除断言(订阅制没有回调替换);改为断言 `relay._subs["down"] == []`(已退订) |

`_accept_bredr` 等生产方法不带 ctl(用 self._pair),单测走带 ctl 的 `_xxx_on` 变体;生产方法一行委托:

```python
    async def _accept_bredr(self) -> int:
        return await self._accept_bredr_on(self._pair.downstream)

    async def _connect_bredr(self) -> int:
        ident = self._identities.get("bredr")
        assert ident is not None
        return await self._connect_bredr_on(self._pair.upstream, ident.address)
```

移植的测试清单(23 个,全部保留原断言语义):

- accept 6 个:`test_auto_accept_replies_accept_for_acl` / `test_auto_accept_ignores_sco_request` / `test_no_accept_when_auto_accept_off` / `test_accept_timeout_raises_when_no_connection` / `test_accept_timeout_none_waits_indefinitely` / `test_auto_accept_rejects_target_earbud_page`
- connect 8 个:`test_build_create_connection_params_layout` / `test_build_create_connection_params_allow_role_switch` / `test_connect_returns_handle_on_success` / `test_connect_retries_on_page_timeout` / `test_connect_raises_after_max_retries` / `test_connect_ignores_mismatched_connection_complete` / `test_connect_cancels_on_timeout_then_retries` / `test_connect_reuses_tracked_earbud_connection_without_paging` / `test_connect_adopts_earbud_connection_arriving_between_attempts`
- disconnect 6 个:`test_phone_disconnect_triggers_target_disconnect` / `test_disconnect_for_other_handle_ignored` / `test_second_disconnect_is_idempotent` / `test_graceful_disconnect_sends_and_waits` / `test_graceful_disconnect_already_down_times_out_quietly` / `test_graceful_disconnect_tolerates_command_error`
- secure 3 个:`test_auth_success_then_set_encryption` / `test_auth_failure_skips_encryption` / `test_ensure_phone_visible_reopens_scan_each_round`

其中 `build_create_connection_params` 从 orchestrator **原样搬**进 session.py(模块级函数 + `_BREDR_PACKET_TYPE_ALL` + `HCI_CREATE_CONNECTION_CANCEL` 常量)。disconnect 的 watch 测试改用 `session._make_watch(...)` 返回的回调直接注入 `session._subscribe("down", cb)`。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/mitm/test_session_bredr.py -q`
Expected: FAIL(方法不存在)

- [ ] **Step 3: 在 session.py 落地 BR 实现(替换 Task 6 的 NotImplementedError 占位)**

① 模块级(orchestrator 原样搬):`_BREDR_PACKET_TYPE_ALL`、`HCI_CREATE_CONNECTION_CANCEL`、`build_create_connection_params`。

② `_accept_bredr_on`(源:orchestrator `_await_bredr_connection`,L934-1031;接线改订阅):

```python
    async def _accept_bredr_on(
        self, controller: "HCIController", *, auto_accept: bool = True
    ) -> int:
        """等手机发起经典连接(自动 Accept ACL;耳机回连伪装身份的 page 拒绝)。"""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[int] = loop.create_future()
        ident = self._identities.get("bredr")
        identity_le = (
            bytes(reversed(bytes.fromhex(ident.address.replace(":", ""))))
            if ident is not None else None
        )

        def _log_accept_error(task: "asyncio.Task") -> None:
            exc = task.exception()
            if exc is not None:
                logger.warning("Accept_Connection_Request 发送失败: %s", exc)

        def on_event(event: HCIEvent) -> None:
            if event.event_code == EventCode.CONNECTION_REQUEST:
                params = getattr(event, "parameters", b"") or b""
                if len(params) >= 10 and params[0:6] == identity_le:
                    # 耳机把伪装设备当已配对手机回连:拒绝(0x0D),不当「手机」
                    asyncio.ensure_future(controller.send_command(
                        HCICommand(opcode=HCI_REJECT_CONNECTION_REQ,
                                   parameters=params[0:6] + bytes([0x0D]))))
                elif len(params) >= 10 and params[9] == 0x01 and auto_accept:
                    task = asyncio.ensure_future(controller.send_command(
                        HCICommand(opcode=HCI_ACCEPT_CONNECTION_REQ,
                                   parameters=params[0:6] + bytes([0x01]))))
                    task.add_done_callback(_log_accept_error)
            if event.event_code == EventCode.CONNECTION_COMPLETE:
                params = getattr(event, "parameters", b"") or b""
                is_earbud = (identity_le is not None and len(params) >= 9
                             and params[3:9] == identity_le)
                if (not is_earbud and len(params) >= 3 and params[0] == 0x00
                        and not fut.done()):
                    fut.set_result(int.from_bytes(params[1:3], "little"))

        self._subscribe("down", on_event)
        logger.info("session[bredr]: 等待手机发起连接(accept_timeout=%s)...",
                    "常驻" if self._accept_timeout is None else f"{self._accept_timeout}s")
        try:
            return await asyncio.wait_for(fut, timeout=self._accept_timeout)
        finally:
            self._unsubscribe("down", on_event)
```

③ `_connect_bredr_on`(源:orchestrator `_connect_bredr_target`,L820-932;接线改订阅;tracker 查表/采纳逻辑原样保留):

```python
    async def _connect_bredr_on(
        self, controller: "HCIController", target_addr: str, *, max_retries: int = 5
    ) -> int:
        addr_le = bytes(reversed(bytes.fromhex(target_addr.replace(":", ""))))
        params = build_create_connection_params(addr_le)
        loop = asyncio.get_running_loop()
        state: dict = {"fut": loop.create_future(), "handle": None,
                       "status": None, "in_flight": False}

        def on_event(event: HCIEvent) -> None:
            if event.event_code == EventCode.CONNECTION_COMPLETE:
                p = event.parameters
                if len(p) >= 9 and p[3:9] == addr_le:
                    if not state["in_flight"]:
                        if p[0] == 0x00:
                            # page 间隙耳机自行回连:记表,循环开头复用
                            adopted = int.from_bytes(p[1:3], "little")
                            self._bredr_conns[addr_le.hex()] = adopted
                            logger.info("session[bredr]: 耳机 page 间隙自行回连 handle=0x%03X",
                                        adopted)
                        return
                    state["in_flight"] = False
                    state["status"] = p[0]
                    if not state["fut"].done():
                        if p[0] == 0x00:
                            state["handle"] = int.from_bytes(p[1:3], "little")
                            state["fut"].set_result(True)
                        else:
                            state["fut"].set_result(False)

        self._subscribe("up", on_event)
        try:
            for attempt in range(1, max_retries + 1):
                tracked = self._bredr_conns.get(addr_le.hex())
                if tracked is not None:
                    logger.info("session[bredr]: 耳机已自行回连 handle=0x%03X,复用", tracked)
                    return tracked
                state["fut"] = loop.create_future()
                state["in_flight"] = True
                try:
                    await controller.send_command(
                        HCICommand(opcode=HCI_CREATE_CONNECTION, parameters=params))
                except Exception:
                    state["in_flight"] = False
                    raise
                try:
                    ok = await asyncio.wait_for(state["fut"], timeout=self._connect_timeout)
                except asyncio.TimeoutError:
                    state["in_flight"] = False
                    ok = False
                    if attempt < max_retries:
                        try:
                            await asyncio.wait_for(
                                controller.send_command(
                                    HCICommand(opcode=HCI_CREATE_CONNECTION_CANCEL,
                                               parameters=addr_le)),
                                timeout=2.0)
                        except Exception as exc:
                            logger.debug("Create_Connection_Cancel 失败(可能已自然完成): %s", exc)
                if ok:
                    logger.info("session[bredr]: 已连上目标 %s handle=0x%03X",
                                target_addr, state["handle"])
                    return state["handle"]
                logger.warning("session[bredr]: Create_Connection 第 %d/%d 次失败 status=%s",
                               attempt, max_retries, state["status"])
            raise RuntimeError(f"Create_Connection to {target_addr} failed after {max_retries} attempts")
        finally:
            self._unsubscribe("up", on_event)
```

④ `_ensure_phone_visible` + `_secure_target_link_on`(源 L732-818,接线改订阅;逻辑逐字保留):

```python
    async def _ensure_phone_visible(self) -> None:
        """每轮等手机前重发 Scan_Enable=0x03(Intel ACL 期间暂停 inquiry scan 且不恢复)。"""
        try:
            await self._pair.downstream.send_command(
                HCICommand(opcode=HCI_WRITE_SCAN_ENABLE, parameters=bytes([0x03])))
        except Exception as exc:
            logger.warning("session: 重开下游 scan 失败: %s", exc)

    async def _secure_target_link_on(
        self, controller: "HCIController", handle: int, *, timeout: float = 15.0
    ) -> None:
        """耳机链路主动认证(+配对)并加密。根因:耳机对 AVDTP/RFCOMM 回
        authorization-pending 等本端认证,无人发起则 30-60s 后 0x05 断链。"""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[int] = loop.create_future()

        def on_event(event: HCIEvent) -> None:
            if (event.event_code == EventCode.AUTH_COMPLETE
                    and len(event.parameters) >= 1 and not fut.done()):
                fut.set_result(event.parameters[0])

        self._subscribe("up", on_event)
        try:
            await asyncio.sleep(1.0)  # 给对端一点稳定时间(建链后常先跑 SDP)
            try:
                await controller.send_command(
                    HCICommand(opcode=HCI_AUTH_REQUESTED,
                               parameters=handle.to_bytes(2, "little")))
            except Exception as exc:
                logger.warning("session: Authentication_Requested 发送失败: %s", exc)
                return
            try:
                status = await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("session: 等 Authentication_Complete 超时(%ss)", timeout)
                return
            if status != 0x00:
                logger.warning("session: 耳机链路认证失败 status=0x%02X", status)
                return
            logger.info("session: 耳机链路认证完成,启用加密 handle=0x%03X", handle)
            try:
                await controller.send_command(
                    HCICommand(opcode=HCI_SET_CONNECTION_ENCRYPTION,
                               parameters=handle.to_bytes(2, "little") + bytes([0x01])))
            except Exception as exc:
                logger.warning("session: Set_Connection_Encryption 发送失败: %s", exc)
        finally:
            self._unsubscribe("up", on_event)
```

⑤ `_graceful_disconnect_on`(源 L550-600;接线改订阅。注意:它要**临时**抢断链事件,订阅制下 watch 也在收同一事件——互不冲突,都收得到):

```python
    async def _graceful_disconnect_on(
        self, controller: "HCIController", handle: int, *, timeout: float = 2.0
    ) -> None:
        """补发幂等 HCI_Disconnect 并等 Disconnection_Complete(BE200 楔死教训)。"""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()
        side = "down" if controller is self._pair.downstream else "up"

        def on_event(event: HCIEvent) -> None:
            if event.event_code == EventCode.DISCONNECTION_COMPLETE:
                p = event.parameters
                if (len(p) >= 4 and int.from_bytes(p[1:3], "little") == handle
                        and not fut.done()):
                    fut.set_result(None)

        self._subscribe(side, on_event)
        try:
            try:
                await controller.send_command(
                    HCICommand(opcode=HCI_DISCONNECT,
                               parameters=handle.to_bytes(2, "little") + bytes([0x16])))
            except Exception:
                logger.debug("HCI_Disconnect handle=0x%03X 报错(可能已断)", handle)
            try:
                await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                logger.debug("等 Disconnection_Complete 超时 handle=0x%03X(可能已断)", handle)
        finally:
            self._unsubscribe(side, on_event)
```

生产方法委托(供 `_run_link`/骨架调用):

```python
    async def _graceful_disconnect(self, controller, handle, *, timeout: float = 2.0) -> None:
        await self._graceful_disconnect_on(controller, handle, timeout=timeout)

    async def _bredr_bring_up(self, link: _LinkState) -> None:
        # 每轮等手机前已由 accept 循环外重开 scan;relay 建立后立即主动认证+加密
        asyncio.ensure_future(
            self._secure_target_link_on(self._pair.upstream, link.earbud_handle))
```

⑥ `_accept_bredr`/`_connect_bredr` 委托 + 在 `_run_link` 的 `while True:` 开头(br 模式时)调 `await self._ensure_phone_visible()`(在 accept 之前;LE 模式不需要):

```python
        while True:
            if mode == "bredr":
                await self._ensure_phone_visible()
            phone_handle = await accept()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/mitm/test_session_bredr.py tests/unit/mitm/test_session.py -q`
Expected: PASS(23+7)

- [ ] **Step 5: 提交**

```bash
git add pybluehost/cli/app/mitm/session.py tests/unit/mitm/test_session_bredr.py
git commit -m "feat(mitm): session BR 链路 — port accept/connect/tracker/secure-link/scan-reopen"
```

### Task 8: session.py — LE 链路补真(LE_Create_Connection + 真实地址 SMP + LTK 加密)

**Files:**
- Modify: `pybluehost/cli/app/mitm/session.py`
- Test: `tests/unit/mitm/test_session_le.py`(新建)

- [ ] **Step 1: 写失败测试**

```python
"""LE 链路:连接建立、SMP 桥接真实地址、LTK 加密。"""
import asyncio
import struct

from pybluehost.cli.app.mitm.recon import ClonedIdentity
from pybluehost.cli.app.mitm.session import (
    MitmSession,
    _addr_str_to_le6,
    build_le_create_connection_params,
)
from pybluehost.hci.constants import (
    HCI_LE_CREATE_CONNECTION,
    HCI_LE_LONG_TERM_KEY_REQUEST_REPLY,
    HCI_LE_START_ENCRYPTION,
    LEMetaSubEvent,
)
from pybluehost.hci.packets import HCI_LE_Meta_Event, HCICommand, HCIEvent
from tests.unit.mitm.test_session import FakeCtl, FakePair, _mk_session


def test_addr_str_to_le6():
    assert _addr_str_to_le6("38:D5:18:CD:52:F7") == bytes.fromhex("F752CD18D538")


def test_build_le_create_connection_params_layout():
    p = build_le_create_connection_params(bytes.fromhex("F752CD18D538"), 0)
    # scan_int(2) scan_win(2) filter(1) ptype(1) paddr(6) own(1)
    # min(2) max(2) lat(2) timeout(2) ce_min(2) ce_max(2) = 25 字节
    assert len(p) == 25
    scan_int, scan_win = struct.unpack_from("<HH", p, 0)
    assert (scan_int, scan_win) == (0x0060, 0x0030)
    assert p[4] == 0x00          # filter: 用 peer 地址
    assert p[5] == 0x00          # peer addr type public
    assert p[6:12] == bytes.fromhex("F752CD18D538")
    assert p[12] == 0x00         # own addr type public
    ci_min, ci_max, lat, sup = struct.unpack_from("<HHHH", p, 13)
    assert (ci_min, ci_max, lat, sup) == (0x0006, 0x000C, 0x0000, 0x00C8)


def _le_conn_event(handle=0x0030, role=0x00, peer_type=0, peer6=bytes.fromhex("F752CD18D538")):
    params = (bytes([0x00]) + handle.to_bytes(2, "little") + bytes([role])
              + bytes([peer_type]) + peer6
              + struct.pack("<HHB", 0x0008, 0x0000, 0x00))  # interval/latency/clock
    return HCI_LE_Meta_Event.from_bytes(
        0x3E, bytes([LEMetaSubEvent.LE_CONNECTION_COMPLETE]) + params)


async def test_accept_le_parses_handle_and_peer_addr():
    s, pair = _mk_session(identities={"bredr": None, "le": ClonedIdentity(
        address="38:D5:18:CD:52:F8", address_type=0, adv_data=b"",
        scan_response=b"", name=None)})
    task = asyncio.ensure_future(s._accept_le_on(pair.downstream))
    await asyncio.sleep(0)
    pair.downstream.inject_event(0x3E, _le_conn_event().raw_bytes[3:])
    # inject_event 直接喂 HCIEvent;LE Meta 需经 _accept_le_on 内的解析 —
    # 实现:订阅回调里 isinstance(HCI_LE_Meta_Event) 判断。此处注入已构造好的对象:
    # (见实现注释 — FakeCtl.inject_event 传 HCIEvent.from_bytes;LE 用专用注入)
    conn = await asyncio.wait_for(task, 1.0)
    assert conn.handle == 0x0030
    assert conn.role == 0x00
    assert conn.peer_addr6 == bytes.fromhex("F752CD18D538")


async def test_connect_le_sends_create_connection_and_waits():
    s, pair = _mk_session(identities={"bredr": None, "le": ClonedIdentity(
        address="38:D5:18:CD:52:F7", address_type=0, adv_data=b"",
        scan_response=b"", name=None)})
    task = asyncio.ensure_future(s._connect_le_on(pair.upstream))
    await asyncio.sleep(0)
    # Create_Connection 已发出
    assert any(c.opcode == HCI_LE_CREATE_CONNECTION for c in pair.upstream.commands)
    pair.upstream._on_hci_event(_le_conn_event(handle=0x0040))
    handle = await asyncio.wait_for(task, 1.0)
    assert handle == 0x0040


async def test_smp_bridged_with_real_addresses_end_to_end():
    """两侧 ScPairing 用真实 addr7 时,SMP Request 经 relay 到达对侧 pairing。"""
    s, pair = _mk_session(identities={"bredr": None, "le": ClonedIdentity(
        address="38:D5:18:CD:52:F7", address_type=0, adv_data=b"",
        scan_response=b"", name=None)})
    relay, link = s._build_link_for_test()
    from pybluehost.cli.app.mitm.pairing.smp_pdu import PAIRING_REQUEST
    from pybluehost.cli.app.mitm.acl import encode_l2cap_basic, CID_SMP
    pdu = encode_l2cap_basic(CID_SMP, bytes([PAIRING_REQUEST]) + bytes(6))
    acl = HCIACLData(handle=link.phone_handle, pb_flag=0x02, data=pdu)
    await relay.on_phone_acl(acl)
    # SMP 是本地终结:不应转发到对侧 send,而是喂进 phone pairing(无异常即可)
    await relay.flush()


async def test_le_bring_up_starts_encryption_after_pairing():
    s, pair = _mk_session(identities={"bredr": None, "le": ClonedIdentity(
        address="38:D5:18:CD:52:F7", address_type=0, adv_data=b"",
        scan_response=b"", name=None)})
    relay, link = s._build_link_for_test()
    # 模拟 pairing 已完成(直接塞 LTK)
    link.pairings["target"].ltk = b"\x11" * 16
    task = asyncio.ensure_future(s._le_bring_up_on(link))
    await asyncio.wait_for(task, 2.0)
    enc = [c for c in pair.upstream.commands if c.opcode == HCI_LE_START_ENCRYPTION]
    assert len(enc) == 1
    assert enc[0].parameters[0:2] == link.earbud_handle.to_bytes(2, "little")
    assert enc[0].parameters[12:28] == b"\x11" * 16


async def test_ltk_request_replies_from_pairing():
    s, pair = _mk_session(identities={"bredr": None, "le": ClonedIdentity(
        address="38:D5:18:CD:52:F7", address_type=0, adv_data=b"",
        scan_response=b"", name=None)})
    relay, link = s._build_link_for_test()
    s._le = link
    link.pairings["phone"].ltk = b"\x22" * 16
    sub_params = (link.phone_handle.to_bytes(2, "little")
                  + b"\x01" * 8 + b"\x02" * 2)
    s._on_phone_ltk_request(link.phone_handle, b"\x01" * 8, 0x0202)
    await asyncio.sleep(0)
    replies = [c for c in pair.downstream.commands
               if c.opcode == HCI_LE_LONG_TERM_KEY_REQUEST_REPLY]
    assert len(replies) == 1 and replies[0].parameters[2:18] == b"\x22" * 16
```

说明:`_le_conn_event().raw_bytes[3:]` 与注入方式的细节以实现为准——FakeCtl 需要一个 `inject_le(obj)` 直接传事件对象;`_build_link_for_test` 是 Task 8 加的测试辅助(按固定 handle 0x10/0x11 建 LE link 并填 pairings),生产路径不使用。写实现时如测试辅助不合适,以"断言语义不变"为准微调注入方式。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/mitm/test_session_le.py -q`
Expected: FAIL(符号不存在)

- [ ] **Step 3: session.py 落地 LE 实现**

① 模块级:

```python
import struct  # 顶部

def _addr_str_to_le6(addr: str) -> bytes:
    return bytes(reversed(bytes.fromhex(addr.replace(":", ""))))


def _addr_str_to_le7(addr: str, addr_type: int) -> bytes:
    """ScPairing 的 A1/A2:(addr_type || 6B LE 序)。"""
    return bytes([addr_type & 0x01]) + _addr_str_to_le6(addr)


def build_le_create_connection_params(peer_addr_le: bytes, peer_addr_type: int) -> bytes:
    """HCI_LE_Create_Connection 参数体(Core Vol4 E §7.8.12)。"""
    return (
        struct.pack("<HH", 0x0060, 0x0030)     # scan interval/window
        + bytes([0x00])                        # initiator_filter: peer addr
        + bytes([peer_addr_type & 0x01]) + peer_addr_le
        + bytes([0x00])                        # own_addr_type: public
        + struct.pack("<HHHHHH",
                      0x0006, 0x000C,          # conn interval 7.5-15ms
                      0x0000,                  # latency
                      0x00C8,                  # supervision timeout 2s
                      0x0000, 0x0000)          # ce len
    )
```

② 连接等待/发起(订阅制;LE Connection Complete 子事件布局:status(1) handle(2) role(1) peer_type(1) peer_addr(6) ...):

```python
@dataclass
class _LeConn:
    handle: int
    role: int
    peer_addr_type: int
    peer_addr6: bytes


    async def _accept_le_on(self, controller: "HCIController") -> _LeConn:
        """等 LE_Connection_Complete / Enhanced,解析 handle+role+对端地址。"""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[_LeConn] = loop.create_future()

        def on_event(event: HCIEvent) -> None:
            if (isinstance(event, HCI_LE_Meta_Event) and event.subevent_code in (
                    LEMetaSubEvent.LE_CONNECTION_COMPLETE,
                    LEMetaSubEvent.LE_ENHANCED_CONNECTION_COMPLETE)):
                p = event.subevent_parameters
                if len(p) >= 11 and p[0] == 0x00 and not fut.done():
                    # 布局:status(0) handle(1:3) role(3) peer_type(4) peer(5:11)
                    fut.set_result(_LeConn(
                        handle=int.from_bytes(p[1:3], "little"),
                        role=p[3],
                        peer_addr_type=p[4],
                        peer_addr6=bytes(p[5:11]),
                    ))

        self._subscribe("down", on_event)
        try:
            return await asyncio.wait_for(fut, timeout=self._accept_timeout
                                          if self._accept_timeout is not None
                                          else self._connect_timeout)
        finally:
            self._unsubscribe("down", on_event)
```

(Enhanced 子事件前 11 字节布局与 LE_Connection_Complete 相同,以上解析两用。)

```python
    async def _connect_le_on(self, controller: "HCIController",
                             *, max_retries: int = 3) -> int:
        """LE_Create_Connection 连真耳机;事件匹配对端地址才消费。"""
        ident = self._identities.get("le")
        assert ident is not None
        addr_le = _addr_str_to_le6(ident.address)
        params = build_le_create_connection_params(addr_le, ident.address_type)
        loop = asyncio.get_running_loop()
        state: dict = {"fut": loop.create_future(), "in_flight": False}

        def on_event(event: HCIEvent) -> None:
            if (isinstance(event, HCI_LE_Meta_Event) and event.subevent_code in (
                    LEMetaSubEvent.LE_CONNECTION_COMPLETE,
                    LEMetaSubEvent.LE_ENHANCED_CONNECTION_COMPLETE)):
                p = event.subevent_parameters
                if len(p) >= 11 and p[0] == 0x00 and bytes(p[5:11]) == addr_le:
                    if state["in_flight"] and not state["fut"].done():
                        state["in_flight"] = False
                        state["fut"].set_result(int.from_bytes(p[1:3], "little"))

        self._subscribe("up", on_event)
        try:
            for attempt in range(1, max_retries + 1):
                state["fut"] = loop.create_future()
                state["in_flight"] = True
                try:
                    await controller.send_command(
                        HCICommand(opcode=HCI_LE_CREATE_CONNECTION, parameters=params))
                except Exception:
                    state["in_flight"] = False
                    raise
                try:
                    return await asyncio.wait_for(state["fut"],
                                                  timeout=self._connect_timeout)
                except asyncio.TimeoutError:
                    state["in_flight"] = False
                    if attempt < max_retries:
                        try:
                            await asyncio.wait_for(
                                controller.send_command(
                                    HCICommand(opcode=HCI_LE_CREATE_CONNECTION_CANCEL,
                                               parameters=bytes([ident.address_type & 0x01])
                                               + addr_le)),
                                timeout=2.0)
                        except Exception as exc:
                            logger.debug("LE Create_Connection_Cancel 失败: %s", exc)
            raise RuntimeError(f"LE Create_Connection to {ident.address} failed")
        finally:
            self._unsubscribe("up", on_event)
```

③ SMP 桥接(源:orchestrator `_build_relay`/`_make_smp_emitter`/`_drain_smp`/`_send_smp` 原样逻辑,挂到 `_LinkState`):

```python
    def _le_relay_extras(self, link: _LinkState) -> None:
        """LE 专用:真实地址的 ScPairing(phone=responder,target=initiator)。
        地址字段由 _build_link 的 LE 分支先填好。"""
        link.pairings = {
            "phone": ScPairing(role="responder",
                               local_addr=link.phone_addr7,
                               peer_addr=link.phone_peer7,
                               delegate=self._delegate, side_name="phone"),
            "target": ScPairing(role="initiator",
                                local_addr=link.target_addr7,
                                peer_addr=link.target_peer7,
                                delegate=self._delegate, side_name="target"),
        }
```

`_LinkState` 地址字段(Task 6 定义补齐):`phone_addr7 / phone_peer7 / target_addr7 / target_peer7`(dataclass 字段,默认 `b""`)。为使 `_build_link` 在 LE 分支填地址+pairings+smp_handler,Task 6 的 `_build_link` 中 `relay = AclRelay(..., smp_handler=None, ...)` 改为:

```python
        relay = AclRelay(phone_side=phone_side, target_side=target_side,
                         capture=self._capture, smp_handler=None,
                         transform=self._transform)
        ...
        if mode == "le":
            self._le_relay_extras(link)                      # 地址已填 → 建 pairings
            relay._smp_handler = self._make_smp_handler(link)  # 地址就绪后挂 handler
```

(`relay._smp_handler` 是 relay 的私有属性;更干净的做法是 `_build_link` 里 LE 分支先 `_le_fill_addresses(link, le_conn)` → `_le_relay_extras(link)` → 再用 `self._make_smp_handler(link)` 构造 AclRelay。执行时采用后者,避免戳私有成员。)

`_make_smp_handler(link)` 与 drain 队列(源 orchestrator L214-273 原样逻辑,队列/drain 存 `link`):

```python
    def _make_smp_handler(self, link: _LinkState):
        link.smp_queues = {"phone": asyncio.Queue(), "target": asyncio.Queue()}
        for name in ("phone", "target"):
            link.drain_tasks.append(asyncio.ensure_future(self._drain_le_smp(link, name)))
        for name, pairing in link.pairings.items():
            q = link.smp_queues[name]
            pairing.set_output(lambda pdu, _q=q: _q.put_nowait(pdu))

        async def smp_handler(side_name: str, cid: int, payload: bytes) -> None:
            pairing = link.pairings.get(side_name)
            if pairing is None:
                logger.warning("session[le]: 未知侧 %r 的 SMP PDU,丢弃", side_name)
                return
            await pairing.feed(payload)

        return smp_handler

    async def _drain_le_smp(self, link: _LinkState, name: str) -> None:
        queue = link.smp_queues[name]
        side_ctl = (self._pair.downstream if name == "phone" else self._pair.upstream)
        handle = link.phone_handle if name == "phone" else link.earbud_handle
        max_payload = (self._pair.downstream.le_acl_packet_length
                       or self._pair.downstream.acl_packet_length or 27
                       ) if name == "phone" else (
                       self._pair.upstream.le_acl_packet_length
                       or self._pair.upstream.acl_packet_length or 27)
        while True:
            pdu = await queue.get()
            try:
                l2 = encode_l2cap_basic(CID_SMP, pdu)
                for frag in fragment(handle=handle, l2cap_pdu=l2, max_payload=max_payload):
                    await side_ctl.send_acl_data(frag.handle, frag.pb_flag, frag.data)
            except Exception:
                logger.exception("session[le]: 发送 %s 侧 SMP 失败", name)
            finally:
                queue.task_done()
```

session.py 顶部补 import:`from pybluehost.cli.app.mitm.acl import CID_SMP, encode_l2cap_basic, fragment`、`from pybluehost.cli.app.mitm.pairing.smp import ScPairing`、`from pybluehost.hci.constants import HCI_LE_CREATE_CONNECTION, HCI_LE_CREATE_CONNECTION_CANCEL, HCI_LE_LONG_TERM_KEY_REQUEST_REPLY, HCI_LE_START_ENCRYPTION, LEMetaSubEvent`、`from pybluehost.hci.packets import HCI_LE_Meta_Event`。

④ bring_up + LTK(Task 9 持久化接入点已留):

```python
    async def _accept_le(self) -> _LeConn:
        return await self._accept_le_on(self._pair.downstream)

    async def _connect_le(self) -> int:
        return await self._connect_le_on(self._pair.upstream)

    async def _le_bring_up(self, link: _LinkState) -> None:
        # 1) initiator(target 侧)发起 SMP
        await link.pairings["target"].start()
        # 2) 等 target 配对完成 → LE_Start_Encryption(~20s 上限)
        pairing = link.pairings["target"]
        for _ in range(2000):
            if pairing.is_complete() and pairing.ltk is not None:
                break
            await asyncio.sleep(0.01)
        if pairing.is_complete() and pairing.ltk is not None:
            params = (link.earbud_handle.to_bytes(2, "little")
                      + bytes(8) + bytes(2) + pairing.ltk)   # SC: rand/ediv = 0
            await self._pair.upstream.send_command(
                HCICommand(opcode=HCI_LE_START_ENCRYPTION, parameters=params))
            self._save_le_ltk("target", link, pairing.ltk)
        else:
            logger.warning("session[le]: target 配对未完成,跳过 LE_Start_Encryption")

    def _on_phone_ltk_request(self, handle: int, rand: bytes, ediv: int) -> None:
        link = self._le
        ltk = None
        if link is not None and handle == link.phone_handle:
            ltk = link.pairings["phone"].ltk or self._load_le_ltk("phone", link)
        if ltk is None:
            logger.warning("session[le]: phone LTK 未就绪,忽略 LE_LTK_Request")
            return
        asyncio.ensure_future(self._pair.downstream.send_command(
            HCICommand(opcode=HCI_LE_LONG_TERM_KEY_REQUEST_REPLY,
                       parameters=handle.to_bytes(2, "little") + ltk)))

    # Task 9 接入点;本任务先给内存版
    def _load_le_ltk(self, side: str, link: _LinkState):
        return None

    def _save_le_ltk(self, side: str, link: _LinkState, ltk: bytes) -> None:
        pass
```

⑤ run() 的 LE 启用段 + `_build_link` LE 地址填充(Task 6 的 `_build_link` LE 分支内):

```python
    # run() 中,LE 启用时一次性做:
    if "le" in modes:
        for name, ctl in (("down", self._pair.downstream), ("up", self._pair.upstream)):
            evt = await ctl.send_command(
                HCICommand(opcode=HCI_READ_BD_ADDR))   # send_command 返回事件(见控制器)
        # 本机地址:evt.parameters[-6:] 是 LE 序;存 self._down_addr6/_up_addr6
        self._down_le_ltk_listener_installed = True
        self._pair.downstream.on_le_ltk_request(self._on_phone_ltk_request)
```

**实现注意**:`HCIController.send_command` 的返回值是 Command Complete 事件(与 `mitm_traced.py:_read_mac` 用法一致:`evt.parameters[-6:]` 即本机 BD_ADDR 的 LE 序)。`_build_link` LE 分支填:

```python
        if mode == "le":
            ident = self._identities.get("le")
            conn = le_conn   # accept 返回的 _LeConn,经参数传入 _build_link
            link.phone_addr7 = bytes([0x00]) + self._down_addr6
            link.phone_peer7 = bytes([conn.peer_addr_type]) + conn.peer_addr6
            link.target_addr7 = bytes([0x00]) + self._up_addr6
            link.target_peer7 = bytes([ident.address_type & 0x01]) + _addr_str_to_le6(ident.address)
```

即 `_build_link` 签名加可选 `le_conn: "_LeConn | None" = None`,`_run_link` 里把 `accept()` 的返回值透传(accept 统一返回 `int | _LeConn`,BR 返回 int,LE 返回 _LeConn;`_build_link` 里取 handle)。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/mitm/test_session_le.py tests/unit/mitm/test_session.py tests/unit/mitm/test_session_bredr.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add pybluehost/cli/app/mitm/session.py tests/unit/mitm/test_session_le.py
git commit -m "feat(mitm): session LE 链路 — LE_Create_Connection + 真实地址 SMP + LTK 加密"
```

---

### Task 9: LE LTK 持久化(pairing/ltk_store.py)

**Files:**
- Create: `pybluehost/cli/app/mitm/pairing/ltk_store.py`
- Modify: `pybluehost/cli/app/mitm/session.py`(替换内存版 `_load_le_ltk/_save_le_ltk`)
- Test: `tests/unit/mitm/test_ltk_store.py`(新建)

- [ ] **Step 1: 写失败测试**

```python
"""LE LTK JSONL 持久化;与 SspTermination 的 link-key JSONL 同文件兼容。"""
import json

from pybluehost.cli.app.mitm.pairing.ltk_store import append_ltk, load_ltks


def test_append_then_load_roundtrip(tmp_path):
    path = tmp_path / "k.jsonl"
    append_ltk(path, side="phone", addr="AA:BB:CC:DD:EE:FF", ltk=b"\x11" * 16)
    append_ltk(path, side="target", addr="38:D5:18:CD:52:F7", ltk=b"\x22" * 16)
    ltks = load_ltks(path)
    assert ltks[("phone", "AA:BB:CC:DD:EE:FF")] == b"\x11" * 16
    assert ltks[("target", "38:D5:18:CD:52:F7")] == b"\x22" * 16


def test_load_mixed_file_ignores_ssp_link_key_records(tmp_path):
    """同一文件里 SspTermination 写的 link_key 记录不能让 load 抛错/混入。"""
    path = tmp_path / "k.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "t", "side": "phone", "addr": "AA:BB",
                            "link_key": "00" * 16, "key_type": 0x05}) + "\n")
        f.write(json.dumps({"type": "ltk", "side": "phone",
                            "addr": "AA:BB", "ltk": "11" * 16}) + "\n")
    ltks = load_ltks(path)
    assert ltks == {("phone", "AA:BB"): b"\x11" * 16}


def test_load_missing_and_corrupt(tmp_path):
    assert load_ltks(tmp_path / "nope.jsonl") == {}
    p = tmp_path / "bad.jsonl"
    p.write_text("garbage line\n", encoding="utf-8")
    assert load_ltks(p) == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/mitm/test_ltk_store.py -q`
Expected: FAIL(`ModuleNotFoundError: ltk_store`)

- [ ] **Step 3: 实现 ltk_store.py**

```python
"""LE LTK 的 JSONL 持久化(与 SspTermination 的 link-key 记录同一文件、按 type 区分)。"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def load_ltks(path: str | Path) -> dict:
    """读 (side, addr) → ltk;文件缺失/坏行/非 ltk 记录一律跳过。"""
    out: dict = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("type") != "ltk":
                        continue
                    out[(rec["side"], rec["addr"].upper())] = bytes.fromhex(rec["ltk"])
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        pass  # 首次运行文件不存在属正常
    return out


def append_ltk(path: str | Path, *, side: str, addr: str, ltk: bytes) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": "ltk",
        "side": side,
        "addr": addr.upper(),
        "ltk": ltk.hex(),
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as exc:
        logger.warning("session[le]: LTK 落盘失败 path=%s: %s", path, exc)
```

- [ ] **Step 4: session.py 替换内存版并接线**

`__init__` 加载:

```python
        self._ltks = load_ltks(key_log) if key_log else {}
```

替换两个占位为(按"该侧对端地址"查):

```python
    def _load_le_ltk(self, side: str, link: _LinkState) -> "bytes | None":
        peer7 = link.phone_peer7 if side == "phone" else link.target_peer7
        addr = ":".join(f"{b:02X}" for b in reversed(peer7[1:]))
        return self._ltks.get((side, addr))

    def _save_le_ltk(self, side: str, link: _LinkState, ltk: bytes) -> None:
        peer7 = link.phone_peer7 if side == "phone" else link.target_peer7
        addr = ":".join(f"{b:02X}" for b in reversed(peer7[1:]))
        self._ltks[(side, addr)] = ltk
        if self._key_log:
            append_ltk(self._key_log, side=side, addr=addr, ltk=ltk)
```

顶部 import:`from pybluehost.cli.app.mitm.pairing.ltk_store import append_ltk, load_ltks`。`_le_bring_up` 里 target 配对完成后,若 phone pairing 也已完成则一并 `self._save_le_ltk("phone", link, link.pairings["phone"].ltk)`。

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/unit/mitm/test_ltk_store.py tests/unit/mitm/test_session_le.py -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add pybluehost/cli/app/mitm/pairing/ltk_store.py pybluehost/cli/app/mitm/session.py tests/unit/mitm/test_ltk_store.py
git commit -m "feat(mitm): LE LTK JSONL 持久化(与 SSP key-log 同文件,type 区分)"
```

### Task 10: CLI 重写(scan/relay 子命令)+ cutover 删 orchestrator

**Files:**
- Modify: `pybluehost/cli/app/mitm/cli.py`(重写)、`pybluehost/cli/app/mitm/controllers.py`(加 `open_controller`)
- Modify: `scripts/mitm_traced.py`(MitmRelay→MitmSession)
- Delete: `pybluehost/cli/app/mitm/orchestrator.py`
- Delete: `tests/unit/mitm/test_orchestrator.py`、`test_orchestrator_bredr_accept.py`、`test_orchestrator_bredr_connect.py`、`test_orchestrator_bredr_disconnect.py`、`test_secure_target_link.py`
- Modify: `tests/unit/mitm/test_cli_main.py`、`tests/unit/mitm/test_cli_skeleton.py`、`tests/unit/mitm/__init__.py`(如引用被删符号)
- Modify: `AGENTS.md`(新增重构条目)

- [ ] **Step 1: controllers.py 追加单 controller 打开(scan 只用一只 dongle)**

```python
async def open_controller(spec: str):
    """打开并初始化一只 controller(scan 用);失败回滚已打开的 transport。"""
    t = await parse_transport_arg(spec)
    ctrl = HCIController(t)
    try:
        await t.open()
        await ctrl.initialize()
    except Exception:
        await _close_transport(t)
        raise
    return ctrl, t
```

(顶部已有 import 齐全;`_close_transport`/`parse_transport_arg`/`HCIController` 都在同文件已用。)

- [ ] **Step 2: cli.py 整体重写为 scan/relay 两个子命令**

```python
"""'app mitm' —— BLE/BR ACL 透传中间人(授权测试专用)。scan/relay 两步式。"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pybluehost.cli.app.mitm.pairing.delegate import PairingDelegate
    from pybluehost.cli.app.mitm.recon import ClonedIdentity, ScanEntry

logger = logging.getLogger(__name__)

IDENTITY_DEFAULT = "mitm-targets.json"
KEY_LOG_DEFAULT = "mitm-keys.jsonl"


def default_btsnoop_name() -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"mitm-{ts}.btsnoop"


def _select_delegate(pairing: str) -> "PairingDelegate":
    from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate
    # 授权 MITM 测试两端都是自己的设备;Interactive 读 stdin 会卡死自动化门。
    return AutoConfirmDelegate()


# ---- 身份 JSON(见 Task 5,原样保留:_section_from_identity/_identity_from_section/
# identity_save/identity_load/IDENTITY_DEFAULT) ----


def _print_entries(entries, label: str) -> None:
    print(f"\n=== {label} 扫描结果({len(entries)} 台)===")
    for i, e in enumerate(entries, 1):
        ident = e.identity
        rssi = f"{e.rssi:>4}" if e.rssi is not None else "   -"
        print(f"{i:>3}  {ident.address}  CoD={ident.class_of_device or 0:06X}"
              f"  RSSI={rssi}  {ident.name or '(名称未知)'}")


def _choose(entries) -> Optional["ScanEntry"]:
    """编号选择 / r 重扫(返回哨兵)/ q 整体退出。自动化(--target)不进这里。"""
    while True:
        raw = input("选择要复制的设备编号 / r 重扫 / q 退出: ").strip().lower()
        if raw == "q":
            raise SystemExit("用户退出,未保存。")
        if raw == "r":
            return "rescan"
        if raw.isdigit() and 1 <= int(raw) <= len(entries):
            return entries[int(raw) - 1]
        print("无效输入")


def _auto_pick(entries, args) -> Optional["ScanEntry"]:
    """--target/--target-name 自动化命中(地址不区分大小写);没命中返回 None。"""
    for e in entries:
        if args.target and e.identity.address.upper() == args.target.upper():
            return e
        if args.target_name and e.identity.name == args.target_name:
            return e
    return None


async def _scan_section(args, ctrl, mode: str) -> Optional["ClonedIdentity"]:
    """扫一段(bredr/le)并选定;返回身份,自动化未命中返回 None。

    交互式:r 重扫不限次;q 由 _choose 抛 SystemExit 结束整个 scan(不保存)。
    """
    from pybluehost.cli.app.mitm.bredr_recon import (
        fetch_remote_name,
        inquiry_scan_all,
    )
    from pybluehost.cli.app.mitm.recon import ble_scan_all

    label = "BR/EDR inquiry" if mode == "bredr" else "BLE adv"

    async def sweep():
        if mode == "bredr":
            return await inquiry_scan_all(ctrl, rounds=args.br_rounds)
        return await ble_scan_all(ctrl, window=args.le_window)

    while True:
        entries = await sweep()
        if not entries:
            print(f"({mode}) 未发现设备:让设备进配对模式/开盖,或换 --mode")
        _print_entries(entries, label)
        auto = _auto_pick(entries, args)
        if auto is not None:
            print(f"自动命中: {auto.identity.address}")
            ident = auto.identity
        elif args.target or args.target_name:
            return None  # 自动化模式没命中,不进交互
        else:
            pick = _choose(entries)
            if pick == "rescan":
                continue
            ident = pick.identity
            if mode == "bredr" and ident.name is None:
                ident.name = await fetch_remote_name(ctrl, ident.address)
                print(f"RNR 补名: {ident.name}")
        return ident


async def _scan_main(args: argparse.Namespace) -> None:
    from pybluehost.cli.app.mitm.controllers import open_controller

    logger.warning("⚠ MITM 仅限授权测试:确保你对目标设备有合法授权。")
    ctrl, transport = await open_controller(args.upstream)
    sections: dict = {}
    try:
        if args.mode in ("bredr", "both"):
            ident = await _scan_section(args, ctrl, "bredr")
            if ident is not None:
                sections["bredr"] = ident
        if args.mode in ("le", "both"):
            ident = await _scan_section(args, ctrl, "le")
            if ident is not None:
                sections["le"] = ident
    finally:
        await _close(transport)

    if not sections:
        print("没有选定任何设备,未保存。")
        return
    path = args.save or IDENTITY_DEFAULT
    identity_save(path, sections)
    print(f"已保存到 {path}: {sorted(sections)}")


async def _close(transport) -> None:
    from pybluehost.cli.app.mitm.controllers import _close_transport
    await _close_transport(transport)


def _inline_recon_identity(args, ctrl, mode: str) -> Optional["ClonedIdentity"]:
    """--target/--target-name 自动化路径:内联探测(90s 多轮预算)。"""
    if args.mode not in (mode, "both"):
        return None
    if mode == "bredr":
        from pybluehost.cli.app.mitm.bredr_recon import inquiry_for_target
        return asyncio.get_event_loop().run_until_complete(
            inquiry_for_target(ctrl, target_addr=args.target,
                               target_name=args.target_name))
    from pybluehost.cli.app.mitm.recon import scan_for_target
    return asyncio.get_event_loop().run_until_complete(
        scan_for_target(ctrl, target_addr=args.target, target_name=args.target_name))
```

**实现注意**:上面 `_inline_recon_identity` 用 run_until_complete 的写法是错的——`_relay_main` 是 async,直接 `await`:

```python
async def _inline_recon(args, ctrl, mode: str) -> Optional["ClonedIdentity"]:
    if args.mode not in (mode, "both") or not (args.target or args.target_name):
        return None
    if mode == "bredr":
        from pybluehost.cli.app.mitm.bredr_recon import inquiry_for_target
        return await inquiry_for_target(ctrl, target_addr=args.target,
                                        target_name=args.target_name)
    from pybluehost.cli.app.mitm.recon import scan_for_target
    return await scan_for_target(ctrl, target_addr=args.target,
                                 target_name=args.target_name)
```

```python
async def _relay_main(args: argparse.Namespace) -> None:
    from pybluehost.cli.app.mitm.controllers import open_controller_pair
    from pybluehost.cli.app.mitm.session import MitmSession
    from pybluehost.cli.app.mitm.transform import DEMO_RULES, RegexReplacer

    logger.warning("⚠ MITM 仅限授权测试:确保你对目标设备与手机均有合法授权。")
    identities = {"bredr": None, "le": None}

    # 身份来源二选一:identity JSON(默认)/ 内联 recon(--target/--target-name)
    if args.target or args.target_name:
        from pybluehost.cli.app.mitm.controllers import open_controller
        ctrl, transport = await open_controller(args.upstream)
        try:
            for mode in ("bredr", "le"):
                ident = await _inline_recon(args, ctrl, mode)
                if ident is not None:
                    identities[mode] = ident
        finally:
            await _close(transport)
    else:
        path = args.identity or IDENTITY_DEFAULT
        loaded = identity_load(path)
        if not loaded:
            raise SystemExit(
                f"身份文件 {path} 不存在或为空:先跑 `pybluehost app mitm scan`,"
                "或用 --target 指定目标。")
        identities.update(loaded)

    # --mode 过滤:both 全跑;单模式只保留对应段
    if args.mode == "bredr":
        identities["le"] = None
    elif args.mode == "le":
        identities["bredr"] = None

    pair = await open_controller_pair(args.upstream, args.downstream)
    btsnoop = args.btsnoop or default_btsnoop_name()
    session = MitmSession(
        pair,
        identities=identities,
        delegate=_select_delegate(args.pairing),
        numeric=(args.pairing == "numeric"),
        btsnoop=btsnoop,
        clone_address=args.clone_address,
        key_log=args.key_log or KEY_LOG_DEFAULT,
        name_override=args.downstream_name,
        transform=RegexReplacer(DEMO_RULES),
    )
    try:
        await session.run()
    finally:
        await session.teardown()


def register_mitm_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("mitm", help="BLE/BR ACL 透传中间人(授权测试专用)")
    sub = p.add_subparsers(dest="mitm_cmd", required=True)

    scan = sub.add_parser("scan", help="发现全部设备,列表选一个复制,存身份 JSON")
    scan.add_argument("--upstream", required=True, help="扫描用 transport")
    scan.add_argument("--mode", choices=["le", "bredr", "both"], default="both",
                      help="bredr→inquiry / le→adv scan / both→先 BR 后 LE")
    scan.add_argument("--save", help=f"身份 JSON 路径(默认 {IDENTITY_DEFAULT})")
    scan.add_argument("--target", help="自动化:直接按地址命中,不出列表")
    scan.add_argument("--target-name", help="自动化:按名字命中")
    scan.add_argument("--br-rounds", type=int, default=2,
                      help="BR inquiry 轮数(每轮 ~10.24s,默认 2)")
    scan.add_argument("--le-window", type=float, default=10.0, help="LE 扫描窗口秒")
    scan.set_defaults(func=lambda a: asyncio.run(_scan_main(a)))

    relay = sub.add_parser("relay", help="用身份 JSON 起中继(默认读 mitm-targets.json)")
    relay.add_argument("--upstream", required=True)
    relay.add_argument("--downstream", required=True)
    relay.add_argument("--mode", choices=["le", "bredr", "both"], default="both",
                       help="默认按身份文件内容全跑;可只跑一段")
    relay.add_argument("--identity", help=f"身份 JSON(默认 {IDENTITY_DEFAULT})")
    relay.add_argument("--target", help="无身份文件时的内联探测(地址)")
    relay.add_argument("--target-name", help="无身份文件时的内联探测(名字)")
    relay.add_argument("--key-log", help=f"link key/LTK JSONL(默认 {KEY_LOG_DEFAULT})")
    relay.add_argument("--btsnoop", help="btsnoop 输出(默认按时间戳)")
    relay.add_argument("--clone-address", action="store_true")
    relay.add_argument("--downstream-name", help="覆盖手机侧伪装名")
    relay.add_argument("--pairing", choices=["just-works", "numeric"],
                       default="just-works")
    relay.set_defaults(func=lambda a: asyncio.run(_relay_main(a)))
```

(`identity_save/identity_load` 在同文件 Task 5 已定义;`build_relays_from_args`/`RelaySpec` 删除。)

- [ ] **Step 3: 更新测试(test_cli_main / test_cli_skeleton)**

`test_cli_skeleton.py` 的 `test_register_mitm_command_adds_subparser` 改为:

```python
def test_register_mitm_command_adds_scan_and_relay():
    import argparse
    from pybluehost.cli.app.mitm.cli import register_mitm_command

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(required=True)
    register_mitm_command(sub)
    args = parser.parse_args(["mitm", "relay", "--upstream", "x", "--downstream", "y"])
    assert args.upstream == "x" and args.mode == "both"
    args2 = parser.parse_args(["mitm", "scan", "--upstream", "x"])
    assert args2.br_rounds == 2
```

`test_cli_main.py`:删 `test_both_mode_builds_le_and_bredr`/`test_le_mode_builds_one`(RelaySpec 已不存在),其余保留;新增:

```python
def test_key_log_default_is_stable_name():
    from pybluehost.cli.app.mitm.cli import KEY_LOG_DEFAULT
    assert KEY_LOG_DEFAULT == "mitm-keys.jsonl"  # 修时间戳默认 bug:跨重启可复用 key
```

- [ ] **Step 4: 删 orchestrator + 旧测试,更新 scripts/mitm_traced.py**

```bash
git rm pybluehost/cli/app/mitm/orchestrator.py \
       tests/unit/mitm/test_orchestrator.py \
       tests/unit/mitm/test_orchestrator_bredr_accept.py \
       tests/unit/mitm/test_orchestrator_bredr_connect.py \
       tests/unit/mitm/test_orchestrator_bredr_disconnect.py \
       tests/unit/mitm/test_secure_target_link.py
```

`scripts/mitm_traced.py` 的 `_main` 中继装配段改为(其余 trace/stats 逻辑不动):

```python
    from pybluehost.cli.app.mitm.session import MitmSession
    from pybluehost.cli.app.mitm.transform import DEMO_RULES, RegexReplacer

    identities: dict = {"bredr": None, "le": None}
    if args.transport_mode in ("bredr", "both"):
        from pybluehost.cli.app.mitm.bredr_recon import inquiry_for_target
        identities["bredr"] = await inquiry_for_target(
            pair.upstream, target_addr=args.target, target_name=None)
    if args.transport_mode in ("le", "both"):
        from pybluehost.cli.app.mitm.recon import scan_for_target
        identities["le"] = await scan_for_target(
            pair.upstream, target_addr=args.target, target_name=None)
    session = MitmSession(
        pair,
        identities=identities,
        delegate=_select_delegate(args.pairing),
        numeric=(args.pairing == "numeric"),
        btsnoop=(f"mitm-{ts}.btsnoop" if args.transport_mode != "both"
                 else None),  # 双链路共用一个 capture,btsnoop 只给单模式
        key_log=args.key_log,
        clone_address=args.clone_address,
        name_override=args.downstream_name,
        transform=RegexReplacer(DEMO_RULES),
    )
    try:
        stats_task = asyncio.ensure_future(
            _stats_reporter([session], phone_stats, earbud_stats,
                            pair.downstream, pair.upstream))
        try:
            await session.run()
        finally:
            stats_task.cancel()
    finally:
        await session.teardown()
        await earbud_trace.stop()
        await phone_trace.stop()
```

`_stats_reporter` 里 `all(r.connected.is_set() for r in relays)` 改 `relays[0].connected.is_set()`(传 `[session]`)。import 行删 `build_relays_from_args`(已不存在)。`--transport-mode` 的 choices 保留 `["le", "bredr", "both"]`,默认改 `both`(这是 traced 脚本,用户现跑 BR 时显式传)。

再 grep 兜底:

```bash
grep -rn "orchestrator\|MitmRelay\|build_relays_from_args\|RelaySpec" pybluehost scripts tests --include="*.py"
```
Expected: 无输出(全清)。

- [ ] **Step 5: 跑 mitm 全量测试**

Run: `python -m pytest tests/unit/mitm -q`
Expected: PASS(test_session* / transform / identity / scan_all / relay / acl / capture / controllers / pairing / cli 全绿;已删文件不出现)

- [ ] **Step 6: AGENTS.md 增加条目**

在 AGENTS.md 的 MITM 相关 Q&A 区追加:

```markdown
## Q: MITM 模块重构(session.py)后的结构?
A: orchestrator.py(1114 行 god-class)已删,改 `session.py` 的 MitmSession:
- 每 controller 的 set_upstream **唯一属主**:HCI 事件 subscribe/unsubscribe 多点订阅,
  ACL 按 handle 的 if/else 分发到各链路 AclRelay(prev-forward 链式 hook 从此不存在);
- BR 的 SspTermination 在 run() 启动段 attach(等手机之前,G3 时序);
- _run_link 一份骨架,LE/BR 各一个;两链独立重连互不联动;
- LE 补真:LE_Create_Connection、连接事件真实地址喂 SMP(f5/f6)、LTK JSONL 持久化;
- CLI 两步式:`mitm scan`(全发现+列表选设备→ mitm-targets.json,按段合并)
  → `mitm relay`(默认读 mitm-targets.json / mitm-keys.jsonl,秒起);
- transform:transform.py 的 DEMO_RULES 正则替换(用户改规则),AclRelay 唯一新增钩子。
设计稿:docs/superpowers/specs/2026-09-03-mitm-redesign-design.md
```

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "refactor(mitm)!: CLI 重写为 scan/relay 子命令 + 删 orchestrator 改 session

- cli.py:scan(全发现+列表选设备+按段合并存 JSON)/ relay(identity 默认秒起)
- 默认值固定:mitm-targets.json / mitm-keys.jsonl(修时间戳 key-log 重连零配对 bug)
- controllers.open_controller(scan 单 dongle)
- scripts/mitm_traced.py 适配 MitmSession
- BREAKING: 旧 'app mitm' 单命令移除,分 scan/relay 子命令"
```

---

### Task 11: 全量回归 + 硬件验证清单

**Files:** 无新代码;验证 + 文档。

- [ ] **Step 1: 整仓测试**

Run: `python -m pytest -q`
Expected: 全绿(含 437+ 既有;mitm 新增约 45 个)

- [ ] **Step 2: 架构硬规则检查**

```bash
grep -rn "from pybluehost.\(l2cap\|ble\|classic\|gap\|profiles\|stack\)" pybluehost/cli/app/mitm --include="*.py"
grep -rn "hci/controller.py" pybluehost/cli/app/mitm --include="*.py" | grep import
git diff master --stat -- pybluehost/hci/controller.py
```
Expected: 前两条无输出;第三条无 diff(controller.py 未动)。

- [ ] **Step 3: 提交(如有遗漏文件)**

```bash
git status --short   # 应干净
```

- [ ] **Step 4: 硬件回归(人工,用户操作;按顺序)**

1. **scan**:`pybluehost app mitm scan --upstream usb:8087:0036#N --mode both` — 列表出设备、选耳机、RNR 补名、JSON 落盘。
2. **BR golden**:`pybluehost app mitm relay --upstream ... --downstream ... --mode bredr` — 手机连上、A2DP 播 5 分钟无声、音量快跳无卡顿、断开重连零配对、`relay 未连接`/双 dongle OK 后 Ctrl-C 退出无楔死。
3. **LE 单链路**:`--mode le` — 手机连 LE 广播、GATT 可用、重连走持久化 LTK。
4. **双链路**:默认 `--mode both` — 音频(BR)+ 控制(LE)同跑,断 LE 不影响音频。
5. **transform**:在 `transform.py` 打开一条 demo 规则,btsnoop 里确认替换生效且 L2CAP 长度头正确。

任何一步失败 → 按 AGENTS.md 无声三根因 + systematic-debugging 流程排查;dongle 楔死只能拔插。

---

## Plan 自查(写完计划后已过一遍)

**Spec 覆盖对照**:双链路同对 dongle(T6-T8)、单命令 relay(T10)、两链独立(T6 `_run_link`)、if/else 分发(T6)、BR SSP 启动段 attach 时序(T6 run())、f382b1e 三纪律(T7:secure link/tracker/scan-reopen;prev-forward 收敛于订阅制)、LE 补真(T8)、LTK 持久化(T9)、transform(T1-T2)、scan-all+RNR(T3-T4)、身份 JSON 按段合并(T5)、CLI 默认值/时间戳 bug 修复(T10)、scan 重扫交互(T10 `_choose` 的 r 分支)、硬件回归(T11)。设计稿"两连窗口丢包与现状一致"——session 行为同现状(建链后才挂 ACL 路由),无需专门任务。

**Placeholder 扫描**:Task 6 的 accept/connect 占位是显式 `NotImplementedError`(Task 7/8 落地),非 TBD;无其它占位。

**类型一致性**:`_LinkState` 字段(phone_handle/earbud_handle/relay/link_lost/pairings/drain_tasks/watches/4×addr7/smp_queues)在 T6 定义、T7/T8 使用一致;`_accept_*_on`/`_connect_*_on`/`_secure_target_link_on`/`_graceful_disconnect_on` 命名与测试移植配方一致;`ScanEntry.identity/.rssi` T3/T4/T10 一致;`identity_save/identity_load` T5/T10 一致。





