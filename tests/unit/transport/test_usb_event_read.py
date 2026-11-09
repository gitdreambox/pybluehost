"""The interrupt-IN read must be able to hold the largest HCI event.

A conformant ``HCI_Remote_Name_Request_Complete`` is::

    event code (1) + parameter total length (1)
    + Status (1) + BD_ADDR (6) + Name (248)  = 257 octets

The USB transport used to ask pyusb for 255 octets, so the controller's
257-octet event arrived two octets short and the name query failed with
"remote name completion truncated: 253 bytes (need >= 255)".  The same cap
silently clipped any other maximal event (LE Meta extended advertising
reports, for instance).
"""
from __future__ import annotations

import pytest

from pybluehost.transport.base import HCI_EVENT_READ_SIZE
from pybluehost.transport.usb.base import USBTransport

EVENT_CODE = 0x3F  # Remote_Name_Request_Complete
LARGEST_HCI_EVENT = 2 + 255  # event code + parameter total length + body


def _full_remote_name_event() -> bytes:
    """A 257-octet event whose 248-octet name array is completely filled."""
    name = b"JBL Live Beam 4".ljust(248, b"\x00")
    return bytes([EVENT_CODE, 255, 0x00]) + bytes.fromhex("a1b2c3d4e5f6") + name


class _RecordingSink:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    async def on_transport_data(self, data: bytes) -> None:
        self.chunks.append(data)

    async def on_transport_error(self, error: object) -> None:  # pragma: no cover - unused
        raise AssertionError("no transport error expected")


def _transport_under_test() -> USBTransport:
    """A USBTransport that never touches pyusb (``__init__`` opens a device)."""
    return USBTransport.__new__(USBTransport)


def test_event_read_size_fits_the_largest_hci_event():
    assert HCI_EVENT_READ_SIZE >= LARGEST_HCI_EVENT


async def test_read_interrupt_loop_asks_for_a_buffer_that_holds_a_full_event():
    transport = _transport_under_test()
    transport._is_open = True
    transport._sink = _RecordingSink()
    sizes: list[int] = []
    event = _full_remote_name_event()

    async def fake_read(size: int, timeout: float) -> bytes:
        sizes.append(size)
        transport._is_open = False  # exit the loop after one delivery
        return event

    transport.read_interrupt = fake_read  # type: ignore[method-assign]

    await transport._read_interrupt_loop()

    assert sizes == [HCI_EVENT_READ_SIZE]
    assert transport._sink.chunks == [b"\x04" + event]


async def test_wait_for_event_asks_for_a_buffer_that_holds_a_full_event():
    transport = _transport_under_test()
    sizes: list[int] = []
    event = _full_remote_name_event()

    async def fake_read(size: int, timeout: float) -> bytes:
        sizes.append(size)
        return event

    transport.read_interrupt = fake_read  # type: ignore[method-assign]

    assert await transport._wait_for_event(timeout=1.0) == event
    assert sizes == [HCI_EVENT_READ_SIZE]
