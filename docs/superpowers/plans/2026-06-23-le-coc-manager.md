# LE CoC Manager Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute task-by-task. Steps use `- [ ]` syntax.

**Goal:** Add LE Credit-Based Channel (LE CoC) connection signaling + connect/listen API to the v1.0 L2CAP manager so v1.2 P.8 (and any future LE CoC consumer) can open channels through a normal `stack.l2cap.*` API. `LECoCChannel` already exists in `pybluehost/l2cap/ble.py` and handles K-frame send/recv + credit accounting; what's missing is the LE signaling PDU exchange that brings the channel into existence and tears it down.

**Architecture:**
- New `pybluehost/l2cap/le_signaling.py` — codec for LE signaling PDUs (Core Spec Vol 3 Part A §4 LE-U mode subset):
  - `0x06` DISCONNECTION_REQUEST / `0x07` DISCONNECTION_RESPONSE (shared form with Classic)
  - `0x14` LE_CREDIT_BASED_CONNECTION_REQUEST
  - `0x15` LE_CREDIT_BASED_CONNECTION_RESPONSE
  - `0x16` LE_FLOW_CONTROL_CREDIT
- Extend `pybluehost/l2cap/manager.py`:
  - When opening an LE connection, wire `CID_LE_SIGNALING` (already created at line 150) to a new `_on_le_signaling(handle, data)` handler via `SimpleChannelEvents(on_data=...)`.
  - Track LE listeners (`self._le_listeners: dict[psm, callback]`), pending outgoing requests (`self._pending_le_connect: dict[identifier, Future]`), allocated dynamic CIDs (`self._le_dynamic_cids: dict[handle, set[int]]`).
  - Add `async def connect_le_coc_channel(self, handle, psm, *, mtu=512, mps=251, initial_credits=10) -> LECoCChannel`.
  - Add `def listen_le_coc_channel(self, psm, handler)`.
  - Honour incoming requests: allocate CID (start at 0x0040), respond with our params, instantiate `LECoCChannel`, invoke the listener.
  - Honour `LE_FLOW_CONTROL_CREDIT`: call `LECoCChannel.add_credits(n)`.
  - On disconnect (handle level), tear down per-handle channels.

**Tech Stack:** Python 3.10+, asyncio, struct, pytest with `asyncio_mode=auto`. No new deps.

**Spec references:**
- Core Spec Vol 3 Part A §4 (L2CAP signaling) — LE signaling channel 0x0005
- Existing `pybluehost/l2cap/ble.py::LECoCChannel` — K-frame format, credit accounting
- Existing Classic signaling pattern in `pybluehost/l2cap/manager.py::_on_classic_signaling`

**Out of scope (v1):**
- Enhanced LE Credit Based Channels (multi-channel via `0x17`/`0x18`/`0x19` LE Credit Based ECFC) — deferred
- Reconfiguration request/response (`0x1A`/`0x1B`) — deferred
- Echo/Information request handling on LE signaling

---

## Task 1: LE signaling PDU codec

**Files:**
- Create: `pybluehost/l2cap/le_signaling.py`
- Create: `tests/unit/l2cap/test_le_signaling_codec.py`

LE signaling PDUs share the same `[code(u8), identifier(u8), length(u16 LE), data]` framing as Classic signaling.

### Payloads (Core Spec Vol 3 Part A §4.22-4.24)

```
0x14 LE_CREDIT_BASED_CONNECTION_REQUEST data:
    LE_PSM(2 LE) | SCID(2 LE) | MTU(2 LE) | MPS(2 LE) | InitialCredits(2 LE)

0x15 LE_CREDIT_BASED_CONNECTION_RESPONSE data:
    DCID(2 LE) | MTU(2 LE) | MPS(2 LE) | InitialCredits(2 LE) | Result(2 LE)

0x16 LE_FLOW_CONTROL_CREDIT data:
    CID(2 LE) | Credits(2 LE)

0x06 DISCONNECTION_REQUEST data:
    DCID(2 LE) | SCID(2 LE)

0x07 DISCONNECTION_RESPONSE data:
    DCID(2 LE) | SCID(2 LE)
```

Result codes for 0x15: 0x0000=Success, 0x0002=PSM not supported, 0x0004=No resources, 0x0005=Insufficient authentication, etc.

- [ ] **Step 1.1: Write failing tests** — covering encode + decode round-trip for each PDU type + length-validation edges.
- [ ] **Step 1.2: Implement `le_signaling.py`** — `@dataclass` for each PDU, `encode_*` + `decode_le_signaling(data) -> (code, identifier, payload_obj)` dispatcher.
- [ ] **Step 1.3: Run tests, ensure pass; commit**

---

## Task 2: LE signaling dispatcher in L2CAPManager

**Files:**
- Modify: `pybluehost/l2cap/manager.py`
- Create: `tests/unit/l2cap/test_le_signaling_dispatch.py`

- [ ] **Step 2.1:** Add `_on_le_signaling(self, handle, data)` method that decodes each PDU and routes:
  - `LE_CREDIT_BASED_CONNECTION_REQUEST` → `_handle_incoming_le_coc_request(handle, ident, req)`
  - `LE_CREDIT_BASED_CONNECTION_RESPONSE` → resolves a pending outgoing request future
  - `LE_FLOW_CONTROL_CREDIT` → `_credit.add_credits(n)` on the channel matching the peer-supplied CID
  - `DISCONNECTION_REQUEST` → close the channel, reply with RESPONSE
  - `DISCONNECTION_RESPONSE` → resolve pending disconnect future / silently accept
- [ ] **Step 2.2:** Wire `_on_le_signaling` to `CID_LE_SIGNALING` in `on_connection` (`SimpleChannelEvents(on_data=...)`).
- [ ] **Step 2.3:** Add state attributes in `__init__`:
  - `self._le_listeners: dict[int, Callable]` (psm → handler)
  - `self._pending_le_connect: dict[int, asyncio.Future]` (signaling identifier → future)
  - `self._next_le_identifier: int = 1`
  - `self._next_le_cid: int = 0x0040`  # LE dynamic CID range starts here
  - `self._le_channels: dict[int, LECoCChannel]` (local SCID → channel)
- [ ] **Step 2.4:** Tests + commit.

---

## Task 3: `connect_le_coc_channel` (outgoing)

**Files:**
- Modify: `pybluehost/l2cap/manager.py`
- Create: `tests/unit/l2cap/test_le_coc_connect.py`

- [ ] **Step 3.1:** Implement:

```python
async def connect_le_coc_channel(
    self, handle: int, psm: int, *,
    mtu: int = 512, mps: int = 251, initial_credits: int = 10,
    timeout: float = 5.0,
) -> LECoCChannel:
    if handle not in self._connections:
        raise RuntimeError(f"no connection on handle 0x{handle:04X}")
    scid = self._allocate_le_cid()
    ident = self._next_le_identifier; self._next_le_identifier = (self._next_le_identifier % 255) + 1
    req = LECreditBasedConnectionRequest(
        le_psm=psm, scid=scid, mtu=mtu, mps=mps, initial_credits=initial_credits,
    )
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    self._pending_le_connect[ident] = fut
    pdu = encode_le_signaling(0x14, ident, encode_le_credit_request(req))
    sig_ch = self._connections[handle][CID_LE_SIGNALING]
    await sig_ch.send(pdu)
    resp: LECreditBasedConnectionResponse = await asyncio.wait_for(fut, timeout)
    if resp.result != 0x0000:
        raise L2CAPError(f"LE CoC connect failed: result=0x{resp.result:04X}")
    ch = LECoCChannel(
        connection_handle=handle, cid=scid, peer_cid=resp.dcid,
        hci=self._hci, mtu=min(mtu, resp.mtu), mps=min(mps, resp.mps),
        initial_credits=resp.initial_credits,
    )
    self._le_channels[scid] = ch
    self._connections[handle][scid] = ch
    return ch
```

(Adapt to actual `LECoCChannel.__init__` signature — read `ble.py` carefully.)

- [ ] **Step 3.2:** Tests using a fake LE signaling channel + canned Connect Response → assert channel is created with the negotiated params.
- [ ] **Step 3.3:** Commit.

---

## Task 4: `listen_le_coc_channel` (incoming)

**Files:**
- Modify: `pybluehost/l2cap/manager.py`
- Create: `tests/unit/l2cap/test_le_coc_listen.py`

- [ ] **Step 4.1:** Implement:

```python
def listen_le_coc_channel(self, psm: int, handler: Callable[[LECoCChannel], object]) -> None:
    self._le_listeners[psm] = handler

async def _handle_incoming_le_coc_request(
    self, handle: int, ident: int, req: LECreditBasedConnectionRequest,
) -> None:
    listener = self._le_listeners.get(req.le_psm)
    if listener is None:
        # Reply with "PSM not supported" (0x0002).
        await self._send_le_signaling(
            handle, 0x15, ident,
            encode_le_credit_response(LECreditBasedConnectionResponse(
                dcid=0, mtu=0, mps=0, initial_credits=0, result=0x0002,
            )),
        )
        return
    dcid = self._allocate_le_cid()
    our_mtu, our_mps, our_credits = 512, 251, 10
    await self._send_le_signaling(
        handle, 0x15, ident,
        encode_le_credit_response(LECreditBasedConnectionResponse(
            dcid=dcid, mtu=our_mtu, mps=our_mps, initial_credits=our_credits, result=0x0000,
        )),
    )
    ch = LECoCChannel(
        connection_handle=handle, cid=dcid, peer_cid=req.scid,
        hci=self._hci, mtu=min(our_mtu, req.mtu), mps=min(our_mps, req.mps),
        initial_credits=req.initial_credits,
    )
    self._le_channels[dcid] = ch
    self._connections[handle][dcid] = ch
    try:
        listener(ch)
    except Exception:
        logger.exception("LE CoC listener raised")
```

- [ ] **Step 4.2:** Tests: feed a request PDU into `_on_le_signaling`, assert handler called with a channel, assert response written.
- [ ] **Step 4.3:** Commit.

---

## Task 5: Flow control credits + disconnect

**Files:**
- Modify: `pybluehost/l2cap/manager.py`
- Create: `tests/unit/l2cap/test_le_coc_credits.py`

- [ ] **Step 5.1:** Wire incoming `LE_FLOW_CONTROL_CREDIT` to call `ch.add_credits(n)` on the matching channel (lookup by local CID == credit_pdu.cid? careful — verify whether the field is the local SCID or peer's CID. Per spec, `CID` is the source channel — sender's CID; so we need to find the channel whose `peer_cid == credit.cid`).
- [ ] **Step 5.2:** Add `LECoCChannel.close()` to send DISCONNECTION_REQUEST and wait for RESPONSE (or just-fire-and-forget if the peer doesn't reply). Existing `close()` may already exist — extend it.
- [ ] **Step 5.3:** Handle inbound `DISCONNECTION_REQUEST` for an LE CoC channel: close locally + send RESPONSE.
- [ ] **Step 5.4:** Tests + commit.

---

## Task 6: e2e via VirtualLink

**Files:**
- Create: `tests/e2e/test_le_coc_lifecycle.py`

Two `Stack.virtual()` instances paired via `VirtualLink` (BLE virtual transport). Central runs `listen_le_coc_channel`; peripheral runs `connect_le_coc_channel`. Verify:
- Connect succeeds, returns channel objects on both sides
- Data sent peripheral→central is received via `ch._events.on_data`
- Data central→peripheral works similarly
- Disconnect cleanly closes both sides

- [ ] **Step 6.1:** Write test; iterate until green.
- [ ] **Step 6.2:** Commit + STATUS.md row.

---

## Self-Review Checklist

- Spec coverage: each Task maps to a Core-spec PDU (0x06/0x07/0x14/0x15/0x16). Out-of-scope items (ECFC, Reconfigure) explicitly excluded.
- No placeholders. Each step shows actual code or precise behavior.
- Forward-compat with P.8: after this Plan, P.8 T2-T5 unblocks because `stack.l2cap.connect_le_coc_channel` and `listen_le_coc_channel` are available.
