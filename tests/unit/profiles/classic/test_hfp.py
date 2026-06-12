import pytest

from pybluehost.classic.sdp import DataElement, DataElementType
from pybluehost.profiles.classic import HFPAudioGateway, HFPHandsFree
from pybluehost.profiles.classic._hfp_constants import (
    HANDSFREE_UUID, HFP_AG_UUID, HFP_HF_UUID,
)


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


def test_hf_advertises_handsfree_uuid():
    stack = _FakeStack()
    hf = HFPHandsFree(stack=stack)
    hf.register()
    uuids = _service_class_uuids(stack.registered_sdp_records[0])
    # HF role advertises 0x111E (Handsfree) and 0x1203 (GenericAudio)
    assert 0x111E in uuids
    assert 0x1203 in uuids


def test_ag_advertises_handsfree_ag_uuid():
    stack = _FakeStack()
    ag = HFPAudioGateway(stack=stack)
    ag.register()
    uuids = _service_class_uuids(stack.registered_sdp_records[0])
    assert HFP_AG_UUID in uuids
    assert 0x1203 in uuids


def test_hf_registers_rfcomm_listener():
    stack = _FakeStack()
    hf = HFPHandsFree(stack=stack)
    hf.register()
    # HFP commonly uses RFCOMM channel 13 (chosen by Plan A.4)
    assert 13 in stack.registered_rfcomm_listeners


def test_ag_registers_rfcomm_listener():
    stack = _FakeStack()
    ag = HFPAudioGateway(stack=stack)
    ag.register()
    assert 13 in stack.registered_rfcomm_listeners


def test_hf_constructor_accepts_codec_list():
    hf = HFPHandsFree(stack=_FakeStack(), supported_codecs=("CVSD",))
    assert hf.supported_codecs == ("CVSD",)


def test_ag_constructor_with_handler():
    seen = []

    async def on_event(event: str) -> None:
        seen.append(event)

    ag = HFPAudioGateway(stack=_FakeStack(), on_call_event=on_event)
    assert ag.on_call_event is on_event


def test_public_api_imports():
    """All A.4 entry points are importable from the public API."""
    from pybluehost.profiles.classic import (
        HFPAudioGateway, HFPHandsFree, HFPSession,
    )
    from pybluehost.profiles.classic._hfp_constants import (
        HFPCodecID, HFPCallState, HFPCallSetupState, HFPIndicator,
        HFFeature, AGFeature, HFP_HF_UUID, HFP_AG_UUID, HANDSFREE_UUID,
    )
    from pybluehost.profiles.classic._at_parser import (
        ATCommand, ATResponse, ATUnsolicited, parse_at_line, ATLineBuffer,
    )
    from pybluehost.profiles.classic._hfp_at import (
        build_brsf_command, build_brsf_response, build_bac_command,
        build_cind_test_response, build_cind_read_response, build_cmer_command,
        build_ciev_unsolicited, build_bcs_command, build_bcs_unsolicited,
    )
    from pybluehost.profiles.classic._hfp_state import HFPStateMachine, SLCState
    from pybluehost.profiles.classic._sco_loopback import (
        WavToScoSender, ScoToWavReceiver,
    )
    from pybluehost.hci.packets import HCISCOData
    from pybluehost.hci.sco import SCOLink
    for sym in (HFPHandsFree, HFPAudioGateway, HFPSession,
                ATCommand, HFPStateMachine, SLCState,
                WavToScoSender, ScoToWavReceiver, HCISCOData, SCOLink):
        assert sym is not None
