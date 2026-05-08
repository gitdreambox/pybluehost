"""Verify RFCOMM emits INFO/WARN logs."""
from __future__ import annotations

import logging


def test_channel_opened_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.classic.rfcomm")
    from pybluehost.classic.rfcomm import _log_channel_opened

    _log_channel_opened(dlci=0x06, channel=3, mtu=1024)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("DLCI=0x06" in m and "channel 3" in m and "MTU=1024" in m for m in msgs)


def test_channel_disconnect_abnormal_logs_warn(caplog):
    caplog.set_level(logging.WARNING, logger="pybluehost.classic.rfcomm")
    from pybluehost.classic.rfcomm import _log_channel_disconnect_abnormal

    _log_channel_disconnect_abnormal(dlci=0x06, reason="link_loss")
    msgs = [r.getMessage() for r in caplog.records]
    assert any("DLCI=0x06" in m and "link_loss" in m for m in msgs)
