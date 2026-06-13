import pytest

from pybluehost.classic.sdp import DataElement, DataElementType
from pybluehost.profiles.classic import HSPAudioGateway, HSPHeadset
from pybluehost.profiles.classic._hsp_constants import (
    HEADSET_UUID, HSP_AG_RFCOMM_CHANNEL, HSP_AG_UUID,
    HSP_HS_RFCOMM_CHANNEL, HSP_HS_UUID,
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
