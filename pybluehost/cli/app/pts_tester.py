"""`pybluehost app pts-tester` — run a BTP tester for autoptsclient (Phase 2 P.5)."""
import argparse
import asyncio
import logging

from pybluehost.cli._lifecycle import (
    add_common_arguments, run_app_command, trace_kwargs_from_args,
)


def register_pts_tester_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "pts-tester",
        help="Run a BTP tester listening for autoptsclient (Phase 2)",
    )
    add_common_arguments(p)
    p.add_argument(
        "--listen", default="127.0.0.1:65103",
        help="host:port to listen on for autoptsclient (default 127.0.0.1:65103)",
    )
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(
            args.transport,
            lambda stack, stop: _pts_tester_main(stack, stop, listen=args.listen),
            **trace_kwargs_from_args(args),
        )
    ))


async def _pts_tester_main(stack, stop_event, *, listen: str):
    logger = logging.getLogger(__name__)
    from pybluehost.pts.btp import (
        BtpServiceRegistry, BtpTester, CoreService,
    )

    if ":" not in listen:
        raise ValueError(f"--listen must be host:port, got {listen!r}")
    host, port_str = listen.rsplit(":", 1)
    port = int(port_str)

    registry = BtpServiceRegistry()
    registry.register(CoreService(registry=registry))
    # GAP/GATT/L2CAP/SMP services land in P.6-P.8.
    tester = BtpTester(registry=registry, host=host, port=port)
    await tester.start()
    logger.info(
        "PyBlueHost BTP tester listening on %s:%d "
        "(P.5: Core service only; GAP/GATT/L2CAP/SMP land in P.6-P.8)",
        host, port,
    )
    try:
        await stop_event.wait()
    finally:
        await tester.stop()
