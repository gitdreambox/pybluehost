"""IutActions.program_private_address — RPA/NRPA programming + resolution gate.

The Intel BE200 answers ``LE_Set_Address_Resolution_Enable`` with Command
Disallowed (0x0C) in *either* direction while an advertising set is live. When
``program_private_address`` runs after ``SET_PRIVACY`` (or a previous case) has
already turned resolution on, its own ``set_random_address`` path restores
resolution around the address write — so the action's unconditional trailing
``set_address_resolution(True)`` re-enables an already-on state *after*
advertising has resumed, and the controller rejects it (0x0C). The rejection is
harmless state-wise but it is exactly the failure signature seen on
GAP/BROB/BCST/BV-05 and GAP/PRIV/* on the 2026-11 BE200 rig: an
``LE_Set_Address_Resolution_Enable(True) rejected, status=0x0C`` right after the
filter-list programming.

The fix mirrors ``prepare_auto_connection``: only enable resolution when it is
not already enabled.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.pts.actions import PTS_IUT_IRK, IutActions


def _make_privacy(*, resolution_enabled: bool):
    privacy = SimpleNamespace(
        enabled=False,
        enable=AsyncMock(),
        generate_rpa=lambda irk, random_bytes=None: b"\x72" * 6,
        generate_nrpa=lambda random_bytes=None: b"\x34" * 6,
        set_random_address=AsyncMock(return_value=True),
        set_address_resolution=AsyncMock(return_value=True),
        add_to_resolving_list=AsyncMock(),
        start_rotation=AsyncMock(),
        stop_rotation=AsyncMock(),
        _resolution_enabled=resolution_enabled,
        _irk=None,
        _current_address=None,
    )
    privacy.enable.side_effect = lambda irk=None: setattr(privacy, "enabled", True)
    smp = SimpleNamespace(
        local_irk=None,
        set_local_irk=lambda irk: setattr(smp, "local_irk", irk),
    )
    storage = SimpleNamespace(load_bond=AsyncMock(return_value=None))
    stack = SimpleNamespace(
        config=SimpleNamespace(bond_storage=storage),
        gap=SimpleNamespace(ble_privacy=privacy),
        _smp=smp,
        on_connection_event=lambda cb: None,
        local_address=None,
    )
    return IutActions(stack), privacy, smp


@pytest.mark.asyncio
async def test_program_private_address_enables_resolution_when_off():
    """Fresh privacy state: resolution must be switched on once."""
    actions, privacy, smp = _make_privacy(resolution_enabled=False)

    await actions.program_private_address(resolvable=True)

    privacy.enable.assert_awaited_once_with(PTS_IUT_IRK)
    privacy.set_random_address.assert_awaited_once()
    privacy.set_address_resolution.assert_awaited_once_with(True)
    privacy.start_rotation.assert_awaited_once()
    assert smp.local_irk == PTS_IUT_IRK


@pytest.mark.asyncio
async def test_program_private_address_skips_redundant_resolution_enable():
    """When resolution is already on (SET_PRIVACY ran, or a prior case), the
    action must not re-enable it after advertising has resumed — the BE200
    rejects that with 0x0C."""
    actions, privacy, smp = _make_privacy(resolution_enabled=True)

    await actions.program_private_address(resolvable=True)

    privacy.enable.assert_awaited_once_with(PTS_IUT_IRK)
    privacy.set_random_address.assert_awaited_once()
    privacy.set_address_resolution.assert_not_awaited()
    privacy.start_rotation.assert_awaited_once()


@pytest.mark.asyncio
async def test_rpa_activation_after_bonded_disconnect_programs_the_peer_irk():
    """GAP/BROB/BCST/BV-05 pairs over a public-identity connection, disconnects,
    and only then asks for RPA advertising. The peer identity must survive that
    disconnect long enough to program its IRK: in phase 2 the accept list holds
    the LT identity while its SCAN_REQ uses an RPA, so without this resolving-
    list entry the controller never sends the required scan response."""
    actions, privacy, _ = _make_privacy(resolution_enabled=False)
    peer = BDAddress.from_string("FC:9E:53:D5:8D:EB")
    peer_irk = bytes.fromhex("35910545206ed6d69bae3e61f3fd8c06")
    actions.stack.config.bond_storage.load_bond.return_value = SimpleNamespace(
        peer_address=peer, irk=peer_irk,
    )
    actions._on_connection_event(SimpleNamespace(
        state="connected", handle=0x0800, peer_address=peer, transport="le",
    ))
    actions._on_connection_event(SimpleNamespace(
        state="disconnected", handle=0x0800, peer_address=peer, transport="le",
    ))

    await actions.program_private_address(resolvable=True)

    privacy.add_to_resolving_list.assert_awaited_once_with(
        peer.to_hci(), peer_irk, PTS_IUT_IRK,
    )


@pytest.mark.asyncio
async def test_outgoing_connect_stops_rpa_rotation_before_resolution_setup():
    """The first ACEP connection races the rotation started by SET_PRIVACY at
    t+5 s. Freeze host address rotation before any connect-related HCI work;
    advertising cases do not pass through this central-only path."""
    actions, privacy, _ = _make_privacy(resolution_enabled=True)
    peer = BDAddress.from_string("FC:9E:53:D5:8D:EB")
    order: list[str] = []
    privacy.stop_rotation.side_effect = lambda: order.append("stop")
    actions._prepare_rpa_resolution = AsyncMock(
        side_effect=lambda addr: order.append("prepare"))
    actions._stack.connect_gatt = AsyncMock(
        return_value=SimpleNamespace(connection_handle=0x0800))
    actions._stack.l2cap = SimpleNamespace(
        get_fixed_channel=lambda handle, cid: object())

    await actions.connect(peer)

    assert order[:2] == ["stop", "prepare"]
