"""GATT BTP service — translates GATT opcodes into Phase 1 IutActions / GATTServer / GATTClient calls.

See design spec §11.5 + auto-pts doc/btp_gatt.txt (2026-06-22 upstream-aligned).

Command handlers land in P.7 Tasks 2-8; this file is the skeleton.
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


class GattService(BtpService):
    """GATT BTP service (both server-build and client-drive sides)."""

    SERVICE_ID = op.SERVICE_GATT

    def __init__(self, *, actions: "IutActions", tester: "BtpTester") -> None:
        self._actions = actions
        self._tester = tester
        self._controller_index: int = 0
        # Server-side build state. Populated by Add Service / Add Characteristic /
        # Add Descriptor handlers; consumed by Start Server.
        self._pending_db: list = []

    async def _handle_op_01(self, controller_index: int, data: bytes):
        """READ_SUPPORTED_COMMANDS — bitfield of supported GATT opcodes."""
        cmds = self.supported_commands()
        if not cmds:
            return op.BTP_STATUS_SUCCESS, bytes(0)
        n_bytes = (max(cmds) // 8) + 1
        out = bytearray(n_bytes)
        for code in cmds:
            bit_index = code - 1
            out[bit_index // 8] |= 1 << (bit_index % 8)
        return op.BTP_STATUS_SUCCESS, bytes(out)
