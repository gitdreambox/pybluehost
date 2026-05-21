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
        """Tear down all CONNECTED / PENDING handles; emit appropriate completion events."""
        for handle in list(self._handles.keys()):
            entry = self._handles.get(handle)
            if entry is None:
                continue
            if entry.state == _ConnState.CONNECTED:
                await self._emit_disconnection_complete(handle, reason=0x16)  # Local_Host_Terminated
            elif entry.state == _ConnState.PENDING:
                await self._emit_connection_complete(
                    entry.initiator, status=0x16, handle=0x0000,
                    peer_addr=entry.acceptor_addr,
                )
                self._handles.pop(handle, None)
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
        Optional[bytes]. Sub-bridge branches return synthetic HCI responses
        for BR/EDR opcodes the bridge owns; None falls through to default
        dispatch on the underlying VirtualController.
        """

        async def _intercept(opcode: int, raw_params: bytes) -> Optional[bytes]:
            # --- InquiryBridge ---
            if opcode == HCI_INQUIRY:
                asyncio.create_task(self._inquiry(controller))
                return self._command_status(opcode, status=0)
            if opcode == HCI_INQUIRY_CANCEL:
                asyncio.create_task(self._inquiry_complete(controller))
                return self._command_complete(opcode, b"\x00")
            # --- ConnectionBridge ---
            if opcode == HCI_CREATE_CONNECTION:
                peer_addr_bytes = raw_params[0:6]
                asyncio.create_task(
                    self._create_connection(controller, peer_addr_bytes)
                )
                return self._command_status(opcode, status=0)
            if opcode == HCI_ACCEPT_CONNECTION_REQ:
                peer_addr_bytes = raw_params[0:6]
                asyncio.create_task(
                    self._accept_connection(controller, peer_addr_bytes)
                )
                return self._command_status(opcode, status=0)
            if opcode == HCI_REJECT_CONNECTION_REQ:
                peer_addr_bytes = raw_params[0:6]
                reason = raw_params[6] if len(raw_params) > 6 else 0x0D
                asyncio.create_task(
                    self._reject_connection(controller, peer_addr_bytes, reason)
                )
                return self._command_status(opcode, status=0)
            # --- AuthBridge ---
            if opcode == HCI_AUTH_REQUESTED:
                handle = struct.unpack_from("<H", raw_params, 0)[0]
                entry = self._handles.get(handle)
                if entry is None:
                    return self._command_status(opcode, status=0x02)
                asyncio.create_task(self._auth_emit_link_key_request(controller, entry))
                return self._command_status(opcode, status=0)
            if opcode == HCI_LINK_KEY_REQUEST_REPLY:
                # Positive reply: caller has a stored link key. Emit
                # Auth_Complete directly to the initiator; skip the
                # IO_Capability dance (bonded-reconnect fast path).
                peer_addr_bytes = raw_params[0:6]
                asyncio.create_task(
                    self._auth_emit_authentication_complete(controller, status=0)
                )
                return self._command_complete(opcode, b"\x00" + peer_addr_bytes)
            if opcode == HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY:
                # No stored key: proceed to IO_Capability dispatch.
                peer_addr_bytes = raw_params[0:6]
                asyncio.create_task(
                    self._auth_emit_io_cap_requests(controller, peer_addr_bytes)
                )
                return self._command_complete(opcode, b"\x00" + peer_addr_bytes)
            if opcode == HCI_IO_CAPABILITY_REQUEST_REPLY:
                peer_addr_bytes = raw_params[0:6]
                io_cap = raw_params[6]
                oob = raw_params[7]
                auth_req = raw_params[8]
                asyncio.create_task(self._auth_forward_io_cap_response(
                    controller, peer_addr_bytes, io_cap, oob, auth_req,
                ))
                return self._command_complete(opcode, b"\x00" + peer_addr_bytes)
            if opcode == HCI_USER_CONFIRMATION_REQUEST_REPLY:
                peer_addr_bytes = raw_params[0:6]
                asyncio.create_task(self._auth_user_confirm_reply(
                    controller, peer_addr_bytes, accepted=True,
                ))
                return self._command_complete(opcode, b"\x00" + peer_addr_bytes)
            if opcode == HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY:
                peer_addr_bytes = raw_params[0:6]
                asyncio.create_task(self._auth_user_confirm_reply(
                    controller, peer_addr_bytes, accepted=False,
                ))
                return self._command_complete(opcode, b"\x00" + peer_addr_bytes)
            # --- EncryptionBridge ---
            if opcode == HCI_SET_CONNECTION_ENCRYPTION:
                handle = struct.unpack_from("<H", raw_params, 0)[0]
                enable = raw_params[2] if len(raw_params) > 2 else 0
                asyncio.create_task(self._emit_encryption_change(handle, enable))
                return self._command_status(opcode, status=0)
            # --- DisconnectBridge ---
            if opcode == HCI_DISCONNECT:
                handle = struct.unpack_from("<H", raw_params, 0)[0]
                reason = raw_params[2] if len(raw_params) > 2 else 0x13
                asyncio.create_task(
                    self._emit_disconnection_complete(handle, reason)
                )
                return self._command_status(opcode, status=0)
            return None

        return _intercept

    # -- Synthetic event-frame builders ------------------------------------

    def _command_complete(self, opcode: int, return_params: bytes) -> bytes:
        """Build an H4-wrapped Command_Complete event."""
        body = bytes([0x01]) + struct.pack("<H", opcode) + return_params
        return bytes([0x04, int(EventCode.COMMAND_COMPLETE), len(body)]) + body

    def _command_status(self, opcode: int, status: int = 0) -> bytes:
        """Build an H4-wrapped Command_Status event."""
        body = bytes([status, 0x01]) + struct.pack("<H", opcode)
        return bytes([0x04, int(EventCode.COMMAND_STATUS), len(body)]) + body

    # -- InquiryBridge -----------------------------------------------------

    async def _inquiry(self, initiator: VirtualController) -> None:
        """Emit Inquiry_Result for the peer (if discoverable) then Inquiry_Complete."""
        peer = self._peer_of(initiator)
        peer_addr = (
            self.peripheral_address if initiator is self.central
            else self.central_address
        )
        if peer._inquiry_scan:
            body = (
                bytes([0x01])
                + peer_addr.address
                + bytes([0x01])              # page_scan_repetition_mode R1
                + bytes([0x00, 0x00])         # reserved
                + bytes([0x00, 0x00, 0x00])   # class_of_device (unspecified)
                + bytes([0x00, 0x00])         # clock_offset
            )
            event = HCIEvent(
                event_code=int(EventCode.INQUIRY_RESULT), parameters=body,
            )
            await initiator._send_event_to_host(event)
        await self._inquiry_complete(initiator)

    async def _inquiry_complete(self, initiator: VirtualController) -> None:
        body = bytes([0x00])  # status = 0
        event = HCIEvent(
            event_code=int(EventCode.INQUIRY_COMPLETE), parameters=body,
        )
        await initiator._send_event_to_host(event)

    # -- ConnectionBridge --------------------------------------------------

    async def _create_connection(
        self, initiator: VirtualController, peer_addr_bytes: bytes,
    ) -> None:
        """Page the peer; if peer.page_scan, emit Connection_Request; else Page_Timeout."""
        peer = self._peer_of(initiator)
        if not peer._page_scan:
            await asyncio.sleep(self.page_timeout_seconds)
            await self._emit_connection_complete(
                initiator, status=0x04, handle=0x0000,
                peer_addr=BDAddress(peer_addr_bytes),
            )
            return
        handle = self._allocate_handle()
        peer_addr = BDAddress(peer_addr_bytes)
        initiator_addr = self._addr_of(initiator)
        self._handles[handle] = _ConnEntry(
            handle=handle, state=_ConnState.PENDING,
            initiator=initiator, initiator_addr=initiator_addr,
            acceptor=peer, acceptor_addr=peer_addr,
        )
        # Connection_Request: BD_ADDR(6) + Class_Of_Device(3) + Link_Type(1=ACL)
        body = initiator_addr.address + bytes([0x00, 0x00, 0x00, 0x01])
        event = HCIEvent(
            event_code=int(EventCode.CONNECTION_REQUEST), parameters=body,
        )
        await peer._send_event_to_host(event)

    async def _accept_connection(
        self, acceptor: VirtualController, peer_addr_bytes: bytes,
    ) -> None:
        entry = next(
            (e for e in self._handles.values()
             if e.state == _ConnState.PENDING and e.acceptor is acceptor),
            None,
        )
        if entry is None:
            return
        entry.state = _ConnState.CONNECTED
        await asyncio.gather(
            self._emit_connection_complete(
                entry.initiator, status=0, handle=entry.handle,
                peer_addr=entry.acceptor_addr,
            ),
            self._emit_connection_complete(
                entry.acceptor, status=0, handle=entry.handle,
                peer_addr=entry.initiator_addr,
            ),
        )

    async def _reject_connection(
        self, acceptor: VirtualController, peer_addr_bytes: bytes, reason: int,
    ) -> None:
        entry = next(
            (e for e in self._handles.values()
             if e.state == _ConnState.PENDING and e.acceptor is acceptor),
            None,
        )
        if entry is None:
            return
        await self._emit_connection_complete(
            entry.initiator, status=reason, handle=0x0000,
            peer_addr=entry.acceptor_addr,
        )
        del self._handles[entry.handle]

    async def _emit_connection_complete(
        self, controller: VirtualController, *,
        status: int, handle: int, peer_addr: BDAddress,
    ) -> None:
        body = (
            bytes([status])
            + struct.pack("<H", handle)
            + peer_addr.address
            + bytes([0x01, 0x00])  # link_type=ACL, encryption_mode=disabled
        )
        event = HCIEvent(
            event_code=int(EventCode.CONNECTION_COMPLETE), parameters=body,
        )
        await controller._send_event_to_host(event)

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

    # -- AuthBridge --------------------------------------------------------

    async def _auth_emit_link_key_request(
        self, initiator: VirtualController, entry: _ConnEntry,
    ) -> None:
        body = entry.acceptor_addr.address
        event = HCIEvent(
            event_code=int(EventCode.LINK_KEY_REQUEST), parameters=body,
        )
        await initiator._send_event_to_host(event)

    async def _auth_emit_authentication_complete(
        self, initiator: VirtualController, status: int,
    ) -> None:
        """Emit Auth_Complete to initiator (used after positive
        Link_Key_Request_Reply in bonded reconnect)."""
        entry = next(
            (e for e in self._handles.values()
             if e.initiator is initiator and e.state == _ConnState.CONNECTED),
            None,
        )
        if entry is None:
            return
        body = bytes([status]) + struct.pack("<H", entry.handle)
        event = HCIEvent(
            event_code=int(EventCode.AUTH_COMPLETE), parameters=body,
        )
        await initiator._send_event_to_host(event)

    async def _auth_emit_io_cap_requests(
        self, initiator: VirtualController, peer_addr_bytes: bytes,
    ) -> None:
        """Emit IO_Capability_Request to BOTH sides."""
        peer = self._peer_of(initiator)
        body_to_initiator = self._addr_of(peer).address
        body_to_peer = self._addr_of(initiator).address
        await asyncio.gather(
            initiator._send_event_to_host(HCIEvent(
                event_code=int(EventCode.IO_CAPABILITY_REQUEST),
                parameters=body_to_initiator,
            )),
            peer._send_event_to_host(HCIEvent(
                event_code=int(EventCode.IO_CAPABILITY_REQUEST),
                parameters=body_to_peer,
            )),
        )

    async def _auth_forward_io_cap_response(
        self, source: VirtualController, peer_addr_bytes: bytes,
        io_cap: int, oob: int, auth_req: int,
    ) -> None:
        """Forward IO_Capability_Response to peer; when both have arrived,
        emit User_Confirmation_Request to both."""
        peer = self._peer_of(source)
        source_addr = self._addr_of(source).address
        body = source_addr + bytes([io_cap, oob, auth_req])
        await peer._send_event_to_host(HCIEvent(
            event_code=int(EventCode.IO_CAPABILITY_RESPONSE),
            parameters=body,
        ))
        entry_key = self._handle_key_for_pair(source, peer)
        state = self._auth_state.setdefault(entry_key, {})
        state[("io_cap", id(source))] = True
        has_source = state.get(("io_cap", id(source)), False)
        has_peer = state.get(("io_cap", id(peer)), False)
        if has_source and has_peer:
            await asyncio.gather(
                source._send_event_to_host(HCIEvent(
                    event_code=int(EventCode.USER_CONFIRMATION_REQUEST),
                    parameters=self._addr_of(peer).address + struct.pack("<I", 0),
                )),
                peer._send_event_to_host(HCIEvent(
                    event_code=int(EventCode.USER_CONFIRMATION_REQUEST),
                    parameters=self._addr_of(source).address + struct.pack("<I", 0),
                )),
            )

    async def _auth_user_confirm_reply(
        self, source: VirtualController, peer_addr_bytes: bytes, *, accepted: bool,
    ) -> None:
        """Track per-side user-confirm replies. Once both arrive, emit
        Simple_Pairing_Complete + Link_Key_Notification + Auth_Complete (success)
        or Simple_Pairing_Complete(0x05) (failure)."""
        peer = self._peer_of(source)
        entry_key = self._handle_key_for_pair(source, peer)
        state = self._auth_state.setdefault(entry_key, {})
        state[("confirm", id(source))] = accepted
        if not accepted:
            await asyncio.gather(
                source._send_event_to_host(HCIEvent(
                    event_code=int(EventCode.SIMPLE_PAIRING_COMPLETE),
                    parameters=bytes([0x05]) + self._addr_of(peer).address,
                )),
                peer._send_event_to_host(HCIEvent(
                    event_code=int(EventCode.SIMPLE_PAIRING_COMPLETE),
                    parameters=bytes([0x05]) + self._addr_of(source).address,
                )),
            )
            self._auth_state.pop(entry_key, None)
            return
        other = state.get(("confirm", id(peer)))
        if other is None:
            return
        if other is True:
            link_key = self._deterministic_link_key(
                self._addr_of(source), self._addr_of(peer),
            )
            entry = next(
                (e for e in self._handles.values()
                 if {e.initiator, e.acceptor} == {source, peer}),
                None,
            )
            await asyncio.gather(
                source._send_event_to_host(HCIEvent(
                    event_code=int(EventCode.SIMPLE_PAIRING_COMPLETE),
                    parameters=bytes([0x00]) + self._addr_of(peer).address,
                )),
                peer._send_event_to_host(HCIEvent(
                    event_code=int(EventCode.SIMPLE_PAIRING_COMPLETE),
                    parameters=bytes([0x00]) + self._addr_of(source).address,
                )),
                source._send_event_to_host(HCIEvent(
                    event_code=int(EventCode.LINK_KEY_NOTIFICATION),
                    parameters=self._addr_of(peer).address + link_key + bytes([0x05]),
                )),
                peer._send_event_to_host(HCIEvent(
                    event_code=int(EventCode.LINK_KEY_NOTIFICATION),
                    parameters=self._addr_of(source).address + link_key + bytes([0x05]),
                )),
            )
            if entry is not None:
                await entry.initiator._send_event_to_host(HCIEvent(
                    event_code=int(EventCode.AUTH_COMPLETE),
                    parameters=bytes([0x00]) + struct.pack("<H", entry.handle),
                ))
            self._auth_state.pop(entry_key, None)

    # -- EncryptionBridge --------------------------------------------------

    async def _emit_encryption_change(self, handle: int, enable: int) -> None:
        entry = self._handles.get(handle)
        if entry is None:
            return
        body = bytes([0x00]) + struct.pack("<H", handle) + bytes([enable])
        await asyncio.gather(
            entry.initiator._send_event_to_host(HCIEvent(
                event_code=int(EventCode.ENCRYPTION_CHANGE), parameters=body,
            )),
            entry.acceptor._send_event_to_host(HCIEvent(
                event_code=int(EventCode.ENCRYPTION_CHANGE), parameters=body,
            )),
        )

    # -- DisconnectBridge --------------------------------------------------

    async def _emit_disconnection_complete(self, handle: int, reason: int) -> None:
        entry = self._handles.get(handle)
        if entry is None:
            return
        entry.state = _ConnState.DISCONNECTING
        body = bytes([0x00]) + struct.pack("<H", handle) + bytes([reason])
        await asyncio.gather(
            entry.initiator._send_event_to_host(HCIEvent(
                event_code=int(EventCode.DISCONNECTION_COMPLETE), parameters=body,
            )),
            entry.acceptor._send_event_to_host(HCIEvent(
                event_code=int(EventCode.DISCONNECTION_COMPLETE), parameters=body,
            )),
        )
        self._handles.pop(handle, None)

    def _handle_key_for_pair(self, a: VirtualController, b: VirtualController) -> tuple:
        return tuple(sorted([id(a), id(b)]))

    def _deterministic_link_key(self, addr_a: BDAddress, addr_b: BDAddress) -> bytes:
        """Synthesize a stable 16-byte link key from sorted addresses."""
        material = b"".join(sorted([addr_a.address, addr_b.address]))
        return hashlib.sha256(material).digest()[:16]
