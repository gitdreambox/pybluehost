"""Shared pytest fixtures and hooks for PyBlueHost test suite."""
from __future__ import annotations

import os

import pytest

from tests._fallback_tracker import FallbackTracker
from tests._transport_select import (
    InvalidSpec,
    SameFamilyError,
    autodetect_primary,
    enforce_same_family,
    family_of,
    find_second_usb_adapter,
    parse_spec,
    usb_spec_bus_address,
)


_FALLBACK_TRACKER = FallbackTracker()
_PRIMARY_CACHE_ATTR = "_pybluehost_selected_transport_spec"
_PEER_CACHE_ATTR = "_pybluehost_selected_peer_spec"
_CACHE_MISSING = object()


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


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers and handle transport diagnostics."""
    # Markers are already declared in pyproject.toml; this hook is for
    # programmatic registration if pyproject.toml is not loaded.
    config.addinivalue_line("markers", "unit: isolated unit tests (no real hardware, no network)")
    config.addinivalue_line("markers", "integration: multi-layer tests using VirtualController + Loopback")
    config.addinivalue_line("markers", "e2e: full-stack Loopback double-stack tests")
    config.addinivalue_line("markers", "btsnoop: btsnoop file replay tests")
    config.addinivalue_line("markers", "hardware: real USB Bluetooth adapter required (skipped in CI)")
    config.addinivalue_line("markers", "slow: tests taking >5s")

    if config.getoption("--list-transports"):
        from pybluehost.transport.usb import USBTransport

        candidates = USBTransport.list_devices()
        if not candidates:
            print("[pybluehost-tests] No Bluetooth USB adapters detected.")
        else:
            print("[pybluehost-tests] Detected Bluetooth USB adapters:")
            for candidate in candidates:
                spec = (
                    f"usb:vendor={candidate.vendor},"
                    f"bus={candidate.bus},"
                    f"address={candidate.address}"
                )
                print(
                    f"  {candidate.vendor:8s} {candidate.name:10s} "
                    f"bus={candidate.bus} address={candidate.address}  ({spec})"
                )
        pytest.exit("--list-transports done", returncode=0)


def _resolve_primary_spec(config: pytest.Config) -> str:
    """Resolve primary transport spec from --transport, env, or autodetect."""
    cached = getattr(config, _PRIMARY_CACHE_ATTR, _CACHE_MISSING)
    if cached is not _CACHE_MISSING:
        return cached

    spec = config.getoption("--transport")
    if spec is None:
        spec = os.environ.get("PYBLUEHOST_TEST_TRANSPORT")

    autodetected = False
    if spec is None:
        try:
            spec = autodetect_primary()
        except InvalidSpec as exc:
            pytest.exit(f"Invalid transport spec from autodetect: {exc}", returncode=4)
        autodetected = True

    try:
        parse_spec(spec)
    except InvalidSpec as exc:
        pytest.exit(f"Invalid transport spec: {spec!r} - {exc}", returncode=4)

    if not autodetected and family_of(spec) in {"usb", "uart"}:
        try:
            _verify_spec_available(spec)
        except RuntimeError as exc:
            pytest.exit(f"Transport {spec!r} unavailable: {exc}", returncode=4)

    if autodetected and spec == "virtual":
        _FALLBACK_TRACKER.mark_fallback()

    setattr(config, _PRIMARY_CACHE_ATTR, spec)
    return spec


def _verify_spec_available(spec: str) -> None:
    """Raise RuntimeError if the explicit hardware spec is unavailable."""
    family, params = parse_spec(spec)
    if family == "usb":
        from pybluehost.transport.usb import USBTransport

        bus, address = usb_spec_bus_address(spec)
        vendor = params.get("vendor")
        try:
            USBTransport.auto_detect(vendor=vendor, bus=bus, address=address)
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc
    elif family == "uart":
        port = params["raw"].split("@", 1)[0]
        if not os.path.exists(port):
            raise RuntimeError(f"UART port not found: {port}")


def _resolve_peer_spec(config: pytest.Config, primary: str) -> str | None:
    """Resolve peer spec; None means dependent tests are skipped."""
    cached = getattr(config, _PEER_CACHE_ATTR, _CACHE_MISSING)
    if cached is not _CACHE_MISSING:
        return cached

    peer = config.getoption("--transport-peer")
    if peer is None:
        peer = os.environ.get("PYBLUEHOST_TEST_TRANSPORT_PEER")

    if peer is not None:
        try:
            parse_spec(peer)
            enforce_same_family(primary, peer)
        except (InvalidSpec, SameFamilyError) as exc:
            pytest.exit(str(exc), returncode=4)
        setattr(config, _PEER_CACHE_ATTR, peer)
        return peer

    fam = family_of(primary)
    if fam == "virtual":
        peer = "virtual"
    elif fam == "usb":
        bus, address = usb_spec_bus_address(primary)
        peer = find_second_usb_adapter(primary_bus=bus, primary_address=address)
    else:
        peer = None

    setattr(config, _PEER_CACHE_ATTR, peer)
    return peer


@pytest.fixture(scope="session")
def selected_transport_spec(request: pytest.FixtureRequest) -> str:
    """Session-level primary transport spec selected for this test run."""
    return _resolve_primary_spec(request.config)


@pytest.fixture(scope="session")
def selected_peer_spec(
    selected_transport_spec: str,
    request: pytest.FixtureRequest,
) -> str | None:
    """Session-level peer transport spec, or None when no peer is available."""
    return _resolve_peer_spec(request.config, selected_transport_spec)


@pytest.fixture(scope="session")
def transport_mode(selected_transport_spec: str) -> str:
    """Selected transport family: virtual, usb, or uart."""
    return family_of(selected_transport_spec)
