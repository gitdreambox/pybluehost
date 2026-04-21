"""PyBlueHost CLI entry point."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point for pybluehost."""
    parser = argparse.ArgumentParser(
        prog="pybluehost",
        description="PyBlueHost — Python Bluetooth Host Stack CLI",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Register fw subcommand
    from pybluehost.cli.fw import register_fw_commands
    from pybluehost.cli.usb import register_usb_commands

    register_fw_commands(subparsers)
    register_usb_commands(subparsers)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
