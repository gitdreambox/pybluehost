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
    HCI_READ_BD_ADDR,
    HCI_READ_BUFFER_SIZE,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_SET_EVENT_MASK,
    HCI_LE_SET_EVENT_MASK,
    HCI_WRITE_LE_HOST_SUPPORTED,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
    HCI_WRITE_SCAN_ENABLE,
    HCI_HOST_BUFFER_SIZE,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_LE_SET_RANDOM_ADDRESS,
)

EXPECTED_INIT_OPCODES = [
    HCI_RESET,
    HCI_READ_LOCAL_VERSION,
    HCI_READ_LOCAL_SUPPORTED_COMMANDS,
    HCI_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_READ_BD_ADDR,
    HCI_READ_BUFFER_SIZE,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_SET_EVENT_MASK,
    HCI_LE_SET_EVENT_MASK,
    HCI_WRITE_LE_HOST_SUPPORTED,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
    HCI_WRITE_SCAN_ENABLE,
    HCI_HOST_BUFFER_SIZE,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_LE_SET_RANDOM_ADDRESS,
]


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


async def test_hci_init_sequence_sends_all_16_commands(stack):
    hci = stack.hci
    transport = _record_sent_opcodes(hci)

    await asyncio.wait_for(hci.initialize(), timeout=5.0)

    assert len(transport.sent_opcodes) == len(EXPECTED_INIT_OPCODES), (
        f"Expected {len(EXPECTED_INIT_OPCODES)} init commands, "
        f"got {len(transport.sent_opcodes)}: "
        f"{[hex(op) for op in transport.sent_opcodes]}"
    )
    assert transport.sent_opcodes == EXPECTED_INIT_OPCODES


async def test_hci_init_sequence_all_commands_succeed(stack):
    hci = stack.hci
    transport = _record_sent_opcodes(hci)

    await asyncio.wait_for(hci.initialize(), timeout=5.0)

    # If initialize() completed without error, all commands succeeded
    assert len(transport.sent_opcodes) == 16


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
