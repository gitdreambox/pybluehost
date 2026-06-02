"""BLE recon: scan for a target device and capture its application-layer identity.

Allowed imports: pybluehost.hci.controller, pybluehost.hci.constants,
pybluehost.hci.packets.  No l2cap/ble/classic/gap/profiles/stack.
"""

from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pybluehost.hci.constants import (
    EventCode,
    HCI_LE_SET_SCAN_ENABLE,
    HCI_LE_SET_SCAN_PARAMS,
    LEMetaSubEvent,
)
from pybluehost.hci.packets import (
    HCI_LE_Meta_Event,
    HCICommand,
    HCIEvent,
    parse_le_advertising_reports,
)

if TYPE_CHECKING:
    from pybluehost.hci.controller import HCIController


# ---------------------------------------------------------------------------
# ClonedIdentity — snapshot of a target device's advertising identity
# ---------------------------------------------------------------------------

@dataclass
class ClonedIdentity:
    """Captured application-layer identity of a scanned BLE device."""

    address: str           # "AA:BB:CC:DD:EE:FF" (upper-case)
    address_type: int      # 0=public, 1=random
    adv_data: bytes        # payload from ADV_IND / ADV_SCAN_IND report
    scan_response: bytes   # payload from SCAN_RSP report (may be empty)
    name: str | None       # decoded local name from adv/scan-rsp, or None


# ---------------------------------------------------------------------------
# parse_adv_name — pure AD-structure parser
# ---------------------------------------------------------------------------

def parse_adv_name(adv: bytes) -> str | None:
    """Return the first Complete (0x09) or Shortened (0x08) Local Name from
    an advertising payload, or None if not present.

    Iterates AD structures ``[length][type][value...]``.  Guards against
    malformed input (zero-length records, truncated data).
    """
    offset = 0
    while offset < len(adv):
        length = adv[offset]
        if length == 0:
            # AD length 0 means padding — stop parsing
            break
        offset += 1
        if offset + length > len(adv):
            # Truncated record — bail out
            break
        ad_type = adv[offset]
        value = adv[offset + 1: offset + length]
        if ad_type in (0x08, 0x09):
            # Shortened Local Name (0x08) or Complete Local Name (0x09)
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return value.decode("latin-1")
        offset += length
    return None


# ---------------------------------------------------------------------------
# scan_for_target — active BLE scan using HCIController
# ---------------------------------------------------------------------------

async def scan_for_target(
    controller: "HCIController",
    *,
    target_addr: str | None = None,
    target_name: str | None = None,
    timeout: float = 10.0,
) -> ClonedIdentity:
    """Perform an active BLE scan and return a ClonedIdentity for the first
    matching device.

    Matching rules (at least one must be provided):
    - ``target_addr``: case-insensitive BD address string ("AA:BB:CC:DD:EE:FF")
    - ``target_name``: exact name match via parse_adv_name

    Accumulates adv_data from any non-SCAN_RSP report and scan_response from
    a SCAN_RSP (event_type 0x04) for the same address.  Returns as soon as
    both are seen, or on timeout (adv_data alone is sufficient).

    Raises asyncio.TimeoutError if the timeout expires before any match.
    """
    if target_addr is None and target_name is None:
        raise ValueError("At least one of target_addr or target_name must be specified")

    target_addr_norm = target_addr.upper() if target_addr else None

    # Per-address state collected so far
    adv_data_map: dict[str, bytes] = {}
    scan_rsp_map: dict[str, bytes] = {}
    addr_type_map: dict[str, int] = {}

    matched_event = asyncio.Event()
    matched_addr: list[str] = []  # populated when a match is found

    # Save previous upstream callbacks so we can restore ALL of them on exit
    # (set_upstream overwrites on_hci_event/on_acl_data/on_sco_data together —
    # restoring only on_hci_event would silently clear the other two).
    prev_on_hci_event = controller._on_hci_event  # type: ignore[attr-defined]
    prev_on_acl_data = controller._on_acl_data  # type: ignore[attr-defined]
    prev_on_sco_data = controller._on_sco_data  # type: ignore[attr-defined]

    def on_hci_event(event: HCIEvent) -> None:
        if event.event_code != EventCode.LE_META:
            # Pass through to previous handler
            if prev_on_hci_event is not None:
                result = prev_on_hci_event(event)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            return

        # Decode the LE Meta event to access subevent fields
        if isinstance(event, HCI_LE_Meta_Event):
            subevent_code = event.subevent_code
            subevent_params = event.subevent_parameters
        elif hasattr(event, "parameters") and event.parameters:
            subevent_code = event.parameters[0]
            subevent_params = event.parameters[1:]
        else:
            return

        if subevent_code != LEMetaSubEvent.LE_ADVERTISING_REPORT:
            # Pass through other LE meta events
            if prev_on_hci_event is not None:
                result = prev_on_hci_event(event)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            return

        reports = parse_le_advertising_reports(subevent_params)
        for report in reports:
            # Convert 6-byte little-endian address to "AA:BB:CC:DD:EE:FF"
            addr_str = ":".join(f"{b:02X}" for b in reversed(report.address))
            addr_type_map[addr_str] = report.address_type

            is_scan_rsp = (report.event_type == 0x04)

            if is_scan_rsp:
                scan_rsp_map[addr_str] = report.data
            else:
                adv_data_map[addr_str] = report.data

            # Check if this address already matched (accumulating scan_rsp)
            if matched_addr and addr_str == matched_addr[0] and not matched_event.is_set():
                # Got scan response for already-matched address — signal.
                # continue (not return): sibling reports in the same LE Meta
                # packet must still be processed.
                matched_event.set()
                continue

            # Skip match check for pure SCAN_RSP (no adv_data yet)
            if is_scan_rsp and addr_str not in adv_data_map:
                continue

            # Check match criteria
            addr_match = (target_addr_norm is not None and addr_str == target_addr_norm)
            name_match = False
            if target_name is not None:
                name_from_adv = parse_adv_name(adv_data_map.get(addr_str, b""))
                name_from_rsp = parse_adv_name(scan_rsp_map.get(addr_str, b""))
                name_match = (name_from_adv == target_name or name_from_rsp == target_name)

            if addr_match or name_match:
                if not matched_addr:
                    matched_addr.append(addr_str)
                # Signal immediately if both adv + scan_rsp seen, else wait
                if addr_str in adv_data_map and addr_str in scan_rsp_map:
                    matched_event.set()
                elif addr_str in adv_data_map:
                    # Signal now; caller will return with what we have
                    matched_event.set()

    # Register our handler
    controller.set_upstream(on_hci_event=on_hci_event)

    try:
        # Configure active scanning: type=0x01, interval=0x0010, window=0x0010,
        # own_addr_type=0x00, filter_policy=0x00
        scan_params = struct.pack("<BHHBB", 0x01, 0x0010, 0x0010, 0x00, 0x00)
        await controller.send_command(
            HCICommand(opcode=HCI_LE_SET_SCAN_PARAMS, parameters=scan_params)
        )

        # Enable scanning, filter_duplicates=0 (so we see both ADV and SCAN_RSP)
        scan_enable = bytes([0x01, 0x00])
        await controller.send_command(
            HCICommand(opcode=HCI_LE_SET_SCAN_ENABLE, parameters=scan_enable)
        )

        # Wait for a match (or timeout)
        await asyncio.wait_for(matched_event.wait(), timeout=timeout)

    finally:
        # Stop scanning
        try:
            scan_disable = bytes([0x00, 0x00])
            await controller.send_command(
                HCICommand(opcode=HCI_LE_SET_SCAN_ENABLE, parameters=scan_disable)
            )
        except Exception:
            pass
        # Restore ALL previous upstream callbacks (not just on_hci_event)
        controller.set_upstream(
            on_hci_event=prev_on_hci_event,
            on_acl_data=prev_on_acl_data,
            on_sco_data=prev_on_sco_data,
        )

    # Build ClonedIdentity from accumulated data
    addr = matched_addr[0]
    final_adv = adv_data_map.get(addr, b"")
    final_rsp = scan_rsp_map.get(addr, b"")
    name = parse_adv_name(final_adv) or parse_adv_name(final_rsp)

    return ClonedIdentity(
        address=addr,
        address_type=addr_type_map.get(addr, 0),
        adv_data=final_adv,
        scan_response=final_rsp,
        name=name,
    )
