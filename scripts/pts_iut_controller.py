"""Start a JSON-line TCP controller for PTS IUT automation."""
from __future__ import annotations

import argparse
import asyncio
import logging

from pybluehost.cli._lifecycle import run_app_command
from pybluehost.pts.iut_controller import run_json_controller


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transport", help="Transport spec, e.g. usb:0A12:0001#1")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18766)
    parser.add_argument("--log-level", default="INFO")
    return parser


async def _main_async(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    async def main_coro(stack, stop_event):
        await run_json_controller(
            stack,
            stop_event,
            transport=args.transport,
            host=args.host,
            port=args.port,
        )

    return await run_app_command(args.transport, main_coro)


def main() -> int:
    args = _build_parser().parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
