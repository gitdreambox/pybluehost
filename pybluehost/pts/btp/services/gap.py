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
