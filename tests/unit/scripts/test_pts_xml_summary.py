from pathlib import Path


def _write_pts_xml(path: Path, *, case_id: str, verdict: str,
                   description: str = "clean") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = case_id.split("/", 1)[0]
    path.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<ARCHIVE>
  <VERSION>2.0</VERSION>
  <PicsPixit>Test Case Started: {profile} v. 11.13.0.4, {case_id} started on Monday, June 22, 2026, 20:13:49</PicsPixit>
  <LOG>
Start Test Case:         {case_id}
Verdict Description:     {description}
Final Verdict:           {verdict}
Encrypted Verdict:       redacted
Test Case Ended:         {case_id}
Final Verdict:{verdict}
  </LOG>
</ARCHIVE>
""",
        encoding="utf-8",
    )


def test_parse_result_xml_extracts_case_verdict_and_description(tmp_path):
    from scripts.pts_xml_summary import parse_result_xml

    xml = tmp_path / "SDP_SR_SS_BI_02_C.xml"
    _write_pts_xml(
        xml,
        case_id="SDP/SR/SS/BI-02-C",
        verdict="INDCSV",
        description="Did not receive SDP_ERROR_RSP with the error code 0x0003",
    )

    result = parse_result_xml(xml)

    assert result.profile == "SDP"
    assert result.case_id == "SDP/SR/SS/BI-02-C"
    assert result.verdict == "INDCSV"
    assert result.description == (
        "Did not receive SDP_ERROR_RSP with the error code 0x0003"
    )
    assert result.path == xml


def test_scan_result_xmls_returns_sorted_results(tmp_path):
    from scripts.pts_xml_summary import scan_result_xmls

    _write_pts_xml(
        tmp_path / "workspace" / "SDP" / "case2" / "result.xml",
        case_id="SDP/SR/SS/BI-02-C",
        verdict="PASS",
    )
    _write_pts_xml(
        tmp_path / "workspace" / "L2CAP" / "case1" / "result.xml",
        case_id="L2CAP/COS/CID/BI-01-C",
        verdict="PASS",
    )
    (tmp_path / "workspace" / "notes.txt").write_text("ignore", encoding="utf-8")

    results = scan_result_xmls(tmp_path / "workspace")

    assert [r.case_id for r in results] == [
        "L2CAP/COS/CID/BI-01-C",
        "SDP/SR/SS/BI-02-C",
    ]


def test_render_markdown_uses_relative_paths(tmp_path):
    from scripts.pts_xml_summary import render_markdown, scan_result_xmls

    _write_pts_xml(
        tmp_path / "workspace" / "SDP" / "case1" / "result.xml",
        case_id="SDP/SR/SA/BI-01-C",
        verdict="PASS",
        description="Record found",
    )
    results = scan_result_xmls(tmp_path / "workspace")

    markdown = render_markdown(results, root=tmp_path)

    assert "| Profile | Test Case | Verdict | XML | Description |" in markdown
    assert "| SDP | `SDP/SR/SA/BI-01-C` | PASS |" in markdown
    assert "`workspace\\SDP\\case1\\result.xml`" in markdown
    assert "Record found" in markdown


def test_non_pass_result_prefers_diagnostic_description(tmp_path):
    from scripts.pts_xml_summary import parse_result_xml

    xml = tmp_path / "SDP_SR_SS_BI_02_C.xml"
    _write_pts_xml(
        xml,
        case_id="SDP/SR/SS/BI-02-C",
        verdict="INDCSV",
        description="Did not receive SDP_ERROR_RSP with the error code 0x0003",
    )
    text = xml.read_text(encoding="utf-8")
    xml.write_text(
        text.replace(
            "Final Verdict:           INDCSV",
            "Verdict Description:     Received HCI disconnection event. Handle = 0x0100\n"
            "Final Verdict:           INDCSV",
        ),
        encoding="utf-8",
    )

    result = parse_result_xml(xml)

    assert result.description == (
        "Did not receive SDP_ERROR_RSP with the error code 0x0003"
    )


def test_latest_by_case_keeps_newest_path_per_case(tmp_path):
    from scripts.pts_xml_summary import latest_by_case, scan_result_xmls

    _write_pts_xml(
        tmp_path / "SDP_SR_SS_BI_02_C_2026_06_22_20_13_49" / "result.xml",
        case_id="SDP/SR/SS/BI-02-C",
        verdict="INDCSV",
    )
    _write_pts_xml(
        tmp_path / "SDP_SR_SS_BI_02_C_2026_06_24_10_00_00" / "result.xml",
        case_id="SDP/SR/SS/BI-02-C",
        verdict="PASS",
    )

    latest = latest_by_case(scan_result_xmls(tmp_path))

    assert len(latest) == 1
    assert latest[0].case_id == "SDP/SR/SS/BI-02-C"
    assert latest[0].verdict == "PASS"
