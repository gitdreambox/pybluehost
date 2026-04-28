"""'app sdp-browser' — connect, query SDP records, print, exit."""
from __future__ import annotations

import argparse
import asyncio
import sys

from pybluehost.classic.sdp import DataElement, DataElementType, SDPClient
from pybluehost.cli._target import TARGET_HELP, parse_target_arg
from pybluehost.cli._lifecycle import add_trace_arguments, run_app_command, trace_kwargs_from_args
from pybluehost.l2cap.constants import PSM_SDP
from pybluehost.stack import Stack

DEFAULT_SCAN_UUIDS = (
    0x1002,  # Public Browse Group
    0x1000,  # Service Discovery Server
    0x1001,  # Browse Group Descriptor
    0x1101,  # Serial Port
    0x1105,  # OBEX Object Push
    0x1106,  # OBEX File Transfer
    0x1108,  # Headset
    0x110A,  # Audio Source
    0x110B,  # Audio Sink
    0x110C,  # A/V Remote Control Target
    0x110D,  # Advanced Audio Distribution
    0x110E,  # A/V Remote Control
    0x1112,  # Headset Audio Gateway
    0x1115,  # PANU
    0x1116,  # NAP
    0x1117,  # GN
    0x111E,  # Handsfree
    0x111F,  # Handsfree Audio Gateway
    0x1124,  # Human Interface Device
    0x112D,  # SIM Access
    0x1200,  # PnP Information
)


def _parse_uuid_arg(value: str) -> int:
    uuid = int(value, 0)
    if not 0 <= uuid <= 0xFFFF:
        raise argparse.ArgumentTypeError("UUID must be a 16-bit value")
    return uuid


def register_sdp_browser_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("sdp-browser", help="Connect, query SDP, print, exit")
    p.add_argument("-t", "--transport", required=True)
    p.add_argument("-a", "--target", help=TARGET_HELP)
    p.add_argument(
        "--uuid",
        type=_parse_uuid_arg,
        default=None,
        help="Service UUID16 to query; omit to scan common SDP service UUIDs",
    )
    add_trace_arguments(p)
    p.set_defaults(func=lambda args: asyncio.run(_sdp_browser_main(args)))


async def _sdp_browser_main(args: argparse.Namespace) -> int:
    if not args.target:
        print("Error: --target is required", file=sys.stderr)
        return 2

    addr, _atype = parse_target_arg(args.target)
    service_uuid = getattr(args, "uuid", None)
    return await run_app_command(
        args.transport,
        lambda stack, stop: _sdp_browser_run(stack, stop, addr, service_uuid),
        **trace_kwargs_from_args(args),
    )


async def _sdp_browser_run(stack: Stack, stop: asyncio.Event, addr, service_uuid: int) -> None:
    del stop
    print(f"Connecting to {addr}")
    handle = await stack.connect_classic(addr)
    print(f"Connected ACL handle=0x{handle:04X}")
    await stack.authenticate_classic(handle)
    print(f"Authenticated ACL handle=0x{handle:04X}")
    await stack.enable_classic_encryption(handle)
    print(f"Encrypted ACL handle=0x{handle:04X}")
    channel = await stack.l2cap.connect_classic_channel(handle=handle, psm=PSM_SDP)
    if service_uuid is None:
        client = SDPClient(channel, request_timeout=1.0, retries=0)
    else:
        client = SDPClient(channel)
    records = await _query_sdp_records(client, service_uuid)
    if not records:
        print("No SDP records found")
        return
    for index, record in enumerate(records, start=1):
        print(f"Record {index}:")
        for attr_id, value in sorted(record.items()):
            print(f"  0x{attr_id:04X}: {_format_sdp_value(value)}")


async def _query_sdp_records(
    client: SDPClient,
    service_uuid: int | None,
) -> list[dict[int, DataElement]]:
    if service_uuid is not None:
        return await client.search_attributes(target=None, uuid=service_uuid)

    records: list[dict[int, DataElement]] = []
    seen: set[object] = set()
    for uuid in DEFAULT_SCAN_UUIDS:
        try:
            found = await client.search_attributes(target=None, uuid=uuid)
        except TimeoutError:
            continue
        for record in found:
            key = _record_key(record)
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
    return records


def _record_key(record: dict[int, object]) -> object:
    handle = record.get(0x0000)
    if isinstance(handle, DataElement):
        return ("handle", handle.value)
    if handle is not None:
        return ("handle", handle)
    return tuple(sorted((attr_id, _format_sdp_value(value)) for attr_id, value in record.items()))


def _format_sdp_value(value: object) -> str:
    if isinstance(value, DataElement):
        if value.type in (DataElementType.SEQUENCE, DataElementType.ALTERNATIVE):
            return "[" + ", ".join(_format_sdp_value(v) for v in value.value) + "]"
        return str(value.value)
    return str(value)
