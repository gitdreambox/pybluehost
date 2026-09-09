"""BR/EDR recon: inquiry scan → capture target's BD_ADDR / CoD / EIR / name.

Allowed imports: pybluehost.cli.app.mitm.recon.ClonedIdentity,
pybluehost.hci.controller, pybluehost.hci.constants, pybluehost.hci.packets,
pybluehost.core.address.  No l2cap/ble/classic/gap/profiles/stack.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pybluehost.cli.app.mitm.recon import ClonedIdentity
from pybluehost.hci.constants import (
    EventCode,
    HCI_INQUIRY,
    HCI_INQUIRY_CANCEL,
    HCI_REMOTE_NAME_REQUEST,
    HCI_WRITE_INQUIRY_MODE,
)
from pybluehost.hci.packets import HCICommand, HCIEvent

if TYPE_CHECKING:
    from pybluehost.hci.controller import HCIController

logger = logging.getLogger(__name__)


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
# Inquiry result parsing — pure functions (extracted from inquiry_for_target)
# ---------------------------------------------------------------------------

def parse_inquiry_result_entries(data: bytes) -> list[tuple[str, int | None]]:
    """HCI_Inquiry_Result(0x02) → [(addr_str, CoD)]. 14 bytes per entry.

    Layout: num_responses(1), then per-response:
      bd_addr(6 LE) | page_scan_rep_mode(1) + reserved(2) |
      class_of_device(3 LE) | clock_offset(2)   → 14 bytes total per entry
    """
    if not data:
        return []
    count = data[0]
    offset = 1
    out: list[tuple[str, int | None]] = []
    for _ in range(count):
        # 14 bytes per entry (Core Vol4 E §7.7.2). Note: classic/gap.py historically
        # skipped only 2 bytes (skip-2/guard-13), which does not match the spec; here
        # we skip 3 per spec (PSRM 1 + Reserved 2).
        if offset + 14 > len(data):
            return out
        addr = _bd_addr_str(data[offset: offset + 6])
        offset += 6
        offset += 3  # page_scan_rep_mode(1) + reserved(2)
        cod = int.from_bytes(data[offset: offset + 3], "little")
        offset += 3
        offset += 2  # clock_offset
        out.append((addr, cod))
    return out


def parse_inquiry_result_with_rssi_entries(
    data: bytes,
) -> list[tuple[str, int | None, int | None]]:
    """HCI_Inquiry_Result_with_RSSI(0x22) → [(addr, CoD, rssi), ...].

    Layout per response (num_responses at offset 0, up to 10):
    addr(6 LE) page_scan_rep_mode(1) page_scan_period_mode(1)
    page_scan_mode(1) class_of_device(3 LE) clock_offset(2 LE) rssi(1).
    """
    if not data:
        return []
    count = data[0]
    offset = 1
    out: list[tuple[str, int | None, int | None]] = []
    for _ in range(count):
        # 15 bytes per entry (Core Vol4 E §7.7.3)
        if offset + 15 > len(data):
            return out
        addr = _bd_addr_str(data[offset: offset + 6])
        offset += 6
        offset += 3  # page_scan_rep_mode(1) + page_scan_period_mode(1) + page_scan_mode(1)
        cod = int.from_bytes(data[offset: offset + 3], "little")
        offset += 3
        offset += 2  # clock_offset
        rssi = data[offset]
        if rssi >= 128:
            rssi -= 256  # signed byte
        offset += 1
        out.append((addr, cod, rssi))
    return out


def parse_extended_inquiry_result_entry(
    data: bytes,
) -> tuple[str, int | None, bytes, int | None]:
    """HCI_Extended_Inquiry_Result(0x2F) → (addr, CoD, EIR, rssi)。

    Layout: num_responses(1)=1, bd_addr(6 LE), page_scan_rep_mode(1),
            reserved(1), class_of_device(3 LE), clock_offset(2),
            rssi(1), eir_data(240).  Total params = 255 bytes.
    """
    if len(data) < 15:
        return "", None, b"", None
    # num_responses at offset 0 (always 1)
    offset = 1
    addr = _bd_addr_str(data[offset: offset + 6])
    offset += 6
    offset += 1  # page_scan_rep_mode
    offset += 1  # reserved
    cod = int.from_bytes(data[offset: offset + 3], "little")
    offset += 3
    offset += 2  # clock_offset
    rssi = data[offset] if offset < len(data) else None
    if rssi is not None and rssi >= 128:
        rssi -= 256  # signed byte
    offset += 1
    eir = data[offset: offset + 240] if offset + 240 <= len(data) else data[offset:]
    return addr, cod, eir, rssi


# ---------------------------------------------------------------------------
# inquiry_for_target — HCI inquiry sequence
# ---------------------------------------------------------------------------

# General Inquiry Access Code LAP (0x9E8B33) as 3 bytes little-endian
_GIAC_LAP = bytes([0x33, 0x8B, 0x9E])


async def inquiry_for_target(
    controller: "HCIController",
    *,
    target_addr: str | None = None,
    target_name: str | None = None,
    timeout: float = 12.0,
    total_timeout: float = 90.0,
) -> ClonedIdentity:
    """Perform a BR/EDR inquiry and return a ClonedIdentity for the first
    matching device.

    Matching rules (at least one must be provided):
    - ``target_addr``: case-insensitive BD address ("AA:BB:CC:DD:EE:FF")
    - ``target_name``: exact name match via parse_eir_name on EIR data

    Captures bd_addr, CoD, and EIR (from EXTENDED_INQUIRY_RESULT if
    available).  If the name is still unknown after EIR parsing, issues
    HCI_REMOTE_NAME_REQUEST to capture the target's real local name (needed
    for transparent impersonation regardless of the match criteria).

    Real-hardware experience (JBL Live Beam 4, 2026-09-04): TWS earbuds answer GIAC
    inquiry only in pairing/discoverable mode, and the pairing-mode window is short
    (minutes); they do not answer at all while connected to a phone. A single ~10s
    window is easy to miss → rescan in a loop within the ``total_timeout`` budget,
    ``timeout`` seconds per round, logging and continuing on a miss so the operator
    has time to re-trigger pairing mode without restarting the script.
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

    def on_hci_event(event: HCIEvent) -> None:
        code = event.event_code
        params = event.parameters if hasattr(event, "parameters") else b""

        if code == EventCode.INQUIRY_RESULT:
            for addr, cod in parse_inquiry_result_entries(params):
                cod_map[addr] = cod
                _check_match(addr)
        elif code == EventCode.EXTENDED_INQUIRY_RESULT:
            addr, cod, eir_data, _rssi = parse_extended_inquiry_result_entry(params)
            if addr:
                cod_map[addr] = cod
                eir_map[addr] = eir_data
                _check_match(addr)
        elif prev_on_hci_event is not None:
            # Pass through to previous handler
            result = prev_on_hci_event(event)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)

    # Register our handler
    controller.set_upstream(on_hci_event=on_hci_event)

    try:
        # Rescan loop: single-round GIAC inquiry, duration=8 (≈10.24 s), unlimited
        # responses. A non-discoverable earbud yields an empty round; rescan within
        # the total_timeout budget until matched.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + total_timeout
        inquiry_params = _GIAC_LAP + bytes([0x08, 0x00])
        round_no = 0
        while True:
            round_no += 1
            await controller.send_command(
                HCICommand(opcode=HCI_INQUIRY, parameters=inquiry_params)
            )
            try:
                await asyncio.wait_for(matched_event.wait(), timeout=timeout)
                break  # matched
            except asyncio.TimeoutError:
                # Missed this round: leave inquiry state first (cancel is idempotent
                # before a match), then decide whether to rescan
                try:
                    await controller.send_command(
                        HCICommand(opcode=HCI_INQUIRY_CANCEL, parameters=b"")
                    )
                except Exception:
                    pass
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError(
                        f"inquiry {total_timeout:.0f}s 内未发现目标 "
                        f"{target_addr or target_name}(设备需处于配对/可发现模式;"
                        f"已重扫 {round_no} 轮)"
                    )
                logger.warning(
                    "recon: 第 %d 轮 inquiry 未发现目标 %s,继续扫描(剩余 ~%.0fs;"
                    "请确认设备处于配对/可发现模式)",
                    round_no, target_addr or target_name, remaining,
                )

        addr = matched_addr[0]

        # If name is still unknown after EIR parsing, issue Remote_Name_Request.
        # Transparent MITM needs the target's real name to clone the local name
        # (otherwise impersonate skips Write Local Name, the dongle has an empty name,
        # and the phone's scan list shows nothing to tap). So regardless of whether a
        # target_name criterion was given, RNR proactively whenever EIR has no name.
        name_from_eir = parse_eir_name(eir_map.get(addr, b""))
        if name_from_eir is None:
            # Re-arm event so we can wait for name completion
            matched_event.clear()
            # fetch_remote_name first cancels any in-progress inquiry: Intel
            # controllers return 0x0C Command Disallowed for RNR during inquiry
            # (real-hardware finding), so the controller must leave inquiry state
            # before Remote_Name_Request can be sent. The target is already matched,
            # so inquiry can stop at any time. RNR failure/timeout still releases the
            # wait and returns the info gathered so far.
            name = await fetch_remote_name(
                controller, addr, timeout=min(timeout, 10.0)
            )
            if name is not None:
                matched_name.clear()
                matched_name.append(name)
            matched_event.set()

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
        class_of_device=cod_map.get(addr),
    )


# ---------------------------------------------------------------------------
# fetch_remote_name — Remote_Name_Request for a single device
# ---------------------------------------------------------------------------


async def fetch_remote_name(
    controller: "HCIController", addr: str, *, timeout: float = 10.0
) -> str | None:
    """Remote_Name_Request for a single device (Inquiry_Cancel first, required by Intel hardware). Returns None on failure."""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str | None] = loop.create_future()
    prev_on_hci_event = controller._on_hci_event  # type: ignore[attr-defined]
    prev_on_acl_data = controller._on_acl_data    # type: ignore[attr-defined]
    prev_on_sco_data = controller._on_sco_data    # type: ignore[attr-defined]
    addr_le = bytes.fromhex(addr.replace(":", ""))[::-1]

    def on_event(event: HCIEvent) -> None:
        if event.event_code == EventCode.REMOTE_NAME_REQUEST_COMPLETE:
            p = event.parameters
            if len(p) >= 7 and p[1:7] == addr_le:
                if not fut.done():
                    if p[0] != 0x00:
                        fut.set_result(None)
                    else:
                        raw = p[7:255]
                        fut.set_result(
                            raw.rstrip(b"\x00").decode("utf-8", errors="replace") or None
                        )
        if prev_on_hci_event is not None:
            result = prev_on_hci_event(event)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)

    controller.set_upstream(on_hci_event=on_event)
    try:
        try:
            await controller.send_command(
                HCICommand(opcode=HCI_INQUIRY_CANCEL, parameters=b"")
            )
        except Exception:
            pass  # cancel errors are normal when not in inquiry state
        try:
            await controller.send_command(
                HCICommand(
                    opcode=HCI_REMOTE_NAME_REQUEST,
                    parameters=addr_le + bytes([0x01, 0x00, 0x00, 0x00]),
                )
            )
        except Exception:
            return None
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return None
    finally:
        controller.set_upstream(
            on_hci_event=prev_on_hci_event,
            on_acl_data=prev_on_acl_data,
            on_sco_data=prev_on_sco_data,
        )


# ---------------------------------------------------------------------------
# inquiry_scan_all — BR/EDR full scan
# ---------------------------------------------------------------------------


async def inquiry_scan_all(
    controller: "HCIController",
    *,
    rounds: int = 2,
    round_seconds: float = 10.24,
) -> "list[ScanEntry]":
    """BR/EDR inquiry full scan: `rounds` rounds (default 2 ≈ 20s), collecting all devices.

    EIR names are used directly; devices without a name are NOT RNR'd during the scan
    (per-device RNR is too slow) — the caller runs fetch_remote_name for the single
    device the user picks.
    """
    from pybluehost.cli.app.mitm.recon import ScanEntry  # noqa: PLC0415

    cod_map: dict[str, int | None] = {}
    eir_map: dict[str, bytes] = {}
    rssi_map: dict[str, int | None] = {}

    prev_on_hci_event = controller._on_hci_event  # type: ignore[attr-defined]
    prev_on_acl_data = controller._on_acl_data    # type: ignore[attr-defined]
    prev_on_sco_data = controller._on_sco_data    # type: ignore[attr-defined]

    def on_event(event: HCIEvent) -> None:
        code = event.event_code
        params = getattr(event, "parameters", b"") or b""
        if code == EventCode.INQUIRY_RESULT:
            for addr, cod in parse_inquiry_result_entries(params):
                cod_map.setdefault(addr, cod)
        elif code == EventCode.INQUIRY_RESULT_WITH_RSSI:
            for addr, cod, rssi in parse_inquiry_result_with_rssi_entries(params):
                cod_map.setdefault(addr, cod)
                rssi_map[addr] = rssi
        elif code == EventCode.EXTENDED_INQUIRY_RESULT:
            addr, cod, eir, rssi = parse_extended_inquiry_result_entry(params)
            if addr:
                cod_map.setdefault(addr, cod)
                eir_map[addr] = eir
                rssi_map[addr] = rssi
        elif prev_on_hci_event is not None:
            result = prev_on_hci_event(event)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)

    controller.set_upstream(on_hci_event=on_event)
    try:
        # Controllers power up in inquiry mode 0 (legacy) and only return legacy
        # Inquiry_Result (no RSSI/name) → set mode 2 (EIR with RSSI) first so results
        # carry RSSI and names. Some controllers/flows may not support the command;
        # on failure just warn and fall back to legacy results.
        try:
            await controller.send_command(
                HCICommand(opcode=HCI_WRITE_INQUIRY_MODE, parameters=bytes([2]))
            )
        except Exception as e:
            logger.warning(
                "Write_Inquiry_Mode 失败,退回 legacy inquiry 结果: %s", e
            )
        for _ in range(max(1, rounds)):
            try:
                await controller.send_command(
                    HCICommand(
                        opcode=HCI_INQUIRY,
                        parameters=_GIAC_LAP + bytes([0x08, 0x00]),
                    )
                )
            except Exception:
                pass
            await asyncio.sleep(round_seconds)
            try:
                await controller.send_command(
                    HCICommand(opcode=HCI_INQUIRY_CANCEL, parameters=b"")
                )
            except Exception:
                pass
    finally:
        controller.set_upstream(
            on_hci_event=prev_on_hci_event,
            on_acl_data=prev_on_acl_data,
            on_sco_data=prev_on_sco_data,
        )

    entries: list[ScanEntry] = []
    for addr in sorted(cod_map):
        name = parse_eir_name(eir_map.get(addr, b""))
        entries.append(ScanEntry(
            identity=ClonedIdentity(
                address=addr,
                address_type=0,
                adv_data=eir_map.get(addr, b""),
                scan_response=b"",
                name=name,
                class_of_device=cod_map.get(addr),
            ),
            rssi=rssi_map.get(addr),
        ))
    return entries
