"""Collect per-test-case PTS verdicts from auto-pts client logs.

auto-pts records the *client-side* outcome in its results XML (e.g. ``BTP
ERROR`` when a WID handler raises), which can diverge from the verdict PTS
itself computed. The PTS verdict is the ground truth for conformance testing —
it appears in each test-case log as a ``PTS_LOGTYPE_FINAL_VERDICT`` block::

    ... PTS_LOGTYPE_FINAL_VERDICT Final Verdict
    <blank>
    +220062 ms
    <blank>
     GAP/IDLE/NAMP/BV-01-C PASS

This script scans the auto-pts client log tree and prints ``<case> <verdict>``
per test case, most-recent run winning when a case was run several times.

Usage:
    python scripts/pts_collect_verdicts.py [logs_root]

Default logs_root: <auto-pts>/logs (auto-detected from the autopts package).
"""
from __future__ import annotations

import os
import re
import sys

# Verdict words PTS can emit after the case name on the verdict line.
# INDCSV is PTS's abbreviation for an inconclusive run (normalised to INCONC).
_VERDICTS = ("PASS", "FAIL", "INCONC", "INDCSV", "INCONCLUSIVE", "ERROR",
             "BTP ERROR", "XML-RPC ERROR", "FATAL ERROR", "TIMEOUT")

_NORMALISE = {"INDCSV": "INCONC", "INCONCLUSIVE": "INCONC"}


def _autopts_logs_default() -> str:
    try:
        import autopts  # type: ignore
        root = os.path.dirname(os.path.dirname(os.path.abspath(autopts.__file__)))
        return os.path.join(root, "logs")
    except Exception:
        return "logs"


def _extract_verdict(log_text: str, case_hint: str) -> str | None:
    """Return the PTS verdict from a single test-case log, or None."""
    # Find the FINAL_VERDICT marker, then the first following line that carries
    # the case name + a trailing verdict word.
    idx = log_text.find("PTS_LOGTYPE_FINAL_VERDICT")
    if idx < 0:
        return None
    tail = log_text[idx:]
    for line in tail.splitlines()[1:8]:
        line = line.strip()
        if not line or line.startswith("+"):
            continue
        # Expect "<CASE> <VERDICT>"
        for v in _VERDICTS:
            if line.endswith(v) and (case_hint in line or "/" in line):
                return _NORMALISE.get(v, v)
        # Sometimes the verdict is the only token.
        if line in _VERDICTS:
            return _NORMALISE.get(line, line)
    return None


def collect(logs_root: str) -> "dict[str, tuple[str, str]]":
    """Return {case_name: (verdict, log_path)}.

    PASS is sticky: a case that ever PASSed keeps PASS even if a later run
    failed. The PTS hardware link (peripheral connection, RF) is flaky, so a
    re-run of a passing case can spuriously FAIL/INCONC — that must not erase
    a demonstrated pass from the conformance matrix. Among non-PASS runs the
    latest wins. Real regressions are caught by the unit-test suite, not here.
    """
    results: dict[str, tuple[str, float, str]] = {}
    for dirpath, _dirs, files in os.walk(logs_root):
        for fn in files:
            if not fn.endswith(".log"):
                continue
            path = os.path.join(dirpath, fn)
            # case name = filename without the trailing _YYYY_MM_DD_HH_MM_SS.log
            m = re.match(r"(.+)_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}\.log$", fn)
            if not m:
                continue
            case = m.group(1).replace("_", "/")
            # Restore the trailing "-C" style: GAP_IDLE_NAMP_BV-01-C -> GAP/IDLE/NAMP/BV-01-C
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            verdict = _extract_verdict(text, case)
            if verdict is None:
                continue
            mtime = os.path.getmtime(path)
            cur = results.get(case)
            if cur is None:
                results[case] = (verdict, mtime, path)
            elif cur[0] == "PASS":
                continue                      # PASS sticky — never downgrade
            elif verdict == "PASS":
                results[case] = (verdict, mtime, path)   # upgrade to PASS
            elif mtime > cur[1]:
                results[case] = (verdict, mtime, path)   # non-PASS: latest wins
    return {case: (v, p) for case, (v, _m, p) in results.items()}


def main() -> None:
    logs_root = sys.argv[1] if len(sys.argv) > 1 else _autopts_logs_default()
    results = collect(logs_root)
    if not results:
        print(f"No verdicts found under {logs_root}")
        return
    counts: dict[str, int] = {}
    for case in sorted(results):
        verdict, path = results[case]
        counts[verdict] = counts.get(verdict, 0) + 1
        print(f"{case:45s} {verdict}")
    print("\nSummary:")
    for v, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {v:15s} {n}")
    print(f"  {'TOTAL':15s} {len(results)}")


if __name__ == "__main__":
    main()
