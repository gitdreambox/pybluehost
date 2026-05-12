"""PcapngSink unit tests."""
from __future__ import annotations

import struct
from datetime import datetime, timezone
from pathlib import Path

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


async def test_pcapng_sink_writes_direction_pseudo_header(tmp_path: Path) -> None:
    """The 4-byte big-endian pseudo-header is 0 for DOWN (sent), 1 for UP (received)."""
    path = tmp_path / "trace.pcapng"
    sink = PcapngSink(path)
    await sink.on_trace(_evt("hci", Direction.DOWN, b"\xAA\xBB\xCC\xDD"))
    await sink.on_trace(_evt("hci", Direction.UP, b"\x11\x22\x33\x44"))
    await sink.close()

    data = path.read_bytes()

    # Skip SHB (28 bytes) + IDB (20 bytes) = 48 bytes
    # First EPB starts at offset 48
    epb1_offset = 48
    epb1_type, epb1_total_len = struct.unpack_from("<II", data, epb1_offset)
    assert epb1_type == 0x00000006
    # EPB body starts after 8-byte header; pseudo-header is the 17th-20th bytes
    # of the body (after interface_id, ts_high, ts_low, captured_len, original_len = 20 bytes).
    epb1_phdr = data[epb1_offset + 8 + 20 : epb1_offset + 8 + 20 + 4]
    assert epb1_phdr == b"\x00\x00\x00\x00"  # DOWN

    epb2_offset = epb1_offset + epb1_total_len
    epb2_phdr = data[epb2_offset + 8 + 20 : epb2_offset + 8 + 20 + 4]
    assert epb2_phdr == b"\x00\x00\x00\x01"  # UP
