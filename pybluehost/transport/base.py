from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class TransportSink(Protocol):
    """Callback: how a transport delivers received bytes to a consumer."""

    async def on_data(self, data: bytes) -> None: ...


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
