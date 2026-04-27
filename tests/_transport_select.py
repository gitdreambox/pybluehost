"""Transport selection helper used by tests/conftest.py.

Resolves a transport spec from CLI/env/autodetect and provides supporting
helpers for peer adapter discovery and family checks. Pure helpers: no pytest
dependency, no I/O beyond USB enumeration.
"""
from __future__ import annotations

_VALID_VENDORS = {"intel", "realtek", "csr"}
_USB_KEYS = {"vendor", "bus", "address"}


class InvalidSpec(ValueError):
    """Raised when a transport spec string is malformed."""


class SameFamilyError(ValueError):
    """Raised when peer transport family does not match primary."""


def family_of(spec: str) -> str:
    """Return 'virtual' / 'usb' / 'uart' for any valid spec."""
    family, _params = parse_spec(spec)
    return family


def parse_spec(spec: str) -> tuple[str, dict[str, str]]:
    """Validate spec syntax and return (family, key/value dict).

    Raises InvalidSpec for malformed input. Does not open any device.
    """
    if not spec or not spec.strip():
        raise InvalidSpec("Transport spec is empty")

    if spec == "virtual":
        return ("virtual", {})
    if spec == "usb":
        return ("usb", {})
    if spec.startswith("usb:"):
        return ("usb", _parse_usb_params(spec[4:]))
    if spec.startswith("uart:"):
        rest = spec[5:].strip()
        if not rest:
            raise InvalidSpec("UART spec missing port")
        return ("uart", {"raw": rest})
    raise InvalidSpec(f"Unknown transport spec: {spec!r}")


def autodetect_primary() -> str:
    """Return a usb:... spec for the first detected adapter, or 'virtual'."""
    from pybluehost.transport.usb import USBTransport

    try:
        candidates = USBTransport.list_devices()
    except Exception as exc:
        raise InvalidSpec("Unable to enumerate USB transports") from exc
    if not candidates:
        return "virtual"
    return _usb_candidate_spec(candidates[0])


def find_second_usb_adapter(
    primary_bus: int | None,
    primary_address: int | None,
) -> str | None:
    """Return a usb:... spec for a USB adapter other than the primary, or None."""
    if primary_bus is None or primary_address is None:
        return None

    from pybluehost.transport.usb import USBTransport

    for cand in USBTransport.list_devices():
        if cand.bus == primary_bus and cand.address == primary_address:
            continue
        return _usb_candidate_spec(cand)
    return None


def enforce_same_family(primary: str, peer: str) -> None:
    """Raise SameFamilyError if peer family differs from primary."""
    p_fam = family_of(primary)
    q_fam = family_of(peer)
    if p_fam != q_fam:
        raise SameFamilyError(
            f"Peer transport must match primary family ({p_fam} vs {q_fam})"
        )


def usb_spec_bus_address(spec: str) -> tuple[int | None, int | None]:
    """Extract (bus, address) from a usb:... spec, or (None, None) if absent."""
    family, params = parse_spec(spec)
    if family != "usb":
        return (None, None)
    bus = _optional_int(params, "bus")
    address = _optional_int(params, "address")
    return (bus, address)


def vendor_of(spec: str) -> str | None:
    """Return 'intel' / 'realtek' / 'csr' for usb specs with vendor=, else None.

    Used by real_hardware_only marker enforcement to decide vendor-constrained skips.
    """
    family, params = parse_spec(spec)
    if family != "usb":
        return None
    return params.get("vendor")


def _parse_usb_params(raw: str) -> dict[str, str]:
    if not raw:
        raise InvalidSpec("USB spec is missing parameters")

    params: dict[str, str] = {}
    for token in raw.split(","):
        if not token or not token.strip():
            raise InvalidSpec("USB spec contains an empty token")
        if "=" not in token:
            raise InvalidSpec(f"USB spec part missing '=': {token.strip()!r}")

        key, value = token.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key:
            raise InvalidSpec("Empty usb spec key")
        if key in params:
            raise InvalidSpec(f"Duplicate usb spec key: {key!r}")
        if key not in _USB_KEYS:
            raise InvalidSpec(f"Unknown usb spec key: {key!r}")
        if not value:
            raise InvalidSpec(f"Empty usb {key} value")

        if key == "vendor":
            vendor = value.lower()
            if vendor not in _VALID_VENDORS:
                raise InvalidSpec(f"Unsupported vendor: {value!r}")
            params[key] = vendor
        elif key in {"bus", "address"}:
            _validate_usb_int(key, value)
            params[key] = value

    return params


def _validate_usb_int(key: str, value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise InvalidSpec(f"Invalid usb {key} value: {value!r}") from exc
    if parsed < 0:
        raise InvalidSpec(f"Invalid usb {key} value: {value!r}")
    return parsed


def _optional_int(params: dict[str, str], key: str) -> int | None:
    value = params.get(key)
    if value is None:
        return None
    return _validate_usb_int(key, value)


def _usb_candidate_spec(candidate: object) -> str:
    return (
        f"usb:vendor={candidate.vendor},"
        f"bus={candidate.bus},"
        f"address={candidate.address}"
    )
