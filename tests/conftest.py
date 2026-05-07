"""Shared pytest fixtures and hooks for the PyBlueHost test suite.

This file is intentionally thin: it registers CLI options + markers, exposes
session/test fixtures, and wires up the report header / terminal summary /
collection modifier hooks. The actual logic lives in three sibling modules:

* :mod:`pybluehost.transport.spec` — spec string parsing (shared with the CLI).
* :mod:`tests._transport_resolve` — session-scoped resolution + autodetect.
* :mod:`tests._marker_enforcement` — ``real_hardware_only`` / ``virtual_only`` rules.
"""
from __future__ import annotations

import logging
import os

import pytest

from pybluehost.transport.spec import format_usb_candidate_spec

from tests._fallback_tracker import TRACKER
from tests._marker_enforcement import (
    real_hw_skip_reason,
    virtual_only_skip_reason,
)
from tests._transport_resolve import (
    build_stack_from_spec,
    resolve_peer_spec,
    resolve_primary_spec,
)
from tests._transport_select import (
    family_of,
    parse_spec,
    usb_spec_bus_address,
    vendor_of,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI option registration + diagnostics
# ---------------------------------------------------------------------------

def pytest_addoption(parser: pytest.Parser) -> None:
    """Register transport-selection CLI options."""
    parser.addoption(
        "--transport",
        action="store",
        default=None,
        help="Primary transport spec: virtual | usb[:vendor=...,bus=N,address=M] | uart:/dev/...",
    )
    parser.addoption(
        "--transport-peer",
        action="store",
        default=None,
        help="Peer transport spec (only affects peer_stack fixture). Same family as --transport.",
    )
    parser.addoption(
        "--list-transports",
        action="store_true",
        default=False,
        help="Print every detected Bluetooth transport adapter, then exit.",
    )

    # pytest's built-in ``debugging`` plugin registers ``--trace`` as a
    # boolean PDB shortcut. We want ``--trace=<spec>`` for HCI / protocol
    # layer logging. To avoid the collision we register under a pytest-only
    # name; the equivalent CLI option (``pybluehost --trace=...``) is
    # unaffected because the CLI runs in its own argparse parser.
    parser.addoption(
        "--pybluehost-trace",
        action="store",
        default=None,
        help="Trace spec for HCI / protocol layer logging (e.g. 'hci=debug,l2cap'). "
             "Same syntax as pybluehost CLI's --trace.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers and handle ``--list-transports`` diagnostics."""
    # Markers are also declared in pyproject.toml; this hook is for programmatic
    # registration if the toml is not loaded.
    config.addinivalue_line("markers", "unit: isolated unit tests (no real hardware, no transport)")
    config.addinivalue_line("markers", "integration: layered tests using stack fixture (transport-bound)")
    config.addinivalue_line("markers", "e2e: full-stack tests (transport-bound)")
    config.addinivalue_line("markers", "btsnoop: btsnoop file replay tests")
    config.addinivalue_line(
        "markers",
        "real_hardware_only(transport=..., vendor=...): requires real hardware",
    )
    config.addinivalue_line(
        "markers",
        "virtual_only: deterministic test, only valid on virtual controller",
    )
    config.addinivalue_line("markers", "slow: tests taking >5s")

    from pybluehost.core.trace_control import (
        InvalidTraceSpec,
        apply_logging_levels,
        parse_trace_spec,
    )
    trace_str = config.getoption("--pybluehost-trace") or os.environ.get("PYBLUEHOST_TRACE")
    try:
        trace_spec = parse_trace_spec(trace_str)
    except InvalidTraceSpec as exc:
        pytest.exit(f"Invalid --trace value: {exc}", returncode=4)
    apply_logging_levels(trace_spec)
    config._pybluehost_trace_spec = trace_spec

    if config.getoption("--list-transports"):
        from pybluehost.transport.usb import USBTransport

        candidates = USBTransport.list_devices()
        if not candidates:
            logger.warning("[pybluehost-tests] No Bluetooth USB adapters detected.")
        else:
            logger.warning("[pybluehost-tests] Detected Bluetooth USB adapters:")
            for candidate in candidates:
                spec = format_usb_candidate_spec(
                    vendor=candidate.vendor,
                    bus=candidate.bus,
                    address=candidate.address,
                )
                logger.warning(
                    "  %-8s %-10s bus=%s address=%s  (%s)",
                    candidate.vendor,
                    candidate.name,
                    candidate.bus,
                    candidate.address,
                    spec,
                )
        pytest.exit("--list-transports done", returncode=0)


# ---------------------------------------------------------------------------
# Report header + terminal summary
# ---------------------------------------------------------------------------

def _header_source_label(config: pytest.Config) -> str:
    if config.getoption("--transport") is not None:
        return "explicit"
    if os.environ.get("PYBLUEHOST_TEST_TRANSPORT") is not None:
        return "explicit"
    if TRACKER.is_fallback():
        if TRACKER.has_unusable_hardware():
            return "auto-detected — hardware unusable"
        return "auto-detected — no hardware found"
    return "auto-detected"


def _peer_header_source_label(config: pytest.Config) -> str:
    if config.getoption("--transport-peer") is not None:
        return "explicit"
    if os.environ.get("PYBLUEHOST_TEST_TRANSPORT_PEER") is not None:
        return "explicit"
    return "auto-detected"


def _format_header_spec(spec: str) -> str:
    """Return a readable transport spec for pytest's report header."""
    family, _params = parse_spec(spec)
    if family != "usb":
        return spec

    bus, address = usb_spec_bus_address(spec)
    if bus is None or address is None:
        return spec

    from pybluehost.transport.usb import USBTransport

    for candidate in USBTransport.list_devices():
        if candidate.bus == bus and candidate.address == address:
            name = getattr(candidate, "name", "") or candidate.vendor.title()
            return f"usb ({name}, bus={bus} address={address})"
    return spec


def pytest_report_header(config: pytest.Config) -> list[str]:
    """Print selected PyBlueHost transport information in pytest's header."""
    if config.getoption("--list-transports"):
        return []

    primary = resolve_primary_spec(config)
    label = _header_source_label(config)
    lines = [f"[pybluehost-tests] transport: {_format_header_spec(primary)} [{label}]"]

    peer = resolve_peer_spec(config, primary)
    if peer is not None and (
        peer != primary or config.getoption("--transport-peer") is not None
    ):
        peer_label = _peer_header_source_label(config)
        lines.append(
            f"[pybluehost-tests] peer transport: "
            f"{_format_header_spec(peer)} [{peer_label}]"
        )

    return lines


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """Warn when autodetect fell back to virtual for tests using stack."""
    if not TRACKER.is_fallback():
        return

    n = TRACKER.count
    terminalreporter.write_sep("=", "pybluehost transport summary")
    if TRACKER.has_unusable_hardware():
        terminalreporter.write_line(
            f"⚠  Auto-detect found no usable hardware. {n} tests ran on virtual."
        )
    else:
        terminalreporter.write_line(
            f"⚠  Auto-detect found no hardware. {n} tests ran on virtual."
        )
    terminalreporter.write_line(
        "   Set --transport=usb (or PYBLUEHOST_TEST_TRANSPORT=usb) to validate"
    )
    terminalreporter.write_line("   against real hardware.")
    terminalreporter.write_sep("=")


# ---------------------------------------------------------------------------
# Session + test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def selected_transport_spec(request: pytest.FixtureRequest) -> str:
    """Session-level primary transport spec selected for this test run."""
    return resolve_primary_spec(request.config)


@pytest.fixture(scope="session")
def selected_peer_spec(
    selected_transport_spec: str,
    request: pytest.FixtureRequest,
) -> str | None:
    """Session-level peer transport spec, or ``None`` when no peer is available."""
    return resolve_peer_spec(request.config, selected_transport_spec)


@pytest.fixture(scope="session")
def transport_mode(selected_transport_spec: str) -> str:
    """Selected transport family: ``virtual``, ``usb``, or ``uart``."""
    return family_of(selected_transport_spec)


@pytest.fixture
async def stack(selected_transport_spec: str, request: pytest.FixtureRequest):
    """Full Stack on the selected transport. Built and torn down per test."""
    try:
        s = await build_stack_from_spec(selected_transport_spec)
    except Exception as exc:
        pytest.exit(
            f"Transport {selected_transport_spec!r} unavailable: {exc}",
            returncode=4,
        )
    if TRACKER.is_fallback():
        TRACKER.increment()
    spec = getattr(request.config, "_pybluehost_trace_spec", None)
    if spec is not None and not spec.is_empty():
        from pybluehost.core.trace_control import attach_console_sink
        attach_console_sink(spec, s.trace)
    try:
        yield s
    finally:
        await s.close()


@pytest.fixture
async def peer_stack(selected_peer_spec: str | None):
    """Second Stack. Skips the test when no peer transport is available."""
    if selected_peer_spec is None:
        pytest.skip(
            "peer_stack: no second adapter available; pass --transport-peer=..."
        )
    try:
        s = await build_stack_from_spec(selected_peer_spec)
    except Exception as exc:
        pytest.skip(f"peer_stack: transport {selected_peer_spec!r} unavailable: {exc}")
    try:
        yield s
    finally:
        await s.close()


# ---------------------------------------------------------------------------
# Marker enforcement
# ---------------------------------------------------------------------------

def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Enforce ``real_hardware_only(transport=, vendor=)`` and ``virtual_only`` markers."""
    spec = resolve_primary_spec(config)
    resolve_peer_spec(config, spec)
    fam = family_of(spec)
    current_vendor = vendor_of(spec)

    for item in items:
        marker = item.get_closest_marker("real_hardware_only")
        if marker is not None:
            reason = real_hw_skip_reason(marker, fam, current_vendor)
            if reason is not None:
                item.add_marker(pytest.mark.skip(reason=reason))

        if item.get_closest_marker("virtual_only") is not None:
            reason = virtual_only_skip_reason(fam)
            if reason is not None:
                item.add_marker(pytest.mark.skip(reason=reason))
