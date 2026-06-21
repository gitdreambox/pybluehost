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
    classic_central_peripheral_pair, virtual_classic_link_or_real_rf, transport_mode,
):
    """central_peripheral_pair registers SPP service on peripheral;
    bridge attaches in virtual mode."""
    stack_c, stack_p = classic_central_peripheral_pair
    # SDP server has at least one registered record
    assert len(stack_p._sdp._records) >= 1
    if transport_mode == "virtual":
        # Peripheral is connectable + discoverable per the fixture.
        assert stack_p._virtual_controller._inquiry_scan is True
        assert stack_p._virtual_controller._page_scan is True
    else:
        # Hardware mode cannot observe controller scan-enable state through
        # VirtualController internals; successful fixture setup is the contract.
        assert virtual_classic_link_or_real_rf is None
        assert getattr(stack_p, "_virtual_controller", None) is None


import contextlib

from pybluehost.core.address import BDAddress


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_classic_sdp_browse(
    classic_central_peripheral_pair, virtual_classic_link_or_real_rf, transport_mode,
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
        disconnect_classic_and_wait, e2e_timeout,
    )

    stack_c, stack_p = classic_central_peripheral_pair
    if not _supports_classic_ssp(stack_c):
        pytest.skip("adapter does not support BR/EDR SSP")

    handle = None
    try:
        handle = await classic_discover_and_pair_jw(
            stack_c, stack_p._local_address,
            scan_timeout=e2e_timeout(transport_mode, virtual=3.0, usb=10.0),
            pair_timeout=e2e_timeout(transport_mode, virtual=3.0, usb=10.0),
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
                await disconnect_classic_and_wait(
                    stack_c, handle,
                    timeout=e2e_timeout(transport_mode, virtual=2.0, usb=5.0),
                )


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_classic_rfcomm_spp_echo(
    classic_central_peripheral_pair, virtual_classic_link_or_real_rf, transport_mode,
):
    """Open RFCOMM/SPP channel to the peripheral's echo handler; send two
    messages; verify both are echoed back."""
    import asyncio

    from pybluehost.classic.sdp import SDPClient
    from pybluehost.classic.spp import SPPClient
    from pybluehost.l2cap.constants import PSM_SDP

    from tests.e2e._helpers import (
        _supports_classic_ssp, classic_discover_and_pair_jw,
        disconnect_classic_and_wait, e2e_timeout,
    )

    stack_c, stack_p = classic_central_peripheral_pair
    if not _supports_classic_ssp(stack_c):
        pytest.skip("adapter does not support BR/EDR SSP")

    handle = None
    spp_conn = None
    try:
        handle = await classic_discover_and_pair_jw(
            stack_c, stack_p._local_address,
            scan_timeout=e2e_timeout(transport_mode, virtual=3.0, usb=10.0),
            pair_timeout=e2e_timeout(transport_mode, virtual=3.0, usb=10.0),
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
        echoed = await asyncio.wait_for(spp_conn.recv(), timeout=e2e_timeout(transport_mode, virtual=1.0, usb=3.0))
        assert echoed == b"hello classic\n"

        # Second echo
        await spp_conn.send(b"second line\n")
        echoed2 = await asyncio.wait_for(spp_conn.recv(), timeout=e2e_timeout(transport_mode, virtual=1.0, usb=3.0))
        assert echoed2 == b"second line\n"

    finally:
        if spp_conn is not None:
            with contextlib.suppress(Exception):
                await spp_conn.close()
        if handle is not None:
            with contextlib.suppress(Exception):
                await disconnect_classic_and_wait(
                    stack_c, handle,
                    timeout=e2e_timeout(transport_mode, virtual=2.0, usb=5.0),
                )


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
    from tests._transport_resolve import build_stack_from_spec
    from tests.e2e._helpers import (
        _supports_classic_ssp, classic_discover_and_pair_jw,
        classic_discover_peripheral, disconnect_classic_and_wait, e2e_timeout,
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
        if transport_mode == "virtual":
            stack_c = await Stack.virtual(config=cfg_c, address=central_addr)
            stack_p = await Stack.virtual(config=cfg_p, address=peripheral_addr)
            link = VirtualClassicLink(
                central=stack_c._virtual_controller,
                peripheral=stack_p._virtual_controller,
                central_address=central_addr,
                peripheral_address=peripheral_addr,
                page_timeout_seconds=0.5,
            )
            link.attach()
        else:
            stack_c = await build_stack_from_spec(selected_transport_spec, config=cfg_c)
            stack_p = await build_stack_from_spec(selected_peer_spec, config=cfg_p)
            link = None
        service = register_spp_echo_service(stack_p)
        await service.register(channel=SPP_SERVER_CHANNEL, name=SPP_SERVICE_NAME)
        await stack_p.gap.classic_discoverability.set_connectable(True)
        await stack_p.gap.classic_discoverability.set_discoverable(True)
        return stack_c, stack_p, link

    async def _close_pair(stack_c, stack_p, link):
        if link is not None:
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
    if transport_mode != "virtual":
        central_addr = stack_c._local_address
        peripheral_addr = stack_p._local_address

    handle = None
    try:
        handle = await classic_discover_and_pair_jw(
            stack_c, peripheral_addr,
            scan_timeout=e2e_timeout(transport_mode, virtual=3.0, usb=20.0),
            pair_timeout=e2e_timeout(transport_mode, virtual=3.0, usb=15.0),
        )
        bond_c = await JsonBondStorage(bonds_c_path).load_bond(peripheral_addr)
        assert bond_c is not None, "central bond not persisted after pair"
        assert bond_c.link_key_type in {0x04, 0x05}, (
            "expected P-192 combination link key (0x04 unauthenticated "
            f"or 0x05 authenticated), got {bond_c.link_key_type!r}"
        )
        with contextlib.suppress(Exception):
            await disconnect_classic_and_wait(
                stack_c, handle,
                timeout=e2e_timeout(transport_mode, virtual=2.0, usb=5.0),
            )
    finally:
        await _close_pair(stack_c, stack_p, link)

    # ===== Session 2 =====
    stack_c, stack_p, link = await _open_pair()
    if transport_mode != "virtual":
        central_addr = stack_c._local_address
        peripheral_addr = stack_p._local_address
    handle = None
    try:
        await classic_discover_peripheral(stack_c, peripheral_addr, timeout=e2e_timeout(transport_mode, virtual=3.0, usb=20.0))
        await asyncio.sleep(e2e_timeout(transport_mode, virtual=0.05, usb=0.5))
        handle = await stack_c.connect_classic(peripheral_addr, timeout=e2e_timeout(transport_mode, virtual=3.0, usb=20.0))
        await stack_c.authenticate_classic(handle, timeout=e2e_timeout(transport_mode, virtual=3.0, usb=15.0))
        await stack_c.enable_classic_encryption(handle, timeout=e2e_timeout(transport_mode, virtual=2.0, usb=5.0))

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
                await disconnect_classic_and_wait(
                    stack_c, handle,
                    timeout=e2e_timeout(transport_mode, virtual=2.0, usb=5.0),
                )
        await _close_pair(stack_c, stack_p, link)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_classic_ssp_numeric_comparison_persists_bond(
    tmp_path, selected_transport_spec, selected_peer_spec, transport_mode,
):
    """SSP Numeric Comparison success path persists authenticated link keys.

    The delegates record User_Confirmation requests, so this test proves the
    success case exercised SSP confirmation rather than only link setup.
    """
    import contextlib

    from pybluehost.ble.security import SecurityConfig
    from pybluehost.ble.smp import AutoAcceptDelegate, JsonBondStorage
    from pybluehost.core.address import BDAddress
    from pybluehost.core.types import IOCapability
    from pybluehost.hci.virtual_classic_link import VirtualClassicLink
    from pybluehost.stack import Stack, StackConfig
    from tests._transport_resolve import build_stack_from_spec
    from tests.e2e._classic_test_service import (
        SPP_SERVER_CHANNEL, SPP_SERVICE_NAME, register_spp_echo_service,
    )
    from tests.e2e._helpers import (
        _supports_classic_ssp, classic_discover_and_pair_jw,
        disconnect_classic_and_wait, e2e_timeout,
    )

    class _AcceptNumeric(AutoAcceptDelegate):
        def __init__(self) -> None:
            self.calls: list[tuple[object, int]] = []

        async def confirm_numeric(self, peer_addr, value):
            self.calls.append((peer_addr, value))
            return True

    central_delegate = _AcceptNumeric()
    peripheral_delegate = _AcceptNumeric()
    central_addr = BDAddress.from_string("0A:0A:0A:0A:0A:0A")
    peripheral_addr = BDAddress.from_string("0B:0B:0B:0B:0B:0B")
    bonds_c_path = tmp_path / "classic_nc_bonds_c.json"
    bonds_p_path = tmp_path / "classic_nc_bonds_p.json"

    cfg_c = StackConfig(
        bond_storage=JsonBondStorage(bonds_c_path),
        security=SecurityConfig(enable_secure_connections=False, mitm_required=True),
        classic_io_capability=IOCapability.DISPLAY_YES_NO,
    )
    cfg_p = StackConfig(
        bond_storage=JsonBondStorage(bonds_p_path),
        security=SecurityConfig(enable_secure_connections=False, mitm_required=True),
        classic_io_capability=IOCapability.DISPLAY_YES_NO,
    )
    stack_c = None
    stack_p = None
    link = None
    handle = None
    try:
        if transport_mode == "virtual":
            stack_c = await Stack.virtual(config=cfg_c, address=central_addr)
            stack_p = await Stack.virtual(config=cfg_p, address=peripheral_addr)
            link = VirtualClassicLink(
                central=stack_c._virtual_controller,
                peripheral=stack_p._virtual_controller,
                central_address=central_addr,
                peripheral_address=peripheral_addr,
                page_timeout_seconds=0.5,
            )
            link.attach()
        else:
            stack_c = await build_stack_from_spec(selected_transport_spec, config=cfg_c)
            stack_p = await build_stack_from_spec(selected_peer_spec, config=cfg_p)
            peripheral_addr = stack_p._local_address

        if not _supports_classic_ssp(stack_c):
            pytest.skip("adapter does not support BR/EDR SSP")

        service = register_spp_echo_service(stack_p)
        await service.register(channel=SPP_SERVER_CHANNEL, name=SPP_SERVICE_NAME)
        await stack_p.gap.classic_discoverability.set_connectable(True)
        await stack_p.gap.classic_discoverability.set_discoverable(True)
        stack_c.gap.set_pairing_delegate(central_delegate)
        stack_p.gap.set_pairing_delegate(peripheral_delegate)

        handle = await classic_discover_and_pair_jw(
            stack_c,
            peripheral_addr,
            scan_timeout=e2e_timeout(transport_mode, virtual=3.0, usb=20.0),
            pair_timeout=e2e_timeout(transport_mode, virtual=3.0, usb=15.0),
        )
        bond_c = await JsonBondStorage(bonds_c_path).load_bond(peripheral_addr)
        assert bond_c is not None, "central classic bond not persisted"
        assert bond_c.link_key, "classic bond missing link key"
        assert bond_c.link_key_type in {0x05, 0x07}
        assert central_delegate.calls or peripheral_delegate.calls
    finally:
        if handle is not None and stack_c is not None:
            with contextlib.suppress(Exception):
                await disconnect_classic_and_wait(
                    stack_c,
                    handle,
                    timeout=e2e_timeout(transport_mode, virtual=2.0, usb=5.0),
                )
        if link is not None:
            with contextlib.suppress(Exception):
                await link.disconnect()
        if stack_c is not None:
            with contextlib.suppress(Exception):
                await stack_c.close()
        if stack_p is not None:
            with contextlib.suppress(Exception):
                await stack_p.close()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_classic_pair_failure_disconnects_cleanly(
    classic_central_peripheral_pair, virtual_classic_link_or_real_rf, transport_mode,
):
    """Inject a Peripheral SSP handler that rejects User_Confirmation →
    stack.authenticate_classic() raises → connection disconnect + stack
    teardown both complete within 2s. Regression guard against leaked
    auth-completion futures.
    """
    import asyncio

    from tests.e2e._helpers import (
        _supports_classic_ssp, classic_discover_peripheral,
        disconnect_classic_and_wait, e2e_timeout,
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

    stack_p.gap.set_pairing_delegate(_RejectClassicConfirm())

    handle = None
    try:
        await classic_discover_peripheral(
            stack_c, stack_p._local_address, timeout=e2e_timeout(transport_mode, virtual=3.0, usb=20.0),
        )
        handle = await stack_c.connect_classic(
            stack_p._local_address, timeout=e2e_timeout(transport_mode, virtual=3.0, usb=20.0),
        )

        # Authenticate must raise on Auth_Complete with non-zero status.
        with pytest.raises(Exception, match=r"(authentication|Auth_Complete|SSP|status|fail)"):
            await stack_c.authenticate_classic(handle, timeout=e2e_timeout(transport_mode, virtual=3.0, usb=15.0))

        # Critical: cleanup completes within budget.
        await disconnect_classic_and_wait(
            stack_c, handle,
            timeout=e2e_timeout(transport_mode, virtual=2.0, usb=5.0),
        )
    finally:
        # fixture teardown closes both stacks within 2s
        pass
