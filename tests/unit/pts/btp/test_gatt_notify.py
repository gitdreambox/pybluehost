"""GATT BTP — Attribute Value Changed (0x81) event emission on Set Value (0x06).

Upstream auto-pts has no server-side Notify/Indicate opcodes; instead a server
value update raises a unified 0x81 event. See plan banner."""
import asyncio

import pytest

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import BtpFrame
from pybluehost.pts.btp.services.gatt import GattService


class _FakeTester:
    def __init__(self):
        self.events: list[BtpFrame] = []

    async def emit_event(self, frame: BtpFrame) -> None:
        self.events.append(frame)


class _FakeActions:
    def __init__(self):
        self.calls = []


def _make_svc():
    tester = _FakeTester()
    svc = GattService(actions=_FakeActions(), tester=tester)
    return svc, tester


@pytest.mark.asyncio
async def test_set_value_emits_attribute_value_changed_event():
    svc, tester = _make_svc()
    # Build a service + characteristic so we have a known handle.
    svc_body = bytes([op.GATT_SERVICE_PRIMARY, 2]) + bytes.fromhex("0F18")
    _, svc_resp = await svc.dispatch(
        opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=svc_body,
    )
    svc_h = int.from_bytes(svc_resp, "little")
    char_body = (
        svc_h.to_bytes(2, "little")
        + bytes([op.GATT_CHRC_PROP_READ | op.GATT_CHRC_PROP_NOTIFY, op.GATT_PERM_READ, 2])
        + bytes.fromhex("1929")
    )
    _, char_resp = await svc.dispatch(
        opcode=op.OP_GATT_ADD_CHARACTERISTIC, controller_index=0, data=char_body,
    )
    char_h = int.from_bytes(char_resp, "little")

    # SET_VALUE updates the attribute and emits the event.
    set_body = char_h.to_bytes(2, "little") + (3).to_bytes(2, "little") + b"\x01\x02\x03"
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_SET_VALUE, controller_index=0, data=set_body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    await asyncio.sleep(0)

    assert len(tester.events) == 1
    evt = tester.events[0]
    assert evt.service == op.SERVICE_GATT
    assert evt.opcode == op.OP_GATT_EVENT_ATTR_VALUE_CHANGED
    # Payload: handle(u16 LE) + data_len(u16 LE) + data
    assert int.from_bytes(evt.data[0:2], "little") == char_h
    assert int.from_bytes(evt.data[2:4], "little") == 3
    assert evt.data[4:7] == b"\x01\x02\x03"


@pytest.mark.asyncio
async def test_set_value_failed_does_not_emit_event():
    """If Set Value fails (unknown handle), no event is emitted."""
    svc, tester = _make_svc()
    bad_body = (0xFFFF).to_bytes(2, "little") + (1).to_bytes(2, "little") + b"\x00"
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_SET_VALUE, controller_index=0, data=bad_body,
    )
    assert status == op.BTP_STATUS_FAILED
    await asyncio.sleep(0)
    assert tester.events == []


@pytest.mark.asyncio
async def test_set_value_zero_length_payload_emits_event():
    """A set-to-empty value is valid and still emits the event."""
    svc, tester = _make_svc()
    svc_body = bytes([op.GATT_SERVICE_PRIMARY, 2]) + bytes.fromhex("0F18")
    _, svc_resp = await svc.dispatch(
        opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=svc_body,
    )
    svc_h = int.from_bytes(svc_resp, "little")
    char_body = (
        svc_h.to_bytes(2, "little")
        + bytes([op.GATT_CHRC_PROP_READ, op.GATT_PERM_READ, 2])
        + bytes.fromhex("1929")
    )
    _, char_resp = await svc.dispatch(
        opcode=op.OP_GATT_ADD_CHARACTERISTIC, controller_index=0, data=char_body,
    )
    char_h = int.from_bytes(char_resp, "little")

    set_body = char_h.to_bytes(2, "little") + (0).to_bytes(2, "little")
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_SET_VALUE, controller_index=0, data=set_body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    await asyncio.sleep(0)
    assert len(tester.events) == 1
    assert int.from_bytes(tester.events[0].data[2:4], "little") == 0
