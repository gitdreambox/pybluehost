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


def test_render_summary_document_groups_expected_cases_by_profile():
    from scripts.pts_post_run_update import render_summary_document

    markdown = render_summary_document(
        [
            "L2CAP/COS/CID/BI-01-C",
            "SDP/SR/SA/BI-01-C",
            "SDP/SR/SS/BI-02-C",
            "GAP/CENTRAL/CONN/BV-01-C",
        ],
        [
            _result("L2CAP/COS/CID/BI-01-C", "PASS", path="runs/l2cap.xml"),
            _result("SDP/SR/SA/BI-01-C", "PASS", path="runs/sdp-pass.xml"),
            _result("SDP/SR/SS/BI-02-C", "INDCSV", path="runs/sdp-indcsv.xml"),
        ],
        generated_on="2026-06-25",
        root=Path("."),
    )

    assert "Generated: 2026-06-25" in markdown
    assert "| L2CAP | 1 | 1 | 0 | 0 | 100.0% |" in markdown
    assert "| SDP | 2 | 1 | 1 | 0 | 50.0% |" in markdown
    assert "| GAP | 1 | 0 | 0 | 1 | 0.0% |" in markdown
    assert "| **Total expected** | **4** | **2** | **1** | **1** | **50.0%** |" in markdown
    assert "`GAP/CENTRAL/CONN/BV-01-C`" in markdown
    assert "`SDP/SR/SS/BI-02-C`" in markdown
    assert "`runs\\sdp-indcsv.xml`" in markdown


def test_write_summary_document_writes_markdown_and_returns_status(tmp_path):
    from scripts.pts_post_run_update import write_summary_document

    output = tmp_path / "SUMMARY.md"
    status = write_summary_document(
        ["SDP/SR/SS/BI-02-C"],
        [_result("SDP/SR/SS/BI-02-C", "PASS", path="runs/sdp.xml")],
        output,
        generated_on="2026-06-25",
        root=Path("."),
    )

    assert status.passed
    assert output.read_text(encoding="utf-8").startswith("# PTS XML Evidence Summary")
