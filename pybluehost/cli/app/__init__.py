# pybluehost/cli/app/__init__.py
"""CLI 'app' namespace — commands that open an HCI transport."""
from __future__ import annotations

import argparse


def register_app_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'app' subcommand with all its sub-subcommands."""
    app_parser = subparsers.add_parser("app", help="Bluetooth functionality (needs transport)")
    app_subs = app_parser.add_subparsers(dest="app_cmd")
    # Sub-commands registered as we add them
    from pybluehost.cli.app.ble_scan import register_ble_scan_command
    register_ble_scan_command(app_subs)
