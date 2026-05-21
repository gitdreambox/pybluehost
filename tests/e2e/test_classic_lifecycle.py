"""End-to-end BR/EDR (Classic) workflow scenarios."""
from __future__ import annotations

import pytest


def test_classic_test_service_constants():
    """build helpers + constants are importable and self-consistent."""
    from tests.e2e._classic_test_service import (
        SPP_SERVER_CHANNEL,
        SPP_CLASS_UUID,
        SPP_SERVICE_NAME,
        register_spp_echo_service,
    )
    assert SPP_SERVER_CHANNEL == 1
    assert SPP_CLASS_UUID == 0x1101
    assert SPP_SERVICE_NAME == "PBH-E2E SPP"
    assert callable(register_spp_echo_service)


@pytest.mark.asyncio
async def test_supports_classic_ssp_virtual_short_circuits_true():
    from pybluehost.stack import Stack
    from pybluehost.core.address import BDAddress
    from tests.e2e._helpers import _supports_classic_ssp

    stack = await Stack.virtual(address=BDAddress.from_string("0A:0A:0A:0A:0A:0A"))
    try:
        assert _supports_classic_ssp(stack) is True
    finally:
        await stack.close()
