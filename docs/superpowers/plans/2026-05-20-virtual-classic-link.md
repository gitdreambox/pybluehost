# VirtualClassicLink Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the BR/EDR (Classic) counterpart of `VirtualLELink` so two `Stack.virtual()` instances can complete real peer-to-peer Classic workflows (inquiry → connect → SSP pair → ACL data → encryption → disconnect) without relying on synthetic `simulate_*` event-injection hacks.

**Architecture:** One new class `VirtualClassicLink` in `pybluehost/hci/virtual_classic_link.py` (alongside the LE bridge). It owns six logical sub-bridges (Inquiry / Connection / ACL / Auth / Encryption / Disconnect) sharing a connection-handle table. Each sub-bridge intercepts a specific set of HCI commands via a new generic `command_interceptor` attribute on `VirtualController` and routes HCI events / ACL data to the other side via the existing `_send_event_to_host` / `_inject_acl_to_host` paths. Host-side protocol layers (`SSPManager`, L2CAP, etc.) do all the work; the bridge is transport-level glue.

**Tech Stack:** Python 3.10+, asyncio, pytest, pytest-asyncio. Reuses `VirtualController`, `HCIEvent`, `HCIACLData`, existing event-code / opcode constants in `pybluehost/hci/`.

**Design spec:** [`docs/superpowers/specs/2026-05-20-virtual-classic-link-design.md`](../specs/2026-05-20-virtual-classic-link-design.md)

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Modify | `pybluehost/hci/virtual.py` | Add `command_interceptor: Optional[Callable]` attribute to `VirtualController`; call it at the top of `process()` after the ACL branch, before the Standard Command Complete dispatch. Add scan-enable tracking (`_inquiry_scan: bool`, `_page_scan: bool`) populated by the `HCI_Write_Scan_Enable` handler. |
| Create | `pybluehost/hci/virtual_classic_link.py` | `VirtualClassicLink` class with six sub-bridges + connection-handle table + `connect()` / `disconnect()` lifecycle |
| Create | `tests/integration/test_virtual_classic_link.py` | Per-primitive bridge tests (~15) |
| Create | `tests/integration/test_classic_e2e_smoke.py` | Single inquiry→connect→SSP JW pair→encrypt→disconnect smoke E2E |
| Modify | `docs/superpowers/STATUS.md` | Mark Plan complete; add follow-up Classic Workflow E2E to 下一步 |

---

## HCI opcode reference (used throughout the plan)

These constants exist in `pybluehost/hci/constants.py` — verify exact spellings via `grep -n "HCI_INQUIRY\|HCI_CREATE_CONNECTION\|HCI_ACCEPT_CONNECTION\|HCI_REJECT_CONNECTION\|HCI_DISCONNECT\|HCI_AUTHENTICATION_REQUESTED\|HCI_LINK_KEY_REQUEST\|HCI_IO_CAPABILITY\|HCI_USER_CONFIRMATION\|HCI_PIN_CODE\|HCI_SET_CONNECTION_ENCRYPTION\|HCI_WRITE_SCAN_ENABLE" pybluehost/hci/constants.py`. If a name is missing, the implementer adds the constant (no behavior change) and references it in the plan code.

| Command | OGF/OCF | Constant (verify) |
|---|---|---|
| Inquiry | 01/0001 | `HCI_INQUIRY` |
| Inquiry_Cancel | 01/0002 | `HCI_INQUIRY_CANCEL` |
| Create_Connection | 01/0005 | `HCI_CREATE_CONNECTION` |
| Disconnect | 01/0006 | `HCI_DISCONNECT` |
| Accept_Connection_Request | 01/0009 | `HCI_ACCEPT_CONNECTION_REQUEST` |
| Reject_Connection_Request | 01/000A | `HCI_REJECT_CONNECTION_REQUEST` |
| Link_Key_Request_Reply | 01/000B | `HCI_LINK_KEY_REQUEST_REPLY` |
| Link_Key_Request_Negative_Reply | 01/000C | `HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY` |
| PIN_Code_Request_Reply | 01/000D | `HCI_PIN_CODE_REQUEST_REPLY` |
| PIN_Code_Request_Negative_Reply | 01/000E | `HCI_PIN_CODE_REQUEST_NEGATIVE_REPLY` |
| Authentication_Requested | 01/0011 | `HCI_AUTHENTICATION_REQUESTED` |
| Set_Connection_Encryption | 01/0013 | `HCI_SET_CONNECTION_ENCRYPTION` |
| IO_Capability_Request_Reply | 01/002B | `HCI_IO_CAPABILITY_REQUEST_REPLY` |
| User_Confirmation_Request_Reply | 01/002C | `HCI_USER_CONFIRMATION_REQUEST_REPLY` |
| User_Confirmation_Request_Negative_Reply | 01/002D | `HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY` |
| Write_Scan_Enable | 03/001A | `HCI_WRITE_SCAN_ENABLE` |

| Event | EventCode | Reference |
|---|---|---|
| Inquiry_Result | 0x02 | `EventCode.INQUIRY_RESULT` |
| Inquiry_Complete | 0x01 | `EventCode.INQUIRY_COMPLETE` |
| Connection_Request | 0x04 | `EventCode.CONNECTION_REQUEST` |
| Connection_Complete | 0x03 | `EventCode.CONNECTION_COMPLETE` |
| Disconnection_Complete | 0x05 | `EventCode.DISCONNECTION_COMPLETE` |
| Authentication_Complete | 0x06 | `EventCode.AUTHENTICATION_COMPLETE` |
| Link_Key_Request | 0x17 | `EventCode.LINK_KEY_REQUEST` |
| Link_Key_Notification | 0x18 | `EventCode.LINK_KEY_NOTIFICATION` |
| PIN_Code_Request | 0x16 | `EventCode.PIN_CODE_REQUEST` |
| IO_Capability_Request | 0x31 | `EventCode.IO_CAPABILITY_REQUEST` |
| IO_Capability_Response | 0x32 | `EventCode.IO_CAPABILITY_RESPONSE` |
| User_Confirmation_Request | 0x33 | `EventCode.USER_CONFIRMATION_REQUEST` |
| Simple_Pairing_Complete | 0x36 | `EventCode.SIMPLE_PAIRING_COMPLETE` |
| Encryption_Change | 0x08 | `EventCode.ENCRYPTION_CHANGE` |

---

## Task 1: VirtualController hooks for the bridge

**Files:**
- Modify: `pybluehost/hci/virtual.py` (add `command_interceptor` attribute + scan-enable tracking + dispatch hook in `process()`)
- Test: `tests/integration/test_virtual_classic_link.py` (new file with skeleton + 2 tests for the new hooks)

The bridge needs two pieces of `VirtualController` machinery that don't exist today:
- A generic `command_interceptor: Optional[Callable[[opcode: int, raw_params: bytes], Awaitable[Optional[bytes]]]]` attribute. The hook is called at the top of `process()` (after the ACL branch). If the interceptor returns a non-None bytes value, that value is the HCI response sent to the host (typically `Command_Complete` or `Command_Status`). If it returns None, `process()` falls through to the default dispatch.
- Two scan-enable bits (`_inquiry_scan`, `_page_scan`) updated by an `HCI_Write_Scan_Enable` handler so the bridge can ask each side "are you currently discoverable?".

- [ ] **Step 1: Create the test file with a failing test**

Create `tests/integration/test_virtual_classic_link.py`:

```python
"""Per-primitive integration tests for VirtualClassicLink."""
from __future__ import annotations

import asyncio
import struct

import pytest

from pybluehost.hci.virtual import VirtualController


@pytest.mark.asyncio
async def test_virtual_controller_has_command_interceptor_attribute():
    vc = VirtualController()
    assert hasattr(vc, "command_interceptor")
    assert vc.command_interceptor is None


@pytest.mark.asyncio
async def test_virtual_controller_command_interceptor_runs_first():
    """When set, command_interceptor is called and its return value is used as
    the HCI response."""
    vc = VirtualController()
    seen: list = []

    async def _intercept(opcode: int, raw_params: bytes):
        seen.append((opcode, raw_params))
        # Return a synthetic Command_Complete that the test can recognize.
        return b"\x04\x05\x01\x00\x00\xCE\xCE"  # event_code=0x0E (CC), len=5, ncmd=1, opcode_lo, opcode_hi, status=0xCE

    vc.command_interceptor = _intercept
    # H4 command frame: type=01, opcode=0x040C (Set_Event_Filter as an arbitrary unused command), len=0
    frame = bytes([0x01, 0x0C, 0x04, 0x00])
    response = await vc.process(frame)
    assert seen and seen[0][0] == 0x040C
    assert response == b"\x04\x05\x01\x00\x00\xCE\xCE"


@pytest.mark.asyncio
async def test_virtual_controller_command_interceptor_passthrough_when_none():
    """When interceptor is unset (None), default dispatch runs."""
    vc = VirtualController()
    # HCI_Reset (0x0C03) → default dispatch produces a Command_Complete with status=0.
    frame = bytes([0x01, 0x03, 0x0C, 0x00])
    response = await vc.process(frame)
    assert response is not None
    # Command_Complete event_code=0x0E; status byte at offset 6 should be 0x00.
    assert response[0] == 0x04 and response[1] >= 4
```

Run: `uv run pytest tests/integration/test_virtual_classic_link.py -v`
Expected: FAIL — `command_interceptor` attribute missing.

- [ ] **Step 2: Add the `command_interceptor` attribute and dispatch hook**

In `pybluehost/hci/virtual.py`, add an attribute initialization in `VirtualController.__init__` (or wherever the other hooks like `_encryption_start_hook`, `_ltk_reply_hook` are declared — grep first to find the canonical site):

```python
self.command_interceptor = None   # type: Optional[Callable[[int, bytes], Awaitable[Optional[bytes]]]]
self._inquiry_scan = False
self._page_scan = False
```

In `VirtualController.process()`, after the ACL branch and the `if data[0] != HCI_COMMAND_PACKET: return None` guard, parse the opcode + raw_params, then call the interceptor BEFORE the default dispatch:

```python
opcode = struct.unpack_from("<H", data, 1)[0]
param_len = data[3]
raw_params = data[4 : 4 + param_len]

if self.command_interceptor is not None:
    result = await self.command_interceptor(opcode, raw_params)
    if result is not None:
        return result
    # interceptor returned None — fall through to default dispatch
```

Where existing code already extracts opcode/param_len after the guard, share that work (move the parse-once block above the interceptor call).

Verify the existing dispatch (encryption, default Command_Complete) still works for non-intercepted opcodes by NOT short-circuiting on `result is None` — only on a real bytes return.

- [ ] **Step 3: Add scan-enable tracking**

The handler for `HCI_Write_Scan_Enable` (opcode `0x1A` in OGF 0x03 → full opcode `0x0C1A`) reads the 1-byte scan-enable bitmap:
- bit 0 (mask 0x01): `inquiry_scan`
- bit 1 (mask 0x02): `page_scan`

Add inside `VirtualController.process()` BEFORE the default dispatch (and BEFORE the interceptor — interceptor returns None for this opcode so both can apply):

```python
if opcode == HCI_WRITE_SCAN_ENABLE and param_len >= 1:
    enable = raw_params[0]
    self._inquiry_scan = bool(enable & 0x01)
    self._page_scan = bool(enable & 0x02)
    # Allow the default dispatch to also build the Command_Complete reply.
```

Use the existing constant if `HCI_WRITE_SCAN_ENABLE` is defined; otherwise add it to `pybluehost/hci/constants.py` (grep first).

- [ ] **Step 4: Add a test for scan-enable tracking**

Append to `tests/integration/test_virtual_classic_link.py`:

```python
@pytest.mark.asyncio
async def test_virtual_controller_write_scan_enable_updates_flags():
    vc = VirtualController()
    assert vc._inquiry_scan is False and vc._page_scan is False
    # Write_Scan_Enable opcode = 0x0C1A; param = 0x03 (inquiry + page).
    frame = bytes([0x01, 0x1A, 0x0C, 0x01, 0x03])
    await vc.process(frame)
    assert vc._inquiry_scan is True
    assert vc._page_scan is True
    # Now disable inquiry, keep page.
    frame_disable_inquiry = bytes([0x01, 0x1A, 0x0C, 0x01, 0x02])
    await vc.process(frame_disable_inquiry)
    assert vc._inquiry_scan is False
    assert vc._page_scan is True
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/integration/test_virtual_classic_link.py -v`
Expected: all 4 PASS.

Run: `uv run pytest tests/integration/ -q --transport=virtual`
Expected: no regressions (existing tests still pass, including the LE bridge tests).

- [ ] **Step 6: Commit**

```bash
git add pybluehost/hci/virtual.py tests/integration/test_virtual_classic_link.py
git commit -m "feat(hci/virtual): command_interceptor hook + scan-enable tracking

Sub-Plan VirtualClassicLink Task 1. Adds:
  * VirtualController.command_interceptor: Optional[Callable[[opcode, raw_params],
    Awaitable[Optional[bytes]]]] — bridge entry point. Called at top of
    process() after ACL branch; non-None bytes returned become the HCI response;
    None falls through to default dispatch.
  * VirtualController._inquiry_scan / ._page_scan — tracked via the existing
    HCI_Write_Scan_Enable opcode; bridge uses these to decide discoverability."
```

---

## Task 2: VirtualClassicLink skeleton

**Files:**
- Create: `pybluehost/hci/virtual_classic_link.py`
- Test: `tests/integration/test_virtual_classic_link.py` (append)

Establishes the class shell that subsequent tasks fill in. Provides:
- `_ConnState` enum
- per-handle state table
- handle allocator
- `connect()` / `disconnect()` lifecycle (currently a no-op skeleton; sub-bridges flesh out)
- `attach()` / `detach()` to install the bridge's `command_interceptor` on both controllers

- [ ] **Step 1: Append failing test**

```python
from pybluehost.hci.virtual_classic_link import VirtualClassicLink, _ConnState
from pybluehost.core.address import BDAddress


@pytest.mark.asyncio
async def test_virtual_classic_link_construction_attaches_interceptors():
    """Constructing the bridge installs command_interceptor on both controllers."""
    central = VirtualController()
    peripheral = VirtualController()
    addr_c = BDAddress(b"\x0A" * 6)
    addr_p = BDAddress(b"\x0B" * 6)
    link = VirtualClassicLink(
        central=central, peripheral=peripheral,
        central_address=addr_c, peripheral_address=addr_p,
    )
    link.attach()
    assert central.command_interceptor is not None
    assert peripheral.command_interceptor is not None
    link.detach()
    assert central.command_interceptor is None
    assert peripheral.command_interceptor is None


def test_conn_state_enum_values():
    assert _ConnState.NONE == 0
    assert _ConnState.PENDING == 1
    assert _ConnState.CONNECTED == 2
    assert _ConnState.DISCONNECTING == 3
```

- [ ] **Step 2: Create the skeleton**

Create `pybluehost/hci/virtual_classic_link.py`:

```python
"""BR/EDR (Classic) loopback bridge: two VirtualControllers paired peer-to-peer.

Counterpart to VirtualLELink. Bridges inquiry, connection, ACL, SSP/Legacy
authentication, encryption, and disconnect HCI events so that two Stack.virtual()
instances can complete real peer-to-peer Classic workflows end-to-end.
"""
from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    EventCode,
    # Bridge-intercepted opcodes; if any are missing, add them in constants.py.
    HCI_INQUIRY,
    HCI_INQUIRY_CANCEL,
    HCI_CREATE_CONNECTION,
    HCI_ACCEPT_CONNECTION_REQUEST,
    HCI_REJECT_CONNECTION_REQUEST,
    HCI_DISCONNECT,
    HCI_AUTHENTICATION_REQUESTED,
    HCI_LINK_KEY_REQUEST_REPLY,
    HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY,
    HCI_IO_CAPABILITY_REQUEST_REPLY,
    HCI_USER_CONFIRMATION_REQUEST_REPLY,
    HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY,
    HCI_PIN_CODE_REQUEST_REPLY,
    HCI_PIN_CODE_REQUEST_NEGATIVE_REPLY,
    HCI_SET_CONNECTION_ENCRYPTION,
)
from pybluehost.hci.packets import HCIACLData, HCIEvent
from pybluehost.hci.virtual import VirtualController


class _ConnState(IntEnum):
    NONE = 0
    PENDING = 1
    CONNECTED = 2
    DISCONNECTING = 3


@dataclass
class _ConnEntry:
    handle: int
    state: _ConnState
    initiator: VirtualController            # which side called Create_Connection
    initiator_addr: BDAddress
    acceptor: VirtualController
    acceptor_addr: BDAddress


@dataclass
class VirtualClassicLink:
    """Two-controller BR/EDR bridge. See module docstring."""

    central: VirtualController
    peripheral: VirtualController
    central_address: BDAddress
    peripheral_address: BDAddress
    page_timeout_seconds: float = 0.1     # short for tests; real default is 5.12s
    _handles: dict[int, _ConnEntry] = field(default_factory=dict, init=False)
    _next_handle: int = field(default=0x0040, init=False)
    _attached: bool = field(default=False, init=False)

    # -- Lifecycle ---------------------------------------------------------

    def attach(self) -> None:
        """Install command_interceptor on both controllers."""
        self.central.command_interceptor = self._make_interceptor(self.central)
        self.peripheral.command_interceptor = self._make_interceptor(self.peripheral)
        # ACL forwarders
        self.central.set_acl_forwarder(self._forward_central_to_peripheral)
        self.peripheral.set_acl_forwarder(self._forward_peripheral_to_central)
        self._attached = True

    def detach(self) -> None:
        """Remove command_interceptors; release all handles."""
        self.central.command_interceptor = None
        self.peripheral.command_interceptor = None
        self.central.set_acl_forwarder(None)
        self.peripheral.set_acl_forwarder(None)
        self._handles.clear()
        self._attached = False

    async def disconnect(self) -> None:
        """Tear down all connected/pending handles; emit appropriate completion events.

        Subsequent tasks add the per-state event emission. For Task 2 this is a
        no-op stub that the smoke E2E and DisconnectBridge task (Task 8) will fill.
        """
        for entry in list(self._handles.values()):
            # Task 8 fills this in with full event emission.
            pass
        self.detach()

    # -- Internals ---------------------------------------------------------

    def _allocate_handle(self) -> int:
        h = self._next_handle
        self._next_handle += 1
        return h

    def _peer_of(self, controller: VirtualController) -> VirtualController:
        return self.peripheral if controller is self.central else self.central

    def _addr_of(self, controller: VirtualController) -> BDAddress:
        return (
            self.central_address if controller is self.central
            else self.peripheral_address
        )

    def _make_interceptor(self, controller: VirtualController):
        """Build a command_interceptor closure bound to `controller`.

        Returns an async function with the signature (opcode, raw_params) ->
        Optional[bytes]. The default implementation returns None for all opcodes,
        letting VirtualController's default dispatch run. Subsequent tasks add
        per-opcode branches that intercept and return synthetic responses.
        """

        async def _intercept(opcode: int, raw_params: bytes) -> Optional[bytes]:
            # Tasks 3-8 add per-opcode handling here.
            return None

        return _intercept

    # -- ACL forwarders ----------------------------------------------------

    async def _forward_central_to_peripheral(self, acl: HCIACLData) -> None:
        await self._forward_acl(self.central, acl)

    async def _forward_peripheral_to_central(self, acl: HCIACLData) -> None:
        await self._forward_acl(self.peripheral, acl)

    async def _forward_acl(self, source: VirtualController, acl: HCIACLData) -> None:
        """Forward ACL from source to peer if handle is CONNECTED. Drop silently otherwise."""
        entry = self._handles.get(acl.handle)
        if entry is None or entry.state != _ConnState.CONNECTED:
            return
        peer = self._peer_of(source)
        await peer._inject_acl_to_host(acl)
```

- [ ] **Step 3: Add `HCI_*` constants if missing**

Run: `grep -n "HCI_INQUIRY\b\|HCI_CREATE_CONNECTION\|HCI_ACCEPT_CONNECTION\|HCI_REJECT_CONNECTION\|HCI_DISCONNECT\|HCI_AUTHENTICATION_REQUESTED\|HCI_LINK_KEY_REQUEST_REPLY\|HCI_IO_CAPABILITY_REQUEST_REPLY\|HCI_USER_CONFIRMATION_REQUEST_REPLY\|HCI_PIN_CODE_REQUEST_REPLY\|HCI_SET_CONNECTION_ENCRYPTION\|HCI_WRITE_SCAN_ENABLE" pybluehost/hci/constants.py`

For each missing constant, add it to `constants.py` using the OGF/OCF → opcode formula `(OGF << 10) | OCF`. The reference table at the top of this Plan has the OGF/OCF values. Example:

```python
HCI_INQUIRY = (0x01 << 10) | 0x0001              # 0x0401
HCI_CREATE_CONNECTION = (0x01 << 10) | 0x0005    # 0x0405
HCI_ACCEPT_CONNECTION_REQUEST = (0x01 << 10) | 0x0009   # 0x0409
HCI_REJECT_CONNECTION_REQUEST = (0x01 << 10) | 0x000A   # 0x040A
HCI_DISCONNECT = (0x01 << 10) | 0x0006           # 0x0406
HCI_AUTHENTICATION_REQUESTED = (0x01 << 10) | 0x0011   # 0x0411
HCI_LINK_KEY_REQUEST_REPLY = (0x01 << 10) | 0x000B
HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY = (0x01 << 10) | 0x000C
HCI_IO_CAPABILITY_REQUEST_REPLY = (0x01 << 10) | 0x002B
HCI_USER_CONFIRMATION_REQUEST_REPLY = (0x01 << 10) | 0x002C
HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY = (0x01 << 10) | 0x002D
HCI_PIN_CODE_REQUEST_REPLY = (0x01 << 10) | 0x000D
HCI_PIN_CODE_REQUEST_NEGATIVE_REPLY = (0x01 << 10) | 0x000E
HCI_SET_CONNECTION_ENCRYPTION = (0x01 << 10) | 0x0013
HCI_WRITE_SCAN_ENABLE = (0x03 << 10) | 0x001A    # 0x0C1A
```

Also confirm `EventCode` has `INQUIRY_RESULT`, `INQUIRY_COMPLETE`, `CONNECTION_REQUEST`, `CONNECTION_COMPLETE`, `DISCONNECTION_COMPLETE`, `AUTHENTICATION_COMPLETE`, `LINK_KEY_REQUEST`, `LINK_KEY_NOTIFICATION`, `PIN_CODE_REQUEST`, `IO_CAPABILITY_REQUEST`, `IO_CAPABILITY_RESPONSE`, `USER_CONFIRMATION_REQUEST`, `SIMPLE_PAIRING_COMPLETE`, `ENCRYPTION_CHANGE`. Add any missing.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/integration/test_virtual_classic_link.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/hci/virtual_classic_link.py pybluehost/hci/constants.py tests/integration/test_virtual_classic_link.py
git commit -m "feat(hci): VirtualClassicLink skeleton (state machine + lifecycle)

Sub-Plan VirtualClassicLink Task 2. Adds:
  * VirtualClassicLink class with _ConnState enum, per-handle state table,
    handle allocator, attach()/detach() lifecycle, ACL forwarders.
  * Bridge command_interceptor closure is a no-op for now; Tasks 3-8 add
    per-opcode branches.
  * HCI command opcode + event code constants added to constants.py."
```

---

## Task 3: InquiryBridge

**Files:**
- Modify: `pybluehost/hci/virtual_classic_link.py`
- Test: `tests/integration/test_virtual_classic_link.py`

InquiryBridge handles `HCI_Inquiry` and `HCI_Inquiry_Cancel`. When stack A runs inquiry, the bridge checks whether stack B has `inquiry_scan=True` (set via `HCI_Write_Scan_Enable`). If yes → emit `Inquiry_Result` to A with B's BD_ADDR, then `Inquiry_Complete`. If no → only `Inquiry_Complete` with empty result.

- [ ] **Step 1: Append failing tests**

```python
async def _h4_cmd(opcode: int, params: bytes = b"") -> bytes:
    return bytes([0x01]) + struct.pack("<H", opcode) + bytes([len(params)]) + params


async def _make_linked_pair(*, peer_discoverable: bool = True):
    """Create two VirtualControllers + bridge; optionally make peripheral discoverable."""
    c = VirtualController()
    p = VirtualController()
    addr_c = BDAddress(b"\x0A" * 6)
    addr_p = BDAddress(b"\x0B" * 6)
    link = VirtualClassicLink(
        central=c, peripheral=p,
        central_address=addr_c, peripheral_address=addr_p,
    )
    link.attach()
    if peer_discoverable:
        # Write_Scan_Enable = 0x03 (inquiry + page)
        await p.process(await _h4_cmd(0x0C1A, bytes([0x03])))
    return c, p, addr_c, addr_p, link


def _capture_events(vc: VirtualController) -> list[HCIEvent]:
    """Install a host-side sink that records all events the controller emits."""
    captured: list[HCIEvent] = []

    class _Sink:
        async def on_transport_data(self, data: bytes):
            # Strip the H4 indicator + parse HCIEvent.
            from pybluehost.hci.packets import HCIEvent as _HE
            if data and data[0] == 0x04:  # event packet
                event = _HE(event_code=data[1], parameters=data[3:3 + data[2]])
                captured.append(event)

    vc._host_sink = _Sink()
    return captured


@pytest.mark.asyncio
async def test_inquiry_discovers_discoverable_peer():
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=True)
    events_c = _capture_events(c)
    # HCI_Inquiry params: LAP(3) + Inquiry_Length(1) + Num_Responses(1)
    inquiry_params = bytes([0x33, 0x8B, 0x9E, 0x08, 0x00])
    await c.process(await _h4_cmd(0x0401, inquiry_params))
    await asyncio.sleep(0.05)
    inquiry_results = [e for e in events_c if e.event_code == int(EventCode.INQUIRY_RESULT)]
    assert len(inquiry_results) == 1
    # Inquiry_Result params: num(1) + BD_ADDR(6) + page_scan_repetition(1) + reserved(2) + cod(3) + clock_offset(2)
    body = inquiry_results[0].parameters
    assert body[0] == 1  # num devices
    assert body[1:7] == addr_p.address
    inquiry_completes = [e for e in events_c if e.event_code == int(EventCode.INQUIRY_COMPLETE)]
    assert len(inquiry_completes) == 1


@pytest.mark.asyncio
async def test_inquiry_skips_non_discoverable_peer():
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=False)
    events_c = _capture_events(c)
    await c.process(await _h4_cmd(0x0401, bytes([0x33, 0x8B, 0x9E, 0x08, 0x00])))
    await asyncio.sleep(0.05)
    assert not [e for e in events_c if e.event_code == int(EventCode.INQUIRY_RESULT)]
    completes = [e for e in events_c if e.event_code == int(EventCode.INQUIRY_COMPLETE)]
    assert len(completes) == 1


@pytest.mark.asyncio
async def test_inquiry_cancel_completes_with_cancelled_status():
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=True)
    events_c = _capture_events(c)
    await c.process(await _h4_cmd(0x0402))  # Inquiry_Cancel
    await asyncio.sleep(0.05)
    completes = [e for e in events_c if e.event_code == int(EventCode.INQUIRY_COMPLETE)]
    assert len(completes) == 1
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/integration/test_virtual_classic_link.py -k inquiry -v`
Expected: FAIL — interceptor doesn't handle inquiry yet.

- [ ] **Step 3: Implement InquiryBridge inside `_make_interceptor`**

Replace the no-op body in `_make_interceptor` with the InquiryBridge branch. Open `pybluehost/hci/virtual_classic_link.py` and update:

```python
def _make_interceptor(self, controller: VirtualController):
    async def _intercept(opcode: int, raw_params: bytes) -> Optional[bytes]:
        # --- InquiryBridge ---
        if opcode == HCI_INQUIRY:
            asyncio.create_task(self._inquiry(controller))
            return self._command_status(opcode, status=0)
        if opcode == HCI_INQUIRY_CANCEL:
            asyncio.create_task(self._inquiry_complete(controller, num_responses=0))
            return self._command_complete(opcode, b"\x00")  # status=0

        # (Tasks 4-8 fill in remaining opcodes here)
        return None

    return _intercept
```

Add the supporting methods on `VirtualClassicLink`:

```python
def _command_complete(self, opcode: int, return_params: bytes) -> bytes:
    """Build a Command_Complete event (H4 wrapped)."""
    body = bytes([0x01]) + struct.pack("<H", opcode) + return_params
    return bytes([0x04, int(EventCode.COMMAND_COMPLETE), len(body)]) + body

def _command_status(self, opcode: int, status: int = 0) -> bytes:
    """Build a Command_Status event (H4 wrapped)."""
    body = bytes([status, 0x01]) + struct.pack("<H", opcode)
    return bytes([0x04, int(EventCode.COMMAND_STATUS), len(body)]) + body


async def _inquiry(self, initiator: VirtualController) -> None:
    """Emit Inquiry_Result for the peer (if discoverable) then Inquiry_Complete."""
    peer = self._peer_of(initiator)
    peer_addr = self.peripheral_address if initiator is self.central else self.central_address
    if peer._inquiry_scan:
        # Inquiry_Result event:
        # num_responses(1) + BD_ADDR(6) + page_scan_repetition_mode(1)
        # + reserved(2) + class_of_device(3) + clock_offset(2)
        body = (
            bytes([0x01])
            + peer_addr.address
            + bytes([0x01])  # page_scan_repetition_mode R1
            + bytes([0x00, 0x00])  # reserved
            + bytes([0x00, 0x00, 0x00])  # class_of_device (unspecified)
            + bytes([0x00, 0x00])  # clock_offset
        )
        event = HCIEvent(event_code=int(EventCode.INQUIRY_RESULT), parameters=body)
        await initiator._send_event_to_host(event)
    await self._inquiry_complete(initiator, num_responses=1 if peer._inquiry_scan else 0)


async def _inquiry_complete(self, initiator: VirtualController, *, num_responses: int) -> None:
    body = bytes([0x00])  # status = 0
    event = HCIEvent(event_code=int(EventCode.INQUIRY_COMPLETE), parameters=body)
    await initiator._send_event_to_host(event)
```

Add `EventCode.COMMAND_COMPLETE` and `EventCode.COMMAND_STATUS` to the imports if they aren't there. Verify both event-code values exist in `pybluehost/hci/constants.py` (they should — they're already used by the existing dispatcher).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/integration/test_virtual_classic_link.py -k inquiry -v`
Expected: 3 PASS.

Run: `uv run pytest tests/integration/ -q --transport=virtual`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/hci/virtual_classic_link.py tests/integration/test_virtual_classic_link.py
git commit -m "feat(hci/virtual_classic_link): InquiryBridge

Sub-Plan VirtualClassicLink Task 3. HCI_Inquiry on initiator emits an
Inquiry_Result for the peer iff peer's inquiry_scan is enabled (set via
HCI_Write_Scan_Enable from the host); always emits a final Inquiry_Complete.
HCI_Inquiry_Cancel emits Inquiry_Complete immediately. The interceptor
returns Command_Status for Inquiry (per spec — Inquiry is a long-running
command) and Command_Complete for Inquiry_Cancel."
```

---

## Task 4: ConnectionBridge

**Files:**
- Modify: `pybluehost/hci/virtual_classic_link.py`
- Test: `tests/integration/test_virtual_classic_link.py`

Implements `HCI_Create_Connection`, `HCI_Accept_Connection_Request`, `HCI_Reject_Connection_Request`, and the page-timeout case.

- [ ] **Step 1: Append failing tests**

```python
def _parse_handle(event: HCIEvent) -> int:
    # Connection_Complete params: status(1) + handle(2) + bd_addr(6) + ...
    return struct.unpack_from("<H", event.parameters, 1)[0]


@pytest.mark.asyncio
async def test_create_connection_succeeds_when_page_scan_enabled():
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=True)
    events_c = _capture_events(c)
    events_p = _capture_events(p)

    # Create_Connection params: BD_ADDR(6) + Packet_Type(2) + PSRM(1) + reserved(1) + Clock_Offset(2) + Allow_Role_Switch(1)
    create_params = (
        addr_p.address
        + struct.pack("<H", 0xCC18)
        + bytes([0x01, 0x00])
        + bytes([0x00, 0x00])
        + bytes([0x01])
    )
    await c.process(await _h4_cmd(0x0405, create_params))
    await asyncio.sleep(0.05)
    requests = [e for e in events_p if e.event_code == int(EventCode.CONNECTION_REQUEST)]
    assert len(requests) == 1

    # Peripheral host responds with Accept_Connection_Request (params: BD_ADDR + role(1)=slave)
    accept_params = addr_c.address + bytes([0x01])
    await p.process(await _h4_cmd(0x0409, accept_params))
    await asyncio.sleep(0.05)
    completes_c = [e for e in events_c if e.event_code == int(EventCode.CONNECTION_COMPLETE)]
    completes_p = [e for e in events_p if e.event_code == int(EventCode.CONNECTION_COMPLETE)]
    assert len(completes_c) == 1 and len(completes_p) == 1
    assert _parse_handle(completes_c[0]) == _parse_handle(completes_p[0])
    # Status byte at offset 0 should be 0 on both.
    assert completes_c[0].parameters[0] == 0 and completes_p[0].parameters[0] == 0


@pytest.mark.asyncio
async def test_create_connection_page_timeout_when_page_scan_disabled():
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=False)
    # Force a known page timeout for the test
    link.page_timeout_seconds = 0.05
    events_c = _capture_events(c)
    create_params = (
        addr_p.address
        + struct.pack("<H", 0xCC18)
        + bytes([0x01, 0x00, 0x00, 0x00, 0x01])
    )
    await c.process(await _h4_cmd(0x0405, create_params))
    await asyncio.sleep(0.2)
    completes = [e for e in events_c if e.event_code == int(EventCode.CONNECTION_COMPLETE)]
    assert len(completes) == 1
    assert completes[0].parameters[0] == 0x04  # Page Timeout


@pytest.mark.asyncio
async def test_reject_connection_emits_status_error():
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=True)
    events_c = _capture_events(c)
    create_params = addr_p.address + struct.pack("<H", 0xCC18) + bytes([0x01, 0x00, 0x00, 0x00, 0x01])
    await c.process(await _h4_cmd(0x0405, create_params))
    await asyncio.sleep(0.05)

    # Peripheral host rejects: Reject_Connection_Request (BD_ADDR + reason(1))
    reject_params = addr_c.address + bytes([0x0D])  # Connection_Rejected_Limited_Resources
    await p.process(await _h4_cmd(0x040A, reject_params))
    await asyncio.sleep(0.05)
    completes = [e for e in events_c if e.event_code == int(EventCode.CONNECTION_COMPLETE)]
    assert len(completes) == 1
    assert completes[0].parameters[0] == 0x0D
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/integration/test_virtual_classic_link.py -k create_connection -v`
Expected: FAIL.

- [ ] **Step 3: Extend the interceptor**

In `_make_interceptor`'s `_intercept` function, after the InquiryBridge branch:

```python
        # --- ConnectionBridge ---
        if opcode == HCI_CREATE_CONNECTION:
            # raw_params: BD_ADDR(6) + ...
            peer_addr_bytes = raw_params[0:6]
            asyncio.create_task(self._create_connection(controller, peer_addr_bytes))
            return self._command_status(opcode, status=0)

        if opcode == HCI_ACCEPT_CONNECTION_REQUEST:
            peer_addr_bytes = raw_params[0:6]
            asyncio.create_task(self._accept_connection(controller, peer_addr_bytes))
            return self._command_status(opcode, status=0)

        if opcode == HCI_REJECT_CONNECTION_REQUEST:
            peer_addr_bytes = raw_params[0:6]
            reason = raw_params[6] if len(raw_params) > 6 else 0x0D
            asyncio.create_task(self._reject_connection(controller, peer_addr_bytes, reason))
            return self._command_status(opcode, status=0)
```

Add these methods to `VirtualClassicLink`:

```python
async def _create_connection(self, initiator: VirtualController, peer_addr_bytes: bytes) -> None:
    """Page the peer; if peer.page_scan, emit Connection_Request; else schedule Page_Timeout."""
    peer = self._peer_of(initiator)
    if not peer._page_scan:
        await asyncio.sleep(self.page_timeout_seconds)
        await self._emit_connection_complete(
            initiator, status=0x04, handle=0x0000, peer_addr=BDAddress(peer_addr_bytes),
        )
        return

    # Allocate handle and PENDING state
    handle = self._allocate_handle()
    peer_addr = BDAddress(peer_addr_bytes)
    initiator_addr = self._addr_of(initiator)
    self._handles[handle] = _ConnEntry(
        handle=handle, state=_ConnState.PENDING,
        initiator=initiator, initiator_addr=initiator_addr,
        acceptor=peer, acceptor_addr=peer_addr,
    )
    # Emit Connection_Request to peer host:
    # BD_ADDR(6) + Class_Of_Device(3) + Link_Type(1)
    body = initiator_addr.address + bytes([0x00, 0x00, 0x00, 0x01])  # ACL link
    event = HCIEvent(event_code=int(EventCode.CONNECTION_REQUEST), parameters=body)
    await peer._send_event_to_host(event)


async def _accept_connection(self, acceptor: VirtualController, peer_addr_bytes: bytes) -> None:
    """Match the PENDING entry where this acceptor is the peer, set CONNECTED, emit both."""
    entry = next(
        (e for e in self._handles.values()
         if e.state == _ConnState.PENDING and e.acceptor is acceptor),
        None,
    )
    if entry is None:
        return
    entry.state = _ConnState.CONNECTED
    await asyncio.gather(
        self._emit_connection_complete(
            entry.initiator, status=0, handle=entry.handle, peer_addr=entry.acceptor_addr,
        ),
        self._emit_connection_complete(
            entry.acceptor, status=0, handle=entry.handle, peer_addr=entry.initiator_addr,
        ),
    )


async def _reject_connection(
    self, acceptor: VirtualController, peer_addr_bytes: bytes, reason: int,
) -> None:
    entry = next(
        (e for e in self._handles.values()
         if e.state == _ConnState.PENDING and e.acceptor is acceptor),
        None,
    )
    if entry is None:
        return
    await self._emit_connection_complete(
        entry.initiator, status=reason, handle=0x0000, peer_addr=entry.acceptor_addr,
    )
    del self._handles[entry.handle]


async def _emit_connection_complete(
    self, controller: VirtualController, *,
    status: int, handle: int, peer_addr: BDAddress,
) -> None:
    """Build and send Connection_Complete event."""
    body = (
        bytes([status])
        + struct.pack("<H", handle)
        + peer_addr.address
        + bytes([0x01, 0x00])  # link_type=ACL, encryption_mode=disabled
    )
    event = HCIEvent(event_code=int(EventCode.CONNECTION_COMPLETE), parameters=body)
    await controller._send_event_to_host(event)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/integration/test_virtual_classic_link.py -v`
Expected: all PASS (Tasks 1-4 tests).

- [ ] **Step 5: Commit**

```bash
git add pybluehost/hci/virtual_classic_link.py tests/integration/test_virtual_classic_link.py
git commit -m "feat(hci/virtual_classic_link): ConnectionBridge

Sub-Plan VirtualClassicLink Task 4. HCI_Create_Connection allocates a
handle, sets PENDING, emits Connection_Request to peer (if peer.page_scan).
If peer is not page-scannable, emits Connection_Complete(status=0x04
Page_Timeout) after page_timeout_seconds (default 0.1s, configurable).
HCI_Accept_Connection_Request transitions to CONNECTED and emits
Connection_Complete to both sides with the same handle.
HCI_Reject_Connection_Request emits Connection_Complete with the supplied
reason status to the initiator only and releases the handle."
```

---

## Task 5: ACLBridge

**Files:**
- Modify: `pybluehost/hci/virtual_classic_link.py`
- Test: `tests/integration/test_virtual_classic_link.py`

ACL forwarders were already wired in Task 2 (`set_acl_forwarder(self._forward_central_to_peripheral)` etc.). The existing `_forward_acl()` correctly checks for `CONNECTED` state. Task 5 adds tests that exercise the forwarder paths and the disconnected-handle drop behavior. No new production code.

- [ ] **Step 1: Append failing tests**

```python
@pytest.mark.asyncio
async def test_acl_data_routes_a_to_b():
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=True)
    # Establish a connection so a handle exists in CONNECTED.
    create_params = addr_p.address + struct.pack("<H", 0xCC18) + bytes([0x01, 0x00, 0x00, 0x00, 0x01])
    await c.process(await _h4_cmd(0x0405, create_params))
    await asyncio.sleep(0.05)
    await p.process(await _h4_cmd(0x0409, addr_c.address + bytes([0x01])))
    await asyncio.sleep(0.05)

    handle = next(iter(link._handles.values())).handle

    # Capture ACL data injected to peripheral.
    p_received: list[bytes] = []

    async def _capture(data: bytes):
        if data and data[0] == 0x02:  # ACL packet
            p_received.append(data)

    class _PSink:
        async def on_transport_data(self, data: bytes):
            await _capture(data)

    p._host_sink = _PSink()

    # Build an ACL packet from the central side: header h_f + length + data
    handle_flags = handle | (0x02 << 12)  # PB flag 02 = first non-flushable
    payload = b"\x04\x00\x40\x00\x12\x34\x56\x78"  # L2CAP signaling-ish frame
    acl_frame = (
        bytes([0x02])
        + struct.pack("<H", handle_flags)
        + struct.pack("<H", len(payload))
        + payload
    )
    await c.process(acl_frame)
    await asyncio.sleep(0.05)
    assert len(p_received) == 1
    # The peripheral should have received the same payload back (handle stays, payload preserved)
    assert payload in p_received[0]


@pytest.mark.asyncio
async def test_acl_data_routes_b_to_a():
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=True)
    create_params = addr_p.address + struct.pack("<H", 0xCC18) + bytes([0x01, 0x00, 0x00, 0x00, 0x01])
    await c.process(await _h4_cmd(0x0405, create_params))
    await asyncio.sleep(0.05)
    await p.process(await _h4_cmd(0x0409, addr_c.address + bytes([0x01])))
    await asyncio.sleep(0.05)

    handle = next(iter(link._handles.values())).handle
    c_received: list[bytes] = []

    class _CSink:
        async def on_transport_data(self, data: bytes):
            if data and data[0] == 0x02:
                c_received.append(data)

    c._host_sink = _CSink()

    payload = b"\xAB\xCD\xEF"
    acl = (
        bytes([0x02])
        + struct.pack("<H", handle | (0x02 << 12))
        + struct.pack("<H", len(payload))
        + payload
    )
    await p.process(acl)
    await asyncio.sleep(0.05)
    assert len(c_received) == 1
    assert payload in c_received[0]


@pytest.mark.asyncio
async def test_acl_on_disconnected_handle_drops_silently():
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=True)
    p_received: list[bytes] = []

    class _PSink:
        async def on_transport_data(self, data: bytes):
            if data and data[0] == 0x02:
                p_received.append(data)

    p._host_sink = _PSink()

    # No connection established; send ACL on a fake handle.
    payload = b"\x00\x00"
    acl = (
        bytes([0x02])
        + struct.pack("<H", 0x0040 | (0x02 << 12))
        + struct.pack("<H", len(payload))
        + payload
    )
    await c.process(acl)
    await asyncio.sleep(0.05)
    assert p_received == []
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/integration/test_virtual_classic_link.py -k acl -v`
Expected: PASS (`_forward_acl` from Task 2 already handles all three cases).

If any fail because the ACL path needs additional plumbing (e.g., the bridge's `acl_forwarder` is not being called because the existing `_acl_forwarder` is replaced when `attach()` runs), the implementer adapts.

- [ ] **Step 3: If tests pass without code changes, commit them**

```bash
git add tests/integration/test_virtual_classic_link.py
git commit -m "test(hci/virtual_classic_link): ACLBridge — forward both directions + drop on disconnected handle

Sub-Plan VirtualClassicLink Task 5. ACL routing was wired in Task 2 via
_forward_acl. These tests validate that ACL frames flow A→B and B→A on a
CONNECTED handle, and silently drop on a non-existent / disconnected
handle (no exception, no spurious event)."
```

If any test failed and required production-code adjustments, include those files in the commit and note the fix in the commit message.

---

## Task 6: AuthBridge

**Files:**
- Modify: `pybluehost/hci/virtual_classic_link.py`
- Test: `tests/integration/test_virtual_classic_link.py`

AuthBridge handles the SSP + Legacy authentication event flow. Forwards `Link_Key_Request`, `IO_Capability_Request/Response`, `User_Confirmation_Request`, `Simple_Pairing_Complete`, `Authentication_Complete`, `Link_Key_Notification`.

The simplest model: when an HCI command from one side would normally produce an event reply on the same side (Link_Key_Request_Reply, IO_Capability_Request_Reply, etc.), the bridge instead routes a corresponding event to the peer side OR emits a synthesized completion event to both sides.

**Concrete flow** (matches §4 data flow in the spec):

1. Initiator sends `HCI_Authentication_Requested(handle)` → bridge emits `Link_Key_Request` to initiator.
2. Initiator replies `HCI_Link_Key_Request_Negative_Reply` (no stored key) → bridge emits `IO_Capability_Request` to BOTH sides (initiator + acceptor).
3. Each side replies `HCI_IO_Capability_Request_Reply(BD_ADDR, io_cap, auth_req)` → bridge forwards as `IO_Capability_Response` to the peer.
4. After both IO_Capability_Responses delivered, bridge emits `User_Confirmation_Request(numeric_value=0)` to BOTH (JW path).
5. Each side replies `HCI_User_Confirmation_Request_Reply(BD_ADDR)` → bridge tracks both replies; once both accepted, emits `Simple_Pairing_Complete(status=0)` to both, then `Link_Key_Notification(BD_ADDR_of_peer, key_type=0x05, link_key)` to both. The link_key is deterministic from sorted (initiator_addr, acceptor_addr).
6. Finally bridge emits `Authentication_Complete(status=0, handle)` to the initiator only.

If either side replies `Negative_Reply`, bridge emits `Simple_Pairing_Complete(status=0x05)` then `Authentication_Complete(status=0x05)` to initiator; no link key notification.

- [ ] **Step 1: Append failing tests**

```python
async def _establish_connection(c, p, addr_c, addr_p):
    """Helper: bring up a CONNECTED handle between c and p."""
    create_params = addr_p.address + struct.pack("<H", 0xCC18) + bytes([0x01, 0x00, 0x00, 0x00, 0x01])
    await c.process(await _h4_cmd(0x0405, create_params))
    await asyncio.sleep(0.02)
    await p.process(await _h4_cmd(0x0409, addr_c.address + bytes([0x01])))
    await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_link_key_request_routes_to_initiator():
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=True)
    await _establish_connection(c, p, addr_c, addr_p)
    events_c = _capture_events(c)
    # Initiator triggers authentication: HCI_Authentication_Requested(handle)
    handle = next(iter(link._handles.values())).handle
    await c.process(await _h4_cmd(0x0411, struct.pack("<H", handle)))
    await asyncio.sleep(0.05)
    lkr = [e for e in events_c if e.event_code == int(EventCode.LINK_KEY_REQUEST)]
    assert len(lkr) == 1
    # Body: BD_ADDR(6); should be peer's address
    assert lkr[0].parameters[0:6] == addr_p.address


@pytest.mark.asyncio
async def test_io_capability_round_trip():
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=True)
    await _establish_connection(c, p, addr_c, addr_p)
    events_c = _capture_events(c)
    events_p = _capture_events(p)
    handle = next(iter(link._handles.values())).handle
    await c.process(await _h4_cmd(0x0411, struct.pack("<H", handle)))
    await asyncio.sleep(0.02)
    # Initiator: no stored key
    await c.process(await _h4_cmd(0x040C, addr_p.address))
    await asyncio.sleep(0.05)
    # Both sides should now see IO_Capability_Request
    iocr_c = [e for e in events_c if e.event_code == int(EventCode.IO_CAPABILITY_REQUEST)]
    iocr_p = [e for e in events_p if e.event_code == int(EventCode.IO_CAPABILITY_REQUEST)]
    assert len(iocr_c) == 1 and len(iocr_p) == 1

    # Both reply with IO_Capability_Request_Reply (BD_ADDR + io_cap + oob_data + auth_req)
    await c.process(await _h4_cmd(0x042B, addr_p.address + bytes([0x03, 0x00, 0x00])))
    await p.process(await _h4_cmd(0x042B, addr_c.address + bytes([0x03, 0x00, 0x00])))
    await asyncio.sleep(0.05)
    iocres_c = [e for e in events_c if e.event_code == int(EventCode.IO_CAPABILITY_RESPONSE)]
    iocres_p = [e for e in events_p if e.event_code == int(EventCode.IO_CAPABILITY_RESPONSE)]
    assert len(iocres_c) == 1 and len(iocres_p) == 1


@pytest.mark.asyncio
async def test_user_confirmation_negative_reply_fails_pairing():
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=True)
    await _establish_connection(c, p, addr_c, addr_p)
    events_c = _capture_events(c)
    events_p = _capture_events(p)
    handle = next(iter(link._handles.values())).handle
    await c.process(await _h4_cmd(0x0411, struct.pack("<H", handle)))
    await c.process(await _h4_cmd(0x040C, addr_p.address))
    await asyncio.sleep(0.02)
    await c.process(await _h4_cmd(0x042B, addr_p.address + bytes([0x03, 0x00, 0x00])))
    await p.process(await _h4_cmd(0x042B, addr_c.address + bytes([0x03, 0x00, 0x00])))
    await asyncio.sleep(0.05)
    # Now both should see User_Confirmation_Request (JW)
    ucr_c = [e for e in events_c if e.event_code == int(EventCode.USER_CONFIRMATION_REQUEST)]
    ucr_p = [e for e in events_p if e.event_code == int(EventCode.USER_CONFIRMATION_REQUEST)]
    assert len(ucr_c) == 1 and len(ucr_p) == 1
    # Peripheral rejects via Negative_Reply
    await p.process(await _h4_cmd(0x042D, addr_c.address))
    await asyncio.sleep(0.05)
    spc_c = [e for e in events_c if e.event_code == int(EventCode.SIMPLE_PAIRING_COMPLETE)]
    spc_p = [e for e in events_p if e.event_code == int(EventCode.SIMPLE_PAIRING_COMPLETE)]
    assert len(spc_c) == 1 and len(spc_p) == 1
    assert spc_c[0].parameters[0] == 0x05  # Auth_Failure
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/integration/test_virtual_classic_link.py -k "link_key_request or io_capability or user_confirmation" -v`
Expected: FAIL.

- [ ] **Step 3: Implement AuthBridge in the interceptor**

Add to `_intercept` (continue after ConnectionBridge):

```python
        # --- AuthBridge ---
        if opcode == HCI_AUTHENTICATION_REQUESTED:
            handle = struct.unpack_from("<H", raw_params, 0)[0]
            entry = self._handles.get(handle)
            if entry is None:
                return self._command_status(opcode, status=0x02)  # Unknown_Connection
            asyncio.create_task(self._auth_emit_link_key_request(controller, entry))
            return self._command_status(opcode, status=0)

        if opcode in (HCI_LINK_KEY_REQUEST_REPLY, HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY):
            # Initiator told the controller it has (or hasn't) a stored key.
            # In both cases, proceed to IO Capability exchange.
            peer_addr = raw_params[0:6]
            asyncio.create_task(self._auth_emit_io_cap_requests(controller, peer_addr))
            return self._command_complete(opcode, b"\x00" + peer_addr)

        if opcode == HCI_IO_CAPABILITY_REQUEST_REPLY:
            peer_addr = raw_params[0:6]
            io_cap = raw_params[6]
            oob = raw_params[7]
            auth_req = raw_params[8]
            asyncio.create_task(
                self._auth_forward_io_cap_response(controller, peer_addr, io_cap, oob, auth_req)
            )
            return self._command_complete(opcode, b"\x00" + peer_addr)

        if opcode == HCI_USER_CONFIRMATION_REQUEST_REPLY:
            peer_addr = raw_params[0:6]
            asyncio.create_task(self._auth_user_confirm_reply(controller, peer_addr, accepted=True))
            return self._command_complete(opcode, b"\x00" + peer_addr)

        if opcode == HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY:
            peer_addr = raw_params[0:6]
            asyncio.create_task(self._auth_user_confirm_reply(controller, peer_addr, accepted=False))
            return self._command_complete(opcode, b"\x00" + peer_addr)
```

Add the supporting methods. Track per-handle SSP state in a separate dict (`self._auth_state: dict[int, dict] = {}` in `__init__`-equivalent; add to the dataclass with `field(default_factory=dict, init=False)`).

```python
async def _auth_emit_link_key_request(self, initiator: VirtualController, entry: _ConnEntry) -> None:
    body = entry.acceptor_addr.address
    event = HCIEvent(event_code=int(EventCode.LINK_KEY_REQUEST), parameters=body)
    await initiator._send_event_to_host(event)


async def _auth_emit_io_cap_requests(self, initiator: VirtualController, peer_addr: bytes) -> None:
    """Emit IO_Capability_Request to BOTH sides."""
    peer = self._peer_of(initiator)
    body_to_initiator = self._addr_of(peer).address
    body_to_peer = self._addr_of(initiator).address
    await asyncio.gather(
        initiator._send_event_to_host(HCIEvent(
            event_code=int(EventCode.IO_CAPABILITY_REQUEST),
            parameters=body_to_initiator,
        )),
        peer._send_event_to_host(HCIEvent(
            event_code=int(EventCode.IO_CAPABILITY_REQUEST),
            parameters=body_to_peer,
        )),
    )


async def _auth_forward_io_cap_response(
    self, source: VirtualController, peer_addr: bytes,
    io_cap: int, oob: int, auth_req: int,
) -> None:
    """Forward IO_Capability_Response to peer; when both have arrived, emit User_Confirmation_Request to both."""
    peer = self._peer_of(source)
    # Send IO_Capability_Response to peer
    source_addr = self._addr_of(source).address
    body = source_addr + bytes([io_cap, oob, auth_req])
    await peer._send_event_to_host(HCIEvent(
        event_code=int(EventCode.IO_CAPABILITY_RESPONSE),
        parameters=body,
    ))
    # Track that this side has replied
    entry_key = self._handle_key_for_pair(source, peer)
    state = self._auth_state.setdefault(entry_key, {})
    state[id(source)] = True
    if len(state) == 2:
        # Both sides have responded; emit User_Confirmation_Request to both (JW path, numeric=0).
        await asyncio.gather(
            source._send_event_to_host(HCIEvent(
                event_code=int(EventCode.USER_CONFIRMATION_REQUEST),
                parameters=self._addr_of(peer).address + struct.pack("<I", 0),
            )),
            peer._send_event_to_host(HCIEvent(
                event_code=int(EventCode.USER_CONFIRMATION_REQUEST),
                parameters=self._addr_of(source).address + struct.pack("<I", 0),
            )),
        )


async def _auth_user_confirm_reply(
    self, source: VirtualController, peer_addr: bytes, *, accepted: bool,
) -> None:
    """Track per-side user-confirm replies; once both arrive, emit Simple_Pairing_Complete +
    Link_Key_Notification + Authentication_Complete or failure events.
    """
    peer = self._peer_of(source)
    entry_key = self._handle_key_for_pair(source, peer)
    state = self._auth_state.setdefault(entry_key, {})
    state[("confirm", id(source))] = accepted
    if not accepted:
        # Failure path: emit Simple_Pairing_Complete(0x05) to both immediately.
        body = bytes([0x05]) + self._addr_of(peer).address
        await asyncio.gather(
            source._send_event_to_host(HCIEvent(
                event_code=int(EventCode.SIMPLE_PAIRING_COMPLETE),
                parameters=body,
            )),
            peer._send_event_to_host(HCIEvent(
                event_code=int(EventCode.SIMPLE_PAIRING_COMPLETE),
                parameters=bytes([0x05]) + self._addr_of(source).address,
            )),
        )
        self._auth_state.pop(entry_key, None)
        return
    # Check whether the OTHER side has also accepted.
    other = state.get(("confirm", id(peer)))
    if other is None:
        return  # waiting for the other side
    if other is True:
        # Both accepted. Emit Simple_Pairing_Complete + Link_Key_Notification + Auth_Complete.
        link_key = self._deterministic_link_key(self._addr_of(source), self._addr_of(peer))
        spc_source = bytes([0x00]) + self._addr_of(peer).address
        spc_peer = bytes([0x00]) + self._addr_of(source).address
        lkn_source = self._addr_of(peer).address + link_key + bytes([0x05])  # key_type=Combination_Key
        lkn_peer = self._addr_of(source).address + link_key + bytes([0x05])
        # Find the handle for Auth_Complete (initiator only)
        entry = next(
            (e for e in self._handles.values()
             if {e.initiator, e.acceptor} == {source, peer}),
            None,
        )
        auth_complete_body = b""
        initiator = entry.initiator if entry else source
        if entry is not None:
            auth_complete_body = bytes([0x00]) + struct.pack("<H", entry.handle)
        await asyncio.gather(
            source._send_event_to_host(HCIEvent(
                event_code=int(EventCode.SIMPLE_PAIRING_COMPLETE), parameters=spc_source,
            )),
            peer._send_event_to_host(HCIEvent(
                event_code=int(EventCode.SIMPLE_PAIRING_COMPLETE), parameters=spc_peer,
            )),
            source._send_event_to_host(HCIEvent(
                event_code=int(EventCode.LINK_KEY_NOTIFICATION), parameters=lkn_source,
            )),
            peer._send_event_to_host(HCIEvent(
                event_code=int(EventCode.LINK_KEY_NOTIFICATION), parameters=lkn_peer,
            )),
        )
        if entry is not None:
            await initiator._send_event_to_host(HCIEvent(
                event_code=int(EventCode.AUTHENTICATION_COMPLETE),
                parameters=auth_complete_body,
            ))
        self._auth_state.pop(entry_key, None)


def _handle_key_for_pair(self, a: VirtualController, b: VirtualController) -> tuple[int, int]:
    return tuple(sorted([id(a), id(b)]))


def _deterministic_link_key(self, addr_a: BDAddress, addr_b: BDAddress) -> bytes:
    """Synthesize a stable 16-byte link key from sorted addresses."""
    import hashlib
    material = bytes(sorted([addr_a.address, addr_b.address]))
    return hashlib.sha256(material).digest()[:16]
```

Add `_auth_state: dict = field(default_factory=dict, init=False)` to the `@dataclass`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/integration/test_virtual_classic_link.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/hci/virtual_classic_link.py tests/integration/test_virtual_classic_link.py
git commit -m "feat(hci/virtual_classic_link): AuthBridge (SSP + Legacy authentication events)

Sub-Plan VirtualClassicLink Task 6. Routes the full SSP authentication
event flow between two controllers:
HCI_Authentication_Requested -> Link_Key_Request to initiator;
Link_Key_Request_Reply/Negative_Reply -> IO_Capability_Request to BOTH;
IO_Capability_Request_Reply per-side -> IO_Capability_Response to peer;
when both sides have replied, User_Confirmation_Request emitted to both
(Just Works, numeric=0);
both User_Confirmation_Request_Reply -> Simple_Pairing_Complete(0) +
Link_Key_Notification (deterministic key from sorted addresses) +
Authentication_Complete to initiator.
Negative_Reply on either side -> Simple_Pairing_Complete(0x05 Auth_Failure)
to both."
```

---

## Task 7: EncryptionBridge

**Files:**
- Modify: `pybluehost/hci/virtual_classic_link.py`
- Test: `tests/integration/test_virtual_classic_link.py`

`HCI_Set_Connection_Encryption(handle, enable)` → emit `Encryption_Change(status=0, handle, enabled)` to BOTH sides.

- [ ] **Step 1: Append failing test**

```python
@pytest.mark.asyncio
async def test_encryption_change_routes_to_both_sides():
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=True)
    await _establish_connection(c, p, addr_c, addr_p)
    events_c = _capture_events(c)
    events_p = _capture_events(p)
    handle = next(iter(link._handles.values())).handle
    # HCI_Set_Connection_Encryption: handle(2) + enable(1)
    await c.process(await _h4_cmd(0x0413, struct.pack("<H", handle) + bytes([0x01])))
    await asyncio.sleep(0.05)
    enc_c = [e for e in events_c if e.event_code == int(EventCode.ENCRYPTION_CHANGE)]
    enc_p = [e for e in events_p if e.event_code == int(EventCode.ENCRYPTION_CHANGE)]
    assert len(enc_c) == 1 and len(enc_p) == 1
    # Body: status(1) + handle(2) + enabled(1)
    assert enc_c[0].parameters[0] == 0x00
    assert struct.unpack_from("<H", enc_c[0].parameters, 1)[0] == handle
    assert enc_c[0].parameters[3] == 0x01
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/integration/test_virtual_classic_link.py -k encryption -v`
Expected: FAIL.

- [ ] **Step 3: Add EncryptionBridge to the interceptor**

```python
        # --- EncryptionBridge ---
        if opcode == HCI_SET_CONNECTION_ENCRYPTION:
            handle = struct.unpack_from("<H", raw_params, 0)[0]
            enable = raw_params[2] if len(raw_params) > 2 else 0
            asyncio.create_task(self._emit_encryption_change(handle, enable))
            return self._command_status(opcode, status=0)
```

And the helper:

```python
async def _emit_encryption_change(self, handle: int, enable: int) -> None:
    entry = self._handles.get(handle)
    if entry is None:
        return
    body = bytes([0x00]) + struct.pack("<H", handle) + bytes([enable])
    await asyncio.gather(
        entry.initiator._send_event_to_host(HCIEvent(
            event_code=int(EventCode.ENCRYPTION_CHANGE), parameters=body,
        )),
        entry.acceptor._send_event_to_host(HCIEvent(
            event_code=int(EventCode.ENCRYPTION_CHANGE), parameters=body,
        )),
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/integration/test_virtual_classic_link.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/hci/virtual_classic_link.py tests/integration/test_virtual_classic_link.py
git commit -m "feat(hci/virtual_classic_link): EncryptionBridge

Sub-Plan VirtualClassicLink Task 7. HCI_Set_Connection_Encryption ->
Encryption_Change(status=0, handle, enabled) emitted to BOTH sides
(initiator + acceptor of the original connection)."
```

---

## Task 8: DisconnectBridge + link.disconnect() teardown

**Files:**
- Modify: `pybluehost/hci/virtual_classic_link.py`
- Test: `tests/integration/test_virtual_classic_link.py`

`HCI_Disconnect(handle, reason)` → emit `Disconnection_Complete(status=0, handle, reason)` to BOTH sides, release handle. `link.disconnect()` emits Disconnect_Complete for all CONNECTED handles + cleans state.

- [ ] **Step 1: Append failing tests**

```python
@pytest.mark.asyncio
async def test_disconnect_routes_to_both_sides():
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=True)
    await _establish_connection(c, p, addr_c, addr_p)
    events_c = _capture_events(c)
    events_p = _capture_events(p)
    handle = next(iter(link._handles.values())).handle
    # HCI_Disconnect: handle(2) + reason(1)
    await c.process(await _h4_cmd(0x0406, struct.pack("<H", handle) + bytes([0x13])))
    await asyncio.sleep(0.05)
    dc_c = [e for e in events_c if e.event_code == int(EventCode.DISCONNECTION_COMPLETE)]
    dc_p = [e for e in events_p if e.event_code == int(EventCode.DISCONNECTION_COMPLETE)]
    assert len(dc_c) == 1 and len(dc_p) == 1
    # Body: status(1) + handle(2) + reason(1)
    assert dc_c[0].parameters[3] == 0x13
    # Handle released
    assert handle not in link._handles


@pytest.mark.asyncio
async def test_link_teardown_releases_all_handles():
    c, p, addr_c, addr_p, link = await _make_linked_pair(peer_discoverable=True)
    await _establish_connection(c, p, addr_c, addr_p)
    events_c = _capture_events(c)
    events_p = _capture_events(p)
    assert len(link._handles) == 1
    await link.disconnect()
    await asyncio.sleep(0.05)
    dc_c = [e for e in events_c if e.event_code == int(EventCode.DISCONNECTION_COMPLETE)]
    dc_p = [e for e in events_p if e.event_code == int(EventCode.DISCONNECTION_COMPLETE)]
    assert len(dc_c) == 1 and len(dc_p) == 1
    # Reason = 0x16 Local_Host_Terminated
    assert dc_c[0].parameters[3] == 0x16
    assert link._handles == {}
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/integration/test_virtual_classic_link.py -k disconnect -v`
Expected: FAIL — Disconnect interceptor + link.disconnect() body missing.

- [ ] **Step 3: Implement DisconnectBridge**

In `_intercept`, after EncryptionBridge:

```python
        # --- DisconnectBridge ---
        if opcode == HCI_DISCONNECT:
            handle = struct.unpack_from("<H", raw_params, 0)[0]
            reason = raw_params[2] if len(raw_params) > 2 else 0x13
            asyncio.create_task(self._emit_disconnection_complete(handle, reason))
            return self._command_status(opcode, status=0)
```

Helper:

```python
async def _emit_disconnection_complete(self, handle: int, reason: int) -> None:
    entry = self._handles.get(handle)
    if entry is None:
        return
    entry.state = _ConnState.DISCONNECTING
    body = bytes([0x00]) + struct.pack("<H", handle) + bytes([reason])
    await asyncio.gather(
        entry.initiator._send_event_to_host(HCIEvent(
            event_code=int(EventCode.DISCONNECTION_COMPLETE), parameters=body,
        )),
        entry.acceptor._send_event_to_host(HCIEvent(
            event_code=int(EventCode.DISCONNECTION_COMPLETE), parameters=body,
        )),
    )
    self._handles.pop(handle, None)
```

Update `link.disconnect()` to emit completion events for all CONNECTED handles before detaching:

```python
async def disconnect(self) -> None:
    """Tear down all connected/pending handles; emit appropriate completion events."""
    for handle in list(self._handles.keys()):
        entry = self._handles.get(handle)
        if entry is None:
            continue
        if entry.state == _ConnState.CONNECTED:
            await self._emit_disconnection_complete(handle, reason=0x16)  # Local_Host_Terminated
        elif entry.state == _ConnState.PENDING:
            # Emit Connection_Complete(status=0x16) to initiator only.
            await self._emit_connection_complete(
                entry.initiator, status=0x16, handle=0x0000,
                peer_addr=entry.acceptor_addr,
            )
            self._handles.pop(handle, None)
    self.detach()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/integration/test_virtual_classic_link.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/hci/virtual_classic_link.py tests/integration/test_virtual_classic_link.py
git commit -m "feat(hci/virtual_classic_link): DisconnectBridge + link.disconnect() teardown

Sub-Plan VirtualClassicLink Task 8. HCI_Disconnect ->
Disconnection_Complete(status=0, handle, reason) to BOTH sides; handle
released. link.disconnect() walks all entries: CONNECTED -> emit
Disconnection_Complete(reason=0x16 Local_Host_Terminated); PENDING ->
emit Connection_Complete(status=0x16) to initiator only; clears state
and detaches command_interceptor + acl_forwarder from both controllers."
```

---

## Task 9: Smoke E2E — inquiry → connect → SSP JW pair → encrypt → disconnect

**Files:**
- Create: `tests/integration/test_classic_e2e_smoke.py`

Validates the full bridge end-to-end against real Stack instances + real SSPManager. This proves the bridge integrates correctly with the existing host-side stack layers.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_classic_e2e_smoke.py`:

```python
"""Classic E2E smoke: two Stack.virtual() instances bridged by VirtualClassicLink
complete inquiry -> connect -> SSP Just Works pair -> encrypt -> disconnect.
"""
from __future__ import annotations

import asyncio

import pytest

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import JsonBondStorage
from pybluehost.core.address import BDAddress
from pybluehost.hci.virtual_classic_link import VirtualClassicLink
from pybluehost.stack import Stack, StackConfig


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_classic_inquiry_connect_ssp_jw_pair_disconnect(tmp_path):
    """End-to-end smoke: two stacks via VirtualClassicLink complete the canonical
    Classic pairing flow."""
    storage_c = JsonBondStorage(tmp_path / "bonds_c.json")
    storage_p = JsonBondStorage(tmp_path / "bonds_p.json")
    cfg_c = StackConfig(
        bond_storage=storage_c,
        security=SecurityConfig(enable_secure_connections=False),
    )
    cfg_p = StackConfig(
        bond_storage=storage_p,
        security=SecurityConfig(enable_secure_connections=False),
    )
    central_addr = BDAddress(b"\x0A" * 6)
    peripheral_addr = BDAddress(b"\x0B" * 6)
    stack_c = await Stack.virtual(config=cfg_c, address=central_addr)
    stack_p = await Stack.virtual(config=cfg_p, address=peripheral_addr)

    link = VirtualClassicLink(
        central=stack_c._virtual_controller,
        peripheral=stack_p._virtual_controller,
        central_address=central_addr,
        peripheral_address=peripheral_addr,
        page_timeout_seconds=0.5,
    )
    link.attach()

    try:
        # Peripheral becomes discoverable + page-scannable
        await stack_p.gap.classic_discoverability.set_discoverable(True)
        await asyncio.sleep(0.05)

        # Central runs inquiry; verifies peripheral is discovered
        discovered: list[BDAddress] = []

        def _on_inquiry_result(info):
            discovered.append(info.address)

        stack_c.gap.classic_discovery.on_result(_on_inquiry_result)
        await stack_c.gap.classic_discovery.start()
        await asyncio.sleep(0.2)
        await stack_c.gap.classic_discovery.cancel()
        assert peripheral_addr in discovered, f"peripheral not discovered: {discovered}"

        # Central connects to peripheral
        handle = await stack_c.connect_classic(peripheral_addr, timeout=2.0)

        # SSPManager on both sides drives the SSP JW pair via the bridged events.
        # Trigger authentication from the central side.
        await stack_c._hci.send_command_raw(bytes(
            [0x01, 0x11, 0x04, 0x02]
        ) + handle.to_bytes(2, "little"))
        # Wait for SSP JW to complete on both sides (Auth_Complete on central, Link_Key_Notification on both).
        await asyncio.sleep(0.3)

        # Verify bonds persisted on both sides
        bond_c = await storage_c.load_bond(peripheral_addr)
        bond_p = await storage_p.load_bond(central_addr)
        assert bond_c is not None, f"central bond not persisted; storage={await storage_c.list_bonds()}"
        assert bond_p is not None, f"peripheral bond not persisted; storage={await storage_p.list_bonds()}"
        assert bond_c.link_key == bond_p.link_key
        assert bond_c.link_key_type == 0x05

        # Encryption
        await stack_c._hci.send_command_raw(bytes(
            [0x01, 0x13, 0x04, 0x03]
        ) + handle.to_bytes(2, "little") + bytes([0x01]))
        await asyncio.sleep(0.1)

        # Disconnect
        await stack_c.gap.classic_connections.disconnect(handle)
        await asyncio.sleep(0.1)

    finally:
        await link.disconnect()
        await stack_c.close()
        await stack_p.close()
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/integration/test_classic_e2e_smoke.py -v --transport=virtual`

This is the most complex test in the bridge suite. Expect to iterate. Common debug points:
- **`stack_c.connect_classic` doesn't exist** — grep `pybluehost/stack.py` for the actual public API name (it may be `stack.gap.classic_connections.connect(addr)` returning a handle, or async equivalent).
- **`stack.gap.classic_discovery.start()` API mismatch** — grep `pybluehost/classic/gap.py` `class ClassicDiscovery` for the right method name and `on_result` shape.
- **`stack._hci.send_command_raw` doesn't exist** — replace with the proper command-sending API. The right invocation might be via `HCI_Authentication_Requested_Command` dataclass + `await stack._hci.send_command(cmd)`. Grep for examples.
- **SSPManager doesn't auto-engage** — make sure `stack._gap.classic_ssp` has its `set_io_capability` called with NoInputNoOutput (auto-accept JW path). If SSPManager won't respond to `User_Confirmation_Request` without a `_confirm_handler`, install one that auto-accepts. The existing host code at `pybluehost/classic/gap.py:339` already handles SSP events.
- **Bond persistence requires specific events** — the SSPManager listens for `Link_Key_Notification` and `Simple_Pairing_Complete`. Both are emitted by the bridge in Task 6. If bonds aren't persisting, verify both events reach the correct host sink.

The implementer may need to adjust the test to use the actual public API names. The bridge's behavior is the contract; the test's API calls are flexible.

- [ ] **Step 3: Run full integration suite**

Run: `uv run pytest tests/integration/ -q --transport=virtual`
Expected: 1 new smoke test PASSES + no regressions.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_classic_e2e_smoke.py
git commit -m "test(integration): Classic E2E smoke (inquiry -> connect -> SSP JW pair -> disconnect)

Sub-Plan VirtualClassicLink Task 9. Two Stack.virtual() instances bridged
by VirtualClassicLink complete the canonical Classic flow end-to-end:
peripheral becomes discoverable; central inquires and discovers; central
connects; SSPManager on both sides drives SSP Just Works via bridged events;
bonds persist on both sides with the deterministic link key from the bridge
(link_key_type=0x05 Combination_Key); encryption succeeds; disconnect
completes cleanly on both sides."
```

---

## Task 10: STATUS.md update

**Files:**
- Modify: `docs/superpowers/STATUS.md`

- [ ] **Step 1: Update top-of-file**

```
**当前进行中**：VirtualClassicLink — ✅ 完成
**下一步**：Classic Workflow E2E（SDP browse + RFCOMM/SPP echo + bonded reconnect）/ 断线重连闭环 / 真机 E2E 验证
**不在路线图**：SMP Sub-Plan 3c (OOB) — 暂无计划支持
```

- [ ] **Step 2: Add row to Plan-progress table**

Append after the E2E LE Lifecycle row (or wherever the most recent Plan row lives):

```
| VirtualClassicLink | BR/EDR (Classic) peer-to-peer 桥接：Inquiry / Connection / ACL / Auth (SSP+Legacy) / Encryption / Disconnect 六个子桥；两个 Stack.virtual() 真实 inquiry→connect→SSP JW pair→encrypt→disconnect 端到端 | ✅ 完成 | [2026-05-20-virtual-classic-link](plans/2026-05-20-virtual-classic-link.md) | `pybluehost/hci/virtual_classic_link.py`, `pybluehost/hci/virtual.py`, `pybluehost/hci/constants.py` |
```

Increment "总计：N 个 Plan" by one.

- [ ] **Step 3: Add detailed-progress section**

Append after the E2E LE Lifecycle section:

```markdown
### ✅ VirtualClassicLink
- 完成时间：2026-05-20
- Plan 文档：[2026-05-20-virtual-classic-link.md](plans/2026-05-20-virtual-classic-link.md)
- BR/EDR (Classic) peer-to-peer 桥接基础设施。Counterpart to VirtualLELink。
- 六个子桥（同一 `VirtualClassicLink` 类）：
  - InquiryBridge：`HCI_Inquiry` 仅当 peer 的 `inquiry_scan=1` 时返回 `Inquiry_Result`；否则空 `Inquiry_Complete`。`HCI_Inquiry_Cancel` 立即完成。
  - ConnectionBridge：`HCI_Create_Connection` → 分配 handle + `Connection_Request` to peer；peer `Accept` → `Connection_Complete` 双端；peer `Reject` → 仅 initiator 收 `Connection_Complete(reason)`；peer 不可 page → `Page_Timeout(0x04)`。
  - ACLBridge：CONNECTED handle 上的 ACL 数据双向直通；非 connected handle 静默丢弃。
  - AuthBridge：`HCI_Authentication_Requested` → `Link_Key_Request` 给 initiator；`Link_Key_Request_(Negative_)Reply` → 双端 `IO_Capability_Request`；双端 `IO_Cap_Reply` → 互相 `IO_Capability_Response`；两端都答完 → 双端 `User_Confirmation_Request(numeric=0)`（JW）；两端都 accept → `Simple_Pairing_Complete(0)` + `Link_Key_Notification`（key 由 sorted addr SHA-256[:16] 确定性生成，key_type=0x05）+ `Authentication_Complete` 给 initiator；任一 reject → `Simple_Pairing_Complete(0x05)` 双端。
  - EncryptionBridge：`HCI_Set_Connection_Encryption` → `Encryption_Change(enabled=1)` 双端。
  - DisconnectBridge：`HCI_Disconnect` → `Disconnection_Complete` 双端 + 释放 handle。
- `VirtualController` 扩展：新增 `command_interceptor` 钩子（generic）+ `_inquiry_scan/_page_scan` 跟踪。桥接通过 `command_interceptor` 截获 16 个 Classic 命令并合成响应；其它命令仍走默认 dispatch。
- 验收：`uv run pytest tests/integration/test_virtual_classic_link.py -v` PASS (15 per-primitive)；`tests/integration/test_classic_e2e_smoke.py` PASS (1 smoke)；全套仅 3 个 pre-existing USB diagnostics 失败。
- 不在范围（按设计推迟）：Classic Workflow E2E（SDP browse / RFCOMM/SPP echo / bonded reconnect with auto-encrypt）= 后续 Plan；BR/EDR SC via bridge（key_type=0x07）= 后续 Plan，现 single-controller simulate hook 已覆盖 bond 持久化；SCO/eSCO 同步音频；硬件 Classic E2E。
```

- [ ] **Step 4: Final full-suite run**

Run: `uv run pytest tests/ -q --transport=virtual`
Expected: only the 3 pre-existing USB-diagnostics failures.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/STATUS.md
git commit -m "docs(status): VirtualClassicLink complete

BR/EDR peer-to-peer bridge counterpart to VirtualLELink. Six sub-bridges
(Inquiry, Connection, ACL, Auth, Encryption, Disconnect) sharing a
connection-handle table; intercepts 16 HCI commands via a new generic
command_interceptor hook on VirtualController; emits synthetic HCI events
through the existing _send_event_to_host path so hosts can't distinguish
bridged events from real-radio ones. 15 per-primitive tests + 1 smoke E2E
PASS. Classic Workflow E2E (SDP/RFCOMM/SPP/bonded-reconnect) is the
follow-up Plan."
```

---

## Acceptance Checklist

- [ ] `VirtualController.command_interceptor` attribute + dispatch hook in `process()`.
- [ ] `VirtualController._inquiry_scan` / `._page_scan` populated via `HCI_Write_Scan_Enable`.
- [ ] `pybluehost/hci/virtual_classic_link.py` exists with `VirtualClassicLink` class.
- [ ] `_ConnState` enum (NONE/PENDING/CONNECTED/DISCONNECTING).
- [ ] Handle allocator starts at `0x40`, increments, releases on Disconnect_Complete.
- [ ] `attach()` / `detach()` lifecycle works.
- [ ] InquiryBridge: discoverable peer found / non-discoverable skipped / cancel works.
- [ ] ConnectionBridge: accept + reject + page-timeout all reach the right host(s) with correct status.
- [ ] ACLBridge: L2CAP frames route both directions verbatim; non-existent-handle drops silently.
- [ ] AuthBridge: Link_Key_Request, IO_Capability_Request/Response, User_Confirmation_Request, Simple_Pairing_Complete, Authentication_Complete, Link_Key_Notification all flow correctly.
- [ ] EncryptionBridge: Set_Connection_Encryption → Encryption_Change to both.
- [ ] DisconnectBridge: HCI_Disconnect → Disconnection_Complete to both; handle released.
- [ ] `link.disconnect()` teardown: emit appropriate completion events for all handles; clear state.
- [ ] 15 per-primitive bridge tests pass.
- [ ] 1 smoke E2E passes.
- [ ] No regressions in existing `test_pairing_classic_sc_hci.py` (single-controller simulate hook still works).
- [ ] STATUS.md updated.

## Out of Scope (deferred)

| Item | When |
|---|---|
| Classic Workflow E2E (SDP browse, RFCOMM/SPP echo, bonded reconnect) | Immediate follow-up Plan |
| BR/EDR Secure Connections via bridge (key_type=0x07) | Future Plan |
| SCO / eSCO synchronous audio (A2DP, HFP) | Independent Plan |
| Real-hardware Classic E2E (two USB adapters) | Manual; reuses scenarios once `build_stack_from_spec` accepts `config=` |
| Extended Inquiry Response / Hold / Sniff / Park | Out of scope |
| OOB | **Not on roadmap** |
