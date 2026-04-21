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


def test_spp_service_construction():
    svc = SPPService(rfcomm=None, sdp=None)
    assert svc is not None


def test_spp_client_construction():
    client = SPPClient(rfcomm=None, sdp_client=None)
    assert client is not None
