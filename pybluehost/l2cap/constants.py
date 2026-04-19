"""L2CAP constants: CIDs, PSMs, signaling command codes."""
from __future__ import annotations
from enum import IntEnum

# Fixed Channel Identifiers (CID)
CID_CLASSIC_SIGNALING = 0x0001
CID_CONNECTIONLESS    = 0x0002
CID_ATT               = 0x0004
CID_LE_SIGNALING      = 0x0005
CID_SMP               = 0x0006
CID_SMP_BR_EDR        = 0x0007
CID_DYNAMIC_MIN       = 0x0040
CID_DYNAMIC_MAX       = 0x007F

# Protocol/Service Multiplexer (PSM) values
PSM_SDP     = 0x0001
PSM_RFCOMM  = 0x0003
PSM_AVDTP   = 0x0019
PSM_ATT     = 0x001F

class SignalingCode(IntEnum):
    COMMAND_REJECT         = 0x01
    CONNECTION_REQUEST     = 0x02
    CONNECTION_RESPONSE    = 0x03
    CONFIGURE_REQUEST      = 0x04
    CONFIGURE_RESPONSE     = 0x05
    DISCONNECTION_REQUEST  = 0x06
    DISCONNECTION_RESPONSE = 0x07
    INFORMATION_REQUEST    = 0x0A
    INFORMATION_RESPONSE   = 0x0B
    CONN_PARAM_UPDATE_REQ  = 0x12
    CONN_PARAM_UPDATE_RSP  = 0x13
    LE_CREDIT_CONN_REQ     = 0x14
    LE_CREDIT_CONN_RSP     = 0x15
    FLOW_CONTROL_CREDIT    = 0x16
