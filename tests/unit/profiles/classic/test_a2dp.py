from pybluehost.classic.sdp import DataElement, DataElementType
from pybluehost.profiles.classic import A2DPSink, A2DPSource


class _FakeStack:
    """Minimal stack stub: SDP record registrar + L2CAP listener registry."""

    def __init__(self):
        self.registered_sdp_records = []
        self.registered_psm_listeners = {}

    @property
    def sdp(self):
        owner = self

        class _SDP:
            def register(self, record):
                owner.registered_sdp_records.append(record)
                return len(owner.registered_sdp_records)

        return _SDP()

    @property
    def l2cap(self):
        owner = self

        class _L2CAP:
            def listen_classic_channel(self, psm, handler):
                owner.registered_psm_listeners[psm] = handler

        return _L2CAP()


def _service_class_uuids(record) -> list[int]:
    svc_attr = record.attributes[0x0001]
    out = []
    for el in svc_attr.value:
        if el.type == DataElementType.UUID:
            out.append(el.value)
    return out


def test_a2dp_source_default_sbc_capability():
    from pybluehost.avdtp.constants import ServiceCategory
    src = A2DPSource(stack=_FakeStack())
    caps = src.local_capabilities()
    cats = [c for c, _ in caps]
    assert ServiceCategory.MEDIA_TRANSPORT in cats
    assert ServiceCategory.MEDIA_CODEC in cats


def test_a2dp_source_register_installs_sdp_and_listener():
    stack = _FakeStack()
    src = A2DPSource(stack=stack)
    src.register()
    assert len(stack.registered_sdp_records) == 1
    assert 0x0019 in stack.registered_psm_listeners


def test_a2dp_sink_default_sbc_capability():
    from pybluehost.avdtp.constants import ServiceCategory
    sink = A2DPSink(stack=_FakeStack())
    caps = sink.local_capabilities()
    cats = [c for c, _ in caps]
    assert ServiceCategory.MEDIA_TRANSPORT in cats
    assert ServiceCategory.MEDIA_CODEC in cats


def test_a2dp_sink_register_uses_sink_uuid():
    """Sink advertises AudioSink (0x110B) not AudioSource (0x110A)."""
    stack = _FakeStack()
    sink = A2DPSink(stack=stack)
    sink.register()
    record = stack.registered_sdp_records[0]
    assert 0x110B in _service_class_uuids(record)


def test_a2dp_source_uuid_in_record():
    stack = _FakeStack()
    src = A2DPSource(stack=stack)
    src.register()
    record = stack.registered_sdp_records[0]
    assert 0x110A in _service_class_uuids(record)


def test_public_api_imports():
    """Every documented entry point is importable from the public API."""
    from pybluehost.profiles.classic import A2DPSink, A2DPSource
    from pybluehost.avdtp import (
        AVDTPSignalID, AVDTPPacketType, AVDTPMessageType,
        AVDTPErrorCode, MediaType, TSEP, ServiceCategory, PSM_AVDTP,
    )
    from pybluehost.avdtp.signaling import AVDTPMessage, SBCCapability
    from pybluehost.avdtp.media import AVDTPMediaPacket
    from pybluehost.avdtp.sep import StreamEndpoint
    from pybluehost.avdtp.session import AVDTPSession

    for symbol in (A2DPSource, A2DPSink, AVDTPMessage, AVDTPMediaPacket,
                   StreamEndpoint, AVDTPSession, SBCCapability):
        assert symbol is not None
