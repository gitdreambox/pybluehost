"""Session-scoped transport-selection fixtures."""
from __future__ import annotations

import subprocess
import sys
import textwrap
import uuid
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
_CONFTEST_SPEC = importlib.util.spec_from_file_location(
    "project_conftest_for_session_fixture_tests",
    ROOT / "tests" / "conftest.py",
)
assert _CONFTEST_SPEC is not None
assert _CONFTEST_SPEC.loader is not None
project_conftest = importlib.util.module_from_spec(_CONFTEST_SPEC)
_CONFTEST_SPEC.loader.exec_module(project_conftest)


class _Config:
    def __init__(
        self,
        *,
        transport: str | None = None,
        peer: str | None = None,
    ) -> None:
        self._transport = transport
        self._peer = peer

    def getoption(self, name: str) -> str | None:
        if name == "--transport":
            return self._transport
        if name == "--transport-peer":
            return self._peer
        raise AssertionError(f"unexpected option: {name}")


def _run_inline(body: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run pytest on an inline test file under tests/unit so conftest loads."""
    test_file = ROOT / "tests" / "unit" / f"_inline_session_{uuid.uuid4().hex}.py"
    test_file.write_text(textwrap.dedent(body), encoding="utf-8")
    try:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(test_file),
                "-q",
                "--no-header",
                *args,
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
    finally:
        test_file.unlink(missing_ok=True)


def test_explicit_virtual():
    body = """
    def test_check(selected_transport_spec, transport_mode):
        assert selected_transport_spec == "virtual"
        assert transport_mode == "virtual"
    """
    r = _run_inline(body, "--transport=virtual")
    assert r.returncode == 0, r.stdout + r.stderr


def test_invalid_spec_exits_with_4():
    body = """
    def test_dummy(selected_transport_spec):
        pass
    """
    r = _run_inline(body, "--transport=garbage")
    assert r.returncode == 4, r.stdout + r.stderr
    assert "Invalid transport spec" in (r.stdout + r.stderr)


def test_env_var_used_when_no_flag(monkeypatch: pytest.MonkeyPatch):
    body = """
    def test_check(selected_transport_spec):
        assert selected_transport_spec == "virtual"
    """
    monkeypatch.setenv("PYBLUEHOST_TEST_TRANSPORT", "virtual")
    r = _run_inline(body)
    assert r.returncode == 0, r.stdout + r.stderr


def test_cross_family_peer_exits_nonzero():
    body = """
    def test_dummy(selected_peer_spec):
        pass
    """
    r = _run_inline(
        body,
        "--transport=usb",
        "--transport-peer=virtual",
    )
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "Peer transport must match primary family" in out or "unavailable" in out


def test_primary_resolution_is_cached_per_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_autodetect() -> str:
        nonlocal calls
        calls += 1
        return "virtual"

    monkeypatch.delenv("PYBLUEHOST_TEST_TRANSPORT", raising=False)
    monkeypatch.setattr(project_conftest, "autodetect_primary", fake_autodetect)
    config = _Config()

    assert project_conftest._resolve_primary_spec(config) == "virtual"
    assert project_conftest._resolve_primary_spec(config) == "virtual"
    assert calls == 1


def test_ambiguous_usb_primary_passes_none_to_peer_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[int | None, int | None]] = []

    def fake_find_second_usb_adapter(
        primary_bus: int | None,
        primary_address: int | None,
    ) -> str | None:
        seen.append((primary_bus, primary_address))
        return None

    monkeypatch.delenv("PYBLUEHOST_TEST_TRANSPORT_PEER", raising=False)
    monkeypatch.setattr(
        project_conftest,
        "find_second_usb_adapter",
        fake_find_second_usb_adapter,
    )

    assert project_conftest._resolve_peer_spec(_Config(), "usb:vendor=intel") is None
    assert seen == [(None, None)]
