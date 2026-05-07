"""Verify L2CAPManager emits INFO logs for connection lifecycle events."""
from __future__ import annotations

import logging

import pytest

from pybluehost.core.types import LinkType
from pybluehost.l2cap.manager import L2CAPManager


@pytest.mark.asyncio
async def test_on_connection_emits_info_log(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.l2cap")
    mgr = L2CAPManager(hci=object())
    await mgr.on_connection(
        handle=0x40,
        link_type=LinkType.LE,
        peer_address=b"\x06\x05\x04\x03\x02\x01",
        role=0,
    )
    msgs = [r.getMessage() for r in caplog.records]
    assert any("0x0040" in m for m in msgs)


@pytest.mark.asyncio
async def test_on_disconnection_emits_info_log(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.l2cap")
    mgr = L2CAPManager(hci=object())
    await mgr.on_connection(
        handle=0x40,
        link_type=LinkType.LE,
        peer_address=b"\x06\x05\x04\x03\x02\x01",
        role=0,
    )
    caplog.clear()
    await mgr.on_disconnection(handle=0x40, reason=0x16)
    msgs = [r.getMessage() for r in caplog.records]
    assert any(
        "0x0040" in m and ("disconnect" in m.lower() or "closed" in m.lower())
        for m in msgs
    )
