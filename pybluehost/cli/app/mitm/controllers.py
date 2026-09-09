"""Build and initialize upstream/downstream HCIControllers from two transport strings (hci+transport only)."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from pybluehost.cli._transport import parse_transport_arg
from pybluehost.hci.constants import (
    HCI_RESET,
    HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT,
)
from pybluehost.hci.controller import HCIController
from pybluehost.hci.packets import (
    HCI_Write_Secure_Connections_Host_Support_Command,
    HCICommand,
)
from pybluehost.transport.base import Transport

logger = logging.getLogger(__name__)


async def _enable_secure_connections(controller: HCIController, side: str) -> None:
    """Enable Secure Connections Host Support (P-256 SSP) on a BR/EDR controller.

    Real-hardware G3 finding: modern phones (Android 12+) require Secure Connections
    for BR/EDR SSP; a bare HCIController has no security_config, so initialize() never
    sends this command, and phone-side pairing fails at Simple_Pairing_Complete (0x05
    authentication failure) before the public-key/numeric-comparison stage. Call before
    any connection is established. Falls back to Legacy SSP with a warning if the
    controller does not support it.
    """
    if not controller._supported_commands.has(HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT):  # type: ignore[attr-defined]
        logger.warning(
            "%s 控制器不支持 Secure Connections(Write_Secure_Connections_Host_Support),"
            "回退 Legacy SSP", side,
        )
        return
    await controller.send_command(
        HCI_Write_Secure_Connections_Host_Support_Command(
            secure_connections_host_support=0x01
        )
    )


async def _close_transport(t: object) -> None:
    """Close one transport, tolerating sync/async close; swallow errors with a warning."""
    close = getattr(t, "close", None)
    if close is None:
        return
    try:
        res = close()
        if asyncio.iscoroutine(res):
            await res
    except Exception:  # a close failure must not block cleanup of the other transports
        logger.warning("关闭 transport %r 失败", t, exc_info=True)


@dataclass
class ControllerPair:
    upstream: HCIController
    downstream: HCIController
    _transports: tuple[Transport, Transport] = field(repr=False)

    async def close(self) -> None:
        # Send HCI_Reset to both sides before closing USB: force-clear all
        # connection/pairing state and return the controllers to a clean state.
        # Real-hardware lesson (BE200): exiting with a live ACL hangs the firmware —
        # the next init's HCI Reset gets no response and the dongle must be replugged.
        # A wedged controller whose command path is still alive can also be rescued by
        # Reset. Reset both sides **concurrently**: one wedged dongle (eating timeouts
        # one by one) must not delay cleanup of the healthy one. Best-effort: a fully
        # hung one times out and is closed anyway.
        async def _reset(ctrl, side):
            try:
                await asyncio.wait_for(
                    ctrl.send_command(HCICommand(opcode=HCI_RESET)), timeout=2.0
                )
                logger.info("%s 已 HCI_Reset,控制器回到干净态", side)
            except Exception:
                logger.debug("%s HCI_Reset 失败(控制器可能已异常)", side)

        await asyncio.gather(
            _reset(self.downstream, "downstream"),
            _reset(self.upstream, "upstream"),
        )
        # Close one by one; a failure does not affect the rest (avoids leaking the
        # second transport).
        for t in self._transports:
            await _close_transport(t)


async def open_controller_pair(upstream: str, downstream: str) -> ControllerPair:
    up_t = await parse_transport_arg(upstream)
    down_t = await parse_transport_arg(downstream)
    up = HCIController(up_t)
    down = HCIController(down_t)
    opened: list[Transport] = []
    try:
        await up_t.open()
        opened.append(up_t)
        await down_t.open()
        opened.append(down_t)
        await asyncio.gather(up.initialize(), down.initialize())
        # Enable Secure Connections on both sides before any connection: required for
        # phone-side SSP.
        await asyncio.gather(
            _enable_secure_connections(up, "upstream"),
            _enable_secure_connections(down, "downstream"),
        )
    except Exception:
        # Partial failure: roll back already-opened transports to avoid leaking
        # USB/UART handles.
        for t in reversed(opened):
            await _close_transport(t)
        raise
    return ControllerPair(upstream=up, downstream=down, _transports=(up_t, down_t))


async def open_controller(spec: str):
    """Open and initialize one controller (for scan); roll back the transport on failure."""
    t = await parse_transport_arg(spec)
    ctrl = HCIController(t)
    try:
        await t.open()
        await ctrl.initialize()
    except Exception:
        await _close_transport(t)
        raise
    return ctrl, t
