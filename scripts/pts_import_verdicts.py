"""Bulk-import PTS verdicts from auto-pts client logs into the results matrix.

Wraps ``pts_collect_verdicts.collect`` (PTS ground-truth ``FINAL_VERDICT`` per
case) and writes each verdict into ``docs/PTS/results/matrix/<group>.yaml``,
creating case entries that don't exist yet (``pts_matrix.update_case`` refuses
unknown cases, which is right for hand-entry but wrong for a bulk import).

Group mapping: leading path segment of the case id — GAP/GATT map directly,
L2CAP -> l2cap.yaml, SM -> smp.yaml. Verdict mapping: PASS->pass, FAIL->fail,
INCONC->inconc; anything else is left as-is (skipped).

A case currently marked ``blocked`` is left alone: that verdict records a
judgement about the *case* (a PTS errata, a hardware limit), which no re-run can
overturn. Logs accumulate under ``logs_root`` across many days and every one of
them is stamped with the ``--date`` this tool is invoked with, so without the
guard a single import rewrites those judgements from whatever the most recent
unrelated run produced. Pass ``--force`` to re-open one deliberately.

Usage:
    python scripts/pts_import_verdicts.py [logs_root] [--date YYYY-MM-DD]
                                          [--dry-run] [--force]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pts_collect_verdicts as pcv  # noqa: E402
import pts_matrix as pm  # noqa: E402

_MATRIX_DIR = Path(__file__).resolve().parents[1] / "docs" / "PTS" / "results" / "matrix"

_GROUP_FILE = {
    "GAP": "gap.yaml",
    "GATT": "gatt.yaml",
    "L2CAP": "l2cap.yaml",
    "SM": "smp.yaml",
    "SDP": "sdp.yaml",
    "RFCOMM": "rfcomm.yaml",
}

_VERDICT_MAP = {"PASS": "pass", "FAIL": "fail", "INCONC": "inconc"}


def _blank_entry() -> dict:
    return {"verdict": "untested", "last_run": None, "notes": "", "bug_refs": []}


def import_verdicts(logs_root: str, *, date: str, dry_run: bool = False,
                    force: bool = False) -> dict:
    results = pcv.collect(logs_root)
    # case_id uses "_" -> "/" already in collector; ensure leading group.
    per_group: dict[str, dict[str, str]] = {}
    skipped: dict[str, str] = {}
    for case, (verdict, _path) in results.items():
        group = case.split("/")[0]
        mapped = _VERDICT_MAP.get(verdict)
        if group not in _GROUP_FILE or mapped is None:
            skipped[case] = verdict
            continue
        per_group.setdefault(group, {})[case] = mapped

    summary = {"updated": 0, "created": 0, "skipped": len(skipped), "preserved": 0}
    for group, cases in per_group.items():
        path = _MATRIX_DIR / _GROUP_FILE[group]
        matrix = pm.load_matrix(path) if path.exists() else {
            "group": group, "last_updated": date, "runs": 0, "cases": {},
        }
        for case, verdict in sorted(cases.items()):
            existing = matrix["cases"].get(case)
            if existing is None:
                matrix["cases"][case] = _blank_entry()
                summary["created"] += 1
            elif existing.get("verdict") == "blocked" and not force:
                summary["preserved"] += 1
                continue
            pm.update_case(matrix, case, verdict=verdict, last_run=date)
            summary["updated"] += 1
        if not dry_run:
            pm.save_matrix(path, matrix)
    return {"summary": summary, "skipped": skipped}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs_root", nargs="?", default=None)
    ap.add_argument("--date", default=_dt.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="also overwrite cases currently marked 'blocked'")
    args = ap.parse_args()
    logs_root = args.logs_root or pcv._autopts_logs_default()
    out = import_verdicts(logs_root, date=args.date, dry_run=args.dry_run,
                          force=args.force)
    s = out["summary"]
    print(f"{'DRY-RUN ' if args.dry_run else ''}updated={s['updated']} "
          f"created={s['created']} skipped={s['skipped']} preserved={s['preserved']}")
    if s["preserved"]:
        print("  (blocked cases kept - pass --force to overwrite them)")
    for case, verdict in sorted(out["skipped"].items()):
        print(f"  skipped {case:45s} {verdict}")


if __name__ == "__main__":
    main()
