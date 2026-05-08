"""Verify SMP emits INFO/WARN logs at pairing lifecycle events."""
from __future__ import annotations

import logging


def test_pairing_started_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.ble.smp")
    from pybluehost.ble.smp import _log_pairing_started

    _log_pairing_started(handle=0x40, io_caps="DisplayYesNo", bonding=True, mitm=True)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("DisplayYesNo" in m for m in msgs)


def test_pairing_failed_logs_warn(caplog):
    caplog.set_level(logging.WARNING, logger="pybluehost.ble.smp")
    from pybluehost.ble.smp import _log_pairing_failed

    _log_pairing_failed(handle=0x40, reason=0x05)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("0x05" in m or "Pairing_Not_Supported" in m for m in msgs)


def test_pairing_complete_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.ble.smp")
    from pybluehost.ble.smp import _log_pairing_complete

    _log_pairing_complete(handle=0x40, peer_addr="6E:1A:9C:81:5C:24", ltk_stored=True)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("paired" in m.lower() and "6E:1A:9C:81:5C:24" in m for m in msgs)
