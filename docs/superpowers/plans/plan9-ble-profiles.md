# Plan 8: BLE Profile Framework + Built-in Profiles

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement the `profiles/ble/` framework: `BLEProfileServer`/`BLEProfileClient` base classes, YAML service loader, `@ble_service` class decorator + method decorators, and 9 built-in profiles (GAP Service, GATT Service, DIS, BAS, HRS, BLS, HIDS, RSCS, CSCS).

**Architecture reference:** `docs/architecture/12-ble-profiles.md`

**Dependencies:** `pybluehost/ble/gatt.py`, `pybluehost/core/uuid.py`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/profiles/ble/__init__.py` | Re-export profile public API |
| `pybluehost/profiles/ble/base.py` | `BLEProfileServer`, `BLEProfileClient` ABC |
| `pybluehost/profiles/ble/decorators.py` | `@ble_service` class decorator (yaml_path), `@on_read`, `@on_write`, `@on_notify`, `@on_indicate` method decorators |
| `pybluehost/profiles/ble/yaml_loader.py` | `ServiceYAMLLoader` class with `load()`, `loads()`, `load_builtin()`, `validate()` |
| `pybluehost/profiles/ble/services/gap.yaml` | GAP Service (0x1800) |
| `pybluehost/profiles/ble/services/gatt.yaml` | GATT Service (0x1801) |
| `pybluehost/profiles/ble/services/dis.yaml` | Device Information Service (0x180A) |
| `pybluehost/profiles/ble/services/bas.yaml` | Battery Service (0x180F) |
| `pybluehost/profiles/ble/services/hrs.yaml` | Heart Rate Service (0x180D) |
| `pybluehost/profiles/ble/services/bls.yaml` | Blood Pressure Service (0x1810) |
| `pybluehost/profiles/ble/services/hids.yaml` | HID Service (0x1812) |
| `pybluehost/profiles/ble/services/rscs.yaml` | Running Speed & Cadence (0x1814) |
| `pybluehost/profiles/ble/services/cscs.yaml` | Cycling Speed & Cadence (0x1816) |
| `pybluehost/profiles/ble/gap_service.py` | `GAPServiceServer` (0x1800) |
| `pybluehost/profiles/ble/gatt_service.py` | `GATTServiceServer` (0x1801) |
| `pybluehost/profiles/ble/dis.py` | `DeviceInformationServer` + `DeviceInformationClient` |
| `pybluehost/profiles/ble/bas.py` | `BatteryServer` + `BatteryClient` |
| `pybluehost/profiles/ble/hrs.py` | `HeartRateServer` + `HeartRateClient` |
| `pybluehost/profiles/ble/bls.py` | `BloodPressureServer` |
| `pybluehost/profiles/ble/hids.py` | `HIDServer` |
| `pybluehost/profiles/ble/rscs.py` | `RSCServer` |
| `pybluehost/profiles/ble/cscs.py` | `CSCServer` |
| `tests/unit/profiles/__init__.py` | |
| `tests/unit/profiles/test_base.py` | Base class, `@ble_service` decorator, method decorator tests |
| `tests/unit/profiles/test_builtin.py` | DIS, BAS, HRS, BLS, HIDS registration and read/write |
| `tests/unit/profiles/test_missing_profiles.py` | BLS, HIDS, RSCS, CSCS, GATTService registration tests |
| `tests/unit/profiles/test_clients.py` | HeartRateClient, BatteryClient tests |

---

## Task 1: Base Classes + Decorators

**Files:** `base.py`, `decorators.py`, `tests/unit/profiles/test_base.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/profiles/test_base.py
import asyncio, pytest
from pybluehost.profiles.ble.base import BLEProfileServer, BLEProfileClient
from pybluehost.profiles.ble.decorators import ble_service, on_read, on_write, on_notify, on_indicate
from pybluehost.ble.gatt import GATTServer, ServiceDefinition, CharacteristicDefinition, CharProperties, Permissions
from pybluehost.core.uuid import UUID16

# Test using explicit service_uuid attribute
class HeartRateTestServer(BLEProfileServer):
    service_uuid = UUID16(0x180D)

    @on_read(UUID16(0x2A38))  # Body Sensor Location
    async def read_location(self) -> bytes:
        return bytes([0x01])  # Chest

    @on_write(UUID16(0x2A39))  # Control Point
    async def write_control_point(self, value: bytes) -> None:
        self._last_cp = value

    @on_notify(UUID16(0x2A37))  # Heart Rate Measurement
    async def hrm_stream(self) -> bytes:
        return bytes([0x00, 0x48])  # flags=0, HR=72 bpm

@pytest.mark.asyncio
async def test_profile_register_adds_service():
    server = HeartRateTestServer()
    gatt = GATTServer()
    await server.register(gatt)
    # GATTServer should now have the HR service
    assert len(gatt.services) >= 1

@pytest.mark.asyncio
async def test_profile_read_callback():
    server = HeartRateTestServer()
    gatt = GATTServer()
    await server.register(gatt)
    # Find value handle for 0x2A38
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A38))
    assert handle is not None
    value = await gatt.db.read_dynamic(handle)
    assert value == bytes([0x01])

@pytest.mark.asyncio
async def test_profile_notify():
    server = HeartRateTestServer()
    gatt = GATTServer()
    await server.register(gatt)
    # Calling the notify source should return HRM data
    data = await server.hrm_stream()
    assert data == bytes([0x00, 0x48])

def test_ble_service_decorator_sets_class_attrs():
    # Create a minimal YAML file and test the decorator
    from pybluehost.profiles.ble.decorators import ble_service, on_read, on_indicate
    from pybluehost.profiles.ble.base import BLEProfileServer

    # Test that decorator marks _service_yaml on class
    # (actual YAML loading tested separately)
    import types
    cls = types.new_class("TestProfile", (BLEProfileServer,))
    # Verify decorator is callable and returns class
    # (full test uses real YAML in Task 2)

def test_on_indicate_decorator_marks_method():
    from pybluehost.profiles.ble.decorators import on_indicate

    @on_indicate(0x2A05)
    async def service_changed(self) -> bytes:
        return b"\x00\x01\x00\x01"

    assert service_changed._ble_callback_type == "indicate"
    assert service_changed._ble_uuid == 0x2A05

def test_on_read_decorator_sets_metadata():
    class Srv(BLEProfileServer):
        service_uuid = UUID16(0x180D)
        @on_read(UUID16(0x2A38))
        async def read_loc(self): return b"\x01"
        async def register(self, g): pass

    assert hasattr(Srv.read_loc, "_att_read")
    assert Srv.read_loc._att_read == UUID16(0x2A38)

def test_on_notify_decorator_sets_metadata():
    class Srv(BLEProfileServer):
        service_uuid = UUID16(0x180D)
        @on_notify(UUID16(0x2A37))
        async def hrm(self): return b"\x00\x48"
        async def register(self, g): pass

    assert hasattr(Srv.hrm, "_att_notify")
    assert Srv.hrm._att_notify == UUID16(0x2A37)
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `base.py`**

```python
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pybluehost.ble.gatt import GATTServer, GATTClient

class BLEProfileServer(ABC):
    """Base class for all BLE profile server implementations."""
    service_uuid: "UUID"  # subclass sets this, OR use @ble_service decorator

    @abstractmethod
    async def register(self, gatt_server: "GATTServer") -> None:
        """Register the service definition and bind all decorated callbacks."""

    def _build_service_definition(self) -> "ServiceDefinition":
        """Introspect @on_read/@on_write/@on_notify/@on_indicate metadata and build ServiceDefinition."""
        from pybluehost.ble.gatt import ServiceDefinition, CharacteristicDefinition, CharProperties, Permissions
        chars = []
        for name in dir(self.__class__):
            method = getattr(self.__class__, name, None)
            if method is None: continue
            char_uuid = None
            props = CharProperties(0)
            if hasattr(method, "_att_read"):
                char_uuid = method._att_read; props |= CharProperties.READ
            if hasattr(method, "_att_write"):
                char_uuid = method._att_write; props |= CharProperties.WRITE
            if hasattr(method, "_att_notify"):
                char_uuid = method._att_notify; props |= CharProperties.NOTIFY
            if hasattr(method, "_att_indicate"):
                char_uuid = method._att_indicate; props |= CharProperties.INDICATE
            if char_uuid:
                chars.append(CharacteristicDefinition(
                    uuid=char_uuid, properties=props,
                    permissions=Permissions.READABLE | Permissions.WRITABLE,
                ))
        return ServiceDefinition(uuid=self.service_uuid, characteristics=chars)

class BLEProfileClient(ABC):
    """Base class for all BLE profile client implementations."""
    _service_uuid: "UUID"  # subclass sets this

    def __init__(self) -> None:
        self._gatt = None
        self._service = None
        self._char_handles: dict = {}

    async def discover(self, gatt_client: "GATTClient") -> None:
        """Discover the profile service and cache characteristic handles."""
        self._gatt = gatt_client
        services = await gatt_client.discover_all_services()
        self._service = next(
            (s for s in services if s.uuid == self._service_uuid), None
        )
        if self._service is None:
            raise ValueError(f"Service {self._service_uuid} not found on remote device")
        chars = await gatt_client.discover_characteristics(self._service)
        self._char_handles = {c.uuid: c for c in chars}

    async def read(self, uuid: "UUID") -> bytes:
        char = self._char_handles[uuid]
        return await self._gatt.read_characteristic(char)

    async def write(self, uuid: "UUID", value: bytes) -> None:
        char = self._char_handles[uuid]
        await self._gatt.write_characteristic(char, value)

    async def subscribe(self, uuid: "UUID", handler) -> None:
        char = self._char_handles[uuid]
        await self._gatt.subscribe_notifications(char, handler)
```

- [ ] **Step 4: Implement `decorators.py`**

```python
# decorators.py — complete implementation

def ble_service(yaml_path: str):
    """Class decorator: load YAML service definition and bind to Profile class."""
    def decorator(cls: type) -> type:
        from pybluehost.profiles.ble.yaml_loader import ServiceYAMLLoader
        cls._service_yaml = yaml_path
        cls._service_definition = ServiceYAMLLoader.load_builtin(yaml_path)
        return cls
    return decorator

def on_read(uuid: int | str):
    """Method decorator: mark async method as read handler for characteristic UUID."""
    def decorator(fn):
        fn._ble_callback_type = "read"
        fn._ble_uuid = uuid
        fn._att_read = uuid
        return fn
    return decorator

def on_write(uuid: int | str):
    """Method decorator: mark async method as write handler."""
    def decorator(fn):
        fn._ble_callback_type = "write"
        fn._ble_uuid = uuid
        fn._att_write = uuid
        return fn
    return decorator

def on_notify(uuid: int | str):
    """Method decorator: mark async method as notify data source."""
    def decorator(fn):
        fn._ble_callback_type = "notify"
        fn._ble_uuid = uuid
        fn._att_notify = uuid
        return fn
    return decorator

def on_indicate(uuid: int | str):
    """Method decorator: mark async method as indicate data source."""
    def decorator(fn):
        fn._ble_callback_type = "indicate"
        fn._ble_uuid = uuid
        fn._att_indicate = uuid
        return fn
    return decorator
```

`BLEProfileServer.register()` introspects the instance for methods decorated with `_att_read`/`_att_write`/`_att_notify`/`_att_indicate`, builds `ServiceDefinition`, calls `gatt_server.add_service()`, then calls `gatt_server.on_read(uuid, callback)` etc. for each.

- [ ] **Step 5: Run tests — verify they pass**

- [ ] **Step 6: Commit**
```bash
git add pybluehost/profiles/ble/base.py pybluehost/profiles/ble/decorators.py tests/unit/profiles/
git commit -m "feat(profiles): add BLEProfileServer base and on_read/write/notify/indicate decorators"
```

---

## Task 2: YAML Service Loader

**Files:** `yaml_loader.py`, `services/*.yaml`

- [ ] **Step 1: Write tests**

```python
# tests/unit/profiles/test_yaml_loader.py
from pybluehost.profiles.ble.yaml_loader import ServiceYAMLLoader
from pathlib import Path
from pybluehost.core.uuid import UUID16

def test_load_dis_yaml():
    path = Path(__file__).parent.parent.parent.parent / "pybluehost/profiles/ble/services/dis.yaml"
    svc = ServiceYAMLLoader.load(path)
    assert svc.uuid == UUID16(0x180A)
    assert len(svc.characteristics) == 6
    char_uuids = [c.uuid for c in svc.characteristics]
    assert UUID16(0x2A29) in char_uuids  # Manufacturer Name
    assert UUID16(0x2A24) in char_uuids  # Model Number

def test_yaml_loader_loads_string():
    yaml_str = """
service:
  uuid: "0x180D"
  name: Heart Rate
  type: primary
  characteristics:
    - uuid: "0x2A37"
      name: Heart Rate Measurement
      properties:
        notify: true
"""
    svc = ServiceYAMLLoader.loads(yaml_str)
    assert svc.uuid == UUID16(0x180D)
    assert len(svc.characteristics) == 1

def test_yaml_loader_load_builtin_hrs():
    svc = ServiceYAMLLoader.load_builtin("hrs")
    assert svc.uuid == UUID16(0x180D)

def test_yaml_loader_validate_bad_yaml():
    errors = ServiceYAMLLoader.validate("nonexistent.yaml")
    assert len(errors) > 0
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `yaml_loader.py`**

```python
from pathlib import Path

class ServiceYAMLLoader:
    """Load YAML service definitions and convert to ServiceDefinition."""

    @staticmethod
    def load(path: str | Path) -> "ServiceDefinition":
        """Load from file path."""
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return ServiceYAMLLoader._parse(data)

    @staticmethod
    def loads(yaml_string: str) -> "ServiceDefinition":
        """Load from YAML string."""
        import yaml
        data = yaml.safe_load(yaml_string)
        return ServiceYAMLLoader._parse(data)

    @staticmethod
    def load_builtin(name: str) -> "ServiceDefinition":
        """Load built-in service by name (e.g. 'hrs', 'bas', 'dis').
        
        Accepts either a bare name ('hrs') or a filename ('hrs.yaml').
        """
        services_dir = Path(__file__).parent / "services"
        stem = Path(name).stem  # strip .yaml if present
        path = services_dir / f"{stem}.yaml"
        return ServiceYAMLLoader.load(path)

    @staticmethod
    def validate(path: str | Path) -> list[str]:
        """Validate YAML format, return list of errors (empty = valid)."""
        errors = []
        try:
            import yaml
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data is None:
                errors.append("Empty YAML file")
            # Accept both top-level 'uuid' (flat) and 'service.uuid' (nested) formats
            elif "uuid" not in data and "service" not in data:
                errors.append("Missing required key: 'uuid' or 'service'")
        except FileNotFoundError:
            errors.append(f"File not found: {path}")
        except Exception as e:
            errors.append(str(e))
        return errors

    @staticmethod
    def _parse(data: dict) -> "ServiceDefinition":
        from pybluehost.ble.gatt import ServiceDefinition, CharacteristicDefinition, CharProperties, Permissions
        from pybluehost.core.uuid import UUID16

        # Support both flat format (uuid: ...) and nested format (service: {uuid: ...})
        if "service" in data:
            svc_data = data["service"]
        else:
            svc_data = data

        uuid = UUID16(int(svc_data["uuid"], 16))
        chars = []
        for c in svc_data.get("characteristics", []):
            char_uuid = UUID16(int(c["uuid"], 16))
            props_data = c.get("properties", {})
            props = CharProperties(0)
            if isinstance(props_data, dict):
                if props_data.get("read"):    props |= CharProperties.READ
                if props_data.get("write"):   props |= CharProperties.WRITE
                if props_data.get("notify"):  props |= CharProperties.NOTIFY
                if props_data.get("indicate"):props |= CharProperties.INDICATE
            elif isinstance(props_data, list):
                if "read" in props_data:    props |= CharProperties.READ
                if "write" in props_data:   props |= CharProperties.WRITE
                if "notify" in props_data:  props |= CharProperties.NOTIFY
                if "indicate" in props_data:props |= CharProperties.INDICATE
            chars.append(CharacteristicDefinition(
                uuid=char_uuid, properties=props,
                permissions=Permissions.READABLE | Permissions.WRITABLE,
            ))
        return ServiceDefinition(uuid=uuid, characteristics=chars)
```

- [ ] **Step 4: Create YAML service files**

```yaml
# services/dis.yaml
service:
  uuid: "0x180A"
  name: Device Information
  type: primary
  characteristics:
    - uuid: "0x2A29"
      name: Manufacturer Name String
      properties:
        read: true
    - uuid: "0x2A24"
      name: Model Number String
      properties:
        read: true
    - uuid: "0x2A27"
      name: Hardware Revision String
      properties:
        read: true
    - uuid: "0x2A26"
      name: Firmware Revision String
      properties:
        read: true
    - uuid: "0x2A28"
      name: Software Revision String
      properties:
        read: true
    - uuid: "0x2A50"
      name: PnP ID
      properties:
        read: true
```

```yaml
# services/bas.yaml
service:
  uuid: "0x180F"
  name: Battery Service
  type: primary
  characteristics:
    - uuid: "0x2A19"
      name: Battery Level
      properties:
        read: true
        notify: true
      descriptors:
        - uuid: "0x2902"
          name: CCCD
```

```yaml
# services/hrs.yaml
service:
  uuid: "0x180D"
  name: Heart Rate
  type: primary
  characteristics:
    - uuid: "0x2A37"
      name: Heart Rate Measurement
      properties:
        notify: true
      descriptors:
        - uuid: "0x2902"
          name: CCCD
    - uuid: "0x2A38"
      name: Body Sensor Location
      properties:
        read: true
    - uuid: "0x2A39"
      name: Heart Rate Control Point
      properties:
        write: true
```

```yaml
# services/gap.yaml
service:
  uuid: "0x1800"
  name: Generic Access
  type: primary
  characteristics:
    - uuid: "0x2A00"
      name: Device Name
      properties:
        read: true
        write: true
    - uuid: "0x2A01"
      name: Appearance
      properties:
        read: true
```

```yaml
# services/gatt.yaml
service:
  uuid: "0x1801"
  name: Generic Attribute
  type: primary
  characteristics:
    - uuid: "0x2A05"
      name: Service Changed
      properties:
        indicate: true
      descriptors:
        - uuid: "0x2902"
          name: CCCD
```

```yaml
# services/bls.yaml
service:
  uuid: "0x1810"
  name: Blood Pressure
  type: primary
  characteristics:
    - uuid: "0x2A35"
      name: Blood Pressure Measurement
      properties:
        indicate: true
      descriptors:
        - uuid: "0x2902"
          name: CCCD
    - uuid: "0x2A36"
      name: Intermediate Cuff Pressure
      properties:
        notify: true
    - uuid: "0x2A49"
      name: Blood Pressure Feature
      properties:
        read: true
```

```yaml
# services/hids.yaml
service:
  uuid: "0x1812"
  name: Human Interface Device
  type: primary
  characteristics:
    - uuid: "0x2A4A"
      name: HID Information
      properties:
        read: true
    - uuid: "0x2A4B"
      name: Report Map
      properties:
        read: true
    - uuid: "0x2A4D"
      name: Report
      properties:
        notify: true
        write: true
    - uuid: "0x2A4C"
      name: HID Control Point
      properties:
        write: true
```

```yaml
# services/rscs.yaml
service:
  uuid: "0x1814"
  name: Running Speed and Cadence
  type: primary
  characteristics:
    - uuid: "0x2A53"
      name: RSC Measurement
      properties:
        notify: true
      descriptors:
        - uuid: "0x2902"
          name: CCCD
    - uuid: "0x2A54"
      name: RSC Feature
      properties:
        read: true
```

```yaml
# services/cscs.yaml
service:
  uuid: "0x1816"
  name: Cycling Speed and Cadence
  type: primary
  characteristics:
    - uuid: "0x2A5B"
      name: CSC Measurement
      properties:
        notify: true
      descriptors:
        - uuid: "0x2902"
          name: CCCD
    - uuid: "0x2A5C"
      name: CSC Feature
      properties:
        read: true
```

- [ ] **Step 5: Run tests — verify they pass**

- [ ] **Step 6: Commit**
```bash
git add pybluehost/profiles/ble/yaml_loader.py pybluehost/profiles/ble/services/
git commit -m "feat(profiles): add ServiceYAMLLoader and built-in service YAML definitions"
```

---

## Task 3: Built-in Profiles (DIS, BAS, HRS, GAP)

**Files:** `dis.py`, `bas.py`, `hrs.py`, `gap_service.py`, `tests/unit/profiles/test_builtin.py`

- [ ] **Step 1: Write failing tests**

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

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `dis.py`, `bas.py`, `hrs.py`, `gap_service.py`**

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

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Write package `__init__.py`**

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

- [ ] **Step 6: Run all profile tests + full suite**
```bash
uv run pytest tests/unit/profiles/ -v
uv run pytest tests/ -v --tb=short
```

- [ ] **Step 7: Commit**
```bash
git add pybluehost/profiles/ble/dis.py pybluehost/profiles/ble/bas.py \
        pybluehost/profiles/ble/hrs.py pybluehost/profiles/ble/gap_service.py \
        pybluehost/profiles/ble/__init__.py tests/unit/profiles/
git commit -m "feat(profiles): add DIS, BAS, HRS, GAP profile servers with update_measurement API"
```

---

## Task 4: Missing Built-in Profiles (BLS, HIDS, RSCS, CSCS, GATTService)

**Files:**
- Create: `pybluehost/profiles/ble/bls.py`
- Create: `pybluehost/profiles/ble/hids.py`
- Create: `pybluehost/profiles/ble/rscs.py`
- Create: `pybluehost/profiles/ble/cscs.py`
- Create: `pybluehost/profiles/ble/gatt_service.py`
- Test: `tests/unit/profiles/test_missing_profiles.py`

- [ ] **Step 1: Write failing tests**

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

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement all five profiles**

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

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**
```bash
git add pybluehost/profiles/ble/bls.py pybluehost/profiles/ble/hids.py \
        pybluehost/profiles/ble/rscs.py pybluehost/profiles/ble/cscs.py \
        pybluehost/profiles/ble/gatt_service.py \
        tests/unit/profiles/test_missing_profiles.py
git commit -m "feat(profiles): add BLS, HIDS, RSCS, CSCS, GATTService profiles with @ble_service decorator"
```

---

## Task 5: Profile Clients (HeartRateClient, BatteryClient)

**Files:**
- Modify: `pybluehost/profiles/ble/hrs.py` — HeartRateClient already scaffolded in Task 3; expand here
- Modify: `pybluehost/profiles/ble/bas.py` — BatteryClient already scaffolded in Task 3; expand here
- Test: `tests/unit/profiles/test_clients.py`

- [ ] **Step 1: Write failing tests**

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

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Verify/expand client implementations in `hrs.py` and `bas.py`**

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

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Run full suite**
```bash
uv run pytest tests/unit/profiles/ -v
uv run pytest tests/ -v --tb=short
```

- [ ] **Step 6: Commit + update STATUS.md**
```bash
git add pybluehost/profiles/ tests/unit/profiles/
git commit -m "feat(profiles): add HeartRateClient and BatteryClient with mock-friendly discover API"

git add docs/superpowers/STATUS.md
git commit -m "docs: mark Plan 8 (BLE Profiles) complete in STATUS.md"
```

---

## 审查补充事项 (2026-04-18 审查后追加)

### 补充 1: ServiceYAMLLoader.validate() 方法（架构 12-ble-profiles.md §12.4）

需要补充实现和测试：

```python
class ServiceYAMLLoader:
    @staticmethod
    def validate(path: str | Path) -> list[str]:
        """Validate YAML service definition, return list of error messages (empty = valid)."""
        ...
```

验证规则：
- UUID 格式正确（16-bit 或 128-bit）
- Characteristic properties 合法（read/write/notify/indicate 等）
- 必填字段存在

### 补充 2: Profile E2E Loopback 测试（架构 14-testing.md §14.5）

9 个内置 Profile 需要 Loopback E2E 测试：Server + Client 双角色完整交互。至少覆盖：
- HRS: Client subscribe notify → Server update heart rate → Client receive notification
- BAS: Client read battery level → 验证值正确
- DIS: Client read manufacturer name → 验证字符串正确

### 补充 3: Client 侧 Profile 实现

Plan 文件结构提到了 Client 类但没有详细 Task。需要补充：
- `HeartRateClient.subscribe_measurement()` → 接收 notification
- `BatteryClient.read_level()` → 读取电池电量
- Client 的 `discover()` 方法 + 缓存失效（Service Changed indication）

### 补充 4: 拆分建议（已在 STATUS.md 标注）

- **Plan 9a — Profile 框架**: base.py, decorators.py, yaml_loader.py（含 validate）, 9 个 YAML 定义文件
- **Plan 9b — 内置 Profile 实现**: 9 个 Server .py + Client 类 + profiles/classic/spp.py + E2E Loopback 测试
