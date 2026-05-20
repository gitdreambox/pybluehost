# VirtualClassicLink — Design Spec

**Date**: 2026-05-20
**Scope**: Build the BR/EDR (Classic) counterpart of `VirtualLELink` so two `Stack.virtual()` instances can complete real peer-to-peer Classic workflows (inquiry → connect → SSP pair → ACL data → encryption → disconnect). Infrastructure-only Plan; Classic SDP/RFCOMM/SPP workflow E2E scenarios become a follow-up Plan.
**Predecessors**: Pytest Transport Selection (introduced `Stack.virtual()` factory + `VirtualController`), SMP Sub-Plan 1 (existing `VirtualLELink` reference), HCI Tolerant Initialization (capability bitmap), Classic SSP single-controller integration test (`tests/integration/test_pairing_classic_sc_hci.py`).
**Successors**: Classic Workflow E2E (SDP browse, RFCOMM/SPP echo, bonded reconnect with auto-encrypt). All host-side BR/EDR layers (`SSPManager`, `RFCOMMManager`, `SDPClient`, `BondStorage`) already exist; this Plan just makes them testable peer-to-peer.

---

## 1. Goals

Today the project tests Classic features by injecting HCI events into a single `VirtualController` via the `simulate_*` test hooks (e.g. `simulate_ssp_pairing` at `pybluehost/hci/virtual.py:310`). That style validates host behavior on synthetic event streams but cannot validate peer-to-peer interactions: there is no second Stack, no second BD_ADDR, no real ACL traffic, no inquiry from one controller actually surfacing the other's address.

`VirtualClassicLink` mirrors `VirtualLELink` (LE) and provides exactly that second peer. The bridge is a **transport-level glue object** — it routes HCI events and ACL data between two `VirtualController` instances but understands nothing about SDP / RFCOMM / SSP / pairing semantics. Host layers do all the protocol work; the bridge just makes the wire look real.

This Plan delivers:
- The `VirtualClassicLink` class.
- Per-primitive integration tests proving each bridged behavior in isolation.
- One end-to-end smoke test: two stacks complete `inquiry → connect → SSP JW pair → encryption → disconnect`.

Follow-up Plans (out of scope here) build Classic SDP browse, RFCOMM/SPP echo, bonded reconnect, and the full Classic E2E suite on top.

## 2. Architecture

`VirtualClassicLink(central, peripheral, central_address, peripheral_address)` is one class living in `pybluehost/hci/virtual_classic_link.py`. It owns six logical sub-bridges, all sharing a connection-handle table:

| Sub-bridge | Responsibility |
|---|---|
| **InquiryBridge** | On `HCI_Inquiry` from either side, peer is "discoverable" iff its `inquiry_scan` bit (from `HCI_Write_Scan_Enable`) is 1 → emit `Inquiry_Result` + `Inquiry_Complete` to the initiator. |
| **ConnectionBridge** | `HCI_Create_Connection` → allocate handle, set `PENDING`, emit `Connection_Request` to peer. Peer's host replies with `HCI_Accept_Connection_Request` → set `CONNECTED`, emit `Connection_Complete` to both. Or peer rejects → `Connection_Complete(status=err)` to initiator only, release handle. Honors peer's `page_scan` flag (Page_Timeout if disabled). |
| **ACLBridge** | After `CONNECTED`, ACL data from one host routes verbatim to the other host's `on_acl_data` upstream. No reassembly; fragments pass through. |
| **AuthBridge** | Coordinates SSP + Legacy authentication event flow. Forwards `Link_Key_Request`, `IO_Capability_Request`, `IO_Capability_Response`, `User_Confirmation_Request`, `User_Confirmation_Request_Negative_Reply`, `PIN_Code_Request`, `Simple_Pairing_Complete`, `Authentication_Complete`, `Link_Key_Notification` between sides. Does NOT understand pairing flavors — just routes events the host layers exchange. |
| **EncryptionBridge** | `HCI_Set_Connection_Encryption(enable=1)` → `Encryption_Change(status=0, enabled=1)` to both. Disabling is symmetric. |
| **DisconnectBridge** | `HCI_Disconnect` from either side → `Disconnect_Complete` to both, release handle. |

The bridge intercepts host-issued HCI commands by hooking into each `VirtualController`'s command dispatch — the same hook point the existing `simulate_*` methods use. Every event the bridge emits flows through the controller's existing `_send_event_to_host(...)` path, so hosts cannot tell bridge-generated events apart from `simulate_*`-generated or real-radio events.

## 3. State machine + handle allocation

Per-handle state:

```python
class _ConnState(IntEnum):
    NONE = 0
    PENDING = 1       # Create_Connection sent, awaiting Accept/Reject
    CONNECTED = 2
    DISCONNECTING = 3
```

**Handle allocation**: bridge owns the handle namespace. On `Connection_Complete`, bridge assigns the next free handle starting at `0x0040`, incrementing. Both sides see the same handle for the same logical link. Handles release on `Disconnect_Complete`.

**Discoverability flag store**: bridge inspects `HCI_Write_Scan_Enable` from each stack and remembers `inquiry_scan` + `page_scan` bits per side.

**Roles**: bridge does NOT track central/peripheral. BR/EDR has initiator (created the connection) and acceptor; the bridge records which side called `Create_Connection` and treats it as initiator for the lifetime of the link.

### HCI commands the bridge intercepts

| Command | OGF/OCF | Effect |
|---|---|---|
| `HCI_Inquiry` | 0x01 0x0001 | Emit Inquiry_Result + Inquiry_Complete |
| `HCI_Inquiry_Cancel` | 0x01 0x0002 | Emit Inquiry_Complete(cancelled) |
| `HCI_Create_Connection` | 0x01 0x0005 | Alloc handle; emit Connection_Request to peer |
| `HCI_Accept_Connection_Request` | 0x01 0x0009 | Emit Connection_Complete to both |
| `HCI_Reject_Connection_Request` | 0x01 0x000A | Emit Connection_Complete(0x0D) to initiator; release handle |
| `HCI_Disconnect` | 0x01 0x0006 | Emit Disconnect_Complete to both |
| `HCI_Authentication_Requested` | 0x01 0x0011 | Emit Link_Key_Request to initiator |
| `HCI_Link_Key_Request_Reply` | 0x01 0x000B | Stash + forward IO_Capability_Request to peer |
| `HCI_Link_Key_Request_Negative_Reply` | 0x01 0x000C | Same as Reply but with no stored key |
| `HCI_IO_Capability_Request_Reply` | 0x01 0x002B | Emit IO_Capability_Response to peer |
| `HCI_User_Confirmation_Request_Reply` | 0x01 0x002C | Track confirm |
| `HCI_User_Confirmation_Request_Negative_Reply` | 0x01 0x002D | Emit Simple_Pairing_Complete(err) to both |
| `HCI_PIN_Code_Request_Reply` | 0x01 0x000D | Track PIN (legacy SSP) |
| `HCI_PIN_Code_Request_Negative_Reply` | 0x01 0x000E | Emit Auth_Complete(err) to both |
| `HCI_Set_Connection_Encryption` | 0x01 0x0013 | Emit Encryption_Change to both |
| `HCI_Write_Scan_Enable` | 0x03 0x001A | Update local discoverability flags |

All other HCI commands flow through to the existing `VirtualController` dispatch unchanged.

### ACL data routing

When host A sends ACL data on a `CONNECTED` handle, the bridge calls host B's `on_acl_data(acl_packet)` upstream (the same hook L2CAP uses). Fragments pass through; the bridge does NOT do reassembly or L2CAP/SDP/RFCOMM parsing — those are higher-layer concerns.

## 4. Data flow

### A) Inquiry only

```
B: HCI_Write_Scan_Enable(inquiry_scan=1, page_scan=1)
A: HCI_Inquiry(duration=8s)
   Bridge: peer B has inquiry_scan=1 → emit Inquiry_Result(A) with B's BD_ADDR
   Bridge: emit Inquiry_Complete(A, status=0)
```

### B) Inquiry → Connect → SSP JW pair → Encrypt → Disconnect (the canonical smoke)

```
B: HCI_Write_Scan_Enable(inquiry+page)
A: HCI_Inquiry → A sees B → Inquiry_Complete

A: HCI_Create_Connection(B_addr)
   Bridge: handle=0x40; state=PENDING; emit Connection_Request(B's host, A_addr)
B: HCI_Accept_Connection_Request(A_addr)
   Bridge: state=CONNECTED; emit Connection_Complete(handle=0x40) to both

A: HCI_Authentication_Requested(handle=0x40)
   Bridge: emit Link_Key_Request(A, B_addr)
A: HCI_Link_Key_Request_Negative_Reply(B_addr)
   Bridge: emit IO_Capability_Request(A) and IO_Capability_Request(B)
A: HCI_IO_Capability_Request_Reply(B_addr, io_cap=NoInputNoOutput, auth_req=0)
B: HCI_IO_Capability_Request_Reply(A_addr, io_cap=NoInputNoOutput, auth_req=0)
   Bridge: emit IO_Capability_Response to both sides
   Bridge: emit User_Confirmation_Request(numeric=0) to both — JW path
A: HCI_User_Confirmation_Request_Reply(B_addr)
B: HCI_User_Confirmation_Request_Reply(A_addr)
   Bridge: emit Simple_Pairing_Complete(status=0) to both
   Bridge: emit Link_Key_Notification(BD_ADDR=peer, key_type=0x05 Combination_Key, link_key=randomized) to both
   Bridge: emit Authentication_Complete(status=0, handle=0x40) to A

A: HCI_Set_Connection_Encryption(handle=0x40, enable=1)
   Bridge: emit Encryption_Change(status=0, handle=0x40, enabled=1) to both

A: HCI_Disconnect(handle=0x40, reason=0x13)
   Bridge: state=DISCONNECTING; emit Disconnect_Complete(handle=0x40, reason=0x13) to both
   Bridge: release handle
```

### C) ACL data round-trip (post-encryption)

```
A: ACL fragment (handle=0x40, cid=0x0001 signaling)
   Bridge: route to B's host on_acl_data upstream verbatim
B: ACL reply
   Bridge: route to A's host on_acl_data upstream
```

The bridge does not parse L2CAP / SDP / RFCOMM — those are pure pass-through. Existing host-side layers handle the rest.

## 5. Error, edge, and concurrency

| Scenario | Bridge response |
|---|---|
| Peer not discoverable on Inquiry | Inquiry_Complete with no Inquiry_Result for that peer |
| Peer not page-scannable on Create_Connection | Connection_Complete(status=0x04 Page_Timeout) to initiator after configurable delay (default 5 s; test override) |
| Reject_Connection_Request | Connection_Complete(status=0x0D) to initiator; handle released |
| User_Confirmation_Request_Negative_Reply | Simple_Pairing_Complete(status=0x05 Authentication_Failure) to both |
| PIN_Code_Request_Negative_Reply | Authentication_Complete(status=0x05) to both |
| HCI_Disconnect while PENDING (before Accept) | State→NONE; Disconnect_Complete only to disconnect-initiator; the other side never saw Connection_Complete |
| ACL on a non-existent / disconnected handle | Drop silently with `logger.debug` (matches real controller — would NAK) |
| Double Accept_Connection_Request for same BD_ADDR | Ignore second; first wins |
| `link.disconnect()` while CONNECTED handles exist | Emit Disconnect_Complete(reason=0x16 Local_Host_Terminated) to both for each handle; emit Connection_Complete(status=0x16) to initiator for each PENDING |

**Concurrency**: each `VirtualController` already serializes outgoing events through its `_host_sink` asyncio queue. The bridge appends events to those queues using `asyncio.create_task` for fire-and-forget delivery. Cross-controller ordering uses the event loop scheduler; no extra locking required. The bridge mutex protects the handle table only.

## 6. File layout

```
pybluehost/hci/virtual_classic_link.py        NEW — VirtualClassicLink class (~600 lines)
tests/integration/test_virtual_classic_link.py  NEW — per-primitive bridge tests (~14)
tests/integration/test_classic_e2e_smoke.py     NEW — one end-to-end smoke test
```

No changes to existing production code. `VirtualController`'s command-dispatch hook is already used by the `simulate_*` test methods — the bridge plugs into the same point.

## 7. Test strategy

### Per-primitive (14 tests in `test_virtual_classic_link.py`)

| Test | Asserts |
|---|---|
| `test_inquiry_discovers_discoverable_peer` | Inquiry returns peer BD_ADDR when peer's inquiry_scan=1 |
| `test_inquiry_skips_non_discoverable_peer` | Inquiry completes with no results when peer's inquiry_scan=0 |
| `test_inquiry_cancel_completes_with_cancelled_status` | HCI_Inquiry_Cancel emits Inquiry_Complete(cancelled) |
| `test_create_connection_succeeds_when_page_scan_enabled` | Both sides see Connection_Complete(status=0, same handle) |
| `test_create_connection_page_timeout_when_page_scan_disabled` | Initiator sees Connection_Complete(status=0x04) after the configured delay |
| `test_accept_connection_round_trip` | Connection_Request + Accept → CONNECTED on both |
| `test_reject_connection_emits_status_error` | Reject → initiator sees Connection_Complete(0x0D); handle released |
| `test_acl_data_routes_a_to_b` | L2CAP signaling frame from A reaches B's on_acl_data verbatim |
| `test_acl_data_routes_b_to_a` | Reverse direction same |
| `test_acl_on_disconnected_handle_drops_silently` | No event/error |
| `test_link_key_request_routes_to_initiator` | Auth_Requested → Link_Key_Request to A's host |
| `test_io_capability_round_trip` | Both sides see IO_Capability_Response after exchange |
| `test_user_confirmation_negative_reply_fails_pairing` | One side replies negative → Simple_Pairing_Complete(0x05) to both |
| `test_encryption_change_routes_to_both_sides` | Set_Connection_Encryption → Encryption_Change(enabled=1) to both |
| `test_disconnect_routes_to_both_sides` | HCI_Disconnect → Disconnect_Complete to both; handle released |
| `test_link_teardown_releases_all_handles` | Two connected handles + link.disconnect() → both sides see Disconnect_Complete for each |

### Smoke E2E (1 test in `test_classic_e2e_smoke.py`)

```python
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_classic_inquiry_connect_ssp_jw_pair_disconnect(tmp_path):
    """End-to-end smoke: two stacks complete inquiry → connect → SSP JW pair → encrypt → disconnect."""
    # Setup: two Stack.virtual() with bond storage + VirtualClassicLink bridging them
    # Stack B writes scan enable (inquiry + page)
    # Stack A runs inquiry → discovers B
    # Stack A connects to B
    # Both stacks complete SSP Just Works via existing SSPManager
    # Both observe Encryption_Change
    # Bond persists on both sides with link_key_type=0x05 (Combination_Key)
    # Stack A disconnects; both see Disconnect_Complete
```

This single composite test validates the bridge end-to-end and proves SSPManager + BondStorage wire up correctly against bridged events. Detailed workflow scenarios (SDP browse, RFCOMM/SPP echo, bonded reconnect) become the follow-up Classic Workflow E2E Plan.

### Acceptance

- `uv run pytest tests/integration/test_virtual_classic_link.py -v --transport=virtual` → 14 passed.
- `uv run pytest tests/integration/test_classic_e2e_smoke.py -v --transport=virtual` → 1 passed.
- `uv run pytest tests/ -q --transport=virtual` → suite green minus the 3 pre-existing USB-diagnostics failures.

## 8. Known risks

1. **Command-dispatch hook surface**: the bridge intercepts a specific list of HCI commands. If `VirtualController`'s dispatch is structured such that test-hook interception is awkward, the implementer may need a thin extension point on `VirtualController` (e.g., `command_interceptor: Callable | None`). This would be a small production-code change, in scope for this Plan only if essential.

2. **Link key generation**: the bridge emits `Link_Key_Notification` with a synthesized key. The exact value doesn't matter as long as both sides receive the SAME key (so bonded reconnect tests later work). Plan: use a deterministic value derived from sorted `(addr_a, addr_b)` to make it reproducible in tests.

3. **Page_Timeout delay**: real controllers wait the configured `HCI_Write_Page_Timeout` value (default 5.12 s); for tests we want this configurable per-bridge (default 0.1 s, real default available via constructor kwarg).

4. **ACL fragmentation**: L2CAP can send multi-fragment PDUs. Real controllers reassemble across fragments before delivering to the next layer; in our virtual model the host does ACL-frame reassembly itself (L2CAP layer), so the bridge truly just passes through. Verify this is the case by inspecting existing virtual LE ACL handling (which works today).

5. **Existing `simulate_ssp_pairing` test hook**: that hook injects a synthetic 4-event sequence on one controller. The bridge gives a more accurate simulation, but the existing test (`test_pairing_classic_sc_hci.py`) keeps using the simulate hook for its specific assertions. Both coexist; the simulate hook stays.

6. **Connection handle collision with LE**: BR/EDR and LE handles share the same 12-bit namespace (`HCI_Connection_Handle`). Bridge starts at `0x40` to leave room for LE handles which start at `0x01`. Conflict detection is not needed in our virtual world because a single Stack only has one VirtualController managing both.

7. **SCO/eSCO out of scope**: A2DP, HFP, and any synchronous audio profiles will not work over this bridge. If a future Plan needs them, add a `SCOBridge` sub-bridge.

## 9. Acceptance criteria

- [ ] `pybluehost/hci/virtual_classic_link.py` exists with `VirtualClassicLink` class.
- [ ] `VirtualClassicLink(central, peripheral, central_address, peripheral_address)` constructor; `connect()` / `disconnect()` lifecycle methods optional (not all sub-bridges require explicit connect()).
- [ ] InquiryBridge: discoverable peer found, non-discoverable peer skipped, cancel works.
- [ ] ConnectionBridge: accept + reject + page-timeout all reach the right host(s) with the right status.
- [ ] ACLBridge: L2CAP frames route both directions verbatim; non-existent-handle drops silently.
- [ ] AuthBridge: Link_Key_Request, IO_Capability_Request/Response, User_Confirmation_Request, Simple_Pairing_Complete, Authentication_Complete, Link_Key_Notification all flow correctly between sides.
- [ ] EncryptionBridge: Set_Connection_Encryption → Encryption_Change on both.
- [ ] DisconnectBridge: Disconnect → Disconnect_Complete on both; handle released.
- [ ] 14 per-primitive integration tests pass.
- [ ] 1 smoke E2E test passes.
- [ ] No regressions in existing `test_pairing_classic_sc_hci.py` (single-controller simulate hook still works).
- [ ] STATUS.md updated to mark Plan complete; the follow-up "Classic Workflow E2E" entry added to 下一步.

## 10. Out of scope (deferred)

| Item | When |
|---|---|
| Classic Workflow E2E (SDP browse, RFCOMM/SPP echo, bonded reconnect) | Follow-up Plan; this is the immediate successor |
| BR/EDR Secure Connections via bridge (key_type=0x07) | Follow-up Plan; existing single-controller simulate test covers SC bond persistence |
| SCO / eSCO audio channels (A2DP, HFP) | Independent Plan if needed |
| Page scan timing accuracy / inquiry interval semantics | Not needed for workflow validation |
| Real-hardware Classic E2E | Separate manual smoke; same scenario code reusable with `--transport=usb:...` once `build_stack_from_spec` accepts `config=` |
| Extended Inquiry Response (EIR) name discovery | Optional follow-up |
| Hold / Sniff / Park modes | Out of scope |
