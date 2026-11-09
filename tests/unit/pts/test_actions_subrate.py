"""Connection Subrating (BTP GAP SUBRATE_REQUEST op 0x2b / SUBRATE_CHANGE ev 0x92)
— PTS GAP/CSUB/CSR/BV-01-C (Peripheral) + GAP/CSUB/CSU/BV-01-C (Central).

Core Vol 4 Part E §7.8.124 has ONE HCI command — ``LE_Subrate_Request`` —
serve both roles ("used by a Central or a Peripheral"), so a single BTP opcode
drives both cases. The Controller answers with Command Status immediately and
completes the procedure asynchronously with an **LE Subrate Change** LE Meta
event (subevent 0x23), which is what the Upper Tester has to be told about:

    BTP 0x2b  ->  HCI LE_Subrate_Request (0x207E)
    HCI LE Subrate Change (0x23)  ->  BTP 0x92

auto-pts's ``gap_subrate_change_ev_`` rejects the event unless the address
equals its own LT address, so the address we report must be the PEER's, in HCI
little-endian byte order (like DEVICE_CONNECTED / DEVICE_FOUND).
"""
from __future__ import annotations

import asyncio
import struct
from types import SimpleNamespace

import pytest

from pybluehost.ble.gap import BLEConnectionManager
from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import HCI_LE_SUBRATE_REQUEST
from pybluehost.pts import btp as _btp_pkg  # noqa: F401  (ensure package import side effects)
from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import BtpFrame
from pybluehost.pts.btp.services.gap import GapService
from pybluehost.pts.actions import ConnInfo, IutActions

PEER = "94:53:FF:1E:6A:EE"
# auto-pts stack defaults, set in autopts/ptsprojects/stack/layers/gap.py.
SUBRATE_MIN, SUBRATE_MAX, LATENCY, CONT_NUMBER, TIMEOUT = 10, 20, 0x0064, 5, 0x0BB8


class _FakeHCI:
    def __init__(self) -> None:
        self.commands: list = []

    async def send_command(self, cmd):
        self.commands.append(cmd)
        return SimpleNamespace(status=0)


# ---------------------------------------------------------------------------
# BLEConnectionManager.subrate_request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subrate_request_sends_le_subrate_request_command():
    hci = _FakeHCI()
    mgr = BLEConnectionManager(hci=hci)
    await mgr.subrate_request(
        0x0040, subrate_min=SUBRATE_MIN, subrate_max=SUBRATE_MAX,
        max_latency=LATENCY, continuation_number=CONT_NUMBER,
        supervision_timeout=TIMEOUT,
    )

    assert len(hci.commands) == 1
    cmd = hci.commands[0]
    assert cmd.opcode == HCI_LE_SUBRATE_REQUEST
    assert cmd.opcode == 0x207E
    # Vol 4 Part E §7.8.124: Connection_Handle + Subrate_Min + Subrate_Max +
    # Max_Latency + Continuation_Number + Supervision_Timeout, all u16 LE.
    assert cmd.parameters == struct.pack(
        "<HHHHHH", 0x0040, SUBRATE_MIN, SUBRATE_MAX, LATENCY,
        CONT_NUMBER, TIMEOUT,
    )


# ---------------------------------------------------------------------------
# IutActions.subrate_request
# ---------------------------------------------------------------------------

def _make_actions() -> tuple[IutActions, _FakeHCI]:
    hci = _FakeHCI()
    stack = SimpleNamespace(
        config=SimpleNamespace(bond_storage=None),
        _smp=SimpleNamespace(_bond_storage=None),
        gap=SimpleNamespace(ble_connections=BLEConnectionManager(hci=hci)),
        l2cap=SimpleNamespace(),
        on_connection_event=lambda cb: None,
        local_address=None,
    )
    return IutActions(stack), hci


def _subrate_params() -> bytes:
    return struct.pack("<HHHHH", SUBRATE_MIN, SUBRATE_MAX, LATENCY,
                       CONT_NUMBER, TIMEOUT)


@pytest.mark.asyncio
async def test_subrate_request_resolves_handle_and_forwards():
    actions, hci = _make_actions()
    peer = BDAddress.from_string(PEER)
    actions._session.connections[0x0040] = ConnInfo(
        handle=0x0040, peer=peer, transport="le", gatt_client=None
    )
    await actions.subrate_request(peer.to_hci(), _subrate_params())

    assert len(hci.commands) == 1
    cmd = hci.commands[0]
    assert cmd.opcode == HCI_LE_SUBRATE_REQUEST
    assert cmd.parameters == struct.pack(
        "<HHHHHH", 0x0040, SUBRATE_MIN, SUBRATE_MAX, LATENCY,
        CONT_NUMBER, TIMEOUT,
    )


@pytest.mark.asyncio
async def test_subrate_request_unknown_peer_raises():
    actions, hci = _make_actions()
    peer = BDAddress.from_string(PEER)
    with pytest.raises(ValueError, match="no LE connection"):
        await actions.subrate_request(peer.to_hci(), _subrate_params())
    assert hci.commands == []


@pytest.mark.asyncio
async def test_subrate_request_ignores_classic_connections():
    actions, hci = _make_actions()
    peer = BDAddress.from_string(PEER)
    actions._session.connections[0x0007] = ConnInfo(
        handle=0x0007, peer=peer, transport="classic", gatt_client=None
    )
    with pytest.raises(ValueError, match="no LE connection"):
        await actions.subrate_request(peer.to_hci(), _subrate_params())
    assert hci.commands == []


@pytest.mark.asyncio
async def test_subrate_request_rejects_short_params():
    actions, _ = _make_actions()
    peer = BDAddress.from_string(PEER)
    actions._session.connections[0x0040] = ConnInfo(
        handle=0x0040, peer=peer, transport="le", gatt_client=None
    )
    with pytest.raises(ValueError, match="expected 10 param bytes"):
        await actions.subrate_request(peer.to_hci(), b"\x01\x02")


# ---------------------------------------------------------------------------
# GapService SUBRATE_REQUEST (BTP op 0x2b)
# ---------------------------------------------------------------------------

class _FakeTester:
    def __init__(self) -> None:
        self.events: list[BtpFrame] = []

    async def emit_event(self, frame: BtpFrame) -> None:
        self.events.append(frame)


class _FakeActions:
    def __init__(self) -> None:
        self.calls: list = []

    async def subrate_request(self, addr_bytes: bytes, params: bytes) -> None:
        self.calls.append((bytes(addr_bytes), bytes(params)))


def _subrate_body(addr_type: int, addr_hci: bytes) -> bytes:
    return (bytes([addr_type]) + addr_hci
            + struct.pack("<HHHHH", SUBRATE_MIN, SUBRATE_MAX, LATENCY,
                          CONT_NUMBER, TIMEOUT))


@pytest.mark.asyncio
async def test_subrate_request_handler_forwards_addr_and_params():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    peer = BDAddress.from_string(PEER)

    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_SUBRATE_REQUEST, controller_index=0,
        data=_subrate_body(op.GAP_ADDR_TYPE_PUBLIC, peer.to_hci()),
    )

    assert status == op.BTP_STATUS_SUCCESS
    assert actions.calls == [(peer.to_hci(), _subrate_params())]


@pytest.mark.asyncio
async def test_subrate_request_handler_short_body_fails():
    svc = GapService(actions=_FakeActions(), tester=_FakeTester())
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_SUBRATE_REQUEST, controller_index=0, data=b"\x00" * 16,
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_subrate_request_handler_action_error_fails():
    """A missing LE connection ('no LE connection to ...') must come back as
    BTP_STATUS_FAILED, not escape as an exception into the socket loop."""
    class _Raising:
        async def subrate_request(self, addr_bytes, params):
            raise ValueError("no LE connection")

    svc = GapService(actions=_Raising(), tester=_FakeTester())
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_SUBRATE_REQUEST, controller_index=0,
        data=_subrate_body(0, bytes(6)),
    )
    assert status == op.BTP_STATUS_FAILED


# ---------------------------------------------------------------------------
# Stack parses the LE Subrate Change event (LE Meta subevent 0x23)
# ---------------------------------------------------------------------------

def _subrate_change_params(status: int, handle: int, factor: int, latency: int,
                           cont: int, timeout: int) -> bytes:
    return (bytes([status]) + struct.pack("<HHHHH", handle, factor, latency,
                                          cont, timeout))


@pytest.mark.asyncio
async def test_stack_fires_subrate_change_listener():
    from pybluehost.hci.constants import LEMetaSubEvent
    from pybluehost.hci.packets import HCI_LE_Meta_Event
    from pybluehost.stack import Stack

    stack = await Stack.virtual()
    seen: list = []
    stack.on_subrate_change(lambda *args: seen.append(args))

    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_SUBRATE_CHANGE,
        subevent_parameters=_subrate_change_params(
            status=0x00, handle=0x0040, factor=SUBRATE_MAX, latency=LATENCY,
            cont=CONT_NUMBER, timeout=TIMEOUT,
        ),
    )
    await stack._on_hci_event(event)

    # Subrate_Factor reported by the controller is the *actual* factor it chose
    # (<= the requested Subrate_Max), not the requested value.
    assert seen == [(0x0040, 0x00, SUBRATE_MAX, LATENCY, CONT_NUMBER, TIMEOUT)]
    await stack.close()


@pytest.mark.asyncio
async def test_stack_ignores_other_le_meta_subevents():
    from pybluehost.hci.constants import LEMetaSubEvent
    from pybluehost.hci.packets import HCI_LE_Meta_Event
    from pybluehost.stack import Stack

    stack = await Stack.virtual()
    seen: list = []
    stack.on_subrate_change(lambda *args: seen.append(args))

    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_CONNECTION_COMPLETE,
        subevent_parameters=_subrate_change_params(0x00, 0x0040, 20, 100, 5, 3000),
    )
    await stack._on_hci_event(event)
    assert seen == []
    await stack.close()


@pytest.mark.asyncio
async def test_stack_ignores_truncated_subrate_change():
    from pybluehost.hci.constants import LEMetaSubEvent
    from pybluehost.hci.packets import HCI_LE_Meta_Event
    from pybluehost.stack import Stack

    stack = await Stack.virtual()
    seen: list = []
    stack.on_subrate_change(lambda *args: seen.append(args))

    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_SUBRATE_CHANGE,
        subevent_parameters=bytes(10),  # one byte short of the 11-byte body
    )
    await stack._on_hci_event(event)
    assert seen == []
    await stack.close()


# ---------------------------------------------------------------------------
# GapService.on_subrate_change (BTP ev 0x92)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subrate_change_event_layout_matches_autopts():
    """auto-pts ``gap_subrate_change_ev_`` unpacks ``<B6sBHHHHH``:
    addr_type + addr(6) + status + subrate_factor + peripheral_latency +
    continuation_number + supervision_timeout = 18 bytes. The address must be
    the peer's in HCI (little-endian) order — auto-pts compares it against its
    own LT address."""
    tester = _FakeTester()
    svc = GapService(actions=_FakeActions(), tester=tester)
    peer = BDAddress.from_string(PEER)

    svc.on_subrate_change(
        addr=peer.to_hci(), addr_type=op.GAP_ADDR_TYPE_PUBLIC, status=0x00,
        handle=0x0040, subrate_factor=SUBRATE_MAX, peripheral_latency=LATENCY,
        continuation_number=CONT_NUMBER, supervision_timeout=TIMEOUT,
    )
    await asyncio.sleep(0)

    assert len(tester.events) == 1
    event = tester.events[0]
    assert event.service == op.SERVICE_GAP
    assert event.opcode == op.OP_GAP_EVENT_SUBRATE_CHANGE
    assert event.opcode == 0x92
    assert len(event.data) == 18
    assert event.data == (
        bytes([op.GAP_ADDR_TYPE_PUBLIC]) + peer.to_hci()
        + struct.pack("<BHHHHH", 0x00, 0x0040, SUBRATE_MAX, LATENCY,
                      CONT_NUMBER, TIMEOUT)
    )


@pytest.mark.asyncio
async def test_subrate_change_event_address_is_little_endian():
    """le_bytes_to_hex_str reverses the event address, so the emitted bytes must
    be HCI order — the display-order ``.address`` would reverse to a bogus MAC
    that never matches auto-pts's LT address."""
    tester = _FakeTester()
    svc = GapService(actions=_FakeActions(), tester=tester)
    peer = BDAddress.from_string(PEER)

    svc.on_subrate_change(
        addr=peer.to_hci(), addr_type=0, status=0, handle=0x0040,
        subrate_factor=20, peripheral_latency=100, continuation_number=5,
        supervision_timeout=3000,
    )
    await asyncio.sleep(0)

    assert tester.events[0].data[1:7] == peer.to_hci()
    assert tester.events[0].data[1:7] != peer.address


@pytest.mark.asyncio
async def test_subrate_change_event_without_tester_is_safe():
    svc = GapService(actions=_FakeActions(), tester=None)
    svc.on_subrate_change(
        addr=bytes(6), addr_type=0, status=0, handle=0x0040,
        subrate_factor=20, peripheral_latency=100, continuation_number=5,
        supervision_timeout=3000,
    )
    await asyncio.sleep(0)
