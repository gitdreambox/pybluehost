# Plan 5: BLE Stack Implementation (ATT / GATT / SMP)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement `pybluehost/ble/att.py`, `ble/gatt.py`, `ble/smp.py` — ATT PDU codec, ATT Bearer request/response machinery, GATT Server/Client with ServiceDefinition, and SMP pairing state machine.

**Architecture reference:** `docs/architecture/09-ble-stack.md`

**Dependencies:** `pybluehost/core/`, `pybluehost/l2cap/`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/ble/__init__.py` | Re-export BLE public API |
| `pybluehost/ble/att.py` | ATT PDU types + `ATTBearer` |
| `pybluehost/ble/gatt.py` | `AttributeDatabase`, `GATTServer`, `GATTClient` |
| `pybluehost/ble/smp.py` | `SMPManager`, `SMPCrypto`, `BondStorage` (Protocol), `JsonBondStorage` |
| `pybluehost/ble/security.py` | `SecurityConfig`, `CTKDDirection`, `CTKDManager` |
| `tests/unit/ble/__init__.py` | |
| `tests/unit/ble/test_att.py` | ATT PDU encode/decode + Bearer request/response |
| `tests/unit/ble/test_gatt.py` | GATT Server attribute database + read/write |
| `tests/unit/ble/test_smp.py` | SMP state machine + all 7 crypto functions with Spec test vectors |
| `tests/unit/ble/test_security.py` | SecurityConfig defaults + CTKDManager derive functions |

---

## Task 1: ATT PDU Codec

**Files:** `pybluehost/ble/att.py` (PDU types only), `tests/unit/ble/test_att.py`

- [ ] **Step 1: Write failing ATT PDU tests**

```python
# tests/unit/ble/test_att.py
from pybluehost.ble.att import (
    ATTOpcode, ATTPdu,
    ATT_Exchange_MTU_Request, ATT_Exchange_MTU_Response,
    ATT_Read_Request, ATT_Read_Response,
    ATT_Write_Request, ATT_Write_Response,
    ATT_Write_Command, ATT_Handle_Value_Notification,
    ATT_Handle_Value_Indication, ATT_Handle_Value_Confirmation,
    ATT_Error_Response, ATT_Find_By_Type_Value_Request,
    ATT_Read_By_Type_Request, ATT_Read_By_Group_Type_Request,
    decode_att_pdu,
)

def test_exchange_mtu_request_encode():
    pdu = ATT_Exchange_MTU_Request(client_rx_mtu=512)
    raw = pdu.to_bytes()
    assert raw[0] == ATTOpcode.EXCHANGE_MTU_REQUEST
    assert int.from_bytes(raw[1:3], "little") == 512

def test_exchange_mtu_request_decode():
    raw = bytes([0x02, 0x00, 0x02])  # MTU=512
    pdu = decode_att_pdu(raw)
    assert isinstance(pdu, ATT_Exchange_MTU_Request)
    assert pdu.client_rx_mtu == 512

def test_read_request_encode():
    pdu = ATT_Read_Request(attribute_handle=0x0003)
    raw = pdu.to_bytes()
    assert raw[0] == ATTOpcode.READ_REQUEST
    assert int.from_bytes(raw[1:3], "little") == 0x0003

def test_read_response_decode():
    raw = bytes([0x0B, 0xAA, 0xBB, 0xCC])
    pdu = decode_att_pdu(raw)
    assert isinstance(pdu, ATT_Read_Response)
    assert pdu.attribute_value == b"\xAA\xBB\xCC"

def test_write_request_encode():
    pdu = ATT_Write_Request(attribute_handle=0x0005, attribute_value=b"\x01")
    raw = pdu.to_bytes()
    assert raw[0] == ATTOpcode.WRITE_REQUEST
    assert int.from_bytes(raw[1:3], "little") == 0x0005
    assert raw[3:] == b"\x01"

def test_notification_encode():
    pdu = ATT_Handle_Value_Notification(attribute_handle=0x000A, attribute_value=b"\x42")
    raw = pdu.to_bytes()
    assert raw[0] == ATTOpcode.HANDLE_VALUE_NOTIFICATION
    assert raw[3:] == b"\x42"

def test_error_response_decode():
    raw = bytes([0x01, 0x0A, 0x03, 0x00, 0x0A])
    pdu = decode_att_pdu(raw)
    assert isinstance(pdu, ATT_Error_Response)
    assert pdu.request_opcode_in_error == 0x0A
    assert pdu.attribute_handle_in_error == 0x0003
    assert pdu.error_code == 0x0A  # Attribute Not Found
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement ATT PDU codec in `att.py`**

```python
class ATTOpcode(IntEnum):
    ERROR_RESPONSE               = 0x01
    EXCHANGE_MTU_REQUEST         = 0x02
    EXCHANGE_MTU_RESPONSE        = 0x03
    FIND_INFORMATION_REQUEST     = 0x04
    FIND_INFORMATION_RESPONSE    = 0x05
    FIND_BY_TYPE_VALUE_REQUEST   = 0x06
    FIND_BY_TYPE_VALUE_RESPONSE  = 0x07
    READ_BY_TYPE_REQUEST         = 0x08
    READ_BY_TYPE_RESPONSE        = 0x09
    READ_REQUEST                 = 0x0A
    READ_RESPONSE                = 0x0B
    READ_BLOB_REQUEST            = 0x0C
    READ_BLOB_RESPONSE           = 0x0D
    READ_MULTIPLE_REQUEST        = 0x0E
    READ_MULTIPLE_RESPONSE       = 0x0F
    READ_BY_GROUP_TYPE_REQUEST   = 0x10
    READ_BY_GROUP_TYPE_RESPONSE  = 0x11
    WRITE_REQUEST                = 0x12
    WRITE_RESPONSE               = 0x13
    WRITE_COMMAND                = 0x52
    PREPARE_WRITE_REQUEST        = 0x16
    PREPARE_WRITE_RESPONSE       = 0x17
    EXECUTE_WRITE_REQUEST        = 0x18
    EXECUTE_WRITE_RESPONSE       = 0x19
    HANDLE_VALUE_NOTIFICATION    = 0x1B
    HANDLE_VALUE_INDICATION      = 0x1D
    HANDLE_VALUE_CONFIRMATION    = 0x1E
    SIGNED_WRITE_COMMAND         = 0xD2
```

Each PDU is a `@dataclass` with `to_bytes()` + `decode_att_pdu()` dispatcher.

- [ ] **Step 4: Implement `ATTBearer` class**

```python
class ATTBearer:
    def __init__(self, channel: Channel, mtu: int = 23) -> None: ...
    async def exchange_mtu(self, mtu: int) -> int: ...
    async def read(self, handle: int) -> bytes: ...
    async def write(self, handle: int, value: bytes) -> None: ...
    async def write_without_response(self, handle: int, value: bytes) -> None: ...
    # Long attribute operations (attributes larger than MTU):
    async def read_blob(self, handle: int, offset: int) -> bytes: ...
    async def read_long(self, handle: int) -> bytes:
        """Read attribute value longer than MTU via repeated Read_Blob_Request."""
        result = b""
        offset = 0
        while True:
            chunk = await self.read_blob(handle, offset)
            result += chunk
            if len(chunk) < (self._mtu - 1):
                break
            offset += len(chunk)
        return result
    async def prepare_write(self, handle: int, offset: int, value: bytes) -> bytes: ...
    async def execute_write(self, flags: int) -> None: ...
    async def write_long(self, handle: int, value: bytes) -> None:
        """Write attribute longer than MTU via Prepare_Write + Execute_Write."""
        chunk_size = self._mtu - 5
        for i, offset in enumerate(range(0, len(value), chunk_size)):
            await self.prepare_write(handle, offset, value[offset:offset+chunk_size])
        await self.execute_write(0x01)
    # Internal: pending request futures keyed by response opcode
    async def _request(self, pdu: ATTPdu, response_opcode: int) -> ATTPdu: ...
    async def _on_pdu(self, data: bytes) -> None:
        # Decode PDU → if response: resolve pending future
        #              if notification/indication: call registered handler
```

Add to `tests/unit/ble/test_att.py`:

```python
@pytest.mark.asyncio
async def test_att_bearer_read_blob():
    """ATTBearer.read_blob sends Read_Blob_Request, awaits Read_Blob_Response."""
    from pybluehost.ble.att import ATTBearer, ATT_Read_Blob_Request, ATT_Read_Blob_Response
    # Verify ATT_Read_Blob_Request encodes correctly
    pdu = ATT_Read_Blob_Request(attribute_handle=0x0003, value_offset=5)
    raw = pdu.to_bytes()
    assert raw[0] == ATTOpcode.READ_BLOB_REQUEST
    assert int.from_bytes(raw[1:3], "little") == 0x0003
    assert int.from_bytes(raw[3:5], "little") == 5
```

- [ ] **Step 5: Run tests — verify they pass**

- [ ] **Step 6: Commit**
```bash
git add pybluehost/ble/att.py tests/unit/ble/test_att.py
git commit -m "feat(ble): add ATT PDU codec and ATTBearer request/response machinery"
```

---

## Task 2: GATT Layer

**Files:** `pybluehost/ble/gatt.py`, `tests/unit/ble/test_gatt.py`

- [ ] **Step 1: Write failing GATT tests**

```python
# tests/unit/ble/test_gatt.py
import pytest
from pybluehost.ble.gatt import (
    AttributeDatabase, GATTServer,
    ServiceDefinition, CharacteristicDefinition,
    CharProperties, Permissions,
)
from pybluehost.core.uuid import UUID16

def test_attribute_database_add_and_read():
    db = AttributeDatabase()
    handle = db.add(type_uuid=UUID16(0x2800), permissions=Permissions.READABLE, value=b"\x0D\x18")
    assert handle == 0x0001
    assert db.read(handle) == b"\x0D\x18"

def test_attribute_database_write():
    db = AttributeDatabase()
    handle = db.add(UUID16(0x2803), Permissions.READABLE | Permissions.WRITABLE, b"\x00")
    db.write(handle, b"\xFF")
    assert db.read(handle) == b"\xFF"

def test_gatt_server_add_service_expands_attributes():
    server = GATTServer()
    svc = ServiceDefinition(
        uuid=UUID16(0x180D),
        characteristics=[
            CharacteristicDefinition(
                uuid=UUID16(0x2A37),
                properties=CharProperties.NOTIFY,
                permissions=Permissions.READABLE,
            )
        ]
    )
    handles = server.add_service(svc)
    # Service Declaration (0x2800) + Characteristic Declaration (0x2803) + Value + CCCD
    assert handles.service_handle == 0x0001
    assert handles.characteristic_handles[0].declaration_handle == 0x0002
    assert handles.characteristic_handles[0].value_handle == 0x0003
    assert handles.characteristic_handles[0].cccd_handle == 0x0004

def test_gatt_server_on_read_callback():
    server = GATTServer()
    svc = ServiceDefinition(
        uuid=UUID16(0x180D),
        characteristics=[
            CharacteristicDefinition(
                uuid=UUID16(0x2A38),
                properties=CharProperties.READ,
                permissions=Permissions.READABLE,
                value=b"\x01",
            )
        ]
    )
    server.add_service(svc)
    # Read characteristic value directly from attribute database
    val = server.db.read(0x0003)  # value handle
    assert val == b"\x01"

@pytest.mark.asyncio
async def test_gatt_server_handle_read_request():
    from pybluehost.ble.att import ATT_Read_Request, ATT_Read_Response
    server = GATTServer()
    svc = ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A38), properties=CharProperties.READ,
                                  permissions=Permissions.READABLE, value=b"\x42")
    ])
    server.add_service(svc)
    req = ATT_Read_Request(attribute_handle=0x0003)
    response = await server.handle_request(conn_handle=0x0001, pdu=req)
    assert isinstance(response, ATT_Read_Response)
    assert response.attribute_value == b"\x42"

@pytest.mark.asyncio
async def test_gatt_server_notify():
    from pybluehost.ble.gatt import GATTServer, ServiceDefinition, CharacteristicDefinition, CharProperties, Permissions
    from pybluehost.core.uuid import UUID16
    server = GATTServer()
    svc = ServiceDefinition(uuid=UUID16(0x180D), characteristics=[
        CharacteristicDefinition(uuid=UUID16(0x2A37), properties=CharProperties.NOTIFY,
                                  permissions=Permissions.READABLE)
    ])
    server.add_service(svc)
    notifications = []
    server.on_notification_sent(lambda handle, value, conn: notifications.append((handle, value)))
    # Triggering notify for connection 0x0040 with CCCD enabled
    server.enable_notifications(conn_handle=0x0040, value_handle=0x0003)
    await server.notify(handle=0x0003, value=bytes([0x00, 72]), connections=[0x0040])
    assert len(notifications) == 1
    assert notifications[0][1] == bytes([0x00, 72])
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `gatt.py`**

- `Permissions(Flag)`: READABLE, WRITABLE, READABLE_ENCRYPTED, WRITABLE_ENCRYPTED
- `CharProperties(Flag)`: READ, WRITE, NOTIFY, INDICATE, WRITE_WITHOUT_RESPONSE, etc.
- `Attribute(dataclass)`: handle, type_uuid, permissions, value (bytes or callable)
- `AttributeDatabase`: linear list, handle auto-increment from 0x0001, find_by_type, find_by_group
- `ServiceDefinition(dataclass)`, `CharacteristicDefinition(dataclass)`, `DescriptorDefinition(dataclass)`
- `GATTServer.add_service(svc)`: expand to attribute sequence: Service Declaration → Char Declaration → Value → CCCD (if notify/indicate) → Descriptors
- `GATTServer.handle_request(conn_handle, pdu)`: dispatch ATT opcode → read/write DB → return response PDU
- `GATTServer` additional notification/indication API:
  ```python
  class GATTServer:
      # Additional methods:
      async def notify(self, handle: int, value: bytes, connections: list[int] | None = None) -> None: ...
      async def indicate(self, handle: int, value: bytes, connection: int) -> None: ...
      def enable_notifications(self, conn_handle: int, value_handle: int) -> None:
          """Called when remote writes 0x0001 to CCCD — enables notifications."""
      def on_notification_sent(self, handler) -> None:
          """Register callback invoked after each notification is sent."""
      def find_characteristic_value_handle(self, uuid: UUID) -> int | None:
          """Find value handle for a characteristic by UUID."""
  ```
- `GATTClient`: async methods wrapping ATTBearer calls + parsing response PDUs

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**
```bash
git add pybluehost/ble/gatt.py tests/unit/ble/test_gatt.py
git commit -m "feat(ble): add GATT AttributeDatabase, GATTServer and GATTClient"
```

---

## Task 3: SMP Layer

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

## Task 4: SecurityConfig + CTKDManager

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

## Task 5: Package Exports + Final Validation

- [ ] **Step 1: Write `pybluehost/ble/__init__.py`**

```python
from pybluehost.ble.att import (
    ATTOpcode, ATTPdu, ATTBearer,
    ATT_Read_Request, ATT_Read_Response,
    ATT_Write_Request, ATT_Write_Response,
    ATT_Handle_Value_Notification, ATT_Handle_Value_Indication,
    decode_att_pdu,
)
from pybluehost.ble.gatt import (
    Permissions, CharProperties,
    Attribute, AttributeDatabase,
    ServiceDefinition, CharacteristicDefinition, DescriptorDefinition,
    GATTServer, GATTClient,
)
from pybluehost.ble.smp import (
    SMPCode, SMPManager, SMPCrypto, SMPState,
    BondInfo, BondStorage,          # dataclass + Protocol interface
    JsonBondStorage,                # Concrete JSON implementation
    PairingDelegate, AutoAcceptDelegate,
)
from pybluehost.ble.security import (
    SecurityConfig, CTKDDirection, CTKDManager,
)

__all__ = [
    "ATTOpcode", "ATTPdu", "ATTBearer",
    "ATT_Read_Request", "ATT_Read_Response",
    "ATT_Write_Request", "ATT_Write_Response",
    "ATT_Handle_Value_Notification", "ATT_Handle_Value_Indication",
    "decode_att_pdu",
    "Permissions", "CharProperties",
    "Attribute", "AttributeDatabase",
    "ServiceDefinition", "CharacteristicDefinition", "DescriptorDefinition",
    "GATTServer", "GATTClient",
    "SMPCode", "SMPManager", "SMPCrypto", "SMPState",
    "BondInfo", "BondStorage", "JsonBondStorage",
    "PairingDelegate", "AutoAcceptDelegate",
    "SecurityConfig", "CTKDDirection", "CTKDManager",
]
```

- [ ] **Step 2: Run all BLE tests + full suite**
```bash
uv run pytest tests/unit/ble/ -v
uv run pytest tests/ -v --tb=short
```

- [ ] **Step 3: Commit + update STATUS.md**
```bash
git add pybluehost/ble/__init__.py
git commit -m "feat(ble): finalize BLE package exports"

# Update STATUS.md: Plan 5 ✅, Plan 6 🔄
git add docs/superpowers/STATUS.md
git commit -m "docs: mark Plan 5 (BLE stack) complete in STATUS.md"
```

---

## 审查补充事项 (2026-04-18 审查后追加)

以下事项在深度审查中发现遗漏，需要在执行时补充到对应 Task 中。

### 补充 1: GATT Service Changed Indication（PRD §5.4, 架构 09-ble-stack.md §9.3）

GATT Service 0x1801 需要支持 Service Changed Characteristic (0x2A05):
- 当 GATT 数据库动态更新时（添加/删除 service），发送 indication 给订阅了的 client
- 包含受影响的 attribute handle 范围
- Client 收到后应重新 discover services
- 测试：GATTServer 增删 service → 验证 indication 发送 → Client 重新 discover

### 补充 2: GATT Client Discovery 完整流程测试

架构 09-ble-stack.md §9.3 定义了完整的 discovery API：
- `discover_all_services()` → ATT_Read_By_Group_Type_Request
- `discover_characteristics(service)` → ATT_Read_By_Type_Request
- `discover_descriptors(char)` → ATT_Find_Information_Request

需要补充完整 discovery 流程的 E2E 测试（通过 Loopback 双角色验证）。

### 补充 3: SMP IO Capability 矩阵测试（架构 09-ble-stack.md §9.4）

BT Core Spec Table 2.8 定义 5×5=25 种 IO Capability 组合，每种对应不同配对模型：
- DisplayOnly × DisplayOnly → Just Works
- DisplayYesNo × DisplayYesNo → Numeric Comparison (SC) / Just Works (Legacy)
- KeyboardOnly × DisplayOnly → Passkey Entry
- ...等

至少需要覆盖 4 种配对模型各 1-2 个代表性组合的测试。

### 补充 4: SecurityConfig + CTKDManager（架构 09-ble-stack.md §9.4）

Plan 文件结构列出了 `ble/security.py` 但没有对应 Task。需要补充：

```python
@dataclass
class SecurityConfig:
    io_capability: IOCapability = IOCapability.NO_INPUT_NO_OUTPUT
    mitm_required: bool = False
    sc_only: bool = False
    bond: bool = True
    ctkd_enabled: bool = False

class CTKDManager:
    """Cross-Transport Key Derivation (h6/h7 functions)."""
    async def derive_br_edr_key_from_le(self, ltk: LTK) -> LinkKey: ...
    async def derive_le_key_from_br_edr(self, link_key: LinkKey) -> LTK: ...
```

- h6/h7 加密函数需要 Spec 附录 D 测试向量
- CTKD 流程需要完整状态机测试

### 补充 5: SMP c1 测试需要精确断言

当前 c1 测试只检查 `len(result) == 16`，应对比 BT Core Spec 附录 D.1 的精确值：

```python
def test_smp_c1_spec_vector():
    # Spec Appendix D.1 test vector
    k = bytes.fromhex("00000000000000000000000000000000")
    r = bytes.fromhex("e0 2e 70 c6 4e 27 88 63 0e 2e 69 85 d2 ea 03 24".replace(" ", ""))
    preq = bytes.fromhex("07071000000100")
    pres = bytes.fromhex("05000800000302")
    iat = 0x01
    rat = 0x00
    ia = bytes.fromhex("a6 0a 71 47 a2 00".replace(" ", ""))
    ra = bytes.fromhex("a1 ab 57 c1 23 00".replace(" ", ""))
    expected = bytes.fromhex("86 3b c2 b8 e5 c4 86 36 72 98 16 e6 ee 2c 40 de".replace(" ", ""))
    assert smp_c1(k, r, preq, pres, iat, rat, ia, ra) == expected
```

### 补充 6: SMP f5 测试地址截断说明

Plan 中 `A2 = bytes.fromhex("00a713702dcfc1")[:6]` 截断了 7 字节到 6 字节。这是因为地址前缀包含地址类型字节（1 byte type + 6 bytes addr）。需要在注释中说明这一点，或改为：

```python
A2_type = 0x00  # public address
A2_addr = bytes.fromhex("a713702dcfc1")
A2 = bytes([A2_type]) + A2_addr  # 7 bytes: type + addr
```

### 补充 7: 拆分建议（已在 STATUS.md 标注）

- **Plan 6a — ATT + GATT**: att.py（全部 PDU + ATTBearer 客户端+服务端）, gatt.py（AttributeDatabase + GATTServer + GATTClient + Service Changed）
- **Plan 6b — SMP + Security**: smp.py（SMPManager + 9 个加密函数 + BondStorage + IO Capability 矩阵）, security.py（SecurityConfig + CTKDManager）

可并行开发，技术风险不同（GATT = 数据库设计，SMP = 密码学正确性）。
