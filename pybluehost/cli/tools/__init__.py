# pybluehost/cli/tools/__init__.py
"""CLI 'tools' namespace — offline utilities."""
from __future__ import annotations

import argparse


def register_tools_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'tools' subcommand with all its sub-subcommands."""
    tools_parser = subparsers.add_parser("tools", help="Offline utility tools")
    tools_subs = tools_parser.add_subparsers(dest="tools_cmd")

    from pybluehost.cli.tools.decode import register_decode_command
    from pybluehost.cli.tools.fw import register_fw_commands
    from pybluehost.cli.tools.rpa import register_rpa_commands
    from pybluehost.cli.tools.usb import register_usb_commands

    register_decode_command(tools_subs)
    register_fw_commands(tools_subs)
    register_rpa_commands(tools_subs)
    register_usb_commands(tools_subs)
