"""T6: unit tests for btsnoop media-stream quality analysis (synthetic trace)."""
import struct

from scripts import mitm_media_analyze as ma

EPOCH_DELTA_US = 62167219200_000_000


def _btsnoop(records: list[bytes], flags: list[int] | None = None) -> bytes:
    out = b"btsnoop\x00" + struct.pack(">II", 1, 1002)
    for i, payload in enumerate(records):
        fl = flags[i] if flags else 0
        out += struct.pack(">IIIIq", len(payload), len(payload), fl, 0, EPOCH_DELTA_US + i * 20_000)
        out += payload
    return out


def _acl_frame(handle: int, l2cap_pdu: bytes) -> bytes:
    return struct.pack("<BHH", 0x02, handle | (0x02 << 12), len(l2cap_pdu)) + l2cap_pdu


def _l2cap(cid: int, payload: bytes) -> bytes:
    return struct.pack("<HH", len(payload), cid) + payload


def _rtp(seq: int, ts: int = 0) -> bytes:
    return struct.pack(">BBHII", 0x80, 0x60, seq, ts, 0xAABBCCDD) + b"\x00" * 100


def test_parse_records_roundtrip():
    blob = _btsnoop([_acl_frame(0x11, _l2cap(0x0040, b"abc"))])
    recs = list(ma.iter_btsnoop(blob))
    assert len(recs) == 1
    assert recs[0].direction == "sent"
    assert recs[0].handle == 0x11


def test_rtp_seq_analysis_detects_gap():
    records = [_acl_frame(0x11, _l2cap(0x0040, _rtp(s))) for s in (1, 2, 4, 5)]
    blob = _btsnoop(records)
    report = ma.analyze(blob)
    assert report.total_media_packets == 4
    assert report.lost_packets == 1
    assert report.out_of_order == 0


def test_rtp_seq_analysis_clean_stream():
    records = [_acl_frame(0x11, _l2cap(0x0040, _rtp(s, ts=s * 200))) for s in range(1, 101)]
    blob = _btsnoop(records)
    report = ma.analyze(blob)
    assert report.total_media_packets == 100
    assert report.lost_packets == 0
    assert 0 < report.packets_per_second < 200


def test_compare_reports_pass_fail():
    good = ma.MediaReport(total_media_packets=100, lost_packets=0, out_of_order=0,
                          packets_per_second=50.0, max_gap_ms=20.0, p99_gap_ms=25.0)
    bad = ma.MediaReport(total_media_packets=90, lost_packets=10, out_of_order=0,
                         packets_per_second=30.0, max_gap_ms=200.0, p99_gap_ms=180.0)
    verdicts = ma.compare(good, bad)
    assert verdicts["loss"] is True
    assert verdicts["rate"] is False
