"""Tests for VirtualController.create() factory."""
from __future__ import annotations

import asyncio

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.hci.virtual import VirtualController, _HCIPipe
from pybluehost.transport.base import Transport


class _Collect:
    def __init__(self) -> None:
        self.received: list[bytes] = []

    async def on_transport_data(self, data: bytes) -> None:
        self.received.append(data)


@pytest.mark.asyncio
async def test_create_returns_vc_and_open_host_transport():
    vc, host_t = await VirtualController.create()

    assert isinstance(vc, VirtualController)
    assert isinstance(host_t, Transport)
    assert host_t.is_open


@pytest.mark.asyncio
async def test_create_accepts_explicit_address():
    addr = BDAddress.from_string("11:22:33:44:55:66")

    vc, _ = await VirtualController.create(address=addr)

    assert vc._address == addr


@pytest.mark.asyncio
async def test_create_default_address_when_none():
    vc, _ = await VirtualController.create()

    assert vc._address is not None
    assert str(vc._address) != "00:00:00:00:00:00"


@pytest.mark.asyncio
async def test_host_transport_round_trip_through_vc():
    """Sending HCI Reset via host transport gets Command Complete back."""
    _, host_t = await VirtualController.create()
    received: list[bytes] = []

    class _Sink:
        async def on_transport_data(self, data: bytes) -> None:
            received.append(data)

    host_t.set_sink(_Sink())

    await host_t.send(b"\x01\x03\x0c\x00")
    await asyncio.sleep(0.05)

    assert len(received) >= 1
    assert received[0][0] == 0x04
    assert received[0][1] == 0x0E


@pytest.mark.asyncio
async def test_hci_pipe_pair_delivers_bytes_bidirectionally():
    a, b = _HCIPipe.pair()
    sink_a = _Collect()
    sink_b = _Collect()
    a.set_sink(sink_a)
    b.set_sink(sink_b)
    await a.open()
    await b.open()

    await a.send(b"A")
    await b.send(b"B")

    assert sink_a.received == [b"B"]
    assert sink_b.received == [b"A"]


@pytest.mark.asyncio
async def test_hci_pipe_send_when_closed_raises():
    a, b = _HCIPipe.pair()
    await b.open()

    with pytest.raises(RuntimeError, match="not open"):
        await a.send(b"X")


@pytest.mark.asyncio
async def test_hci_pipe_send_when_peer_closed_is_dropped():
    a, b = _HCIPipe.pair()
    sink_b = _Collect()
    b.set_sink(sink_b)
    await a.open()

    await a.send(b"X")

    assert sink_b.received == []


@pytest.mark.asyncio
async def test_hci_pipe_solo_instance_has_no_peer():
    solo = _HCIPipe()
    await solo.open()

    with pytest.raises(RuntimeError, match="peer"):
        await solo.send(b"X")


def test_hci_pipe_info_identifies_virtual_transport():
    pipe, _ = _HCIPipe.pair()

    assert pipe.info.type == "virtual"
    assert pipe.info.description == "VirtualController pipe"
