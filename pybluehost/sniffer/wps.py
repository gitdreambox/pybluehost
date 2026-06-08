"""Teledyne LeCroy WPS injection — pure encoding + Windows backend."""
from __future__ import annotations

from pybluehost.core.trace import Direction


# Drf bitfield (from liveimport.ini personality "Command;ACL;SCO;Event")
_DRF_COMMAND = 1
_DRF_ACL = 2
_DRF_SCO = 4
_DRF_EVENT = 8

# Stream
_STREAM_HOST = 0
_STREAM_CONTROLLER = 1


def wps_frame_params(h4_type: int, direction: Direction) -> tuple[int, int] | None:
    """Map (H4 packet type, direction) → (Drf, Stream) for WPS SendFrame3.

    Returns None for ISO (0x05) — not representable in default WPS personality.
    Caller (WpsBackend.inject) must skip None and warn once per session.

    See design spec §3.3.
    """
    if h4_type == 0x01:
        return (_DRF_COMMAND, _STREAM_HOST)
    if h4_type == 0x04:
        return (_DRF_EVENT, _STREAM_CONTROLLER)
    if h4_type == 0x02:
        return (_DRF_ACL, _STREAM_HOST if direction == Direction.DOWN else _STREAM_CONTROLLER)
    if h4_type == 0x03:
        return (_DRF_SCO, _STREAM_HOST if direction == Direction.DOWN else _STREAM_CONTROLLER)
    if h4_type == 0x05:
        return None
    raise ValueError(f"unknown H4 packet type: 0x{h4_type:02X}")
