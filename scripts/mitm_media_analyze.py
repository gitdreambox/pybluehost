"""btsnoop media-stream quality analysis: RTP sequence/rate/jitter of the AVDTP media channel.

Usage:
  python scripts/mitm_media_analyze.py trace.btsnoop
  python scripts/mitm_media_analyze.py mitm.btsnoop --compare baseline.btsnoop

G5 criterion: lost==0 and out-of-order==0 and rate within ≤5% of baseline.
"""
from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

_EPOCH_DELTA_US = 62167219200_000_000


@dataclass
class AclRecord:
    direction: str  # "sent" | "recv" (from the recording controller's perspective)
    handle: int
    ts_us: int
    cid: int
    payload: bytes


@dataclass
class MediaReport:
    total_media_packets: int
    lost_packets: int
    out_of_order: int
    packets_per_second: float
    max_gap_ms: float
    p99_gap_ms: float


def iter_btsnoop(blob: bytes):
    """Yield AclRecord; only complete L2CAP frames (each record's single ACL first fragment is
    a complete PDU)."""
    assert blob[:8] == b"btsnoop\x00", "not a btsnoop file"
    off = 16
    while off + 24 <= len(blob):
        orig, incl, flags, _drops, ts = struct.unpack_from(">IIIIq", blob, off)
        off += 24
        payload = blob[off:off + incl]
        off += incl
        if len(payload) < 5 or payload[0] != 0x02:
            continue  # non-ACL H4 frame
        handle_flags, dlen = struct.unpack_from("<HH", payload, 1)
        data = payload[5:5 + dlen]
        if len(data) < 4:
            continue
        length, cid = struct.unpack_from("<HH", data, 0)
        yield AclRecord(
            direction="recv" if (flags & 1) else "sent",
            handle=handle_flags & 0x0FFF,
            ts_us=ts - _EPOCH_DELTA_US,
            cid=cid,
            payload=data[4:4 + length],
        )


def _looks_like_rtp(payload: bytes) -> bool:
    return len(payload) >= 12 and (payload[0] >> 6) == 2


def analyze(blob: bytes) -> MediaReport:
    # 1. media channel = the CID carrying the most valid RTP packets
    seqs: dict[int, list[tuple[int, int]]] = {}  # cid → [(ts_us, seq)]
    for rec in iter_btsnoop(blob):
        if _looks_like_rtp(rec.payload):
            seq = struct.unpack_from(">H", rec.payload, 2)[0]
            seqs.setdefault(rec.cid, []).append((rec.ts_us, seq))
    media_cid = max(seqs, key=lambda c: len(seqs[c]), default=None)
    samples = seqs.get(media_cid, []) if media_cid is not None else []
    # 2. RTP analysis (time-ordered; seq wraparound uses mod-65536 difference)
    samples.sort()
    lost = ooo = 0
    prev = None
    gaps_ms: list[float] = []
    for ts, seq in samples:
        if prev is not None:
            pts, pseq = prev
            diff = (seq - pseq) & 0xFFFF
            if diff == 0 or diff > 0x8000:
                ooo += 1
            elif diff > 1:
                lost += diff - 1
            gaps_ms.append((ts - pts) / 1000.0)
        prev = (ts, seq)
    dur_s = (samples[-1][0] - samples[0][0]) / 1e6 if len(samples) > 1 else 0
    gaps_sorted = sorted(gaps_ms)
    p99 = gaps_sorted[min(int(len(gaps_sorted) * 0.99), len(gaps_sorted) - 1)] if gaps_sorted else 0.0
    return MediaReport(
        total_media_packets=len(samples),
        lost_packets=lost,
        out_of_order=ooo,
        packets_per_second=(len(samples) / dur_s) if dur_s > 0 else 0.0,
        max_gap_ms=max(gaps_ms) if gaps_ms else 0.0,
        p99_gap_ms=p99,
    )


def compare(mitm: MediaReport, baseline: MediaReport) -> dict[str, bool]:
    rate_ok = (
        baseline.packets_per_second > 0
        and abs(mitm.packets_per_second - baseline.packets_per_second)
        / baseline.packets_per_second <= 0.05
    )
    return {
        "loss": mitm.lost_packets == 0,
        "reorder": mitm.out_of_order == 0,
        "rate": rate_ok,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("trace")
    ap.add_argument("--compare", help="baseline trace; the main argument is the MITM trace")
    args = ap.parse_args()
    mitm = analyze(Path(args.trace).read_bytes())
    print(f"MITM trace: pkts={mitm.total_media_packets} lost={mitm.lost_packets} "
          f"ooo={mitm.out_of_order} rate={mitm.packets_per_second:.1f}pps "
          f"max_gap={mitm.max_gap_ms:.1f}ms p99_gap={mitm.p99_gap_ms:.1f}ms")
    if args.compare:
        base = analyze(Path(args.compare).read_bytes())
        print(f"baseline:   pkts={base.total_media_packets} rate={base.packets_per_second:.1f}pps")
        verdicts = compare(mitm, base)
        for k, ok in verdicts.items():
            print(f"  {k}: {'PASS' if ok else 'FAIL'}")
        sys.exit(0 if all(verdicts.values()) else 1)


if __name__ == "__main__":
    main()
