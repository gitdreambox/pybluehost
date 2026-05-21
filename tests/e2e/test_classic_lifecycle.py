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


@pytest.mark.asyncio
async def test_classic_fixtures_load_and_register_service(
    classic_central_peripheral_pair, virtual_classic_link_or_real_rf,
):
    """central_peripheral_pair registers SPP service on peripheral;
    bridge attaches in virtual mode."""
    stack_c, stack_p = classic_central_peripheral_pair
    # SDP server has at least one registered record
    assert len(stack_p._sdp._records) >= 1
    # Peripheral is connectable + discoverable per the fixture
    assert stack_p._virtual_controller._inquiry_scan is True
    assert stack_p._virtual_controller._page_scan is True


import contextlib

from pybluehost.core.address import BDAddress


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_classic_sdp_browse(
    classic_central_peripheral_pair, virtual_classic_link_or_real_rf,
):
    """Connect + SSP JW pair, then SDP search-attributes for the SPP record.

    Asserts the registered SPP service is found and the RFCOMM channel
    number embedded in ProtocolDescriptorList matches SPP_SERVER_CHANNEL.
    """
    from pybluehost.classic.sdp import SDPClient
    from pybluehost.l2cap.constants import PSM_SDP

    from tests.e2e._classic_test_service import (
        SPP_CLASS_UUID, SPP_SERVER_CHANNEL,
    )
    from tests.e2e._helpers import (
        _supports_classic_ssp, classic_discover_and_pair_jw,
    )

    stack_c, stack_p = classic_central_peripheral_pair
    if not _supports_classic_ssp(stack_c):
        pytest.skip("adapter does not support BR/EDR SSP")

    handle = None
    try:
        handle = await classic_discover_and_pair_jw(
            stack_c, stack_p._local_address,
        )

        # Open an L2CAP channel on the SDP PSM (0x0001) to feed SDPClient.
        l2cap_channel = await stack_c._l2cap.connect_classic_channel(
            handle, psm=PSM_SDP,
        )
        client = SDPClient(l2cap=l2cap_channel)

        channel = await client.find_rfcomm_channel(
            target=handle, service_uuid=SPP_CLASS_UUID,
        )
        assert channel == SPP_SERVER_CHANNEL, (
            f"find_rfcomm_channel returned {channel!r}, "
            f"expected {SPP_SERVER_CHANNEL}"
        )
    finally:
        if handle is not None:
            with contextlib.suppress(Exception):
                await stack_c.gap.classic_connections.disconnect(handle)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_classic_rfcomm_spp_echo(
    classic_central_peripheral_pair, virtual_classic_link_or_real_rf,
):
    """Open RFCOMM/SPP channel to the peripheral's echo handler; send two
    messages; verify both are echoed back."""
    import asyncio

    from pybluehost.classic.sdp import SDPClient
    from pybluehost.classic.spp import SPPClient
    from pybluehost.l2cap.constants import PSM_SDP

    from tests.e2e._helpers import (
        _supports_classic_ssp, classic_discover_and_pair_jw,
    )

    stack_c, stack_p = classic_central_peripheral_pair
    if not _supports_classic_ssp(stack_c):
        pytest.skip("adapter does not support BR/EDR SSP")

    handle = None
    spp_conn = None
    try:
        handle = await classic_discover_and_pair_jw(
            stack_c, stack_p._local_address,
        )

        # SDP client needs an L2CAP channel on PSM_SDP for SPPClient's
        # internal service discovery.
        sdp_chan = await stack_c._l2cap.connect_classic_channel(
            handle, psm=PSM_SDP,
        )
        sdp_client = SDPClient(l2cap=sdp_chan)
        spp_client = SPPClient(rfcomm=stack_c._rfcomm, sdp_client=sdp_client)

        spp_conn = await spp_client.connect(target=handle)

        # First echo
        await spp_conn.send(b"hello classic\n")
        echoed = await asyncio.wait_for(spp_conn.recv(), timeout=1.0)
        assert echoed == b"hello classic\n"

        # Second echo
        await spp_conn.send(b"second line\n")
        echoed2 = await asyncio.wait_for(spp_conn.recv(), timeout=1.0)
        assert echoed2 == b"second line\n"

    finally:
        if spp_conn is not None:
            with contextlib.suppress(Exception):
                await spp_conn.close()
        if handle is not None:
            with contextlib.suppress(Exception):
                await stack_c.gap.classic_connections.disconnect(handle)
