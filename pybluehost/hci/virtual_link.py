"""Loopback bridge: two VirtualControllers paired as Central + Peripheral.

Used by E2E pairing tests to exercise SMP across a single LE connection
between two in-process Stack instances.
"""
from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass, field

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import EventCode, LEMetaSubEvent
from pybluehost.hci.packets import HCIACLData, HCIEvent
from pybluehost.hci.virtual import VirtualController


@dataclass
class VirtualLELink:
    """A loopback LE connection between two VirtualControllers.

    Bridges:
    - ACL data frames in both directions.
    - LE encryption handshake: LE_Start_Encryption (Central) → LE_LTK_Request
      (Peripheral) → LTK_Request_Reply (Peripheral) → ENCRYPTION_CHANGE on both
      sides.  This mirrors the real BT controller behaviour during SMP Phase 2.
    """

    central: VirtualController
    peripheral: VirtualController
    central_address: BDAddress
    peripheral_address: BDAddress
    handle: int = 0x0040
    connected: bool = field(default=False, init=False)

    async def connect(self) -> int:
        """Emit LE_Connection_Complete to both sides and wire ACL + encryption forwarding."""
        # ACL bridge
        self.central.set_acl_forwarder(self._forward_central_to_peripheral)
        self.peripheral.set_acl_forwarder(self._forward_peripheral_to_central)

        # Encryption bridge hooks
        self.central._encryption_start_hook = self._on_central_start_encryption
        self.peripheral._ltk_reply_hook = self._on_peripheral_ltk_reply

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
            + peer.to_hci()
            + struct.pack("<HHH", 0x0028, 0x0000, 0x0048)
            + bytes([0x00])
        )
        event = HCIEvent(event_code=int(EventCode.LE_META), parameters=params)
        await vc._send_event_to_host(event)

    async def _forward_central_to_peripheral(self, acl: HCIACLData) -> None:
        await self.peripheral._inject_acl_to_host(acl)

    async def _forward_peripheral_to_central(self, acl: HCIACLData) -> None:
        await self.central._inject_acl_to_host(acl)

    # -- Encryption bridging ---------------------------------------------------

    async def _on_central_start_encryption(
        self, handle: int, rand: bytes, ediv: int, ltk: bytes
    ) -> None:
        """Called when the Central sends HCI_LE_Start_Encryption.

        Injects LE_LTK_Request into the Peripheral so stack_b's SMP can reply
        with LTK_Request_Reply (or Negative_Reply).  The actual ENCRYPTION_CHANGE
        events are emitted after the Peripheral responds.
        """
        # Inject LE_LTK_Request (LE Meta subevent 0x05) to the Peripheral.
        subevent_data = (
            bytes([int(LEMetaSubEvent.LE_LONG_TERM_KEY_REQUEST)])
            + struct.pack("<H", handle)
            + rand
            + struct.pack("<H", ediv)
        )
        meta_event = HCIEvent(
            event_code=int(EventCode.LE_META), parameters=subevent_data
        )
        await self.peripheral._send_event_to_host(meta_event)

    async def _on_peripheral_ltk_reply(self, handle: int, ltk: bytes) -> None:
        """Called when the Peripheral sends HCI_LE_LTK_Request_Reply.

        Emits ENCRYPTION_CHANGE (enabled) to both Central and Peripheral.

        Both events are scheduled as concurrent tasks so that neither side's
        key-distribution PDUs can race ahead of the other side's
        ENCRYPTION_CHANGE delivery.
        """
        # Fire both ENCRYPTION_CHANGE events in the same event-loop turn.
        # _emit_simulated_encryption_change uses asyncio.sleep(0) before
        # injecting the event, which keeps both deliveries in lock-step.
        await asyncio.gather(
            self.peripheral._emit_simulated_encryption_change(handle, status=0, enabled=1),
            self.central._emit_simulated_encryption_change(handle, status=0, enabled=1),
        )

    # -- Disconnect ------------------------------------------------------------

    async def disconnect(self) -> None:
        """Emit Disconnection_Complete (reason 0x13 remote user) to both sides."""
        if not self.connected:
            return
        self.connected = False
        # Remove encryption hooks so standalone behaviour resumes after disconnect.
        self.central._encryption_start_hook = None
        self.peripheral._ltk_reply_hook = None
        for vc in (self.central, self.peripheral):
            params = bytes([0x00]) + struct.pack("<H", self.handle) + bytes([0x13])
            event = HCIEvent(
                event_code=int(EventCode.DISCONNECTION_COMPLETE), parameters=params,
            )
            await vc._send_event_to_host(event)
