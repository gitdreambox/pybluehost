"""Loopback bridge: two VirtualControllers paired as Central + Peripheral.

Used by E2E pairing tests to exercise SMP across a single LE connection
between two in-process Stack instances.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import EventCode, LEMetaSubEvent
from pybluehost.hci.packets import HCIACLData, HCIEvent
from pybluehost.hci.virtual import VirtualController


@dataclass
class VirtualLELink:
    """A loopback LE connection between two VirtualControllers."""

    central: VirtualController
    peripheral: VirtualController
    central_address: BDAddress
    peripheral_address: BDAddress
    handle: int = 0x0040
    connected: bool = field(default=False, init=False)

    async def connect(self) -> int:
        """Emit LE_Connection_Complete to both sides and wire ACL forwarding."""
        self.central.set_acl_forwarder(self._forward_central_to_peripheral)
        self.peripheral.set_acl_forwarder(self._forward_peripheral_to_central)
        await self._emit_connection_complete(
            self.central, role=0x00, peer=self.peripheral_address,
        )
        await self._emit_connection_complete(
            self.peripheral, role=0x01, peer=self.central_address,
        )
        self.connected = True
        return self.handle

    async def _emit_connection_complete(
        self, vc: VirtualController, role: int, peer: BDAddress,
    ) -> None:
        # LE Meta subevent body layout (LE_Connection_Complete):
        # subevent(1) + status(1) + handle(2) + role(1) + peer_addr_type(1)
        # + peer_addr(6) + interval(2) + latency(2) + supervision(2) + master_clock_acc(1)
        params = (
            bytes([int(LEMetaSubEvent.LE_CONNECTION_COMPLETE), 0x00])
            + struct.pack("<H", self.handle)
            + bytes([role, 0x00])
            + peer.address
            + struct.pack("<HHH", 0x0028, 0x0000, 0x0048)
            + bytes([0x00])
        )
        event = HCIEvent(event_code=int(EventCode.LE_META), parameters=params)
        await vc._send_event_to_host(event)

    async def _forward_central_to_peripheral(self, acl: HCIACLData) -> None:
        await self.peripheral._inject_acl_to_host(acl)

    async def _forward_peripheral_to_central(self, acl: HCIACLData) -> None:
        await self.central._inject_acl_to_host(acl)

    async def disconnect(self) -> None:
        """Emit Disconnection_Complete (reason 0x13 remote user) to both sides."""
        if not self.connected:
            return
        self.connected = False
        for vc in (self.central, self.peripheral):
            params = bytes([0x00]) + struct.pack("<H", self.handle) + bytes([0x13])
            event = HCIEvent(
                event_code=int(EventCode.DISCONNECTION_COMPLETE), parameters=params,
            )
            await vc._send_event_to_host(event)
