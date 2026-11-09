"""pts-tester forwards bond-resume encryption as BTP SEC_LEVEL_CHANGED.

GATT/SR/GAR/BV-11/12 assume a pre-existing IUT↔LT bond: PTS skips pairing and
goes straight to LL_ENC_REQUEST, so the pairing-driven SEC_LEVEL_CHANGED path
never fires. auto-pts advances its `conn.sec_level` model only via that event;
without it the EATT-listen WID (wid 400) waits 30s for
`conn.sec_level >= min_level` and the case aborts (FATAL) even though the link
is encrypted. The stack's "encrypted" connection event carries the peer and the
security level; this forwarding turns it into BTP ev 0x89.
"""
import asyncio

import pytest

from pybluehost.cli.app.pts_tester import _forward_sec_level
from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import BtpFrame
from pybluehost.pts.btp.services.gap import GapService


class _FakeTester:
    def __init__(self):
        self.events = []

    async def emit_event(self, frame: BtpFrame) -> None:
        self.events.append(frame)


class _Ev:
    def __init__(self, sec_level):
        self.sec_level = sec_level


@pytest.mark.asyncio
@pytest.mark.parametrize("sec_level,expected", [(2, 2), (3, 3), (None, 2)])
async def test_forward_sec_level_emits_btp_event(sec_level, expected):
    tester = _FakeTester()
    gap = GapService(actions=None, tester=tester)

    _forward_sec_level(gap, _Ev(sec_level), peer_bytes=b"\x01\x02\x03\x04\x05\x06", addr_type=0)
    await asyncio.sleep(0)

    assert len(tester.events) == 1
    evt = tester.events[0]
    assert evt.opcode == op.OP_GAP_EVENT_SEC_LEVEL_CHANGED
    assert evt.data == bytes([0]) + b"\x01\x02\x03\x04\x05\x06" + bytes([expected])
