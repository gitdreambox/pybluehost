"""pybluehost.audio.codec — pure-Python SBC/CVSD/mSBC encoders+decoders.

Plan A.1 ships these for use by AVDTP (A2DP, A.2) and SCO (HFP, A.4). No
Bluetooth dependencies; each codec is plain DSP.
"""
from pybluehost.audio.codec.cvsd import CVSDDecoder, CVSDEncoder
from pybluehost.audio.codec.msbc import MSBCDecoder, MSBCEncoder
from pybluehost.audio.codec.sbc import SBCDecoder, SBCEncoder, SBCHeader

__all__ = [
    "SBCEncoder", "SBCDecoder", "SBCHeader",
    "CVSDEncoder", "CVSDDecoder",
    "MSBCEncoder", "MSBCDecoder",
]
