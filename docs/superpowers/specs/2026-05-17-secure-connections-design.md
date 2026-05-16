# Secure Connections (LE SC + BR/EDR SC) — Design Spec

**Date**: 2026-05-17
**Scope**: PRD §5.4 LE Secure Connections + PRD §5.5 BR/EDR Secure Connections, Just Works association model only.
**Predecessors**: [SMP Sub-Plan 1 (Legacy Just Works)](../plans/2026-05-13-smp-pairing-legacy-jw.md), [HCI Tolerant Initialization](../plans/2026-05-16-hci-tolerant-initialization.md)

---

## 1. Goals

Add Secure Connections (SC) support to both transports:

- **LE Secure Connections (LE SC)** — Pairing via SMP using P-256 ECDH and `f4/f5/f6/g2` (Core 5.4 Vol 3 Part H §2.3.5.6)
- **BR/EDR Secure Connections (BR/EDR SC)** — Pairing via Classic SSP using controller-driven P-256 ECDH (Core 5.4 Vol 3 Part C §5.2)

Just Works association model only for both. Numeric Comparison / Passkey Entry / OOB deferred to Sub-Plan 3.

SC is **opt-in** via configuration. Default off. Features that require SC (CTKD now; LE Audio / Security Mode 1 Level 4 / SC Only Mode / ISO encryption in future Plans) trigger a build-time validation that refuses to start until `enable_secure_connections=True`.

## 2. Configuration

### 2.1 `SecurityConfig.enable_secure_connections`

New field in `pybluehost/ble/security.py`:

```python
@dataclass
class SecurityConfig:
    enable_secure_connections: bool = False
    bondable: bool = True
    auto_encrypt_on_bonded_reconnect: bool = True
    ctkd_enable: bool = False  # already exists
    # ... existing fields ...
```

### 2.2 Validation

`_validate_sc_dependencies(security_config)` runs at `Stack._build` time:

```python
def _validate_sc_dependencies(cfg: SecurityConfig) -> None:
    requires_sc: list[str] = []
    if cfg.ctkd_enable:
        requires_sc.append("CTKD")
    # Future hooks (commented stubs):
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

`ConfigurationError` is a new exception in `pybluehost/core/errors.py`, inheriting from `PyBlueHostError`.

### 2.3 Behavior matrix

| `enable_secure_connections` | CTKD enabled | Result |
|-----------------------------|--------------|--------|
| `False` (default) | `False` | Legacy pairing only — current Sub-Plan 1 behavior, no change |
| `False` | `True` | `ConfigurationError` at `Stack._build` |
| `True` | `False` | LE SC + BR/EDR SC available; if peer doesn't advertise SC, fallback to Legacy |
| `True` | `True` | LE SC + BR/EDR SC + CTKD path enabled |

### 2.4 SC is opt-in because

- LE Just Works SC offers no MITM protection over Legacy Just Works — pure compute cost increase for zero auth gain in the no-MITM case
- BR/EDR SC requires controller support (`Write_Secure_Connections_Host_Support`) that older adapters may lack — silently enabling could break Classic pairing
- LEA / CTKD / Security Mode 1 Level 4 users must explicitly accept the SC requirement so the dependency is visible
- Sub-Plan 1's Legacy behavior stays as the validated default; SC is purely additive

## 3. LE Secure Connections

### 3.1 New cryptography (`pybluehost/ble/_smp_sc_crypto.py`)

```python
def generate_p256_keypair() -> tuple[bytes, bytes]:
    """Generate a fresh ephemeral P-256 keypair.

    Returns (private_key_bytes_32, public_key_bytes_64).
    Public key is X (32 bytes) || Y (32 bytes), each in little-endian per
    Core Spec 5.4 Vol 3 Part H §2.3.5.6.1.
    """

def compute_dhkey(local_private: bytes, peer_public: bytes) -> bytes:
    """Compute the DHKey = ECDH(local_private, peer_public).

    Both inputs are little-endian per BT spec. Output is the X coordinate
    of the shared point in little-endian (32 bytes).
    """
```

Uses `cryptography.hazmat.primitives.asymmetric.ec` for the underlying P-256 operations. Byte-order conversion (BT spec little-endian ↔ `cryptography` big-endian) is contained within this module.

### 3.2 New PDUs

In `pybluehost/ble/smp.py`:

```python
class SMPCode(IntEnum):
    # existing...
    PAIRING_PUBLIC_KEY  = 0x0C
    PAIRING_DHKEY_CHECK = 0x0D


@dataclass
class SMPPairingPublicKey(SMPPdu):
    """Pairing Public Key PDU (Core 5.4 Vol 3 Part H §3.5.6)."""
    public_key_x: bytes = b""  # 32 bytes LE
    public_key_y: bytes = b""  # 32 bytes LE


@dataclass
class SMPPairingDHKeyCheck(SMPPdu):
    """Pairing DHKey Check PDU (Core 5.4 Vol 3 Part H §3.5.7)."""
    dhkey_check: bytes = b""  # 16 bytes
```

### 3.3 State machine extensions

In `pybluehost/ble/smp.py`:

```python
class SMPState(IntEnum):
    # existing...
    PUBLIC_KEY_EXCHANGE = 8
    DHKEY_CHECK         = 9


class SMPEvent(IntEnum):
    # existing...
    PAIRING_PUBLIC_KEY_RX = 16
    PAIRING_DHKEY_CHECK_RX = 17
```

`SMPPairingContext` gains:

```python
    # SC working state
    local_private_key: bytes = b""
    local_public_key: bytes = b""
    peer_public_key: bytes = b""
    dhkey: bytes = b""
    mac_key: bytes = b""
    ltk_sc: bytes = b""             # f5-derived; replaces Legacy STK indirection
    local_dhkey_check: bytes = b""  # Ea (Initiator) or Eb (Responder)
    peer_dhkey_check: bytes = b""
```

### 3.4 Selection logic

`_smp_state.register_transitions(ctx)` is now config-aware:

```python
def register_transitions(ctx: SMPPairingContext) -> None:
    sc_negotiated = (
        ctx.security_config.enable_secure_connections
        and (ctx.local_auth_req & 0x08)
        and (ctx.peer_auth_req & 0x08)
    )
    if sc_negotiated:
        _register_sc_transitions(ctx)
    else:
        _register_legacy_transitions(ctx)
```

`local_auth_req`'s SC bit (0x08) is set during Pairing Request/Response construction when `enable_secure_connections=True`. The peer's SC bit is observed when the Pairing Response (Initiator) or Pairing Request (Responder) arrives. The decision happens after Phase 1 — the state machine is initially in IDLE→FEATURE_EXCHANGE→CONFIRMING under Legacy, but if peer advertises SC, we jump to PUBLIC_KEY_EXCHANGE before the Confirm/Random work.

To keep this clean, the Plan registers a "pre-Phase-2 fork" transition: `FEATURE_EXCHANGE` exit branches on the SC bit. If SC, go to `PUBLIC_KEY_EXCHANGE`; if Legacy, current `CONFIRMING`.

### 3.5 SC Phase 2 flow (Just Works)

```
After Phase 1 feature exchange (auth_req SC bits set on both sides):

  IDLE → FEATURE_EXCHANGE (existing)
      → PUBLIC_KEY_EXCHANGE
         Both sides send SMPPairingPublicKey (no order requirement; initiator first by convention)
         On receiving peer key: compute DHKey = ECDH(local_priv, peer_pub)
         Just Works: skip Ya/Yb authentication value (set to 0)
      → CONFIRMING (we reuse the existing state for SC's Confirm/Random exchange)
         Responder: Nb = random16(); Cb = f4(PKbx, PKax, Nb, 0); send SMPPairingConfirm(Cb)
         (Initiator does NOT send a Confirm in SC Just Works — only the Responder does)
      → RANDOM_EXCHANGE
         Initiator: Na = random16(); send SMPPairingRandom(Na)
         Responder: send SMPPairingRandom(Nb)
         Initiator: verify Cb == f4(PKbx, PKax, Nb, 0); on mismatch FAIL with reason=CONFIRM_VALUE_FAILED
         Both: derive (MacKey, LTK) = f5(DHKey, Na, Nb, A, B)
      → DHKEY_CHECK
         Initiator: Ea = f6(MacKey, Na, Nb, rb=0, IOcapA, A, B); send SMPPairingDHKeyCheck(Ea)
         Responder: verify Ea = f6(MacKey, Na, Nb, ra=0, IOcapA, A, B)
                    Eb = f6(MacKey, Nb, Na, ra=0, IOcapB, B, A); send SMPPairingDHKeyCheck(Eb)
         Initiator: verify Eb = f6(MacKey, Nb, Na, rb=0, IOcapB, B, A)
                    on mismatch FAIL with reason=DHKEY_CHECK_FAILED
      → STK_ENCRYPTING (reuse state name; LTK is the f5-derived value, no STK indirection)
         Initiator: HCI_LE_Start_Encryption(handle, ediv=0, rand=0, ltk=ltk_sc)
         Both: on Encryption_Change(success) → KEY_DISTRIBUTION
      → KEY_DISTRIBUTION
         No LTK distribution in SC (both already have the f5-derived LTK)
         IRK + CSRK distribution per masks (unchanged from Legacy)
         On KEYS_RECEIVED → BONDED
                            BondInfo persisted with sc=True, authenticated=False (Just Works)
```

### 3.6 Just Works auto-accept

LE SC Just Works skips Numeric Comparison user confirmation (it's a no-MITM model). The PairingDelegate's `confirm_just_works(peer_addr)` callback still gates the procedure — same as Legacy. If False, abort with `PAIRING_NOT_SUPPORTED`.

## 4. BR/EDR Secure Connections

### 4.1 HCI surface additions

New commands (in `pybluehost/hci/packets.py`):

| Command | Opcode | Used by |
|---------|--------|---------|
| `HCI_Write_Secure_Connections_Host_Support` | 0x0C7A | `HCIController.initialize()` when `enable_secure_connections=True` |
| `HCI_IO_Capability_Request_Reply` | 0x042B | `SSPManager` |
| `HCI_IO_Capability_Request_Negative_Reply` | 0x0434 | `SSPManager` (rejection path) |
| `HCI_User_Confirmation_Request_Reply` | 0x042C | `SSPManager` (Just Works auto-accept) |
| `HCI_User_Confirmation_Request_Negative_Reply` | 0x042D | `SSPManager` (rejection) |
| `HCI_Link_Key_Request_Reply` | 0x040B | `SSPManager` reconnect path |
| `HCI_Link_Key_Request_Negative_Reply` | 0x040C | `SSPManager` (no stored key) |

New events:

| Event | Code | Handler |
|-------|------|---------|
| `HCI_Link_Key_Request_Event` | 0x17 | `SSPManager.on_link_key_request` — look up `BondInfo.link_key`; reply or negative-reply |
| `HCI_Link_Key_Notification_Event` | 0x18 | `SSPManager.on_link_key_notification` — persist `BondInfo(link_key=..., link_key_type=0x05–0x08, sc=True)` |
| `HCI_IO_Capability_Request_Event` | 0x31 | `SSPManager.on_io_capability_request` — reply with our IO caps + auth_req (SC bit set) |
| `HCI_User_Confirmation_Request_Event` | 0x33 | `SSPManager.on_user_confirmation_request` — auto-accept for Just Works |
| `HCI_Simple_Pairing_Complete_Event` | 0x36 | `SSPManager.on_simple_pairing_complete` — emit pairing-complete event |

`HCIController` exposes 5 new listener-registration methods matching these handlers.

### 4.2 Init sequence change

`HCIController.initialize()` adds one step after `Write_Simple_Pairing_Mode`:

```python
if cfg.security.enable_secure_connections:
    if supported_commands.has(HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT):
        await self.send_command(HCI_Write_Secure_Connections_Host_Support_Command(enabled=1))
    else:
        logger.warning("controller does not support BR/EDR Secure Connections; falling back to Legacy SSP")
```

`HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT = 0x0C7A` is added to `pybluehost/hci/capabilities._OPCODE_BIT_POSITIONS` at its spec position (octet 32, bit 3).

### 4.3 SSPManager flow (Just Works)

```
Inbound connection request (Classic) → controller enters SSP →

1. HCI_IO_Capability_Request_Event(bd_addr)
   SSPManager replies HCI_IO_Capability_Request_Reply(
       bd_addr,
       io_capability=NO_INPUT_NO_OUTPUT,
       oob_data_present=0,
       authentication_requirements=0x04,  # MITM Not Required + General Bonding + SC (bit 3 = SC)
   )

2. HCI_IO_Capability_Response_Event (peer's IO caps — informational only, SSPManager logs and continues)

3. HCI_User_Confirmation_Request_Event(bd_addr, numeric_value)
   Just Works → SSPManager replies HCI_User_Confirmation_Request_Reply(bd_addr)
   (NumericComparison would route to delegate; deferred to Sub-Plan 3)

4. HCI_Simple_Pairing_Complete_Event(status, bd_addr)
   status=0 → pairing succeeded; status≠0 → emit failure event, do NOT persist

5. HCI_Link_Key_Notification_Event(bd_addr, link_key, key_type)
   Persist BondInfo with:
     link_key = key
     link_key_type = key_type (0x05–0x08 for SC; 0x04 for legacy SSP)
     sc = key_type in {0x07, 0x08}  # Authenticated/Unauthenticated Combination Key from P-256
     authenticated = key_type in {0x06, 0x08}  # Authenticated key
   Then emit pairing-complete event with sc=True
```

Reconnect path (BR/EDR SC):

```
6. HCI_Link_Key_Request_Event(bd_addr)
   SSPManager looks up BondInfo by bd_addr.
   If BondInfo with link_key found: HCI_Link_Key_Request_Reply(bd_addr, link_key)
   Else: HCI_Link_Key_Request_Negative_Reply(bd_addr) → controller re-triggers SSP
```

### 4.4 BondInfo fields used for BR/EDR SC

`BondInfo` already has `link_key`, `link_key_type`, `sc`, `authenticated` fields. No dataclass change needed.

## 5. Architecture diagram

```
                 ┌────────────────────────────────────────────────────────┐
                 │                  Stack._build(cfg)                     │
                 │   _validate_sc_dependencies(cfg.security)              │
                 │                                                        │
                 │  ┌──────────────────────┐  ┌─────────────────────────┐ │
                 │  │     SMPManager       │  │      SSPManager         │ │
                 │  │   (cfg.security)     │  │    (cfg.security)       │ │
                 │  └─────────┬────────────┘  └───────────┬─────────────┘ │
                 └─────────────┼──────────────────────────┼───────────────┘
                               │                          │
                               ▼                          ▼
              ┌──────────────────────────────┐  ┌─────────────────────────┐
              │     _smp_state.py            │  │  HCI events:            │
              │  register_transitions(ctx)   │  │   IO_Capability_Request │
              │  branches Legacy / SC        │  │   User_Confirmation_Req │
              └────┬───────────────────┬─────┘  │   Link_Key_Request      │
                   │                   │        │   Link_Key_Notification │
        Legacy path│       SC path     │        │   Simple_Pairing_Compl. │
            (Sub-Plan 1)               ▼        └────────────┬────────────┘
                              ┌─────────────────┐            │
                              │ _smp_sc_crypto  │            ▼
                              │  ECDH + DHKey   │   ┌─────────────────────┐
                              └────────┬────────┘   │  HCIController      │
                                       │            │  Write_SC_Host_Supp │
                                       ▼            │  on_* listeners     │
                              ┌─────────────────┐   └─────────────────────┘
                              │  SMPCrypto      │
                              │  f4/f5/f6/g2    │
                              │  (already on    │
                              │   master)       │
                              └─────────────────┘
```

## 6. Test strategy

### LE SC

- **Unit (~5 tests)**: ECDH keygen + DHKey + byte-order; SC PDU round-trip; state-machine transitions; selection logic (SC vs Legacy based on config + peer); failure paths (DHKey mismatch, Confirm mismatch).
- **Loopback E2E (~2 tests)**: Two `Stack.virtual()` instances paired via existing `VirtualLELink`, both with `enable_secure_connections=True`, complete SC Just Works → BondInfo persisted with `sc=True` → reconnect auto-encrypts.
- **Config-off regression**: Same setup with `enable_secure_connections=False` → falls back to Legacy even if peer offers SC; `BondInfo.sc=False`.

### BR/EDR SC

- **HCI integration (~3 tests)**: Inject synthesized SSP event sequence into `SSPManager` via new `VirtualController.simulate_ssp_pairing(bd_addr, key_type)` test hook; assert correct HCI command replies; assert `BondInfo` persisted with correct `link_key_type` and `sc` flag.
- **Reconnect**: Inject `HCI_Link_Key_Request_Event`; assert SSPManager looks up stored bond and replies with `HCI_Link_Key_Request_Reply`.

### Config validation

- **Unit**: `_validate_sc_dependencies` raises `ConfigurationError` for `ctkd_enable=True` + `enable_secure_connections=False`; passes when both True.

### Hardware (manual)

- LE SC: Android phone configured for LE SC required → pair Just Works → verify bond persists with `sc=True`
- BR/EDR SC: Linux `bluetoothctl` peer with SC enabled → Classic pair → verify `Link_Key_Notification` arrives with `key_type ∈ {0x07, 0x08}`

## 7. Out of scope (deferred)

| Item | Future Plan |
|------|-------------|
| Numeric Comparison association model (6-digit code display + user confirm) | Sub-Plan 3 |
| Passkey Entry (Legacy 20-round + SC 20-round) | Sub-Plan 3 |
| OOB (P-256 hash exchange over out-of-band channel) | Sub-Plan 3 |
| Full IO Capability × association model matrix | Sub-Plan 3 |
| LE Audio infrastructure | v3.0+ |
| Two-controller Classic loopback bridge | Independent Plan |
| Security Mode 1 Level 4 / Security Mode 4 Level 4 enforcement | Independent Plan |
| "Secure Connections Only Mode" | Independent Plan |
| ISO Channel encryption | v3.0+ |
| GATT permission enforcement based on SC level | Independent Plan |
| CTKD activation (the manager exists; activating it requires SC) | Wire it up after Sub-Plan 2 lands |

## 8. Known risks

1. **`cryptography` library byte order**: `cryptography.hazmat.primitives.asymmetric.ec` returns big-endian point coordinates; BT spec wants little-endian on the wire. Conversion happens in `_smp_sc_crypto.py` — must be tested with spec test vectors (Core 5.4 Vol 3 Part H Appendix D test vectors).
2. **SC bit position in `auth_req`**: SC bit is bit 3 (mask 0x08), MITM is bit 2 (mask 0x04). Misreading the spec table → silent fallback to Legacy. Tests must assert both peer's SC bit detection and our own SC bit emission.
3. **VirtualController SSP simulation completeness**: Stubbing the 5-event SSP sequence requires careful sequencing to match real controller timing. Risk of false-positive integration tests. Mitigation: keep simulation simple (linear sequence), and document that real-controller validation is hardware-only.
4. **CTKD validation gate is one-way**: Plan doesn't activate CTKD yet, only blocks misconfig. When CTKD activates in a future Plan, it should add a "CTKD has been used; bond requires SC" runtime check to BondStorage load path.
5. **Mixed Sub-Plan 1 + Sub-Plan 2 bonds**: Existing Sub-Plan 1 bonds (Legacy, `sc=False`) must still load and trigger Legacy reconnect — verified by Sub-Plan 1 follow-up's legacy `rand` int-format compatibility (same pattern applies).
6. **BR/EDR SC requires controller cooperation**: If the controller doesn't support `Write_Secure_Connections_Host_Support`, we log a warning and fall back to legacy SSP. Tests must cover both "controller supports" and "controller doesn't support" paths.

## 9. Acceptance criteria

- [ ] `SecurityConfig.enable_secure_connections` defaults False; opt-in via config
- [ ] `_validate_sc_dependencies` raises `ConfigurationError` when CTKD enabled without SC
- [ ] LE SC Just Works pairing succeeds via loopback E2E with two `Stack.virtual()` instances
- [ ] LE SC bond persisted with `sc=True`, `authenticated=False`
- [ ] Reconnect after LE SC pairing auto-encrypts using f5-derived LTK
- [ ] When `enable_secure_connections=False`, SC bit never set in `auth_req` even if peer advertises it; Legacy path used
- [ ] BR/EDR SC HCI commands + events round-trip (encode/decode)
- [ ] `HCIController.initialize()` issues `Write_Secure_Connections_Host_Support` when config-on AND controller supports it
- [ ] `SSPManager` handles full SSP event sequence; replies with correct HCI commands
- [ ] `SSPManager` persists `BondInfo` with `link_key_type ∈ {0x05, 0x06, 0x07, 0x08}` and `sc=True` for P-256 keys
- [ ] `SSPManager` Link_Key_Request lookup works for reconnect
- [ ] Full suite passes; coverage ≥ 85%; only 3 pre-existing USB diagnostics failures remain
- [ ] STATUS.md marks Plan complete
