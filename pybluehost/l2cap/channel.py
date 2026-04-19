"""L2CAP Channel abstractions: Channel ABC, ChannelState, ChannelEvents."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Protocol


class ChannelState(Enum):
    CLOSED = "closed"
    CONFIG = "config"  # Classic only: configuration phase
    OPEN = "open"
    DISCONNECTING = "disconnecting"


class ChannelEvents(Protocol):
    """Callbacks from a channel to its consumer."""

    async def on_data(self, data: bytes) -> None: ...
    async def on_close(self, reason: int) -> None: ...


@dataclass
class SimpleChannelEvents:
    """Simple implementation of ChannelEvents for testing."""

    on_data: Callable[[bytes], Awaitable[None] | None] | None = None
    on_close: Callable[[int], Awaitable[None] | None] | None = None


class Channel(ABC):
    """Abstract L2CAP channel."""

    @property
    @abstractmethod
    def cid(self) -> int: ...

    @property
    @abstractmethod
    def connection_handle(self) -> int: ...

    @property
    @abstractmethod
    def state(self) -> ChannelState: ...

    @property
    @abstractmethod
    def mtu(self) -> int: ...

    @abstractmethod
    async def send(self, data: bytes) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    def set_events(self, events: ChannelEvents | SimpleChannelEvents) -> None: ...

    @abstractmethod
    async def _on_pdu(self, data: bytes) -> None:
        """Called by L2CAPManager when a PDU arrives for this channel."""
        ...
