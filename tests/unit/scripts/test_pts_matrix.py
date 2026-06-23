import pytest


@pytest.fixture
def gap_matrix_path(tmp_path):
    path = tmp_path / "gap.yaml"
    path.write_text("""group: GAP
last_updated: 2026-06-08
runs: 0
cases:
  GAP/CENTRAL/CONN/BV-01-C:
    verdict: pass
    last_run: '2026-06-08'
    notes: clean
    bug_refs: []
  GAP/CENTRAL/CONN/BV-02-C:
    verdict: fail
    last_run: '2026-06-08'
    notes: WID 42 addr mismatch
    bug_refs: [abc123def]
  GAP/CENTRAL/CONN/BV-03-C:
    verdict: untested
    last_run: null
    notes: ''
    bug_refs: []
""")
    return path


def test_load_matrix(gap_matrix_path):
    from scripts.pts_matrix import load_matrix
    m = load_matrix(gap_matrix_path)
    assert m["group"] == "GAP"
    assert len(m["cases"]) == 3


def test_summary_counts_by_verdict(gap_matrix_path):
    from scripts.pts_matrix import summary_for
    s = summary_for(gap_matrix_path)
    assert s["pass"] == 1
    assert s["fail"] == 1
    assert s["untested"] == 1
    assert s["inconc"] == 0
    assert s["blocked"] == 0
    assert s["total"] == 3


def test_update_verdict(gap_matrix_path):
    from scripts.pts_matrix import load_matrix, update_case, save_matrix
    m = load_matrix(gap_matrix_path)
    update_case(
        m, "GAP/CENTRAL/CONN/BV-03-C",
        verdict="pass", last_run="2026-06-09", notes="passed after fix",
    )
    save_matrix(gap_matrix_path, m)
    m2 = load_matrix(gap_matrix_path)
    assert m2["cases"]["GAP/CENTRAL/CONN/BV-03-C"]["verdict"] == "pass"
    assert m2["cases"]["GAP/CENTRAL/CONN/BV-03-C"]["last_run"] == "2026-06-09"
    assert m2["cases"]["GAP/CENTRAL/CONN/BV-03-C"]["notes"] == "passed after fix"


def test_update_appends_bug_ref(gap_matrix_path):
    from scripts.pts_matrix import load_matrix, update_case
    m = load_matrix(gap_matrix_path)
    update_case(m, "GAP/CENTRAL/CONN/BV-02-C", verdict="fail", bug="abc456")
    refs = m["cases"]["GAP/CENTRAL/CONN/BV-02-C"]["bug_refs"]
    assert "abc456" in refs
    assert "abc123def" in refs    # original bug ref preserved


def test_update_rejects_invalid_verdict(gap_matrix_path):
    from scripts.pts_matrix import load_matrix, update_case
    m = load_matrix(gap_matrix_path)
    with pytest.raises(ValueError, match="verdict"):
        update_case(m, "GAP/CENTRAL/CONN/BV-01-C", verdict="bogus")


def test_update_unknown_case_raises(gap_matrix_path):
    from scripts.pts_matrix import load_matrix, update_case
    m = load_matrix(gap_matrix_path)
    with pytest.raises(KeyError):
        update_case(m, "GAP/UNKNOWN/CASE", verdict="pass")


def test_render_summary_markdown(tmp_path):
    """Render a summary across multiple matrices to markdown."""
    from scripts.pts_matrix import render_summary_markdown

    (tmp_path / "gap.yaml").write_text("""group: GAP
last_updated: 2026-06-08
runs: 1
cases:
  G1: {verdict: pass, last_run: null, notes: '', bug_refs: []}
  G2: {verdict: fail, last_run: null, notes: '', bug_refs: []}
""")
    (tmp_path / "gatt.yaml").write_text("""group: GATT
last_updated: 2026-06-08
runs: 1
cases:
  T1: {verdict: pass, last_run: null, notes: '', bug_refs: []}
""")
    md = render_summary_markdown(tmp_path)
    assert "GAP" in md and "GATT" in md
    assert "pass" in md.lower()
    # Pass-rate is rendered as % somewhere.
    assert "%" in md


def test_init_seeds_matrix_from_case_list(tmp_path):
    from scripts.pts_matrix import init_matrix, load_matrix
    path = tmp_path / "l2cap.yaml"
    cases = ["L2CAP/COC/BV-01-C", "L2CAP/COC/BV-02-C"]
    init_matrix(path, group="L2CAP", cases=cases)
    m = load_matrix(path)
    assert m["group"] == "L2CAP"
    assert set(m["cases"]) == set(cases)
    for entry in m["cases"].values():
        assert entry["verdict"] == "untested"
