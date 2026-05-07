"""pytest --trace option registration + propagation."""
from __future__ import annotations

import pathlib
import subprocess
import sys


_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_pytest_help_shows_trace_option():
    # ``-p no:debugging`` disables pytest's built-in ``--trace`` PDB shortcut
    # so our conftest can register ``--trace=<spec>`` for layer logging.
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:debugging", "--help"],
        capture_output=True, text=True,
        cwd=str(_PROJECT_ROOT),
    )
    assert "--trace" in r.stdout
    # The PyBlueHost option accepts a spec; its help text should be visible.
    assert "Trace spec" in r.stdout


def test_pytest_invalid_trace_exits_nonzero(tmp_path):
    # Place the throwaway test file inside the project so the project's
    # conftest.py is auto-discovered (pytest walks from the test file up to
    # rootdir collecting conftests).
    inline_dir = _PROJECT_ROOT / "tests" / "unit" / "_trace_smoke"
    inline_dir.mkdir(exist_ok=True)
    test_file = inline_dir / "test_inline_invalid_trace.py"
    test_file.write_text("def test_dummy(): pass\n")
    try:
        r = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                "-p", "no:debugging",
                str(test_file),
                "--trace=invalid_layer",
                "-q",
            ],
            capture_output=True, text=True,
            cwd=str(_PROJECT_ROOT),
        )
    finally:
        test_file.unlink(missing_ok=True)
        try:
            inline_dir.rmdir()
        except OSError:
            pass
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "Unknown layer" in out or "Invalid" in out
