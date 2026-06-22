"""BtpTester — asyncio TCP server bridging autoptsclient to IUT services."""
from __future__ import annotations

import asyncio
import logging

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import (
    BTP_HEADER_SIZE, BtpFrame, decode_btp_frame, encode_btp_frame,
)
from pybluehost.pts.btp.services.base import BtpServiceRegistry
from pybluehost.pts.btp.services.core import CoreService

logger = logging.getLogger(__name__)


class BtpTester:
    """One-client TCP BTP tester. Construct with a populated registry, start(), wait."""

    def __init__(
        self, *, registry: BtpServiceRegistry, host: str = "127.0.0.1", port: int = 8765,
    ) -> None:
        self._registry = registry
        self._host = host
        self._port = port
        self._server: asyncio.Server | None = None
        self._client_writer: asyncio.StreamWriter | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, host=self._host, port=self._port,
        )
        logger.info("BtpTester listening on %s:%d", self._host, self._port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None
        if self._client_writer is not None:
            try:
                self._client_writer.close()
                await self._client_writer.wait_closed()
            except Exception:
                pass
            self._client_writer = None

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        logger.info("BtpTester: client connected from %s", peer)
        self._client_writer = writer
        # Emit unsolicited READY event.
        core = self._registry.get(op.SERVICE_CORE)
        if isinstance(core, CoreService):
            ready_event = BtpFrame(
                service=op.SERVICE_CORE,
                opcode=op.OP_CORE_EVENT_READY,
                controller_index=op.CONTROLLER_INDEX_NONE,
                data=core.make_ready_event_payload(),
            )
            writer.write(encode_btp_frame(ready_event))
            await writer.drain()

        try:
            while True:
                header = await reader.readexactly(BTP_HEADER_SIZE)
                data_len = int.from_bytes(header[3:5], "little")
                body = await reader.readexactly(data_len) if data_len else b""
                request = decode_btp_frame(header + body)
                response = await self._dispatch(request)
                writer.write(encode_btp_frame(response))
                await writer.drain()
        except asyncio.IncompleteReadError:
            logger.info("BtpTester: client disconnected (peer=%s)", peer)
        except Exception:    # noqa: BLE001
            logger.exception("BtpTester: client loop error")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            self._client_writer = None

    async def _dispatch(self, request: BtpFrame) -> BtpFrame:
        service = self._registry.get(request.service)
        if service is None:
            return BtpFrame(
                service=request.service, opcode=op.OP_STATUS_RESPONSE,
                controller_index=request.controller_index,
                data=bytes([op.BTP_STATUS_UNKNOWN_CMD]),
            )
        status, response_data = await service.dispatch(
            opcode=request.opcode, controller_index=request.controller_index,
            data=request.data,
        )
        # Status response = opcode 0x00 in the same service.
        # Payload = [status_byte, ...response_data].
        return BtpFrame(
            service=request.service, opcode=op.OP_STATUS_RESPONSE,
            controller_index=request.controller_index,
            data=bytes([status]) + response_data,
        )

    async def emit_event(self, event: BtpFrame) -> None:
        """Send an unsolicited event to the connected client."""
        if self._client_writer is None:
            logger.debug("BtpTester: emit_event with no client connected; dropping")
            return
        self._client_writer.write(encode_btp_frame(event))
        await self._client_writer.drain()
