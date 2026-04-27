# pybluehost/cli/_transport.py
"""Parse --transport string into a Transport instance."""
from __future__ import annotations

from pybluehost.transport.base import Transport


async def parse_transport_arg(s: str) -> Transport:
    """Parse a --transport CLI argument into a Transport instance.

    Formats:
        virtual                        -> VirtualController + LoopbackTransport pair
        usb                            → USBTransport.auto_detect()
        usb:vendor=intel               → USBTransport.auto_detect(vendor="intel")
        uart:/dev/ttyUSB0              → UARTTransport(port=..., baudrate=115200)
        uart:/dev/ttyUSB0@921600       → UARTTransport(port=..., baudrate=921600)
    """
    if s == "virtual":
        from pybluehost.core.address import BDAddress
        from pybluehost.hci.virtual import VirtualController
        from pybluehost.transport.loopback import LoopbackTransport

        vc = VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:01"))
        host_t, ctrl_t = LoopbackTransport.pair()

        class _VCSink:
            async def on_transport_data(self, data: bytes) -> None:
                response = await vc.process(data)
                if response is not None and host_t._sink is not None:
                    await host_t._sink.on_transport_data(response)

        ctrl_t.set_sink(_VCSink())
        await host_t.open()
        await ctrl_t.open()
        return host_t

    if s == "usb" or s.startswith("usb:"):
        from pybluehost.transport.usb import USBTransport
        vendor: str | None = None
        if s.startswith("usb:"):
            for kv in s[4:].split(","):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    if k.strip() == "vendor":
                        vendor = v.strip()
        return USBTransport.auto_detect(vendor=vendor)

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
