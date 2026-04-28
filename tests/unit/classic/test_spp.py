"""Tests for the SPP (Serial Port Profile) module."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pybluehost.classic.spp import SPPClient, SPPConnection, SPPService


async def test_spp_connection_send():
    channel = MagicMock()
    channel.send = AsyncMock()
    conn = SPPConnection(rfcomm_channel=channel)
    await conn.send(b"hello")
    channel.send.assert_called_once_with(b"hello")


async def test_spp_connection_context_manager():
    channel = MagicMock()
    channel.send = AsyncMock()
    channel.close = AsyncMock()
    conn = SPPConnection(rfcomm_channel=channel)
    async with conn:
        await conn.send(b"test")
    channel.close.assert_called_once()


async def test_spp_connection_close():
    channel = MagicMock()
    channel.close = AsyncMock()
    conn = SPPConnection(rfcomm_channel=channel)
    await conn.close()
    channel.close.assert_called_once()


async def test_spp_connection_recv_gets_rfcomm_channel_data():
    from pybluehost.classic.rfcomm import RFCOMMChannel

    channel = RFCOMMChannel(dlci=2, session=None)
    conn = SPPConnection(rfcomm_channel=channel)

    await channel._on_data(b"hello")

    assert await conn.recv() == b"hello"


def test_spp_service_construction():
    svc = SPPService(rfcomm=None, sdp=None)
    assert svc is not None


def test_spp_client_construction():
    client = SPPClient(rfcomm=None, sdp_client=None)
    assert client is not None


async def test_spp_client_connect_uses_sdp_and_rfcomm():
    class FakeSDPClient:
        def __init__(self):
            self.calls = []

        async def find_rfcomm_channel(self, target, service_uuid):
            self.calls.append((target, service_uuid))
            return 5

    class FakeRFCOMM:
        def __init__(self):
            self.calls = []
            self.channel = MagicMock()

        async def connect(self, acl_handle, server_channel):
            self.calls.append((acl_handle, server_channel))
            return self.channel

    sdp = FakeSDPClient()
    rfcomm = FakeRFCOMM()
    client = SPPClient(rfcomm=rfcomm, sdp_client=sdp)

    conn = await client.connect(target=0x0042)

    assert sdp.calls == [(0x0042, 0x1101)]
    assert rfcomm.calls == [(0x0042, 5)]
    assert isinstance(conn, SPPConnection)
    assert conn.rfcomm_channel is rfcomm.channel


async def test_spp_client_connect_reports_missing_sdp_record():
    class FakeSDPClient:
        async def find_rfcomm_channel(self, target, service_uuid):
            return None

    client = SPPClient(rfcomm=MagicMock(), sdp_client=FakeSDPClient())

    with pytest.raises(RuntimeError, match="SPP service not found"):
        await client.connect(target=0x0042)
