# 第十二节：BLE Profile 框架与内置 Profile

## 12.1 模块划分

```
profiles/
├── ble/
│   ├── base.py              # BLEProfileServer / BLEProfileClient 基类
│   ├── yaml_loader.py       # YAML Service 定义加载器
│   ├── decorators.py        # @ble_service / @on_read / @on_write / @on_notify 装饰器
│   ├── services/            # 内置 Service 定义（YAML，由我们编写）
│   │   ├── gap.yaml
│   │   ├── gatt.yaml
│   │   ├── dis.yaml
│   │   ├── bas.yaml
│   │   ├── hrs.yaml
│   │   ├── bls.yaml
│   │   ├── hids.yaml
│   │   ├── rscs.yaml
│   │   └── cscs.yaml
│   ├── gap_service.py       # GAP Service (0x1800)
│   ├── gatt_service.py      # GATT Service (0x1801)
│   ├── dis.py               # Device Information Service (0x180A)
│   ├── bas.py               # Battery Service (0x180F)
│   ├── hrs.py               # Heart Rate Service (0x180D)
│   ├── bls.py               # Blood Pressure Service (0x1810)
│   ├── hids.py              # HID over GATT Service (0x1812)
│   ├── rscs.py              # Running Speed and Cadence (0x1814)
│   └── cscs.py              # Cycling Speed and Cadence (0x1816)
```

## 12.2 BLE Service 定义：三种方案

PyBlueHost 支持三种 BLE Service 定义方式。本节详细介绍每种方案的设计、用法和适用场景，并在 12.3 节给出对比分析和最终选型理由。

### 方案 A：纯 Python Dataclass 定义

通过 Python 代码直接构造 `ServiceDefinition` 对象，所有结构和属性都在代码中表达。

```python
from pybluehost.ble.gatt import (
    ServiceDefinition, CharacteristicDefinition, DescriptorDefinition,
    CharProperties, Permissions, UUID16,
)

# 定义 Heart Rate Service
hrs_service = ServiceDefinition(
    uuid=UUID16(0x180D),
    characteristics=[
        CharacteristicDefinition(
            uuid=UUID16(0x2A37),  # Heart Rate Measurement
            properties=CharProperties.NOTIFY,
            permissions=Permissions.READABLE,
            descriptors=[
                DescriptorDefinition(uuid=UUID16(0x2902)),  # CCCD
            ],
        ),
        CharacteristicDefinition(
            uuid=UUID16(0x2A38),  # Body Sensor Location
            properties=CharProperties.READ,
            permissions=Permissions.READABLE,
        ),
        CharacteristicDefinition(
            uuid=UUID16(0x2A39),  # Heart Rate Control Point
            properties=CharProperties.WRITE,
            permissions=Permissions.WRITABLE,
        ),
    ],
)

# 注册服务并绑定回调
server.add_service(hrs_service)
server.on_read(UUID16(0x2A38), lambda: bytes([0x01]))
server.on_write(UUID16(0x2A39), handle_control_point)
server.on_notify(UUID16(0x2A37), heart_rate_stream)
```

**优势：**
- 完全在 Python 类型系统内，IDE 补全和静态检查完整
- 适合动态构建服务（运行时根据条件组装 Characteristic）
- 无外部文件依赖，单文件即完整

**劣势：**
- 代码冗长，UUID 和 Property 声明淹没在 Python 语法噪音中
- 不可跨语言/跨工具复用
- 结构和行为混杂在同一代码块中

### 方案 B：纯 YAML 定义

用 YAML 文件声明服务的完整结构（Service UUID、Characteristic UUID、Properties），Python 侧仅注册回调。

#### YAML Service 定义

```yaml
# hrs.yaml — Heart Rate Service
service:
  uuid: 0x180D
  name: Heart Rate
  type: primary

  characteristics:
    - uuid: 0x2A37
      name: Heart Rate Measurement
      properties:
        notify: true
      descriptors:
        - uuid: 0x2902
          name: CCCD

    - uuid: 0x2A38
      name: Body Sensor Location
      properties:
        read: true

    - uuid: 0x2A39
      name: Heart Rate Control Point
      properties:
        write: true
```

#### Python 使用

```python
from pybluehost.profiles.ble.yaml_loader import load_service_yaml

# 从 YAML 加载服务结构
service = load_service_yaml("hrs.yaml")
server.add_service(service)

# 分别注册回调
server.on_read(0x2A38, lambda: bytes([0x01]))
server.on_write(0x2A39, handle_control_point)
server.on_notify(0x2A37, heart_rate_stream)
```

**优势：**
- 声明式，服务结构一目了然，无语法噪音
- 可跨语言/跨工具复用
- 支持运行时动态加载

**劣势：**
- 行为（回调）无法在 YAML 中表达，必须在 Python 中额外注册
- 结构与行为分散在两个文件中，维护成本增加
- 无 IDE 类型检查，UUID 拼写错误只能运行时发现

### 方案 C：混合方式（YAML 结构 + Python 行为绑定）— 推荐

YAML 定义服务结构，Python 装饰器将回调绑定到对应的 Characteristic，结构与行为在同一个类中统一管理。

#### YAML 定义（同方案 B）

```yaml
# hrs.yaml — Heart Rate Service
service:
  uuid: 0x180D
  name: Heart Rate
  type: primary

  characteristics:
    - uuid: 0x2A37
      name: Heart Rate Measurement
      properties:
        notify: true
      descriptors:
        - uuid: 0x2902
          name: CCCD

    - uuid: 0x2A38
      name: Body Sensor Location
      properties:
        read: true

    - uuid: 0x2A39
      name: Heart Rate Control Point
      properties:
        write: true
```

#### Python Profile 实现

```python
from pybluehost.profiles.ble.base import BLEProfileServer
from pybluehost.profiles.ble.decorators import ble_service, on_read, on_write, on_notify

@ble_service("hrs.yaml")
class HeartRateServer(BLEProfileServer):
    """Heart Rate Profile Server"""

    def __init__(self) -> None:
        super().__init__()
        self._sensor_location: int = 0x01  # Chest

    @on_notify(0x2A37)
    async def heart_rate_measurement(self) -> bytes:
        bpm = await self._read_sensor()
        return struct.pack("BB", 0x00, bpm)

    @on_read(0x2A38)
    async def body_sensor_location(self) -> bytes:
        return bytes([self._sensor_location])

    @on_write(0x2A39)
    async def heart_rate_control_point(self, value: bytes) -> None:
        if value == b"\x01":
            self._reset_energy_expended()
```

#### 装饰器机制

```python
def ble_service(yaml_path: str):
    """类装饰器：加载 YAML 并将服务结构绑定到 Profile 类"""
    def decorator(cls: type[BLEProfileServer]) -> type[BLEProfileServer]:
        cls._service_yaml = yaml_path
        cls._service_definition = load_service_yaml(yaml_path)
        return cls
    return decorator

def on_read(uuid: int | str):
    """方法装饰器：绑定 read 回调到指定 Characteristic UUID"""
    def decorator(func):
        func._ble_callback_type = "read"
        func._ble_uuid = UUID16(uuid) if isinstance(uuid, int) else UUID.from_string(uuid)
        return func
    return decorator

def on_write(uuid: int | str):
    """方法装饰器：绑定 write 回调"""
    # 同上模式

def on_notify(uuid: int | str):
    """方法装饰器：绑定 notify 数据生产回调"""
    # 同上模式

def on_indicate(uuid: int | str):
    """方法装饰器：绑定 indicate 数据生产回调"""
    # 同上模式
```

#### BLEProfileServer 基类

```python
class BLEProfileServer:
    _service_yaml: ClassVar[str | None] = None
    _service_definition: ClassVar[ServiceDefinition | None] = None

    async def register(self, gatt_server: GATTServer) -> None:
        """注册服务到 GATT Server，自动绑定装饰器标记的回调"""
        if self._service_definition is None:
            raise RuntimeError("No service definition. Use @ble_service or set_service().")

        handle = gatt_server.add_service(self._service_definition)

        for method_name in dir(self):
            method = getattr(self, method_name)
            if hasattr(method, "_ble_callback_type"):
                cb_type = method._ble_callback_type
                uuid = method._ble_uuid
                if cb_type == "read":
                    gatt_server.on_read(uuid, method)
                elif cb_type == "write":
                    gatt_server.on_write(uuid, method)
                elif cb_type == "notify":
                    gatt_server.on_notify(uuid, method)
                elif cb_type == "indicate":
                    gatt_server.on_indicate(uuid, method)

    def set_service(self, definition: ServiceDefinition) -> None:
        """运行时替换服务定义（纯 Python 方案兼容）"""
        self._service_definition = definition
```

#### BLEProfileClient 基类

```python
class BLEProfileClient:
    _service_uuid: ClassVar[UUID]

    async def discover(self, gatt_client: GATTClient) -> None:
        """发现目标服务并缓存 Characteristic 句柄"""
        services = await gatt_client.discover_all_services()
        target = next(s for s in services if s.uuid == self._service_uuid)
        self._characteristics = await gatt_client.discover_characteristics(target)
        self._gatt = gatt_client

    async def read(self, uuid: UUID) -> bytes:
        char = self._find_char(uuid)
        return await self._gatt.read_characteristic(char)

    async def write(self, uuid: UUID, value: bytes, response: bool = True) -> None:
        char = self._find_char(uuid)
        await self._gatt.write_characteristic(char, value, response)

    async def subscribe(self, uuid: UUID, handler: Callable[[bytes], Awaitable],
                         indication: bool = False) -> None:
        char = self._find_char(uuid)
        await self._gatt.subscribe(char, handler, indication)
```

## 12.3 三种方案对比与选型决策

### 对比矩阵

| 维度 | 方案 A：纯 Python | 方案 B：纯 YAML | 方案 C：混合（推荐） |
|------|-------------------|----------------|---------------------|
| **类型安全** | 完整，编译期 IDE 检查 | 无，运行时解析 | 结构 YAML 运行时 + 行为 Python 编译期 |
| **可读性** | 差，结构被语法噪音包裹 | 好，声明式一目了然 | 好，结构与行为各司其职 |
| **跨语言复用** | 不可 | 可，YAML 通用格式 | 可，YAML 部分通用 |
| **动态加载** | 需 importlib | 天然支持 | 支持 |
| **回调绑定** | 手动注册，易遗漏 | 手动注册，分散两处 | 装饰器自动绑定，集中管理 |
| **内聚性** | 中，结构+行为同文件但混杂 | 差，结构与行为分散 | 好，一类一文件 + 对应 YAML |
| **调试体验** | 堆栈清晰 | YAML 解析错误需定位 | YAML 加载时验证 + Python 堆栈 |
| **学习曲线** | 只需 Python | 需了解 YAML 格式 | 中等，YAML + 装饰器 |
| **扩展自定义 Service** | 复制代码修改 | 复制 YAML 修改 | 复制 YAML + 继承类 |

### 选择方案 C 的理由

**理由一：结构与行为的天然分离**

BLE Service 定义有两个本质不同的部分：
- **结构**（哪些 Service、哪些 Characteristic、UUID 是什么、Properties 是什么）—— 静态声明，不含逻辑
- **行为**（read 返回什么数据、write 如何处理、notify 何时触发）—— 动态逻辑，必须用代码

YAML 天然适合描述静态结构，Python 天然适合表达动态行为。强行用 Python 描述结构（方案 A）导致大量样板代码；强行将行为从结构中分离到不同文件（方案 B）导致维护困难。混合方式让每种语言做它最擅长的事。

**理由二：装饰器消除手动注册**

方案 A 和方案 B 都需要手动调用 `server.on_read(uuid, callback)` 注册回调，容易遗漏或 UUID 拼写错误。方案 C 的装饰器 `@on_read(0x2A38)` 在类定义时就完成绑定，`register()` 方法自动扫描并注册，消除了手动注册这一错误源。

**理由三：向后兼容纯 Python 方式**

方案 C 不强制使用 YAML。通过 `set_service(ServiceDefinition(...))` 可以完全用纯 Python 定义服务结构，覆盖需要动态组装 Service 的高级场景。三种方式共存，用户按需选择：

```python
# 方式 1：纯 Python（动态/高级场景）
server = BLEProfileServer()
server.set_service(ServiceDefinition(...))
await server.register(gatt_server)

# 方式 2：纯 YAML + 手动注册（快速原型）
service = load_service_yaml("custom.yaml")
gatt_server.add_service(service)
gatt_server.on_read(uuid, callback)

# 方式 3：YAML + 装饰器类（推荐，Profile 开发标准方式）
@ble_service("custom.yaml")
class MyServer(BLEProfileServer):
    @on_read(0x2A38)
    async def read_value(self) -> bytes: ...
```

**理由四：教育与文档价值**

YAML 文件本身就是 Service 结构的文档。新用户可以先阅读 YAML 理解服务由哪些 Characteristic 组成，再看 Python 类理解行为实现。这比纯代码方式的学习路径更清晰，符合 PyBlueHost 的教育目标。

## 12.4 YAML Service Loader 设计

```python
class ServiceYAMLLoader:
    """加载 YAML Service 定义并转换为 ServiceDefinition"""

    @staticmethod
    def load(path: str | Path) -> ServiceDefinition:
        """从文件路径加载"""

    @staticmethod
    def loads(yaml_string: str) -> ServiceDefinition:
        """从 YAML 字符串加载"""

    @staticmethod
    def load_builtin(name: str) -> ServiceDefinition:
        """加载内置 Service YAML（如 'hrs', 'bas', 'dis'）"""

    @staticmethod
    def validate(path: str | Path) -> list[str]:
        """验证 YAML 格式，返回错误列表（空列表 = 通过）"""
```

### YAML Service Schema 规范

```yaml
# PyBlueHost BLE Service 定义 Schema
# 根据各 Profile Specification 编写
service:
  uuid: 0x180D                        # 16-bit 或 128-bit UUID 字符串
  name: Heart Rate                    # 可读名称
  type: primary                       # primary | secondary

  includes:                           # Included Service（可选）
    - uuid: 0x1800

  characteristics:
    - uuid: 0x2A37                    # 16-bit 或 128-bit UUID 字符串
      name: Heart Rate Measurement    # 可读名称
      properties:
        read: false
        write: false
        write-without-response: false
        notify: true
        indicate: false
        signed-write: false
        broadcast: false
        extended-properties: false
      permissions:                    # 可选，默认 open
        read: open                    # open | encrypted | authenticated
        write: open
      descriptors:
        - uuid: 0x2902
          name: CCCD
        - uuid: 0x2901
          name: User Description
          value: "Heart Rate Measurement"
```

## 12.5 内置 Profile 实现

以下 9 个 Profile 均采用方案 C 混合方式实现，每个 Profile = 一个 YAML 文件 + 一个 Python 类。

### GAP Service（0x1800）

```python
@ble_service("gap.yaml")
class GAPServiceServer(BLEProfileServer):
    @on_read(0x2A00)  # Device Name
    async def device_name(self) -> bytes: ...
    @on_read(0x2A01)  # Appearance
    async def appearance(self) -> bytes: ...
```

### GATT Service（0x1801）

```python
@ble_service("gatt.yaml")
class GATTServiceServer(BLEProfileServer):
    @on_indicate(0x2A05)  # Service Changed
    async def service_changed(self) -> bytes: ...
```

### Device Information Service（0x180A）

```python
@ble_service("dis.yaml")
class DeviceInformationServer(BLEProfileServer):
    def __init__(self, manufacturer: str = "", model: str = "",
                 serial: str = "", firmware_rev: str = "",
                 hardware_rev: str = "", software_rev: str = "") -> None: ...

    @on_read(0x2A29)  # Manufacturer Name
    async def manufacturer_name(self) -> bytes: ...
    @on_read(0x2A24)  # Model Number
    async def model_number(self) -> bytes: ...
    # ... 其余 Characteristic 类似
```

### Battery Service（0x180F）

```python
@ble_service("bas.yaml")
class BatteryServer(BLEProfileServer):
    @on_read(0x2A19)   # Battery Level
    async def battery_level(self) -> bytes: ...
    @on_notify(0x2A19)
    async def battery_level_notify(self) -> bytes: ...

    async def update_battery_level(self, level: int) -> None:
        """外部调用：更新电量并触发通知"""
```

### Heart Rate Service（0x180D）

```python
@ble_service("hrs.yaml")
class HeartRateServer(BLEProfileServer):
    @on_notify(0x2A37)  # Heart Rate Measurement
    async def measurement(self) -> bytes: ...
    @on_read(0x2A38)    # Body Sensor Location
    async def sensor_location(self) -> bytes: ...
    @on_write(0x2A39)   # Heart Rate Control Point
    async def control_point(self, value: bytes) -> None: ...
```

### Blood Pressure Service（0x1810）

```python
@ble_service("bls.yaml")
class BloodPressureServer(BLEProfileServer):
    @on_indicate(0x2A35)  # Blood Pressure Measurement
    async def measurement(self) -> bytes: ...
    @on_notify(0x2A36)    # Intermediate Cuff Pressure
    async def intermediate(self) -> bytes: ...
    @on_read(0x2A49)      # Blood Pressure Feature
    async def feature(self) -> bytes: ...
```

### HID over GATT Service（0x1812）

```python
@ble_service("hids.yaml")
class HIDServer(BLEProfileServer):
    @on_read(0x2A4A)    # HID Information
    async def hid_info(self) -> bytes: ...
    @on_read(0x2A4B)    # Report Map
    async def report_map(self) -> bytes: ...
    @on_notify(0x2A4D)  # Report (Input)
    async def input_report(self) -> bytes: ...
    @on_write(0x2A4D)   # Report (Output)
    async def output_report(self, value: bytes) -> None: ...
    @on_write(0x2A4C)   # HID Control Point
    async def control_point(self, value: bytes) -> None: ...
```

### Running Speed and Cadence（0x1814）

```python
@ble_service("rscs.yaml")
class RSCServer(BLEProfileServer):
    @on_notify(0x2A53)  # RSC Measurement
    async def measurement(self) -> bytes: ...
    @on_read(0x2A54)    # RSC Feature
    async def feature(self) -> bytes: ...
```

### Cycling Speed and Cadence（0x1816）

```python
@ble_service("cscs.yaml")
class CSCServer(BLEProfileServer):
    @on_notify(0x2A5B)  # CSC Measurement
    async def measurement(self) -> bytes: ...
    @on_read(0x2A5C)    # CSC Feature
    async def feature(self) -> bytes: ...
```

## 12.6 Client 侧 Profile

```python
class HeartRateClient(BLEProfileClient):
    _service_uuid = UUID16(0x180D)

    async def read_sensor_location(self) -> int:
        data = await self.read(UUID16(0x2A38))
        return data[0]

    async def subscribe_measurement(self, handler: Callable[[int], Awaitable]) -> None:
        async def _parse(data: bytes) -> None:
            flags = data[0]
            bpm = data[1] if not (flags & 0x01) else struct.unpack_from("<H", data, 1)[0]
            await handler(bpm)
        await self.subscribe(UUID16(0x2A37), _parse)

    async def reset_energy_expended(self) -> None:
        await self.write(UUID16(0x2A39), b"\x01")
```

## 12.7 自定义 Profile 示例

用户创建自定义 Service 只需两步：

**Step 1：定义 YAML**

```yaml
# my_custom_service.yaml
service:
  uuid: "12345678-1234-5678-9abc-def012345678"
  name: My Custom Service
  type: primary

  characteristics:
    - uuid: "12345678-1234-5678-9abc-def012345679"
      name: Custom Data
      properties:
        read: true
        notify: true

    - uuid: "12345678-1234-5678-9abc-def01234567a"
      name: Custom Control
      properties:
        write: true
```

**Step 2：实现 Python 类**

```python
@ble_service("my_custom_service.yaml")
class MyCustomServer(BLEProfileServer):
    @on_read("12345678-1234-5678-9abc-def012345679")
    async def custom_data(self) -> bytes:
        return self._get_sensor_data()

    @on_notify("12345678-1234-5678-9abc-def012345679")
    async def custom_data_notify(self) -> bytes:
        return self._get_sensor_data()

    @on_write("12345678-1234-5678-9abc-def01234567a")
    async def custom_control(self, value: bytes) -> None:
        self._handle_command(value)
```

## 12.8 使用示例

### Server 端完整流程

```python
stack = await Stack.from_usb()

# 注册多个 Profile
hrs = HeartRateServer()
bas = BatteryServer()
dis = DeviceInformationServer(manufacturer="PyBlueHost", model="Demo")

await hrs.register(stack.gatt_server)
await bas.register(stack.gatt_server)
await dis.register(stack.gatt_server)

# 开始广播
ad = AdvertisingData()
ad.set_flags(0x06)
ad.set_complete_local_name("PyBH-HRM")
ad.add_service_uuid16(0x180D)
await stack.gap.ble_advertiser.start(AdvertisingConfig(), ad)

# 模拟心率数据
import asyncio
while True:
    await hrs.update_measurement(bpm=72)
    await asyncio.sleep(1.0)
```

### Client 端完整流程

```python
stack = await Stack.from_usb()

# 扫描并连接
results = await stack.gap.ble_scanner.scan_for(5.0)
target = next(r for r in results if r.advertising_data.has_service(0x180D))
conn = await stack.gap.ble_connections.connect(target.address)

# 使用 Profile Client
hrs_client = HeartRateClient()
await hrs_client.discover(conn.gatt_client)

location = await hrs_client.read_sensor_location()
print(f"Sensor location: {location}")

await hrs_client.subscribe_measurement(lambda bpm: print(f"BPM: {bpm}"))
```
