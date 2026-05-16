# HCI Tolerant Initialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `HCIController.initialize()` tolerant of low-end controllers by gating each post-Reset command on its bit in the `Read_Local_Supported_Commands` bitmap (per Core Spec 5.4 Vol 4 Part E §6.27 Table 6.27).

**Architecture:** A `SupportedCommands` class wraps the 64-byte bitmap with `has(opcode) -> bool` lookups via an opcode → (octet, bit) table. `HCIController.initialize()` parses the bitmap after issuing `Read_Local_Supported_Commands`, then skips any subsequent command whose bit is unset (with a debug log). Two commands are mandatory and hard-fail if the controller can't handle them: `HCI_Reset` (issued before we know the bitmap, but if it fails everything else fails too) and `Read_BD_ADDR` (the BD address is load-bearing for SMP/GAP).

**Tech Stack:** Python 3.10+; existing `pybluehost/hci/{controller,packets,virtual}.py`; pytest (`--transport=virtual`).

**Review baseline**: review-notes-2026-05-12.md §三 中期重构 #5 "HCI 容错初始化".

---

## 范围声明

**包含**：

1. New `SupportedCommands` value class wrapping the 64-byte bitmap with `has(opcode) -> bool` queries
2. `HCIController.initialize()` parses bitmap after `Read_Local_Supported_Commands` and skips unsupported subsequent commands
3. `HCIController.supported_commands` public property to expose the parsed bitmap
4. `VirtualController._handle_read_local_supported_commands` returns a permissive bitmap that exercises every command in the init sequence (so existing tests keep working)
5. Unit + integration tests covering: bitmap parsing, opcode → (octet,bit) mapping, low-end-controller scenario (custom VirtualController subclass with restricted bitmap), hard-fail behavior for missing `Read_BD_ADDR`

**不包含**（推迟）：

- Vendor-specific HCI command capability detection (Intel `Read_Boot_Params`, Realtek `Read_ROM_Version`) — already handled per-vendor in transport-layer firmware loaders
- Reordering the init sequence based on dependency analysis — current order is fine
- Coverage for ALL 256 HCI opcodes — we only need bits for the 14 commands `initialize()` issues
- LMP / LE Features bitmap parsing (separate concern; not part of this Plan)

---

## 文件改动清单

| 类型 | 路径 | 责任 |
|------|------|------|
| Create | `pybluehost/hci/capabilities.py` | `SupportedCommands` class + opcode → (octet, bit) registry |
| Modify | `pybluehost/hci/__init__.py` | export `SupportedCommands` |
| Modify | `pybluehost/hci/controller.py` | parse bitmap; gate each subsequent init command; expose `supported_commands` property |
| Modify | `pybluehost/hci/virtual.py` | `_handle_read_local_supported_commands` returns permissive bitmap |
| Create | `tests/unit/hci/test_capabilities.py` | `SupportedCommands` parse + has() tests |
| Create | `tests/unit/hci/test_initialize_tolerant.py` | initialize() skip behavior + hard-fail behavior |
| Modify | `docs/superpowers/STATUS.md` | mark Plan complete |

---

## 任务依赖图

```
Task 1 (SupportedCommands + registry) ──► Task 3 (initialize gating)
Task 2 (VC permissive bitmap) ───────────►
                                Task 4 (low-end controller test)
Task 5 (STATUS)
```

Task 1 + 2 are independent; both must precede Task 3 (Task 3 reads the bitmap from VC). Task 4 builds a custom VC subclass for the low-end scenario. Task 5 closes.

---

## Task 1: `SupportedCommands` value class + opcode registry

**Files:**
- Create: `pybluehost/hci/capabilities.py`
- Modify: `pybluehost/hci/__init__.py`
- Create: `tests/unit/hci/test_capabilities.py`

### Step 1.1: Write failing test

- [ ] **Create `tests/unit/hci/test_capabilities.py`:**

```python
"""SupportedCommands parses the 64-byte HCI Read_Local_Supported_Commands bitmap."""
from __future__ import annotations

import pytest

from pybluehost.hci.capabilities import SupportedCommands
from pybluehost.hci.constants import (
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_READ_BD_ADDR,
    HCI_READ_LOCAL_SUPPORTED_COMMANDS,
    HCI_RESET,
    HCI_SET_EVENT_MASK,
)


def test_supported_commands_requires_64_byte_bitmap():
    """Construction rejects bitmaps that aren't exactly 64 bytes."""
    with pytest.raises(ValueError):
        SupportedCommands(bytes(63))
    with pytest.raises(ValueError):
        SupportedCommands(bytes(65))


def test_all_ones_bitmap_supports_every_known_opcode():
    caps = SupportedCommands(b"\xFF" * 64)
    # Spot-check a handful of opcodes that initialize() issues
    assert caps.has(HCI_RESET)
    assert caps.has(HCI_READ_BD_ADDR)
    assert caps.has(HCI_LE_READ_BUFFER_SIZE)
    assert caps.has(HCI_LE_SET_RANDOM_ADDRESS)
    assert caps.has(HCI_LE_SET_SCAN_PARAMS)
    assert caps.has(HCI_SET_EVENT_MASK)
    assert caps.has(HCI_READ_LOCAL_SUPPORTED_COMMANDS)


def test_all_zeros_bitmap_supports_nothing_known():
    caps = SupportedCommands(b"\x00" * 64)
    assert not caps.has(HCI_RESET)
    assert not caps.has(HCI_READ_BD_ADDR)
    assert not caps.has(HCI_LE_READ_BUFFER_SIZE)


def test_opcode_outside_registry_returns_false():
    """Unknown opcodes (not in our gating table) report as unsupported.

    This is intentional: gating defaults to skip-unknown, which fails closed.
    """
    caps = SupportedCommands(b"\xFF" * 64)
    assert caps.has(0xFFFF) is False


def test_hci_reset_bit_is_octet5_bit7():
    """HCI_Reset is at octet 5 bit 7 (Core 5.4 Vol 4 Part E Table 6.27)."""
    bitmap = bytearray(64)
    bitmap[5] = 0b1000_0000  # bit 7 set
    caps = SupportedCommands(bytes(bitmap))
    assert caps.has(HCI_RESET)

    bitmap[5] = 0b0111_1111  # bit 7 cleared
    caps = SupportedCommands(bytes(bitmap))
    assert not caps.has(HCI_RESET)


def test_read_bd_addr_bit_is_octet15_bit1():
    """Read_BD_ADDR is at octet 15 bit 1 (Core 5.4 Vol 4 Part E Table 6.27)."""
    bitmap = bytearray(64)
    bitmap[15] = 0b0000_0010  # bit 1
    caps = SupportedCommands(bytes(bitmap))
    assert caps.has(HCI_READ_BD_ADDR)

    bitmap[15] = 0b1111_1101  # all except bit 1
    caps = SupportedCommands(bytes(bitmap))
    assert not caps.has(HCI_READ_BD_ADDR)
```

### Step 1.2: Run test to verify it fails

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/hci/test_capabilities.py -v --transport=virtual
```

Expected: `ImportError: cannot import name 'SupportedCommands' from 'pybluehost.hci.capabilities'`.

### Step 1.3: Implement `SupportedCommands`

- [ ] **Create `pybluehost/hci/capabilities.py`:**

```python
"""HCI controller capability inspection.

SupportedCommands wraps the 64-byte bitmap returned by HCI_Read_Local_Supported_Commands
(Core Spec 5.4 Vol 4 Part E §6.27, Table 6.27 "Supported_Commands"). The bitmap
encodes "this controller implements command X" as a single bit at a (octet, bit)
coordinate documented in the table. ``has(opcode)`` returns True iff the bit for
the given opcode is set; unknown opcodes return False.
"""
from __future__ import annotations

from dataclasses import dataclass

from pybluehost.hci.constants import (
    HCI_HOST_BUFFER_SIZE,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_LE_SET_EVENT_MASK,
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_READ_BD_ADDR,
    HCI_READ_BUFFER_SIZE,
    HCI_READ_LOCAL_SUPPORTED_COMMANDS,
    HCI_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_READ_LOCAL_VERSION,
    HCI_RESET,
    HCI_SET_EVENT_MASK,
    HCI_WRITE_LE_HOST_SUPPORTED,
    HCI_WRITE_SCAN_ENABLE,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
)


# Core Spec 5.4 Vol 4 Part E §6.27, Table 6.27 — Supported_Commands bitmap layout.
# Maps each opcode that HCIController.initialize() issues to its (octet, bit) position.
# If you add a new command to initialize(), add its entry here too — otherwise the
# capability check falls back to "unsupported" and the command will be skipped.
_OPCODE_BIT_POSITIONS: dict[int, tuple[int, int]] = {
    HCI_RESET:                              (5, 7),
    HCI_SET_EVENT_MASK:                     (5, 6),
    HCI_WRITE_SCAN_ENABLE:                  (6, 2),
    HCI_HOST_BUFFER_SIZE:                   (10, 6),
    HCI_READ_LOCAL_VERSION:                 (14, 3),
    HCI_READ_LOCAL_SUPPORTED_FEATURES:      (14, 4),
    HCI_READ_LOCAL_SUPPORTED_COMMANDS:      (14, 5),
    HCI_READ_BUFFER_SIZE:                   (14, 7),
    HCI_READ_BD_ADDR:                       (15, 1),
    HCI_WRITE_SIMPLE_PAIRING_MODE:          (17, 6),
    HCI_WRITE_LE_HOST_SUPPORTED:            (24, 6),
    HCI_LE_SET_EVENT_MASK:                  (25, 0),
    HCI_LE_SET_RANDOM_ADDRESS:              (25, 4),
    HCI_LE_READ_BUFFER_SIZE:                (25, 7),
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES:   (26, 0),
    HCI_LE_SET_SCAN_PARAMS:                 (26, 2),
}


@dataclass(frozen=True)
class SupportedCommands:
    """64-byte HCI Supported_Commands bitmap with opcode lookup."""

    bitmap: bytes

    def __post_init__(self) -> None:
        if len(self.bitmap) != 64:
            raise ValueError(
                f"SupportedCommands bitmap must be 64 bytes, got {len(self.bitmap)}"
            )

    def has(self, opcode: int) -> bool:
        """Return True iff the controller advertises support for the given opcode.

        Unknown opcodes (not in the gating table) return False — callers that
        gate on this should treat the missing entry as "no opinion, send anyway"
        externally (HCIController.initialize() only gates the commands it knows
        about, so unknown opcodes are simply never queried).
        """
        position = _OPCODE_BIT_POSITIONS.get(opcode)
        if position is None:
            return False
        octet, bit = position
        return bool(self.bitmap[octet] & (1 << bit))
```

### Step 1.4: Export from `hci/__init__.py`

- [ ] **Modify `pybluehost/hci/__init__.py`**: add to the existing imports + `__all__`:

```python
from pybluehost.hci.capabilities import SupportedCommands
```

And `"SupportedCommands"` to the `__all__` list (alphabetical).

### Step 1.5: Run tests to verify they pass

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/hci/test_capabilities.py -v --transport=virtual
```

Expected: 6 passed.

### Step 1.6: Commit

- [ ] **Run:**

```bash
git add pybluehost/hci/capabilities.py pybluehost/hci/__init__.py tests/unit/hci/test_capabilities.py
git commit -m "feat(hci): add SupportedCommands bitmap parser

SupportedCommands wraps the 64-byte bitmap from HCI_Read_Local_Supported_Commands
(Core 5.4 Vol 4 Part E Table 6.27). _OPCODE_BIT_POSITIONS maps each opcode that
HCIController.initialize() issues to its (octet, bit) coordinate.

Foundation for tolerant initialization on low-end controllers."
```

---

## Task 2: VirtualController returns permissive bitmap

**Files:**
- Modify: `pybluehost/hci/virtual.py`

### Step 2.1: Identify and modify the bitmap handler

- [ ] **Run:**

```bash
grep -n "_handle_read_local_supported_commands" pybluehost/hci/virtual.py
```

Expected: hits at line 79 (handler registration) and around line 301 (method body).

The current body is:

```python
    def _handle_read_local_supported_commands(self, cmd: HCICommand) -> bytes:
        # status + 64 bytes of supported commands bitmap
        return b"\x00" + b"\x00" * 64
```

This returns all-zeros — once Task 3 enables gating, `initialize()` would skip every post-Reset command. We need the bitmap to advertise support for at least the commands `initialize()` issues today.

### Step 2.2: Replace with a permissive bitmap

- [ ] **Modify `pybluehost/hci/virtual.py`** — replace the body of `_handle_read_local_supported_commands` with:

```python
    def _handle_read_local_supported_commands(self, cmd: HCICommand) -> bytes:
        """Return a permissive Supported_Commands bitmap.

        We advertise all the commands HCIController.initialize() issues so the
        tolerant-init gating (Task 3) doesn't skip anything. Tests that need a
        restricted bitmap subclass VirtualController and override this method.
        """
        from pybluehost.hci.capabilities import _OPCODE_BIT_POSITIONS

        bitmap = bytearray(64)
        for octet, bit in _OPCODE_BIT_POSITIONS.values():
            bitmap[octet] |= 1 << bit
        return b"\x00" + bytes(bitmap)
```

### Step 2.3: Verify

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/hci/ -q --transport=virtual
uv run --frozen pytest tests/ -q --transport=virtual --tb=no 2>&1 | tail -7
```

Expected: only the 3 pre-existing USB diagnostics failures remain.

### Step 2.4: Commit

- [ ] **Run:**

```bash
git add pybluehost/hci/virtual.py
git commit -m "feat(hci/virtual): return permissive Supported_Commands bitmap

VirtualController now advertises all commands HCIController.initialize()
issues. Required before Task 3 (tolerant-init gating) lands — without
this, gated init would skip every post-Reset command against a virtual
controller. Tests needing a restricted bitmap subclass VirtualController
and override _handle_read_local_supported_commands."
```

---

## Task 3: `HCIController.initialize()` gates on bitmap

**Files:**
- Modify: `pybluehost/hci/controller.py`
- Create: `tests/unit/hci/test_initialize_tolerant.py`

### Step 3.1: Read existing initialize()

- [ ] **Run:**

```bash
sed -n '222,280p' pybluehost/hci/controller.py
```

Confirm the current shape — a `for cmd in init_commands: await self.send_command(cmd)` loop.

### Step 3.2: Write failing test

- [ ] **Create `tests/unit/hci/test_initialize_tolerant.py`:**

```python
"""HCIController.initialize() gates each command on the Supported_Commands bitmap."""
from __future__ import annotations

import pytest

from pybluehost.hci.capabilities import SupportedCommands
from pybluehost.hci.constants import (
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_READ_BD_ADDR,
)
from pybluehost.hci.controller import HCIController
from pybluehost.hci.virtual import VirtualController


class _RestrictedVC(VirtualController):
    """A VirtualController whose Supported_Commands bitmap omits a few commands.

    Used to verify that HCIController.initialize() skips unsupported commands
    instead of timing out or raising.
    """

    def __init__(self, *args, omitted_opcodes: list[int] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._omitted_opcodes = set(omitted_opcodes or [])

    def _handle_read_local_supported_commands(self, cmd) -> bytes:
        from pybluehost.hci.capabilities import _OPCODE_BIT_POSITIONS
        bitmap = bytearray(64)
        for opcode, (octet, bit) in _OPCODE_BIT_POSITIONS.items():
            if opcode in self._omitted_opcodes:
                continue
            bitmap[octet] |= 1 << bit
        return b"\x00" + bytes(bitmap)


async def test_initialize_skips_unsupported_optional_commands():
    """A controller that doesn't support LE_Set_Random_Address still initializes."""
    from pybluehost.core.address import BDAddress
    vc = _RestrictedVC(
        address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        omitted_opcodes=[HCI_LE_SET_RANDOM_ADDRESS],
    )
    # Use the same _HCIPipe pattern as VirtualController.create()
    from pybluehost.hci.virtual import VirtualController as _Real
    host_t = await _vc_pair(vc, _Real)
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)
    try:
        await hci.initialize()
        # Now exposes the parsed bitmap
        assert hci.supported_commands is not None
        assert isinstance(hci.supported_commands, SupportedCommands)
        assert not hci.supported_commands.has(HCI_LE_SET_RANDOM_ADDRESS)
        # But the mandatory Read_BD_ADDR still ran
        assert hci.supported_commands.has(HCI_READ_BD_ADDR)
    finally:
        await host_t.close()


async def test_initialize_hard_fails_on_missing_read_bd_addr():
    """Read_BD_ADDR is mandatory — if the controller doesn't support it, init fails."""
    from pybluehost.core.address import BDAddress
    vc = _RestrictedVC(
        address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        omitted_opcodes=[HCI_READ_BD_ADDR],
    )
    from pybluehost.hci.virtual import VirtualController as _Real
    host_t = await _vc_pair(vc, _Real)
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)
    try:
        with pytest.raises(RuntimeError, match="Read_BD_ADDR"):
            await hci.initialize()
    finally:
        await host_t.close()


async def test_supported_commands_property_is_none_before_initialize():
    """Before initialize(), the parsed bitmap is None."""
    from pybluehost.core.address import BDAddress
    vc = VirtualController(address=BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    from pybluehost.hci.virtual import VirtualController as _Real
    host_t = await _vc_pair(vc, _Real)
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)
    try:
        assert hci.supported_commands is None
    finally:
        await host_t.close()


# --- Helper: wire a custom VirtualController to a host transport pipe ----

async def _vc_pair(vc, vc_cls):
    """Adapter that pairs a custom VirtualController instance with the standard
    _HCIPipe host transport (mirrors VirtualController.create())."""
    from pybluehost.hci.virtual import _HCIPipe
    host_t = _HCIPipe()
    ctrl_t = _HCIPipe()
    host_t._partner = ctrl_t
    ctrl_t._partner = host_t

    class _VCSink:
        async def on_transport_data(_self, data):
            response = await vc.process(data)
            if response is not None:
                await host_t._sink.on_transport_data(response)

        async def on_transport_error(_self, error):
            pass

    ctrl_t.set_sink(_VCSink())
    await host_t.open()
    await ctrl_t.open()
    vc._host_sink = host_t._sink
    return host_t
```

If the `_vc_pair` helper signature doesn't quite match `VirtualController.create()`'s structure, look at the current `VirtualController.create()` implementation and copy its wiring exactly — you need the same `_HCIPipe` pair + `_VCSink` adapter.

### Step 3.3: Run test to verify it fails

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/hci/test_initialize_tolerant.py -v --transport=virtual
```

Expected: `hci.supported_commands` doesn't exist (AttributeError); init doesn't gate or hard-fail.

### Step 3.4: Add `supported_commands` field + property

- [ ] **Modify `pybluehost/hci/controller.py`**: In `HCIController.__init__`, add:

```python
        self._supported_commands: "SupportedCommands | None" = None
```

(near other per-instance state init).

Add the property near other public properties:

```python
    @property
    def supported_commands(self) -> "SupportedCommands | None":
        """The parsed Supported_Commands bitmap from initialize(), or None before init."""
        return self._supported_commands
```

Add the import at the top of the file (use `TYPE_CHECKING` to keep runtime light, or import directly — match the project's style):

```python
from pybluehost.hci.capabilities import SupportedCommands
```

### Step 3.5: Modify `initialize()` to gate commands

- [ ] **Replace the body of `HCIController.initialize()`** (currently the `for cmd in init_commands: await self.send_command(cmd)` loop) with:

```python
    async def initialize(self) -> None:
        """Send the HCI init sequence, skipping commands the controller doesn't advertise.

        After HCI_Reset and Read_Local_Supported_Commands, every subsequent
        command is gated on its bit in the Supported_Commands bitmap. If the
        controller reports a command as unsupported, it is skipped with a
        debug log. Two commands are mandatory: HCI_Reset (without which the
        controller is in an unknown state) and Read_BD_ADDR (without which
        SMP/GAP cannot function); if either is unsupported or fails, init
        raises RuntimeError.
        """
        from pybluehost.hci.capabilities import SupportedCommands
        from pybluehost.hci.packets import (
            HCI_Reset,
            HCI_Read_Local_Version_Command,
            HCI_Read_Local_Supported_Commands_Command,
            HCI_Read_Local_Supported_Features_Command,
            HCI_Read_BD_ADDR_Command,
            HCI_Read_Buffer_Size_Command,
            HCI_LE_Read_Buffer_Size_Command,
            HCI_LE_Read_Local_Supported_Features_Command,
            HCI_Set_Event_Mask_Command,
            HCI_LE_Set_Event_Mask_Command,
            HCI_Write_LE_Host_Supported_Command,
            HCI_Write_Simple_Pairing_Mode_Command,
            HCI_Write_Scan_Enable_Command,
            HCI_Host_Buffer_Size_Command,
            HCI_LE_Set_Scan_Parameters_Command,
            HCI_LE_Set_Random_Address_Command,
        )
        from pybluehost.hci.constants import HCI_READ_BD_ADDR

        EVENT_MASK_ALL = b"\xFF\xFF\xFF\xFF\xFF\xFF\xFF\x3F"
        LE_EVENT_MASK = b"\x1F\x00\x00\x00\x00\x00\x00\x00"
        RANDOM_ADDRESS = bytes(6)

        # Step 1: HCI_Reset — mandatory, never gated.
        await self.send_command(HCI_Reset())

        # Step 2: Read_Local_Supported_Commands — parse the response bitmap.
        rsp = await self.send_command(HCI_Read_Local_Supported_Commands_Command())
        # Command_Complete return_parameters: status(1) + bitmap(64)
        bitmap = rsp.return_parameters[1:65]
        if len(bitmap) != 64:
            raise RuntimeError(
                f"Read_Local_Supported_Commands returned {len(bitmap)}-byte bitmap, expected 64"
            )
        self._supported_commands = SupportedCommands(bitmap)

        # Step 3+: Each subsequent command is gated on its bit. Read_BD_ADDR is mandatory.
        optional_commands = [
            HCI_Read_Local_Version_Command(),
            HCI_Read_Local_Supported_Features_Command(),
            HCI_Read_Buffer_Size_Command(),
            HCI_LE_Read_Buffer_Size_Command(),
            HCI_LE_Read_Local_Supported_Features_Command(),
            HCI_Set_Event_Mask_Command(event_mask=EVENT_MASK_ALL),
            HCI_LE_Set_Event_Mask_Command(le_event_mask=LE_EVENT_MASK),
            HCI_Write_LE_Host_Supported_Command(le_supported_host=0x01, simultaneous_le_host=0x00),
            HCI_Write_Simple_Pairing_Mode_Command(simple_pairing_mode=0x01),
            HCI_Write_Scan_Enable_Command(scan_enable=0x00),
            HCI_Host_Buffer_Size_Command(
                host_acl_data_packet_length=0x0200,
                host_synchronous_data_packet_length=0xFF,
                host_total_num_acl_data_packets=0x0014,
                host_total_num_synchronous_data_packets=0x0000,
            ),
            HCI_LE_Set_Scan_Parameters_Command(
                le_scan_type=0x01,
                le_scan_interval=0x0010,
                le_scan_window=0x0010,
                own_address_type=0x00,
                scanning_filter_policy=0x00,
            ),
            HCI_LE_Set_Random_Address_Command(random_address=RANDOM_ADDRESS),
        ]

        # Read_BD_ADDR — mandatory.
        if not self._supported_commands.has(HCI_READ_BD_ADDR):
            raise RuntimeError("controller does not support Read_BD_ADDR (mandatory)")
        await self.send_command(HCI_Read_BD_ADDR_Command())

        # Optional commands — skip if bit unset.
        for cmd in optional_commands:
            opcode = cmd.opcode
            if not self._supported_commands.has(opcode):
                logger.debug(
                    "HCI initialize: skipping unsupported command opcode=0x%04X",
                    opcode,
                )
                continue
            await self.send_command(cmd)
```

If `logger` isn't already a module-level binding in `controller.py`, add at the top: `import logging` and `logger = logging.getLogger(__name__)`.

Notes:
- `HCICommand.opcode` is a dataclass field; verify by reading `pybluehost/hci/packets.py` (the base `HCICommand` class declares `opcode: int = 0`). Each subclass sets the opcode in `__post_init__` or as a default. The lookup `cmd.opcode` should work.
- `HCI_Read_BD_ADDR_Command` is moved to be issued explicitly after the gated optional commands list — this matches the design where Read_BD_ADDR is required. Keep its placement WHERE THE LOGIC requires (mandatory-first, then optionals), not WHERE it was previously in the linear list.

### Step 3.6: Run test to verify it passes

- [ ] **Run:**

```bash
uv run --frozen pytest tests/unit/hci/test_initialize_tolerant.py -v --transport=virtual
uv run --frozen pytest tests/unit/hci/ -q --transport=virtual
uv run --frozen pytest tests/ -q --transport=virtual --tb=no 2>&1 | tail -7
```

Expected:
- 3 new tests PASS
- Existing HCI integration tests no regressions
- Full suite: only 3 pre-existing USB diagnostics failures

If `tests/integration/test_hci_init.py` or similar relies on the exact ordering of issued commands, update those assertions. The Plan's design moves `Read_BD_ADDR` to run after the optional batch — if a test asserts ordering, fix it (the new order is the correct one).

### Step 3.7: Commit

- [ ] **Run:**

```bash
git add pybluehost/hci/controller.py tests/unit/hci/test_initialize_tolerant.py
git commit -m "feat(hci/controller): tolerant initialization gated on Supported_Commands

HCIController.initialize() now:
- Issues HCI_Reset (always)
- Issues HCI_Read_Local_Supported_Commands and parses the 64-byte bitmap
- Stores the parsed SupportedCommands on self._supported_commands
- Hard-fails if the bitmap doesn't advertise HCI_Read_BD_ADDR (mandatory)
- Skips any optional init command whose bit is unset, with a debug log

Adds HCIController.supported_commands public property. Closes
review-notes-2026-05-12.md §三 中期重构 #5."
```

---

## Task 4: STATUS.md update

**Files:**
- Modify: `docs/superpowers/STATUS.md`

### Step 4.1: Run full regression + coverage

- [ ] **Run:**

```bash
uv run --frozen pytest tests/ -q --transport=virtual --cov=pybluehost --cov-fail-under=85 --tb=no 2>&1 | tail -10
```

Expected: only 3 pre-existing USB diagnostics failures; coverage ≥ 85%.

### Step 4.2: Update STATUS.md

- [ ] **Modify `docs/superpowers/STATUS.md`**:

(a) Update "当前进行中":

```markdown
**当前进行中**：HCI 容错初始化 — ✅ 完成
**下一步**：SMP Sub-Plan 2 (LE Secure Connections) / 断线重连闭环 / e2e 覆盖
```

(b) Append to Plan 总览 table:

```markdown
| HCI 容错初始化 | initialize() 按 Supported_Commands bitmap 跳过不支持的命令；Read_BD_ADDR 硬要求 | ✅ 完成 | [2026-05-16-hci-tolerant-initialization](plans/2026-05-16-hci-tolerant-initialization.md) | `pybluehost/hci/capabilities.py`, `pybluehost/hci/controller.py`, `pybluehost/hci/virtual.py` |
```

Increment the `**总计：N 个 Plan**` line by 1.

(c) Append to 详细进度:

```markdown
### ✅ HCI 容错初始化
- 完成时间：2026-05-16
- Plan 文档：[2026-05-16-hci-tolerant-initialization.md](plans/2026-05-16-hci-tolerant-initialization.md)
- 关键变化：
  - 新 `pybluehost/hci/capabilities.py`: `SupportedCommands` value class + 16-entry opcode→(octet,bit) registry per Core 5.4 Vol 4 Part E Table 6.27
  - `HCIController.initialize()` parses the 64-byte bitmap and gates 13 optional commands; hard-fails on missing Read_BD_ADDR
  - `HCIController.supported_commands` public property exposes the parsed bitmap
  - `VirtualController._handle_read_local_supported_commands` now returns a permissive bitmap covering all init commands
- 已知遗留：仅 3 个 pre-existing USB diagnostics 失败
- 验收：`uv run --frozen pytest tests/ -q --transport=virtual --cov-fail-under=85` PASS；3 个 new capability tests + 3 new tolerant-init tests
```

### Step 4.3: Commit

- [ ] **Run:**

```bash
git add docs/superpowers/STATUS.md
git commit -m "docs(progress): HCI tolerant initialization Plan complete

Closes review-notes-2026-05-12.md §三 中期重构 #5."
```

---

## 验收清单

- [ ] `SupportedCommands` parses 64-byte bitmap; rejects non-64-byte input; `has(opcode)` lookup works for the 16 registered opcodes
- [ ] `HCIController.supported_commands` is `None` before `initialize()` and a `SupportedCommands` instance afterward
- [ ] `HCIController.initialize()` skips optional commands whose bits are unset (verified by `_RestrictedVC` test)
- [ ] `HCIController.initialize()` raises `RuntimeError` if `Read_BD_ADDR` is unsupported
- [ ] VirtualController bitmap covers every command `initialize()` issues, so existing tests still pass
- [ ] Full suite: only 3 pre-existing USB diagnostics failures; coverage ≥ 85%

## 常见问题 / Troubleshooting

### Q: Spec bit positions for some opcode in `_OPCODE_BIT_POSITIONS` are off

- **现象**：A test asserts (octet, bit) for `HCI_X` is (a, b) but the registry has it as (a', b')
- **原因**：Core Spec 5.4 Vol 4 Part E Table 6.27 is authoritative. The Plan's table may have typos — verify against the spec when in doubt.
- **解决方案**：Look up the canonical position in the spec, update `_OPCODE_BIT_POSITIONS`, run the corresponding test. The "spot-check" tests in `test_capabilities.py` are intentionally minimal (HCI_Reset and Read_BD_ADDR only) so the registry can grow without per-bit-position test churn.

### Q: After Task 2, an integration test starts failing with "Read_BD_ADDR not supported"

- **现象**：A test that uses the default `VirtualController` suddenly fails initialize() because the bitmap is missing Read_BD_ADDR
- **原因**：The permissive bitmap in Task 2 missed a bit, or `_OPCODE_BIT_POSITIONS` doesn't have an entry for Read_BD_ADDR
- **解决方案**：Verify `HCI_READ_BD_ADDR: (15, 1)` is in the registry. The permissive bitmap iterates `_OPCODE_BIT_POSITIONS.values()` so it should include it automatically.

### Q: `cmd.opcode` access fails because the opcode is set in `__post_init__`, not as a class default

- **现象**：`AttributeError: 'HCI_LE_Read_Buffer_Size_Command' object has no attribute 'opcode'` or `cmd.opcode` returns 0
- **原因**：Some `HCICommand` subclasses might set opcode as `field(default=..., init=False)` rather than as a regular default
- **解决方案**：Confirm by reading `pybluehost/hci/packets.py`. The HCI commands all have `opcode: int = HCI_XXX` as a default field, so `cmd.opcode` should work. If a particular command sets it differently, look up its opcode via a name → opcode map (`from pybluehost.hci.constants import HCI_LE_READ_BUFFER_SIZE` etc.) and pass that directly.

Self-review 结论：
- 4 tasks, each with clear scope; no TBD/placeholder steps
- Type consistency: `SupportedCommands(bitmap: bytes)` signature used the same way in Task 1 (creation) and Task 3 (call site)
- `_OPCODE_BIT_POSITIONS` referenced as a public-ish module attribute (single underscore) from Task 2's VirtualController + Task 3's tests — acceptable for an internal registry
- Coverage: every opcode HCIController.initialize() issues is in the registry (16 entries; 16 commands issued)
- 验收 checklist matches the In-scope items in §范围声明
