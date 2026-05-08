"""Verify ATT emits INFO/WARN logs at MTU exchange and Error_Response."""
from __future__ import annotations

import logging

import pytest

from pybluehost.ble.att import (
    ATT_Error_Response,
    ATT_Exchange_MTU_Response,
)


def test_mtu_exchange_response_logs_info(caplog):
    caplog.set_level(logging.INFO, logger="pybluehost.ble.att")
    pdu = ATT_Exchange_MTU_Response(server_rx_mtu=247)
    pdu.log_received()
    msgs = [r.getMessage() for r in caplog.records]
    assert any("MTU exchanged" in m and "247" in m for m in msgs)


def test_error_response_logs_warn(caplog):
    caplog.set_level(logging.WARNING, logger="pybluehost.ble.att")
    pdu = ATT_Error_Response(
        request_opcode_in_error=0x0A,
        attribute_handle_in_error=0x002A,
        error_code=0x05,
    )
    pdu.log_received()
    msgs = [r.getMessage() for r in caplog.records]
    assert any("0x002A" in m for m in msgs)
    assert any("Insufficient_Authentication" in m or "0x05" in m for m in msgs)
