"""BR/EDR Secure Simple Pairing — local HCI termination.

Controller-driven: the host only responds to HCI events (IO_Capability_Request,
User_Confirmation_Request, Link_Key_Notification, Link_Key_Request).  No
application-layer crypto is required — the controller handles all SSP maths.

Allowed deps: pybluehost.hci.*, pybluehost.core.address, pairing.delegate.
"""
from __future__ import annotations

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    HCI_IO_CAPABILITY_REQUEST_REPLY,
    HCI_USER_CONFIRMATION_REQUEST_REPLY,
    HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY,
    HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY,
)
from pybluehost.hci.packets import HCICommand, HCI_Link_Key_Request_Reply_Command

from .delegate import PairingDelegate

# IO capability codes (Bluetooth Core Spec Vol 2 Part C §5.2.2.2)
IOCAP_DISPLAY_ONLY: int = 0x00
IOCAP_DISPLAY_YESNO: int = 0x01
IOCAP_KEYBOARD_ONLY: int = 0x02
IOCAP_NO_INPUT_NO_OUTPUT: int = 0x03

# Authentication requirements (Vol 2 Part C §5.2.2.5)
_AUTH_DEDICATED_BONDING_NO_MITM: int = 0x02   # Just Works
_AUTH_DEDICATED_BONDING_MITM: int = 0x03       # Numeric Comparison


class SspTermination:
    """Respond to SSP HCI events on behalf of a BR/EDR side in a MITM proxy.

    Parameters
    ----------
    controller:
        An HCIController (or compatible fake) that exposes the four
        ``on_io_capability_request``, ``on_user_confirmation_request``,
        ``on_link_key_notification``, and ``on_link_key_request`` listener
        registration methods plus ``send_command``.
    delegate:
        A :class:`PairingDelegate` whose ``confirm_numeric`` is called for
        User_Confirmation_Request events.
    side_name:
        Human-readable label passed to ``delegate.confirm_numeric`` (e.g.
        ``"target"`` or ``"phone"``).
    numeric:
        If *True*, advertise DisplayYesNo capability and request MITM
        protection (Numeric Comparison flow).  If *False* (default), advertise
        NoInputNoOutput (Just Works).
    """

    def __init__(
        self,
        controller,
        *,
        delegate: PairingDelegate,
        side_name: str,
        numeric: bool = False,
    ) -> None:
        self._controller = controller
        self._delegate = delegate
        self._side_name = side_name
        self._numeric = numeric
        # addr string → 16-byte link key
        self._link_keys: dict[str, bytes] = {}

    # ------------------------------------------------------------------
    # Listener registration
    # ------------------------------------------------------------------

    def attach(self) -> None:
        """Register all four SSP event listeners on the controller."""
        self._controller.on_io_capability_request(self._on_io)
        self._controller.on_user_confirmation_request(self._on_uc)
        self._controller.on_link_key_notification(self._on_lkn)
        self._controller.on_link_key_request(self._on_lkr)

    # ------------------------------------------------------------------
    # Event handlers (coroutines — controller awaits them)
    # ------------------------------------------------------------------

    async def _on_io(self, addr: BDAddress) -> None:
        """Reply to IO_Capability_Request with our chosen IO capability."""
        io_cap = IOCAP_DISPLAY_YESNO if self._numeric else IOCAP_NO_INPUT_NO_OUTPUT
        auth_req = _AUTH_DEDICATED_BONDING_MITM if self._numeric else _AUTH_DEDICATED_BONDING_NO_MITM
        params = (
            addr.address
            + bytes([io_cap])
            + bytes([0x00])      # OOB data not present
            + bytes([auth_req])
        )
        await self._controller.send_command(
            HCICommand(opcode=HCI_IO_CAPABILITY_REQUEST_REPLY, parameters=params)
        )

    async def _on_uc(self, addr: BDAddress, value: int) -> None:
        """Reply to User_Confirmation_Request after asking the delegate."""
        accept = await self._delegate.confirm_numeric(self._side_name, value)
        if accept:
            opcode = HCI_USER_CONFIRMATION_REQUEST_REPLY
        else:
            opcode = HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY
        await self._controller.send_command(
            HCICommand(opcode=opcode, parameters=addr.address)
        )

    def _on_lkn(self, addr: BDAddress, key: bytes, key_type: int) -> None:
        """Store a newly-negotiated link key (sync — no HCI reply needed)."""
        self._link_keys[str(addr)] = key

    async def _on_lkr(self, addr: BDAddress) -> None:
        """Reply to Link_Key_Request with stored key or a negative reply."""
        key = self._link_keys.get(str(addr))
        if key is not None:
            # 用专用 command 类(bd_addr 反转成小端 wire),与 classic/gap.py 一致。
            await self._controller.send_command(
                HCI_Link_Key_Request_Reply_Command(bd_addr=addr, link_key=key)
            )
        else:
            await self._controller.send_command(
                HCICommand(opcode=HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY, parameters=addr.address)
            )
