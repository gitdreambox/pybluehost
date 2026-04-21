"""Classic Bluetooth stack — SDP, RFCOMM, SPP, and GAP."""
from pybluehost.classic.sdp import (
    DataElement,
    DataElementType,
    SDPClient,
    SDPServer,
    ServiceRecord,
    decode_data_element,
    encode_data_element,
    make_rfcomm_service_record,
)
from pybluehost.classic.rfcomm import (
    RFCOMMChannel,
    RFCOMMFrame,
    RFCOMMFrameType,
    RFCOMMManager,
    RFCOMMSession,
    calc_fcs,
    decode_frame,
    encode_frame,
)
from pybluehost.classic.spp import (
    SPPClient,
    SPPConnection,
    SPPService,
)
from pybluehost.classic.gap import (
    ClassicConnection,
    ClassicConnectionManager,
    ClassicDiscoverability,
    ClassicDiscovery,
    InquiryConfig,
    SSPManager,
    SSPMethod,
    ScanEnableFlags,
)

__all__ = [
    # sdp
    "DataElement",
    "DataElementType",
    "SDPClient",
    "SDPServer",
    "ServiceRecord",
    "decode_data_element",
    "encode_data_element",
    "make_rfcomm_service_record",
    # rfcomm
    "RFCOMMChannel",
    "RFCOMMFrame",
    "RFCOMMFrameType",
    "RFCOMMManager",
    "RFCOMMSession",
    "calc_fcs",
    "decode_frame",
    "encode_frame",
    # spp
    "SPPClient",
    "SPPConnection",
    "SPPService",
    # gap
    "ClassicConnection",
    "ClassicConnectionManager",
    "ClassicDiscoverability",
    "ClassicDiscovery",
    "InquiryConfig",
    "SSPManager",
    "SSPMethod",
    "ScanEnableFlags",
]
