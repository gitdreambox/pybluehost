"""pybluehost tools info — dump full HCI capability set of an adapter.

Opens the adapter via the same ``--transport=<spec>`` syntax pytest uses,
runs the standard HCI init (which caches manufacturer/version/feature
bitmaps), then prints either a human-readable table or ``--json``.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from typing import Any

from pybluehost.hci.features_decode import (
    BREDR_FEATURE_BIT_NAMES,
    BREDR_FEATURE_BIT_NAMES_P1,
    BREDR_FEATURE_BIT_NAMES_P2,
    LE_FEATURE_BIT_NAMES,
    SUPPORTED_COMMAND_NAMES,
    hci_version_name,
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

    # In --json mode, stack init can emit INFO-level logs to stdout (transport
    # init banners, firmware load progress, etc.) which would contaminate the
    # JSON output. Redirect stdout to stderr for the duration of init so the
    # final JSON print is the only thing on stdout.
    json_stdout_redirect: contextlib.AbstractContextManager[Any] = (
        contextlib.redirect_stdout(sys.stderr) if args.json
        else contextlib.nullcontext()
    )

    with json_stdout_redirect:
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
    hci_version = hci.hci_version if hci.hci_version is not None else 0
    hci_revision = hci.hci_revision if hci.hci_revision is not None else 0
    lmp_version = hci.lmp_version if hci.lmp_version is not None else 0
    lmp_subversion = hci.lmp_subversion if hci.lmp_subversion is not None else 0

    cmd_bitmap = bytes(hci.supported_commands.bitmap) if hci.supported_commands else b""
    le_features = hci.le_features or b""
    bredr_features = hci.bredr_features or b""
    bredr_features_p1 = hci.bredr_features_p1 or b""
    bredr_features_p2 = hci.bredr_features_p2 or b""
    le_features_pages = getattr(hci, "le_features_pages", None) or {}
    le_features_max_page = getattr(hci, "le_features_max_page", None)

    le_decoded = _decode_bitmap(le_features, LE_FEATURE_BIT_NAMES)
    bredr_decoded = _decode_bitmap(bredr_features, BREDR_FEATURE_BIT_NAMES)
    bredr_decoded_p1 = _decode_bitmap(bredr_features_p1, BREDR_FEATURE_BIT_NAMES_P1)
    bredr_decoded_p2 = _decode_bitmap(bredr_features_p2, BREDR_FEATURE_BIT_NAMES_P2)
    cmd_decoded, unknown_bits = _decode_commands_bitmap(cmd_bitmap)

    # See docs/HARDWARE_E2E.md §3.1 for the spec references behind each row.
    summary = {
        # LE Secure Connections: controller exposes both P-256 ECDH commands
        # via HCI Supported_Commands octet 34 bits 1+2.
        "le_secure_connections": (
            _opcode_set(cmd_bitmap, 34, 1)   # HCI_LE_Read_Local_P-256_Public_Key
            and _opcode_set(cmd_bitmap, 34, 2)  # HCI_LE_Generate_DHKey
        ),
        # LL Privacy / Resolvable Private Address resolution in controller.
        # LE Features octet 0 bit 6.
        "le_privacy_rpa": _bit_set(le_features, 0, 6),
        # LE Extended Advertising (BT 5.0+). LE Features octet 1 bit 4.
        "le_extended_advertising": _bit_set(le_features, 1, 4),
        # LE 2M PHY (high-throughput). LE Features octet 1 bit 0.
        "le_2m_phy": _bit_set(le_features, 1, 0),
        # LE Coded PHY (long range). LE Features octet 1 bit 3.
        "le_coded_phy": _bit_set(le_features, 1, 3),
        # BR/EDR Baseline encryption. LMP Features page 0 octet 0 bit 2.
        "bredr_encryption": _bit_set(bredr_features, 0, 2),
        # BR/EDR Secure Simple Pairing: controller advertises the IO Capability
        # reply command (Supported_Commands octet 32 bit 5). Matches
        # tests/e2e/_helpers.py:_supports_classic_ssp — the gate that decides
        # whether Classic e2e tests run vs skip.
        "bredr_ssp": _opcode_set(cmd_bitmap, 32, 5),
        # BR/EDR Secure Connections (controller). LMP page 2 octet 1 bit 0.
        # Only populated if Read_Local_Extended_Features page 2 was fetched.
        "bredr_sc_controller": _bit_set(bredr_features_p2, 1, 0),
        # BR/EDR Secure Connections (host). LMP page 1 octet 0 bit 3 — what
        # the host has WRITTEN to the controller via Write_Secure_Connections_
        # Host_Support. Reflects PyBlueHost's own config in the current session.
        "bredr_sc_host_support": _bit_set(bredr_features_p1, 0, 3),
        # Extended Inquiry Response. LMP Features page 0 octet 6 bit 0.
        "extended_inquiry_response": _bit_set(bredr_features, 6, 0),
    }

    return {
        "transport": transport,
        "bd_addr": bd_addr,
        "manufacturer_id": manufacturer_id,
        "manufacturer_name": manufacturer_name(manufacturer_id),
        "hci_version": hci_version,
        "hci_version_name": hci_version_name(hci_version),
        "hci_revision": hci_revision,
        "hci_revision_hex": f"0x{hci_revision:04X}",
        "lmp_version": lmp_version,
        "lmp_version_name": hci_version_name(lmp_version),
        "lmp_subversion": lmp_subversion,
        "lmp_subversion_hex": f"0x{lmp_subversion:04X}",
        "capability_summary": summary,
        # ACL buffer pool sizes from HCI_Read_Buffer_Size / HCI_LE_Read_Buffer_Size.
        # ``total_packets`` is the Total_Num_*_ACL_Data_Packets credit count
        # that L2CAP flow control uses (HCIController._acl_flow semaphore).
        # On dual-mode adapters where LE shares the BR/EDR pool, the LE
        # response's total_packets is 0 (controller signals "use BR/EDR pool").
        "acl_buffers": {
            "bredr_packet_length": hci.acl_packet_length,
            "bredr_total_packets": hci.acl_total_packets,
            "le_packet_length": hci.le_acl_packet_length,
            "le_total_packets": hci.le_acl_total_packets,
        },
        "le_features": le_decoded,
        "bredr_features": bredr_decoded,
        "bredr_features_page1": bredr_decoded_p1,
        "bredr_features_page2": bredr_decoded_p2,
        # LE Features extension pages (Spec 6.0+). Empty dict on Spec 5.4
        # controllers since they don't advertise Read_Local_Supported_Features_Page.
        "le_features_pages": {
            str(page): bytes(features).hex()
            for page, features in sorted(le_features_pages.items())
        },
        "le_features_max_page": le_features_max_page,
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
    """Decode the 64-byte Supported_Commands bitmap.

    Returns (decoded, unknown_bits_set). decoded is {"<octet>/<bit>": "<name>"}
    for every set bit whose position appears in SUPPORTED_COMMAND_NAMES.
    Set bits at positions not in that table are reserved or vendor-specific
    in Spec 5.4; they end up in unknown_bits_set.
    """
    decoded: dict[str, str] = {}
    unknown: list[dict[str, int]] = []
    for octet in range(len(cmd_bitmap)):
        byte = cmd_bitmap[octet]
        for bit in range(8):
            if byte & (1 << bit):
                name = SUPPORTED_COMMAND_NAMES.get((octet, bit))
                if name is not None:
                    decoded[f"{octet}/{bit}"] = name
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
        f"  HCI Version     : {data['hci_version_name']} "
        f"(raw 0x{data['hci_version']:02X}, revision {data['hci_revision_hex']})"
    )
    lines.append(
        f"  LMP Version     : {data['lmp_version_name']} "
        f"(raw 0x{data['lmp_version']:02X})"
    )
    lines.append(
        f"  LMP Subversion  : {data['lmp_subversion_hex']} "
        f"({data['lmp_subversion']} — vendor-specific firmware build)"
    )
    lines.append("")

    lines.append("Capability summary")
    lines.append("------------------")
    for key, val in data["capability_summary"].items():
        marker = "yes" if val else "-"
        lines.append(f"  {key:<32} : {marker}")
    lines.append("")

    buf = data["acl_buffers"]
    lines.append("ACL buffer pool (L2CAP flow control credit source)")
    lines.append("---------------------------------------------------")
    lines.append(
        f"  BR/EDR packet length  : "
        f"{buf['bredr_packet_length'] if buf['bredr_packet_length'] is not None else '-'}"
    )
    lines.append(
        f"  BR/EDR total packets  : "
        f"{buf['bredr_total_packets'] if buf['bredr_total_packets'] is not None else '-'}"
    )
    lines.append(
        f"  LE packet length      : "
        f"{buf['le_packet_length'] if buf['le_packet_length'] is not None else '-'}"
    )
    le_total = buf["le_total_packets"]
    if le_total == 0:
        lines.append(
            "  LE total packets      : 0 (shares BR/EDR pool — per Spec 5.4 Vol 4 §4.1.1)"
        )
    else:
        lines.append(
            f"  LE total packets      : "
            f"{le_total if le_total is not None else '-'}"
        )
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

    if data["bredr_features_page1"]:
        lines.append("BR/EDR Features (page 1, host features)")
        lines.append("---------------------------------------")
        for ob, entry in data["bredr_features_page1"].items():
            marker = "yes" if entry["supported"] else " "
            lines.append(f"  {ob:<5} {entry['name']:<55} : {marker}")
        lines.append("")

    if data["bredr_features_page2"]:
        lines.append("BR/EDR Features (page 2, controller extended)")
        lines.append("---------------------------------------------")
        for ob, entry in data["bredr_features_page2"].items():
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
