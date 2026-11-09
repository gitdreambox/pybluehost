from pathlib import Path

from scripts.pts_xml_summary import PtsXmlResult


def _result(case_id: str, verdict: str, *, path: str = "result.xml") -> PtsXmlResult:
    return PtsXmlResult(
        profile=case_id.split("/", 1)[0],
        case_id=case_id,
        verdict=verdict,
        path=Path(path),
        description="diagnostic",
    )


def test_load_expected_cases_supports_profiles_mapping(tmp_path):
    from scripts.pts_completion_check import load_expected_cases

    manifest = tmp_path / "expected.yaml"
    manifest.write_text(
        """profiles:
  L2CAP:
    - L2CAP/COS/CID/BI-01-C
  SDP:
    - SDP/SR/SA/BI-01-C
    - SDP/SR/SS/BI-02-C
""",
        encoding="utf-8",
    )

    assert load_expected_cases(manifest) == [
        "L2CAP/COS/CID/BI-01-C",
        "SDP/SR/SA/BI-01-C",
        "SDP/SR/SS/BI-02-C",
    ]


def test_check_completion_reports_missing_and_non_pass_cases():
    from scripts.pts_completion_check import check_completion

    status = check_completion(
        [
            "L2CAP/COS/CID/BI-01-C",
            "SDP/SR/SA/BI-01-C",
            "SDP/SR/SS/BI-02-C",
        ],
        [
            _result("L2CAP/COS/CID/BI-01-C", "PASS", path="l2cap.xml"),
            _result("SDP/SR/SS/BI-02-C", "INDCSV", path="sdp.xml"),
        ],
    )

    assert not status.passed
    assert status.pass_count == 1
    assert status.total == 3
    assert status.missing_cases == ["SDP/SR/SA/BI-01-C"]
    assert [r.case_id for r in status.non_pass_results] == ["SDP/SR/SS/BI-02-C"]


def test_check_completion_passes_when_all_expected_cases_pass():
    from scripts.pts_completion_check import check_completion

    status = check_completion(
        ["A/CASE", "B/CASE"],
        [_result("A/CASE", "PASS"), _result("B/CASE", "PASS")],
    )

    assert status.passed
    assert status.pass_count == 2
    assert status.missing_cases == []
    assert status.non_pass_results == []


def test_render_markdown_shows_completion_status_and_paths():
    from scripts.pts_completion_check import check_completion, render_markdown

    status = check_completion(
        ["SDP/SR/SS/BI-02-C"],
        [
            _result(
                "SDP/SR/SS/BI-02-C",
                "INDCSV",
                path="runs/SDP_SR_SS_BI_02_C.xml",
            )
        ],
    )

    markdown = render_markdown(status, root=Path("."))

    assert "Status: INCOMPLETE" in markdown
    assert "0/1 PASS" in markdown
    assert "`SDP/SR/SS/BI-02-C`" in markdown
    assert "`runs\\SDP_SR_SS_BI_02_C.xml`" in markdown
