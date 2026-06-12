"""Unit tests for SCOLink — Task 7 of Plan A.4."""
import pytest

from pybluehost.hci.sco import SCOLink
from pybluehost.hci.sco_constants import (
    PRESET_CVSD_S1, PRESET_MSBC_T2,
)


@pytest.mark.asyncio
async def test_sco_link_init():
    link = SCOLink(handle=0x42, codec="CVSD")
    assert link.handle == 0x42
    assert link.codec == "CVSD"


@pytest.mark.asyncio
async def test_sco_link_send_invokes_controller():
    sent = []

    class _FakeController:
        async def send_sco_data(self, handle: int, data: bytes, packet_status: int = 0) -> None:
            sent.append((handle, data))

    link = SCOLink(handle=0x42, codec="CVSD", controller=_FakeController())
    await link.send(b"\xAA\xBB")
    assert len(sent) == 1
    assert sent[0][0] == 0x42
    assert sent[0][1] == b"\xAA\xBB"


@pytest.mark.asyncio
async def test_sco_link_on_data_callback_invoked():
    received = []

    async def cb(data: bytes) -> None:
        received.append(data)

    link = SCOLink(handle=0x42, codec="CVSD")
    link.set_on_data(cb)
    # Simulate inbound packet.
    from pybluehost.hci.packets import HCISCOData
    await link._on_inbound(HCISCOData(handle=0x42, data=b"\xCC\xDD"))
    assert received == [b"\xCC\xDD"]


@pytest.mark.asyncio
async def test_sco_link_ignores_packets_for_other_handle():
    received = []

    async def cb(data: bytes) -> None:
        received.append(data)

    link = SCOLink(handle=0x42, codec="CVSD")
    link.set_on_data(cb)
    from pybluehost.hci.packets import HCISCOData
    await link._on_inbound(HCISCOData(handle=0x99, data=b"\x00"))
    assert received == []


def test_preset_cvsd_s1_values():
    p = PRESET_CVSD_S1
    assert p["voice_setting"] == 0x0060
    assert p["retransmission_effort"] == 0x01


def test_preset_msbc_t2_values():
    p = PRESET_MSBC_T2
    assert p["voice_setting"] == 0x0063
    assert p["retransmission_effort"] == 0x02
