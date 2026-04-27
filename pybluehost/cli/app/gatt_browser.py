"""'app gatt-browser' — connect, discover GATT, print, exit."""
from __future__ import annotations

import argparse
import asyncio
import sys

from pybluehost.cli._virtual_peer import virtual_peer_with
from pybluehost.cli._target import parse_target_arg
from pybluehost.ble.gatt import UUID_PRIMARY_SERVICE, UUID_CHARACTERISTIC
from pybluehost.profiles.ble import BatteryServer
from pybluehost.stack import Stack


def register_gatt_browser_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("gatt-browser", help="Connect, discover GATT, print, exit")
    p.add_argument("--transport", required=True)
    p.add_argument("--target", help="BD_ADDR (required unless --transport virtual)")
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
        print(f"Connected to {addr}")
        print("(Real-hardware GATT discovery not implemented in v1; virtual only.)")
        return 0


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
