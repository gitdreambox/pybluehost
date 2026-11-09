"""BTP GATT EATT_CONNECT (0x1f) wiring + Server Supported Features EATT bit."""
from __future__ import annotations

import pytest

from pybluehost.core.uuid import UUID16
from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.gatt import GattService, _standard_gap_gatt_services

WIRE_ADDR = bytes.fromhex("010203040506")
CONN = 0x0E01


class _FakePeer:
    def to_hci(self) -> bytes:
        return WIRE_ADDR


class _ConnInfo:
    transport = "le"
    peer = _FakePeer()


class _Session:
    connections = {CONN: _ConnInfo()}


class _FakeChannel:
    def __init__(self, cid: int) -> None:
        self.cid = cid
        self.connection_handle = CONN
        self.mtu = 512


class _FakeL2CAP:
    def __init__(self) -> None:
        self.eatt_calls: list[tuple[int, int]] = []
        self.channels = [_FakeChannel(0x0041), _FakeChannel(0x0042)]

    async def connect_eatt_channels(self, handle, *, num=1, timeout=5.0):
        self.eatt_calls.append((handle, num))
        return self.channels[:num]


class _FakeStack:
    def __init__(self) -> None:
        self.l2cap = _FakeL2CAP()
        self.attached: list[object] = []

    def attach_eatt_bearer(self, channel) -> None:
        self.attached.append(channel)


class _FakeActions:
    def __init__(self) -> None:
        self._stack = _FakeStack()

    def status(self):
        return _Session()


class _FakeTester:
    def emit_event(self, *args, **kwargs):
        pass


def test_server_supported_features_reports_eatt():
    """GAW/BV-12 and GAC/BI-01 initial conditions require SSF (0x2B3A) octet 0
    bit 0 set (EATT supported, Core Vol 3 Part G Table 7.11)."""
    services = _standard_gap_gatt_services()
    gatt = next(s for s in services if s.uuid == UUID16(0x1801))
    ssf = next(c for c in gatt.characteristics if c.uuid == UUID16(0x2B3A))
    assert ssf.value == b"\x01"


@pytest.mark.asyncio
async def test_eatt_connect_attaches_each_channel_to_the_gatt_server():
    service = GattService(actions=_FakeActions(), tester=_FakeTester())
    status, payload = await service._handle_op_1f(0, bytes([0x00]) + WIRE_ADDR + bytes([2]))
    assert status == op.BTP_STATUS_SUCCESS
    assert payload == b""
    stack = service._actions._stack
    assert stack.l2cap.eatt_calls == [(CONN, 2)]
    assert stack.attached == stack.l2cap.channels


class _FakeStackNoAttach:
    def __init__(self) -> None:
        self.l2cap = _FakeL2CAP()


class _FakeActionsNoAttach:
    def __init__(self) -> None:
        self._stack = _FakeStackNoAttach()

    def status(self):
        return _Session()


class _FakeL2CAPRaise:
    async def connect_eatt_channels(self, handle, *, num=1, timeout=5.0):
        raise RuntimeError("eatt connect boom")


class _FakeStackRaise:
    def __init__(self) -> None:
        self.l2cap = _FakeL2CAPRaise()


class _FakeActionsRaise:
    def __init__(self) -> None:
        self._stack = _FakeStackRaise()

    def status(self):
        return _Session()


class _FakeStackAttachFail:
    def __init__(self) -> None:
        self.l2cap = _FakeL2CAP()

    def attach_eatt_bearer(self, channel) -> None:
        raise RuntimeError("attach boom")


class _FakeActionsAttachFail:
    def __init__(self) -> None:
        self._stack = _FakeStackAttachFail()

    def status(self):
        return _Session()


@pytest.mark.asyncio
async def test_eatt_connect_without_attach_support_still_succeeds():
    service = GattService(actions=_FakeActionsNoAttach(), tester=_FakeTester())
    status, payload = await service._handle_op_1f(0, bytes([0x00]) + WIRE_ADDR + bytes([1]))
    assert status == op.BTP_STATUS_SUCCESS
    assert payload == b""


@pytest.mark.asyncio
async def test_eatt_connect_manager_raise_fails():
    service = GattService(actions=_FakeActionsRaise(), tester=_FakeTester())
    status, _ = await service._handle_op_1f(0, bytes([0x00]) + WIRE_ADDR + bytes([1]))
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_eatt_connect_attach_failure_fails():
    service = GattService(actions=_FakeActionsAttachFail(), tester=_FakeTester())
    status, _ = await service._handle_op_1f(0, bytes([0x00]) + WIRE_ADDR + bytes([2]))
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_eatt_connect_unknown_peer_fails():
    service = GattService(actions=_FakeActions(), tester=_FakeTester())
    status, _ = await service._handle_op_1f(0, bytes([0x00]) + bytes(6) + bytes([1]))
    assert status == op.BTP_STATUS_FAILED
