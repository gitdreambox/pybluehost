"""USB device discovery and selection helpers.

Pure-function helpers for enumerating USB devices, identifying Bluetooth
adapters, and matching them against caller-supplied selection criteria.
None of these helpers open a transport; that is base.py's job.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pybluehost.transport.spec import format_usb_transport_name
from pybluehost.transport.usb.chips import ChipInfo

logger = logging.getLogger(__name__)

# Lazy import: pyusb is optional
try:
    import usb
    import usb.core
    import usb.util
except ImportError:
    usb = None  # type: ignore[assignment]


@dataclass(frozen=True)
class DeviceCandidate:
    """One enumerated Bluetooth USB device with location metadata."""

    chip_info: ChipInfo
    bus: int
    address: int
    occurrence: int = 1

    @property
    def vendor(self) -> str:
        return self.chip_info.vendor

    @property
    def name(self) -> str:
        return self.chip_info.name

    @property
    def transport_name(self) -> str:
        return format_usb_transport_name(
            self.chip_info.vid,
            self.chip_info.pid,
            self.occurrence,
        )


def known_chip_for(dev: Any) -> ChipInfo | None:
    """Return the ChipInfo matching this device, or None if not in the registry."""
    from pybluehost.transport.usb import KNOWN_CHIPS  # local to avoid circular import
    for chip in KNOWN_CHIPS:
        if dev.idVendor == chip.vid and dev.idProduct == chip.pid:
            return chip
    return None


def known_usb_vendors() -> frozenset[str]:
    """Return supported USB vendor filters derived from ``KNOWN_CHIPS``."""
    from pybluehost.transport.usb import KNOWN_CHIPS  # local to avoid circular import
    return frozenset(chip.vendor for chip in KNOWN_CHIPS)


def usb_class_tuple(obj: Any, prefix: str) -> tuple[int, int, int]:
    return (
        int(getattr(obj, f"{prefix}Class", 0) or 0),
        int(getattr(obj, f"{prefix}SubClass", 0) or 0),
        int(getattr(obj, f"{prefix}Protocol", 0) or 0),
    )


def is_bluetooth_usb_class(values: tuple[int, int, int]) -> bool:
    return values == (0xE0, 0x01, 0x01)


def iter_usb_interfaces(dev: Any) -> list[Any]:
    interfaces: list[Any] = []
    try:
        for cfg in dev:
            for intf in cfg:
                interfaces.append(intf)
    except Exception:
        pass
    try:
        cfg = dev.get_active_configuration()
        interfaces.append(cfg[(0, 0)])
    except Exception:
        pass
    return interfaces


def is_bluetooth_usb_device(dev: Any) -> bool:
    if known_chip_for(dev) is not None:
        return True
    if is_bluetooth_usb_class(usb_class_tuple(dev, "bDevice")):
        return True
    for intf in iter_usb_interfaces(dev):
        if is_bluetooth_usb_class(usb_class_tuple(intf, "bInterface")):
            return True
    return False


def format_usb_class(values: tuple[int, int, int]) -> str:
    cls, sub, proto = values
    class_names = {
        0x00: "Device",
        0x09: "Hub",
        0xE0: "Wireless Controller",
    }
    return f"{class_names.get(cls, 'Unknown')} ({cls:02x}:{sub:02x}:{proto:02x})"


def _descriptor_string(dev: Any, attr: str) -> str | None:
    try:
        value = getattr(dev, attr)
        if value:
            return str(value)
    except Exception:
        pass
    return None


def _bluetooth_usb_occurrence_indexes(devices: list[Any]) -> dict[int, int]:
    indexes: dict[int, int] = {}
    counts: dict[tuple[int, int], int] = {}
    for dev in devices:
        if not is_bluetooth_usb_device(dev):
            continue
        key = (int(dev.idVendor), int(dev.idProduct))
        counts[key] = counts.get(key, 0) + 1
        indexes[id(dev)] = counts[key]
    return indexes


def _matches_usb_selection(
    dev: Any,
    *,
    bus: int | None,
    address: int | None,
    vid: int | None,
    pid: int | None,
    serial: str | None,
    occurrence: int | None,
    occurrence_index: int | None,
) -> bool:
    if bus is not None and int(getattr(dev, "bus", 0) or 0) != bus:
        return False
    if address is not None and int(getattr(dev, "address", 0) or 0) != address:
        return False
    if vid is not None and int(dev.idVendor) != vid:
        return False
    if pid is not None and int(dev.idProduct) != pid:
        return False
    if serial is not None and _descriptor_string(dev, "serial_number") != serial:
        return False
    if occurrence is not None and occurrence_index != occurrence:
        return False
    return True


def get_usb_endpoints(dev: Any) -> list[dict[str, str]]:
    """Extract endpoint info from USB HCI interface 0."""
    endpoints = []
    if usb is None:
        return endpoints
    try:
        try:
            dev.set_configuration()
        except Exception:
            pass
        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]
        for ep in intf:
            direction = (
                "IN"
                if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN
                else "OUT"
            )
            ep_type_val = usb.util.endpoint_type(ep.bmAttributes)
            type_names = {0: "Control", 1: "Isochronous", 2: "Bulk", 3: "Interrupt"}
            endpoints.append(
                {
                    "address": f"0x{ep.bEndpointAddress:02x}",
                    "type": type_names.get(ep_type_val, "Unknown"),
                    "direction": direction,
                }
            )
    except Exception:
        pass
    return endpoints


def _bumble_transport_names(dev: Any, occurrence: int | None = None) -> list[str]:
    return [
        format_usb_transport_name(
            int(dev.idVendor),
            int(dev.idProduct),
            occurrence or 1,
        )
    ]
