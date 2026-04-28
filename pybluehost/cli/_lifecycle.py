# pybluehost/cli/_lifecycle.py
"""Lifecycle helpers for long-running CLI commands."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from pybluehost.cli._transport import parse_transport_arg
from pybluehost.core.trace import BtsnoopSink, CallbackSink, Direction, TraceEvent
from pybluehost.stack import Stack, StackConfig


async def _print_hci_trace(event: TraceEvent) -> None:
    if event.source_layer != "hci" or not event.raw_bytes:
        return
    label = "TX" if event.direction == Direction.DOWN else "RX"
    print(f"[HCI {label}] {event.raw_bytes.hex(' ')}", file=sys.stderr, flush=True)


def add_trace_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--hci-log", action="store_true", help="Print HCI TX/RX packets to stderr")
    parser.add_argument("--btsnoop", type=Path, help="Write HCI btsnoop log to a .cfa file")


def trace_kwargs_from_args(args: Any) -> dict[str, Any]:
    return {
        "hci_log": getattr(args, "hci_log", False),
        "btsnoop": getattr(args, "btsnoop", None),
    }


async def run_app_command(
    transport_arg: str,
    main_coro: Callable[[Stack, asyncio.Event], Awaitable[None]],
    *,
    hci_log: bool = False,
    btsnoop: str | Path | None = None,
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
        config = StackConfig()
        if hci_log:
            config.trace_sinks.append(CallbackSink(_print_hci_trace))
        if btsnoop is not None:
            config.trace_sinks.append(BtsnoopSink(btsnoop))
        stack = await Stack._build(transport=transport, config=config)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

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
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0
    finally:
        await stack.close()
