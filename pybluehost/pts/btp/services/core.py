"""Core BTP service — service discovery + log + MTU (auto-pts doc/btp_core.txt).

Upstream-aligned 2026-06-22: implements LOG_MESSAGE (0x05) + READ_BTP_MTU (0x06).
Plan P.5 originally specified RESET_BOARD at 0x05; upstream has no such command,
so it's omitted entirely. (RESET_BOARD removed: not in upstream)
"""
from __future__ import annotations

import logging

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.base import BtpService, BtpServiceRegistry

logger = logging.getLogger(__name__)


# Maximum BTP frame size the tester accepts. 5-byte header + 1024-byte payload
# is a common auto-pts choice and fits comfortably inside one TCP segment.
BTP_MTU = 5 + 1024


class CoreService(BtpService):
    SERVICE_ID = op.SERVICE_CORE

    def __init__(self, *, registry: BtpServiceRegistry) -> None:
        self._registry = registry

    async def _handle_op_01(self, controller_index: int, data: bytes):
        """READ_SUPPORTED_COMMANDS — bitfield of supported Core opcodes."""
        cmds = self.supported_commands()
        if not cmds:
            return op.BTP_STATUS_SUCCESS, bytes(0)
        n_bytes = (max(cmds) // 8) + 1
        out = bytearray(n_bytes)
        for code in cmds:
            # Bit n is set for opcode (n+1) per auto-pts convention.
            bit_index = code - 1
            byte_idx = bit_index // 8
            bit_off = bit_index % 8
            out[byte_idx] |= 1 << bit_off
        return op.BTP_STATUS_SUCCESS, bytes(out)

    async def _handle_op_02(self, controller_index: int, data: bytes):
        """READ_SUPPORTED_SERVICES — bitfield of registered service IDs."""
        services = self._registry.supported_services()
        if not services:
            return op.BTP_STATUS_SUCCESS, bytes(0)
        n_bytes = (max(services) // 8) + 1
        out = bytearray(n_bytes)
        for sid in services:
            out[sid // 8] |= 1 << (sid % 8)
        return op.BTP_STATUS_SUCCESS, bytes(out)

    async def _handle_op_03(self, controller_index: int, data: bytes):
        """REGISTER — autoptsclient claims a service ID. Informational in P.5
        (services are registered tester-side at startup)."""
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
        service_id = data[0]
        if self._registry.get(service_id) is None:
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_04(self, controller_index: int, data: bytes):
        """UNREGISTER — release a service ID. No-op in P.5."""
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_05(self, controller_index: int, data: bytes):
        """LOG_MESSAGE — autoptsclient sends a log string to the tester."""
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = repr(data)
        logger.info("[btp/core/log] %s", text)
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_06(self, controller_index: int, data: bytes):
        """READ_BTP_MTU — return the maximum BTP frame size the tester accepts."""
        return op.BTP_STATUS_SUCCESS, BTP_MTU.to_bytes(2, "little")

    def make_ready_event_payload(
        self, *, version_major: int = 1, version_minor: int = 0,
        capabilities: int = 0,
    ) -> bytes:
        """Build the payload of an unsolicited IUT_READY event (Core opcode 0x80)."""
        return bytes([version_major & 0xFF, version_minor & 0xFF, capabilities & 0xFF])
