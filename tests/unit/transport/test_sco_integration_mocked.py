"""Full SCO setup flow integration test (mocked Intel USB transport).

Drives HCIController.setup_synchronous_connection end-to-end:
  codec inference → prepare_for_sco("mSBC")
                  → INTEL_SCO_ALT_BY_CODEC["mSBC"] = 6
                  → select_sco_alt_setting(6)
                  → _device.set_interface_altsetting(0, 6)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pybluehost.hci.controller import HCIController
from pybluehost.hci.sco_constants import PRESET_CVSD_S1, PRESET_MSBC_T2
from pybluehost.transport.usb.intel import IntelUSBTransport


def _iso_ep(addr: int, direction_in: bool) -> MagicMock:
    ep = MagicMock()
    ep.bEndpointAddress = addr | (0x80 if direction_in else 0)
    ep.bmAttributes = 0x01
    return ep


def _build_intel_transport_with_iso_eps():
    """Construct an IntelUSBTransport whose USB device pretends to have
    iso IN/OUT endpoints on Alt 6 (mSBC)."""
    t = IntelUSBTransport.__new__(IntelUSBTransport)
    t._device = MagicMock()
    t._is_open = True
    t._sink = None
    t._reader_tasks = []
    t._ep_iso_in = None
    t._ep_iso_out = None
    t._current_alt_setting = 0
    t._iso_reader_task = None

    iface = MagicMock()
    iface.endpoints.return_value = [_iso_ep(0x83, True), _iso_ep(0x03, False)]
    cfg = t._device.get_active_configuration.return_value
    cfg.__getitem__.side_effect = (
        lambda key: iface if key[0] == 0 and key[1] in (1, 6) else (_ for _ in ()).throw(KeyError(key))
    )
    return t


@pytest.mark.asyncio
async def test_full_sco_setup_flow_intel_msbc():
    transport = _build_intel_transport_with_iso_eps()
    transport.send = AsyncMock()

    ctrl = HCIController(transport=transport)

    async def fake_send_command(cmd):
        fut = ctrl._pending_sync_conn.get(0x000A)
        if fut and not fut.done():
            fut.set_result(0x00FE)
    ctrl.send_command = fake_send_command

    with patch("usb.util.find_descriptor") as fd, \
         patch("usb.util.endpoint_direction") as ed, \
         patch("usb.util.endpoint_type") as et:
        fd.side_effect = lambda iface, custom_match=None: next(
            (e for e in iface.endpoints() if custom_match(e)), None,
        )
        ed.side_effect = lambda addr: 0x80 if (addr & 0x80) else 0x00
        et.side_effect = lambda attrs: attrs & 0x03

        sco_handle = await ctrl.setup_synchronous_connection(
            acl_handle=0x000A, preset=PRESET_MSBC_T2,
        )

    assert sco_handle == 0x00FE
    transport._device.set_interface_altsetting.assert_called_once_with(
        interface=0, alternate_setting=6,
    )
    assert transport._current_alt_setting == 6
    assert transport._ep_iso_in is not None
    assert transport._ep_iso_out is not None

    # Cancel the iso reader task that select_sco_alt_setting spawns,
    # so the test doesn't leak.
    if transport._iso_reader_task is not None:
        transport._iso_reader_task.cancel()
        try:
            await transport._iso_reader_task
        except BaseException:
            pass


@pytest.mark.asyncio
async def test_full_sco_setup_flow_intel_cvsd():
    transport = _build_intel_transport_with_iso_eps()
    transport.send = AsyncMock()

    ctrl = HCIController(transport=transport)

    async def fake_send_command(cmd):
        fut = ctrl._pending_sync_conn.get(0x0005)
        if fut and not fut.done():
            fut.set_result(0x0050)
    ctrl.send_command = fake_send_command

    with patch("usb.util.find_descriptor") as fd, \
         patch("usb.util.endpoint_direction") as ed, \
         patch("usb.util.endpoint_type") as et:
        fd.side_effect = lambda iface, custom_match=None: next(
            (e for e in iface.endpoints() if custom_match(e)), None,
        )
        ed.side_effect = lambda addr: 0x80 if (addr & 0x80) else 0x00
        et.side_effect = lambda attrs: attrs & 0x03

        sco_handle = await ctrl.setup_synchronous_connection(
            acl_handle=0x0005, preset=PRESET_CVSD_S1,
        )

    assert sco_handle == 0x0050
    transport._device.set_interface_altsetting.assert_called_once_with(
        interface=0, alternate_setting=1,
    )
    assert transport._current_alt_setting == 1

    if transport._iso_reader_task is not None:
        transport._iso_reader_task.cancel()
        try:
            await transport._iso_reader_task
        except BaseException:
            pass
