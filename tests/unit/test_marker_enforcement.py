"""real_hardware_only / virtual_only marker enforcement."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
INLINE_PYTEST_TIMEOUT_SECONDS = 30
_CONFTEST_SPEC = importlib.util.spec_from_file_location(
    "project_conftest_for_marker_enforcement_tests",
    ROOT / "tests" / "conftest.py",
)
assert _CONFTEST_SPEC is not None
assert _CONFTEST_SPEC.loader is not None
project_conftest = importlib.util.module_from_spec(_CONFTEST_SPEC)
_CONFTEST_SPEC.loader.exec_module(project_conftest)


class _Marker:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


def _run_inline(body: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run pytest on an inline test under tests/unit so project conftest loads."""
    test_file = ROOT / "tests" / "unit" / f"_inline_marker_{uuid.uuid4().hex}.py"
    test_file.write_text(textwrap.dedent(body), encoding="utf-8")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_file),
        "-v",
        "-rs",
        "--no-header",
        "--strict-markers",
        *args,
    ]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=INLINE_PYTEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or exc.output or ""
        stderr = exc.stderr or ""
        timeout_message = (
            f"Inline pytest timed out after {INLINE_PYTEST_TIMEOUT_SECONDS} seconds\n"
        )
        return subprocess.CompletedProcess(
            cmd,
            returncode=124,
            stdout=str(stdout),
            stderr=timeout_message + str(stderr),
        )
    finally:
        test_file.unlink(missing_ok=True)


def test_run_inline_reports_timeout(monkeypatch: pytest.MonkeyPatch):
    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            cmd=[sys.executable, "-m", "pytest"],
            timeout=30,
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    r = _run_inline("def test_dummy(): pass")
    out = r.stdout + r.stderr

    assert r.returncode != 0
    assert "timed out after 30 seconds" in out
    assert "partial stdout" in out
    assert "partial stderr" in out


def test_inline_uses_project_conftest_and_strict_markers():
    body = """
    def test_fixture_available(selected_transport_spec):
        assert selected_transport_spec == "virtual"
    """
    r = _run_inline(body, "--transport=virtual")
    assert r.returncode == 0, r.stdout + r.stderr

    body = """
    import pytest
    @pytest.mark.not_registered_by_project
    def test_unknown_marker():
        pass
    """
    r = _run_inline(body, "--transport=virtual")
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "not_registered_by_project" in out


def test_real_hardware_only_bare_skipped_on_virtual():
    body = """
    import pytest
    @pytest.mark.real_hardware_only
    def test_marked():
        assert True
    """
    r = _run_inline(body, "--transport=virtual")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 skipped" in r.stdout
    assert "requires real hardware" in (r.stdout + r.stderr)


def test_virtual_only_runs_on_virtual():
    body = """
    import pytest
    @pytest.mark.virtual_only
    def test_marked():
        assert True
    """
    r = _run_inline(body, "--transport=virtual")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 passed" in r.stdout


def test_transport_uart_marker_skipped_on_virtual():
    body = """
    import pytest
    @pytest.mark.real_hardware_only(transport="uart")
    def test_marked():
        assert True
    """
    r = _run_inline(body, "--transport=virtual")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 skipped" in r.stdout
    assert "requires real hardware" in (r.stdout + r.stderr)


def test_vendor_without_transport_is_marker_error():
    body = """
    import pytest
    @pytest.mark.real_hardware_only(vendor="intel")
    def test_marked():
        assert True
    """
    r = _run_inline(body, "--transport=virtual")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "1 skipped" in out
    assert "marker error" in out
    assert "vendor= requires transport='usb'" in out


def test_invalid_transport_value_is_marker_error():
    body = """
    import pytest
    @pytest.mark.real_hardware_only(transport="bluetooth")
    def test_marked():
        assert True
    """
    r = _run_inline(body, "--transport=virtual")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "1 skipped" in out
    assert "marker error" in out
    assert "transport must be 'usb' or 'uart'" in out


def test_invalid_vendor_value_is_marker_error():
    body = """
    import pytest
    @pytest.mark.real_hardware_only(transport="usb", vendor="qualcomm")
    def test_marked():
        assert True
    """
    r = _run_inline(body, "--transport=virtual")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "1 skipped" in out
    assert "marker error" in out
    assert "unsupported vendor" in out


def test_virtual_only_skip_reason_on_non_virtual_family():
    assert (
        project_conftest._virtual_only_skip_reason("usb")
        == "deterministic test, runs only on virtual controller"
    )
    assert project_conftest._virtual_only_skip_reason("uart") is not None
    assert project_conftest._virtual_only_skip_reason("virtual") is None


def test_real_hardware_only_transport_constraint_on_real_hardware_family():
    marker = _Marker(transport="usb")

    assert (
        project_conftest._real_hw_skip_reason(
            marker,
            "uart",
            current_vendor=None,
        )
        == "requires 'usb' transport, got 'uart'"
    )
    assert project_conftest._real_hw_skip_reason(marker, "usb", "intel") is None


@pytest.mark.parametrize("vendors", ["intel", ("intel", "realtek"), ["intel", "csr"]])
def test_real_hardware_only_accepts_vendor_string_tuple_and_list(vendors: object):
    marker = _Marker(transport="usb", vendor=vendors)

    assert project_conftest._real_hw_skip_reason(marker, "usb", "intel") is None


def test_real_hardware_only_rejects_bad_vendor_inside_tuple_or_list():
    tuple_marker = _Marker(transport="usb", vendor=("intel", "qualcomm"))
    list_marker = _Marker(transport="usb", vendor=["csr", "qualcomm"])

    assert "unsupported vendor 'qualcomm'" in project_conftest._real_hw_skip_reason(
        tuple_marker,
        "usb",
        "intel",
    )
    assert "unsupported vendor 'qualcomm'" in project_conftest._real_hw_skip_reason(
        list_marker,
        "usb",
        "csr",
    )


def test_real_hardware_only_skips_non_matching_vendor():
    marker = _Marker(transport="usb", vendor=("intel", "realtek"))

    assert (
        project_conftest._real_hw_skip_reason(marker, "usb", "csr")
        == "requires vendor in ('intel', 'realtek'), got 'csr'"
    )
