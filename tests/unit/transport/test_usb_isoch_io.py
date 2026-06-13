"""USBTransport real iso IN/OUT for SCO data."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from pybluehost.transport.usb.base import USBTransport


def _make_transport():
    t = USBTransport.__new__(USBTransport)
    t._device = MagicMock()
    t._is_open = True
    t._ep_iso_in = None
    t._ep_iso_out = None
    t._current_alt_setting = 0
    t._reader_tasks = []
    t._sink = None
    t._iso_reader_task = None
    return t


@pytest.mark.asyncio
async def test_isoch_out_writes_to_iso_endpoint():
    t = _make_transport()
    t._ep_iso_out = MagicMock()
    await t._isoch_out(b"\xAB\xCD")
    t._ep_iso_out.write.assert_called_once_with(b"\xAB\xCD")


@pytest.mark.asyncio
async def test_isoch_out_raises_when_iso_endpoint_unconfigured():
    t = _make_transport()
    t._ep_iso_out = None
    with pytest.raises(RuntimeError, match="alt"):
        await t._isoch_out(b"\x00")


@pytest.mark.asyncio
async def test_read_iso_loop_pushes_h4_prefixed_sco_to_sink():
    """When iso IN endpoint yields data, the reader loop wraps it with
    H4 packet type 0x03 (SCO) and forwards to the sink."""
    t = _make_transport()
    ep = MagicMock()
    # First call returns 4 bytes of SCO payload, then the loop will be stopped
    ep.read.side_effect = [b"\x01\x02\x03\x04", b""]
    t._ep_iso_in = ep

    received = []
    sink = MagicMock()

    async def on_data(packet):
        received.append(packet)
        if len(received) >= 1:
            t._is_open = False  # let the loop exit
    sink.on_transport_data = on_data
    t._sink = sink

    await t._read_iso_loop()

    assert received[0] == b"\x03\x01\x02\x03\x04"


@pytest.mark.asyncio
async def test_select_sco_alt_setting_starts_iso_reader_when_alt_gt_0():
    """When Alt > 0 and iso IN EP is found, select_sco_alt_setting must
    spawn the iso reader task and add it to _reader_tasks."""
    t = _make_transport()

    iso_in = MagicMock()
    iso_in.bEndpointAddress = 0x83
    iso_in.bmAttributes = 0x01
    iso_out = MagicMock()
    iso_out.bEndpointAddress = 0x03
    iso_out.bmAttributes = 0x01

    iface = MagicMock()
    iface.endpoints.return_value = [iso_in, iso_out]
    cfg = t._device.get_active_configuration.return_value
    cfg.__getitem__.side_effect = lambda key: iface if key == (0, 1) else (_ for _ in ()).throw(KeyError(key))

    from unittest.mock import patch
    with patch("usb.util.find_descriptor") as fd, \
         patch("usb.util.endpoint_direction") as ed, \
         patch("usb.util.endpoint_type") as et:
        fd.side_effect = lambda iface, custom_match=None: next(
            (e for e in iface.endpoints() if custom_match(e)), None,
        )
        ed.side_effect = lambda addr: 0x80 if (addr & 0x80) else 0x00
        et.side_effect = lambda attrs: attrs & 0x03

        await t.select_sco_alt_setting(1)

    assert t._iso_reader_task is not None
    assert t._iso_reader_task in t._reader_tasks
    # Cancel so the test doesn't leak
    t._iso_reader_task.cancel()
    try:
        await t._iso_reader_task
    except asyncio.CancelledError:
        pass
