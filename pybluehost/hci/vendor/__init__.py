"""HCI vendor-specific constants and parsers."""

from pybluehost.hci.vendor.intel import (
    HCI_VS_INTEL_READ_VERSION,
    HCI_VS_INTEL_WRITE_FIRMWARE,
    INTEL_TLV_TYPE_CNV,
    INTEL_TLV_TYPE_TIMESTAMP,
    IntelReadVersionResponse,
)
from pybluehost.hci.vendor.realtek import (
    HCI_VS_REALTEK_READ_ROM_VERSION,
    HCI_VS_REALTEK_WRITE_FIRMWARE,
    RealtekROMVersion,
)

__all__ = [
    "HCI_VS_INTEL_READ_VERSION",
    "HCI_VS_INTEL_WRITE_FIRMWARE",
    "INTEL_TLV_TYPE_CNV",
    "INTEL_TLV_TYPE_TIMESTAMP",
    "IntelReadVersionResponse",
    "HCI_VS_REALTEK_READ_ROM_VERSION",
    "HCI_VS_REALTEK_WRITE_FIRMWARE",
    "RealtekROMVersion",
]
