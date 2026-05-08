"""Verify SDP emits INFO/WARN logs."""
from __future__ import annotations

import logging


def test_service_search_complete_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.classic.sdp")
    from pybluehost.classic.sdp import _log_service_search_complete

    _log_service_search_complete(uuid=0x1101, num_records=3)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("0x1101" in m and "3" in m for m in msgs)


def test_service_search_timeout_logs_warn(caplog):
    caplog.set_level(logging.WARNING, logger="pybluehost.classic.sdp")
    from pybluehost.classic.sdp import _log_service_search_timeout

    _log_service_search_timeout(uuid=0x1101)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("timeout" in m.lower() and "0x1101" in m for m in msgs)
