# Plan 6b: SMP + SecurityConfig

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement `pybluehost/ble/smp.py` (SMP pairing state machine, 9 crypto functions with Spec test vectors, BondStorage Protocol, JsonBondStorage, IO Capability matrix) and `pybluehost/ble/security.py` (SecurityConfig, CTKDManager).

**Architecture reference:** `docs/architecture/09-ble-stack.md` §9.4

**Dependencies:** `pybluehost/core/`, `pybluehost/l2cap/`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/ble/smp.py` | `SMPManager`, `SMPCrypto`, `BondStorage` (Protocol), `JsonBondStorage`, `PairingDelegate`, `AutoAcceptDelegate` |
| `pybluehost/ble/security.py` | `SecurityConfig`, `CTKDDirection`, `CTKDManager` |
| `tests/unit/ble/test_smp.py` | SMP state machine + all 9 crypto functions with Spec test vectors |
| `tests/unit/ble/test_security.py` | SecurityConfig defaults + CTKDManager derive functions |

---

## Task 1: SMP Layer

## Task 1: SMP Layer

**Files:** `pybluehost/ble/smp.py`, `tests/unit/ble/test_smp.py`

- [ ] **Step 1: Write failing SMP tests**

```python
# tests/unit/ble/test_smp.py
import pytest
from pybluehost.ble.smp import SMPCrypto, JsonBondStorage, SMPPdu, SMPCode

def test_smp_crypto_c1():
    # BT Core Spec 5.3 Vol 3 Part H §C.1 — Legacy Confirm Value
    k   = bytes.fromhex("00000000000000000000000000000000")
    r   = bytes.fromhex("5783D52156AD6F0E6388274EC6702EE0")
    preq = bytes.fromhex("07071000000110")
    pres = bytes.fromhex("05000800000302")
    iat = 1; rat = 0
    ia  = bytes.fromhex("A1A2A3A4A5A6")
    ra  = bytes.fromhex("B1B2B3B4B5B6")
    result = SMPCrypto.c1(k, r, preq, pres, iat, rat, ia, ra)
    assert len(result) == 16

def test_smp_crypto_s1():
    # BT Core Spec 5.3 Vol 3 Part H §C.1.2 — Legacy STK
    k  = bytes.fromhex("00000000000000000000000000000000")
    r1 = bytes.fromhex("000F0E0D0C0B0A091122334455667788")
    r2 = bytes.fromhex("010203040506070899AABBCCDDEEFF00")
    result = SMPCrypto.s1(k, r1, r2)
    assert result == bytes.fromhex("9a1fe1f0e8b0f49b5b4216ae796da062")

def test_smp_crypto_f4():
    # BT Core Spec 5.3 Vol 3 Part H §C.2.4 — SC Confirm (f4)
    U = bytes.fromhex("20b003d2f297be2c5e2c83a7e9f9a5b9eff49111acf4fddbcc0301480e359de6")
    V = bytes.fromhex("55188b3d32f6bb9a900afcfbeed4e72a59cb9ac2f19d7cfb6b4fdd49f47fc5fd")
    X = bytes.fromhex("d5cb8454d177733effffb2ec712baeab")
    Z = 0
    result = SMPCrypto.f4(U, V, X, Z)
    assert result == bytes.fromhex("f2c916f107a9bd1cf1eda1bea974872d")

def test_smp_crypto_f5():
    # BT Core Spec 5.3 Vol 3 Part H §C.2.5 — SC Key Generation (f5)
    W  = bytes.fromhex("98a58fb4d436cc4c629cfc3a4b03b4c39ef08e73a27cfc97cec9b6de0fa71cd1")
    N1 = bytes.fromhex("d5cb8454d177733effffb2ec712baeab")
    N2 = bytes.fromhex("a6e8e7cc25a75f6e216583f7ff3dc4cf")
    A1 = bytes.fromhex("00561237371c")
    A2 = bytes.fromhex("00a713702dcfc1")[:6]
    mac_key, ltk = SMPCrypto.f5(W, N1, N2, A1, A2)
    assert len(mac_key) == 16
    assert len(ltk) == 16
    # Verify against Spec values
    assert mac_key == bytes.fromhex("2965f176a1084a02fd3f6a20ce636e20")
    assert ltk     == bytes.fromhex("69867911069d7cd21f09181886887983")

def test_smp_crypto_f6():
    # BT Core Spec 5.3 Vol 3 Part H §C.2.6 — SC DH-Key Check (f6)
    W     = bytes.fromhex("2965f176a1084a02fd3f6a20ce636e20")
    N1    = bytes.fromhex("d5cb8454d177733effffb2ec712baeab")
    N2    = bytes.fromhex("a6e8e7cc25a75f6e216583f7ff3dc4cf")
    R     = bytes.fromhex("12a3343bb453bb5408da42d20c2d0fc8")
    IOcap = bytes.fromhex("010102")
    A1    = bytes.fromhex("00561237371c")
    A2    = bytes.fromhex("00a713702dcf")
    result = SMPCrypto.f6(W, N1, N2, R, IOcap, A1, A2)
    assert result == bytes.fromhex("e3c47398656745e3b25b58617e97c06b")

def test_smp_crypto_g2():
    # BT Core Spec 5.3 Vol 3 Part H §C.2.7 — SC Numeric Comparison (g2)
    U = bytes.fromhex("20b003d2f297be2c5e2c83a7e9f9a5b9eff49111acf4fddbcc0301480e359de6")
    V = bytes.fromhex("55188b3d32f6bb9a900afcfbeed4e72a59cb9ac2f19d7cfb6b4fdd49f47fc5fd")
    X = bytes.fromhex("d5cb8454d177733effffb2ec712baeab")
    Y = bytes.fromhex("a6e8e7cc25a75f6e216583f7ff3dc4cf")
    result = SMPCrypto.g2(U, V, X, Y)
    assert result == 0x2f9ed5ba  # six-digit code = result % 1000000

def test_smp_crypto_ah():
    # BT Core Spec 5.3 Vol 3 Part H §C.2.2 — RPA Hash (ah)
    k = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b")
    r = bytes.fromhex("708194")
    result = SMPCrypto.ah(k, r)
    assert result == bytes.fromhex("0dfbaa")

def test_smp_crypto_h6():
    # BT Core Spec 5.3 Vol 3 Part H §C.2.10 — h6
    W     = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b")
    keyID = b"lebr"
    result = SMPCrypto.h6(W, keyID)
    assert result == bytes.fromhex("2d9ae102e76dc91ce8d3a9e280b16399")

def test_smp_crypto_h7():
    # BT Core Spec 5.3 Vol 3 Part H §C.2.11 — h7
    SALT = bytes.fromhex("6c888391aab6e7ca8cbbc3c0d2db3473")
    W    = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b")
    result = SMPCrypto.h7(SALT, W)
    assert result == bytes.fromhex("fb173597c6a3c0ecd2998c2a75a57011")

def test_smp_pdu_pairing_request_encode():
    from pybluehost.ble.smp import SMPPairingRequest
    pdu = SMPPairingRequest(
        io_capability=0x03, oob_data_flag=0x00,
        auth_requirements=0x0D, max_enc_key_size=16,
        initiator_key_distribution=0x01, responder_key_distribution=0x01,
    )
    raw = pdu.to_bytes()
    assert raw[0] == SMPCode.PAIRING_REQUEST
    assert raw[1] == 0x03  # io_capability

@pytest.mark.asyncio
async def test_bond_storage_save_load(tmp_path):
    from pybluehost.core.address import BDAddress
    from pybluehost.ble.smp import BondInfo, JsonBondStorage
    storage = JsonBondStorage(path=tmp_path / "bonds.json")
    addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
    bond = BondInfo(
        peer_address=addr,
        address_type=0x00,
        ltk=bytes(16),
        ediv=0,
        rand=0,
        key_size=16,
        authenticated=False,
        sc=True,
    )
    await storage.save_bond(address=addr, bond=bond)
    loaded = await storage.load_bond(address=addr)
    assert loaded is not None
    assert loaded.ltk == bytes(16)
    assert loaded.sc is True

@pytest.mark.asyncio
async def test_bond_storage_missing_returns_none(tmp_path):
    from pybluehost.core.address import BDAddress
    from pybluehost.ble.smp import JsonBondStorage
    storage = JsonBondStorage(path=tmp_path / "bonds.json")
    addr = BDAddress.from_string("11:22:33:44:55:66")
    assert await storage.load_bond(addr) is None

@pytest.mark.asyncio
async def test_bond_storage_list_bonds(tmp_path):
    from pybluehost.core.address import BDAddress
    from pybluehost.ble.smp import BondInfo, JsonBondStorage
    storage = JsonBondStorage(path=tmp_path / "bonds.json")
    addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
    bond = BondInfo(peer_address=addr, address_type=0, ltk=bytes(16))
    await storage.save_bond(addr, bond)
    bonds = await storage.list_bonds()
    assert addr in bonds

@pytest.mark.asyncio
async def test_bond_storage_delete(tmp_path):
    from pybluehost.core.address import BDAddress
    from pybluehost.ble.smp import BondInfo, JsonBondStorage
    storage = JsonBondStorage(path=tmp_path / "bonds.json")
    addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
    bond = BondInfo(peer_address=addr, address_type=0, ltk=bytes(16))
    await storage.save_bond(addr, bond)
    await storage.delete_bond(addr)
    assert await storage.load_bond(addr) is None

@pytest.mark.asyncio
async def test_auto_accept_delegate_confirms_everything():
    from pybluehost.ble.smp import AutoAcceptDelegate
    delegate = AutoAcceptDelegate()
    assert await delegate.confirm_numeric(1, 123456) is True
    assert await delegate.request_passkey(1) == 0
    assert await delegate.confirm_pairing(1, None) is True
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `smp.py`**

- `SMPCode(IntEnum)`: PAIRING_REQUEST=0x01 through KEYPRESS_NOTIFICATION=0x0E
- `SMPPdu` base class with `to_bytes()` / `decode_smp_pdu()`
- Concrete PDU classes: `SMPPairingRequest`, `SMPPairingResponse`, `SMPPairingConfirm`, `SMPPairingRandom`, `SMPEncryptionInformation`, `SMPMasterIdentification`, `SMPIdentityInformation`, `SMPIdentityAddressInformation`, `SMPSigningInformation`, `SMPSecurityRequest`
- `SMPCode(IntEnum)`: PAIRING_REQUEST=0x01 through KEYPRESS_NOTIFICATION=0x0E
- `SMPCrypto`: all 9 crypto functions:
  - `c1(k, r, preq, pres, iat, rat, ia, ra)` — Legacy Confirm (AES-ECB)
  - `s1(k, r1, r2)` — Legacy STK
  - `f4(U, V, X, Z)` — SC Confirm: `AES-CMAC(X, U||V||Z)` where U,V are 32-byte EC point coords
  - `f5(W, N1, N2, A1, A2)` — SC MacKey + LTK: two AES-CMAC calls with T = AES-CMAC(SALT, W), SALT = 6C888391...
  - `f6(W, N1, N2, R, IOcap, A1, A2)` — SC DH-Key Check: `AES-CMAC(W, N1||N2||R||IOcap||A1||A2)`
  - `g2(U, V, X, Y)` — SC Numeric Comparison: `AES-CMAC(X, U||V||Y)[12:16]` mod 1,000,000 as int
  - `ah(k, r)` — RPA hash: `AES-ECB(k, r||0x00_padding)[0:3]`
  - `h6(W, keyID)` — `AES-CMAC(W, keyID)`
  - `h7(SALT, W)` — `AES-CMAC(SALT, W)`

- `BondInfo` **dataclass** (single record for one bonded peer):
  ```python
  @dataclass
  class BondInfo:
      peer_address: BDAddress
      address_type: int  # AddressType
      ltk: bytes | None = None
      irk: bytes | None = None
      csrk: bytes | None = None
      ediv: int = 0
      rand: int = 0
      key_size: int = 16
      authenticated: bool = False
      sc: bool = False
      link_key: bytes | None = None
      link_key_type: int | None = None
      ctkd_derived: bool = False
  ```

- `BondStorage` **Protocol** (interface — do NOT make a concrete class):
  ```python
  class BondStorage(Protocol):
      async def save_bond(self, address: BDAddress, bond: BondInfo) -> None: ...
      async def load_bond(self, address: BDAddress) -> BondInfo | None: ...
      async def delete_bond(self, address: BDAddress) -> None: ...
      async def list_bonds(self) -> list[BDAddress]: ...
  ```

- `JsonBondStorage` — concrete async implementation of `BondStorage` Protocol:
  ```python
  class JsonBondStorage:
      def __init__(self, path: Path | str) -> None:
          self._path = Path(path)
          self._data: dict[str, dict] = {}
          if self._path.exists():
              import json
              with open(self._path) as f:
                  self._data = json.load(f)
      
      async def save_bond(self, address: BDAddress, bond: BondInfo) -> None:
          key = str(address)
          self._data[key] = {
              "peer_address": str(bond.peer_address),
              "address_type": bond.address_type,
              "ltk": bond.ltk.hex() if bond.ltk else None,
              "irk": bond.irk.hex() if bond.irk else None,
              "csrk": bond.csrk.hex() if bond.csrk else None,
              "ediv": bond.ediv, "rand": bond.rand,
              "key_size": bond.key_size,
              "authenticated": bond.authenticated, "sc": bond.sc,
              "link_key": bond.link_key.hex() if bond.link_key else None,
              "link_key_type": bond.link_key_type,
              "ctkd_derived": bond.ctkd_derived,
          }
          self._flush()
      
      async def load_bond(self, address: BDAddress) -> BondInfo | None:
          entry = self._data.get(str(address))
          if not entry:
              return None
          from pybluehost.core.address import BDAddress as _BDA
          return BondInfo(
              peer_address=_BDA.from_string(entry["peer_address"]),
              address_type=entry["address_type"],
              ltk=bytes.fromhex(entry["ltk"]) if entry.get("ltk") else None,
              irk=bytes.fromhex(entry["irk"]) if entry.get("irk") else None,
              csrk=bytes.fromhex(entry["csrk"]) if entry.get("csrk") else None,
              ediv=entry.get("ediv", 0), rand=entry.get("rand", 0),
              key_size=entry.get("key_size", 16),
              authenticated=entry.get("authenticated", False),
              sc=entry.get("sc", False),
              link_key=bytes.fromhex(entry["link_key"]) if entry.get("link_key") else None,
              link_key_type=entry.get("link_key_type"),
              ctkd_derived=entry.get("ctkd_derived", False),
          )
      
      async def delete_bond(self, address: BDAddress) -> None:
          self._data.pop(str(address), None)
          self._flush()
      
      async def list_bonds(self) -> list[BDAddress]:
          from pybluehost.core.address import BDAddress
          return [BDAddress.from_string(k) for k in self._data]
      
      def _flush(self) -> None:
          import json
          self._path.parent.mkdir(parents=True, exist_ok=True)
          with open(self._path, "w") as f:
              json.dump(self._data, f, indent=2)
  ```

- `PairingDelegate` **Protocol** and `AutoAcceptDelegate` (default for testing):
  ```python
  class PairingDelegate(Protocol):
      """User interaction interface for SMP pairing."""
      async def confirm_numeric(self, connection: int, number: int) -> bool: ...
      async def request_passkey(self, connection: int) -> int: ...
      async def display_passkey(self, connection: int, passkey: int) -> None: ...
      async def confirm_pairing(self, connection: int, peer: "BDAddress") -> bool: ...

  class AutoAcceptDelegate:
      """Default: auto-accept everything (for testing and simple scenarios)."""
      async def confirm_numeric(self, connection: int, number: int) -> bool:
          return True
      async def request_passkey(self, connection: int) -> int:
          return 0
      async def display_passkey(self, connection: int, passkey: int) -> None:
          pass
      async def confirm_pairing(self, connection: int, peer: "BDAddress") -> bool:
          return True
  ```

- `SMPManager`: state machine, `pair(connection, io_capability, bonding, sc)`, `on_pairing_request(handler)`, `set_bond_storage(storage: BondStorage)`, `set_delegate(delegate: PairingDelegate)`

**Note:** Add `cryptography>=41.0` to pyproject.toml dev dependencies for AES-CMAC / ECDH.

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**
```bash
git add pybluehost/ble/smp.py tests/unit/ble/test_smp.py pyproject.toml
git commit -m "feat(ble): add SMP pairing state machine, crypto, and bond storage"
```

---

---

## Task 2: SecurityConfig + CTKDManager

## Task 2: SecurityConfig + CTKDManager

**Files:** `pybluehost/ble/security.py`, `tests/unit/ble/test_security.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/ble/test_security.py
from pybluehost.ble.security import SecurityConfig, CTKDDirection, CTKDManager
from pybluehost.core.keys import LTK

def test_security_config_defaults():
    cfg = SecurityConfig()
    assert cfg.io_capability == 0x03       # NoInputNoOutput
    assert cfg.oob_flag == 0x00
    assert cfg.auth_requirements == 0x0D   # Bonding | MITM | SC
    assert cfg.max_key_size == 16
    assert cfg.initiator_keys == 0x01
    assert cfg.responder_keys == 0x01

def test_ctkd_direction_enum():
    assert CTKDDirection.LE_TO_BREDR == "le_to_bredr"
    assert CTKDDirection.BREDR_TO_LE == "bredr_to_le"

def test_derive_link_key_from_ltk():
    # BT Core Spec 5.3 Vol 3 Part H §3.6.1
    # Use h7(SALT_tmp2, LTK) → ILK, then h6(ILK, "lebr") → link_key
    ltk = LTK(key=bytes.fromhex("ec0234a357c8ad05341010a60a397d9b"),
               rand=bytes(8), ediv=0, authenticated=True, sc=True)
    link_key = CTKDManager.derive_link_key_from_ltk(ltk)
    assert len(link_key) == 16  # 16-byte BR/EDR link key

def test_derive_ltk_from_link_key():
    link_key = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b")
    ltk = CTKDManager.derive_ltk_from_link_key(link_key)
    assert isinstance(ltk, LTK)
    assert len(ltk.key) == 16

def test_ctkd_round_trip():
    """LTK → link_key → LTK' should reconstruct the same key (spec derivation is deterministic)."""
    ltk = LTK(key=bytes.fromhex("ec0234a357c8ad05341010a60a397d9b"),
               rand=bytes(8), ediv=0, authenticated=True, sc=True)
    link_key = CTKDManager.derive_link_key_from_ltk(ltk)
    ltk2 = CTKDManager.derive_ltk_from_link_key(link_key)
    assert ltk2.key == ltk.key
```

- [ ] **Step 2: Run tests — verify they fail**
```bash
uv run pytest tests/unit/ble/test_security.py -v
```

- [ ] **Step 3: Implement `pybluehost/ble/security.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pybluehost.core.keys import LTK
from pybluehost.ble.smp import SMPCrypto

@dataclass
class SecurityConfig:
    io_capability: int = 0x03       # NoInputNoOutput
    oob_flag: int = 0x00
    auth_requirements: int = 0x0D   # Bonding | MITM | SC
    max_key_size: int = 16
    initiator_keys: int = 0x01      # LTK
    responder_keys: int = 0x01      # LTK

class CTKDDirection(str, Enum):
    LE_TO_BREDR = "le_to_bredr"
    BREDR_TO_LE = "bredr_to_le"

class CTKDManager:
    """Cross-Transport Key Derivation per BT Core Spec 5.3 Vol 3 Part H §3.6.1."""

    # SALTs from spec Table H.8
    _SALT_TMP1 = bytes.fromhex("6c888391aab6e7ca8cbbc3c0d2db3473")  # "tmp1"
    _SALT_TMP2 = bytes.fromhex("31703ef27b8ac9c44fef1b50ac8b51c3")  # "tmp2"

    @staticmethod
    def derive_link_key_from_ltk(ltk: LTK) -> bytes:
        """Derive BR/EDR Link Key from LE LTK: ilk = h7(SALT_tmp2, LTK); link_key = h6(ilk, 'lebr')."""
        ilk = SMPCrypto.h7(CTKDManager._SALT_TMP2, ltk.key)
        return SMPCrypto.h6(ilk, b"lebr")

    @staticmethod
    def derive_ltk_from_link_key(link_key: bytes) -> LTK:
        """Derive LE LTK from BR/EDR Link Key: ilk = h7(SALT_tmp1, link_key); ltk_key = h6(ilk, 'brle')."""
        ilk = SMPCrypto.h7(CTKDManager._SALT_TMP1, link_key)
        key = SMPCrypto.h6(ilk, b"brle")
        return LTK(key=key, rand=bytes(8), ediv=0, authenticated=True, sc=True)
```

- [ ] **Step 4: Run tests — verify they pass**
```bash
uv run pytest tests/unit/ble/test_security.py -v
```

- [ ] **Step 5: Commit**
```bash
git add pybluehost/ble/security.py tests/unit/ble/test_security.py
git commit -m "feat(ble): add SecurityConfig and CTKDManager for cross-transport key derivation"
```

---

---

## Task 3: Package Exports + Final Validation

- [ ] **Step 1: Update `pybluehost/ble/__init__.py`** to export SMP + Security symbols

- [ ] **Step 2: Run all SMP + Security tests**
```bash
uv run pytest tests/unit/ble/test_smp.py tests/unit/ble/test_security.py -v
uv run pytest tests/ -v --tb=short
```

- [ ] **Step 3: Commit + update STATUS.md**

---

## 审查补充事项 (from Plan 6 review)

### 补充 1: SMP IO Capability 矩阵测试（架构 09-ble-stack.md §9.4）

BT Core Spec Table 2.8 定义 5×5=25 种 IO Capability 组合，每种对应不同配对模型：
- DisplayOnly × DisplayOnly → Just Works
- DisplayYesNo × DisplayYesNo → Numeric Comparison (SC) / Just Works (Legacy)
- KeyboardOnly × DisplayOnly → Passkey Entry
- ...等

至少需要覆盖 4 种配对模型各 1-2 个代表性组合的测试。

### 补充 2: SMP c1 测试需要精确断言

当前 c1 测试只检查 `len(result) == 16`，应对比 BT Core Spec 附录 D.1 的精确值。

### 补充 3: SMP f5 测试地址截断说明

Plan 中 `A2 = bytes.fromhex("00a713702dcfc1")[:6]` 截断了 7 字节到 6 字节。这是因为地址前缀包含地址类型字节（1 byte type + 6 bytes addr）。需要在注释中说明。
