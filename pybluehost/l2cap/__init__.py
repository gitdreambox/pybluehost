"""L2CAP layer — channels, constants, and SAR utilities."""
from pybluehost.l2cap.channel import (
    Channel,
    ChannelEvents,
    ChannelState,
    SimpleChannelEvents,
)
from pybluehost.l2cap.ble import FixedChannel, LECoCChannel
from pybluehost.l2cap.classic import (
    ChannelMode,
    ClassicChannel,
    ERTMEngine,
    StreamingEngine,
)
from pybluehost.l2cap.constants import (
    CID_ATT,
    CID_CLASSIC_SIGNALING,
    CID_CONNECTIONLESS,
    CID_DYNAMIC_MAX,
    CID_DYNAMIC_MIN,
    CID_LE_SIGNALING,
    CID_SMP,
    CID_SMP_BR_EDR,
    PSM_ATT,
    PSM_AVDTP,
    PSM_RFCOMM,
    PSM_SDP,
    SignalingCode,
)
from pybluehost.l2cap.sar import Reassembler, Segmenter

__all__ = [
    # channel
    "Channel",
    "ChannelEvents",
    "ChannelState",
    "SimpleChannelEvents",
    # ble
    "FixedChannel",
    "LECoCChannel",
    # classic
    "ChannelMode",
    "ClassicChannel",
    "ERTMEngine",
    "StreamingEngine",
    # constants
    "CID_ATT",
    "CID_CLASSIC_SIGNALING",
    "CID_CONNECTIONLESS",
    "CID_DYNAMIC_MAX",
    "CID_DYNAMIC_MIN",
    "CID_LE_SIGNALING",
    "CID_SMP",
    "CID_SMP_BR_EDR",
    "PSM_ATT",
    "PSM_AVDTP",
    "PSM_RFCOMM",
    "PSM_SDP",
    "SignalingCode",
    # sar
    "Reassembler",
    "Segmenter",
]
