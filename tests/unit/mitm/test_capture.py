from pathlib import Path

import struct

from pybluehost.cli.app.mitm.acl import RelayDirection
from pybluehost.cli.app.mitm.capture import BtsnoopCaptureTap, NullTap


async def test_null_tap_is_noop():
    tap = NullTap()
    await tap.on_pdu(RelayDirection.PHONE_TO_TARGET, 0x40, b"\x00\x01")
    await tap.close()  # just must not raise


async def test_btsnoop_tap_writes_records(tmp_path: Path):
    path = tmp_path / "cap.btsnoop"
    tap = BtsnoopCaptureTap(path)
    await tap.on_pdu(RelayDirection.TARGET_TO_PHONE, 0x40,
                     bytes([0x03, 0x00, 0x04, 0x00, 0x0A, 0x03, 0x00]))
    await tap.close()

    raw = path.read_bytes()
    assert raw.startswith(b"btsnoop\x00")        # file header
    assert len(raw) > 16                          # records beyond the header
    assert bytes([0x0A, 0x03, 0x00]) in raw       # ATT payload persisted


async def test_btsnoop_tap_preserves_order_and_drains_on_close(tmp_path: Path):
    """Multiple PDUs are written serially in the background; close() ensures all are persisted and keep their enqueue order."""
    path = tmp_path / "multi.btsnoop"
    tap = BtsnoopCaptureTap(path)
    for i in range(5):
        await tap.on_pdu(RelayDirection.PHONE_TO_TARGET, 0x40,
                         bytes([0x01, 0x00, 0x04, 0x00, 0xA0 + i]))
    await tap.close()

    raw = path.read_bytes()
    # Parse btsnoop records one by one and take the last payload byte (0xA0+i) of each to verify enqueue order.
    # raw.find() cannot be used: the timestamp/length fields may coincidentally contain the marker byte
    # (timestamps grow after the epoch shift to 0-AD, making collisions more likely), which would
    # misjudge the order. Parsing record by record and taking only the real payload is immune to this collision.
    off = 16  # skip 16-byte file header
    markers = []
    while off + 24 <= len(raw):
        _orig, incl, _flags, _drops, _ts = struct.unpack_from(">IIIIq", raw, off)
        payload = raw[off + 24: off + 24 + incl]
        markers.append(payload[-1])
        off += 24 + incl
    assert markers == [0xA0 + i for i in range(5)]


async def test_on_pdu_after_close_is_noop(tmp_path: Path):
    tap = BtsnoopCaptureTap(tmp_path / "c.btsnoop")
    await tap.close()
    # on_pdu after close() must neither raise nor write
    await tap.on_pdu(RelayDirection.PHONE_TO_TARGET, 0x40, bytes([0x01, 0x00, 0x04, 0x00, 0x99]))
