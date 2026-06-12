"""HFP v1.8 §4.2 Service Level Connection state machine.

Models both HF and AG roles. The HF role drives the handshake by emitting
commands; the AG role responds with values + OK. Once the SLC is established,
both sides idle until either:
- HF sends AT+BCS=<id> after receiving +BCS (codec selection), or
- AG emits +CIEV (indicator change) or RING / +CLIP (incoming call).

This module is pure logic — no I/O. The HFPSession (Task 5) drives byte I/O
on the RFCOMM channel and feeds parsed AT messages here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from pybluehost.profiles.classic._at_parser import (
    ATCommand, ATResponse, ATUnsolicited,
)
from pybluehost.profiles.classic._hfp_at import (
    build_bac_command,
    build_brsf_command, build_brsf_response,
    build_cind_read_response, build_cind_test_response,
    build_cmer_command,
    parse_bac_command, parse_brsf_command, parse_brsf_response,
    parse_cmer_command,
)
from pybluehost.profiles.classic._hfp_constants import (
    AGFeature, HFFeature, HFPCodecID,
)


class SLCState(IntEnum):
    """SLC handshake states. HF and AG share the same enum but traverse different paths."""
    IDLE = 0
    BRSF_WAIT = 1        # HF: sent AT+BRSF, awaiting +BRSF response
    BAC_WAIT = 2         # HF: sent AT+BAC, awaiting OK (only if codec_neg supported)
    CIND_TEST_WAIT = 3   # HF: sent AT+CIND=?, awaiting +CIND
    CIND_READ_WAIT = 4   # HF: sent AT+CIND?, awaiting +CIND values
    CMER_WAIT = 5        # HF: sent AT+CMER, awaiting OK
    ESTABLISHED = 6
    FAILED = 7


@dataclass
class HFPStateMachine:
    role: str                # 'hf' or 'ag'
    local_features: int
    local_codecs: list[HFPCodecID]
    indicators: list[tuple[str, tuple[int, int]]] = field(default_factory=list)
    indicator_values: dict[str, int] = field(default_factory=dict)

    state: SLCState = SLCState.IDLE
    peer_features: int = 0
    peer_codecs: list[HFPCodecID] = field(default_factory=list)
    negotiated_codec: Optional[HFPCodecID] = None
    # Internal: how many OKs the AG has emitted in the post-+BRSF flurry
    _ag_pending_phase: int = 0

    # --- HF role -----------------------------------------------------
    def begin(self) -> list[ATCommand | ATResponse | ATUnsolicited]:
        """HF only — start the SLC by sending AT+BRSF."""
        if self.role != "hf":
            raise RuntimeError("begin() is HF-side only")
        self.state = SLCState.BRSF_WAIT
        return [build_brsf_command(self.local_features)]

    def feed(self, msg) -> list[ATCommand | ATResponse | ATUnsolicited]:
        """Process one inbound AT message; return zero or more outbound messages."""
        if self.role == "hf":
            return self._feed_hf(msg)
        return self._feed_ag(msg)

    def _feed_hf(self, msg) -> list:
        if self.state == SLCState.BRSF_WAIT:
            if isinstance(msg, ATResponse) and msg.name == "+BRSF":
                self.peer_features = parse_brsf_response(msg)
                return []
            if isinstance(msg, ATResponse) and msg.is_terminator and msg.name == "OK":
                # Decide next step: BAC if both sides support codec negotiation.
                if (self.peer_features & int(AGFeature.CODEC_NEGOTIATION)
                        and self.local_features & int(HFFeature.CODEC_NEGOTIATION)):
                    self.state = SLCState.BAC_WAIT
                    return [build_bac_command(self.local_codecs)]
                # Skip BAC, go straight to CIND=?
                self.state = SLCState.CIND_TEST_WAIT
                return [ATCommand(name="+CIND", kind="test", args=[])]
            return []
        if self.state == SLCState.BAC_WAIT:
            if isinstance(msg, ATResponse) and msg.is_terminator and msg.name == "OK":
                self.state = SLCState.CIND_TEST_WAIT
                return [ATCommand(name="+CIND", kind="test", args=[])]
            return []
        if self.state == SLCState.CIND_TEST_WAIT:
            if isinstance(msg, ATResponse) and msg.name == "+CIND":
                # Indicator definitions arrived.
                return []
            if isinstance(msg, ATResponse) and msg.is_terminator and msg.name == "OK":
                self.state = SLCState.CIND_READ_WAIT
                return [ATCommand(name="+CIND", kind="read", args=[])]
            return []
        if self.state == SLCState.CIND_READ_WAIT:
            if isinstance(msg, ATResponse) and msg.name == "+CIND":
                return []
            if isinstance(msg, ATResponse) and msg.is_terminator and msg.name == "OK":
                self.state = SLCState.CMER_WAIT
                return [build_cmer_command(mode=3, ind_reporting=1)]
            return []
        if self.state == SLCState.CMER_WAIT:
            if isinstance(msg, ATResponse) and msg.is_terminator and msg.name == "OK":
                self.state = SLCState.ESTABLISHED
            return []
        return []

    def _feed_ag(self, msg) -> list:
        if isinstance(msg, ATCommand):
            if msg.name == "+BRSF" and msg.kind == "set":
                self.peer_features = parse_brsf_command(msg)
                return [
                    build_brsf_response(self.local_features),
                    ATResponse(name="OK", is_terminator=True),
                ]
            if msg.name == "+BAC" and msg.kind == "set":
                self.peer_codecs = parse_bac_command(msg)
                return [ATResponse(name="OK", is_terminator=True)]
            if msg.name == "+CIND" and msg.kind == "test":
                return [
                    build_cind_test_response(self.indicators),
                    ATResponse(name="OK", is_terminator=True),
                ]
            if msg.name == "+CIND" and msg.kind == "read":
                ordering = [name for name, _ in self.indicators]
                return [
                    build_cind_read_response(self.indicator_values, ordering=ordering),
                    ATResponse(name="OK", is_terminator=True),
                ]
            if msg.name == "+CMER" and msg.kind == "set":
                self.state = SLCState.ESTABLISHED
                return [ATResponse(name="OK", is_terminator=True)]
        return []
