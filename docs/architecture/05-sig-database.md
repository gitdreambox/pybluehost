# 第五节：SIG 数据库

## 5.1 概述

Bluetooth SIG 官方仓库（`pybluehost/lib/sig/`）以 git submodule 形式集成，包含 Assigned Numbers、GSS（GATT Specification Supplement）、Device Properties 等 YAML 数据。`SIGDatabase` 是全项目共用的查表基础设施，为所有协议层提供 UUID、常量、厂商信息等运行时查询。

## 5.2 SIG 仓库结构

```
pybluehost/lib/sig/                          # git submodule
├── assigned_numbers/
│   ├── uuids/
│   │   ├── service_uuids.yaml               # Service UUID ↔ 名称
│   │   ├── characteristic_uuids.yaml        # Characteristic UUID ↔ 名称
│   │   ├── descriptors.yaml                 # Descriptor UUID ↔ 名称
│   │   ├── protocol_identifiers.yaml        # Protocol UUID
│   │   ├── service_class.yaml               # Service Class UUID
│   │   └── ...
│   ├── company_identifiers/
│   │   └── company_identifiers.yaml         # Company ID ↔ 厂商名称
│   ├── core/
│   │   ├── ad_types.yaml                    # AD Type 编码
│   │   ├── appearance_values.yaml           # 设备外观分类
│   │   ├── class_of_device.yaml             # Classic CoD
│   │   ├── psm.yaml                         # L2CAP PSM
│   │   ├── coding_format.yaml               # 音频编码格式
│   │   ├── core_version.yaml                # Core Spec 版本号
│   │   ├── formattypes.yaml                 # Characteristic Presentation Format
│   │   └── ...
│   └── profiles_and_services/
│       ├── a2dp/                             # A2DP 常量
│       ├── avrcp/                            # AVRCP 常量
│       ├── hfp/                              # HFP 常量
│       ├── hdp/                              # HDP 常量
│       └── ...
├── gss/                                      # GATT Specification Supplement
│   ├── org.bluetooth.characteristic.heart_rate_measurement.yaml
│   ├── org.bluetooth.characteristic.battery_level.yaml
│   └── ...                                   # 277 个 Characteristic 字段级编码规范
└── dp/                                       # Device Properties
    ├── properties/                           # 205 个 Property → Characteristic 映射
    ├── property_groups.yaml
    └── property_ids.yaml
```

## 5.3 各层使用场景

| SIG 数据 | 使用方 | 用途 |
|----------|--------|------|
| `uuids/service_uuids.yaml` | GATT、GAP、SDP | Service UUID ↔ 名称互查 |
| `uuids/characteristic_uuids.yaml` | GATT、ATT | Characteristic UUID ↔ 名称互查 |
| `uuids/descriptors.yaml` | GATT | Descriptor UUID ↔ 名称互查 |
| `uuids/protocol_identifiers.yaml` | SDP | Protocol UUID 查询 |
| `uuids/service_class.yaml` | SDP、Classic GAP | Service Class UUID 查询 |
| `company_identifiers.yaml` | GAP 广播解析、DIS | Company ID ↔ 厂商名称 |
| `core/ad_types.yaml` | GAP | 广播 AD Structure 类型解析 |
| `core/appearance_values.yaml` | GAP | 设备外观类别与子类别 |
| `core/class_of_device.yaml` | Classic GAP | CoD Major/Minor Class 解析 |
| `core/psm.yaml` | L2CAP | PSM ↔ 协议名称 |
| `core/coding_format.yaml` | A2DP、LE Audio | 音频编码格式 |
| `profiles_and_services/avrcp/` | AVRCP Profile | Media Attribute ID、Folder Type 等 |
| `profiles_and_services/a2dp/` | A2DP Profile | Codec 常量 |
| `profiles_and_services/hfp/` | HFP Profile | AT Command 常量 |
| `gss/*.yaml` | GATT（可选增强） | Characteristic 值的字段级编解码 |

## 5.4 SIGDatabase 设计

```python
class SIGDatabase:
    """运行时加载 SIG 官方 YAML，提供全栈查表 API"""

    _instance: ClassVar["SIGDatabase | None"] = None
    _sig_root: ClassVar[Path]  # pybluehost/lib/sig/

    @classmethod
    def get(cls) -> "SIGDatabase":
        """单例，首次调用时从 YAML 文件加载到内存"""

    # ── UUID 查询 ──
    def service_name(self, uuid: int) -> str | None:
        """0x180D → 'Heart Rate'"""
    def service_id(self, uuid: int) -> str | None:
        """0x180D → 'org.bluetooth.service.heart_rate'"""
    def characteristic_name(self, uuid: int) -> str | None:
        """0x2A37 → 'Heart Rate Measurement'"""
    def characteristic_id(self, uuid: int) -> str | None:
        """0x2A37 → 'org.bluetooth.characteristic.heart_rate_measurement'"""
    def descriptor_name(self, uuid: int) -> str | None:
        """0x2902 → 'Client Characteristic Configuration'"""
    def uuid_by_name(self, name: str) -> int | None:
        """'Heart Rate' → 0x180D（搜索 service + characteristic + descriptor）"""

    # ── Company ID ──
    def company_name(self, company_id: int) -> str | None:
        """0x004C → 'Apple, Inc.'"""
    def company_id_by_name(self, name: str) -> int | None:
        """'Apple, Inc.' → 0x004C"""

    # ── GAP 常量 ──
    def ad_type_name(self, type_code: int) -> str | None:
        """0x01 → 'Flags'"""
    def appearance_name(self, value: int) -> str | None:
        """0x0341 → 'Running Walking Sensor: In-Shoe'"""
    def appearance_category(self, value: int) -> str | None:
        """0x0341 → 'Running Walking Sensor'"""

    # ── Classic GAP ──
    def class_of_device_str(self, cod: int) -> str:
        """0x200404 → 'Audio/Video - Wearable Headset Device'"""

    # ── L2CAP ──
    def psm_name(self, psm: int) -> str | None:
        """0x0001 → 'SDP'"""

    # ── Profile 常量 ──
    def profile_constants(self, profile: str) -> dict:
        """'avrcp' → 加载 profiles_and_services/avrcp/ 下所有常量"""
```

## 5.5 内部实现

### 延迟加载

```python
class SIGDatabase:
    def __init__(self) -> None:
        self._services: dict[int, _UUIDEntry] | None = None
        self._characteristics: dict[int, _UUIDEntry] | None = None
        self._companies: dict[int, str] | None = None
        # ... 其他表同理

    def _ensure_services(self) -> dict[int, _UUIDEntry]:
        if self._services is None:
            self._services = self._load_uuid_yaml("uuids/service_uuids.yaml")
        return self._services

@dataclass(frozen=True)
class _UUIDEntry:
    uuid: int
    name: str
    identifier: str  # org.bluetooth.service.xxx
```

每类数据在首次访问时加载，避免启动时全部读取。加载后缓存在内存中，后续查询为 O(1) 字典查找。

### YAML 解析

```python
def _load_uuid_yaml(self, relative_path: str) -> dict[int, _UUIDEntry]:
    path = self._sig_root / "assigned_numbers" / relative_path
    with open(path) as f:
        data = yaml.safe_load(f)
    return {
        entry["uuid"]: _UUIDEntry(
            uuid=entry["uuid"],
            name=entry["name"],
            identifier=entry.get("id", ""),
        )
        for entry in data["uuids"]
    }
```

## 5.6 更新策略

```bash
# 更新 SIG 数据：仅需 git submodule update
git submodule update --remote pybluehost/lib/sig

# 无需修改任何 Python 代码
# SIGDatabase 下次首次访问时自动加载更新后的 YAML
```

- SIG 仓库作为 git submodule，版本锁定在特定 commit
- 更新时 `git submodule update --remote` 即可
- 所有常量数据（UUID、Company ID、AD Type 等）更新不需要修改代码
- 运行时从 YAML 文件加载，始终反映当前 submodule 版本

## 5.7 使用示例

```python
from pybluehost.core.sig_db import SIGDatabase

sig = SIGDatabase.get()

# UUID 查询
sig.service_name(0x180D)              # "Heart Rate"
sig.characteristic_name(0x2A37)       # "Heart Rate Measurement"
sig.descriptor_name(0x2902)           # "Client Characteristic Configuration"
sig.uuid_by_name("Battery Level")    # 0x2A19

# Company ID
sig.company_name(0x004C)             # "Apple, Inc."
sig.company_name(0x0006)             # "Microsoft"

# GAP 常量
sig.ad_type_name(0x01)               # "Flags"
sig.ad_type_name(0x09)               # "Complete Local Name"
sig.appearance_name(0x03C1)          # "Cycling: Cycling Computer"

# Classic
sig.class_of_device_str(0x200404)    # "Audio/Video - Wearable Headset Device"

# L2CAP
sig.psm_name(0x0001)                 # "SDP"
sig.psm_name(0x0003)                 # "RFCOMM"

# Trace 日志增强：将 UUID 自动解析为可读名称
# 例如 ATT Read Request handle=0x000C → "Battery Level (0x2A19)"
```

## 5.8 模块位置

```
pybluehost/
├── core/
│   └── sig_db.py          # SIGDatabase 实现
└── lib/
    └── sig/               # git submodule（SIG 官方仓库）
```

`SIGDatabase` 位于 `core/` 层，可被所有上层模块引用，不引入任何层间依赖。
