"""'app gatt-browser' - connect, discover GATT, print, exit."""
from __future__ import annotations

import argparse
import asyncio
import sys

from pybluehost.cli._target import TARGET_HELP, parse_target_arg
from pybluehost.cli._lifecycle import add_trace_arguments, run_app_command, trace_kwargs_from_args
from pybluehost.core.uuid import UUID16, UUID128
from pybluehost.stack import Stack


def register_gatt_browser_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("gatt-browser", help="Connect, discover GATT, print, exit")
    p.add_argument("-t", "--transport", required=True)
    p.add_argument("-a", "--target", help=TARGET_HELP)
    add_trace_arguments(p)
    p.set_defaults(func=lambda args: asyncio.run(_gatt_browser_main(args)))


async def _gatt_browser_main(args: argparse.Namespace) -> int:
    if not args.target:
        print("Error: --target is required", file=sys.stderr)
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
    print(f"Connecting to {addr}")
    try:
        client = await stack.connect_gatt(addr)
        services = await client.discover_all_services()
    except asyncio.TimeoutError as exc:
        raise RuntimeError("Timed out waiting for BLE connection or GATT response") from exc
    print(f"Connected to {addr}")
    await _print_discovered_gatt_tree(client, services)


def _print_connection_event(event) -> None:
    if event.state == "connected":
        print(f"Connected handle=0x{event.handle:04X}", file=sys.stderr)
    elif event.state == "disconnected":
        print(
            f"Disconnected handle=0x{event.handle:04X} reason={event.reason}",
            file=sys.stderr,
        )
    elif event.state == "failed":
        print(f"Connection failed reason={event.reason}", file=sys.stderr)


def _print_discovered_services(services: list[tuple[int, int, bytes]]) -> None:
    for start_handle, end_handle, uuid_bytes in services:
        uuid_text = _format_uuid(uuid_bytes)
        print(f"- Service {uuid_text}  handles=0x{start_handle:04X}-0x{end_handle:04X}")


async def _print_discovered_gatt_tree(client, services: list[tuple[int, int, bytes]]) -> None:
    for svc_start, svc_end, svc_uuid in services:
        print(f"- Service {_format_uuid(svc_uuid)}  handles=0x{svc_start:04X}-0x{svc_end:04X}")
        characteristics = await client.discover_characteristics(svc_start, svc_end)
        for index, char in enumerate(characteristics):
            print(
                f"  - Char {_format_uuid(char.uuid)}  "
                f"decl=0x{char.declaration_handle:04X} "
                f"value=0x{char.value_handle:04X} "
                f"props=0x{char.properties:02X} {_format_char_properties(char.properties)}"
            )
            next_decl = (
                characteristics[index + 1].declaration_handle
                if index + 1 < len(characteristics)
                else svc_end + 1
            )
            desc_start = char.value_handle + 1
            desc_end = min(next_decl - 1, svc_end)
            for desc in await client.discover_descriptors(desc_start, desc_end):
                print(f"    - Descriptor {_format_uuid(desc.uuid)}  handle=0x{desc.handle:04X}")


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
