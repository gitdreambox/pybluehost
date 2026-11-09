"""Verdict import must not let a re-run overturn a deliberate `blocked`.

A `blocked` entry records a judgement made about the *case*, not about one run:
an errata that makes the case impossible, or a hardware limit. Logs pile up in
`/tmp/auto-pts/logs` across many days and the importer stamps every one of them
with the date it is invoked with, so without this guard every import silently
rewrites those judgements from whatever the most recent unrelated run happened
to produce.
"""
from pathlib import Path

import pytest
import yaml


@pytest.fixture()
def matrix_dir(tmp_path, monkeypatch):
    """Point pts_import_verdicts at a throwaway matrix directory."""
    import scripts.pts_import_verdicts as piv

    d = tmp_path / "matrix"
    monkeypatch.setattr(piv, "_MATRIX_DIR", d)
    return d


def _write_matrix(matrix_dir: Path, name: str, cases: dict) -> Path:
    matrix_dir.mkdir(parents=True, exist_ok=True)
    path = matrix_dir / name
    path.write_text(
        yaml.safe_dump({"group": name.split(".")[0].upper(), "last_updated": "2026-09-01",
                        "runs": 0, "cases": cases}),
        encoding="utf-8",
    )
    return path


def _collect(monkeypatch, results: dict) -> None:
    import scripts.pts_import_verdicts as piv

    monkeypatch.setattr(piv.pcv, "collect", lambda _root: results)


def test_import_preserves_a_blocked_verdict(matrix_dir, monkeypatch):
    from scripts.pts_import_verdicts import import_verdicts

    path = _write_matrix(matrix_dir, "gatt.yaml", {
        "GATT/SR/GAW/BV-01-C": {
            "verdict": "blocked", "last_run": "2026-09-16",
            "notes": "BLOCKED BY PTS ERRATUM", "bug_refs": [],
        },
    })
    _collect(monkeypatch, {"GATT/SR/GAW/BV-01-C": ("INCONC", "x.log")})

    out = import_verdicts("/nowhere", date="2026-09-16")

    entry = yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]["GATT/SR/GAW/BV-01-C"]
    assert entry["verdict"] == "blocked"
    assert entry["notes"] == "BLOCKED BY PTS ERRATUM"
    assert out["summary"]["preserved"] == 1
    assert out["summary"]["updated"] == 0


def test_import_force_overwrites_a_blocked_verdict(matrix_dir, monkeypatch):
    from scripts.pts_import_verdicts import import_verdicts

    path = _write_matrix(matrix_dir, "gatt.yaml", {
        "GATT/SR/GAW/BV-01-C": {
            "verdict": "blocked", "last_run": "2026-09-16",
            "notes": "obsolete", "bug_refs": [],
        },
    })
    _collect(monkeypatch, {"GATT/SR/GAW/BV-01-C": ("PASS", "x.log")})

    import_verdicts("/nowhere", date="2026-09-17", force=True)

    entry = yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]["GATT/SR/GAW/BV-01-C"]
    assert entry["verdict"] == "pass"
    assert entry["last_run"] == "2026-09-17"


def test_import_still_updates_a_non_blocked_verdict(matrix_dir, monkeypatch):
    from scripts.pts_import_verdicts import import_verdicts

    path = _write_matrix(matrix_dir, "gatt.yaml", {
        "GATT/SR/GAR/BI-09-C": {
            "verdict": "inconc", "last_run": "2026-09-01",
            "notes": "", "bug_refs": [],
        },
    })
    _collect(monkeypatch, {"GATT/SR/GAR/BI-09-C": ("PASS", "x.log")})

    out = import_verdicts("/nowhere", date="2026-09-16")

    entry = yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]["GATT/SR/GAR/BI-09-C"]
    assert entry["verdict"] == "pass"
    assert out["summary"] == {"updated": 1, "created": 0, "skipped": 0, "preserved": 0}
