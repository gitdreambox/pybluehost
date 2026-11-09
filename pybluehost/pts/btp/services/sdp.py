"""SDP BTP service (doc/btp_sdp.txt) — SDP client ops toward the Lower Tester.

auto-pts drives SDP/CL cases (SSA/SA) through these commands; the Lower
Tester is the SDP *server*, the IUT the client. Service-record handles found
by a search are reported via the Service Record Handle Found event (0x80) so
auto-pts's stack.sdp model collects them for later WID handlers.
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


class SdpService(BtpService):
    """BR/EDR SDP client BTP service."""

    SERVICE_ID = op.SERVICE_SDP

    def __init__(self, *, actions: "IutActions", tester: "BtpTester") -> None:
        self._actions = actions
        self._tester = tester

    async def _handle_op_01(self, controller_index: int, data: bytes):
        """READ_SUPPORTED_COMMANDS — bitfield of supported SDP opcodes."""
        cmds = self.supported_commands()
        if not cmds:
            return op.BTP_STATUS_SUCCESS, bytes(0)
        n_bytes = (max(cmds) // 8) + 1
        out = bytearray(n_bytes)
        for code in cmds:
            out[code // 8] |= 1 << (code % 8)
        return op.BTP_STATUS_SUCCESS, bytes(out)

    async def _handle_op_02(self, controller_index: int, data: bytes):
        """SEARCH_REQ — body: addr_type(1)+addr(6)+uuid_len(1)+uuid.

        Runs SDP_ServiceSearch over PSM_SDP and emits the Service Record
        Handle Found event with every discovered handle.
        """
        if len(data) < 9:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        uuid_len = data[7]
        uuid_raw = bytes(data[8:8 + uuid_len])
        if uuid_len == 2:
            uuid = int.from_bytes(uuid_raw, "little")
        elif uuid_len == 16:
            # 128-bit UUID: keep as raw bytes; our client API takes 16-bit.
            uuid = int.from_bytes(uuid_raw[-2:], "little")
        else:
            return op.BTP_STATUS_FAILED, b""
        try:
            client = await self._actions.sdp_client_for(addr)
            handles = await client.search(target=None, uuid=uuid)
        except Exception:
            logger.exception("SDP SEARCH_REQ raised")
            return op.BTP_STATUS_FAILED, b""
        # Event: addr_type(1)+addr(6)+count(1)+handles(4 each). Address is the
        # PTS's — echo the little-endian wire address back.
        payload = bytes([data[0]]) + addr + bytes([len(handles)])
        for h in handles:
            payload += int(h).to_bytes(4, "little")
        from pybluehost.pts.btp.protocol import BtpFrame
        frame = BtpFrame(
            service=self.SERVICE_ID,
            opcode=op.OP_SDP_EVENT_SERVICE_RECORD_HANDLE,
            controller_index=0, data=payload,
        )
        try:
            import asyncio
            asyncio.create_task(self._tester.emit_event(frame))
        except Exception:
            logger.exception("SDP handle-found event emit failed")
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_03(self, controller_index: int, data: bytes):
        """ATTR_REQ — body: addr_type(1)+addr(6)+service_record_handle(4).

        Runs SDP_ServiceAttribute for the given record handle (full attribute
        range); PTS observes the on-air transaction.
        """
        if len(data) < 11:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        handle = int.from_bytes(data[7:11], "little")
        try:
            client = await self._actions.sdp_client_for(addr)
            await client.get_attributes(target=None, handle=handle, attr_ids=[])
        except Exception:
            logger.exception("SDP ATTR_REQ raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_04(self, controller_index: int, data: bytes):
        """SEARCH_ATTR_REQ — body: addr_type(1)+addr(6)+uuid_len(1)+uuid.

        Runs the combined SDP_ServiceSearchAttribute transaction.
        """
        if len(data) < 9:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        uuid_len = data[7]
        uuid_raw = bytes(data[8:8 + uuid_len])
        if uuid_len == 2:
            uuid = int.from_bytes(uuid_raw, "little")
        elif uuid_len == 16:
            uuid = int.from_bytes(uuid_raw[-2:], "little")
        else:
            return op.BTP_STATUS_FAILED, b""
        try:
            client = await self._actions.sdp_client_for(addr)
            await client.search_attributes(target=None, uuid=uuid)
        except Exception:
            logger.exception("SDP SEARCH_ATTR_REQ raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""
