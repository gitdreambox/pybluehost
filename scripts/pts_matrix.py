"""PTS results status-matrix tooling.

Per-group YAML files at docs/pts/results/matrix/<group>.yaml track each test
case's last verdict, notes, and bug references. This module provides:

- load_matrix(path) / save_matrix(path, data)
- update_case(matrix, case_id, *, verdict, last_run, notes, bug)
- summary_for(path) — counts by verdict
- render_summary_markdown(dir) — render a markdown SUMMARY
- init_matrix(path, group, cases) — seed a new matrix from a case-ID list

CLI: python scripts/pts_matrix.py [load|update|summary|render-summary|init] ...
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path
from typing import Any

import yaml


VALID_VERDICTS = ("untested", "pass", "fail", "inconc", "blocked")


def load_matrix(path: Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def save_matrix(path: Path, matrix: dict[str, Any]) -> None:
    matrix["last_updated"] = _dt.date.today().isoformat()
    Path(path).write_text(
        yaml.safe_dump(matrix, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def update_case(
    matrix: dict[str, Any], case_id: str, *,
    verdict: str | None = None,
    last_run: str | None = None,
    notes: str | None = None,
    bug: str | None = None,
) -> None:
    if verdict is not None and verdict not in VALID_VERDICTS:
        raise ValueError(
            f"invalid verdict {verdict!r}; must be one of {VALID_VERDICTS}"
        )
    cases = matrix.setdefault("cases", {})
    if case_id not in cases:
        raise KeyError(f"unknown test case {case_id!r} in matrix")
    entry = cases[case_id]
    if verdict is not None:
        entry["verdict"] = verdict
    if last_run is not None:
        entry["last_run"] = last_run
    if notes is not None:
        entry["notes"] = notes
    if bug is not None:
        refs = entry.setdefault("bug_refs", [])
        if bug not in refs:
            refs.append(bug)


def summary_for(path: Path) -> dict[str, int]:
    m = load_matrix(path)
    counts = {v: 0 for v in VALID_VERDICTS}
    for entry in m.get("cases", {}).values():
        v = entry.get("verdict", "untested")
        if v in counts:
            counts[v] += 1
    counts["total"] = sum(counts[v] for v in VALID_VERDICTS)
    return counts


def render_summary_markdown(matrix_dir: Path) -> str:
    matrix_dir = Path(matrix_dir)
    rows = []
    for p in sorted(matrix_dir.glob("*.yaml")):
        s = summary_for(p)
        total = s["total"]
        pct = (100.0 * s["pass"] / total) if total else 0.0
        m = load_matrix(p)
        rows.append({
            "group": m.get("group", p.stem.upper()),
            "total": total, "pass": s["pass"], "fail": s["fail"],
            "untested": s["untested"], "pct": pct,
        })

    out: list[str] = []
    out.append("# PTS test-case pass-rate summary")
    out.append("")
    out.append(f"Generated: {_dt.date.today().isoformat()}")
    out.append("")
    out.append("| Group | Total | Pass | Fail | Untested | Pass-rate |")
    out.append("|---|---|---|---|---|---|")
    grand_total = grand_pass = 0
    for r in rows:
        out.append(
            f"| {r['group']} | {r['total']} | {r['pass']} | {r['fail']} | "
            f"{r['untested']} | {r['pct']:.1f}% |"
        )
        grand_total += r["total"]
        grand_pass += r["pass"]
    overall = (100.0 * grand_pass / grand_total) if grand_total else 0.0
    out.append(
        f"| **Total** | **{grand_total}** | **{grand_pass}** | — | — | "
        f"**{overall:.1f}%** |"
    )
    out.append("")
    return "\n".join(out) + "\n"


def init_matrix(path: Path, *, group: str, cases: list[str]) -> None:
    matrix = {
        "group": group,
        "last_updated": _dt.date.today().isoformat(),
        "runs": 0,
        "cases": {
            cid: {"verdict": "untested", "last_run": None,
                  "notes": "", "bug_refs": []}
            for cid in cases
        },
    }
    save_matrix(path, matrix)


# ---- CLI ----------------------------------------------------------------

def _cli() -> int:
    p = argparse.ArgumentParser(prog="pts_matrix")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("summary", help="Print per-group counts.")
    ps.add_argument("matrix", help="Path to <group>.yaml")

    pu = sub.add_parser("update", help="Set a case's verdict.")
    pu.add_argument("matrix")
    pu.add_argument("case_id")
    pu.add_argument("--verdict", required=True, choices=VALID_VERDICTS)
    pu.add_argument("--last-run", default=None)
    pu.add_argument("--notes", default=None)
    pu.add_argument("--bug", default=None)

    pr = sub.add_parser("render-summary", help="Render SUMMARY.md from a matrix dir.")
    pr.add_argument("dir", help="docs/pts/results/matrix/ path")
    pr.add_argument("--output", "-o", default=None,
                    help="If omitted, prints to stdout.")

    pi = sub.add_parser("init", help="Seed a new matrix file.")
    pi.add_argument("matrix")
    pi.add_argument("group")
    pi.add_argument("cases", nargs="+")

    args = p.parse_args()
    if args.cmd == "summary":
        for k, v in summary_for(Path(args.matrix)).items():
            print(f"{k:>10s}  {v}")
        return 0
    if args.cmd == "update":
        m = load_matrix(Path(args.matrix))
        update_case(
            m, args.case_id, verdict=args.verdict,
            last_run=args.last_run, notes=args.notes, bug=args.bug,
        )
        save_matrix(Path(args.matrix), m)
        return 0
    if args.cmd == "render-summary":
        md = render_summary_markdown(Path(args.dir))
        if args.output:
            Path(args.output).write_text(md, encoding="utf-8")
        else:
            sys.stdout.write(md)
        return 0
    if args.cmd == "init":
        init_matrix(Path(args.matrix), group=args.group, cases=args.cases)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
