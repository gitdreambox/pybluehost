"""SPP (Serial Port Profile) — stream-oriented serial port emulation."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from pybluehost.classic.rfcomm import RFCOMMChannel, RFCOMMManager
from pybluehost.classic.sdp import SDPClient, SDPServer, make_rfcomm_service_record


# ---------------------------------------------------------------------------
# SPPConnection
# ---------------------------------------------------------------------------

@dataclass
class SPPConnection:
    """A single SPP connection wrapping an RFCOMM channel."""
    rfcomm_channel: RFCOMMChannel
    _recv_queue: asyncio.Queue[bytes] = field(default_factory=asyncio.Queue)

    def __post_init__(self) -> None:
        if hasattr(self.rfcomm_channel, "on_data"):
            self.rfcomm_channel.on_data(self._recv_queue.put_nowait)

    async def send(self, data: bytes) -> None:
        """Send data over the SPP connection."""
        await self.rfcomm_channel.send(data)

    async def recv(self, max_bytes: int = 4096) -> bytes:
        """Receive data from the SPP connection."""
        data = await self._recv_queue.get()
        return data[:max_bytes]

    async def close(self) -> None:
        """Close the SPP connection."""
        await self.rfcomm_channel.close()

    async def __aenter__(self) -> SPPConnection:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()


# ---------------------------------------------------------------------------
# SPPService (server side)
# ---------------------------------------------------------------------------

class SPPService:
    """SPP server: register SDP record + listen on RFCOMM channel."""

    def __init__(
        self,
        rfcomm: RFCOMMManager | None,
        sdp: SDPServer | None,
    ) -> None:
        self._rfcomm = rfcomm
        self._sdp = sdp
        self._handler: Callable[[SPPConnection], Awaitable[None]] | None = None
        self._sdp_handle: int | None = None

    async def register(self, channel: int = 1, name: str = "Serial Port") -> None:
        """Register the SPP service (SDP record + RFCOMM listener)."""
        if self._sdp is not None:
            record = make_rfcomm_service_record(
                service_uuid=0x1101, channel=channel, name=name,
            )
            self._sdp_handle = self._sdp.register(record)

        if self._rfcomm is not None:
            await self._rfcomm.listen(channel, self._on_connection)

    def on_connection(self, handler: Callable[[SPPConnection], Awaitable[None]]) -> None:
        """Set the handler for incoming SPP connections."""
        self._handler = handler

    async def _on_connection(self, rfcomm_channel: RFCOMMChannel) -> None:
        if self._handler is not None:
            conn = SPPConnection(rfcomm_channel=rfcomm_channel)
            await self._handler(conn)


# ---------------------------------------------------------------------------
# SPPClient
# ---------------------------------------------------------------------------

class SPPClient:
    """SPP client: discover and connect to remote SPP services."""

    def __init__(
        self,
        rfcomm: RFCOMMManager | None,
        sdp_client: SDPClient | None,
    ) -> None:
        self._rfcomm = rfcomm
        self._sdp_client = sdp_client

    async def connect(self, target: object) -> SPPConnection:
        """Connect to a remote SPP service.

        1. SDP: find_rfcomm_channel(target, UUID16(0x1101))
        2. RFCOMM: connect(acl_handle, channel)
        3. Wrap in SPPConnection
        """
        if self._sdp_client is None:
            raise NotImplementedError("Requires SDP client")
        if self._rfcomm is None:
            raise NotImplementedError("Requires RFCOMM manager")
        channel = await self._sdp_client.find_rfcomm_channel(target, 0x1101)
        if channel is None:
            raise RuntimeError("SPP service not found")
        rfcomm_channel = await self._rfcomm.connect(target, channel)
        return SPPConnection(rfcomm_channel=rfcomm_channel)
