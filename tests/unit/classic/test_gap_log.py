"""Verify Classic GAP + SSP emit INFO logs."""
from __future__ import annotations

import logging


def test_inquiry_started_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.classic.gap")
    from pybluehost.classic.gap import _log_inquiry_started

    _log_inquiry_started(duration_ms=10240)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("Inquiry started" in m for m in msgs)


def test_inquiry_complete_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.classic.gap")
    from pybluehost.classic.gap import _log_inquiry_complete

    _log_inquiry_complete(num_devices=4)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("4 devices" in m for m in msgs)


def test_ssp_user_confirmation_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.ble.smp")
    from pybluehost.ble.security import _log_ssp_user_confirmation

    _log_ssp_user_confirmation(handle=0x40, numeric_value=123456)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("123456" in m and "0x0040" in m for m in msgs)
