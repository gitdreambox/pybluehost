"""Session-scoped transport-selection fixtures."""
from __future__ import annotations

import subprocess
import sys
import textwrap
import uuid
import importlib.util
from dataclasses import dataclass
from pathlib import Path

import pytest
from _pytest.outcomes import Exit


ROOT = Path(__file__).parents[2]
INLINE_PYTEST_TIMEOUT_SECONDS = 30
_CONFTEST_SPEC = importlib.util.spec_from_file_location(
    "project_conftest_for_session_fixture_tests",
    ROOT / "tests" / "conftest.py",
)
assert _CONFTEST_SPEC is not None
assert _CONFTEST_SPEC.loader is not None
project_conftest = importlib.util.module_from_spec(_CONFTEST_SPEC)
_CONFTEST_SPEC.loader.exec_module(project_conftest)


@dataclass(frozen=True)
class _Candidate:
    vendor: str
    bus: int
    address: int


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
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_file),
        "-q",
        "--no-header",
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


def test_cross_family_peer_exits_during_collection_without_peer_fixture():
    body = """
    def test_dummy():
        assert True
    """
    r = _run_inline(
        body,
        "--transport=virtual",
        "--transport-peer=usb",
    )
    out = r.stdout + r.stderr
    assert r.returncode == 4
    assert "Peer transport must match primary family" in out


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


def test_autodetected_usb_falls_back_to_virtual_when_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYBLUEHOST_TEST_TRANSPORT", raising=False)
    monkeypatch.setattr(
        project_conftest,
        "autodetect_primary",
        lambda: "usb:vendor=intel,bus=1,address=4",
    )
    monkeypatch.setattr(
        project_conftest,
        "_probe_autodetected_spec_usable",
        lambda spec: False,
    )

    assert project_conftest._resolve_primary_spec(_Config()) == "virtual"


def test_autodetected_usb_keeps_hardware_when_probe_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYBLUEHOST_TEST_TRANSPORT", raising=False)
    monkeypatch.setattr(
        project_conftest,
        "autodetect_primary",
        lambda: "usb:vendor=intel,bus=1,address=4",
    )
    monkeypatch.setattr(
        project_conftest,
        "_probe_autodetected_spec_usable",
        lambda spec: True,
    )

    assert (
        project_conftest._resolve_primary_spec(_Config())
        == "usb:vendor=intel,bus=1,address=4"
    )


def test_explicit_usb_primary_normalizes_to_concrete_adapter_and_peer_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pybluehost.transport.usb import USBTransport

    candidates = [
        _Candidate(vendor="intel", bus=1, address=4),
        _Candidate(vendor="realtek", bus=2, address=5),
    ]
    seen_auto_detect: list[tuple[str | None, int | None, int | None]] = []

    def fake_auto_detect(
        *,
        vendor: str | None = None,
        bus: int | None = None,
        address: int | None = None,
        **_kwargs: object,
    ) -> object:
        seen_auto_detect.append((vendor, bus, address))
        return object()

    monkeypatch.setattr(USBTransport, "auto_detect", fake_auto_detect)
    monkeypatch.setattr(USBTransport, "list_devices", classmethod(lambda cls: candidates))
    monkeypatch.delenv("PYBLUEHOST_TEST_TRANSPORT_PEER", raising=False)

    config = _Config(transport="usb")
    primary = project_conftest._resolve_primary_spec(config)
    peer = project_conftest._resolve_peer_spec(config, primary)

    assert primary == "usb:vendor=intel,bus=1,address=4"
    assert peer == "usb:vendor=realtek,bus=2,address=5"
    assert seen_auto_detect == [(None, None, None)]


def test_vendor_filtered_usb_primary_normalizes_to_matching_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pybluehost.transport.usb import USBTransport

    candidates = [
        _Candidate(vendor="realtek", bus=1, address=4),
        _Candidate(vendor="intel", bus=2, address=5),
    ]
    seen_auto_detect: list[tuple[str | None, int | None, int | None]] = []

    def fake_auto_detect(
        *,
        vendor: str | None = None,
        bus: int | None = None,
        address: int | None = None,
        **_kwargs: object,
    ) -> object:
        seen_auto_detect.append((vendor, bus, address))
        return object()

    monkeypatch.setattr(USBTransport, "auto_detect", fake_auto_detect)
    monkeypatch.setattr(USBTransport, "list_devices", classmethod(lambda cls: candidates))

    primary = project_conftest._resolve_primary_spec(_Config(transport="usb:vendor=intel"))

    assert primary == "usb:vendor=intel,bus=2,address=5"
    assert seen_auto_detect == [("intel", None, None)]


def test_generic_usb_fallback_keeps_original_when_no_known_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pybluehost.transport.usb import USBTransport

    monkeypatch.setattr(USBTransport, "auto_detect", lambda **_kwargs: object())
    monkeypatch.setattr(USBTransport, "list_devices", classmethod(lambda cls: []))

    assert project_conftest._resolve_primary_spec(_Config(transport="usb")) == "usb"


@pytest.mark.asyncio
async def test_build_stack_from_spec_rejects_invalid_uart_baudrate() -> None:
    with pytest.raises(project_conftest.InvalidSpec) as excinfo:
        await project_conftest._build_stack_from_spec("uart:/dev/ttyUSB0@fast")

    assert "Invalid UART baudrate" in str(excinfo.value)
    assert "fast" in str(excinfo.value)


@pytest.mark.asyncio
async def test_stack_fixture_exits_with_clear_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_build(_spec: str) -> object:
        raise RuntimeError("open failed")

    monkeypatch.setattr(project_conftest, "_build_stack_from_spec", fake_build)

    gen = project_conftest.stack.__wrapped__("usb:vendor=intel")
    with pytest.raises(Exit) as excinfo:
        await gen.__anext__()

    assert excinfo.value.returncode == 4
    assert "Transport 'usb:vendor=intel' unavailable: open failed" in str(
        excinfo.value
    )


@pytest.mark.asyncio
async def test_peer_stack_fixture_skips_with_clear_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_build(_spec: str) -> object:
        raise RuntimeError("peer open failed")

    monkeypatch.setattr(project_conftest, "_build_stack_from_spec", fake_build)

    gen = project_conftest.peer_stack.__wrapped__("usb:vendor=realtek")
    with pytest.raises(pytest.skip.Exception) as excinfo:
        await gen.__anext__()

    assert "peer_stack: transport 'usb:vendor=realtek' unavailable" in str(
        excinfo.value
    )
    assert "peer open failed" in str(excinfo.value)
