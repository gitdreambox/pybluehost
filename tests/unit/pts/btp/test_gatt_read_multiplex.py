"""Read Multiple Variable Length over multiple bearers (GATT/CL/GAR/BV-10).

BTP READ_MULTIPLE_VAR (0x20) carries no bearer field — the bearer choice is
IUT-internal policy. GATT.TS §4.6.1 (BV-10) requires the FIRST request on the
unenhanced ATT bearer and the SECOND on an EATT bearer, and BOTH must be on air
while both are pending (the Lower Tester answers the ATT-bearer request only
after the EATT-bearer request arrives — MSC Figure 4.91). BTP commands are
dispatched serially, so the service fires both transactions on the first
command and hands the EATT future to the second.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.gatt import GattService


WIRE_ADDR = bytes.fromhex("AABBCCDDEEFF")
CONN = 0x000C


class _RecordingBearer:
    def __init__(self, name: str) -> None:
        self.name = name
        self.requests: list[list[int]] = []

    async def read_multiple_variable(self, handles):
        self.requests.append(list(handles))
        return [bytes([len(handles)])]


class _FakeGattClient:
    def __init__(self) -> None:
        self.default_bearer = _RecordingBearer("att")
        self.connection_handle = CONN

    async def read_multiple_variable_characteristic(self, handles, *, bearer=None):
        b = bearer if bearer is not None else self.default_bearer
        return await b.read_multiple_variable(handles)


class _ConnInfo:
    def __init__(self, peer, handle, gatt_client):
        self.peer = peer
        self.handle = handle
        self.transport = "le"
        self.gatt_client = gatt_client


class _FakeSession:
    def __init__(self):
        self.connections = {}


class _FakeActions:
    def __init__(self, client, eatt_bearers=()):
        self._session = _FakeSession()
        self._session.connections[CONN] = _ConnInfo(WIRE_ADDR, CONN, client)
        self._eatt_bearers = {CONN: list(eatt_bearers)}

    def status(self):
        return self._session

    def eatt_client_bearers_for_handle(self, handle):
        return list(self._eatt_bearers.get(handle, []))


def _body(count=2):
    return (
        bytes([0]) + WIRE_ADDR + bytes([count])
        + (0x031C).to_bytes(2, "little")
        + (0x0195).to_bytes(2, "little")
    )


@pytest.mark.asyncio
async def test_multiplexed_sequence_answers_att_command_then_eatt_command():
    """Command #1 fires BOTH transactions and is answered from the ATT bearer;
    command #2 collects the EATT future. Both requests are on air while both
    commands are pending — the serial-dispatch deadlock BV-10 died in."""
    client = _FakeGattClient()
    eatt = _RecordingBearer("eatt")
    svc = GattService(actions=_FakeActions(client, eatt_bearers=[eatt]),
                      tester=MagicMock())
    status1, data1 = await svc.dispatch(
        opcode=op.OP_GATT_READ_MULTIPLE_VAR, controller_index=0, data=_body())
    status2, data2 = await svc.dispatch(
        opcode=op.OP_GATT_READ_MULTIPLE_VAR, controller_index=0, data=_body())
    assert status1 == status2 == op.BTP_STATUS_SUCCESS
    assert data1 == data2 == bytes([0x00]) + (1).to_bytes(2, "little") + b"\x02"
    # Exactly one request per bearer — both fired by command #1.
    assert client.default_bearer.requests == [[0x031C, 0x0195]]
    assert eatt.requests == [[0x031C, 0x0195]]


@pytest.mark.asyncio
async def test_four_commands_alternate_bearers():
    """seq0 fires (att+eatt), seq1 collects eatt, seq2 fires again, seq3
    collects — requests keep alternating across bearers."""
    client = _FakeGattClient()
    eatt = _RecordingBearer("eatt")
    svc = GattService(actions=_FakeActions(client, eatt_bearers=[eatt]),
                      tester=MagicMock())
    for _ in range(4):
        status, _ = await svc.dispatch(
            opcode=op.OP_GATT_READ_MULTIPLE_VAR, controller_index=0, data=_body())
        assert status == op.BTP_STATUS_SUCCESS
    assert len(client.default_bearer.requests) == 2
    assert len(eatt.requests) == 2


@pytest.mark.asyncio
async def test_without_eatt_bearers_every_request_stays_on_att():
    """No attached EATT bearer (GAR/BV-08 single-bearer case): rotation is a
    no-op and every request uses the default ATT bearer."""
    client = _FakeGattClient()
    svc = GattService(actions=_FakeActions(client), tester=MagicMock())
    for _ in range(2):
        status, _ = await svc.dispatch(
            opcode=op.OP_GATT_READ_MULTIPLE_VAR, controller_index=0, data=_body())
        assert status == op.BTP_STATUS_SUCCESS
    assert client.default_bearer.requests == [[0x031C, 0x0195], [0x031C, 0x0195]]


@pytest.mark.asyncio
async def test_eatt_connect_registers_client_bearers_via_actions_hook():
    """EATT_CONNECT (0x1f) must also hand each new channel to the actions layer
    so a GATT-client ATT bearer exists on it (server attach alone leaves the
    bearer server-only and BV-10's second request would have nowhere to go)."""
    registered: list[tuple[int, object]] = []

    class _Channel:
        def __init__(self, cid):
            self.cid = cid
            self.connection_handle = CONN
            self.mtu = 512

    class _L2CAP:
        def __init__(self):
            self.channels = [_Channel(0x0041)]

        async def connect_eatt_channels(self, handle, *, num=1, timeout=5.0):
            return self.channels[:num]

    class _Stack:
        def __init__(self):
            self.l2cap = _L2CAP()
            self.attached = []

        def attach_eatt_bearer(self, channel):
            self.attached.append(channel)

    class _Actions:
        def __init__(self):
            self._stack = _Stack()
            self._session = _FakeSession()
            self._session.connections[CONN] = _ConnInfo(
                type("P", (), {"to_hci": staticmethod(lambda: WIRE_ADDR)})(),
                CONN, None)

        def status(self):
            return self._session

        def attach_eatt_client_bearer(self, handle, channel):
            registered.append((handle, channel))

    svc = GattService(actions=_Actions(), tester=MagicMock())
    status, _ = await svc._handle_op_1f(0, bytes([0x00]) + WIRE_ADDR + bytes([1]))
    assert status == op.BTP_STATUS_SUCCESS
    assert [(h, ch.cid) for h, ch in registered] == [(CONN, 0x0041)]
