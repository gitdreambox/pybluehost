# MITM-3: BR/EDR 路径 + SSP 终结 + 可选改址 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 MITM 在 BR/EDR 上跑通透传：inquiry recon 克隆目标（BD_ADDR/CoD/EIR/name）→ 下游开 inquiry/page scan 伪装 → 与手机/目标各自经 **HCI SSP 事件**终结配对/加密 → 复用 MITM-1 的 `AclRelay` 透传 ACL。可选 `--clone-address`（vendor `Write_BD_ADDR`）。

**Architecture:** BR 路径复用 MITM-2 的 `MitmRelay` 三阶段骨架与 MITM-1 的 `AclRelay`（CID 分流策略表已含 BR signaling 0x01 透传、RFCOMM/SDP 动态 channel 透明转发）。差异只在三处：recon（inquiry 而非 scan）、impersonate（inquiry/page scan + CoD/EIR 而非广播）、配对（**SSP 经 HCI 事件，无 app 密码学**——控制器做 SSP 加密）。可选 vendor 写址在 app 内实现，**不污染** `hci/vendor/`。仍**不导入** l2cap/ble/classic/gap/profiles/stack。

**Tech Stack:** MITM-1/2 的 `acl`/`relay`/`orchestrator`/`controllers`、`pybluehost.hci.{constants,controller}`、`HCIController` 的 SSP 事件钩子（`on_io_capability_request` / `on_user_confirmation_request` / `on_link_key_notification` / `on_link_key_request`）。

**依赖前提（spec §2 + MITM-1/2 契约）：** `AclRelay` 对 BR 完全复用；`HCIController` 暴露 SSP 事件钩子（见 `controller.py` `on_io_capability_request` 等）；测试用 `hci/virtual_classic_link.py`（Inquiry/Connection/ACL/Auth/Encryption/Disconnect 六桥）。

> **改址依赖（仅 `--clone-address`）：** Broadcom `0xFC01` Write_BD_ADDR / CSR PSKEY。芯片对照见 spec §8。默认模式不依赖改址（手机按 inquiry 应答的地址 page MITM 自身地址，见 spec §3.1）。

---

## File Structure

| 文件 | 职责 |
|------|------|
| `pybluehost/cli/app/mitm/pairing/ssp.py` | `SspTermination` —— 注册 HCI SSP 事件 + link key store（JW + Numeric） |
| `pybluehost/cli/app/mitm/bredr_recon.py` | `inquiry_for_target` —— BR inquiry + Remote Name → ClonedIdentity 复用 |
| `pybluehost/cli/app/mitm/bredr_impersonate.py` | `start_bredr_impersonation` —— 写 CoD/EIR/name + 开 inquiry/page scan |
| `pybluehost/cli/app/mitm/address.py` | `clone_bd_addr` —— vendor Write_BD_ADDR + 能力探测（可选） |
| `pybluehost/cli/app/mitm/orchestrator.py` | 扩展 `MitmRelay` 支持 `mode="bredr"` 分支 |
| `tests/unit/mitm/pairing/test_ssp.py` | SSP 事件序列驱动 JW + Numeric + link key store |
| `tests/unit/mitm/test_address.py` | Write_BD_ADDR 命令构造 + 能力探测 |
| `tests/e2e/test_mitm_bredr.py` | VirtualClassicLink 三角 BR 透传 e2e |

---

## Task 1: SSP 终结（HCI 事件驱动 + link key store）

**Files:**
- Create: `pybluehost/cli/app/mitm/pairing/ssp.py`
- Test: `tests/unit/mitm/pairing/test_ssp.py`

`SspTermination` 把一个 `HCIController` 的 SSP 事件接管为本地终结：IO Capability Request → 回 NoInputNoOutput（JW）或 DisplayYesNo（Numeric）；User Confirmation Request → 经 delegate 决定回 `User_Confirmation_Request_Reply`/`Negative_Reply`；Link Key Notification → 存；Link Key Request → 查（命中回 reply、未命中回 negative reply 触发新 SSP）。

- [ ] **Step 1: 写失败测试 —— 用 fake controller 验证事件应答**

Create `tests/unit/mitm/pairing/test_ssp.py`:

```python
from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate
from pybluehost.cli.app.mitm.pairing.ssp import SspTermination


class FakeController:
    """记录 SSP 事件钩子注册 + 捕获回复命令(用 opcode 名字)。"""
    def __init__(self):
        self.io_cb = None
        self.uc_cb = None
        self.lkn_cb = None
        self.lkr_cb = None
        self.replies = []  # (name, args)

    def on_io_capability_request(self, cb): self.io_cb = cb
    def on_user_confirmation_request(self, cb): self.uc_cb = cb
    def on_link_key_notification(self, cb): self.lkn_cb = cb
    def on_link_key_request(self, cb): self.lkr_cb = cb

    async def reply_io_capability(self, addr, io_cap):
        self.replies.append(("io", addr, io_cap))
    async def reply_user_confirmation(self, addr, accept):
        self.replies.append(("uc", addr, accept))
    async def reply_link_key(self, addr, key):
        self.replies.append(("lk", addr, key))


async def test_io_capability_just_works_replies_noinputnooutput():
    fc = FakeController()
    ssp = SspTermination(fc, delegate=AutoConfirmDelegate(), side_name="phone")
    ssp.attach()
    await fc.io_cb("AA:BB:CC:DD:EE:FF")
    assert fc.replies == [("io", "AA:BB:CC:DD:EE:FF", 0x03)]  # NoInputNoOutput


async def test_user_confirmation_auto_accept():
    fc = FakeController()
    ssp = SspTermination(fc, delegate=AutoConfirmDelegate(), side_name="phone")
    ssp.attach()
    await fc.uc_cb("AA:BB:CC:DD:EE:FF", 123456)
    assert ("uc", "AA:BB:CC:DD:EE:FF", True) in fc.replies


async def test_link_key_store_roundtrip():
    fc = FakeController()
    ssp = SspTermination(fc, delegate=AutoConfirmDelegate(), side_name="phone")
    ssp.attach()
    await fc.lkn_cb("AA:BB:CC:DD:EE:FF", b"\x11" * 16)   # 存
    await fc.lkr_cb("AA:BB:CC:DD:EE:FF")                  # 查 → 命中回 reply
    assert ("lk", "AA:BB:CC:DD:EE:FF", b"\x11" * 16) in fc.replies
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/unit/mitm/pairing/test_ssp.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写实现**

Create `pybluehost/cli/app/mitm/pairing/ssp.py`:

```python
"""BR/EDR SSP 本地终结:控制器驱动,主机只处理 HCI 事件 + 存 link key。

无 app 密码学(SSP ECDH/numeric 由控制器完成)。JW = NoInputNoOutput;
Numeric = DisplayYesNo + delegate 确认。
"""
from __future__ import annotations

from pybluehost.cli.app.mitm.pairing.delegate import PairingDelegate

IOCAP_DISPLAY_YESNO = 0x01
IOCAP_NO_INPUT_NO_OUTPUT = 0x03


class SspTermination:
    def __init__(
        self, controller, *, delegate: PairingDelegate, side_name: str,
        numeric: bool = False,
    ) -> None:
        self._c = controller
        self._delegate = delegate
        self._side = side_name
        self._numeric = numeric
        self._link_keys: dict[str, bytes] = {}

    def attach(self) -> None:
        self._c.on_io_capability_request(self._on_io)
        self._c.on_user_confirmation_request(self._on_uc)
        self._c.on_link_key_notification(self._on_lkn)
        self._c.on_link_key_request(self._on_lkr)

    async def _on_io(self, addr: str) -> None:
        io_cap = IOCAP_DISPLAY_YESNO if self._numeric else IOCAP_NO_INPUT_NO_OUTPUT
        await self._c.reply_io_capability(addr, io_cap)

    async def _on_uc(self, addr: str, value: int) -> None:
        accept = await self._delegate.confirm_numeric(self._side, value)
        await self._c.reply_user_confirmation(addr, accept)

    async def _on_lkn(self, addr: str, key: bytes) -> None:
        self._link_keys[addr] = key

    async def _on_lkr(self, addr: str) -> None:
        key = self._link_keys.get(addr)
        await self._c.reply_link_key(addr, key)  # key=None → 实现里发 negative reply
```

> 注：`reply_io_capability` / `reply_user_confirmation` / `reply_link_key` 是对 `HCIController` 现有 SSP 应答能力的薄封装；若 `HCIController` 暴露的是 `send_command(...)`，在执行时用对应 HCI 命令（`IO_Capability_Request_Reply` / `User_Confirmation_Request_Reply` / `Link_Key_Request_Reply` / `_Negative_Reply`）实现这三个方法（可作为 `SspTermination` 的私有方法），并相应调整 FakeController 与测试。

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/unit/mitm/pairing/test_ssp.py -v`
Expected: PASS（3 个）

- [ ] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/pairing/ssp.py tests/unit/mitm/pairing/test_ssp.py
git commit -m "feat(mitm): SspTermination —— BR SSP HCI 事件终结 + link key store"
```

---

## Task 2: 可选改址（vendor Write_BD_ADDR + 能力探测）

**Files:**
- Create: `pybluehost/cli/app/mitm/address.py`
- Test: `tests/unit/mitm/test_address.py`

- [ ] **Step 1: 写失败测试 —— Broadcom 命令构造 + 不支持时探测**

Create `tests/unit/mitm/test_address.py`:

```python
import pytest

from pybluehost.cli.app.mitm.address import (
    AddressCloneUnsupported,
    build_broadcom_write_bdaddr,
)


def test_broadcom_write_bdaddr_opcode_and_addr_order():
    # BD_ADDR 在 HCI 里小端;Broadcom 0xFC01 payload = 6 字节小端地址
    cmd = build_broadcom_write_bdaddr("AA:BB:CC:DD:EE:FF")
    assert cmd.opcode == 0xFC01
    assert cmd.params == bytes.fromhex("ffeeddccbbaa")  # 小端


def test_unsupported_chip_raises():
    with pytest.raises(AddressCloneUnsupported):
        raise AddressCloneUnsupported("Intel: BD_ADDR OTP 锁死,改用 Broadcom/CSR 伪装侧")
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/unit/mitm/test_address.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写实现**

Create `pybluehost/cli/app/mitm/address.py`:

```python
"""可选地址克隆(--clone-address):vendor Write_BD_ADDR + 能力探测。

仅 BR 重连/地址锁定场景需要(spec §3.1)。在 app 内实现,不污染 hci/vendor。
Broadcom: 0xFC01 + 6 字节小端 BD_ADDR(临时,掉电还原)。
CSR: PSKEY 写(0xFC00,持久)——按需扩展。
"""
from __future__ import annotations

from dataclasses import dataclass

from pybluehost.hci.packets import HCICommand

_BROADCOM_WRITE_BDADDR = 0xFC01


class AddressCloneUnsupported(Exception):
    """下游芯片不支持写 BD_ADDR(如 Intel)。"""


@dataclass
class _Cmd:
    opcode: int
    params: bytes


def _addr_to_le_bytes(addr: str) -> bytes:
    parts = [int(x, 16) for x in addr.split(":")]
    return bytes(reversed(parts))


def build_broadcom_write_bdaddr(addr: str) -> _Cmd:
    return _Cmd(opcode=_BROADCOM_WRITE_BDADDR, params=_addr_to_le_bytes(addr))


async def clone_bd_addr(controller, addr: str) -> None:
    """探测下游芯片厂商并发对应 Write_BD_ADDR;不支持则 raise。

    用 controller.manufacturer_id() 区分 Broadcom(0x000F)/CSR(0x000A)/Intel(0x0002)。
    Intel → AddressCloneUnsupported。发命令用 controller.send_command(HCICommand(...))。
    具体 CSR PSKEY 序列在执行时按需补;Broadcom 路径即上面的命令。
    """
    raise NotImplementedError("在执行时按 manufacturer_id 分支发 vendor 命令")
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/unit/mitm/test_address.py -v`
Expected: PASS（2 个；`clone_bd_addr` 的厂商分支在接 orchestrator 时补，由 e2e/手动验证）

- [ ] **Step 5: Commit**

```bash
git add pybluehost/cli/app/mitm/address.py tests/unit/mitm/test_address.py
git commit -m "feat(mitm): 可选 vendor Write_BD_ADDR + 能力探测(Broadcom/CSR)"
```

---

## Task 3: BR recon（inquiry + Remote Name）

**Files:**
- Create: `pybluehost/cli/app/mitm/bredr_recon.py`
- Test: e2e（inquiry 需真实 controller 行为，单测覆盖纯解析）

- [ ] **Step 1: 写实现 + EIR 名字解析的失败测试**

Create `tests/unit/mitm/test_recon.py` 追加（复用 MITM-2 的文件）：

```python
from pybluehost.cli.app.mitm.bredr_recon import parse_eir_name  # noqa: E402


def test_parse_eir_complete_name():
    eir = bytes([0x05, 0x09, ord("P"), ord("h"), ord("o"), ord("n")])  # "Phon"
    assert parse_eir_name(eir) == "Phon"
```

Create `pybluehost/cli/app/mitm/bredr_recon.py`:

```python
"""BR recon:inquiry + Remote Name → ClonedIdentity(复用 recon.ClonedIdentity)。"""
from __future__ import annotations

from pybluehost.cli.app.mitm.recon import ClonedIdentity

_EIR_SHORT_NAME = 0x08
_EIR_COMPLETE_NAME = 0x09


def parse_eir_name(eir: bytes) -> str | None:
    i = 0
    while i + 1 < len(eir):
        length = eir[i]
        if length == 0:
            break
        ad_type = eir[i + 1]
        value = eir[i + 2 : i + 1 + length]
        if ad_type in (_EIR_COMPLETE_NAME, _EIR_SHORT_NAME):
            return value.decode("utf-8", errors="replace")
        i += 1 + length
    return None


async def inquiry_for_target(
    controller, *, target_addr: str | None, target_name: str | None, timeout: float = 12.0,
) -> ClonedIdentity:
    """Inquiry 抓 bd_addr/CoD/EIR,必要时 Remote Name Request 补名字。

    HCI 序列(Inquiry / Inquiry Result with RSSI/EIR / Remote Name Request)在执行时
    按 hci.constants 实现;收齐后构造 ClonedIdentity(adv_data 字段复用为 EIR,
    scan_response=b"")。
    """
    raise NotImplementedError("在执行时填充 inquiry HCI 序列")
```

- [ ] **Step 2: 运行纯函数测试**

Run: `uv run pytest tests/unit/mitm/test_recon.py -k eir -v`
Expected: PASS

- [ ] **Step 3: 实现 `inquiry_for_target` 的 HCI 序列**

参照 `hci/constants.py` 的 Inquiry 命令族；用 `controller.send_command` 起 inquiry，事件里收 `Inquiry Result`（含 CoD/EIR），匹配 `target_addr`/`target_name`，必要时 `Remote_Name_Request`，构造 `ClonedIdentity` 并 return。替换占位。

- [ ] **Step 4: Commit**

```bash
git add pybluehost/cli/app/mitm/bredr_recon.py tests/unit/mitm/test_recon.py
git commit -m "feat(mitm): BR recon —— inquiry + EIR 名字解析"
```

---

## Task 4: BR 伪装（CoD/EIR + inquiry/page scan）

**Files:**
- Create: `pybluehost/cli/app/mitm/bredr_impersonate.py`
- Test: e2e 覆盖

- [ ] **Step 1: 写实现**

Create `pybluehost/cli/app/mitm/bredr_impersonate.py`:

```python
"""下游 BR 伪装:写 CoD/EIR/本地名,开 inquiry scan + page scan(裸 HCI)。"""
from __future__ import annotations

from pybluehost.cli.app.mitm.recon import ClonedIdentity


async def start_bredr_impersonation(
    controller, identity: ClonedIdentity, *, clone_address: bool = False,
) -> None:
    """套用 CoD/EIR/name 并开 inquiry+page scan。

    clone_address=True → 先 app.address.clone_bd_addr(controller, identity.address)。
    HCI 序列(Write Class of Device / Write Extended Inquiry Response /
    Write Local Name / Write Scan Enable=inquiry+page)在执行时按 hci.constants 实现。
    """
    if clone_address:
        from pybluehost.cli.app.mitm.address import clone_bd_addr
        await clone_bd_addr(controller, identity.address)
    raise NotImplementedError("在执行时填充 CoD/EIR/scan-enable HCI 序列")
```

- [ ] **Step 2: 实现 HCI 序列**

`Write_Class_of_Device` / `Write_Extended_Inquiry_Response` / `Write_Local_Name` / `Write_Scan_Enable`（inquiry+page scan）。替换占位。

- [ ] **Step 3: Commit**

```bash
git add pybluehost/cli/app/mitm/bredr_impersonate.py
git commit -m "feat(mitm): BR 伪装 —— CoD/EIR + inquiry/page scan"
```

---

## Task 5: MitmRelay 扩展 BR 分支 + VirtualClassicLink 三角 e2e

**Files:**
- Modify: `pybluehost/cli/app/mitm/orchestrator.py`
- Test: `tests/e2e/test_mitm_bredr.py`

- [ ] **Step 1: 写失败 e2e**

Create `tests/e2e/test_mitm_bredr.py`:

```python
import pytest

pytestmark = pytest.mark.asyncio


async def test_mitm_bredr_passthrough_just_works(mitm_bredr_triangle):
    """phone 经 MITM 对 target:inquiry→connect→SSP(JW)→SDP browse + RFCOMM echo。"""
    tri = mitm_bredr_triangle  # fixture:VirtualClassicLink 双桥 + target/phone Stack + MITM
    relay = tri.relay

    await relay.run_recon()
    await relay.run_impersonate()
    await relay.run_relay()

    services = await tri.phone_sdp_browse()
    assert tri.expected_rfcomm_channel in services
    echoed = await tri.phone_rfcomm_echo(b"ping")
    assert echoed == b"ping"
    assert tri.btsnoop_path.exists()
```

- [ ] **Step 2: 写 e2e fixture（VirtualClassicLink 三角）**

在 `tests/e2e/conftest.py` 增 `mitm_bredr_triangle`：两条 `hci/virtual_classic_link.py` 桥（target↔mitm-upstream、mitm-downstream↔phone），`target`/`phone` 完整 `Stack`（含 SDP/RFCOMM 服务，复用 `tests/e2e/_classic_test_service.py`），MITM 用 `MitmRelay(mode="bredr")`。暴露 `relay`/`phone_sdp_browse`/`phone_rfcomm_echo`/`expected_rfcomm_channel`/`btsnoop_path`。

- [ ] **Step 3: 运行，确认失败**

Run: `uv run pytest tests/e2e/test_mitm_bredr.py -v --transport=virtual`
Expected: FAIL — fixture/`mode="bredr"` 未就绪

- [ ] **Step 4: 扩展 `MitmRelay` 的 BR 分支**

Modify `pybluehost/cli/app/mitm/orchestrator.py`：给 `MitmRelay.__init__` 加 `mode: str = "le"`（取值 `le`/`bredr`）；`run_recon`/`run_impersonate` 按 mode 分派：

```python
    async def run_recon(self) -> None:
        if self._mode == "bredr":
            from pybluehost.cli.app.mitm.bredr_recon import inquiry_for_target
            self._identity = await inquiry_for_target(
                self._pair.upstream, target_addr=self._target_addr, target_name=self._target_name
            )
        else:
            from pybluehost.cli.app.mitm.recon import scan_for_target
            self._identity = await scan_for_target(
                self._pair.upstream, target_addr=self._target_addr, target_name=self._target_name
            )

    async def run_impersonate(self) -> None:
        assert self._identity is not None
        if self._mode == "bredr":
            from pybluehost.cli.app.mitm.bredr_impersonate import start_bredr_impersonation
            await start_bredr_impersonation(
                self._pair.downstream, self._identity, clone_address=self._clone_address
            )
        else:
            from pybluehost.cli.app.mitm.impersonate import start_impersonation
            await start_impersonation(
                self._pair.downstream, self._identity, clone_address=self._clone_address
            )
```

`run_relay` 的 BR 分支：配对用 `SspTermination`（每侧一个 `.attach()`）替代 `ScPairing`；连接经 page/被 page 建立；`AclRelay` 武装与 LE 完全一致（CID 分流复用，BR signaling 0x01 透传、RFCOMM/SDP 动态 channel 透明转发）。SSP 不走 `smp_handler`（SSP 是 HCI 事件，不经 L2CAP 0x06），故 BR 模式 `AclRelay` 的 `smp_handler=None`。

- [ ] **Step 5: 运行 e2e，确认通过**

Run: `uv run pytest tests/e2e/test_mitm_bredr.py -v --transport=virtual`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pybluehost/cli/app/mitm/orchestrator.py tests/e2e/test_mitm_bredr.py tests/e2e/conftest.py
git commit -m "feat(mitm): MitmRelay BR 分支 + VirtualClassicLink 三角 e2e(SSP JW)"
```

---

## Task 6: 收尾 —— 全套测试 + STATUS.md

- [ ] **Step 1: 全套测试**

Run: `uv run pytest tests/ -q --transport=virtual`
Expected: 全部 PASS（BLE + BR e2e 在内）

- [ ] **Step 2: 确认协议栈零改动**

Run: `git diff --name-only $(git merge-base HEAD master)..HEAD | grep -E "pybluehost/(l2cap|ble|classic|gap\.py|profiles|stack\.py)" || echo "OK: 协议栈零改动"`
Expected: `OK: 协议栈零改动`

- [ ] **Step 3: 更新 STATUS.md 并 Commit**

```markdown
| MITM-3 | BR/EDR 路径 + SSP 终结 + 可选改址 | ✅ 完成 | [mitm-3](plans/2026-06-01-mitm-3-bredr-path-ssp.md) | `pybluehost/cli/app/mitm/{pairing/ssp,bredr_recon,bredr_impersonate,address}.py` |
```

```bash
git add docs/superpowers/STATUS.md docs/superpowers/plans/2026-06-01-mitm-3-bredr-path-ssp.md
git commit -m "docs(progress): complete MITM-3 —— BR 透传 + SSP 终结"
```

---

## 完成标准

- `tests/unit/mitm/pairing/test_ssp.py`、`test_address.py`、`test_recon.py`(EIR) PASS。
- `tests/e2e/test_mitm_bredr.py` VirtualClassicLink 三角 BR 透传（SSP JW + SDP + RFCOMM echo）PASS。
- 协议栈层零改动。

## 给 MITM-4 的接口契约

- `MitmRelay(pair, *, mode="le"|"bredr", target_addr, target_name, btsnoop, clone_address, delegate)`。
- `--clone-address` 经 `address.clone_bd_addr` 生效（BR）/ `LE Set Random Address`（LE，在 `impersonate.start_impersonation` 内）。
- Numeric Comparison 在 BLE 走 `ScPairing` 的 `confirm_numeric`、BR 走 `SspTermination(numeric=True)` 的 `confirm_numeric`；MITM-4 提供交互 delegate 注入两条路径。
