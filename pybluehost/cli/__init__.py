# pybluehost/cli/__init__.py
"""PyBlueHost CLI entry point."""
from __future__ import annotations

import argparse
import sys

from pybluehost.logging_config import DEFAULT_LOG_FILE, DEFAULT_LOG_LEVEL, configure_logging


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point for pybluehost."""
    parser = argparse.ArgumentParser(
        prog="pybluehost",
        description="PyBlueHost - Python Bluetooth Host Stack CLI",
    )
    parser.add_argument(
        "--log-file",
        default=DEFAULT_LOG_FILE,
        help=f"Write PyBlueHost logs to this file (default: {DEFAULT_LOG_FILE})",
    )
    parser.add_argument(
        "--log-level",
        default=DEFAULT_LOG_LEVEL,
        help=f"PyBlueHost log level (default: {DEFAULT_LOG_LEVEL})",
    )
    subparsers = parser.add_subparsers(dest="command")

    from pybluehost.cli.app import register_app_commands
    from pybluehost.cli.tools import register_tools_commands

    register_app_commands(subparsers)
    register_tools_commands(subparsers)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    if not hasattr(args, "func"):
        # Top-level namespace given without subcommand
        parser.print_help()
        return 2

    configure_logging(log_file=args.log_file, level=args.log_level)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
