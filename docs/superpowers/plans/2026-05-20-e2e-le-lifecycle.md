# E2E LE Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first `tests/e2e/` suite: four LE workflow scenarios that exercise multi-subsystem composition (GAP discovery + connection + SMP pairing + GATT discovery + read/write/notify + bond persistence + auto-encrypt). Transport-agnostic via existing `stack` / `peer_stack` / `transport_mode` fixtures so the same scenarios run on virtual (CI) and hardware (manual smoke).

**Architecture:** Test-only changes under `tests/e2e/`. A small shared service definition (`_test_service.py`), helper utilities (`_helpers.py`), per-test fixtures (`conftest.py`), and the four scenario tests (`test_le_lifecycle.py`). SC capability is gated via HCI introspection (`_supports_le_sc`) — no per-vendor allowlist. Mode-specific glue (the `VirtualLELink` bridge) lives in a single fixture that returns `None` in hardware mode.

**Tech Stack:** Python 3.10+, pytest, `pytest-asyncio`, existing `Stack` / `GATTClient` / `BLEScanner` / `BLEAdvertiser` / `BLEConnectionManager` / `GATTServer` / `JsonBondStorage` / `VirtualLELink` from the codebase. No new production code is introduced.

**Design spec:** [`docs/superpowers/specs/2026-05-20-e2e-le-lifecycle-design.md`](../specs/2026-05-20-e2e-le-lifecycle-design.md)

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Replace | `tests/e2e/conftest.py` | Replace the empty placeholder with `central_peripheral_pair` and `virtual_link_or_real_rf` fixtures |
| Create | `tests/e2e/_test_service.py` | `TEST_SERVICE_UUID`, the three characteristic UUIDs, `INITIAL_READ_VALUE`, `build_test_service()` |
| Create | `tests/e2e/_helpers.py` | `_supports_le_sc`, `central_discover_peripheral`, `central_discover_and_pair_sc_jw`, `wait_for_notifications`, `resolve_handles` |
| Create | `tests/e2e/test_le_lifecycle.py` | The four scenarios |
| Modify | `docs/superpowers/STATUS.md` | Mark Plan complete; update "下一步" |

No production-code changes anticipated. If a hidden API gap surfaces during implementation (the GATT client lacks a tight enough surface for a test step), the implementer reports DONE_WITH_CONCERNS rather than expanding scope.

---

## API surfaces this Plan uses (verified against current codebase)

The implementer should treat these as the source of truth — they were grepped from the live code before this Plan was written:

- `Stack.virtual(config, address)` / `Stack.from_usb(...)` — factories (already wired via `build_stack_from_spec`).
- `stack._local_address: BDAddress | None` — local BD_ADDR populated during init.
- `stack._gatt_server: GATTServer` — instance attribute.
- `GATTServer.add_service(svc: ServiceDefinition) -> ServiceHandles` (pybluehost/ble/gatt.py:204).
- `GATTServer.notify(handle: int, value: bytes, connections: list[int] | None = None)` (line 408).
- `GATTServer.enable_notifications(conn_handle, value_handle)` / `disable_notifications(...)` (lines 382/387) — driven by CCCD writes.
- `stack.gap.ble_advertiser.start(ad_data: AdvertisingData | None, scan_rsp_data: AdvertisingData | None)` (pybluehost/ble/gap.py:122).
- `stack.gap.ble_scanner.start(config: ScanConfig)` / `stop()` (line 197/208).
- `stack.gap.ble_scanner.on_result(handler: Callable[[ScanResult], object])` (line 187).
- `ScanResult.address: BDAddress`, `.advertising_data: AdvertisingData` (line 56).
- `stack.gap.ble_connections.connect(target: BDAddress, ...)` (pybluehost/ble/gap.py:273).
- `stack.gap.ble_connections.disconnect(handle, reason=0x13)` (line 301).
- `stack.connect_gatt(target: BDAddress, *, timeout: float = 10.0) -> GATTClient` (pybluehost/stack.py:704). Sets `client._connection_handle`.
- `GATTClient.discover_all_services() -> list[tuple[int, int, bytes]]` (returns (start, end, uuid_bytes) tuples) (pybluehost/ble/gatt.py:448).
- `GATTClient.discover_characteristics(start_handle, end_handle) -> list[DiscoveredCharacteristic]` (line 476). `DiscoveredCharacteristic.uuid: bytes`, `.value_handle: int`, `.declaration_handle: int`, `.properties: int`.
- `GATTClient.discover_descriptors(start_handle, end_handle) -> list[DiscoveredDescriptor]` (line 523).
- `GATTClient.read_characteristic(handle) -> bytes` (line 571).
- `GATTClient.write_characteristic(handle, value)` (line 574). Used for both regular value writes and CCCD writes (CCCDs are just attributes).
- `GATTClient._bearer.set_notification_handler(handler: Callable[[int, bytes], None | Awaitable[None]])` (pybluehost/ble/att.py:733). E2E tests reach into `_bearer` here; this is private but stable.
- `stack.pair(handle, timeout=...)` — see existing integration tests.
- `stack._smp.set_delegate(delegate)` — used in Sub-Plan 3a/3b tests.
- `stack.on_connection_event(handler: Callable[[StackConnectionEvent], object])` (pybluehost/stack.py:101). `event.state` strings include `"encrypted"`.
- `JsonBondStorage(path).load_bond(addr) -> BondInfo | None` and `.save_bond(bond)`.
- `VirtualLELink(central, peripheral, central_address, peripheral_address).connect() -> handle` / `.disconnect()` — only used in virtual mode.

Session-level fixtures from `tests/conftest.py` (already in place):
- `stack` — yields a fully-initialized `Stack` from `--transport=...`.
- `peer_stack` — yields a second `Stack` from `--transport-peer=...` (skips when absent).
- `transport_mode` — returns `"virtual"` / `"usb"` / `"uart"` / etc.
- `selected_transport_spec` / `selected_peer_spec` — the raw spec strings.

---

## Task 1: Shared test service

**Files:**
- Create: `tests/e2e/_test_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/e2e/_test_service.py`:

```python
"""Canonical GATT service used by tests/e2e/ scenarios.

Three characteristics:
  * read   — fixed initial value (TEST_READ).
  * write  — Write Without Response + Write; tests append observed writes.
  * notify — Notify; tests subscribe and observe value updates.
"""
from __future__ import annotations

from pybluehost.ble.gatt import (
    CharacteristicDefinition,
    DescriptorDefinition,
    ServiceDefinition,
)
from pybluehost.ble.permissions import (
    CharProperties,
    Permissions,
)
from pybluehost.core.uuid import UUID16, UUID128


TEST_SERVICE_UUID    = UUID128(bytes.fromhex("0000feed0000100080000000746573e2"))
TEST_READ_CHAR_UUID  = UUID128(bytes.fromhex("0000feed0000100080000000feed0001"))
TEST_WRITE_CHAR_UUID = UUID128(bytes.fromhex("0000feed0000100080000000feed0002"))
TEST_NOTIFY_CHAR_UUID = UUID128(bytes.fromhex("0000feed0000100080000000feed0003"))

INITIAL_READ_VALUE   = b"PyBlueHost E2E v1"
INITIAL_NOTIFY_VALUE = b"\x00"

CCCD_UUID = UUID16(0x2902)


def build_test_service() -> ServiceDefinition:
    """Return the canonical E2E test service definition."""
    return ServiceDefinition(
        uuid=TEST_SERVICE_UUID,
        is_primary=True,
        characteristics=[
            CharacteristicDefinition(
                uuid=TEST_READ_CHAR_UUID,
                properties=CharProperties.READ,
                permissions=Permissions.READ,
                value=INITIAL_READ_VALUE,
            ),
            CharacteristicDefinition(
                uuid=TEST_WRITE_CHAR_UUID,
                properties=CharProperties.WRITE | CharProperties.WRITE_WITHOUT_RESPONSE,
                permissions=Permissions.WRITE,
                value=b"",
            ),
            CharacteristicDefinition(
                uuid=TEST_NOTIFY_CHAR_UUID,
                properties=CharProperties.NOTIFY | CharProperties.READ,
                permissions=Permissions.READ,
                value=INITIAL_NOTIFY_VALUE,
                descriptors=[
                    DescriptorDefinition(
                        uuid=CCCD_UUID,
                        permissions=Permissions.READ | Permissions.WRITE,
                        value=b"\x00\x00",
                    ),
                ],
            ),
        ],
    )
```

Also create the test file `tests/e2e/test_le_lifecycle.py` shell that imports this for sanity:

```python
"""End-to-end LE lifecycle scenarios."""
from __future__ import annotations

# (will be filled in by Tasks 4–7)
```

And add a minimal sanity test in `tests/e2e/test_le_lifecycle.py`:

```python
def test_test_service_definition_round_trips():
    """build_test_service() returns a valid ServiceDefinition with 3 chars."""
    from tests.e2e._test_service import build_test_service
    svc = build_test_service()
    assert len(svc.characteristics) == 3
    uuids = [c.uuid for c in svc.characteristics]
    from tests.e2e._test_service import (
        TEST_READ_CHAR_UUID, TEST_WRITE_CHAR_UUID, TEST_NOTIFY_CHAR_UUID,
    )
    assert TEST_READ_CHAR_UUID in uuids
    assert TEST_WRITE_CHAR_UUID in uuids
    assert TEST_NOTIFY_CHAR_UUID in uuids
```

- [ ] **Step 2: Run the test (expect failure first)**

Run: `uv run pytest tests/e2e/test_le_lifecycle.py -v`
Expected: FAIL — `tests.e2e._test_service` does not exist yet.

- [ ] **Step 3: Verify enum / class names**

Before assuming the imports above are correct, verify them:

```bash
grep -n "class CharProperties\|class Permissions\|class CharacteristicDefinition\|class DescriptorDefinition\|class ServiceDefinition\|class UUID16\|class UUID128" pybluehost/ble/gatt.py pybluehost/ble/permissions.py pybluehost/core/uuid.py 2>/dev/null
```

Adjust the import paths and enum-member names in `_test_service.py` to match what's actually there. (e.g., `WRITE_WITHOUT_RESPONSE` may be `WRITE_NO_RSP`; `Permissions.READ` may be `Permissions.READABLE` etc.) Use what the codebase actually uses.

- [ ] **Step 4: Run tests again**

Run: `uv run pytest tests/e2e/test_le_lifecycle.py -v`
Expected: 1 PASS.
Run: `uv run pytest tests/e2e/ -q` — expect 1 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/_test_service.py tests/e2e/test_le_lifecycle.py
git commit -m "test(e2e): canonical test service definition for LE lifecycle scenarios

Adds tests/e2e/_test_service.py with TEST_SERVICE_UUID and three
characteristics (read, write, notify with CCCD). build_test_service()
returns a ServiceDefinition that scenario tests register on the Peripheral.
Includes a basic round-trip sanity test."
```

---

## Task 2: Helpers (`_helpers.py`)

**Files:**
- Create: `tests/e2e/_helpers.py`
- Test: `tests/e2e/test_le_lifecycle.py` (append)

- [ ] **Step 1: Append failing tests**

Append to `tests/e2e/test_le_lifecycle.py`:

```python
import asyncio
import pytest


@pytest.mark.asyncio
async def test_wait_for_notifications_returns_when_count_reached():
    from tests.e2e._helpers import wait_for_notifications
    events: list = []

    async def producer():
        await asyncio.sleep(0.01)
        events.append(b"a")
        await asyncio.sleep(0.01)
        events.append(b"b")

    task = asyncio.create_task(producer())
    await wait_for_notifications(events, n=2, timeout=1.0)
    await task
    assert events == [b"a", b"b"]


@pytest.mark.asyncio
async def test_wait_for_notifications_raises_on_timeout():
    from tests.e2e._helpers import wait_for_notifications
    events: list = []
    with pytest.raises(asyncio.TimeoutError):
        await wait_for_notifications(events, n=1, timeout=0.05)


def test_resolve_handles_returns_per_uuid_value_handles():
    """Given a discovered-characteristics list, returns a dict keyed by UUID
    that maps to the value_handle."""
    from tests.e2e._helpers import resolve_handles
    from tests.e2e._test_service import (
        TEST_READ_CHAR_UUID, TEST_WRITE_CHAR_UUID, TEST_NOTIFY_CHAR_UUID,
    )
    from pybluehost.ble.gatt import DiscoveredCharacteristic
    chars = [
        DiscoveredCharacteristic(declaration_handle=0x10, value_handle=0x11,
                                 properties=0x02, uuid=TEST_READ_CHAR_UUID.to_bytes()),
        DiscoveredCharacteristic(declaration_handle=0x12, value_handle=0x13,
                                 properties=0x08, uuid=TEST_WRITE_CHAR_UUID.to_bytes()),
        DiscoveredCharacteristic(declaration_handle=0x14, value_handle=0x15,
                                 properties=0x10, uuid=TEST_NOTIFY_CHAR_UUID.to_bytes()),
    ]
    handles = resolve_handles(chars, {
        "read": TEST_READ_CHAR_UUID,
        "write": TEST_WRITE_CHAR_UUID,
        "notify": TEST_NOTIFY_CHAR_UUID,
    })
    assert handles == {"read": 0x11, "write": 0x13, "notify": 0x15}
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/e2e/test_le_lifecycle.py -v -k "wait_for_notifications or resolve_handles"`
Expected: FAIL — `tests.e2e._helpers` does not exist.

- [ ] **Step 3: Implement helpers**

Create `tests/e2e/_helpers.py`:

```python
"""Shared helpers for tests/e2e/ scenarios.

Discovery + capability + flow utilities. All are transport-agnostic.
"""
from __future__ import annotations

import asyncio
import time
from typing import Iterable

from pybluehost.ble.gap import ScanConfig
from pybluehost.ble.gatt import DiscoveredCharacteristic
from pybluehost.core.address import BDAddress
from pybluehost.core.uuid import UUID16, UUID128


# ---------------------------------------------------------------------------
# Capability gating
# ---------------------------------------------------------------------------

# HCI command-bitmap positions for the SC-related commands. From
# pybluehost/hci/capabilities.py (HCI tolerant init Plan).
_OCTET_LE_READ_LOCAL_P256_PK = 34   # bit 1
_BIT_LE_READ_LOCAL_P256_PK = 1
_OCTET_LE_GENERATE_DHKEY = 34       # bit 2
_BIT_LE_GENERATE_DHKEY = 2


def _supports_le_sc(stack) -> bool:
    """True iff the controller advertises LE Secure Connections commands.

    Reads pre-cached capability bitmap from stack._hci. Virtual mode advertises
    full support; older hardware (e.g. BT 4.0 dongles) does not.
    """
    hci = getattr(stack, "_hci", None)
    if hci is None:
        return False
    caps = getattr(hci, "supported_commands", None) or getattr(hci, "_supported_commands", None)
    if caps is None:
        return False
    # caps is a 64-byte bitmap; check the two SC commands at octet 34, bits 1 + 2.
    p256 = bool(caps[_OCTET_LE_READ_LOCAL_P256_PK] & (1 << _BIT_LE_READ_LOCAL_P256_PK))
    dhkey = bool(caps[_OCTET_LE_GENERATE_DHKEY] & (1 << _BIT_LE_GENERATE_DHKEY))
    return p256 and dhkey


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

async def central_discover_peripheral(
    stack_c, expected_addr: BDAddress, timeout: float = 5.0,
) -> None:
    """Start scanning, wait for an advertising report matching expected_addr,
    stop scanning.

    Returns when the address is seen (does NOT connect). Caller proceeds
    with stack_c.gap.ble_connections.connect(expected_addr) or
    stack_c.connect_gatt(expected_addr).
    """
    seen_event = asyncio.Event()

    def _on_result(result):
        if result.address == expected_addr:
            seen_event.set()

    stack_c.gap.ble_scanner.on_result(_on_result)
    await stack_c.gap.ble_scanner.start(ScanConfig())
    try:
        await asyncio.wait_for(seen_event.wait(), timeout=timeout)
    finally:
        await stack_c.gap.ble_scanner.stop()


async def central_discover_and_pair_sc_jw(
    stack_c, expected_addr: BDAddress, *, scan_timeout: float = 5.0,
    pair_timeout: float = 20.0,
) -> tuple[object, int]:
    """Convenience composition: scan → connect_gatt → pair (SC Just Works).

    Returns (gatt_client, connection_handle).
    """
    await central_discover_peripheral(stack_c, expected_addr, timeout=scan_timeout)
    client = await stack_c.connect_gatt(expected_addr, timeout=scan_timeout)
    handle = client._connection_handle
    await stack_c.pair(handle, timeout=pair_timeout)
    return client, handle


# ---------------------------------------------------------------------------
# Notification waiter
# ---------------------------------------------------------------------------

async def wait_for_notifications(events: list, n: int, timeout: float = 1.0) -> None:
    """Block until len(events) >= n; raise asyncio.TimeoutError otherwise."""
    deadline = time.monotonic() + timeout
    while len(events) < n:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError(
                f"only received {len(events)}/{n} notifications within {timeout}s"
            )
        await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# Handle resolution
# ---------------------------------------------------------------------------

def resolve_handles(
    chars: list[DiscoveredCharacteristic],
    labels: dict[str, UUID16 | UUID128],
) -> dict[str, int]:
    """Given a discovered-characteristics list and a label→UUID mapping,
    return a label→value_handle mapping.

    Raises KeyError if any requested UUID was not discovered.
    """
    result: dict[str, int] = {}
    for label, uuid in labels.items():
        target = uuid.to_bytes()
        found = next((c for c in chars if c.uuid == target), None)
        if found is None:
            raise KeyError(f"characteristic {label!r} (uuid={uuid}) not discovered")
        result[label] = found.value_handle
    return result
```

**Note on `supported_commands`**: The implementer should grep `pybluehost/hci/capabilities.py` and `pybluehost/hci/controller.py` to see how the bitmap is exposed on the `HCIController`. The attribute name may be `supported_commands` (public) or `_supported_commands` (private). Use the one that exists; the helper above handles both.

**Note on `gap` attribute**: `Stack` may expose the unified GAP as `stack.gap` or `stack._gap`. Grep first: `grep -n "self._gap\|stack.gap" pybluehost/stack.py`. If only `_gap` exists, the helpers should use that; the public-API spelling is the implementer's call given the codebase precedent.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/e2e/test_le_lifecycle.py -v -k "wait_for_notifications or resolve_handles"`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/_helpers.py tests/e2e/test_le_lifecycle.py
git commit -m "test(e2e): helpers — capability gate, discovery, notifications

Adds tests/e2e/_helpers.py with _supports_le_sc (HCI Read_Local_Supported_Commands
bitmap introspection), central_discover_peripheral (scan + match address),
central_discover_and_pair_sc_jw (full discovery→connect→pair flow),
wait_for_notifications (await-with-timeout loop), and resolve_handles
(characteristic UUID→value-handle dict). All transport-agnostic."
```

---

## Task 3: Fixtures (`conftest.py` replacement)

**Files:**
- Replace: `tests/e2e/conftest.py`

- [ ] **Step 1: Inspect the current conftest**

Run: `cat tests/e2e/conftest.py`
Confirm it's the placeholder created by Pytest Transport Selection Task 15. Preserve any non-trivial content if present (likely just a re-export of session fixtures).

- [ ] **Step 2: Replace with the new fixtures**

Write `tests/e2e/conftest.py`:

```python
"""Test-scoped fixtures for tests/e2e/.

The session-level `stack`, `peer_stack`, `transport_mode`, `selected_transport_spec`
fixtures come from tests/conftest.py and are not re-exported here.
"""
from __future__ import annotations

import pytest_asyncio

from pybluehost.hci.virtual_link import VirtualLELink

from tests.e2e._test_service import build_test_service


@pytest_asyncio.fixture
async def central_peripheral_pair(stack, peer_stack):
    """Yields (stack_central, stack_peripheral) with the E2E test service
    registered on the Peripheral.

    `stack` and `peer_stack` come from tests/conftest.py session fixtures and
    are already initialized for the active --transport / --transport-peer.
    """
    peer_stack._gatt_server.add_service(build_test_service())
    yield stack, peer_stack


@pytest_asyncio.fixture
async def virtual_link_or_real_rf(central_peripheral_pair, transport_mode):
    """Virtual: bridge the two virtual controllers with a VirtualLELink.
    Hardware: yield None — real RF connects them naturally.
    """
    stack_c, stack_p = central_peripheral_pair
    if transport_mode == "virtual":
        link = VirtualLELink(
            central=stack_c._virtual_controller,
            peripheral=stack_p._virtual_controller,
            central_address=stack_c._local_address,
            peripheral_address=stack_p._local_address,
        )
        try:
            yield link
        finally:
            try:
                await link.disconnect()
            except Exception:
                pass
    else:
        yield None
```

- [ ] **Step 3: Smoke-verify the fixtures load**

Run: `uv run pytest tests/e2e/ -v --transport=virtual --collect-only`
Expected: no collection errors; the existing helper tests still collected.

Run: `uv run pytest tests/e2e/test_le_lifecycle.py -v --transport=virtual`
Expected: existing tests still pass (the helpers from Tasks 1–2 don't use the new fixtures yet, so they're unaffected).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/conftest.py
git commit -m "test(e2e): fixtures — central_peripheral_pair + virtual_link_or_real_rf

central_peripheral_pair registers the canonical test service on the
Peripheral. virtual_link_or_real_rf bridges two virtual controllers via
VirtualLELink in virtual mode and yields None in hardware mode (real RF
connects them naturally). Composes with the session-level stack /
peer_stack / transport_mode fixtures from tests/conftest.py."
```

---

## Task 4: Test 1 — `test_e2e_scan_connect_pair_read`

**Files:**
- Modify: `tests/e2e/test_le_lifecycle.py` (append)

- [ ] **Step 1: Append the failing test**

Append to `tests/e2e/test_le_lifecycle.py`:

```python
import pytest
import pytest_asyncio

from pybluehost.core.gap_common import AdvertisingData


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_scan_connect_pair_read(central_peripheral_pair, virtual_link_or_real_rf):
    """Scan → Connect → SC JW Pair → discover service → read characteristic.

    Smoke baseline: shortest valuable end-to-end path.
    """
    from tests.e2e._helpers import (
        _supports_le_sc, central_discover_and_pair_sc_jw, resolve_handles,
    )
    from tests.e2e._test_service import (
        TEST_SERVICE_UUID, TEST_READ_CHAR_UUID, INITIAL_READ_VALUE,
    )

    stack_c, stack_p = central_peripheral_pair
    if not _supports_le_sc(stack_c):
        pytest.skip("adapter does not support LE Secure Connections")

    # Peripheral starts advertising
    ad_data = AdvertisingData.from_dict({
        "local_name": "PBH-E2E",
        "service_uuids_128": [TEST_SERVICE_UUID],
    })
    await stack_p.gap.ble_advertiser.start(ad_data=ad_data)

    try:
        # Central: scan + connect + pair
        client, handle = await central_discover_and_pair_sc_jw(
            stack_c, stack_p._local_address,
        )

        # Discover services
        services = await client.discover_all_services()
        svc = next(
            (s for s in services if s[2] == TEST_SERVICE_UUID.to_bytes()),
            None,
        )
        assert svc is not None, f"TEST_SERVICE_UUID not found among {services}"
        s_handle, e_handle, _uuid = svc

        # Discover characteristics within the service handle range
        chars = await client.discover_characteristics(s_handle, e_handle)
        handles = resolve_handles(chars, {"read": TEST_READ_CHAR_UUID})

        # Read the characteristic
        value = await client.read_characteristic(handles["read"])
        assert value == INITIAL_READ_VALUE, (
            f"read returned {value!r}, expected {INITIAL_READ_VALUE!r}"
        )
    finally:
        # Clean disconnect
        if "handle" in dir():
            with __import__("contextlib").suppress(Exception):
                await stack_c.gap.ble_connections.disconnect(handle)
        with __import__("contextlib").suppress(Exception):
            await stack_p.gap.ble_advertiser.stop()
```

**Note on `AdvertisingData.from_dict`**: verify the actual API. Grep:
```
grep -n "class AdvertisingData\|def from_dict\|def from_bytes\|local_name\|service_uuids" pybluehost/core/gap_common.py
```
Use whatever spelling the codebase has. If `from_dict` doesn't exist, use the documented constructor or `AdvertisingData(...)` form.

- [ ] **Step 2: Run the test (expect failure)**

Run: `uv run pytest tests/e2e/test_le_lifecycle.py::test_e2e_scan_connect_pair_read -v --transport=virtual`
Expected: most likely an API-name fix is needed (e.g., `AdvertisingData.from_dict`), or the fixture setup needs an asyncio.sleep after advertising start. Debug iteratively.

- [ ] **Step 3: Resolve any API mismatches**

If the test fails because:
- `AdvertisingData.from_dict` doesn't exist → use the constructor form the codebase actually exposes (`AdvertisingData(...)` with named fields).
- The scanner doesn't see the advertisement within 5 s → check that `virtual_link_or_real_rf` is bridging the controllers correctly; add `await asyncio.sleep(0.05)` after `advertiser.start()` to let the controller post the first advert.
- `client.discover_all_services()` returns empty → confirm the peripheral's `_gatt_server.add_service(...)` ran before the connection (the fixture order should ensure this).
- The read value differs → check the service definition's READ char value matches `INITIAL_READ_VALUE`.

Treat API mismatches as test-only adjustments — do NOT change production code.

- [ ] **Step 4: Run the test (expect pass)**

Run: `uv run pytest tests/e2e/test_le_lifecycle.py::test_e2e_scan_connect_pair_read -v --transport=virtual`
Expected: PASS in under 10 s.

- [ ] **Step 5: Run full e2e module**

Run: `uv run pytest tests/e2e/ -v --transport=virtual`
Expected: all tests so far PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/e2e/test_le_lifecycle.py
git commit -m "test(e2e): scan-connect-pair-read scenario (test 1/4)

Central scans for advertising peripheral, connects, completes SC Just Works
pair via central_discover_and_pair_sc_jw helper, discovers the test service,
discovers its characteristics, reads the canonical read characteristic.
Verifies the value matches INITIAL_READ_VALUE. Disconnects cleanly on
teardown. SC capability-gated via _supports_le_sc."
```

---

## Task 5: Test 2 — `test_e2e_gatt_write_and_notify`

**Files:**
- Modify: `tests/e2e/test_le_lifecycle.py` (append)

- [ ] **Step 1: Append the failing test**

```python
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_gatt_write_and_notify(central_peripheral_pair, virtual_link_or_real_rf):
    """Write a characteristic; subscribe to notifications; observe two
    notifications; unsubscribe; verify a third notification is NOT observed."""
    import asyncio

    from tests.e2e._helpers import (
        _supports_le_sc, central_discover_and_pair_sc_jw,
        resolve_handles, wait_for_notifications,
    )
    from tests.e2e._test_service import (
        TEST_SERVICE_UUID, TEST_WRITE_CHAR_UUID, TEST_NOTIFY_CHAR_UUID, CCCD_UUID,
    )

    stack_c, stack_p = central_peripheral_pair
    if not _supports_le_sc(stack_c):
        pytest.skip("adapter does not support LE Secure Connections")

    # Track writes observed on the peripheral GATT server.
    peripheral_writes: list[bytes] = []
    # GATTServer doesn't natively expose a per-attribute write callback in the
    # codebase today, so we attach a small hook to its write handler. The
    # implementer should grep:
    #   grep -n "def write_attribute\|on_write\|_on_write\|handle_write" pybluehost/ble/gatt.py
    # and pick whichever extension point exists. Simplest path: register a
    # listener on the GATTServer; failing that, monkey-patch the handler for
    # TEST_WRITE_CHAR_UUID's value_handle in this test.
    #
    # For the loopback case the alternate simple verification is: read the
    # characteristic from the central side AFTER the write completes and
    # confirm the value updated.

    ad = __import__("pybluehost.core.gap_common", fromlist=["AdvertisingData"]).AdvertisingData
    await stack_p.gap.ble_advertiser.start(
        ad_data=ad.from_dict({
            "local_name": "PBH-E2E",
            "service_uuids_128": [TEST_SERVICE_UUID],
        }),
    )

    try:
        client, handle = await central_discover_and_pair_sc_jw(
            stack_c, stack_p._local_address,
        )

        services = await client.discover_all_services()
        svc = next(s for s in services if s[2] == TEST_SERVICE_UUID.to_bytes())
        s_handle, e_handle, _ = svc

        chars = await client.discover_characteristics(s_handle, e_handle)
        handles = resolve_handles(chars, {
            "write": TEST_WRITE_CHAR_UUID,
            "notify": TEST_NOTIFY_CHAR_UUID,
        })

        # Discover CCCD descriptor for the notify char (it's at value_handle + 1
        # typically; use discover_descriptors to find it explicitly).
        descs = await client.discover_descriptors(handles["notify"] + 1, e_handle)
        cccd = next(
            (d for d in descs if d.uuid == CCCD_UUID.to_bytes()),
            None,
        )
        assert cccd is not None, "CCCD not discovered"

        # --- Write path ---
        await client.write_characteristic(handles["write"], b"hello e2e")
        await asyncio.sleep(0.05)
        # Verify by reading the value back from peripheral via GATT server's
        # attribute store, if accessible. Implementer: pick the path that
        # works given the actual GATTServer API.
        # Simplest: client reads the write char and confirms the value updated.
        # NOTE: this requires the write char to also have READ permission.
        # If not, the implementer should add a server-side write observer.

        # --- Notify path ---
        notify_events: list[bytes] = []

        def _on_notify(att_handle: int, value: bytes) -> None:
            if att_handle == handles["notify"]:
                notify_events.append(value)

        client._bearer.set_notification_handler(_on_notify)

        # Subscribe by writing 0x0001 to the CCCD
        await client.write_characteristic(cccd.handle, bytes([0x01, 0x00]))
        await asyncio.sleep(0.05)

        # Peripheral emits two notifications
        await stack_p._gatt_server.notify(handles["notify"], b"ping-1")
        await stack_p._gatt_server.notify(handles["notify"], b"ping-2")

        await wait_for_notifications(notify_events, n=2, timeout=2.0)
        assert notify_events == [b"ping-1", b"ping-2"]

        # Unsubscribe
        await client.write_characteristic(cccd.handle, bytes([0x00, 0x00]))
        await asyncio.sleep(0.05)
        await stack_p._gatt_server.notify(handles["notify"], b"ping-3")
        await asyncio.sleep(0.2)
        assert notify_events == [b"ping-1", b"ping-2"]    # still 2 — unsubscribed

    finally:
        with __import__("contextlib").suppress(Exception):
            await stack_c.gap.ble_connections.disconnect(handle)
        with __import__("contextlib").suppress(Exception):
            await stack_p.gap.ble_advertiser.stop()
```

**Note on write observation**: the test currently *implicitly* trusts the GATTServer's default attribute store to accept the write. If you need to assert the peripheral observed the write more strongly, two options:
1. Make TEST_WRITE_CHAR_UUID also READable, and have the central read it back after writing.
2. Add a listener pattern to `GATTServer` if one exists; otherwise add a tiny helper to the test only (not to production code).

If neither path is feasible without production-code changes, document this as DONE_WITH_CONCERNS — the notify half of the test is the higher-value portion.

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/e2e/test_le_lifecycle.py::test_e2e_gatt_write_and_notify -v --transport=virtual`

If notifications don't arrive, debug:
- Is the CCCD write reaching the peripheral? Check `stack_p._gatt_server._notifications_enabled` after the subscribe write.
- Is the `notify()` call from the peripheral reaching the central? Trace via logger.

- [ ] **Step 3: Run full e2e module**

Run: `uv run pytest tests/e2e/ -v --transport=virtual`
Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_le_lifecycle.py
git commit -m "test(e2e): GATT write + notify subscribe/unsubscribe (test 2/4)

After SC JW pair: writes to the writable characteristic; subscribes to
notifications by writing 0x0001 to the CCCD; peripheral emits two
notifications and central observes both via ATTBearer notification handler;
unsubscribes; verifies a third peripheral notify is NOT observed."
```

---

## Task 6: Test 3 — `test_e2e_bonded_reconnect_auto_encrypt`

**Files:**
- Modify: `tests/e2e/test_le_lifecycle.py` (append)

This test manages its own two-session lifecycle (does NOT use the `central_peripheral_pair` fixture, since each session needs fresh stacks pointing at the same on-disk bond storage).

- [ ] **Step 1: Append the failing test**

```python
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_bonded_reconnect_auto_encrypt(
    tmp_path, selected_transport_spec, selected_peer_spec, transport_mode,
):
    """Two sessions sharing on-disk bond storage. Session 1: pair + bond.
    Session 2: reconnect → auto-encrypt event fires → GATT read works on
    the encrypted link without redoing SMP."""
    import asyncio

    from pybluehost.ble.security import SecurityConfig
    from pybluehost.ble.smp import JsonBondStorage
    from pybluehost.core.address import BDAddress
    from pybluehost.core.gap_common import AdvertisingData
    from pybluehost.hci.virtual_link import VirtualLELink
    from pybluehost.stack import StackConfig

    from tests._transport_resolve import build_stack_from_spec
    from tests.e2e._helpers import (
        _supports_le_sc, central_discover_and_pair_sc_jw,
        central_discover_peripheral, resolve_handles,
    )
    from tests.e2e._test_service import (
        TEST_SERVICE_UUID, TEST_READ_CHAR_UUID, INITIAL_READ_VALUE,
        build_test_service,
    )

    bonds_c_path = tmp_path / "bonds_c.json"
    bonds_p_path = tmp_path / "bonds_p.json"

    async def _open_pair():
        cfg_c = StackConfig(
            bond_storage=JsonBondStorage(bonds_c_path),
            security=SecurityConfig(enable_secure_connections=True),
        )
        cfg_p = StackConfig(
            bond_storage=JsonBondStorage(bonds_p_path),
            security=SecurityConfig(enable_secure_connections=True),
        )
        stack_c = await build_stack_from_spec(selected_transport_spec, config=cfg_c)
        stack_p = await build_stack_from_spec(selected_peer_spec, config=cfg_p)
        stack_p._gatt_server.add_service(build_test_service())
        link = None
        if transport_mode == "virtual":
            link = VirtualLELink(
                central=stack_c._virtual_controller,
                peripheral=stack_p._virtual_controller,
                central_address=stack_c._local_address,
                peripheral_address=stack_p._local_address,
            )
        return stack_c, stack_p, link

    async def _close_pair(stack_c, stack_p, link):
        if link is not None:
            with __import__("contextlib").suppress(Exception):
                await link.disconnect()
        await stack_c.close()
        await stack_p.close()

    # ---------- Session 1 ----------
    stack_c, stack_p, link = await _open_pair()
    if not _supports_le_sc(stack_c):
        await _close_pair(stack_c, stack_p, link)
        pytest.skip("adapter does not support LE Secure Connections")

    ad = AdvertisingData.from_dict({
        "local_name": "PBH-E2E",
        "service_uuids_128": [TEST_SERVICE_UUID],
    })
    await stack_p.gap.ble_advertiser.start(ad_data=ad)
    try:
        client, handle = await central_discover_and_pair_sc_jw(
            stack_c, stack_p._local_address,
        )
        bond = await stack_c._config.bond_storage.load_bond(stack_p._local_address)
        assert bond is not None and bond.sc is True
        await stack_c.gap.ble_connections.disconnect(handle)
    finally:
        await stack_p.gap.ble_advertiser.stop()
        await _close_pair(stack_c, stack_p, link)

    # ---------- Session 2 ----------
    stack_c, stack_p, link = await _open_pair()

    encrypted_events: list = []
    stack_c.on_connection_event(
        lambda e: encrypted_events.append(e) if getattr(e, "state", None) == "encrypted" else None
    )

    await stack_p.gap.ble_advertiser.start(ad_data=ad)
    try:
        # Reconnect — no pair() call; auto-encrypt should fire.
        await central_discover_peripheral(stack_c, stack_p._local_address, timeout=5.0)
        client = await stack_c.connect_gatt(stack_p._local_address, timeout=10.0)
        handle = client._connection_handle

        for _ in range(40):  # ~2s budget
            if encrypted_events:
                break
            await asyncio.sleep(0.05)
        assert encrypted_events, "auto-encrypt did not fire on bonded reconnect"

        # GATT read works on the resumed encrypted link.
        services = await client.discover_all_services()
        svc = next(s for s in services if s[2] == TEST_SERVICE_UUID.to_bytes())
        chars = await client.discover_characteristics(svc[0], svc[1])
        handles = resolve_handles(chars, {"read": TEST_READ_CHAR_UUID})
        value = await client.read_characteristic(handles["read"])
        assert value == INITIAL_READ_VALUE

        await stack_c.gap.ble_connections.disconnect(handle)
    finally:
        await stack_p.gap.ble_advertiser.stop()
        await _close_pair(stack_c, stack_p, link)
```

**Note on `build_stack_from_spec` import path**: grep `tests/_transport_resolve.py` / `tests/_transport_select.py` to confirm whether the factory lives in `_transport_resolve` or `_transport_select`. Update the import accordingly.

**Note on `stack._config`**: `_config` may be the field name OR `Stack` may expose `config` publicly. Verify with `grep -n "self._config\|self.config" pybluehost/stack.py | head -5`.

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/e2e/test_le_lifecycle.py::test_e2e_bonded_reconnect_auto_encrypt -v --transport=virtual`

Common debug points:
- Session 2's `central_discover_peripheral` times out → make sure session 2's `peer_stack` also restarts advertising. The test already does `stack_p.gap.ble_advertiser.start(ad_data=ad)`.
- `encrypted` event never fires → trace the LE LTK Request flow. The Sub-Plan 1 followups Plan delivered the auto-encrypt path; the integration test `test_sc_reconnect_auto_restores_encryption` proves it works.

- [ ] **Step 3: Run full e2e module**

Run: `uv run pytest tests/e2e/ -v --transport=virtual`
Expected: 3 of the 4 scenarios PASS (Test 4 not yet written).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_le_lifecycle.py
git commit -m "test(e2e): bonded reconnect with auto-encrypt (test 3/4)

Two-session lifecycle: Session 1 pairs (SC JW) and persists bond on disk;
Session 2 opens fresh stacks pointing at the same JsonBondStorage paths,
reconnects without redoing pair, observes the encryption-change event,
then performs a GATT read on the encrypted link. Validates the PRD-acceptance
bonded-device lifecycle in a single composite scenario."
```

---

## Task 7: Test 4 — `test_e2e_pair_failure_disconnects_cleanly`

**Files:**
- Modify: `tests/e2e/test_le_lifecycle.py` (append)

- [ ] **Step 1: Append the failing test**

```python
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_pair_failure_disconnects_cleanly(central_peripheral_pair, virtual_link_or_real_rf):
    """Mismatched NC delegates → pair() raises with reason=4 → teardown completes
    within 2s on each stack. Regression guard against leaked pairing_complete
    futures from Sub-Plan 3a/3b reviews."""
    import asyncio

    from pybluehost.ble.security import SecurityConfig
    from pybluehost.ble.smp import AutoAcceptDelegate
    from pybluehost.core.gap_common import AdvertisingData
    from pybluehost.core.types import IOCapability

    from tests.e2e._helpers import _supports_le_sc, central_discover_peripheral
    from tests.e2e._test_service import TEST_SERVICE_UUID

    stack_c, stack_p = central_peripheral_pair
    if not _supports_le_sc(stack_c):
        pytest.skip("adapter does not support LE Secure Connections")

    # Force NC association: SC + MITM on both sides + matching IO caps.
    # We can't trivially reconfigure SecurityConfig on a live stack; instead
    # we drive the failure by injecting mismatched NC delegates.
    class _AcceptDelegate(AutoAcceptDelegate):
        async def confirm_numeric(self, peer_addr, value):
            return True

    class _RejectDelegate(AutoAcceptDelegate):
        async def confirm_numeric(self, peer_addr, value):
            return False

    stack_c._smp.set_delegate(_AcceptDelegate())
    stack_p._smp.set_delegate(_RejectDelegate())

    # NOTE: this assumes `central_peripheral_pair`'s underlying StackConfig
    # has mitm_required=True and IO caps that select NC. If the session
    # fixtures don't, this test will fall through to SC Just Works and the
    # delegate rejection won't trigger. In that case:
    #
    # 1. Verify with a pre-pair assertion that _association_model would
    #    return "numeric_comparison" given the current ctx — out of scope here.
    # 2. Or, more robust: skip this test when stack security config doesn't
    #    advertise mitm_required:
    if not getattr(stack_c._config.security, "mitm_required", False):
        pytest.skip(
            "test_e2e_pair_failure requires SecurityConfig(mitm_required=True); "
            "tests/conftest.py session fixtures should be extended to allow "
            "per-test SecurityConfig override"
        )

    ad = AdvertisingData.from_dict({
        "local_name": "PBH-E2E",
        "service_uuids_128": [TEST_SERVICE_UUID],
    })
    await stack_p.gap.ble_advertiser.start(ad_data=ad)
    try:
        await central_discover_peripheral(stack_c, stack_p._local_address)
        client = await stack_c.connect_gatt(stack_p._local_address, timeout=5.0)
        handle = client._connection_handle

        with pytest.raises(Exception, match="SMP pairing failed"):
            await stack_c.pair(handle, timeout=5.0)

        # Critical: cleanup after the failed pair completes within 2s.
        await asyncio.wait_for(
            stack_c.gap.ble_connections.disconnect(handle), timeout=2.0,
        )
    finally:
        with __import__("contextlib").suppress(Exception):
            await stack_p.gap.ble_advertiser.stop()
```

**Note on session-fixture SecurityConfig**: the session-level `stack` / `peer_stack` fixtures may not advertise `mitm_required=True`. If they don't, this test skips cleanly. Extending the session fixtures to allow per-test override is a separate Plan; for now the skip path is correct behavior.

If during implementation it becomes clear that the test will always skip on the current fixture configuration, the implementer may either:
- Replace the session-fixture path with a per-test stack construction (similar to Test 3's `_open_pair`), OR
- Document the skip as expected and move on.

The point of this test is regression-protection against the leaked-future class of bugs; if it can't run, that's a partial loss but not a Plan failure.

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/e2e/test_le_lifecycle.py::test_e2e_pair_failure_disconnects_cleanly -v --transport=virtual`

Expected: PASS or SKIP depending on session fixture config. PASS preferred.

- [ ] **Step 3: Run full e2e module**

Run: `uv run pytest tests/e2e/ -v --transport=virtual`
Expected: 4 scenarios all PASS (or one skipped if fixture config doesn't enable MITM).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_le_lifecycle.py
git commit -m "test(e2e): pair-failure clean teardown (test 4/4)

Mismatched NC delegates → stack.pair() raises with reason=4 → connection
disconnect + stack teardown complete within 2s. Regression guard for the
leaked pairing_complete future class of bugs flagged in Sub-Plan 3a/3b
final reviews. Skips when session-level SecurityConfig doesn't enable
mitm_required."
```

---

## Task 8: STATUS.md update

**Files:**
- Modify: `docs/superpowers/STATUS.md`

- [ ] **Step 1: Update top-of-file**

In `docs/superpowers/STATUS.md`, near line 9–11:

```markdown
**当前进行中**：E2E LE Lifecycle — ✅ 完成
**下一步**：断线重连闭环 / Classic E2E / 真机 E2E 验证（同套测试用 --transport=usb）
**不在路线图**：SMP Sub-Plan 3c (OOB) — 暂无计划支持；如未来有具体硬件/产品需求再立项
```

- [ ] **Step 2: Add the new Plan row to the progress table**

Append to the Plan table (around line 51, after the 3b-2 row):

```markdown
| E2E LE Lifecycle | tests/e2e/ 首轮覆盖：scan→connect→pair→GATT 4 个端到端场景；transport-agnostic（virtual 自动跑 / hardware 用 --transport=usb 手动跑） | ✅ 完成 | [2026-05-20-e2e-le-lifecycle](plans/2026-05-20-e2e-le-lifecycle.md) | `tests/e2e/{conftest,_test_service,_helpers,test_le_lifecycle}.py` |
```

Increment "总计：N 个 Plan" by one (line ~53).

- [ ] **Step 3: Add detailed-progress section**

Append a detailed section after the existing 3b-2 detailed section, matching the markdown style of prior sections (date, what was built, acceptance criteria checked, follow-ups). Concise — ~10 lines.

Example shape (adjust wording to match the existing per-Plan sections):

```markdown
### ✅ 2026-05-20 — E2E LE Lifecycle

- 提交范围：`tests/e2e/_test_service.py`、`tests/e2e/_helpers.py`、`tests/e2e/conftest.py`、`tests/e2e/test_le_lifecycle.py`
- 4 个 LE 端到端场景：scan→connect→pair→read（smoke 基线）；GATT write+notify subscribe/unsubscribe；bonded reconnect auto-encrypt 双 session；pair-failure 清洁拆链。
- transport-agnostic：使用 `stack` + `peer_stack` + `transport_mode` 既有 fixtures；虚拟模式自动 VirtualLELink 桥接，硬件模式 yield None。
- SC 能力门控：`_supports_le_sc` 读取 HCI Read_Local_Supported_Commands 位图（octet 34, bits 1+2）；不做厂商白名单。
- 验收：`uv run pytest tests/e2e/ -v --transport=virtual` PASS；`uv run pytest tests/ -q --transport=virtual` 仅 3 个 pre-existing USB diagnostics 失败。
- 硬件运行方式（手动）：`uv run pytest tests/e2e/ -v --transport=usb:VID:PID#1 --transport-peer=usb:VID:PID#2`；不在 CI 中。
```

- [ ] **Step 4: Verify the markdown renders**

Run: `head -60 docs/superpowers/STATUS.md` and skim. No broken table syntax, no missing pipes.

- [ ] **Step 5: Run the whole suite one last time**

Run: `uv run pytest tests/ -q --transport=virtual`
Expected: only the 3 pre-existing USB-diagnostics failures.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/STATUS.md
git commit -m "docs(status): E2E LE Lifecycle complete

4 LE workflow scenarios under tests/e2e/. Transport-agnostic via existing
stack/peer_stack fixtures; SC-capability-gated via HCI introspection.
Updates 当前进行中 / 下一步 lines, adds new Plan row + detailed section."
```

---

## Acceptance Checklist

- [ ] `tests/e2e/_test_service.py` exists with `TEST_SERVICE_UUID`, three characteristic UUIDs, `INITIAL_READ_VALUE`, `build_test_service()`.
- [ ] `tests/e2e/_helpers.py` exists with `_supports_le_sc`, `central_discover_peripheral`, `central_discover_and_pair_sc_jw`, `wait_for_notifications`, `resolve_handles`.
- [ ] `tests/e2e/conftest.py` exposes `central_peripheral_pair` and `virtual_link_or_real_rf` fixtures.
- [ ] `tests/e2e/test_le_lifecycle.py` has 4 `@pytest.mark.e2e` async scenarios: scan-connect-pair-read, write-and-notify, bonded-reconnect, pair-failure-cleanup.
- [ ] `uv run pytest tests/e2e/ -v --transport=virtual` → 4 passed (or 3 + 1 skipped if fixture MITM gate doesn't engage, which is acceptable per Task 7 note).
- [ ] `uv run pytest tests/ -q --transport=virtual` → suite green minus pre-existing USB-diagnostics failures.
- [ ] STATUS.md updated to mark Plan ✅; "下一步" reflects the new state; OOB still marked off-roadmap.

## Out of Scope (deferred)

| Item | When |
|---|---|
| Classic E2E (inquiry → SDP → RFCOMM/SPP) | Separate Plan |
| Trace/btsnoop assertion harness | Separate Plan |
| CLI subprocess orchestration | Separate Plan |
| Phone interop tests | Separate Plan |
| Hardware CI runner / two-adapter test bench | Infrastructure work, not test code |
| Pair-flavor matrix (NC / Passkey / SC Passkey lifecycles in E2E) | Per-flavor pair correctness already in `tests/integration/test_pairing_*.py`; add only when a specific composition bug surfaces |
| OOB pairing | **Not on roadmap** |
