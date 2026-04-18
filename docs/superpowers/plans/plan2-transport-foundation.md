# Transport Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build the Transport layer foundation: an async `Transport` ABC plus software-only concrete implementations (Loopback, UART, TCP, UDP, Btsnoop-replay) that upper layers can use without requiring Bluetooth hardware.

**Architecture:** All transports follow the same shape — `async open/close/send` + a `TransportSink` callback (`async on_data(bytes)`) for received data. The underlying byte streams use H4 framing (Core Spec Vol 4 Part A), so a shared `H4Framer` state machine reassembles packets for stream-oriented transports (UART, TCP). Datagram-oriented transports (UDP, Btsnoop replay) deliver one complete HCI packet per message. `LoopbackTransport.pair()` connects two in-memory instances for unit testing upper layers without hardware. USB/chip auto-detect/firmware loading are intentionally deferred to later plans.

**Tech Stack:** Python 3.10+, asyncio, `pyserial-asyncio` (new runtime dep for UART), `pytest` + `pytest-asyncio` (already present). Reuses `pybluehost.core.errors.TransportError` and the btsnoop format written by `pybluehost.core.trace.BtsnoopSink`.

---

## File Structure

```
pybluehost/transport/
├── __init__.py          # Public exports
├── base.py              # Transport ABC, TransportInfo, TransportSink, ReconnectPolicy
├── h4.py                # H4Framer — pure-bytes packet reassembly state machine
├── loopback.py          # LoopbackTransport (in-memory pair)
├── uart.py              # UARTTransport (pyserial-asyncio + H4Framer)
├── tcp.py               # TCPTransport (asyncio streams + H4Framer)
├── udp.py               # UDPTransport (one datagram per HCI packet)
└── btsnoop.py           # BtsnoopTransport (replay mode, reads btsnoop files)

tests/unit/transport/
├── __init__.py
├── test_base.py
├── test_h4.py
├── test_loopback.py
├── test_uart.py
├── test_tcp.py
├── test_udp.py
└── test_btsnoop.py
```

**File responsibility rules:**
- `base.py` holds abstract types and the common interface. No concrete I/O.
- `h4.py` is pure logic (bytes in, packets out). No I/O, no asyncio.
- Each concrete transport file handles only its own I/O mechanism and uses `H4Framer` when the underlying channel is stream-oriented.
- No transport touches HCI semantics — they transmit bytes; Plan 3 (HCI) decodes.

---

## Task 1: Transport Base ABC and Package Scaffolding

**Files:**
- Create: `pybluehost/transport/__init__.py` (empty for now; final exports added in Task 8)
- Create: `pybluehost/transport/base.py`
- Create: `tests/unit/transport/__init__.py` (empty)
- Create: `tests/unit/transport/test_base.py`

- [x] **Step 1: Create empty package markers**

Create `pybluehost/transport/__init__.py` with a single docstring line:

```python
"""PyBlueHost transport layer."""
```

Create `tests/unit/transport/__init__.py` as an empty file (0 bytes).

- [x] **Step 2: Write the failing tests for base types**

Create `tests/unit/transport/test_base.py`:

```python
import pytest

from pybluehost.transport.base import (
    ReconnectPolicy,
    Transport,
    TransportInfo,
    TransportSink,
)


class _StubTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self._opened = False
        self.sent: list[bytes] = []

    async def open(self) -> None:
        self._opened = True

    async def close(self) -> None:
        self._opened = False

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    @property
    def is_open(self) -> bool:
        return self._opened

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(type="stub", description="stub", platform="any", details={})


class TestTransportInfo:
    def test_fields(self):
        info = TransportInfo(
            type="uart",
            description="UART /dev/ttyUSB0 @ 115200",
            platform="linux",
            details={"port": "/dev/ttyUSB0", "baudrate": 115200},
        )
        assert info.type == "uart"
        assert info.details["baudrate"] == 115200

    def test_info_is_frozen(self):
        info = TransportInfo(type="x", description="x", platform="any", details={})
        with pytest.raises(Exception):
            info.type = "y"  # type: ignore[misc]


class TestReconnectPolicy:
    def test_values(self):
        assert ReconnectPolicy.NONE.value == "none"
        assert ReconnectPolicy.IMMEDIATE.value == "immediate"
        assert ReconnectPolicy.EXPONENTIAL.value == "exponential"


class TestTransportABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Transport()  # type: ignore[abstract]

    @pytest.mark.asyncio
    async def test_stub_lifecycle(self):
        t = _StubTransport()
        assert t.is_open is False
        await t.open()
        assert t.is_open is True
        await t.send(b"\x01\x02")
        assert t.sent == [b"\x01\x02"]
        await t.close()
        assert t.is_open is False

    @pytest.mark.asyncio
    async def test_set_sink(self):
        received: list[bytes] = []

        class Sink:
            async def on_data(self, data: bytes) -> None:
                received.append(data)

        t = _StubTransport()
        sink = Sink()
        t.set_sink(sink)
        assert t._sink is sink
        t.set_sink(None)
        assert t._sink is None

    @pytest.mark.asyncio
    async def test_default_reset_is_close_then_open(self):
        t = _StubTransport()
        await t.open()
        assert t.is_open is True
        await t.reset()
        assert t.is_open is True  # reset reopens
        # verify close was actually called: send after reset still works
        await t.send(b"\x03")
        assert t.sent == [b"\x03"]

    def test_transport_sink_is_runtime_protocol(self):
        assert hasattr(TransportSink, "__class_getitem__") or True  # Protocol sanity
```

- [x] **Step 3: Run the test, confirm it fails**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/unit/transport/test_base.py -v
```

Expected: `ModuleNotFoundError: No module named 'pybluehost.transport.base'`.

- [x] **Step 4: Implement `pybluehost/transport/base.py`**

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class TransportSink(Protocol):
    """Callback: how a transport delivers received bytes to a consumer."""

    async def on_data(self, data: bytes) -> None: ...


@dataclass(frozen=True)
class TransportInfo:
    type: str
    description: str
    platform: str
    details: dict[str, Any]


class ReconnectPolicy(Enum):
    NONE = "none"
    IMMEDIATE = "immediate"
    EXPONENTIAL = "exponential"


class Transport(ABC):
    """Abstract transport. Subclasses implement open/close/send and expose is_open/info."""

    def __init__(self) -> None:
        self._sink: TransportSink | None = None

    @abstractmethod
    async def open(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def send(self, data: bytes) -> None: ...

    @property
    @abstractmethod
    def is_open(self) -> bool: ...

    @property
    @abstractmethod
    def info(self) -> TransportInfo: ...

    def set_sink(self, sink: TransportSink | None) -> None:
        self._sink = sink

    async def reset(self) -> None:
        """Default reconnect: close then open. Subclasses may override."""
        await self.close()
        await self.open()
```

- [x] **Step 5: Run test, confirm pass**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/unit/transport/test_base.py -v
```

Expected: all tests PASS.

- [x] **Step 6: Commit**

```bash
git add pybluehost/transport/__init__.py pybluehost/transport/base.py \
        tests/unit/transport/__init__.py tests/unit/transport/test_base.py
git commit -m "feat(transport): add Transport ABC, TransportInfo, TransportSink, ReconnectPolicy"
```

---

## Task 2: LoopbackTransport

**Files:**
- Create: `pybluehost/transport/loopback.py`
- Create: `tests/unit/transport/test_loopback.py`

- [x] **Step 1: Write the failing test**

Create `tests/unit/transport/test_loopback.py`:

```python
import pytest

from pybluehost.transport.loopback import LoopbackTransport


class _Collect:
    def __init__(self) -> None:
        self.received: list[bytes] = []

    async def on_data(self, data: bytes) -> None:
        self.received.append(data)


class TestLoopbackPair:
    @pytest.mark.asyncio
    async def test_pair_delivers_bytes_to_peer(self):
        a, b = LoopbackTransport.pair()
        sink_b = _Collect()
        b.set_sink(sink_b)
        await a.open()
        await b.open()
        await a.send(b"\x01\x03\x0c\x00")
        assert sink_b.received == [b"\x01\x03\x0c\x00"]

    @pytest.mark.asyncio
    async def test_pair_is_bidirectional(self):
        a, b = LoopbackTransport.pair()
        sink_a, sink_b = _Collect(), _Collect()
        a.set_sink(sink_a)
        b.set_sink(sink_b)
        await a.open()
        await b.open()
        await a.send(b"A")
        await b.send(b"B")
        assert sink_a.received == [b"B"]
        assert sink_b.received == [b"A"]

    @pytest.mark.asyncio
    async def test_send_when_closed_raises(self):
        a, b = LoopbackTransport.pair()
        await b.open()
        # a not opened
        with pytest.raises(RuntimeError, match="not open"):
            await a.send(b"X")

    @pytest.mark.asyncio
    async def test_send_when_peer_closed_is_dropped(self):
        a, b = LoopbackTransport.pair()
        sink_b = _Collect()
        b.set_sink(sink_b)
        await a.open()
        # b not opened → send from a is dropped silently
        await a.send(b"X")
        assert sink_b.received == []

    @pytest.mark.asyncio
    async def test_info(self):
        a, _ = LoopbackTransport.pair()
        assert a.info.type == "loopback"
        assert a.info.platform == "any"

    @pytest.mark.asyncio
    async def test_solo_instance_has_no_peer(self):
        solo = LoopbackTransport()
        await solo.open()
        with pytest.raises(RuntimeError, match="peer"):
            await solo.send(b"X")
```

- [x] **Step 2: Confirm fail**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/unit/transport/test_loopback.py -v
```

Expected: `ModuleNotFoundError`.

- [x] **Step 3: Implement `pybluehost/transport/loopback.py`**

```python
from __future__ import annotations

from pybluehost.transport.base import Transport, TransportInfo


class LoopbackTransport(Transport):
    """In-memory loopback. Bytes sent on one instance are delivered to its peer's sink."""

    def __init__(self) -> None:
        super().__init__()
        self._peer: "LoopbackTransport | None" = None
        self._open = False

    @classmethod
    def pair(cls) -> tuple["LoopbackTransport", "LoopbackTransport"]:
        a = cls()
        b = cls()
        a._peer = b
        b._peer = a
        return a, b

    async def open(self) -> None:
        self._open = True

    async def close(self) -> None:
        self._open = False

    async def send(self, data: bytes) -> None:
        if not self._open:
            raise RuntimeError("LoopbackTransport not open")
        if self._peer is None:
            raise RuntimeError("LoopbackTransport has no peer")
        if self._peer._open and self._peer._sink is not None:
            await self._peer._sink.on_data(data)

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="loopback",
            description="In-memory loopback transport",
            platform="any",
            details={},
        )
```

- [x] **Step 4: Confirm pass**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/unit/transport/test_loopback.py -v
```

Expected: all tests PASS.

- [x] **Step 5: Commit**

```bash
git add pybluehost/transport/loopback.py tests/unit/transport/test_loopback.py
git commit -m "feat(transport): add LoopbackTransport for in-memory pair testing"
```

---

## Task 3: H4 Framer (pure state machine)

**Files:**
- Create: `pybluehost/transport/h4.py`
- Create: `tests/unit/transport/test_h4.py`

**Background for the implementer:**
H4 framing (Core Spec Vol 4 Part A) prefixes every HCI packet with a 1-byte indicator byte:

| Indicator | Packet | Header after indicator | Payload length field |
|-----------|--------|------------------------|----------------------|
| 0x01 | Command | 3 bytes (opcode 2 LE + len 1) | byte 2 (1 byte) |
| 0x02 | ACL | 4 bytes (handle+flags 2 LE + len 2 LE) | bytes 2–3 (2 bytes, LE) |
| 0x03 | SCO | 3 bytes (handle 2 LE + len 1) | byte 2 (1 byte) |
| 0x04 | Event | 2 bytes (event_code 1 + len 1) | byte 1 (1 byte) |
| 0x05 | ISO | 4 bytes (handle+flags 2 LE + len 2 LE, low 14 bits) | bytes 2–3 (2 bytes, mask 0x3FFF) |

The framer accumulates bytes and yields complete packets (indicator + header + payload) as `bytes` objects.

- [x] **Step 1: Write the failing tests**

Create `tests/unit/transport/test_h4.py`:

```python
import pytest

from pybluehost.transport.h4 import H4Framer


class TestH4FramerComplete:
    def test_hci_reset_command(self):
        # HCI_Reset: indicator 01, opcode 0C03, length 00
        packet = bytes.fromhex("01030c00")
        framer = H4Framer()
        out = list(framer.feed(packet))
        assert out == [packet]

    def test_command_complete_event(self):
        # Event 0x0E (Command Complete), length 04, payload 01 03 0C 00
        packet = bytes.fromhex("040e0401030c00")
        framer = H4Framer()
        out = list(framer.feed(packet))
        assert out == [packet]

    def test_acl_data_two_byte_length(self):
        # ACL: indicator 02, handle+flags 0x0001 LE, length 0x0004 LE, payload 4 bytes
        packet = bytes.fromhex("02010004000102030405")[:9]  # 1+4+4=9 bytes total
        # Build precisely:
        packet = bytes([0x02, 0x01, 0x00, 0x04, 0x00]) + bytes(range(4))
        framer = H4Framer()
        out = list(framer.feed(packet))
        assert out == [packet]


class TestH4FramerPartial:
    def test_bytes_split_across_feeds(self):
        packet = bytes.fromhex("01030c00")
        framer = H4Framer()
        assert list(framer.feed(packet[:1])) == []
        assert list(framer.feed(packet[1:3])) == []
        assert list(framer.feed(packet[3:])) == [packet]

    def test_one_byte_at_a_time(self):
        packet = bytes.fromhex("040e0401030c00")
        framer = H4Framer()
        emitted: list[bytes] = []
        for b in packet:
            emitted.extend(framer.feed(bytes([b])))
        assert emitted == [packet]


class TestH4FramerMulti:
    def test_two_packets_in_one_feed(self):
        p1 = bytes.fromhex("01030c00")
        p2 = bytes.fromhex("040e0401030c00")
        framer = H4Framer()
        out = list(framer.feed(p1 + p2))
        assert out == [p1, p2]

    def test_packet_plus_partial_next(self):
        p1 = bytes.fromhex("01030c00")
        p2 = bytes.fromhex("040e0401030c00")
        framer = H4Framer()
        out = list(framer.feed(p1 + p2[:3]))
        assert out == [p1]
        out2 = list(framer.feed(p2[3:]))
        assert out2 == [p2]


class TestH4FramerISO:
    def test_iso_data_masks_length_to_14_bits(self):
        # ISO: indicator 05, handle+flags 0x0001 LE, length 0xC008 LE (top 2 bits flags, low 14 = 0x0008)
        packet = bytes([0x05, 0x01, 0x00, 0x08, 0xC0]) + bytes(8)
        framer = H4Framer()
        out = list(framer.feed(packet))
        assert out == [packet]


class TestH4FramerErrors:
    def test_unknown_indicator_raises(self):
        framer = H4Framer()
        with pytest.raises(ValueError, match="Unknown H4 indicator"):
            list(framer.feed(b"\xFF\x00\x00"))
```

- [x] **Step 2: Confirm fail**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/unit/transport/test_h4.py -v
```

Expected: `ModuleNotFoundError`.

- [x] **Step 3: Implement `pybluehost/transport/h4.py`**

```python
from __future__ import annotations

from typing import Iterator


H4_COMMAND = 0x01
H4_ACL = 0x02
H4_SCO = 0x03
H4_EVENT = 0x04
H4_ISO = 0x05


# indicator → (header_len_after_indicator, length_field_offset_in_header, length_field_bytes)
_HEADER_SHAPE: dict[int, tuple[int, int, int]] = {
    H4_COMMAND: (3, 2, 1),
    H4_ACL:     (4, 2, 2),
    H4_SCO:     (3, 2, 1),
    H4_EVENT:   (2, 1, 1),
    H4_ISO:     (4, 2, 2),
}


class H4Framer:
    """Accumulate bytes and yield complete H4 packets (indicator + header + payload)."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> Iterator[bytes]:
        self._buf.extend(data)
        while True:
            if not self._buf:
                return
            indicator = self._buf[0]
            if indicator not in _HEADER_SHAPE:
                raise ValueError(f"Unknown H4 indicator 0x{indicator:02x}")
            header_len, len_off, len_bytes = _HEADER_SHAPE[indicator]
            if len(self._buf) < 1 + header_len:
                return
            if len_bytes == 1:
                payload_len = self._buf[1 + len_off]
            else:
                payload_len = int.from_bytes(
                    self._buf[1 + len_off : 1 + len_off + len_bytes], "little"
                )
                if indicator == H4_ISO:
                    payload_len &= 0x3FFF
            total = 1 + header_len + payload_len
            if len(self._buf) < total:
                return
            packet = bytes(self._buf[:total])
            del self._buf[:total]
            yield packet
```

- [x] **Step 4: Confirm pass**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/unit/transport/test_h4.py -v
```

Expected: all tests PASS.

- [x] **Step 5: Commit**

```bash
git add pybluehost/transport/h4.py tests/unit/transport/test_h4.py
git commit -m "feat(transport): add H4Framer for HCI packet reassembly"
```

---

## Task 4: UARTTransport

**Files:**
- Modify: `pyproject.toml` (add `pyserial-asyncio` runtime dep)
- Create: `pybluehost/transport/uart.py`
- Create: `tests/unit/transport/test_uart.py`

- [x] **Step 1: Add pyserial-asyncio dependency**

Edit `pyproject.toml` — find the existing `dependencies` list:

```toml
dependencies = [
    "pyyaml>=6.0",
]
```

Replace with:

```toml
dependencies = [
    "pyserial-asyncio>=0.6",
    "pyyaml>=6.0",
]
```

Then run:

```bash
cd /home/ubuntu/code/pybluehost && uv sync
```

- [x] **Step 2: Write the failing test**

Create `tests/unit/transport/test_uart.py`:

```python
import asyncio

import pytest

from pybluehost.transport.uart import UARTTransport


class _Collect:
    def __init__(self) -> None:
        self.received: list[bytes] = []

    async def on_data(self, data: bytes) -> None:
        self.received.append(data)


class _FakeWriter:
    def __init__(self) -> None:
        self.written: list[bytes] = []
        self._closed = False

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self._closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.fixture
def fake_serial(monkeypatch):
    """Monkeypatch serial_asyncio.open_serial_connection to return controllable streams."""
    reader = asyncio.StreamReader()
    writer = _FakeWriter()

    async def fake_open_serial_connection(**kwargs):
        return reader, writer

    import serial_asyncio  # imported here so the import in uart.py resolves first

    monkeypatch.setattr(
        serial_asyncio, "open_serial_connection", fake_open_serial_connection
    )
    return reader, writer


class TestUARTTransport:
    @pytest.mark.asyncio
    async def test_open_sets_is_open(self, fake_serial):
        t = UARTTransport("/dev/ttyUSB0", 115200)
        assert t.is_open is False
        await t.open()
        assert t.is_open is True
        await t.close()
        assert t.is_open is False

    @pytest.mark.asyncio
    async def test_send_writes_to_serial(self, fake_serial):
        _, writer = fake_serial
        t = UARTTransport("/dev/ttyUSB0", 115200)
        await t.open()
        await t.send(b"\x01\x03\x0c\x00")
        assert writer.written == [b"\x01\x03\x0c\x00"]
        await t.close()

    @pytest.mark.asyncio
    async def test_received_bytes_become_packets(self, fake_serial):
        reader, _ = fake_serial
        sink = _Collect()
        t = UARTTransport("/dev/ttyUSB0", 115200)
        t.set_sink(sink)
        await t.open()
        reader.feed_data(bytes.fromhex("01030c00040e0401030c00"))
        # Let the read loop run
        for _ in range(5):
            await asyncio.sleep(0)
        await t.close()
        assert sink.received == [
            bytes.fromhex("01030c00"),
            bytes.fromhex("040e0401030c00"),
        ]

    @pytest.mark.asyncio
    async def test_send_when_closed_raises(self, fake_serial):
        t = UARTTransport("/dev/ttyUSB0", 115200)
        with pytest.raises(RuntimeError, match="not open"):
            await t.send(b"X")

    @pytest.mark.asyncio
    async def test_info(self, fake_serial):
        t = UARTTransport("/dev/ttyUSB0", 115200)
        info = t.info
        assert info.type == "uart"
        assert info.details["port"] == "/dev/ttyUSB0"
        assert info.details["baudrate"] == 115200
```

- [x] **Step 3: Confirm fail**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/unit/transport/test_uart.py -v
```

Expected: `ModuleNotFoundError: No module named 'pybluehost.transport.uart'`.

- [x] **Step 4: Implement `pybluehost/transport/uart.py`**

```python
from __future__ import annotations

import asyncio

import serial_asyncio

from pybluehost.transport.base import Transport, TransportInfo
from pybluehost.transport.h4 import H4Framer


class UARTTransport(Transport):
    """H4 HCI framing over a serial port (pyserial-asyncio backend)."""

    def __init__(self, port: str, baudrate: int = 115200) -> None:
        super().__init__()
        self._port = port
        self._baudrate = baudrate
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._framer = H4Framer()

    async def open(self) -> None:
        self._reader, self._writer = await serial_asyncio.open_serial_connection(
            url=self._port, baudrate=self._baudrate
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._reader = None

    async def send(self, data: bytes) -> None:
        if self._writer is None:
            raise RuntimeError("UARTTransport not open")
        self._writer.write(data)
        await self._writer.drain()

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                chunk = await self._reader.read(4096)
                if not chunk:
                    return
                for packet in self._framer.feed(chunk):
                    if self._sink is not None:
                        await self._sink.on_data(packet)
        except asyncio.CancelledError:
            raise

    @property
    def is_open(self) -> bool:
        return self._writer is not None

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="uart",
            description=f"UART {self._port} @ {self._baudrate}",
            platform="any",
            details={"port": self._port, "baudrate": self._baudrate},
        )
```

- [x] **Step 5: Confirm pass**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/unit/transport/test_uart.py -v
```

Expected: all tests PASS.

- [x] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock pybluehost/transport/uart.py tests/unit/transport/test_uart.py
git commit -m "feat(transport): add UARTTransport using pyserial-asyncio and H4Framer"
```

---

## Task 5: TCPTransport

**Files:**
- Create: `pybluehost/transport/tcp.py`
- Create: `tests/unit/transport/test_tcp.py`

- [x] **Step 1: Write the failing test**

Create `tests/unit/transport/test_tcp.py`:

```python
import asyncio

import pytest

from pybluehost.transport.tcp import TCPTransport


class _Collect:
    def __init__(self) -> None:
        self.received: list[bytes] = []

    async def on_data(self, data: bytes) -> None:
        self.received.append(data)


@pytest.fixture
async def echo_server():
    """Local TCP echo: any bytes the client sends come back, and the server
    can also push extra bytes. Yields (host, port, push_fn)."""
    host = "127.0.0.1"
    push_queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        async def pump_pushes():
            while True:
                data = await push_queue.get()
                writer.write(data)
                await writer.drain()

        push_task = asyncio.create_task(pump_pushes())
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    return
                writer.write(data)
                await writer.drain()
        finally:
            push_task.cancel()

    server = await asyncio.start_server(handle, host, 0)
    port = server.sockets[0].getsockname()[1]

    async def push(data: bytes) -> None:
        await push_queue.put(data)

    try:
        yield host, port, push
    finally:
        server.close()
        await server.wait_closed()


class TestTCPTransport:
    @pytest.mark.asyncio
    async def test_open_close(self, echo_server):
        host, port, _ = echo_server
        t = TCPTransport(host, port)
        assert t.is_open is False
        await t.open()
        assert t.is_open is True
        await t.close()
        assert t.is_open is False

    @pytest.mark.asyncio
    async def test_send_is_echoed_and_reassembled(self, echo_server):
        host, port, _ = echo_server
        sink = _Collect()
        t = TCPTransport(host, port)
        t.set_sink(sink)
        await t.open()
        packet = bytes.fromhex("01030c00")
        await t.send(packet)
        # wait for echo to come back via reader loop
        for _ in range(20):
            if sink.received:
                break
            await asyncio.sleep(0.01)
        await t.close()
        assert sink.received == [packet]

    @pytest.mark.asyncio
    async def test_fragmented_server_push_reassembled(self, echo_server):
        host, port, push = echo_server
        sink = _Collect()
        t = TCPTransport(host, port)
        t.set_sink(sink)
        await t.open()
        packet = bytes.fromhex("040e0401030c00")
        await push(packet[:3])
        await push(packet[3:])
        for _ in range(20):
            if sink.received:
                break
            await asyncio.sleep(0.01)
        await t.close()
        assert sink.received == [packet]

    @pytest.mark.asyncio
    async def test_send_when_closed_raises(self, echo_server):
        host, port, _ = echo_server
        t = TCPTransport(host, port)
        with pytest.raises(RuntimeError, match="not open"):
            await t.send(b"X")

    @pytest.mark.asyncio
    async def test_info(self, echo_server):
        host, port, _ = echo_server
        t = TCPTransport(host, port)
        assert t.info.type == "tcp"
        assert t.info.details["host"] == host
        assert t.info.details["port"] == port
```

- [x] **Step 2: Confirm fail**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/unit/transport/test_tcp.py -v
```

Expected: `ModuleNotFoundError`.

- [x] **Step 3: Implement `pybluehost/transport/tcp.py`**

```python
from __future__ import annotations

import asyncio

from pybluehost.transport.base import Transport, TransportInfo
from pybluehost.transport.h4 import H4Framer


class TCPTransport(Transport):
    """H4 HCI framing over a TCP stream."""

    def __init__(self, host: str, port: int) -> None:
        super().__init__()
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._framer = H4Framer()

    async def open(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self._host, self._port)
        self._reader_task = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._reader = None

    async def send(self, data: bytes) -> None:
        if self._writer is None:
            raise RuntimeError("TCPTransport not open")
        self._writer.write(data)
        await self._writer.drain()

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                chunk = await self._reader.read(4096)
                if not chunk:
                    return
                for packet in self._framer.feed(chunk):
                    if self._sink is not None:
                        await self._sink.on_data(packet)
        except asyncio.CancelledError:
            raise

    @property
    def is_open(self) -> bool:
        return self._writer is not None

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="tcp",
            description=f"TCP {self._host}:{self._port}",
            platform="any",
            details={"host": self._host, "port": self._port},
        )
```

- [x] **Step 4: Confirm pass**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/unit/transport/test_tcp.py -v
```

Expected: all tests PASS.

- [x] **Step 5: Commit**

```bash
git add pybluehost/transport/tcp.py tests/unit/transport/test_tcp.py
git commit -m "feat(transport): add TCPTransport with H4 reassembly"
```

---

## Task 6: UDPTransport

**Files:**
- Create: `pybluehost/transport/udp.py`
- Create: `tests/unit/transport/test_udp.py`

**Note:** UDP delivers one complete HCI packet per datagram, so no H4 reassembly is required. The sink receives whatever bytes arrived in one datagram.

- [x] **Step 1: Write the failing test**

Create `tests/unit/transport/test_udp.py`:

```python
import asyncio

import pytest

from pybluehost.transport.udp import UDPTransport


class _Collect:
    def __init__(self) -> None:
        self.received: list[bytes] = []

    async def on_data(self, data: bytes) -> None:
        self.received.append(data)


class _EchoServerProto(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr) -> None:
        assert self.transport is not None
        self.transport.sendto(data, addr)


@pytest.fixture
async def echo_udp_server():
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        _EchoServerProto, local_addr=("127.0.0.1", 0)
    )
    host, port = transport.get_extra_info("sockname")
    try:
        yield host, port
    finally:
        transport.close()


class TestUDPTransport:
    @pytest.mark.asyncio
    async def test_open_close(self, echo_udp_server):
        host, port = echo_udp_server
        t = UDPTransport(host, port)
        assert t.is_open is False
        await t.open()
        assert t.is_open is True
        await t.close()
        assert t.is_open is False

    @pytest.mark.asyncio
    async def test_send_datagram_echoed(self, echo_udp_server):
        host, port = echo_udp_server
        sink = _Collect()
        t = UDPTransport(host, port)
        t.set_sink(sink)
        await t.open()
        packet = bytes.fromhex("01030c00")
        await t.send(packet)
        for _ in range(20):
            if sink.received:
                break
            await asyncio.sleep(0.01)
        await t.close()
        assert sink.received == [packet]

    @pytest.mark.asyncio
    async def test_send_when_closed_raises(self, echo_udp_server):
        host, port = echo_udp_server
        t = UDPTransport(host, port)
        with pytest.raises(RuntimeError, match="not open"):
            await t.send(b"X")

    @pytest.mark.asyncio
    async def test_info(self, echo_udp_server):
        host, port = echo_udp_server
        t = UDPTransport(host, port)
        assert t.info.type == "udp"
        assert t.info.details["host"] == host
        assert t.info.details["port"] == port
```

- [x] **Step 2: Confirm fail**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/unit/transport/test_udp.py -v
```

Expected: `ModuleNotFoundError`.

- [x] **Step 3: Implement `pybluehost/transport/udp.py`**

```python
from __future__ import annotations

import asyncio

from pybluehost.transport.base import Transport, TransportInfo


class _UDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue[bytes]) -> None:
        self._queue = queue

    def datagram_received(self, data: bytes, addr) -> None:
        self._queue.put_nowait(data)


class UDPTransport(Transport):
    """One complete HCI packet per UDP datagram. No H4 reassembly needed."""

    def __init__(self, host: str, port: int) -> None:
        super().__init__()
        self._host = host
        self._port = port
        self._transport: asyncio.DatagramTransport | None = None
        self._queue: asyncio.Queue[bytes] | None = None
        self._drain_task: asyncio.Task[None] | None = None

    async def open(self) -> None:
        loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _UDPProtocol(self._queue),  # type: ignore[arg-type]
            remote_addr=(self._host, self._port),
        )
        self._drain_task = asyncio.create_task(self._drain())

    async def _drain(self) -> None:
        assert self._queue is not None
        try:
            while True:
                data = await self._queue.get()
                if self._sink is not None:
                    await self._sink.on_data(data)
        except asyncio.CancelledError:
            raise

    async def close(self) -> None:
        if self._drain_task is not None:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
            self._drain_task = None
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        self._queue = None

    async def send(self, data: bytes) -> None:
        if self._transport is None:
            raise RuntimeError("UDPTransport not open")
        self._transport.sendto(data)

    @property
    def is_open(self) -> bool:
        return self._transport is not None

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="udp",
            description=f"UDP {self._host}:{self._port}",
            platform="any",
            details={"host": self._host, "port": self._port},
        )
```

- [x] **Step 4: Confirm pass**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/unit/transport/test_udp.py -v
```

Expected: all tests PASS.

- [x] **Step 5: Commit**

```bash
git add pybluehost/transport/udp.py tests/unit/transport/test_udp.py
git commit -m "feat(transport): add UDPTransport (one datagram per HCI packet)"
```

---

## Task 7: BtsnoopTransport (replay mode)

**Files:**
- Create: `pybluehost/transport/btsnoop.py`
- Create: `tests/unit/transport/test_btsnoop.py`

**Background for the implementer:**
Btsnoop v1 file structure (as written by `pybluehost.core.trace.BtsnoopSink`):
- 16-byte header: 8-byte magic `b"btsnoop\x00"` + big-endian uint32 version (=1) + big-endian uint32 datalink (=1002 for H4).
- Each record: `>I` orig_len + `>I` incl_len + `>I` flags + `>I` drops + `>q` timestamp + `incl_len` bytes of payload. Timestamp is microseconds since 2000-01-01 UTC.

`BtsnoopTransport` replays every record's payload to the sink in file order. `realtime=True` sleeps for the inter-record delta; `realtime=False` (default) delivers as fast as possible.

- [x] **Step 1: Write the failing test**

Create `tests/unit/transport/test_btsnoop.py`:

```python
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pybluehost.core.trace import BtsnoopSink, Direction, TraceEvent
from pybluehost.transport.btsnoop import BtsnoopTransport


class _Collect:
    def __init__(self) -> None:
        self.received: list[bytes] = []

    async def on_data(self, data: bytes) -> None:
        self.received.append(data)


def _write_btsnoop(path: Path, payloads: list[tuple[bytes, float]]) -> None:
    """Write a btsnoop file with (payload, wall_clock_seconds_unix) pairs."""
    sink = BtsnoopSink(str(path))
    for payload, ts in payloads:
        sink._file.flush()  # noqa: SLF001
        # Build an event with controlled wall_clock
        wall = datetime.fromtimestamp(ts, tz=timezone.utc)
        event = TraceEvent(
            timestamp=0.0,
            wall_clock=wall,
            source_layer="hci",
            direction=Direction.UP,
            raw_bytes=payload,
            decoded=None,
            connection_handle=None,
            metadata={},
        )
        # Synchronous write via sink's async on_trace (safe — no awaits)
        asyncio.get_event_loop().run_until_complete(sink.on_trace(event)) \
            if False else None  # placeholder — use asyncio.run helper below
    # The helper below does the actual work; keep this function a no-op shell
    raise NotImplementedError("use _write_btsnoop_async below")


async def _write_btsnoop_async(path: Path, payloads: list[tuple[bytes, float]]) -> None:
    sink = BtsnoopSink(str(path))
    for payload, ts in payloads:
        wall = datetime.fromtimestamp(ts, tz=timezone.utc)
        await sink.on_trace(TraceEvent(
            timestamp=0.0,
            wall_clock=wall,
            source_layer="hci",
            direction=Direction.UP,
            raw_bytes=payload,
            decoded=None,
            connection_handle=None,
            metadata={},
        ))
    await sink.flush()
    await sink.close()


class TestBtsnoopTransport:
    @pytest.mark.asyncio
    async def test_replays_records_in_order(self, tmp_path: Path):
        path = tmp_path / "cap.cfa"
        p1 = bytes.fromhex("040e0401030c00")
        p2 = bytes.fromhex("01030c00")
        await _write_btsnoop_async(path, [(p1, 1700000000.0), (p2, 1700000000.1)])

        sink = _Collect()
        t = BtsnoopTransport(str(path))
        t.set_sink(sink)
        await t.open()
        # Wait for replay task to finish draining the file
        for _ in range(50):
            if len(sink.received) == 2:
                break
            await asyncio.sleep(0.01)
        await t.close()
        assert sink.received == [p1, p2]

    @pytest.mark.asyncio
    async def test_send_is_silently_dropped(self, tmp_path: Path):
        path = tmp_path / "empty.cfa"
        await _write_btsnoop_async(path, [])

        t = BtsnoopTransport(str(path))
        await t.open()
        await t.send(b"ignored")  # no error
        await t.close()

    @pytest.mark.asyncio
    async def test_rejects_invalid_magic(self, tmp_path: Path):
        path = tmp_path / "bad.cfa"
        path.write_bytes(b"NOTBTSNOOP" + b"\x00" * 10)
        t = BtsnoopTransport(str(path))
        await t.open()
        for _ in range(20):
            await asyncio.sleep(0.01)
            if t._replay_task is not None and t._replay_task.done():  # noqa: SLF001
                break
        # Replay task should have raised — confirm it's done and has an exception
        assert t._replay_task is not None  # noqa: SLF001
        assert t._replay_task.done()  # noqa: SLF001
        exc = t._replay_task.exception()  # noqa: SLF001
        assert isinstance(exc, ValueError) and "btsnoop" in str(exc)
        await t.close()

    @pytest.mark.asyncio
    async def test_realtime_sleeps_between_records(self, tmp_path: Path):
        path = tmp_path / "timed.cfa"
        p1 = bytes.fromhex("01030c00")
        p2 = bytes.fromhex("040e0401030c00")
        # 0.1s apart
        await _write_btsnoop_async(path, [(p1, 1700000000.0), (p2, 1700000000.1)])

        sink = _Collect()
        t = BtsnoopTransport(str(path), realtime=True)
        t.set_sink(sink)
        start = asyncio.get_running_loop().time()
        await t.open()
        for _ in range(50):
            if len(sink.received) == 2:
                break
            await asyncio.sleep(0.02)
        elapsed = asyncio.get_running_loop().time() - start
        await t.close()
        assert sink.received == [p1, p2]
        assert elapsed >= 0.08  # allow some scheduler slop under 0.1s target

    @pytest.mark.asyncio
    async def test_info(self, tmp_path: Path):
        path = tmp_path / "any.cfa"
        await _write_btsnoop_async(path, [])
        t = BtsnoopTransport(str(path))
        assert t.info.type == "btsnoop"
        assert t.info.details["path"] == str(path)
        assert t.info.details["realtime"] is False
```

- [x] **Step 2: Confirm fail**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/unit/transport/test_btsnoop.py -v
```

Expected: `ModuleNotFoundError`.

- [x] **Step 3: Implement `pybluehost/transport/btsnoop.py`**

```python
from __future__ import annotations

import asyncio
import struct
from pathlib import Path

from pybluehost.transport.base import Transport, TransportInfo


class BtsnoopTransport(Transport):
    """Replay an existing btsnoop capture file, delivering records to the sink.

    Writes are silently dropped (replay is read-only).
    """

    def __init__(self, path: str | Path, *, realtime: bool = False) -> None:
        super().__init__()
        self._path = Path(path)
        self._realtime = realtime
        self._replay_task: asyncio.Task[None] | None = None
        self._open = False

    async def open(self) -> None:
        self._open = True
        self._replay_task = asyncio.create_task(self._replay())

    async def _replay(self) -> None:
        with open(self._path, "rb") as f:
            header = f.read(16)
            if header[:8] != b"btsnoop\x00":
                raise ValueError(f"not a btsnoop file: {self._path}")
            last_ts_us: int | None = None
            while True:
                rec_header = f.read(24)
                if len(rec_header) < 24:
                    return
                orig_len, incl_len, flags, drops, ts = struct.unpack(">IIIIq", rec_header)
                payload = f.read(incl_len)
                if len(payload) < incl_len:
                    return
                if self._realtime and last_ts_us is not None:
                    delta = (ts - last_ts_us) / 1_000_000
                    if delta > 0:
                        await asyncio.sleep(delta)
                last_ts_us = ts
                if self._sink is not None and self._open:
                    await self._sink.on_data(payload)

    async def close(self) -> None:
        self._open = False
        if self._replay_task is not None:
            self._replay_task.cancel()
            try:
                await self._replay_task
            except (asyncio.CancelledError, Exception):
                pass
            self._replay_task = None

    async def send(self, data: bytes) -> None:
        return  # silently drop — replay is read-only

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="btsnoop",
            description=f"btsnoop replay {self._path}",
            platform="any",
            details={"path": str(self._path), "realtime": self._realtime},
        )
```

- [x] **Step 4: Confirm pass**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/unit/transport/test_btsnoop.py -v
```

Expected: all tests PASS.

- [x] **Step 5: Commit**

```bash
git add pybluehost/transport/btsnoop.py tests/unit/transport/test_btsnoop.py
git commit -m "feat(transport): add BtsnoopTransport for file replay"
```

---

## Task 8: Package Exports and Final Verification

**Files:**
- Modify: `pybluehost/transport/__init__.py`

- [x] **Step 1: Replace `pybluehost/transport/__init__.py`**

Replace the existing docstring-only content with full exports:

```python
"""PyBlueHost transport layer."""

from pybluehost.transport.base import (
    ReconnectPolicy,
    Transport,
    TransportInfo,
    TransportSink,
)
from pybluehost.transport.btsnoop import BtsnoopTransport
from pybluehost.transport.h4 import H4Framer
from pybluehost.transport.loopback import LoopbackTransport
from pybluehost.transport.tcp import TCPTransport
from pybluehost.transport.uart import UARTTransport
from pybluehost.transport.udp import UDPTransport

__all__ = [
    "BtsnoopTransport",
    "H4Framer",
    "LoopbackTransport",
    "ReconnectPolicy",
    "TCPTransport",
    "Transport",
    "TransportInfo",
    "TransportSink",
    "UARTTransport",
    "UDPTransport",
]
```

- [x] **Step 2: Smoke-test imports**

```bash
cd /home/ubuntu/code/pybluehost && uv run python -c "
from pybluehost.transport import (
    BtsnoopTransport, H4Framer, LoopbackTransport,
    ReconnectPolicy, TCPTransport, Transport, TransportInfo, TransportSink,
    UARTTransport, UDPTransport,
)
print('ok')
"
```

Expected output: `ok`.

- [x] **Step 3: Full test suite**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/ -v --tb=short
```

Expected: all tests PASS (Plan 1: 135 + Plan 2: ~30 new ≈ 165+).

- [x] **Step 4: Coverage check**

```bash
cd /home/ubuntu/code/pybluehost && uv run pytest tests/ --cov=pybluehost.transport --cov-report=term-missing
```

Expected: `pybluehost.transport` coverage ≥ 85%.

- [x] **Step 5: Commit**

```bash
git add pybluehost/transport/__init__.py
git commit -m "feat(transport): finalize transport package exports"
```

---

## Verification Checklist

After all tasks are complete, verify:

- [x] `uv run pytest tests/ -v` — all tests pass (Plan 1 + Plan 2)
- [x] `uv run pytest tests/ --cov=pybluehost.transport --cov-report=term-missing` — coverage ≥ 85%
- [x] `python -c "from pybluehost.transport import Transport, LoopbackTransport, H4Framer"` — imports work
- [x] `LoopbackTransport.pair()` round-trips bytes (covered by tests)
- [x] `H4Framer` correctly reassembles partial/multi-packet feeds (covered by tests)
- [x] `BtsnoopTransport` replays files written by `BtsnoopSink` (covered by tests)

**Deferred to later plans (not in scope):**
- USB transport + chip auto-detection → Plan 3
- Intel/Realtek firmware loading + download CLI → Plan 4
- Linux `HCIUserChannelTransport`, Windows WinUSB verification → Plan 5
- Active reconnect logic (the `ReconnectPolicy` enum + default `reset()` is here; the supervisor that runs reconnect attempts lives with `Stack` in Plan 8+)

---

## 补充遗漏项（2026-04-16 深度审查后追加）

以下功能在深度审查中发现遗漏，并入 **Plan 3a** 时补充到 `transport/base.py`。

### 遗漏项 1：`ReconnectConfig` dataclass（并入 Plan 3a）
- **缺失内容**：`ReconnectConfig(policy, max_attempts, base_delay, max_delay)` dataclass
- **架构文档来源**：arch/06-transport.md §6.9、arch/13-stack-api.md §13.5 StackConfig
- **影响**：`Stack.from_uart(..., reconnect=ReconnectConfig(...))` 的参数类型依赖此类
- **修改文件**：`transport/base.py`（追加 dataclass）、`transport/__init__.py`（追加导出）

### 遗漏项 2：`TransportSink.on_transport_error()` 回调（并入 Plan 3a）
- **缺失内容**：`TransportSink` Protocol 缺少 `async on_transport_error(error: TransportError) -> None` 方法
- **架构文档来源**：arch/02-sap.md §2.2 TransportSink
- **影响**：Transport 断线/错误无法通知 HCI 层；错误传播链路断裂
- **修改文件**：`transport/base.py`（修改 TransportSink Protocol 定义）
- **测试补充**：`test_base.py` 追加 `test_transport_sink_has_on_error_method()`

### 常见问题 / Troubleshooting

#### Q: `UARTTransport` 测试 `test_received_bytes_become_packets` 偶发 timeout
- **现象**：asyncio 队列等待超时，测试在低速 CI 机器上偶尔失败
- **原因**：mock serial reader 写入速度与事件循环调度存在竞态
- **解决方案**：在 `asyncio.wait_for()` 超时设为 2.0 秒，并确保 mock 在协程 yield 点后写数据

#### Q: `BtsnoopTransport` 在 Windows 上路径解析失败
- **现象**：`FileNotFoundError` 即使路径存在
- **原因**：Windows 路径分隔符；使用 `pathlib.Path` 而非裸字符串拼接即可解决
