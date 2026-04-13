# Plan 1: Core Infrastructure Implementation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundational `pybluehost/core/` package that all protocol layers depend on — errors, address types, UUID types, key types, byte buffer helpers, state machine framework, trace system, and SIG database.

**Architecture:** Each module in `core/` is independent and has no dependency on any protocol layer. Modules may depend on each other in a strict DAG: `errors` ← `address` ← `uuid` ← `keys` ← `buffer`; `errors` ← `statemachine`; `statemachine` ← `trace`. The `sig_db` module depends only on `pyyaml` and the SIG submodule data files.

**Tech Stack:** Python 3.10+, pytest, pyyaml, asyncio

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/core/__init__.py` | Re-export public API for `core` |
| `pybluehost/core/errors.py` | Base exception hierarchy |
| `pybluehost/core/address.py` | `BDAddress`, `AddressType` |
| `pybluehost/core/uuid.py` | `UUID16`, `UUID128`, Bluetooth UUID constants |
| `pybluehost/core/keys.py` | `LinkKey`, `LTK`, `IRK`, `CSRK` key dataclasses |
| `pybluehost/core/types.py` | `IOCapability`, `ConnectionRole`, `LinkType` shared enums |
| `pybluehost/core/buffer.py` | `ByteBuffer` for PDU construction and parsing |
| `pybluehost/core/statemachine.py` | `StateMachine[S, E]`, `Transition`, `InvalidTransitionError` |
| `pybluehost/core/trace.py` | `TraceEvent`, `TraceSystem`, `TraceSink`, all sink implementations |
| `pybluehost/core/sig_db.py` | `SIGDatabase` singleton with lazy-loaded YAML lookups |
| `tests/unit/core/test_errors.py` | Error hierarchy tests |
| `tests/unit/core/test_address.py` | Address tests |
| `tests/unit/core/test_uuid.py` | UUID tests |
| `tests/unit/core/test_keys.py` | Key dataclass tests |
| `tests/unit/core/test_types.py` | Shared enum tests |
| `tests/unit/core/test_buffer.py` | ByteBuffer tests |
| `tests/unit/core/test_statemachine.py` | State machine tests |
| `tests/unit/core/test_trace.py` | Trace system tests |
| `tests/unit/core/test_sig_db.py` | SIG database tests |
| `tests/conftest.py` | Shared pytest fixtures |

---

## Task 1: Project Setup and Error Hierarchy

**Files:**
- Create: `pybluehost/core/__init__.py`
- Create: `pybluehost/core/errors.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/core/__init__.py`
- Create: `tests/unit/core/test_errors.py`
- Create: `tests/conftest.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pyyaml and pytest dependencies to pyproject.toml**

```toml
[project]
name = "pybluehost"
version = "0.0.1"
description = "A professional Python Bluetooth Host stack for testing, simulation and protocol education."
readme = "README.md"
license = "MIT"
requires-python = ">=3.10"
authors = [
    {name = "PyBlueHost Contributors"},
]
keywords = ["bluetooth", "ble", "hci", "host", "stack"]
classifiers = [
    "Development Status :: 1 - Planning",
    "Intended Audience :: Developers",
    "Intended Audience :: Education",
    "Topic :: Software Development :: Libraries",
    "Topic :: System :: Networking",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
dependencies = [
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
]

[project.urls]
Homepage = "https://github.com/xcode4096/pybluehost"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Run `uv sync` to install dependencies**

Run: `uv sync`
Expected: Dependencies installed, `.venv` updated.

- [ ] **Step 3: Create directory structure and __init__.py files**

Create `tests/__init__.py`, `tests/unit/__init__.py`, `tests/unit/core/__init__.py` — all empty files.

Create `tests/conftest.py`:

```python
"""Shared pytest fixtures for PyBlueHost test suite."""
```

Create `pybluehost/core/__init__.py`:

```python
"""PyBlueHost core infrastructure — shared by all protocol layers."""
```

- [ ] **Step 4: Write the failing test for errors**

```python
# tests/unit/core/test_errors.py
from pybluehost.core.errors import (
    PyBlueHostError,
    TransportError,
    HCIError,
    L2CAPError,
    GATTError,
    SMPError,
    InvalidTransitionError,
    TimeoutError as BTTimeoutError,
)


def test_base_error_is_exception():
    assert issubclass(PyBlueHostError, Exception)


def test_transport_error_inherits_base():
    err = TransportError("USB disconnected")
    assert isinstance(err, PyBlueHostError)
    assert str(err) == "USB disconnected"


def test_hci_error_with_status_code():
    err = HCIError("Command failed", status=0x02)
    assert isinstance(err, PyBlueHostError)
    assert err.status == 0x02
    assert "Command failed" in str(err)


def test_l2cap_error_inherits_base():
    err = L2CAPError("Channel refused")
    assert isinstance(err, PyBlueHostError)


def test_gatt_error_with_att_error_code():
    err = GATTError("Read not permitted", att_error=0x02)
    assert isinstance(err, PyBlueHostError)
    assert err.att_error == 0x02


def test_smp_error_with_reason():
    err = SMPError("Pairing failed", reason=0x04)
    assert isinstance(err, PyBlueHostError)
    assert err.reason == 0x04


def test_invalid_transition_error():
    err = InvalidTransitionError(
        sm_name="hci_conn",
        from_state="CONNECTED",
        event="CONNECT_COMPLETE",
    )
    assert isinstance(err, PyBlueHostError)
    assert "hci_conn" in str(err)
    assert "CONNECTED" in str(err)
    assert "CONNECT_COMPLETE" in str(err)


def test_timeout_error_inherits_base():
    err = BTTimeoutError("HCI command timeout", timeout=5.0)
    assert isinstance(err, PyBlueHostError)
    assert err.timeout == 5.0
```

- [ ] **Step 5: Run test to verify it fails**

Run: `uv run pytest tests/unit/core/test_errors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pybluehost.core.errors'`

- [ ] **Step 6: Write minimal implementation**

```python
# pybluehost/core/errors.py
from __future__ import annotations


class PyBlueHostError(Exception):
    """Base exception for all PyBlueHost errors."""


class TransportError(PyBlueHostError):
    """Transport layer error (USB disconnect, serial timeout, etc.)."""


class HCIError(PyBlueHostError):
    """HCI layer error with optional status code."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class L2CAPError(PyBlueHostError):
    """L2CAP layer error."""


class GATTError(PyBlueHostError):
    """GATT layer error with optional ATT error code."""

    def __init__(self, message: str, att_error: int = 0) -> None:
        super().__init__(message)
        self.att_error = att_error


class SMPError(PyBlueHostError):
    """SMP layer error with optional reason code."""

    def __init__(self, message: str, reason: int = 0) -> None:
        super().__init__(message)
        self.reason = reason


class InvalidTransitionError(PyBlueHostError):
    """Raised when a state machine receives an event with no defined transition."""

    def __init__(self, sm_name: str, from_state: str, event: str) -> None:
        self.sm_name = sm_name
        self.from_state = from_state
        self.event = event
        super().__init__(
            f"{sm_name}: no transition from {from_state} via {event}"
        )


class TimeoutError(PyBlueHostError):
    """Operation timed out."""

    def __init__(self, message: str, timeout: float = 0.0) -> None:
        super().__init__(message)
        self.timeout = timeout
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/unit/core/test_errors.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml pybluehost/core/__init__.py pybluehost/core/errors.py tests/ 
git commit -m "feat(core): add error hierarchy and project test setup"
```

---

## Task 2: Address Types

**Files:**
- Create: `pybluehost/core/address.py`
- Create: `tests/unit/core/test_address.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/core/test_address.py
import pytest
from pybluehost.core.address import BDAddress, AddressType


class TestAddressType:
    def test_enum_values(self):
        assert AddressType.PUBLIC == 0x00
        assert AddressType.RANDOM == 0x01
        assert AddressType.PUBLIC_IDENTITY == 0x02
        assert AddressType.RANDOM_IDENTITY == 0x03


class TestBDAddress:
    def test_from_string_public(self):
        addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        assert addr.address == bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])
        assert addr.type == AddressType.PUBLIC

    def test_from_string_random(self):
        addr = BDAddress.from_string("11:22:33:44:55:66", AddressType.RANDOM)
        assert addr.type == AddressType.RANDOM

    def test_from_string_lowercase(self):
        addr = BDAddress.from_string("aa:bb:cc:dd:ee:ff")
        assert addr.address == bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])

    def test_from_string_invalid_length(self):
        with pytest.raises(ValueError, match="6 colon-separated"):
            BDAddress.from_string("AA:BB:CC")

    def test_from_string_invalid_hex(self):
        with pytest.raises(ValueError):
            BDAddress.from_string("GG:HH:II:JJ:KK:LL")

    def test_str_representation(self):
        addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        assert str(addr) == "AA:BB:CC:DD:EE:FF"

    def test_equality(self):
        a = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        b = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        assert a == b

    def test_inequality_different_address(self):
        a = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        b = BDAddress.from_string("11:22:33:44:55:66")
        assert a != b

    def test_inequality_different_type(self):
        a = BDAddress.from_string("AA:BB:CC:DD:EE:FF", AddressType.PUBLIC)
        b = BDAddress.from_string("AA:BB:CC:DD:EE:FF", AddressType.RANDOM)
        assert a != b

    def test_hashable(self):
        addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        d = {addr: "test"}
        assert d[addr] == "test"

    def test_frozen(self):
        addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        with pytest.raises(AttributeError):
            addr.type = AddressType.RANDOM  # type: ignore[misc]

    def test_is_rpa_true(self):
        # RPA: top 2 bits of first byte are 01 (0x40-0x7F)
        addr = BDAddress(address=bytes([0x4A, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]), type=AddressType.RANDOM)
        assert addr.is_rpa is True

    def test_is_rpa_false_public(self):
        addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF", AddressType.PUBLIC)
        assert addr.is_rpa is False

    def test_is_rpa_false_static_random(self):
        # Static random: top 2 bits are 11 (0xC0-0xFF)
        addr = BDAddress(address=bytes([0xC0, 0x11, 0x22, 0x33, 0x44, 0x55]), type=AddressType.RANDOM)
        assert addr.is_rpa is False

    def test_random_factory(self):
        addr = BDAddress.random()
        assert addr.type == AddressType.RANDOM
        assert len(addr.address) == 6
        # Static random address: top 2 bits must be 11
        assert addr.address[0] & 0xC0 == 0xC0

    def test_from_bytes(self):
        raw = bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06])
        addr = BDAddress(address=raw)
        assert addr.address == raw
        assert addr.type == AddressType.PUBLIC
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/core/test_address.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# pybluehost/core/address.py
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import IntEnum


class AddressType(IntEnum):
    PUBLIC = 0x00
    RANDOM = 0x01
    PUBLIC_IDENTITY = 0x02
    RANDOM_IDENTITY = 0x03


@dataclass(frozen=True)
class BDAddress:
    """Bluetooth Device Address (6 bytes + type)."""

    address: bytes
    type: AddressType = AddressType.PUBLIC

    @classmethod
    def from_string(cls, s: str, type: AddressType = AddressType.PUBLIC) -> BDAddress:
        parts = s.split(":")
        if len(parts) != 6:
            raise ValueError(f"Expected 6 colon-separated hex bytes, got {len(parts)}")
        raw = bytes(int(p, 16) for p in parts)
        return cls(address=raw, type=type)

    @classmethod
    def random(cls) -> BDAddress:
        raw = bytearray(os.urandom(6))
        raw[0] = (raw[0] & 0x3F) | 0xC0  # static random: top 2 bits = 11
        return cls(address=bytes(raw), type=AddressType.RANDOM)

    @property
    def is_rpa(self) -> bool:
        if self.type != AddressType.RANDOM:
            return False
        return (self.address[0] & 0xC0) == 0x40

    def __str__(self) -> str:
        return ":".join(f"{b:02X}" for b in self.address)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/core/test_address.py -v`
Expected: All 16 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/core/address.py tests/unit/core/test_address.py
git commit -m "feat(core): add BDAddress and AddressType"
```

---

## Task 3: UUID Types

**Files:**
- Create: `pybluehost/core/uuid.py`
- Create: `tests/unit/core/test_uuid.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/core/test_uuid.py
import pytest
from pybluehost.core.uuid import UUID16, UUID128, BLUETOOTH_BASE_UUID


class TestUUID16:
    def test_create(self):
        u = UUID16(0x180D)
        assert u.value == 0x180D

    def test_str(self):
        assert str(UUID16(0x180D)) == "0x180D"

    def test_to_bytes_le(self):
        assert UUID16(0x180D).to_bytes() == b"\x0D\x18"

    def test_from_bytes_le(self):
        u = UUID16.from_bytes(b"\x0D\x18")
        assert u.value == 0x180D

    def test_to_uuid128(self):
        u128 = UUID16(0x180D).to_uuid128()
        assert isinstance(u128, UUID128)
        expected = bytearray(BLUETOOTH_BASE_UUID)
        expected[2] = 0x18
        expected[3] = 0x0D
        assert u128.value == bytes(expected)

    def test_equality(self):
        assert UUID16(0x180D) == UUID16(0x180D)
        assert UUID16(0x180D) != UUID16(0x180F)

    def test_hashable(self):
        s = {UUID16(0x180D), UUID16(0x180F), UUID16(0x180D)}
        assert len(s) == 2

    def test_from_bytes_wrong_length(self):
        with pytest.raises(ValueError):
            UUID16.from_bytes(b"\x01")

    def test_range_validation(self):
        with pytest.raises(ValueError):
            UUID16(0x10000)
        with pytest.raises(ValueError):
            UUID16(-1)


class TestUUID128:
    def test_create(self):
        val = bytes(range(16))
        u = UUID128(val)
        assert u.value == val

    def test_from_string(self):
        u = UUID128.from_string("0000180d-0000-1000-8000-00805f9b34fb")
        assert len(u.value) == 16

    def test_str(self):
        u = UUID128.from_string("0000180D-0000-1000-8000-00805F9B34FB")
        s = str(u)
        assert s.lower() == "0000180d-0000-1000-8000-00805f9b34fb"

    def test_to_bytes(self):
        val = bytes(range(16))
        assert UUID128(val).to_bytes() == val

    def test_from_bytes(self):
        val = bytes(range(16))
        u = UUID128.from_bytes(val)
        assert u.value == val

    def test_equality(self):
        a = UUID128.from_string("0000180d-0000-1000-8000-00805f9b34fb")
        b = UUID128.from_string("0000180d-0000-1000-8000-00805f9b34fb")
        assert a == b

    def test_hashable(self):
        a = UUID128.from_string("0000180d-0000-1000-8000-00805f9b34fb")
        d = {a: "test"}
        assert d[a] == "test"

    def test_from_string_invalid(self):
        with pytest.raises(ValueError):
            UUID128.from_string("not-a-uuid")

    def test_wrong_length_bytes(self):
        with pytest.raises(ValueError):
            UUID128(bytes(15))

    def test_is_bluetooth_base(self):
        u = UUID16(0x180D).to_uuid128()
        assert u.is_bluetooth_base is True

    def test_is_not_bluetooth_base(self):
        u = UUID128(bytes(16))
        assert u.is_bluetooth_base is False

    def test_to_uuid16_roundtrip(self):
        original = UUID16(0x180D)
        u128 = original.to_uuid128()
        back = u128.to_uuid16()
        assert back is not None
        assert back == original

    def test_to_uuid16_non_base_returns_none(self):
        u = UUID128(bytes(16))
        assert u.to_uuid16() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/core/test_uuid.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# pybluehost/core/uuid.py
from __future__ import annotations

import re
from dataclasses import dataclass

# Bluetooth Base UUID: 00000000-0000-1000-8000-00805F9B34FB
BLUETOOTH_BASE_UUID = bytes([
    0x00, 0x00, 0x00, 0x00,  # bytes 0-3 (UUID16 goes in bytes 2-3)
    0x00, 0x00,              # bytes 4-5
    0x10, 0x00,              # bytes 6-7
    0x80, 0x00,              # bytes 8-9
    0x00, 0x80, 0x5F, 0x9B, 0x34, 0xFB,  # bytes 10-15
])

_UUID_RE = re.compile(
    r"^([0-9a-fA-F]{8})-([0-9a-fA-F]{4})-([0-9a-fA-F]{4})"
    r"-([0-9a-fA-F]{4})-([0-9a-fA-F]{12})$"
)


@dataclass(frozen=True)
class UUID16:
    """16-bit Bluetooth UUID."""

    value: int

    def __post_init__(self) -> None:
        if not (0 <= self.value <= 0xFFFF):
            raise ValueError(f"UUID16 value must be 0x0000-0xFFFF, got {self.value:#x}")

    def to_bytes(self) -> bytes:
        return self.value.to_bytes(2, "little")

    @classmethod
    def from_bytes(cls, data: bytes) -> UUID16:
        if len(data) != 2:
            raise ValueError(f"UUID16 requires 2 bytes, got {len(data)}")
        return cls(int.from_bytes(data, "little"))

    def to_uuid128(self) -> UUID128:
        buf = bytearray(BLUETOOTH_BASE_UUID)
        buf[2] = (self.value >> 8) & 0xFF
        buf[3] = self.value & 0xFF
        return UUID128(bytes(buf))

    def __str__(self) -> str:
        return f"0x{self.value:04X}"


@dataclass(frozen=True)
class UUID128:
    """128-bit UUID."""

    value: bytes

    def __post_init__(self) -> None:
        if len(self.value) != 16:
            raise ValueError(f"UUID128 requires 16 bytes, got {len(self.value)}")

    @classmethod
    def from_string(cls, s: str) -> UUID128:
        m = _UUID_RE.match(s)
        if not m:
            raise ValueError(f"Invalid UUID128 string: {s}")
        hex_str = "".join(m.groups())
        return cls(bytes.fromhex(hex_str))

    @classmethod
    def from_bytes(cls, data: bytes) -> UUID128:
        if len(data) != 16:
            raise ValueError(f"UUID128 requires 16 bytes, got {len(data)}")
        return cls(data)

    def to_bytes(self) -> bytes:
        return self.value

    @property
    def is_bluetooth_base(self) -> bool:
        return (
            self.value[0:2] == BLUETOOTH_BASE_UUID[0:2]
            and self.value[4:] == BLUETOOTH_BASE_UUID[4:]
        )

    def to_uuid16(self) -> UUID16 | None:
        if not self.is_bluetooth_base:
            return None
        return UUID16((self.value[2] << 8) | self.value[3])

    def __str__(self) -> str:
        h = self.value.hex()
        return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/core/test_uuid.py -v`
Expected: All 18 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/core/uuid.py tests/unit/core/test_uuid.py
git commit -m "feat(core): add UUID16 and UUID128 types"
```

---

## Task 4: Key Types and Shared Enums

**Files:**
- Create: `pybluehost/core/keys.py`
- Create: `pybluehost/core/types.py`
- Create: `tests/unit/core/test_keys.py`
- Create: `tests/unit/core/test_types.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/core/test_keys.py
import pytest
from pybluehost.core.keys import LinkKey, LTK, IRK, CSRK, LinkKeyType


class TestLinkKey:
    def test_create(self):
        key = LinkKey(value=bytes(16), key_type=LinkKeyType.AUTHENTICATED_P256)
        assert len(key.value) == 16
        assert key.key_type == LinkKeyType.AUTHENTICATED_P256

    def test_wrong_length(self):
        with pytest.raises(ValueError, match="16 bytes"):
            LinkKey(value=bytes(10), key_type=LinkKeyType.UNAUTHENTICATED_P192)


class TestLTK:
    def test_create(self):
        ltk = LTK(value=bytes(16), ediv=0x1234, rand=0xABCD)
        assert ltk.ediv == 0x1234
        assert ltk.rand == 0xABCD
        assert ltk.key_size == 16

    def test_custom_key_size(self):
        ltk = LTK(value=bytes(16), ediv=0, rand=0, key_size=7)
        assert ltk.key_size == 7

    def test_wrong_length(self):
        with pytest.raises(ValueError, match="16 bytes"):
            LTK(value=bytes(8), ediv=0, rand=0)


class TestIRK:
    def test_create(self):
        irk = IRK(value=bytes(16))
        assert len(irk.value) == 16

    def test_wrong_length(self):
        with pytest.raises(ValueError, match="16 bytes"):
            IRK(value=bytes(4))


class TestCSRK:
    def test_create(self):
        csrk = CSRK(value=bytes(16))
        assert len(csrk.value) == 16

    def test_wrong_length(self):
        with pytest.raises(ValueError, match="16 bytes"):
            CSRK(value=bytes(20))
```

```python
# tests/unit/core/test_types.py
from pybluehost.core.types import IOCapability, ConnectionRole, LinkType


class TestIOCapability:
    def test_enum_values(self):
        assert IOCapability.DISPLAY_ONLY == 0x00
        assert IOCapability.DISPLAY_YES_NO == 0x01
        assert IOCapability.KEYBOARD_ONLY == 0x02
        assert IOCapability.NO_INPUT_NO_OUTPUT == 0x03
        assert IOCapability.KEYBOARD_DISPLAY == 0x04


class TestConnectionRole:
    def test_enum_values(self):
        assert ConnectionRole.CENTRAL == 0x00
        assert ConnectionRole.PERIPHERAL == 0x01


class TestLinkType:
    def test_enum_values(self):
        assert LinkType.SCO == 0x00
        assert LinkType.ACL == 0x01
        assert LinkType.ESCO == 0x02
        assert LinkType.LE == 0x03
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_keys.py tests/unit/core/test_types.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementations**

```python
# pybluehost/core/keys.py
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class LinkKeyType(IntEnum):
    UNAUTHENTICATED_P192 = 0x04
    AUTHENTICATED_P192 = 0x05
    UNAUTHENTICATED_P256 = 0x07
    AUTHENTICATED_P256 = 0x08


def _validate_16(value: bytes, name: str) -> None:
    if len(value) != 16:
        raise ValueError(f"{name} requires 16 bytes, got {len(value)}")


@dataclass(frozen=True)
class LinkKey:
    """BR/EDR Link Key."""
    value: bytes
    key_type: LinkKeyType

    def __post_init__(self) -> None:
        _validate_16(self.value, "LinkKey")


@dataclass(frozen=True)
class LTK:
    """BLE Long Term Key."""
    value: bytes
    ediv: int
    rand: int
    key_size: int = 16

    def __post_init__(self) -> None:
        _validate_16(self.value, "LTK")


@dataclass(frozen=True)
class IRK:
    """Identity Resolving Key."""
    value: bytes

    def __post_init__(self) -> None:
        _validate_16(self.value, "IRK")


@dataclass(frozen=True)
class CSRK:
    """Connection Signature Resolving Key."""
    value: bytes

    def __post_init__(self) -> None:
        _validate_16(self.value, "CSRK")
```

```python
# pybluehost/core/types.py
from __future__ import annotations

from enum import IntEnum


class IOCapability(IntEnum):
    DISPLAY_ONLY = 0x00
    DISPLAY_YES_NO = 0x01
    KEYBOARD_ONLY = 0x02
    NO_INPUT_NO_OUTPUT = 0x03
    KEYBOARD_DISPLAY = 0x04


class ConnectionRole(IntEnum):
    CENTRAL = 0x00
    PERIPHERAL = 0x01


class LinkType(IntEnum):
    SCO = 0x00
    ACL = 0x01
    ESCO = 0x02
    LE = 0x03
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_keys.py tests/unit/core/test_types.py -v`
Expected: All 14 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/core/keys.py pybluehost/core/types.py tests/unit/core/test_keys.py tests/unit/core/test_types.py
git commit -m "feat(core): add key types (LinkKey/LTK/IRK/CSRK) and shared enums"
```

---

## Task 5: Byte Buffer for PDU Construction and Parsing

**Files:**
- Create: `pybluehost/core/buffer.py`
- Create: `tests/unit/core/test_buffer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/core/test_buffer.py
import pytest
from pybluehost.core.buffer import ByteBuffer


class TestByteBufferWrite:
    def test_write_uint8(self):
        buf = ByteBuffer()
        buf.write_uint8(0xFF)
        assert buf.getvalue() == b"\xFF"

    def test_write_uint16_le(self):
        buf = ByteBuffer()
        buf.write_uint16(0x1234)
        assert buf.getvalue() == b"\x34\x12"

    def test_write_uint32_le(self):
        buf = ByteBuffer()
        buf.write_uint32(0x12345678)
        assert buf.getvalue() == b"\x78\x56\x34\x12"

    def test_write_bytes(self):
        buf = ByteBuffer()
        buf.write_bytes(b"\x01\x02\x03")
        assert buf.getvalue() == b"\x01\x02\x03"

    def test_write_address(self):
        buf = ByteBuffer()
        buf.write_bytes(bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06]))
        assert len(buf.getvalue()) == 6

    def test_chaining(self):
        buf = ByteBuffer()
        buf.write_uint8(0x01)
        buf.write_uint16(0x0200)
        buf.write_bytes(b"\xAA")
        assert buf.getvalue() == b"\x01\x00\x02\xAA"

    def test_len(self):
        buf = ByteBuffer()
        buf.write_uint8(0x01)
        buf.write_uint16(0x0200)
        assert len(buf) == 3


class TestByteBufferRead:
    def test_read_uint8(self):
        buf = ByteBuffer(b"\xFF\xAA")
        assert buf.read_uint8() == 0xFF
        assert buf.read_uint8() == 0xAA

    def test_read_uint16_le(self):
        buf = ByteBuffer(b"\x34\x12")
        assert buf.read_uint16() == 0x1234

    def test_read_uint32_le(self):
        buf = ByteBuffer(b"\x78\x56\x34\x12")
        assert buf.read_uint32() == 0x12345678

    def test_read_bytes(self):
        buf = ByteBuffer(b"\x01\x02\x03\x04")
        assert buf.read_bytes(3) == b"\x01\x02\x03"
        assert buf.read_bytes(1) == b"\x04"

    def test_read_remaining(self):
        buf = ByteBuffer(b"\x01\x02\x03")
        buf.read_uint8()
        assert buf.read_remaining() == b"\x02\x03"

    def test_read_past_end_raises(self):
        buf = ByteBuffer(b"\x01")
        buf.read_uint8()
        with pytest.raises(ValueError, match="underflow"):
            buf.read_uint8()

    def test_remaining_count(self):
        buf = ByteBuffer(b"\x01\x02\x03")
        assert buf.remaining == 3
        buf.read_uint8()
        assert buf.remaining == 2

    def test_offset_tracking(self):
        buf = ByteBuffer(b"\x01\x02\x03")
        assert buf.offset == 0
        buf.read_uint8()
        assert buf.offset == 1
        buf.read_uint16()
        assert buf.offset == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/core/test_buffer.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# pybluehost/core/buffer.py
from __future__ import annotations

import struct


class ByteBuffer:
    """PDU construction and parsing helper with little-endian defaults."""

    def __init__(self, data: bytes = b"") -> None:
        self._buf = bytearray(data)
        self._offset = 0
        self._write_mode = len(data) == 0

    # ── Write operations ──

    def write_uint8(self, value: int) -> None:
        self._buf.append(value & 0xFF)

    def write_uint16(self, value: int) -> None:
        self._buf.extend(struct.pack("<H", value))

    def write_uint32(self, value: int) -> None:
        self._buf.extend(struct.pack("<I", value))

    def write_bytes(self, data: bytes) -> None:
        self._buf.extend(data)

    def getvalue(self) -> bytes:
        return bytes(self._buf)

    # ── Read operations ──

    def _check_read(self, n: int) -> None:
        if self._offset + n > len(self._buf):
            raise ValueError(
                f"Buffer underflow: need {n} bytes at offset {self._offset}, "
                f"but only {len(self._buf) - self._offset} remaining"
            )

    def read_uint8(self) -> int:
        self._check_read(1)
        val = self._buf[self._offset]
        self._offset += 1
        return val

    def read_uint16(self) -> int:
        self._check_read(2)
        val = struct.unpack_from("<H", self._buf, self._offset)[0]
        self._offset += 2
        return val

    def read_uint32(self) -> int:
        self._check_read(4)
        val = struct.unpack_from("<I", self._buf, self._offset)[0]
        self._offset += 4
        return val

    def read_bytes(self, n: int) -> bytes:
        self._check_read(n)
        val = bytes(self._buf[self._offset : self._offset + n])
        self._offset += n
        return val

    def read_remaining(self) -> bytes:
        val = bytes(self._buf[self._offset :])
        self._offset = len(self._buf)
        return val

    @property
    def remaining(self) -> int:
        return len(self._buf) - self._offset

    @property
    def offset(self) -> int:
        return self._offset

    def __len__(self) -> int:
        return len(self._buf)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/core/test_buffer.py -v`
Expected: All 16 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/core/buffer.py tests/unit/core/test_buffer.py
git commit -m "feat(core): add ByteBuffer for PDU construction and parsing"
```

---

## Task 6: State Machine Framework

**Files:**
- Create: `pybluehost/core/statemachine.py`
- Create: `tests/unit/core/test_statemachine.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/core/test_statemachine.py
import asyncio
from enum import Enum, auto

import pytest

from pybluehost.core.errors import InvalidTransitionError
from pybluehost.core.statemachine import StateMachine, Transition, StateMachineObserver


class S(Enum):
    IDLE = auto()
    ACTIVE = auto()
    DONE = auto()


class E(Enum):
    START = auto()
    FINISH = auto()
    RESET = auto()
    TIMEOUT = auto()


class TestStateMachineBasic:
    def test_initial_state(self):
        sm = StateMachine("test", S.IDLE)
        assert sm.state == S.IDLE

    def test_name(self):
        sm = StateMachine("my_sm", S.IDLE)
        assert sm.name == "my_sm"

    @pytest.mark.asyncio
    async def test_simple_transition(self):
        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        await sm.fire(E.START)
        assert sm.state == S.ACTIVE

    @pytest.mark.asyncio
    async def test_two_transitions(self):
        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        sm.add_transition(S.ACTIVE, E.FINISH, S.DONE)
        await sm.fire(E.START)
        await sm.fire(E.FINISH)
        assert sm.state == S.DONE

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self):
        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        with pytest.raises(InvalidTransitionError, match="no transition from IDLE via FINISH"):
            await sm.fire(E.FINISH)

    @pytest.mark.asyncio
    async def test_history_recorded(self):
        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        sm.add_transition(S.ACTIVE, E.FINISH, S.DONE)
        await sm.fire(E.START)
        await sm.fire(E.FINISH)
        assert len(sm.history) == 2
        assert sm.history[0].from_state == S.IDLE
        assert sm.history[0].event == E.START
        assert sm.history[0].to_state == S.ACTIVE
        assert sm.history[1].from_state == S.ACTIVE
        assert sm.history[1].event == E.FINISH
        assert sm.history[1].to_state == S.DONE

    @pytest.mark.asyncio
    async def test_transition_has_timestamp(self):
        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        await sm.fire(E.START)
        assert isinstance(sm.history[0].timestamp, float)
        assert sm.history[0].timestamp > 0


class TestStateMachineActions:
    @pytest.mark.asyncio
    async def test_action_called_on_transition(self):
        called_with: list[dict] = []

        async def on_start(**ctx: object) -> None:
            called_with.append(dict(ctx))

        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE, action=on_start)
        await sm.fire(E.START, handle=0x40)
        assert len(called_with) == 1
        assert called_with[0]["handle"] == 0x40

    @pytest.mark.asyncio
    async def test_action_not_called_on_wrong_transition(self):
        called = False

        async def on_start(**ctx: object) -> None:
            nonlocal called
            called = True

        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE, action=on_start)
        sm.add_transition(S.ACTIVE, E.FINISH, S.DONE)
        await sm.fire(E.START)
        called = False
        await sm.fire(E.FINISH)
        assert called is False


class TestStateMachineObserverPattern:
    @pytest.mark.asyncio
    async def test_observer_notified(self):
        transitions: list[Transition] = []

        class TestObserver(StateMachineObserver):
            def on_transition(self, sm_name: str, transition: Transition) -> None:
                transitions.append(transition)

        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        sm.add_observer(TestObserver())
        await sm.fire(E.START)
        assert len(transitions) == 1
        assert transitions[0].from_state == S.IDLE
        assert transitions[0].to_state == S.ACTIVE


class TestStateMachineTimeout:
    @pytest.mark.asyncio
    async def test_timeout_fires_event(self):
        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        sm.add_transition(S.ACTIVE, E.TIMEOUT, S.IDLE)
        sm.set_timeout(S.ACTIVE, 0.05, E.TIMEOUT)
        await sm.fire(E.START)
        assert sm.state == S.ACTIVE
        await asyncio.sleep(0.1)
        assert sm.state == S.IDLE

    @pytest.mark.asyncio
    async def test_timeout_cancelled_on_transition(self):
        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        sm.add_transition(S.ACTIVE, E.FINISH, S.DONE)
        sm.add_transition(S.ACTIVE, E.TIMEOUT, S.IDLE)
        sm.set_timeout(S.ACTIVE, 0.05, E.TIMEOUT)
        await sm.fire(E.START)
        await sm.fire(E.FINISH)
        assert sm.state == S.DONE
        await asyncio.sleep(0.1)
        assert sm.state == S.DONE  # timeout should NOT have fired
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/core/test_statemachine.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# pybluehost/core/statemachine.py
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Generic, Protocol, TypeVar

from pybluehost.core.errors import InvalidTransitionError

S = TypeVar("S", bound=Enum)
E = TypeVar("E", bound=Enum)


@dataclass(frozen=True)
class Transition(Generic[S, E]):
    timestamp: float
    from_state: S
    event: E
    to_state: S


class StateMachineObserver(Protocol):
    def on_transition(self, sm_name: str, transition: Transition) -> None: ...  # type: ignore[type-arg]


@dataclass
class _Rule:
    to_state: Any
    action: Callable[..., Awaitable[None]] | None


class StateMachine(Generic[S, E]):
    def __init__(self, name: str, initial: S) -> None:
        self._name = name
        self._state: S = initial
        self._transitions: dict[tuple[S, E], _Rule] = {}
        self._timeouts: dict[S, tuple[float, E]] = {}
        self._history: list[Transition[S, E]] = []
        self._observers: list[StateMachineObserver] = []
        self._timeout_task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> S:
        return self._state

    @property
    def history(self) -> list[Transition[S, E]]:
        return list(self._history)

    def add_transition(
        self,
        from_state: S,
        event: E,
        to_state: S,
        action: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        self._transitions[(from_state, event)] = _Rule(to_state=to_state, action=action)

    def set_timeout(self, state: S, seconds: float, timeout_event: E) -> None:
        self._timeouts[state] = (seconds, timeout_event)

    def add_observer(self, observer: StateMachineObserver) -> None:
        self._observers.append(observer)

    async def fire(self, event: E, **context: object) -> None:
        key = (self._state, event)
        rule = self._transitions.get(key)
        if rule is None:
            raise InvalidTransitionError(
                sm_name=self._name,
                from_state=self._state.name,
                event=event.name,
            )

        from_state = self._state
        self._cancel_timeout()
        self._state = rule.to_state

        transition = Transition(
            timestamp=time.monotonic(),
            from_state=from_state,
            event=event,
            to_state=rule.to_state,
        )
        self._history.append(transition)

        for obs in self._observers:
            obs.on_transition(self._name, transition)

        if rule.action is not None:
            await rule.action(**context)

        self._arm_timeout()

    def _arm_timeout(self) -> None:
        timeout_cfg = self._timeouts.get(self._state)
        if timeout_cfg is None:
            return
        seconds, timeout_event = timeout_cfg

        async def _fire_timeout() -> None:
            await asyncio.sleep(seconds)
            await self.fire(timeout_event)

        self._timeout_task = asyncio.ensure_future(_fire_timeout())

    def _cancel_timeout(self) -> None:
        if self._timeout_task is not None and not self._timeout_task.done():
            self._timeout_task.cancel()
            self._timeout_task = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/core/test_statemachine.py -v`
Expected: All 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/core/statemachine.py tests/unit/core/test_statemachine.py
git commit -m "feat(core): add StateMachine[S, E] framework with timeouts and observer"
```

---

## Task 7: Trace System — Data Model and TraceSystem

**Files:**
- Create: `pybluehost/core/trace.py`
- Create: `tests/unit/core/test_trace.py`

- [ ] **Step 1: Write the failing tests for TraceEvent and TraceSystem**

```python
# tests/unit/core/test_trace.py
import asyncio
from datetime import datetime, timezone

import pytest

from pybluehost.core.trace import (
    TraceEvent,
    Direction,
    TraceSystem,
    RingBufferSink,
    JsonSink,
    CallbackSink,
)


class TestTraceEvent:
    def test_create(self):
        event = TraceEvent(
            timestamp=1000.0,
            wall_clock=datetime(2026, 4, 14, tzinfo=timezone.utc),
            source_layer="hci",
            direction=Direction.DOWN,
            raw_bytes=b"\x01\x03\x0c\x00",
            decoded={"opcode": "HCI_Reset"},
            connection_handle=None,
            metadata={},
        )
        assert event.source_layer == "hci"
        assert event.direction == Direction.DOWN
        assert event.raw_bytes == b"\x01\x03\x0c\x00"

    def test_frozen(self):
        event = TraceEvent(
            timestamp=0, wall_clock=datetime.now(timezone.utc),
            source_layer="hci", direction=Direction.UP,
            raw_bytes=b"", decoded=None,
            connection_handle=None, metadata={},
        )
        with pytest.raises(AttributeError):
            event.source_layer = "l2cap"  # type: ignore[misc]


class TestDirection:
    def test_values(self):
        assert Direction.UP.value == "host \u2190 controller"
        assert Direction.DOWN.value == "host \u2192 controller"


class TestTraceSystem:
    @pytest.mark.asyncio
    async def test_emit_to_single_sink(self):
        received: list[TraceEvent] = []

        async def handler(event: TraceEvent) -> None:
            received.append(event)

        ts = TraceSystem()
        ts.add_sink(CallbackSink(handler))
        await ts.start()

        event = _make_event("hci", Direction.DOWN, b"\x01")
        ts.emit(event)
        await asyncio.sleep(0.05)

        await ts.stop()
        assert len(received) == 1
        assert received[0].raw_bytes == b"\x01"

    @pytest.mark.asyncio
    async def test_emit_to_multiple_sinks(self):
        count_a = 0
        count_b = 0

        async def sink_a(event: TraceEvent) -> None:
            nonlocal count_a
            count_a += 1

        async def sink_b(event: TraceEvent) -> None:
            nonlocal count_b
            count_b += 1

        ts = TraceSystem()
        ts.add_sink(CallbackSink(sink_a))
        ts.add_sink(CallbackSink(sink_b))
        await ts.start()

        ts.emit(_make_event("hci", Direction.DOWN, b"\x01"))
        await asyncio.sleep(0.05)

        await ts.stop()
        assert count_a == 1
        assert count_b == 1

    @pytest.mark.asyncio
    async def test_disabled_does_not_emit(self):
        received: list[TraceEvent] = []

        async def handler(event: TraceEvent) -> None:
            received.append(event)

        ts = TraceSystem()
        ts.add_sink(CallbackSink(handler))
        ts.enabled = False
        await ts.start()

        ts.emit(_make_event("hci", Direction.DOWN, b"\x01"))
        await asyncio.sleep(0.05)

        await ts.stop()
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_remove_sink(self):
        received: list[TraceEvent] = []

        async def handler(event: TraceEvent) -> None:
            received.append(event)

        sink = CallbackSink(handler)
        ts = TraceSystem()
        ts.add_sink(sink)
        ts.remove_sink(sink)
        await ts.start()

        ts.emit(_make_event("hci", Direction.DOWN, b"\x01"))
        await asyncio.sleep(0.05)

        await ts.stop()
        assert len(received) == 0


class TestRingBufferSink:
    @pytest.mark.asyncio
    async def test_recent(self):
        ring = RingBufferSink(capacity=5)
        for i in range(3):
            await ring.on_trace(_make_event("hci", Direction.DOWN, bytes([i])))
        assert len(ring.recent(10)) == 3
        assert ring.recent(2) == ring.recent(10)[-2:]

    @pytest.mark.asyncio
    async def test_capacity_overflow(self):
        ring = RingBufferSink(capacity=3)
        for i in range(5):
            await ring.on_trace(_make_event("hci", Direction.DOWN, bytes([i])))
        events = ring.recent(10)
        assert len(events) == 3
        assert events[0].raw_bytes == bytes([2])  # oldest kept

    @pytest.mark.asyncio
    async def test_filter_by_layer(self):
        ring = RingBufferSink(capacity=10)
        await ring.on_trace(_make_event("hci", Direction.DOWN, b"\x01"))
        await ring.on_trace(_make_event("l2cap", Direction.UP, b"\x02"))
        await ring.on_trace(_make_event("hci", Direction.UP, b"\x03"))
        filtered = ring.filter(layer="hci")
        assert len(filtered) == 2

    @pytest.mark.asyncio
    async def test_filter_by_direction(self):
        ring = RingBufferSink(capacity=10)
        await ring.on_trace(_make_event("hci", Direction.DOWN, b"\x01"))
        await ring.on_trace(_make_event("hci", Direction.UP, b"\x02"))
        filtered = ring.filter(direction=Direction.UP)
        assert len(filtered) == 1

    @pytest.mark.asyncio
    async def test_dump_returns_string(self):
        ring = RingBufferSink(capacity=10)
        await ring.on_trace(_make_event("hci", Direction.DOWN, b"\x01\x02"))
        text = ring.dump()
        assert isinstance(text, str)
        assert "hci" in text


class TestCallbackSink:
    @pytest.mark.asyncio
    async def test_callback_called(self):
        received: list[TraceEvent] = []

        async def handler(event: TraceEvent) -> None:
            received.append(event)

        sink = CallbackSink(handler)
        event = _make_event("att", Direction.DOWN, b"\x01")
        await sink.on_trace(event)
        assert len(received) == 1


def _make_event(layer: str, direction: Direction, raw: bytes) -> TraceEvent:
    return TraceEvent(
        timestamp=0.0,
        wall_clock=datetime.now(timezone.utc),
        source_layer=layer,
        direction=direction,
        raw_bytes=raw,
        decoded=None,
        connection_handle=None,
        metadata={},
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/core/test_trace.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# pybluehost/core/trace.py
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol


class Direction(Enum):
    UP = "host \u2190 controller"
    DOWN = "host \u2192 controller"


@dataclass(frozen=True)
class TraceEvent:
    timestamp: float
    wall_clock: datetime
    source_layer: str
    direction: Direction
    raw_bytes: bytes
    decoded: dict[str, Any] | None
    connection_handle: int | None
    metadata: dict[str, Any]


class TraceSink(Protocol):
    async def on_trace(self, event: TraceEvent) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...


class TraceSystem:
    def __init__(self) -> None:
        self._sinks: list[TraceSink] = []
        self._queue: asyncio.Queue[TraceEvent] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def add_sink(self, sink: TraceSink) -> None:
        self._sinks.append(sink)

    def remove_sink(self, sink: TraceSink) -> None:
        self._sinks.remove(sink)

    def emit(self, event: TraceEvent) -> None:
        if not self._enabled:
            return
        self._queue.put_nowait(event)

    async def start(self) -> None:
        self._task = asyncio.ensure_future(self._dispatch_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        while not self._queue.empty():
            event = self._queue.get_nowait()
            for sink in self._sinks:
                await sink.on_trace(event)

        for sink in self._sinks:
            await sink.flush()
            await sink.close()

    async def _dispatch_loop(self) -> None:
        try:
            while True:
                event = await self._queue.get()
                for sink in self._sinks:
                    await sink.on_trace(event)
        except asyncio.CancelledError:
            return


class RingBufferSink:
    def __init__(self, capacity: int = 1000) -> None:
        self._buffer: deque[TraceEvent] = deque(maxlen=capacity)

    async def on_trace(self, event: TraceEvent) -> None:
        self._buffer.append(event)

    async def flush(self) -> None:
        pass

    async def close(self) -> None:
        pass

    def recent(self, n: int = 20) -> list[TraceEvent]:
        items = list(self._buffer)
        return items[-n:]

    def filter(
        self,
        layer: str | None = None,
        direction: Direction | None = None,
    ) -> list[TraceEvent]:
        result = list(self._buffer)
        if layer is not None:
            result = [e for e in result if e.source_layer == layer]
        if direction is not None:
            result = [e for e in result if e.direction == direction]
        return result

    def dump(self) -> str:
        lines = []
        for e in self._buffer:
            hex_str = e.raw_bytes.hex() if e.raw_bytes else "(empty)"
            lines.append(f"[{e.source_layer}] {e.direction.name} {hex_str}")
        return "\n".join(lines)


class CallbackSink:
    def __init__(self, callback: Callable[[TraceEvent], Awaitable[None]]) -> None:
        self._callback = callback

    async def on_trace(self, event: TraceEvent) -> None:
        await self._callback(event)

    async def flush(self) -> None:
        pass

    async def close(self) -> None:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/core/test_trace.py -v`
Expected: All 14 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pybluehost/core/trace.py tests/unit/core/test_trace.py
git commit -m "feat(core): add TraceSystem with RingBufferSink and CallbackSink"
```

---

## Task 8: Trace System — JsonSink

**Files:**
- Modify: `pybluehost/core/trace.py`
- Modify: `tests/unit/core/test_trace.py`

- [ ] **Step 1: Write the failing tests for JsonSink**

Append to `tests/unit/core/test_trace.py`:

```python
import json
import tempfile
from pathlib import Path


class TestJsonSink:
    @pytest.mark.asyncio
    async def test_writes_jsonl(self, tmp_path: Path):
        path = tmp_path / "trace.jsonl"
        sink = JsonSink(str(path))
        await sink.on_trace(_make_event("hci", Direction.DOWN, b"\x01\x03\x0c\x00"))
        await sink.flush()
        await sink.close()

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["layer"] == "hci"
        assert obj["dir"] == "down"
        assert obj["hex"] == "01030c00"

    @pytest.mark.asyncio
    async def test_multiple_events(self, tmp_path: Path):
        path = tmp_path / "trace.jsonl"
        sink = JsonSink(str(path))
        await sink.on_trace(_make_event("hci", Direction.DOWN, b"\x01"))
        await sink.on_trace(_make_event("l2cap", Direction.UP, b"\x02"))
        await sink.flush()
        await sink.close()

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_decoded_included(self, tmp_path: Path):
        path = tmp_path / "trace.jsonl"
        sink = JsonSink(str(path))
        event = TraceEvent(
            timestamp=0.0,
            wall_clock=datetime.now(timezone.utc),
            source_layer="hci",
            direction=Direction.DOWN,
            raw_bytes=b"\x01",
            decoded={"opcode": "HCI_Reset"},
            connection_handle=0x40,
            metadata={"extra": "info"},
        )
        await sink.on_trace(event)
        await sink.flush()
        await sink.close()

        obj = json.loads(path.read_text().strip())
        assert obj["decoded"] == {"opcode": "HCI_Reset"}
        assert obj["handle"] == 0x40
        assert obj["meta"] == {"extra": "info"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/core/test_trace.py::TestJsonSink -v`
Expected: FAIL (JsonSink not yet fully implemented or not imported)

- [ ] **Step 3: Add JsonSink implementation to trace.py**

Add to `pybluehost/core/trace.py`:

```python
import json as _json
from pathlib import Path


class JsonSink:
    """JSON Lines trace sink — one JSON object per line."""

    def __init__(self, path: str | Path, decode: bool = True) -> None:
        self._path = Path(path)
        self._decode = decode
        self._file = open(self._path, "w", encoding="utf-8")

    async def on_trace(self, event: TraceEvent) -> None:
        obj: dict[str, Any] = {
            "ts": event.timestamp,
            "wall": event.wall_clock.isoformat(),
            "layer": event.source_layer,
            "dir": event.direction.name.lower(),
            "hex": event.raw_bytes.hex(),
        }
        if event.decoded is not None:
            obj["decoded"] = event.decoded
        if event.connection_handle is not None:
            obj["handle"] = event.connection_handle
        if event.metadata:
            obj["meta"] = event.metadata
        self._file.write(_json.dumps(obj) + "\n")

    async def flush(self) -> None:
        self._file.flush()

    async def close(self) -> None:
        self._file.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/core/test_trace.py::TestJsonSink -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Run full trace test suite**

Run: `uv run pytest tests/unit/core/test_trace.py -v`
Expected: All 17 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add pybluehost/core/trace.py tests/unit/core/test_trace.py
git commit -m "feat(core): add JsonSink for JSONL trace output"
```

---

## Task 9: Trace System — BtsnoopSink

**Files:**
- Modify: `pybluehost/core/trace.py`
- Modify: `tests/unit/core/test_trace.py`

- [ ] **Step 1: Write the failing tests for BtsnoopSink**

Append to `tests/unit/core/test_trace.py`:

```python
import struct


class TestBtsnoopSink:
    @pytest.mark.asyncio
    async def test_writes_valid_header(self, tmp_path: Path):
        path = tmp_path / "trace.cfa"
        sink = BtsnoopSink(str(path))
        await sink.close()

        data = path.read_bytes()
        assert data[:8] == b"btsnoop\x00"
        version = struct.unpack(">I", data[8:12])[0]
        assert version == 1
        datalink = struct.unpack(">I", data[12:16])[0]
        assert datalink == 1002  # H4

    @pytest.mark.asyncio
    async def test_writes_packet_record(self, tmp_path: Path):
        path = tmp_path / "trace.cfa"
        sink = BtsnoopSink(str(path))

        event = _make_event("hci", Direction.DOWN, b"\x01\x03\x0c\x00")
        await sink.on_trace(event)
        await sink.flush()
        await sink.close()

        data = path.read_bytes()
        assert len(data) > 16  # header + at least one record

        # Parse first record after 16-byte header
        offset = 16
        orig_len = struct.unpack(">I", data[offset : offset + 4])[0]
        incl_len = struct.unpack(">I", data[offset + 4 : offset + 8])[0]
        flags = struct.unpack(">I", data[offset + 8 : offset + 12])[0]
        assert orig_len == incl_len
        assert orig_len == 4  # len of raw_bytes
        assert flags == 0  # sent (DOWN)

    @pytest.mark.asyncio
    async def test_direction_flags(self, tmp_path: Path):
        path = tmp_path / "trace.cfa"
        sink = BtsnoopSink(str(path))
        await sink.on_trace(_make_event("hci", Direction.DOWN, b"\x01"))
        await sink.on_trace(_make_event("hci", Direction.UP, b"\x02"))
        await sink.flush()
        await sink.close()

        data = path.read_bytes()
        # First record flags
        flags1 = struct.unpack(">I", data[24:28])[0]
        assert flags1 == 0  # sent

        # Second record: offset = 16 (header) + 24 (record header) + 1 (payload)
        rec2_offset = 16 + 24 + 1
        flags2 = struct.unpack(">I", data[rec2_offset + 8 : rec2_offset + 12])[0]
        assert flags2 == 1  # received

    @pytest.mark.asyncio
    async def test_ignores_non_hci_events(self, tmp_path: Path):
        path = tmp_path / "trace.cfa"
        sink = BtsnoopSink(str(path))
        await sink.on_trace(_make_event("l2cap", Direction.DOWN, b"\x01"))
        await sink.on_trace(_make_event("sm:conn", Direction.UP, b""))
        await sink.flush()
        await sink.close()

        data = path.read_bytes()
        assert len(data) == 16  # header only, no records
```

Also add `BtsnoopSink` to the import at the top of the test file.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/core/test_trace.py::TestBtsnoopSink -v`
Expected: FAIL

- [ ] **Step 3: Add BtsnoopSink implementation to trace.py**

Add to `pybluehost/core/trace.py`:

```python
import struct as _struct


# btsnoop epoch: 2000-01-01 00:00:00 UTC in microseconds since Unix epoch
_BTSNOOP_EPOCH_DELTA_US = 946684800_000_000


class BtsnoopSink:
    """Btsnoop file sink — Android/Wireshark compatible .cfa format."""

    # Only HCI-boundary events are written (source_layer in {"transport", "hci"})
    _HCI_LAYERS = {"transport", "hci"}

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._file = open(self._path, "wb")
        self._write_header()

    def _write_header(self) -> None:
        self._file.write(b"btsnoop\x00")  # 8-byte magic
        self._file.write(_struct.pack(">I", 1))  # version
        self._file.write(_struct.pack(">I", 1002))  # datalink: H4

    async def on_trace(self, event: TraceEvent) -> None:
        if event.source_layer not in self._HCI_LAYERS:
            return
        if not event.raw_bytes:
            return

        payload = event.raw_bytes
        orig_len = len(payload)
        incl_len = orig_len
        flags = 0 if event.direction == Direction.DOWN else 1
        drops = 0

        wall_us = int(event.wall_clock.timestamp() * 1_000_000)
        ts = wall_us + _BTSNOOP_EPOCH_DELTA_US

        self._file.write(_struct.pack(">I", orig_len))
        self._file.write(_struct.pack(">I", incl_len))
        self._file.write(_struct.pack(">I", flags))
        self._file.write(_struct.pack(">I", drops))
        self._file.write(_struct.pack(">q", ts))
        self._file.write(payload)

    async def flush(self) -> None:
        self._file.flush()

    async def close(self) -> None:
        self._file.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/core/test_trace.py::TestBtsnoopSink -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Run full trace test suite**

Run: `uv run pytest tests/unit/core/test_trace.py -v`
Expected: All 21 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add pybluehost/core/trace.py tests/unit/core/test_trace.py
git commit -m "feat(core): add BtsnoopSink for Wireshark-compatible HCI trace"
```

---

## Task 10: Trace System — StateMachineTraceBridge

**Files:**
- Modify: `pybluehost/core/trace.py`
- Modify: `tests/unit/core/test_trace.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/core/test_trace.py`:

```python
from enum import auto
from pybluehost.core.statemachine import StateMachine, Transition as SMTransition
from pybluehost.core.trace import StateMachineTraceBridge


class _TS(Enum):
    IDLE = auto()
    ACTIVE = auto()

class _TE(Enum):
    GO = auto()


class TestStateMachineTraceBridge:
    @pytest.mark.asyncio
    async def test_bridge_emits_trace_on_transition(self):
        received: list[TraceEvent] = []

        async def handler(event: TraceEvent) -> None:
            received.append(event)

        ts = TraceSystem()
        ts.add_sink(CallbackSink(handler))
        await ts.start()

        bridge = StateMachineTraceBridge(ts)
        sm = StateMachine("test_sm", _TS.IDLE)
        sm.add_transition(_TS.IDLE, _TE.GO, _TS.ACTIVE)
        sm.add_observer(bridge)

        await sm.fire(_TE.GO)
        await asyncio.sleep(0.05)
        await ts.stop()

        assert len(received) == 1
        assert received[0].source_layer == "sm:test_sm"
        assert received[0].raw_bytes == b""
        assert received[0].decoded["from"] == "IDLE"
        assert received[0].decoded["to"] == "ACTIVE"
        assert received[0].decoded["event"] == "GO"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/core/test_trace.py::TestStateMachineTraceBridge -v`
Expected: FAIL

- [ ] **Step 3: Add StateMachineTraceBridge to trace.py**

Add to `pybluehost/core/trace.py`:

```python
import time


class StateMachineTraceBridge:
    """Bridges StateMachine observer events into the TraceSystem."""

    def __init__(self, trace: TraceSystem) -> None:
        self._trace = trace

    def on_transition(self, sm_name: str, transition: Any) -> None:
        event = TraceEvent(
            timestamp=transition.timestamp,
            wall_clock=datetime.now(timezone.utc),
            source_layer=f"sm:{sm_name}",
            direction=Direction.UP,
            raw_bytes=b"",
            decoded={
                "from": transition.from_state.name,
                "to": transition.to_state.name,
                "event": transition.event.name,
            },
            connection_handle=None,
            metadata={},
        )
        self._trace.emit(event)
```

Add missing import at top of `trace.py`:

```python
from datetime import datetime, timezone
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/core/test_trace.py::TestStateMachineTraceBridge -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/unit/core/ -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add pybluehost/core/trace.py tests/unit/core/test_trace.py
git commit -m "feat(core): add StateMachineTraceBridge for unified trace pipeline"
```

---

## Task 11: SIG Database

**Files:**
- Create: `pybluehost/core/sig_db.py`
- Create: `tests/unit/core/test_sig_db.py`

The SIG YAML data is already available at `pybluehost/lib/sig/` as a git submodule. The actual YAML formats are:

- `assigned_numbers/uuids/service_uuids.yaml`: `{uuids: [{uuid: 0x1800, name: "GAP", id: "org.bluetooth.service.gap"}, ...]}`
- `assigned_numbers/uuids/characteristic_uuids.yaml`: same format with `id: "org.bluetooth.characteristic.gap.device_name"`
- `assigned_numbers/uuids/descriptors.yaml`: same format
- `assigned_numbers/company_identifiers/company_identifiers.yaml`: `{company_identifiers: [{value: 0x10B2, name: "..."}, ...]}`
- `assigned_numbers/core/ad_types.yaml`: `{ad_types: [{value: 0x01, name: "Flags", reference: "..."}, ...]}`
- `assigned_numbers/core/appearance_values.yaml`: `{appearance_values: [{category: 0x000, name: "Unknown"}, ...]}`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/core/test_sig_db.py
from pathlib import Path

import pytest

from pybluehost.core.sig_db import SIGDatabase


@pytest.fixture
def sig_db() -> SIGDatabase:
    """Create a fresh SIGDatabase instance pointing at the real submodule data."""
    sig_root = Path(__file__).resolve().parents[3] / "pybluehost" / "lib" / "sig"
    if not sig_root.exists():
        pytest.skip("SIG submodule not initialized")
    return SIGDatabase(sig_root)


class TestServiceUUIDs:
    def test_service_name(self, sig_db: SIGDatabase):
        assert sig_db.service_name(0x1800) == "GAP"
        assert sig_db.service_name(0x180D) == "Heart Rate"

    def test_service_name_unknown(self, sig_db: SIGDatabase):
        assert sig_db.service_name(0xFFFF) is None

    def test_service_id(self, sig_db: SIGDatabase):
        result = sig_db.service_id(0x1800)
        assert result is not None
        assert "gap" in result.lower()


class TestCharacteristicUUIDs:
    def test_characteristic_name(self, sig_db: SIGDatabase):
        assert sig_db.characteristic_name(0x2A00) == "Device Name"
        assert sig_db.characteristic_name(0x2A37) == "Heart Rate Measurement"

    def test_characteristic_name_unknown(self, sig_db: SIGDatabase):
        assert sig_db.characteristic_name(0xFFFF) is None

    def test_characteristic_id(self, sig_db: SIGDatabase):
        result = sig_db.characteristic_id(0x2A00)
        assert result is not None
        assert "device_name" in result


class TestDescriptorUUIDs:
    def test_descriptor_name(self, sig_db: SIGDatabase):
        name = sig_db.descriptor_name(0x2900)
        assert name is not None
        assert "Extended Properties" in name

    def test_descriptor_name_unknown(self, sig_db: SIGDatabase):
        assert sig_db.descriptor_name(0xFFFF) is None


class TestUUIDByName:
    def test_find_service(self, sig_db: SIGDatabase):
        assert sig_db.uuid_by_name("Heart Rate") == 0x180D

    def test_find_characteristic(self, sig_db: SIGDatabase):
        assert sig_db.uuid_by_name("Device Name") == 0x2A00

    def test_not_found(self, sig_db: SIGDatabase):
        assert sig_db.uuid_by_name("Nonexistent Thing XYZ") is None


class TestCompanyID:
    def test_company_name(self, sig_db: SIGDatabase):
        name = sig_db.company_name(0x004C)
        assert name is not None
        assert "Apple" in name

    def test_company_name_unknown(self, sig_db: SIGDatabase):
        assert sig_db.company_name(0xFFFF) is None

    def test_company_id_by_name(self, sig_db: SIGDatabase):
        cid = sig_db.company_id_by_name("Apple")
        assert cid is not None
        assert cid == 0x004C


class TestADTypes:
    def test_ad_type_name(self, sig_db: SIGDatabase):
        assert sig_db.ad_type_name(0x01) == "Flags"

    def test_ad_type_name_unknown(self, sig_db: SIGDatabase):
        assert sig_db.ad_type_name(0xFF) is None


class TestAppearance:
    def test_appearance_category(self, sig_db: SIGDatabase):
        name = sig_db.appearance_category(0x001)
        assert name is not None
        assert "Phone" in name

    def test_appearance_category_unknown(self, sig_db: SIGDatabase):
        assert sig_db.appearance_category(0xFFF) is None


class TestLazyLoading:
    def test_data_loaded_on_first_access(self, sig_db: SIGDatabase):
        assert sig_db._services is None
        sig_db.service_name(0x1800)
        assert sig_db._services is not None

    def test_second_access_uses_cache(self, sig_db: SIGDatabase):
        sig_db.service_name(0x1800)
        cached = sig_db._services
        sig_db.service_name(0x180D)
        assert sig_db._services is cached


class TestSingleton:
    def test_get_returns_singleton(self):
        SIGDatabase._instance = None
        a = SIGDatabase.get()
        b = SIGDatabase.get()
        assert a is b
        SIGDatabase._instance = None  # cleanup
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/core/test_sig_db.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# pybluehost/core/sig_db.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import yaml


@dataclass(frozen=True)
class _UUIDEntry:
    uuid: int
    name: str
    identifier: str


class SIGDatabase:
    """Runtime SIG official YAML lookup — lazy-loaded, singleton."""

    _instance: ClassVar[SIGDatabase | None] = None
    _default_root: ClassVar[Path] = Path(__file__).resolve().parent.parent / "lib" / "sig"

    def __init__(self, sig_root: Path | None = None) -> None:
        self._sig_root = sig_root or self._default_root
        self._services: dict[int, _UUIDEntry] | None = None
        self._characteristics: dict[int, _UUIDEntry] | None = None
        self._descriptors: dict[int, _UUIDEntry] | None = None
        self._companies: dict[int, str] | None = None
        self._company_name_to_id: dict[str, int] | None = None
        self._ad_types: dict[int, str] | None = None
        self._appearances: dict[int, str] | None = None

    @classmethod
    def get(cls) -> SIGDatabase:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── UUID lookups ──

    def service_name(self, uuid: int) -> str | None:
        entry = self._ensure_services().get(uuid)
        return entry.name if entry else None

    def service_id(self, uuid: int) -> str | None:
        entry = self._ensure_services().get(uuid)
        return entry.identifier if entry else None

    def characteristic_name(self, uuid: int) -> str | None:
        entry = self._ensure_characteristics().get(uuid)
        return entry.name if entry else None

    def characteristic_id(self, uuid: int) -> str | None:
        entry = self._ensure_characteristics().get(uuid)
        return entry.identifier if entry else None

    def descriptor_name(self, uuid: int) -> str | None:
        entry = self._ensure_descriptors().get(uuid)
        return entry.name if entry else None

    def uuid_by_name(self, name: str) -> int | None:
        for table_fn in (self._ensure_services, self._ensure_characteristics, self._ensure_descriptors):
            for entry in table_fn().values():
                if entry.name == name:
                    return entry.uuid
        return None

    # ── Company ID ──

    def company_name(self, company_id: int) -> str | None:
        return self._ensure_companies().get(company_id)

    def company_id_by_name(self, name: str) -> int | None:
        self._ensure_companies()
        assert self._company_name_to_id is not None
        for stored_name, cid in self._company_name_to_id.items():
            if name.lower() in stored_name.lower():
                return cid
        return None

    # ── GAP constants ──

    def ad_type_name(self, type_code: int) -> str | None:
        return self._ensure_ad_types().get(type_code)

    def appearance_category(self, value: int) -> str | None:
        return self._ensure_appearances().get(value)

    # ── Internal loaders ──

    def _ensure_services(self) -> dict[int, _UUIDEntry]:
        if self._services is None:
            self._services = self._load_uuid_yaml("uuids/service_uuids.yaml")
        return self._services

    def _ensure_characteristics(self) -> dict[int, _UUIDEntry]:
        if self._characteristics is None:
            self._characteristics = self._load_uuid_yaml("uuids/characteristic_uuids.yaml")
        return self._characteristics

    def _ensure_descriptors(self) -> dict[int, _UUIDEntry]:
        if self._descriptors is None:
            self._descriptors = self._load_uuid_yaml("uuids/descriptors.yaml")
        return self._descriptors

    def _ensure_companies(self) -> dict[int, str]:
        if self._companies is None:
            path = self._sig_root / "assigned_numbers" / "company_identifiers" / "company_identifiers.yaml"
            with open(path) as f:
                data = yaml.safe_load(f)
            self._companies = {}
            self._company_name_to_id = {}
            for entry in data["company_identifiers"]:
                cid = entry["value"]
                name = entry["name"]
                self._companies[cid] = name
                self._company_name_to_id[name] = cid
        return self._companies

    def _ensure_ad_types(self) -> dict[int, str]:
        if self._ad_types is None:
            path = self._sig_root / "assigned_numbers" / "core" / "ad_types.yaml"
            with open(path) as f:
                data = yaml.safe_load(f)
            self._ad_types = {e["value"]: e["name"] for e in data["ad_types"]}
        return self._ad_types

    def _ensure_appearances(self) -> dict[int, str]:
        if self._appearances is None:
            path = self._sig_root / "assigned_numbers" / "core" / "appearance_values.yaml"
            with open(path) as f:
                data = yaml.safe_load(f)
            self._appearances = {e["category"]: e["name"] for e in data["appearance_values"]}
        return self._appearances

    def _load_uuid_yaml(self, relative_path: str) -> dict[int, _UUIDEntry]:
        path = self._sig_root / "assigned_numbers" / relative_path
        with open(path) as f:
            data = yaml.safe_load(f)
        return {
            entry["uuid"]: _UUIDEntry(
                uuid=entry["uuid"],
                name=entry["name"],
                identifier=entry.get("id", ""),
            )
            for entry in data["uuids"]
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/core/test_sig_db.py -v`
Expected: All 18 tests PASS.

- [ ] **Step 5: Run full core test suite**

Run: `uv run pytest tests/unit/core/ -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add pybluehost/core/sig_db.py tests/unit/core/test_sig_db.py
git commit -m "feat(core): add SIGDatabase with lazy-loaded YAML lookups"
```

---

## Task 12: Core Package Exports and Final Verification

**Files:**
- Modify: `pybluehost/core/__init__.py`
- Modify: `pybluehost/__init__.py`

- [ ] **Step 1: Update core/__init__.py with public exports**

```python
# pybluehost/core/__init__.py
"""PyBlueHost core infrastructure — shared by all protocol layers."""

from pybluehost.core.address import AddressType, BDAddress
from pybluehost.core.buffer import ByteBuffer
from pybluehost.core.errors import (
    GATTError,
    HCIError,
    InvalidTransitionError,
    L2CAPError,
    PyBlueHostError,
    SMPError,
    TimeoutError,
    TransportError,
)
from pybluehost.core.keys import CSRK, IRK, LTK, LinkKey, LinkKeyType
from pybluehost.core.sig_db import SIGDatabase
from pybluehost.core.statemachine import StateMachine, Transition
from pybluehost.core.trace import (
    BtsnoopSink,
    CallbackSink,
    Direction,
    JsonSink,
    RingBufferSink,
    TraceEvent,
    TraceSystem,
)
from pybluehost.core.types import ConnectionRole, IOCapability, LinkType
from pybluehost.core.uuid import UUID16, UUID128

__all__ = [
    "AddressType",
    "BDAddress",
    "BtsnoopSink",
    "ByteBuffer",
    "CSRK",
    "CallbackSink",
    "ConnectionRole",
    "Direction",
    "GATTError",
    "HCIError",
    "IOCapability",
    "IRK",
    "InvalidTransitionError",
    "JsonSink",
    "L2CAPError",
    "LTK",
    "LinkKey",
    "LinkKeyType",
    "LinkType",
    "PyBlueHostError",
    "RingBufferSink",
    "SMPError",
    "SIGDatabase",
    "StateMachine",
    "TimeoutError",
    "TraceEvent",
    "TraceSystem",
    "Transition",
    "TransportError",
    "UUID16",
    "UUID128",
]
```

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/ -v --tb=short`
Expected: All tests PASS (approximately 80+ tests).

- [ ] **Step 3: Run with coverage**

Run: `uv run pytest tests/ --cov=pybluehost.core --cov-report=term-missing`
Expected: Core module coverage ≥ 85%.

- [ ] **Step 4: Commit**

```bash
git add pybluehost/core/__init__.py pybluehost/__init__.py
git commit -m "feat(core): finalize core package exports"
```

---

## Verification Checklist

After all tasks are complete, verify:

- [ ] `uv run pytest tests/ -v` — all tests pass
- [ ] `uv run pytest tests/ --cov=pybluehost.core --cov-report=term-missing` — coverage ≥ 85%
- [ ] `python -c "from pybluehost.core import StateMachine, TraceSystem, SIGDatabase, BDAddress, UUID16"` — imports work
- [ ] `python -c "from pybluehost.core.sig_db import SIGDatabase; db = SIGDatabase.get(); print(db.service_name(0x180D))"` — prints "Heart Rate"
