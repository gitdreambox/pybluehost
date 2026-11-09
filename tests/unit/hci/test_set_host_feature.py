"""The Host declares its own LE FeatureSet bits via LE_Set_Host_Feature.

Bits 0..63 of the LE FeatureSet are exchanged on air during the Feature
Exchange, and some of them are owned by the Host rather than the controller —
the controller cannot set them on its own. Connection Subrating (Host Support)
is one of them.

This is a regression guard for GAP/CSUB: while bit 38 is clear, a peer refuses
to run the Connection Subrating procedure at all (Vol 6 Part B §5.1.19, and
§7.8.124 for the Central-side error). The symptom is misleading — the HCI
command succeeds on its own parameters and then no LE Subrate Change event ever
arrives, so it reads as a missing controller capability rather than a missing
Host declaration.
"""
from __future__ import annotations

import asyncio
import struct

from pybluehost.hci.constants import (
    HCI_EVENT_PACKET,
    HCI_LE_SET_HOST_FEATURE,
    LE_FEATURE_BIT_CONNECTION_SUBRATING_HOST_SUPPORT,
    EventCode,
)
from pybluehost.hci.controller import HCIController
from pybluehost.hci.packets import HCICommand, decode_hci_packet
from pybluehost.hci.virtual import VirtualController


class FakeTransport:
    """Minimal transport that records sent bytes and allows injecting data."""

    def __init__(self) -> None:
        self._sink = None
        self.sent: list[bytes] = []

    def set_sink(self, sink) -> None:
        self._sink = sink

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def inject(self, data: bytes) -> None:
        if self._sink:
            await self._sink.on_transport_data(data)


def build_command_complete(opcode: int, status: int = 0x00) -> bytes:
    params = struct.pack("<BH", 1, opcode) + bytes([status])
    header = struct.pack("<BBB", HCI_EVENT_PACKET, EventCode.COMMAND_COMPLETE, len(params))
    return header + params


async def _send_with_status(ctrl: HCIController, transport: FakeTransport,
                            command: HCICommand, status: int) -> tuple:
    async def inject_response():
        await asyncio.sleep(0.01)
        await transport.inject(build_command_complete(command.opcode, status=status))

    task = asyncio.ensure_future(inject_response())
    try:
        result = await ctrl.set_host_feature(
            command.parameters[0], enabled=bool(command.parameters[1])
        )
    finally:
        await task
    return result, transport.sent[-1]


async def test_set_host_feature_sends_bit_number_and_value():
    transport = FakeTransport()
    ctrl = HCIController(transport, command_timeout=2.0)

    status, raw = await _send_with_status(
        ctrl, transport,
        HCICommand(opcode=HCI_LE_SET_HOST_FEATURE, parameters=b"\x26\x01"),
        status=0x00,
    )

    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCICommand)
    assert pkt.opcode == HCI_LE_SET_HOST_FEATURE
    # 38 folded into one octet; second octet is the enable flag.
    assert pkt.parameters == bytes([LE_FEATURE_BIT_CONNECTION_SUBRATING_HOST_SUPPORT, 0x01])
    assert status == 0x00


async def test_set_host_feature_clears_the_bit_when_disabled():
    transport = FakeTransport()
    ctrl = HCIController(transport, command_timeout=2.0)

    _, raw = await _send_with_status(
        ctrl, transport,
        HCICommand(opcode=HCI_LE_SET_HOST_FEATURE, parameters=b"\x26\x00"),
        status=0x00,
    )

    pkt = decode_hci_packet(raw)
    assert pkt.parameters == bytes([LE_FEATURE_BIT_CONNECTION_SUBRATING_HOST_SUPPORT, 0x00])


async def test_set_host_feature_returns_refusal_instead_of_raising():
    """0x0C (a connection is up) and 0x11 (not Host-owned) are both reportable,
    not fatal — pre-5.2 controllers answer 0x01 for the command itself."""
    transport = FakeTransport()
    ctrl = HCIController(transport, command_timeout=2.0)

    for status_code in (0x01, 0x0C, 0x11):
        status, _ = await _send_with_status(
            ctrl, transport,
            HCICommand(opcode=HCI_LE_SET_HOST_FEATURE, parameters=b"\x26\x01"),
            status=status_code,
        )
        assert status == status_code


class _RecordingVC(VirtualController):
    """A VirtualController that remembers which opcodes the Host sent."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen: list[int] = []

    async def process(self, data: bytes):
        pkt = decode_hci_packet(data)
        if isinstance(pkt, HCICommand):
            self.seen.append(pkt.opcode)
        return await super().process(data)


async def test_initialize_declares_connection_subrating_host_support():
    vc, host_t = await _RecordingVC.create()
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)

    await hci.initialize()

    assert HCI_LE_SET_HOST_FEATURE in vc.seen


async def test_initialize_survives_a_controller_without_set_host_feature():
    """The VirtualController answers Unknown Command for unregistered opcodes,
    which is exactly what a pre-5.2 controller does — init must not care."""
    vc, host_t = await _RecordingVC.create()
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)

    await hci.initialize()

    assert vc.seen.count(HCI_LE_SET_HOST_FEATURE) == 1
    assert hci.supported_commands is not None
