"""Test-scoped fixtures for tests/e2e/.

The session-level `stack`, `peer_stack`, `transport_mode`, `selected_transport_spec`
fixtures come from tests/conftest.py and are not re-exported here.
"""
from __future__ import annotations

import pytest_asyncio

from pybluehost.hci.virtual_classic_link import VirtualClassicLink
from pybluehost.hci.virtual_link import VirtualLELink

from tests.e2e._classic_test_service import (
    SPP_SERVER_CHANNEL,
    SPP_SERVICE_NAME,
    register_spp_echo_service,
)
from tests.e2e._test_service import build_test_service


@pytest_asyncio.fixture
async def central_peripheral_pair(
    stack, peer_stack, selected_transport_spec, selected_peer_spec, transport_mode,
):
    """Yields (stack_central, stack_peripheral) with the E2E test service
    registered on the Peripheral.

    `stack` and `peer_stack` come from tests/conftest.py session fixtures and
    are already initialized for the active --transport / --transport-peer.
    """
    from tests.e2e._helpers import le_role_swap_required

    if le_role_swap_required(
        selected_transport_spec, selected_peer_spec, transport_mode,
    ):
        stack_c, stack_p = peer_stack, stack
    else:
        stack_c, stack_p = stack, peer_stack
    stack_p._gatt_server.add_service(build_test_service())
    yield stack_c, stack_p


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


@pytest_asyncio.fixture
async def classic_central_peripheral_pair(stack, peer_stack):
    """Register SPP service on Peripheral + set connectable + discoverable.

    Yields (stack_central, stack_peripheral) ready for Classic workflow scenarios.
    """
    service = register_spp_echo_service(peer_stack)
    await service.register(channel=SPP_SERVER_CHANNEL, name=SPP_SERVICE_NAME)
    await peer_stack.gap.classic_discoverability.set_connectable(True)
    await peer_stack.gap.classic_discoverability.set_discoverable(True)
    yield stack, peer_stack


@pytest_asyncio.fixture
async def virtual_classic_link_or_real_rf(classic_central_peripheral_pair, transport_mode):
    """Virtual: build + attach a VirtualClassicLink. Hardware: yield None."""
    stack_c, stack_p = classic_central_peripheral_pair
    if transport_mode == "virtual":
        link = VirtualClassicLink(
            central=stack_c._virtual_controller,
            peripheral=stack_p._virtual_controller,
            central_address=stack_c._local_address,
            peripheral_address=stack_p._local_address,
            page_timeout_seconds=0.5,
        )
        link.attach()
        try:
            yield link
        finally:
            try:
                await link.disconnect()
            except Exception:
                pass
    else:
        yield None
