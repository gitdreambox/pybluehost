"""'app gatt-browser' - connect, discover GATT, print, exit."""
from __future__ import annotations

import argparse
import asyncio
import logging

from pybluehost.cli._target import TARGET_HELP, parse_target_arg
from pybluehost.cli._lifecycle import add_trace_arguments, run_app_command, trace_kwargs_from_args
from pybluehost.core.uuid import UUID16, UUID128
from pybluehost.stack import Stack

logger = logging.getLogger(__name__)


def register_gatt_browser_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("gatt-browser", help="Connect, discover GATT, print, exit")
    p.add_argument("-t", "--transport", required=True)
    p.add_argument("-a", "--target", help=TARGET_HELP)
    add_trace_arguments(p)
    p.set_defaults(func=lambda args: asyncio.run(_gatt_browser_main(args)))


async def _gatt_browser_main(args: argparse.Namespace) -> int:
    if not args.target:
        logger.error("Error: --target is required")
        return 2

    addr, _atype = parse_target_arg(args.target)
    return await run_app_command(
        args.transport,
        lambda stack, stop: _gatt_browser_run(stack, stop, addr),
        **trace_kwargs_from_args(args),
    )


async def _gatt_browser_run(stack: Stack, stop: asyncio.Event, addr) -> None:
    del stop
    if hasattr(stack, "on_connection_event"):
        stack.on_connection_event(_print_connection_event)
    logger.info("Connecting to %s", addr)
    try:
        client = await stack.connect_gatt(addr)
        services = await client.discover_all_services()
    except asyncio.TimeoutError as exc:
        raise RuntimeError("Timed out waiting for BLE connection or GATT response") from exc
    logger.info("Connected to %s", addr)
    await _print_discovered_gatt_tree(client, services)


def _print_connection_event(event) -> None:
    if event.state == "connected":
        logger.info("Connected handle=0x%04X", event.handle)
    elif event.state == "disconnected":
        logger.warning("Disconnected handle=0x%04X reason=%s", event.handle, event.reason)
    elif event.state == "failed":
        logger.error("Connection failed reason=%s", event.reason)


def _print_discovered_services(services: list[tuple[int, int, bytes]]) -> None:
    for start_handle, end_handle, uuid_bytes in services:
        uuid_text = _format_uuid(uuid_bytes)
        logger.info("- Service %s  handles=0x%04X-0x%04X", uuid_text, start_handle, end_handle)


async def _print_discovered_gatt_tree(client, services: list[tuple[int, int, bytes]]) -> None:
    for svc_start, svc_end, svc_uuid in services:
        logger.info(
            "- Service %s  handles=0x%04X-0x%04X",
            _format_uuid(svc_uuid),
            svc_start,
            svc_end,
        )
        characteristics = await client.discover_characteristics(svc_start, svc_end)
        for index, char in enumerate(characteristics):
            logger.info(
                "  - Char %s  decl=0x%04X value=0x%04X props=0x%02X %s",
                _format_uuid(char.uuid),
                char.declaration_handle,
                char.value_handle,
                char.properties,
                _format_char_properties(char.properties),
            )
            next_decl = (
                characteristics[index + 1].declaration_handle
                if index + 1 < len(characteristics)
                else svc_end + 1
            )
            desc_start = char.value_handle + 1
            desc_end = min(next_decl - 1, svc_end)
            for desc in await client.discover_descriptors(desc_start, desc_end):
                logger.info(
                    "    - Descriptor %s  handle=0x%04X",
                    _format_uuid(desc.uuid),
                    desc.handle,
                )


def _format_uuid(uuid_bytes: bytes) -> str:
    if len(uuid_bytes) == 2:
        return f"0x{UUID16.from_bytes(uuid_bytes).value:04X}"
    if len(uuid_bytes) == 16:
        uuid = UUID128.from_bytes(uuid_bytes)
        uuid16 = uuid.to_uuid16()
        if uuid16 is not None:
            return f"0x{uuid16.value:04X}"
        return str(uuid)
    return uuid_bytes.hex()


def _format_char_properties(properties: int) -> str:
    names = [
        (0x01, "BROADCAST"),
        (0x02, "READ"),
        (0x04, "WRITE_WITHOUT_RESPONSE"),
        (0x08, "WRITE"),
        (0x10, "NOTIFY"),
        (0x20, "INDICATE"),
        (0x40, "AUTHENTICATED_SIGNED_WRITES"),
        (0x80, "EXTENDED_PROPERTIES"),
    ]
    matched = [name for bit, name in names if properties & bit]
    return "|".join(matched) if matched else "-"
