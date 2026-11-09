"""Print the PTS final verdict from one auto-pts test-case log.

The retry harness (`scripts/pts_retry_cases.sh`) needs the verdict PTS itself
computed, because auto-pts's client-side summary can say ``BTP TIMEOUT`` /
``BTP ERROR`` while PTS already judged the case PASS. Scraping the summary log
therefore mislabels those runs and makes the harness retry a case that already
passed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from scripts.pts_collect_verdicts import _extract_verdict


def verdict_from_log(path: str | Path) -> str | None:
    """Return PTS's final verdict from ``path`` (or None when not judged yet)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return _extract_verdict(text, "")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: pts_case_verdict.py <case-log>", file=sys.stderr)
        return 2
    verdict = verdict_from_log(argv[0])
    if verdict:
        print(verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
