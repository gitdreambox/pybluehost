# pybluehost/cli/app/__init__.py
"""CLI 'app' namespace — commands that open an HCI transport."""
from __future__ import annotations

import argparse


def register_app_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'app' subcommand with all its sub-subcommands."""
    app_parser = subparsers.add_parser("app", help="Bluetooth functionality (needs transport)")
    app_parser.set_defaults(func=lambda _args: app_parser.print_help() or 2)
    app_subs = app_parser.add_subparsers(dest="app_cmd")
    # Sub-commands registered as we add them
    from pybluehost.cli.app.ble_scan import register_ble_scan_command
    register_ble_scan_command(app_subs)
    from pybluehost.cli.app.ble_adv import register_ble_adv_command
    register_ble_adv_command(app_subs)
    from pybluehost.cli.app.classic_inquiry import register_classic_inquiry_command
    register_classic_inquiry_command(app_subs)
    from pybluehost.cli.app.gatt_browser import register_gatt_browser_command
    register_gatt_browser_command(app_subs)
    from pybluehost.cli.app.sdp_browser import register_sdp_browser_command
    register_sdp_browser_command(app_subs)
    from pybluehost.cli.app.gatt_server import register_gatt_server_command
    register_gatt_server_command(app_subs)
    from pybluehost.cli.app.hr_monitor import register_hr_monitor_command
    register_hr_monitor_command(app_subs)
    from pybluehost.cli.app.spp_echo import register_spp_echo_command
    register_spp_echo_command(app_subs)
