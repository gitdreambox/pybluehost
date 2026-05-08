"""Verify HCIController emits INFO logs at LE_Connection_Complete / Disconnection_Complete."""
from __future__ import annotations

import logging


def test_le_connection_complete_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.hci.connection")
    from pybluehost.hci.controller import _log_le_connection_complete

    _log_le_connection_complete(handle=0x40, peer_addr="6E:1A:9C:81:5C:24", role=0, interval_ms=30.0)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("0x0040" in m and "Central" in m for m in msgs)


def test_disconnection_complete_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.hci.connection")
    from pybluehost.hci.controller import _log_disconnection_complete

    _log_disconnection_complete(handle=0x40, reason=0x08)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("Connection_Timeout" in m for m in msgs)
