"""Transport spec string parser.

Single source of truth for the ``virtual | usb[:vendor=,bus=,address=] | uart:...``
spec string format. Used by both the test infrastructure (``--transport`` /
``--transport-peer`` pytest options) and the CLI (``parse_transport_arg``) so
the parsing rules and error messages stay consistent.

This module performs validation only — it does not enumerate or open devices.
"""
from __future__ import annotations


class InvalidSpec(ValueError):
    """Raised when a transport spec string is malformed."""


class SameFamilyError(ValueError):
    """Raised when peer transport family does not match primary."""


_VALID_VENDORS = {"intel", "realtek", "csr"}
_USB_KEYS = {"vendor", "bus", "address"}

UART_SPEC_FORMAT = "uart:<port>[@baud]"
USB_SPEC_FORMAT = "usb[:vendor=...,bus=N,address=M]"
TRANSPORT_SPEC_FORMAT = f"virtual | {USB_SPEC_FORMAT} | {UART_SPEC_FORMAT}"


def parse_spec(spec: str) -> tuple[str, dict[str, str]]:
    """Validate spec syntax and return ``(family, params)``.

    ``family`` is one of ``"virtual"``, ``"usb"``, ``"uart"``. ``params`` is a
    dict of validated key/value pairs (e.g. ``{"vendor": "intel", "bus": "1"}``
    for usb, ``{"raw": "/dev/ttyUSB0@921600"}`` for uart, empty dict otherwise).

    Raises :class:`InvalidSpec` for malformed input. Does not open any device.
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


def family_of(spec: str) -> str:
    """Return ``"virtual"`` / ``"usb"`` / ``"uart"`` for any valid spec."""
    family, _ = parse_spec(spec)
    return family


def usb_spec_bus_address(spec: str) -> tuple[int | None, int | None]:
    """Extract ``(bus, address)`` from a usb spec, or ``(None, None)`` if absent."""
    family, params = parse_spec(spec)
    if family != "usb":
        return (None, None)
    bus = _optional_int(params, "bus")
    address = _optional_int(params, "address")
    return (bus, address)


def uart_spec_port_baud(spec: str) -> tuple[str, int]:
    """Extract ``(port, baudrate)`` from a uart spec.

    The baudrate defaults to 115200 when the spec does not include ``@baud``.
    """
    family, params = parse_spec(spec)
    if family != "uart":
        raise InvalidSpec(f"Expected uart transport spec: {spec!r}")

    raw = params["raw"]
    port = raw
    baudrate = 115200
    if "@" in raw:
        port, baudrate_s = raw.rsplit("@", 1)
        if not baudrate_s:
            raise InvalidSpec(f"UART spec missing baudrate: {spec!r}")
        try:
            baudrate = int(baudrate_s)
        except ValueError as exc:
            raise InvalidSpec(
                f"Invalid UART baudrate in spec {spec!r}: {baudrate_s!r}"
            ) from exc

    port = port.strip()
    if not port:
        raise InvalidSpec("UART spec missing port")
    if baudrate <= 0:
        raise InvalidSpec(f"Invalid UART baudrate in spec {spec!r}: {baudrate!r}")
    return (port, baudrate)


def vendor_of(spec: str) -> str | None:
    """Return ``"intel"`` / ``"realtek"`` / ``"csr"`` for usb specs with vendor=, else None."""
    family, params = parse_spec(spec)
    if family != "usb":
        return None
    return params.get("vendor")


def format_usb_candidate_spec(vendor: str, bus: int, address: int) -> str:
    """Render a concrete usb spec string for a known-vendor adapter location."""
    return f"usb:vendor={vendor},bus={bus},address={address}"


def enforce_same_family(primary: str, peer: str) -> None:
    """Raise :class:`SameFamilyError` if peer family differs from primary."""
    p_fam = family_of(primary)
    q_fam = family_of(peer)
    if p_fam != q_fam:
        raise SameFamilyError(
            f"Peer transport must match primary family ({p_fam} vs {q_fam})"
        )


def _parse_usb_params(raw: str) -> dict[str, str]:
    if not raw:
        raise InvalidSpec("USB spec is missing parameters")

    params: dict[str, str] = {}
    for token in raw.split(","):
        if not token or not token.strip():
            raise InvalidSpec("USB spec contains an empty token")
        if "=" not in token:
            raise InvalidSpec(f"Malformed usb spec token: {token.strip()!r}")

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
