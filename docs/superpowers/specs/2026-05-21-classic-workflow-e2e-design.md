# Classic Workflow E2E — Design Spec

**Date**: 2026-05-21
**Scope**: BR/EDR (Classic) workflow-level end-to-end tests on top of the just-shipped `VirtualClassicLink` infrastructure. Four scenarios validating SDP browse, RFCOMM/SPP echo, bonded reconnect with auto-encrypt, and pair-failure clean teardown. Test-only; no production-code changes anticipated.
**Predecessors**: [VirtualClassicLink](../plans/2026-05-20-virtual-classic-link.md), [E2E LE Lifecycle](../plans/2026-05-20-e2e-le-lifecycle.md) (same shape, different transport), Pytest Transport Selection (provides `stack` / `peer_stack` / `transport_mode` session fixtures), all SMP Sub-Plans (host-side `SSPManager` + bond persistence).
**Successors**: 断线重连闭环 (cross-cutting LE+Classic reconnect closure), 真机 E2E 验证 (same scenarios run on two USB adapters manually).

---

## 1. Goals

Today the `tests/e2e/` suite has LE workflow coverage (`test_le_lifecycle.py` — 4 scenarios) and Classic infrastructure validation (`test_virtual_classic_link.py` — 21 per-primitive + `test_classic_e2e_smoke.py` — 1 smoke). The smoke test proves the bridge works; this Plan adds the **workflow-level** Classic tests on top, mirroring the LE E2E shape.

Design priorities, in order:
1. **Validate Classic workflow composition** — multi-subsystem flows (Inquiry + SSP + SDP, or SSP + RFCOMM/SPP) that per-feature integration tests don't exercise together.
2. **Transport-agnostic** — same scenarios run on `--transport=virtual` (CI) and `--transport=usb:VID:PID --transport-peer=usb:VID:PID#2` (manual hardware bench).
3. **CI-runnable** — virtual mode produces deterministic sub-30-second runs.
4. **Negative-path coverage** — pair-failure clean teardown is the regression guard.

Out of scope (separate Plans): BR/EDR SC pairing via bridge (key_type=0x07); Numeric Comparison / Passkey BR/EDR variants; A2DP / HFP / SCO; reconnect-from-cold-storage without re-advertising; phone interop.

## 2. Test inventory

Four scenarios in `tests/e2e/test_classic_lifecycle.py`.

| # | Test | Validates |
|---|---|---|
| 1 | `test_e2e_classic_sdp_browse` | Inquiry → connect → SSP JW → SDP search for SPP UUID → SDP search-attributes for `ServiceClassIDList`, `ServiceName`, `ProtocolDescriptorList`. Verifies the RFCOMM channel number embedded in the protocol descriptor. |
| 2 | `test_e2e_classic_rfcomm_spp_echo` | Post-pair: open RFCOMM/SPP channel to a Peripheral-registered echo handler; send two messages bidirectionally; verify echo. Validates RFCOMM SABM/UA + UIH frame round-trip. |
| 3 | `test_e2e_classic_bonded_reconnect_auto_encrypt` | Two-session lifecycle sharing on-disk `JsonBondStorage`. Session 1 pairs and persists `BondInfo(link_key, link_key_type=0x05)`. Session 2 reconnects → `SSPManager._handle_link_key_request` looks up stored bond → replies with link key (no re-pair) → encryption succeeds → SDP browse confirms link is usable. |
| 4 | `test_e2e_classic_pair_failure_disconnects_cleanly` | Inject a Peripheral handler that rejects `User_Confirmation_Request` → `stack.authenticate_classic()` raises → connection disconnect + stack teardown both complete within 2 s. Regression guard against leaked auth-completion futures. |

**Coverage rationale**:
- Test 1 = the minimum SDP-on-Classic validation no current test exercises end-to-end.
- Test 2 = highest-value capability (SPP echo is the canonical RFCOMM use case).
- Test 3 = PRD-acceptance bonded lifecycle (the Classic counterpart of LE Test 3).
- Test 4 = negative path; ensures Classic auth failures don't leak state.

## 3. Architecture

Test-only Plan. New / extended files:

```
tests/e2e/
├── _classic_test_service.py          NEW  — SPP server channel + handler + SDP record helpers
├── conftest.py                       EXT  — classic_central_peripheral_pair +
│                                            virtual_classic_link_or_real_rf fixtures
├── _helpers.py                       EXT  — _supports_classic_ssp,
│                                            classic_discover_peripheral,
│                                            classic_discover_and_pair_jw
└── test_classic_lifecycle.py         NEW  — 4 scenarios
```

No production-code changes anticipated. If a hidden API gap surfaces during implementation (e.g., `SPPClient` doesn't expose `recv`-with-timeout), the implementer reports `DONE_WITH_CONCERNS` rather than expanding scope.

## 4. Capability gating

Mirroring LE E2E's `_supports_le_sc`, this Plan adds `_supports_classic_ssp(stack) → bool` keyed on HCI capability introspection (no per-vendor allowlist):
- Virtual mode short-circuits True.
- Hardware adapters: check the LE Features bitmap for BR/EDR Host Support bit + the Read_Local_Supported_Commands bitmap for SSP-related opcodes (e.g. `HCI_IO_Capability_Request_Reply` at octet 32 bit 5).

Each scenario begins with `if not _supports_classic_ssp(stack_c): pytest.skip("adapter does not support BR/EDR SSP")`.

## 5. Fixtures

### 5.1 Shared test service (`tests/e2e/_classic_test_service.py`)

Exports:
```python
SPP_SERVER_CHANNEL = 1
SPP_SERVICE_NAME = "PBH-E2E SPP"
SPP_CLASS_UUID = 0x1101   # Serial Port Profile

def build_spp_sdp_record() -> SDPRecord:
    """Return an SDP record representing an SPP service on SPP_SERVER_CHANNEL."""

async def echo_handler(channel):
    """RFCOMM channel handler that echoes every received frame back on the same channel."""
```

Used by Tests 1, 2, 3. The implementer adapts the exact `SDPRecord` constructor to whatever `SDPServer.add_service(...)` expects.

### 5.2 Async fixtures (`tests/e2e/conftest.py` additions)

```python
@pytest_asyncio.fixture
async def classic_central_peripheral_pair(stack, peer_stack):
    """Register SPP service on Peripheral + set connectable+discoverable.

    Yields (stack_c, stack_p) ready for Classic workflow scenarios.
    """
    peer_stack._sdp.add_service(build_spp_sdp_record())
    await peer_stack._rfcomm.listen(SPP_SERVER_CHANNEL, echo_handler)
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
            await link.disconnect()
    else:
        yield None
```

### 5.3 Helpers (`tests/e2e/_helpers.py` additions)

```python
def _supports_classic_ssp(stack) -> bool:
    """True iff the controller advertises BR/EDR SSP support."""

async def classic_discover_peripheral(
    stack_c, expected_addr, timeout=3.0,
) -> None:
    """Run inquiry on stack_c, wait until expected_addr appears, then cancel."""

async def classic_discover_and_pair_jw(
    stack_c, peripheral_addr, *, scan_timeout=3.0, pair_timeout=3.0,
) -> int:
    """Composition: discover → connect_classic → authenticate_classic.
    Returns the connection handle.
    """
```

## 6. Per-scenario data flow

### Test 1 — SDP browse

```
Setup: classic_central_peripheral_pair + virtual_classic_link_or_real_rf
Skip:  if not _supports_classic_ssp(stack_c): pytest.skip(...)

C: handle = await classic_discover_and_pair_jw(stack_c, stack_p._local_address)
C: client = SDPClient(stack_c._l2cap, handle=handle)
   handle_list = await client.search(target=handle, uuid=SPP_CLASS_UUID)
   assert len(handle_list) >= 1
   svc_handle = handle_list[0]
   attrs = await client.search_attributes(
       target=handle, service_handle=svc_handle,
       attribute_ids=[0x0001, 0x0004, 0x0100],
   )
   assert SPP_CLASS_UUID in [uuid_to_int(u) for u in attrs[0x0001]]
   assert attrs[0x0100] == SPP_SERVICE_NAME
   # 0x0004 = ProtocolDescriptorList; assert RFCOMM channel = SPP_SERVER_CHANNEL
C: await stack_c.gap.classic_connections.disconnect(handle)
```

Asserts SDP `ServiceSearchAttributeRequest` round-trip returns the registered SPP record with the expected channel number.

### Test 2 — RFCOMM/SPP echo

```
Setup: same fixture; echo_handler already registered on RFCOMM channel 1 by the fixture
Skip:  same capability gate

C: handle = await classic_discover_and_pair_jw(stack_c, stack_p._local_address)
C: spp_client = SPPClient(stack_c._rfcomm)
   spp_conn = await spp_client.connect(target=handle)
   await spp_conn.send(b"hello classic\n")
   echoed = await spp_conn.recv(timeout=1.0)
   assert echoed == b"hello classic\n"
   await spp_conn.send(b"second line\n")
   echoed2 = await spp_conn.recv(timeout=1.0)
   assert echoed2 == b"second line\n"
   await spp_conn.close()
C: await stack_c.gap.classic_connections.disconnect(handle)
```

Exercises RFCOMM SABM/UA establishment + UIH frame round-trip + DISC teardown. The `SPPClient.connect/send/recv/close` API names are best-effort; the implementer verifies against `pybluehost/classic/spp.py` and adjusts.

### Test 3 — Bonded reconnect with auto-encrypt

Two-session lifecycle. Builds its own stacks (does NOT use `classic_central_peripheral_pair`) so each session opens fresh stacks pointing at the same on-disk bond storage.

```
Skip: capability gate inside Session 1's stack_c

Session 1:
  storage_c = JsonBondStorage(tmp_path / "bonds_c.json")
  storage_p = JsonBondStorage(tmp_path / "bonds_p.json")
  cfg_c = StackConfig(bond_storage=storage_c, security=SecurityConfig())
  cfg_p = StackConfig(bond_storage=storage_p, security=SecurityConfig())
  stack_c = await Stack.virtual(config=cfg_c, address=BDAddress.from_string("0A:0A:0A:0A:0A:0A"))
  stack_p = await Stack.virtual(config=cfg_p, address=BDAddress.from_string("0B:0B:0B:0B:0B:0B"))
  stack_p._sdp.add_service(build_spp_sdp_record())
  link = VirtualClassicLink(...).attach()
  Peripheral set_connectable + set_discoverable.
  handle = await classic_discover_and_pair_jw(stack_c, stack_p._local_address)
  bond = await storage_c.load_bond(stack_p._local_address)
  assert bond is not None and bond.link_key_type == 0x05
  await stack_c.gap.classic_connections.disconnect(handle)
  await link.disconnect()
  await stack_c.close()
  await stack_p.close()

Session 2 (same tmp_path):
  Reopen two stacks with the same storage paths. Wire a fresh VirtualClassicLink.
  Peripheral set_connectable + set_discoverable; re-register SPP service.
  handle = await classic_discover_peripheral(stack_c, peripheral_addr)
  handle = await stack_c.connect_classic(peripheral_addr, timeout=3.0)
  # Trigger authentication. Because the bond exists, SSPManager's Link_Key_Request
  # handler replies with the stored link key instead of negative-reply, and the
  # bridge's AuthBridge takes the "stored key" path (no IO_Capability_Request,
  # no User_Confirmation_Request — direct Auth_Complete).
  await stack_c.authenticate_classic(handle, timeout=3.0)
  await stack_c.enable_classic_encryption(handle, timeout=2.0)
  # Verify the encrypted link works for an SDP query.
  client = SDPClient(stack_c._l2cap, handle=handle)
  handle_list = await client.search(target=handle, uuid=SPP_CLASS_UUID)
  assert len(handle_list) >= 1
  await stack_c.gap.classic_connections.disconnect(handle)
  await link.disconnect()
  await stack_c.close()
  await stack_p.close()
```

**Bridge support note**: the existing `VirtualClassicLink.AuthBridge` handles `HCI_Link_Key_Request_Reply` (positive) AND `HCI_Link_Key_Request_Negative_Reply` (no stored key). For a successful bonded reconnect, the AuthBridge needs to recognize the positive-reply case and emit `Auth_Complete(status=0, handle)` directly, skipping the SSP IO_Capability dance. The implementer verifies this works against the existing bridge code; if not, a small bridge enhancement is in scope for this Plan (treat the positive Link_Key_Request_Reply as completing auth and emit Auth_Complete to initiator without further SSP events).

### Test 4 — Pair-failure clean teardown

```
Setup: classic_central_peripheral_pair + virtual_classic_link_or_real_rf
Skip:  capability gate

Inject SSP rejection on Peripheral:
    stack_p._gap.classic_ssp.on_user_confirmation(lambda addr, numeric: False)

C: handle = await classic_discover_peripheral(stack_c, stack_p._local_address)
C: handle = await stack_c.connect_classic(stack_p._local_address, timeout=3.0)
C: with pytest.raises(Exception, match=r"(authentication|Auth_Complete|SSP).*fail"):
       await stack_c.authenticate_classic(handle, timeout=3.0)

# Critical: cleanup within 2s
await asyncio.wait_for(
    stack_c.gap.classic_connections.disconnect(handle), timeout=2.0,
)
# fixture teardown closes both stacks within 2s
```

The exact exception message from `authenticate_classic` on failure may differ. The implementer adjusts the `match=` regex after the first run.

## 7. Capability + APIs surveyed (verify during implementation)

The implementer runs these greps before writing code:

```bash
# SDPClient
grep -n "class SDPClient\|def search\|def search_attributes\|def __init__" pybluehost/classic/sdp.py

# SDPServer registration
grep -n "class SDPServer\|def add_service\|def register" pybluehost/classic/sdp.py

# SPPClient
grep -n "class SPPClient\|class SPPConnection\|def connect\|def send\|def recv\|def close" pybluehost/classic/spp.py

# RFCOMMManager listen
grep -n "def listen\|server_channel" pybluehost/classic/rfcomm.py

# Stack public Classic API (verified by VirtualClassicLink smoke test)
grep -n "connect_classic\|authenticate_classic\|enable_classic_encryption" pybluehost/stack.py

# SSP delegate hook (Test 4)
grep -n "on_user_confirmation\|set_io_capability\|class SSPManager" pybluehost/classic/gap.py
```

If any helper assumed in the data-flow sketches doesn't exist (e.g. `SPPConnection.recv(timeout=...)` may need to be implemented or wrapped), the implementer either:
1. Uses the closest existing API and adjusts the test.
2. Adds a small test-only wrapper in `_helpers.py`.
3. If neither works, reports `DONE_WITH_CONCERNS`.

Production code changes are out of scope.

## 8. Error & edge handling

| Scenario | Failure | Handling |
|---|---|---|
| All | SC/SSP absent on hardware | `pytest.skip("adapter does not support BR/EDR SSP")` |
| Test 1, 2 | Inquiry doesn't surface peer | `pytest.fail("no peripheral discovered")` after 3 s |
| Test 1 | SDP service not found | Failure message lists discovered services |
| Test 2 | RFCOMM connect timeout | Failure includes the L2CAP channel state |
| Test 2 | Echo recv timeout | Failure includes bytes received so far |
| Test 3 | Auto-encrypt doesn't reach Session 2 | Test fails with the observed `Auth_Complete` status |
| Test 3 | SDP query on encrypted link fails | Propagate the SDP error code |
| Test 4 | `authenticate_classic` doesn't raise | `pytest.raises` catches that and fails |
| Test 4 | Teardown hangs | `asyncio.wait_for(..., timeout=2.0)` raises TimeoutError |

Each scenario carries `@pytest.mark.e2e` (already registered in `tests/conftest.py`) and uses `tmp_path` for any bond storage.

## 9. Known risks

1. **`stack.authenticate_classic` failure semantics**. The exact exception (and message) raised on auth failure depends on the existing host-side implementation. The implementer verifies first then adjusts the `pytest.raises(match=...)` regex. If `authenticate_classic` doesn't raise on failure, Test 4 polls `Auth_Complete` event status directly via a recorded callback.

2. **Bonded-reconnect bridge behavior**. The existing `VirtualClassicLink.AuthBridge` was designed around the no-stored-key path (Link_Key_Request → negative-reply → IO_Capability flow). The positive-reply case (`HCI_Link_Key_Request_Reply` with the actual key) needs to emit `Auth_Complete(status=0, handle)` directly to the initiator without proceeding through the IO_Capability sequence. **Verify this works against the existing bridge code first**. If the bridge currently falls through to the IO_Capability path on positive-reply too, a small enhancement is in scope for this Plan (one branch in `_auth_emit_io_cap_requests`).

3. **SPP API surface mismatch**. The plan text uses `SPPClient.connect`, `SPPConnection.send/recv/close`. If the actual `pybluehost/classic/spp.py` exposes different methods (e.g. asyncio-stream-style `read(n)` instead of `recv(timeout)`), the implementer adapts. Document the actual API in the test file's docstring.

4. **Address byte-order asymmetry in SSPManager** — already flagged in the VirtualClassicLink smoke test. Tests use palindromic addresses (`0A:0A:...` / `0B:0B:...`) to dodge it. Same convention here. Documented inline.

5. **RFCOMM credit / flow control** — RFCOMM uses credit-based flow control over UIH frames. The bridge's ACL pass-through plus the host's existing RFCOMM stack should handle this transparently. If the echo test fails because credits don't replenish, that's an RFCOMM-stack issue (out of scope) or a bridge gap (in scope but small).

6. **Two-session VirtualClassicLink reuse** (Test 3). Each session creates a fresh `VirtualClassicLink`. Need to confirm no state leaks across sessions (e.g., `_handles` table reset on each new bridge). The bridge is instantiated fresh per session in the test body so state is per-instance; no shared state risk.

## 10. Acceptance criteria

- [ ] `tests/e2e/_classic_test_service.py` exists with `SPP_SERVER_CHANNEL`, `SPP_CLASS_UUID`, `SPP_SERVICE_NAME`, `build_spp_sdp_record()`, `echo_handler()`.
- [ ] `tests/e2e/conftest.py` exports `classic_central_peripheral_pair` + `virtual_classic_link_or_real_rf` fixtures.
- [ ] `tests/e2e/_helpers.py` adds `_supports_classic_ssp`, `classic_discover_peripheral`, `classic_discover_and_pair_jw`.
- [ ] `tests/e2e/test_classic_lifecycle.py` has 4 `@pytest.mark.e2e` async scenarios: SDP browse, RFCOMM/SPP echo, bonded reconnect, pair-failure cleanup.
- [ ] `uv run pytest tests/e2e/test_classic_lifecycle.py -v --transport=virtual` → 4 passed (or 3 + 1 SKIP if a session-fixture limit, per LE E2E precedent).
- [ ] `uv run pytest tests/ -q --transport=virtual` → suite green minus the 3 pre-existing USB-diagnostics failures.
- [ ] STATUS.md updated to mark Plan ✅; "下一步" reflects the new state.

## 11. Running on hardware

Same code, manual invocation:

```bash
uv run pytest tests/e2e/test_classic_lifecycle.py -v \
    --transport=usb:vendor=intel#1 \
    --transport-peer=usb:vendor=intel#2
```

Capability gate auto-skips on adapters without BR/EDR SSP. Test 3 (two-session, builds its own stacks) currently skips in hardware mode until `build_stack_from_spec` accepts `config=` — same status as LE Test 3.

If hardware reveals real-world issues (vendor SSP quirks, RFCOMM timing, SDP fragment limits), those go into a future Plan rather than this generic E2E suite.

## 12. Out of scope (deferred)

| Item | When |
|---|---|
| BR/EDR Secure Connections pairing via bridge (key_type=0x07) | Future Plan; existing single-controller `simulate_ssp_pairing` covers SC bond persistence |
| Numeric Comparison / Passkey Entry BR/EDR variants | Future Plan; current pair tests use Just Works only |
| A2DP / HFP / SCO synchronous channels | Independent Plan if needed |
| Reconnect from cold storage (no re-advertising) | Future Plan; current Test 3 relies on Peripheral re-enabling page-scan + inquiry-scan in Session 2 |
| Phone interop (Android/iOS as peer) | Independent Plan |
| Multi-channel RFCOMM (more than one concurrent SPP) | Out of scope |
| Hardware CI runner / two-adapter test bench | Infrastructure work, not test code |
