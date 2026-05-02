"""Session-level transport resolution for the pytest test infrastructure.

Resolves ``--transport`` / ``--transport-peer`` / env vars / autodetect into a
concrete transport spec, with usability probing for autodetected hardware so
that an enumerable-but-unusable adapter (e.g. Intel BE200 with bthusb driver)
falls back to the next candidate or to ``virtual``. Caches the resolution on
``pytest.Config`` so each session resolves only once.

Pure helpers — no pytest hook implementations live here. The hooks in
``tests/conftest.py`` call into this module.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from tests._fallback_tracker import TRACKER
from tests._transport_select import (
    InvalidSpec,
    SameFamilyError,
    autodetect_usb_candidates,
    enforce_same_family,
    family_of,
    find_second_usb_adapter,
    parse_spec,
    uart_spec_port_baud,
    usb_spec_bus_address,
)

_PRIMARY_CACHE_ATTR = "_pybluehost_selected_transport_spec"
_PEER_CACHE_ATTR = "_pybluehost_selected_peer_spec"
_CACHE_MISSING = object()


def resolve_primary_spec(config: pytest.Config) -> str:
    """Resolve primary transport spec from --transport, env, or autodetect.

    Caches the result on the config so subsequent calls return the same spec
    without re-probing hardware. Calls ``pytest.exit(returncode=4)`` for
    invalid specs or unavailable explicit hardware.
    """
    cached = getattr(config, _PRIMARY_CACHE_ATTR, _CACHE_MISSING)
    if cached is not _CACHE_MISSING:
        return cached

    spec = config.getoption("--transport")
    if spec is None:
        spec = os.environ.get("PYBLUEHOST_TEST_TRANSPORT")

    autodetected = False
    hardware_probe_failed = False
    if spec is None:
        try:
            usb_candidates = autodetect_usb_candidates()
        except InvalidSpec as exc:
            pytest.exit(f"Invalid transport spec from autodetect: {exc}", returncode=4)
        autodetected = True
        spec = _first_usable_autodetected_spec(usb_candidates)
        hardware_probe_failed = bool(usb_candidates) and spec == "virtual"

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
        TRACKER.mark_fallback()
        if hardware_probe_failed:
            TRACKER.mark_unusable_hardware()

    setattr(config, _PRIMARY_CACHE_ATTR, spec)
    return spec


def resolve_peer_spec(config: pytest.Config, primary: str) -> str | None:
    """Resolve peer spec; ``None`` means dependent tests are skipped."""
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


async def build_stack_from_spec(spec: str):
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


def _first_usable_autodetected_spec(candidates: list[str]) -> str:
    """Return first usable autodetected USB spec, or ``virtual`` if none works."""
    for candidate in candidates:
        if _probe_autodetected_spec_usable(candidate):
            return candidate
    return "virtual"


def _probe_autodetected_spec_usable(spec: str) -> bool:
    """Return whether an autodetected hardware transport can initialize a Stack."""
    try:
        return asyncio.run(_probe_stack_open_close(spec))
    except RuntimeError:
        return False


async def _probe_stack_open_close(spec: str) -> bool:
    stack = None
    try:
        stack = await build_stack_from_spec(spec)
    except Exception:
        return False
    finally:
        if stack is not None:
            await stack.close()
    return True


def _verify_spec_available(spec: str) -> str | None:
    """Raise ``RuntimeError`` if the explicit hardware spec is unavailable.

    Returns a normalized concrete spec when USB enumeration can identify the
    selected adapter. Generic USB fallback devices may lack chip/location
    metadata; in that case the original spec is kept by returning ``None``.
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
