from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from pybluehost.core.errors import TransportError


class TransportSink(Protocol):
    """Callback: how a transport delivers received bytes to a consumer."""

    async def on_data(self, data: bytes) -> None: ...

    async def on_transport_error(self, error: TransportError) -> None: ...


@dataclass(frozen=True)
class TransportInfo:
    type: str
    description: str
    platform: str
    details: dict[str, Any]


class ReconnectPolicy(Enum):
    NONE = "none"
    IMMEDIATE = "immediate"
    EXPONENTIAL = "exponential"


@dataclass(frozen=True)
class ReconnectConfig:
    policy: ReconnectPolicy = ReconnectPolicy.NONE
    max_attempts: int = 5
    base_delay: float = 1.0
    max_delay: float = 60.0


class Transport(ABC):
    """Abstract transport. Subclasses implement open/close/send and expose is_open/info."""

    def __init__(self) -> None:
        self._sink: TransportSink | None = None

    @abstractmethod
    async def open(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def send(self, data: bytes) -> None: ...

    @property
    @abstractmethod
    def is_open(self) -> bool: ...

    @property
    @abstractmethod
    def info(self) -> TransportInfo: ...

    def set_sink(self, sink: TransportSink | None) -> None:
        self._sink = sink

    async def reset(self) -> None:
        """Default reconnect: close then open. Subclasses may override."""
        await self.close()
        await self.open()

    async def _notify_error(self, error: TransportError) -> None:
        """Notify the sink of a transport error if it supports on_transport_error."""
        if self._sink is not None and hasattr(self._sink, "on_transport_error"):
            await self._sink.on_transport_error(error)
