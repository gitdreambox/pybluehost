"""IUT action layer — primitives shared by Phase 1 REPL and Phase 2 BTP tester.

See design spec §4. Each primitive maps 1:1 to a Stack/GAP/SMP/SDP call;
`IutSession` tracks state (active connections + last_handle for handle-elision)
so MMI prompts like "do X on the current connection" work without re-specifying.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pybluehost.ble.gatt import GATTClient
    from pybluehost.core.address import BDAddress
    from pybluehost.stack import Stack


@dataclass
class ConnInfo:
    """One connection in the IUT's session table (out-going + incoming)."""

    handle: int
    peer: "BDAddress | None"
    transport: str  # "le" | "classic"
    gatt_client: "GATTClient | None" = None  # central side only


@dataclass
class IutSession:
    """Cross-command state of the REPL (or BTP tester) session."""

    connections: dict[int, ConnInfo] = field(default_factory=dict)
    last_handle: int | None = None
    le_io_capability: int = 0x03  # NoInputNoOutput default
    classic_io_capability: int = 0x01  # DisplayYesNo default


class IutActions:
    """Drive PyBlueHost as a PTS IUT. Primitive set per design spec §4."""

    def __init__(self, stack: "Stack") -> None:
        self._stack = stack
        self._session = IutSession()
        # Register handler for incoming connections
        self._stack.on_connection_event(self._on_connection_event)

    # ---- LE advertising / scanning ---------------------------------------

    async def advertise(self, *, adv_type: int | None = None, data: bytes | None = None) -> None:
        """Start BLE advertising."""
        from pybluehost.ble.gap import AdvertisingConfig

        config = AdvertisingConfig()
        ad_data = data
        await self._stack.gap.ble_advertiser.start(config, ad_data=ad_data)

    async def stop_advertising(self) -> None:
        """Stop any active BLE advertising. Idempotent."""
        await self._stack.gap.ble_advertiser.stop()

    async def scan(self, *, active: bool = False, on_result: callable | None = None) -> None:
        """Start BLE scanning."""
        if on_result is not None:
            self._stack.gap.ble_scanner.on_result(on_result)
        await self._stack.gap.ble_scanner.start()

    async def stop_scan(self) -> None:
        """Stop any active BLE scanning. Idempotent."""
        await self._stack.gap.ble_scanner.stop()

    # ---- Connection management ------------------------------------------

    async def connect(self, addr: "BDAddress", *, le: bool = True) -> int:
        """Connect to a peer. Returns connection handle."""
        if le:
            client = await self._stack.connect_gatt(addr)
            handle = client.conn_handle
            conn = ConnInfo(handle=handle, peer=addr, transport="le", gatt_client=client)
        else:
            handle = await self._stack.connect_classic(addr)
            conn = ConnInfo(handle=handle, peer=addr, transport="classic", gatt_client=None)
        self._session.connections[handle] = conn
        self._session.last_handle = handle
        return handle

    async def disconnect(self, handle: int | None = None) -> None:
        """Disconnect a connection. If handle=None, use last_handle."""
        if handle is None:
            handle = self._session.last_handle
        if handle is None:
            raise ValueError("no active connection; specify <handle>")
        conn = self._session.connections.get(handle)
        if conn is None:
            raise ValueError(f"unknown handle 0x{handle:04X}")
        # Both LE and Classic use gap.disconnect
        await self._stack.gap.disconnect(handle)
        # Cleanup happens via on_connection_event handler asynchronously

    # ---- Pairing / encryption -------------------------------------------

    async def pair(
        self, handle: int | None = None, *, io_cap: str | None = None, mitm: bool = False
    ) -> None:
        """Initiate pairing on a connection."""
        target = handle if handle is not None else self._session.last_handle
        if target is None:
            raise ValueError("no active connection; specify <handle>")
        if io_cap is not None:
            self.set_io_cap(io_cap)
        if mitm:
            self._stack.config.security.auth_requirements |= 0x04  # MITM bit
            self._stack.config.security.mitm_required = True
        await self._stack.pair(target)

    async def encrypt(self, handle: int | None = None) -> None:
        """Enable encryption on a connection."""
        target = handle if handle is not None else self._session.last_handle
        if target is None:
            raise ValueError("no active connection; specify <handle>")
        conn = self._session.connections.get(target)
        if conn is not None and conn.transport == "classic":
            await self._stack.enable_classic_encryption(target)
        else:
            await self._stack.encrypt(target)

    _IO_CAP_NAMES = {
        "DisplayOnly": 0x00,
        "DisplayYesNo": 0x01,
        "KeyboardOnly": 0x02,
        "NoInputNoOutput": 0x03,
        "KeyboardDisplay": 0x04,
    }

    def set_io_cap(self, cap: str) -> None:
        """Set IO capability for next pairing."""
        if cap not in self._IO_CAP_NAMES:
            raise ValueError(
                f"unknown io_cap '{cap}'; choose one of {list(self._IO_CAP_NAMES.keys())}"
            )
        value = self._IO_CAP_NAMES[cap]
        self._session.le_io_capability = value
        self._stack.config.security.io_capability = value

    # ---- GATT server (peripheral role) ----------------------------------

    async def notify(self, char_handle: int, value: bytes, handle: int | None = None) -> None:
        """Send GATT notification."""
        target = handle if handle is not None else self._session.last_handle
        if target is None:
            raise ValueError("no active connection; specify <handle>")
        await self._stack.gatt_server.notify(char_handle, value, connections=[target])

    async def indicate(self, char_handle: int, value: bytes, handle: int | None = None) -> None:
        """Send GATT indication."""
        target = handle if handle is not None else self._session.last_handle
        if target is None:
            raise ValueError("no active connection; specify <handle>")
        await self._stack.gatt_server.indicate(char_handle, value, connection=target)

    # ---- GATT client (central role) ------------------------------------

    async def read(self, char_handle: int, handle: int | None = None) -> bytes:
        """Read a GATT characteristic (central role only)."""
        target = handle if handle is not None else self._session.last_handle
        if target is None:
            raise ValueError("no active connection; specify <handle>")
        conn = self._session.connections.get(target)
        if conn is None or conn.gatt_client is None:
            raise ValueError(f"handle 0x{target:04X} is not a central connection (no GATTClient)")
        return await conn.gatt_client.read_characteristic(char_handle)

    async def write(self, char_handle: int, value: bytes, handle: int | None = None) -> None:
        """Write a GATT characteristic (central role only)."""
        target = handle if handle is not None else self._session.last_handle
        if target is None:
            raise ValueError("no active connection; specify <handle>")
        conn = self._session.connections.get(target)
        if conn is None or conn.gatt_client is None:
            raise ValueError(f"handle 0x{target:04X} is not a central connection (no GATTClient)")
        await conn.gatt_client.write_characteristic(char_handle, value)

    # ---- Classic SDP / RFCOMM / L2CAP ----------------------------------

    async def sdp_browse(self, addr: "BDAddress", *, uuid: int | None = None) -> list:
        """Browse SDP on a peer."""
        if uuid is not None:
            return await self._stack.sdp.search(addr, uuid)
        return await self._stack.sdp.search_attributes(addr)

    async def rfcomm_open(self, addr: "BDAddress", channel: int) -> None:
        """Open RFCOMM channel to a peer."""
        # Ensure ACL exists
        existing_handle = None
        for h, c in self._session.connections.items():
            if c.peer == addr and c.transport == "classic":
                existing_handle = h
                break

        if existing_handle is None:
            handle = await self._stack.connect_classic(addr)
            self._session.connections[handle] = ConnInfo(
                handle=handle, peer=addr, transport="classic", gatt_client=None
            )
            self._session.last_handle = handle
        else:
            handle = existing_handle

        await self._stack.rfcomm.connect(handle, channel)

    async def l2cap_connect(self, addr: "BDAddress", psm: int) -> None:
        """Open L2CAP channel to a peer."""
        # Ensure ACL exists
        existing_handle = None
        for h, c in self._session.connections.items():
            if c.peer == addr:
                existing_handle = h
                break

        if existing_handle is None:
            handle = await self._stack.connect_classic(addr)
            self._session.connections[handle] = ConnInfo(
                handle=handle, peer=addr, transport="classic", gatt_client=None
            )
            self._session.last_handle = handle
        else:
            handle = existing_handle

        await self._stack.l2cap.connect(handle, psm)

    # ---- Session inspection ---------------------------------------------

    def status(self) -> IutSession:
        """Return current session snapshot."""
        return self._session

    # ---- Internal event handlers ----------------------------------------

    def _on_connection_event(self, event) -> None:
        """Handle incoming connections and disconnections."""
        # StackConnectionEvent shape: state, handle, reason
        if event.state == "connected" and event.handle is not None:
            if event.handle not in self._session.connections:
                # Incoming connection (peripheral side)
                self._session.connections[event.handle] = ConnInfo(
                    handle=event.handle, peer=None, transport="le", gatt_client=None
                )
                self._session.last_handle = event.handle
        elif event.state == "disconnected" and event.handle is not None:
            self._session.connections.pop(event.handle, None)
            if self._session.last_handle == event.handle:
                self._session.last_handle = None
