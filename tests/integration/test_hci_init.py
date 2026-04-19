"""Integration test: HCIController init sequence against VirtualController."""
from __future__ import annotations

import asyncio
import pytest

from pybluehost.core.address import BDAddress
from pybluehost.core.errors import CommandTimeoutError
from pybluehost.core.trace import TraceSystem
from pybluehost.hci.controller import HCIController
from pybluehost.hci.virtual import VirtualController
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


class LoopbackTransport:
    """In-process transport routing HCIController bytes through VirtualController."""

    def __init__(self, vc: VirtualController) -> None:
        self._vc = vc
        self._sink = None
        self.sent_opcodes: list[int] = []

    def set_sink(self, sink) -> None:
        self._sink = sink

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def send(self, data: bytes) -> None:
        pkt = decode_hci_packet(data)
        if isinstance(pkt, HCICommand):
            self.sent_opcodes.append(pkt.opcode)
        response = await self._vc.process(data)
        if response is not None and self._sink is not None:
            await self._sink.on_transport_data(response)


async def test_hci_init_sequence_sends_all_16_commands():
    vc = VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:FF"))
    transport = LoopbackTransport(vc)
    controller = HCIController(transport=transport)

    await asyncio.wait_for(controller.initialize(), timeout=5.0)

    assert len(transport.sent_opcodes) == len(EXPECTED_INIT_OPCODES), (
        f"Expected {len(EXPECTED_INIT_OPCODES)} init commands, "
        f"got {len(transport.sent_opcodes)}: "
        f"{[hex(op) for op in transport.sent_opcodes]}"
    )
    assert transport.sent_opcodes == EXPECTED_INIT_OPCODES


async def test_hci_init_sequence_all_commands_succeed():
    vc = VirtualController(address=BDAddress.from_string("11:22:33:44:55:66"))
    transport = LoopbackTransport(vc)
    controller = HCIController(transport=transport)

    await asyncio.wait_for(controller.initialize(), timeout=5.0)

    # If initialize() completed without error, all commands succeeded
    assert len(transport.sent_opcodes) == 16


async def test_hci_init_sequence_timeout_raises():
    class SilentTransport:
        def set_sink(self, sink): pass
        async def open(self): pass
        async def close(self): pass
        async def send(self, data: bytes): pass

    controller = HCIController(transport=SilentTransport(), command_timeout=0.05)
    with pytest.raises(CommandTimeoutError):
        await controller.initialize()
