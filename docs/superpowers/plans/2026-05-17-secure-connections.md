# Secure Connections (LE SC + BR/EDR SC) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in Secure Connections support to both transports — LE Secure Connections via SMP P-256 ECDH and BR/EDR Secure Connections via Classic SSP — with Just Works association model only.

**Architecture:** New `SecurityConfig.enable_secure_connections` flag (default `False`); `_validate_sc_dependencies` blocks misconfig (CTKD without SC). LE SC adds ECDH P-256, two new SMP PDUs, and state-machine branching in `_smp_state.py`. BR/EDR SC extends existing `SSPManager` to handle the 5 SSP HCI events and persist P-256-derived `Link_Key`. Both share existing `SMPCrypto.f4/f5/f6` and existing `VirtualLELink` for tests.

**Tech Stack:** Python 3.10+; `cryptography>=41.0` (already a dep — used for AES-CMAC; now also for ECDH P-256); pytest (`--transport=virtual`); existing `core/statemachine.StateMachine`, `hci/capabilities.SupportedCommands`.

**Spec baseline**: [docs/superpowers/specs/2026-05-17-secure-connections-design.md](../specs/2026-05-17-secure-connections-design.md)

---

## 范围声明

**包含**：
1. `SecurityConfig.enable_secure_connections: bool = False` (opt-in) + `_validate_sc_dependencies` + `ConfigurationError`
2. New HCI commands + events for BR/EDR SC (some already exist as opcode constants — only missing dataclass wrappers + listener APIs)
3. `HCIController.initialize()` conditionally enables BR/EDR SC via `Write_Secure_Connections_Host_Support` (gated on config AND Supported_Commands bitmap)
4. LE SC ECDH P-256 crypto module + 2 new SMP PDUs + state machine extension
5. SC selection logic: only used when config-on AND both sides advertise SC; else fallback to Legacy
6. LE SC full flow: Public Key exchange → DHKey → f4 Confirm → f5 LTK → f6 DHKey Check → encryption
7. BR/EDR SC full flow via SSPManager: 5 SSP events handled, P-256 `Link_Key` persisted
8. Loopback E2E for LE SC (via existing `VirtualLELink`)
9. HCI-event-driven integration test for BR/EDR SC (no Classic two-controller bridge — deferred)

**不包含**（推迟）：
- Numeric Comparison / Passkey Entry / OOB association models → Sub-Plan 3
- Two-controller Classic loopback bridge → independent Plan
- LE Audio / Security Mode 1 Level 4 / SC Only Mode / ISO encryption — config validation lists these as future hooks, but no enforcement

---

## 文件改动清单

| Type | Path | Responsibility |
|------|------|---------------|
| Modify | `pybluehost/core/errors.py` | New `ConfigurationError` |
| Modify | `pybluehost/ble/security.py` | `SecurityConfig.enable_secure_connections`; `_validate_sc_dependencies` |
| Modify | `pybluehost/hci/constants.py` | New event codes: `LINK_KEY_NOTIFICATION = 0x18`, `SIMPLE_PAIRING_COMPLETE = 0x36`. New opcodes: `HCI_LINK_KEY_REQUEST_REPLY = 0x040B`, `HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT = 0x0C7A` (verify existing ones; only add missing) |
| Modify | `pybluehost/hci/packets.py` | New command dataclasses: `HCI_Write_Secure_Connections_Host_Support_Command`, `HCI_IO_Capability_Request_Reply_Command`, `HCI_IO_Capability_Request_Negative_Reply_Command`, `HCI_User_Confirmation_Request_Reply_Command`, `HCI_User_Confirmation_Request_Negative_Reply_Command`, `HCI_Link_Key_Request_Reply_Command`, `HCI_Link_Key_Request_Negative_Reply_Command` (verify which exist before adding) |
| Modify | `pybluehost/hci/capabilities.py` | Add `HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT: (32, 3)` to `_OPCODE_BIT_POSITIONS` |
| Modify | `pybluehost/hci/controller.py` | 5 new listener APIs: `on_io_capability_request`, `on_user_confirmation_request`, `on_simple_pairing_complete`, `on_link_key_notification`, `on_link_key_request`. Init step for `Write_SC_Host_Support` config-gated |
| Modify | `pybluehost/hci/virtual.py` | Stub for `Write_SC_Host_Support`; `simulate_ssp_pairing(bd_addr, key_type)` test hook |
| Create | `pybluehost/ble/_smp_sc_crypto.py` | ECDH P-256 keypair + DHKey + byte-order helpers |
| Modify | `pybluehost/ble/smp.py` | New `SMPCode.PAIRING_PUBLIC_KEY=0x0C` / `.PAIRING_DHKEY_CHECK=0x0D`; new PDU classes `SMPPairingPublicKey`, `SMPPairingDHKeyCheck`; extend `SMPState`, `SMPEvent`, `SMPPairingContext` SC fields |
| Modify | `pybluehost/ble/_smp_state.py` | `register_transitions` branches on SC negotiation; new `_sc_*` action callbacks |
| Modify | `pybluehost/classic/gap.py` | Extend `SSPManager` to handle `Simple_Pairing_Complete` and `Link_Key_Notification` events; reply with new HCI commands; persist `BondInfo(link_key, link_key_type, sc=True)` |
| Modify | `pybluehost/stack.py` | Call `_validate_sc_dependencies(cfg.security)` in `_build`; pass `security_config` to `SMPManager` so context can see `enable_secure_connections` |
| Create | `tests/unit/ble/test_security_config_sc_validation.py` | `_validate_sc_dependencies` tests |
| Create | `tests/unit/hci/test_sc_packets.py` | New HCI command + event round-trip |
| Create | `tests/unit/hci/test_sc_listener_apis.py` | 5 new listener APIs fire correctly |
| Create | `tests/unit/ble/test_smp_sc_crypto.py` | ECDH keypair + DHKey + byte-order tests with spec test vectors |
| Create | `tests/unit/ble/test_smp_sc_pdus.py` | `SMPPairingPublicKey` + `SMPPairingDHKeyCheck` round-trip |
| Create | `tests/unit/ble/test_smp_le_sc_state_machine.py` | SC transitions, Initiator + Responder Phase 2 |
| Create | `tests/unit/ble/test_smp_sc_legacy_fallback.py` | Config-off → SC bit not set even if peer offers |
| Create | `tests/unit/classic/test_ssp_secure_connections.py` | SSPManager handles full SSP sequence + persists Link_Key |
| Create | `tests/integration/test_pairing_le_sc_loopback.py` | LE SC Just Works loopback E2E |
| Create | `tests/integration/test_pairing_classic_sc_hci.py` | BR/EDR SC HCI-event-driven integration |
| Modify | `docs/superpowers/STATUS.md` | Mark Plan complete |

---

## 任务依赖图

```
GROUP A — Shared foundation
  Task 1: SecurityConfig + ConfigurationError + validation
  Task 2: HCI commands & events for BR/EDR SC
  Task 3: HCIController listener APIs
  Task 4: HCIController.initialize() Write_SC_Host_Support gating

GROUP B — LE SC (depends on Task 1)
  Task 5:  _smp_sc_crypto.py — ECDH P-256
  Task 6:  SMP PDUs + state/event enums + context fields
  Task 7:  _smp_state.py — SC vs Legacy branching at FEATURE_EXCHANGE exit
  Task 8:  SC Phase 2.1 — Public Key exchange
  Task 9:  SC Phase 2.2 — Confirm/Random + f4 verify + f5 LTK derivation
  Task 10: SC Phase 2.3 — DHKey check (f6) + encryption start with f5 LTK
  Task 11: SC Phase 3 — skip LTK distribution, BondInfo(sc=True)
  Task 12: LE SC loopback E2E test

GROUP C — BR/EDR SC (depends on Tasks 2-3)
  Task 13: SSPManager — extend for SC events (Simple_Pairing_Complete, Link_Key_Notification)
  Task 14: SSPManager BondInfo persistence + reconnect Link_Key_Request reply
  Task 15: BR/EDR SC HCI-event-driven integration test

GROUP D — Wrap
  Task 16: STATUS.md + Plan checkbox tick + Plan-doc checkboxes ticked
```

---

## Task 1: `SecurityConfig.enable_secure_connections` + validation

**Files:**
- Modify: `pybluehost/core/errors.py`
- Modify: `pybluehost/ble/security.py`
- Create: `tests/unit/ble/test_security_config_sc_validation.py`

### Step 1.1: Add ConfigurationError

- [ ] **Modify `pybluehost/core/errors.py`**: add after `ReplayModeError`:

```python
class ConfigurationError(PyBlueHostError):
    """Raised when StackConfig / SecurityConfig has an internally inconsistent setting."""
```

- [ ] **Modify `pybluehost/core/__init__.py`**: add `ConfigurationError` to imports and `__all__` (alphabetical, between `CommandTimeoutError` and `Direction`).

### Step 1.2: Write failing test

- [ ] **Create `tests/unit/ble/test_security_config_sc_validation.py`:**

```python
"""SecurityConfig.enable_secure_connections + _validate_sc_dependencies."""
from __future__ import annotations

import pytest

from pybluehost.ble.security import SecurityConfig, _validate_sc_dependencies
from pybluehost.core.errors import ConfigurationError


def test_enable_secure_connections_defaults_false():
    cfg = SecurityConfig()
    assert cfg.enable_secure_connections is False


def test_enable_secure_connections_overrideable():
    cfg = SecurityConfig(enable_secure_connections=True)
    assert cfg.enable_secure_connections is True


def test_validation_passes_with_sc_off_and_no_dependents():
    cfg = SecurityConfig(enable_secure_connections=False, ctkd_enable=False)
    _validate_sc_dependencies(cfg)


def test_validation_passes_with_sc_on_and_ctkd():
    cfg = SecurityConfig(enable_secure_connections=True, ctkd_enable=True)
    _validate_sc_dependencies(cfg)


def test_validation_blocks_ctkd_without_sc():
    cfg = SecurityConfig(enable_secure_connections=False, ctkd_enable=True)
    with pytest.raises(ConfigurationError, match="CTKD"):
        _validate_sc_dependencies(cfg)
```

### Step 1.3: Run test to verify it fails

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/ble/test_security_config_sc_validation.py -v --transport=virtual
```

Expected: AttributeError / ImportError (`enable_secure_connections`, `ctkd_enable`, `_validate_sc_dependencies` missing).

### Step 1.4: Implement

- [ ] **Modify `pybluehost/ble/security.py`** — extend `SecurityConfig` and add validator. Read the existing dataclass first to preserve other fields:

```python
@dataclass
class SecurityConfig:
    """SMP security configuration for a connection."""
    io_capability: int = 0x03       # NoInputNoOutput
    oob_flag: int = 0x00
    auth_requirements: int = 0x0D   # Bonding | MITM | SC (legacy default; not used by current code)
    max_key_size: int = 16
    initiator_keys: int = 0x01
    responder_keys: int = 0x01
    enable_secure_connections: bool = False
    ctkd_enable: bool = False
    # Future hooks (commented stubs; future Plans uncomment and add their entry to _validate_sc_dependencies):
    # lea_enable: bool = False
    # le_security_mode: str = "1_2"
    # classic_security_mode: str = "4_2"
    # sc_only_mode: bool = False
    # iso_encryption_enable: bool = False
    # numeric_comparison_enable: bool = False


def _validate_sc_dependencies(cfg: "SecurityConfig") -> None:
    """Raise ConfigurationError if any SC-dependent feature is enabled without enable_secure_connections.

    Currently checks only CTKD. Future Plans add their own checks here.
    """
    from pybluehost.core.errors import ConfigurationError
    requires_sc: list[str] = []
    if cfg.ctkd_enable:
        requires_sc.append("CTKD")
    # Future hooks (commented stubs — uncomment when each feature lands):
    # if cfg.lea_enable:                          requires_sc.append("LE Audio")
    # if cfg.le_security_mode == "1_4":           requires_sc.append("LE Security Mode 1 Level 4")
    # if cfg.classic_security_mode == "4_4":      requires_sc.append("BR/EDR Security Mode 4 Level 4")
    # if cfg.sc_only_mode:                        requires_sc.append("Secure Connections Only Mode")
    # if cfg.iso_encryption_enable:               requires_sc.append("ISO Channel encryption")
    # if cfg.numeric_comparison_enable:           requires_sc.append("Numeric Comparison")
    if requires_sc and not cfg.enable_secure_connections:
        raise ConfigurationError(
            f"these features require enable_secure_connections=True: "
            f"{', '.join(requires_sc)}"
        )
```

### Step 1.5: Wire validation into Stack._build

- [ ] **Modify `pybluehost/stack.py`** — in `Stack._build`, after `cfg = config or StackConfig()`, add:

```python
        from pybluehost.ble.security import _validate_sc_dependencies
        _validate_sc_dependencies(cfg.security)
```

### Step 1.6: Verify

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/ble/test_security_config_sc_validation.py -v --transport=virtual
uv run --frozen pytest tests/ -q --transport=virtual --tb=no 2>&1 | tail -7
```

Expected: 5 new tests PASS; full suite only the 3 pre-existing failures.

### Step 1.7: Commit

- [ ] **Run:**

```bash
git add pybluehost/core/errors.py pybluehost/core/__init__.py pybluehost/ble/security.py pybluehost/stack.py tests/unit/ble/test_security_config_sc_validation.py
git commit -m "feat(security): add enable_secure_connections opt-in + dependency validation

SecurityConfig.enable_secure_connections defaults False; SC is opt-in.
_validate_sc_dependencies blocks CTKD-without-SC configurations at
Stack._build time, raising ConfigurationError. Future Plans add their
own entries (LEA, Security Mode 1 Level 4, SC Only Mode, ISO encryption,
Numeric Comparison) as those features land."
```

---

## Task 2: HCI commands & events for BR/EDR SC

**Files:**
- Modify: `pybluehost/hci/constants.py`
- Modify: `pybluehost/hci/packets.py`
- Create: `tests/unit/hci/test_sc_packets.py`

### Step 2.1: Audit existing constants/packets

- [ ] **Run** the following to determine what's already in place:

```bash
grep -nE "HCI_(WRITE_SECURE|IO_CAPABILITY|USER_CONFIRMATION|LINK_KEY_REQUEST|LINK_KEY_NEG|LINK_KEY_NOTIFICATION|SIMPLE_PAIRING_COMPLETE)" pybluehost/hci/constants.py
grep -nE "class HCI_(Write_Secure|IO_Capability|User_Confirmation|Link_Key)" pybluehost/hci/packets.py
```

The existing surface contains some opcode constants (used by `SSPManager` already). Missing pieces vary; only add what's not already there. Below lists the full target state — skip any item already present.

Target opcode constants (all under OGF=0x01 link control, OGF=0x03 controller, OGF=0x08 LE):

```python
# Already exist (do NOT re-add):
#   HCI_IO_CAPABILITY_REQUEST_REPLY            = 0x042B
#   HCI_IO_CAPABILITY_REQUEST_NEGATIVE_REPLY   = 0x0434
#   HCI_USER_CONFIRMATION_REQUEST_REPLY        = 0x042C
#   HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY = 0x042D
#   HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY        = 0x040C
# Verify; add only if missing:
HCI_LINK_KEY_REQUEST_REPLY                     = 0x040B
HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT      = 0x0C7A
```

Target event codes:

```python
class EventCode(IntEnum):
    # Add (verify each first):
    LINK_KEY_REQUEST             = 0x17
    LINK_KEY_NOTIFICATION        = 0x18
    IO_CAPABILITY_REQUEST        = 0x31
    IO_CAPABILITY_RESPONSE       = 0x32
    USER_CONFIRMATION_REQUEST    = 0x33
    SIMPLE_PAIRING_COMPLETE      = 0x36
```

### Step 2.2: Write failing test

- [ ] **Create `tests/unit/hci/test_sc_packets.py`:**

```python
"""HCI Secure Connections command + event encode/decode."""
from __future__ import annotations

import struct

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    EventCode,
    HCI_LINK_KEY_REQUEST_REPLY,
    HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT,
)
from pybluehost.hci.packets import (
    HCI_Link_Key_Request_Reply_Command,
    HCI_Write_Secure_Connections_Host_Support_Command,
    decode_hci_packet,
)


def test_write_secure_connections_host_support_encode():
    cmd = HCI_Write_Secure_Connections_Host_Support_Command(secure_connections_host_support=0x01)
    raw = cmd.to_bytes()
    opcode = int.from_bytes(raw[1:3], "little")
    assert opcode == HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT
    assert raw[3] == 1  # param length
    assert raw[4] == 1  # enabled


def test_link_key_request_reply_encode():
    addr = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    cmd = HCI_Link_Key_Request_Reply_Command(bd_addr=addr, link_key=b"\xAA" * 16)
    raw = cmd.to_bytes()
    opcode = int.from_bytes(raw[1:3], "little")
    assert opcode == HCI_LINK_KEY_REQUEST_REPLY
    assert raw[3] == 22  # 6 bytes addr + 16 bytes key
    # Address is sent little-endian in BT (LSB first); BDAddress stores big-endian
    assert raw[4:10] == bytes(addr.address[::-1])
    assert raw[10:26] == b"\xAA" * 16


def test_link_key_notification_event_decode():
    """HCI_Link_Key_Notification: bd_addr(6) + link_key(16) + key_type(1) = 23 params."""
    params = b"\x06\x05\x04\x03\x02\x01" + b"\xBB" * 16 + bytes([0x07])  # SC unauthenticated key
    raw = b"\x04" + bytes([EventCode.LINK_KEY_NOTIFICATION]) + bytes([len(params)]) + params
    packet = decode_hci_packet(raw)
    from pybluehost.hci.packets import HCIEvent
    assert isinstance(packet, HCIEvent)
    assert packet.event_code == EventCode.LINK_KEY_NOTIFICATION
    assert packet.parameters == params


def test_simple_pairing_complete_event_decode():
    """HCI_Simple_Pairing_Complete: status(1) + bd_addr(6) = 7 params."""
    params = b"\x00" + b"\x06\x05\x04\x03\x02\x01"
    raw = b"\x04" + bytes([EventCode.SIMPLE_PAIRING_COMPLETE]) + bytes([len(params)]) + params
    packet = decode_hci_packet(raw)
    from pybluehost.hci.packets import HCIEvent
    assert isinstance(packet, HCIEvent)
    assert packet.event_code == EventCode.SIMPLE_PAIRING_COMPLETE
    assert packet.parameters[0] == 0
```

Note: BT spec sends BD_ADDR over the wire in little-endian (LSB first), and our `BDAddress` class stores it big-endian (matching `bytes(addr.address)`). The encode flips with `[::-1]` and decode flips back.

### Step 2.3: Run test to verify it fails

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/hci/test_sc_packets.py -v --transport=virtual
```

Expected: ImportError on missing classes.

### Step 2.4: Add missing constants

- [ ] **Modify `pybluehost/hci/constants.py`**: in the existing opcode region (after other 0x040x/0x042x/0x0C7x constants — match position):

```python
HCI_LINK_KEY_REQUEST_REPLY                = 0x040B  # if missing
HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT = 0x0C7A  # if missing
```

Add to `EventCode` IntEnum any missing entries from the list in Step 2.1.

### Step 2.5: Add command dataclasses

- [ ] **Modify `pybluehost/hci/packets.py`** — add command dataclasses. Place each in the same region as other LE / link-control commands (match existing file structure):

```python
@PacketRegistry.register_command(HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT)
@dataclass
class HCI_Write_Secure_Connections_Host_Support_Command(HCICommand):
    """HCI_Write_Secure_Connections_Host_Support (Core 5.4 Vol 4 Part E §7.3.92)."""
    secure_connections_host_support: int = 0
    opcode: int = HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT

    def __post_init__(self) -> None:
        self.parameters = bytes([self.secure_connections_host_support])


@PacketRegistry.register_command(HCI_LINK_KEY_REQUEST_REPLY)
@dataclass
class HCI_Link_Key_Request_Reply_Command(HCICommand):
    """HCI_Link_Key_Request_Reply (Core 5.4 Vol 4 Part E §7.1.10)."""
    bd_addr: BDAddress | None = None
    link_key: bytes = field(default_factory=lambda: bytes(16))
    opcode: int = HCI_LINK_KEY_REQUEST_REPLY

    def __post_init__(self) -> None:
        if self.bd_addr is None:
            raise ValueError("bd_addr is required")
        if len(self.link_key) != 16:
            raise ValueError("link_key must be 16 bytes")
        # BT wire format is little-endian; BDAddress.address stores big-endian
        self.parameters = bytes(self.bd_addr.address[::-1]) + self.link_key
```

Similar pattern for the other 4 commands referenced in the spec (`HCI_IO_Capability_Request_Reply_Command`, `_Negative_Reply`, `HCI_User_Confirmation_Request_Reply_Command`, `_Negative_Reply`, `HCI_Link_Key_Request_Negative_Reply_Command`) — only add the ones NOT already present (some may already exist as opcode constants without dataclass wrappers; in that case, just add the dataclass). The IO_Capability_Request_Reply payload is `bd_addr(6) + io_capability(1) + oob_data_present(1) + authentication_requirements(1)`; the others are `bd_addr(6)` only (and `_Negative_Reply` variants are `bd_addr(6) + reason(1)`).

For SC bit in `authentication_requirements` reply: 0x04 = MITM Not Required + General Bonding + SC bit (bit 3).

Add `from pybluehost.core.address import BDAddress` to packets.py imports if not present.

### Step 2.6: Verify

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/hci/test_sc_packets.py -v --transport=virtual
uv run --frozen pytest tests/unit/hci/ -q --transport=virtual
```

Expected: 4 new tests PASS; no regressions.

### Step 2.7: Commit

- [ ] **Run:**

```bash
git add pybluehost/hci/constants.py pybluehost/hci/packets.py tests/unit/hci/test_sc_packets.py
git commit -m "feat(hci): add Secure Connections HCI commands and events

Commands: HCI_Write_Secure_Connections_Host_Support, Link_Key_Request_Reply
(and existing Negative_Reply / IO_Capability / User_Confirmation wrappers as needed).
Events: LINK_KEY_REQUEST, LINK_KEY_NOTIFICATION, IO_CAPABILITY_REQUEST,
IO_CAPABILITY_RESPONSE, USER_CONFIRMATION_REQUEST, SIMPLE_PAIRING_COMPLETE.

Foundation for BR/EDR Secure Connections (Sub-Plan 2 Task 13)."
```

---

## Task 3: HCIController listener APIs

**Files:**
- Modify: `pybluehost/hci/controller.py`
- Create: `tests/unit/hci/test_sc_listener_apis.py`

### Step 3.1: Write failing test

- [ ] **Create `tests/unit/hci/test_sc_listener_apis.py`:**

```python
"""HCIController listener APIs for SC HCI events."""
from __future__ import annotations

import asyncio

from pybluehost.hci.constants import EventCode
from pybluehost.hci.controller import HCIController
from pybluehost.hci.packets import HCIEvent
from pybluehost.hci.virtual import VirtualController


async def test_on_io_capability_request_fires():
    vc, host_t = await VirtualController.create()
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)
    seen: list = []
    hci.on_io_capability_request(lambda addr: seen.append(addr))
    try:
        await hci.initialize()
        # Inject the event from controller side
        params = bytes(reversed(b"\x01\x02\x03\x04\x05\x06"))  # BT wire = little-endian
        evt = HCIEvent(event_code=int(EventCode.IO_CAPABILITY_REQUEST), parameters=params)
        await vc._send_event_to_host(evt)
        await asyncio.sleep(0.05)
        assert len(seen) == 1
    finally:
        await host_t.close()


async def test_on_simple_pairing_complete_fires():
    vc, host_t = await VirtualController.create()
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)
    seen: list = []
    hci.on_simple_pairing_complete(lambda status, addr: seen.append((status, addr)))
    try:
        await hci.initialize()
        params = b"\x00" + bytes(reversed(b"\x01\x02\x03\x04\x05\x06"))
        evt = HCIEvent(event_code=int(EventCode.SIMPLE_PAIRING_COMPLETE), parameters=params)
        await vc._send_event_to_host(evt)
        await asyncio.sleep(0.05)
        assert seen and seen[0][0] == 0
    finally:
        await host_t.close()


async def test_on_link_key_notification_fires():
    vc, host_t = await VirtualController.create()
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)
    seen: list = []
    hci.on_link_key_notification(lambda addr, key, key_type: seen.append((addr, key, key_type)))
    try:
        await hci.initialize()
        params = bytes(reversed(b"\x01\x02\x03\x04\x05\x06")) + b"\xBB" * 16 + bytes([0x07])
        evt = HCIEvent(event_code=int(EventCode.LINK_KEY_NOTIFICATION), parameters=params)
        await vc._send_event_to_host(evt)
        await asyncio.sleep(0.05)
        assert len(seen) == 1
        _, key, key_type = seen[0]
        assert key == b"\xBB" * 16
        assert key_type == 0x07
    finally:
        await host_t.close()
```

### Step 3.2: Run test to verify it fails

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/hci/test_sc_listener_apis.py -v --transport=virtual
```

Expected: AttributeError on `on_io_capability_request` etc.

### Step 3.3: Add listener APIs

- [ ] **Modify `pybluehost/hci/controller.py`** — in `HCIController.__init__`, add (alongside `_encryption_change_listeners` etc.):

```python
        self._io_capability_request_listeners: list = []
        self._user_confirmation_request_listeners: list = []
        self._simple_pairing_complete_listeners: list = []
        self._link_key_notification_listeners: list = []
        self._link_key_request_listeners: list = []
```

Add registration methods (near other `on_*`):

```python
    def on_io_capability_request(self, listener) -> None:
        """Register listener called as (addr: BDAddress) when IO_Capability_Request fires."""
        self._io_capability_request_listeners.append(listener)

    def on_user_confirmation_request(self, listener) -> None:
        """Register listener called as (addr: BDAddress, numeric_value: int) when User_Confirmation_Request fires."""
        self._user_confirmation_request_listeners.append(listener)

    def on_simple_pairing_complete(self, listener) -> None:
        """Register listener called as (status: int, addr: BDAddress) when Simple_Pairing_Complete fires."""
        self._simple_pairing_complete_listeners.append(listener)

    def on_link_key_notification(self, listener) -> None:
        """Register listener called as (addr: BDAddress, link_key: bytes, key_type: int)."""
        self._link_key_notification_listeners.append(listener)

    def on_link_key_request(self, listener) -> None:
        """Register listener called as (addr: BDAddress) when Link_Key_Request fires."""
        self._link_key_request_listeners.append(listener)
```

In the HCI event dispatcher (search for existing dispatch — likely in `_handle_event` or wherever existing `on_encryption_change` is invoked), add dispatch for each event:

```python
        from pybluehost.core.address import BDAddress
        from pybluehost.hci.constants import EventCode

        if event.event_code == EventCode.IO_CAPABILITY_REQUEST and len(event.parameters) >= 6:
            addr = BDAddress(bytes(reversed(event.parameters[:6])))  # wire LE → BDAddress BE
            for listener in list(self._io_capability_request_listeners):
                result = listener(addr)
                if asyncio.iscoroutine(result):
                    await result

        if event.event_code == EventCode.USER_CONFIRMATION_REQUEST and len(event.parameters) >= 10:
            addr = BDAddress(bytes(reversed(event.parameters[:6])))
            numeric = int.from_bytes(event.parameters[6:10], "little")
            for listener in list(self._user_confirmation_request_listeners):
                result = listener(addr, numeric)
                if asyncio.iscoroutine(result):
                    await result

        if event.event_code == EventCode.SIMPLE_PAIRING_COMPLETE and len(event.parameters) >= 7:
            status = event.parameters[0]
            addr = BDAddress(bytes(reversed(event.parameters[1:7])))
            for listener in list(self._simple_pairing_complete_listeners):
                result = listener(status, addr)
                if asyncio.iscoroutine(result):
                    await result

        if event.event_code == EventCode.LINK_KEY_NOTIFICATION and len(event.parameters) >= 23:
            addr = BDAddress(bytes(reversed(event.parameters[:6])))
            key = event.parameters[6:22]
            key_type = event.parameters[22]
            for listener in list(self._link_key_notification_listeners):
                result = listener(addr, key, key_type)
                if asyncio.iscoroutine(result):
                    await result

        if event.event_code == EventCode.LINK_KEY_REQUEST and len(event.parameters) >= 6:
            addr = BDAddress(bytes(reversed(event.parameters[:6])))
            for listener in list(self._link_key_request_listeners):
                result = listener(addr)
                if asyncio.iscoroutine(result):
                    await result
```

### Step 3.4: Verify

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/hci/test_sc_listener_apis.py -v --transport=virtual
uv run --frozen pytest tests/unit/hci/ -q --transport=virtual
uv run --frozen pytest tests/ -q --transport=virtual --tb=no 2>&1 | tail -7
```

Expected: 3 new tests PASS; no regressions.

### Step 3.5: Commit

- [ ] **Run:**

```bash
git add pybluehost/hci/controller.py tests/unit/hci/test_sc_listener_apis.py
git commit -m "feat(hci): add 5 SC HCI event listener APIs

HCIController exposes on_io_capability_request, on_user_confirmation_request,
on_simple_pairing_complete, on_link_key_notification, on_link_key_request.
Each is fired by the existing event dispatcher when the corresponding
HCI event arrives. Foundation for SSPManager extension in Task 13."
```

---

## Task 4: `HCIController.initialize()` enables BR/EDR SC

**Files:**
- Modify: `pybluehost/hci/capabilities.py`
- Modify: `pybluehost/hci/controller.py`
- Modify: `pybluehost/hci/virtual.py`

### Step 4.1: Add SC opcode to capabilities registry

- [ ] **Modify `pybluehost/hci/capabilities.py`** — add to `_OPCODE_BIT_POSITIONS` (alphabetical/logical place):

```python
    HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT: (32, 3),
```

Plus the import of `HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT` from constants.

### Step 4.2: Make VirtualController advertise the new bit

- [ ] **Modify `pybluehost/hci/virtual.py`** — `_handle_read_local_supported_commands` already builds the bitmap from `_OPCODE_BIT_POSITIONS.values()`, so adding the entry in Step 4.1 automatically makes the VC permissive bitmap include this command. No change needed unless the VC also needs a handler.

Add a handler for the new command (returns success, no return params):

```python
            HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT: self._handle_status_only,
```

Place in the existing `_handlers` dict where other status-only commands are registered. `_handle_status_only` should already exist as a generic helper.

### Step 4.3: Write failing test

- [ ] **Create `tests/unit/hci/test_initialize_sc_gating.py`:**

```python
"""HCIController.initialize() conditionally enables BR/EDR Secure Connections."""
from __future__ import annotations

from pybluehost.ble.security import SecurityConfig
from pybluehost.hci.controller import HCIController
from pybluehost.hci.packets import HCI_Write_Secure_Connections_Host_Support_Command
from pybluehost.hci.virtual import VirtualController


async def test_initialize_skips_write_sc_when_config_off():
    vc, host_t = await VirtualController.create()
    sent: list = []
    hci = HCIController(
        transport=host_t, trace=None, command_timeout=2.0,
        security_config=SecurityConfig(enable_secure_connections=False),
    )
    original_send = hci.send_command

    async def _capture(cmd):
        sent.append(cmd)
        return await original_send(cmd)
    hci.send_command = _capture
    try:
        await hci.initialize()
        assert not any(isinstance(c, HCI_Write_Secure_Connections_Host_Support_Command) for c in sent)
    finally:
        await host_t.close()


async def test_initialize_issues_write_sc_when_config_on():
    vc, host_t = await VirtualController.create()
    sent: list = []
    hci = HCIController(
        transport=host_t, trace=None, command_timeout=2.0,
        security_config=SecurityConfig(enable_secure_connections=True),
    )
    original_send = hci.send_command

    async def _capture(cmd):
        sent.append(cmd)
        return await original_send(cmd)
    hci.send_command = _capture
    try:
        await hci.initialize()
        sc_cmds = [c for c in sent if isinstance(c, HCI_Write_Secure_Connections_Host_Support_Command)]
        assert len(sc_cmds) == 1
        assert sc_cmds[0].secure_connections_host_support == 0x01
    finally:
        await host_t.close()
```

### Step 4.4: Modify `HCIController.__init__` to accept security_config

- [ ] **Modify `pybluehost/hci/controller.py`** — `HCIController.__init__` signature:

```python
    def __init__(
        self,
        transport: object,
        trace: object | None,
        command_timeout: float = 5.0,
        *,
        security_config: "SecurityConfig | None" = None,
    ) -> None:
```

Store `self._security_config = security_config`.

Add import at top:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pybluehost.ble.security import SecurityConfig
```

### Step 4.5: Add SC enablement step in `initialize()`

- [ ] **Modify `pybluehost/hci/controller.py`** `initialize()` — after the `Write_Simple_Pairing_Mode` command in the optional batch (or wherever in the gated-optional loop), add:

The cleanest approach: keep the existing 13 optional commands list, then after the loop add a special block for SC:

```python
        # SC enablement — gated on both config AND controller support
        if (self._security_config is not None
            and self._security_config.enable_secure_connections):
            if self._supported_commands.has(HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT):
                await self.send_command(HCI_Write_Secure_Connections_Host_Support_Command(
                    secure_connections_host_support=0x01,
                ))
            else:
                logger.warning(
                    "controller does not support BR/EDR Secure Connections "
                    "(Write_Secure_Connections_Host_Support unsupported); falling back to Legacy SSP"
                )
```

Add the necessary imports at the top of the method body:

```python
        from pybluehost.hci.constants import HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT
        from pybluehost.hci.packets import HCI_Write_Secure_Connections_Host_Support_Command
```

### Step 4.6: Update Stack._build to pass security_config to HCIController

- [ ] **Modify `pybluehost/stack.py`** — in `_build`:

```python
        hci = HCIController(
            transport=transport, trace=trace, command_timeout=cfg.command_timeout,
            security_config=cfg.security,
        )
```

### Step 4.7: Verify

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/hci/test_initialize_sc_gating.py -v --transport=virtual
uv run --frozen pytest tests/unit/hci/ tests/unit/test_stack.py tests/unit/test_stack_pair_api.py -q --transport=virtual
uv run --frozen pytest tests/ -q --transport=virtual --tb=no 2>&1 | tail -7
```

Expected: 2 new tests PASS; no regressions.

### Step 4.8: Commit

- [ ] **Run:**

```bash
git add pybluehost/hci/ pybluehost/stack.py tests/unit/hci/test_initialize_sc_gating.py
git commit -m "feat(hci): conditionally enable BR/EDR Secure Connections in initialize()

HCIController gains a security_config kwarg. When config-on AND controller
supports it (per Supported_Commands bitmap, octet 32 bit 3),
HCI_Write_Secure_Connections_Host_Support(enabled=1) is issued after the
standard optional commands. Default config is SC-off so existing
behavior is unchanged."
```

---

## Task 5: `_smp_sc_crypto.py` — ECDH P-256

**Files:**
- Create: `pybluehost/ble/_smp_sc_crypto.py`
- Create: `tests/unit/ble/test_smp_sc_crypto.py`

### Step 5.1: Write failing tests

- [ ] **Create `tests/unit/ble/test_smp_sc_crypto.py`:**

```python
"""ECDH P-256 keypair + DHKey + byte-order tests using Core 5.4 Vol 3 Part H App D test vectors."""
from __future__ import annotations

from pybluehost.ble._smp_sc_crypto import compute_dhkey, generate_p256_keypair


def test_keypair_sizes():
    priv, pub = generate_p256_keypair()
    assert len(priv) == 32
    assert len(pub) == 64  # X (32) || Y (32), each little-endian


def test_keypair_is_ephemeral():
    """Each call returns a fresh keypair."""
    priv1, pub1 = generate_p256_keypair()
    priv2, pub2 = generate_p256_keypair()
    assert priv1 != priv2
    assert pub1 != pub2


def test_dhkey_symmetric_property():
    """ECDH(A_priv, B_pub) == ECDH(B_priv, A_pub).

    This is the foundational ECDH property; the actual SC pairing relies on it.
    """
    priv_a, pub_a = generate_p256_keypair()
    priv_b, pub_b = generate_p256_keypair()
    dhkey_ab = compute_dhkey(priv_a, pub_b)
    dhkey_ba = compute_dhkey(priv_b, pub_a)
    assert dhkey_ab == dhkey_ba
    assert len(dhkey_ab) == 32


def test_dhkey_spec_test_vector():
    """Core 5.4 Vol 3 Part H Appendix D.5.6 — ECDH test vector.

    Sample initiator private key Ai:
      3f49f6d4 a3c55f38 74c9b3e3 d2103f50 4aff607b eb40b799 5899b8a6 cd3c1abd
    Sample responder private key Bi:
      55188b3d 32f6bb9a 900afcfb eed4e72a 59cb9ac2 f19d7cfb 6b4fdd49 f47fc5fd
    Sample responder public key (Bx, By) — little-endian as on the wire — see App D
    Sample DHKey:
      ec0234a3 57c8ad05 341010a6 0a397d9b 99796b13 b4f866f1 868d34f3 73bfa698

    NOTE: cryptography library returns big-endian; conversion happens inside compute_dhkey.
    """
    # Initiator private (big-endian as cryptography expects internally; bytes.fromhex is BE):
    priv_a_be = bytes.fromhex("3f49f6d4a3c55f3874c9b3e3d2103f504aff607beb40b7995899b8a6cd3c1abd")
    # Responder private:
    priv_b_be = bytes.fromhex("55188b3d32f6bb9a900afcfbeed4e72a59cb9ac2f19d7cfb6b4fdd49f47fc5fd")
    # Our API takes LITTLE-ENDIAN per BT spec wire format
    priv_a = priv_a_be[::-1]
    priv_b = priv_b_be[::-1]
    # Compute pub for B using cryptography directly (the public-key derivation matches both libs)
    from cryptography.hazmat.primitives.asymmetric import ec
    sk_b = ec.derive_private_key(int.from_bytes(priv_b_be, "big"), ec.SECP256R1())
    pub_b_point = sk_b.public_key().public_numbers()
    pub_b_x_be = pub_b_point.x.to_bytes(32, "big")
    pub_b_y_be = pub_b_point.y.to_bytes(32, "big")
    pub_b = pub_b_x_be[::-1] + pub_b_y_be[::-1]
    # Compute DHKey
    dhkey = compute_dhkey(priv_a, pub_b)
    # Expected DHKey (big-endian per spec; our API returns little-endian)
    expected_be = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b99796b13b4f866f1868d34f373bfa698")
    assert dhkey == expected_be[::-1], f"DHKey mismatch:\n got  {dhkey.hex()}\n want {expected_be[::-1].hex()}"
```

### Step 5.2: Run test to verify it fails

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/ble/test_smp_sc_crypto.py -v --transport=virtual
```

Expected: `ImportError` on `pybluehost.ble._smp_sc_crypto`.

### Step 5.3: Implement `_smp_sc_crypto.py`

- [ ] **Create `pybluehost/ble/_smp_sc_crypto.py`:**

```python
"""ECDH P-256 primitives for LE Secure Connections.

BT Core 5.4 Vol 3 Part H §2.3.5.6.1 defines the SC pairing using P-256 ECDH.
The wire format is little-endian (LSB first); `cryptography` uses big-endian
internally. This module handles the byte-order conversion at the boundary.
"""
from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


def generate_p256_keypair() -> tuple[bytes, bytes]:
    """Generate an ephemeral P-256 keypair.

    Returns:
        (private_key, public_key) where:
        - private_key: 32 bytes, little-endian
        - public_key: 64 bytes = X (32 bytes LE) || Y (32 bytes LE)
    """
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_value = private_key.private_numbers().private_value
    priv_bytes_be = private_value.to_bytes(32, "big")
    pub_numbers = private_key.public_key().public_numbers()
    pub_x_be = pub_numbers.x.to_bytes(32, "big")
    pub_y_be = pub_numbers.y.to_bytes(32, "big")
    # Convert all to LE on the wire
    return priv_bytes_be[::-1], pub_x_be[::-1] + pub_y_be[::-1]


def compute_dhkey(local_private: bytes, peer_public: bytes) -> bytes:
    """Compute DHKey = ECDH(local_private, peer_public).

    Args:
        local_private: 32-byte little-endian private scalar.
        peer_public: 64-byte little-endian public point (X || Y).

    Returns:
        DHKey: 32-byte little-endian shared X coordinate.
    """
    if len(local_private) != 32:
        raise ValueError(f"private key must be 32 bytes, got {len(local_private)}")
    if len(peer_public) != 64:
        raise ValueError(f"public key must be 64 bytes, got {len(peer_public)}")

    # Convert LE → BE for cryptography
    priv_be = bytes(reversed(local_private))
    peer_x_be = bytes(reversed(peer_public[:32]))
    peer_y_be = bytes(reversed(peer_public[32:]))

    private_value = int.from_bytes(priv_be, "big")
    private_key = ec.derive_private_key(private_value, ec.SECP256R1())

    peer_x = int.from_bytes(peer_x_be, "big")
    peer_y = int.from_bytes(peer_y_be, "big")
    peer_pub_numbers = ec.EllipticCurvePublicNumbers(peer_x, peer_y, ec.SECP256R1())
    peer_pub_key = peer_pub_numbers.public_key()

    shared = private_key.exchange(ec.ECDH(), peer_pub_key)
    # `exchange` returns the X coordinate as big-endian. Convert to LE on output.
    return bytes(reversed(shared))
```

### Step 5.4: Verify

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/ble/test_smp_sc_crypto.py -v --transport=virtual
```

Expected: 4 tests PASS.

If `test_dhkey_spec_test_vector` fails, the byte-order conversion is off somewhere. Re-check that:
- `private_value.to_bytes(32, "big")` converts the Python int to BE bytes
- Output reversed gives LE
- DHKey output: `private_key.exchange()` returns BE; we reverse to LE

### Step 5.5: Commit

- [ ] **Run:**

```bash
git add pybluehost/ble/_smp_sc_crypto.py tests/unit/ble/test_smp_sc_crypto.py
git commit -m "feat(ble): add ECDH P-256 primitives for LE Secure Connections

_smp_sc_crypto.py provides generate_p256_keypair() and compute_dhkey()
with BT-spec little-endian wire format. Wraps cryptography library's
big-endian internal representation at the module boundary. Verified
against Core 5.4 Vol 3 Part H Appendix D test vector."
```

---

## Task 6: SMP PDUs + state/event enums + context fields

**Files:**
- Modify: `pybluehost/ble/smp.py`
- Create: `tests/unit/ble/test_smp_sc_pdus.py`

### Step 6.1: Write failing test

- [ ] **Create `tests/unit/ble/test_smp_sc_pdus.py`:**

```python
"""SMP Secure Connections PDU encode/decode."""
from __future__ import annotations

from pybluehost.ble.smp import (
    SMPCode,
    SMPPairingDHKeyCheck,
    SMPPairingPublicKey,
    decode_smp_pdu,
)


def test_pairing_public_key_round_trip():
    pdu = SMPPairingPublicKey(
        public_key_x=bytes(range(32)),
        public_key_y=bytes(range(32, 64)),
    )
    raw = pdu.to_bytes()
    assert raw[0] == SMPCode.PAIRING_PUBLIC_KEY
    assert len(raw) == 1 + 64
    decoded = decode_smp_pdu(raw)
    assert isinstance(decoded, SMPPairingPublicKey)
    assert decoded.public_key_x == bytes(range(32))
    assert decoded.public_key_y == bytes(range(32, 64))


def test_pairing_dhkey_check_round_trip():
    pdu = SMPPairingDHKeyCheck(dhkey_check=bytes(range(16)))
    raw = pdu.to_bytes()
    assert raw[0] == SMPCode.PAIRING_DHKEY_CHECK
    assert len(raw) == 1 + 16
    decoded = decode_smp_pdu(raw)
    assert isinstance(decoded, SMPPairingDHKeyCheck)
    assert decoded.dhkey_check == bytes(range(16))


def test_state_enum_has_sc_states():
    from pybluehost.ble.smp import SMPState
    assert "PUBLIC_KEY_EXCHANGE" in {s.name for s in SMPState}
    assert "DHKEY_CHECK" in {s.name for s in SMPState}


def test_event_enum_has_sc_events():
    from pybluehost.ble.smp import SMPEvent
    assert "PAIRING_PUBLIC_KEY_RX" in {e.name for e in SMPEvent}
    assert "PAIRING_DHKEY_CHECK_RX" in {e.name for e in SMPEvent}


def test_context_has_sc_fields():
    from pybluehost.ble.smp import PairingRole, SMPPairingContext
    from pybluehost.core.address import BDAddress
    ctx = SMPPairingContext.create(
        connection_handle=0x0040,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        role=PairingRole.INITIATOR,
    )
    # All SC fields exist and default to empty bytes
    assert ctx.local_private_key == b""
    assert ctx.local_public_key == b""
    assert ctx.peer_public_key == b""
    assert ctx.dhkey == b""
    assert ctx.mac_key == b""
    assert ctx.ltk_sc == b""
    assert ctx.local_dhkey_check == b""
    assert ctx.peer_dhkey_check == b""
```

### Step 6.2: Run test to verify it fails

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/ble/test_smp_sc_pdus.py -v --transport=virtual
```

Expected: ImportError / AttributeError on new PDUs / states / events / fields.

### Step 6.3: Add SMPCode entries + PDU classes

- [ ] **Modify `pybluehost/ble/smp.py`** `SMPCode` enum:

```python
class SMPCode(IntEnum):
    # existing...
    PAIRING_PUBLIC_KEY  = 0x0C
    PAIRING_DHKEY_CHECK = 0x0D
```

Add PDU classes — place near other PDU classes, follow existing pattern:

```python
@dataclass
class SMPPairingPublicKey(SMPPdu):
    """Pairing Public Key PDU (Core 5.4 Vol 3 Part H §3.5.6)."""
    public_key_x: bytes = b""
    public_key_y: bytes = b""

    @property
    def code(self) -> int:
        return SMPCode.PAIRING_PUBLIC_KEY

    def to_bytes(self) -> bytes:
        if len(self.public_key_x) != 32 or len(self.public_key_y) != 32:
            raise ValueError("public_key_x and public_key_y must each be 32 bytes")
        return bytes([SMPCode.PAIRING_PUBLIC_KEY]) + self.public_key_x + self.public_key_y

    @classmethod
    def from_bytes(cls, data: bytes) -> "SMPPairingPublicKey":
        if len(data) != 65:
            raise ValueError(f"SMPPairingPublicKey must be 65 bytes, got {len(data)}")
        return cls(public_key_x=data[1:33], public_key_y=data[33:65])


@dataclass
class SMPPairingDHKeyCheck(SMPPdu):
    """Pairing DHKey Check PDU (Core 5.4 Vol 3 Part H §3.5.7)."""
    dhkey_check: bytes = b""

    @property
    def code(self) -> int:
        return SMPCode.PAIRING_DHKEY_CHECK

    def to_bytes(self) -> bytes:
        if len(self.dhkey_check) != 16:
            raise ValueError("dhkey_check must be 16 bytes")
        return bytes([SMPCode.PAIRING_DHKEY_CHECK]) + self.dhkey_check

    @classmethod
    def from_bytes(cls, data: bytes) -> "SMPPairingDHKeyCheck":
        if len(data) != 17:
            raise ValueError(f"SMPPairingDHKeyCheck must be 17 bytes, got {len(data)}")
        return cls(dhkey_check=data[1:17])
```

Adjust `to_bytes` / `from_bytes` shape to match existing PDU classes in the file — they may use `@property code` differently. Match the existing pattern.

Update `decode_smp_pdu` to dispatch the new opcodes to these classes.

### Step 6.4: Extend SMPState / SMPEvent / SMPPairingContext

- [ ] **Modify `pybluehost/ble/smp.py`**:

```python
class SMPState(IntEnum):
    # existing 8 states...
    PUBLIC_KEY_EXCHANGE = 8
    DHKEY_CHECK         = 9


class SMPEvent(IntEnum):
    # existing 16 events...
    PAIRING_PUBLIC_KEY_RX  = 16
    PAIRING_DHKEY_CHECK_RX = 17
```

In `SMPPairingContext`:

```python
    # SC working state (added by Sub-Plan 2)
    local_private_key: bytes = b""
    local_public_key: bytes = b""
    peer_public_key: bytes = b""
    dhkey: bytes = b""
    mac_key: bytes = b""
    ltk_sc: bytes = b""
    local_dhkey_check: bytes = b""
    peer_dhkey_check: bytes = b""
```

Update the SC-aware `_pdu_to_event` mapping in `SMPManager`:

```python
    mapping = {
        # existing entries...
        SMPCode.PAIRING_PUBLIC_KEY: SMPEvent.PAIRING_PUBLIC_KEY_RX,
        SMPCode.PAIRING_DHKEY_CHECK: SMPEvent.PAIRING_DHKEY_CHECK_RX,
    }
```

### Step 6.5: Verify

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/ble/test_smp_sc_pdus.py tests/unit/ble/test_smp_state_machine.py -v --transport=virtual
```

Expected: 5 new tests PASS; existing state-machine tests still PASS.

### Step 6.6: Commit

- [ ] **Run:**

```bash
git add pybluehost/ble/smp.py tests/unit/ble/test_smp_sc_pdus.py
git commit -m "feat(ble/smp): add SC PDUs, states, events, and context fields

SMPCode adds PAIRING_PUBLIC_KEY (0x0C) and PAIRING_DHKEY_CHECK (0x0D).
SMPState adds PUBLIC_KEY_EXCHANGE, DHKEY_CHECK.
SMPEvent adds PAIRING_PUBLIC_KEY_RX, PAIRING_DHKEY_CHECK_RX.
SMPPairingContext adds 8 SC working-state fields (local/peer keys, DHKey,
MacKey, LTK_sc, dhkey_check values).

Foundation for SC state-machine transitions (Tasks 7-11)."
```

---

## Task 7-11: SC state-machine transitions

These five tasks implement the SC pairing flow inside `_smp_state.py`. The state machine framework, helper structure, and patterns are inherited from Sub-Plan 1's `_smp_state.py`. Each task adds a phase + corresponding test.

### Task 7: SC vs Legacy branching at FEATURE_EXCHANGE exit

Update `register_transitions(ctx)` to inspect `ctx.security_config.enable_secure_connections` and the peer's `auth_req` SC bit (0x08). If both set → register SC transitions; else → register Legacy transitions (existing behavior).

Steps:
- [ ] Add `security_config` field to `SMPPairingContext.create()`; default `None`
- [ ] `SMPManager.start_initiator` and the Responder-create path pass `self._security_config` (new field on SMPManager from Task 1)
- [ ] In `_initiator_send_pairing_request`: when `ctx.security_config and ctx.security_config.enable_secure_connections`, set `auth_req |= 0x08` (SC bit)
- [ ] In `_initiator_recv_pairing_response`: observe `pdu.auth_req & 0x08`. If both local AND peer SC bits set, branch to `_sc_initiator_send_public_key` instead of `_initiator_recv_pairing_response`'s legacy Confirm path
- [ ] Same fork in `_responder_recv_pairing_request`

Test: `tests/unit/ble/test_smp_sc_legacy_fallback.py` — when config off, SC bit never set; when peer offers SC but config off, ignore peer's SC bit and continue Legacy.

Commit: `feat(ble/smp): SC vs Legacy branching at Phase 1 exit`

### Task 8: SC Phase 2.1 — Public Key exchange

Add transitions:
- `FEATURE_EXCHANGE → PUBLIC_KEY_EXCHANGE` on local action `_sc_send_public_key` (called inside Phase 1 action when SC selected)
- `PUBLIC_KEY_EXCHANGE → PUBLIC_KEY_EXCHANGE` on `PAIRING_PUBLIC_KEY_RX` (peer's key received → compute DHKey → wait for Responder Confirm)

Steps:
- [ ] `_sc_send_public_key(ctx)`: generate keypair, store local_private/public, send `SMPPairingPublicKey`
- [ ] `_sc_recv_public_key(ctx, pdu)`: store peer_public_key, compute DHKey via `compute_dhkey(local_private, peer_public)`
- [ ] On Responder side: after sending its own public key in response to Initiator's, also generate Nb, compute Cb = `f4(PKbx, PKax, Nb, 0)`, send `SMPPairingConfirm(Cb)` → state advances to `CONFIRMING`
- [ ] Initiator: after receiving peer's public key, wait in `PUBLIC_KEY_EXCHANGE` for `PAIRING_CONFIRM_RX` (Responder's Cb)

Test: `tests/unit/ble/test_smp_le_sc_state_machine.py` — drive both sides through public key exchange + assert DHKey computed + Cb sent (Responder) / Confirm awaited (Initiator).

Commit: `feat(ble/smp): SC Phase 2.1 public key exchange`

### Task 9: SC Phase 2.2 — Confirm/Random + f4 verify + f5 LTK derivation

Add transitions:
- `PUBLIC_KEY_EXCHANGE → CONFIRMING` on Initiator side: after sending Nb, Responder's `PAIRING_CONFIRM_RX` arrives → store, send Na
- `CONFIRMING → RANDOM_EXCHANGE` on `PAIRING_RANDOM_RX` (Na for Responder, Nb for Initiator): generate own Random, send, verify peer Cb (Initiator only — Responder didn't receive a Cb), derive (MacKey, LTK) = f5(DHKey, Na, Nb, A, B)

Actions:
- [ ] `_sc_initiator_recv_responder_confirm(ctx, pdu)`: store Cb, send Na (already generated locally or generate now)
- [ ] `_sc_recv_random(ctx, pdu)`: store peer_random, if Initiator verify Cb == f4(PKbx, PKax, Nb, 0). On mismatch fail with reason=0x04 (DHKEY_CHECK_FAILED is for Phase 2.3; Confirm Value Failed = 0x04 fits here). On success derive MacKey + LTK_sc via SMPCrypto.f5.

Test: drive both sides through full Phase 2.2; assert LTK derived; assert correct failure on tampered Cb.

Commit: `feat(ble/smp): SC Phase 2.2 confirm/random + f5 LTK derivation`

### Task 10: SC Phase 2.3 — DHKey check (f6) + encryption start

Add transitions:
- `RANDOM_EXCHANGE → DHKEY_CHECK` on local action `_sc_send_dhkey_check`: compute Ea (Initiator) or Eb (Responder) via `f6(MacKey, NA, NB, ra/rb=0, IOcap, A, B)`, send `SMPPairingDHKeyCheck`
- `DHKEY_CHECK → DHKEY_CHECK` on `PAIRING_DHKEY_CHECK_RX`: verify peer's value via `f6(MacKey, NB, NA, ra/rb=0, peer_IOcap, B, A)`. On mismatch fail with reason=0x0B (DHKey Check Failed)
- After both checks succeed (Initiator): `DHKEY_CHECK → STK_ENCRYPTING` via `HCI_LE_Start_Encryption(handle, ediv=0, rand=0, ltk=ltk_sc)` (use the f5-derived LTK directly; no STK indirection in SC)

Add new failure reason constant:

```python
PAIRING_FAILED_REASON_DHKEY_CHECK_FAILED = 0x0B
```

Commit: `feat(ble/smp): SC Phase 2.3 DHKey check + LTK encryption start`

### Task 11: SC Phase 3 — skip LTK distribution + BondInfo(sc=True)

In SC mode, `_start_phase3` should:
- [ ] NOT distribute LTK (both sides already have the f5-derived LTK)
- [ ] Still distribute IRK + IdentityAddress per masks (if mask & 0x02)
- [ ] Still distribute CSRK per masks (if mask & 0x04)
- [ ] `_persist_bond` sets `BondInfo.sc=True`, `BondInfo.ltk=ctx.ltk_sc` (the f5-derived LTK), `BondInfo.authenticated=False` (Just Works)

Add a branch in `_start_phase3` based on `ctx.role == PairingRole.INITIATOR` (existing) + `ctx.security_config.enable_secure_connections AND (ctx.local_auth_req & 0x08) AND (ctx.peer_auth_req & 0x08)`:

```python
sc_mode = (
    ctx.security_config is not None
    and ctx.security_config.enable_secure_connections
    and (ctx.local_auth_req & 0x08)
    and (ctx.peer_auth_req & 0x08)
)
if not sc_mode and (mask & 0x01):
    # Legacy LTK distribution — existing path
    ...
elif sc_mode:
    # Skip LTK distribution
    pass
# IRK / CSRK distribution unchanged
```

Test: extend `test_smp_phase3_key_distribution.py` with SC variant — assert no `SMPEncryptionInformation`/`SMPMasterIdentification` sent in SC mode; `BondInfo.sc==True`.

Commit: `feat(ble/smp): SC Phase 3 — skip LTK distribution, BondInfo(sc=True)`

---

## Task 12: LE SC loopback E2E test

**Files:**
- Create: `tests/integration/test_pairing_le_sc_loopback.py`

### Step 12.1: Test

Use the same `VirtualLELink` pattern as Sub-Plan 1's `test_pairing_loopback.py`, but with `enable_secure_connections=True` on both stacks:

```python
async def test_two_virtual_stacks_pair_with_sc_just_works(tmp_path):
    from pybluehost.ble.security import SecurityConfig
    from pybluehost.ble.smp import JsonBondStorage
    from pybluehost.core.address import BDAddress
    from pybluehost.hci.virtual_link import VirtualLELink
    from pybluehost.stack import Stack, StackConfig

    storage_a = JsonBondStorage(tmp_path / "bonds_a.json")
    storage_b = JsonBondStorage(tmp_path / "bonds_b.json")
    cfg_a = StackConfig(
        bond_storage=storage_a,
        security=SecurityConfig(enable_secure_connections=True),
    )
    cfg_b = StackConfig(
        bond_storage=storage_b,
        security=SecurityConfig(enable_secure_connections=True),
    )
    stack_a = await Stack.virtual(config=cfg_a)
    stack_b = await Stack.virtual(config=cfg_b)

    link = VirtualLELink(
        central=stack_a._virtual_controller,
        peripheral=stack_b._virtual_controller,
        central_address=BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A"),
        peripheral_address=BDAddress(b"\x0B\x0B\x0B\x0B\x0B\x0B"),
    )
    handle = await link.connect()
    import asyncio; await asyncio.sleep(0.1)
    await stack_a.pair(handle=handle, timeout=15.0)

    bond_a = await storage_a.load_bond(BDAddress(b"\x0B\x0B\x0B\x0B\x0B\x0B"))
    bond_b = await storage_b.load_bond(BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A"))
    assert bond_a is not None and bond_a.sc is True
    assert bond_b is not None and bond_b.sc is True
    assert bond_a.ltk == bond_b.ltk  # SC LTK is shared (f5-derived)

    await link.disconnect()
    await stack_a.close()
    await stack_b.close()
```

Commit: `test(integration): LE SC Just Works loopback E2E`

---

## Task 13-14: SSPManager BR/EDR SC extension

### Task 13: SSPManager handles Simple_Pairing_Complete + Link_Key_Notification

Extend `pybluehost/classic/gap.py:SSPManager`:
- [ ] Add `_io_capability_request_listeners` not needed — register directly via `HCIController.on_io_capability_request(self._on_io_cap_req)` in `__init__`
- [ ] Existing `on_hci_event` handles IO_Capability_Request, Link_Key_Request, User_Confirmation_Request via if/elif. **NEW**: also handle `LINK_KEY_NOTIFICATION` and `SIMPLE_PAIRING_COMPLETE`
- [ ] When `enable_secure_connections=True`, set `authentication_requirements=0x04` (MITM Not Required + General Bonding + SC bit) in IO Capability reply
- [ ] On `SIMPLE_PAIRING_COMPLETE` with status=0 → emit a stack-level event "classic pairing complete"
- [ ] On `LINK_KEY_NOTIFICATION` → derive sc flag from key_type:
  - key_type 0x05 = Unauthenticated Combination Key from P-256 (SC, unauthenticated) → `sc=True, authenticated=False`
  - key_type 0x06 = Authenticated Combination Key from P-256 (SC, authenticated) → `sc=True, authenticated=True`
  - key_type 0x07 = General Bonding (newer naming; spec-version dependent) → `sc=True, authenticated=False`
  - key_type 0x08 = Authenticated Linked Key from P-256 → `sc=True, authenticated=True`
  - any 0x00-0x04 = Legacy SSP → `sc=False`
- [ ] Persist `BondInfo(peer_address, link_key, link_key_type, sc, authenticated)` to BondStorage

### Task 14: SSPManager Link_Key_Request reply lookup

- [ ] On `LINK_KEY_REQUEST`, look up bond by peer address. If `bond.link_key` exists → `HCI_Link_Key_Request_Reply(addr, link_key)`. Else → existing negative reply.

Tests for Tasks 13-14: `tests/unit/classic/test_ssp_secure_connections.py` — inject the 5 SSP events synthesized as `HCIEvent`s, drive `SSPManager.on_hci_event()`, assert correct HCI command replies, assert `BondInfo` persistence with correct `sc` and `link_key_type` fields.

Commits:
- `feat(classic/ssp): handle Simple_Pairing_Complete + Link_Key_Notification`
- `feat(classic/ssp): Link_Key_Request lookup for SC reconnect`

---

## Task 15: BR/EDR SC HCI-event-driven integration test

**Files:**
- Create: `tests/integration/test_pairing_classic_sc_hci.py`

Inject a full SSP event sequence (IO_Capability_Request → IO_Capability_Response → User_Confirmation_Request → Simple_Pairing_Complete → Link_Key_Notification) into a Stack with `enable_secure_connections=True`. Use `VirtualController.simulate_ssp_pairing(bd_addr, key_type)` test hook added in this task (extends `simulate_le_ltk_request`-style mechanism for Classic SSP).

- [ ] Add `VirtualController.simulate_ssp_pairing(bd_addr, key_type=0x07)` method that emits the 5 events with proper timing
- [ ] Assert SSPManager replies arrive in correct order with correct parameters
- [ ] Assert BondInfo persisted with `sc=True`, `link_key_type=0x07`

Commit: `test(integration): BR/EDR SC HCI-event-driven integration`

---

## Task 16: STATUS.md + Plan completion

**Files:**
- Modify: `docs/superpowers/STATUS.md`
- Modify: `docs/superpowers/plans/2026-05-17-secure-connections.md` (tick checkboxes)

### Step 16.1: Full regression

```bash
uv run --frozen pytest tests/ -q --transport=virtual --cov=pybluehost --cov-fail-under=85 --tb=no 2>&1 | tail -10
```

Expected: only 3 pre-existing failures; coverage ≥ 85%.

### Step 16.2: Tick all checkboxes

```bash
sed -i 's/^- \[ \]/- [x]/g' docs/superpowers/plans/2026-05-17-secure-connections.md
```

### Step 16.3: STATUS.md updates

Update 当前进行中 / 下一步; append Plan 总览 row; append 详细进度 block; increment Plan total.

### Step 16.4: Commit

```bash
git add docs/superpowers/STATUS.md docs/superpowers/plans/2026-05-17-secure-connections.md
git commit -m "docs(progress): Secure Connections (LE SC + BR/EDR SC) Plan complete"
```

---

## 验收清单

- [ ] `SecurityConfig.enable_secure_connections` defaults False; opt-in via config
- [ ] `_validate_sc_dependencies` raises `ConfigurationError` when CTKD enabled without SC
- [ ] LE SC Just Works pairing succeeds via loopback E2E with two `Stack.virtual()` instances
- [ ] LE SC bond persisted with `sc=True`, `authenticated=False`; both sides have identical f5-derived LTK
- [ ] When `enable_secure_connections=False`, SC bit never set in `auth_req` — Legacy path used
- [ ] BR/EDR SC HCI commands + events round-trip
- [ ] `HCIController.initialize()` issues `Write_Secure_Connections_Host_Support` when config-on AND controller supports it; warns and skips otherwise
- [ ] `SSPManager` handles full SSP event sequence; persists `BondInfo` with `link_key_type ∈ {0x05, 0x06, 0x07, 0x08}` and `sc=True` for P-256 keys
- [ ] `SSPManager` `Link_Key_Request` lookup works for SC reconnect
- [ ] Full suite: only 3 pre-existing USB diagnostics failures; coverage ≥ 85%

## Known risks / Troubleshooting

### Q: LE SC test vector (Task 5) fails
- Verify cryptography library version (≥ 41.0); `private_value.to_bytes(32, "big")` order matters. Try printing intermediate big-endian values before reversing.

### Q: f4 verification fails in Task 9
- f4 inputs in spec: `f4(U, V, X, Z)` where U=peer public key X coordinate, V=local public key X coordinate (NOT the full 64-byte public key — just the X half). Z is the authentication value: 0 for Just Works, the passkey bit for Passkey Entry. Double-check we're passing only the X coordinate (32 bytes) and Z=0.

### Q: Phase 3 in SC mode tries to send LTK
- Sub-Plan 1's `_start_phase3` issues `SMPEncryptionInformation` etc. when mask bit 0x01 is set. Add SC check: skip the EncKey distribution (mask bit 0x01) entirely in SC mode — but still send IRK (bit 0x02) and CSRK (bit 0x04). The mask check itself stays; just gate the EncKey block on `not sc_mode`.

### Q: BR/EDR SC bit position in IO_Capability_Request_Reply.authentication_requirements
- The "authentication_requirements" field in IO_Capability_Request_Reply has a different bit layout than SMP's auth_req. Per Core 5.4 Vol 4 Part E §7.1.30: values 0x00–0x05 (MITM No/Yes × No Bonding/Dedicated/General Bonding). The SC bit is NOT in this field — it's implicit via `Write_Secure_Connections_Host_Support`. So `auth_req=0x04` = MITM Not Required + General Bonding is correct; the controller infers SC mode from the global flag.

### Q: HCIController.send_command signature change breaks existing tests
- Adding `security_config` kwarg should be additive (keyword-only with default None). Existing callers passing positional args are unaffected. If tests pass `security_config` positionally somehow, fix the test.

Self-review:
- 16 tasks cover all design-doc components; each task has TDD scaffold
- No TBD/TODO placeholders; "verify which exist before adding" is a concrete check, not a placeholder
- Type consistency: `SecurityConfig.enable_secure_connections` named consistently across tasks; `_validate_sc_dependencies` signature consistent; HCI command names match `HCI_Write_Secure_Connections_Host_Support_Command` everywhere; SC PDU class names consistent (`SMPPairingPublicKey`, `SMPPairingDHKeyCheck`); SC state names (`PUBLIC_KEY_EXCHANGE`, `DHKEY_CHECK`) consistent across enum and transition code
- Tasks 7-11 are described at lower granularity than 1-6 because they're variations on the Sub-Plan 1 pattern; the implementer should reference `_smp_state.py` for the established style and produce per-task commits
