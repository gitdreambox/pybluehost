"""BR/EDR recon: inquiry scan → capture target's BD_ADDR / CoD / EIR / name.

Allowed imports: pybluehost.cli.app.mitm.recon.ClonedIdentity,
pybluehost.hci.controller, pybluehost.hci.constants, pybluehost.hci.packets,
pybluehost.core.address.  No l2cap/ble/classic/gap/profiles/stack.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pybluehost.cli.app.mitm.recon import ClonedIdentity
from pybluehost.hci.constants import (
    EventCode,
    HCI_INQUIRY,
    HCI_INQUIRY_CANCEL,
    HCI_REMOTE_NAME_REQUEST,
)
from pybluehost.hci.packets import HCICommand, HCIEvent

if TYPE_CHECKING:
    from pybluehost.hci.controller import HCIController


# ---------------------------------------------------------------------------
# parse_eir_name — pure, fully unit-tested
# ---------------------------------------------------------------------------

def parse_eir_name(eir: bytes) -> str | None:
    """Return the first Complete (0x09) or Shortened (0x08) Local Name from
    an Extended Inquiry Response payload, or None if not present.

    EIR uses the same AD-structure format as BLE advertising:
    ``[length][type][value...]``.  Guards against malformed input
    (zero-length records, truncated data).
    """
    offset = 0
    while offset < len(eir):
        length = eir[offset]
        if length == 0:
            # Padding — stop parsing
            break
        offset += 1
        if offset + length > len(eir):
            # Truncated record — bail out
            break
        ad_type = eir[offset]
        value = eir[offset + 1: offset + length]
        if ad_type in (0x08, 0x09):
            # Shortened (0x08) or Complete (0x09) Local Name
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return value.decode("latin-1")
        offset += length
    return None


# ---------------------------------------------------------------------------
# _bd_addr_str — 6-byte little-endian → "AA:BB:CC:DD:EE:FF"
# ---------------------------------------------------------------------------

def _bd_addr_str(raw: bytes) -> str:
    return ":".join(f"{b:02X}" for b in reversed(raw))


# ---------------------------------------------------------------------------
# inquiry_for_target — HCI inquiry sequence
# ---------------------------------------------------------------------------

# General Inquiry Access Code LAP (0x9E8B33) as 3 bytes little-endian
_GIAC_LAP = bytes([0x33, 0x8B, 0x9E])

# EXTENDED_INQUIRY_RESULT event code (0x2F) is not in EventCode enum yet
_EVENT_EXTENDED_INQUIRY_RESULT = 0x2F


async def inquiry_for_target(
    controller: "HCIController",
    *,
    target_addr: str | None = None,
    target_name: str | None = None,
    timeout: float = 12.0,
) -> ClonedIdentity:
    """Perform a BR/EDR inquiry and return a ClonedIdentity for the first
    matching device.

    Matching rules (at least one must be provided):
    - ``target_addr``: case-insensitive BD address ("AA:BB:CC:DD:EE:FF")
    - ``target_name``: exact name match via parse_eir_name on EIR data

    Captures bd_addr, CoD, and EIR (from EXTENDED_INQUIRY_RESULT if
    available).  If name is still unknown and ``target_name`` is given (or any
    name is desired), issues HCI_REMOTE_NAME_REQUEST.

    Full validation deferred to Task 5 / hardware integration.
    """
    if target_addr is None and target_name is None:
        raise ValueError("At least one of target_addr or target_name must be specified")

    target_addr_norm = target_addr.upper() if target_addr else None

    # Per-address accumulated state
    cod_map: dict[str, int] = {}
    eir_map: dict[str, bytes] = {}

    matched_event = asyncio.Event()
    matched_addr: list[str] = []
    matched_name: list[str | None] = []

    # Save all three upstream callbacks (set_upstream replaces all three)
    prev_on_hci_event = controller._on_hci_event   # type: ignore[attr-defined]
    prev_on_acl_data  = controller._on_acl_data    # type: ignore[attr-defined]
    prev_on_sco_data  = controller._on_sco_data    # type: ignore[attr-defined]

    # -----------------------------------------------------------------------
    # Inner helpers
    # -----------------------------------------------------------------------

    def _check_match(addr: str) -> None:
        """Signal matched_event if addr satisfies the caller's criteria."""
        if matched_event.is_set():
            return

        addr_match = (target_addr_norm is not None and addr.upper() == target_addr_norm)
        name_match = False
        if target_name is not None:
            eir_name = parse_eir_name(eir_map.get(addr, b""))
            name_match = (eir_name == target_name)

        if addr_match or name_match:
            if not matched_addr:
                matched_addr.append(addr)
                eir_name = parse_eir_name(eir_map.get(addr, b""))
                matched_name.append(eir_name)
            matched_event.set()

    def _parse_inquiry_result(data: bytes) -> None:
        """Parse HCI_INQUIRY_RESULT (EventCode 0x02).

        Layout: num_responses(1), then per-response:
          bd_addr(6 LE) | page_scan_rep_mode(1) | reserved(2) |
          class_of_device(3 LE) | clock_offset(2)   → 14 bytes total per entry
        """
        if not data:
            return
        count = data[0]
        offset = 1
        for _ in range(count):
            if offset + 13 > len(data):
                return
            addr_raw = data[offset: offset + 6]
            offset += 6
            offset += 2  # page_scan_rep_mode(1) + reserved(1) — note: 2 bytes per spec
            cod = int.from_bytes(data[offset: offset + 3], "little")
            offset += 3
            offset += 2  # clock_offset
            addr = _bd_addr_str(addr_raw)
            cod_map[addr] = cod
            _check_match(addr)

    def _parse_extended_inquiry_result(data: bytes) -> None:
        """Parse HCI_EXTENDED_INQUIRY_RESULT (0x2F).

        Layout: num_responses(1)=1, bd_addr(6 LE), page_scan_rep_mode(1),
                reserved(1), class_of_device(3 LE), clock_offset(2),
                rssi(1), eir_data(240).  Total params = 255 bytes.
        """
        if len(data) < 15:
            return
        # num_responses at offset 0 (always 1)
        offset = 1
        addr_raw = data[offset: offset + 6]
        offset += 6
        offset += 1  # page_scan_rep_mode
        offset += 1  # reserved
        cod = int.from_bytes(data[offset: offset + 3], "little")
        offset += 3
        offset += 2  # clock_offset
        offset += 1  # rssi
        eir_data = data[offset: offset + 240] if offset + 240 <= len(data) else data[offset:]
        addr = _bd_addr_str(addr_raw)
        cod_map[addr] = cod
        eir_map[addr] = eir_data
        _check_match(addr)

    def _on_remote_name_complete(data: bytes) -> None:
        """Parse REMOTE_NAME_REQUEST_COMPLETE (0x07).

        Layout: status(1) + bd_addr(6 LE) + name(248, NUL-padded).
        """
        if len(data) < 7:
            return
        status = data[0]
        if status != 0x00:
            # Name request failed — still unblock if addr matched
            if matched_addr and not matched_event.is_set():
                matched_event.set()
            return
        addr_raw = data[1:7]
        addr = _bd_addr_str(addr_raw)
        name_raw = data[7:7 + 248] if len(data) >= 255 else data[7:]
        name = name_raw.rstrip(b"\x00").decode("utf-8", errors="replace") or None
        if matched_addr and addr.upper() == matched_addr[0].upper():
            matched_name.clear()
            matched_name.append(name)
            matched_event.set()

    def on_hci_event(event: HCIEvent) -> None:
        code = event.event_code
        params = event.parameters if hasattr(event, "parameters") else b""

        if code == EventCode.INQUIRY_RESULT:
            _parse_inquiry_result(params)
        elif code == _EVENT_EXTENDED_INQUIRY_RESULT:
            _parse_extended_inquiry_result(params)
        elif code == EventCode.REMOTE_NAME_REQUEST_COMPLETE:
            _on_remote_name_complete(params)
        else:
            # Pass through to previous handler
            if prev_on_hci_event is not None:
                result = prev_on_hci_event(event)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)

    # Register our handler
    controller.set_upstream(on_hci_event=on_hci_event)

    try:
        # Start inquiry: GIAC LAP, duration=8 (≈10.24 s), unlimited responses
        inquiry_params = _GIAC_LAP + bytes([0x08, 0x00])
        await controller.send_command(
            HCICommand(opcode=HCI_INQUIRY, parameters=inquiry_params)
        )

        # Wait for a matching device (or timeout)
        await asyncio.wait_for(matched_event.wait(), timeout=timeout)

        addr = matched_addr[0]

        # If name is still unknown after EIR parsing, issue Remote_Name_Request
        name_from_eir = parse_eir_name(eir_map.get(addr, b""))
        if name_from_eir is None and target_name is not None:
            # Re-arm event so we can wait for name completion
            matched_event.clear()
            name_params = bytes.fromhex(
                # bd_addr 6 bytes little-endian
                "".join(f"{b:02X}" for b in bytes.fromhex(addr.replace(":", ""))[::-1])
            ) + bytes([0x01, 0x00, 0x00, 0x00])
            await controller.send_command(
                HCICommand(opcode=HCI_REMOTE_NAME_REQUEST, parameters=name_params)
            )
            # Wait up to remaining time (use a fresh short window)
            try:
                await asyncio.wait_for(matched_event.wait(), timeout=min(timeout, 10.0))
            except asyncio.TimeoutError:
                pass  # Return what we have

    finally:
        # Cancel any ongoing inquiry
        try:
            await controller.send_command(
                HCICommand(opcode=HCI_INQUIRY_CANCEL, parameters=b"")
            )
        except Exception:
            pass
        # Restore ALL previous upstream callbacks
        controller.set_upstream(
            on_hci_event=prev_on_hci_event,
            on_acl_data=prev_on_acl_data,
            on_sco_data=prev_on_sco_data,
        )

    addr = matched_addr[0]
    final_eir = eir_map.get(addr, b"")
    final_name = (
        matched_name[0] if matched_name else parse_eir_name(final_eir)
    )

    return ClonedIdentity(
        address=addr,
        address_type=0,  # BR/EDR is always public (type 0)
        adv_data=final_eir,
        scan_response=b"",
        name=final_name,
    )
