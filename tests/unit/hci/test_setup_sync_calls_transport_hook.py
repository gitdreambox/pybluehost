"""HCIController.setup_synchronous_connection calls transport.prepare_for_sco
with the correct codec string before sending the HCI command."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from pybluehost.hci.controller import HCIController
from pybluehost.hci.sco_constants import PRESET_CVSD_S1, PRESET_MSBC_T2


def _stub_controller_with_transport():
    """Build an HCIController with a mock transport that has prepare_for_sco."""
    transport = MagicMock()
    transport.prepare_for_sco = AsyncMock()
    transport.send = AsyncMock()
    ctrl = HCIController(transport=transport)
    return ctrl, transport


@pytest.mark.asyncio
async def test_setup_sync_connection_invokes_prepare_for_sco_msbc():
    ctrl, transport = _stub_controller_with_transport()

    async def fake_send_command(cmd):
        # Simulate Sync_Conn_Complete arriving for the pending future
        fut = ctrl._pending_sync_conn.get(0x0001)
        if fut and not fut.done():
            fut.set_result(0x0042)

    ctrl.send_command = fake_send_command

    sco_handle = await ctrl.setup_synchronous_connection(
        acl_handle=0x0001, preset=PRESET_MSBC_T2,
    )

    assert sco_handle == 0x0042
    transport.prepare_for_sco.assert_awaited_once_with("mSBC")


@pytest.mark.asyncio
async def test_setup_sync_connection_invokes_prepare_for_sco_cvsd():
    ctrl, transport = _stub_controller_with_transport()

    async def fake_send_command(cmd):
        fut = ctrl._pending_sync_conn.get(0x0001)
        if fut and not fut.done():
            fut.set_result(0x0099)

    ctrl.send_command = fake_send_command

    sco_handle = await ctrl.setup_synchronous_connection(
        acl_handle=0x0001, preset=PRESET_CVSD_S1,
    )

    assert sco_handle == 0x0099
    transport.prepare_for_sco.assert_awaited_once_with("CVSD")


@pytest.mark.asyncio
async def test_setup_sync_connection_tolerates_transport_without_hook():
    """Transports that don't define prepare_for_sco still work (legacy guard)."""
    transport = MagicMock(spec=["send"])   # no prepare_for_sco attr
    transport.send = AsyncMock()
    ctrl = HCIController(transport=transport)

    async def fake_send_command(cmd):
        fut = ctrl._pending_sync_conn.get(0x0001)
        if fut and not fut.done():
            fut.set_result(0x0033)

    ctrl.send_command = fake_send_command
    sco = await ctrl.setup_synchronous_connection(
        acl_handle=0x0001, preset=PRESET_CVSD_S1,
    )
    assert sco == 0x0033
