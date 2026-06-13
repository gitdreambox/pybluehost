import asyncio
import math
import os
import struct
import wave

import pytest

from pybluehost.classic.sdp import DataElement, DataElementType
from pybluehost.hci.packets import HCISCOData
from pybluehost.hci.sco import SCOLink
from pybluehost.hci.sco_constants import PRESET_CVSD_S1
from pybluehost.profiles.classic import HSPAudioGateway, HSPHeadset
from pybluehost.profiles.classic._hsp_constants import (
    HEADSET_UUID, HSP_AG_RFCOMM_CHANNEL, HSP_AG_UUID,
    HSP_HS_RFCOMM_CHANNEL, HSP_HS_UUID,
)
from pybluehost.profiles.classic._sco_loopback import (
    ScoToWavReceiver, WavToScoSender,
)
from pybluehost.profiles.classic.hsp import HSPSession


class _FakeStack:
    def __init__(self):
        self.registered_sdp_records = []
        self.registered_rfcomm_listeners = {}

    @property
    def sdp(self):
        owner = self

        class _SDP:
            def register(self, record):
                owner.registered_sdp_records.append(record)
                return len(owner.registered_sdp_records)

        return _SDP()

    @property
    def rfcomm(self):
        owner = self

        class _RFCOMM:
            def listen_channel(self, channel, handler):
                owner.registered_rfcomm_listeners[channel] = handler

        return _RFCOMM()


def _service_class_uuids(record) -> list[int]:
    svc_attr = record.attributes[0x0001]
    return [
        el.value for el in svc_attr.value
        if el.type == DataElementType.UUID
    ]


def test_hs_advertises_headset_hs_uuid():
    stack = _FakeStack()
    hs = HSPHeadset(stack=stack)
    hs.register()
    uuids = _service_class_uuids(stack.registered_sdp_records[0])
    assert HSP_HS_UUID in uuids
    assert HEADSET_UUID in uuids
    assert 0x1203 in uuids


def test_ag_advertises_headset_ag_uuid():
    stack = _FakeStack()
    ag = HSPAudioGateway(stack=stack)
    ag.register()
    uuids = _service_class_uuids(stack.registered_sdp_records[0])
    assert HSP_AG_UUID in uuids
    assert 0x1203 in uuids


def test_hs_registers_rfcomm_channel_5():
    stack = _FakeStack()
    hs = HSPHeadset(stack=stack)
    hs.register()
    assert HSP_HS_RFCOMM_CHANNEL in stack.registered_rfcomm_listeners


def test_ag_registers_rfcomm_channel_12():
    stack = _FakeStack()
    ag = HSPAudioGateway(stack=stack)
    ag.register()
    assert HSP_AG_RFCOMM_CHANNEL in stack.registered_rfcomm_listeners


def test_ag_constructor_with_on_button_press():
    seen = []

    async def cb() -> None:
        seen.append(True)

    ag = HSPAudioGateway(stack=_FakeStack(), on_button_press=cb)
    assert ag.on_button_press is cb


@pytest.mark.asyncio
async def test_hsp_session_setup_sco_uses_cvsd(tmp_path):
    """HSPSession.setup_sco() always uses CVSD preset (no negotiation)."""
    captured = {}

    class _FakeHCI:
        async def setup_synchronous_connection(self, *, acl_handle, preset):
            captured["acl_handle"] = acl_handle
            captured["preset"] = preset
            return 0x0299

        def set_on_sco_data(self, callback):
            captured["on_sco_data"] = callback

    class _FakeStack:
        @property
        def hci(self):
            return _FakeHCI()

    sess = HSPSession(
        stack=_FakeStack(), rfcomm=None, handle=0x42, role="hs",
    )
    sco_link = await sess.setup_sco()
    assert isinstance(sco_link, SCOLink)
    assert sco_link.codec == "CVSD"
    assert sco_link.handle == 0x0299
    assert captured["acl_handle"] == 0x42
    assert captured["preset"] == PRESET_CVSD_S1


@pytest.mark.asyncio
async def test_hsp_sco_link_works_with_a4_wav_workers(tmp_path):
    """A.4's WavToScoSender + ScoToWavReceiver accept an HSP SCOLink (CVSD)."""
    src = tmp_path / "src.wav"
    dst = tmp_path / "dst.wav"
    sr = 8000
    n = int(sr * 0.2)
    samples = [int(6000 * math.sin(2 * math.pi * 400 * i / sr)) for i in range(n)]
    with wave.open(str(src), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(struct.pack(f"<{n}h", *samples))

    class _LoopbackController:
        def __init__(self):
            self._sink = None

        def attach_sink(self, link):
            self._sink = link

        async def send_sco_data(self, *args, **kwargs):
            # Accept either (HCISCOData) or (handle, data) signatures.
            if len(args) == 1 and isinstance(args[0], HCISCOData):
                pkt = args[0]
            elif len(args) == 2:
                pkt = HCISCOData(handle=args[0], data=args[1])
            else:
                handle = kwargs.get("handle", 0)
                data = kwargs.get("data", b"")
                pkt = HCISCOData(handle=handle, data=data)
            if self._sink is not None:
                await self._sink._on_inbound(pkt)

    ctrl = _LoopbackController()
    sender_link = SCOLink(handle=0x42, codec="CVSD", controller=ctrl)
    receiver_link = SCOLink(handle=0x42, codec="CVSD")
    ctrl.attach_sink(receiver_link)

    receiver = ScoToWavReceiver(wav_path=str(dst), sco_link=receiver_link)
    sender = WavToScoSender(wav_path=str(src), sco_link=sender_link)

    total = await sender.run()
    await asyncio.sleep(0)
    receiver.close()

    assert total > 0
    assert os.path.exists(dst)
    with wave.open(str(dst), "rb") as r:
        assert r.getframerate() == 8000


def test_public_api_imports():
    """All A.5 entry points are importable from the public API."""
    from pybluehost.profiles.classic import (
        HSPAudioGateway, HSPHeadset, HSPSession,
    )
    from pybluehost.profiles.classic._hsp_constants import (
        HEADSET_UUID, HSP_HS_UUID, HSP_AG_UUID, HSP_PROFILE_VERSION,
        HSP_HS_RFCOMM_CHANNEL, HSP_AG_RFCOMM_CHANNEL,
        HSP_AT_VGS, HSP_AT_VGM, HSP_AT_CKPD,
        HSP_DEFAULT_GAIN, HSP_GAIN_MAX, HSP_CKPD_KEY,
    )
    from pybluehost.profiles.classic._hsp_at import (
        build_vgs_command, build_vgm_command, build_ckpd_command,
        build_ring_unsolicited,
        parse_vgs_command, parse_vgm_command, parse_ckpd_command,
    )
    for sym in (HSPHeadset, HSPAudioGateway, HSPSession,
                build_vgs_command, build_ckpd_command, build_ring_unsolicited):
        assert sym is not None
