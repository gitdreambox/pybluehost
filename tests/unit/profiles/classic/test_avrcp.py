import asyncio

import pytest
import pytest_asyncio

from pybluehost.classic.avctp.constants import (
    AVRCP_CONTROLLER_UUID, AVRCP_TARGET_UUID, PSM_AVCTP,
)
from pybluehost.classic.avrcp.constants import AVRCPOperationID
from pybluehost.classic.sdp import DataElement, DataElementType
from pybluehost.profiles.classic import AVRCPController, AVRCPTarget


class _FakeStack:
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


def test_controller_registers_psm_0x0017():
    stack = _FakeStack()
    ctrl = AVRCPController(stack=stack)
    ctrl.register()
    assert PSM_AVCTP in stack.registered_psm_listeners
    assert len(stack.registered_sdp_records) == 1


def test_controller_advertises_controller_uuid():
    stack = _FakeStack()
    ctrl = AVRCPController(stack=stack)
    ctrl.register()
    uuids = _service_class_uuids(stack.registered_sdp_records[0])
    assert AVRCP_CONTROLLER_UUID in uuids


def test_target_advertises_target_uuid():
    stack = _FakeStack()
    tgt = AVRCPTarget(stack=stack)
    tgt.register()
    uuids = _service_class_uuids(stack.registered_sdp_records[0])
    assert AVRCP_TARGET_UUID in uuids


def test_target_constructor_with_handlers():
    """Pass through handlers + notification register handler can be supplied."""
    async def on_pt(cmd):
        return True

    async def on_notify_register(event_id):
        return b"\x01"

    stack = _FakeStack()
    tgt = AVRCPTarget(
        stack=stack,
        on_pass_through=on_pt,
        on_notification_register=on_notify_register,
    )
    assert tgt.on_pass_through is on_pt
    assert tgt.on_notification_register is on_notify_register


def test_public_api_imports():
    """All A.3 entry points are importable from the public API."""
    from pybluehost.profiles.classic import (
        AVRCPController, AVRCPSession, AVRCPTarget,
    )
    from pybluehost.classic.avctp import (
        AVCTPPacketType, AVCTPMessageDirection,
        PSM_AVCTP, AVRCP_PROFILE_UUID,
        AVRCP_CONTROLLER_UUID, AVRCP_TARGET_UUID,
    )
    from pybluehost.classic.avctp.message import AVCTPMessage, AVCTPReassembler
    from pybluehost.classic.avctp.session import AVCTPSession
    from pybluehost.classic.avrcp import (
        AVCFrame, AVCCtype, AVCOpCode, AVCSubunitType,
        AVRCPEventID, AVRCPMetadataPDU, AVRCPOperationID, AVRCPPlayStatus,
    )
    from pybluehost.classic.avrcp.passthrough import PassThroughCommand, PassThroughResponse
    from pybluehost.classic.avrcp.notification import (
        build_notification_changed_response,
        build_notification_interim_response,
        build_register_notification_command,
    )
    from pybluehost.classic.avrcp.unit_info import (
        build_unit_info_command, build_unit_info_response,
        build_subunit_info_command, build_subunit_info_response,
    )
    for sym in (AVRCPController, AVRCPTarget, AVRCPSession,
                AVCTPMessage, AVCTPReassembler, AVCTPSession,
                AVCFrame, PassThroughCommand, PassThroughResponse):
        assert sym is not None
