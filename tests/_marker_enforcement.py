"""Validation + skip-decision logic for ``real_hardware_only`` and ``virtual_only`` markers.

Pure helpers — the pytest hook in ``tests/conftest.py`` collects markers and
calls into this module to decide whether to add a ``pytest.mark.skip`` to the
item. Splitting this out keeps ``conftest.py`` focused on pytest plumbing and
makes the marker rules individually unit-testable.
"""
from __future__ import annotations

import pytest

_VALID_TRANSPORTS = {"usb", "uart"}


def real_hw_skip_reason(
    marker: pytest.Mark,
    fam: str,
    current_vendor: str | None,
) -> str | None:
    """Return a skip reason string, or ``None`` if the test should run.

    ``marker`` is the ``real_hardware_only`` mark applied to the test item.
    ``fam`` is the resolved primary transport family (``virtual``/``usb``/``uart``).
    ``current_vendor`` is the resolved vendor for usb-family specs (else ``None``).
    """
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
            if vendor not in _known_usb_vendors():
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


def virtual_only_skip_reason(fam: str) -> str | None:
    """Return a skip reason when a ``virtual_only`` test is selected off virtual."""
    if fam == "virtual":
        return None
    return "deterministic test, runs only on virtual controller"


def _marker_values(value: object) -> tuple[object, ...]:
    """Normalize scalar and sequence marker kwargs for validation."""
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list)):
        return tuple(value)
    return (value,)


def _known_usb_vendors() -> frozenset[str]:
    from pybluehost.transport.usb import known_usb_vendors

    return known_usb_vendors()
