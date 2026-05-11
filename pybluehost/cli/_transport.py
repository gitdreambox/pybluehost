# pybluehost/cli/_transport.py
"""Parse --transport string into a Transport instance."""
from __future__ import annotations

from pybluehost.transport.base import Transport
from pybluehost.transport.spec import (
    InvalidSpec,
    parse_spec,
    uart_spec_port_baud,
    usb_spec_bus_address,
    usb_spec_identity,
)


async def parse_transport_arg(s: str) -> Transport:
    """Parse a --transport CLI argument into a Transport instance.

    Formats:
        virtual                        -> VirtualController transport
        usb                            -> USBTransport.auto_detect()
        usb:33FA:0012#1                -> auto_detect with VID/PID/occurrence filter
        uart:/dev/ttyUSB0              -> UARTTransport(port=..., baudrate=115200)
        uart:/dev/ttyUSB0@921600       -> UARTTransport(port=..., baudrate=921600)
    """
    try:
        family, params = parse_spec(s)
    except InvalidSpec as exc:
        raise ValueError(str(exc)) from exc

    if family == "virtual":
        from pybluehost.hci.virtual import VirtualController

        _vc, host_t = await VirtualController.create()
        return host_t

    if family == "usb":
        from pybluehost.transport.usb import USBTransport

        bus, address = usb_spec_bus_address(s)
        vid, pid, serial, occurrence = usb_spec_identity(s)
        if vid is not None or pid is not None:
            return USBTransport.auto_detect(
                vendor=params.get("vendor"),
                bus=bus,
                address=address,
                vid=vid,
                pid=pid,
                serial=serial,
                occurrence=occurrence,
            )
        return USBTransport.auto_detect(
            vendor=params.get("vendor"),
            bus=bus,
            address=address,
        )

    if family == "uart":
        from pybluehost.transport.uart import UARTTransport

        port, baudrate = uart_spec_port_baud(s)
        return UARTTransport(port=port, baudrate=baudrate)

    raise ValueError(f"Unknown transport: {s!r}")
