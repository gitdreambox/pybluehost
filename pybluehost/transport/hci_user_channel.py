"""Linux-only: raw HCI access via AF_BLUETOOTH hci_user_channel socket."""

from __future__ import annotations

import asyncio
import socket
import struct
import subprocess
import sys
from typing import Any

from pybluehost.transport.base import Transport, TransportInfo
from pybluehost.core.errors import TransportError

# Linux Bluetooth socket constants
AF_BLUETOOTH = 31
BTPROTO_HCI = 1
HCI_CHANNEL_USER = 1


class HCIUserChannelTransport(Transport):
    """Linux-only: raw HCI access via AF_BLUETOOTH hci_user_channel socket.

    This bypasses the kernel's Bluetooth stack entirely, giving the user
    full control over the HCI interface. Requires root or CAP_NET_RAW.

    The HCI device must be brought down (``hciconfig hciN down``) before
    binding to the user channel.
    """

    def __init__(self, hci_index: int = 0) -> None:
        super().__init__()
        if sys.platform != "linux":
            raise RuntimeError("HCIUserChannelTransport is only available on Linux")
        self._hci_index = hci_index
        self._sock: socket.socket | None = None
        self._is_open = False
        self._reader_task: asyncio.Task | None = None  # type: ignore[type-arg]

    async def open(self) -> None:
        """Open the HCI user channel socket.

        1. Bring the HCI interface down (hciconfig hciN down)
        2. Create AF_BLUETOOTH socket
        3. Bind to (hci_index, HCI_CHANNEL_USER)
        4. Start async reader task
        """
        # Bring interface down so kernel releases it
        try:
            subprocess.run(
                ["hciconfig", f"hci{self._hci_index}", "down"],
                check=True,
                capture_output=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise TransportError(
                f"Failed to bring hci{self._hci_index} down: {exc}"
            ) from exc

        # Create raw HCI socket
        try:
            self._sock = socket.socket(AF_BLUETOOTH, socket.SOCK_RAW, BTPROTO_HCI)
            # Bind to (hci_index, HCI_CHANNEL_USER)
            # struct sockaddr_hci { sa_family_t hci_family; uint16_t hci_dev; uint16_t hci_channel; }
            self._sock.bind((self._hci_index, HCI_CHANNEL_USER))
            self._sock.setblocking(False)
        except OSError as exc:
            if self._sock:
                self._sock.close()
                self._sock = None
            raise TransportError(
                f"Failed to open hci_user_channel for hci{self._hci_index}: {exc}. "
                "Ensure you have root or CAP_NET_RAW."
            ) from exc

        self._is_open = True

        # Start async reader
        loop = asyncio.get_running_loop()
        self._reader_task = asyncio.create_task(self._read_loop(loop))

    async def close(self) -> None:
        """Close the socket and cancel the reader task."""
        self._is_open = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._sock:
            self._sock.close()
            self._sock = None

    async def send(self, data: bytes) -> None:
        """Send raw HCI data through the user channel socket."""
        if not self._is_open or not self._sock:
            raise RuntimeError("Transport is not open")
        loop = asyncio.get_running_loop()
        await loop.sock_sendall(self._sock, data)

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="hci_user_channel",
            description=f"Linux HCI User Channel: hci{self._hci_index}",
            platform="linux",
            details={"hci_index": self._hci_index},
        )

    async def _read_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Continuously read from the socket and forward to sink."""
        assert self._sock is not None
        try:
            while self._is_open:
                try:
                    data = await loop.sock_recv(self._sock, 4096)
                    if not data:
                        break
                    if self._sink:
                        await self._sink.on_transport_data(data)
                except OSError as exc:
                    if self._is_open:
                        await self._notify_error(
                            TransportError(f"HCI read error: {exc}")
                        )
                    break
        except asyncio.CancelledError:
            pass
