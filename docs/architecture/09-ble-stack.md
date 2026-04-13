# 第九节：BLE 协议栈详细设计（ATT / GATT / SMP）

## 9.1 模块划分

```
ble/
├── att.py          # ATT 协议层：PDU encode/decode + ATT Bearer
├── gatt.py         # GATT Client + Server + Service/Characteristic 定义
├── smp.py          # SMP 配对 + 密钥管理 + Bond 持久化 + CTKD
└── gap.py          # BLE GAP（见第十一节）
```

## 9.2 ATT 层

### ATT PDU 类型

完整覆盖所有 ATT opcode（0x01-0x1D, 0x52, 0xD2），每种 opcode 一个 dataclass。

### ATT Bearer

```python
class ATTBearer:
    """通过 L2CAP Fixed Channel (CID=0x0004) 收发 ATT PDU"""

    # Client 侧请求/响应
    async def exchange_mtu(self, mtu: int) -> int: ...
    async def read(self, handle: int) -> bytes: ...
    async def read_blob(self, handle: int, offset: int) -> bytes: ...
    async def read_by_type(self, start: int, end: int, uuid: UUID) -> list: ...
    async def read_by_group_type(self, start: int, end: int, uuid: UUID) -> list: ...
    async def write(self, handle: int, value: bytes) -> None: ...
    async def write_without_response(self, handle: int, value: bytes) -> None: ...
    async def prepare_write(self, handle: int, offset: int, value: bytes) -> bytes: ...
    async def execute_write(self, flags: int) -> None: ...

    # 通知/指示回调
    def on_notification(self, handler: Callable[[int, bytes], Awaitable]) -> None: ...
    def on_indication(self, handler: Callable[[int, bytes], Awaitable]) -> None: ...

    # Long Attribute 便捷方法
    async def read_long(self, handle: int) -> bytes: ...
    async def write_long(self, handle: int, value: bytes) -> None: ...

    # 内部：request → Future 匹配 → response
    async def _request(self, pdu: ATTPdu) -> ATTPdu: ...
```

## 9.3 GATT 层

### Attribute Database（Server 侧）

```python
@dataclass
class Attribute:
    handle: int
    type_uuid: UUID
    permissions: Permissions
    value: bytes | Callable[[], bytes]  # 静态值或动态回调

class Permissions(Flag):
    READABLE = auto()
    WRITABLE = auto()
    READABLE_ENCRYPTED = auto()
    WRITABLE_ENCRYPTED = auto()
    READABLE_AUTHENTICATED = auto()
    WRITABLE_AUTHENTICATED = auto()

class AttributeDatabase:
    """线性 attribute 表，handle 从 0x0001 递增"""
    def add(self, type_uuid: UUID, permissions: Permissions, value: ...) -> int: ...
    def read(self, handle: int) -> bytes: ...
    def write(self, handle: int, value: bytes) -> None: ...
    def find_by_type(self, ...) -> list[Attribute]: ...
    def find_by_group(self, ...) -> list[AttributeGroup]: ...
```

### Service / Characteristic 定义

```python
@dataclass
class ServiceDefinition:
    uuid: UUID
    characteristics: list[CharacteristicDefinition]
    is_primary: bool = True
    included_services: list[UUID] = field(default_factory=list)

@dataclass
class CharacteristicDefinition:
    uuid: UUID
    properties: CharProperties    # Read | Write | Notify | Indicate | ...
    permissions: Permissions
    value: bytes | Callable = b""
    descriptors: list[DescriptorDefinition] = field(default_factory=list)

class CharProperties(Flag):
    BROADCAST = 0x01
    READ = 0x02
    WRITE_WITHOUT_RESPONSE = 0x04
    WRITE = 0x08
    NOTIFY = 0x10
    INDICATE = 0x20
    AUTHENTICATED_SIGNED_WRITES = 0x40
    EXTENDED_PROPERTIES = 0x80
```

### GATT Server

```python
class GATTServer:
    def add_service(self, service: ServiceDefinition) -> ServiceHandle: ...
    async def notify(self, handle: int, value: bytes, connections: list[int] | None = None) -> None: ...
    async def indicate(self, handle: int, value: bytes, connection: int) -> None: ...
    async def handle_request(self, conn_handle: int, pdu: ATTPdu) -> ATTPdu: ...
```

`add_service` 自动展开为 attribute 序列：Service Declaration → Characteristic Declaration → Value → CCCD → Descriptors。

### GATT Client

```python
class GATTClient:
    async def discover_all_services(self) -> list[Service]: ...
    async def discover_characteristics(self, service: Service) -> list[Characteristic]: ...
    async def discover_descriptors(self, char: Characteristic, end_handle: int) -> list[Descriptor]: ...
    async def read_characteristic(self, char: Characteristic) -> bytes: ...
    async def write_characteristic(self, char: Characteristic, value: bytes, response: bool = True) -> None: ...
    async def subscribe(self, char: Characteristic, handler: ..., indication: bool = False) -> None: ...
    async def unsubscribe(self, char: Characteristic) -> None: ...
```

## 9.4 SMP 层

### 配对状态机

```python
class SMPState(Enum):
    IDLE = auto()
    W4_PAIRING_RSP = auto()
    W4_PAIRING_REQ = auto()
    W4_PUBLIC_KEY = auto()       # SC
    W4_CONFIRM = auto()          # Legacy
    W4_RANDOM = auto()           # Legacy
    W4_DHKEY_CHECK = auto()      # SC
    W4_USER_CONFIRM = auto()     # Numeric Comparison / Passkey
    W4_LTK = auto()
    W4_ENCRYPTION = auto()
    W4_CTKD = auto()             # Cross-Transport Key Derivation
    BONDED = auto()
```

### SMP Manager

```python
class SMPManager:
    async def pair(self, connection: int, io_capability: IOCapability = ...,
                    bonding: bool = True, sc: bool = True) -> PairingResult: ...
    def on_pairing_request(self, handler: PairingRequestHandler) -> None: ...
    def set_bond_storage(self, storage: BondStorage) -> None: ...
```

### IO Capability 矩阵

根据 Bluetooth Core Spec Table 2.8 (SC) / Table 2.7 (Legacy) 确定配对模型：
- Just Works / Numeric Comparison / Passkey Entry / OOB

### 加密函数

```python
class SMPCrypto:
    @staticmethod
    def c1(k, r, preq, pres, iat, rat, ia, ra) -> bytes: ...  # Legacy Confirm
    @staticmethod
    def s1(k, r1, r2) -> bytes: ...                            # Legacy STK
    @staticmethod
    def f4(u, v, x, z) -> bytes: ...                           # SC Confirm
    @staticmethod
    def f5(w, n1, n2, a1, a2) -> tuple[bytes, bytes]: ...      # SC LTK + MacKey
    @staticmethod
    def f6(w, n1, n2, r, io_cap, a1, a2) -> bytes: ...         # SC DHKey Check
    @staticmethod
    def g2(u, v, x, y) -> int: ...                             # Numeric Comparison
    @staticmethod
    def ah(irk, r) -> bytes: ...                                # RPA hash
```

### Security Configuration

```python
class SecurityConfig:
    le_sc_enabled: bool = True
    le_legacy_allowed: bool = True
    le_sc_only: bool = False
    bredr_sc_enabled: bool = True
    bredr_sc_only: bool = False
    ctkd_enabled: bool = False              # 默认关闭，用户显式开启
    ctkd_direction: CTKDDirection = CTKDDirection.BOTH

class CTKDDirection(Enum):
    LE_TO_BREDR = "le_to_bredr"
    BREDR_TO_LE = "bredr_to_le"
    BOTH = "both"
```

### CTKD（Cross-Transport Key Derivation）

```python
class CTKDManager:
    """CTKD：BLE LTK ↔ Classic Link Key 互相派生"""
    async def derive_br_edr_from_le(self, connection: int, ltk: bytes) -> LinkKey: ...
    async def derive_le_from_br_edr(self, connection: int, link_key: bytes) -> bytes: ...
    @staticmethod
    def h6(key: bytes, key_id: str) -> bytes: ...
    @staticmethod
    def h7(salt: bytes, key: bytes) -> bytes: ...
```

CTKD 仅在 `SecurityConfig.ctkd_enabled = True` 时触发，且要求双方都使用 Secure Connections。

### Bond 持久化

```python
class BondStorage(Protocol):
    async def save_bond(self, address: BDAddress, bond: BondInfo) -> None: ...
    async def load_bond(self, address: BDAddress) -> BondInfo | None: ...
    async def delete_bond(self, address: BDAddress) -> None: ...
    async def list_bonds(self) -> list[BDAddress]: ...

@dataclass
class BondInfo:
    peer_address: BDAddress
    address_type: AddressType
    ltk: bytes | None = None
    irk: bytes | None = None
    csrk: bytes | None = None
    ediv: int = 0
    rand: int = 0
    key_size: int = 16
    authenticated: bool = False
    sc: bool = False
    link_key: bytes | None = None        # BR/EDR
    link_key_type: LinkKeyType | None = None
    ctkd_derived: bool = False

class JsonBondStorage(BondStorage):
    """JSON 文件后端（默认实现）"""
    # {data_dir}/bonds/{address}.json
```

### 用户交互（PairingDelegate）

```python
class PairingDelegate(Protocol):
    async def confirm_numeric(self, connection: int, number: int) -> bool: ...
    async def request_passkey(self, connection: int) -> int: ...
    async def display_passkey(self, connection: int, passkey: int) -> None: ...
    async def confirm_pairing(self, connection: int, peer: BDAddress) -> bool: ...

class AutoAcceptDelegate(PairingDelegate):
    """默认实现：自动接受一切（适用于测试）"""
```
