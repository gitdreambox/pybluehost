"""HFP v1.8 constants — codec IDs, feature bitmasks, call states, indicator names."""
from __future__ import annotations

from enum import IntEnum


# Bluetooth-assigned UUIDs (HFP v1.8 §5.4).
HANDSFREE_UUID = 0x111E      # legacy / generic
HFP_HF_UUID = 0x111E         # HF role
HFP_AG_UUID = 0x111F         # AudioGateway role
HFP_PROFILE_VERSION = 0x0108   # HFP v1.8 binary version code


class HFPCodecID(IntEnum):
    """HFP v1.8 §5.4.2.3 — AT+BAC codec list values."""
    CVSD = 1
    MSBC = 2


class HFPCallState(IntEnum):
    """HFP v1.8 §4.34 — +CIND `call` indicator range."""
    NO_CALL = 0
    ACTIVE = 1


class HFPCallSetupState(IntEnum):
    """HFP v1.8 §4.34 — +CIND `callsetup` indicator range."""
    NONE = 0
    INCOMING = 1
    OUTGOING = 2
    OUTGOING_ALERTING = 3


class HFPIndicator(str):
    """HFP §4.34 standard indicator names exchanged via +CIND."""
    SERVICE = "service"
    CALL = "call"
    CALLSETUP = "callsetup"
    SIGNAL = "signal"
    ROAM = "roam"
    BATTCHG = "battchg"
    CALLHELD = "callheld"


class HFFeature(IntEnum):
    """HFP v1.8 §4.34.1 — HF features bitmask (AT+BRSF)."""
    EC_NR = 1 << 0
    THREE_WAY = 1 << 1
    CLI = 1 << 2
    VOICE_RECOGNITION = 1 << 3
    REMOTE_VOLUME_CONTROL = 1 << 4
    ENHANCED_CALL_STATUS = 1 << 5
    ENHANCED_CALL_CONTROL = 1 << 6
    CODEC_NEGOTIATION = 1 << 7
    HF_INDICATORS = 1 << 8
    ESCO_S4_T2 = 1 << 9


class AGFeature(IntEnum):
    """HFP v1.8 §4.34.2 — AG features bitmask (+BRSF)."""
    THREE_WAY = 1 << 0
    EC_NR = 1 << 1
    VOICE_RECOGNITION = 1 << 2
    IN_BAND_RING = 1 << 3
    VOICE_TAG = 1 << 4
    REJECT_CALL = 1 << 5
    ENHANCED_CALL_STATUS = 1 << 6
    ENHANCED_CALL_CONTROL = 1 << 7
    EXTENDED_ERROR = 1 << 8
    CODEC_NEGOTIATION = 1 << 9
    HF_INDICATORS = 1 << 10
    ESCO_S4_T2 = 1 << 11


# Sensible defaults — Plan A.4 advertises codec negotiation + basic features only.
DEFAULT_HF_FEATURES = (
    HFFeature.EC_NR | HFFeature.CLI | HFFeature.CODEC_NEGOTIATION
)
DEFAULT_AG_FEATURES = (
    AGFeature.EC_NR | AGFeature.REJECT_CALL | AGFeature.CODEC_NEGOTIATION
)
