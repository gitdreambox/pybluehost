"""Session header and terminal summary."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
INLINE_PYTEST_TIMEOUT_SECONDS = 30
_CONFTEST_SPEC = importlib.util.spec_from_file_location(
    "project_conftest_for_report_header_tests",
    ROOT / "tests" / "conftest.py",
)
assert _CONFTEST_SPEC is not None
assert _CONFTEST_SPEC.loader is not None
project_conftest = importlib.util.module_from_spec(_CONFTEST_SPEC)
_CONFTEST_SPEC.loader.exec_module(project_conftest)


@dataclass(frozen=True)
class _Candidate:
    vendor: str
    name: str
    bus: int
    address: int


class _Config:
    def __init__(
        self,
        *,
        list_transports: bool = False,
        transport: str | None = None,
        peer: str | None = None,
    ) -> None:
        self._list_transports = list_transports
        self._transport = transport
        self._peer = peer

    def getoption(self, name: str) -> str | bool | None:
        if name == "--list-transports":
            return self._list_transports
        if name == "--transport":
            return self._transport
        if name == "--transport-peer":
            return self._peer
        raise AssertionError(f"unexpected option: {name}")


class _TerminalReporter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write_sep(self, sep: str, title: str | None = None) -> None:
        self.lines.append(title or sep)

    def write_line(self, line: str) -> None:
        self.lines.append(line)


def _run_inline(body: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run pytest on an inline test under tests/unit so project conftest loads."""
    test_file = ROOT / "tests" / "unit" / f"_inline_header_{uuid.uuid4().hex}.py"
    test_file.write_text(textwrap.dedent(body), encoding="utf-8")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_file),
        "-v",
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


def test_header_shows_explicit_virtual():
    r = _run_inline("def test_dummy(): pass", "--transport=virtual")
    out = r.stdout + r.stderr

    assert r.returncode == 0, out
    assert "[pybluehost-tests] transport: virtual [explicit]" in out


def test_report_header_shows_explicit_peer_virtual():
    assert project_conftest.pytest_report_header(
        _Config(transport="virtual", peer="virtual"),
    ) == [
        "[pybluehost-tests] transport: virtual [explicit]",
        "[pybluehost-tests] peer transport: virtual [explicit]",
    ]


def test_peer_report_header_uses_peer_explicit_label_when_primary_auto(
    monkeypatch: pytest.MonkeyPatch,
):
    config = _Config(peer="virtual")
    setattr(config, project_conftest._PRIMARY_CACHE_ATTR, "virtual")

    assert project_conftest.pytest_report_header(config) == [
        "[pybluehost-tests] transport: virtual [auto-detected]",
        "[pybluehost-tests] peer transport: virtual [explicit]",
    ]


def test_format_header_spec_uses_friendly_usb_candidate(
    monkeypatch: pytest.MonkeyPatch,
):
    from pybluehost.transport.usb import USBTransport

    monkeypatch.setattr(
        USBTransport,
        "list_devices",
        classmethod(
            lambda cls: [
                _Candidate(vendor="intel", name="Intel AX210", bus=1, address=4),
            ]
        ),
    )

    assert project_conftest._format_header_spec(
        "usb:vendor=intel,bus=1,address=4",
    ) == "usb (Intel AX210, bus=1 address=4)"


def test_no_fallback_summary_when_explicit_virtual_stack_fixture_used():
    body = """
    def test_dummy(stack):
        assert stack is not None
    """
    r = _run_inline(body, "--transport=virtual")
    out = r.stdout + r.stderr

    assert r.returncode == 0, out
    assert "Auto-detect found no hardware" not in out
    assert "pybluehost transport summary" not in out


def test_report_header_suppressed_for_list_transports(
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_if_resolved(_config: object) -> str:
        raise AssertionError("list mode should not resolve transport specs")

    monkeypatch.setattr(project_conftest, "_resolve_primary_spec", fail_if_resolved)

    assert project_conftest.pytest_report_header(
        _Config(list_transports=True),
    ) == []


def test_report_header_uses_exact_fallback_label(monkeypatch: pytest.MonkeyPatch):
    tracker = project_conftest.FallbackTracker()
    tracker.mark_fallback()
    monkeypatch.setattr(project_conftest, "_FALLBACK_TRACKER", tracker)

    assert project_conftest._header_source_label(_Config()) == (
        "auto-detected — no hardware found"
    )


def test_fallback_summary_uses_stack_fixture_count(monkeypatch: pytest.MonkeyPatch):
    tracker = project_conftest.FallbackTracker()
    tracker.mark_fallback()
    tracker.increment()
    tracker.increment()
    monkeypatch.setattr(project_conftest, "_FALLBACK_TRACKER", tracker)
    terminal = _TerminalReporter()

    project_conftest.pytest_terminal_summary(terminal, exitstatus=0, config=_Config())

    assert terminal.lines == [
        "pybluehost transport summary",
        "⚠  Auto-detect found no hardware. 2 tests ran on virtual.",
        "   Set --transport=usb (or PYBLUEHOST_TEST_TRANSPORT=usb) to validate",
        "   against real hardware.",
        "=",
    ]
