"""ACL PDU regex-replacement demo. To change rules, edit DEMO_RULES at the bottom.

Replacement happens inside AclRelay at the reassembled complete-L2CAP-PDU layer
(not the HCI fragment layer); encode_l2cap_basic then rewrites the length header
from the new payload, so length changes are handled naturally. Capture taps after
enqueue, so what is captured is exactly what goes on the wire after replacement.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from pybluehost.cli.app.mitm.acl import RelayDirection

# AclRelay transform hook signature: (direction, cid, payload) -> payload
PduTransform = Callable[[RelayDirection, int, bytes], bytes]


@dataclass(frozen=True)
class ReplaceRule:
    pattern: bytes                              # bytes regex (matched on the L2CAP payload)
    repl: bytes                                 # replacement (supports \g<1> backreferences)
    direction: Optional[RelayDirection] = None  # None = apply in both directions
    cid: Optional[int] = None                   # None = all CIDs; set = only that channel


class RegexReplacer:
    """Compile a set of ReplaceRule into an AclRelay transform hook."""

    def __init__(self, rules: Sequence[ReplaceRule]) -> None:
        self._compiled = [(re.compile(r.pattern), r) for r in rules]

    def __call__(self, direction: RelayDirection, cid: int, payload: bytes) -> bytes:
        for rx, rule in self._compiled:
            if rule.direction is not None and rule.direction is not direction:
                continue
            if rule.cid is not None and rule.cid != cid:
                continue
            payload = rx.sub(rule.repl, payload)
        return payload


# ====== DEMO: add your own rules below ======
DEMO_RULES: list[ReplaceRule] = [
    # Example: replace a device-name string on the control channel. Uncomment to enable:
    # ReplaceRule(pattern=b"WQ7035", repl=b"MITM7035"),
    # Example: replace a 4-byte sequence only in the phone→target direction on a specific CID:
    # ReplaceRule(pattern=bytes.fromhex("deadbeef"), repl=bytes.fromhex("cafebabe"),
    #             direction=RelayDirection.PHONE_TO_TARGET),
]
