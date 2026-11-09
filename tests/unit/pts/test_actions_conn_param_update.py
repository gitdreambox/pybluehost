"""Connection Parameter Update (BTP GAP CONN_PARAM_UPDATE op 0x16 + DEVICE_CONNECTED
conn-params baseline) — PTS GAP/CONN/CPUP.

Auto-pts's DEVICE_CONNECTED handler stores the reported (interval, latency,
supervision_timeout) as ``stack.gap.conn_params``; WID 46 reads it, bumps latency,
and sends CONN_PARAM_UPDATE for the IUT to perform. Two pieces must line up:

1. DEVICE_CONNECTED must carry the *real* connection params (not zeros) — the
   stack captures them from LE Connection Complete into ``_le_conn_params``.
2. The IUT must actually send HCI LE_Connection_Update when CONN_PARAM_UPDATE
   arrives — ``IutActions.conn_param_update`` resolves the peer's LE handle and
   forwards to ``BLEConnectionManager.connection_update``.
"""
from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest

from pybluehost.ble.gap import BLEConnectionManager
from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import HCI_LE_CONNECTION_UPDATE
from pybluehost.pts.actions import ConnInfo, IutActions

PEER = "94:53:FF:1E:6A:EE"


class _FakeHCI:
    def __init__(self) -> None:
        self.commands: list = []

    async def send_command(self, cmd):
        self.commands.append(cmd)
        return SimpleNamespace(status=0)


# ---------------------------------------------------------------------------
# BLEConnectionManager.connection_update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connection_update_sends_le_connection_update_command():
    hci = _FakeHCI()
    mgr = BLEConnectionManager(hci=hci)
    await mgr.connection_update(0x0040, itvl_min=0x0030, itvl_max=0x0046,
                                latency=0x0001, supervision_timeout=0x01F4)

    assert len(hci.commands) == 1
    cmd = hci.commands[0]
    assert cmd.opcode == HCI_LE_CONNECTION_UPDATE
    assert cmd.parameters == struct.pack(
        "<HHHHHHH", 0x0040, 0x0030, 0x0046, 0x0001, 0x01F4, 0x0000, 0x0000
    )


# ---------------------------------------------------------------------------
# IutActions.conn_param_update
# ---------------------------------------------------------------------------

def _make_actions(role: int = 0x00) -> tuple[IutActions, _FakeHCI, "_FakeL2CAP"]:
    hci = _FakeHCI()
    l2cap = _FakeL2CAP(role=role)
    stack = SimpleNamespace(
        config=SimpleNamespace(bond_storage=None),
        _smp=SimpleNamespace(_bond_storage=None),
        gap=SimpleNamespace(ble_connections=BLEConnectionManager(hci=hci)),
        l2cap=l2cap,
        on_connection_event=lambda cb: None,
        local_address=None,
    )
    return IutActions(stack), hci, l2cap


class _FakeL2CAP:
    """Stands in for L2CAPManager: reports the LE role under test and records
    peripheral-side Connection Parameter Update Requests."""

    def __init__(self, role: int = 0x00) -> None:
        self.role = role
        self.cpu_requests: list = []

    def le_role(self, handle: int) -> int:
        return self.role

    async def request_le_conn_param_update(
        self, *, handle: int, itvl_min: int, itvl_max: int,
        latency: int, timeout: int, timeout_s: float = 5.0,
    ) -> int:
        self.cpu_requests.append((handle, itvl_min, itvl_max, latency, timeout))
        return 0x0000


@pytest.mark.asyncio
async def test_conn_param_update_resolves_handle_and_forwards():
    actions, hci, _ = _make_actions()
    peer = BDAddress.from_string(PEER)
    actions._session.connections[0x0040] = ConnInfo(
        handle=0x0040, peer=peer, transport="le", gatt_client=None
    )
    params = struct.pack("<HHHH", 0x0030, 0x0046, 0x0001, 0x01F4)
    await actions.conn_param_update(peer.to_hci(), params)

    assert len(hci.commands) == 1
    cmd = hci.commands[0]
    assert cmd.opcode == HCI_LE_CONNECTION_UPDATE
    assert cmd.parameters == struct.pack(
        "<HHHHHHH", 0x0040, 0x0030, 0x0046, 0x0001, 0x01F4, 0x0000, 0x0000
    )


@pytest.mark.asyncio
async def test_conn_param_update_as_peripheral_uses_l2cap_signaling():
    """L2CAP/LE/CPU/BV-01-C: the CPU procedure is peripheral→central only, so a
    peripheral IUT must carry it on the L2CAP signalling channel (0x12) rather
    than HCI LE_Connection_Update (which is the central's LL procedure)."""
    actions, hci, l2cap = _make_actions(role=0x01)
    peer = BDAddress.from_string(PEER)
    actions._session.connections[0x0040] = ConnInfo(
        handle=0x0040, peer=peer, transport="le", gatt_client=None
    )
    params = struct.pack("<HHHH", 0x0030, 0x0046, 0x0001, 0x01F4)
    await actions.conn_param_update(peer.to_hci(), params)

    assert l2cap.cpu_requests == [(0x0040, 0x0030, 0x0046, 0x0001, 0x01F4)]
    assert hci.commands == [], "peripheral must not use the central-only LL procedure"


@pytest.mark.asyncio
async def test_conn_param_update_unknown_peer_raises():
    actions, hci, _ = _make_actions()
    peer = BDAddress.from_string(PEER)
    params = struct.pack("<HHHH", 0x0030, 0x0046, 0x0001, 0x01F4)
    with pytest.raises(ValueError, match="no LE connection"):
        await actions.conn_param_update(peer.to_hci(), params)
    assert hci.commands == []


@pytest.mark.asyncio
async def test_conn_param_update_ignores_classic_connections():
    """A classic (BR/EDR) connection to the same peer must not be picked — the
    update is LE-only."""
    actions, hci, _ = _make_actions()
    peer = BDAddress.from_string(PEER)
    actions._session.connections[0x0007] = ConnInfo(
        handle=0x0007, peer=peer, transport="classic", gatt_client=None
    )
    params = struct.pack("<HHHH", 0x0030, 0x0046, 0x0001, 0x01F4)
    with pytest.raises(ValueError, match="no LE connection"):
        await actions.conn_param_update(peer.to_hci(), params)
    assert hci.commands == []


# ---------------------------------------------------------------------------
# Stack captures connection params from LE Connection Complete
# ---------------------------------------------------------------------------

def _conn_complete_params(*, enhanced: bool, handle: int, itvl: int,
                          latency: int, timeout: int) -> bytes:
    base = b"\x00" + struct.pack("<H", handle) + bytes([0x01, 0x00]) + bytes(6)
    if enhanced:
        base += bytes(12)  # local_rpa + peer_rpa
    return base + struct.pack("<HHH", itvl, latency, timeout) + bytes([0x00])


@pytest.mark.asyncio
async def test_stack_captures_conn_params_from_connection_complete():
    from pybluehost.hci.constants import LEMetaSubEvent
    from pybluehost.hci.packets import HCI_LE_Meta_Event
    from pybluehost.stack import Stack

    stack = await Stack.virtual()
    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_CONNECTION_COMPLETE,
        subevent_parameters=_conn_complete_params(
            enhanced=False, handle=0x0040, itvl=0x0030, latency=0x0001, timeout=0x01F4
        ),
    )
    await stack._on_hci_event(event)
    assert stack._le_conn_params[0x0040] == (0x0030, 0x0001, 0x01F4)
    await stack.close()


@pytest.mark.asyncio
async def test_stack_captures_conn_params_from_enhanced_connection_complete():
    """Enhanced Connection Complete (0x0A) inserts local+peer RPA after the peer
    address, shifting the params by 12 bytes."""
    from pybluehost.hci.constants import LEMetaSubEvent
    from pybluehost.hci.packets import HCI_LE_Meta_Event
    from pybluehost.stack import Stack

    stack = await Stack.virtual()
    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_ENHANCED_CONNECTION_COMPLETE,
        subevent_parameters=_conn_complete_params(
            enhanced=True, handle=0x0041, itvl=0x0018, latency=0x0000, timeout=0x00C8
        ),
    )
    await stack._on_hci_event(event)
    assert stack._le_conn_params[0x0041] == (0x0018, 0x0000, 0x00C8)
    await stack.close()


@pytest.mark.asyncio
async def test_conn_params_available_during_connected_event():
    """The params must be captured BEFORE the connected event fires — pts-tester's
    DEVICE_CONNECTED synthesis reads _le_conn_params synchronously from inside the
    connection-event callback, so a listener must see them already populated."""
    from pybluehost.hci.constants import LEMetaSubEvent
    from pybluehost.hci.packets import HCI_LE_Meta_Event
    from pybluehost.stack import Stack

    stack = await Stack.virtual()
    seen: dict[int, tuple[int, int, int] | None] = {}
    stack.on_connection_event(
        lambda ev: seen.setdefault(ev.handle, stack._le_conn_params.get(ev.handle))
        if ev.state == "connected" else None
    )
    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_CONNECTION_COMPLETE,
        subevent_parameters=_conn_complete_params(
            enhanced=False, handle=0x0042, itvl=0x0024, latency=0x0002, timeout=0x01F4
        ),
    )
    await stack._on_hci_event(event)
    assert seen[0x0042] == (0x0024, 0x0002, 0x01F4)
    await stack.close()


@pytest.mark.asyncio
async def test_le_connected_event_marks_transport_le_even_for_high_handle():
    """LE connection handles can be >= 0x0100 (AX201 hands out 0x0E01). The
    connected event must carry transport="le" explicitly — the IUT session table
    otherwise falls back to a handle-threshold guess and mis-marks it "classic",
    which makes conn_param_update fail with 'no LE connection' (GAP/CONN/CPUP/BV-01)."""
    from pybluehost.hci.constants import LEMetaSubEvent
    from pybluehost.hci.packets import HCI_LE_Meta_Event
    from pybluehost.stack import Stack

    stack = await Stack.virtual()
    seen: dict[int, str | None] = {}
    stack.on_connection_event(
        lambda ev: seen.setdefault(ev.handle, ev.transport)
        if ev.state == "connected" else None
    )
    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_CONNECTION_COMPLETE,
        subevent_parameters=_conn_complete_params(
            enhanced=False, handle=0x0E01, itvl=0x0042, latency=0x0001, timeout=0x07D0
        ),
    )
    await stack._on_hci_event(event)
    assert seen[0x0E01] == "le"
    await stack.close()
