"""Virtual peer Stack for client-side commands without real hardware."""
from __future__ import annotations

import contextlib
from typing import AsyncIterator, Awaitable, Callable

from pybluehost.stack import Stack


@contextlib.asynccontextmanager
async def virtual_peer_with(
    server_factory: Callable[[object], Awaitable[None]],
) -> AsyncIterator[Stack]:
    """Spin up a second Stack on a virtual controller to act as a peer.

    Args:
        server_factory: async callable taking the GATTServer; registers profiles.

    Yields:
        Powered peer Stack. Caller can read peer.local_address as --target.
    """
    peer = await Stack.virtual()
    try:
        await server_factory(peer.gatt_server)
        yield peer
    finally:
        await peer.close()
