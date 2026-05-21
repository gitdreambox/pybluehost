# Classic Workflow E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four BR/EDR workflow-level E2E tests on top of the just-shipped `VirtualClassicLink` infrastructure: SDP browse, RFCOMM/SPP echo, bonded reconnect with auto-encrypt, and pair-failure clean teardown. Transport-agnostic so the same suite runs on virtual (CI) and hardware (manual, two USB adapters).

**Architecture:** Test-only Plan. New module `tests/e2e/_classic_test_service.py` registers a canonical SPP service on the peripheral. `tests/e2e/conftest.py` and `tests/e2e/_helpers.py` are extended with Classic-specific fixtures and helpers (mirroring the LE E2E shape). Four scenarios live in `tests/e2e/test_classic_lifecycle.py`. Tests 1, 2, 4 use the session-level `stack` + `peer_stack` fixtures via the new `classic_central_peripheral_pair` + `virtual_classic_link_or_real_rf` fixtures. Test 3 builds its own stacks to manage per-test `JsonBondStorage` paths across two sessions.

**Tech Stack:** Python 3.10+, pytest, pytest-asyncio. Reuses existing `Stack`, `VirtualClassicLink`, `SDPClient`, `SDPServer.register`, `make_rfcomm_service_record`, `SPPService`, `SPPClient`, `SPPConnection`, `RFCOMMManager`, `JsonBondStorage`, plus session fixtures `stack` / `peer_stack` / `transport_mode` from `tests/conftest.py`. No production-code changes anticipated; one small `VirtualClassicLink.AuthBridge` enhancement may be needed for the bonded-reconnect positive-Link_Key_Request_Reply path (called out in §Risk).

**Design spec:** [`docs/superpowers/specs/2026-05-21-classic-workflow-e2e-design.md`](../specs/2026-05-21-classic-workflow-e2e-design.md)

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Create | `tests/e2e/_classic_test_service.py` | `SPP_SERVER_CHANNEL`, `SPP_CLASS_UUID`, `SPP_SERVICE_NAME`; helpers to register an SPP service on a peripheral stack |
| Modify | `tests/e2e/_helpers.py` | Add `_supports_classic_ssp`, `classic_discover_peripheral`, `classic_discover_and_pair_jw` |
| Modify | `tests/e2e/conftest.py` | Add `classic_central_peripheral_pair` + `virtual_classic_link_or_real_rf` fixtures |
| Create | `tests/e2e/test_classic_lifecycle.py` | Four scenarios |
| Modify | `docs/superpowers/STATUS.md` | Mark Plan complete; add follow-up row |

---

## API surfaces this Plan uses (verified against the live codebase)

- `SDPServer.register(record: ServiceRecord) -> int` (pybluehost/classic/sdp.py:281).
- `make_rfcomm_service_record(service_uuid: int, channel: int, name: str) -> ServiceRecord` (sdp.py:234).
- `SPPService(rfcomm, sdp).register(channel=1, name=...)` and `.on_connection(handler)` (pybluehost/classic/spp.py:50-81).
- `SPPClient(rfcomm, sdp_client).connect(target) -> SPPConnection` (spp.py:88-114).
- `SPPConnection.send(bytes)` and `recv(max_bytes: int = 4096) -> bytes` (no timeout arg — wrap with `asyncio.wait_for`).
- `RFCOMMManager.connect(acl_handle, server_channel) -> RFCOMMChannel`, `.listen(server_channel, handler)` (rfcomm.py:395-414).
- `SDPClient(l2cap_channel).search_attributes(target, uuid, attr_ids) -> list[dict[int, DataElement]]` (sdp.py:495). **NB**: `SDPClient.search` raises `NotImplementedError` — use `search_attributes` or `find_rfcomm_channel` only.
- `SDPClient.find_rfcomm_channel(target, service_uuid) -> int | None` (sdp.py:544).
- `stack.connect_classic(target, timeout)`, `stack.authenticate_classic(handle, timeout)`, `stack.enable_classic_encryption(handle, timeout)`, `stack.gap.classic_connections.disconnect(handle)` — all verified working in `tests/integration/test_classic_e2e_smoke.py`.
- `stack._sdp` (SDPServer instance), `stack._rfcomm` (RFCOMMManager), `stack._l2cap` (L2CAPManager).
- `stack.gap.classic_discoverability.set_connectable(True)` / `set_discoverable(True)`.
- `stack.gap.classic_ssp` — the SSPManager; has `on_user_confirmation(handler)` setter (verified in the smoke test).
- `VirtualClassicLink` already supports the `Auth_Requested → Link_Key_Request → Link_Key_Request_Reply` path; whether the **positive** Link_Key_Request_Reply (with stored key) leads directly to `Auth_Complete` without the IO_Capability dance is verified in Task 6 and a small bridge fix is added there if needed.

---

## Task 1: Shared SPP test service module

**Files:**
- Create: `tests/e2e/_classic_test_service.py`

- [ ] **Step 1: Create the test service module**

Create `tests/e2e/_classic_test_service.py`:

```python
"""Canonical SPP test service for Classic E2E scenarios.

Registers an SPP service (UUID 0x1101) on RFCOMM channel SPP_SERVER_CHANNEL
on a Peripheral stack, with an echo handler that mirrors received bytes back
on the same channel.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from pybluehost.classic.sdp import make_rfcomm_service_record
from pybluehost.classic.spp import SPPConnection, SPPService

SPP_SERVER_CHANNEL = 1
SPP_CLASS_UUID = 0x1101  # Serial Port Profile
SPP_SERVICE_NAME = "PBH-E2E SPP"


def register_spp_echo_service(stack) -> SPPService:
    """Wire an SPP service with an echo handler on a Peripheral stack.

    Returns the SPPService instance. The caller is responsible for `await
    service.register(channel=SPP_SERVER_CHANNEL, name=SPP_SERVICE_NAME)` (this
    helper just builds the wiring).
    """
    service = SPPService(rfcomm=stack._rfcomm, sdp=stack._sdp)

    async def _echo_handler(conn: SPPConnection) -> None:
        try:
            while True:
                data = await conn.recv()
                if not data:
                    break
                await conn.send(data)
        except asyncio.CancelledError:
            return
        except Exception:
            return

    service.on_connection(_echo_handler)
    return service
```

- [ ] **Step 2: Write a basic sanity test in `tests/e2e/test_classic_lifecycle.py`**

Create `tests/e2e/test_classic_lifecycle.py`:

```python
"""End-to-end BR/EDR (Classic) workflow scenarios."""
from __future__ import annotations


def test_classic_test_service_constants():
    """build helpers + constants are importable and self-consistent."""
    from tests.e2e._classic_test_service import (
        SPP_SERVER_CHANNEL,
        SPP_CLASS_UUID,
        SPP_SERVICE_NAME,
        register_spp_echo_service,
    )
    assert SPP_SERVER_CHANNEL == 1
    assert SPP_CLASS_UUID == 0x1101
    assert SPP_SERVICE_NAME == "PBH-E2E SPP"
    assert callable(register_spp_echo_service)
```

- [ ] **Step 3: Run the test**

```
uv run pytest tests/e2e/test_classic_lifecycle.py -v
```
Expected: 1 PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/_classic_test_service.py tests/e2e/test_classic_lifecycle.py
git commit -m "test(e2e): canonical SPP test service for Classic E2E scenarios

Sub-Plan Classic Workflow E2E Task 1. Adds the SPP_SERVER_CHANNEL +
SPP_CLASS_UUID + SPP_SERVICE_NAME constants and a register_spp_echo_service
helper that wires SPPService on a Peripheral stack with an echo
handler. Scenario tests in subsequent tasks register and use this service."
```

---

## Task 2: Helpers (`_helpers.py` additions)

**Files:**
- Modify: `tests/e2e/_helpers.py`
- Test: `tests/e2e/test_classic_lifecycle.py` (append)

- [ ] **Step 1: Append failing tests**

Append to `tests/e2e/test_classic_lifecycle.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_supports_classic_ssp_virtual_short_circuits_true():
    from pybluehost.stack import Stack
    from pybluehost.core.address import BDAddress
    from tests.e2e._helpers import _supports_classic_ssp

    stack = await Stack.virtual(address=BDAddress.from_string("0A:0A:0A:0A:0A:0A"))
    try:
        assert _supports_classic_ssp(stack) is True
    finally:
        await stack.close()
```

- [ ] **Step 2: Run failing test**

```
uv run pytest tests/e2e/test_classic_lifecycle.py::test_supports_classic_ssp_virtual_short_circuits_true -v
```
Expected: FAIL — `_supports_classic_ssp` not defined.

- [ ] **Step 3: Add the helper functions**

Append to `tests/e2e/_helpers.py`:

```python
# ---------------------------------------------------------------------------
# Classic (BR/EDR) helpers
# ---------------------------------------------------------------------------

def _supports_classic_ssp(stack) -> bool:
    """True iff the controller advertises BR/EDR SSP support.

    Virtual mode short-circuits True. Hardware adapters consult the HCI
    Read_Local_Supported_Commands bitmap for SSP opcodes (IO_Capability_Request_Reply
    at octet 32 bit 5).
    """
    if getattr(stack, "_virtual_controller", None) is not None:
        return True
    hci = getattr(stack, "_hci", None)
    if hci is None:
        return False
    caps = getattr(hci, "supported_commands", None)
    if caps is None:
        return False
    bitmap = getattr(caps, "bitmap", None) or caps
    try:
        # IO_Capability_Request_Reply is at octet 32 bit 5 per Core Spec 5.4
        # Vol 4 Part E §6.27.
        return bool(bitmap[32] & (1 << 5))
    except (IndexError, TypeError):
        return False


async def classic_discover_peripheral(
    stack_c, expected_addr, timeout: float = 3.0,
) -> None:
    """Run inquiry on stack_c, wait until expected_addr appears in a result,
    then cancel.

    Mirrors the LE-side central_discover_peripheral but uses ClassicDiscovery."""
    import asyncio

    seen_event = asyncio.Event()

    def _on_result(info):
        # ClassicDiscovery results expose .address (or .bd_addr depending on
        # the dataclass spelling). Use a defensive check.
        addr = getattr(info, "address", None) or getattr(info, "bd_addr", None)
        if addr == expected_addr:
            seen_event.set()

    stack_c.gap.classic_discovery.on_result(_on_result)
    await stack_c.gap.classic_discovery.start()
    try:
        await asyncio.wait_for(seen_event.wait(), timeout=timeout)
    finally:
        if hasattr(stack_c.gap.classic_discovery, "cancel"):
            try:
                await stack_c.gap.classic_discovery.cancel()
            except Exception:
                pass


async def classic_discover_and_pair_jw(
    stack_c, peripheral_addr, *,
    scan_timeout: float = 3.0, pair_timeout: float = 3.0,
) -> int:
    """Composition: discover → connect_classic → authenticate_classic.

    Returns the connection handle on success.
    """
    await classic_discover_peripheral(stack_c, peripheral_addr, timeout=scan_timeout)
    handle = await stack_c.connect_classic(peripheral_addr, timeout=scan_timeout)
    await stack_c.authenticate_classic(handle, timeout=pair_timeout)
    return handle
```

- [ ] **Step 4: Verify field name (`.address` vs `.bd_addr`)**

Run: `grep -n "address\|bd_addr" pybluehost/classic/gap.py | grep -i "DeviceInfo\|InquiryResult" | head`

Adjust the `_on_result` handler if the actual field name differs. The defensive `getattr(info, ..., None) or getattr(info, ..., None)` pattern handles either spelling.

- [ ] **Step 5: Run the test**

```
uv run pytest tests/e2e/test_classic_lifecycle.py::test_supports_classic_ssp_virtual_short_circuits_true -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/e2e/_helpers.py tests/e2e/test_classic_lifecycle.py
git commit -m "test(e2e): Classic helpers — capability gate + discover + pair composition

Sub-Plan Classic Workflow E2E Task 2. Adds _supports_classic_ssp (HCI
Read_Local_Supported_Commands bitmap introspection at octet 32 bit 5;
virtual stack short-circuits True since host does SSP), classic_discover_peripheral
(inquiry + match address), classic_discover_and_pair_jw (discovery → connect →
authenticate composition). All transport-agnostic."
```

---

## Task 3: Fixtures

**Files:**
- Modify: `tests/e2e/conftest.py`
- Test: `tests/e2e/test_classic_lifecycle.py` (append)

- [ ] **Step 1: Append failing test**

```python
@pytest.mark.asyncio
async def test_classic_fixtures_load_and_register_service(
    classic_central_peripheral_pair, virtual_classic_link_or_real_rf,
):
    """central_peripheral_pair registers SPP service on peripheral; bridge attaches in virtual mode."""
    stack_c, stack_p = classic_central_peripheral_pair
    # SDP server has at least one registered record
    assert len(stack_p._sdp._records) >= 1
    # Peripheral is connectable + discoverable per the fixture
    assert stack_p._virtual_controller._inquiry_scan is True
    assert stack_p._virtual_controller._page_scan is True
```

- [ ] **Step 2: Run failing test**

```
uv run pytest tests/e2e/test_classic_lifecycle.py::test_classic_fixtures_load_and_register_service -v --transport=virtual
```
Expected: FAIL — fixtures undefined.

- [ ] **Step 3: Add fixtures to `tests/e2e/conftest.py`**

Append to `tests/e2e/conftest.py`:

```python
from pybluehost.hci.virtual_classic_link import VirtualClassicLink

from tests.e2e._classic_test_service import (
    SPP_SERVER_CHANNEL,
    SPP_SERVICE_NAME,
    register_spp_echo_service,
)


@pytest_asyncio.fixture
async def classic_central_peripheral_pair(stack, peer_stack):
    """Register SPP service on Peripheral + set connectable+discoverable.

    Yields (stack_central, stack_peripheral) ready for Classic workflow scenarios.
    """
    service = register_spp_echo_service(peer_stack)
    await service.register(channel=SPP_SERVER_CHANNEL, name=SPP_SERVICE_NAME)
    await peer_stack.gap.classic_discoverability.set_connectable(True)
    await peer_stack.gap.classic_discoverability.set_discoverable(True)
    yield stack, peer_stack


@pytest_asyncio.fixture
async def virtual_classic_link_or_real_rf(classic_central_peripheral_pair, transport_mode):
    """Virtual: build + attach a VirtualClassicLink. Hardware: yield None."""
    stack_c, stack_p = classic_central_peripheral_pair
    if transport_mode == "virtual":
        link = VirtualClassicLink(
            central=stack_c._virtual_controller,
            peripheral=stack_p._virtual_controller,
            central_address=stack_c._local_address,
            peripheral_address=stack_p._local_address,
            page_timeout_seconds=0.5,
        )
        link.attach()
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

- [ ] **Step 4: Verify `set_connectable` / `set_discoverable` exist**

Run: `grep -n "set_connectable\|set_discoverable" pybluehost/classic/gap.py`

The VirtualClassicLink smoke test already uses both — they exist. If grep returns nothing, fall back to direct HCI writes via `stack_p._hci.send_command(HCI_Write_Scan_Enable_Command(scan_enable=0x03))` or similar.

- [ ] **Step 5: Run test**

```
uv run pytest tests/e2e/test_classic_lifecycle.py::test_classic_fixtures_load_and_register_service -v --transport=virtual
```
Expected: PASS.

```
uv run pytest tests/e2e/ -q --transport=virtual
```
Expected: no regressions (existing LE E2E tests still pass).

- [ ] **Step 6: Commit**

```bash
git add tests/e2e/conftest.py tests/e2e/test_classic_lifecycle.py
git commit -m "test(e2e): Classic fixtures — classic_central_peripheral_pair + bridge

Sub-Plan Classic Workflow E2E Task 3. classic_central_peripheral_pair
registers the canonical SPP service on the Peripheral (echo handler) +
sets connectable + discoverable. virtual_classic_link_or_real_rf bridges
two virtual controllers via VirtualClassicLink in virtual mode and yields
None in hardware mode (real RF connects them). Composes with the existing
session-level stack / peer_stack / transport_mode fixtures."
```

---

## Task 4: Test 1 — SDP browse

**Files:**
- Modify: `tests/e2e/test_classic_lifecycle.py` (append)

- [ ] **Step 1: Append the failing test**

```python
import contextlib

from pybluehost.core.address import BDAddress


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_classic_sdp_browse(
    classic_central_peripheral_pair, virtual_classic_link_or_real_rf,
):
    """Connect + SSP JW pair, then SDP search-attributes for the SPP record.

    Asserts the registered SPP service is found and the RFCOMM channel
    number embedded in ProtocolDescriptorList matches SPP_SERVER_CHANNEL.
    """
    import asyncio
    from pybluehost.classic.sdp import SDPClient
    from pybluehost.l2cap.constants import PSM_SDP

    from tests.e2e._classic_test_service import (
        SPP_CLASS_UUID, SPP_SERVER_CHANNEL,
    )
    from tests.e2e._helpers import (
        _supports_classic_ssp, classic_discover_and_pair_jw,
    )

    stack_c, stack_p = classic_central_peripheral_pair
    if not _supports_classic_ssp(stack_c):
        pytest.skip("adapter does not support BR/EDR SSP")

    handle = None
    try:
        handle = await classic_discover_and_pair_jw(
            stack_c, stack_p._local_address,
        )

        # Open an L2CAP channel on the SDP PSM (0x0001) to feed SDPClient.
        l2cap_channel = await stack_c._l2cap.open_classic_channel(
            handle, psm=PSM_SDP,
        )
        client = SDPClient(l2cap=l2cap_channel)

        # find_rfcomm_channel uses search_attributes under the hood. If the
        # bridge + SDP server are wired correctly, it returns
        # SPP_SERVER_CHANNEL.
        channel = await client.find_rfcomm_channel(
            target=handle, service_uuid=SPP_CLASS_UUID,
        )
        assert channel == SPP_SERVER_CHANNEL, (
            f"find_rfcomm_channel returned {channel!r}, "
            f"expected {SPP_SERVER_CHANNEL}"
        )
    finally:
        if handle is not None:
            with contextlib.suppress(Exception):
                await stack_c.gap.classic_connections.disconnect(handle)
```

**Note on `stack_c._l2cap.open_classic_channel`**: the exact method name may differ. Grep `pybluehost/l2cap/manager.py` for the public method that opens a classic L2CAP channel on a given PSM. If only `_open_classic_channel` exists or if the API requires a different invocation, adjust.

- [ ] **Step 2: Run the test**

```
uv run pytest tests/e2e/test_classic_lifecycle.py::test_e2e_classic_sdp_browse -v --transport=virtual
```

Iterate on failures. Likely issues:
- **`open_classic_channel` not found** — grep `pybluehost/l2cap/manager.py` for the actual method. Use whatever public API is exposed (may be `listen_classic_channel` + `connect_classic_channel`, or `connect(handle, psm)`).
- **SDP request times out** — verify the bridge routes ACL between the two stacks on the established handle. Verify the SDP server on the peripheral side received the request (set a logger.debug on `SDPServer._handle_search_attribute`).
- **`find_rfcomm_channel` returns `None`** — the SDP server didn't find a record matching SPP_CLASS_UUID. Verify the service was registered before the SDP request: `stack_p._sdp._records` should contain at least one record.

You may make test-side adjustments. **Do not modify production code unless a production bug is genuinely blocking.**

- [ ] **Step 3: Run full e2e module**

```
uv run pytest tests/e2e/ -v --transport=virtual
```
Expected: no regressions.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_classic_lifecycle.py
git commit -m "test(e2e): Classic SDP browse scenario (test 1/4)

Sub-Plan Classic Workflow E2E Task 4. Central connects to peripheral via
classic_discover_and_pair_jw, opens an L2CAP channel on PSM_SDP, constructs
an SDPClient, queries find_rfcomm_channel(SPP_CLASS_UUID), and verifies the
returned channel matches the SPP_SERVER_CHANNEL the fixture registered.
SC capability-gated via _supports_classic_ssp."
```

---

## Task 5: Test 2 — RFCOMM/SPP echo

**Files:**
- Modify: `tests/e2e/test_classic_lifecycle.py` (append)

- [ ] **Step 1: Append the failing test**

```python
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_classic_rfcomm_spp_echo(
    classic_central_peripheral_pair, virtual_classic_link_or_real_rf,
):
    """Open RFCOMM/SPP channel to the peripheral's echo handler; send two
    messages; verify both are echoed back."""
    import asyncio

    from pybluehost.classic.sdp import SDPClient
    from pybluehost.classic.spp import SPPClient
    from pybluehost.l2cap.constants import PSM_SDP

    from tests.e2e._helpers import (
        _supports_classic_ssp, classic_discover_and_pair_jw,
    )

    stack_c, stack_p = classic_central_peripheral_pair
    if not _supports_classic_ssp(stack_c):
        pytest.skip("adapter does not support BR/EDR SSP")

    handle = None
    spp_conn = None
    try:
        handle = await classic_discover_and_pair_jw(
            stack_c, stack_p._local_address,
        )

        # SDP client needs an L2CAP channel on PSM_SDP for SPPClient to do
        # service discovery internally.
        sdp_chan = await stack_c._l2cap.open_classic_channel(handle, psm=PSM_SDP)
        sdp_client = SDPClient(l2cap=sdp_chan)
        spp_client = SPPClient(rfcomm=stack_c._rfcomm, sdp_client=sdp_client)

        spp_conn = await spp_client.connect(target=handle)

        # First echo
        await spp_conn.send(b"hello classic\n")
        echoed = await asyncio.wait_for(spp_conn.recv(), timeout=1.0)
        assert echoed == b"hello classic\n"

        # Second echo
        await spp_conn.send(b"second line\n")
        echoed2 = await asyncio.wait_for(spp_conn.recv(), timeout=1.0)
        assert echoed2 == b"second line\n"

    finally:
        if spp_conn is not None:
            with contextlib.suppress(Exception):
                await spp_conn.close()
        if handle is not None:
            with contextlib.suppress(Exception):
                await stack_c.gap.classic_connections.disconnect(handle)
```

- [ ] **Step 2: Run the test**

```
uv run pytest tests/e2e/test_classic_lifecycle.py::test_e2e_classic_rfcomm_spp_echo -v --transport=virtual
```

Iterate on failures. Likely issues:
- **`SPPClient.connect` raises "SPP service not found"** — the SDP lookup didn't find a match. Means Task 4's `find_rfcomm_channel` is the same SDP path; if Task 4 passes but this fails, check whether SDPClient was constructed with the right L2CAP channel.
- **RFCOMM SABM never replied with UA** — the RFCOMMManager.listen on the peripheral didn't see the SABM. Check that the peripheral has the RFCOMM listener attached via `SPPService.register()` (the fixture does this).
- **`spp_conn.recv()` times out after send** — echo handler isn't receiving the data or isn't echoing. Check the handler in `_classic_test_service.py` is async-safe and the SPPConnection wires `on_data → _recv_queue.put_nowait` correctly.
- **Number_Of_Completed_Packets exhaustion** — if many ACL frames flow, the bridge needs to track completion. The VirtualController already auto-emits `Number_Of_Completed_Packets` (per the SC Passkey fix). Should work for ~10-20 frames the echo test sends.

- [ ] **Step 3: Run full e2e module**

```
uv run pytest tests/e2e/ -v --transport=virtual
```
Expected: no regressions.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_classic_lifecycle.py
git commit -m "test(e2e): Classic RFCOMM/SPP echo scenario (test 2/4)

Sub-Plan Classic Workflow E2E Task 5. After SSP JW pair, opens an SDP
L2CAP channel and uses it for SPPClient's SDP lookup; SPPClient.connect
opens RFCOMM channel to the peripheral's registered SPP server (echo
handler from Task 1's _classic_test_service module); send 'hello classic\\n'
+ 'second line\\n', verify both are echoed back via SPPConnection.recv()
wrapped in asyncio.wait_for. Exercises RFCOMM SABM/UA + UIH frame
bidirectional flow + DISC teardown."
```

---

## Task 6: Test 3 — Bonded reconnect with auto-encrypt

**Files:**
- Modify: `tests/e2e/test_classic_lifecycle.py` (append)
- Possibly modify: `pybluehost/hci/virtual_classic_link.py` (Risk #2 from spec — only if needed)

This test does NOT use the `classic_central_peripheral_pair` fixture. It manages its own two-session lifecycle so each session opens fresh stacks pointing at the same on-disk bond storage.

**Important**: the existing `VirtualClassicLink.AuthBridge` was designed for the no-stored-key path. Bonded reconnect uses the positive `HCI_Link_Key_Request_Reply` (with the stored 16-byte link key). Verify whether the existing bridge emits `Auth_Complete(status=0)` directly on positive Link_Key_Request_Reply, OR whether it incorrectly proceeds with the IO_Capability flow. If the latter, a small bridge enhancement is in scope: in `_intercept`'s `HCI_LINK_KEY_REQUEST_REPLY` branch, distinguish positive (`raw_params` includes 16-byte key beyond the 6-byte BD_ADDR) from negative (just BD_ADDR), and on positive emit `Auth_Complete(status=0, handle)` to initiator + skip the IO_Capability dispatch.

- [ ] **Step 1: Inspect the existing bridge AuthBridge behavior**

Read `pybluehost/hci/virtual_classic_link.py` and locate the `HCI_LINK_KEY_REQUEST_REPLY` branch in `_intercept`. Note: the bridge currently routes all `HCI_LINK_KEY_REQUEST_REPLY` and `HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY` through `_auth_emit_io_cap_requests(...)`, treating both identically. This is wrong for bonded reconnect.

- [ ] **Step 2: Append failing test**

```python
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_classic_bonded_reconnect_auto_encrypt(
    tmp_path, selected_transport_spec, selected_peer_spec, transport_mode,
):
    """Two-session lifecycle. Session 1 pairs (SSP JW) → bond persisted on
    disk. Session 2 reopens fresh stacks at the same storage paths; the
    Link_Key_Request handler on the central side replies with the stored
    key; the bridge recognizes this positive-reply path and emits
    Auth_Complete directly; no IO_Capability flow; encryption succeeds;
    SDP browse confirms the link is usable."""
    import asyncio
    import contextlib

    from pybluehost.ble.security import SecurityConfig
    from pybluehost.ble.smp import JsonBondStorage
    from pybluehost.classic.sdp import SDPClient
    from pybluehost.core.address import BDAddress
    from pybluehost.hci.virtual_classic_link import VirtualClassicLink
    from pybluehost.l2cap.constants import PSM_SDP
    from pybluehost.stack import Stack, StackConfig

    from tests.e2e._classic_test_service import (
        SPP_CLASS_UUID, SPP_SERVER_CHANNEL, SPP_SERVICE_NAME,
        register_spp_echo_service,
    )
    from tests.e2e._helpers import (
        _supports_classic_ssp, classic_discover_and_pair_jw,
        classic_discover_peripheral,
    )

    if transport_mode != "virtual":
        pytest.skip(
            "hardware mode: build_stack_from_spec doesn't accept config= yet"
        )

    central_addr = BDAddress.from_string("0A:0A:0A:0A:0A:0A")
    peripheral_addr = BDAddress.from_string("0B:0B:0B:0B:0B:0B")
    bonds_c_path = tmp_path / "bonds_c.json"
    bonds_p_path = tmp_path / "bonds_p.json"

    async def _open_pair():
        cfg_c = StackConfig(
            bond_storage=JsonBondStorage(bonds_c_path),
            security=SecurityConfig(enable_secure_connections=False),
        )
        cfg_p = StackConfig(
            bond_storage=JsonBondStorage(bonds_p_path),
            security=SecurityConfig(enable_secure_connections=False),
        )
        stack_c = await Stack.virtual(config=cfg_c, address=central_addr)
        stack_p = await Stack.virtual(config=cfg_p, address=peripheral_addr)
        # Register SPP service on the peripheral.
        service = register_spp_echo_service(stack_p)
        await service.register(channel=SPP_SERVER_CHANNEL, name=SPP_SERVICE_NAME)
        await stack_p.gap.classic_discoverability.set_connectable(True)
        await stack_p.gap.classic_discoverability.set_discoverable(True)
        link = VirtualClassicLink(
            central=stack_c._virtual_controller,
            peripheral=stack_p._virtual_controller,
            central_address=central_addr,
            peripheral_address=peripheral_addr,
            page_timeout_seconds=0.5,
        )
        link.attach()
        return stack_c, stack_p, link

    async def _close_pair(stack_c, stack_p, link):
        with contextlib.suppress(Exception):
            await link.disconnect()
        with contextlib.suppress(Exception):
            await stack_c.close()
        with contextlib.suppress(Exception):
            await stack_p.close()

    # ===== Session 1 =====
    stack_c, stack_p, link = await _open_pair()
    if not _supports_classic_ssp(stack_c):
        await _close_pair(stack_c, stack_p, link)
        pytest.skip("adapter does not support BR/EDR SSP")

    handle = None
    try:
        handle = await classic_discover_and_pair_jw(
            stack_c, peripheral_addr,
        )
        bond_c = await JsonBondStorage(bonds_c_path).load_bond(peripheral_addr)
        assert bond_c is not None, "central bond not persisted after pair"
        assert bond_c.link_key_type == 0x05, (
            f"expected Combination_Key (0x05), got {bond_c.link_key_type!r}"
        )
        with contextlib.suppress(Exception):
            await stack_c.gap.classic_connections.disconnect(handle)
    finally:
        await _close_pair(stack_c, stack_p, link)

    # ===== Session 2 =====
    stack_c, stack_p, link = await _open_pair()
    handle = None
    try:
        await classic_discover_peripheral(stack_c, peripheral_addr, timeout=3.0)
        handle = await stack_c.connect_classic(peripheral_addr, timeout=3.0)
        # Authenticate using the stored bond. The bridge recognizes the
        # positive Link_Key_Request_Reply and emits Auth_Complete directly.
        await stack_c.authenticate_classic(handle, timeout=3.0)
        await stack_c.enable_classic_encryption(handle, timeout=2.0)

        # Verify the encrypted link works for an SDP query.
        sdp_chan = await stack_c._l2cap.open_classic_channel(handle, psm=PSM_SDP)
        sdp_client = SDPClient(l2cap=sdp_chan)
        channel = await sdp_client.find_rfcomm_channel(
            target=handle, service_uuid=SPP_CLASS_UUID,
        )
        assert channel == SPP_SERVER_CHANNEL
    finally:
        if handle is not None:
            with contextlib.suppress(Exception):
                await stack_c.gap.classic_connections.disconnect(handle)
        await _close_pair(stack_c, stack_p, link)
```

- [ ] **Step 3: Run the test**

```
uv run pytest tests/e2e/test_classic_lifecycle.py::test_e2e_classic_bonded_reconnect_auto_encrypt -v --transport=virtual
```

Expected on first run: Session 2 fails because the bridge incorrectly treats positive Link_Key_Request_Reply the same as negative-reply (goes through IO_Capability flow, which won't terminate because the central never expects another User_Confirmation_Request).

- [ ] **Step 4: Patch the bridge (if needed)**

If Step 3 confirms the bridge needs the fix, modify `pybluehost/hci/virtual_classic_link.py`. Locate the `HCI_LINK_KEY_REQUEST_REPLY` branch in `_intercept`:

```python
if opcode in (HCI_LINK_KEY_REQUEST_REPLY, HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY):
    peer_addr_bytes = raw_params[0:6]
    asyncio.create_task(
        self._auth_emit_io_cap_requests(controller, peer_addr_bytes)
    )
    return self._command_complete(opcode, b"\x00" + peer_addr_bytes)
```

Replace with:

```python
if opcode == HCI_LINK_KEY_REQUEST_REPLY:
    # Positive reply: caller has a stored link key. Emit Auth_Complete
    # directly to the initiator; skip the IO_Capability dance.
    peer_addr_bytes = raw_params[0:6]
    # Find the connection entry where `controller` is the initiator of
    # the auth-requested handle.
    asyncio.create_task(
        self._auth_emit_authentication_complete(controller, status=0)
    )
    return self._command_complete(opcode, b"\x00" + peer_addr_bytes)
if opcode == HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY:
    # No stored key: proceed to IO_Capability dispatch.
    peer_addr_bytes = raw_params[0:6]
    asyncio.create_task(
        self._auth_emit_io_cap_requests(controller, peer_addr_bytes)
    )
    return self._command_complete(opcode, b"\x00" + peer_addr_bytes)
```

Add the helper:

```python
async def _auth_emit_authentication_complete(
    self, initiator: VirtualController, status: int,
) -> None:
    """Emit Auth_Complete to initiator (used after positive Link_Key_Request_Reply
    in bonded reconnect)."""
    # Find the most-recent CONNECTED handle for initiator.
    entry = next(
        (e for e in self._handles.values()
         if e.initiator is initiator and e.state == _ConnState.CONNECTED),
        None,
    )
    if entry is None:
        return
    body = bytes([status]) + struct.pack("<H", entry.handle)
    event = HCIEvent(
        event_code=int(EventCode.AUTH_COMPLETE), parameters=body,
    )
    await initiator._send_event_to_host(event)
```

- [ ] **Step 5: Run the test again**

```
uv run pytest tests/e2e/test_classic_lifecycle.py::test_e2e_classic_bonded_reconnect_auto_encrypt -v --transport=virtual
```
Expected: PASS.

Also re-run the existing bridge tests to make sure the change didn't break anything:

```
uv run pytest tests/integration/test_virtual_classic_link.py tests/integration/test_classic_e2e_smoke.py -v --transport=virtual
```
Expected: all PASS (the existing smoke test exercises the negative-reply path, which is unchanged).

- [ ] **Step 6: Commit**

```bash
git add tests/e2e/test_classic_lifecycle.py pybluehost/hci/virtual_classic_link.py
git commit -m "test(e2e): Classic bonded reconnect with auto-encrypt (test 3/4)

Sub-Plan Classic Workflow E2E Task 6. Two-session lifecycle sharing on-disk
JsonBondStorage paths.
- Session 1: classic_discover_and_pair_jw → SSPManager persists BondInfo
  with link_key_type=0x05 → disconnect, close both stacks.
- Session 2: reopen fresh stacks at the same storage paths; central
  connects; SSPManager's Link_Key_Request handler replies with the stored
  16-byte key; bridge's AuthBridge recognizes positive Link_Key_Request_Reply
  and emits Auth_Complete(status=0) to initiator directly without
  IO_Capability dispatch; encryption enabled; SDP browse confirms the
  encrypted link is usable.

Includes a small VirtualClassicLink fix: HCI_LINK_KEY_REQUEST_REPLY (positive)
and HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY now take distinct paths — positive
emits Auth_Complete via the new _auth_emit_authentication_complete helper;
negative proceeds to IO_Capability as before."
```

Note: if Step 3 showed the bridge already works correctly (the helper is not needed), include only the test in the commit and adjust the message accordingly.

---

## Task 7: Test 4 — Pair-failure clean teardown

**Files:**
- Modify: `tests/e2e/test_classic_lifecycle.py` (append)

- [ ] **Step 1: Append the failing test**

```python
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_classic_pair_failure_disconnects_cleanly(
    classic_central_peripheral_pair, virtual_classic_link_or_real_rf,
):
    """Inject a Peripheral SSP handler that rejects User_Confirmation →
    stack.authenticate_classic() raises → connection disconnect + stack
    teardown both complete within 2s. Regression guard against leaked
    auth-completion futures.
    """
    import asyncio
    import contextlib

    from tests.e2e._helpers import (
        _supports_classic_ssp, classic_discover_peripheral,
    )

    stack_c, stack_p = classic_central_peripheral_pair
    if not _supports_classic_ssp(stack_c):
        pytest.skip("adapter does not support BR/EDR SSP")

    # Inject rejecting User_Confirmation handler on the peripheral.
    stack_p.gap.classic_ssp.on_user_confirmation(
        lambda addr, numeric: False,
    )

    handle = None
    try:
        await classic_discover_peripheral(
            stack_c, stack_p._local_address, timeout=3.0,
        )
        handle = await stack_c.connect_classic(
            stack_p._local_address, timeout=3.0,
        )

        # Authenticate must raise on Auth_Complete with non-zero status.
        # Adjust the match= regex after first run if needed.
        with pytest.raises(Exception, match=r"(authentication|Auth_Complete|SSP|status).*"):
            await stack_c.authenticate_classic(handle, timeout=3.0)

        # Critical: cleanup completes within 2s.
        await asyncio.wait_for(
            stack_c.gap.classic_connections.disconnect(handle), timeout=2.0,
        )
    finally:
        # Fixture teardown closes both stacks within 2s (regression guard).
        pass
```

- [ ] **Step 2: Run the test**

```
uv run pytest tests/e2e/test_classic_lifecycle.py::test_e2e_classic_pair_failure_disconnects_cleanly -v --transport=virtual
```

Common debug points:
- **`authenticate_classic` doesn't raise** — `Auth_Complete(status=0x05)` may surface differently. Check whether `stack._classic_auth_waiters` propagates the error status. If not, the test can capture the event directly and assert on status.
- **`stack_p.gap.classic_ssp.on_user_confirmation` signature** — verify with `grep -n "def on_user_confirmation" pybluehost/classic/gap.py`. The handler signature in the smoke test is `(BDAddress, int) -> bool`; same here.
- **Teardown hangs** — if `stack.close()` doesn't return in 2s after the failed pair, that's a real leak. Capture it as DONE_WITH_CONCERNS rather than skipping the test.

- [ ] **Step 3: Adjust the `pytest.raises(match=...)` regex if needed**

Based on the actual exception message, narrow the regex to the actual text.

- [ ] **Step 4: Run full e2e module**

```
uv run pytest tests/e2e/ -v --transport=virtual
```
Expected: 4 new tests PASS (+ existing tests).

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/test_classic_lifecycle.py
git commit -m "test(e2e): Classic pair-failure clean teardown (test 4/4)

Sub-Plan Classic Workflow E2E Task 7. Peripheral SSP handler rejects
User_Confirmation → stack_c.authenticate_classic raises with the
Auth_Complete error status → disconnect + stack.close() both complete
within 2s. Regression guard for the leaked-auth-future class of bugs.
Skips on hardware where session-fixture SecurityConfig may differ."
```

---

## Task 8: STATUS.md update

**Files:**
- Modify: `docs/superpowers/STATUS.md`

**Important**: Use the absolute worktree-path for the Edit tool (`/home/ubuntu/code/pybluehost/.claude/worktrees/<worktree-name>/docs/superpowers/STATUS.md`) to avoid the main-repo CWD issue seen in earlier sessions.

- [ ] **Step 1: Update top-of-file**

Update the "**当前进行中**" / "**下一步**" lines:

```
**当前进行中**：Classic Workflow E2E — ✅ 完成
**下一步**：断线重连闭环 / 真机 E2E 验证（同套测试用 --transport=usb）
**不在路线图**：SMP Sub-Plan 3c (OOB) — 暂无计划支持
```

- [ ] **Step 2: Add row to Plan-progress table**

Append after the VirtualClassicLink row:

```
| Classic Workflow E2E | tests/e2e/ Classic 4 个端到端场景：SDP browse + RFCOMM/SPP echo + bonded reconnect 双 session + pair-failure 清洁拆链；transport-agnostic（virtual 自动跑 / hardware 用 --transport=usb 手动跑） | ✅ 完成 | [2026-05-21-classic-workflow-e2e](plans/2026-05-21-classic-workflow-e2e.md) | `tests/e2e/{_classic_test_service,_helpers,conftest,test_classic_lifecycle}.py`, `pybluehost/hci/virtual_classic_link.py` |
```

Increment "总计：N 个 Plan" line by one.

- [ ] **Step 3: Add detailed-progress section**

Append after the VirtualClassicLink detailed section. Aim for ~12 lines.

```markdown
### ✅ Classic Workflow E2E
- 完成时间：2026-05-21
- Plan 文档：[2026-05-21-classic-workflow-e2e.md](plans/2026-05-21-classic-workflow-e2e.md)
- 提交范围：`tests/e2e/_classic_test_service.py`、`tests/e2e/_helpers.py`、`tests/e2e/conftest.py`、`tests/e2e/test_classic_lifecycle.py`；+ `pybluehost/hci/virtual_classic_link.py` 小修（bonded reconnect 路径）
- 4 个 BR/EDR 端到端场景（`@pytest.mark.e2e`）：
  - `test_e2e_classic_sdp_browse`：connect → SSP JW → SDP `find_rfcomm_channel(0x1101)` 返回 SPP_SERVER_CHANNEL。
  - `test_e2e_classic_rfcomm_spp_echo`：connect → SSP JW → SPPClient.connect → 双向回显两条消息。
  - `test_e2e_classic_bonded_reconnect_auto_encrypt`：双 session。Session 1 配对 + bond.link_key_type=0x05 持久化；Session 2 重连 → 桥接识别 positive Link_Key_Request_Reply 直接发 Auth_Complete → 加密 → SDP 验证可用。
  - `test_e2e_classic_pair_failure_disconnects_cleanly`：peripheral 拒绝 User_Confirmation → `stack.authenticate_classic` 抛错 → 双端 `stack.close()` ≤ 2s 完成。
- transport-agnostic：用 `classic_central_peripheral_pair` + `virtual_classic_link_or_real_rf` fixtures（基于 `tests/conftest.py` 的 `stack`/`peer_stack`/`transport_mode`）。
- Bridge fix：`VirtualClassicLink._intercept` 将 `HCI_LINK_KEY_REQUEST_REPLY`（positive，含 16-byte 链接密钥）与 `HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY` 分两条路径——positive 直接发 `Auth_Complete(0)` 给 initiator；negative 维持原 IO_Capability 派发。
- 验收：`uv run pytest tests/e2e/test_classic_lifecycle.py -v --transport=virtual` PASS（4/4，含 Test 3 双 session）；`uv run pytest tests/ -q --transport=virtual` 仅 3 个 pre-existing USB diagnostics 失败。
- 硬件运行方式（手动，未在 CI）：`uv run pytest tests/e2e/test_classic_lifecycle.py -v --transport=usb:VID:PID#1 --transport-peer=usb:VID:PID#2`；Test 3 在硬件模式 skip 直到 `build_stack_from_spec` 增加 `config=` 参数。
- 不在范围（按设计推迟）：BR/EDR SC via bridge（key_type=0x07）= 后续 Plan；NC/Passkey BR/EDR 变体；A2DP/HFP/SCO；多通道 RFCOMM；手机互联。
```

- [ ] **Step 4: Verify markdown renders cleanly**

Read the file head to skim. No broken table syntax, no missing pipes.

- [ ] **Step 5: Final full-suite run**

```
uv run pytest tests/ -q --transport=virtual
```
Expected: only the 3 pre-existing USB-diagnostics failures.

Verbatim report the pass/fail count.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/STATUS.md
git commit -m "docs(status): Classic Workflow E2E complete

4 BR/EDR workflow scenarios under tests/e2e/test_classic_lifecycle.py on
top of VirtualClassicLink. Documents the small bridge fix for the bonded
reconnect positive-Link_Key_Request_Reply path."
```

---

## Acceptance Checklist

- [ ] `tests/e2e/_classic_test_service.py` exists with the documented surfaces (constants + `register_spp_echo_service`).
- [ ] `tests/e2e/_helpers.py` adds `_supports_classic_ssp`, `classic_discover_peripheral`, `classic_discover_and_pair_jw`.
- [ ] `tests/e2e/conftest.py` exposes `classic_central_peripheral_pair` and `virtual_classic_link_or_real_rf` fixtures.
- [ ] `tests/e2e/test_classic_lifecycle.py` has 4 `@pytest.mark.e2e` async scenarios (Tests 1–4).
- [ ] `pybluehost/hci/virtual_classic_link.py` distinguishes positive vs negative Link_Key_Request_Reply (if Step 3 of Task 6 showed it was needed).
- [ ] `uv run pytest tests/e2e/test_classic_lifecycle.py -v --transport=virtual` → 4 PASS (or 3 + 1 SKIP if a session-fixture limit applies, per LE E2E precedent).
- [ ] `uv run pytest tests/ -q --transport=virtual` → suite green minus the 3 pre-existing USB-diagnostics failures.
- [ ] STATUS.md updated.

## Out of Scope (deferred)

| Item | When |
|---|---|
| BR/EDR SC pairing via bridge (key_type=0x07) | Future Plan |
| NC / Passkey BR/EDR pair variants | Future Plan |
| A2DP / HFP / SCO synchronous channels | Independent Plan |
| Multi-channel RFCOMM | Out of scope |
| Phone interop (Android/iOS as Classic peer) | Independent Plan |
| Hardware CI runner | Infrastructure, not test code |
