# Plan 9a: BLE Profile Framework

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement the BLE profile framework: `BLEProfileServer`/`BLEProfileClient` base classes, decorators (@ble_service, @on_read, @on_write, @on_notify, @on_indicate), YAML service loader with validate(), and 9 YAML service definition files.

**Architecture reference:** `docs/architecture/12-ble-profiles.md`

**Dependencies:** `pybluehost/ble/gatt.py`, `pybluehost/core/uuid.py`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pybluehost/profiles/ble/__init__.py` | Re-export profile public API |
| `pybluehost/profiles/ble/base.py` | `BLEProfileServer`, `BLEProfileClient` ABC |
| `pybluehost/profiles/ble/decorators.py` | `@ble_service` class decorator, `@on_read`, `@on_write`, `@on_notify`, `@on_indicate` method decorators |
| `pybluehost/profiles/ble/yaml_loader.py` | `ServiceYAMLLoader` class with `load()`, `loads()`, `load_builtin()`, `validate()` |
| `pybluehost/profiles/ble/services/*.yaml` | 9 built-in service YAML definitions (gap, gatt, dis, bas, hrs, bls, hids, rscs, cscs) |
| `tests/unit/profiles/__init__.py` | |
| `tests/unit/profiles/test_base.py` | Base class, decorator tests |
| `tests/unit/profiles/test_yaml_loader.py` | YAML loader tests |

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

---

## Task 3: Final Validation

- [ ] **Step 1: Run all framework tests**
```bash
uv run pytest tests/unit/profiles/test_base.py tests/unit/profiles/test_yaml_loader.py -v
```

- [ ] **Step 2: Commit + update STATUS.md**

---

## 审查补充事项 (from Plan 9 review)

### 补充 1: ServiceYAMLLoader.validate() 方法（架构 12-ble-profiles.md §12.4）

验证规则：
- UUID 格式正确（16-bit 或 128-bit）
- Characteristic properties 合法（read/write/notify/indicate 等）
- 必填字段存在
