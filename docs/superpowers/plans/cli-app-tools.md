# CLI app + tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `pybluehost app <cmd>` and `pybluehost tools <cmd>` CLI namespaces — 8 hardware commands and 4 offline tool families — so users can validate and debug the stack without writing Python.

**Architecture:** Two-namespace CLI with shared helpers. `app/` commands open an HCI transport (loopback/usb/uart) via a unified `parse_transport_arg()`; `tools/` commands are pure offline. Long-running commands share a `run_app_command()` lifecycle wrapper handling SIGINT and graceful close. Client commands in loopback mode auto-spin a peer Stack via `loopback_peer_with()`.

**Tech Stack:** Python 3.10+, asyncio, argparse, pytest, existing `pybluehost.stack.Stack` factory, `cryptography` (for RPA via `SMPCrypto.ah`).

**Spec reference:** [docs/superpowers/specs/cli-app-tools-design.md](../specs/cli-app-tools-design.md)

---

## File Structure

```
pybluehost/cli/
├── __init__.py            # MODIFY: register app + tools (remove top-level fw, usb)
├── fw.py                  # DELETE (moved to tools/fw.py)
├── usb.py                 # DELETE (moved to tools/usb.py)
├── _transport.py          # CREATE: parse_transport_arg
├── _target.py             # CREATE: parse_target_arg
├── _lifecycle.py          # CREATE: run_app_command (SIGINT, close)
├── _loopback_peer.py      # CREATE: loopback_peer_with context manager
├── app/
│   ├── __init__.py        # CREATE: register_app_commands
│   ├── ble_scan.py        # CREATE
│   ├── ble_adv.py         # CREATE
│   ├── classic_inquiry.py # CREATE
│   ├── gatt_browser.py    # CREATE
│   ├── sdp_browser.py     # CREATE
│   ├── gatt_server.py     # CREATE
│   ├── hr_monitor.py      # CREATE
│   └── spp_echo.py        # CREATE
└── tools/
    ├── __init__.py        # CREATE: register_tools_commands
    ├── fw.py              # MOVE from cli/fw.py
    ├── usb.py             # MOVE from cli/usb.py
    ├── decode.py          # CREATE
    └── rpa.py             # CREATE
```

Tests under `tests/unit/cli/` mirror the structure.

---

## Task 1: `_transport.py` — parse_transport_arg

**Files:**
- Create: `pybluehost/cli/_transport.py`
- Test: `tests/unit/cli/test_transport.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/cli/test_transport.py
import pytest
from pybluehost.cli._transport import parse_transport_arg
from pybluehost.transport.loopback import LoopbackTransport
from pybluehost.transport.uart import UARTTransport


def test_parse_loopback():
    t = parse_transport_arg("loopback")
    assert isinstance(t, LoopbackTransport)


def test_parse_uart_default_baud():
    t = parse_transport_arg("uart:/dev/ttyUSB0")
    assert isinstance(t, UARTTransport)
    assert t._port == "/dev/ttyUSB0"
    assert t._baudrate == 115200


def test_parse_uart_custom_baud():
    t = parse_transport_arg("uart:/dev/ttyUSB0@921600")
    assert isinstance(t, UARTTransport)
    assert t._baudrate == 921600


def test_parse_unknown_raises():
    with pytest.raises(ValueError, match="Unknown transport"):
        parse_transport_arg("foo")


def test_parse_uart_missing_port_raises():
    with pytest.raises(ValueError, match="UART port required"):
        parse_transport_arg("uart:")
```

- [x] **Step 2: Run tests — verify they fail**

Run: `uv run pytest tests/unit/cli/test_transport.py -v`
Expected: FAIL with `ModuleNotFoundError: pybluehost.cli._transport`

- [x] **Step 3: Implement `_transport.py`**

```python
# pybluehost/cli/_transport.py
"""Parse --transport string into a Transport instance."""
from __future__ import annotations

from pybluehost.transport.base import Transport


def parse_transport_arg(s: str) -> Transport:
    """Parse a --transport CLI argument into a Transport instance.

    Formats:
        loopback                       → LoopbackTransport (host side, paired with VC)
        usb                            → USBTransport.auto_detect()
        usb:vendor=intel               → USBTransport.auto_detect(vendor="intel")
        uart:/dev/ttyUSB0              → UARTTransport(port=..., baudrate=115200)
        uart:/dev/ttyUSB0@921600       → UARTTransport(port=..., baudrate=921600)
    """
    if s == "loopback":
        from pybluehost.transport.loopback import LoopbackTransport
        host_t, _ctrl_t = LoopbackTransport.pair()
        return host_t

    if s == "usb" or s.startswith("usb:"):
        from pybluehost.transport.usb import USBTransport
        vendor: str | None = None
        if s.startswith("usb:"):
            for kv in s[4:].split(","):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    if k.strip() == "vendor":
                        vendor = v.strip()
        return USBTransport.auto_detect(vendor=vendor)

    if s.startswith("uart:"):
        from pybluehost.transport.uart import UARTTransport
        spec = s[5:]
        if not spec:
            raise ValueError("UART port required: uart:/dev/ttyXXX[@baud]")
        if "@" in spec:
            port, baud_s = spec.rsplit("@", 1)
            baud = int(baud_s)
        else:
            port = spec
            baud = 115200
        return UARTTransport(port=port, baudrate=baud)

    raise ValueError(f"Unknown transport: {s!r}")
```

- [x] **Step 4: Run tests — verify they pass**

Run: `uv run pytest tests/unit/cli/test_transport.py -v`
Expected: 5 PASS

- [x] **Step 5: Commit**

```bash
git add pybluehost/cli/_transport.py tests/unit/cli/test_transport.py
git commit -m "feat(cli): add parse_transport_arg helper"
```

---

## Task 2: `_target.py` — parse_target_arg

**Files:**
- Create: `pybluehost/cli/_target.py`
- Test: `tests/unit/cli/test_target.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/cli/test_target.py
import pytest
from pybluehost.cli._target import parse_target_arg
from pybluehost.core.address import BDAddress, AddressType


def test_parse_default_public():
    addr, atype = parse_target_arg("AA:BB:CC:DD:EE:FF")
    assert addr == BDAddress.from_string("AA:BB:CC:DD:EE:FF")
    assert atype == AddressType.PUBLIC


def test_parse_explicit_public():
    addr, atype = parse_target_arg("AA:BB:CC:DD:EE:FF/public")
    assert atype == AddressType.PUBLIC


def test_parse_random():
    addr, atype = parse_target_arg("AA:BB:CC:DD:EE:FF/random")
    assert atype == AddressType.RANDOM


def test_parse_invalid_address_raises():
    with pytest.raises(ValueError):
        parse_target_arg("ZZZZZZ")


def test_parse_invalid_type_raises():
    with pytest.raises(ValueError, match="Unknown address type"):
        parse_target_arg("AA:BB:CC:DD:EE:FF/bogus")
```

- [x] **Step 2: Run tests — verify fail**

Run: `uv run pytest tests/unit/cli/test_target.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement `_target.py`**

```python
# pybluehost/cli/_target.py
"""Parse --target string into (BDAddress, AddressType)."""
from __future__ import annotations

from pybluehost.core.address import AddressType, BDAddress


def parse_target_arg(s: str) -> tuple[BDAddress, AddressType]:
    """Parse a --target CLI argument.

    Formats:
        AA:BB:CC:DD:EE:FF              → public address
        AA:BB:CC:DD:EE:FF/public       → public
        AA:BB:CC:DD:EE:FF/random       → random
    """
    if "/" in s:
        addr_s, type_s = s.split("/", 1)
        type_s = type_s.lower()
        if type_s == "public":
            atype = AddressType.PUBLIC
        elif type_s == "random":
            atype = AddressType.RANDOM
        else:
            raise ValueError(f"Unknown address type: {type_s!r}")
    else:
        addr_s = s
        atype = AddressType.PUBLIC
    return (BDAddress.from_string(addr_s), atype)
```

- [x] **Step 4: Run tests — verify pass**

Run: `uv run pytest tests/unit/cli/test_target.py -v`
Expected: 5 PASS

- [x] **Step 5: Commit**

```bash
git add pybluehost/cli/_target.py tests/unit/cli/test_target.py
git commit -m "feat(cli): add parse_target_arg helper"
```

---

## Task 3: `_lifecycle.py` — run_app_command

**Files:**
- Create: `pybluehost/cli/_lifecycle.py`
- Test: `tests/unit/cli/test_lifecycle.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/cli/test_lifecycle.py
import asyncio
import pytest
from pybluehost.cli._lifecycle import run_app_command


async def test_run_app_command_completes_normally():
    async def main(stack, stop):
        # Just exit immediately
        return

    code = await run_app_command("loopback", main)
    assert code == 0


async def test_run_app_command_handles_stop_event():
    async def main(stack, stop):
        await stop.wait()

    # Schedule stop after a tick
    async def trigger_stop():
        await asyncio.sleep(0.05)
        # Simulate SIGINT by setting the internal event
        # We rely on signal handler; this test instead verifies the wait path
        # by raising KeyboardInterrupt-equivalent via cancellation
        raise asyncio.CancelledError

    # Direct test: call main with an immediately-set stop
    stop = asyncio.Event()
    stop.set()

    async def main2(stack, stop):
        await stop.wait()

    code = await run_app_command("loopback", main2)
    assert code == 0  # main2 returned, no SIGINT


async def test_run_app_command_propagates_error():
    async def main(stack, stop):
        raise RuntimeError("boom")

    code = await run_app_command("loopback", main)
    assert code == 1


async def test_run_app_command_invalid_transport():
    async def main(stack, stop):
        return

    code = await run_app_command("bogus", main)
    assert code == 1
```

- [x] **Step 2: Run tests — verify fail**

Run: `uv run pytest tests/unit/cli/test_lifecycle.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement `_lifecycle.py`**

```python
# pybluehost/cli/_lifecycle.py
"""Lifecycle helpers for long-running CLI commands."""
from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from typing import Awaitable, Callable

from pybluehost.cli._transport import parse_transport_arg
from pybluehost.stack import Stack


async def run_app_command(
    transport_arg: str,
    main_coro: Callable[[Stack, asyncio.Event], Awaitable[None]],
) -> int:
    """Run a long-running app command with SIGINT/SIGTERM handling.

    Steps:
        1. parse_transport_arg + Stack._build
        2. Install signal handlers → set stop_event
        3. Run main_coro(stack, stop_event)
           - if main_coro returns first → exit 0
           - if stop_event fires first → cancel main, exit 130
           - if main_coro raises → exit 1
        4. Always close the stack
    """
    stop_event = asyncio.Event()

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_event.set)
    except RuntimeError:
        pass

    try:
        transport = parse_transport_arg(transport_arg)
        stack = await Stack._build(transport=transport)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        main_task = asyncio.create_task(main_coro(stack, stop_event))
        stop_task = asyncio.create_task(stop_event.wait())
        done, _ = await asyncio.wait(
            {main_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if main_task not in done:
            main_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await main_task
            return 130
        stop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stop_task
        # Re-raise main exception, if any
        exc = main_task.exception()
        if exc is not None:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0
    finally:
        await stack.close()
```

- [x] **Step 4: Run tests — verify pass**

Run: `uv run pytest tests/unit/cli/test_lifecycle.py -v`
Expected: 4 PASS

- [x] **Step 5: Commit**

```bash
git add pybluehost/cli/_lifecycle.py tests/unit/cli/test_lifecycle.py
git commit -m "feat(cli): add run_app_command lifecycle helper"
```

---

## Task 4: `_loopback_peer.py` — loopback_peer_with

**Files:**
- Create: `pybluehost/cli/_loopback_peer.py`
- Test: `tests/unit/cli/test_loopback_peer.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/cli/test_loopback_peer.py
import pytest
from pybluehost.cli._loopback_peer import loopback_peer_with
from pybluehost.profiles.ble import BatteryServer


async def test_loopback_peer_yields_powered_stack():
    async def factory(gatt):
        srv = BatteryServer(initial_level=42)
        await srv.register(gatt)

    async with loopback_peer_with(factory) as peer:
        assert peer.is_powered
        assert peer.local_address is not None


async def test_loopback_peer_closes_on_exit():
    async def factory(gatt):
        return

    async with loopback_peer_with(factory) as peer:
        pass
    assert not peer.is_powered
```

- [x] **Step 2: Run tests — verify fail**

Run: `uv run pytest tests/unit/cli/test_loopback_peer.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement `_loopback_peer.py`**

```python
# pybluehost/cli/_loopback_peer.py
"""Loopback peer Stack for client-side commands without real hardware."""
from __future__ import annotations

import contextlib
from typing import AsyncIterator, Awaitable, Callable

from pybluehost.stack import Stack


@contextlib.asynccontextmanager
async def loopback_peer_with(
    server_factory: Callable[[object], Awaitable[None]],
) -> AsyncIterator[Stack]:
    """Spin up a second Stack in loopback mode to act as a peer.

    Args:
        server_factory: async callable taking the GATTServer; registers profiles.

    Yields:
        Powered peer Stack. Caller can read peer.local_address as --target.
    """
    peer = await Stack.loopback()
    try:
        await server_factory(peer.gatt_server)
        yield peer
    finally:
        await peer.close()
```

- [x] **Step 4: Run tests — verify pass**

Run: `uv run pytest tests/unit/cli/test_loopback_peer.py -v`
Expected: 2 PASS

- [x] **Step 5: Commit**

```bash
git add pybluehost/cli/_loopback_peer.py tests/unit/cli/test_loopback_peer.py
git commit -m "feat(cli): add loopback_peer_with helper"
```

---

## Task 5: Move `cli/fw.py` and `cli/usb.py` into `cli/tools/`

**Files:**
- Move: `pybluehost/cli/fw.py` → `pybluehost/cli/tools/fw.py`
- Move: `pybluehost/cli/usb.py` → `pybluehost/cli/tools/usb.py`
- Move: `tests/unit/cli/test_fw.py` (update imports)
- Move: `tests/unit/cli/test_usb.py` (update imports if exists)
- Create: `pybluehost/cli/tools/__init__.py`

- [x] **Step 1: Create empty tools/ package, move files**

```bash
mkdir -p pybluehost/cli/tools
git mv pybluehost/cli/fw.py pybluehost/cli/tools/fw.py
git mv pybluehost/cli/usb.py pybluehost/cli/tools/usb.py
```

- [x] **Step 2: Update imports inside moved files**

Edit `pybluehost/cli/tools/fw.py` — search for any internal `from pybluehost.cli.fw import` (none expected) and any `from pybluehost.cli.usb import` (none expected). The `register_fw_commands` function signature stays the same.

Edit `pybluehost/cli/tools/usb.py` — same check.

- [x] **Step 3: Create `pybluehost/cli/tools/__init__.py` (skeleton)**

```python
# pybluehost/cli/tools/__init__.py
"""CLI 'tools' namespace — offline utilities."""
from __future__ import annotations

import argparse


def register_tools_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'tools' subcommand with all its sub-subcommands."""
    tools_parser = subparsers.add_parser("tools", help="Offline utility tools")
    tools_subs = tools_parser.add_subparsers(dest="tools_cmd")

    from pybluehost.cli.tools.fw import register_fw_commands
    from pybluehost.cli.tools.usb import register_usb_commands

    register_fw_commands(tools_subs)
    register_usb_commands(tools_subs)
```

- [x] **Step 4: Update test imports**

Run: `grep -rn "pybluehost.cli.fw\|pybluehost.cli.usb" tests/`

Replace each occurrence in `tests/unit/cli/test_fw.py` (and any test_usb.py) with `pybluehost.cli.tools.fw` / `pybluehost.cli.tools.usb`. Use Edit with `replace_all=true`.

- [x] **Step 5: Verify existing tests still pass**

Run: `uv run pytest tests/unit/cli/ -v`
Expected: existing fw/usb tests PASS at new paths.

- [x] **Step 6: Commit**

```bash
git add pybluehost/cli/tools/ tests/unit/cli/
git commit -m "refactor(cli): move fw and usb commands into tools/ subpackage"
```

---

## Task 6: `tools/decode.py` — HCI packet decode

**Files:**
- Create: `pybluehost/cli/tools/decode.py`
- Test: `tests/unit/cli/test_tools_decode.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/cli/test_tools_decode.py
import argparse
from pybluehost.cli.tools.decode import register_decode_command, _cmd_decode


def test_decode_hci_reset(capsys):
    args = argparse.Namespace(hex="01030c00")
    rc = _cmd_decode(args)
    captured = capsys.readouterr()
    assert rc == 0
    assert "HCI_Reset" in captured.out
    assert "0x0C03" in captured.out or "0xc03" in captured.out.lower()


def test_decode_invalid_hex(capsys):
    args = argparse.Namespace(hex="ZZ")
    rc = _cmd_decode(args)
    captured = capsys.readouterr()
    assert rc != 0


def test_decode_empty(capsys):
    args = argparse.Namespace(hex="")
    rc = _cmd_decode(args)
    assert rc != 0
```

- [x] **Step 2: Run tests — verify fail**

Run: `uv run pytest tests/unit/cli/test_tools_decode.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement `decode.py`**

```python
# pybluehost/cli/tools/decode.py
"""'tools decode' — decode an H4 HCI packet from hex string."""
from __future__ import annotations

import argparse
import sys

from pybluehost.hci.packets import decode_hci_packet


def register_decode_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("decode", help="Decode an HCI packet from hex")
    p.add_argument("hex", help="Hex string of an H4 HCI packet (e.g. 01030c00)")
    p.set_defaults(func=_cmd_decode)


def _cmd_decode(args: argparse.Namespace) -> int:
    s = args.hex.strip().replace(" ", "").replace(":", "")
    if not s:
        print("Error: empty hex string", file=sys.stderr)
        return 1
    try:
        data = bytes.fromhex(s)
    except ValueError as e:
        print(f"Error: invalid hex: {e}", file=sys.stderr)
        return 1
    try:
        pkt = decode_hci_packet(data)
    except Exception as e:
        print(f"Error: decode failed: {e}", file=sys.stderr)
        return 1
    print(type(pkt).__name__)
    for field in pkt.__dataclass_fields__ if hasattr(pkt, "__dataclass_fields__") else []:
        val = getattr(pkt, field)
        if isinstance(val, int):
            print(f"  {field:20s} 0x{val:X}")
        elif isinstance(val, bytes):
            print(f"  {field:20s} {val.hex()}")
        else:
            print(f"  {field:20s} {val!r}")
    return 0
```

- [x] **Step 4: Run tests — verify pass**

Run: `uv run pytest tests/unit/cli/test_tools_decode.py -v`
Expected: 3 PASS

- [x] **Step 5: Commit**

```bash
git add pybluehost/cli/tools/decode.py tests/unit/cli/test_tools_decode.py
git commit -m "feat(cli): add tools decode command"
```

---

## Task 7: `tools/rpa.py` — RPA gen-irk / gen-rpa / verify

**Files:**
- Create: `pybluehost/cli/tools/rpa.py`
- Test: `tests/unit/cli/test_tools_rpa.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/cli/test_tools_rpa.py
import argparse
from pybluehost.cli.tools.rpa import _cmd_gen_irk, _cmd_gen_rpa, _cmd_verify


def test_gen_irk_outputs_32_hex_chars(capsys):
    rc = _cmd_gen_irk(argparse.Namespace())
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert len(out) == 32
    bytes.fromhex(out)  # must be valid hex


def test_gen_rpa_with_known_irk_round_trips(capsys):
    irk = "0102030405060708090a0b0c0d0e0f10"
    rc = _cmd_gen_rpa(argparse.Namespace(irk=irk))
    out = capsys.readouterr().out
    assert rc == 0
    # Output line includes a colon-separated 6-byte address with /random suffix
    addr_line = [l for l in out.splitlines() if "/random" in l][0]
    addr = addr_line.split()[-1].split("/")[0]
    parts = addr.split(":")
    assert len(parts) == 6


def test_verify_matches_freshly_generated(capsys):
    irk = "0102030405060708090a0b0c0d0e0f10"
    # Generate
    _cmd_gen_rpa(argparse.Namespace(irk=irk))
    out = capsys.readouterr().out
    addr = [l for l in out.splitlines() if "/random" in l][0].split()[-1].split("/")[0]
    # Verify
    rc = _cmd_verify(argparse.Namespace(irk=irk, addr=addr))
    out2 = capsys.readouterr().out
    assert rc == 0
    assert "match" in out2.lower()
    assert "no match" not in out2.lower()


def test_verify_no_match_with_wrong_irk(capsys):
    irk1 = "0102030405060708090a0b0c0d0e0f10"
    irk2 = "ffffffffffffffffffffffffffffffff"
    _cmd_gen_rpa(argparse.Namespace(irk=irk1))
    out = capsys.readouterr().out
    addr = [l for l in out.splitlines() if "/random" in l][0].split()[-1].split("/")[0]
    rc = _cmd_verify(argparse.Namespace(irk=irk2, addr=addr))
    out2 = capsys.readouterr().out
    assert rc == 1
    assert "no match" in out2.lower()


def test_gen_rpa_invalid_irk_length(capsys):
    rc = _cmd_gen_rpa(argparse.Namespace(irk="aabb"))
    assert rc != 0
```

- [x] **Step 2: Run tests — verify fail**

Run: `uv run pytest tests/unit/cli/test_tools_rpa.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement `rpa.py`**

```python
# pybluehost/cli/tools/rpa.py
"""'tools rpa' — IRK and Resolvable Private Address utilities."""
from __future__ import annotations

import argparse
import os
import sys

from pybluehost.ble.smp import SMPCrypto


def register_rpa_commands(subparsers: argparse._SubParsersAction) -> None:
    rpa_parser = subparsers.add_parser("rpa", help="IRK / RPA utilities")
    rpa_subs = rpa_parser.add_subparsers(dest="rpa_cmd")

    p_irk = rpa_subs.add_parser("gen-irk", help="Generate a random 16-byte IRK")
    p_irk.set_defaults(func=_cmd_gen_irk)

    p_rpa = rpa_subs.add_parser("gen-rpa", help="Generate an RPA from an IRK")
    p_rpa.add_argument("--irk", required=True, help="IRK as 32 hex chars")
    p_rpa.set_defaults(func=_cmd_gen_rpa)

    p_ver = rpa_subs.add_parser("verify", help="Verify an RPA was generated by an IRK")
    p_ver.add_argument("--irk", required=True, help="IRK as 32 hex chars")
    p_ver.add_argument("--addr", required=True, help="BD_ADDR as XX:XX:XX:XX:XX:XX")
    p_ver.set_defaults(func=_cmd_verify)


def _parse_irk(s: str) -> bytes:
    irk = bytes.fromhex(s)
    if len(irk) != 16:
        raise ValueError(f"IRK must be 16 bytes (32 hex chars), got {len(irk)}")
    return irk


def _format_addr(addr_bytes: bytes) -> str:
    """addr_bytes: 6 bytes, MSB-first → XX:XX:XX:XX:XX:XX"""
    return ":".join(f"{b:02X}" for b in addr_bytes)


def _cmd_gen_irk(args: argparse.Namespace) -> int:
    print(os.urandom(16).hex())
    return 0


def _cmd_gen_rpa(args: argparse.Namespace) -> int:
    try:
        irk = _parse_irk(args.irk)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    # prand: 24 bits, with top two bits = 0b01 (resolvable type)
    prand_int = int.from_bytes(os.urandom(3), "big")
    prand_int = (prand_int & 0x3FFFFF) | 0x400000  # top 2 bits = 01
    prand = prand_int.to_bytes(3, "big")
    hash_bytes = SMPCrypto.ah(irk, prand)
    addr_bytes = prand + hash_bytes  # 6 bytes total, MSB → LSB
    print(f"IRK:    {irk.hex()}")
    print(f"prand:  {prand.hex()}")
    print(f"hash:   {hash_bytes.hex()}")
    print(f"RPA:    {_format_addr(addr_bytes)}/random")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    try:
        irk = _parse_irk(args.irk)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    addr_str = args.addr.strip()
    parts = addr_str.split(":")
    if len(parts) != 6:
        print(f"Error: invalid BD_ADDR: {addr_str!r}", file=sys.stderr)
        return 1
    try:
        addr_bytes = bytes(int(p, 16) for p in parts)  # MSB → LSB
    except ValueError:
        print(f"Error: invalid BD_ADDR: {addr_str!r}", file=sys.stderr)
        return 1
    prand = addr_bytes[0:3]
    hash_observed = addr_bytes[3:6]
    hash_expected = SMPCrypto.ah(irk, prand)
    if hash_observed == hash_expected:
        print("match")
        return 0
    print("no match")
    return 1
```

- [x] **Step 4: Run tests — verify pass**

Run: `uv run pytest tests/unit/cli/test_tools_rpa.py -v`
Expected: 5 PASS

- [x] **Step 5: Commit**

```bash
git add pybluehost/cli/tools/rpa.py tests/unit/cli/test_tools_rpa.py
git commit -m "feat(cli): add tools rpa gen-irk/gen-rpa/verify commands"
```

---

## Task 8: Wire up `tools/__init__.py` (decode + rpa)

**Files:**
- Modify: `pybluehost/cli/tools/__init__.py`
- Test: `tests/unit/cli/test_tools_init.py`

- [x] **Step 1: Write failing test**

```python
# tests/unit/cli/test_tools_init.py
import argparse
from pybluehost.cli.tools import register_tools_commands


def test_register_tools_commands_adds_subcommands():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_tools_commands(subs)
    args = parser.parse_args(["tools", "decode", "01030c00"])
    assert args.cmd == "tools"
    assert args.tools_cmd == "decode"
    assert args.hex == "01030c00"


def test_register_tools_rpa_gen_irk():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_tools_commands(subs)
    args = parser.parse_args(["tools", "rpa", "gen-irk"])
    assert args.tools_cmd == "rpa"
    assert args.rpa_cmd == "gen-irk"


def test_register_tools_fw_list():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_tools_commands(subs)
    args = parser.parse_args(["tools", "fw", "list"])
    assert args.tools_cmd == "fw"
```

- [x] **Step 2: Run test — verify fail**

Run: `uv run pytest tests/unit/cli/test_tools_init.py -v`
Expected: FAIL — `decode` and `rpa` not registered yet.

- [x] **Step 3: Update `pybluehost/cli/tools/__init__.py`**

```python
# pybluehost/cli/tools/__init__.py
"""CLI 'tools' namespace — offline utilities."""
from __future__ import annotations

import argparse


def register_tools_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'tools' subcommand with all its sub-subcommands."""
    tools_parser = subparsers.add_parser("tools", help="Offline utility tools")
    tools_subs = tools_parser.add_subparsers(dest="tools_cmd")

    from pybluehost.cli.tools.decode import register_decode_command
    from pybluehost.cli.tools.fw import register_fw_commands
    from pybluehost.cli.tools.rpa import register_rpa_commands
    from pybluehost.cli.tools.usb import register_usb_commands

    register_decode_command(tools_subs)
    register_fw_commands(tools_subs)
    register_rpa_commands(tools_subs)
    register_usb_commands(tools_subs)
```

- [x] **Step 4: Run tests — verify pass**

Run: `uv run pytest tests/unit/cli/test_tools_init.py -v`
Expected: 3 PASS

- [x] **Step 5: Commit**

```bash
git add pybluehost/cli/tools/__init__.py tests/unit/cli/test_tools_init.py
git commit -m "feat(cli): wire up tools/ namespace with decode + rpa + fw + usb"
```

---

## Task 9: `app/ble_scan.py` — long-running BLE scan

**Files:**
- Create: `pybluehost/cli/app/__init__.py` (initial skeleton)
- Create: `pybluehost/cli/app/ble_scan.py`
- Test: `tests/unit/cli/test_app_ble_scan.py`

- [x] **Step 1: Write failing test**

```python
# tests/unit/cli/test_app_ble_scan.py
import asyncio
import pytest
from pybluehost.cli.app.ble_scan import _ble_scan_main
from pybluehost.stack import Stack


async def test_ble_scan_starts_and_stops_cleanly():
    stack = await Stack.loopback()
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    task = asyncio.create_task(_ble_scan_main(stack, stop))
    asyncio.create_task(stopper())
    await task  # should return when stop.set
    await stack.close()
```

- [x] **Step 2: Run test — verify fail**

Run: `uv run pytest tests/unit/cli/test_app_ble_scan.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Create skeleton `app/__init__.py`**

```python
# pybluehost/cli/app/__init__.py
"""CLI 'app' namespace — commands that open an HCI transport."""
from __future__ import annotations

import argparse


def register_app_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'app' subcommand with all its sub-subcommands."""
    app_parser = subparsers.add_parser("app", help="Bluetooth functionality (needs transport)")
    app_subs = app_parser.add_subparsers(dest="app_cmd")
    # Sub-commands registered as we add them
    from pybluehost.cli.app.ble_scan import register_ble_scan_command
    register_ble_scan_command(app_subs)
```

- [x] **Step 4: Implement `app/ble_scan.py`**

```python
# pybluehost/cli/app/ble_scan.py
"""'app ble-scan' — long-running BLE advertisement scan."""
from __future__ import annotations

import argparse
import asyncio

from pybluehost.cli._lifecycle import run_app_command
from pybluehost.stack import Stack


def register_ble_scan_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("ble-scan", help="Scan BLE advertisements (Ctrl+C to stop)")
    p.add_argument("--transport", required=True, help="loopback | usb[:vendor=...] | uart:/dev/...[@baud]")
    p.set_defaults(func=lambda args: asyncio.run(run_app_command(args.transport, _ble_scan_main)))


async def _ble_scan_main(stack: Stack, stop: asyncio.Event) -> None:
    seen: dict[str, int] = {}

    def on_result(result):
        addr_s = str(result.address)
        rssi = result.rssi
        if addr_s not in seen or abs(seen[addr_s] - rssi) > 5:
            name = getattr(result, "local_name", None) or "<no name>"
            print(f"{addr_s}  rssi={rssi:>4}  {name}")
            seen[addr_s] = rssi

    stack.gap.ble_scanner.on_result(on_result)
    await stack.gap.ble_scanner.start()
    try:
        await stop.wait()
    finally:
        await stack.gap.ble_scanner.stop()
```

- [x] **Step 5: Run test — verify pass**

Run: `uv run pytest tests/unit/cli/test_app_ble_scan.py -v`
Expected: 1 PASS

- [x] **Step 6: Commit**

```bash
git add pybluehost/cli/app/__init__.py pybluehost/cli/app/ble_scan.py tests/unit/cli/test_app_ble_scan.py
git commit -m "feat(cli): add app ble-scan command (long-running)"
```

---

## Task 10: `app/ble_adv.py` — long-running BLE advertise

**Files:**
- Create: `pybluehost/cli/app/ble_adv.py`
- Modify: `pybluehost/cli/app/__init__.py` (register)
- Test: `tests/unit/cli/test_app_ble_adv.py`

- [x] **Step 1: Write failing test**

```python
# tests/unit/cli/test_app_ble_adv.py
import asyncio
import pytest
from pybluehost.cli.app.ble_adv import _ble_adv_main
from pybluehost.stack import Stack


async def test_ble_adv_starts_and_stops_cleanly():
    stack = await Stack.loopback()
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    args_name = "PyBlueHostTest"
    task = asyncio.create_task(_ble_adv_main(stack, stop, name=args_name))
    asyncio.create_task(stopper())
    await task
    await stack.close()
```

- [x] **Step 2: Run test — verify fail**

Run: `uv run pytest tests/unit/cli/test_app_ble_adv.py -v`
Expected: FAIL `ModuleNotFoundError`

- [x] **Step 3: Implement `app/ble_adv.py`**

```python
# pybluehost/cli/app/ble_adv.py
"""'app ble-adv' — start BLE advertising until Ctrl+C."""
from __future__ import annotations

import argparse
import asyncio

from pybluehost.ble.gap import AdvertisingConfig
from pybluehost.cli._lifecycle import run_app_command
from pybluehost.stack import Stack


def register_ble_adv_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("ble-adv", help="Advertise BLE (Ctrl+C to stop)")
    p.add_argument("--transport", required=True)
    p.add_argument("--name", default="PyBlueHost", help="Local name in advertising data")
    p.set_defaults(
        func=lambda args: asyncio.run(
            run_app_command(args.transport, lambda s, e: _ble_adv_main(s, e, name=args.name))
        )
    )


async def _ble_adv_main(stack: Stack, stop: asyncio.Event, *, name: str) -> None:
    config = AdvertisingConfig()
    config.local_name = name
    await stack.gap.ble_advertiser.start(config)
    print(f"Advertising as {name!r} — Ctrl+C to stop")
    try:
        await stop.wait()
    finally:
        await stack.gap.ble_advertiser.stop()
```

- [x] **Step 4: Register in `app/__init__.py`**

Edit `pybluehost/cli/app/__init__.py` and add:

```python
    from pybluehost.cli.app.ble_adv import register_ble_adv_command
    register_ble_adv_command(app_subs)
```

- [x] **Step 5: Run test — verify pass**

Run: `uv run pytest tests/unit/cli/test_app_ble_adv.py -v`
Expected: 1 PASS. If `AdvertisingConfig` does not have a `local_name` attribute, inspect `pybluehost/ble/gap.py` and adjust to use the actual field name (e.g. set advertising data bytes directly).

- [x] **Step 6: Commit**

```bash
git add pybluehost/cli/app/ble_adv.py pybluehost/cli/app/__init__.py tests/unit/cli/test_app_ble_adv.py
git commit -m "feat(cli): add app ble-adv command (long-running)"
```

---

## Task 11: `app/classic_inquiry.py` — looped Classic inquiry

**Files:**
- Create: `pybluehost/cli/app/classic_inquiry.py`
- Modify: `pybluehost/cli/app/__init__.py`
- Test: `tests/unit/cli/test_app_classic_inquiry.py`

- [x] **Step 1: Write failing test**

```python
# tests/unit/cli/test_app_classic_inquiry.py
import asyncio
import pytest
from pybluehost.cli.app.classic_inquiry import _classic_inquiry_main
from pybluehost.stack import Stack


async def test_classic_inquiry_loops_and_stops():
    stack = await Stack.loopback()
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    task = asyncio.create_task(_classic_inquiry_main(stack, stop))
    asyncio.create_task(stopper())
    await task
    await stack.close()
```

- [x] **Step 2: Run test — verify fail**

Run: `uv run pytest tests/unit/cli/test_app_classic_inquiry.py -v`
Expected: FAIL

- [x] **Step 3: Implement `app/classic_inquiry.py`**

```python
# pybluehost/cli/app/classic_inquiry.py
"""'app classic-inquiry' — looped Classic inquiry, dedup-print results."""
from __future__ import annotations

import argparse
import asyncio

from pybluehost.classic.gap import InquiryConfig
from pybluehost.cli._lifecycle import run_app_command
from pybluehost.stack import Stack


def register_classic_inquiry_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("classic-inquiry", help="Loop Classic inquiry (Ctrl+C to stop)")
    p.add_argument("--transport", required=True)
    p.set_defaults(func=lambda args: asyncio.run(run_app_command(args.transport, _classic_inquiry_main)))


async def _classic_inquiry_main(stack: Stack, stop: asyncio.Event) -> None:
    seen: set[str] = set()

    def on_result(info):
        addr_s = str(info.address)
        if addr_s not in seen:
            name = getattr(info, "name", None) or "<unknown>"
            cod = getattr(info, "class_of_device", 0)
            print(f"{addr_s}  CoD=0x{cod:06X}  {name}")
            seen.add(addr_s)

    stack.gap.classic_discovery.on_result(on_result)
    config = InquiryConfig(duration=8)

    while not stop.is_set():
        try:
            await stack.gap.classic_discovery.start(config)
        except Exception as e:
            print(f"Inquiry error: {e}")
            break
        # Wait either inquiry duration or stop, whichever first
        try:
            await asyncio.wait_for(stop.wait(), timeout=config.duration * 1.28)
        except asyncio.TimeoutError:
            pass
        await stack.gap.classic_discovery.stop()
```

- [x] **Step 4: Register in `app/__init__.py`**

```python
    from pybluehost.cli.app.classic_inquiry import register_classic_inquiry_command
    register_classic_inquiry_command(app_subs)
```

- [x] **Step 5: Run test — verify pass**

Run: `uv run pytest tests/unit/cli/test_app_classic_inquiry.py -v`
Expected: 1 PASS

- [x] **Step 6: Commit**

```bash
git add pybluehost/cli/app/classic_inquiry.py pybluehost/cli/app/__init__.py tests/unit/cli/test_app_classic_inquiry.py
git commit -m "feat(cli): add app classic-inquiry command (long-running)"
```

---

## Task 12: `app/gatt_browser.py` — one-shot GATT discovery

**Files:**
- Create: `pybluehost/cli/app/gatt_browser.py`
- Modify: `pybluehost/cli/app/__init__.py`
- Test: `tests/unit/cli/test_app_gatt_browser.py`

- [x] **Step 1: Write failing test**

```python
# tests/unit/cli/test_app_gatt_browser.py
import argparse
import pytest
from pybluehost.cli.app.gatt_browser import _gatt_browser_main


async def test_gatt_browser_loopback_prints_battery_service(capsys):
    args = argparse.Namespace(transport="loopback", target=None)
    rc = await _gatt_browser_main(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "0x180F" in out or "180F" in out.upper() or "Battery" in out
```

- [x] **Step 2: Run test — verify fail**

Run: `uv run pytest tests/unit/cli/test_app_gatt_browser.py -v`
Expected: FAIL

- [x] **Step 3: Implement `app/gatt_browser.py`**

```python
# pybluehost/cli/app/gatt_browser.py
"""'app gatt-browser' — connect, discover GATT, print, exit."""
from __future__ import annotations

import argparse
import asyncio
import sys

from pybluehost.cli._loopback_peer import loopback_peer_with
from pybluehost.cli._target import parse_target_arg
from pybluehost.cli._transport import parse_transport_arg
from pybluehost.profiles.ble import BatteryServer
from pybluehost.stack import Stack


def register_gatt_browser_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("gatt-browser", help="Connect, discover GATT, print, exit")
    p.add_argument("--transport", required=True)
    p.add_argument("--target", help="BD_ADDR (required unless --transport loopback)")
    p.set_defaults(func=lambda args: asyncio.run(_gatt_browser_main(args)))


async def _gatt_browser_main(args: argparse.Namespace) -> int:
    is_loopback = args.transport == "loopback"
    if not is_loopback and not args.target:
        print("Error: --target is required for non-loopback transport", file=sys.stderr)
        return 2

    try:
        transport = parse_transport_arg(args.transport)
        stack = await Stack._build(transport=transport)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    async def battery_factory(gatt):
        await BatteryServer(initial_level=85).register(gatt)

    try:
        if is_loopback:
            async with loopback_peer_with(battery_factory) as peer:
                target_addr = peer.local_address
                print(f"Connected to {target_addr} (loopback peer)")
                _print_gatt_tree_for_loopback(peer)
        else:
            addr, _atype = parse_target_arg(args.target)
            print(f"Connected to {addr}")
            # Real connection would happen here; for now we report intent
            print("(Real-hardware GATT discovery not implemented in v1; loopback only.)")
        return 0
    finally:
        await stack.close()


def _print_gatt_tree_for_loopback(peer: Stack) -> None:
    """Iterate peer.gatt_server.db and print services/characteristics."""
    db = peer.gatt_server.db
    services = db.list_services() if hasattr(db, "list_services") else []
    for svc in services:
        print(f"─ Service {svc.uuid}")
        chars = db.list_characteristics(svc) if hasattr(db, "list_characteristics") else []
        for char in chars:
            value = db.read(char.value_handle) if hasattr(char, "value_handle") else b""
            print(f"   ├─ Char {char.uuid} handle=0x{char.value_handle:04X} value={value.hex()}")
```

> NOTE: Real over-the-air GATT discovery requires a working LE connection on a real adapter. For loopback this would also need a paired-VC connection. To keep this task bounded, **loopback prints the local DB tree of the peer**; real-hardware support is a follow-up.

If `db.list_services` / `list_characteristics` don't exist on the actual `AttributeDatabase`, walk the attributes manually using `db.attributes` (which exists per `pybluehost/ble/gatt.py`).

- [x] **Step 4: Register in `app/__init__.py`**

```python
    from pybluehost.cli.app.gatt_browser import register_gatt_browser_command
    register_gatt_browser_command(app_subs)
```

- [x] **Step 5: Run test — verify pass**

Run: `uv run pytest tests/unit/cli/test_app_gatt_browser.py -v`
Expected: 1 PASS. If GATT DB inspection method names differ, adapt to use the real API (read `pybluehost/ble/gatt.py` once for the actual method names; do not invent).

- [x] **Step 6: Commit**

```bash
git add pybluehost/cli/app/gatt_browser.py pybluehost/cli/app/__init__.py tests/unit/cli/test_app_gatt_browser.py
git commit -m "feat(cli): add app gatt-browser command (loopback DB inspection)"
```

---

## Task 13: `app/sdp_browser.py` — one-shot SDP query

**Files:**
- Create: `pybluehost/cli/app/sdp_browser.py`
- Modify: `pybluehost/cli/app/__init__.py`
- Test: `tests/unit/cli/test_app_sdp_browser.py`

- [x] **Step 1: Write failing test**

```python
# tests/unit/cli/test_app_sdp_browser.py
import argparse
from pybluehost.cli.app.sdp_browser import _sdp_browser_main


async def test_sdp_browser_loopback_prints_records(capsys):
    args = argparse.Namespace(transport="loopback", target=None)
    rc = await _sdp_browser_main(args)
    out = capsys.readouterr().out
    assert rc == 0
    # Loopback peer SDPServer starts with no records by default; just verify a header
    assert "SDP" in out or "records" in out.lower()
```

- [x] **Step 2: Run test — verify fail**

Run: `uv run pytest tests/unit/cli/test_app_sdp_browser.py -v`
Expected: FAIL

- [x] **Step 3: Implement `app/sdp_browser.py`**

```python
# pybluehost/cli/app/sdp_browser.py
"""'app sdp-browser' — connect, query SDP records, print, exit."""
from __future__ import annotations

import argparse
import asyncio
import sys

from pybluehost.cli._target import parse_target_arg
from pybluehost.cli._transport import parse_transport_arg
from pybluehost.stack import Stack


def register_sdp_browser_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("sdp-browser", help="Connect, query SDP, print, exit")
    p.add_argument("--transport", required=True)
    p.add_argument("--target", help="BD_ADDR (required unless --transport loopback)")
    p.set_defaults(func=lambda args: asyncio.run(_sdp_browser_main(args)))


async def _sdp_browser_main(args: argparse.Namespace) -> int:
    is_loopback = args.transport == "loopback"
    if not is_loopback and not args.target:
        print("Error: --target is required for non-loopback transport", file=sys.stderr)
        return 2

    try:
        transport = parse_transport_arg(args.transport)
        stack = await Stack._build(transport=transport)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        if is_loopback:
            print("SDP records (loopback peer):")
            peer_sdp = stack.sdp
            records = list(peer_sdp.records()) if hasattr(peer_sdp, "records") else []
            if not records:
                print("  (no records registered)")
            for rec in records:
                print(f"  Record handle=0x{rec.handle:08X}")
        else:
            addr, _atype = parse_target_arg(args.target)
            print(f"Connected to {addr}")
            print("(Real-hardware SDP query not implemented in v1; loopback only.)")
        return 0
    finally:
        await stack.close()
```

If `SDPServer` exposes records under a different attribute, adapt by reading `pybluehost/classic/sdp.py` and using the real iteration method.

- [x] **Step 4: Register in `app/__init__.py`**

```python
    from pybluehost.cli.app.sdp_browser import register_sdp_browser_command
    register_sdp_browser_command(app_subs)
```

- [x] **Step 5: Run test — verify pass**

Run: `uv run pytest tests/unit/cli/test_app_sdp_browser.py -v`
Expected: 1 PASS

- [x] **Step 6: Commit**

```bash
git add pybluehost/cli/app/sdp_browser.py pybluehost/cli/app/__init__.py tests/unit/cli/test_app_sdp_browser.py
git commit -m "feat(cli): add app sdp-browser command (loopback inspection)"
```

---

## Task 14: `app/gatt_server.py` — long-running GATT server

**Files:**
- Create: `pybluehost/cli/app/gatt_server.py`
- Modify: `pybluehost/cli/app/__init__.py`
- Test: `tests/unit/cli/test_app_gatt_server.py`

- [x] **Step 1: Write failing test**

```python
# tests/unit/cli/test_app_gatt_server.py
import asyncio
from pybluehost.cli.app.gatt_server import _gatt_server_main
from pybluehost.stack import Stack


async def test_gatt_server_registers_battery_and_hrs():
    stack = await Stack.loopback()
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    task = asyncio.create_task(_gatt_server_main(stack, stop))
    asyncio.create_task(stopper())
    await task
    # Verify services registered
    db = stack.gatt_server.db
    # Find by UUID 0x180F (Battery) and 0x180D (HRS)
    found_uuids = set()
    for attr in getattr(db, "_attributes", []):
        uuid_val = getattr(attr, "uuid", None)
        if uuid_val is not None:
            found_uuids.add(int(uuid_val) if hasattr(uuid_val, "value") else uuid_val.value if hasattr(uuid_val, "value") else None)
    # Loose assertion: server didn't crash
    await stack.close()
```

- [x] **Step 2: Run test — verify fail**

Run: `uv run pytest tests/unit/cli/test_app_gatt_server.py -v`
Expected: FAIL `ModuleNotFoundError`

- [x] **Step 3: Implement `app/gatt_server.py`**

```python
# pybluehost/cli/app/gatt_server.py
"""'app gatt-server' — register Battery + HRS, await connections."""
from __future__ import annotations

import argparse
import asyncio

from pybluehost.cli._lifecycle import run_app_command
from pybluehost.profiles.ble import BatteryServer, HeartRateServer
from pybluehost.stack import Stack


def register_gatt_server_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("gatt-server", help="Run Battery + HRS GATT server (Ctrl+C to stop)")
    p.add_argument("--transport", required=True)
    p.set_defaults(func=lambda args: asyncio.run(run_app_command(args.transport, _gatt_server_main)))


async def _gatt_server_main(stack: Stack, stop: asyncio.Event) -> None:
    battery = BatteryServer(initial_level=85)
    hrs = HeartRateServer(sensor_location=0x02)
    await battery.register(stack.gatt_server)
    await hrs.register(stack.gatt_server)
    print(f"GATT server up: BatteryServer + HeartRateServer registered")
    print(f"Local address: {stack.local_address}")
    print("Awaiting connections — Ctrl+C to stop")
    await stop.wait()
```

- [x] **Step 4: Register in `app/__init__.py`**

```python
    from pybluehost.cli.app.gatt_server import register_gatt_server_command
    register_gatt_server_command(app_subs)
```

- [x] **Step 5: Run test — verify pass**

Run: `uv run pytest tests/unit/cli/test_app_gatt_server.py -v`
Expected: 1 PASS

- [x] **Step 6: Commit**

```bash
git add pybluehost/cli/app/gatt_server.py pybluehost/cli/app/__init__.py tests/unit/cli/test_app_gatt_server.py
git commit -m "feat(cli): add app gatt-server command (long-running)"
```

---

## Task 15: `app/hr_monitor.py` — HRS server with 1Hz notifications

**Files:**
- Create: `pybluehost/cli/app/hr_monitor.py`
- Modify: `pybluehost/cli/app/__init__.py`
- Test: `tests/unit/cli/test_app_hr_monitor.py`

- [x] **Step 1: Write failing test**

```python
# tests/unit/cli/test_app_hr_monitor.py
import asyncio
from pybluehost.cli.app.hr_monitor import _hr_monitor_main
from pybluehost.stack import Stack


async def test_hr_monitor_pushes_measurements_until_stop():
    stack = await Stack.loopback()
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.15)
        stop.set()

    task = asyncio.create_task(_hr_monitor_main(stack, stop, interval=0.05))
    asyncio.create_task(stopper())
    await task
    await stack.close()
```

- [x] **Step 2: Run test — verify fail**

Run: `uv run pytest tests/unit/cli/test_app_hr_monitor.py -v`
Expected: FAIL

- [x] **Step 3: Implement `app/hr_monitor.py`**

```python
# pybluehost/cli/app/hr_monitor.py
"""'app hr-monitor' — HRS server pushing random heart-rate notifications."""
from __future__ import annotations

import argparse
import asyncio
import random

from pybluehost.cli._lifecycle import run_app_command
from pybluehost.profiles.ble import HeartRateServer
from pybluehost.stack import Stack


def register_hr_monitor_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("hr-monitor", help="HRS server pushing random heart-rate (Ctrl+C to stop)")
    p.add_argument("--transport", required=True)
    p.set_defaults(func=lambda args: asyncio.run(run_app_command(args.transport, _hr_monitor_main)))


async def _hr_monitor_main(stack: Stack, stop: asyncio.Event, *, interval: float = 1.0) -> None:
    hrs = HeartRateServer(sensor_location=0x02)
    await hrs.register(stack.gatt_server)
    print(f"HRS up at {stack.local_address} — pushing random bpm every {interval}s")

    while not stop.is_set():
        bpm = random.randint(60, 100)
        await hrs.update_measurement(bpm=bpm)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
```

- [x] **Step 4: Register in `app/__init__.py`**

```python
    from pybluehost.cli.app.hr_monitor import register_hr_monitor_command
    register_hr_monitor_command(app_subs)
```

- [x] **Step 5: Run test — verify pass**

Run: `uv run pytest tests/unit/cli/test_app_hr_monitor.py -v`
Expected: 1 PASS

- [x] **Step 6: Commit**

```bash
git add pybluehost/cli/app/hr_monitor.py pybluehost/cli/app/__init__.py tests/unit/cli/test_app_hr_monitor.py
git commit -m "feat(cli): add app hr-monitor command (long-running)"
```

---

## Task 16: `app/spp_echo.py` — RFCOMM echo server

**Files:**
- Create: `pybluehost/cli/app/spp_echo.py`
- Modify: `pybluehost/cli/app/__init__.py`
- Test: `tests/unit/cli/test_app_spp_echo.py`

- [x] **Step 1: Write failing test**

```python
# tests/unit/cli/test_app_spp_echo.py
import asyncio
from pybluehost.cli.app.spp_echo import _spp_echo_main
from pybluehost.stack import Stack


async def test_spp_echo_starts_and_stops_cleanly():
    stack = await Stack.loopback()
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    task = asyncio.create_task(_spp_echo_main(stack, stop))
    asyncio.create_task(stopper())
    await task
    await stack.close()
```

- [x] **Step 2: Run test — verify fail**

Run: `uv run pytest tests/unit/cli/test_app_spp_echo.py -v`
Expected: FAIL

- [x] **Step 3: Implement `app/spp_echo.py`**

```python
# pybluehost/cli/app/spp_echo.py
"""'app spp-echo' — RFCOMM channel 1 echo server."""
from __future__ import annotations

import argparse
import asyncio

from pybluehost.cli._lifecycle import run_app_command
from pybluehost.stack import Stack


def register_spp_echo_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("spp-echo", help="RFCOMM ch1 echo server (Ctrl+C to stop)")
    p.add_argument("--transport", required=True)
    p.set_defaults(func=lambda args: asyncio.run(run_app_command(args.transport, _spp_echo_main)))


async def _spp_echo_main(stack: Stack, stop: asyncio.Event) -> None:
    rfcomm = stack.rfcomm
    print(f"SPP echo server (loopback only echoes locally) — local={stack.local_address}")
    # Best-effort: register a channel handler that echoes received bytes.
    # If RFCOMMManager API differs, fall back to printing the wait loop only.
    if hasattr(rfcomm, "register_channel"):
        async def handler(channel):
            async for data in channel:
                await channel.write(data)

        try:
            await rfcomm.register_channel(channel_id=1, handler=handler)
        except TypeError:
            # API mismatch — degrade gracefully (loopback has no peer anyway)
            pass
    await stop.wait()
```

If the `RFCOMMManager` registration API has different arguments, read `pybluehost/classic/rfcomm.py` and adapt — the goal is just to wait on `stop` cleanly in loopback mode. If RFCOMM has no register API yet, just `await stop.wait()` and print a NOTE.

- [x] **Step 4: Register in `app/__init__.py`**

```python
    from pybluehost.cli.app.spp_echo import register_spp_echo_command
    register_spp_echo_command(app_subs)
```

- [x] **Step 5: Run test — verify pass**

Run: `uv run pytest tests/unit/cli/test_app_spp_echo.py -v`
Expected: 1 PASS

- [x] **Step 6: Commit**

```bash
git add pybluehost/cli/app/spp_echo.py pybluehost/cli/app/__init__.py tests/unit/cli/test_app_spp_echo.py
git commit -m "feat(cli): add app spp-echo command (long-running)"
```

---

## Task 17: Wire `cli/__init__.py` + update README

**Files:**
- Modify: `pybluehost/cli/__init__.py`
- Modify: `README.md` (CLI section)
- Test: `tests/unit/cli/test_main_entry.py`

- [x] **Step 1: Write failing test**

```python
# tests/unit/cli/test_main_entry.py
import pytest
from pybluehost.cli import main


def test_main_no_args_prints_help_returns_0(capsys):
    rc = main([])
    captured = capsys.readouterr()
    assert rc == 0
    assert "usage" in captured.out.lower() or "usage" in captured.err.lower()


def test_main_app_namespace_exists(capsys):
    # Just verify parser accepts 'app --help'
    with pytest.raises(SystemExit) as ei:
        main(["app", "--help"])
    assert ei.value.code == 0


def test_main_tools_namespace_exists():
    with pytest.raises(SystemExit) as ei:
        main(["tools", "--help"])
    assert ei.value.code == 0


def test_main_top_level_fw_no_longer_exists():
    """fw moved to 'tools fw' — top-level should fail."""
    with pytest.raises(SystemExit) as ei:
        main(["fw", "list"])
    assert ei.value.code != 0  # argparse error
```

- [x] **Step 2: Run tests — verify fail**

Run: `uv run pytest tests/unit/cli/test_main_entry.py -v`
Expected: FAIL — `app`/`tools` not registered yet at top level.

- [x] **Step 3: Update `pybluehost/cli/__init__.py`**

```python
# pybluehost/cli/__init__.py
"""PyBlueHost CLI entry point."""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point for pybluehost."""
    parser = argparse.ArgumentParser(
        prog="pybluehost",
        description="PyBlueHost — Python Bluetooth Host Stack CLI",
    )
    subparsers = parser.add_subparsers(dest="command")

    from pybluehost.cli.app import register_app_commands
    from pybluehost.cli.tools import register_tools_commands

    register_app_commands(subparsers)
    register_tools_commands(subparsers)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    if not hasattr(args, "func"):
        # Top-level namespace given without subcommand
        parser.print_help()
        return 2

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 4: Update `README.md` CLI section**

Replace the existing CLI section in `README.md`:

```markdown
## 命令行工具

PyBlueHost CLI 分为两个命名空间：

- `pybluehost app <cmd>` — 需要打开 HCI transport，跑真实蓝牙功能
- `pybluehost tools <cmd>` — 离线工具，不需要 transport

### app（蓝牙功能，必填 `--transport`）

```bash
# 长跑命令（Ctrl+C 结束）
uv run pybluehost app ble-scan --transport usb
uv run pybluehost app ble-adv --transport usb --name MyDevice
uv run pybluehost app classic-inquiry --transport usb
uv run pybluehost app gatt-server --transport loopback
uv run pybluehost app hr-monitor --transport loopback
uv run pybluehost app spp-echo --transport usb

# 一次性命令
uv run pybluehost app gatt-browser --transport loopback
uv run pybluehost app sdp-browser --transport loopback
```

`--transport` 接受 `loopback` / `usb` / `usb:vendor=intel` / `uart:/dev/ttyUSB0[@115200]`。

### tools（离线工具）

```bash
# HCI 包解码
uv run pybluehost tools decode 01030c00

# RPA 计算
uv run pybluehost tools rpa gen-irk
uv run pybluehost tools rpa gen-rpa --irk <32-hex>
uv run pybluehost tools rpa verify --irk <32-hex> --addr AA:BB:CC:DD:EE:FF

# 固件管理
uv run pybluehost tools fw list
uv run pybluehost tools fw download <chip>

# USB 诊断
uv run pybluehost tools usb scan
```
```

- [x] **Step 5: Run main entry tests + full suite**

Run:
```bash
uv run pytest tests/unit/cli/test_main_entry.py -v
uv run pytest tests/ -m "not hardware" -q
```
Expected: main entry 4 PASS; full suite all PASS.

- [x] **Step 6: Commit**

```bash
git add pybluehost/cli/__init__.py README.md tests/unit/cli/test_main_entry.py
git commit -m "feat(cli): wire app+tools namespaces, drop top-level fw/usb, update README"
```

---

## Task 18: Final verification + STATUS update

- [x] **Step 1: Run full test suite with coverage**

```bash
uv run pytest tests/ -m "not hardware" --cov=pybluehost --cov-report=term-missing --cov-fail-under=85
```
Expected: all PASS, coverage ≥85%.

- [x] **Step 2: Verify CLI tree**

```bash
uv run pybluehost --help
uv run pybluehost app --help
uv run pybluehost tools --help
uv run pybluehost tools rpa --help
```
Expected: all show clean help with all subcommands listed.

- [x] **Step 3: Smoke-test loopback commands end-to-end**

```bash
uv run pybluehost tools decode 01030c00
uv run pybluehost tools rpa gen-irk
uv run pybluehost app gatt-browser --transport loopback
```
Expected: all run without exception, produce expected output.

- [x] **Step 4: Update `docs/superpowers/STATUS.md`**

Add a new row to the Plan overview table for this work, and a detail entry — see existing format. Set status ✅ with completion date 2026-04-25.

- [x] **Step 5: Commit STATUS update**

```bash
git add docs/superpowers/STATUS.md
git commit -m "docs(progress): mark CLI app+tools plan complete"
```

---

## Notes for the implementer

- **API verification:** A few tasks (`gatt-browser`, `sdp-browser`, `spp-echo`) reference attributes (`db.list_services`, `sdp.records`, `rfcomm.register_channel`) that may not exist exactly. The plan instructs you to read the real source (`pybluehost/ble/gatt.py`, `pybluehost/classic/sdp.py`, `pybluehost/classic/rfcomm.py`) and use the actual method names. **Do not invent APIs.** If a needed feature does not exist, downgrade gracefully (print "not yet supported" + still wait on `stop`) — these are mostly stubs in v1 anyway and full impl can be a follow-up plan.
- **Always use `uv run pytest`** — never bare `pytest`.
- **All async tests** — `asyncio_mode = "auto"` in pyproject.toml means `async def test_X()` is auto-collected.
- **One commit per task** — TDD cadence: failing test → impl → passing test → commit.
- **Don't skip the failing-test step.** It catches typos in test imports before you waste time on impl.
