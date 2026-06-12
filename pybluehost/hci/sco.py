"""SCOLink — one SCO/eSCO link plus its callback wiring.

One SCOLink instance represents a single active SCO/eSCO connection identified
by its *handle* (the 12-bit value from Synchronous_Connection_Complete).  It
routes inbound HCISCOData packets to a registered callback and wraps outbound
data in HCISCOData before forwarding to the controller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from pybluehost.hci.packets import HCISCOData


@dataclass
class SCOLink:
    """Represents one SCO/eSCO connection.

    ``handle``
        The 12-bit connection handle issued by Synchronous_Connection_Complete.
    ``codec``
        Informational codec tag (e.g. ``'CVSD'`` or ``'mSBC'``) — used by the
        audio layer to decide how to encode/decode the payload.
    ``controller``
        Optional reference to the HCIController.  Required to call ``send()``.
        The expected interface is::

            await controller.send_sco_data(handle: int, data: bytes) -> None
    """

    handle: int
    codec: str
    controller: Optional[Any] = None

    _on_data: Optional[Callable[[bytes], Awaitable[None]]] = field(
        default=None, init=False, repr=False
    )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_on_data(self, callback: Callable[[bytes], Awaitable[None]]) -> None:
        """Register an async callback invoked with each inbound SCO payload."""
        self._on_data = callback

    async def send(self, data: bytes) -> None:
        """Send *data* as an HCI SCO Data packet via the attached controller.

        Raises ``RuntimeError`` if no controller is attached.
        """
        if self.controller is None:
            raise RuntimeError("SCOLink has no controller — cannot send")
        await self.controller.send_sco_data(self.handle, data)

    async def _on_inbound(self, pkt: HCISCOData) -> None:
        """Called by the upper layer with each received HCISCOData packet.

        Silently ignores packets whose handle does not match this link's handle.
        """
        if pkt.handle != self.handle:
            return
        if self._on_data is not None:
            await self._on_data(pkt.data)

    async def close(self) -> None:
        """Release resources held by this link.

        Connection teardown (HCI_Disconnect) is the parent session's
        responsibility; this method only clears the inbound callback.
        """
        self._on_data = None
