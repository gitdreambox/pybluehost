"""IutActions.unpair (BTP GAP UNPAIR op 0x12) — remove a peer's bond.

PTS GAP/BOND tests drive WID 135 ("remove the bond") via BTP GAP UNPAIR. The
handler delegates to ``IutActions.unpair``, which must delete the peer's bond
from the stack's bond storage so the next connection is treated as unbonded.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pybluehost.ble.smp import BondInfo, InMemoryBondStorage
from pybluehost.core.address import BDAddress
from pybluehost.pts.actions import IutActions

PEER = "94:53:FF:1E:6A:EE"


def _make_actions(storage: InMemoryBondStorage) -> IutActions:
    stack = SimpleNamespace(
        config=SimpleNamespace(bond_storage=storage),
        _smp=SimpleNamespace(_bond_storage=storage),
        on_connection_event=lambda cb: None,
        local_address=None,
    )
    return IutActions(stack)


@pytest.mark.asyncio
async def test_unpair_deletes_peer_bond():
    storage = InMemoryBondStorage()
    peer = BDAddress.from_string(PEER)
    await storage.save_bond(BondInfo(peer_address=peer, ltk=b"\x01" * 16))
    actions = _make_actions(storage)

    await actions.unpair(peer)

    assert await storage.load_bond(peer) is None, "unpair must remove the peer's bond"


@pytest.mark.asyncio
async def test_unpair_unknown_peer_is_noop():
    """Unpairing a peer with no stored bond must not raise (idempotent)."""
    storage = InMemoryBondStorage()
    actions = _make_actions(storage)
    await actions.unpair(BDAddress.from_string(PEER))  # no bond — should not raise


@pytest.mark.asyncio
async def test_unpair_only_removes_target_peer():
    storage = InMemoryBondStorage()
    peer = BDAddress.from_string(PEER)
    other = BDAddress.from_string("00:1A:7D:DA:71:11")
    await storage.save_bond(BondInfo(peer_address=peer, ltk=b"\x01" * 16))
    await storage.save_bond(BondInfo(peer_address=other, ltk=b"\x02" * 16))
    actions = _make_actions(storage)

    await actions.unpair(peer)

    assert await storage.load_bond(peer) is None
    assert await storage.load_bond(other) is not None, "unrelated bonds must be kept"
