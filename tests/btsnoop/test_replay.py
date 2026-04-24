"""Tests that replay a captured btsnoop file and verify packet delivery."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pybluehost.transport.btsnoop import BtsnoopTransport

FIXTURE = Path(__file__).parent.parent / "data" / "hci_reset.btsnoop"


@pytest.mark.btsnoop
async def test_btsnoop_replay_packet_count():
    transport = BtsnoopTransport(path=str(FIXTURE))
    packets: list[bytes] = []

    class Sink:
        async def on_transport_data(self, data: bytes) -> None:
            packets.append(data)

    transport.set_sink(Sink())
    await transport.open()
    # Wait for replay task to finish
    await asyncio.sleep(0.1)
    await transport.close()
    assert len(packets) == 4


@pytest.mark.btsnoop
async def test_btsnoop_replay_first_packet_is_reset_cmd():
    transport = BtsnoopTransport(path=str(FIXTURE))
    packets: list[bytes] = []

    class Sink:
        async def on_transport_data(self, data: bytes) -> None:
            packets.append(data)

    transport.set_sink(Sink())
    await transport.open()
    await asyncio.sleep(0.1)
    await transport.close()
    # First packet: HCI Reset Command (H4: 0x01, opcode 0x0C03, len 0)
    assert packets[0] == bytes([0x01, 0x03, 0x0C, 0x00])


@pytest.mark.btsnoop
async def test_btsnoop_replay_second_packet_is_cc_reset():
    transport = BtsnoopTransport(path=str(FIXTURE))
    packets: list[bytes] = []

    class Sink:
        async def on_transport_data(self, data: bytes) -> None:
            packets.append(data)

    transport.set_sink(Sink())
    await transport.open()
    await asyncio.sleep(0.1)
    await transport.close()
    # Second packet: Command Complete for Reset
    # 0x04 (event), 0x0E (CC), len=4, ncmds=1, opcode=0x0C03, status=0
    assert packets[1] == bytes([0x04, 0x0E, 0x04, 0x01, 0x03, 0x0C, 0x00])


@pytest.mark.btsnoop
async def test_btsnoop_replay_fourth_packet_contains_bd_addr():
    transport = BtsnoopTransport(path=str(FIXTURE))
    packets: list[bytes] = []

    class Sink:
        async def on_transport_data(self, data: bytes) -> None:
            packets.append(data)

    transport.set_sink(Sink())
    await transport.open()
    await asyncio.sleep(0.1)
    await transport.close()
    # Fourth packet: CC for Read_BD_ADDR, contains AA:BB:CC:DD:EE:01 (little-endian)
    assert len(packets[3]) == 13
    # BD_ADDR bytes at offset 7..12
    assert packets[3][7:13] == bytes([0x01, 0xEE, 0xDD, 0xCC, 0xBB, 0xAA])
