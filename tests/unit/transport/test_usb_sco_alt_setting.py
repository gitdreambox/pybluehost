"""USBTransport.select_sco_alt_setting: switch USB interface alt setting,
re-enumerate iso IN/OUT endpoints."""
import pytest
from unittest.mock import MagicMock, patch

from pybluehost.transport.usb.base import USBTransport


def _iso_ep(addr: int, direction_in: bool) -> MagicMock:
    ep = MagicMock()
    ep.bEndpointAddress = addr | (0x80 if direction_in else 0)
    ep.bmAttributes = 0x01  # iso
    return ep


def _bulk_ep(addr: int, direction_in: bool) -> MagicMock:
    ep = MagicMock()
    ep.bEndpointAddress = addr | (0x80 if direction_in else 0)
    ep.bmAttributes = 0x02  # bulk
    return ep


def _make_alt_iface(endpoints):
    iface = MagicMock()
    iface.endpoints.return_value = endpoints
    return iface


def _attach_alt_iface(device, alt: int, iface):
    cfg = device.get_active_configuration.return_value
    def _getitem(key):
        if key == (0, alt):
            return iface
        raise KeyError(key)
    cfg.__getitem__.side_effect = _getitem


def _make_transport():
    t = USBTransport.__new__(USBTransport)
    t._device = MagicMock()
    t._is_open = True
    t._ep_iso_in = None
    t._ep_iso_out = None
    t._current_alt_setting = 0
    t._reader_tasks = []
    t._iso_reader_task = None
    return t


@pytest.mark.asyncio
async def test_select_alt_1_switches_interface_and_locates_iso_eps():
    t = _make_transport()
    alt_iface = _make_alt_iface([_iso_ep(0x03, True), _iso_ep(0x03, False)])
    _attach_alt_iface(t._device, 1, alt_iface)

    with patch("usb.util.find_descriptor") as fd:
        # Mimic real find_descriptor: scan endpoints with custom_match
        fd.side_effect = lambda iface, custom_match=None: next(
            (e for e in iface.endpoints() if custom_match(e)), None,
        )
        # Also need endpoint_direction + endpoint_type to work on our mock EPs
        with patch("usb.util.endpoint_direction") as ed, patch("usb.util.endpoint_type") as et:
            ed.side_effect = lambda addr: 0x80 if (addr & 0x80) else 0x00
            et.side_effect = lambda attrs: attrs & 0x03
            await t.select_sco_alt_setting(1)

    t._device.set_interface_altsetting.assert_called_once_with(
        interface=0, alternate_setting=1,
    )
    assert t._ep_iso_in is not None
    assert t._ep_iso_out is not None
    assert t._current_alt_setting == 1


@pytest.mark.asyncio
async def test_select_same_alt_is_noop():
    t = _make_transport()
    t._current_alt_setting = 1
    await t.select_sco_alt_setting(1)
    t._device.set_interface_altsetting.assert_not_called()


@pytest.mark.asyncio
async def test_select_alt_0_clears_iso_eps():
    """Selecting Alt 0 (SCO off) is supported and clears iso endpoints."""
    t = _make_transport()
    t._current_alt_setting = 1
    t._ep_iso_in = MagicMock()
    t._ep_iso_out = MagicMock()
    alt_iface = _make_alt_iface([])  # No iso EPs in Alt 0
    _attach_alt_iface(t._device, 0, alt_iface)

    with patch("usb.util.find_descriptor") as fd:
        fd.side_effect = lambda iface, custom_match=None: next(
            (e for e in iface.endpoints() if custom_match(e)), None,
        )
        with patch("usb.util.endpoint_direction") as ed, patch("usb.util.endpoint_type") as et:
            ed.side_effect = lambda addr: 0x80 if (addr & 0x80) else 0x00
            et.side_effect = lambda attrs: attrs & 0x03
            await t.select_sco_alt_setting(0)

    assert t._ep_iso_in is None
    assert t._ep_iso_out is None
    assert t._current_alt_setting == 0
