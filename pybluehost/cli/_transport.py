# pybluehost/cli/_transport.py
"""Parse --transport string into a Transport instance."""
from __future__ import annotations

from pybluehost.transport.base import Transport


async def parse_transport_arg(s: str) -> Transport:
    """Parse a --transport CLI argument into a Transport instance.

    Formats:
        virtual                        -> VirtualController transport
        usb                            → USBTransport.auto_detect()
        usb:vendor=intel               → USBTransport.auto_detect(vendor="intel")
        uart:/dev/ttyUSB0              → UARTTransport(port=..., baudrate=115200)
        uart:/dev/ttyUSB0@921600       → UARTTransport(port=..., baudrate=921600)
    """
    if s == "virtual":
        from pybluehost.hci.virtual import VirtualController

        _vc, host_t = await VirtualController.create()
        return host_t

    if s == "usb" or s.startswith("usb:"):
        from pybluehost.transport.usb import USBTransport
        vendor: str | None = None
        bus: int | None = None
        address: int | None = None
        if s.startswith("usb:"):
            seen_keys: set[str] = set()
            for kv in s[4:].split(","):
                if "=" not in kv:
                    raise ValueError(f"Malformed usb spec token: {kv.strip()!r}")
                k, v = kv.split("=", 1)
                k = k.strip()
                v = v.strip()
                if not k:
                    raise ValueError("Empty usb spec key")
                if k in seen_keys:
                    raise ValueError(f"Duplicate usb spec key: {k!r}")
                seen_keys.add(k)
                if not v:
                    raise ValueError(f"Empty usb {k} value")
                if k == "vendor":
                    vendor = v
                elif k == "bus":
                    try:
                        bus = int(v)
                    except ValueError as exc:
                        raise ValueError(f"Invalid usb bus value: {v!r}") from exc
                    if bus < 0:
                        raise ValueError(f"Invalid usb bus value: {v!r}")
                elif k == "address":
                    try:
                        address = int(v)
                    except ValueError as exc:
                        raise ValueError(f"Invalid usb address value: {v!r}") from exc
                    if address < 0:
                        raise ValueError(f"Invalid usb address value: {v!r}")
                else:
                    raise ValueError(f"Unknown usb spec key: {k!r}")
        return USBTransport.auto_detect(vendor=vendor, bus=bus, address=address)

    if s.startswith("uart:"):
        from pybluehost.transport.uart import UARTTransport
        spec = s[5:]
        if not spec:
            raise ValueError("UART port required: uart:/dev/ttyXXX[@baud]")
        if "@" in spec:
            port, baud_s = spec.rsplit("@", 1)
            baud = int(baud_s)
        else:
            port = spec
            baud = 115200
        return UARTTransport(port=port, baudrate=baud)

    raise ValueError(f"Unknown transport: {s!r}")
