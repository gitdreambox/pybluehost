"""Bluetooth Classic profiles (A2DP, AVRCP, HFP, HSP)."""
from pybluehost.profiles.classic.a2dp import A2DPSession, A2DPSink, A2DPSource
from pybluehost.profiles.classic.avrcp import (
    AVRCPController, AVRCPSession, AVRCPTarget,
)
from pybluehost.profiles.classic.hfp import (
    HFPAudioGateway, HFPHandsFree, HFPSession,
)
from pybluehost.profiles.classic.hsp import (
    HSPAudioGateway, HSPHeadset, HSPSession,
)

__all__ = [
    "A2DPSource", "A2DPSink", "A2DPSession",
    "AVRCPController", "AVRCPTarget", "AVRCPSession",
    "HFPAudioGateway", "HFPHandsFree", "HFPSession",
    "HSPAudioGateway", "HSPHeadset", "HSPSession",
]
