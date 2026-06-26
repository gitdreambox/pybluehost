"""BLEConnectionManager.set_phy — request + await LE_PHY_Update_Complete.

Stubs out the HCI layer so we exercise the wait/timeout/handle-filter logic
without needing a real transport.
"""
from __future__ import annotations

import asyncio

import pytest

from pybluehost.ble.gap import BLEConnectionManager
from pybluehost.hci.constants import LEPhy, LEPhyMask
from pybluehost.hci.packets import HCI_LE_Set_PHY, LEPhyUpdateComplete


class _StubHCI:
    """Records sent commands; manually fires queued LE_PHY_Update_Complete events."""

    def __init__(self):
        self.sent: list = []
        self._listeners: list = []
        self._le_phy_update_listeners = self._listeners  # mimic controller attr

    async def send_command(self, cmd):
        self.sent.append(cmd)
        # Simulated Command Status return — not checked by set_phy.

    def on_le_phy_update(self, listener) -> None:
        self._listeners.append(listener)

    def fire_phy_update(self, parsed: LEPhyUpdateComplete) -> None:
        for listener in list(self._listeners):
            listener(parsed)


@pytest.mark.asyncio
async def test_set_phy_sends_command_with_2m_mask():
    hci = _StubHCI()
    mgr = BLEConnectionManager(hci)

    async def fire_event_soon():
        await asyncio.sleep(0)
        hci.fire_phy_update(LEPhyUpdateComplete(
            status=0, connection_handle=0x0040,
            tx_phy=LEPhy.LE_2M, rx_phy=LEPhy.LE_2M,
        ))

    asyncio.create_task(fire_event_soon())
    result = await mgr.set_phy(0x0040, LEPhyMask.LE_2M, LEPhyMask.LE_2M)

    assert isinstance(hci.sent[0], HCI_LE_Set_PHY)
    assert hci.sent[0].connection_handle == 0x0040
    assert hci.sent[0].all_phys == 0
    assert hci.sent[0].tx_phys == LEPhyMask.LE_2M
    assert hci.sent[0].rx_phys == LEPhyMask.LE_2M
    assert result.tx_phy == LEPhy.LE_2M
    assert result.rx_phy == LEPhy.LE_2M
    assert result.status == 0


@pytest.mark.asyncio
async def test_set_phy_ignores_event_for_different_handle():
    """Race-safe: an unrelated PHY update on another connection must not unblock us."""
    hci = _StubHCI()
    mgr = BLEConnectionManager(hci)

    async def fire_two_events():
        await asyncio.sleep(0)
        # First event: wrong handle, should be filtered out.
        hci.fire_phy_update(LEPhyUpdateComplete(
            status=0, connection_handle=0x0099,
            tx_phy=LEPhy.LE_1M, rx_phy=LEPhy.LE_1M,
        ))
        # Second event: our handle, should resolve.
        await asyncio.sleep(0)
        hci.fire_phy_update(LEPhyUpdateComplete(
            status=0, connection_handle=0x0040,
            tx_phy=LEPhy.LE_2M, rx_phy=LEPhy.LE_2M,
        ))

    asyncio.create_task(fire_two_events())
    result = await mgr.set_phy(0x0040, LEPhyMask.LE_2M, LEPhyMask.LE_2M)
    assert result.connection_handle == 0x0040
    assert result.tx_phy == LEPhy.LE_2M


@pytest.mark.asyncio
async def test_set_phy_times_out_when_no_event_arrives():
    hci = _StubHCI()
    mgr = BLEConnectionManager(hci)
    with pytest.raises(asyncio.TimeoutError):
        await mgr.set_phy(
            0x0040, LEPhyMask.LE_2M, LEPhyMask.LE_2M, timeout_s=0.05,
        )


@pytest.mark.asyncio
async def test_set_phy_cleans_up_listener_on_success():
    hci = _StubHCI()
    mgr = BLEConnectionManager(hci)

    async def fire_event_soon():
        await asyncio.sleep(0)
        hci.fire_phy_update(LEPhyUpdateComplete(
            status=0, connection_handle=0x0040,
            tx_phy=LEPhy.LE_2M, rx_phy=LEPhy.LE_2M,
        ))

    asyncio.create_task(fire_event_soon())
    await mgr.set_phy(0x0040, LEPhyMask.LE_2M, LEPhyMask.LE_2M)
    # After the call, the temporary listener must be removed — otherwise
    # repeated PHY updates would leak callbacks and eventually grow memory.
    assert hci._listeners == []


@pytest.mark.asyncio
async def test_set_phy_cleans_up_listener_on_timeout():
    hci = _StubHCI()
    mgr = BLEConnectionManager(hci)
    with pytest.raises(asyncio.TimeoutError):
        await mgr.set_phy(0x0040, LEPhyMask.LE_2M, LEPhyMask.LE_2M, timeout_s=0.05)
    assert hci._listeners == []


@pytest.mark.asyncio
async def test_set_phy_surfaces_controller_failure_status():
    """If peer rejects PHY update, status != 0 — caller can inspect."""
    hci = _StubHCI()
    mgr = BLEConnectionManager(hci)

    async def fire_failure():
        await asyncio.sleep(0)
        hci.fire_phy_update(LEPhyUpdateComplete(
            status=0x1F, connection_handle=0x0040,
            tx_phy=LEPhy.LE_1M, rx_phy=LEPhy.LE_1M,
        ))

    asyncio.create_task(fire_failure())
    result = await mgr.set_phy(0x0040, LEPhyMask.LE_2M, LEPhyMask.LE_2M)
    assert result.status == 0x1F
    # Peer kept the old PHY (1M) — surface that fact too.
    assert result.tx_phy == LEPhy.LE_1M
