# tests/unit/avctp/test_session.py
import asyncio

import pytest
import pytest_asyncio

from pybluehost.avctp.constants import AVRCP_PROFILE_UUID
from pybluehost.avctp.session import AVCTPSession


class _FakeChannel:
    def __init__(self) -> None:
        self._inbound: asyncio.Queue[bytes] = asyncio.Queue()
        self._peer: "_FakeChannel | None" = None

    def pair(self, peer: "_FakeChannel") -> None:
        self._peer = peer
        peer._peer = self

    async def send(self, data: bytes) -> None:
        await self._peer._inbound.put(bytes(data))

    async def recv(self) -> bytes:
        return await self._inbound.get()


@pytest_asyncio.fixture
async def paired_sessions():
    ch_a = _FakeChannel()
    ch_b = _FakeChannel()
    ch_a.pair(ch_b)

    received = []

    async def echo(payload: bytes) -> bytes:
        received.append(payload)
        return b"OK:" + payload

    sess_a = AVCTPSession(ch_a, profile_id=AVRCP_PROFILE_UUID)
    sess_b = AVCTPSession(ch_b, profile_id=AVRCP_PROFILE_UUID, on_command=echo)
    await sess_a.start()
    await sess_b.start()
    yield sess_a, sess_b, received
    await sess_a.stop()
    await sess_b.stop()


async def test_send_command_returns_peer_response(paired_sessions):
    sess_a, _sess_b, received = paired_sessions
    response = await sess_a.send_command(b"PLAY")
    assert response == b"OK:PLAY"
    assert received == [b"PLAY"]


async def test_transaction_label_wraps(paired_sessions):
    sess_a, _, _ = paired_sessions
    for i in range(20):
        resp = await sess_a.send_command(bytes([i & 0xFF]))
        assert resp == b"OK:" + bytes([i & 0xFF])


async def test_peer_command_without_handler_returns_ipid():
    """If a session has no on_command callback, incoming commands get an
    IPID=1 response (Invalid Profile ID)."""
    ch_a = _FakeChannel()
    ch_b = _FakeChannel()
    ch_a.pair(ch_b)
    sess_a = AVCTPSession(ch_a, profile_id=AVRCP_PROFILE_UUID)
    sess_b = AVCTPSession(ch_b, profile_id=AVRCP_PROFILE_UUID)   # no on_command
    await sess_a.start()
    await sess_b.start()
    try:
        with pytest.raises(RuntimeError, match="IPID"):
            await sess_a.send_command(b"PING")
    finally:
        await sess_a.stop()
        await sess_b.stop()
