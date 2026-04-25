# Plan 8a: BLE GAP

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement BLE GAP layer: `core/gap_common.py` (shared types), `ble/gap.py` (BLEAdvertiser, ExtendedAdvertiser, BLEScanner, BLEConnectionManager, PrivacyManager, WhiteList).

**Architecture reference:** `docs/architecture/11-gap.md`

**Dependencies:** `pybluehost/core/`, `pybluehost/hci/`, `pybluehost/ble/`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/core/gap_common.py` | `ClassOfDevice`, `Appearance`, `FilterPolicy`, `AdvertisingData`, `DeviceInfo` |
| `pybluehost/ble/gap.py` | `BLEAdvertiser`, `ExtendedAdvertiser`, `BLEScanner`, `BLEConnectionManager`, `PrivacyManager`, `WhiteList` |
| `tests/unit/core/test_gap_common.py` | AdvertisingData encode/decode |
| `tests/unit/ble/test_gap.py` | BLE GAP unit tests |

---

## Task 1: Shared GAP Types + AdvertisingData

**Files:** `pybluehost/core/gap_common.py`, `tests/unit/core/test_gap_common.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/core/test_gap_common.py
from pybluehost.core.gap_common import AdvertisingData, Appearance, ClassOfDevice

def test_advertising_data_flags():
    ad = AdvertisingData()
    ad.set_flags(0x06)  # BR/EDR not supported, LE General Discoverable
    raw = ad.to_bytes()
    assert raw[0] == 2     # length
    assert raw[1] == 0x01  # AD type: Flags
    assert raw[2] == 0x06

def test_advertising_data_complete_name():
    ad = AdvertisingData()
    ad.set_complete_local_name("PyBH")
    raw = ad.to_bytes()
    assert 0x09 in raw  # AD type: Complete Local Name
    idx = raw.index(0x09)
    assert raw[idx+1:idx+5] == b"PyBH"

def test_advertising_data_uuid16():
    ad = AdvertisingData()
    ad.add_service_uuid16(0x180D)  # Heart Rate
    raw = ad.to_bytes()
    assert 0x03 in raw  # AD type: 16-bit UUIDs
    # 0x0D18 in little-endian
    assert b"\x0D\x18" in raw

def test_advertising_data_manufacturer():
    ad = AdvertisingData()
    ad.set_manufacturer_specific(company_id=0x0006, data=b"\xAB\xCD")  # Microsoft
    raw = ad.to_bytes()
    assert 0xFF in raw  # AD type: Manufacturer Specific

def test_advertising_data_from_bytes_roundtrip():
    ad = AdvertisingData()
    ad.set_flags(0x06)
    ad.set_complete_local_name("Test")
    raw = ad.to_bytes()
    decoded = AdvertisingData.from_bytes(raw)
    assert decoded.get_complete_local_name() == "Test"

def test_appearance_enum():
    assert Appearance.GENERIC_PHONE == 0x0040
    assert Appearance.HEART_RATE_SENSOR == 0x0341

def test_class_of_device():
    cod = ClassOfDevice(major_device_class=0x01, minor_device_class=0x04, service_class=0x200)
    assert cod.to_int() == (0x200 << 13) | (0x01 << 8) | (0x04 << 2)
```

- [x] **Step 2: Run tests — verify they fail**

- [x] **Step 3: Implement `gap_common.py`**

```python
class Appearance(IntEnum):
    UNKNOWN                = 0x0000
    GENERIC_PHONE          = 0x0040
    GENERIC_COMPUTER       = 0x0080
    GENERIC_WATCH          = 0x00C0
    SPORTS_WATCH           = 0x00C1
    GENERIC_CLOCK          = 0x0100
    GENERIC_DISPLAY        = 0x0140
    GENERIC_REMOTE_CONTROL = 0x0180
    GENERIC_EYE_GLASSES    = 0x01C0
    GENERIC_TAG            = 0x0200
    GENERIC_KEYRING        = 0x0240
    GENERIC_MEDIA_PLAYER   = 0x0280
    GENERIC_BARCODE_SCANNER = 0x02C0
    GENERIC_THERMOMETER    = 0x0300
    HEART_RATE_SENSOR      = 0x0341
    BLOOD_PRESSURE         = 0x0381
    GENERIC_HID            = 0x03C0
    HID_KEYBOARD           = 0x03C1
    HID_MOUSE              = 0x03C2
    CYCLING_SPEED_CADENCE  = 0x0481
    RUNNING_WALKING_SENSOR = 0x0540

class AdvertisingData:
    """AD Structure encode/decode. Stores structures as dict[ad_type → bytes]."""
    AD_FLAGS = 0x01; AD_UUID16_MORE = 0x02; AD_UUID16_COMPLETE = 0x03
    AD_UUID128_MORE = 0x06; AD_UUID128_COMPLETE = 0x07
    AD_SHORT_LOCAL_NAME = 0x08; AD_COMPLETE_LOCAL_NAME = 0x09
    AD_TX_POWER = 0x0A; AD_SLAVE_CONN_INTERVAL = 0x12
    AD_MANUFACTURER_SPECIFIC = 0xFF

    def set_flags(self, flags: int) -> None: ...
    def set_complete_local_name(self, name: str) -> None: ...
    def get_complete_local_name(self) -> str | None: ...
    def add_service_uuid16(self, uuid: int) -> None: ...
    def set_manufacturer_specific(self, company_id: int, data: bytes) -> None: ...
    def set_tx_power(self, level: int) -> None: ...
    def to_bytes(self) -> bytes: ...
    @classmethod
    def from_bytes(cls, data: bytes) -> "AdvertisingData": ...
```

- [x] **Step 4: Run tests — verify they pass**

- [x] **Step 5: Commit**
```bash
git add pybluehost/core/gap_common.py tests/unit/core/test_gap_common.py
git commit -m "feat(core): add gap_common types — AdvertisingData, Appearance, ClassOfDevice"
```

---

## Task 2: BLE GAP

**Files:** `pybluehost/ble/gap.py`, `tests/unit/ble/test_gap.py`

- [x] **Step 1: Write failing BLE GAP tests**

```python
# tests/unit/ble/test_gap.py
import asyncio, pytest
from pybluehost.ble.gap import BLEAdvertiser, BLEScanner, AdvertisingConfig, ScanConfig
from pybluehost.core.gap_common import AdvertisingData

class FakeHCI:
    def __init__(self): self.commands = []
    async def send_command(self, cmd):
        self.commands.append(cmd)
        from pybluehost.hci.packets import HCI_Command_Complete_Event
        from pybluehost.hci.constants import ErrorCode
        return HCI_Command_Complete_Event(
            num_hci_command_packets=1,
            command_opcode=cmd.opcode,
            return_parameters=bytes([ErrorCode.SUCCESS]),
        )

@pytest.mark.asyncio
async def test_advertiser_start_sends_hci_commands(tmp_path):
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    ad = AdvertisingData()
    ad.set_flags(0x06)
    ad.set_complete_local_name("Test")
    await advertiser.start(config=AdvertisingConfig(), ad_data=ad)
    # Should have sent: Set_Adv_Params, Set_Adv_Data, Set_Adv_Enable
    opcodes = [cmd.opcode for cmd in hci.commands]
    from pybluehost.hci.constants import (
        HCI_LE_SET_ADVERTISING_PARAMS, HCI_LE_SET_ADVERTISING_DATA,
        HCI_LE_SET_ADVERTISE_ENABLE,
    )
    assert HCI_LE_SET_ADVERTISING_PARAMS in opcodes
    assert HCI_LE_SET_ADVERTISING_DATA in opcodes
    assert HCI_LE_SET_ADVERTISE_ENABLE in opcodes

@pytest.mark.asyncio
async def test_advertiser_stop(tmp_path):
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    ad = AdvertisingData()
    await advertiser.start(config=AdvertisingConfig(), ad_data=ad)
    hci.commands.clear()
    await advertiser.stop()
    opcodes = [cmd.opcode for cmd in hci.commands]
    from pybluehost.hci.constants import HCI_LE_SET_ADVERTISE_ENABLE
    assert HCI_LE_SET_ADVERTISE_ENABLE in opcodes

@pytest.mark.asyncio
async def test_scanner_delivers_results():
    hci = FakeHCI()
    scanner = BLEScanner(hci=hci)
    results = []
    scanner.on_result(lambda r: results.append(r))
    await scanner.start()
    # Inject a simulated advertising report event
    from pybluehost.ble.gap import ScanResult
    from pybluehost.core.address import BDAddress
    from pybluehost.core.gap_common import AdvertisingData
    report = ScanResult(
        address=BDAddress.from_string("AA:BB:CC:DD:EE:FF"),
        rssi=-70,
        advertising_data=AdvertisingData(),
        connectable=True,
    )
    await scanner._on_advertising_report(report)
    assert len(results) == 1
    assert results[0].rssi == -70

@pytest.mark.asyncio
async def test_whitelist_add_device():
    from pybluehost.ble.gap import WhiteList
    from pybluehost.core.address import BDAddress
    hci = FakeHCI()
    wl = WhiteList(hci=hci)
    addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
    await wl.add(addr, address_type=0x00)
    from pybluehost.hci.constants import HCI_LE_ADD_DEVICE_TO_WHITE_LIST
    assert HCI_LE_ADD_DEVICE_TO_WHITE_LIST in [cmd.opcode for cmd in hci.commands]

@pytest.mark.asyncio
async def test_whitelist_clear():
    from pybluehost.ble.gap import WhiteList
    hci = FakeHCI()
    wl = WhiteList(hci=hci)
    await wl.clear()
    from pybluehost.hci.constants import HCI_LE_CLEAR_WHITE_LIST
    assert HCI_LE_CLEAR_WHITE_LIST in [cmd.opcode for cmd in hci.commands]

@pytest.mark.asyncio
async def test_extended_advertiser_create_set():
    from pybluehost.ble.gap import ExtendedAdvertiser, ExtAdvertisingConfig
    hci = FakeHCI()
    ext_adv = ExtendedAdvertiser(hci=hci)
    config = ExtAdvertisingConfig(adv_handle=0, primary_phy=1, secondary_phy=1, adv_type=0x05)
    await ext_adv.create_set(config)
    from pybluehost.hci.constants import HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS
    assert HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS in [cmd.opcode for cmd in hci.commands]

@pytest.mark.asyncio
async def test_extended_advertiser_start_stop():
    from pybluehost.ble.gap import ExtendedAdvertiser, ExtAdvertisingConfig
    hci = FakeHCI()
    ext_adv = ExtendedAdvertiser(hci=hci)
    await ext_adv.start(handles=[0], durations=None)
    from pybluehost.hci.constants import HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE
    assert HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE in [cmd.opcode for cmd in hci.commands]

def test_ble_connection_dataclass():
    from pybluehost.core.address import BDAddress
    from pybluehost.ble.gap import BLEConnection, ConnectionRole
    conn = BLEConnection(handle=0x0040, peer_address=BDAddress.from_string("AA:BB:CC:DD:EE:FF"), role=ConnectionRole.CENTRAL)
    assert conn.handle == 0x0040
    assert conn.att is None
```

- [x] **Step 2: Run tests — verify they fail**

- [x] **Step 3: Implement `ble/gap.py`**

```python
@dataclass
class AdvertisingConfig:
    min_interval_ms: float = 100.0
    max_interval_ms: float = 100.0
    adv_type: int = 0x00          # ADV_IND
    channel_map: int = 0x07       # all channels
    filter_policy: int = 0x00

@dataclass
class ScanConfig:
    active: bool = False
    interval_ms: float = 100.0
    window_ms: float = 50.0
    filter_duplicates: bool = True

@dataclass
class ScanResult:
    address: BDAddress
    rssi: int
    advertising_data: AdvertisingData
    connectable: bool = True

@dataclass
class BLEConnectionConfig:
    scan_interval_ms: float = 60.0
    scan_window_ms: float = 30.0
    min_interval_ms: float = 30.0
    max_interval_ms: float = 50.0
    latency: int = 0
    supervision_timeout_ms: float = 5000.0

class BLEAdvertiser:
    async def start(self, config, ad_data, scan_rsp_data=None) -> None: ...
    async def stop(self) -> None: ...
    async def update_data(self, ad_data) -> None: ...

class BLEScanner:
    async def start(self, config=ScanConfig()) -> None: ...
    async def stop(self) -> None: ...
    def on_result(self, handler) -> None: ...
    async def scan_for(self, duration: float, config=ScanConfig()) -> list[ScanResult]: ...
    async def _on_advertising_report(self, result: ScanResult) -> None: ...  # called by HCI event router

class BLEConnectionManager:
    async def connect(self, target, config=BLEConnectionConfig()) -> "BLEConnection": ...
    async def cancel_connect(self) -> None: ...
    def on_connection(self, handler) -> None: ...
    async def disconnect(self, handle, reason=0x13) -> None: ...

@dataclass
class BLEConnection:
    handle: int
    peer_address: BDAddress
    role: ConnectionRole
    att: ATTBearer | None = None
    gatt_client: GATTClient | None = None
    gatt_server: GATTServer | None = None
    smp: SMPManager | None = None

# Test for BLEConnection dataclass (add to tests/unit/ble/test_gap.py):
# def test_ble_connection_dataclass():
#     from pybluehost.core.address import BDAddress
#     from pybluehost.ble.gap import BLEConnection, ConnectionRole
#     conn = BLEConnection(handle=0x0040, peer_address=BDAddress.from_string("AA:BB:CC:DD:EE:FF"), role=ConnectionRole.CENTRAL)
#     assert conn.handle == 0x0040
#     assert conn.att is None

class PrivacyManager:
    async def enable(self, irk=None) -> None: ...
    async def disable(self) -> None: ...
    @staticmethod
    def resolve_rpa(rpa, irk) -> bool: ...

class WhiteList:
    """Wraps HCI LE White List commands (LE_Clear/Add/Remove_Device_From_White_List)."""
    def __init__(self, hci) -> None: ...
    async def add(self, address: BDAddress, address_type: int = 0x00) -> None: ...
    async def remove(self, address: BDAddress, address_type: int = 0x00) -> None: ...
    async def clear(self) -> None: ...

# Note: add these to hci/constants.py:
#   HCI_LE_CLEAR_WHITE_LIST            = make_opcode(OGF.LE, 0x10)
#   HCI_LE_ADD_DEVICE_TO_WHITE_LIST    = make_opcode(OGF.LE, 0x11)
#   HCI_LE_REMOVE_DEVICE_FROM_WHITE_LIST = make_opcode(OGF.LE, 0x12)

@dataclass
class ExtAdvertisingConfig:
    adv_handle: int = 0
    primary_phy: int = 1       # 1=1M, 3=coded
    secondary_phy: int = 1
    adv_type: int = 0x05       # non-connectable, non-scannable, undirected
    max_skip: int = 0

class ExtendedAdvertiser:
    """BT 5.0+ Extended Advertising — supports multiple advertising sets and coded PHY."""
    def __init__(self, hci) -> None: ...
    async def create_set(self, config: ExtAdvertisingConfig) -> None: ...
    async def set_data(self, handle: int, ad_data: AdvertisingData) -> None: ...
    async def start(self, handles: list[int], durations: list[float] | None = None) -> None: ...
    async def stop(self, handles: list[int]) -> None: ...
    async def remove_set(self, handle: int) -> None: ...

# Note: add these to hci/constants.py:
#   HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS  = make_opcode(OGF.LE, 0x36)
#   HCI_LE_SET_EXTENDED_ADVERTISING_DATA    = make_opcode(OGF.LE, 0x37)
#   HCI_LE_SET_EXTENDED_SCAN_RSP_DATA       = make_opcode(OGF.LE, 0x38)
#   HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE  = make_opcode(OGF.LE, 0x39)
```

- [x] **Step 4: Run tests — verify they pass**

- [x] **Step 5: Commit**
```bash
git add pybluehost/ble/gap.py tests/unit/ble/test_gap.py
git commit -m "feat(ble): add BLE GAP — Advertiser, Scanner, ConnectionManager, PrivacyManager"
```

- [x] **Step 6: Run full BLE GAP test suite + update STATUS.md**
```bash
uv run pytest tests/unit/ble/test_gap.py tests/unit/core/test_gap_common.py -v
uv run pytest tests/ -v --tb=short

git add docs/superpowers/STATUS.md
git commit -m "docs(progress): complete Plan 8a (BLE GAP) — update STATUS.md"
```

---

## 审查补充事项 (2026-04-18 审查后追加)

### 补充 1: Extended Advertising (AE)（PRD §5.6, 架构 11-gap.md §11.3）— 重大遗漏

当前 Plan 只有 Legacy Advertising (BLEAdvertiser)，完全缺少 Extended Advertising。需要补充：

```python
class ExtendedAdvertiser:
    """Bluetooth 5.0 Extended Advertising — 支持多广播集、长数据、多 PHY。"""
    async def create_set(self, params: ExtAdvParams) -> int: ...  # 返回 adv_handle
    async def set_data(self, adv_handle: int, data: bytes) -> None: ...
    async def set_scan_response(self, adv_handle: int, data: bytes) -> None: ...
    async def start(self, adv_handle: int, duration: float = 0) -> None: ...
    async def stop(self, adv_handle: int) -> None: ...
    async def remove_set(self, adv_handle: int) -> None: ...
```

涉及 HCI 命令：LE_Set_Extended_Advertising_Parameters, LE_Set_Extended_Advertising_Data, LE_Set_Extended_Scan_Response_Data, LE_Set_Extended_Advertising_Enable。

### 补充 2: WhiteList / 过滤策略（PRD §5.6, 架构 11-gap.md §11.5）— 重大遗漏

```python
class WhiteList:
    async def add(self, addr: BDAddress) -> None: ...
    async def remove(self, addr: BDAddress) -> None: ...
    async def clear(self) -> None: ...
    @property
    def entries(self) -> list[BDAddress]: ...
```

涉及 HCI 命令：LE_Add_Device_To_White_List, LE_Remove_Device_From_White_List, LE_Clear_White_List.

### 补充 3: PrivacyManager (RPA) 完整实现（架构 11-gap.md §11.3）

当前 Plan 只有 `resolve_rpa()` 静态方法。完整实现需要：
- `enable() / disable()` — 开启/关闭隐私模式
- `add_peer_irk(addr, irk)` — 添加对端 IRK 到 Resolving List
- RPA 定期轮换（默认 15 分钟，通过 HCI LE_Set_Resolvable_Private_Address_Timeout）
- Resolving List 管理（HCI LE_Add_Device_To_Resolving_List 等）

### 补充 5: 拆分建议（已在 STATUS.md 标注）

- **Plan 8a — BLE GAP**: core/gap_common.py + ble/gap.py（BLEAdvertiser + ExtendedAdvertiser + BLEScanner + BLEConnectionManager + PrivacyManager + WhiteList）
- **Plan 8b — Classic GAP + 统一入口**: classic/gap.py + pybluehost/gap.py 统一类
