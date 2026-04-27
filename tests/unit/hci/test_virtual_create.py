"""Tests for VirtualController.create() factory."""
from __future__ import annotations

import asyncio

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.hci.virtual import VirtualController
from pybluehost.transport.base import Transport


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
