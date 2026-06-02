# MITM-2: BLE 路径 + App 内最小 SMP 实现计划

> **✅ 已完成（2026-06-02，范围 C）。** 交付:`pairing/{crypto,smp_pdu,delegate,smp}.py`(SC 密码学移植已验证实现 + KAT;SC Just Works/Numeric 状态机,LTK 延后、畸形 PDU 优雅失败、IOcap 从对端解析)、`recon.py`、`impersonate.py`、`orchestrator.py`(MitmRelay 三阶段 + SMP↔ScPairing↔ACL 保序桥接)、CLI 接线。**Task 7 取范围 C**:编排代码 + fake 单测齐全;**虚拟三角 e2e 延后真机**(VirtualController 不支持真实广播/扫描;run_relay 的连接/加密 HCI 接线为结构性实现,真机时须填真实 A1/A2 本地地址)。协议栈 + hci 层零改动。全部 mitm 单测通过。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 MITM 在 BLE 上跑通完整透传:recon 扫描克隆目标应用层身份 → 下游广播伪装 → 与手机/目标各自用 **app 自带最小 SMP（LE Secure Connections，Just Works）** 配对终结加密 → 双向 ACL 透传。

**Architecture:** 全部在 `pybluehost/cli/app/mitm/` 内，仍**不导入** l2cap/ble/classic/gap/profiles/stack。最小 SMP 自己实现 SC 配对（PDU 编解码 + f4/f5/f6/g2 密码学 + 状态机），SMP PDU 经 MITM-1 的 `AclRelay.smp_handler` 进/出，自己封 L2CAP 0x06 帧。加密通过 HCI（`LE Enable Encryption` / 响应 `LE LTK Request`）开启。

**Tech Stack:** `cryptography>=41.0`（已是依赖：AES-CMAC `cryptography.hazmat.primitives.cmac`、P-256 ECDH `...asymmetric.ec`）、MITM-1 的 `acl`/`relay`/`controllers`、`pybluehost.hci.{packets,constants,controller}`。

**依赖 MITM-1 的接口契约：** `AclRelay(phone_side, target_side, *, capture, smp_handler, on_teardown)`；`RelaySide(name, handle, acl_max_payload, send_acl)`；`open_controller_pair`；`encode_l2cap_basic(CID_SMP, pdu)` + `fragment(...)` 发 SMP 包。

> **密码学向量权威源：** 仓库内 `docs/Core_v6.0.pdf`，Vol 3, Part H, **Appendix D.2–D.5**（f4/f5/f6/g2 worked examples）。下方 KAT 向量若与 PDF 不符，**以 PDF 为准更正**。

---

## File Structure

| 文件 | 职责 |
|------|------|
| `pybluehost/cli/app/mitm/pairing/__init__.py` | 包标记 |
| `pybluehost/cli/app/mitm/pairing/crypto.py` | `aes_cmac` + `f4`/`f5`/`f6`/`g2` + `generate_keypair`/`dhkey` |
| `pybluehost/cli/app/mitm/pairing/smp_pdu.py` | SMP 操作码常量 + PDU 编解码 |
| `pybluehost/cli/app/mitm/pairing/delegate.py` | `PairingDelegate`（`confirm_numeric` 默认自动 yes） |
| `pybluehost/cli/app/mitm/pairing/smp.py` | `ScPairing` —— SC Just Works 状态机（initiator + responder 双角色） |
| `pybluehost/cli/app/mitm/recon.py` | `ClonedIdentity` + BLE 扫描 recon（裸 HCI） |
| `pybluehost/cli/app/mitm/impersonate.py` | BLE 广播伪装（裸 HCI 设 adv data + enable） |
| `pybluehost/cli/app/mitm/orchestrator.py` | `MitmRelay` —— BLE 三阶段编排（recon→impersonate→relay） |
| `tests/unit/mitm/pairing/test_crypto.py` | f4/f5/f6/g2 KAT |
| `tests/unit/mitm/pairing/test_smp_pdu.py` | PDU 编解码 |
| `tests/unit/mitm/pairing/test_smp.py` | SC JW 状态机（双 `ScPairing` 自配对） |
| `tests/unit/mitm/test_recon.py` | adv report 解析 → ClonedIdentity |
| `tests/e2e/test_mitm_ble.py` | 虚拟三角 BLE 透传 e2e |

---

## Task 1: SMP 密码学原语（f4/f5/f6/g2 + ECDH）

**Files:**
- Create: `pybluehost/cli/app/mitm/pairing/__init__.py`、`pybluehost/cli/app/mitm/pairing/crypto.py`
- Test: `tests/unit/mitm/pairing/test_crypto.py`

> **⚠ 执行修正（落地时以此为准，覆盖下方旧代码）：** 本仓库已有**经验证**的 SC 密码学实现，直接**移植**它(不 import ble,只复制实现到 app 内,符合"app 自带")，避免重写引入字节序/常量 bug：
> - 参考实现：`pybluehost/ble/smp.py` 的 `_aes_cmac`(行 333)与 `SMPCrypto.f4/f5/f6/g2`(行 384-437)。**照搬其语义**到 `pairing/crypto.py`：
>   - `f5` 的 SALT = `bytes.fromhex("6c888391aab6e7ca8cbbc3c0d2db3473")`(**不是**下方旧代码里的值)；keyID=`b"btle"`；length=`b"\x01\x00"`。
>   - `g2(U,V,X,Y)` 返回**完整 uint32** = `struct.unpack(">I", aes_cmac(X, U+V+Y)[12:16])[0]`(mod 10^6 留给 ScPairing 展示时做)。
>   - `f4(U,V,X,Z)` 的 `Z` 是 **int**：`aes_cmac(X, U+V+bytes([Z]))`。
> - ECDH：参考 `pybluehost/ble/_smp_sc_crypto.py` 的 `generate_p256_keypair`/`compute_dhkey`(**小端 wire 格式**，边界处 `[::-1]` 转换)。MITM 自带一份等价实现。
> - KAT：**复用** `tests/unit/ble/test_smp_sc_crypto.py`(ECDH 向量)与 `tests/unit/ble/test_smp.py`(f4/f5/f6/g2 KAT)里的已验证向量数值，拷进 `tests/unit/mitm/pairing/test_crypto.py`。
> - **字节序一致性**：e2e 三角里 MITM 要和真实栈 SMP 互操作，SMP PDU wire 是小端。落地 Task 4 状态机时务必对照 `pybluehost/ble/smp.py` 的 SC 收发流程确认公钥/confirm/random/DHKey-check 的字节序。

- [ ] **Step 1: 写失败测试（KAT；优先用仓库已验证向量，见上方修正）**

Create `pybluehost/cli/app/mitm/pairing/__init__.py`（空文件，仅包标记）。

Create `tests/unit/mitm/pairing/test_crypto.py`:

```python
from pybluehost.cli.app.mitm.pairing.crypto import f4, f5, f6, g2

# 向量:Core_v6.0.pdf Vol3 Part H Appendix D.2-D.5。若不符以 PDF 为准更正。
U = bytes.fromhex("20b003d2f297be2c5e2c83a7e9f9a5b9eff49111acf4fddbcc0301480e359de6")
V = bytes.fromhex("55188b3d32f6bb9a900afcfbeed4e72a59cb9ac2f19d7cfb6b4fdd49f47fc5fd")
X = bytes.fromhex("d5cb8454d177733effffb2ec712baeab")
Na = bytes.fromhex("d5cb8454d177733effffb2ec712baeab")
Nb = bytes.fromhex("a6e8e7cc25a75f6e216583f7ff3dc4cf")


def test_f4_kat():
    assert f4(U, V, X, b"\x00") == bytes.fromhex("f2c916f107a9bd1cf1eda1bea974872d")


def test_f5_kat():
    w = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b99796b13b4f866f1868d34f373bfa698")
    a1 = bytes.fromhex("00561237373bfce0"[:14])  # 7 字节:addr type(00)+BD_ADDR
    a2 = bytes.fromhex("00a713702dcfc1")
    mackey, ltk = f5(w, Na, Nb, a1, a2)
    assert mackey == bytes.fromhex("2965f176a1084a02fd3f6a20ce636e20")
    assert ltk == bytes.fromhex("69867911169d7cd23980522b594750a38"[:32])


def test_g2_returns_6_digit_int():
    val = g2(U, V, X, Nb)
    assert 0 <= val < 1_000_000
```

> **注：** `f5`/`g2` 的 A1/A2 与最终值请对照 PDF 校准；本步重点是确立函数签名与 KAT 形式，执行时以 PDF 向量为准。

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/unit/mitm/pairing/test_crypto.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写实现**

Create `pybluehost/cli/app/mitm/pairing/crypto.py`:

```python
"""LE Secure Connections 密码学原语(Core Vol3 Part H §2.2)。

全部按 spec 的大端字节序运算;PDU 层负责收发时的端序转换。
依赖 cryptography(已是项目依赖),不导入 ble/ 下的 SMP 代码。
"""
from __future__ import annotations

from cryptography.hazmat.primitives import cmac
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import algorithms

_CURVE = ec.SECP256R1()
_F5_SALT = bytes.fromhex("6C888391AAF5A53860370BDB5A6083BE")
_F5_KEYID = bytes.fromhex("62746c65")  # "btle"


def aes_cmac(key: bytes, msg: bytes) -> bytes:
    c = cmac.CMAC(algorithms.AES(key))
    c.update(msg)
    return c.finalize()


def f4(u: bytes, v: bytes, x: bytes, z: bytes) -> bytes:
    """确认值函数:AES-CMAC_x(u || v || z)。u,v=32B;x=16B key;z=1B。"""
    return aes_cmac(x, u + v + z)


def f5(w: bytes, n1: bytes, n2: bytes, a1: bytes, a2: bytes) -> tuple[bytes, bytes]:
    """密钥派生:返回 (MacKey 16B, LTK 16B)。w=DHKey 32B;n1,n2=16B;a1,a2=7B。"""
    t = aes_cmac(_F5_SALT, w)
    length = (256).to_bytes(2, "big")
    mackey = aes_cmac(t, b"\x00" + _F5_KEYID + n1 + n2 + a1 + a2 + length)
    ltk = aes_cmac(t, b"\x01" + _F5_KEYID + n1 + n2 + a1 + a2 + length)
    return mackey, ltk


def f6(w: bytes, n1: bytes, n2: bytes, r: bytes, iocap: bytes, a1: bytes, a2: bytes) -> bytes:
    """校验值:AES-CMAC_w(n1||n2||r||iocap||a1||a2)。w=MacKey 16B;iocap=3B。"""
    return aes_cmac(w, n1 + n2 + r + iocap + a1 + a2)


def g2(u: bytes, v: bytes, x: bytes, y: bytes) -> int:
    """数字比较值:AES-CMAC_x(u||v||y) 取低 32 位 mod 10^6。"""
    full = aes_cmac(x, u + v + y)
    return int.from_bytes(full[-4:], "big") % 1_000_000


def generate_keypair() -> tuple[ec.EllipticCurvePrivateKey, bytes]:
    """生成 P-256 密钥对,返回 (私钥对象, 公钥 x||y 64B 大端)。"""
    priv = ec.generate_private_key(_CURVE)
    nums = priv.public_key().public_numbers()
    pk = nums.x.to_bytes(32, "big") + nums.y.to_bytes(32, "big")
    return priv, pk


def dhkey(priv: ec.EllipticCurvePrivateKey, peer_pk: bytes) -> bytes:
    """ECDH:返回共享 x 坐标 32B 大端。peer_pk = x||y 64B。"""
    x = int.from_bytes(peer_pk[:32], "big")
    y = int.from_bytes(peer_pk[32:], "big")
    peer = ec.EllipticCurvePublicNumbers(x, y, _CURVE).public_key()
    shared = priv.exchange(ec.ECDH(), peer)
    return shared  # 32B x 坐标
```

- [ ] **Step 4: 运行，确认通过（必要时按 PDF 更正向量）**

Run: `uv run pytest tests/unit/mitm/pairing/test_crypto.py -v`
Expected: PASS。若某 KAT 失败，打开 `docs/Core_v6.0.pdf` App D 核对该向量并更正测试常量后重跑。

- [ ] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/pairing/ tests/unit/mitm/pairing/test_crypto.py
git commit -m "feat(mitm): SMP SC 密码学原语 f4/f5/f6/g2 + ECDH"
```

---

## Task 2: SMP PDU 编解码

**Files:**
- Create: `pybluehost/cli/app/mitm/pairing/smp_pdu.py`
- Test: `tests/unit/mitm/pairing/test_smp_pdu.py`

- [ ] **Step 1: 写失败测试**

Create `tests/unit/mitm/pairing/test_smp_pdu.py`:

```python
from pybluehost.cli.app.mitm.pairing import smp_pdu as P


def test_opcodes():
    assert P.PAIRING_REQUEST == 0x01
    assert P.PAIRING_RESPONSE == 0x02
    assert P.PAIRING_CONFIRM == 0x03
    assert P.PAIRING_RANDOM == 0x04
    assert P.PAIRING_PUBLIC_KEY == 0x0C
    assert P.PAIRING_DHKEY_CHECK == 0x0D


def test_pairing_request_roundtrip():
    # io_cap=0x03(NoInputNoOutput), oob=0, authreq=0x09(SC+bonding), maxkey=16, init=0, resp=0
    body = bytes([0x03, 0x00, 0x09, 0x10, 0x00, 0x00])
    pdu = P.encode(P.PAIRING_REQUEST, body)
    assert pdu == bytes([0x01]) + body
    op, payload = P.decode(pdu)
    assert op == P.PAIRING_REQUEST
    assert payload == body


def test_public_key_pdu_is_65_bytes():
    pk = bytes(range(64))
    pdu = P.encode(P.PAIRING_PUBLIC_KEY, pk)
    assert len(pdu) == 65
    assert pdu[0] == P.PAIRING_PUBLIC_KEY
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/unit/mitm/pairing/test_smp_pdu.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写实现**

Create `pybluehost/cli/app/mitm/pairing/smp_pdu.py`:

```python
"""SMP PDU(L2CAP CID 0x06)操作码与编解码。"""
from __future__ import annotations

PAIRING_REQUEST = 0x01
PAIRING_RESPONSE = 0x02
PAIRING_CONFIRM = 0x03
PAIRING_RANDOM = 0x04
PAIRING_FAILED = 0x05
PAIRING_PUBLIC_KEY = 0x0C
PAIRING_DHKEY_CHECK = 0x0D

# authreq 位
AUTHREQ_BONDING = 0x01
AUTHREQ_MITM = 0x04
AUTHREQ_SC = 0x08

# IO capability
IOCAP_DISPLAY_ONLY = 0x00
IOCAP_DISPLAY_YESNO = 0x01
IOCAP_NO_INPUT_NO_OUTPUT = 0x03


def encode(opcode: int, body: bytes = b"") -> bytes:
    return bytes([opcode]) + body


def decode(pdu: bytes) -> tuple[int, bytes]:
    return pdu[0], pdu[1:]
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/unit/mitm/pairing/test_smp_pdu.py -v`
Expected: PASS（3 个）

- [ ] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/pairing/smp_pdu.py tests/unit/mitm/pairing/test_smp_pdu.py
git commit -m "feat(mitm): SMP PDU 操作码 + 编解码"
```

---

## Task 3: PairingDelegate

**Files:**
- Create: `pybluehost/cli/app/mitm/pairing/delegate.py`
- Test: `tests/unit/mitm/pairing/test_smp.py`（先建文件放 delegate 测试）

- [ ] **Step 1: 写失败测试**

Create `tests/unit/mitm/pairing/test_smp.py`:

```python
from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate


async def test_auto_confirm_yes():
    d = AutoConfirmDelegate()
    assert await d.confirm_numeric("phone", 123456) is True
    assert await d.confirm_numeric("target", 654321) is True
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/unit/mitm/pairing/test_smp.py -k confirm -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写实现**

Create `pybluehost/cli/app/mitm/pairing/delegate.py`:

```python
"""PairingDelegate:Numeric Comparison 由测试者确认。

默认 AutoConfirmDelegate 在两侧都自动 yes(授权测试场景;数字不一致也接受,
见 spec §3.1)。CLI 的 --pairing numeric 用交互实现替换它。
"""
from __future__ import annotations

from typing import Protocol


class PairingDelegate(Protocol):
    async def confirm_numeric(self, side_name: str, value: int) -> bool: ...


class AutoConfirmDelegate:
    async def confirm_numeric(self, side_name: str, value: int) -> bool:
        return True
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/unit/mitm/pairing/test_smp.py -k confirm -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/pairing/delegate.py tests/unit/mitm/pairing/test_smp.py
git commit -m "feat(mitm): PairingDelegate + AutoConfirmDelegate"
```

---

## Task 4: ScPairing 状态机（SC Just Works，双角色自配对）

**Files:**
- Create: `pybluehost/cli/app/mitm/pairing/smp.py`
- Test: `tests/unit/mitm/pairing/test_smp.py`

`ScPairing` 是一个**纯协议状态机**：不碰 HCI/transport，只吃 SMP PDU（bytes）、吐要发送的 SMP PDU（bytes）+ 完成回调（带 LTK）。这样可用"两个 ScPairing 互喂"的方式离线验证整条 SC JW 流程。

- [ ] **Step 1: 追加失败测试 —— 两个 ScPairing 互喂跑通 SC JW**

Append to `tests/unit/mitm/pairing/test_smp.py`:

```python
import asyncio

from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate
from pybluehost.cli.app.mitm.pairing.smp import ScPairing


async def _pump(a: ScPairing, b: ScPairing):
    """把 a 的出站 PDU 喂给 b,反之亦然,直到两边都完成。"""
    a_out, b_out = asyncio.Queue(), asyncio.Queue()
    a.set_output(a_out.put_nowait)
    b.set_output(b_out.put_nowait)
    await a.start()  # initiator 起步
    for _ in range(40):  # 足够多轮
        if a.is_complete() and b.is_complete():
            return
        moved = False
        while not a_out.empty():
            await b.feed(a_out.get_nowait()); moved = True
        while not b_out.empty():
            await a.feed(b_out.get_nowait()); moved = True
        if not moved:
            break
    raise AssertionError("SC JW 未在限定轮数内完成")


async def test_sc_just_works_initiator_responder_agree_on_ltk():
    # A1/A2:addr type(1B)+addr(6B);随意但两边一致认知
    init_addr = bytes([0x00]) + bytes.fromhex("aabbccddeeff")
    resp_addr = bytes([0x00]) + bytes.fromhex("112233445566")
    a = ScPairing(role="initiator", local_addr=init_addr, peer_addr=resp_addr,
                  delegate=AutoConfirmDelegate(), side_name="A")
    b = ScPairing(role="responder", local_addr=resp_addr, peer_addr=init_addr,
                  delegate=AutoConfirmDelegate(), side_name="B")
    await _pump(a, b)
    assert a.is_complete() and b.is_complete()
    assert a.ltk is not None
    assert a.ltk == b.ltk  # 双方派生同一 LTK
    assert len(a.ltk) == 16
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/unit/mitm/pairing/test_smp.py -k just_works -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: 写实现**

Create `pybluehost/cli/app/mitm/pairing/smp.py`:

```python
"""ScPairing —— LE Secure Connections(Just Works / Numeric Comparison)最小状态机。

纯协议:吃 SMP PDU bytes、吐 SMP PDU bytes,完成后 self.ltk 可用。
不碰 HCI/L2CAP;外层(orchestrator)负责封 L2CAP 0x06 帧、HCI 开加密。
仅实现 SC + Just Works/Numeric Comparison;不做 legacy / passkey / 密钥分发。
"""
from __future__ import annotations

import os
from collections.abc import Callable

from pybluehost.cli.app.mitm.pairing import smp_pdu as P
from pybluehost.cli.app.mitm.pairing.crypto import dhkey, f4, f5, f6, g2, generate_keypair
from pybluehost.cli.app.mitm.pairing.delegate import PairingDelegate

# 固定:NoInputNoOutput → Just Works;authreq = SC + bonding
_IOCAP = P.IOCAP_NO_INPUT_NO_OUTPUT
_AUTHREQ = P.AUTHREQ_SC | P.AUTHREQ_BONDING
_MAX_KEY = 16


def _pair_cmd_body(iocap: int) -> bytes:
    # io_cap, oob(0), authreq, max_key, init_key_dist(0), resp_key_dist(0)
    return bytes([iocap, 0x00, _AUTHREQ, _MAX_KEY, 0x00, 0x00])


def _iocap_bytes(req_body: bytes, rsp_body: bytes, *, initiator: bool) -> tuple[bytes, bytes]:
    """f6 用的 IOcapA/IOcapB = authreq||oob||io_cap(各取自对应 Pairing cmd)。"""
    a = bytes([req_body[2], req_body[1], req_body[0]])  # initiator 的
    b = bytes([rsp_body[2], rsp_body[1], rsp_body[0]])  # responder 的
    return a, b


class ScPairing:
    def __init__(
        self, *, role: str, local_addr: bytes, peer_addr: bytes,
        delegate: PairingDelegate, side_name: str = "",
    ) -> None:
        assert role in ("initiator", "responder")
        self.role = role
        self._local_addr = local_addr  # 7B: type+addr
        self._peer_addr = peer_addr
        self._delegate = delegate
        self._side = side_name
        self._out: Callable[[bytes], None] | None = None

        self._priv, self._pk = generate_keypair()
        self._peer_pk: bytes = b""
        self._na = b""
        self._nb = b""
        self._cb = b""
        self._req_body = b""
        self._rsp_body = b""
        self.ltk: bytes | None = None
        self._complete = False

    def set_output(self, cb: Callable[[bytes], None]) -> None:
        self._out = cb

    def is_complete(self) -> bool:
        return self._complete

    def _send(self, opcode: int, body: bytes = b"") -> None:
        assert self._out is not None
        self._out(P.encode(opcode, body))

    async def start(self) -> None:
        if self.role == "initiator":
            self._req_body = _pair_cmd_body(_IOCAP)
            self._send(P.PAIRING_REQUEST, self._req_body)

    async def feed(self, pdu: bytes) -> None:
        op, body = P.decode(pdu)
        if op == P.PAIRING_REQUEST:        # responder 收到
            self._req_body = body
            self._rsp_body = _pair_cmd_body(_IOCAP)
            self._send(P.PAIRING_RESPONSE, self._rsp_body)
        elif op == P.PAIRING_RESPONSE:     # initiator 收到
            self._rsp_body = body
            self._send(P.PAIRING_PUBLIC_KEY, self._pk)
        elif op == P.PAIRING_PUBLIC_KEY:
            self._peer_pk = body
            if self.role == "responder":
                self._send(P.PAIRING_PUBLIC_KEY, self._pk)
                # responder 选 Nb,发 Confirm Cb = f4(PKbx, PKax, Nb, 0)
                self._nb = os.urandom(16)
                pkbx, pkax = self._pk[:32], self._peer_pk[:32]
                self._cb = f4(pkbx, pkax, self._nb, b"\x00")
                self._send(P.PAIRING_CONFIRM, self._cb)
        elif op == P.PAIRING_CONFIRM:      # initiator 收到 Cb
            self._cb = body
            self._na = os.urandom(16)
            self._send(P.PAIRING_RANDOM, self._na)
        elif op == P.PAIRING_RANDOM:
            if self.role == "responder":   # 收到 Na → 回 Nb
                self._na = body
                self._send(P.PAIRING_RANDOM, self._nb)
                await self._finish_dhkey_check(send_check=False)
            else:                          # initiator 收到 Nb → 验 Cb
                self._nb = body
                pkbx, pkax = self._peer_pk[:32], self._pk[:32]
                if f4(pkbx, pkax, self._nb, b"\x00") != self._cb:
                    self._send(P.PAIRING_FAILED, bytes([0x04]))  # confirm 不匹配
                    return
                await self._finish_dhkey_check(send_check=True)
        elif op == P.PAIRING_DHKEY_CHECK:
            # 验对端 check;若本端尚未发,则补发(responder 路径)
            await self._verify_peer_check(body)

    async def _numeric_ok(self) -> bool:
        pka, pkb = (self._pk, self._peer_pk) if self.role == "initiator" else (self._peer_pk, self._pk)
        na, nb = self._na, self._nb
        val = g2(pka[:32], pkb[:32], na, nb)
        return await self._delegate.confirm_numeric(self._side, val)

    async def _derive(self) -> tuple[bytes, bytes]:
        w = dhkey(self._priv, self._peer_pk)
        # f5 的 N1/N2/A1/A2 按 initiator/responder 角色排列
        if self.role == "initiator":
            n1, n2, a1, a2 = self._na, self._nb, self._local_addr, self._peer_addr
        else:
            n1, n2, a1, a2 = self._na, self._nb, self._peer_addr, self._local_addr
        return f5(w, n1, n2, a1, a2)  # (mackey, ltk)

    async def _finish_dhkey_check(self, *, send_check: bool) -> None:
        if not await self._numeric_ok():
            self._send(P.PAIRING_FAILED, bytes([0x0B]))  # numeric comparison failed
            return
        mackey, ltk = await self._derive()
        self.ltk = ltk
        iocap_a, iocap_b = _iocap_bytes(self._req_body, self._rsp_body, initiator=True)
        if self.role == "initiator":
            a1, a2 = self._local_addr, self._peer_addr
            ea = f6(mackey, self._na, self._nb, b"\x00" * 16, iocap_a, a1, a2)
            self._send(P.PAIRING_DHKEY_CHECK, ea)
        # responder 在收到 initiator 的 check 后再回(见 _verify_peer_check)
        self._mackey = mackey

    async def _verify_peer_check(self, peer_check: bytes) -> None:
        mackey = self._mackey
        iocap_a, iocap_b = _iocap_bytes(self._req_body, self._rsp_body, initiator=True)
        a1 = self._local_addr if self.role == "initiator" else self._peer_addr
        a2 = self._peer_addr if self.role == "initiator" else self._local_addr
        if self.role == "responder":
            # 验 initiator 的 Ea = f6(MacKey, Na, Nb, 0, IOcapA, A, B)
            expect = f6(mackey, self._na, self._nb, b"\x00" * 16, iocap_a, self._peer_addr, self._local_addr)
            if expect != peer_check:
                self._send(P.PAIRING_FAILED, bytes([0x0B]))
                return
            eb = f6(mackey, self._nb, self._na, b"\x00" * 16, iocap_b, self._local_addr, self._peer_addr)
            self._send(P.PAIRING_DHKEY_CHECK, eb)
            self._complete = True
        else:
            # initiator 验 responder 的 Eb
            expect = f6(mackey, self._nb, self._na, b"\x00" * 16, iocap_b, self._peer_addr, self._local_addr)
            if expect != peer_check:
                self._send(P.PAIRING_FAILED, bytes([0x0B]))
                return
            self._complete = True
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/unit/mitm/pairing/test_smp.py -v`
Expected: PASS（confirm + just_works）。若 LTK 不一致，对照 PDF App D 复核 f5/f6 的 N1/N2/A1/A2 排列。

- [ ] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/pairing/smp.py tests/unit/mitm/pairing/test_smp.py
git commit -m "feat(mitm): ScPairing —— SC Just Works/Numeric 最小状态机"
```

---

## Task 5: ClonedIdentity + BLE recon（裸 HCI 扫描）

**Files:**
- Create: `pybluehost/cli/app/mitm/recon.py`
- Test: `tests/unit/mitm/test_recon.py`

- [ ] **Step 1: 写失败测试 —— adv report 解析**

Create `tests/unit/mitm/test_recon.py`:

```python
from pybluehost.cli.app.mitm.recon import ClonedIdentity, parse_adv_name


def test_parse_complete_local_name():
    # AD structure: len=06, type=09(complete name), "Watch"
    adv = bytes([0x02, 0x01, 0x06,  # flags
                 0x06, 0x09, ord("W"), ord("a"), ord("t"), ord("c"), ord("h")])
    assert parse_adv_name(adv) == "Watch"


def test_parse_adv_name_absent():
    adv = bytes([0x02, 0x01, 0x06])
    assert parse_adv_name(adv) is None


def test_cloned_identity_holds_fields():
    cid = ClonedIdentity(address="AA:BB:CC:DD:EE:FF", address_type=0,
                         adv_data=b"\x02\x01\x06", scan_response=b"", name="Watch")
    assert cid.name == "Watch"
    assert cid.adv_data == b"\x02\x01\x06"
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/unit/mitm/test_recon.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写实现**

Create `pybluehost/cli/app/mitm/recon.py`:

```python
"""BLE recon:扫描目标,抓应用层身份 → ClonedIdentity(裸 HCI)。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pybluehost.hci.controller import HCIController

_AD_SHORT_NAME = 0x08
_AD_COMPLETE_NAME = 0x09


@dataclass
class ClonedIdentity:
    address: str
    address_type: int
    adv_data: bytes
    scan_response: bytes
    name: str | None


def parse_adv_name(adv: bytes) -> str | None:
    """从 AD structures 里取 complete/short local name。"""
    i = 0
    while i + 1 < len(adv):
        length = adv[i]
        if length == 0:
            break
        ad_type = adv[i + 1]
        value = adv[i + 2 : i + 1 + length]
        if ad_type in (_AD_COMPLETE_NAME, _AD_SHORT_NAME):
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return value.decode("latin-1")
        i += 1 + length
    return None


async def scan_for_target(
    controller: HCIController, *, target_addr: str | None, target_name: str | None,
    timeout: float = 10.0,
) -> ClonedIdentity:
    """主动扫描,匹配地址或名字,返回克隆身份。

    具体的 HCI 命令序列(LE Set Scan Parameters/Enable)与 adv-report 事件解析
    在执行时按 pybluehost.hci.constants 的 LE 扫描命令实现;此函数收齐
    adv_data + scan_response 后构造 ClonedIdentity。
    """
    raise NotImplementedError("在执行 Step 5 时填充 HCI 扫描序列")
```

- [ ] **Step 4: 运行纯函数测试，确认通过**

Run: `uv run pytest tests/unit/mitm/test_recon.py -v`
Expected: PASS（3 个；`scan_for_target` 的 HCI 序列在下一步补，单测此处只覆盖纯函数）

- [ ] **Step 5: 实现 `scan_for_target` 的 HCI 扫描序列**

参照 `pybluehost/hci/constants.py` 的 LE 扫描命令（`HCI_LE_SET_SCAN_PARAMETERS` / `HCI_LE_SET_SCAN_ENABLE`），用 `controller.send_command(...)` 开启主动扫描，在 `controller.set_upstream(on_hci_event=...)` 里收 `LE Advertising Report` 子事件，匹配 `target_addr`/`target_name` 后收集 adv_data + scan_response，停止扫描并 `return ClonedIdentity(...)`。用 e2e（Task 7）覆盖真实流程。

替换 `scan_for_target` 的 `raise NotImplementedError`，去掉占位。

- [ ] **Step 6: Commit**

```bash
git add pybluehost/cli/app/mitm/recon.py tests/unit/mitm/test_recon.py
git commit -m "feat(mitm): ClonedIdentity + BLE recon 扫描"
```

---

## Task 6: BLE 伪装广播（裸 HCI）

**Files:**
- Create: `pybluehost/cli/app/mitm/impersonate.py`
- Test: 由 Task 7 e2e 覆盖（广播需真实 controller 行为）

- [ ] **Step 1: 写实现**

Create `pybluehost/cli/app/mitm/impersonate.py`:

```python
"""下游伪装:用 ClonedIdentity 在下游 controller 上开广播(裸 HCI)。"""
from __future__ import annotations

from pybluehost.cli.app.mitm.recon import ClonedIdentity
from pybluehost.hci.controller import HCIController


async def start_impersonation(
    controller: HCIController, identity: ClonedIdentity, *, clone_address: bool = False,
) -> None:
    """设置 adv data / scan response 并开广播。

    clone_address=True 时先 LE Set Random Address(标准命令)套用目标地址;
    否则用下游自身地址(默认,见 spec §3.1)。HCI 命令序列(LE Set Advertising
    Data / Scan Response Data / Advertise Enable)在执行时按 hci.constants 实现。
    """
    raise NotImplementedError("在执行时填充 LE 广播 HCI 序列")
```

- [ ] **Step 2: 实现广播 HCI 序列**

参照 `hci/constants.py`：`HCI_LE_SET_ADVERTISING_DATA`、`HCI_LE_SET_SCAN_RESPONSE_DATA`、`HCI_LE_SET_ADVERTISE_ENABLE`（`clone_address` 时先 `HCI_LE_SET_RANDOM_ADDRESS`）。用 `controller.send_command(...)`。替换 `raise NotImplementedError`。

- [ ] **Step 3: Commit**

```bash
git add pybluehost/cli/app/mitm/impersonate.py
git commit -m "feat(mitm): BLE 伪装广播(裸 HCI)"
```

---

## Task 7: MitmRelay 编排 + BLE 虚拟三角 e2e

**Files:**
- Create: `pybluehost/cli/app/mitm/orchestrator.py`
- Modify: `pybluehost/cli/app/mitm/cli.py`（接 orchestrator）
- Test: `tests/e2e/test_mitm_ble.py`

`MitmRelay` 串起三阶段：recon（上游扫描）→ impersonate（下游广播）→ relay（手机连入 + 两侧配对 + `AclRelay` 武装 + HCI 开加密）。SMP PDU 经 `AclRelay` 的 `smp_handler` 进出，由每侧一个 `ScPairing` 处理；完成后用 LTK 开本侧加密。

- [ ] **Step 1: 写失败 e2e —— 虚拟三角 BLE 透传**

Create `tests/e2e/test_mitm_ble.py`:

```python
import pytest

from pybluehost.cli.app.mitm.orchestrator import MitmRelay

pytestmark = pytest.mark.asyncio


async def test_mitm_ble_passthrough_just_works(mitm_ble_triangle):
    """phone 经 MITM 对 target:连接→JW 配对→ATT 读,数据原样到达 + btsnoop 落盘。"""
    tri = mitm_ble_triangle  # fixture:构造 target/phone 完整 Stack + MITM(双虚拟 controller)
    relay: MitmRelay = tri.relay

    await relay.run_recon()
    await relay.run_impersonate()
    await relay.run_relay()       # 后台启动透传

    value = await tri.phone_read_target_attribute(handle=0x0003)
    assert value == tri.expected_value
    assert tri.btsnoop_path.exists() and tri.btsnoop_path.stat().st_size > 16
```

- [ ] **Step 2: 写 e2e fixture**

在 `tests/e2e/conftest.py`（或新建 `tests/e2e/_mitm_helpers.py` 并在 conftest 暴露 `mitm_ble_triangle`）里构造虚拟三角：两条 `VirtualLELink`（target↔mitm-upstream、mitm-downstream↔phone），`target`/`phone` 用完整 `Stack`（含真 SMP，作测试夹具），MITM 用 `open_controller_pair` 的两个 `HCIController` + `MitmRelay`。fixture 暴露 `relay`、`phone_read_target_attribute`、`expected_value`、`btsnoop_path`。

> 复用现成的 e2e 工具：`tests/e2e/_helpers.py`、`tests/e2e/_test_service.py`（GATT 测试服务）。

- [ ] **Step 3: 运行，确认失败**

Run: `uv run pytest tests/e2e/test_mitm_ble.py -v --transport=virtual`
Expected: FAIL — `ModuleNotFoundError: ...orchestrator` / fixture 未就绪

- [ ] **Step 4: 写 `orchestrator.py`**

Create `pybluehost/cli/app/mitm/orchestrator.py`:

```python
"""MitmRelay —— BLE 三阶段编排。

持有上下游两个 HCIController;recon→impersonate→relay。relay 阶段:
  - 手机连入下游 → 每侧一个 ScPairing(下游=responder,上游=initiator)处理 SMP;
  - SMP PDU 经 AclRelay.smp_handler 收,ScPairing 的 set_output 回封 L2CAP 0x06 帧发出;
  - 配对完成 → 用 LTK 经 HCI 开本侧加密;
  - 数据 CID 由 AclRelay 透明转发。
"""
from __future__ import annotations

import asyncio

from pybluehost.cli.app.mitm.acl import CID_SMP, encode_l2cap_basic, fragment
from pybluehost.cli.app.mitm.capture import BtsnoopCaptureTap, NullTap
from pybluehost.cli.app.mitm.controllers import ControllerPair
from pybluehost.cli.app.mitm.impersonate import start_impersonation
from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate, PairingDelegate
from pybluehost.cli.app.mitm.pairing.smp import ScPairing
from pybluehost.cli.app.mitm.recon import ClonedIdentity, scan_for_target
from pybluehost.cli.app.mitm.relay import AclRelay, RelaySide


class MitmRelay:
    def __init__(
        self, pair: ControllerPair, *, target_addr=None, target_name=None,
        btsnoop=None, clone_address=False, delegate: PairingDelegate | None = None,
    ) -> None:
        self._pair = pair
        self._target_addr = target_addr
        self._target_name = target_name
        self._capture = BtsnoopCaptureTap(btsnoop) if btsnoop else NullTap()
        self._clone_address = clone_address
        self._delegate = delegate or AutoConfirmDelegate()
        self._identity: ClonedIdentity | None = None
        self._relay: AclRelay | None = None

    async def run_recon(self) -> None:
        self._identity = await scan_for_target(
            self._pair.upstream, target_addr=self._target_addr, target_name=self._target_name
        )

    async def run_impersonate(self) -> None:
        assert self._identity is not None
        await start_impersonation(
            self._pair.downstream, self._identity, clone_address=self._clone_address
        )

    async def run_relay(self) -> None:
        """等手机连入 + 连目标 + 两侧配对 + 武装 AclRelay。

        连接事件、配对完成→开加密、AclRelay 武装的具体接线在执行时按
        HCIController 的连接/加密事件 API 完成;ScPairing 与 smp_handler 的
        对接见下方 _make_smp_handler。
        """
        raise NotImplementedError("在执行 Step 5 接好连接/加密/relay 武装")

    def _make_smp_handler(self, sides: dict[str, ScPairing], relay_sides: dict[str, RelaySide]):
        async def handler(side_name: str, cid: int, payload: bytes) -> None:
            await sides[side_name].feed(payload)
        return handler

    def _smp_output(self, side: RelaySide):
        """ScPairing.set_output 的目标:把 SMP PDU 封 L2CAP 0x06 帧发到该侧。"""
        async def send_pdu(pdu: bytes) -> None:
            l2 = encode_l2cap_basic(CID_SMP, pdu)
            for frag in fragment(handle=side.handle, l2cap_pdu=l2, max_payload=side.acl_max_payload):
                await side.send_acl(frag.handle, frag.pb_flag, frag.data)
        # ScPairing.set_output 是同步回调 → 包成 create_task
        return lambda pdu: asyncio.create_task(send_pdu(pdu))

    async def teardown(self) -> None:
        if self._relay is not None:
            await self._relay.teardown()
        await self._pair.close()
```

- [ ] **Step 5: 接好 `run_relay`（连接/配对/加密/武装）**

实现要点（执行时填充，替换 `raise NotImplementedError`）：
1. 在两侧 controller 注册连接完成事件 → 拿到 phone/target 的 connection handle 与各自 `(le_)acl_packet_length`，构造两个 `RelaySide`。
2. 为每侧建一个 `ScPairing`（downstream=responder、upstream=initiator），`set_output` 用 `self._smp_output(side)`；下游 responder 等手机发起、上游 initiator `await pairing.start()`。
3. `AclRelay(phone_side=..., target_side=..., capture=self._capture, smp_handler=self._make_smp_handler(...))`，把每侧 `on_acl_data` 接到 `relay.on_phone_acl`/`on_target_acl`。
4. 某侧 `ScPairing.is_complete()` → 用 `pairing.ltk` 经 HCI 开该侧加密（`LE Enable Encryption` 或响应 `LE LTK Request`，参照 `HCIController` 的加密事件 API）。
5. 两侧加密就绪后透传自然进行（AclRelay 已武装）。

- [ ] **Step 6: 接 CLI**

Modify `pybluehost/cli/app/mitm/cli.py` 的 `_mitm_main`，替换 MITM-1 的 `NotImplementedError`：

```python
async def _mitm_main(args: argparse.Namespace) -> None:
    from pybluehost.cli.app.mitm.controllers import open_controller_pair
    from pybluehost.cli.app.mitm.orchestrator import MitmRelay

    pair = await open_controller_pair(args.upstream, args.downstream)
    relay = MitmRelay(
        pair, target_addr=args.target, target_name=args.target_name,
        btsnoop=args.btsnoop, clone_address=args.clone_address,
    )
    try:
        await relay.run_recon()
        await relay.run_impersonate()
        await relay.run_relay()
    finally:
        await relay.teardown()
```

- [ ] **Step 7: 运行 e2e，确认通过**

Run: `uv run pytest tests/e2e/test_mitm_ble.py -v --transport=virtual`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add pybluehost/cli/app/mitm/orchestrator.py pybluehost/cli/app/mitm/cli.py tests/e2e/test_mitm_ble.py tests/e2e/conftest.py
git commit -m "feat(mitm): MitmRelay BLE 三阶段编排 + 虚拟三角 e2e(Just Works)"
```

---

## Task 8: 收尾 —— 全套测试 + STATUS.md

- [ ] **Step 1: 全套测试**

Run: `uv run pytest tests/ -q --transport=virtual`
Expected: 全部 PASS

- [ ] **Step 2: 确认协议栈零改动**

Run: `git diff --name-only $(git merge-base HEAD master)..HEAD | grep -E "pybluehost/(l2cap|ble|classic|gap\.py|profiles|stack\.py)" || echo "OK: 协议栈零改动"`
Expected: `OK: 协议栈零改动`（注：e2e 夹具用 `Stack` 但不修改其源码）

- [ ] **Step 3: 更新 STATUS.md 并 Commit**

追加 STATUS.md 表行：

```markdown
| MITM-2 | BLE 路径 + app 内最小 SMP(SC JW) | ✅ 完成 | [mitm-2](plans/2026-06-01-mitm-2-ble-path-min-smp.md) | `pybluehost/cli/app/mitm/{pairing/,recon,impersonate,orchestrator}.py` |
```

```bash
git add docs/superpowers/STATUS.md docs/superpowers/plans/2026-06-01-mitm-2-ble-path-min-smp.md
git commit -m "docs(progress): complete MITM-2 —— BLE 透传 + 最小 SMP"
```

---

## 完成标准

- `tests/unit/mitm/pairing/` KAT + SC JW 状态机自配对 PASS。
- `tests/e2e/test_mitm_ble.py` 虚拟三角 BLE 透传（含 JW 配对 + btsnoop）PASS。
- 协议栈层零改动。

## 给 MITM-3 的接口契约

- `MitmRelay` 三阶段方法 `run_recon` / `run_impersonate` / `run_relay`，BR 将复用骨架并注入 BR 差异（inquiry recon、page/inquiry-scan impersonate、SSP 经 HCI 事件而非 SMP）。
- `ScPairing` 仅 BLE 用；BR 的 SSP 终结在 MITM-3 新建 `pairing/ssp.py`（HCI 事件驱动，无 app 密码学）。
- `AclRelay` 对 BR 完全复用（CID 分流策略表已含 BR signaling 0x01 透传）。
