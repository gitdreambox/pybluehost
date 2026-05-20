"""BR/EDR (Classic) loopback bridge: two VirtualControllers paired peer-to-peer.

Counterpart to VirtualLELink. Bridges inquiry, connection, ACL, SSP/Legacy
authentication, encryption, and disconnect HCI events so two Stack.virtual()
instances can complete real peer-to-peer Classic workflows end-to-end.
"""
from __future__ import annotations

import asyncio
import hashlib
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    EventCode,
    HCI_ACCEPT_CONNECTION_REQ,
    HCI_AUTH_REQUESTED,
    HCI_CREATE_CONNECTION,
    HCI_DISCONNECT,
    HCI_INQUIRY,
    HCI_INQUIRY_CANCEL,
    HCI_IO_CAPABILITY_REQUEST_REPLY,
    HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY,
    HCI_LINK_KEY_REQUEST_REPLY,
    HCI_PIN_CODE_REQUEST_NEGATIVE_REPLY,
    HCI_PIN_CODE_REQUEST_REPLY,
    HCI_REJECT_CONNECTION_REQ,
    HCI_SET_CONNECTION_ENCRYPTION,
    HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY,
    HCI_USER_CONFIRMATION_REQUEST_REPLY,
)
from pybluehost.hci.packets import HCIACLData, HCIEvent
from pybluehost.hci.virtual import VirtualController


class _ConnState(IntEnum):
    NONE = 0
    PENDING = 1
    CONNECTED = 2
    DISCONNECTING = 3


@dataclass
class _ConnEntry:
    handle: int
    state: _ConnState
    initiator: VirtualController
    initiator_addr: BDAddress
    acceptor: VirtualController
    acceptor_addr: BDAddress


@dataclass
class VirtualClassicLink:
    """Two-controller BR/EDR bridge. See module docstring."""

    central: VirtualController
    peripheral: VirtualController
    central_address: BDAddress
    peripheral_address: BDAddress
    page_timeout_seconds: float = 0.1
    _handles: dict = field(default_factory=dict, init=False)
    _next_handle: int = field(default=0x0040, init=False)
    _auth_state: dict = field(default_factory=dict, init=False)
    _attached: bool = field(default=False, init=False)

    # -- Lifecycle ---------------------------------------------------------

    def attach(self) -> None:
        self.central.command_interceptor = self._make_interceptor(self.central)
        self.peripheral.command_interceptor = self._make_interceptor(self.peripheral)
        self.central.set_acl_forwarder(self._forward_central_to_peripheral)
        self.peripheral.set_acl_forwarder(self._forward_peripheral_to_central)
        self._attached = True

    def detach(self) -> None:
        self.central.command_interceptor = None
        self.peripheral.command_interceptor = None
        self.central.set_acl_forwarder(None)
        self.peripheral.set_acl_forwarder(None)
        self._handles.clear()
        self._auth_state.clear()
        self._attached = False

    async def disconnect(self) -> None:
        """Tear down all connected/pending handles. Task 8 fills full semantics."""
        # For now just detach. Task 8 expands this to emit completion events
        # for any CONNECTED / PENDING handles before teardown.
        self.detach()

    # -- Internals ---------------------------------------------------------

    def _allocate_handle(self) -> int:
        h = self._next_handle
        self._next_handle += 1
        return h

    def _peer_of(self, controller: VirtualController) -> VirtualController:
        return self.peripheral if controller is self.central else self.central

    def _addr_of(self, controller: VirtualController) -> BDAddress:
        return (
            self.central_address if controller is self.central
            else self.peripheral_address
        )

    def _make_interceptor(self, controller: VirtualController):
        """Build a command_interceptor closure bound to `controller`.

        Returns an async function with signature (opcode, raw_params) ->
        Optional[bytes]. The default body is a no-op; Tasks 3-8 add per-opcode
        branches that intercept BR/EDR commands and return synthetic responses.
        """

        async def _intercept(opcode: int, raw_params: bytes) -> Optional[bytes]:
            # Tasks 3-8 add per-opcode handling here.
            return None

        return _intercept

    # -- ACL forwarders ----------------------------------------------------

    async def _forward_central_to_peripheral(self, acl: HCIACLData) -> None:
        await self._forward_acl(self.central, acl)

    async def _forward_peripheral_to_central(self, acl: HCIACLData) -> None:
        await self._forward_acl(self.peripheral, acl)

    async def _forward_acl(self, source: VirtualController, acl: HCIACLData) -> None:
        """Forward ACL from source to peer if handle is CONNECTED. Drop silently otherwise."""
        entry = self._handles.get(acl.handle)
        if entry is None or entry.state != _ConnState.CONNECTED:
            return
        peer = self._peer_of(source)
        await peer._inject_acl_to_host(acl)
