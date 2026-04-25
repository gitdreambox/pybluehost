# Plan 6a: ATT + GATT

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement `pybluehost/ble/att.py`, `ble/gatt.py` — ATT PDU codec, ATT Bearer request/response machinery, GATT Server/Client with ServiceDefinition, and Service Changed indication.

**Architecture reference:** `docs/architecture/09-ble-stack.md`

**Dependencies:** `pybluehost/core/`, `pybluehost/l2cap/`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/ble/__init__.py` | Re-export ATT + GATT public API |
| `pybluehost/ble/att.py` | ATT PDU types + `ATTBearer` |
| `pybluehost/ble/gatt.py` | `AttributeDatabase`, `GATTServer`, `GATTClient` |
| `tests/unit/ble/__init__.py` | |
| `tests/unit/ble/test_att.py` | ATT PDU encode/decode + Bearer request/response |
| `tests/unit/ble/test_gatt.py` | GATT Server attribute database + read/write |

---

## Task 1: ATT PDU Codec

**Files:** `pybluehost/ble/att.py` (PDU types only), `tests/unit/ble/test_att.py`

- [x] **Step 1: Write failing ATT PDU tests**

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

- [x] **Step 2: Run tests — verify they fail**

- [x] **Step 3: Implement ATT PDU codec in `att.py`**

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

- [x] **Step 4: Implement `ATTBearer` class**

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

- [x] **Step 5: Run tests — verify they pass**

- [x] **Step 6: Commit**
```bash
git add pybluehost/ble/att.py tests/unit/ble/test_att.py
git commit -m "feat(ble): add ATT PDU codec and ATTBearer request/response machinery"
```

---

## Task 2: GATT Layer

**Files:** `pybluehost/ble/gatt.py`, `tests/unit/ble/test_gatt.py`

- [x] **Step 1: Write failing GATT tests**

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

- [x] **Step 2: Run tests — verify they fail**

- [x] **Step 3: Implement `gatt.py`**

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

- [x] **Step 4: Run tests — verify they pass**

- [x] **Step 5: Commit**
```bash
git add pybluehost/ble/gatt.py tests/unit/ble/test_gatt.py
git commit -m "feat(ble): add GATT AttributeDatabase, GATTServer and GATTClient"
```

---

## Task 3: Package Exports + Final Validation

- [x] **Step 1: Write `pybluehost/ble/__init__.py`** (ATT + GATT exports)

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
]
```

- [x] **Step 2: Run all ATT + GATT tests + full suite**
```bash
uv run pytest tests/unit/ble/test_att.py tests/unit/ble/test_gatt.py -v
uv run pytest tests/ -v --tb=short
```

- [x] **Step 3: Commit + update STATUS.md**
```bash
git add pybluehost/ble/__init__.py
git commit -m "feat(ble): finalize ATT + GATT package exports"

# Update STATUS.md: Plan 6a ✅
git add docs/superpowers/STATUS.md
git commit -m "docs: mark Plan 6a (ATT + GATT) complete in STATUS.md"
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
