"""Default Transport.prepare_for_sco hook is an async no-op."""
import pytest
from tests.fakes.transport import FakeTransport


@pytest.mark.asyncio
async def test_transport_prepare_for_sco_cvsd_is_noop():
    t = FakeTransport()
    assert await t.prepare_for_sco("CVSD") is None


@pytest.mark.asyncio
async def test_transport_prepare_for_sco_msbc_is_noop():
    t = FakeTransport()
    assert await t.prepare_for_sco("mSBC") is None
