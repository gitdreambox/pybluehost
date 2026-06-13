"""Intel chip prepare_for_sco maps codec to USB Alt Setting (1=CVSD, 6=mSBC)."""
import pytest
from unittest.mock import AsyncMock

from pybluehost.transport.usb.intel import IntelUSBTransport


def _make():
    t = IntelUSBTransport.__new__(IntelUSBTransport)
    t.select_sco_alt_setting = AsyncMock()
    return t


@pytest.mark.asyncio
async def test_intel_prepare_for_sco_cvsd_selects_alt_1():
    t = _make()
    await t.prepare_for_sco("CVSD")
    t.select_sco_alt_setting.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_intel_prepare_for_sco_msbc_selects_alt_6():
    t = _make()
    await t.prepare_for_sco("mSBC")
    t.select_sco_alt_setting.assert_awaited_once_with(6)


@pytest.mark.asyncio
async def test_intel_prepare_for_sco_unknown_codec_raises():
    t = _make()
    with pytest.raises(ValueError, match="SCO codec"):
        await t.prepare_for_sco("AAC")
