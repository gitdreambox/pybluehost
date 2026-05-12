"""PcapngSink unit tests."""
from __future__ import annotations

import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pybluehost.core import Direction, PcapngSink, TraceEvent


def _evt(layer: str, direction: Direction, payload: bytes) -> TraceEvent:
    return TraceEvent(
        timestamp=0.0,
        wall_clock=datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc),
        source_layer=layer,
        direction=direction,
        raw_bytes=payload,
        decoded=None,
        connection_handle=None,
        metadata={},
    )


async def test_pcapng_sink_writes_shb_idb_and_epb(tmp_path: Path) -> None:
    path = tmp_path / "trace.pcapng"
    sink = PcapngSink(path)

    await sink.on_trace(_evt("hci", Direction.DOWN, b"\x01\x03\x0c\x00"))
    await sink.on_trace(_evt("hci", Direction.UP, b"\x04\x0e\x04\x05\x03\x0c\x00"))
    await sink.close()

    data = path.read_bytes()

    # Section Header Block (SHB): type 0x0A0D0D0A
    shb_type, shb_total_len, byte_order_magic = struct.unpack_from("<IIi", data, 0)
    assert shb_type == 0x0A0D0D0A
    # Byte order magic in little-endian SHB
    assert byte_order_magic == 0x1A2B3C4D

    # Next block should be Interface Description Block (IDB): type 0x00000001
    idb_offset = shb_total_len
    idb_type, idb_total_len = struct.unpack_from("<II", data, idb_offset)
    assert idb_type == 0x00000001
    # LinkType field at offset+8: BLUETOOTH_HCI_H4_WITH_PHDR = 201
    linktype = struct.unpack_from("<H", data, idb_offset + 8)[0]
    assert linktype == 201

    # Two Enhanced Packet Blocks (EPB): type 0x00000006
    epb1_offset = idb_offset + idb_total_len
    epb1_type, epb1_total_len = struct.unpack_from("<II", data, epb1_offset)
    assert epb1_type == 0x00000006

    epb2_offset = epb1_offset + epb1_total_len
    epb2_type, _ = struct.unpack_from("<II", data, epb2_offset)
    assert epb2_type == 0x00000006


async def test_pcapng_sink_skips_non_hci_layers(tmp_path: Path) -> None:
    path = tmp_path / "trace.pcapng"
    sink = PcapngSink(path)
    await sink.on_trace(_evt("att", Direction.DOWN, b"\x02\x01"))
    await sink.close()

    data = path.read_bytes()
    # No EPB written (only SHB + IDB present)
    assert data.count(struct.pack("<I", 0x00000006)) == 0


async def test_pcapng_sink_skips_empty_raw_bytes(tmp_path: Path) -> None:
    path = tmp_path / "trace.pcapng"
    sink = PcapngSink(path)
    await sink.on_trace(_evt("hci", Direction.DOWN, b""))
    await sink.close()

    data = path.read_bytes()
    assert data.count(struct.pack("<I", 0x00000006)) == 0
