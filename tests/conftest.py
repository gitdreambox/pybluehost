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
        family_of_spec = family_of(spec)
    except InvalidSpec as exc:
        pytest.exit(f"Invalid transport spec: {spec!r} - {exc}", returncode=4)

    if not autodetected and family_of_spec in {"usb", "uart"}:
        try:
            verified_spec = _verify_spec_available(spec)
        except RuntimeError as exc:
            pytest.exit(f"Transport {spec!r} unavailable: {exc}", returncode=4)
        if verified_spec is not None:
            spec = verified_spec

    if autodetected and spec == "virtual":
        _FALLBACK_TRACKER.mark_fallback()

    setattr(config, _PRIMARY_CACHE_ATTR, spec)
    return spec


def _verify_spec_available(spec: str) -> str | None:
    """Raise RuntimeError if the explicit hardware spec is unavailable.

    Returns a normalized concrete spec when USB enumeration can identify the
    selected adapter. Generic USB fallback devices may lack chip/location
    metadata; in that case the original spec is kept by returning None.
    """
    family, params = parse_spec(spec)
    if family == "usb":
        from pybluehost.transport.usb import USBTransport

        bus, address = usb_spec_bus_address(spec)
        vendor = params.get("vendor")
        try:
            USBTransport.auto_detect(vendor=vendor, bus=bus, address=address)
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc
        return _known_usb_candidate_spec(
            USBTransport.list_devices(),
            vendor=vendor,
            bus=bus,
            address=address,
        )
    elif family == "uart":
        port = params["raw"].split("@", 1)[0]
        if not os.path.exists(port):
            raise RuntimeError(f"UART port not found: {port}")
    return None


def _known_usb_candidate_spec(
    candidates: list[object],
    *,
    vendor: str | None,
    bus: int | None,
    address: int | None,
) -> str | None:
    """Return the first known USB candidate matching the selected filters."""
    for candidate in candidates:
        if vendor is not None and candidate.vendor != vendor:
            continue
        if bus is not None and candidate.bus != bus:
            continue
        if address is not None and candidate.address != address:
            continue
        return (
            f"usb:vendor={candidate.vendor},"
            f"bus={candidate.bus},"
            f"address={candidate.address}"
        )
    return None


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


async def _build_stack_from_spec(spec: str):
    """Construct a powered Stack matching the selected transport spec."""
    from pybluehost.stack import Stack

    family, params = parse_spec(spec)
    if family == "virtual":
        return await Stack.virtual()
    if family == "usb":
        bus, address = usb_spec_bus_address(spec)
        return await Stack.from_usb(
            vendor=params.get("vendor"),
            bus=bus,
            address=address,
        )
    if family == "uart":
        raw = params["raw"]
        if "@" in raw:
            port, baudrate_s = raw.rsplit("@", 1)
            return await Stack.from_uart(port=port, baudrate=int(baudrate_s))
        return await Stack.from_uart(port=raw)
    raise InvalidSpec(f"Cannot build stack from spec: {spec!r}")


@pytest.fixture
async def stack(selected_transport_spec: str):
    """Full Stack on the selected transport. Built and torn down per test."""
    s = await _build_stack_from_spec(selected_transport_spec)
    if _FALLBACK_TRACKER.is_fallback():
        _FALLBACK_TRACKER.increment()
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
    s = await _build_stack_from_spec(selected_peer_spec)
    try:
        yield s
    finally:
        await s.close()
