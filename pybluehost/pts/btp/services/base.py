"""BtpService base class + registry — per-service dispatch (design spec §11.5)."""
from __future__ import annotations

import logging

from pybluehost.pts.btp import opcodes as op

logger = logging.getLogger(__name__)


class BtpServiceError(Exception):
    """Protocol-level service error (registration / dispatch)."""


class BtpService:
    """Subclass and set `SERVICE_ID` + define `async def _handle_op_XX(controller_index, data)` methods."""

    SERVICE_ID: int = -1     # subclass MUST override

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls.SERVICE_ID == -1:
            raise BtpServiceError(
                f"{cls.__name__} must set SERVICE_ID class attribute"
            )

    async def dispatch(
        self, *, opcode: int, controller_index: int, data: bytes,
    ) -> tuple[int, bytes]:
        """Look up `_handle_op_XX` where XX is the opcode in hex (lower-case, 2 digits).

        Returns ``(status, response_data)``. Unknown opcodes return
        ``(BTP_STATUS_UNKNOWN_CMD, b"")`` without raising.
        """
        handler_name = f"_handle_op_{opcode:02x}"
        handler = getattr(self, handler_name, None)
        if handler is None:
            logger.debug(
                "%s: unhandled opcode 0x%02X", self.__class__.__name__, opcode,
            )
            return op.BTP_STATUS_UNKNOWN_CMD, b""
        try:
            result = await handler(controller_index, data)
        except Exception:    # noqa: BLE001 — turn handler exceptions into FAILED status
            logger.exception(
                "%s: handler 0x%02X raised", self.__class__.__name__, opcode,
            )
            return op.BTP_STATUS_FAILED, b""
        if not isinstance(result, tuple) or len(result) != 2:
            raise BtpServiceError(
                f"handler {handler_name} returned {result!r}, expected (status, bytes)"
            )
        return result

    def supported_commands(self) -> list[int]:
        """List of opcodes this service handles, derived from `_handle_op_XX` methods."""
        out: list[int] = []
        for name in dir(self):
            if name.startswith("_handle_op_") and len(name) == len("_handle_op_") + 2:
                try:
                    out.append(int(name[-2:], 16))
                except ValueError:
                    continue
        return sorted(out)


class BtpServiceRegistry:
    """Owns service instances keyed by SERVICE_ID."""

    def __init__(self) -> None:
        self._services: dict[int, BtpService] = {}

    def register(self, service: BtpService) -> None:
        if service.SERVICE_ID in self._services:
            raise BtpServiceError(
                f"service 0x{service.SERVICE_ID:02X} already registered"
            )
        self._services[service.SERVICE_ID] = service

    def get(self, service_id: int) -> BtpService | None:
        return self._services.get(service_id)

    def supported_services(self) -> list[int]:
        return sorted(self._services.keys())
