"""Shared base for Classic profile classes."""
from __future__ import annotations

from typing import Any


class ClassicProfile:
    """Mixin-like base. Subclasses override `_build_sdp_record()`, `_psm()`,
    and `_on_psm_connect()`.
    """

    stack: Any

    def register(self) -> None:
        """Install SDP record + L2CAP listener. Idempotent."""
        record = self._build_sdp_record()
        self.stack.sdp.register(record)
        self.stack.l2cap.listen_classic_channel(self._psm(), self._on_psm_connect)

    def _build_sdp_record(self):  # pragma: no cover — subclass override
        raise NotImplementedError

    def _psm(self) -> int:  # pragma: no cover — subclass override
        raise NotImplementedError

    def _on_psm_connect(self, channel):  # pragma: no cover — subclass override
        raise NotImplementedError
