# MITM-1: 应用骨架 + ACL Relay 核心 + Capture 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 搭出 MITM 透传应用的骨架（独立于协议栈，仅复用 `transport` + `hci`），并实现 B 式 HCI-ACL 透传的纯逻辑核心：L2CAP PDU 重组、按 CID 分流、跨 buffer 重分片、btsnoop 抓包 tap。

**Architecture:** MITM 是 `pybluehost/cli/app/mitm/` 下的独立应用，**不导入** l2cap/ble/classic/gap/profiles/stack。本 Plan 只做可独立单测的纯逻辑单元（重组器 `L2capReassembler`、分片器 `fragment`、CID 分流 `classify`、中继器 `AclRelay`、抓包 `BtsnoopCaptureTap`）+ CLI 骨架（构造两个 `HCIController`）。真正的 recon/impersonate/配对在 MITM-2/3。

**Tech Stack:** Python 3.10+ asyncio、pytest（`asyncio_mode=auto`）、`pybluehost.hci.packets.HCIACLData`、`pybluehost.hci.controller.HCIController`、`pybluehost.core.trace.BtsnoopSink`。

**依赖前提（已在 spec §2 核准）：** `HCIController` 只 import `core`/`hci`，不牵出上层；`send_acl_data(handle, pb_flag, data)`；buffer 属性 `acl_packet_length` / `le_acl_packet_length`；`HCIACLData(handle, pb_flag, bc_flag, data)` 有 `.to_bytes()`。

---

## File Structure

| 文件 | 职责 |
|------|------|
| `pybluehost/cli/app/mitm/__init__.py` | 包标记 + 导出公共符号 |
| `pybluehost/cli/app/mitm/acl.py` | PB flag 常量、`RelayDirection`、`CidAction`/`classify`、`encode_l2cap_basic`、`L2capReassembler`、`fragment` |
| `pybluehost/cli/app/mitm/capture.py` | `CaptureTap` 协议、`NullTap`、`BtsnoopCaptureTap` |
| `pybluehost/cli/app/mitm/relay.py` | `RelaySide`、`AclRelay`（重组→分流→抓包→重分片→断链传播 hook） |
| `pybluehost/cli/app/mitm/cli.py` | `register_mitm_command` + `_mitm_main` 骨架（构造两个 HCIController） |
| `tests/unit/mitm/test_acl.py` | 重组器/分片器/分流单测 |
| `tests/unit/mitm/test_capture.py` | btsnoop tap 单测 |
| `tests/unit/mitm/test_relay.py` | AclRelay 单测（用 fake side） |
| `tests/unit/mitm/test_cli_skeleton.py` | CLI 骨架构造两个 controller（virtual transport） |

---

## Task 1: 应用包骨架 + 子命令注册

**Files:**
- Create: `pybluehost/cli/app/mitm/__init__.py`
- Create: `pybluehost/cli/app/mitm/cli.py`
- Modify: `pybluehost/cli/app/__init__.py`
- Test: `tests/unit/mitm/test_cli_skeleton.py`

- [x] **Step 1: 写失败测试 —— 子命令已注册**

Create `tests/unit/mitm/test_cli_skeleton.py`:

```python
import argparse

from pybluehost.cli.app.mitm.cli import register_mitm_command


def test_register_mitm_command_adds_subparser():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_mitm_command(subs)
    args = parser.parse_args(
        ["mitm", "--upstream", "virtual", "--downstream", "virtual"]
    )
    assert args.cmd == "mitm"
    assert args.upstream == "virtual"
    assert args.downstream == "virtual"
    assert args.transport_mode == "both"  # 默认值
```

- [x] **Step 2: 运行测试，确认失败**

Run: `uv run pytest tests/unit/mitm/test_cli_skeleton.py -v`
Expected: FAIL — `ModuleNotFoundError: pybluehost.cli.app.mitm`

- [x] **Step 3: 写 `__init__.py` 与 `cli.py` 骨架**

Create `pybluehost/cli/app/mitm/__init__.py`:

```python
"""MITM 透传应用 —— 独立应用,仅复用 transport + hci,不导入协议栈上层。"""
```

Create `pybluehost/cli/app/mitm/cli.py`:

```python
"""'app mitm' —— 目标设备与手机之间的 BLE/BR ACL 透传中间人(授权测试专用)。"""
from __future__ import annotations

import argparse
import asyncio
import logging

logger = logging.getLogger(__name__)


def register_mitm_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "mitm",
        help="BLE/BR ACL 透传中间人(授权测试专用)",
    )
    p.add_argument("--upstream", required=True, help="连目标侧 transport (如 usb:vendor=intel)")
    p.add_argument("--downstream", required=True, help="对手机伪装侧 transport (如 usb:index=1)")
    p.add_argument("--target", help="目标地址 AA:BB:.. (或用 --target-name)")
    p.add_argument("--target-name", help="按名字匹配目标")
    p.add_argument(
        "--transport-mode",
        choices=["le", "bredr", "both"],
        default="both",
        help="透传哪种链路(默认 both)",
    )
    p.add_argument("--clone-address", action="store_true", help="套用目标地址(BR 需可写芯片)")
    p.add_argument("--btsnoop", help="btsnoop 输出路径(默认按时间戳命名)")
    p.add_argument(
        "--pairing", choices=["just-works", "numeric"], default="just-works"
    )
    p.set_defaults(func=lambda args: asyncio.run(_mitm_main(args)))


async def _mitm_main(args: argparse.Namespace) -> None:
    # MITM-1 仅骨架:真正的 recon/impersonate/relay 在 MITM-2/3。
    raise NotImplementedError("MITM relay 编排在 MITM-2/3 实现")
```

- [x] **Step 4: 运行测试，确认通过**

Run: `uv run pytest tests/unit/mitm/test_cli_skeleton.py -v`
Expected: PASS

- [x] **Step 5: 注册到 app 命令组**

Modify `pybluehost/cli/app/__init__.py` —— 在其它 `register_*` 调用之后追加：

```python
    from pybluehost.cli.app.mitm.cli import register_mitm_command
    register_mitm_command(app_subs)
```

- [x] **Step 6: 验证 CLI 可见**

Run: `uv run pybluehost app mitm --help`
Expected: 打印 mitm 帮助，含 `--upstream` / `--downstream` / `--transport-mode`

- [x] **Step 7: Commit**

```bash
git add pybluehost/cli/app/mitm/ pybluehost/cli/app/__init__.py tests/unit/mitm/test_cli_skeleton.py
git commit -m "feat(mitm): app 包骨架 + mitm 子命令注册"
```

---

## Task 2: ACL 常量 + L2CAP 基本帧编码 + CID 分流

**Files:**
- Create: `pybluehost/cli/app/mitm/acl.py`
- Test: `tests/unit/mitm/test_acl.py`

- [x] **Step 1: 写失败测试**

Create `tests/unit/mitm/test_acl.py`:

```python
from pybluehost.cli.app.mitm.acl import (
    CID_ATT,
    CID_SMP,
    CidAction,
    classify,
    encode_l2cap_basic,
)


def test_encode_l2cap_basic():
    # ATT Read Request (opcode 0x0A, handle 0x0003) over CID 0x0004
    pdu = encode_l2cap_basic(CID_ATT, bytes([0x0A, 0x03, 0x00]))
    # 长度(3) little-endian + CID(0x0004) little-endian + payload
    assert pdu == bytes([0x03, 0x00, 0x04, 0x00, 0x0A, 0x03, 0x00])


def test_classify_smp_is_terminate():
    assert classify(CID_SMP) is CidAction.TERMINATE_SMP


def test_classify_att_is_relay():
    assert classify(CID_ATT) is CidAction.RELAY


def test_classify_signaling_is_relay():
    assert classify(0x0001) is CidAction.RELAY  # BR signaling 也透明转发
    assert classify(0x0005) is CidAction.RELAY  # LE signaling
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/unit/mitm/test_acl.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError`

- [x] **Step 3: 写实现**

Create `pybluehost/cli/app/mitm/acl.py`:

```python
"""HCI ACL 透传核心:L2CAP PDU 重组、CID 分流、跨 buffer 重分片。

本模块只认 HCI 分片边界 + L2CAP basic header(2 字节 length + 2 字节 CID),
与 BLE/BR 无关,故两种 transport 共用。
"""
from __future__ import annotations

import struct
from enum import Enum, auto

from pybluehost.hci.packets import HCIACLData

# HCI ACL Packet Boundary flags (Core Vol4 Part E §5.4.2)
PB_FIRST_NON_FLUSH = 0x00  # host→controller 首片(非自动 flush)
PB_CONTINUATION = 0x01     # 续片
PB_FIRST_FLUSH = 0x02      # 首片(自动 flush;接收方向常见)

# 固定 CID
CID_BR_SIGNALING = 0x0001
CID_ATT = 0x0004
CID_LE_SIGNALING = 0x0005
CID_SMP = 0x0006


class RelayDirection(Enum):
    PHONE_TO_TARGET = "phone→target"
    TARGET_TO_PHONE = "target→phone"


class CidAction(Enum):
    RELAY = auto()          # 透明转发(ATT/动态/signaling)
    TERMINATE_SMP = auto()  # 本地终结(BLE SMP, MITM-2 接管)


def classify(cid: int) -> CidAction:
    """决定一个 L2CAP CID 是本地终结还是透明转发。"""
    if cid == CID_SMP:
        return CidAction.TERMINATE_SMP
    return CidAction.RELAY


def encode_l2cap_basic(cid: int, payload: bytes) -> bytes:
    """把 (cid, payload) 编成 L2CAP basic header 帧。"""
    return struct.pack("<HH", len(payload), cid) + payload
```

- [x] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/unit/mitm/test_acl.py -v`
Expected: PASS（4 个测试）

- [x] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/acl.py tests/unit/mitm/test_acl.py
git commit -m "feat(mitm): ACL 常量 + L2CAP basic 编码 + CID 分流"
```

---

## Task 3: L2CAP 重组器（HCI 分片 → 完整 PDU）

**Files:**
- Modify: `pybluehost/cli/app/mitm/acl.py`
- Test: `tests/unit/mitm/test_acl.py`

- [x] **Step 1: 追加失败测试**

Append to `tests/unit/mitm/test_acl.py`:

```python
from pybluehost.cli.app.mitm.acl import (  # noqa: E402  (追加 import)
    PB_CONTINUATION,
    PB_FIRST_FLUSH,
    L2capReassembler,
)
from pybluehost.hci.packets import HCIACLData  # noqa: E402


def test_reassembler_single_complete_pdu():
    r = L2capReassembler()
    # 完整 ATT PDU 在一个 ACL 片里:len=3, cid=4, payload=0A 03 00
    acl = HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH,
                     data=bytes([0x03, 0x00, 0x04, 0x00, 0x0A, 0x03, 0x00]))
    out = r.feed(acl)
    assert out == [(0x0004, bytes([0x0A, 0x03, 0x00]))]


def test_reassembler_fragmented_pdu():
    r = L2capReassembler()
    # payload 5 字节,分两片:首片含 header+前2字节,续片含后3字节
    first = HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH,
                       data=bytes([0x05, 0x00, 0x04, 0x00, 0xAA, 0xBB]))
    cont = HCIACLData(handle=0x40, pb_flag=PB_CONTINUATION,
                      data=bytes([0xCC, 0xDD, 0xEE]))
    assert r.feed(first) == []           # 还不完整
    assert r.feed(cont) == [(0x0004, bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE]))]


def test_reassembler_two_pdus_in_one_fragment():
    r = L2capReassembler()
    # 两个背靠背 PDU 在一个 ACL 片里
    pdu1 = bytes([0x01, 0x00, 0x04, 0x00, 0xAA])
    pdu2 = bytes([0x02, 0x00, 0x06, 0x00, 0xBB, 0xCC])
    acl = HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=pdu1 + pdu2)
    assert r.feed(acl) == [(0x0004, bytes([0xAA])), (0x0006, bytes([0xBB, 0xCC]))]
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/unit/mitm/test_acl.py -k reassembler -v`
Expected: FAIL — `ImportError: cannot import name 'L2capReassembler'`

- [x] **Step 3: 写实现 —— 追加到 `acl.py`**

```python
class L2capReassembler:
    """单方向 HCI ACL 分片 → 完整 L2CAP PDU 重组。

    用法:每个连接方向一个实例;按 PB flag 累积,剥出所有完整 PDU。
    续片(PB_CONTINUATION)追加到缓冲;非续片视为新消息的开始(覆盖缓冲)。
    """

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, acl: HCIACLData) -> list[tuple[int, bytes]]:
        if acl.pb_flag == PB_CONTINUATION:
            self._buf += acl.data
        else:
            self._buf = acl.data

        out: list[tuple[int, bytes]] = []
        while len(self._buf) >= 4:
            length = struct.unpack_from("<H", self._buf, 0)[0]
            total = 4 + length
            if len(self._buf) < total:
                break
            cid = struct.unpack_from("<H", self._buf, 2)[0]
            out.append((cid, self._buf[4:total]))
            self._buf = self._buf[total:]
        return out
```

- [x] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/unit/mitm/test_acl.py -k reassembler -v`
Expected: PASS（3 个）

- [x] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/acl.py tests/unit/mitm/test_acl.py
git commit -m "feat(mitm): L2capReassembler —— HCI 分片重组为完整 PDU"
```

---

## Task 4: 重分片器（PDU → 适配对侧 buffer 的 HCI 分片）

**Files:**
- Modify: `pybluehost/cli/app/mitm/acl.py`
- Test: `tests/unit/mitm/test_acl.py`

- [x] **Step 1: 追加失败测试**

Append to `tests/unit/mitm/test_acl.py`:

```python
from pybluehost.cli.app.mitm.acl import fragment  # noqa: E402


def test_fragment_fits_in_one():
    pdu = bytes([0x03, 0x00, 0x04, 0x00, 0x0A, 0x03, 0x00])  # 7 字节
    frags = fragment(handle=0x40, l2cap_pdu=pdu, max_payload=27)
    assert len(frags) == 1
    assert frags[0].handle == 0x40
    assert frags[0].pb_flag == 0x00  # PB_FIRST_NON_FLUSH
    assert frags[0].data == pdu


def test_fragment_splits_across_buffer():
    pdu = bytes(range(10))  # 0..9
    frags = fragment(handle=0x12, l2cap_pdu=pdu, max_payload=4)
    assert [f.data for f in frags] == [
        bytes([0, 1, 2, 3]),
        bytes([4, 5, 6, 7]),
        bytes([8, 9]),
    ]
    assert frags[0].pb_flag == 0x00          # 首片
    assert all(f.pb_flag == 0x01 for f in frags[1:])  # 续片
    assert all(f.handle == 0x12 for f in frags)


def test_fragment_rejects_zero_buffer():
    import pytest
    with pytest.raises(ValueError):
        fragment(handle=0x1, l2cap_pdu=b"\x00", max_payload=0)
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/unit/mitm/test_acl.py -k fragment -v`
Expected: FAIL — `ImportError: cannot import name 'fragment'`

- [x] **Step 3: 写实现 —— 追加到 `acl.py`**

```python
def fragment(
    *, handle: int, l2cap_pdu: bytes, max_payload: int,
    first_pb: int = PB_FIRST_NON_FLUSH,
) -> list[HCIACLData]:
    """把完整 L2CAP PDU 按 max_payload 切成 HCI ACL 分片。

    首片用 first_pb,其余用 PB_CONTINUATION。max_payload 取对侧控制器的
    acl_packet_length / le_acl_packet_length。
    """
    if max_payload <= 0:
        raise ValueError("max_payload 必须 > 0")
    frags = [
        HCIACLData(handle=handle, pb_flag=first_pb, data=l2cap_pdu[:max_payload])
    ]
    rest = l2cap_pdu[max_payload:]
    while rest:
        frags.append(
            HCIACLData(handle=handle, pb_flag=PB_CONTINUATION, data=rest[:max_payload])
        )
        rest = rest[max_payload:]
    return frags
```

- [x] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/unit/mitm/test_acl.py -v`
Expected: PASS（全部 acl 测试）

- [x] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/acl.py tests/unit/mitm/test_acl.py
git commit -m "feat(mitm): fragment —— PDU 重分片适配对侧 buffer"
```

---

## Task 5: Capture tap（btsnoop 抓包）

**Files:**
- Create: `pybluehost/cli/app/mitm/capture.py`
- Test: `tests/unit/mitm/test_capture.py`

- [x] **Step 1: 写失败测试**

Create `tests/unit/mitm/test_capture.py`:

```python
from pathlib import Path

from pybluehost.cli.app.mitm.acl import RelayDirection
from pybluehost.cli.app.mitm.capture import BtsnoopCaptureTap, NullTap


async def test_null_tap_is_noop():
    tap = NullTap()
    await tap.on_pdu(RelayDirection.PHONE_TO_TARGET, 0x40, b"\x00\x01")
    await tap.close()  # 不抛异常即可


async def test_btsnoop_tap_writes_records(tmp_path: Path):
    path = tmp_path / "cap.btsnoop"
    tap = BtsnoopCaptureTap(path)
    await tap.on_pdu(RelayDirection.TARGET_TO_PHONE, 0x40,
                     bytes([0x03, 0x00, 0x04, 0x00, 0x0A, 0x03, 0x00]))
    await tap.close()

    raw = path.read_bytes()
    assert raw.startswith(b"btsnoop\x00")        # 文件头
    assert len(raw) > 16                          # 头之外有记录
    assert bytes([0x0A, 0x03, 0x00]) in raw       # ATT payload 落盘
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/unit/mitm/test_capture.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: 写实现**

Create `pybluehost/cli/app/mitm/capture.py`:

```python
"""抓包 tap:把被中继的 L2CAP PDU 写进 btsnoop(v1 只观测,不改写)。

复用 core.trace.BtsnoopSink(纯 btsnoop 文件写入器,非协议逻辑)。
未来改写阶段在此 tap 点替换为 InterceptionPipeline。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from pybluehost.cli.app.mitm.acl import PB_FIRST_FLUSH, RelayDirection
from pybluehost.core.trace import BtsnoopSink, Direction, TraceEvent
from pybluehost.hci.packets import HCIACLData


class CaptureTap(Protocol):
    async def on_pdu(self, direction: RelayDirection, handle: int, l2cap_pdu: bytes) -> None: ...
    async def close(self) -> None: ...


class NullTap:
    """不抓包。"""

    async def on_pdu(self, direction: RelayDirection, handle: int, l2cap_pdu: bytes) -> None:
        return None

    async def close(self) -> None:
        return None


class BtsnoopCaptureTap:
    """把每条中继 PDU 重新包成 HCI ACL 记录写入 btsnoop。"""

    def __init__(self, path: str | Path) -> None:
        self._sink = BtsnoopSink(path)

    async def on_pdu(self, direction: RelayDirection, handle: int, l2cap_pdu: bytes) -> None:
        acl = HCIACLData(handle=handle, pb_flag=PB_FIRST_FLUSH, data=l2cap_pdu)
        now = datetime.now(timezone.utc)
        # 方向映射:target→phone 记为 UP(host←controller),phone→target 记为 DOWN。
        bt_dir = (
            Direction.UP
            if direction is RelayDirection.TARGET_TO_PHONE
            else Direction.DOWN
        )
        event = TraceEvent(
            timestamp=now.timestamp(),
            wall_clock=now,
            source_layer="hci",  # BtsnoopSink 只记 transport/hci 层
            direction=bt_dir,
            raw_bytes=acl.to_bytes(),
            decoded=None,
            connection_handle=handle,
            metadata={"mitm_direction": direction.value},
        )
        await self._sink.on_trace(event)

    async def close(self) -> None:
        await self._sink.close()
```

- [x] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/unit/mitm/test_capture.py -v`
Expected: PASS（2 个）

- [x] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/capture.py tests/unit/mitm/test_capture.py
git commit -m "feat(mitm): BtsnoopCaptureTap —— 中继 PDU 写入 btsnoop"
```

---

## Task 6: AclRelay（重组 → 分流 → 抓包 → 重分片 → SMP hook）

**Files:**
- Create: `pybluehost/cli/app/mitm/relay.py`
- Test: `tests/unit/mitm/test_relay.py`

- [x] **Step 1: 写失败测试**

Create `tests/unit/mitm/test_relay.py`:

```python
from pybluehost.cli.app.mitm.acl import (
    CID_ATT,
    CID_SMP,
    PB_FIRST_FLUSH,
    RelayDirection,
)
from pybluehost.cli.app.mitm.relay import AclRelay, RelaySide
from pybluehost.hci.packets import HCIACLData


def _make_side(name, handle, max_payload):
    sent = []

    async def send_acl(h, pb, data):
        sent.append((h, pb, data))

    side = RelaySide(name=name, handle=handle, acl_max_payload=max_payload, send_acl=send_acl)
    return side, sent


async def test_att_pdu_relayed_to_peer():
    phone, phone_sent = _make_side("phone", 0x40, 27)
    target, target_sent = _make_side("target", 0x11, 27)
    relay = AclRelay(phone_side=phone, target_side=target)

    # 手机侧收到一条完整 ATT PDU
    acl = HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH,
                     data=bytes([0x03, 0x00, 0x04, 0x00, 0x0A, 0x03, 0x00]))
    await relay.on_phone_acl(acl)

    # 应原样转发到 target 侧(用 target 的 handle)
    assert len(target_sent) == 1
    h, pb, data = target_sent[0]
    assert h == 0x11
    assert data == bytes([0x03, 0x00, 0x04, 0x00, 0x0A, 0x03, 0x00])
    assert phone_sent == []  # 不回送源侧


async def test_relay_refragments_for_small_peer_buffer():
    phone, _ = _make_side("phone", 0x40, 27)
    target, target_sent = _make_side("target", 0x11, 4)  # 对侧 buffer 很小
    relay = AclRelay(phone_side=phone, target_side=target)

    # 9 字节 payload 的 PDU(总长 4+9=13)
    payload = bytes(range(9))
    pdu = bytes([0x09, 0x00, 0x04, 0x00]) + payload
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=pdu))

    # 13 字节按 max_payload=4 切成 4 片
    assert len(target_sent) == 4
    assert b"".join(d for _, _, d in target_sent) == pdu
    assert target_sent[0][1] == 0x00                       # 首片
    assert all(pb == 0x01 for _, pb, _ in target_sent[1:])  # 续片


async def test_smp_cid_terminated_not_relayed():
    phone, phone_sent = _make_side("phone", 0x40, 27)
    target, target_sent = _make_side("target", 0x11, 27)
    seen = []

    async def smp_handler(side_name, cid, payload):
        seen.append((side_name, cid, payload))

    relay = AclRelay(phone_side=phone, target_side=target, smp_handler=smp_handler)

    # SMP PDU(CID 0x06)
    smp = bytes([0x01, 0x00, 0x06, 0x00, 0x01])  # len=1, cid=6, payload=01
    await relay.on_phone_acl(HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=smp))

    assert target_sent == []                 # 不转发
    assert seen == [("phone", CID_SMP, bytes([0x01]))]


async def test_disconnect_hook_invoked():
    phone, _ = _make_side("phone", 0x40, 27)
    target, _ = _make_side("target", 0x11, 27)
    closed = []
    relay = AclRelay(phone_side=phone, target_side=target,
                     on_teardown=lambda: closed.append(True))
    await relay.teardown()
    assert closed == [True]
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/unit/mitm/test_relay.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: 写实现**

Create `pybluehost/cli/app/mitm/relay.py`:

```python
"""AclRelay —— B 式 HCI-ACL 双向透传的中继器。

每侧(phone/target)一个 RelaySide,持有 send 回调、对侧 buffer 大小、重组器。
on_*_acl 收到 HCIACLData → 重组成 PDU → 按 CID 分流:
  TERMINATE_SMP → 交 smp_handler(MITM-2 接管);
  RELAY → 抓包 → 按对侧 buffer 重分片 → 对侧 send_acl。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pybluehost.cli.app.mitm.acl import (
    CidAction,
    L2capReassembler,
    RelayDirection,
    classify,
    encode_l2cap_basic,
    fragment,
)
from pybluehost.cli.app.mitm.capture import CaptureTap, NullTap
from pybluehost.hci.packets import HCIACLData

SendAcl = Callable[[int, int, bytes], Awaitable[None]]
SmpHandler = Callable[[str, int, bytes], Awaitable[None]]


@dataclass
class RelaySide:
    name: str
    handle: int
    acl_max_payload: int
    send_acl: SendAcl
    reassembler: L2capReassembler = field(default_factory=L2capReassembler)


class AclRelay:
    def __init__(
        self,
        *,
        phone_side: RelaySide,
        target_side: RelaySide,
        capture: CaptureTap | None = None,
        smp_handler: SmpHandler | None = None,
        on_teardown: Callable[[], None] | None = None,
    ) -> None:
        self._phone = phone_side
        self._target = target_side
        self._capture = capture or NullTap()
        self._smp_handler = smp_handler
        self._on_teardown = on_teardown

    async def on_phone_acl(self, acl: HCIACLData) -> None:
        await self._handle(self._phone, self._target, RelayDirection.PHONE_TO_TARGET, acl)

    async def on_target_acl(self, acl: HCIACLData) -> None:
        await self._handle(self._target, self._phone, RelayDirection.TARGET_TO_PHONE, acl)

    async def _handle(
        self, src: RelaySide, dst: RelaySide, direction: RelayDirection, acl: HCIACLData
    ) -> None:
        for cid, payload in src.reassembler.feed(acl):
            if classify(cid) is CidAction.TERMINATE_SMP:
                if self._smp_handler is not None:
                    await self._smp_handler(src.name, cid, payload)
                continue
            pdu = encode_l2cap_basic(cid, payload)
            await self._capture.on_pdu(direction, dst.handle, pdu)
            for frag in fragment(
                handle=dst.handle, l2cap_pdu=pdu, max_payload=dst.acl_max_payload
            ):
                await dst.send_acl(frag.handle, frag.pb_flag, frag.data)

    async def teardown(self) -> None:
        if self._on_teardown is not None:
            self._on_teardown()
        await self._capture.close()
```

- [x] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/unit/mitm/test_relay.py -v`
Expected: PASS（4 个）

- [x] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/relay.py tests/unit/mitm/test_relay.py
git commit -m "feat(mitm): AclRelay —— 双向重组/分流/抓包/重分片 + teardown hook"
```

---

## Task 7: CLI 骨架 —— 构造两个 HCIController 并接好 relay 接线

**Files:**
- Modify: `pybluehost/cli/app/mitm/cli.py`
- Create: `pybluehost/cli/app/mitm/controllers.py`
- Test: `tests/unit/mitm/test_cli_skeleton.py`

- [x] **Step 1: 追加失败测试 —— 从两个 transport 构造并初始化两个 controller**

Append to `tests/unit/mitm/test_cli_skeleton.py`:

```python
import pytest

from pybluehost.cli.app.mitm.controllers import open_controller_pair


@pytest.mark.asyncio
async def test_open_controller_pair_virtual():
    pair = await open_controller_pair("virtual", "virtual")
    try:
        assert pair.upstream is not None
        assert pair.downstream is not None
        # initialize() 后 buffer 大小可读(VirtualController 会给默认值)
        assert pair.downstream.le_acl_packet_length is not None or \
               pair.downstream.acl_packet_length is not None
    finally:
        await pair.close()
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/unit/mitm/test_cli_skeleton.py -k controller_pair -v`
Expected: FAIL — `ModuleNotFoundError: ...mitm.controllers`

- [x] **Step 3: 写实现 —— `controllers.py`**

Create `pybluehost/cli/app/mitm/controllers.py`:

```python
"""从两个 transport 字符串构造并初始化上下游 HCIController(仅 hci+transport)。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pybluehost.cli._transport import parse_transport_arg
from pybluehost.hci.controller import HCIController


@dataclass
class ControllerPair:
    upstream: HCIController
    downstream: HCIController
    _transports: tuple[object, object]

    async def close(self) -> None:
        for t in self._transports:
            close = getattr(t, "close", None)
            if close is not None:
                res = close()
                if asyncio.iscoroutine(res):
                    await res


async def open_controller_pair(upstream: str, downstream: str) -> ControllerPair:
    up_t = await parse_transport_arg(upstream)
    down_t = await parse_transport_arg(downstream)
    up = HCIController(up_t)
    down = HCIController(down_t)
    await up_t.open()
    await down_t.open()
    await asyncio.gather(up.initialize(), down.initialize())
    return ControllerPair(upstream=up, downstream=down, _transports=(up_t, down_t))
```

- [x] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/unit/mitm/test_cli_skeleton.py -k controller_pair -v`
Expected: PASS

- [x] **Step 5: 把 `_mitm_main` 接到 controller pair(骨架仍停在 recon 前)**

Replace `_mitm_main` in `pybluehost/cli/app/mitm/cli.py`:

```python
async def _mitm_main(args: argparse.Namespace) -> None:
    from pybluehost.cli.app.mitm.controllers import open_controller_pair

    pair = await open_controller_pair(args.upstream, args.downstream)
    try:
        logger.info(
            "MITM controllers ready (upstream + downstream). "
            "recon/impersonate/relay 在 MITM-2/3 接入。"
        )
        # MITM-2/3 在此装配 recon → impersonate → AclRelay。
        raise NotImplementedError("MITM relay 编排在 MITM-2/3 实现")
    finally:
        await pair.close()
```

- [x] **Step 6: 运行全套 mitm 单测**

Run: `uv run pytest tests/unit/mitm/ -v`
Expected: PASS（全部）

- [x] **Step 7: Commit**

```bash
git add pybluehost/cli/app/mitm/controllers.py pybluehost/cli/app/mitm/cli.py tests/unit/mitm/test_cli_skeleton.py
git commit -m "feat(mitm): open_controller_pair —— 双 HCIController 构造 + CLI 接线"
```

---

## Task 8: 收尾 —— 全套测试 + STATUS.md 登记

**Files:**
- Modify: `docs/superpowers/STATUS.md`
- Modify: 本 Plan 文档（勾选 checkbox）

- [x] **Step 1: 跑全套测试，确认无回归**

Run: `uv run pytest tests/ -q`
Expected: 全部 PASS（mitm 新增测试在内；协议栈测试不受影响——本 Plan 未改任何协议栈文件）

- [x] **Step 2: 确认未碰协议栈层**

Run: `git diff --name-only $(git merge-base HEAD master)..HEAD | grep -E "pybluehost/(l2cap|ble|classic|gap\.py|profiles|stack\.py)" || echo "OK: 协议栈零改动"`
Expected: 打印 `OK: 协议栈零改动`

- [x] **Step 3: 登记 STATUS.md**

在 `docs/superpowers/STATUS.md` 的 Plan 总览表追加一行：

```markdown
| MITM-1 | MITM 应用骨架 + ACL relay 核心 + capture | ✅ 完成 | [mitm-1](plans/2026-06-01-mitm-1-acl-relay-core.md) | `pybluehost/cli/app/mitm/{acl,relay,capture,controllers,cli}.py` |
```

- [x] **Step 4: 勾选本 Plan 全部 checkbox 并 Commit**

```bash
git add docs/superpowers/STATUS.md docs/superpowers/plans/2026-06-01-mitm-1-acl-relay-core.md
git commit -m "docs(progress): complete MITM-1 —— ACL relay 核心 + 应用骨架"
```

---

## 完成标准

- `tests/unit/mitm/` 全部 PASS（acl 重组/分片/分流、capture、relay、cli 骨架）。
- `uv run pytest tests/ -q` 无回归。
- `pybluehost/` 协议栈层（l2cap/ble/classic/gap/profiles/stack）零改动。
- `pybluehost app mitm --help` 可见；`_mitm_main` 在 recon 前以 `NotImplementedError` 占位（MITM-2 接管）。

## 给 MITM-2 的接口契约（下一个 Plan 依赖）

- `AclRelay(phone_side, target_side, *, capture=None, smp_handler=None, on_teardown=None)`；`on_phone_acl(acl)` / `on_target_acl(acl)` / `teardown()`。
- `RelaySide(name, handle, acl_max_payload, send_acl)`。
- `open_controller_pair(upstream, downstream) -> ControllerPair{upstream, downstream, close()}`。
- `smp_handler(side_name: str, cid: int, payload: bytes)` 回调签名 —— MITM-2 的最小 SMP 在此接入；SMP 发包用 `encode_l2cap_basic(CID_SMP, pdu)` + `RelaySide.send_acl` + `fragment(...)`。
- CID 分流策略表见 `acl.classify`；MITM-3 若要终结 BR 信令可扩展 `CidAction`。
