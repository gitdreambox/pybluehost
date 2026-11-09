"""initialize() probes the extended initiator when the bitmap hides it.

Regression guard for the 2026-10 BE200 rig: that firmware accepts
LE_Extended_Create_Connection (answers Command *Status*) but does not
advertise the Supported_Commands octet 38 bit. Trusting the bitmap routed
every connection through the legacy initiator — and on that firmware a
legacy-initiated connection leaves state behind that makes every extended
scan command answer Command Disallowed once the link closes, silently
starving the RPA-observation cases (pair → disconnect → scan).
"""
from __future__ import annotations

import pytest

from pybluehost.hci.constants import (
    HCI_LE_CREATE_CONNECTION_CANCEL,
    HCI_LE_EXTENDED_CREATE_CONNECTION,
)
from pybluehost.hci.controller import HCIController
from pybluehost.hci.packets import HCICommand, decode_hci_packet
from pybluehost.hci.virtual import VirtualController


def _bitmap_without_extended_initiator(super_handle, cmd):
    """The permissive bitmap with the 0x2043 bit cleared."""
    from pybluehost.hci.capabilities import _OPCODE_BIT_POSITIONS

    raw = super_handle(cmd)
    status, bitmap = raw[:1], bytearray(raw[1:])
    octet, bit = _OPCODE_BIT_POSITIONS[HCI_LE_EXTENDED_CREATE_CONNECTION]
    bitmap[octet] &= ~(1 << bit) & 0xFF
    return status + bytes(bitmap)


class _NoExtendedInitiatorVC(VirtualController):
    """Answers Unknown Command for 0x2043 — a controller that truly lacks it."""

    def _handle_read_local_supported_commands(self, cmd: HCICommand) -> bytes:
        return _bitmap_without_extended_initiator(
            super()._handle_read_local_supported_commands, cmd
        )


class _HidesExtendedInitiatorVC(VirtualController):
    """Accepts 0x2043 (Command Status) without advertising the bitmap bit."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen_extended_initiator = 0
        self.seen_cancel = 0

    def _handle_read_local_supported_commands(self, cmd: HCICommand) -> bytes:
        return _bitmap_without_extended_initiator(
            super()._handle_read_local_supported_commands, cmd
        )

    async def process(self, data: bytes):
        pkt = decode_hci_packet(data)
        if isinstance(pkt, HCICommand):
            if pkt.opcode == HCI_LE_EXTENDED_CREATE_CONNECTION:
                self.seen_extended_initiator += 1
                return self._make_command_status(pkt.opcode, status=0x00)
            if pkt.opcode == HCI_LE_CREATE_CONNECTION_CANCEL:
                self.seen_cancel += 1
                return self._make_command_complete(pkt.opcode, b"\x00")
        return await super().process(data)


@pytest.mark.asyncio
async def test_initialize_probes_and_merges_a_hidden_extended_initiator():
    vc, host_t = await _HidesExtendedInitiatorVC.create()
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)

    await hci.initialize()

    assert vc.seen_extended_initiator == 1
    # The dummy creation must be cancelled — a create in progress blocks the
    # LE scan and address-resolution families.
    assert vc.seen_cancel == 1
    assert hci.supported_commands is not None
    assert hci.supported_commands.has(HCI_LE_EXTENDED_CREATE_CONNECTION)


@pytest.mark.asyncio
async def test_initialize_leaves_the_bit_clear_when_the_command_is_unknown():
    vc, host_t = await _NoExtendedInitiatorVC.create()
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)

    await hci.initialize()

    assert hci.supported_commands is not None
    assert not hci.supported_commands.has(HCI_LE_EXTENDED_CREATE_CONNECTION)
