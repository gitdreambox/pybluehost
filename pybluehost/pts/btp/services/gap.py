"""GAP BTP service — translates GAP opcodes into Phase 1 IutActions calls.

See design spec §11.5 + auto-pts doc/btp_gap.txt for the wire format.

Command handlers land in P.6 Tasks 2-7; this file is the skeleton.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.base import BtpService

if TYPE_CHECKING:
    from pybluehost.pts.actions import IutActions
    from pybluehost.pts.btp.tester import BtpTester

logger = logging.getLogger(__name__)


class GapService(BtpService):
    """LE GAP BTP service. Routes opcodes to IutActions calls; emits async
    GAP events to autoptsclient via BtpTester.emit_event."""

    SERVICE_ID = op.SERVICE_GAP

    def __init__(self, *, actions: "IutActions", tester: "BtpTester") -> None:
        self._actions = actions
        self._tester = tester
        self._current_settings: int = 0

    async def _handle_op_01(self, controller_index: int, data: bytes):
        """READ_SUPPORTED_COMMANDS — bitfield of supported GAP opcodes."""
        cmds = self.supported_commands()
        if not cmds:
            return op.BTP_STATUS_SUCCESS, bytes(0)
        n_bytes = (max(cmds) // 8) + 1
        out = bytearray(n_bytes)
        for code in cmds:
            bit_index = code - 1
            out[bit_index // 8] |= 1 << (bit_index % 8)
        return op.BTP_STATUS_SUCCESS, bytes(out)

    async def _handle_op_02(self, controller_index: int, data: bytes):
        """READ_CONTROLLER_INDEX_LIST — PyBlueHost is single-controller, index 0."""
        return op.BTP_STATUS_SUCCESS, bytes([1, 0])

    async def _handle_op_03(self, controller_index: int, data: bytes):
        """READ_CONTROLLER_INFO — BD_ADDR + settings + class_of_device + name."""
        local_addr = getattr(self._actions, "local_address", None)
        if isinstance(local_addr, bytes) and len(local_addr) == 6:
            addr_bytes = local_addr
        elif local_addr is not None and hasattr(local_addr, "address_bytes"):
            addr_bytes = bytes(local_addr.address_bytes)[:6]
        else:
            addr_bytes = bytes(6)

        # PyBlueHost LE-only capability advertisement (auto-pts settings bits).
        supported_settings = 0
        for bit in (1, 4, 8, 9):    # connectable, bondable, BLE, advertising
            supported_settings |= (1 << bit)
        current_settings = self._current_settings

        out = bytearray()
        out.extend(addr_bytes)
        out.extend(supported_settings.to_bytes(4, "little"))
        out.extend(current_settings.to_bytes(4, "little"))
        out.extend(bytes(3))                                  # class_of_device = 0
        name = b"PyBlueHost"
        out.extend(name.ljust(249, b"\x00"))                  # 249-byte name
        out.extend(name[:11].ljust(11, b"\x00"))              # 11-byte short name
        return op.BTP_STATUS_SUCCESS, bytes(out)

    async def _handle_op_04(self, controller_index: int, data: bytes):
        """RESET — clear per-session GAP state."""
        self._current_settings = 0
        return op.BTP_STATUS_SUCCESS, b""
