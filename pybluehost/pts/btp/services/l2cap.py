"""L2CAP BTP service — LE Credit-Based Channels.

Translates auto-pts L2CAP opcodes into IutActions / v1.0 L2CAP API calls.
Owns a per-session map of BTP chan_id (u8) → v1.0 channel object.

Handlers land in P.8 Tasks 2-4; this file is the skeleton.
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


class LeCoCService(BtpService):
    """LE Credit-Based Channel BTP service."""

    SERVICE_ID = op.SERVICE_L2CAP

    def __init__(self, *, actions: "IutActions", tester: "BtpTester") -> None:
        self._actions = actions
        self._tester = tester
        self._controller_index: int = 0
        # BTP chan_id (u8) → v1.0 channel object (whatever IutActions returns).
        self._channels: dict[int, object] = {}
        # Next chan_id to allocate when accepting/initiating a channel.
        self._next_chan_id: int = 1

    def _allocate_chan_id(self) -> int:
        cid = self._next_chan_id
        self._next_chan_id += 1
        return cid

    async def _handle_op_01(self, controller_index: int, data: bytes):
        """READ_SUPPORTED_COMMANDS — bitfield of supported L2CAP opcodes."""
        cmds = self.supported_commands()
        if not cmds:
            return op.BTP_STATUS_SUCCESS, bytes(0)
        n_bytes = (max(cmds) // 8) + 1
        out = bytearray(n_bytes)
        for code in cmds:
            bit_index = code - 1
            out[bit_index // 8] |= 1 << (bit_index % 8)
        return op.BTP_STATUS_SUCCESS, bytes(out)
