# Trace / Log 系统结构化输出实施计划

> **For agentic workers:** REQUIRED SUB-SKILL — Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Fresh subagent per task with two-stage review (spec compliance + code quality). Steps use `- [ ]` syntax for tracking.
>
> **状态更新协议（强制）**：每完成一个 Step 后勾选 checkbox，每完成一个 Task 后更新 `docs/superpowers/STATUS.md`，并以 `docs(progress): ...` commit 提交（参考 `CLAUDE.md` 的"状态更新协议"）。
>
> **代码风格**：所有代码、docstring、注释使用英文；本计划的描述性文字使用中文。

| 项 | 值 |
|----|----|
| 状态 | ✅ 已完成（2026-05-08） |
| 日期 | 2026-05-05 |
| 设计文档 | [trace-log-system-design.md](../specs/trace-log-system-design.md) |
| 任务数 | 25 |
| 预计耗时 | 12–14 小时 |

**Goal:** 让 HCI trace 与协议层 log 结构化、可读、可控；出问题时根据日志能快速定位是哪一层、哪一步。

**Architecture:** 两条独立通道。HCI/transport 走现有 `TraceSystem` + 新 `ConsoleSink`（彩色、紧凑/展开、防刷屏）+ 新 `format_hci_packet()`（SIG DB 查表）；L2CAP 及以上层走 stdlib `logging`，在每层关键决策点注入约 40 个 logger 调用。统一控制：`--trace` CLI flag + `PYBLUEHOST_TRACE` 环境变量，与 `--transport` 同风格。

**Tech Stack:** Python 3.10+、stdlib `logging`、`pybluehost.core.trace.TraceSystem`、`pybluehost.core.sig_db.SIGDatabase`、`pybluehost.hci.packets.decode_hci_packet`。

---

## 文件结构概览

**新增**

| 路径 | 职责 |
|------|------|
| `pybluehost/hci/format.py` | `format_hci_packet()` 主入口（紧凑 + 展开两种模式） |
| `pybluehost/hci/format_fields.py` | 字段格式化器（约 20 个）：BD_ADDR / UUID / Status / RSSI / PHY / company_id / ... |
| `pybluehost/core/trace_console.py` | `ConsoleSink` 类（ANSI 颜色、TTY 探测、anti-flood） |
| `pybluehost/core/trace_control.py` | `TraceSpec` + `parse_trace_spec()` + `apply_logging_levels()` + `attach_console_sink()` + `trace_install()` |
| `tests/unit/hci/test_format.py` | format golden tests |
| `tests/unit/hci/test_format_fields.py` | 字段格式化器单元测试 |
| `tests/unit/core/test_trace_console.py` | ConsoleSink + anti-flood 测试 |
| `tests/unit/core/test_trace_control.py` | spec 解析 + install 测试 |
| `tests/integration/test_trace_console_e2e.py` | CLI subprocess 集成测试 |

**修改**

| 路径 | 改动要点 |
|------|---------|
| `pybluehost/hci/controller.py` | `_emit_trace` 增加 `decoded` 参数，把 decode_hci_packet 结果挂上 TraceEvent |
| `pybluehost/cli/__init__.py` | 顶层 `--trace` 选项；解析后调 `trace_install` |
| `tests/conftest.py` | pytest `--trace` 选项；session 调 `apply_logging_levels`；stack fixture 内 `attach_console_sink` |
| `pybluehost/core/__init__.py` | re-export `ConsoleSink` 与 `trace_install` |
| `pybluehost/l2cap/manager.py` | INFO/WARN：信道开/关、配置完成、超时 |
| `pybluehost/l2cap/signaling.py` | DEBUG：signaling PDU 摘要 |
| `pybluehost/ble/att.py` | INFO/WARN/DEBUG：MTU、Error_Response、读写摘要 |
| `pybluehost/ble/gatt.py` | INFO/DEBUG：service discovery、CCCD、notification |
| `pybluehost/ble/smp.py` | INFO/WARN：pairing 全流程 |
| `pybluehost/ble/security.py` | INFO：SSP 阶段、user_confirmation |
| `pybluehost/hci/controller.py` | INFO：LE_Connection_Complete / Disconnection_Complete |
| `pybluehost/classic/sdp.py` | INFO/WARN：service search |
| `pybluehost/classic/rfcomm.py` | INFO/WARN：信道开关 |
| `pybluehost/classic/gap.py` | INFO：inquiry 启动/完成 |
| `README.md` | "Trace / Debug" 段落 |
| `AGENTS.md` | "调试 trace" 命令示例 |
| `docs/superpowers/STATUS.md` | 加入新 Plan 行 + 完成详细信息 |

---

## Task 1: 字段格式化器骨架（无 SIG DB 部分）

**Files:**
- Create: `pybluehost/hci/format_fields.py`
- Test: `tests/unit/hci/test_format_fields.py`

- [ ] **Step 1.1: Write failing test**

```python
# tests/unit/hci/test_format_fields.py
"""Unit tests for individual HCI field formatters."""
from __future__ import annotations

import pytest

from pybluehost.hci.format_fields import (
    format_address,
    format_address_type,
    format_error_code,
    format_le_phy,
    format_role,
    format_rssi,
    format_scan_interval,
    format_status,
    format_uuid16,
)


def test_format_address_public_renders_msb_first():
    assert format_address(b"\x06\x05\x04\x03\x02\x01", addr_type=0) == "Public 01:02:03:04:05:06"


def test_format_address_random_static():
    assert format_address(b"\x66\x55\x44\x33\x22\x11", addr_type=1) == "Random 11:22:33:44:55:66"


def test_format_address_type_known_values():
    assert format_address_type(0) == "PUBLIC"
    assert format_address_type(1) == "RANDOM"
    assert format_address_type(2) == "PUBLIC_IDENTITY"
    assert format_address_type(3) == "RANDOM_IDENTITY"
    assert format_address_type(99) == "0x63"


def test_format_status_success():
    assert format_status(0x00) == "Success"


def test_format_status_known_error():
    assert format_status(0x08) == "Connection_Timeout(0x08)"


def test_format_status_unknown_error_falls_back_to_hex():
    assert format_status(0xFE) == "0xFE"


def test_format_error_code_alias_for_status():
    assert format_error_code(0x00) == "Success"


def test_format_le_phy_known_values():
    assert format_le_phy(1) == "1M"
    assert format_le_phy(2) == "2M"
    assert format_le_phy(3) == "Coded"
    assert format_le_phy(4) == "Coded_S2"
    assert format_le_phy(99) == "0x63"


def test_format_role():
    assert format_role(0) == "Central"
    assert format_role(1) == "Peripheral"


def test_format_scan_interval_renders_milliseconds():
    # 0x0040 * 0.625 ms = 40.0 ms
    assert format_scan_interval(0x0040) == "0x0040 (40.0 ms)"


def test_format_rssi_dbm():
    assert format_rssi(-65) == "-65 dBm"


def test_format_rssi_unavailable():
    # 127 = RSSI not available per Core spec
    assert format_rssi(127) == "N/A"


def test_format_uuid16_known_service():
    # 0x180D = Heart_Rate; sig_db is queried but value will appear in plain form
    # if sig_db isn't loaded — Task 2 wires the lookup. Here we test the no-name case.
    out = format_uuid16(0x180D, sig_lookup=lambda v: None)
    assert out == "0x180D"


def test_format_uuid16_with_lookup_appends_name():
    out = format_uuid16(0x180D, sig_lookup=lambda v: "Heart_Rate")
    assert out == "0x180D (Heart_Rate)"
```

- [ ] **Step 1.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/hci/test_format_fields.py -v
```

Expected: ImportError for `pybluehost.hci.format_fields`.

- [ ] **Step 1.3: Implement `format_fields.py` (no SIG DB integration yet)**

```python
# pybluehost/hci/format_fields.py
"""Per-field formatters used by format_hci_packet().

Each function takes a raw value and returns a short human-readable string.
SIG-DB lookups are passed in as callables so this module stays pure
(no module-level I/O); the caller wires sig_db.
"""
from __future__ import annotations

from typing import Callable

# Standard HCI status / error codes (Core spec Vol 2 Part D §1.3).
_STATUS_NAMES: dict[int, str] = {
    0x00: "Success",
    0x01: "Unknown_HCI_Command",
    0x02: "Unknown_Connection_Identifier",
    0x03: "Hardware_Failure",
    0x04: "Page_Timeout",
    0x05: "Authentication_Failure",
    0x06: "PIN_Or_Key_Missing",
    0x07: "Memory_Capacity_Exceeded",
    0x08: "Connection_Timeout",
    0x09: "Connection_Limit_Exceeded",
    0x0A: "Synchronous_Connection_Limit_Exceeded",
    0x0B: "Connection_Already_Exists",
    0x0C: "Command_Disallowed",
    0x0D: "Connection_Rejected_Limited_Resources",
    0x0E: "Connection_Rejected_Security_Reasons",
    0x0F: "Connection_Rejected_Unacceptable_BD_ADDR",
    0x10: "Connection_Accept_Timeout_Exceeded",
    0x11: "Unsupported_Feature_Or_Parameter",
    0x12: "Invalid_HCI_Command_Parameters",
    0x13: "Remote_User_Terminated_Connection",
    0x14: "Remote_Device_Terminated_Low_Resources",
    0x15: "Remote_Device_Terminated_Power_Off",
    0x16: "Connection_Terminated_By_Local_Host",
    0x17: "Repeated_Attempts",
    0x18: "Pairing_Not_Allowed",
    # Truncated; extend as needed.
}

_ADDR_TYPE_NAMES: dict[int, str] = {
    0: "PUBLIC",
    1: "RANDOM",
    2: "PUBLIC_IDENTITY",
    3: "RANDOM_IDENTITY",
}

_LE_PHY_NAMES: dict[int, str] = {
    1: "1M",
    2: "2M",
    3: "Coded",
    4: "Coded_S2",
}

_ROLE_NAMES: dict[int, str] = {
    0: "Central",
    1: "Peripheral",
}


def format_address(addr_bytes: bytes, *, addr_type: int) -> str:
    """Render BD_ADDR with address-type prefix (Public / Random / ...)."""
    label = "Public" if addr_type == 0 else "Random"
    msb_first = bytes(reversed(addr_bytes))
    hex_str = ":".join(f"{b:02X}" for b in msb_first)
    return f"{label} {hex_str}"


def format_address_type(value: int) -> str:
    return _ADDR_TYPE_NAMES.get(value, f"0x{value:02X}")


def format_status(value: int) -> str:
    name = _STATUS_NAMES.get(value)
    if name is None:
        return f"0x{value:02X}"
    if value == 0x00:
        return name
    return f"{name}(0x{value:02X})"


# Alias used by error-code-only event fields.
format_error_code = format_status


def format_le_phy(value: int) -> str:
    return _LE_PHY_NAMES.get(value, f"0x{value:02X}")


def format_role(value: int) -> str:
    return _ROLE_NAMES.get(value, f"0x{value:02X}")


def format_scan_interval(value: int) -> str:
    """LE scan / adv interval: raw units of 0.625 ms."""
    ms = value * 0.625
    return f"0x{value:04X} ({ms:.1f} ms)"


def format_rssi(value: int) -> str:
    """LE RSSI in dBm; per Core spec 127 means 'not available'."""
    if value == 127:
        return "N/A"
    return f"{value} dBm"


def format_uuid16(value: int, *, sig_lookup: Callable[[int], str | None]) -> str:
    """16-bit UUID; appends the SIG name when sig_lookup returns one."""
    name = sig_lookup(value)
    if name is None:
        return f"0x{value:04X}"
    return f"0x{value:04X} ({name})"
```

- [ ] **Step 1.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/hci/test_format_fields.py -v
```

- [ ] **Step 1.5: Commit**

```bash
git add pybluehost/hci/format_fields.py tests/unit/hci/test_format_fields.py
git commit -m "feat(hci): add per-field formatters (BD_ADDR/Status/PHY/...)"
```

---

## Task 2: 字段格式化器 SIG DB 集成

**Files:**
- Modify: `pybluehost/hci/format_fields.py`
- Test: `tests/unit/hci/test_format_fields.py`

- [ ] **Step 2.1: Write failing tests for SIG-DB-backed formatters**

Append to `tests/unit/hci/test_format_fields.py`:
```python
def test_format_company_id_known():
    from pybluehost.hci.format_fields import format_company_id

    assert format_company_id(0x000F) == "0x000F (Broadcom Corporation)"


def test_format_company_id_unknown():
    from pybluehost.hci.format_fields import format_company_id

    assert format_company_id(0xFFFE).startswith("0xFFFE")


def test_format_uuid16_via_sig_db_default_lookup():
    from pybluehost.hci.format_fields import format_uuid16_default

    # 0x180D = Heart Rate Service in SIG yaml.
    out = format_uuid16_default(0x180D)
    assert out.startswith("0x180D (")
    assert "Heart" in out


def test_format_uuid128_renders_lowercase_canonical():
    from pybluehost.hci.format_fields import format_uuid128

    raw = bytes.fromhex("fb349b5f8000008000100000180d0000")
    # Canonical xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (big-endian display).
    assert format_uuid128(raw) == "0000180d-0000-1000-8000-00805f9b34fb"


def test_format_class_of_device_phone():
    from pybluehost.hci.format_fields import format_class_of_device

    # 0x080414 = Phone, Smartphone (CoD layout per Bluetooth assigned numbers).
    out = format_class_of_device(0x080414)
    assert out.startswith("0x080414")
    assert "Phone" in out


def test_format_ad_type_byte_known():
    from pybluehost.hci.format_fields import format_ad_type

    # AD type 0x09 = Complete_Local_Name.
    out = format_ad_type(0x09)
    assert out.startswith("0x09")
    assert "Local_Name" in out
```

- [ ] **Step 2.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/hci/test_format_fields.py -v
```

- [ ] **Step 2.3: Add SIG-DB-backed formatters**

Append to `pybluehost/hci/format_fields.py`:
```python
def format_company_id(value: int) -> str:
    """Company identifier (Bluetooth assigned numbers)."""
    from pybluehost.core.sig_db import SIGDatabase

    name = SIGDatabase.get().company_name(value)
    if name is None:
        return f"0x{value:04X}"
    return f"0x{value:04X} ({name})"


def format_uuid16_default(value: int) -> str:
    """16-bit UUID using the project SIGDatabase for lookup."""
    from pybluehost.core.sig_db import SIGDatabase

    db = SIGDatabase.get()

    def lookup(v: int) -> str | None:
        return (
            db.service_name(v)
            or db.characteristic_name(v)
            or db.descriptor_name(v)
        )

    return format_uuid16(value, sig_lookup=lookup)


def format_uuid128(raw: bytes) -> str:
    """128-bit UUID in canonical xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx form."""
    if len(raw) != 16:
        raise ValueError(f"UUID128 must be 16 bytes, got {len(raw)}")
    msb_first = bytes(reversed(raw))
    h = msb_first.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# Major Service Class bits (CoD octets 13..23, here we encode the most useful subset).
_COD_MAJOR_DEVICE_CLASS: dict[int, str] = {
    0x00: "Miscellaneous",
    0x01: "Computer",
    0x02: "Phone",
    0x03: "LAN/Network_Access_Point",
    0x04: "Audio/Video",
    0x05: "Peripheral",
    0x06: "Imaging",
    0x07: "Wearable",
    0x08: "Toy",
    0x09: "Health",
    0x1F: "Uncategorized",
}

# Phone minor classes (when major = 0x02).
_COD_PHONE_MINOR: dict[int, str] = {
    0x00: "Uncategorized",
    0x01: "Cellular",
    0x02: "Cordless",
    0x03: "Smartphone",
    0x04: "Wired_Modem_Or_Voice_Gateway",
    0x05: "ISDN",
}


def format_class_of_device(value: int) -> str:
    """Class of Device (24-bit) -> '0xNNNNNN (Major, Minor)' if classifiable."""
    major = (value >> 8) & 0x1F
    minor = (value >> 2) & 0x3F
    major_name = _COD_MAJOR_DEVICE_CLASS.get(major)
    if major_name is None:
        return f"0x{value:06X}"
    if major == 0x02:
        minor_name = _COD_PHONE_MINOR.get(minor, f"minor=0x{minor:02X}")
        return f"0x{value:06X} ({major_name}, {minor_name})"
    return f"0x{value:06X} ({major_name})"


def format_ad_type(value: int) -> str:
    """Advertising data type byte; uses SIG DB ad_type_name."""
    from pybluehost.core.sig_db import SIGDatabase

    name = SIGDatabase.get().ad_type_name(value)
    if name is None:
        return f"0x{value:02X}"
    return f"0x{value:02X} ({name})"
```

- [ ] **Step 2.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/hci/test_format_fields.py -v
```

If `format_company_id` test fails because `Broadcom Corporation` differs from yaml ("Broadcom"), update the assertion to whatever the yaml actually contains. Use `grep "0x000F\|Broadcom" pybluehost/lib/sig/assigned_numbers/company_identifiers/company_identifiers.yaml | head` to verify the exact name.

- [ ] **Step 2.5: Commit**

```bash
git add pybluehost/hci/format_fields.py tests/unit/hci/test_format_fields.py
git commit -m "feat(hci): wire SIG DB into company_id/UUID/AD type formatters"
```

---

## Task 3: `format_hci_packet()` 紧凑模式

**Files:**
- Create: `pybluehost/hci/format.py`
- Test: `tests/unit/hci/test_format.py`

- [ ] **Step 3.1: Write failing test**

```python
# tests/unit/hci/test_format.py
"""Tests for format_hci_packet() — compact and expanded rendering."""
from __future__ import annotations

import pytest

from pybluehost.core.trace import Direction
from pybluehost.hci.format import format_hci_packet
from pybluehost.hci.packets import (
    HCI_Command_Complete_Event,
    HCI_LE_Meta_Event,
    HCI_Reset,
    decode_hci_packet,
)


def _down_compact(packet) -> str:
    return format_hci_packet(packet, direction=Direction.DOWN, color=False, expand=False)


def _up_compact(packet) -> str:
    return format_hci_packet(packet, direction=Direction.UP, color=False, expand=False)


def test_compact_known_command_renders_name():
    out = _down_compact(HCI_Reset())
    assert "↓ HCI" in out
    assert "Cmd" in out
    assert "HCI_Reset" in out


def test_compact_command_complete_success_single_line():
    raw = bytes([0x04, 0x0E, 0x04, 0x01, 0x03, 0x0C, 0x00])  # CC, Reset, status=Success
    pkt = decode_hci_packet(raw)
    out = _up_compact(pkt)
    assert out.count("\n") == 0
    assert "↑ HCI" in out
    assert "Evt" in out
    assert "Command_Complete" in out
    assert "status=Success" in out


def test_compact_unknown_event_uses_event_code_hex():
    raw = bytes([0x04, 0xFE, 0x02, 0x01, 0x02])
    pkt = decode_hci_packet(raw)
    out = _up_compact(pkt)
    assert "0xFE" in out


def test_compact_le_meta_advertising_report_summarizes():
    # num_reports=1, ADV_IND, public, addr 06:05:04:03:02:01,
    # data_length=0, rssi=-55 (0xC9)
    body = bytes([0x01, 0x00, 0x00]) + bytes([0x06, 0x05, 0x04, 0x03, 0x02, 0x01]) + bytes([0x00, 0xC9])
    raw = bytes([0x04, 0x3E, len(body) + 1, 0x02]) + body
    pkt = decode_hci_packet(raw)
    out = _up_compact(pkt)
    assert "LE_Advertising_Report" in out
    assert "01:02:03:04:05:06" in out
    assert "-55 dBm" in out
```

- [ ] **Step 3.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/hci/test_format.py -v
```

- [ ] **Step 3.3: Implement compact `format_hci_packet`**

```python
# pybluehost/hci/format.py
"""Render an HCIPacket as a human-readable line for console / log output."""
from __future__ import annotations

from pybluehost.core.trace import Direction
from pybluehost.hci.packets import (
    HCI_Command_Complete_Event,
    HCI_Command_Status_Event,
    HCI_LE_Meta_Event,
    HCICommand,
    HCIEvent,
    HCIPacket,
    parse_le_advertising_reports,
)
from pybluehost.hci.format_fields import (
    format_address,
    format_status,
    format_rssi,
)

_DIR_LABELS = {Direction.DOWN: "↓ HCI", Direction.UP: "↑ HCI"}


def format_hci_packet(
    packet: HCIPacket,
    *,
    direction: Direction,
    color: bool = False,
    expand: bool = False,
) -> str:
    """Render an HCIPacket as a single line (or multi-line when expand=True)."""
    dir_label = _DIR_LABELS.get(direction, "  HCI")
    type_label, name, params = _packet_summary(packet)

    if expand:
        return _format_expanded(dir_label, type_label, name, packet)
    return f"{dir_label} {type_label:<4} {name:<32} {params}".rstrip()


def _packet_summary(packet: HCIPacket) -> tuple[str, str, str]:
    """Return (type_label, name, compact_params_string)."""
    if isinstance(packet, HCICommand):
        name = type(packet).__name__
        params = _command_params(packet)
        return ("Cmd", name, params)
    if isinstance(packet, HCIEvent):
        name, params = _event_summary(packet)
        return ("Evt", name, params)
    return ("Pkt", type(packet).__name__, "")


def _command_params(packet: HCICommand) -> str:
    # Most commands have small param sets; default to opcode + plen for unknowns.
    opcode = getattr(packet, "opcode", None)
    if opcode is None:
        return ""
    return f"opcode=0x{opcode:04X}"


def _event_summary(packet: HCIEvent) -> tuple[str, str]:
    if isinstance(packet, HCI_Command_Complete_Event):
        opcode = packet.command_opcode
        status = format_status(packet.return_parameters[0]) if packet.return_parameters else "?"
        return ("Command_Complete", f"op=0x{opcode:04X} status={status}")
    if isinstance(packet, HCI_Command_Status_Event):
        return ("Command_Status", f"op=0x{packet.command_opcode:04X} status={format_status(packet.status)}")
    if isinstance(packet, HCI_LE_Meta_Event):
        return _le_meta_summary(packet)
    name = type(packet).__name__
    code = getattr(packet, "event_code", 0)
    return (f"{name} (0x{code:02X})", "")


def _le_meta_summary(packet: HCI_LE_Meta_Event) -> tuple[str, str]:
    sub = packet.subevent_code
    if sub == 0x02:  # LE_Advertising_Report
        reports = parse_le_advertising_reports(packet.subevent_parameters)
        if not reports:
            return ("LE_Advertising_Report", "0 reports")
        first = reports[0]
        addr = format_address(first.address, addr_type=first.address_type)
        extra = f" + {len(reports) - 1} more" if len(reports) > 1 else ""
        return (
            "LE_Advertising_Report",
            f"{addr} rssi={format_rssi(first.rssi)}{extra}",
        )
    return (f"LE_Meta(0x{sub:02X})", "")


def _format_expanded(dir_label: str, type_label: str, name: str, packet: HCIPacket) -> str:
    # Placeholder for Task 4 — for now just append a summary line.
    return f"{dir_label} {type_label:<4} {name}"
```

- [ ] **Step 3.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/hci/test_format.py -v
```

- [ ] **Step 3.5: Commit**

```bash
git add pybluehost/hci/format.py tests/unit/hci/test_format.py
git commit -m "feat(hci): add format_hci_packet() compact mode"
```

---

## Task 4: `format_hci_packet()` 展开模式

**Files:**
- Modify: `pybluehost/hci/format.py`
- Test: `tests/unit/hci/test_format.py`

- [ ] **Step 4.1: Write failing test**

Append to `tests/unit/hci/test_format.py`:
```python
def test_command_complete_with_failure_status_expands_when_requested():
    # Command Complete with status 0x12 (Invalid_HCI_Command_Parameters).
    raw = bytes([0x04, 0x0E, 0x04, 0x01, 0x03, 0x0C, 0x12])
    pkt = decode_hci_packet(raw)
    out = format_hci_packet(pkt, direction=Direction.UP, color=False, expand=True)
    assert out.count("\n") >= 2
    assert "Invalid_HCI_Command_Parameters" in out
    assert "0x12" in out
    assert "├─" in out or "└─" in out  # tree-style indent


def test_command_complete_with_failure_auto_expands_in_compact_mode():
    """status != Success on Command_Complete should auto-expand even when expand=False."""
    raw = bytes([0x04, 0x0E, 0x04, 0x01, 0x03, 0x0C, 0x12])
    pkt = decode_hci_packet(raw)
    out = format_hci_packet(pkt, direction=Direction.UP, color=False, expand=False)
    assert out.count("\n") >= 2
    assert "Invalid_HCI_Command_Parameters" in out


def test_compact_command_complete_success_does_not_auto_expand():
    raw = bytes([0x04, 0x0E, 0x04, 0x01, 0x03, 0x0C, 0x00])
    pkt = decode_hci_packet(raw)
    out = format_hci_packet(pkt, direction=Direction.UP, color=False, expand=False)
    assert out.count("\n") == 0
```

- [ ] **Step 4.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/hci/test_format.py -v
```

- [ ] **Step 4.3: Implement auto-expand + multi-line tree**

Replace `_format_expanded` and add auto-expand check in `format_hci_packet`:
```python
def format_hci_packet(
    packet: HCIPacket,
    *,
    direction: Direction,
    color: bool = False,
    expand: bool = False,
) -> str:
    dir_label = _DIR_LABELS.get(direction, "  HCI")
    type_label, name, params = _packet_summary(packet)

    if expand or _should_auto_expand(packet):
        return _format_expanded(dir_label, type_label, name, packet)
    return f"{dir_label} {type_label:<4} {name:<32} {params}".rstrip()


def _should_auto_expand(packet: HCIPacket) -> bool:
    """Auto-expand Command_Complete/Status when status != Success and Disconnection_Complete with non-local-host reason."""
    if isinstance(packet, HCI_Command_Complete_Event):
        if packet.return_parameters and packet.return_parameters[0] != 0x00:
            return True
    if isinstance(packet, HCI_Command_Status_Event) and packet.status != 0x00:
        return True
    return False


def _format_expanded(dir_label: str, type_label: str, name: str, packet: HCIPacket) -> str:
    header = f"{dir_label} {type_label:<4} {name}"
    fields = list(_packet_fields(packet))
    if not fields:
        return header
    lines = [header]
    indent = " " * (len(dir_label) + 1 + len(type_label) + 1 + 1)
    last_idx = len(fields) - 1
    for i, (key, value) in enumerate(fields):
        prefix = "└─" if i == last_idx else "├─"
        lines.append(f"{indent}{prefix} {key:<24} = {value}")
    return "\n".join(lines)


def _packet_fields(packet: HCIPacket) -> list[tuple[str, str]]:
    """Return ordered (label, formatted_value) pairs for expanded rendering."""
    if isinstance(packet, HCI_Command_Complete_Event):
        params = packet.return_parameters or b""
        rows: list[tuple[str, str]] = [
            ("num_hci_command_packets", str(packet.num_hci_command_packets)),
            ("command_opcode", f"0x{packet.command_opcode:04X}"),
        ]
        if params:
            rows.append(("status", format_status(params[0])))
        return rows
    if isinstance(packet, HCI_Command_Status_Event):
        return [
            ("status", format_status(packet.status)),
            ("num_hci_command_packets", str(packet.num_hci_command_packets)),
            ("command_opcode", f"0x{packet.command_opcode:04X}"),
        ]
    return []
```

- [ ] **Step 4.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/hci/test_format.py -v
```

- [ ] **Step 4.5: Commit**

```bash
git add pybluehost/hci/format.py tests/unit/hci/test_format.py
git commit -m "feat(hci): add format_hci_packet() expanded mode + auto-expand on errors"
```

---

## Task 5: `HCIController._emit_trace` 挂载解码后的 packet

**Files:**
- Modify: `pybluehost/hci/controller.py`
- Test: `tests/unit/hci/test_controller_trace.py`

- [ ] **Step 5.1: Write failing test**

```python
# tests/unit/hci/test_controller_trace.py
"""Verify HCIController._emit_trace attaches the decoded packet to TraceEvent."""
from __future__ import annotations

import pytest

from pybluehost.core.trace import Direction, TraceEvent, TraceSystem
from pybluehost.hci.controller import HCIController
from pybluehost.hci.packets import HCI_Reset, HCICommand


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def on_trace(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None: ...
    async def close(self) -> None: ...


@pytest.mark.asyncio
async def test_emit_trace_decodes_and_attaches_packet():
    trace = TraceSystem()
    sink = _RecordingSink()
    trace.add_sink(sink)
    await trace.start()

    raw = HCI_Reset().to_bytes()
    controller = HCIController(transport=None, trace=trace)
    controller._emit_trace(Direction.DOWN, raw)

    await trace.stop()

    assert len(sink.events) == 1
    decoded = sink.events[0].decoded
    assert isinstance(decoded, HCICommand)


@pytest.mark.asyncio
async def test_emit_trace_falls_back_to_none_on_decode_error():
    trace = TraceSystem()
    sink = _RecordingSink()
    trace.add_sink(sink)
    await trace.start()

    controller = HCIController(transport=None, trace=trace)
    controller._emit_trace(Direction.DOWN, b"\xff")  # invalid

    await trace.stop()

    assert sink.events[0].decoded is None
```

- [ ] **Step 5.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/hci/test_controller_trace.py -v
```

- [ ] **Step 5.3: Update `_emit_trace`**

In `pybluehost/hci/controller.py`, replace `_emit_trace`:
```python
    def _emit_trace(self, direction: Direction, raw: bytes) -> None:
        if self._trace is None:
            return
        decoded: object | None
        try:
            from pybluehost.hci.packets import decode_hci_packet

            decoded = decode_hci_packet(raw)
        except Exception:
            decoded = None
        self._trace.emit(
            TraceEvent(
                timestamp=time.time(),
                wall_clock=datetime.now(timezone.utc),
                source_layer="hci",
                direction=direction,
                raw_bytes=raw,
                decoded=decoded,
                connection_handle=None,
                metadata={},
            )
        )
```

Note: `TraceEvent.decoded` is annotated `dict[str, Any] | None` in the current code. Change the annotation to `object | None` in `pybluehost/core/trace.py:TraceEvent` so it can carry typed packets in addition to dicts. Existing JSON sink should continue to work via `getattr(decoded, '__dict__', None)` — Step 5.4 handles JsonSink.

- [ ] **Step 5.4: Update `TraceEvent.decoded` typing + JsonSink fallback**

In `pybluehost/core/trace.py`:
```python
@dataclass(frozen=True)
class TraceEvent:
    timestamp: float
    wall_clock: datetime
    source_layer: str
    direction: Direction
    raw_bytes: bytes
    decoded: object | None    # was dict[str, Any] | None
    connection_handle: int | None
    metadata: dict[str, Any]
```

Update `JsonSink.on_trace` so non-dict decoded objects don't break json serialization:
```python
        if self._decode and event.decoded is not None:
            decoded = event.decoded
            if isinstance(decoded, dict):
                obj["decoded"] = decoded
            else:
                obj["decoded"] = {"_type": type(decoded).__name__}
```

- [ ] **Step 5.5: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/hci/test_controller_trace.py tests/unit/core/ -q
```

- [ ] **Step 5.6: Commit**

```bash
git add pybluehost/hci/controller.py pybluehost/core/trace.py tests/unit/hci/test_controller_trace.py
git commit -m "feat(hci): attach decoded packet to TraceEvent.decoded"
```

---

## Task 6: ConsoleSink 基础（TTY/color 探测、单行写出）

**Files:**
- Create: `pybluehost/core/trace_console.py`
- Test: `tests/unit/core/test_trace_console.py`

- [ ] **Step 6.1: Write failing test**

```python
# tests/unit/core/test_trace_console.py
"""Tests for the live ConsoleSink used by --trace=hci."""
from __future__ import annotations

import io

import pytest

from pybluehost.core.trace import Direction, TraceEvent, TraceSystem
from pybluehost.core.trace_console import ConsoleSink
from pybluehost.hci.packets import HCI_Reset


def _make_event(packet, direction=Direction.DOWN, layer="hci"):
    from datetime import datetime, timezone

    return TraceEvent(
        timestamp=0.0,
        wall_clock=datetime.now(timezone.utc),
        source_layer=layer,
        direction=direction,
        raw_bytes=packet.to_bytes() if packet is not None else b"",
        decoded=packet,
        connection_handle=None,
        metadata={},
    )


@pytest.mark.asyncio
async def test_console_sink_writes_compact_line_for_known_command():
    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False)
    await sink.on_trace(_make_event(HCI_Reset()))
    out = buf.getvalue()
    assert "↓ HCI" in out
    assert "HCI_Reset" in out
    assert "\x1b[" not in out  # no ANSI when color=False


@pytest.mark.asyncio
async def test_console_sink_color_true_emits_ansi_escapes():
    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=True)
    await sink.on_trace(_make_event(HCI_Reset()))
    out = buf.getvalue()
    assert "\x1b[" in out


@pytest.mark.asyncio
async def test_console_sink_filters_by_layer_set():
    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False, layers={"hci"})
    await sink.on_trace(_make_event(HCI_Reset(), layer="sm"))
    assert buf.getvalue() == ""


@pytest.mark.asyncio
async def test_console_sink_skips_when_decoded_missing():
    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False)
    event = TraceEvent(
        timestamp=0.0,
        wall_clock=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        source_layer="hci",
        direction=Direction.DOWN,
        raw_bytes=b"\xff",
        decoded=None,
        connection_handle=None,
        metadata={},
    )
    await sink.on_trace(event)
    out = buf.getvalue()
    # Falls back to '<undecoded ...>' line, not an error.
    assert "undecoded" in out


def test_default_color_is_off_when_not_a_tty(monkeypatch):
    buf = io.StringIO()  # not a TTY
    sink = ConsoleSink(stream=buf)  # color=None -> auto
    assert sink._color is False


def test_no_color_env_var_forces_off(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    sink = ConsoleSink()  # default stream=stderr
    assert sink._color is False


def test_force_color_env_var_forces_on(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    sink = ConsoleSink()
    assert sink._color is True
```

- [ ] **Step 6.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/core/test_trace_console.py -v
```

- [ ] **Step 6.3: Implement `ConsoleSink`**

```python
# pybluehost/core/trace_console.py
"""Live trace sink that writes structured HCI lines to a stream (default stderr).

Honors color via TTY auto-detect / NO_COLOR / FORCE_COLOR per the convention
shared with grep, git, bat. Filters by layer; falls back to a single
'undecoded' line when the trace event has no decoded payload.
"""
from __future__ import annotations

import os
import sys
from typing import IO

from pybluehost.core.trace import Direction, TraceEvent
from pybluehost.hci.format import format_hci_packet
from pybluehost.hci.packets import HCIPacket

_RESET = "\x1b[0m"
_DIM = "\x1b[2m"
_BRIGHT = "\x1b[1m"
_RED_BOLD = "\x1b[1;31m"
_CYAN = "\x1b[36m"
_GREEN = "\x1b[32m"
_YELLOW = "\x1b[33m"
_MAGENTA = "\x1b[35m"


class ConsoleSink:
    """Writes one HCI trace line per event to stream (default stderr)."""

    def __init__(
        self,
        *,
        stream: IO[str] | None = None,
        color: bool | None = None,
        layers: set[str] | None = None,
        level: str = "info",
    ) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._color = self._resolve_color(color, self._stream)
        self._layers = layers
        self._level = level

    @staticmethod
    def _resolve_color(value: bool | None, stream: IO[str]) -> bool:
        if value is True:
            return True
        if value is False:
            return False
        # Auto: env vars first, then TTY check.
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("FORCE_COLOR"):
            return True
        return bool(getattr(stream, "isatty", lambda: False)())

    async def on_trace(self, event: TraceEvent) -> None:
        if self._layers is not None and event.source_layer not in self._layers:
            return
        if event.source_layer != "hci":
            return  # Future: handle other layers; for now only HCI.
        line = self._render(event)
        if line:
            self._stream.write(line + "\n")
            self._stream.flush()

    def _render(self, event: TraceEvent) -> str:
        packet = event.decoded
        if not isinstance(packet, HCIPacket):
            return f"{event.direction.name:<4} HCI <undecoded {event.raw_bytes.hex()[:40]}{'...' if len(event.raw_bytes) > 20 else ''}>"
        try:
            line = format_hci_packet(
                packet,
                direction=event.direction,
                color=False,
                expand=(self._level == "debug"),
            )
        except Exception as exc:
            return f"<format error: {exc}> raw={event.raw_bytes.hex()[:40]}"
        if not self._color:
            return line
        return self._colorize(line, event.direction)

    @staticmethod
    def _colorize(line: str, direction: Direction) -> str:
        # Cyan/green for direction, no other parsing — keeps it simple.
        prefix = _CYAN if direction == Direction.DOWN else _GREEN
        return f"{prefix}{line}{_RESET}"

    async def flush(self) -> None:
        if hasattr(self._stream, "flush"):
            self._stream.flush()

    async def close(self) -> None:
        # Don't close stderr; only close streams the user explicitly handed us.
        pass
```

- [ ] **Step 6.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/core/test_trace_console.py -v
```

- [ ] **Step 6.5: Commit**

```bash
git add pybluehost/core/trace_console.py tests/unit/core/test_trace_console.py
git commit -m "feat(core): add ConsoleSink with TTY/color auto-detect"
```

---

## Task 7: ConsoleSink anti-flood — `Number_Of_Completed_Packets` 抑制 + ACL 截断

**Files:**
- Modify: `pybluehost/core/trace_console.py`
- Test: `tests/unit/core/test_trace_console.py`

- [ ] **Step 7.1: Write failing tests**

Append to `tests/unit/core/test_trace_console.py`:
```python
@pytest.mark.asyncio
async def test_number_of_completed_packets_suppressed_by_default():
    from pybluehost.hci.packets import HCI_Number_Of_Completed_Packets_Event

    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False)
    event = HCI_Number_Of_Completed_Packets_Event(
        connection_handles=[0x40], num_completed=[1],
    )
    await sink.on_trace(_make_event(event, direction=Direction.UP))
    assert buf.getvalue() == ""


@pytest.mark.asyncio
async def test_number_of_completed_packets_shown_when_explicit_include():
    from pybluehost.hci.packets import HCI_Number_Of_Completed_Packets_Event

    buf = io.StringIO()
    sink = ConsoleSink(
        stream=buf, color=False, include={"Number_Of_Completed_Packets"},
    )
    event = HCI_Number_Of_Completed_Packets_Event(
        connection_handles=[0x40], num_completed=[1],
    )
    await sink.on_trace(_make_event(event, direction=Direction.UP))
    assert "Number_Of_Completed_Packets" in buf.getvalue()


@pytest.mark.asyncio
async def test_acl_data_truncates_payload_at_default_24_bytes():
    from pybluehost.hci.packets import HCIACLData

    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False)
    payload = bytes(range(64))  # 64-byte payload
    pkt = HCIACLData(handle=0x40, pb_flag=0, bc_flag=0, data=payload)
    await sink.on_trace(_make_event(pkt))
    out = buf.getvalue()
    assert "handle=0x0040" in out
    assert "len=64" in out
    # First 24 bytes appear; later bytes do not.
    assert payload[:24].hex() in out.lower() or payload[:24].hex(' ') in out
    assert payload[40:].hex() not in out


@pytest.mark.asyncio
async def test_acl_data_full_payload_when_full_acl_enabled():
    from pybluehost.hci.packets import HCIACLData

    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False, full_acl=True)
    payload = bytes(range(40))
    pkt = HCIACLData(handle=0x40, pb_flag=0, bc_flag=0, data=payload)
    await sink.on_trace(_make_event(pkt))
    assert payload[24:].hex(" ") in buf.getvalue() or payload[24:].hex() in buf.getvalue()
```

- [ ] **Step 7.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/core/test_trace_console.py -v
```

- [ ] **Step 7.3: Add suppression + ACL handling to `ConsoleSink`**

In `pybluehost/core/trace_console.py`:
- Add params `include: set[str] | None = None`, `full_acl: bool = False`, `max_acl_payload: int = 24` to `__init__`
- Default suppress set: `{"Number_Of_Completed_Packets"}`
- In `_render`, before formatting check `_should_suppress(packet)` and special-case `HCIACLData` to render `handle=0x{...:04X} pb={..} cid=... len={..} data={hex...}` truncated

```python
    def __init__(
        self,
        *,
        stream: IO[str] | None = None,
        color: bool | None = None,
        layers: set[str] | None = None,
        level: str = "info",
        include: set[str] | None = None,
        full_acl: bool = False,
        max_acl_payload: int = 24,
    ) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._color = self._resolve_color(color, self._stream)
        self._layers = layers
        self._level = level
        self._include = include or set()
        self._full_acl = full_acl
        self._max_acl_payload = max_acl_payload

    _DEFAULT_SUPPRESS = {"Number_Of_Completed_Packets"}

    def _should_suppress(self, packet: object) -> bool:
        name = type(packet).__name__.replace("HCI_", "").replace("_Event", "")
        if name in self._include:
            return False
        return name in self._DEFAULT_SUPPRESS
```

In `_render`:
```python
        if self._should_suppress(packet):
            return ""
        from pybluehost.hci.packets import HCIACLData
        if isinstance(packet, HCIACLData):
            return self._render_acl(event, packet)
        # ... existing format_hci_packet path ...

    def _render_acl(self, event: TraceEvent, packet: "HCIACLData") -> str:
        handle = packet.handle
        plen = len(packet.data)
        body = packet.data if self._full_acl else packet.data[: self._max_acl_payload]
        truncated = "" if (self._full_acl or plen <= self._max_acl_payload) else " ..."
        prefix = _DIR_LABELS.get(event.direction, "  HCI")
        return f"{prefix} ACL  handle=0x{handle:04X} len={plen} data={body.hex(' ')}{truncated}"
```

Add `from pybluehost.hci.format import _DIR_LABELS  # type: ignore` or duplicate the small dict — pick one. Recommended: move `_DIR_LABELS` to a public name (say `DIR_LABELS`) in `format.py` and import it.

- [ ] **Step 7.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/core/test_trace_console.py -v
```

- [ ] **Step 7.5: Commit**

```bash
git add pybluehost/core/trace_console.py pybluehost/hci/format.py tests/unit/core/test_trace_console.py
git commit -m "feat(core): ConsoleSink suppresses Number_Of_Completed_Packets and truncates ACL payload"
```

---

## Task 8: ConsoleSink LE_Adv_Report 折叠（5 秒窗口）

**Files:**
- Modify: `pybluehost/core/trace_console.py`
- Test: `tests/unit/core/test_trace_console.py`

- [ ] **Step 8.1: Write failing test**

Append to `tests/unit/core/test_trace_console.py`:
```python
@pytest.mark.asyncio
async def test_repeated_le_advertising_reports_collapse_for_same_address():
    from pybluehost.hci.packets import HCI_LE_Meta_Event

    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False, adv_collapse_window=5.0)

    body = bytes([0x01, 0x00, 0x00]) + bytes([0x06, 0x05, 0x04, 0x03, 0x02, 0x01]) + bytes([0x00, 0xC9])
    event = HCI_LE_Meta_Event(subevent_code=0x02, subevent_parameters=body)

    # 5 reports for the same address.
    for _ in range(5):
        await sink.on_trace(_make_event(event, direction=Direction.UP))

    out = buf.getvalue()
    # First one printed; the next four collapsed (no printing yet).
    assert out.count("LE_Advertising_Report") == 1


@pytest.mark.asyncio
async def test_collapse_summary_emitted_when_new_address_arrives():
    from pybluehost.hci.packets import HCI_LE_Meta_Event

    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False, adv_collapse_window=5.0)

    addr_a = bytes([0x06, 0x05, 0x04, 0x03, 0x02, 0x01])
    addr_b = bytes([0x66, 0x55, 0x44, 0x33, 0x22, 0x11])

    body_a = bytes([0x01, 0x00, 0x00]) + addr_a + bytes([0x00, 0xC9])
    body_b = bytes([0x01, 0x00, 0x00]) + addr_b + bytes([0x00, 0xC0])

    for _ in range(3):
        await sink.on_trace(_make_event(
            HCI_LE_Meta_Event(subevent_code=0x02, subevent_parameters=body_a),
            direction=Direction.UP,
        ))
    # Now an address-B report arrives — emits the collapsed-A summary first.
    await sink.on_trace(_make_event(
        HCI_LE_Meta_Event(subevent_code=0x02, subevent_parameters=body_b),
        direction=Direction.UP,
    ))

    out = buf.getvalue()
    assert "× 2" in out or "x 2" in out  # 2 additional reports collapsed (3 total - 1 already shown)
    assert "01:02:03:04:05:06" in out
    assert "11:22:33:44:55:66" in out
```

- [ ] **Step 8.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/core/test_trace_console.py -v
```

- [ ] **Step 8.3: Add LE_Adv_Report collapse logic**

In `pybluehost/core/trace_console.py`:
- Add `__init__` param `adv_collapse_window: float = 5.0`
- Internal state: `_recent_adv: dict[tuple[bytes, int], int]  # (addr, addr_type) -> extra_count_since_first_print`
- Internal state: `_last_adv_key: tuple[bytes, int] | None`

In `_render`, before normal LE meta handling:
```python
        from pybluehost.hci.packets import HCI_LE_Meta_Event, parse_le_advertising_reports
        if isinstance(packet, HCI_LE_Meta_Event) and packet.subevent_code == 0x02:
            return self._render_le_adv_collapsed(event, packet)
```

```python
    def _render_le_adv_collapsed(self, event: TraceEvent, packet: "HCI_LE_Meta_Event") -> str:
        from pybluehost.hci.packets import parse_le_advertising_reports

        reports = parse_le_advertising_reports(packet.subevent_parameters)
        if not reports:
            return ""
        first = reports[0]
        key = (first.address, first.address_type)
        out_lines: list[str] = []
        # If address changed, flush any pending collapsed summary for the previous key.
        if self._last_adv_key is not None and self._last_adv_key != key:
            extra = self._recent_adv.get(self._last_adv_key, 0)
            if extra > 0:
                prev_addr_bytes, prev_type = self._last_adv_key
                from pybluehost.hci.format_fields import format_address
                addr_str = format_address(prev_addr_bytes, addr_type=prev_type)
                out_lines.append(f"  ... × {extra} more from {addr_str}")
            self._recent_adv.pop(self._last_adv_key, None)
        if key in self._recent_adv:
            self._recent_adv[key] += 1
            return "\n".join(out_lines) if out_lines else ""
        # First time seeing this key in this window: print full line, start counter.
        self._recent_adv[key] = 0
        self._last_adv_key = key
        line = format_hci_packet(packet, direction=event.direction, color=False, expand=False)
        out_lines.append(line)
        return "\n".join(out_lines)
```

Initialize `self._recent_adv = {}` and `self._last_adv_key = None` in `__init__`.

- [ ] **Step 8.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/core/test_trace_console.py -v
```

- [ ] **Step 8.5: Commit**

```bash
git add pybluehost/core/trace_console.py tests/unit/core/test_trace_console.py
git commit -m "feat(core): collapse repeat LE_Advertising_Report from same address"
```

---

## Task 9: `parse_trace_spec()` — TraceSpec 与解析器

**Files:**
- Create: `pybluehost/core/trace_control.py`
- Test: `tests/unit/core/test_trace_control.py`

- [ ] **Step 9.1: Write failing test**

```python
# tests/unit/core/test_trace_control.py
"""Tests for trace spec parser (--trace / PYBLUEHOST_TRACE)."""
from __future__ import annotations

import pytest

from pybluehost.core.trace_control import (
    InvalidTraceSpec,
    TraceSpec,
    parse_trace_spec,
)


def test_empty_spec_disables_everything():
    spec = parse_trace_spec("")
    assert spec.layers == {}
    assert spec.full_acl is False
    assert spec.include == set()


def test_none_disables_everything():
    spec = parse_trace_spec(None)
    assert spec.layers == {}


def test_single_layer_default_info():
    spec = parse_trace_spec("hci")
    assert spec.layers == {"hci": "info"}


def test_layer_with_explicit_level():
    spec = parse_trace_spec("hci=debug")
    assert spec.layers == {"hci": "debug"}


def test_multiple_layers_independent_levels():
    spec = parse_trace_spec("hci,l2cap=debug,sm")
    assert spec.layers == {"hci": "info", "l2cap": "debug", "sm": "info"}


def test_wildcard_expands_to_all_layers_info():
    spec = parse_trace_spec("*")
    assert "hci" in spec.layers and spec.layers["hci"] == "info"
    assert "l2cap" in spec.layers
    assert "smp" in spec.layers


def test_wildcard_debug():
    spec = parse_trace_spec("*=debug")
    assert all(level == "debug" for level in spec.layers.values())


def test_full_acl_option():
    spec = parse_trace_spec("hci,full-acl")
    assert spec.layers == {"hci": "info"}
    assert spec.full_acl is True


def test_include_option():
    spec = parse_trace_spec("hci,include=Number_Of_Completed_Packets")
    assert spec.include == {"Number_Of_Completed_Packets"}


def test_invalid_layer_raises():
    with pytest.raises(InvalidTraceSpec, match="Unknown layer"):
        parse_trace_spec("invalid_layer")


def test_invalid_level_raises():
    with pytest.raises(InvalidTraceSpec, match="Invalid level"):
        parse_trace_spec("hci=loud")


def test_unknown_option_raises():
    with pytest.raises(InvalidTraceSpec, match="Unknown trace option"):
        parse_trace_spec("hci,extra=garbage")
```

- [ ] **Step 9.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/core/test_trace_control.py -v
```

- [ ] **Step 9.3: Implement parser**

```python
# pybluehost/core/trace_control.py
"""Parse and apply trace control specs from --trace / PYBLUEHOST_TRACE.

Spec syntax (comma-separated tokens):
  layer                -> layer at info level
  layer=info|debug     -> layer at explicit level
  *                    -> all layers info
  *=debug              -> all layers debug
  full-acl             -> include full ACL payload (no truncation)
  include=<EventName>  -> opt event(s) back into the suppress list
"""
from __future__ import annotations

from dataclasses import dataclass, field

_KNOWN_LAYERS = {
    "hci", "sm", "transport",
    "l2cap", "att", "gatt", "smp",
    "sdp", "rfcomm", "gap",
}
_VALID_LEVELS = {"info", "debug"}
_OPTION_PREFIXES = ("full-acl", "include=")


class InvalidTraceSpec(ValueError):
    """Raised when --trace / PYBLUEHOST_TRACE syntax is malformed."""


@dataclass
class TraceSpec:
    layers: dict[str, str] = field(default_factory=dict)
    full_acl: bool = False
    include: set[str] = field(default_factory=set)

    def is_empty(self) -> bool:
        return not self.layers and not self.full_acl and not self.include


def parse_trace_spec(s: str | None) -> TraceSpec:
    """Parse a trace spec string. Empty / None means disabled (returns empty TraceSpec)."""
    spec = TraceSpec()
    if not s or not s.strip():
        return spec

    for raw in s.split(","):
        token = raw.strip()
        if not token:
            continue
        if _is_option_token(token):
            _apply_option(spec, token)
        else:
            _apply_layer(spec, token)
    return spec


def _is_option_token(token: str) -> bool:
    return any(token == p or token.startswith(p) for p in _OPTION_PREFIXES)


def _apply_option(spec: TraceSpec, token: str) -> None:
    if token == "full-acl":
        spec.full_acl = True
        return
    if token.startswith("include="):
        value = token.split("=", 1)[1].strip()
        if not value:
            raise InvalidTraceSpec(f"Empty include= value in {token!r}")
        spec.include.add(value)
        return
    raise InvalidTraceSpec(f"Unknown trace option: {token!r}")


def _apply_layer(spec: TraceSpec, token: str) -> None:
    if "=" in token:
        layer, level = token.split("=", 1)
        layer = layer.strip()
        level = level.strip()
    else:
        layer, level = token, "info"

    if level not in _VALID_LEVELS:
        raise InvalidTraceSpec(f"Invalid level: {level!r} (must be info or debug)")

    if layer == "*":
        for name in _KNOWN_LAYERS:
            spec.layers[name] = level
        return
    if layer not in _KNOWN_LAYERS:
        raise InvalidTraceSpec(f"Unknown layer: {layer!r}")
    spec.layers[layer] = level
```

- [ ] **Step 9.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/core/test_trace_control.py -v
```

- [ ] **Step 9.5: Commit**

```bash
git add pybluehost/core/trace_control.py tests/unit/core/test_trace_control.py
git commit -m "feat(core): add parse_trace_spec for --trace / PYBLUEHOST_TRACE"
```

---

## Task 10: `apply_logging_levels()` — 调整 stdlib logging

**Files:**
- Modify: `pybluehost/core/trace_control.py`
- Test: `tests/unit/core/test_trace_control.py`

- [ ] **Step 10.1: Write failing test**

Append to `tests/unit/core/test_trace_control.py`:
```python
def test_apply_logging_levels_sets_layer_logger_to_info():
    import logging

    from pybluehost.core.trace_control import apply_logging_levels, parse_trace_spec

    apply_logging_levels(parse_trace_spec("l2cap"))
    assert logging.getLogger("pybluehost.l2cap").level == logging.INFO


def test_apply_logging_levels_sets_layer_logger_to_debug():
    import logging

    from pybluehost.core.trace_control import apply_logging_levels, parse_trace_spec

    apply_logging_levels(parse_trace_spec("smp=debug"))
    assert logging.getLogger("pybluehost.ble.smp").level == logging.DEBUG


def test_apply_logging_levels_empty_spec_does_not_change_levels():
    import logging

    from pybluehost.core.trace_control import apply_logging_levels, parse_trace_spec

    logger = logging.getLogger("pybluehost.gatt")
    logger.setLevel(logging.WARNING)
    apply_logging_levels(parse_trace_spec(""))
    assert logger.level == logging.WARNING
```

- [ ] **Step 10.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/core/test_trace_control.py -v
```

- [ ] **Step 10.3: Implement `apply_logging_levels`**

Append to `pybluehost/core/trace_control.py`:
```python
import logging

# Maps trace-spec layer names to their stdlib logger names.
_LAYER_LOGGER: dict[str, str] = {
    "hci": "pybluehost.hci",
    "sm": "pybluehost.core.statemachine",
    "transport": "pybluehost.transport",
    "l2cap": "pybluehost.l2cap",
    "att": "pybluehost.ble.att",
    "gatt": "pybluehost.ble.gatt",
    "smp": "pybluehost.ble.smp",
    "sdp": "pybluehost.classic.sdp",
    "rfcomm": "pybluehost.classic.rfcomm",
    "gap": "pybluehost.classic.gap",
}

_LEVEL_TO_LOGGING: dict[str, int] = {
    "info": logging.INFO,
    "debug": logging.DEBUG,
}


def apply_logging_levels(spec: TraceSpec) -> None:
    """Adjust stdlib logger levels per the spec.

    Idempotent: calling with the same spec twice has the same effect.
    Layers not mentioned in the spec are left untouched.
    """
    for layer, level in spec.layers.items():
        logger_name = _LAYER_LOGGER.get(layer)
        if logger_name is None:
            continue  # parse_trace_spec already validated; defensive only
        logging.getLogger(logger_name).setLevel(_LEVEL_TO_LOGGING[level])
```

- [ ] **Step 10.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/core/test_trace_control.py -v
```

- [ ] **Step 10.5: Commit**

```bash
git add pybluehost/core/trace_control.py tests/unit/core/test_trace_control.py
git commit -m "feat(core): apply_logging_levels honors --trace=layer=level"
```

---

## Task 11: `attach_console_sink()` — 把 ConsoleSink 挂到 TraceSystem

**Files:**
- Modify: `pybluehost/core/trace_control.py`
- Test: `tests/unit/core/test_trace_control.py`

- [ ] **Step 11.1: Write failing test**

Append to `tests/unit/core/test_trace_control.py`:
```python
@pytest.mark.asyncio
async def test_attach_console_sink_only_when_hci_layer_enabled():
    import io

    from pybluehost.core.trace import TraceSystem
    from pybluehost.core.trace_control import (
        attach_console_sink,
        parse_trace_spec,
    )

    trace_system = TraceSystem()
    sink = attach_console_sink(parse_trace_spec("hci"), trace_system, stream=io.StringIO())
    assert sink is not None
    assert sink in trace_system._sinks


@pytest.mark.asyncio
async def test_attach_console_sink_returns_none_when_hci_layer_absent():
    import io

    from pybluehost.core.trace import TraceSystem
    from pybluehost.core.trace_control import (
        attach_console_sink,
        parse_trace_spec,
    )

    trace_system = TraceSystem()
    sink = attach_console_sink(parse_trace_spec("l2cap"), trace_system, stream=io.StringIO())
    assert sink is None
    assert trace_system._sinks == []


@pytest.mark.asyncio
async def test_attach_console_sink_passes_full_acl_and_include():
    import io

    from pybluehost.core.trace import TraceSystem
    from pybluehost.core.trace_control import (
        attach_console_sink,
        parse_trace_spec,
    )

    trace_system = TraceSystem()
    sink = attach_console_sink(
        parse_trace_spec("hci,full-acl,include=Number_Of_Completed_Packets"),
        trace_system,
        stream=io.StringIO(),
    )
    assert sink._full_acl is True
    assert "Number_Of_Completed_Packets" in sink._include
```

- [ ] **Step 11.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/core/test_trace_control.py -v
```

- [ ] **Step 11.3: Implement `attach_console_sink`**

Append to `pybluehost/core/trace_control.py`:
```python
def attach_console_sink(
    spec: TraceSpec,
    trace_system,
    *,
    stream=None,
):
    """Attach a ConsoleSink to trace_system if the spec enables the hci layer.

    Returns the new sink (so caller can keep a reference) or None when no
    sink was attached (hci layer absent or stream unavailable).
    """
    from pybluehost.core.trace_console import ConsoleSink

    hci_level = spec.layers.get("hci")
    if hci_level is None:
        return None
    sink = ConsoleSink(
        stream=stream,
        level=hci_level,
        full_acl=spec.full_acl,
        include=set(spec.include),
    )
    trace_system.add_sink(sink)
    return sink


def trace_install(spec: TraceSpec, trace_system, *, stream=None):
    """One-shot install: apply logging levels + attach ConsoleSink."""
    apply_logging_levels(spec)
    return attach_console_sink(spec, trace_system, stream=stream)
```

- [ ] **Step 11.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/core/test_trace_control.py -v
```

- [ ] **Step 11.5: Commit**

```bash
git add pybluehost/core/trace_control.py tests/unit/core/test_trace_control.py
git commit -m "feat(core): attach_console_sink + trace_install"
```

---

## Task 12: 公开导出与 `pybluehost.core.__init__`

**Files:**
- Modify: `pybluehost/core/__init__.py`
- Test: `tests/unit/core/test_trace_control.py`

- [ ] **Step 12.1: Write failing test**

Append to `tests/unit/core/test_trace_control.py`:
```python
def test_public_re_exports():
    from pybluehost.core import (
        ConsoleSink,
        InvalidTraceSpec,
        TraceSpec,
        attach_console_sink,
        parse_trace_spec,
        trace_install,
    )

    assert ConsoleSink.__module__ == "pybluehost.core.trace_console"
    assert callable(parse_trace_spec)
    assert callable(trace_install)
```

- [ ] **Step 12.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/core/test_trace_control.py::test_public_re_exports -v
```

- [ ] **Step 12.3: Add re-exports**

In `pybluehost/core/__init__.py`, add to the existing exports:
```python
from pybluehost.core.trace_console import ConsoleSink
from pybluehost.core.trace_control import (
    InvalidTraceSpec,
    TraceSpec,
    apply_logging_levels,
    attach_console_sink,
    parse_trace_spec,
    trace_install,
)
```

- [ ] **Step 12.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/core/ -q
```

- [ ] **Step 12.5: Commit**

```bash
git add pybluehost/core/__init__.py tests/unit/core/test_trace_control.py
git commit -m "feat(core): re-export trace_console + trace_control public API"
```

---

## Task 13: CLI `--trace` 选项 + 集成

**Files:**
- Modify: `pybluehost/cli/__init__.py`
- Test: `tests/unit/cli/test_main_trace.py`

- [ ] **Step 13.1: Write failing test**

```python
# tests/unit/cli/test_main_trace.py
"""Tests for top-level --trace CLI option."""
from __future__ import annotations

import pytest

from pybluehost.cli import main


def test_main_help_shows_trace_option(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "--trace" in out


def test_main_invalid_trace_spec_exits_nonzero(monkeypatch, capsys):
    monkeypatch.delenv("PYBLUEHOST_TRACE", raising=False)
    rc = main(["--trace=invalid_layer", "tools", "decode", "01030c00"])
    # Should fail before/at decode; CLI returns non-zero (exact code = 2 from
    # argparse error or 4 from explicit pytest.exit-equivalent — accept both).
    assert rc != 0


def test_main_trace_env_var_used_when_no_flag(monkeypatch, capsys):
    monkeypatch.setenv("PYBLUEHOST_TRACE", "")
    rc = main(["tools", "decode", "01030c00"])
    assert rc == 0  # tools decode is offline, no trace impact
```

- [ ] **Step 13.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/cli/test_main_trace.py -v
```

- [ ] **Step 13.3: Add `--trace` to CLI**

In `pybluehost/cli/__init__.py`, in `main()`:
- Add `parser.add_argument("--trace", default=None, help="Trace spec: e.g. 'hci', 'hci=debug,l2cap', '*=debug', 'hci,full-acl'.")`
- After `args = parser.parse_args(argv)`, before dispatch:

```python
    # Resolve trace spec from --trace > env var > empty.
    import os
    from pybluehost.core.trace_control import (
        InvalidTraceSpec,
        apply_logging_levels,
        parse_trace_spec,
    )

    trace_str = args.trace if args.trace is not None else os.environ.get("PYBLUEHOST_TRACE")
    try:
        trace_spec = parse_trace_spec(trace_str)
    except InvalidTraceSpec as exc:
        print(f"Invalid --trace value: {exc}", file=sys.stderr)
        return 4

    # Apply logging levels immediately so layer loggers are configured before
    # any command runs. ConsoleSink is attached per-Stack inside _lifecycle.
    apply_logging_levels(trace_spec)

    # Make trace_spec available to lifecycle helpers (so they can attach the
    # console sink at Stack creation time).
    args._trace_spec = trace_spec
```

In `pybluehost/cli/_lifecycle.py:run_app_command`, after Stack is built, add:
```python
    spec = getattr(args, "_trace_spec", None)
    if spec is not None and not spec.is_empty():
        from pybluehost.core.trace_control import attach_console_sink
        attach_console_sink(spec, stack.trace)
```

- [ ] **Step 13.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/cli/test_main_trace.py -v
uv run --frozen pytest tests/unit/cli/ -q
```

- [ ] **Step 13.5: Commit**

```bash
git add pybluehost/cli/__init__.py pybluehost/cli/_lifecycle.py tests/unit/cli/test_main_trace.py
git commit -m "feat(cli): add --trace top-level option + per-stack ConsoleSink attach"
```

---

## Task 14: pytest `--trace` 选项 + 集成

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/unit/test_pytest_trace.py`

- [ ] **Step 14.1: Write failing test**

```python
# tests/unit/test_pytest_trace.py
"""pytest --trace option registration + propagation."""
from __future__ import annotations

import subprocess
import sys


def test_pytest_help_shows_trace_option():
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "--help"],
        capture_output=True, text=True,
    )
    assert "--trace" in r.stdout


def test_pytest_invalid_trace_exits_nonzero(tmp_path):
    test_file = tmp_path / "test_inline.py"
    test_file.write_text("def test_dummy(): pass\n")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "--trace=invalid_layer", "-q"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "Unknown layer" in out or "Invalid" in out
```

- [ ] **Step 14.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/test_pytest_trace.py -v
```

- [ ] **Step 14.3: Wire pytest `--trace`**

In `tests/conftest.py`:
- Add option registration:
```python
def pytest_addoption(parser: pytest.Parser) -> None:
    # ... existing --transport / --transport-peer / --list-transports ...
    parser.addoption(
        "--trace",
        action="store",
        default=None,
        help="Trace spec for HCI / protocol layer logging (e.g. 'hci=debug,l2cap').",
    )
```

- In `pytest_configure(config)`, after marker registration, before `--list-transports` exit:
```python
    from pybluehost.core.trace_control import (
        InvalidTraceSpec,
        apply_logging_levels,
        parse_trace_spec,
    )
    trace_str = config.getoption("--trace") or os.environ.get("PYBLUEHOST_TRACE")
    try:
        trace_spec = parse_trace_spec(trace_str)
    except InvalidTraceSpec as exc:
        pytest.exit(f"Invalid --trace value: {exc}", returncode=4)
    apply_logging_levels(trace_spec)
    config._pybluehost_trace_spec = trace_spec
```

- In the `stack` fixture (`tests/conftest.py`), after building the Stack, before yield:
```python
    spec = getattr(request.config, "_pybluehost_trace_spec", None)
    if spec is not None and not spec.is_empty():
        from pybluehost.core.trace_control import attach_console_sink
        attach_console_sink(spec, s.trace)
```

(Receive `request` from the fixture signature.)

- [ ] **Step 14.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/test_pytest_trace.py -v
```

- [ ] **Step 14.5: Commit**

```bash
git add tests/conftest.py tests/unit/test_pytest_trace.py
git commit -m "feat(tests): pytest --trace option + per-stack ConsoleSink attach"
```

---

## Task 15: L2CAP layer logger 注入

**Files:**
- Modify: `pybluehost/l2cap/manager.py`
- Modify: `pybluehost/l2cap/signaling.py`
- Test: `tests/unit/l2cap/test_manager_log.py`

- [ ] **Step 15.1: Write failing test**

```python
# tests/unit/l2cap/test_manager_log.py
"""Verify L2CAPManager emits INFO logs for channel lifecycle events."""
from __future__ import annotations

import logging

import pytest

from pybluehost.l2cap.manager import L2CAPManager


@pytest.mark.asyncio
async def test_on_connection_emits_info_log(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.l2cap")
    mgr = L2CAPManager(hci=object())
    await mgr.on_connection(handle=0x40, peer_address=b"\x06\x05\x04\x03\x02\x01", peer_address_type=0)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("handle=0x0040" in m and ("opened" in m or "connection" in m.lower()) for m in msgs)


@pytest.mark.asyncio
async def test_on_disconnection_emits_info_log(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.l2cap")
    mgr = L2CAPManager(hci=object())
    await mgr.on_connection(handle=0x40, peer_address=b"\x06\x05\x04\x03\x02\x01", peer_address_type=0)
    caplog.clear()
    await mgr.on_disconnection(handle=0x40, reason=0x16)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("handle=0x0040" in m and ("disconnect" in m.lower() or "closed" in m.lower()) for m in msgs)
```

- [ ] **Step 15.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/l2cap/test_manager_log.py -v
```

- [ ] **Step 15.3: Add 5 logger calls in `pybluehost/l2cap/manager.py`**

Add at top of file:
```python
import logging

logger = logging.getLogger(__name__)
```

In `on_connection`: at end of method, log
```python
logger.info("L2CAP connection handle=0x%04X peer=%s opened", handle, _addr_repr(peer_address, peer_address_type))
```

In `on_disconnection`: log
```python
logger.info("L2CAP connection handle=0x%04X closed (reason=0x%02X)", handle, reason)
```

In `_handle_classic_connection_request`: when channel admitted, log
```python
logger.info("L2CAP CID=0x%04X PSM=0x%04X opened", channel.local_cid, psm)
```

In `_handle_classic_configure_request`: when configuration completes (in `_complete_classic_config_if_ready`), log
```python
logger.info("L2CAP CID=0x%04X configured (MTU=%d)", channel.local_cid, channel.mtu)
```

In `_on_classic_signaling`: log WARN on configuration reject
```python
logger.warning("L2CAP CID=0x%04X configuration rejected (result=0x%04X)", cid, result)
```

(Implementer: locate the exact branches that handle CONF_RSP with result≠0 to attach the WARN.)

In `pybluehost/l2cap/signaling.py`: add module-level
```python
import logging

logger = logging.getLogger("pybluehost.l2cap.signaling")
```

In each `_decode_signaling_pdu` / `parse_*_pdu` entry point, add:
```python
logger.debug("L2CAP signaling code=0x%02X id=%d len=%d", code, identifier, length)
```

- [ ] **Step 15.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/l2cap/test_manager_log.py tests/unit/l2cap/ -q
```

- [ ] **Step 15.5: Commit**

```bash
git add pybluehost/l2cap/manager.py pybluehost/l2cap/signaling.py tests/unit/l2cap/test_manager_log.py
git commit -m "feat(l2cap): add INFO/WARN/DEBUG logger calls for channel lifecycle"
```

---

## Task 16: ATT layer logger 注入

**Files:**
- Modify: `pybluehost/ble/att.py`
- Test: `tests/unit/ble/test_att_log.py`

- [ ] **Step 16.1: Write failing test**

```python
# tests/unit/ble/test_att_log.py
"""Verify ATT emits INFO/WARN logs at MTU exchange and Error_Response."""
from __future__ import annotations

import logging

import pytest

from pybluehost.ble.att import (
    ATT_Error_Response,
    ATT_Exchange_MTU_Response,
    decode_att_pdu,
)


def test_mtu_exchange_response_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.ble.att")
    pdu = ATT_Exchange_MTU_Response(server_rx_mtu=247)
    pdu.log_received()  # implementer adds this helper or inlines log at call site
    assert any("MTU exchanged" in r.getMessage() and "247" in r.getMessage() for r in caplog.records)


def test_error_response_logs_warn(caplog):
    caplog.set_level(logging.WARNING, logger="pybluehost.ble.att")
    pdu = ATT_Error_Response(request_opcode=0x0A, attribute_handle=0x002A, error_code=0x05)
    pdu.log_received()
    msgs = [r.getMessage() for r in caplog.records]
    assert any("0x002A" in m for m in msgs)
    assert any("Insufficient_Authentication" in m or "0x05" in m for m in msgs)
```

- [ ] **Step 16.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/ble/test_att_log.py -v
```

- [ ] **Step 16.3: Add logger calls in `pybluehost/ble/att.py`**

Top of file:
```python
import logging

logger = logging.getLogger(__name__)
```

For each PDU class with a `log_received(self)` (preferred) helper, OR inline at the dispatch point in any client/server using these PDUs. Implementer chooses ONE pattern; tests above assume the helper pattern. If tests need adjusting to match the chosen pattern, prefer:

```python
class ATT_Exchange_MTU_Response(ATTPdu):
    def log_received(self) -> None:
        logger.info("ATT MTU exchanged: %d", self.server_rx_mtu)


class ATT_Error_Response(ATTPdu):
    _ERROR_NAMES = {
        0x01: "Invalid_Handle",
        0x02: "Read_Not_Permitted",
        0x05: "Insufficient_Authentication",
        # ... extend as needed
    }
    def log_received(self) -> None:
        name = self._ERROR_NAMES.get(self.error_code, f"0x{self.error_code:02X}")
        logger.warning(
            "ATT Error_Response handle=0x%04X error=%s",
            self.attribute_handle, name,
        )
```

For DEBUG: add `logger.debug` in `decode_att_pdu` (or wherever requests are routed) for each `Read_Request`, `Write_Request`, `Read_By_Type_Request` showing handle + length:
```python
logger.debug("ATT request opcode=0x%02X handle=0x%04X len=%d", opcode, handle, len(payload))
```

- [ ] **Step 16.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/ble/test_att_log.py tests/unit/ble/ -q
```

- [ ] **Step 16.5: Commit**

```bash
git add pybluehost/ble/att.py tests/unit/ble/test_att_log.py
git commit -m "feat(att): add MTU/Error_Response/request logger calls"
```

---

## Task 17: GATT layer logger 注入

**Files:**
- Modify: `pybluehost/ble/gatt.py`
- Test: `tests/unit/ble/test_gatt_log.py`

- [ ] **Step 17.1: Write failing test**

```python
# tests/unit/ble/test_gatt_log.py
"""Verify GATT emits INFO logs at service discovery + CCCD subscription."""
from __future__ import annotations

import logging

import pytest


def test_service_discovery_complete_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.ble.gatt")
    from pybluehost.ble.gatt import _log_service_discovery_complete

    _log_service_discovery_complete(handle=0x40, num_services=5)
    assert any("5 services" in r.getMessage() and "0x0040" in r.getMessage() for r in caplog.records)


def test_cccd_subscription_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.ble.gatt")
    from pybluehost.ble.gatt import _log_cccd_subscribed

    _log_cccd_subscribed(handle=0x40, char_handle=0x002A, char_name="Heart_Rate_Measurement")
    msgs = [r.getMessage() for r in caplog.records]
    assert any("0x002A" in m and "Heart_Rate_Measurement" in m for m in msgs)
```

- [ ] **Step 17.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/ble/test_gatt_log.py -v
```

- [ ] **Step 17.3: Add helpers + call sites**

In `pybluehost/ble/gatt.py`:
```python
import logging

logger = logging.getLogger(__name__)


def _log_service_discovery_complete(*, handle: int, num_services: int) -> None:
    logger.info("GATT discovered %d services on handle=0x%04X", num_services, handle)


def _log_cccd_subscribed(*, handle: int, char_handle: int, char_name: str | None) -> None:
    suffix = f" ({char_name})" if char_name else ""
    logger.info("GATT subscribed to handle=0x%04X%s via CCCD", char_handle, suffix)


def _log_notification_received(*, handle: int, char_handle: int, length: int) -> None:
    logger.debug("GATT notification handle=0x%04X char=0x%04X len=%d", handle, char_handle, length)
```

Then call these helpers from the actual GATT client / server discovery / CCCD write / notification reception code paths.

- [ ] **Step 17.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/ble/test_gatt_log.py -v
```

- [ ] **Step 17.5: Commit**

```bash
git add pybluehost/ble/gatt.py tests/unit/ble/test_gatt_log.py
git commit -m "feat(gatt): add service discovery / CCCD / notification logger calls"
```

---

## Task 18: SMP layer logger 注入

**Files:**
- Modify: `pybluehost/ble/smp.py`
- Test: `tests/unit/ble/test_smp_log.py`

- [ ] **Step 18.1: Write failing test**

```python
# tests/unit/ble/test_smp_log.py
"""Verify SMP emits INFO/WARN logs at pairing lifecycle events."""
from __future__ import annotations

import logging


def test_pairing_started_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.ble.smp")
    from pybluehost.ble.smp import _log_pairing_started

    _log_pairing_started(handle=0x40, io_caps="DisplayYesNo", bonding=True, mitm=True)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("DisplayYesNo" in m for m in msgs)


def test_pairing_failed_logs_warn(caplog):
    caplog.set_level(logging.WARNING, logger="pybluehost.ble.smp")
    from pybluehost.ble.smp import _log_pairing_failed

    _log_pairing_failed(handle=0x40, reason=0x05)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("0x05" in m or "Pairing_Not_Supported" in m for m in msgs)


def test_pairing_complete_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.ble.smp")
    from pybluehost.ble.smp import _log_pairing_complete

    _log_pairing_complete(handle=0x40, peer_addr="6E:1A:9C:81:5C:24", ltk_stored=True)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("paired" in m.lower() and "6E:1A:9C:81:5C:24" in m for m in msgs)
```

- [ ] **Step 18.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/ble/test_smp_log.py -v
```

- [ ] **Step 18.3: Add helpers + call sites in `pybluehost/ble/smp.py`**

```python
import logging

logger = logging.getLogger(__name__)

_PAIRING_FAILURE_NAMES: dict[int, str] = {
    0x01: "Passkey_Entry_Failed",
    0x02: "Out_Of_Band",
    0x03: "Authentication_Requirements",
    0x04: "Confirm_Value_Failed",
    0x05: "Pairing_Not_Supported",
    0x06: "Encryption_Key_Size",
    0x07: "Command_Not_Supported",
    0x08: "Unspecified_Reason",
    0x09: "Repeated_Attempts",
}


def _log_pairing_started(*, handle: int, io_caps: str, bonding: bool, mitm: bool) -> None:
    logger.info(
        "SMP pairing started handle=0x%04X io_caps=%s bonding=%s mitm=%s",
        handle, io_caps, "YES" if bonding else "NO", "YES" if mitm else "NO",
    )


def _log_pairing_phase(*, handle: int, phase: str) -> None:
    logger.info("SMP -> %s on handle=0x%04X", phase, handle)


def _log_pairing_complete(*, handle: int, peer_addr: str, ltk_stored: bool) -> None:
    logger.info(
        "SMP paired with %s (handle=0x%04X) ltk_stored=%s",
        peer_addr, handle, "YES" if ltk_stored else "NO",
    )


def _log_pairing_failed(*, handle: int, reason: int) -> None:
    name = _PAIRING_FAILURE_NAMES.get(reason, f"0x{reason:02X}")
    logger.warning("SMP pairing failed handle=0x%04X reason=%s", handle, name)
```

Wire calls to these from the pairing state machine (find pairing-start / phase-transition / pairing-complete / pairing-failed branches).

- [ ] **Step 18.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/ble/test_smp_log.py -v
```

- [ ] **Step 18.5: Commit**

```bash
git add pybluehost/ble/smp.py tests/unit/ble/test_smp_log.py
git commit -m "feat(smp): add pairing lifecycle logger calls"
```

---

## Task 19: HCI Connection 事件 logger 注入

**Files:**
- Modify: `pybluehost/hci/controller.py`
- Test: `tests/unit/hci/test_controller_log.py`

- [ ] **Step 19.1: Write failing test**

```python
# tests/unit/hci/test_controller_log.py
"""Verify HCIController emits INFO logs at LE_Connection_Complete / Disconnection_Complete."""
from __future__ import annotations

import logging


def test_le_connection_complete_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.hci.connection")
    from pybluehost.hci.controller import _log_le_connection_complete

    _log_le_connection_complete(handle=0x40, peer_addr="6E:1A:9C:81:5C:24", role=0, interval_ms=30.0)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("0x0040" in m and "Central" in m for m in msgs)


def test_disconnection_complete_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.hci.connection")
    from pybluehost.hci.controller import _log_disconnection_complete

    _log_disconnection_complete(handle=0x40, reason=0x08)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("Connection_Timeout" in m for m in msgs)
```

- [ ] **Step 19.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/hci/test_controller_log.py -v
```

- [ ] **Step 19.3: Add helpers + wire in `pybluehost/hci/controller.py`**

```python
import logging

connection_logger = logging.getLogger("pybluehost.hci.connection")


def _log_le_connection_complete(*, handle: int, peer_addr: str, role: int, interval_ms: float) -> None:
    from pybluehost.hci.format_fields import format_role
    connection_logger.info(
        "HCI LE_Connection_Complete handle=0x%04X peer=%s role=%s interval=%.1fms",
        handle, peer_addr, format_role(role), interval_ms,
    )


def _log_disconnection_complete(*, handle: int, reason: int) -> None:
    from pybluehost.hci.format_fields import format_status
    connection_logger.info(
        "HCI Disconnection_Complete handle=0x%04X reason=%s",
        handle, format_status(reason),
    )
```

Call from `_handle_event` when the corresponding events arrive (find existing dispatch for LE_Meta subevent 0x01 = LE_Connection_Complete, and event code 0x05 = Disconnection_Complete).

- [ ] **Step 19.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/hci/test_controller_log.py -v
```

- [ ] **Step 19.5: Commit**

```bash
git add pybluehost/hci/controller.py tests/unit/hci/test_controller_log.py
git commit -m "feat(hci): add Connection_Complete / Disconnection_Complete INFO logs"
```

---

## Task 20: Classic SDP logger 注入

**Files:**
- Modify: `pybluehost/classic/sdp.py`
- Test: `tests/unit/classic/test_sdp_log.py`

- [ ] **Step 20.1: Write failing test**

```python
# tests/unit/classic/test_sdp_log.py
"""Verify SDP emits INFO/WARN logs."""
from __future__ import annotations

import logging


def test_service_search_complete_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.classic.sdp")
    from pybluehost.classic.sdp import _log_service_search_complete

    _log_service_search_complete(uuid=0x1101, num_records=3)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("0x1101" in m and "3" in m for m in msgs)


def test_service_search_timeout_logs_warn(caplog):
    caplog.set_level(logging.WARNING, logger="pybluehost.classic.sdp")
    from pybluehost.classic.sdp import _log_service_search_timeout

    _log_service_search_timeout(uuid=0x1101)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("timeout" in m.lower() and "0x1101" in m for m in msgs)
```

- [ ] **Step 20.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/classic/test_sdp_log.py -v
```

- [ ] **Step 20.3: Add helpers + wire in `pybluehost/classic/sdp.py`**

```python
import logging

logger = logging.getLogger(__name__)


def _log_service_search_complete(*, uuid: int, num_records: int) -> None:
    from pybluehost.hci.format_fields import format_uuid16_default
    logger.info(
        "SDP service search complete: %d records matching %s",
        num_records, format_uuid16_default(uuid),
    )


def _log_service_search_timeout(*, uuid: int) -> None:
    from pybluehost.hci.format_fields import format_uuid16_default
    logger.warning("SDP service search timeout for %s", format_uuid16_default(uuid))
```

Call from existing service search complete / timeout paths.

- [ ] **Step 20.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/classic/test_sdp_log.py -v
```

- [ ] **Step 20.5: Commit**

```bash
git add pybluehost/classic/sdp.py tests/unit/classic/test_sdp_log.py
git commit -m "feat(sdp): add service search INFO/WARN logs"
```

---

## Task 21: Classic RFCOMM logger 注入

**Files:**
- Modify: `pybluehost/classic/rfcomm.py`
- Test: `tests/unit/classic/test_rfcomm_log.py`

- [ ] **Step 21.1: Write failing test**

```python
# tests/unit/classic/test_rfcomm_log.py
"""Verify RFCOMM emits INFO/WARN logs."""
from __future__ import annotations

import logging


def test_channel_opened_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.classic.rfcomm")
    from pybluehost.classic.rfcomm import _log_channel_opened

    _log_channel_opened(dlci=0x06, channel=3, mtu=1024)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("DLCI=0x06" in m and "channel 3" in m and "MTU=1024" in m for m in msgs)


def test_channel_disconnect_abnormal_logs_warn(caplog):
    caplog.set_level(logging.WARNING, logger="pybluehost.classic.rfcomm")
    from pybluehost.classic.rfcomm import _log_channel_disconnect_abnormal

    _log_channel_disconnect_abnormal(dlci=0x06, reason="link_loss")
    msgs = [r.getMessage() for r in caplog.records]
    assert any("DLCI=0x06" in m and "link_loss" in m for m in msgs)
```

- [ ] **Step 21.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/classic/test_rfcomm_log.py -v
```

- [ ] **Step 21.3: Add helpers + wire in `pybluehost/classic/rfcomm.py`**

```python
import logging

logger = logging.getLogger(__name__)


def _log_channel_opened(*, dlci: int, channel: int, mtu: int) -> None:
    logger.info("RFCOMM DLCI=0x%02X (channel %d) opened MTU=%d", dlci, channel, mtu)


def _log_channel_closed(*, dlci: int) -> None:
    logger.info("RFCOMM DLCI=0x%02X closed", dlci)


def _log_channel_disconnect_abnormal(*, dlci: int, reason: str) -> None:
    logger.warning("RFCOMM DLCI=0x%02X abnormal disconnect: %s", dlci, reason)
```

Call from existing channel open / close / abnormal-disconnect paths.

- [ ] **Step 21.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/classic/test_rfcomm_log.py -v
```

- [ ] **Step 21.5: Commit**

```bash
git add pybluehost/classic/rfcomm.py tests/unit/classic/test_rfcomm_log.py
git commit -m "feat(rfcomm): add channel lifecycle logger calls"
```

---

## Task 22: Classic GAP + SSP logger 注入

**Files:**
- Modify: `pybluehost/classic/gap.py`
- Modify: `pybluehost/ble/security.py`
- Test: `tests/unit/classic/test_gap_log.py`

- [ ] **Step 22.1: Write failing test**

```python
# tests/unit/classic/test_gap_log.py
"""Verify Classic GAP + SSP emit INFO logs."""
from __future__ import annotations

import logging


def test_inquiry_started_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.classic.gap")
    from pybluehost.classic.gap import _log_inquiry_started

    _log_inquiry_started(duration_ms=10240)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("Inquiry started" in m for m in msgs)


def test_inquiry_complete_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.classic.gap")
    from pybluehost.classic.gap import _log_inquiry_complete

    _log_inquiry_complete(num_devices=4)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("4 devices" in m for m in msgs)


def test_ssp_user_confirmation_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.ble.smp")
    from pybluehost.ble.security import _log_ssp_user_confirmation

    _log_ssp_user_confirmation(handle=0x40, numeric_value=123456)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("123456" in m and "0x0040" in m for m in msgs)
```

- [ ] **Step 22.2: Run test (FAIL expected)**

```bash
uv run --frozen pytest tests/unit/classic/test_gap_log.py -v
```

- [ ] **Step 22.3: Add helpers + wire**

In `pybluehost/classic/gap.py`:
```python
import logging

logger = logging.getLogger(__name__)


def _log_inquiry_started(*, duration_ms: int) -> None:
    logger.info("Classic Inquiry started (duration=%dms)", duration_ms)


def _log_inquiry_complete(*, num_devices: int) -> None:
    logger.info("Classic Inquiry complete: found %d devices", num_devices)
```

In `pybluehost/ble/security.py`:
```python
import logging

ssp_logger = logging.getLogger("pybluehost.ble.smp")


def _log_ssp_user_confirmation(*, handle: int, numeric_value: int) -> None:
    ssp_logger.info("SSP user_confirmation handle=0x%04X numeric=%06d", handle, numeric_value)


def _log_ssp_phase(*, handle: int, phase: str) -> None:
    ssp_logger.info("SSP phase=%s on handle=0x%04X", phase, handle)
```

Wire calls from existing inquiry start/complete + SSP confirmation handler paths.

- [ ] **Step 22.4: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/unit/classic/test_gap_log.py -v
```

- [ ] **Step 22.5: Commit**

```bash
git add pybluehost/classic/gap.py pybluehost/ble/security.py tests/unit/classic/test_gap_log.py
git commit -m "feat(classic): add Classic GAP inquiry + SSP logger calls"
```

---

## Task 23: 集成 E2E 测试

**Files:**
- Create: `tests/integration/test_trace_console_e2e.py`

- [ ] **Step 23.1: Write the E2E tests**

```python
# tests/integration/test_trace_console_e2e.py
"""End-to-end: launch CLI in a subprocess and inspect stderr trace output."""
from __future__ import annotations

import subprocess
import sys


def _cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "pybluehost", *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)


def test_trace_hci_emits_structured_lines_on_virtual():
    r = _cli("--trace=hci", "tools", "decode", "01030c00")
    # tools decode is offline (no Stack), so no HCI trace expected, but the
    # CLI must accept --trace and exit 0.
    assert r.returncode == 0


def test_trace_invalid_layer_exits_nonzero():
    r = _cli("--trace=invalid_layer", "tools", "decode", "01030c00")
    assert r.returncode != 0
    assert "Unknown layer" in (r.stdout + r.stderr)


def test_trace_env_var_works(monkeypatch=None):
    import os
    env = os.environ.copy()
    env["PYBLUEHOST_TRACE"] = "hci"
    r = _cli("tools", "decode", "01030c00", env=env)
    assert r.returncode == 0
```

- [ ] **Step 23.2: Run test (PASS expected)**

```bash
uv run --frozen pytest tests/integration/test_trace_console_e2e.py -v
```

- [ ] **Step 23.3: Commit**

```bash
git add tests/integration/test_trace_console_e2e.py
git commit -m "test(integration): subprocess CLI verification of --trace"
```

---

## Task 24: README + AGENTS.md 文档

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] **Step 24.1: Add README "Trace / Debug" section**

Append to `README.md` under a new "调试与日志" section:

```markdown
## 调试与日志

PyBlueHost 内置结构化 trace 系统，可在不影响默认零开销的前提下打开任意层的实时彩色日志。

### CLI 用法

```bash
# 打开 HCI 层 trace（彩色单行,自动 TTY 探测,自动展开错误事件）
pybluehost --trace=hci app gatt-browser --transport=virtual

# 多层独立级别
pybluehost --trace=hci=debug,l2cap app gatt-browser --transport=usb

# 全部层 debug（最详细）
pybluehost --trace=*=debug app gatt-browser --transport=virtual

# ACL 不截断（默认 24 字节）
pybluehost --trace=hci,full-acl app spp-echo --transport=usb

# 把通常被静音的事件加回来
pybluehost --trace=hci,include=Number_Of_Completed_Packets app ble-scan --transport=usb
```

### 环境变量

`PYBLUEHOST_TRACE=hci pybluehost ...` —— 与 `--trace=...` 等价；CLI flag 优先。

### 颜色控制

- 默认：stderr 是 TTY 时上色；管道 / 文件自动关
- `NO_COLOR=1` 强制关
- `FORCE_COLOR=1` 强制开

### Layer 名字

`hci`, `sm`, `transport`, `l2cap`, `att`, `gatt`, `smp`, `sdp`, `rfcomm`, `gap`
```

- [ ] **Step 24.2: Add AGENTS.md "调试 trace" snippet**

Append to `AGENTS.md` "常用测试命令" 段落:
```markdown
# Trace / debug
uv run --frozen pytest tests/ --trace=hci --transport=virtual    # pytest 内打开 HCI trace
uv run --frozen pytest tests/ --trace=*=debug --transport=virtual # 全部层 debug
PYBLUEHOST_TRACE=hci=debug uv run --frozen pytest tests/         # 通过环境变量
```

- [ ] **Step 24.3: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: document --trace pytest + CLI options"
```

---

## Task 25: 最终验证 + STATUS.md 更新

**Files:**
- Modify: `docs/superpowers/STATUS.md`

- [ ] **Step 25.1: Run full suite**

```bash
uv run --frozen pytest tests/ -q --transport=virtual --cov=pybluehost --cov-fail-under=85
```

Expected: PASS, coverage ≥ 85%.

- [ ] **Step 25.2: Manual verification of acceptance criteria**

```bash
# §13.1 default no new output
pybluehost app gatt-browser --transport=virtual 2>&1 | head

# §13.2 --trace=hci shows colored single-line
pybluehost --trace=hci app gatt-browser --transport=virtual 2>&1 | head -20

# §13.3 --trace=hci=debug shows multi-line expansion
pybluehost --trace=hci=debug app gatt-browser --transport=virtual 2>&1 | head -30

# §13.4 NO_COLOR=1 strips colors
NO_COLOR=1 pybluehost --trace=hci app gatt-browser --transport=virtual 2>&1 | head | cat -A

# §13.7 --trace=l2cap=debug INFO + DEBUG visible
pybluehost --trace=l2cap=debug app gatt-browser --transport=virtual 2>&1 | grep l2cap

# §13.8 invalid layer exits nonzero with clear message
pybluehost --trace=garbage tools decode 01030c00; echo "exit=$?"

# §13.9 pytest --trace works
uv run --frozen pytest tests/integration/test_stack_fixture.py --trace=hci --transport=virtual -v
```

- [ ] **Step 25.3: Update `docs/superpowers/STATUS.md`**

Add a row to the "Plan 总览" table for "Trace / Log Structured Output" with status ✅, and append a detail block:

```markdown
### ✅ Trace / Log Structured Output
- 设计文档：`docs/superpowers/specs/trace-log-system-design.md`
- 实施计划：`docs/superpowers/plans/trace-log-system.md`
- 完成时间：YYYY-MM-DD
- 关键变化：
  - 新增 `pybluehost/hci/format.py` + `format_fields.py`：HCI packet 结构化人读字符串，含 SIG DB 查表
  - 新增 `pybluehost/core/trace_console.py`：ANSI 彩色 / TTY 探测 / anti-flood / ACL 截断
  - 新增 `pybluehost/core/trace_control.py`：`--trace` / `PYBLUEHOST_TRACE` spec 解析与 install
  - `HCIController._emit_trace` 现在挂载解码后的 HCIPacket 到 `TraceEvent.decoded`
  - 协议层 logger 注入（L2CAP / ATT / GATT / SMP / HCI Conn / SDP / RFCOMM / Classic GAP+SSP），约 40 个 INFO/WARN/DEBUG 决策点
  - CLI 顶层 `--trace` 选项；pytest `--trace` 选项
```

- [ ] **Step 25.4: Final commit**

```bash
git add docs/superpowers/STATUS.md docs/superpowers/plans/trace-log-system.md
git commit -m "docs(progress): mark trace/log system plan complete"
```

---

## 常见问题 / Troubleshooting

（执行过程中发现的问题在这里追加，格式见 `CLAUDE.md` 的"遇到问题时必须记录"。）
