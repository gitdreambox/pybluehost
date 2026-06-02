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
    HCI_WRITE_LOCAL_NAME,
    HCI_WRITE_SCAN_ENABLE,
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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
    5. Write Scan Enable = 0x03 (inquiry scan + page scan).
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

    # 3. Write Extended Inquiry Response
    eir = identity.adv_data or b""
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

    # 5. Enable inquiry scan + page scan
    await controller.send_command(
        HCICommand(
            opcode=HCI_WRITE_SCAN_ENABLE,
            parameters=bytes([0x03]),
        )
    )
