"""GAP/SEC/SEM reconnect regression: controller RPA resolution must only be
programmed while privacy is active.

``IutActions._prepare_rpa_resolution`` used to enable controller address
resolution after *any* pairing that distributed an IRK. On the 2026-10 BE200
rig, enabling controller resolution while the peer advertises its public
identity makes the initiator never complete — the GAP/SEC/SEM/BV-56..67
cluster reconnects to the Lower Tester's *public* address, so the whole
cluster timed out / BTP-errored. Resolution is only legitimate for the
privacy cases (GAP/PRIV/CONN, GAP/DISC/RPA), which reach this path after
``SET_PRIVACY`` has put ``privacy.enabled`` True.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.pts.actions import PTS_IUT_IRK, IutActions

PEER = "FC:9E:53:D5:8D:EB"


def _make_actions(*, privacy_enabled: bool):
    bond = SimpleNamespace(
        peer_address=BDAddress.from_string(PEER),
        irk=bytes.fromhex("bdb746936d8b5fc9845dec5f508dd860"),
    )
    storage = SimpleNamespace(load_bond=AsyncMock(return_value=bond))
    privacy = SimpleNamespace(
        enabled=privacy_enabled,
        add_to_resolving_list=AsyncMock(),
        set_address_resolution=AsyncMock(return_value=True),
    )
    stack = SimpleNamespace(
        config=SimpleNamespace(bond_storage=storage),
        gap=SimpleNamespace(ble_privacy=privacy),
        _smp=SimpleNamespace(local_irk=PTS_IUT_IRK, set_local_irk=lambda irk: None),
        on_connection_event=lambda cb: None,
        local_address=None,
    )
    return IutActions(stack), privacy, storage


@pytest.mark.asyncio
async def test_prepare_rpa_resolution_skips_when_privacy_inactive():
    """A bonded, non-privacy reconnect (GAP/SEC/SEM/BV-56..67) must leave
    controller address resolution off — enabling it wedges the BE200 initiator
    against the Lower Tester's public-identity advertising."""
    actions, privacy, storage = _make_actions(privacy_enabled=False)

    await actions._prepare_rpa_resolution(BDAddress.from_string(PEER))

    privacy.add_to_resolving_list.assert_not_awaited()
    privacy.set_address_resolution.assert_not_awaited()
    storage.load_bond.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_rpa_resolution_programs_when_privacy_active():
    """The privacy cases (GAP/PRIV/CONN/BV-10/11, GAP/DISC/RPA/BV-01) still get
    the peer IRK pushed into the resolving list and controller resolution on."""
    actions, privacy, _ = _make_actions(privacy_enabled=True)

    await actions._prepare_rpa_resolution(BDAddress.from_string(PEER))

    privacy.add_to_resolving_list.assert_awaited_once()
    peer_addr, peer_irk, local_irk = privacy.add_to_resolving_list.await_args.args
    assert peer_addr == BDAddress.from_string(PEER).to_hci()   # wire order
    assert peer_irk == bytes.fromhex("bdb746936d8b5fc9845dec5f508dd860")
    assert local_irk == PTS_IUT_IRK
    privacy.set_address_resolution.assert_awaited_once_with(True)


@pytest.mark.asyncio
async def test_prepare_rpa_resolution_no_bond_storage_is_a_noop():
    """A stack without bond storage (or without a privacy manager) must not
    raise — plain connect continues."""
    stack = SimpleNamespace(
        config=SimpleNamespace(bond_storage=None),
        gap=SimpleNamespace(ble_privacy=None),
        _smp=None,
        on_connection_event=lambda cb: None,
        local_address=None,
    )
    actions = IutActions(stack)

    await actions._prepare_rpa_resolution(BDAddress.from_string(PEER))  # no raise
