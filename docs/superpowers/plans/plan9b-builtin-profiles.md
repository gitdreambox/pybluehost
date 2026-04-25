# Plan 9b: Built-in BLE Profiles + Classic SPP Profile

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement 9 built-in BLE profiles (GAP Service, GATT Service, DIS, BAS, HRS, BLS, HIDS, RSCS, CSCS), Client classes, `profiles/classic/spp.py`, and E2E Loopback tests.

**Architecture reference:** `docs/architecture/12-ble-profiles.md`

**Dependencies:** Plan 9a (BLE Profile Framework), `pybluehost/ble/gatt.py`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/profiles/ble/gap_service.py` | `GAPServiceServer` (0x1800) |
| `pybluehost/profiles/ble/gatt_service.py` | `GATTServiceServer` (0x1801) |
| `pybluehost/profiles/ble/dis.py` | `DeviceInformationServer` + `DeviceInformationClient` |
| `pybluehost/profiles/ble/bas.py` | `BatteryServer` + `BatteryClient` |
| `pybluehost/profiles/ble/hrs.py` | `HeartRateServer` + `HeartRateClient` |
| `pybluehost/profiles/ble/bls.py` | `BloodPressureServer` |
| `pybluehost/profiles/ble/hids.py` | `HIDServer` |
| `pybluehost/profiles/ble/rscs.py` | `RSCServer` |
| `pybluehost/profiles/ble/cscs.py` | `CSCServer` |
| `pybluehost/profiles/classic/spp.py` | Classic SPP Profile 层封装 |
| `tests/unit/profiles/test_builtin.py` | DIS, BAS, HRS, GAP registration and read/write |
| `tests/unit/profiles/test_missing_profiles.py` | BLS, HIDS, RSCS, CSCS, GATTService registration |
| `tests/unit/profiles/test_clients.py` | HeartRateClient, BatteryClient tests |

---

## Task 1: Built-in Profiles (DIS, BAS, HRS, GAP)

## Task 1: Built-in Profiles (DIS, BAS, HRS, GAP)

**Files:** `dis.py`, `bas.py`, `hrs.py`, `gap_service.py`, `tests/unit/profiles/test_builtin.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/profiles/test_builtin.py
import asyncio, pytest
from pybluehost.ble.gatt import GATTServer
from pybluehost.profiles.ble.dis import DeviceInformationServer
from pybluehost.profiles.ble.bas import BatteryServer
from pybluehost.profiles.ble.hrs import HeartRateServer

@pytest.mark.asyncio
async def test_dis_register_and_read():
    server = DeviceInformationServer(manufacturer="ACME", model="X1")
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle_by_uuid(0x2A29)
    assert handle is not None
    value = await gatt.db.read_dynamic(handle)
    assert value == b"ACME"

@pytest.mark.asyncio
async def test_bas_notify_battery_level():
    server = BatteryServer(initial_level=85)
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle_by_uuid(0x2A19)
    assert handle is not None
    value = await gatt.db.read_dynamic(handle)
    assert value == bytes([85])

@pytest.mark.asyncio
async def test_hrs_register():
    server = HeartRateServer(sensor_location=0x01)  # Chest
    gatt = GATTServer()
    await server.register(gatt)
    hrm_handle = gatt.find_characteristic_value_handle_by_uuid(0x2A37)
    loc_handle = gatt.find_characteristic_value_handle_by_uuid(0x2A38)
    assert hrm_handle is not None
    assert loc_handle is not None

@pytest.mark.asyncio
async def test_bls_register_and_read_feature():
    from pybluehost.profiles.ble.bls import BloodPressureServer
    server = BloodPressureServer()
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle_by_uuid(0x2A49)
    assert handle is not None
    value = await gatt.db.read_dynamic(handle)
    import struct
    assert struct.unpack("<H", value)[0] == 0x0000

@pytest.mark.asyncio
async def test_hids_register_and_read_report_map():
    from pybluehost.profiles.ble.hids import HIDServer
    report_map = bytes.fromhex("050901A10185010903750119002501810295017501810175068103C0")
    server = HIDServer(report_map=report_map)
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle_by_uuid(0x2A4B)
    assert handle is not None
    value = await gatt.db.read_dynamic(handle)
    assert value == report_map

@pytest.mark.asyncio
async def test_gap_service_register_and_read_name():
    from pybluehost.profiles.ble.gap_service import GAPServiceServer
    server = GAPServiceServer(device_name="TestDevice")
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle_by_uuid(0x2A00)
    assert handle is not None
    value = await gatt.db.read_dynamic(handle)
    assert value == b"TestDevice"
```

- [x] **Step 2: Run tests — verify they fail**

- [x] **Step 3: Implement `dis.py`, `bas.py`, `hrs.py`, `gap_service.py`**

```python
# dis.py
from pybluehost.profiles.ble.base import BLEProfileServer, BLEProfileClient
from pybluehost.profiles.ble.decorators import on_read
from pybluehost.core.uuid import UUID16

class DeviceInformationServer(BLEProfileServer):
    service_uuid = UUID16(0x180A)

    def __init__(self, manufacturer: str = "", model: str = "",
                 hardware_rev: str = "", firmware_rev: str = "",
                 software_rev: str = "") -> None:
        self._manufacturer = manufacturer
        self._model = model
        self._hardware_rev = hardware_rev
        self._firmware_rev = firmware_rev
        self._software_rev = software_rev

    @on_read(UUID16(0x2A29))
    async def read_manufacturer(self) -> bytes:
        return self._manufacturer.encode()

    @on_read(UUID16(0x2A24))
    async def read_model(self) -> bytes:
        return self._model.encode()

    @on_read(UUID16(0x2A27))
    async def read_hardware_rev(self) -> bytes:
        return self._hardware_rev.encode()

    @on_read(UUID16(0x2A26))
    async def read_firmware_rev(self) -> bytes:
        return self._firmware_rev.encode()

    @on_read(UUID16(0x2A28))
    async def read_software_rev(self) -> bytes:
        return self._software_rev.encode()

class DeviceInformationClient(BLEProfileClient):
    _service_uuid = UUID16(0x180A)

    async def read_manufacturer(self) -> str:
        return (await self.read(UUID16(0x2A29))).decode()

    async def read_model(self) -> str:
        return (await self.read(UUID16(0x2A24))).decode()

# bas.py
from pybluehost.profiles.ble.base import BLEProfileServer, BLEProfileClient
from pybluehost.profiles.ble.decorators import on_read, on_notify
from pybluehost.core.uuid import UUID16

class BatteryServer(BLEProfileServer):
    service_uuid = UUID16(0x180F)

    def __init__(self, initial_level: int = 100) -> None:
        self._level = initial_level

    @on_read(UUID16(0x2A19))
    async def read_level(self) -> bytes:
        return bytes([self._level])

    @on_notify(UUID16(0x2A19))
    async def notify_level(self) -> bytes:
        return bytes([self._level])

    async def update_level(self, level: int, connections: list[int] | None = None) -> None:
        self._level = level
        # TODO: send notification to connected clients

class BatteryClient(BLEProfileClient):
    _service_uuid = UUID16(0x180F)

    async def read_battery_level(self) -> int:
        data = await self.read(UUID16(0x2A19))
        return data[0]

    async def subscribe_battery_level(self, handler) -> None:
        from typing import Callable, Awaitable
        async def _parse(data: bytes) -> None:
            await handler(data[0])
        await self.subscribe(UUID16(0x2A19), _parse)

# hrs.py
from pybluehost.profiles.ble.base import BLEProfileServer, BLEProfileClient
from pybluehost.profiles.ble.decorators import on_read, on_write, on_notify
from pybluehost.core.uuid import UUID16

class HeartRateServer(BLEProfileServer):
    service_uuid = UUID16(0x180D)

    def __init__(self, sensor_location: int = 0x00) -> None:
        self._location = sensor_location
        self._last_bpm = 0

    @on_read(UUID16(0x2A38))
    async def read_location(self) -> bytes:
        return bytes([self._location])

    @on_notify(UUID16(0x2A37))
    async def notify_hrm(self) -> bytes:
        return bytes([0x00, self._last_bpm])  # flags=0, 8-bit HR value

    async def update_measurement(self, bpm: int, connections: list[int] | None = None) -> None:
        """Update the current HR value and notify connected clients (arch doc 12.5)."""
        self._last_bpm = bpm
        # TODO: send notification to connected clients

class HeartRateClient(BLEProfileClient):
    _service_uuid = UUID16(0x180D)

    async def read_sensor_location(self) -> int:
        data = await self.read(UUID16(0x2A38))
        return data[0]

    async def subscribe_measurement(self, handler) -> None:
        async def _parse(data: bytes) -> None:
            flags = data[0]
            bpm = data[1] if not (flags & 0x01) else int.from_bytes(data[1:3], "little")
            await handler(bpm)
        await self.subscribe(UUID16(0x2A37), _parse)

    async def reset_energy_expended(self) -> None:
        await self.write(UUID16(0x2A39), b"\x01")

# gap_service.py
from pybluehost.profiles.ble.base import BLEProfileServer
from pybluehost.profiles.ble.decorators import on_read, on_write
from pybluehost.core.uuid import UUID16

class GAPServiceServer(BLEProfileServer):
    service_uuid = UUID16(0x1800)

    def __init__(self, device_name: str = "PyBlueHost", appearance: int = 0x0000) -> None:
        self._name = device_name
        self._appearance = appearance

    @on_read(UUID16(0x2A00))
    async def read_name(self) -> bytes:
        return self._name.encode()

    @on_write(UUID16(0x2A00))
    async def write_name(self, value: bytes) -> None:
        self._name = value.decode(errors="replace")

    @on_read(UUID16(0x2A01))
    async def read_appearance(self) -> bytes:
        import struct
        return struct.pack("<H", self._appearance)
```

- [x] **Step 4: Run tests — verify they pass**

- [x] **Step 5: Write package `__init__.py`**

```python
# profiles/ble/__init__.py
from pybluehost.profiles.ble.base import BLEProfileServer, BLEProfileClient
from pybluehost.profiles.ble.decorators import ble_service, on_read, on_write, on_notify, on_indicate
from pybluehost.profiles.ble.yaml_loader import ServiceYAMLLoader
from pybluehost.profiles.ble.dis import DeviceInformationServer, DeviceInformationClient
from pybluehost.profiles.ble.bas import BatteryServer, BatteryClient
from pybluehost.profiles.ble.hrs import HeartRateServer, HeartRateClient
from pybluehost.profiles.ble.gap_service import GAPServiceServer
from pybluehost.profiles.ble.gatt_service import GATTServiceServer
from pybluehost.profiles.ble.bls import BloodPressureServer
from pybluehost.profiles.ble.hids import HIDServer
from pybluehost.profiles.ble.rscs import RSCServer
from pybluehost.profiles.ble.cscs import CSCServer

__all__ = [
    "BLEProfileServer", "BLEProfileClient",
    "ble_service", "on_read", "on_write", "on_notify", "on_indicate",
    "ServiceYAMLLoader",
    "DeviceInformationServer", "DeviceInformationClient",
    "BatteryServer", "BatteryClient",
    "HeartRateServer", "HeartRateClient",
    "GAPServiceServer",
    "GATTServiceServer",
    "BloodPressureServer",
    "HIDServer",
    "RSCServer",
    "CSCServer",
]
```

- [x] **Step 6: Run all profile tests + full suite**
```bash
uv run pytest tests/unit/profiles/ -v
uv run pytest tests/ -v --tb=short
```

- [x] **Step 7: Commit**
```bash
git add pybluehost/profiles/ble/dis.py pybluehost/profiles/ble/bas.py \
        pybluehost/profiles/ble/hrs.py pybluehost/profiles/ble/gap_service.py \
        pybluehost/profiles/ble/__init__.py tests/unit/profiles/
git commit -m "feat(profiles): add DIS, BAS, HRS, GAP profile servers with update_measurement API"
```

---

---

## Task 2: Missing Built-in Profiles (BLS, HIDS, RSCS, CSCS, GATTService)

## Task 2: Missing Built-in Profiles (BLS, HIDS, RSCS, CSCS, GATTService)

**Files:**
- Create: `pybluehost/profiles/ble/bls.py`
- Create: `pybluehost/profiles/ble/hids.py`
- Create: `pybluehost/profiles/ble/rscs.py`
- Create: `pybluehost/profiles/ble/cscs.py`
- Create: `pybluehost/profiles/ble/gatt_service.py`
- Test: `tests/unit/profiles/test_missing_profiles.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/profiles/test_missing_profiles.py
import asyncio, pytest
from pybluehost.ble.gatt import GATTServer

@pytest.mark.asyncio
async def test_bls_register():
    from pybluehost.profiles.ble.bls import BloodPressureServer
    server = BloodPressureServer()
    gatt = GATTServer()
    await server.register(gatt)
    bp_handle = gatt.find_characteristic_value_handle_by_uuid(0x2A35)
    assert bp_handle is not None

@pytest.mark.asyncio
async def test_hids_register():
    from pybluehost.profiles.ble.hids import HIDServer
    server = HIDServer(hid_info=bytes([0x11, 0x01, 0x00, 0x03]), report_map=bytes([0x05, 0x01]))
    gatt = GATTServer()
    await server.register(gatt)
    info_handle = gatt.find_characteristic_value_handle_by_uuid(0x2A4A)
    assert info_handle is not None

@pytest.mark.asyncio
async def test_rscs_register():
    from pybluehost.profiles.ble.rscs import RSCServer
    server = RSCServer()
    gatt = GATTServer()
    await server.register(gatt)
    meas_handle = gatt.find_characteristic_value_handle_by_uuid(0x2A53)
    assert meas_handle is not None

@pytest.mark.asyncio
async def test_cscs_register():
    from pybluehost.profiles.ble.cscs import CSCServer
    server = CSCServer()
    gatt = GATTServer()
    await server.register(gatt)
    meas_handle = gatt.find_characteristic_value_handle_by_uuid(0x2A5B)
    assert meas_handle is not None

@pytest.mark.asyncio
async def test_gatt_service_register():
    from pybluehost.profiles.ble.gatt_service import GATTServiceServer
    server = GATTServiceServer()
    gatt = GATTServer()
    await server.register(gatt)
    svc_changed_handle = gatt.find_characteristic_value_handle_by_uuid(0x2A05)
    assert svc_changed_handle is not None
```

- [x] **Step 2: Run tests — verify they fail**

- [x] **Step 3: Implement all five profiles**

```python
# bls.py
from pybluehost.profiles.ble.base import BLEProfileServer
from pybluehost.profiles.ble.decorators import ble_service, on_read, on_notify, on_indicate
from pybluehost.core.uuid import UUID16

@ble_service("bls.yaml")
class BloodPressureServer(BLEProfileServer):
    def __init__(self, feature: int = 0x0000) -> None:
        super().__init__()
        self._feature = feature

    @on_indicate(UUID16(0x2A35))
    async def measurement(self) -> bytes:
        return bytes([0x00, 0x00, 0x00, 0x00, 0x00])  # flags + sys + dia

    @on_notify(UUID16(0x2A36))
    async def intermediate_cuff_pressure(self) -> bytes:
        return bytes([0x00, 0x00, 0x00])

    @on_read(UUID16(0x2A49))
    async def feature(self) -> bytes:
        return self._feature.to_bytes(2, "little")

# hids.py
from pybluehost.profiles.ble.base import BLEProfileServer
from pybluehost.profiles.ble.decorators import ble_service, on_read, on_write, on_notify
from pybluehost.core.uuid import UUID16

@ble_service("hids.yaml")
class HIDServer(BLEProfileServer):
    def __init__(self, hid_info: bytes = bytes([0x11, 0x01, 0x00, 0x00]),
                 report_map: bytes = b"") -> None:
        super().__init__()
        self._hid_info = hid_info
        self._report_map = report_map

    @on_read(UUID16(0x2A4A))
    async def hid_info(self) -> bytes:
        return self._hid_info

    @on_read(UUID16(0x2A4B))
    async def report_map(self) -> bytes:
        return self._report_map

    @on_notify(UUID16(0x2A4D))
    async def input_report(self) -> bytes:
        return b"\x00"

    @on_write(UUID16(0x2A4D))
    async def output_report(self, value: bytes) -> None:
        pass

    @on_write(UUID16(0x2A4C))
    async def control_point(self, value: bytes) -> None:
        pass

# rscs.py
from pybluehost.profiles.ble.base import BLEProfileServer
from pybluehost.profiles.ble.decorators import ble_service, on_read, on_notify
from pybluehost.core.uuid import UUID16

@ble_service("rscs.yaml")
class RSCServer(BLEProfileServer):
    @on_notify(UUID16(0x2A53))
    async def measurement(self) -> bytes:
        return bytes([0x00, 0x00, 0x00, 0x00, 0x00])

    @on_read(UUID16(0x2A54))
    async def feature(self) -> bytes:
        return bytes([0x00, 0x00])

# cscs.py
from pybluehost.profiles.ble.base import BLEProfileServer
from pybluehost.profiles.ble.decorators import ble_service, on_read, on_notify
from pybluehost.core.uuid import UUID16

@ble_service("cscs.yaml")
class CSCServer(BLEProfileServer):
    @on_notify(UUID16(0x2A5B))
    async def measurement(self) -> bytes:
        return bytes([0x00, 0x00, 0x00, 0x00, 0x00])

    @on_read(UUID16(0x2A5C))
    async def feature(self) -> bytes:
        return bytes([0x00, 0x00])

# gatt_service.py
from pybluehost.profiles.ble.base import BLEProfileServer
from pybluehost.profiles.ble.decorators import ble_service, on_indicate
from pybluehost.core.uuid import UUID16

@ble_service("gatt.yaml")
class GATTServiceServer(BLEProfileServer):
    @on_indicate(UUID16(0x2A05))
    async def service_changed(self) -> bytes:
        return bytes([0x01, 0x00, 0xFF, 0xFF])  # start_handle=1, end_handle=65535
```

- [x] **Step 4: Run tests — verify they pass**

- [x] **Step 5: Commit**
```bash
git add pybluehost/profiles/ble/bls.py pybluehost/profiles/ble/hids.py \
        pybluehost/profiles/ble/rscs.py pybluehost/profiles/ble/cscs.py \
        pybluehost/profiles/ble/gatt_service.py \
        tests/unit/profiles/test_missing_profiles.py
git commit -m "feat(profiles): add BLS, HIDS, RSCS, CSCS, GATTService profiles with @ble_service decorator"
```

---

---

## Task 3: Profile Clients (HeartRateClient, BatteryClient)

## Task 3: Profile Clients (HeartRateClient, BatteryClient)

**Files:**
- Modify: `pybluehost/profiles/ble/hrs.py` — HeartRateClient already scaffolded in Task 3; expand here
- Modify: `pybluehost/profiles/ble/bas.py` — BatteryClient already scaffolded in Task 3; expand here
- Test: `tests/unit/profiles/test_clients.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/profiles/test_clients.py
import asyncio, pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_heart_rate_client_read_location():
    from pybluehost.profiles.ble.hrs import HeartRateClient
    from pybluehost.core.uuid import UUID16

    mock_gatt = MagicMock()
    mock_gatt.discover_all_services = AsyncMock(return_value=[
        MagicMock(uuid=UUID16(0x180D))
    ])
    mock_gatt.discover_characteristics = AsyncMock(return_value=[
        MagicMock(uuid=UUID16(0x2A38)),
        MagicMock(uuid=UUID16(0x2A37)),
        MagicMock(uuid=UUID16(0x2A39)),
    ])
    mock_gatt.read_characteristic = AsyncMock(return_value=bytes([0x01]))  # Chest

    client = HeartRateClient()
    await client.discover(mock_gatt)
    location = await client.read_sensor_location()
    assert location == 0x01

@pytest.mark.asyncio
async def test_battery_client_read_level():
    from pybluehost.profiles.ble.bas import BatteryClient
    from pybluehost.core.uuid import UUID16

    mock_gatt = MagicMock()
    mock_gatt.discover_all_services = AsyncMock(return_value=[
        MagicMock(uuid=UUID16(0x180F))
    ])
    mock_gatt.discover_characteristics = AsyncMock(return_value=[
        MagicMock(uuid=UUID16(0x2A19)),
    ])
    mock_gatt.read_characteristic = AsyncMock(return_value=bytes([85]))

    client = BatteryClient()
    await client.discover(mock_gatt)
    level = await client.read_battery_level()
    assert level == 85
```

- [x] **Step 2: Run tests — verify they fail**

- [x] **Step 3: Verify/expand client implementations in `hrs.py` and `bas.py`**

The `HeartRateClient` and `BatteryClient` scaffolded in Task 3 should already cover these tests. Verify the `discover()` signature matches `BLEProfileClient.discover(gatt_client)` and the `read()` method routes through `gatt_client.read_characteristic(char)`.

```python
# HeartRateClient (final form in hrs.py)
class HeartRateClient(BLEProfileClient):
    _service_uuid = UUID16(0x180D)

    async def read_sensor_location(self) -> int:
        data = await self.read(UUID16(0x2A38))
        return data[0]

    async def subscribe_measurement(self, handler) -> None:
        async def _parse(data: bytes) -> None:
            flags = data[0]
            bpm = data[1] if not (flags & 0x01) else int.from_bytes(data[1:3], "little")
            await handler(bpm)
        await self.subscribe(UUID16(0x2A37), _parse)

    async def reset_energy_expended(self) -> None:
        await self.write(UUID16(0x2A39), b"\x01")

# BatteryClient (final form in bas.py)
class BatteryClient(BLEProfileClient):
    _service_uuid = UUID16(0x180F)

    async def read_battery_level(self) -> int:
        data = await self.read(UUID16(0x2A19))
        return data[0]

    async def subscribe_battery_level(self, handler) -> None:
        async def _parse(data: bytes) -> None:
            await handler(data[0])
        await self.subscribe(UUID16(0x2A19), _parse)
```

- [x] **Step 4: Run tests — verify they pass**

- [x] **Step 5: Run full suite**
```bash
uv run pytest tests/unit/profiles/ -v
uv run pytest tests/ -v --tb=short
```

- [x] **Step 6: Commit + update STATUS.md**
```bash
git add pybluehost/profiles/ tests/unit/profiles/
git commit -m "feat(profiles): add HeartRateClient and BatteryClient with mock-friendly discover API"

git add docs/superpowers/STATUS.md
git commit -m "docs: mark Plan 8 (BLE Profiles) complete in STATUS.md"
```

---

---

## 审查补充事项 (from Plan 9 review)

### 补充 1: Profile E2E Loopback 测试（架构 14-testing.md §14.5）

9 个内置 Profile 需要 Loopback E2E 测试：Server + Client 双角色完整交互。至少覆盖：
- HRS: Client subscribe notify → Server update heart rate → Client receive notification
- BAS: Client read battery level → 验证值正确
- DIS: Client read manufacturer name → 验证字符串正确

### 补充 2: Client 侧 Profile 实现

- `HeartRateClient.subscribe_measurement()` → 接收 notification
- `BatteryClient.read_level()` → 读取电池电量
- Client 的 `discover()` 方法 + 缓存失效（Service Changed indication）

### 补充 3: profiles/classic/spp.py（Profile 层封装）

与 Plan 7 的 `classic/spp.py`（协议层）是不同文件。此文件是 Profile 层封装，提供高级 SPP API。
