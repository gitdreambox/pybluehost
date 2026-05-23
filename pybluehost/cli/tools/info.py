"""pybluehost tools info — dump full HCI capability set of an adapter.

Opens the adapter via the same ``--transport=<spec>`` syntax pytest uses,
runs the standard HCI init (which caches manufacturer/version/feature
bitmaps), then prints either a human-readable table or ``--json``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from pybluehost.hci.capabilities import _OPCODE_BIT_POSITIONS
from pybluehost.hci.features_decode import (
    BREDR_FEATURE_BIT_NAMES,
    LE_FEATURE_BIT_NAMES,
    manufacturer_name,
)


def register_info_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "info",
        help="Dump full HCI capability set of an adapter",
    )
    parser.add_argument(
        "--transport",
        required=True,
        help="Transport spec, e.g. 'virtual', 'usb:vendor=intel', 'uart:/dev/ttyUSB0:115200'",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of a human-readable table",
    )
    parser.set_defaults(func=_cmd_info)


def _cmd_info(args: argparse.Namespace) -> int:
    return asyncio.run(_cmd_info_async(args))


async def _cmd_info_async(args: argparse.Namespace) -> int:
    """Async body of the info command."""
    from tests._transport_resolve import build_stack_from_spec

    stack = await build_stack_from_spec(args.transport)
    try:
        data = _collect_capability_data(stack, transport=args.transport)
    finally:
        await stack.close()

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(_format_human_table(data))
    return 0


def _collect_capability_data(stack, *, transport: str) -> dict[str, Any]:
    hci = stack._hci
    bd_addr = (
        str(stack._local_address) if stack._local_address is not None else "unknown"
    )
    manufacturer_id = hci.manufacturer_id or 0
    hci_version = hci.hci_version if hci.hci_version is not None else "unknown"
    lmp_subversion = hci.lmp_subversion if hci.lmp_subversion is not None else 0

    cmd_bitmap = bytes(hci.supported_commands.bitmap) if hci.supported_commands else b""
    le_features = hci.le_features or b""
    bredr_features = hci.bredr_features or b""

    le_decoded = _decode_bitmap(le_features, LE_FEATURE_BIT_NAMES)
    bredr_decoded = _decode_bitmap(bredr_features, BREDR_FEATURE_BIT_NAMES)
    cmd_decoded, unknown_bits = _decode_commands_bitmap(cmd_bitmap)

    summary = {
        "le_secure_connections": _bit_set(le_features, 1, 0)
            and _opcode_set(cmd_bitmap, 34, 1),
        "le_audio_host_support": _bit_set(le_features, 4, 4),
        "le_privacy_rpa": _bit_set(le_features, 0, 6),
        "le_extended_advertising": _bit_set(le_features, 1, 4),
        "bredr_encryption": _bit_set(bredr_features, 0, 2),
        "bredr_ssp": _opcode_set(cmd_bitmap, 32, 5),
        "bredr_sc_controller": _bit_set(bredr_features, 6, 3),
        "extended_inquiry_response": _bit_set(bredr_features, 6, 0),
    }

    return {
        "transport": transport,
        "bd_addr": bd_addr,
        "manufacturer_id": manufacturer_id,
        "manufacturer_name": manufacturer_name(manufacturer_id),
        "hci_version": hci_version,
        "lmp_subversion": lmp_subversion,
        "capability_summary": summary,
        "le_features": le_decoded,
        "bredr_features": bredr_decoded,
        "supported_commands": {
            "decoded": cmd_decoded,
            "unknown_bits_set": unknown_bits,
        },
    }


def _bit_set(bitmap: bytes, octet: int, bit: int) -> bool:
    if octet >= len(bitmap):
        return False
    return bool(bitmap[octet] & (1 << bit))


def _opcode_set(cmd_bitmap: bytes, octet: int, bit: int) -> bool:
    if octet >= len(cmd_bitmap):
        return False
    return bool(cmd_bitmap[octet] & (1 << bit))


def _decode_bitmap(
    bitmap: bytes, name_table: dict[tuple[int, int], str],
) -> dict[str, dict[str, Any]]:
    """{'<octet>/<bit>': {'name': ..., 'supported': bool}} for each named entry."""
    decoded: dict[str, dict[str, Any]] = {}
    for (octet, bit), name in name_table.items():
        decoded[f"{octet}/{bit}"] = {
            "name": name,
            "supported": _bit_set(bitmap, octet, bit),
        }
    return decoded


def _decode_commands_bitmap(
    cmd_bitmap: bytes,
) -> tuple[dict[str, str], list[dict[str, int]]]:
    """Decode the Supported_Commands bitmap.

    Returns (decoded, unknown_bits_set). decoded is {'<octet>/<bit>': '<name>'}
    for every known opcode whose bit is set. unknown_bits_set lists set bits
    that don't appear in _OPCODE_BIT_POSITIONS.
    """
    import pybluehost.hci.constants as hci_constants

    opcode_to_name: dict[int, str] = {
        v: k for k, v in vars(hci_constants).items()
        if k.startswith("HCI_") and isinstance(v, int)
    }
    position_to_name: dict[tuple[int, int], str] = {}
    for opcode, (octet, bit) in _OPCODE_BIT_POSITIONS.items():
        position_to_name[(octet, bit)] = opcode_to_name.get(opcode, f"opcode_0x{opcode:04X}")

    decoded: dict[str, str] = {}
    unknown: list[dict[str, int]] = []
    for octet in range(len(cmd_bitmap)):
        byte = cmd_bitmap[octet]
        for bit in range(8):
            if byte & (1 << bit):
                if (octet, bit) in position_to_name:
                    decoded[f"{octet}/{bit}"] = position_to_name[(octet, bit)]
                else:
                    unknown.append({"octet": octet, "bit": bit})
    return decoded, unknown


def _format_human_table(data: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("PyBlueHost Hardware Survey")
    lines.append("==========================")
    lines.append("")

    lines.append("Adapter identity")
    lines.append("----------------")
    lines.append(f"  Transport       : {data['transport']}")
    lines.append(f"  BD_ADDR         : {data['bd_addr']}")
    # manufacturer_name already embeds the ID for unknown vendors; avoid
    # printing it twice.
    if data["manufacturer_name"].startswith("Unknown"):
        manufacturer_display = data["manufacturer_name"]
    else:
        manufacturer_display = (
            f"{data['manufacturer_name']} (0x{data['manufacturer_id']:04X})"
        )
    lines.append(f"  Manufacturer    : {manufacturer_display}")
    lines.append(
        f"  HCI Version     : {data['hci_version']} "
        f"(LMP subversion 0x{data['lmp_subversion']:04X})"
    )
    lines.append("")

    lines.append("Capability summary")
    lines.append("------------------")
    for key, val in data["capability_summary"].items():
        marker = "yes" if val else "-"
        lines.append(f"  {key:<32} : {marker}")
    lines.append("")

    lines.append("LE Features (octet/bit)")
    lines.append("-----------------------")
    for ob, entry in data["le_features"].items():
        marker = "yes" if entry["supported"] else " "
        lines.append(f"  {ob:<5} {entry['name']:<55} : {marker}")
    lines.append("")

    lines.append("BR/EDR Features (page 0)")
    lines.append("------------------------")
    for ob, entry in data["bredr_features"].items():
        marker = "yes" if entry["supported"] else " "
        lines.append(f"  {ob:<5} {entry['name']:<55} : {marker}")
    lines.append("")

    lines.append("Supported HCI commands (octet/bit -> name)")
    lines.append("------------------------------------------")
    lines.append("  Known commands (decoded):")
    for ob, name in sorted(data["supported_commands"]["decoded"].items()):
        lines.append(f"    {ob:<7} {name}")
    unknown = data["supported_commands"]["unknown_bits_set"]
    lines.append(f"  Unknown bits set: {len(unknown)}")
    for u in unknown[:10]:
        lines.append(f"    octet {u['octet']}, bit {u['bit']}")
    if len(unknown) > 10:
        lines.append(f"    ... and {len(unknown) - 10} more")
    lines.append("")

    lines.append("Recommended pytest invocations")
    lines.append("------------------------------")
    lines.append(f"  uv run pytest tests/ --transport={data['transport']}")
    lines.append("  Two-adapter peer-to-peer:")
    lines.append(f"    uv run pytest tests/e2e/ --transport={data['transport']}#1 --transport-peer={data['transport']}#2")
    return "\n".join(lines)
