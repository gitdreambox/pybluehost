"""L2CAP Channel abstractions: Channel ABC, ChannelState, ChannelEvents."""
from __future__ import annotations

import inspect
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


# ATT opcodes the local GATT *server* must answer (client→server requests and
# commands). Everything else (responses, notifications, indications,
# confirmations) is destined for the local GATT *client* bearer. Used to
# multiplex both roles onto the single ATT fixed channel — see
# install_att_channel_mux.
ATT_SERVER_REQUEST_OPCODES = frozenset({
    0x02,  # Exchange MTU Request
    0x04,  # Find Information Request
    0x06,  # Find By Type Value Request
    0x08,  # Read By Type Request
    0x0A,  # Read Request
    0x0C,  # Read Blob Request
    0x0E,  # Read Multiple Request
    0x10,  # Read By Group Type Request
    0x12,  # Write Request
    0x16,  # Prepare Write Request
    0x18,  # Execute Write Request
    0x20,  # Read Multiple Variable Length Request
    0x52,  # Write Command
    0xD2,  # Signed Write Command
})


def install_att_channel_mux(channel: "Channel") -> None:
    """Multiplex GATT client + server onto one ATT fixed channel.

    The ATT fixed channel has a single ``on_data`` callback, but a connection
    can be both a GATT server (PTS reads/writes our db) and a GATT client (we
    issue requests toward PTS) at once — PTS GAP/SEC cases do exactly this.
    Previously whichever of the server-bind / client-attach paths ran last
    called ``set_events`` and *replaced* the other, so the GATT server silently
    stopped answering once a client bearer attached (PTS would read a protected
    characteristic, get no response, and disconnect — GAP/SEC/AUT INDCSV).

    This installs one stable dispatcher that routes each inbound PDU by opcode:
    requests/commands go to the registered server handler, responses/
    notifications/indications to the client bearer. Handlers are looked up late
    (``_att_server_handler`` / ``_att_client_handler`` attributes on the
    channel), so each side registers independently, in any order, and an absent
    handler simply drops that side's PDUs. Idempotent.
    """
    if getattr(channel, "_att_mux_installed", False):
        return
    channel._att_server_handler = None  # type: ignore[attr-defined]
    channel._att_client_handler = None  # type: ignore[attr-defined]
    channel._att_confirmation_handler = None  # type: ignore[attr-defined]

    async def _mux_on_data(data: bytes) -> None:
        if not data:
            return
        if data[0] in ATT_SERVER_REQUEST_OPCODES:
            handler = channel._att_server_handler  # type: ignore[attr-defined]
        elif data[0] == 0x1E and channel._att_confirmation_handler is not None:  # type: ignore[attr-defined]
            # A Handle Value Confirmation belongs to the server's Service
            # Changed indication when the server owns this connection — route it
            # to the confirmation hook (clear change-unaware) before the client
            # bearer (which would just drop it).
            handler = channel._att_confirmation_handler  # type: ignore[attr-defined]
        else:
            handler = channel._att_client_handler  # type: ignore[attr-defined]
        if handler is not None:
            result = handler(data)
            if inspect.isawaitable(result):
                await result

    channel.set_events(SimpleChannelEvents(on_data=_mux_on_data))
    channel._att_mux_installed = True  # type: ignore[attr-defined]


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
