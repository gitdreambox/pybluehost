"""The retry harness must record PTS's own verdict, not the client summary.

auto-pts logs two different outcomes in one test-case log: the client-side
summary (``BTP TIMEOUT`` when a WID handler raises) and PTS's
``PTS_LOGTYPE_FINAL_VERDICT`` block. The retry script used to scrape the
summary log first, so a case that PTS judged PASS was recorded as an abort and
re-run to exhaustion — GAP/SEC/AUT/BV-17/18/26 on 2026-11-02 all showed
``BTP TIMEOUT`` in the summary while PTS's final verdict was PASS.
"""
from pathlib import Path

from scripts.pts_case_verdict import verdict_from_log


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "GAP_SEC_AUT_BV-17-C_2026_11_02_20_32_45.log"
    path.write_text(text, encoding="utf-8")
    return path


def test_final_verdict_wins_over_a_client_side_abort(tmp_path):
    log = _write(tmp_path, """
    get_error_code returning error code 'BTP TIMEOUT' for exception TimeoutError()
    After run_test_case error_code='BTP TIMEOUT' status='RUNNING'
    PTS_LOGTYPE_FINAL_VERDICT Final Verdict

    +220062 ms

     GAP/SEC/AUT/BV-17-C PASS
""")

    assert verdict_from_log(log) == "PASS"


def test_indcsv_is_normalised(tmp_path):
    log = _write(tmp_path, """
    PTS_LOGTYPE_FINAL_VERDICT Final Verdict

     GAP/SEC/AUT/BV-17-C INDCSV
""")

    assert verdict_from_log(log) == "INCONC"


def test_missing_final_verdict_returns_none(tmp_path):
    log = _write(tmp_path, """
    get_error_code returning error code 'FATAL ERROR' for exception RuntimeError()
""")

    assert verdict_from_log(log) is None
