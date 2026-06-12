import asyncio

import pytest
import pytest_asyncio

from pybluehost.avctp.constants import (
    AVRCP_CONTROLLER_UUID, AVRCP_TARGET_UUID, PSM_AVCTP,
)
from pybluehost.avrcp.constants import AVRCPOperationID
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
