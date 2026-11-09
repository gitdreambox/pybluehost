"""GAP discovery discoverable-mode filtering (GAP/DISC/GENP + LIMP).

The GAP "discovery" procedure is not a raw scan: the IUT must only *report* a
device whose AD Flags marks it discoverable in the mode being run — General
Discovery surfaces General (0x02) or Limited (0x01) discoverable devices, Limited
Discovery surfaces only Limited (0x01), and the Observation procedure surfaces
everything. The TS note for the DISC group spells it out: "Discover … means to
report to the application layer and/or verify the Flags AD type presence and
setting".

Our scan path reported every advertising report, so the *negative* DISC cases —
"does not find Broadcast / Undirected Connectable / Directed Connectable device"
(GAP/DISC/GENP/BV-03/04/05, LIMP/BV-02/03/04/05) — all failed at the
"confirm PTS is NOT discovered" step: the IUT surfaced the Lower Tester's
non-discoverable advertising (Flags = BR/EDR-not-supported only) as a found
device.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pybluehost.pts.btp.services.gap import GapService, _ad_flags_from_eir


def _scan_result(*, flags: int | None = None, connectable: bool = False):
    """Build the ScanResult shape `_on_scan_result` reads."""
    eir = b"" if flags is None else bytes([0x02, 0x01, flags])
    addr = SimpleNamespace(address_type=0, to_hci=lambda: bytes.fromhex("AABBCCDDEEFF"))
    return SimpleNamespace(
        address=addr,
        rssi=0,
        advertising_data=None,
        raw_advertising_data=eir,
        connectable=connectable,
    )


def _make_svc(mode: str):
    svc = GapService(actions=MagicMock(), tester=MagicMock())
    svc._discovery_mode = mode
    emitted: list[bytes] = []

    async def emit_event(frame):
        emitted.append(bytes(frame.data))

    svc._tester.emit_event = emit_event
    return svc, emitted


@pytest.mark.asyncio
async def test_ad_flags_from_eir_extracts_flags():
    assert _ad_flags_from_eir(bytes([0x02, 0x01, 0x04])) == 0x04
    # Flags followed by a second AD structure must not confuse the scan.
    eir = bytes([0x02, 0x01, 0x02, 0x03, 0x09, 0x41, 0x42])
    assert _ad_flags_from_eir(eir) == 0x02
    assert _ad_flags_from_eir(b"") == 0
    assert _ad_flags_from_eir(bytes([0x03, 0x09, 0x41, 0x42])) == 0  # no Flags


@pytest.mark.asyncio
async def test_general_discovery_drops_non_discoverable_broadcast_device():
    """GAP/DISC/GENP/BV-03: a broadcast device (Flags=0x04, no discoverable bit)
    must not surface during General Discovery."""
    svc, emitted = _make_svc("general")
    svc._on_scan_result(_scan_result(flags=0x04))
    assert emitted == []


@pytest.mark.asyncio
async def test_general_discovery_reports_general_and_limited_discoverable():
    svc, emitted = _make_svc("general")
    svc._on_scan_result(_scan_result(flags=0x02))  # General Discoverable
    svc._on_scan_result(_scan_result(flags=0x01))  # Limited Discoverable
    await asyncio.sleep(0)  # flush the create_task'd emit_event
    assert len(emitted) == 2


@pytest.mark.asyncio
async def test_limited_discovery_drops_general_discoverable_device():
    """GAP/DISC/LIMP/BV-02: Limited Discovery must not find a General
    Discoverable device."""
    svc, emitted = _make_svc("limited")
    svc._on_scan_result(_scan_result(flags=0x02))
    await asyncio.sleep(0)
    assert emitted == []


@pytest.mark.asyncio
async def test_limited_discovery_reports_limited_discoverable():
    svc, emitted = _make_svc("limited")
    svc._on_scan_result(_scan_result(flags=0x01))
    await asyncio.sleep(0)
    assert len(emitted) == 1


@pytest.mark.asyncio
async def test_observe_reports_everything_including_non_discoverable():
    """Observation (OBSV) is a raw scan — no discoverable filtering."""
    svc, emitted = _make_svc("observe")
    svc._on_scan_result(_scan_result(flags=0x04))
    svc._on_scan_result(_scan_result(flags=0x00))
    await asyncio.sleep(0)
    assert len(emitted) == 2
