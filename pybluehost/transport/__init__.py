"""PyBlueHost transport layer."""

import sys

from pybluehost.transport.base import (
    ReconnectConfig,
    ReconnectPolicy,
    Transport,
    TransportInfo,
    TransportSink,
)
from pybluehost.transport.btsnoop import BtsnoopTransport
from pybluehost.transport.firmware import (
    FirmwareManager,
    FirmwareNotFoundError,
    FirmwarePolicy,
)
from pybluehost.transport.h4 import H4Framer
from pybluehost.transport.loopback import LoopbackTransport
from pybluehost.transport.tcp import TCPTransport
from pybluehost.transport.uart import UARTTransport
from pybluehost.transport.udp import UDPTransport
from pybluehost.transport.usb import (
    ChipInfo,
    IntelUSBTransport,
    KNOWN_CHIPS,
    NoBluetoothDeviceError,
    RealtekUSBTransport,
    USBTransport,
)

__all__ = [
    "BtsnoopTransport",
    "ChipInfo",
    "FirmwareManager",
    "FirmwareNotFoundError",
    "FirmwarePolicy",
    "H4Framer",
    "IntelUSBTransport",
    "KNOWN_CHIPS",
    "LoopbackTransport",
    "NoBluetoothDeviceError",
    "RealtekUSBTransport",
    "ReconnectConfig",
    "ReconnectPolicy",
    "TCPTransport",
    "Transport",
    "TransportInfo",
    "TransportSink",
    "UARTTransport",
    "UDPTransport",
    "USBTransport",
]

# HCIUserChannelTransport: only available on Linux
if sys.platform == "linux":
    from pybluehost.transport.hci_user_channel import HCIUserChannelTransport

    __all__.append("HCIUserChannelTransport")
