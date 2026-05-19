"""Test-scoped fixtures for tests/e2e/.

The session-level `stack`, `peer_stack`, `transport_mode`, `selected_transport_spec`
fixtures come from tests/conftest.py and are not re-exported here.
"""
from __future__ import annotations

import pytest_asyncio

from pybluehost.hci.virtual_link import VirtualLELink

from tests.e2e._test_service import build_test_service


@pytest_asyncio.fixture
async def central_peripheral_pair(stack, peer_stack):
    """Yields (stack_central, stack_peripheral) with the E2E test service
    registered on the Peripheral.

    `stack` and `peer_stack` come from tests/conftest.py session fixtures and
    are already initialized for the active --transport / --transport-peer.
    """
    peer_stack._gatt_server.add_service(build_test_service())
    yield stack, peer_stack


@pytest_asyncio.fixture
async def virtual_link_or_real_rf(central_peripheral_pair, transport_mode):
    """Virtual: bridge the two virtual controllers with a VirtualLELink.
    Hardware: yield None — real RF connects them naturally.
    """
    stack_c, stack_p = central_peripheral_pair
    if transport_mode == "virtual":
        link = VirtualLELink(
            central=stack_c._virtual_controller,
            peripheral=stack_p._virtual_controller,
            central_address=stack_c._local_address,
            peripheral_address=stack_p._local_address,
        )
        try:
            yield link
        finally:
            try:
                await link.disconnect()
            except Exception:
                pass
    else:
        yield None
