# 第十一节：GAP 详细设计（BLE + Classic）

## 11.1 模块划分

```
ble/gap.py           # BLE GAP
classic/gap.py       # Classic GAP
core/gap_common.py   # 共享类型
```

## 11.2 共享类型

地址类型定义在 `core/address.py`（全栈唯一定义），GAP 特有类型定义在 `core/gap_common.py`。

### `core/address.py`（地址相关，全栈共享）

```python
class AddressType(IntEnum):
    PUBLIC = 0x00; RANDOM = 0x01
    PUBLIC_IDENTITY = 0x02; RANDOM_IDENTITY = 0x03

@dataclass(frozen=True)
class BDAddress:
    address: bytes   # 6 bytes
    type: AddressType = AddressType.PUBLIC
    @classmethod
    def from_string(cls, s: str, type: ...) -> "BDAddress": ...
    @classmethod
    def random(cls) -> "BDAddress": ...
    @property
    def is_rpa(self) -> bool: ...
```

### `core/gap_common.py`（GAP 特有类型）

```python
class ClassOfDevice: ...
class ServiceClass(Flag): ...
class Appearance(IntEnum): ...
class FilterPolicy(Enum): ...

@dataclass
class DeviceInfo:
    """设备发现结果（BLE 和 Classic 统一）"""
    address: BDAddress
    name: str | None = None
    rssi: int | None = None
    advertising_data: AdvertisingData | None = None  # BLE
    class_of_device: ClassOfDevice | None = None     # Classic
```

## 11.3 BLE GAP

### Advertising

```python
class AdvertisingData:
    """AD Structure 编解码"""
    def set_flags(self, flags: int = 0x06) -> None: ...
    def set_complete_local_name(self, name: str) -> None: ...
    def add_service_uuid16(self, uuid: int) -> None: ...
    def set_manufacturer_specific(self, company_id: int, data: bytes) -> None: ...
    def to_bytes(self) -> bytes: ...
    @classmethod
    def from_bytes(cls, data: bytes) -> "AdvertisingData": ...

class BLEAdvertiser:
    async def start(self, config: AdvertisingConfig, ad_data: AdvertisingData,
                     scan_rsp_data: AdvertisingData | None = None) -> None: ...
    async def stop(self) -> None: ...
    async def update_data(self, ad_data: AdvertisingData) -> None: ...

class ExtendedAdvertiser:
    """Extended Advertising (Bluetooth 5.0+)：多广播集、长数据、多 PHY"""
    async def create_set(self, handle: int = 0, config: ExtAdvConfig | None = None) -> None: ...
    async def set_data(self, handle: int, data: AdvertisingData) -> None: ...
    async def start(self, handles: list[int], durations: list[float] | None = None) -> None: ...
    async def stop(self, handles: list[int] | None = None) -> None: ...
```

### Scanning

```python
class BLEScanner:
    async def start(self, config: ScanConfig = ScanConfig()) -> None: ...
    async def stop(self) -> None: ...
    def on_result(self, handler: Callable[[ScanResult], Awaitable]) -> None: ...
    async def scan_for(self, duration: float, config: ...) -> list[ScanResult]: ...

@dataclass
class ScanResult:
    address: BDAddress
    rssi: int
    advertising_data: AdvertisingData
    connectable: bool = True
```

### BLE Connection Management

```python
class BLEConnectionManager:
    async def connect(self, target: BDAddress, config: BLEConnectionConfig = ...) -> BLEConnection: ...
    async def cancel_connect(self) -> None: ...
    def on_connection(self, handler: ...) -> None: ...
    async def update_connection_parameters(self, handle: int, ...) -> None: ...
    async def disconnect(self, handle: int, reason: int = 0x13) -> None: ...

@dataclass
class BLEConnection:
    handle: int
    peer_address: BDAddress
    role: ConnectionRole
    att: ATTBearer | None = None
    gatt_client: GATTClient | None = None
    gatt_server: GATTServer | None = None
    smp: SMPManager | None = None
```

### BLE Privacy（RPA）

```python
class PrivacyManager:
    async def enable(self, irk: bytes | None = None) -> None: ...
    async def disable(self) -> None: ...
    async def add_peer_irk(self, address: BDAddress, irk: bytes) -> None: ...
    @staticmethod
    def resolve_rpa(rpa: BDAddress, irk: bytes) -> bool: ...
    # 内部：定期轮换 RPA（默认 15 分钟）
```

## 11.4 Classic GAP

### Inquiry（设备发现）

```python
class ClassicDiscovery:
    async def start(self, config: InquiryConfig = InquiryConfig()) -> None: ...
    async def stop(self) -> None: ...
    def on_result(self, handler: ...) -> None: ...
    async def discover(self, duration: float = 10.0) -> list[InquiryResult]: ...
    async def request_name(self, address: BDAddress) -> str: ...
```

### Inquiry Scan（被发现）

```python
class ClassicDiscoverability:
    async def set_discoverable(self, enabled: bool) -> None: ...
    async def set_connectable(self, enabled: bool) -> None: ...
    async def set_device_name(self, name: str) -> None: ...
    async def set_class_of_device(self, cod: ClassOfDevice) -> None: ...
    async def set_eir(self, eir_data: bytes) -> None: ...
```

### Classic Connection Management

```python
class ClassicConnectionManager:
    async def connect(self, target: BDAddress, config: ...) -> ClassicConnection: ...
    async def disconnect(self, handle: int, reason: int = 0x13) -> None: ...
    def on_connection(self, handler: ...) -> None: ...
```

### Classic SSP

```python
class SSPManager:
    """Secure Simple Pairing（含 BR/EDR Secure Connections P-256）"""
    def set_delegate(self, delegate: PairingDelegate) -> None: ...
    # 处理 HCI 事件：
    # IO_Capability_Request → Reply
    # User_Confirmation_Request → delegate.confirm_numeric()
    # User_Passkey_Request → delegate.request_passkey()
    # Link_Key_Notification → BondStorage.save_bond()
    # Link_Key_Request → BondStorage.load_bond()
```

## 11.5 统一 GAP 入口

```python
class GAP:
    @property
    def ble_advertiser(self) -> BLEAdvertiser: ...
    @property
    def ble_extended_advertiser(self) -> ExtendedAdvertiser: ...
    @property
    def ble_scanner(self) -> BLEScanner: ...
    @property
    def ble_connections(self) -> BLEConnectionManager: ...
    @property
    def ble_privacy(self) -> PrivacyManager: ...
    @property
    def classic_discovery(self) -> ClassicDiscovery: ...
    @property
    def classic_discoverability(self) -> ClassicDiscoverability: ...
    @property
    def classic_connections(self) -> ClassicConnectionManager: ...
    @property
    def classic_ssp(self) -> SSPManager: ...
    @property
    def whitelist(self) -> WhiteList: ...

    def set_pairing_delegate(self, delegate: PairingDelegate) -> None:
        """统一设置配对代理（BLE SMP + Classic SSP 共用）"""
```
