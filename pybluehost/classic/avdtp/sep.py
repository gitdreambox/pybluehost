"""AVDTP Stream End-Point (SEP) and state machine (AVDTP v1.3 §3.5, §9.1)."""
from __future__ import annotations

from typing import Optional

from pybluehost.classic.avdtp.constants import MediaType, TSEP


class SEPStateError(RuntimeError):
    """Raised on an illegal state transition for a SEP."""


_VALID_TRANSITIONS: dict[str, set[str]] = {
    "IDLE":       {"set_configuration"},
    "CONFIGURED": {"open", "close", "abort"},
    "OPEN":       {"start", "close", "abort"},
    "STREAMING":  {"suspend", "close", "abort"},
}


class StreamEndpoint:
    """AVDTP Stream End-Point — one logical media endpoint owned by a SEP table.

    State diagram (per AVDTP v1.3 §9.1):

        IDLE ─SET_CONFIG─► CONFIGURED ─OPEN─► OPEN ─START─► STREAMING
                              │                 │              │
                              └──── CLOSE ──────┴── SUSPEND ◄──┘
                              └──── ABORT (from anywhere) ─► IDLE
    """

    def __init__(
        self,
        *,
        seid: int,
        media_type: MediaType,
        tsep: TSEP,
    ) -> None:
        if not 1 <= seid <= 62:
            raise ValueError(f"seid {seid} out of range 1..62 (0/63 reserved)")
        self.seid = seid
        self.media_type = media_type
        self.tsep = tsep
        self._state = "IDLE"
        self.configuration: Optional[bytes] = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def in_use(self) -> bool:
        return self._state != "IDLE"

    def _require(self, transition: str) -> None:
        allowed = _VALID_TRANSITIONS.get(self._state, set())
        if transition not in allowed:
            raise SEPStateError(
                f"seid={self.seid} cannot {transition} from state {self._state} "
                f"(allowed: {sorted(allowed)})"
            )

    def transition_set_configuration(self, config: bytes = b"") -> None:
        self._require("set_configuration")
        self.configuration = config
        self._state = "CONFIGURED"

    def transition_open(self) -> None:
        self._require("open")
        self._state = "OPEN"

    def transition_start(self) -> None:
        self._require("start")
        self._state = "STREAMING"

    def transition_suspend(self) -> None:
        self._require("suspend")
        self._state = "OPEN"

    def transition_close(self) -> None:
        if self._state == "IDLE":
            raise SEPStateError(f"seid={self.seid} already IDLE, cannot CLOSE")
        self._state = "IDLE"
        self.configuration = None

    def transition_abort(self) -> None:
        if self._state == "IDLE":
            raise SEPStateError(f"seid={self.seid} already IDLE, cannot ABORT")
        self._state = "IDLE"
        self.configuration = None
