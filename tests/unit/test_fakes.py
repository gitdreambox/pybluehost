"""Tests for shared test fakes."""
from __future__ import annotations

import pytest

from tests.fakes.transport import FakeTransport
from tests.fakes.hci import FakeHCIDownstream
from tests.fakes.l2cap import FakeChannelEvents
from tests.fakes.trace import NullTrace


# ---------------------------------------------------------------------------
# FakeTransport
# ---------------------------------------------------------------------------

async def test_fake_transport_records_sends():
    t = FakeTransport()
    await t.send(b"\x01\x02")
    await t.send(b"\x03\x04")
    assert t.sent == [b"\x01\x02", b"\x03\x04"]


async def test_fake_transport_inject_calls_sink():
    t = FakeTransport()
    received: list[bytes] = []

    class Sink:
        async def on_transport_data(self, data: bytes) -> None:
            received.append(data)

    t.set_sink(Sink())
    await t.inject(b"\xAB\xCD")
    assert received == [b"\xAB\xCD"]


async def test_fake_transport_inject_no_sink():
    t = FakeTransport()
    await t.inject(b"\x01")  # should not raise


async def test_fake_transport_open_close():
    t = FakeTransport()
    assert not t.is_open
    await t.open()
    assert t.is_open
    await t.close()
    assert not t.is_open


async def test_fake_transport_clear():
    t = FakeTransport()
    await t.send(b"\x01")
    t.clear()
    assert t.sent == []


# ---------------------------------------------------------------------------
# FakeHCIDownstream
# ---------------------------------------------------------------------------

async def test_fake_hci_captures_commands():
    from pybluehost.hci.packets import HCI_Reset

    hci = FakeHCIDownstream()
    result = await hci.send_command(HCI_Reset())
    assert len(hci.commands) == 1
    assert type(hci.commands[0]).__name__ == "HCI_Reset"
    assert result.return_parameters[0] == 0  # SUCCESS


async def test_fake_hci_captures_acl_data():
    hci = FakeHCIDownstream()
    await hci.send_acl_data(handle=0x0040, pb_flag=0x02, data=b"\xAB")
    assert hci.acl_sent == [(0x0040, 0x02, b"\xAB")]


async def test_fake_hci_clear():
    from pybluehost.hci.packets import HCI_Reset

    hci = FakeHCIDownstream()
    await hci.send_command(HCI_Reset())
    await hci.send_acl_data(handle=1, pb_flag=0, data=b"")
    hci.clear()
    assert hci.commands == []
    assert hci.acl_sent == []


async def test_fake_hci_last_command_opcode():
    from pybluehost.hci.packets import HCI_Reset

    hci = FakeHCIDownstream()
    assert hci.last_command_opcode() is None
    await hci.send_command(HCI_Reset())
    assert hci.last_command_opcode() is not None


# ---------------------------------------------------------------------------
# FakeChannelEvents
# ---------------------------------------------------------------------------

async def test_fake_channel_events_on_data():
    events = FakeChannelEvents()
    await events.on_data(b"\x01\x02")
    assert events.received == [b"\x01\x02"]


async def test_fake_channel_events_on_close():
    events = FakeChannelEvents()
    await events.on_close()
    assert events.closed is True


async def test_fake_channel_events_on_mtu_changed():
    events = FakeChannelEvents()
    await events.on_mtu_changed(512)
    assert events.mtu_changed_to == 512


async def test_fake_channel_events_clear():
    events = FakeChannelEvents()
    await events.on_data(b"\x01")
    await events.on_close()
    await events.on_mtu_changed(256)
    events.clear()
    assert events.received == []
    assert events.closed is False
    assert events.mtu_changed_to is None


# ---------------------------------------------------------------------------
# NullTrace
# ---------------------------------------------------------------------------

def test_null_trace_does_not_raise():
    trace = NullTrace()
    trace.emit(None)  # type: ignore[arg-type]
    trace.add_sink(None)  # type: ignore[arg-type]
    # Should not raise
