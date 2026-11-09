"""GAP/CONN/ACEP auto-connection preamble (BV-03/04) — resolving list + RPA
initiator address.

The Auto Connection Establishment procedure (Core Vol 3 Part C §9.3.5) has the
IUT keep the LT identity in the controller resolving list and the filter
accept list, then connect autonomously to whatever advertises an address that
resolves to that identity. The Pass verdict additionally checks that the IUT
initiates FROM a resolvable private address.

The LT's RPA is generated from the IRK it distributes during the preamble
pairing. The peer resolving-list entry must prefer that bonded value; the
legacy all-zero workspace IRK is only a no-bond fallback. Installing the zero
entry first is harmful because a subsequent bond-aware add of the same peer
identity is rejected as a duplicate and cannot replace the wrong key.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pybluehost.pts.actions import PTS_IUT_IRK, IutActions

PEER = "94:53:FF:1E:6A:EE"


def _make_actions():
    privacy = SimpleNamespace(
        generate_rpa=lambda irk, random_bytes=None: b"\x71" * 6,
        set_random_address=AsyncMock(return_value=True),
        add_to_resolving_list=AsyncMock(),
        set_address_resolution=AsyncMock(return_value=True),
        stop_rotation=AsyncMock(),
        _current_address=None,
        _resolution_enabled=False,
        _irk=None,
    )
    storage = SimpleNamespace(load_bond=AsyncMock(return_value=None))
    stack = SimpleNamespace(
        config=SimpleNamespace(bond_storage=storage),
        gap=SimpleNamespace(ble_privacy=privacy),
        _smp=None,
        on_connection_event=lambda cb: None,
        local_address=None,
    )
    return IutActions(stack), privacy


@pytest.mark.asyncio
async def test_prepare_auto_connection_programs_rpa_list_and_resolution():
    """The preamble order matters: the controller refuses LE_Set_Random_Address
    while address resolution is enabled (0x0C), so the RPA write must precede
    the resolving-list + resolution-enable programming."""
    from pybluehost.core.address import BDAddress

    actions, privacy = _make_actions()
    peer = BDAddress.from_string(PEER)
    bonded_peer_irk = bytes.fromhex("64d317c6b4a68ae33bbe81830f61783e")
    actions.stack.config.bond_storage.load_bond.return_value = SimpleNamespace(
        peer_address=peer, irk=bonded_peer_irk,
    )
    order: list[str] = []
    privacy.set_random_address.side_effect = (
        lambda *a, **k: order.append("rpa"))
    privacy.add_to_resolving_list.side_effect = (
        lambda *a, **k: order.append("list"))
    privacy.set_address_resolution.side_effect = (
        lambda *a, **k: order.append("resolution"))

    await actions.prepare_auto_connection(PEER)

    privacy.set_random_address.assert_awaited_once()
    privacy.add_to_resolving_list.assert_awaited_once()
    peer_addr, peer_irk, local_irk = privacy.add_to_resolving_list.await_args.args
    assert peer_addr == peer.to_hci()  # wire order
    # The LT's current RPA is generated from the IRK it distributed during the
    # preamble pairing. Installing a zero-IRK entry first is not harmless:
    # the later bond-aware add is rejected as a duplicate and cannot repair it.
    assert peer_irk == bonded_peer_irk
    assert local_irk == PTS_IUT_IRK
    privacy.set_address_resolution.assert_awaited_once_with(True)
    # Order: RPA write BEFORE resolution enable (the controller answers
    # LE_Set_Random_Address with 0x0C once resolution is on).
    assert order == ["rpa", "list", "resolution"]


@pytest.mark.asyncio
async def test_prepare_auto_connection_reuses_an_already_programmed_rpa():
    """WID 400 runs after SET_PRIVACY has already programmed an RPA from the
    same IRK. Re-writing it needs LE_Set_Address_Resolution_Enable(False)
    first, and this Intel firmware answers 0x0C to *both* resolution toggles
    while privacy state is live — every retry then fails and the initiator
    never comes up (GAP/CONN/ACEP/BV-03/04, GAP/PRIV/CONN/BV-11 on the
    2026-11-02 BE200 rig). Reuse the programmed address and leave an already
    enabled controller resolution alone."""
    actions, privacy = _make_actions()
    privacy._current_address = b"\x71" * 6
    privacy._resolution_enabled = True
    privacy._irk = PTS_IUT_IRK

    await actions.prepare_auto_connection(PEER)

    privacy.set_random_address.assert_not_awaited()
    privacy.set_address_resolution.assert_not_awaited()
    privacy.add_to_resolving_list.assert_awaited_once()
    _peer, _peer_irk, local_irk = privacy.add_to_resolving_list.await_args.args
    assert local_irk == PTS_IUT_IRK


@pytest.mark.asyncio
async def test_prepare_auto_connection_enables_resolution_only_when_off():
    """A pre-programmed RPA still needs resolution enabled when an earlier
    step left it off; the address write itself must not be repeated."""
    actions, privacy = _make_actions()
    privacy._current_address = b"\x71" * 6
    privacy._resolution_enabled = False
    privacy._irk = PTS_IUT_IRK

    await actions.prepare_auto_connection(PEER)

    privacy.set_random_address.assert_not_awaited()
    privacy.set_address_resolution.assert_awaited_once_with(True)


@pytest.mark.asyncio
async def test_prepare_auto_connection_without_privacy_manager_raises():
    """A stack without a privacy manager cannot honor the RPA requirement —
    fail loudly instead of silently connecting from the public address (the
    Pass verdict watches the initiator address type)."""
    stack = SimpleNamespace(
        gap=SimpleNamespace(ble_privacy=None),
        _smp=None,
        on_connection_event=lambda cb: None,
        local_address=None,
    )
    actions = IutActions(stack)
    with pytest.raises(RuntimeError):
        await actions.prepare_auto_connection(PEER)


@pytest.mark.asyncio
async def test_prepare_auto_connection_pins_the_local_irk_before_use():
    """The RPA must be built from the SAME IRK published as
    TSPX_iut_device_IRK — pin it on the SMP manager so a later pairing
    distributes what the LT can resolve."""
    actions, privacy = _make_actions()

    class _Smp:
        local_irk = None

        def set_local_irk(self, irk):
            self.local_irk = irk

    smp = _Smp()
    actions._stack = SimpleNamespace(
        gap=actions._stack.gap, _smp=smp,
        on_connection_event=lambda cb: None, local_address=None,
    )

    await actions.prepare_auto_connection(PEER)

    assert smp.local_irk == PTS_IUT_IRK


@pytest.mark.asyncio
async def test_prepare_auto_connection_stops_rotation_before_hci_setup():
    """SET_PRIVACY starts a 5 s host RPA rotation. It must not rewrite the
    random address while ACEP programs the resolving list or starts the
    initiator: the BE200 rejects that whole sequence with 0x0C."""
    actions, privacy = _make_actions()
    order: list[str] = []
    privacy.stop_rotation.side_effect = lambda: order.append("stop")
    privacy.set_random_address.side_effect = lambda *a: order.append("rpa")
    privacy.add_to_resolving_list.side_effect = lambda *a: order.append("list")
    privacy.set_address_resolution.side_effect = lambda *a: order.append("resolution")

    await actions.prepare_auto_connection(PEER)

    assert order == ["stop", "rpa", "list", "resolution"]
