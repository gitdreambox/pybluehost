"""Canonical SPP test service for Classic E2E scenarios.

Registers an SPP service (UUID 0x1101) on RFCOMM channel SPP_SERVER_CHANNEL
on a Peripheral stack, with an echo handler that mirrors received bytes back
on the same channel.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from pybluehost.classic.sdp import make_rfcomm_service_record
from pybluehost.classic.spp import SPPConnection, SPPService

SPP_SERVER_CHANNEL = 1
SPP_CLASS_UUID = 0x1101  # Serial Port Profile
SPP_SERVICE_NAME = "PBH-E2E SPP"


def register_spp_echo_service(stack) -> SPPService:
    """Wire an SPP service with an echo handler on a Peripheral stack.

    Returns the SPPService instance. The caller is responsible for
    `await service.register(channel=SPP_SERVER_CHANNEL, name=SPP_SERVICE_NAME)`
    (this helper just builds the wiring).
    """
    service = SPPService(rfcomm=stack._rfcomm, sdp=stack._sdp)

    async def _echo_handler(conn: SPPConnection) -> None:
        try:
            while True:
                data = await conn.recv()
                if not data:
                    break
                await conn.send(data)
        except asyncio.CancelledError:
            return
        except Exception:
            return

    service.on_connection(_echo_handler)
    return service
