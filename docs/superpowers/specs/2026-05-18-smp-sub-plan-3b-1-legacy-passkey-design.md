# SMP Sub-Plan 3b-1 — Legacy Passkey Entry Design Spec

**Date**: 2026-05-18
**Scope**: PRD §5.4 Legacy (non-SC) Passkey Entry association model
**Predecessors**: [Secure Connections](../plans/2026-05-17-secure-connections.md), [SMP Sub-Plan 3a (Numeric Comparison)](../plans/2026-05-18-smp-sub-plan-3a-numeric-comparison.md)
**Successors**: Sub-Plan 3b-2 (SC Passkey Entry — 20-round commit), Sub-Plan 3c (OOB)

---

## 1. Goals

Add the Legacy (non-SC) Passkey Entry association model. The 6-digit passkey replaces the all-zero TK used by Legacy Just Works; everything downstream (c1, s1, STK, key distribution, reconnection) is unchanged. MITM protection is achieved because each side must compute the same TK to produce a matching c1 Confirm — an attacker who doesn't observe the displayed value cannot.

Passkey is **opt-in via `SecurityConfig.mitm_required=True`** (already added in Sub-Plan 3a). Together with both-sides MITM in `auth_req` and a qualifying IO-capability pair, Legacy pairing flips from Just Works to Passkey Entry.

SC Passkey (the 20-round commit protocol) is **explicitly out of scope** — Sub-Plan 3b-2.

## 2. Selection logic

### 2.1 IO-capability rows in scope

Per Core 5.4 Vol 3 Part H §2.3.5.1 Table 2.7 (Legacy IO Capability ↔ Method), restricted to the cases this sub-plan covers:

| Local IO | Peer IO | Local role |
|---|---|---|
| DisplayOnly / DisplayYesNo | KeyboardOnly | display |
| DisplayOnly / DisplayYesNo | KeyboardDisplay | display |
| KeyboardOnly | DisplayOnly / DisplayYesNo / KeyboardDisplay | input |
| KeyboardDisplay | DisplayOnly / DisplayYesNo / KeyboardOnly | display |
| KeyboardDisplay | KeyboardDisplay | **Initiator** displays, **Responder** inputs |

**Deliberately out of scope** (fall through to Just Works):
- Both KeyboardOnly (spec defines "both input"; practically unused).
- Either side `NO_INPUT_NO_OUTPUT`.

### 2.2 `_association_model()` extension

`pybluehost/ble/_smp_state.py`:

```python
def _association_model(ctx) -> str:
    """Returns: 'just_works' | 'numeric_comparison' | 'passkey_entry'."""
    if _sc_negotiated(ctx):
        # existing NC/JW selection (Sub-Plan 3a) ...
        return "just_works"

    # Legacy path — Sub-Plan 3b-1 addition
    both_mitm = bool(ctx.local_auth_req & 0x04) and bool(ctx.peer_auth_req & 0x04)
    if not both_mitm:
        return "just_works"
    if not _passkey_capable(ctx.local_io_caps, ctx.peer_io_caps):
        return "just_works"
    return "passkey_entry"
```

A pair is *passkey-capable* iff neither side is `NO_INPUT_NO_OUTPUT`, at least one can display (`DISPLAY_ONLY`, `DISPLAY_YES_NO`, `KEYBOARD_DISPLAY`), and at least one can input (`KEYBOARD_ONLY`, `KEYBOARD_DISPLAY`). Both-KeyboardOnly is rejected by the capability check.

### 2.3 `_passkey_local_role()`

```python
def _passkey_local_role(ctx) -> str:
    """Returns 'display' or 'input'. Only meaningful when method == 'passkey_entry'."""
```

Rules:
- If local can display and peer can input but not vice-versa → `display`.
- If local can input and peer can display but not vice-versa → `input`.
- If both are `KEYBOARD_DISPLAY` → Initiator `display`, Responder `input` (Core spec rule).

## 3. Delegate signature normalization

Existing `PairingDelegate` methods don't include `peer_addr`. Normalized to match the Sub-Plan 3a `confirm_numeric(peer_addr, value)` precedent:

```python
class PairingDelegate(Protocol):
    async def confirm_pairing(self, handle: int, io_cap: int) -> bool: ...
    async def confirm_numeric(self, peer_addr: BDAddress, value: int) -> bool: ...
    async def display_passkey(self, peer_addr: BDAddress, passkey: int) -> None: ...
    async def get_passkey(self, peer_addr: BDAddress) -> int: ...
    async def confirm_passkey(self, peer_addr: BDAddress, passkey: int) -> bool: ...
```

`AutoAcceptDelegate`:
- `display_passkey` → no-op.
- `get_passkey` → returns `0` (deterministic, but won't match a randomly generated value — real tests use `_FixedPasskeyDelegate`).
- `confirm_passkey` → returns `True`.

**Cancellation semantics:** any exception from `get_passkey` (timeout, user cancel, validation error) is caught and translated to `PASSKEY_USER_REJECTED`. Return values outside `[0, 999_999]` are also treated as rejection.

The three passkey methods have no production callers today — purely renaming placeholders. Stale references will be updated in lock-step with the rename.

## 4. State machine extension

### 4.1 New state and events

```python
class SMPState(IntEnum):
    ...
    NUMERIC_COMPARE_PENDING = 10
    PASSKEY_INPUT_PENDING = 11        # NEW

class SMPEvent(IntEnum):
    ...
    NUMERIC_COMPARE_USER_CONFIRMED = 18
    NUMERIC_COMPARE_USER_REJECTED = 19
    PASSKEY_USER_ENTERED = 20         # NEW (carries int 0..999_999)
    PASSKEY_USER_REJECTED = 21        # NEW
```

### 4.2 Display role — action-level branching

No new top-level transition. The existing `FEATURE_EXCHANGE + PAIRING_RSP_RX → CONFIRMING` (Initiator) and `IDLE + PAIRING_REQ_RX → CONFIRMING` (Responder) transitions remain. Their actions gain a Passkey branch:

```python
# _initiator_recv_pairing_response (after Phase 1, Initiator side):
model = _association_model(ctx)
if model == "passkey_entry":
    role = _passkey_local_role(ctx)
    if role == "display":
        ctx.passkey = secrets.randbelow(1_000_000)
        await delegate.display_passkey(ctx.peer_address, ctx.passkey)
        ctx.tk = ctx.passkey.to_bytes(16, "little")
        # ... existing c1 confirm send path follows ...
        return
    # role == "input":
    ctx.state_machine._state = SMPState.PASSKEY_INPUT_PENDING
    await _passkey_await_user_input(ctx)
    return
# ... existing JW / SC paths unchanged ...
```

Symmetric branch in `_responder_recv_pairing_request`. The Responder must send `Pairing_Response` first regardless of role (the Initiator depends on it to progress); the Input-role Responder then overrides `_state` to `PASSKEY_INPUT_PENDING`.

### 4.3 Input role — `_passkey_await_user_input()`

Mirrors `_sc_compute_and_await_nc` from Sub-Plan 3a:

```python
async def _passkey_await_user_input(ctx) -> None:
    delegate = getattr(ctx, "_delegate", None) or AutoAcceptDelegate()

    async def _await():
        try:
            value = await delegate.get_passkey(ctx.peer_address)
        except AttributeError:
            value = 0  # backward-compat for delegates missing get_passkey
        except Exception as exc:
            logger.warning("delegate.get_passkey raised: %s; rejecting", exc)
            await ctx.state_machine.fire(SMPEvent.PASSKEY_USER_REJECTED)
            return
        if not isinstance(value, int) or not 0 <= value <= 999_999:
            await ctx.state_machine.fire(SMPEvent.PASSKEY_USER_REJECTED)
            return
        ctx.passkey = value
        await ctx.state_machine.fire(SMPEvent.PASSKEY_USER_ENTERED)

    asyncio.create_task(_await())
```

### 4.4 Transitions registered for both roles

```python
sm.add_transition(PASSKEY_INPUT_PENDING, PAIRING_CONFIRM_RX,
                  PASSKEY_INPUT_PENDING,
                  action=_passkey_buffer_peer_confirm)
sm.add_transition(PASSKEY_INPUT_PENDING, PASSKEY_USER_ENTERED,
                  CONFIRMING,
                  action=lambda **kw: _passkey_user_entered(ctx, **kw))
sm.add_transition(PASSKEY_INPUT_PENDING, PASSKEY_USER_REJECTED,
                  FAILED,
                  action=lambda **kw: _on_failed(ctx, reason=0x01, **kw))
sm.set_timeout(PASSKEY_INPUT_PENDING, 60.0, TIMEOUT)
```

`PASSKEY_INPUT_PENDING` is added to the universal-failure-transitions tuple so `PAIRING_FAILED_RX`, `TIMEOUT`, and `DISCONNECTED` route to `FAILED` automatically.

### 4.5 `_passkey_buffer_peer_confirm` and `_passkey_user_entered`

```python
async def _passkey_buffer_peer_confirm(ctx, *, pdu, **_kw):
    """Initiator (Display) may send Pairing_Confirm before we have user-entered our passkey.
    Buffer it so _passkey_user_entered can validate later."""
    ctx.peer_confirm = pdu.confirm_value


async def _passkey_user_entered(ctx, **_kw):
    """User entered passkey on the Input side. Set TK, compute and send our Confirm.
    The peer Confirm may already be in ctx.peer_confirm (buffered) or arrive later."""
    ctx.tk = ctx.passkey.to_bytes(16, "little")
    ctx.local_random = os.urandom(16)
    preq, pres = ctx.saved_pairing_request[:7], ctx.saved_pairing_response[:7]
    ia = _local_address_bytes(ctx) if ctx.role == INITIATOR else _peer_address_bytes(ctx)
    ra = _peer_address_bytes(ctx) if ctx.role == INITIATOR else _local_address_bytes(ctx)
    ctx.local_confirm = SMPCrypto.c1(ctx.tk, ctx.local_random, preq, pres, 0, 0, ia, ra)
    await ctx.send(SMPPairingConfirm(confirm_value=ctx.local_confirm).to_bytes())
```

Once back in `CONFIRMING`, the existing transitions handle Pairing_Random exchange and c1 verification (which now uses the non-zero TK).

## 5. Data flow

### A) Initiator Display, Responder Input

```
I: send Pairing_Request                              [FEATURE_EXCHANGE]
R: recv Pairing_Request, send Pairing_Response,      [PASSKEY_INPUT_PENDING]
   spawn get_passkey(peer_addr)
I: recv Pairing_Response, generate passkey=N,
   await display_passkey(peer_addr, N), TK=N_LE,
   compute & send Pairing_Confirm                    [CONFIRMING]
R: recv Pairing_Confirm → buffer in ctx.peer_confirm [PASSKEY_INPUT_PENDING]
   user enters N → PASSKEY_USER_ENTERED              [CONFIRMING]
R: set TK=N_LE, compute & send own Confirm
… normal Phase-2 Random + c1 verify + STK encrypt continues …
```

### B) Initiator Input, Responder Display

```
I: send Pairing_Request                              [FEATURE_EXCHANGE]
R: recv Pairing_Request, set TK=N_LE, generate N,
   await display_passkey, send Pairing_Response       [CONFIRMING]
I: recv Pairing_Response → state PASSKEY_INPUT_PENDING
   spawn get_passkey(peer_addr)
I: user enters N → PASSKEY_USER_ENTERED              [CONFIRMING]
   set TK, compute & send Pairing_Confirm
R: recv Pairing_Confirm via existing CONFIRMING transition
…
```

### C) Both KeyboardDisplay

Per spec, Initiator displays. Resolves to case A.

### D) Wrong passkey on Input side

```
… through scenario A or B …
Input side computes Confirm with WRONG TK and sends it.
Display side recv Pairing_Confirm, recv Pairing_Random; c1 verify fails →
  existing _on_failed(ctx, reason=0x04) → FAILED, Pairing_Failed(0x04) sent.
```

## 6. Error & edge handling

| Event in `PASSKEY_INPUT_PENDING` | Handling |
|---|---|
| `PASSKEY_USER_ENTERED` | set TK, compute and send local Confirm; transitions to `CONFIRMING` |
| `PASSKEY_USER_REJECTED` | `_on_failed(reason=0x01 Passkey_Entry_Failed)` |
| `PAIRING_CONFIRM_RX` | buffer peer's value in `ctx.peer_confirm`; stay in state |
| `PAIRING_RANDOM_RX` | protocol violation → `FAILED(reason=0x08)` |
| `PAIRING_FAILED_RX`, `DISCONNECTED`, `TIMEOUT` | universal-failure loop → `FAILED` |

Other edges:
- `display_passkey` raises → log warning, continue with the generated passkey. Display-side cannot fail the protocol on a UI glitch.
- Wrong passkey entered → c1 mismatch on whichever side validates first → existing `_on_failed(0x04)` path. Distinct from cancellation (`0x01`) so the delegate can tell *why* pairing failed.
- Delegate returns out-of-range value → wrapped as `PASSKEY_USER_REJECTED`.

## 7. `_persist_bond` authenticated flag

Sub-Plan 3a sets `BondInfo.authenticated = (_association_model == "numeric_comparison")`. Extend to:

```python
authenticated = _association_model(ctx) in {"numeric_comparison", "passkey_entry"}
```

Applies in the Legacy branch of `_persist_bond` too (currently hardcoded to `authenticated=False` for Legacy).

## 8. File changes

| Action | Path | Responsibility |
|---|---|---|
| Modify | `pybluehost/ble/smp.py` | New `SMPState.PASSKEY_INPUT_PENDING`; two new `SMPEvent` values; rename delegate methods to include `peer_addr`; AutoAccept impls |
| Modify | `pybluehost/ble/_smp_state.py` | Extend `_association_model`; add `_passkey_capable`, `_passkey_local_role`, `_passkey_await_user_input`, `_passkey_buffer_peer_confirm`, `_passkey_user_entered`; branch Phase-1 actions on association model; register transitions + timeout + universal-failure inclusion; update `_persist_bond` |
| Create | `tests/unit/ble/test_smp_passkey_legacy.py` | Selection + role + state-transition unit tests (~12) |
| Create | `tests/integration/test_pairing_legacy_passkey_loopback.py` | Two-stack loopback (success + wrong-passkey paths) |

## 9. Test strategy

### Unit (~12 tests)

- `_association_model` returns `"passkey_entry"` for in-scope rows (DisplayYesNo×KeyboardOnly, KeyboardDisplay×KeyboardDisplay, etc.).
- `_association_model` returns `"just_works"` when MITM unset on either side, when either side is `NO_INPUT_NO_OUTPUT`, or when both are KeyboardOnly.
- `_passkey_local_role` returns `display` / `input` per §2.3 table.
- Display action: generates 6-digit value, sets `ctx.tk = value.to_bytes(16, "little")`, calls `display_passkey(peer_addr, value)`, sends Pairing_Confirm.
- Input action: enters `PASSKEY_INPUT_PENDING`, spawns delegate task, fires `PASSKEY_USER_ENTERED` on int in range, fires `PASSKEY_USER_REJECTED` on exception or out-of-range.
- `PAIRING_CONFIRM_RX` while in `PASSKEY_INPUT_PENDING` stashes peer_confirm.
- `PASSKEY_USER_ENTERED` transition computes c1 with the entered passkey and sends Pairing_Confirm.
- `PASSKEY_USER_REJECTED` transition emits `Pairing_Failed(0x01)`.

### Integration (2 tests) — `tests/integration/test_pairing_legacy_passkey_loopback.py`

- `_FixedPasskeyDelegate(passkey=N)` on both sides, IO caps DisplayYesNo×KeyboardOnly, `mitm_required=True`, `enable_secure_connections=False`. Pairing succeeds; both bonds `authenticated=True`; STK-derived LTKs match.
- Same setup but Input-side delegate returns a different passkey → pairing fails with reason `0x04` (RuntimeError "SMP pairing failed (reason=4)").

### Manual / out of scope

- BR/EDR Passkey Entry SSP (`User_Passkey_Request` / `User_Passkey_Notification`) — separate Plan.
- Real-hardware verification with phone in Passkey mode — separate Plan.

## 10. Known risks

1. **Confirm arrival before user entry on Input side** — explicitly handled via the `PAIRING_CONFIRM_RX → PASSKEY_INPUT_PENDING` self-transition that buffers `ctx.peer_confirm`. Tested directly.
2. **TK byte order** — Core 5.4 Vol 3 Part H §2.3.5.4 specifies the passkey as a 6-digit decimal value encoded as a 32-bit little-endian integer, zero-padded to 16 bytes. Verified against existing c1 implementation by passing `passkey.to_bytes(16, "little")`.
3. **60 s timeout vs cumulative 30 s spec timeout** — Core 5.4 Vol 3 Part H §3.4 requires the *cumulative* SMP transaction not exceed 30 s, but allows user-interaction states to extend it. Using 60 s on `PASSKEY_INPUT_PENDING` is consistent with mainstream stacks (BlueZ, iOS use similar) and reflects realistic 6-digit typing time. If a peer enforces strict 30 s, pairing aborts via `PAIRING_FAILED_RX` from peer — which already routes to `FAILED` via the universal loop.
4. **Both-side `delegate.get_passkey` returning `0` (AutoAccept default)** — both sides would set TK=0 (same as Just Works), and Confirm validation would *pass* but the bond would *not* be MITM-protected despite being marked `authenticated=True`. Mitigation: documentation in `AutoAcceptDelegate` makes this clear; real tests use `_FixedPasskeyDelegate`. AutoAccept is for delegate-shape tests, not for end-to-end Passkey simulation.
5. **KbDisp×KbDisp Initiator-displays rule** — implemented in `_passkey_local_role` and covered by a dedicated unit test.

## 11. Acceptance criteria

- [ ] `_association_model()` returns `"passkey_entry"` for in-scope Legacy IO combinations with MITM on both sides.
- [ ] `_passkey_local_role()` resolves correctly across the §2.3 table.
- [ ] `PairingDelegate.display_passkey`, `get_passkey`, `confirm_passkey` accept `peer_addr` as first param.
- [ ] `SMPState.PASSKEY_INPUT_PENDING` (=11) and the two new events (=20, =21) exist.
- [ ] Display side: random 6-digit passkey generation, `display_passkey` call, TK derivation, Pairing_Confirm send.
- [ ] Input side: enter `PASSKEY_INPUT_PENDING`, await delegate, fire confirm/reject event.
- [ ] Buffered peer Confirm: `PAIRING_CONFIRM_RX` while in `PASSKEY_INPUT_PENDING` stashes correctly.
- [ ] `PASSKEY_USER_ENTERED` action computes c1 with the entered passkey, sends own Confirm.
- [ ] `PASSKEY_USER_REJECTED` action emits `Pairing_Failed(0x01)`.
- [ ] `_persist_bond` sets `authenticated=True` for `passkey_entry`.
- [ ] Loopback E2E (DisplayYesNo×KeyboardOnly): success + wrong-passkey-fails paths pass.
- [ ] Full suite green minus pre-existing USB-diagnostics failures.
- [ ] STATUS.md updated to mark Sub-Plan 3b-1 ✅.

## 12. Out of scope (deferred)

| Item | Future Plan |
|---|---|
| SC Passkey Entry (20-round commit, f4-bit-by-bit reveal) | Sub-Plan 3b-2 |
| OOB (Legacy + SC) | Sub-Plan 3c |
| Both-KeyboardOnly IO pair (rare, both-input semantics) | None planned — fall through to JW |
| BR/EDR Passkey Entry SSP (`User_Passkey_Request`/`User_Passkey_Notification`) | Independent Plan |
| Real-hardware verification with phone in Passkey mode | Independent Plan |
