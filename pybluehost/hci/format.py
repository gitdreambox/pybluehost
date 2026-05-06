"""Render an HCIPacket as a human-readable line for console / log output."""
from __future__ import annotations

from pybluehost.core.trace import Direction
from pybluehost.hci.packets import (
    HCI_Command_Complete_Event,
    HCI_Command_Status_Event,
    HCI_LE_Meta_Event,
    HCICommand,
    HCIEvent,
    HCIPacket,
    parse_le_advertising_reports,
)
from pybluehost.hci.format_fields import (
    format_address,
    format_status,
    format_rssi,
)

_DIR_LABELS = {Direction.DOWN: "↓ HCI", Direction.UP: "↑ HCI"}


def format_hci_packet(
    packet: HCIPacket,
    *,
    direction: Direction,
    color: bool = False,
    expand: bool = False,
) -> str:
    """Render an HCIPacket as a single line (or multi-line when expand=True)."""
    dir_label = _DIR_LABELS.get(direction, "  HCI")
    type_label, name, params = _packet_summary(packet)

    if expand:
        return _format_expanded(dir_label, type_label, name, packet)
    return f"{dir_label} {type_label:<4} {name:<32} {params}".rstrip()


def _packet_summary(packet: HCIPacket) -> tuple[str, str, str]:
    """Return (type_label, name, compact_params_string)."""
    if isinstance(packet, HCICommand):
        name = type(packet).__name__
        params = _command_params(packet)
        return ("Cmd", name, params)
    if isinstance(packet, HCIEvent):
        name, params = _event_summary(packet)
        return ("Evt", name, params)
    return ("Pkt", type(packet).__name__, "")


def _command_params(packet: HCICommand) -> str:
    opcode = getattr(packet, "opcode", None)
    if opcode is None:
        return ""
    return f"opcode=0x{opcode:04X}"


def _event_summary(packet: HCIEvent) -> tuple[str, str]:
    if isinstance(packet, HCI_Command_Complete_Event):
        opcode = packet.command_opcode
        status = format_status(packet.return_parameters[0]) if packet.return_parameters else "?"
        return ("Command_Complete", f"op=0x{opcode:04X} status={status}")
    if isinstance(packet, HCI_Command_Status_Event):
        return ("Command_Status", f"op=0x{packet.command_opcode:04X} status={format_status(packet.status)}")
    if isinstance(packet, HCI_LE_Meta_Event):
        return _le_meta_summary(packet)
    name = type(packet).__name__
    code = getattr(packet, "event_code", 0)
    return (f"{name} (0x{code:02X})", "")


def _le_meta_summary(packet: HCI_LE_Meta_Event) -> tuple[str, str]:
    sub = packet.subevent_code
    if sub == 0x02:  # LE_Advertising_Report
        reports = parse_le_advertising_reports(packet.subevent_parameters)
        if not reports:
            return ("LE_Advertising_Report", "0 reports")
        first = reports[0]
        addr = format_address(first.address, addr_type=first.address_type)
        extra = f" + {len(reports) - 1} more" if len(reports) > 1 else ""
        return (
            "LE_Advertising_Report",
            f"{addr} rssi={format_rssi(first.rssi)}{extra}",
        )
    return (f"LE_Meta(0x{sub:02X})", "")


def _format_expanded(dir_label: str, type_label: str, name: str, packet: HCIPacket) -> str:
    # Placeholder for Task 4 — for now just append a summary line.
    return f"{dir_label} {type_label:<4} {name}"
