"""Transport selection helper used by tests/conftest.py.

Re-exports the shared spec parser from :mod:`pybluehost.transport.spec` and
adds USB enumeration helpers (autodetect, find peer adapter) that are only
needed by the test session, not by the production CLI.
"""
from __future__ import annotations

from pybluehost.transport.spec import (
    InvalidSpec,
    SameFamilyError,
    enforce_same_family,
    family_of,
    parse_spec,
    uart_spec_port_baud,
    usb_spec_bus_address,
    usb_spec_identity,
    vendor_of,
)

__all__ = [
    "InvalidSpec",
    "SameFamilyError",
    "autodetect_primary",
    "autodetect_usb_candidates",
    "enforce_same_family",
    "family_of",
    "find_second_usb_adapter",
    "parse_spec",
    "uart_spec_port_baud",
    "usb_spec_bus_address",
    "vendor_of",
]


def autodetect_primary() -> str:
    """Return a usb:... spec for the first detected adapter, or 'virtual'."""
    candidates = autodetect_usb_candidates()
    if not candidates:
        return "virtual"
    return candidates[0]


def autodetect_usb_candidates() -> list[str]:
    """Return every detected USB adapter as a concrete transport spec."""
    from pybluehost.transport.usb import USBTransport

    try:
        candidates = USBTransport.list_devices()
    except Exception as exc:
        raise InvalidSpec("Unable to enumerate USB transports") from exc
    return [_usb_candidate_spec(candidate) for candidate in candidates]


def find_second_usb_adapter(
    primary_spec: str,
) -> str | None:
    """Return a usb:... spec for a USB adapter other than the primary, or None."""
    vid, pid, _serial, occurrence = usb_spec_identity(primary_spec)
    if vid is None or pid is None or occurrence is None:
        return None

    from pybluehost.transport.usb import USBTransport

    for cand in USBTransport.list_devices():
        spec = _usb_candidate_spec(cand)
        if spec == primary_spec:
            continue
        return spec
    return None


def _usb_candidate_spec(candidate: object) -> str:
    name = getattr(candidate, "transport_name", None)
    if isinstance(name, str) and name:
        return name
    raise InvalidSpec("USB candidate does not expose a canonical transport name")
