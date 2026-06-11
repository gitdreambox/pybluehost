"""Bluetooth Classic profiles (A2DP, AVRCP, HFP, HSP).

Each profile is a small class that registers an SDP record + L2CAP/RFCOMM
listeners against a Stack and exposes session objects for active connections.
"""
from pybluehost.profiles.classic.a2dp import A2DPSession, A2DPSink, A2DPSource

__all__ = ["A2DPSource", "A2DPSink", "A2DPSession"]
