# Plan 7: GAP Layer Implementation (BLE + Classic)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement GAP layer: `core/gap_common.py` (shared types), `ble/gap.py` (BLE Advertising/Scanning/Connection/Privacy), `classic/gap.py` (Inquiry/Page/SSP).

**Architecture reference:** `docs/architecture/11-gap.md`

**Dependencies:** `pybluehost/core/`, `pybluehost/hci/`, `pybluehost/ble/` (ATT), `pybluehost/classic/`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/core/gap_common.py` | `ClassOfDevice`, `Appearance`, `FilterPolicy`, `AdvertisingData`, `DeviceInfo` |
| `pybluehost/ble/gap.py` | `BLEAdvertiser`, `BLEScanner`, `BLEConnectionManager`, `PrivacyManager`, `GAP` |
| `pybluehost/classic/gap.py` | `ClassicDiscovery`, `ClassicDiscoverability`, `ClassicConnectionManager`, `SSPManager` |
| `tests/unit/ble/test_gap.py` | BLE GAP unit tests |
| `tests/unit/classic/test_gap.py` | Classic GAP unit tests |
| `tests/unit/core/test_gap_common.py` | AdvertisingData encode/decode |

---

## Task 1: Shared GAP Types + AdvertisingData

**Files:** `pybluehost/core/gap_common.py`, `tests/unit/core/test_gap_common.py`

- [ ] **Step 1: Write failing tests**

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

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `gap_common.py`**

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

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**
```bash
git add pybluehost/core/gap_common.py tests/unit/core/test_gap_common.py
git commit -m "feat(core): add gap_common types — AdvertisingData, Appearance, ClassOfDevice"
```

---

## Task 2: BLE GAP

**Files:** `pybluehost/ble/gap.py`, `tests/unit/ble/test_gap.py`

- [ ] **Step 1: Write failing BLE GAP tests**

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

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `ble/gap.py`**

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

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**
```bash
git add pybluehost/ble/gap.py tests/unit/ble/test_gap.py
git commit -m "feat(ble): add BLE GAP — Advertiser, Scanner, ConnectionManager, PrivacyManager"
```

---

## Task 3: Classic GAP + Unified GAP Entry Point

**Files:** `pybluehost/classic/gap.py`, `tests/unit/classic/test_gap.py`

- [ ] **Step 1: Write failing Classic GAP tests**

```python
# tests/unit/classic/test_gap.py
import asyncio, pytest
from pybluehost.classic.gap import ClassicDiscovery, ClassicDiscoverability, InquiryConfig

class FakeHCI:
    def __init__(self): self.commands = []
    async def send_command(self, cmd):
        self.commands.append(cmd)
        from pybluehost.hci.packets import HCI_Command_Complete_Event
        from pybluehost.hci.constants import ErrorCode
        return HCI_Command_Complete_Event(
            num_hci_command_packets=1, command_opcode=cmd.opcode,
            return_parameters=bytes([ErrorCode.SUCCESS]),
        )

@pytest.mark.asyncio
async def test_set_discoverable(hci=None):
    hci = FakeHCI()
    d = ClassicDiscoverability(hci=hci)
    await d.set_discoverable(True)
    from pybluehost.hci.constants import HCI_WRITE_SCAN_ENABLE
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_WRITE_SCAN_ENABLE in opcodes

@pytest.mark.asyncio
async def test_set_device_name():
    hci = FakeHCI()
    d = ClassicDiscoverability(hci=hci)
    await d.set_device_name("PyBH-Device")
    from pybluehost.hci.constants import HCI_WRITE_LOCAL_NAME
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_WRITE_LOCAL_NAME in opcodes
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `classic/gap.py`**

`ClassicDiscovery`, `ClassicDiscoverability`, `ClassicConnectionManager`, `SSPManager` — each wraps the relevant HCI commands and handles the corresponding HCI events.

- [ ] **Step 4: Implement unified `GAP` class** (can live in `ble/gap.py` or a top-level `gap.py`)

```python
class GAP:
    """Unified GAP entry point — combines BLE + Classic."""
    def __init__(self, ble_advertiser, ble_scanner, ble_connections,
                 ble_privacy, classic_discovery, classic_discoverability,
                 classic_connections, classic_ssp,
                 whitelist: "WhiteList | None" = None,
                 ble_extended_advertiser: "ExtendedAdvertiser | None" = None) -> None: ...

    @property
    def ble_advertiser(self) -> BLEAdvertiser: ...
    @property
    def ble_scanner(self) -> BLEScanner: ...
    @property
    def ble_connections(self) -> BLEConnectionManager: ...
    @property
    def whitelist(self) -> "WhiteList": ...
    @property
    def ble_extended_advertiser(self) -> "ExtendedAdvertiser | None": ...
    @property
    def classic_discovery(self) -> ClassicDiscovery: ...
    @property
    def classic_discoverability(self) -> ClassicDiscoverability: ...
    @property
    def classic_connections(self) -> ClassicConnectionManager: ...
    def set_pairing_delegate(self, delegate) -> None: ...
```

- [ ] **Step 5: Run all GAP tests + full suite**
```bash
uv run pytest tests/unit/ble/test_gap.py tests/unit/classic/test_gap.py tests/unit/core/test_gap_common.py -v
uv run pytest tests/ -v --tb=short
```

- [ ] **Step 6: Commit + update STATUS.md**
```bash
git add pybluehost/classic/gap.py pybluehost/ble/gap.py pybluehost/core/gap_common.py tests/
git commit -m "feat(gap): add unified GAP layer — BLE Advertising/Scan/Connect + Classic Inquiry/SSP"

git add docs/superpowers/STATUS.md
git commit -m "docs: mark Plan 7 (GAP) complete in STATUS.md"
```
