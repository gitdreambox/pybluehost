"""Summarize PTS result XML verdicts.

The Bluetooth PTS XML archive stores the test case and final verdict in text
blocks rather than stable structured tags. This helper scans those logs and
renders a markdown table that can be pasted into docs/PTS result records.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


_CASE_PATTERNS = (
    re.compile(r"Start Test Case:\s*([A-Z0-9]+(?:/[A-Z0-9_.-]+)+)"),
    re.compile(r"Test Case Started:\s*[^,\n]+,\s*([A-Z0-9]+(?:/[A-Z0-9_.-]+)+)\s+started"),
)
_FINAL_VERDICT_RE = re.compile(r"Final Verdict:\s*([A-Z]+)")
_DESCRIPTION_RE = re.compile(r"Verdict Description:\s*(.+)")
_BENIGN_DESCRIPTION_RE = re.compile(
    r"(successfully initiated connection|connection completed|"
    r"received hci disconnection event|hci disconnection event)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PtsXmlResult:
    profile: str
    case_id: str
    verdict: str
    path: Path
    description: str = ""


def parse_result_xml(path: Path) -> PtsXmlResult:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")

    case_id = _extract_case_id(text)
    verdicts = _FINAL_VERDICT_RE.findall(text)
    if not verdicts:
        raise ValueError(f"missing Final Verdict in {path}")
    verdict = verdicts[-1]
    descriptions = [m.strip() for m in _DESCRIPTION_RE.findall(text)]

    return PtsXmlResult(
        profile=case_id.split("/", 1)[0],
        case_id=case_id,
        verdict=verdict,
        path=path,
        description=_choose_description(verdict, descriptions),
    )


def scan_result_xmls(root: Path) -> list[PtsXmlResult]:
    root = Path(root)
    results: list[PtsXmlResult] = []
    for path in sorted(root.rglob("*.xml")):
        try:
            results.append(parse_result_xml(path))
        except ValueError:
            continue
    return sorted(results, key=lambda r: (r.profile, r.case_id, str(r.path)))


def latest_by_case(results: list[PtsXmlResult]) -> list[PtsXmlResult]:
    latest: dict[tuple[str, str], PtsXmlResult] = {}
    for result in sorted(results, key=lambda r: (r.profile, r.case_id, str(r.path))):
        latest[(result.profile, result.case_id)] = result
    return sorted(latest.values(), key=lambda r: (r.profile, r.case_id, str(r.path)))


def render_markdown(results: list[PtsXmlResult], *, root: Path | None = None) -> str:
    rows = [
        "| Profile | Test Case | Verdict | XML | Description |",
        "|---|---|---|---|---|",
    ]
    for result in results:
        path = _display_path(result.path, root=root)
        rows.append(
            f"| {result.profile} | `{result.case_id}` | {result.verdict} | "
            f"`{path}` | {_escape_table_text(result.description)} |"
        )
    return "\n".join(rows) + "\n"


def _extract_case_id(text: str) -> str:
    for pattern in _CASE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    raise ValueError("missing PTS test case id")


def _choose_description(verdict: str, descriptions: list[str]) -> str:
    if not descriptions:
        return ""
    if verdict == "PASS":
        return descriptions[-1]
    for description in descriptions:
        if not _BENIGN_DESCRIPTION_RE.search(description):
            return description
    return descriptions[-1]


def _display_path(path: Path, *, root: Path | None) -> str:
    if root is not None:
        try:
            path = path.resolve().relative_to(Path(root).resolve())
        except ValueError:
            pass
    return str(path).replace("/", "\\")


def _escape_table_text(text: str) -> str:
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _cli() -> int:
    parser = argparse.ArgumentParser(prog="pts_xml_summary")
    parser.add_argument(
        "root",
        nargs="?",
        default="runs",
        help="Root directory to scan recursively for PTS XML files.",
    )
    parser.add_argument(
        "--relative-to",
        default=None,
        help="Base path used to render relative XML paths. Defaults to root.",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Only render the latest XML result found for each test case.",
    )
    args = parser.parse_args()

    root = Path(args.root)
    relative_to = Path(args.relative_to) if args.relative_to else root
    results = scan_result_xmls(root)
    if args.latest:
        results = latest_by_case(results)
    sys.stdout.write(render_markdown(results, root=relative_to))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())