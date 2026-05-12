"""CSRUSBTransport — initializes CSR8510 / Cambridge Silicon Radio Bluetooth dongles.

CSR8510 is a popular legacy USB Bluetooth dongle that needs no firmware
upload — open + standard HCI reset is enough. The subclass exists so
KNOWN_CHIPS can route to a class that's explicit about that property.
"""
from __future__ import annotations

from pybluehost.transport.usb.base import USBTransport


class CSRUSBTransport(USBTransport):
    """CSR Bluetooth USB transport.

    CSR8510 currently follows the standard Bluetooth USB HCI path, so it can
    use the base USB transport behavior without vendor-specific initialization.
    """
