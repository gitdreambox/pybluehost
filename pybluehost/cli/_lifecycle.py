# pybluehost/cli/_lifecycle.py
"""Lifecycle helpers for long-running CLI commands."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
from pathlib import Path
from typing import Any, Awaitable, Callable

from pybluehost.cli._transport import parse_transport_arg
from pybluehost.core.trace import BtsnoopSink, CallbackSink, Direction, TraceEvent
from pybluehost.stack import Stack, StackConfig
from pybluehost.transport.spec import UART_SPEC_FORMAT, USB_SPEC_FORMAT

logger = logging.getLogger(__name__)
TRANSPORT_HELP = f"virtual | {USB_SPEC_FORMAT} | {UART_SPEC_FORMAT}"


async def _print_hci_trace(event: TraceEvent) -> None:
    if event.source_layer != "hci" or not event.raw_bytes:
        return
    label = "TX" if event.direction == Direction.DOWN else "RX"
    logger.warning("[HCI %s] %s", label, event.raw_bytes.hex(" "))


def add_trace_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--hci-log", action="store_true", help="Print HCI TX/RX packets to stderr")
    parser.add_argument("--btsnoop", type=Path, help="Write HCI btsnoop log to a .cfa file")
    parser.add_argument(
        "--virtual-sniffer", metavar="BACKEND[:opts]", default=None,
        help="Inject live HCI into an analyzer UI: "
             "ellisys[:tcp=,udp=,ellisys-path=] | wps[:wps-path=]",
    )


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-t", "--transport", required=True, help=TRANSPORT_HELP)
    add_trace_arguments(parser)


def trace_kwargs_from_args(args: Any) -> dict[str, Any]:
    return {
        "hci_log": getattr(args, "hci_log", False),
        "btsnoop": getattr(args, "btsnoop", None),
        "virtual_sniffer": getattr(args, "virtual_sniffer", None),
    }


def _format_cli_error(exc: BaseException) -> str:
    detail = str(exc).strip()
    if not detail:
        return type(exc).__name__
    return f"{type(exc).__name__}: {detail}"


async def run_app_command(
    transport_arg: str,
    main_coro: Callable[[Stack, asyncio.Event], Awaitable[None]],
    *,
    config: StackConfig | None = None,
    hci_log: bool = False,
    btsnoop: str | Path | None = None,
    trace_spec: Any = None,
    virtual_sniffer: str | None = None,
) -> int:
    """Run a long-running app command with SIGINT/SIGTERM handling.

    Steps:
        1. parse_transport_arg + Stack._build
        2. Install signal handlers → set stop_event
        3. Run main_coro(stack, stop_event)
           - if main_coro returns first → exit 0
           - if stop_event fires first → cancel main, exit 130
           - if main_coro raises → exit 1
        4. Always close the stack
    """
    stop_event = asyncio.Event()

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_event.set)
    except RuntimeError:
        pass

    try:
        transport = await parse_transport_arg(transport_arg)
        if not transport.is_open:
            await transport.open()
        config = config or StackConfig()
        if hci_log:
            config.trace_sinks.append(CallbackSink(_print_hci_trace))
        if btsnoop is not None:
            config.trace_sinks.append(BtsnoopSink(btsnoop))
        if virtual_sniffer is not None:
            from pybluehost.cli._sniffer_arg import parse_sniffer_arg
            from pybluehost.sniffer.sink import build_virtual_sniffer_sink
            spec = parse_sniffer_arg(virtual_sniffer)
            config.trace_sinks.append(await build_virtual_sniffer_sink(spec))
        stack = await Stack._build(transport=transport, config=config)
        if trace_spec is not None and not trace_spec.is_empty():
            from pybluehost.core.trace_control import attach_console_sink
            attach_console_sink(trace_spec, stack.trace)
    except Exception as e:
        logger.error("Error: %s", _format_cli_error(e))
        return 1

    main_task: asyncio.Task[None] | None = None
    stop_task: asyncio.Task[bool] | None = None
    try:
        main_task = asyncio.create_task(main_coro(stack, stop_event))
        stop_task = asyncio.create_task(stop_event.wait())
        done, _ = await asyncio.wait(
            {main_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if main_task not in done:
            main_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await main_task
            return 130
        stop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stop_task
        # Re-raise main exception, if any
        exc = main_task.exception()
        if exc is not None:
            logger.error("Error: %s", _format_cli_error(exc))
            return 1
        return 0
    except asyncio.CancelledError:
        stop_event.set()
        if main_task is not None:
            main_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await main_task
        if stop_task is not None:
            stop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stop_task
        return 130
    finally:
        await stack.close()
