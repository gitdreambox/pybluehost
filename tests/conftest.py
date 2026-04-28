"""Shared pytest fixtures and hooks for PyBlueHost test suite."""
from __future__ import annotations

import asyncio
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
    uart_spec_port_baud,
    usb_spec_bus_address,
    vendor_of,
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
    config.addinivalue_line(
        "markers",
        "hardware: legacy real USB Bluetooth adapter marker; TODO remove after Tasks 19-20",
    )
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

    if autodetected and family_of_spec in {"usb", "uart"}:
        if not _probe_autodetected_spec_usable(spec):
            spec = "virtual"
            family_of_spec = "virtual"

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


def _probe_autodetected_spec_usable(spec: str) -> bool:
    """Return whether an autodetected hardware transport can initialize a Stack."""
    try:
        return asyncio.run(_probe_stack_open_close(spec))
    except RuntimeError:
        return False


async def _probe_stack_open_close(spec: str) -> bool:
    stack = None
    try:
        stack = await _build_stack_from_spec(spec)
    except Exception:
        return False
    finally:
        if stack is not None:
            await stack.close()
    return True


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
        port, _baudrate = uart_spec_port_baud(spec)
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


def _header_source_label(config: pytest.Config) -> str:
    """Return the source label for the selected transport header."""
    if config.getoption("--transport") is not None:
        return "explicit"
    if os.environ.get("PYBLUEHOST_TEST_TRANSPORT") is not None:
        return "explicit"
    if _FALLBACK_TRACKER.is_fallback():
        return "auto-detected — no hardware found"
    return "auto-detected"


def _peer_header_source_label(config: pytest.Config) -> str:
    """Return the source label for the selected peer transport header."""
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

    primary = _resolve_primary_spec(config)
    label = _header_source_label(config)
    lines = [f"[pybluehost-tests] transport: {_format_header_spec(primary)} [{label}]"]

    peer = _resolve_peer_spec(config, primary)
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
    if not _FALLBACK_TRACKER.is_fallback():
        return

    n = _FALLBACK_TRACKER.count
    terminalreporter.write_sep("=", "pybluehost transport summary")
    terminalreporter.write_line(
        f"⚠  Auto-detect found no hardware. {n} tests ran on virtual."
    )
    terminalreporter.write_line(
        "   Set --transport=usb (or PYBLUEHOST_TEST_TRANSPORT=usb) to validate"
    )
    terminalreporter.write_line("   against real hardware.")
    terminalreporter.write_sep("=")


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
        port, baudrate = uart_spec_port_baud(spec)
        return await Stack.from_uart(port=port, baudrate=baudrate)
    raise InvalidSpec(f"Cannot build stack from spec: {spec!r}")


@pytest.fixture
async def stack(selected_transport_spec: str):
    """Full Stack on the selected transport. Built and torn down per test."""
    try:
        s = await _build_stack_from_spec(selected_transport_spec)
    except Exception as exc:
        pytest.exit(
            f"Transport {selected_transport_spec!r} unavailable: {exc}",
            returncode=4,
        )
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
    try:
        s = await _build_stack_from_spec(selected_peer_spec)
    except Exception as exc:
        pytest.skip(f"peer_stack: transport {selected_peer_spec!r} unavailable: {exc}")
    try:
        yield s
    finally:
        await s.close()


_VALID_TRANSPORTS = {"usb", "uart"}
_VALID_VENDORS = {"intel", "realtek", "csr"}


def _marker_values(value: object) -> tuple[object, ...]:
    """Normalize scalar and sequence marker kwargs for validation."""
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list)):
        return tuple(value)
    return (value,)


def _real_hw_skip_reason(
    marker: pytest.Mark,
    fam: str,
    current_vendor: str | None,
) -> str | None:
    """Return a skip reason string, or None if the test should run."""
    required_transport = marker.kwargs.get("transport")
    required_vendor = marker.kwargs.get("vendor")

    if required_transport is not None and required_transport not in _VALID_TRANSPORTS:
        return (
            "real_hardware_only marker error: transport must be 'usb' or 'uart', "
            f"got {required_transport!r}"
        )

    if required_vendor is not None:
        vendors = _marker_values(required_vendor)
        for vendor in vendors:
            if vendor not in _VALID_VENDORS:
                return f"real_hardware_only marker error: unsupported vendor {vendor!r}"
        if required_transport != "usb":
            return "real_hardware_only marker error: vendor= requires transport='usb'"

    if fam == "virtual":
        return "requires real hardware (use --transport=usb)"
    if required_transport is not None and fam != required_transport:
        return f"requires {required_transport!r} transport, got {fam!r}"
    if required_vendor is not None:
        vendors = _marker_values(required_vendor)
        if current_vendor not in vendors:
            return f"requires vendor in {vendors}, got {current_vendor!r}"
    return None


def _virtual_only_skip_reason(fam: str) -> str | None:
    """Return a skip reason when a virtual_only test is selected off virtual."""
    if fam == "virtual":
        return None
    return "deterministic test, runs only on virtual controller"


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Enforce real_hardware_only(transport=, vendor=) and virtual_only markers."""
    spec = _resolve_primary_spec(config)
    _resolve_peer_spec(config, spec)
    fam = family_of(spec)
    current_vendor = vendor_of(spec)

    for item in items:
        marker = item.get_closest_marker("real_hardware_only")
        if marker is not None:
            reason = _real_hw_skip_reason(marker, fam, current_vendor)
            if reason is not None:
                item.add_marker(pytest.mark.skip(reason=reason))

        if item.get_closest_marker("virtual_only") is not None:
            reason = _virtual_only_skip_reason(fam)
            if reason is not None:
                item.add_marker(pytest.mark.skip(reason=reason))
