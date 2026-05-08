"""Verify GATT emits INFO logs at service discovery + CCCD subscription."""
from __future__ import annotations

import logging


def test_service_discovery_complete_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.ble.gatt")
    from pybluehost.ble.gatt import _log_service_discovery_complete

    _log_service_discovery_complete(handle=0x40, num_services=5)
    assert any("5 services" in r.getMessage() and "0x0040" in r.getMessage() for r in caplog.records)


def test_cccd_subscription_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.ble.gatt")
    from pybluehost.ble.gatt import _log_cccd_subscribed

    _log_cccd_subscribed(handle=0x40, char_handle=0x002A, char_name="Heart_Rate_Measurement")
    msgs = [r.getMessage() for r in caplog.records]
    assert any("0x002A" in m and "Heart_Rate_Measurement" in m for m in msgs)
