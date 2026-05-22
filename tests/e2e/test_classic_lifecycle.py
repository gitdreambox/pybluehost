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


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_classic_bonded_reconnect_auto_encrypt(
    tmp_path, selected_transport_spec, selected_peer_spec, transport_mode,
):
    """Two-session lifecycle. Session 1 pairs (SSP JW) -> bond persisted on
    disk. Session 2 reopens fresh stacks at the same storage paths; the
    Link_Key_Request handler on the central side replies with the stored
    key; the bridge recognizes this positive-reply path and emits
    Auth_Complete directly; no IO_Capability flow; encryption succeeds;
    SDP browse confirms the link is usable."""
    import asyncio
    import contextlib

    from pybluehost.ble.security import SecurityConfig
    from pybluehost.ble.smp import JsonBondStorage
    from pybluehost.classic.sdp import SDPClient
    from pybluehost.core.address import BDAddress
    from pybluehost.hci.virtual_classic_link import VirtualClassicLink
    from pybluehost.l2cap.constants import PSM_SDP
    from pybluehost.stack import Stack, StackConfig

    from tests.e2e._classic_test_service import (
        SPP_CLASS_UUID, SPP_SERVER_CHANNEL, SPP_SERVICE_NAME,
        register_spp_echo_service,
    )
    from tests.e2e._helpers import (
        _supports_classic_ssp, classic_discover_and_pair_jw,
        classic_discover_peripheral,
    )

    if transport_mode != "virtual":
        pytest.skip(
            "hardware mode: build_stack_from_spec doesn't accept config= yet"
        )

    central_addr = BDAddress.from_string("0A:0A:0A:0A:0A:0A")
    peripheral_addr = BDAddress.from_string("0B:0B:0B:0B:0B:0B")
    bonds_c_path = tmp_path / "bonds_c.json"
    bonds_p_path = tmp_path / "bonds_p.json"

    async def _open_pair():
        cfg_c = StackConfig(
            bond_storage=JsonBondStorage(bonds_c_path),
            security=SecurityConfig(enable_secure_connections=False),
        )
        cfg_p = StackConfig(
            bond_storage=JsonBondStorage(bonds_p_path),
            security=SecurityConfig(enable_secure_connections=False),
        )
        stack_c = await Stack.virtual(config=cfg_c, address=central_addr)
        stack_p = await Stack.virtual(config=cfg_p, address=peripheral_addr)
        service = register_spp_echo_service(stack_p)
        await service.register(channel=SPP_SERVER_CHANNEL, name=SPP_SERVICE_NAME)
        await stack_p.gap.classic_discoverability.set_connectable(True)
        await stack_p.gap.classic_discoverability.set_discoverable(True)
        link = VirtualClassicLink(
            central=stack_c._virtual_controller,
            peripheral=stack_p._virtual_controller,
            central_address=central_addr,
            peripheral_address=peripheral_addr,
            page_timeout_seconds=0.5,
        )
        link.attach()
        return stack_c, stack_p, link

    async def _close_pair(stack_c, stack_p, link):
        with contextlib.suppress(Exception):
            await link.disconnect()
        with contextlib.suppress(Exception):
            await stack_c.close()
        with contextlib.suppress(Exception):
            await stack_p.close()

    # ===== Session 1 =====
    stack_c, stack_p, link = await _open_pair()
    if not _supports_classic_ssp(stack_c):
        await _close_pair(stack_c, stack_p, link)
        pytest.skip("adapter does not support BR/EDR SSP")

    handle = None
    try:
        handle = await classic_discover_and_pair_jw(
            stack_c, peripheral_addr,
        )
        bond_c = await JsonBondStorage(bonds_c_path).load_bond(peripheral_addr)
        assert bond_c is not None, "central bond not persisted after pair"
        assert bond_c.link_key_type == 0x05, (
            f"expected Combination_Key (0x05), got {bond_c.link_key_type!r}"
        )
        with contextlib.suppress(Exception):
            await stack_c.gap.classic_connections.disconnect(handle)
    finally:
        await _close_pair(stack_c, stack_p, link)

    # ===== Session 2 =====
    stack_c, stack_p, link = await _open_pair()
    handle = None
    try:
        await classic_discover_peripheral(stack_c, peripheral_addr, timeout=3.0)
        handle = await stack_c.connect_classic(peripheral_addr, timeout=3.0)
        await stack_c.authenticate_classic(handle, timeout=3.0)
        await stack_c.enable_classic_encryption(handle, timeout=2.0)

        # Verify the encrypted link works for an SDP query.
        sdp_chan = await stack_c._l2cap.connect_classic_channel(handle, psm=PSM_SDP)
        sdp_client = SDPClient(l2cap=sdp_chan)
        channel = await sdp_client.find_rfcomm_channel(
            target=handle, service_uuid=SPP_CLASS_UUID,
        )
        assert channel == SPP_SERVER_CHANNEL
    finally:
        if handle is not None:
            with contextlib.suppress(Exception):
                await stack_c.gap.classic_connections.disconnect(handle)
        await _close_pair(stack_c, stack_p, link)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_classic_pair_failure_disconnects_cleanly(
    classic_central_peripheral_pair, virtual_classic_link_or_real_rf,
):
    """Inject a Peripheral SSP handler that rejects User_Confirmation →
    stack.authenticate_classic() raises → connection disconnect + stack
    teardown both complete within 2s. Regression guard against leaked
    auth-completion futures.
    """
    import asyncio

    from tests.e2e._helpers import (
        _supports_classic_ssp, classic_discover_peripheral,
    )

    stack_c, stack_p = classic_central_peripheral_pair
    if not _supports_classic_ssp(stack_c):
        pytest.skip("adapter does not support BR/EDR SSP")

    # Inject a rejecting delegate on the peripheral. SSPManager checks
    # delegate.confirm_numeric FIRST (preferred over the legacy sync
    # on_user_confirmation handler), so we must override the delegate to
    # propagate the rejection — the legacy handler would be ignored when
    # the stack already has an auto-accept SMP delegate plumbed in.
    from pybluehost.ble.smp import AutoAcceptDelegate

    class _RejectClassicConfirm(AutoAcceptDelegate):
        async def confirm_numeric(self, peer_addr, value):
            return False

    stack_p.gap.classic_ssp._delegate = _RejectClassicConfirm()

    handle = None
    try:
        await classic_discover_peripheral(
            stack_c, stack_p._local_address, timeout=3.0,
        )
        handle = await stack_c.connect_classic(
            stack_p._local_address, timeout=3.0,
        )

        # Authenticate must raise on Auth_Complete with non-zero status.
        with pytest.raises(Exception, match=r"(authentication|Auth_Complete|SSP|status|fail)"):
            await stack_c.authenticate_classic(handle, timeout=3.0)

        # Critical: cleanup completes within 2s.
        await asyncio.wait_for(
            stack_c.gap.classic_connections.disconnect(handle), timeout=2.0,
        )
    finally:
        # fixture teardown closes both stacks within 2s
        pass
