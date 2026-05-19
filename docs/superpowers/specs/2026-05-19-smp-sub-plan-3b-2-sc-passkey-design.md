# SMP Sub-Plan 3b-2 — SC Passkey Entry Design Spec

**Date**: 2026-05-19
**Scope**: PRD §5.4 LE Secure Connections Passkey Entry — the 20-round bit-by-bit commit protocol
**Predecessors**: [Secure Connections](../plans/2026-05-17-secure-connections.md), [Sub-Plan 3a NC](../plans/2026-05-18-smp-sub-plan-3a-numeric-comparison.md), [Sub-Plan 3b-1 Legacy Passkey](../plans/2026-05-18-smp-sub-plan-3b-1-legacy-passkey.md)
**Successors**: Sub-Plan 3c (OOB)

---

## 1. Goals

Add LE Secure Connections Passkey Entry on top of the existing SC infrastructure. The 20-round commit protocol reveals one passkey bit per round through an f4 commitment, providing MITM protection equivalent to a 1-in-1,000,000 brute-force window per pairing session.

Selection rules differ from Legacy Passkey only in that `DisplayYesNo×KeyboardDisplay` and `KeyboardDisplay×KeyboardDisplay` resolve to **NC** in SC (Sub-Plan 3a) rather than Passkey. All other Passkey-capable IO pairs in 3b-1 remain Passkey in 3b-2.

3b-2 reuses the delegate plumbing, role-selection, passkey-resolution, and `PASSKEY_INPUT_PENDING` state from 3b-1. The new surface is one extra state (`PASSKEY_SC_ROUND`), per-round bit extraction, and four role/subphase-dispatched actions.

Both-KeyboardOnly remains deliberately out of scope (consistent with 3b-1). SC Passkey on BR/EDR (controller-driven `User_Passkey_Request`/`User_Passkey_Notification`) is a separate Plan.

## 2. Selection logic

### 2.1 `_association_model()` extension

Extending the SC branch (Sub-Plan 3a path) in `pybluehost/ble/_smp_state.py`:

```python
if _sc_negotiated(ctx):
    if not both_mitm:
        return "just_works"
    nc_caps = {int(IOCapability.DISPLAY_YES_NO), int(IOCapability.KEYBOARD_DISPLAY)}
    if int(ctx.local_io_caps) in nc_caps and int(ctx.peer_io_caps) in nc_caps:
        return "numeric_comparison"
    # NEW (Sub-Plan 3b-2): SC Passkey for remaining qualifying pairs
    if _passkey_capable(int(ctx.local_io_caps), int(ctx.peer_io_caps)):
        return "passkey_entry"
    return "just_works"

# Legacy branch unchanged (Sub-Plan 3b-1)
```

The Legacy branch (where SC is not negotiated) is unchanged.

### 2.2 Selection table (in scope)

Per Core 5.4 Vol 3 Part H §2.3.5.1 Table 2.8 — SC Passkey rows after NC has already claimed the NC-eligible pairs:

| Initiator IO | Responder IO | Local role (Initiator) |
|---|---|---|
| DisplayOnly | KeyboardOnly | display |
| DisplayOnly | KeyboardDisplay | display |
| DisplayYesNo | KeyboardOnly | display |
| KeyboardOnly | DisplayOnly | input |
| KeyboardOnly | DisplayYesNo | input |
| KeyboardOnly | KeyboardDisplay | input |
| KeyboardDisplay | DisplayOnly | display |
| KeyboardDisplay | KeyboardOnly | display |

Note that `DisplayYesNo×KeyboardDisplay` and `KeyboardDisplay×KeyboardDisplay` resolve to NC, not Passkey, so they are NOT in this table.

`KeyboardOnly×KeyboardOnly` is out of scope (consistent with 3b-1). `_passkey_capable` (from 3b-1) already rejects it and falls through to Just Works.

`_passkey_local_role()` from 3b-1 is reused unchanged. The `KEYBOARD_DISPLAY × KEYBOARD_DISPLAY` clause in that function is dead for SC (NC claims that pair) but stays for Legacy.

## 3. Delegate handling

Fully reused from 3b-1:

- **Display role**: `delegate.display_passkey(peer_addr, passkey)` called once at entry; the value lives in `ctx.passkey` for all 20 rounds.
- **Input role**: `PASSKEY_INPUT_PENDING` state (reused), `_passkey_await_user_input` spawns `delegate.get_passkey` task, fires `PASSKEY_USER_ENTERED` / `PASSKEY_USER_REJECTED`.
- **Test affordance**: `_passkey_resolve_display_value` (from 3b-1) checks for a `delegate.passkey: int` attribute first; falls back to `secrets.randbelow(1_000_000)`. Loopback tests use a `_FixedPasskeyDelegate(passkey=N)` on both sides.

The `PASSKEY_USER_ENTERED` action — currently routes to `CONFIRMING` and computes Legacy c1 — gets a new branch: if `_sc_negotiated(ctx)` → set state to `PASSKEY_SC_ROUND` with `round=1`, `round_phase="AWAIT_PEER_CONFIRM"` (Responder Input) or send first `Ca_1` and stay on `AWAIT_PEER_CONFIRM` (Initiator Input).

## 4. State machine extension

### 4.1 New state

```python
class SMPState(IntEnum):
    ...
    NUMERIC_COMPARE_PENDING = 10
    PASSKEY_INPUT_PENDING = 11
    PASSKEY_SC_ROUND = 12       # NEW
```

No new `SMPEvent` values — reuses existing `PAIRING_CONFIRM_RX` and `PAIRING_RANDOM_RX`. The two new reflexive transitions on `PASSKEY_SC_ROUND` dispatch on `ctx.passkey_round_phase` and `ctx.role`.

### 4.2 Round state on ctx

```python
ctx.passkey: int                  # 0..999_999 (set at entry by Display side or PASSKEY_USER_ENTERED)
ctx.passkey_round: int            # 1..20
ctx.passkey_round_phase: str      # "AWAIT_PEER_CONFIRM" | "AWAIT_PEER_RANDOM"
ctx.passkey_local_random: bytes   # current round's Na_i or Nb_i (16 bytes)
ctx.passkey_local_confirm: bytes  # current round's Ca_i or Cb_i (16 bytes; for own verification audit)
ctx.passkey_peer_confirm: bytes   # received peer Confirm for current round
ctx.passkey_peer_random: bytes    # received peer Random for current round
```

### 4.3 Bit extraction

Per Core 5.4 Vol 3 Part H §2.3.5.6.4 and §2.2.6:
- The passkey is a 20-bit value (6 decimal digits, max value 999,999 < 2^20).
- For round `i` (1-indexed, 1..20): `bit_i = (passkey >> (20 - i)) & 1` (round 1 uses the MSB).
- `r_i = bytes([0x80 | bit_i])` (1 byte, either `0x80` or `0x81`).
- `f4(U, V, X, Z)` is called with `Z = 0x80 | bit_i` (as int — existing `SMPCrypto.f4` signature already takes an int).

### 4.4 Transitions registered

```python
sm.add_transition(
    SMPState.PASSKEY_SC_ROUND, SMPEvent.PAIRING_CONFIRM_RX,
    SMPState.PASSKEY_SC_ROUND,                         # reflexive
    action=lambda **kw: _sc_passkey_recv_peer_confirm(ctx, **kw),
)
sm.add_transition(
    SMPState.PASSKEY_SC_ROUND, SMPEvent.PAIRING_RANDOM_RX,
    SMPState.PASSKEY_SC_ROUND,                         # reflexive; action overrides to DHKEY_CHECK / RANDOM_EXCHANGE on round 20
    action=lambda **kw: _sc_passkey_recv_peer_random(ctx, **kw),
)
```

Plus:
- `PASSKEY_SC_ROUND` added to the universal-failure-transitions tuple.
- `sm.set_timeout(SMPState.PASSKEY_SC_ROUND, 60.0, SMPEvent.TIMEOUT)`.

### 4.5 Entry from Phase 2.1

After Phase 2.1 (pubkey exchange + DHKey), the existing actions branch on association model:

- `_sc_initiator_recv_peer_public_key` (Initiator side, after DHKey computed): branch on `_association_model`:
  - `"numeric_comparison"` / `"just_works"`: existing (no change).
  - `"passkey_entry"` + role==`"display"`: call `_sc_passkey_initiator_display_enter(ctx)` which resolves passkey, displays, generates Na_1, computes Ca_1, sends `Pairing_Confirm(Ca_1)`, sets state to `PASSKEY_SC_ROUND`, `round=1`, `phase=AWAIT_PEER_CONFIRM`.
  - `"passkey_entry"` + role==`"input"`: set state to `PASSKEY_INPUT_PENDING`; spawn `_passkey_await_user_input`.

- `_sc_responder_recv_peer_public_key` (Responder side, after pubkey send + DHKey): branch on `_association_model`:
  - `"numeric_comparison"` / `"just_works"`: existing (computes Cb = f4(PKbx, PKax, Nb, 0), sends Pairing_Confirm — no change).
  - `"passkey_entry"` + role==`"display"`: call `_sc_passkey_responder_display_enter(ctx)` which resolves passkey, displays, sets state to `PASSKEY_SC_ROUND`, `round=1`, `phase=AWAIT_PEER_CONFIRM`. **Does not send anything** — Responder waits for Initiator's `Ca_1`.
  - `"passkey_entry"` + role==`"input"`: set state to `PASSKEY_INPUT_PENDING`; spawn `_passkey_await_user_input`.

### 4.6 `PASSKEY_USER_ENTERED` action — extended

The existing `_passkey_user_entered` (from 3b-1) currently transitions to `CONFIRMING` and computes Legacy c1. Extend with SC branch:

```python
async def _passkey_user_entered(ctx, **_kw):
    if _sc_negotiated(ctx):
        # Sub-Plan 3b-2: SC Passkey entry — start round 1
        ctx.state_machine._state = SMPState.PASSKEY_SC_ROUND
        ctx.passkey_round = 1
        ctx.passkey_round_phase = "AWAIT_PEER_CONFIRM"
        if ctx.role == PairingRole.INITIATOR:
            await _sc_passkey_send_round_confirm(ctx)
        # Responder: just await Initiator's Ca_1
        return
    # Legacy path (3b-1) — existing logic unchanged
    ...
```

The "transition target" registered in `register_transitions` for `PASSKEY_USER_ENTERED` is `CONFIRMING`. The Legacy action leaves state at CONFIRMING (matching target). The SC action overrides to `PASSKEY_SC_ROUND` — same override pattern used elsewhere in the file.

### 4.7 Per-round actions

```python
async def _sc_passkey_send_round_confirm(ctx):
    """Initiator-only helper: generate Na_i, compute Ca_i, send Pairing_Confirm.

    Called from entry, _passkey_user_entered (SC branch), and round-advancement
    on the Initiator side."""
    i = ctx.passkey_round
    bit = (ctx.passkey >> (20 - i)) & 1
    ctx.passkey_local_random = os.urandom(16)
    pkax = ctx.local_public_key[:32]
    pkbx = ctx.peer_public_key[:32]
    ctx.passkey_local_confirm = SMPCrypto.f4(pkax, pkbx, ctx.passkey_local_random, 0x80 | bit)
    await ctx.send(SMPPairingConfirm(confirm_value=ctx.passkey_local_confirm).to_bytes())


async def _sc_passkey_recv_peer_confirm(ctx, *, pdu, **_kw):
    """Reflexive PASSKEY_SC_ROUND + PAIRING_CONFIRM_RX action."""
    if ctx.passkey_round_phase != "AWAIT_PEER_CONFIRM":
        await _on_failed(ctx, reason=0x08)  # Unspecified
        return
    ctx.passkey_peer_confirm = pdu.confirm_value
    if ctx.role == PairingRole.INITIATOR:
        # Initiator received Cb_i → reveal Na_i
        await ctx.send(SMPPairingRandom(random_value=ctx.passkey_local_random).to_bytes())
    else:
        # Responder received Ca_i → compute and send Cb_i
        i = ctx.passkey_round
        bit = (ctx.passkey >> (20 - i)) & 1
        ctx.passkey_local_random = os.urandom(16)
        pkax = ctx.peer_public_key[:32]
        pkbx = ctx.local_public_key[:32]
        ctx.passkey_local_confirm = SMPCrypto.f4(pkbx, pkax, ctx.passkey_local_random, 0x80 | bit)
        await ctx.send(SMPPairingConfirm(confirm_value=ctx.passkey_local_confirm).to_bytes())
    ctx.passkey_round_phase = "AWAIT_PEER_RANDOM"


async def _sc_passkey_recv_peer_random(ctx, *, pdu, **_kw):
    """Reflexive PASSKEY_SC_ROUND + PAIRING_RANDOM_RX action."""
    if ctx.passkey_round_phase != "AWAIT_PEER_RANDOM":
        await _on_failed(ctx, reason=0x08)
        return
    ctx.passkey_peer_random = pdu.random_value
    i = ctx.passkey_round
    bit = (ctx.passkey >> (20 - i)) & 1
    if ctx.role == PairingRole.INITIATOR:
        # Verify Cb_i = f4(PKbx, PKax, Nb_i, 0x80|bit)
        pkax = ctx.local_public_key[:32]
        pkbx = ctx.peer_public_key[:32]
        expected = SMPCrypto.f4(pkbx, pkax, ctx.passkey_peer_random, 0x80 | bit)
        if expected != ctx.passkey_peer_confirm:
            await _on_failed(ctx, reason=0x04)
            return
        if i < 20:
            ctx.passkey_round = i + 1
            ctx.passkey_round_phase = "AWAIT_PEER_CONFIRM"
            await _sc_passkey_send_round_confirm(ctx)
        else:
            # Round 20 done; exit to Phase 2.3 (DHKey check)
            ctx.local_random = ctx.passkey_local_random  # Na_20
            ctx.peer_random = ctx.passkey_peer_random    # Nb_20
            await _sc_passkey_exit_to_dhkey_check_initiator(ctx)
    else:
        # Responder: verify Ca_i, then send Nb_i
        pkax = ctx.peer_public_key[:32]
        pkbx = ctx.local_public_key[:32]
        expected = SMPCrypto.f4(pkax, pkbx, ctx.passkey_peer_random, 0x80 | bit)
        if expected != ctx.passkey_peer_confirm:
            await _on_failed(ctx, reason=0x04)
            return
        await ctx.send(SMPPairingRandom(random_value=ctx.passkey_local_random).to_bytes())
        if i < 20:
            ctx.passkey_round = i + 1
            ctx.passkey_round_phase = "AWAIT_PEER_CONFIRM"
        else:
            ctx.peer_random = ctx.passkey_peer_random    # Na_20
            ctx.local_random = ctx.passkey_local_random  # Nb_20
            await _sc_passkey_exit_to_random_exchange_responder(ctx)
```

### 4.8 Exit helpers

```python
async def _sc_passkey_exit_to_dhkey_check_initiator(ctx):
    """Initiator exit after round 20: derive f5 with Na_20/Nb_20, then send Ea.

    Reuses existing _sc_send_dhkey_check_initiator from Sub-Plan 2/3a.
    """
    local_addr = _local_address_bytes(ctx)
    peer_addr = _peer_address_bytes(ctx)
    a1 = b"\x00" + local_addr
    a2 = b"\x00" + peer_addr
    mac_key, ltk = SMPCrypto.f5(ctx.dhkey, ctx.local_random, ctx.peer_random, a1, a2)
    ctx.mac_key = mac_key
    ctx.ltk_sc = ltk
    await _sc_send_dhkey_check_initiator(ctx)
    # _sc_send_dhkey_check_initiator already sets state to DHKEY_CHECK


async def _sc_passkey_exit_to_random_exchange_responder(ctx):
    """Responder exit after round 20: derive f5, state -> RANDOM_EXCHANGE.

    The existing RANDOM_EXCHANGE + PAIRING_DHKEY_CHECK_RX transition handles
    Initiator's incoming Ea. No PDU sent here.
    """
    local_addr = _local_address_bytes(ctx)
    peer_addr = _peer_address_bytes(ctx)
    a1 = b"\x00" + peer_addr   # Initiator = peer
    a2 = b"\x00" + local_addr  # Responder = local
    mac_key, ltk = SMPCrypto.f5(ctx.dhkey, ctx.peer_random, ctx.local_random, a1, a2)
    ctx.mac_key = mac_key
    ctx.ltk_sc = ltk
    ctx.state_machine._state = SMPState.RANDOM_EXCHANGE
```

## 5. Data flow

### A) Initiator Display, Responder Input

```
After Phase 2.1:
I: _sc_initiator_recv_peer_public_key → passkey_entry/display:
   passkey=N, display_passkey(peer, N)
   round=1; Na_1=random; Ca_1=f4(PKax,PKbx,Na_1, 0x80|bit_1)
   send Pairing_Confirm(Ca_1); state=PASSKEY_SC_ROUND
R: _sc_responder_recv_peer_public_key → passkey_entry/input:
   state=PASSKEY_INPUT_PENDING; spawn delegate.get_passkey
   on PASSKEY_USER_ENTERED: passkey=N (entered by user)
     state=PASSKEY_SC_ROUND; round=1; phase=AWAIT_PEER_CONFIRM

Round 1:
R: recv Pairing_Confirm(Ca_1) → peer_confirm=Ca_1
   Nb_1=random; Cb_1=f4(PKbx,PKax,Nb_1, 0x80|bit_1)
   send Pairing_Confirm(Cb_1); phase=AWAIT_PEER_RANDOM
I: recv Pairing_Confirm(Cb_1) → peer_confirm=Cb_1
   send Pairing_Random(Na_1); phase=AWAIT_PEER_RANDOM
R: recv Pairing_Random(Na_1) → verify Ca_1=f4(PKax,PKbx,Na_1, 0x80|bit_1)
   send Pairing_Random(Nb_1); round=2; phase=AWAIT_PEER_CONFIRM
I: recv Pairing_Random(Nb_1) → verify Cb_1=f4(PKbx,PKax,Nb_1, 0x80|bit_1)
   round=2; phase=AWAIT_PEER_CONFIRM; send Pairing_Confirm(Ca_2)
...
Round 20:
I (after verifying Cb_20): ctx.local_random=Na_20, peer_random=Nb_20
   derive f5; send Pairing_DHKey_Check(Ea); state=DHKEY_CHECK
R (after verifying Ca_20): ctx.local_random=Nb_20, peer_random=Na_20
   derive f5; state=RANDOM_EXCHANGE (awaits Initiator's Ea)
... existing Phase 2.3 (Ea/Eb verification) continues ...
```

### B) Initiator Input, Responder Display

```
After Phase 2.1:
I: _sc_initiator_recv_peer_public_key → input:
   state=PASSKEY_INPUT_PENDING; spawn delegate.get_passkey
   on PASSKEY_USER_ENTERED: passkey=N
     state=PASSKEY_SC_ROUND; round=1
     send Pairing_Confirm(Ca_1) (via _sc_passkey_send_round_confirm)
R: _sc_responder_recv_peer_public_key → display:
   passkey=N; display_passkey(peer, N)
   state=PASSKEY_SC_ROUND; round=1; phase=AWAIT_PEER_CONFIRM
   (no PDU sent — awaits Ca_1)

… same per-round flow as Case A ...
```

### C) Wrong passkey on either side

```
Round 1:
I sends Ca_1 with passkey bit_1=0
R receives Ca_1; computes Cb_1 with passkey bit_1=1 (wrong)
R sends Cb_1
I recv Cb_1; sends Na_1
R recv Na_1; verify Ca_1=f4(PKax,PKbx,Na_1, 0x80|wrong_bit_1) → MISMATCH
R sends Pairing_Failed(0x04)
… both sides reach FAILED via PAIRING_FAILED_RX universal transition.
```

Note: with mismatched passkeys, divergence is detected at the FIRST differing bit, typically round 1. The round-1 verification at the Responder's `PAIRING_RANDOM_RX` action is where the mismatch surfaces.

## 6. Error & edge handling

| Event in `PASSKEY_SC_ROUND` | Handling |
|---|---|
| `PAIRING_CONFIRM_RX` while `phase = AWAIT_PEER_CONFIRM` | Process per round action |
| `PAIRING_RANDOM_RX` while `phase = AWAIT_PEER_RANDOM` | Verify f4 + advance round or exit |
| Event in wrong subphase | `FAILED(0x08)` Unspecified — protocol violation |
| f4 verification mismatch | `FAILED(0x04)` Confirm Value Failed |
| `PAIRING_FAILED_RX`, `TIMEOUT`, `DISCONNECTED` | Universal-failure loop → `FAILED` |

`PASSKEY_SC_ROUND` joins the universal-failure tuple. 60-second timeout covers cumulative round time (20 rounds × ~50 ms in virtual transport ≪ 60 s; real radio adds tens of ms per round; well bounded).

Edges (consistent with 3b-1):
- Display delegate raises → log warning, proceed with generated passkey; Input side will fail c1 if user got the displayed value wrong.
- Wrong-passkey cancellation surfaces at round 1's `PAIRING_RANDOM_RX` action with `FAILED(0x04)`.
- Delegate's `get_passkey` returns out-of-range int → `PASSKEY_USER_REJECTED` → `FAILED(0x01)` (Passkey Entry Failed).

## 7. File changes

| Action | Path | Responsibility |
|---|---|---|
| Modify | `pybluehost/ble/smp.py` | Add `SMPState.PASSKEY_SC_ROUND = 12`. No new events. |
| Modify | `pybluehost/ble/_smp_state.py` | Extend `_association_model` SC branch for Passkey; add `_sc_passkey_send_round_confirm`, `_sc_passkey_recv_peer_confirm`, `_sc_passkey_recv_peer_random`, `_sc_passkey_exit_to_dhkey_check_initiator`, `_sc_passkey_exit_to_random_exchange_responder`, `_sc_passkey_initiator_display_enter`, `_sc_passkey_responder_display_enter`; branch `_sc_initiator_recv_peer_public_key` and `_sc_responder_recv_peer_public_key` on association model + role; extend `_passkey_user_entered` with SC branch; register `PASSKEY_SC_ROUND` reflexive transitions + 60s timeout + universal-failure inclusion |
| Create | `tests/unit/ble/test_smp_passkey_sc.py` | Selection, bit-extraction, per-round actions, exit-to-DHKey, error edges (~14 tests) |
| Create | `tests/integration/test_pairing_sc_passkey_loopback.py` | SC Passkey E2E (matching + mismatched passkey paths) |
| Modify | `docs/superpowers/STATUS.md` | Mark Sub-Plan 3b-2 complete |

## 8. Test strategy

### Unit (~14 tests)

- `_association_model` returns `"passkey_entry"` for SC + MITM + DisplayOnly×KeyboardOnly, DisplayYesNo×KeyboardOnly, KeyboardDisplay×KeyboardOnly.
- `_association_model` returns `"numeric_comparison"` (not Passkey) for SC + MITM + DisplayYesNo×DisplayYesNo, KeyboardDisplay×KeyboardDisplay, DisplayYesNo×KeyboardDisplay.
- `_association_model` returns `"just_works"` for SC + MITM but unsupported IO (e.g. NoInputNoOutput).
- Bit extraction: `(passkey >> (20 - i)) & 1` for i=1 (MSB) and i=20 (LSB) on a known passkey value.
- `_sc_passkey_send_round_confirm` (Initiator): generates 16-byte random, computes f4 with `0x80|bit_i`, sends Pairing_Confirm.
- `_sc_passkey_recv_peer_confirm` Initiator: stores peer_confirm, sends Pairing_Random with current Na.
- `_sc_passkey_recv_peer_confirm` Responder: computes own Cb, sends Pairing_Confirm.
- `_sc_passkey_recv_peer_random` Initiator: verifies peer Cb; on match advances round and sends next Ca; on mismatch fails with 0x04.
- `_sc_passkey_recv_peer_random` Responder: verifies peer Ca; on match sends Nb; on mismatch fails with 0x04.
- Wrong-subphase event → `FAILED(0x08)`.
- Round 20 exit Initiator: calls `_sc_send_dhkey_check_initiator` after f5 derivation.
- Round 20 exit Responder: state → RANDOM_EXCHANGE after f5 derivation; no PDU sent.
- `PASSKEY_USER_ENTERED` action SC branch: state → PASSKEY_SC_ROUND, round=1.
- `PASSKEY_SC_ROUND` in universal-failure loop + 60s timeout set.

### Integration (2 tests) — `tests/integration/test_pairing_sc_passkey_loopback.py`

- Two `Stack.virtual()`: `mitm_required=True`, `enable_secure_connections=True`, DisplayYesNo×KeyboardOnly IO caps, matching `_FixedPasskeyDelegate(passkey=N)` on both sides → 20 rounds complete; both bonds end up `authenticated=True`, `sc=True`; identical f5-derived LTKs.
- Same setup but Input-side delegate returns a different passkey → `pair()` raises `RuntimeError("SMP pairing failed (reason=4)")` (round 1 detects mismatch).

### Manual / out of scope

- Real-hardware verification with phone in SC Passkey mode — separate Plan.
- BT spec test vectors from Vol 6 Part C §7.2.3 — optional cross-check if available; not required for acceptance (loopback round-trip equivalence is sufficient).

## 9. Known risks

1. **Bit order ambiguity** — Core 5.4 Vol 3 Part H §2.3.5.6.4 isn't crystal-clear on whether i=1 is MSB or LSB. Wireshark dissectors and BlueZ source use MSB-first (round 1 = bit 19 of the passkey). We adopt MSB-first. Loopback tests would still pass on LSB-first as long as both sides agree; cross-vendor interop would surface the bug. Document the choice; if a real phone produces mismatch on a known passkey, swap and retest.

2. **r_i byte format**: f4's `Z` parameter is typed as `int` in our `SMPCrypto.f4`. Passing `0x80 | bit` (an int) flows through AES-CMAC correctly only if `f4` internally serializes Z as a single byte. Verify `SMPCrypto.f4` implementation handles this (spec calls for a 1-byte Z; the existing JW path uses `Z=0`).

3. **Round 20 exit timing on Responder**: the Responder's exit (`state = RANDOM_EXCHANGE`) happens INSIDE the `_sc_passkey_recv_peer_random` action. The registered transition target is `PASSKEY_SC_ROUND` (reflexive). The action overrides `_state` — same pattern used in SC NC. If the SM applies transition target after action, the override would be lost; in practice it does not, since the same pattern works for SC NC and SC Just Works. Covered by integration test.

4. **Initiator's `Pairing_DHKey_Check` arrival on Responder while still in `PASSKEY_SC_ROUND`**: shouldn't happen — Initiator only sends `Ea` after its round 20 verification, which only succeeds after Responder has sent `Nb_20` from the same action that advanced its state to `RANDOM_EXCHANGE`. Race-condition free on a serial L2CAP channel.

5. **Test fragility on virtual transport**: the 20 rounds × 4 PDUs each in a virtual loopback should complete in well under a second. If `pytest-asyncio`'s event loop is starved (other long-running coroutines), the 60s timeout might fire. Keep the integration tests minimal — no background tasks.

## 10. Acceptance criteria

- [ ] `SMPState.PASSKEY_SC_ROUND` (=12) exists.
- [ ] `_association_model` returns `"passkey_entry"` for SC + MITM + in-scope IO pairs; `"numeric_comparison"` still wins for NC-eligible pairs.
- [ ] `_passkey_user_entered` SC branch transitions to `PASSKEY_SC_ROUND` and (for Initiator) sends round-1 Ca.
- [ ] `_sc_initiator_recv_peer_public_key` and `_sc_responder_recv_peer_public_key` branch on association model: Display side enters `PASSKEY_SC_ROUND` directly; Input side enters `PASSKEY_INPUT_PENDING`.
- [ ] Per-round Initiator action: `PAIRING_CONFIRM_RX` → send Pairing_Random; `PAIRING_RANDOM_RX` → verify f4 → next round or exit to DHKEY_CHECK.
- [ ] Per-round Responder action: `PAIRING_CONFIRM_RX` → compute and send own Confirm; `PAIRING_RANDOM_RX` → verify f4 → send own Random → next round or exit to RANDOM_EXCHANGE.
- [ ] Wrong-subphase event → `FAILED(0x08)`. f4 mismatch → `FAILED(0x04)`.
- [ ] `PASSKEY_SC_ROUND` in universal-failure loop + 60s timeout.
- [ ] Round 20 exit Initiator: derives f5, calls `_sc_send_dhkey_check_initiator`, state → DHKEY_CHECK.
- [ ] Round 20 exit Responder: derives f5, state → RANDOM_EXCHANGE.
- [ ] Loopback E2E: matching passkey → 20 rounds complete, bond `authenticated=True, sc=True`; mismatched passkey → pair() raises reason=4.
- [ ] Full suite green minus pre-existing USB-diagnostics failures.
- [ ] STATUS.md updated to mark Sub-Plan 3b-2 ✅.

## 11. Out of scope (deferred)

| Item | Future Plan |
|---|---|
| OOB (Legacy + SC) | Sub-Plan 3c |
| Both-KeyboardOnly IO pair | None — falls through to JW |
| BR/EDR Passkey Entry SSP (`User_Passkey_Request`/`User_Passkey_Notification`) | Independent Plan |
| Real-hardware verification with phone in SC Passkey mode | Independent Plan |
| Spec-vector cross-check (Vol 6 Part C §7.2.3 worked example) | Optional follow-up |
