"""Regenerate PTS result summary after a manual PTS run."""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from collections import defaultdict
from pathlib import Path

from scripts.pts_completion_check import (
    CompletionStatus,
    check_completion,
    load_expected_cases,
    render_markdown as render_completion_markdown,
)
from scripts.pts_xml_summary import (
    PtsXmlResult,
    latest_by_case,
    render_markdown as render_xml_markdown,
    scan_result_xmls,
)


def render_summary_document(
    expected_cases: list[str],
    results: list[PtsXmlResult],
    *,
    generated_on: str | None = None,
    root: Path | None = None,
) -> str:
    generated_on = generated_on or _dt.date.today().isoformat()
    latest_results = latest_by_case(results)
    status = check_completion(expected_cases, latest_results)

    lines = [
        "# PTS XML Evidence Summary",
        "",
        f"Generated: {generated_on}",
        "",
        "This page summarizes the latest PTS XML verdict found for the current "
        "CSR8510 / PTS 8.13.0.4 manual test campaign. It is evidence from "
        "existing XML files only; it does not claim V1.2 PTS IUT completion "
        "unless the completion check status is PASS.",
        "",
        "Regenerate this page after manual PTS execution:",
        "",
        "```powershell",
        "uv run python scripts\\pts_post_run_update.py "
        "docs\\pts\\results\\v1.2-current-expected.yaml runs "
        "--summary-output docs\\pts\\results\\SUMMARY.md --relative-to .",
        "```",
        "",
        "## Profile Summary",
        "",
        "| Profile | Expected | PASS | Non-PASS | Missing XML | Pass-rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in _profile_rows(expected_cases, latest_results):
        lines.append(
            f"| {row['profile']} | {row['expected']} | {row['pass']} | "
            f"{row['non_pass']} | {row['missing']} | {row['pass_rate']:.1f}% |"
        )
    total = _total_row(expected_cases, latest_results)
    lines.append(
        f"| **Total expected** | **{total['expected']}** | **{total['pass']}** | "
        f"**{total['non_pass']}** | **{total['missing']}** | "
        f"**{total['pass_rate']:.1f}%** |"
    )
    lines.extend([
        "",
        "## Latest XML Verdicts",
        "",
        render_xml_markdown(
            [r for r in latest_results if r.case_id in set(expected_cases)],
            root=root,
        ).rstrip(),
        "",
        "## Completion Check",
        "",
        render_completion_markdown(status, root=root).rstrip(),
        "",
    ])
    return "\n".join(lines)


def write_summary_document(
    expected_cases: list[str],
    results: list[PtsXmlResult],
    output: Path,
    *,
    generated_on: str | None = None,
    root: Path | None = None,
) -> CompletionStatus:
    status = check_completion(expected_cases, latest_by_case(results))
    markdown = render_summary_document(
        expected_cases,
        results,
        generated_on=generated_on,
        root=root,
    )
    Path(output).write_text(markdown + "\n", encoding="utf-8")
    return status


def _profile_rows(
    expected_cases: list[str],
    results: list[PtsXmlResult],
) -> list[dict[str, float | int | str]]:
    by_profile: dict[str, list[str]] = defaultdict(list)
    for case in expected_cases:
        by_profile[case.split("/", 1)[0]].append(case)
    latest = {result.case_id: result for result in latest_by_case(results)}
    return [
        _row_for_profile(profile, cases, latest)
        for profile, cases in sorted(by_profile.items())
    ]


def _row_for_profile(
    profile: str,
    cases: list[str],
    latest: dict[str, PtsXmlResult],
) -> dict[str, float | int | str]:
    expected = len(cases)
    pass_count = sum(
        1 for case in cases
        if case in latest and latest[case].verdict == "PASS"
    )
    non_pass = sum(
        1 for case in cases
        if case in latest and latest[case].verdict != "PASS"
    )
    missing = sum(1 for case in cases if case not in latest)
    pass_rate = 100.0 * pass_count / expected if expected else 0.0
    return {
        "profile": profile,
        "expected": expected,
        "pass": pass_count,
        "non_pass": non_pass,
        "missing": missing,
        "pass_rate": pass_rate,
    }


def _total_row(
    expected_cases: list[str],
    results: list[PtsXmlResult],
) -> dict[str, float | int]:
    latest = {result.case_id: result for result in latest_by_case(results)}
    expected = len(expected_cases)
    pass_count = sum(
        1 for case in expected_cases
        if case in latest and latest[case].verdict == "PASS"
    )
    non_pass = sum(
        1 for case in expected_cases
        if case in latest and latest[case].verdict != "PASS"
    )
    missing = sum(1 for case in expected_cases if case not in latest)
    pass_rate = 100.0 * pass_count / expected if expected else 0.0
    return {
        "expected": expected,
        "pass": pass_count,
        "non_pass": non_pass,
        "missing": missing,
        "pass_rate": pass_rate,
    }


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pts_post_run_update")
    parser.add_argument("expected", help="YAML file listing expected PTS cases")
    parser.add_argument(
        "root",
        nargs="?",
        default="runs",
        help="Root directory to scan recursively for PTS XML files.",
    )
    parser.add_argument(
        "--summary-output",
        default=None,
        help="Write regenerated SUMMARY.md to this path. Prints to stdout if omitted.",
    )
    parser.add_argument(
        "--relative-to",
        default=".",
        help="Base path used to render relative XML paths.",
    )
    args = parser.parse_args(argv)

    expected = load_expected_cases(Path(args.expected))
    results = scan_result_xmls(Path(args.root))
    markdown = render_summary_document(
        expected,
        results,
        root=Path(args.relative_to),
    )
    status = check_completion(expected, latest_by_case(results))
    if args.summary_output:
        Path(args.summary_output).write_text(markdown + "\n", encoding="utf-8")
    else:
        sys.stdout.write(markdown + "\n")
    return 0 if status.passed else 1


if __name__ == "__main__":
    sys.exit(_cli())
