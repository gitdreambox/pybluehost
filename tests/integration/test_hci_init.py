"""Integration test: HCIController init sequence against VirtualController."""
from __future__ import annotations

import asyncio
import pytest

from pybluehost.core.errors import CommandTimeoutError
from pybluehost.hci.packets import HCICommand, decode_hci_packet
from pybluehost.hci.constants import (
    HCI_RESET,
    HCI_READ_LOCAL_VERSION,
    HCI_READ_LOCAL_SUPPORTED_COMMANDS,
    HCI_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_READ_LOCAL_EXTENDED_FEATURES,
    HCI_READ_BD_ADDR,
    HCI_READ_BUFFER_SIZE,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_SET_EVENT_MASK,
    HCI_LE_SET_EVENT_MASK,
    HCI_WRITE_LE_HOST_SUPPORTED,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
    HCI_WRITE_SCAN_ENABLE,
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_LE_SET_HOST_FEATURE,
    HCI_LE_EXTENDED_CREATE_CONNECTION,
    HCI_LE_CREATE_CONNECTION_CANCEL,
    # The legacy LE advertising/scanning family (Vol 4 Part E §3.1.1 /
    # Table 3.2). Using any of these makes the controller answer Command
    # Disallowed (0x0C) to every *extended* advertising/scanning command
    # for the rest of the power cycle — so init must never issue one.
    HCI_LE_SET_ADVERTISING_PARAMS,
    HCI_LE_SET_ADVERTISING_DATA,
    HCI_LE_SET_SCAN_RESPONSE_DATA,
    HCI_LE_SET_ADVERTISE_ENABLE,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_LE_SET_SCAN_ENABLE,
    HCI_LE_CREATE_CONNECTION,
)

# HCI_LE_Read_Advertising_Physical_Channel_Tx_Power is the one Table 3.2
# legacy entry with no constant in this stack; it is not issued by init.
LEGACY_LE_ADVERTISING_FAMILY = frozenset(
    {
        HCI_LE_SET_ADVERTISING_PARAMS,
        HCI_LE_SET_ADVERTISING_DATA,
        HCI_LE_SET_SCAN_RESPONSE_DATA,
        HCI_LE_SET_ADVERTISE_ENABLE,
        HCI_LE_SET_SCAN_PARAMS,
        HCI_LE_SET_SCAN_ENABLE,
        HCI_LE_CREATE_CONNECTION,
    }
)

# The extended-initiator probe is conditional: initialize() only issues it when
# the controller's Supported_Commands bitmap lacks the 0x2043 bit (see §7.8.66
# and the probe comment in HCIController.initialize). The VirtualController
# advertises every opcode registered in _OPCODE_BIT_POSITIONS — 0x2043 among
# them — so the plain fixture takes the no-probe path.
EXTENDED_INITIATOR_PROBE = [
    HCI_LE_EXTENDED_CREATE_CONNECTION,
    HCI_LE_CREATE_CONNECTION_CANCEL,
]

EXPECTED_INIT_OPCODES = [
    # Always-mandatory phase
    HCI_RESET,
    HCI_READ_LOCAL_SUPPORTED_COMMANDS,
    HCI_READ_BD_ADDR,
    # Optional commands (gated on Supported_Commands bitmap)
    HCI_READ_LOCAL_VERSION,
    HCI_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_READ_BUFFER_SIZE,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_SET_EVENT_MASK,
    HCI_LE_SET_EVENT_MASK,
    HCI_WRITE_LE_HOST_SUPPORTED,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
    HCI_WRITE_SCAN_ENABLE,
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_LE_SET_HOST_FEATURE,
    # BR/EDR Extended Features pages 1+2 (Spec 5.4 Vol 2 Part C §3.3)
    HCI_READ_LOCAL_EXTENDED_FEATURES,
    HCI_READ_LOCAL_EXTENDED_FEATURES,
]


def expected_init_opcodes(*, extended_initiator_advertised: bool) -> list[int]:
    """The init sequence for a controller with/without the 0x2043 capability bit."""
    opcodes = list(EXPECTED_INIT_OPCODES)
    if not extended_initiator_advertised:
        # The probe runs right after the mandatory Read_BD_ADDR.
        at = opcodes.index(HCI_READ_BD_ADDR) + 1
        opcodes[at:at] = EXTENDED_INITIATOR_PROBE
    return opcodes


def _record_sent_opcodes(hci):
    transport = hci._transport
    original_send = transport.send
    transport.sent_opcodes = []

    async def send(data: bytes) -> None:
        pkt = decode_hci_packet(data)
        if isinstance(pkt, HCICommand):
            transport.sent_opcodes.append(pkt.opcode)
        await original_send(data)

    transport.send = send
    return transport


async def test_hci_init_sequence_sends_all_expected_commands(stack):
    hci = stack.hci
    transport = _record_sent_opcodes(hci)

    await asyncio.wait_for(hci.initialize(), timeout=5.0)

    # The virtual controller advertises every registered opcode, so there is
    # no need to probe for the extended initiator.
    assert hci._supported_commands.has(HCI_LE_EXTENDED_CREATE_CONNECTION)
    expected = expected_init_opcodes(extended_initiator_advertised=True)
    assert len(transport.sent_opcodes) == len(expected), (
        f"Expected {len(expected)} init commands, "
        f"got {len(transport.sent_opcodes)}: "
        f"{[hex(op) for op in transport.sent_opcodes]}"
    )
    assert transport.sent_opcodes == expected


async def test_hci_init_probes_the_extended_initiator_when_the_bitmap_lacks_it(
    stack, monkeypatch,
):
    """A bitmap without octet 38 bit 4 must still unlock the extended initiator.

    The VirtualController advertises every registered opcode and answers
    Command *Complete* to anything it does not know, so modelling "the bit is
    clear but the firmware accepts the command" needs two instance-level
    patches: a restricted bitmap, and a Command *Status* reply for 0x2043 (a
    real controller that supports it answers Status, not Unknown).
    """
    from pybluehost.hci.capabilities import _OPCODE_BIT_POSITIONS

    vc = stack._virtual_controller
    bitmap = bytearray(64)
    for opcode, (octet, bit) in _OPCODE_BIT_POSITIONS.items():
        if opcode == HCI_LE_EXTENDED_CREATE_CONNECTION:
            continue
        bitmap[octet] |= 1 << bit
    monkeypatch.setitem(
        vc._handlers,
        HCI_READ_LOCAL_SUPPORTED_COMMANDS,
        lambda cmd: b"\x00" + bytes(bitmap),
    )

    async def interceptor(opcode: int, params: bytes) -> bytes | None:
        if opcode == HCI_LE_EXTENDED_CREATE_CONNECTION:
            return vc._make_command_status(opcode, status=0)
        return None

    monkeypatch.setattr(vc, "command_interceptor", interceptor)

    hci = stack.hci
    transport = _record_sent_opcodes(hci)

    await asyncio.wait_for(hci.initialize(), timeout=5.0)

    expected = expected_init_opcodes(extended_initiator_advertised=False)
    assert transport.sent_opcodes == expected
    # The probe merged the bit back so connect() can use the extended initiator.
    assert hci._supported_commands.has(HCI_LE_EXTENDED_CREATE_CONNECTION)


async def test_hci_init_sequence_all_commands_succeed(stack):
    hci = stack.hci
    transport = _record_sent_opcodes(hci)

    await asyncio.wait_for(hci.initialize(), timeout=5.0)

    # If initialize() completed without error, all commands succeeded
    assert len(transport.sent_opcodes) == len(
        expected_init_opcodes(extended_initiator_advertised=True)
    )


async def test_hci_init_sequence_timeout_raises(stack):
    class SilentTransport:
        def set_sink(self, sink): pass
        async def open(self): pass
        async def close(self): pass
        async def send(self, data: bytes): pass

    hci = stack.hci
    hci._transport = SilentTransport()
    hci._command_timeout = 0.05
    with pytest.raises(CommandTimeoutError):
        await hci.initialize()


async def test_hci_init_issues_no_legacy_le_advertising_or_scanning_command(stack):
    """Init must stay out of the legacy LE advertising/scanning family.

    Vol 4 Part E §3.1.1 / Table 3.2: once a legacy-family command has been
    issued, every *extended* advertising or scanning command answers Command
    Disallowed (0x0C) until the next power cycle. That is a whole-cycle
    poisoning, invisible from above (a 0x0C reply is just a status byte), so
    a legacy command issued at init silently breaks every extended-family
    user — the extended advertiser and periodic-advertising sync included.

    Asserted on the family rather than on one opcode: swapping the old legacy
    LE_Set_Scan_Parameters for a different legacy command would be the same bug.
    """
    hci = stack.hci
    transport = _record_sent_opcodes(hci)

    await asyncio.wait_for(hci.initialize(), timeout=5.0)

    offenders = [
        hex(op) for op in transport.sent_opcodes if op in LEGACY_LE_ADVERTISING_FAMILY
    ]
    assert offenders == [], (
        f"init issued legacy LE advertising/scanning commands {offenders}; "
        "these poison the extended family for the rest of the power cycle"
    )


async def test_hci_init_programs_the_full_le_event_mask(stack):
    """Asserted on the bytes that go out, not on the constant.

    A mask is only worth what the controller received: the mask that reaches
    the wire is what decides which events exist. Reading the constant back
    would pass even if initialize() dropped the command, sent a truncated
    body, or set the mask *before* Reset cleared it.
    """
    from pybluehost.hci.constants import DEFAULT_LE_EVENT_MASK

    hci = stack.hci
    transport = hci._transport
    original_send = transport.send
    sent = []

    async def send(data: bytes) -> None:
        pkt = decode_hci_packet(data)
        if isinstance(pkt, HCICommand) and pkt.opcode == HCI_LE_SET_EVENT_MASK:
            sent.append(pkt.parameters)
        await original_send(data)

    transport.send = send
    await asyncio.wait_for(hci.initialize(), timeout=5.0)

    assert sent == [DEFAULT_LE_EVENT_MASK.to_bytes(8, "little")], (
        f"init sent LE event mask {[p.hex() for p in sent]}, expected one "
        f"8-byte mask {DEFAULT_LE_EVENT_MASK.to_bytes(8, 'little').hex()}"
    )
