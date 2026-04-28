"""'app gatt-browser' — connect, discover GATT, print, exit."""
from __future__ import annotations

import argparse
import asyncio
import sys

from pybluehost.cli._target import parse_target_arg
from pybluehost.cli._transport import parse_transport_arg
from pybluehost.cli._virtual_peer import virtual_peer_with
from pybluehost.ble.gatt import UUID_PRIMARY_SERVICE, UUID_CHARACTERISTIC
from pybluehost.core.uuid import UUID16, UUID128
from pybluehost.profiles.ble import BatteryServer
from pybluehost.stack import Stack


def register_gatt_browser_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("gatt-browser", help="Connect, discover GATT, print, exit")
    p.add_argument("-t", "--transport", required=True)
    p.add_argument("-a", "--target", help="BD_ADDR (required unless --transport virtual)")
    p.set_defaults(func=lambda args: asyncio.run(_gatt_browser_main(args)))


async def _gatt_browser_main(args: argparse.Namespace) -> int:
    is_virtual = args.transport == "virtual"
    if not is_virtual and not args.target:
        print("Error: --target is required for non-virtual transport", file=sys.stderr)
        return 2

    if is_virtual:
        async def battery_factory(gatt_server):
            await BatteryServer(initial_level=85).register(gatt_server)

        try:
            async with virtual_peer_with(battery_factory) as peer:
                target_addr = peer.local_address
                print(f"Connected to {target_addr} (virtual peer)")
                _print_gatt_tree(peer.gatt_server)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return 0
    else:
        addr, _atype = parse_target_arg(args.target)
        stack = None
        try:
            stack = await _build_stack(args.transport)
            print(f"Connecting to {addr}")
            client = await stack.connect_gatt(addr)
            services = await client.discover_all_services()
            print(f"Connected to {addr}")
            await _print_discovered_gatt_tree(client, services)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        finally:
            if stack is not None:
                await stack.close()
        return 0


async def _build_stack(transport_arg: str) -> Stack:
    transport = await parse_transport_arg(transport_arg)
    if not transport.is_open:
        await transport.open()
    try:
        return await Stack._build(transport=transport)
    except Exception:
        await transport.close()
        raise


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
                f"props=0x{char.properties:02X}"
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


def _print_gatt_tree(gatt_server) -> None:
    """Walk gatt_server.db._attrs and print services/characteristics."""
    from pybluehost.core.uuid import UUID16, UUID128

    db = gatt_server.db
    attrs = db._attrs

    primary_svc_bytes = UUID_PRIMARY_SERVICE.to_bytes()
    char_decl_bytes = UUID_CHARACTERISTIC.to_bytes()

    # Build index of characteristic declarations: decl_handle -> value_handle
    # Characteristic declaration value: properties(1B) + value_handle(2B LE) + uuid(2 or 16B)
    import struct

    # Walk attributes grouping by service
    current_svc_uuid = None
    svc_end_handle: int = 0

    for attr in attrs:
        type_bytes = attr.type_uuid.to_bytes()

        if type_bytes == primary_svc_bytes:
            # Service declaration — decode its UUID
            val = attr.value
            if len(val) == 2:
                svc_uuid = UUID16.from_bytes(val)
            elif len(val) == 16:
                svc_uuid = UUID128.from_bytes(val)
            else:
                svc_uuid = attr.type_uuid
            current_svc_uuid = svc_uuid
            print(f"─ Service 0x{svc_uuid.value:04X}" if isinstance(svc_uuid, UUID16)
                  else f"─ Service {svc_uuid}")

        elif type_bytes == char_decl_bytes:
            # Characteristic declaration — decode value_handle and char UUID
            val = attr.value
            if len(val) >= 3:
                props = val[0]
                value_handle = struct.unpack_from("<H", val, 1)[0]
                uuid_bytes = val[3:]
                if len(uuid_bytes) == 2:
                    char_uuid = UUID16.from_bytes(uuid_bytes)
                    uuid_str = f"0x{char_uuid.value:04X}"
                elif len(uuid_bytes) == 16:
                    char_uuid = UUID128.from_bytes(uuid_bytes)
                    uuid_str = str(char_uuid)
                else:
                    uuid_str = uuid_bytes.hex()
                    value_handle = 0

                # Read value from DB
                try:
                    value = db.read(value_handle)
                except KeyError:
                    value = b""

                print(f"   ├─ Char {uuid_str}  handle=0x{value_handle:04X}  "
                      f"props=0x{props:02X}  value={value.hex()}")
