"""Stack EATT wiring: inbound listener on PSM_EATT (encryption-gated) and
per-channel GATT server binding with bearer identity."""
from __future__ import annotations

import pytest

from pybluehost.ble.att import ATT_Read_Request, ATT_Read_Response, decode_att_pdu
from pybluehost.ble.gatt import (
    CharacteristicDefinition,
    CharProperties,
    GATTServer,
    Permissions,
    ServiceDefinition,
)
from pybluehost.core.uuid import UUID16
from pybluehost.l2cap.constants import PSM_EATT
from pybluehost.stack import Stack

pytestmark = pytest.mark.asyncio

CONN = 0x0040
EATT_CID = 0x0041


class _FakeL2CAP:
    def __init__(self) -> None:
        self._connections: dict[int, dict[int, object]] = {}
        self.listeners: list[tuple[int, object, int]] = []

    def listen_le_coc_channel(self, psm, handler, required_security=0) -> None:
        self.listeners.append((psm, handler, required_security))

    def get_fixed_channel(self, handle, cid):
        return None


class _FakeEattChannel:
    """Minimal channel double: mux needs set_events; the binder needs cid /
    connection_handle / mtu / send."""

    def __init__(self, conn_handle=CONN, cid=EATT_CID, mtu=512) -> None:
        self.connection_handle = conn_handle
        self.cid = cid
        self.mtu = mtu
        self.psm = PSM_EATT
        self.events = None
        self.sent: list[bytes] = []

    def set_events(self, events) -> None:
        self.events = events

    async def send(self, data: bytes) -> None:
        self.sent.append(bytes(data))


def _stack_with_gatt() -> tuple[Stack, GATTServer, _FakeL2CAP, int]:
    stack = Stack()
    l2cap = _FakeL2CAP()
    server = GATTServer()
    handles = server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x180D),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2A38),
                    properties=CharProperties.READ,
                    permissions=Permissions.READABLE,
                    value=b"\xAA" * 40,
                )
            ],
        )
    )
    stack._l2cap = l2cap
    stack._gatt_server = server
    return stack, server, l2cap, handles.characteristic_handles[0].value_handle


async def test_attach_registers_eatt_listener_once_with_encryption_requirement():
    stack, _, l2cap, _ = _stack_with_gatt()
    stack._attach_gatt_server_to_att_channels()
    stack._attach_gatt_server_to_att_channels()  # idempotent
    assert len(l2cap.listeners) == 1
    psm, handler, required_security = l2cap.listeners[0]
    assert psm == PSM_EATT
    assert required_security == 4  # encryption — Core Vol 3 Part G §5.2


async def test_inbound_eatt_channel_gets_gatt_server_with_bearer_identity():
    stack, server, l2cap, value_handle = _stack_with_gatt()
    stack._attach_gatt_server_to_att_channels()
    _, listener, _ = l2cap.listeners[0]
    channel = _FakeEattChannel(mtu=100)
    listener(channel)

    assert server.is_eatt_bearer(CONN, EATT_CID)
    assert server._att_mtu(CONN, EATT_CID) == 100  # channel MTU, not 23

    await channel.events.on_data(ATT_Read_Request(attribute_handle=value_handle).to_bytes())
    assert len(channel.sent) == 1
    rsp = decode_att_pdu(channel.sent[0])
    assert isinstance(rsp, ATT_Read_Response)
    assert rsp.attribute_value == b"\xAA" * 40  # bearer MTU 100 fits it whole


async def test_attach_eatt_bearer_binds_outbound_channel():
    stack, server, _, value_handle = _stack_with_gatt()
    channel = _FakeEattChannel(mtu=64)
    stack.attach_eatt_bearer(channel)
    assert server.is_eatt_bearer(CONN, EATT_CID)
    assert server._att_mtu(CONN, EATT_CID) == 64
    await channel.events.on_data(ATT_Read_Request(attribute_handle=value_handle).to_bytes())
    assert channel.sent, "no ATT response on outbound EATT bearer"


async def test_attach_eatt_bearer_without_gatt_server_is_noop():
    stack = Stack()
    stack._l2cap = _FakeL2CAP()
    stack.attach_eatt_bearer(_FakeEattChannel())  # must not raise
