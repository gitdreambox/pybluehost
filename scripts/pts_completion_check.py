"""Check whether expected PTS cases have PASS XML evidence."""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from scripts.pts_xml_summary import (
    PtsXmlResult,
    latest_by_case,
    scan_result_xmls,
)


@dataclass(frozen=True)
class CompletionStatus:
    total: int
    pass_count: int
    missing_cases: list[str]
    non_pass_results: list[PtsXmlResult]

    @property
    def passed(self) -> bool:
        return not self.missing_cases and not self.non_pass_results


def load_expected_cases(path: Path) -> list[str]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cases: list[str] = []
    if isinstance(data.get("cases"), list):
        cases.extend(str(case) for case in data["cases"])
    profiles = data.get("profiles")
    if isinstance(profiles, dict):
        for profile_cases in profiles.values():
            if isinstance(profile_cases, list):
                cases.extend(str(case) for case in profile_cases)
    return sorted(dict.fromkeys(cases))


def check_completion(
    expected_cases: list[str],
    results: list[PtsXmlResult],
) -> CompletionStatus:
    latest = {result.case_id: result for result in latest_by_case(results)}
    missing = sorted(case for case in expected_cases if case not in latest)
    non_pass = sorted(
        (
            latest[case]
            for case in expected_cases
            if case in latest and latest[case].verdict != "PASS"
        ),
        key=lambda r: r.case_id,
    )
    pass_count = sum(
        1 for case in expected_cases
        if case in latest and latest[case].verdict == "PASS"
    )
    return CompletionStatus(
        total=len(expected_cases),
        pass_count=pass_count,
        missing_cases=missing,
        non_pass_results=non_pass,
    )


def render_markdown(status: CompletionStatus, *, root: Path | None = None) -> str:
    label = "PASS" if status.passed else "INCOMPLETE"
    lines = [
        "# PTS Completion Check",
        "",
        f"Status: {label}",
        "",
        f"Summary: {status.pass_count}/{status.total} PASS",
        "",
    ]
    if status.missing_cases:
        lines.extend([
            "## Missing XML Evidence",
            "",
            "| Test Case |",
            "|---|",
        ])
        lines.extend(f"| `{case}` |" for case in status.missing_cases)
        lines.append("")
    if status.non_pass_results:
        lines.extend([
            "## Non-PASS XML Verdicts",
            "",
            "| Test Case | Verdict | XML | Description |",
            "|---|---|---|---|",
        ])
        for result in status.non_pass_results:
            lines.append(
                f"| `{result.case_id}` | {result.verdict} | "
                f"`{_display_path(result.path, root=root)}` | "
                f"{_escape_table_text(result.description)} |"
            )
        lines.append("")
    return "\n".join(lines)


def _display_path(path: Path, *, root: Path | None) -> str:
    if root is not None:
        try:
            path = path.resolve().relative_to(Path(root).resolve())
        except ValueError:
            pass
    return str(path).replace("/", "\\")


def _escape_table_text(text: str) -> str:
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pts_completion_check")
    parser.add_argument("expected", help="YAML file listing expected PTS cases")
    parser.add_argument(
        "root",
        nargs="?",
        default="runs",
        help="Root directory to scan recursively for PTS XML files.",
    )
    parser.add_argument(
        "--relative-to",
        default=".",
        help="Base path used to render relative XML paths.",
    )
    args = parser.parse_args(argv)

    expected = load_expected_cases(Path(args.expected))
    results = scan_result_xmls(Path(args.root))
    status = check_completion(expected, results)
    sys.stdout.write(render_markdown(status, root=Path(args.relative_to)))
    return 0 if status.passed else 1


if __name__ == "__main__":
    sys.exit(_cli())
