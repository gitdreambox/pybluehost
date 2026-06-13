"""Realtek prepare_for_sco issues vendor cmd 0xFC8B (param 0x02 = HCI bus),
cached so it's only sent once."""
import pytest
from unittest.mock import AsyncMock

from pybluehost.transport.usb.realtek import (
    HCI_VENDOR_RTK_SET_SCO_ROUTING_TYPE,
    RTK_SCO_ROUTING_HCI,
    RealtekUSBTransport,
)


def _make():
    t = RealtekUSBTransport.__new__(RealtekUSBTransport)
    # Fake command_complete with status 0
    t._send_hci_command = AsyncMock(return_value=b"\x0E\x04\x01\x8B\xFC\x00")
    return t


def test_constants_have_expected_values():
    assert HCI_VENDOR_RTK_SET_SCO_ROUTING_TYPE == 0xFC8B
    assert RTK_SCO_ROUTING_HCI == 0x02


@pytest.mark.asyncio
async def test_realtek_prepare_for_sco_sends_vendor_cmd():
    t = _make()
    await t.prepare_for_sco("CVSD")
    t._send_hci_command.assert_awaited_once_with(
        HCI_VENDOR_RTK_SET_SCO_ROUTING_TYPE,
        bytes([RTK_SCO_ROUTING_HCI]),
    )


@pytest.mark.asyncio
async def test_realtek_prepare_for_sco_cached_no_resend():
    t = _make()
    await t.prepare_for_sco("CVSD")
    await t.prepare_for_sco("mSBC")
    await t.prepare_for_sco("CVSD")
    t._send_hci_command.assert_awaited_once()


@pytest.mark.asyncio
async def test_realtek_prepare_for_sco_works_for_both_codecs():
    """Realtek doesn't switch USB Alt Setting per codec — the vendor cmd
    selects HCI routing once, and both CVSD and mSBC then ride the iso EP."""
    t = _make()
    await t.prepare_for_sco("mSBC")
    t._send_hci_command.assert_awaited_once_with(
        HCI_VENDOR_RTK_SET_SCO_ROUTING_TYPE,
        bytes([RTK_SCO_ROUTING_HCI]),
    )
