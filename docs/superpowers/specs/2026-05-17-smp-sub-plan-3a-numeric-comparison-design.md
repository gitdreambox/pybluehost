# SMP Sub-Plan 3a — Numeric Comparison Design Spec

**Date**: 2026-05-17
**Scope**: PRD §5.4 Numeric Comparison association model for LE Secure Connections + BR/EDR Secure Connections
**Predecessors**: [Secure Connections (LE SC + BR/EDR SC)](../plans/2026-05-17-secure-connections.md)
**Successors**: Sub-Plan 3b (Passkey Entry), Sub-Plan 3c (OOB)

---

## 1. Goals

Add Numeric Comparison association model to the existing Secure Connections infrastructure. Both sides display a 6-digit code (`Va = g2(PKax, PKbx, Na, Nb) mod 10^6`) and the user confirms they match via `PairingDelegate.confirm_numeric(peer_addr, value)`. NC provides MITM protection unlike Just Works.

NC is **opt-in via `SecurityConfig.mitm_required=True`** (default False). When MITM is required AND both sides have a display+confirm IO capability AND SC is enabled, NC is selected. Otherwise pairing falls back to Just Works (Sub-Plan 2 path).

Passkey Entry and OOB are explicitly out of scope — they go in Sub-Plan 3b and 3c respectively.

## 2. Selection logic

### 2.1 `SecurityConfig.mitm_required`

New field in `pybluehost/ble/security.py`:

```python
@dataclass
class SecurityConfig:
    # existing fields...
    enable_secure_connections: bool = False
    mitm_required: bool = False  # NEW: triggers NC if IO caps support it
```

### 2.2 Selection table

Core 5.4 Vol 3 Part H §2.3.5.1 Table 2.8, abbreviated to the rows Sub-Plan 3a needs (NC eligibility only; Passkey/OOB rows handled in Sub-Plan 3b/3c):

| Initiator IO Cap | Responder IO Cap | local MITM | peer MITM | SC | → Model |
|------------------|------------------|------------|-----------|----|---------|
| DisplayYesNo (0x01) | DisplayYesNo (0x01) | yes | yes | yes | **NC** |
| DisplayYesNo | KeyboardDisplay (0x04) | yes | yes | yes | **NC** |
| KeyboardDisplay | DisplayYesNo | yes | yes | yes | **NC** |
| KeyboardDisplay | KeyboardDisplay | yes | yes | yes | **NC** |
| any other combo, OR no MITM on either side, OR no SC | | | | | Just Works (Sub-Plan 2 path) |

The MITM bit is bit 2 (mask 0x04) in `auth_req`. The SC bit is bit 3 (mask 0x08).

### 2.3 Selection function

```python
def _association_model(ctx: SMPPairingContext) -> str:
    """Return 'numeric_comparison' or 'just_works' for SC pairing.

    Passkey/OOB selection added in Sub-Plan 3b/3c.
    """
    if not _sc_negotiated(ctx):
        return "just_works"  # Legacy path; NC not applicable
    both_mitm = (ctx.local_auth_req & 0x04) and (ctx.peer_auth_req & 0x04)
    if not both_mitm:
        return "just_works"
    nc_caps = {IOCapability.DISPLAY_YES_NO, IOCapability.KEYBOARD_DISPLAY}
    if ctx.local_io_caps in nc_caps and ctx.peer_io_caps in nc_caps:
        return "numeric_comparison"
    return "just_works"
```

## 3. State machine extension

### 3.1 New state and events

```python
class SMPState(IntEnum):
    # existing 10 states...
    NUMERIC_COMPARE_PENDING = 10


class SMPEvent(IntEnum):
    # existing 18 events...
    NUMERIC_COMPARE_USER_CONFIRMED = 18
    NUMERIC_COMPARE_USER_REJECTED = 19
```

### 3.2 Transitions

When NC is selected after Phase 2.2:

```
RANDOM_EXCHANGE → NUMERIC_COMPARE_PENDING (after f5 derivation)
  action: compute Va = g2(PKax, PKbx, Na, Nb) % 1_000_000
          spawn task: delegate.confirm_numeric(peer_addr, Va)
          on True → fire(NUMERIC_COMPARE_USER_CONFIRMED)
          on False → fire(NUMERIC_COMPARE_USER_REJECTED)

NUMERIC_COMPARE_PENDING → DHKEY_CHECK (on NUMERIC_COMPARE_USER_CONFIRMED)
  action: continue SC Phase 2.3 — compute Ea/Eb, send Pairing_DHKey_Check
          (reuse existing _sc_initiator_recv_peer_random's Phase 2.3 entry)

NUMERIC_COMPARE_PENDING → FAILED (on NUMERIC_COMPARE_USER_REJECTED or TIMEOUT)
  action: send PAIRING_FAILED(reason=0x03)  # Authentication Requirements
          set pairing_complete exception

NUMERIC_COMPARE_PENDING universal failure transitions: PAIRING_FAILED_RX,
DISCONNECTED → FAILED (per Sub-Plan 1 pattern).

60-second timeout while waiting on delegate (user interaction).
```

### 3.3 Branching at Phase 2.2 exit

In `_sc_initiator_recv_peer_random` / `_sc_responder_recv_peer_random` (Sub-Plan 2 Task 9), after deriving `(mac_key, ltk_sc)`, branch on association model:

```python
async def _sc_initiator_recv_peer_random(ctx, *, pdu, **_kw):
    # ... existing Phase 2.2 logic (verify Cb, derive f5) ...

    model = _association_model(ctx)
    if model == "numeric_comparison":
        # Compute Va = g2(PKax, PKbx, Na, Nb), enter NC_PENDING
        ctx.state_machine._state = SMPState.NUMERIC_COMPARE_PENDING
        await _sc_compute_and_await_nc(ctx)
    else:
        # Just Works — existing Phase 2.3 entry (send Ea, state → DHKEY_CHECK)
        await _sc_send_dhkey_check_initiator(ctx)
```

Same pattern for `_sc_responder_recv_peer_random`.

### 3.4 `_sc_compute_and_await_nc`

```python
async def _sc_compute_and_await_nc(ctx):
    """Compute g2 value, present to user via delegate, fire confirmation event."""
    from pybluehost.ble.smp import SMPCrypto
    pkax = ctx.local_public_key[:32] if ctx.role == PairingRole.INITIATOR else ctx.peer_public_key[:32]
    pkbx = ctx.peer_public_key[:32] if ctx.role == PairingRole.INITIATOR else ctx.local_public_key[:32]
    # g2 returns 32-bit int per spec; modulo 10^6 for display
    g2_value = SMPCrypto.g2(pkax, pkbx, ctx.local_random if ctx.role == PairingRole.INITIATOR else ctx.peer_random,
                             ctx.peer_random if ctx.role == PairingRole.INITIATOR else ctx.local_random)
    numeric_value = g2_value % 1_000_000

    async def _await_user_confirm():
        try:
            delegate = ctx._delegate or AutoAcceptDelegate()
            confirmed = await delegate.confirm_numeric(ctx.peer_address, numeric_value)
        except Exception as exc:
            logger.warning("delegate.confirm_numeric raised: %s; rejecting NC", exc)
            confirmed = False
        if confirmed:
            await ctx.state_machine.fire(SMPEvent.NUMERIC_COMPARE_USER_CONFIRMED)
        else:
            await ctx.state_machine.fire(SMPEvent.NUMERIC_COMPARE_USER_REJECTED)

    asyncio.create_task(_await_user_confirm())
```

## 4. `PairingDelegate` extension

```python
class PairingDelegate(Protocol):
    async def confirm_just_works(self, peer_addr: BDAddress) -> bool: ...
    # NEW (Sub-Plan 3a):
    async def confirm_numeric(self, peer_addr: BDAddress, value: int) -> bool: ...


class AutoAcceptDelegate:
    async def confirm_just_works(self, peer_addr): return True
    # NEW:
    async def confirm_numeric(self, peer_addr, value): return True
```

Backward compatibility: when an existing user delegate lacks `confirm_numeric`, the SMP state machine catches `AttributeError` and treats it as auto-accept (preserving Sub-Plan 1/2 behavior).

`ctx._delegate` is plumbed from `SMPManager._delegate` (already exists from PRD 1.0 closure Plan).

## 5. BR/EDR side

`SSPManager.on_hci_event` already handles `USER_CONFIRMATION_REQUEST` (auto-accept). Sub-Plan 3a changes it to call the delegate:

```python
async def _on_user_confirmation_request(self, params: bytes) -> None:
    addr = BDAddress(bytes(reversed(params[:6])))
    numeric_value = int.from_bytes(params[6:10], "little")
    # Call delegate; default auto-accept if delegate has no confirm_numeric
    if self._delegate is not None and hasattr(self._delegate, "confirm_numeric"):
        try:
            accepted = await self._delegate.confirm_numeric(addr, numeric_value)
        except Exception:
            accepted = False
    else:
        accepted = True  # backward compat
    if accepted:
        await self._hci.send_command(_make_cmd(HCI_USER_CONFIRMATION_REQUEST_REPLY, bytes(reversed(addr.address))))
    else:
        await self._hci.send_command(_make_cmd(HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY, bytes(reversed(addr.address))))
```

SSPManager gains a `delegate` constructor kwarg if it doesn't already accept one (verify).

## 6. BondInfo: `authenticated=True` for NC

`_persist_bond` (Sub-Plan 2 Task 11) sets `BondInfo.authenticated=False` for SC Just Works. For NC, this should be `True` — NC provides MITM protection. Update:

```python
async def _persist_bond(ctx, **_kw):
    sc_mode = _sc_negotiated(ctx)
    # NEW: detect NC vs Just Works
    model = _association_model(ctx) if sc_mode else "legacy"
    authenticated = (model == "numeric_comparison")  # NC provides MITM; Just Works doesn't
    # ... rest of bond construction with authenticated=authenticated ...
```

(Sub-Plan 3b will extend `authenticated` logic for Passkey Entry which is also MITM-protected.)

## 7. File changes

| Type | Path | Responsibility |
|------|------|---------------|
| Modify | `pybluehost/ble/security.py` | `SecurityConfig.mitm_required: bool = False` |
| Modify | `pybluehost/ble/smp.py` | `SMPState.NUMERIC_COMPARE_PENDING`, `SMPEvent.NUMERIC_COMPARE_USER_CONFIRMED/REJECTED`; extend `PairingDelegate` Protocol; `AutoAcceptDelegate.confirm_numeric` |
| Modify | `pybluehost/ble/_smp_state.py` | `_association_model()` selection; NC branch in `_sc_initiator/responder_recv_peer_random`; `_sc_compute_and_await_nc`; NC transitions; `_persist_bond` sets `authenticated=True` for NC |
| Modify | `pybluehost/classic/gap.py` | `SSPManager` accepts `delegate` kwarg; `_on_user_confirmation_request` calls `delegate.confirm_numeric` |
| Modify | `pybluehost/stack.py` | Pass delegate to `SSPManager(...)` |
| Create | `tests/unit/ble/test_smp_numeric_comparison.py` | NC selection + delegate + state transitions + g2 computation |
| Create | `tests/unit/classic/test_ssp_numeric_comparison.py` | SSPManager delegate dispatch for NC |
| Create | `tests/integration/test_pairing_le_sc_nc_loopback.py` | LE SC NC E2E with auto-accept delegate |

## 8. Test strategy

### Unit (~8 tests in 2 files)

- `SecurityConfig.mitm_required` defaults False, overrideable
- `PairingDelegate.confirm_numeric` is part of Protocol
- `AutoAcceptDelegate.confirm_numeric` returns True
- `_association_model` returns NC when both MITM + both DisplayYesNo + SC negotiated
- `_association_model` returns Just Works when MITM off
- `_association_model` returns Just Works when SC off (Legacy path)
- `_association_model` returns Just Works when IO Caps insufficient (e.g. one NoInputNoOutput)
- SC NC state machine enters NC_PENDING after Random exchange
- SC NC state machine advances to DHKEY_CHECK on user confirmed
- SC NC state machine fails on user rejected (PAIRING_FAILED reason=0x03 sent)
- SSPManager calls `delegate.confirm_numeric(addr, numeric_value)` on User_Confirmation_Request
- SSPManager sends negative-reply when delegate returns False
- SSPManager auto-accepts when delegate has no `confirm_numeric` (backward compat)

### Loopback E2E (~2 tests)

- Two Stack.virtual() with `mitm_required=True` + `DisplayYesNo` IO cap → NC pairing succeeds; bond.authenticated=True; same f5 LTK on both sides
- Same setup but Responder's delegate returns False → both sides reach FAILED state with reason=0x03

### Manual hardware

- Real phone (Android in NC mode) pairing with PyBlueHost — out of scope for CI; documented for manual verification

## 9. Known risks

1. **`SMPCrypto.g2` output format**: spec calls for 32-bit big-endian integer modulo 10^6. Verify the existing `g2` implementation in `pybluehost/ble/smp.py` — if it returns bytes, we need to convert. Verify against Core 5.4 Vol 3 Part H Appendix D test vectors.

2. **Public key X coordinate ordering for g2**: `g2(U, V, X, Y)` per spec: U=Initiator public X, V=Responder public X, X=Na, Y=Nb. Both sides compute the SAME g2 (it's symmetric in the appropriate sense). Verify by inspection.

3. **Delegate timing**: `confirm_numeric` is async and may take seconds (user reaction). The state machine's 60s timeout from `NUMERIC_COMPARE_PENDING` must fire correctly via existing `StateMachine.set_timeout` API.

4. **Delegate exception handling**: if user delegate raises (programmer error), we treat as reject. Document this in the Protocol docstring.

5. **BR/EDR `_on_user_confirmation_request` race**: the controller sends `User_Confirmation_Request` and expects a reply within ~30s. If our delegate stalls, the controller may timeout and abort SSP. Same 60s soft timeout warning as for LE SC.

6. **Backward compat for `PairingDelegate` consumers**: external code subclassing the Protocol won't have `confirm_numeric`. Our state machine uses `hasattr` / try-catch fallback to auto-accept. Document this in the API docs.

## 10. Acceptance criteria

- [ ] `SecurityConfig.mitm_required` field added; defaults False
- [ ] `PairingDelegate.confirm_numeric` Protocol method + `AutoAcceptDelegate` impl
- [ ] `_association_model` selection function for SC NC vs Just Works
- [ ] `SMPState.NUMERIC_COMPARE_PENDING` + 2 NC events
- [ ] SC NC state machine: enter NC_PENDING after Random; await delegate; on confirm → DHKEY_CHECK; on reject → FAILED(0x03)
- [ ] `BondInfo.authenticated=True` for NC pairing (vs False for Just Works)
- [ ] `SSPManager` BR/EDR User_Confirmation_Request delegate dispatch
- [ ] Loopback E2E: two Stack.virtual() instances with NC settings pair successfully; reject path raises
- [ ] Full suite: only the 3 pre-existing USB diagnostics failures; coverage ≥ 85%
- [ ] STATUS.md updated to mark Sub-Plan 3a complete

## 11. Out of scope (deferred to Sub-Plan 3b/3c)

| Item | Future Plan |
|------|-------------|
| Passkey Entry (Legacy 20-round + SC 20-round) | Sub-Plan 3b |
| OOB (Legacy + SC) | Sub-Plan 3c |
| DisplayOnly / KeyboardOnly IO caps and their selection rows | Sub-Plan 3b |
| Full IO Capability matrix (all 5x5 combinations) | Sub-Plan 3b/3c |
| Real-hardware automated verification | Independent Plan |
