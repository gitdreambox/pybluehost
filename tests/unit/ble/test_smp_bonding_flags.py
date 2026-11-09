"""``_persist_bond`` must honour the negotiated Bonding_Flags.

Core Vol 3 Part H §2.3.4: the keys are stored when either side sets
Bonding_Flags = 0x01 in its Pairing Request/Response.  With both flags clear
the keys only protect that connection, so nothing may be persisted.

GATT/SR/GAN/BV-01-C exercises exactly this: it pairs with Bonding_Flags = 0 and
then, after a reconnect, expects the IUT to have reset the CCCD to 0x0000.  A
stored bond would make the IUT treat the client as bonded and keep 0x0001 —
the case can never pass while non-bonded keys are persisted.
"""

import asyncio
from types import SimpleNamespace

import pytest

from pybluehost.ble import _smp_state as state_mod
from pybluehost.ble.smp import PairingRole
from pybluehost.core.address import BDAddress


class _MemStorage:
    def __init__(self) -> None:
        self.saved = []

    async def save_bond(self, bond) -> None:
        self.saved.append(bond)


def _ctx(storage: _MemStorage, *, local_auth_req: int, peer_auth_req: int):
    return SimpleNamespace(
        peer_address=BDAddress(bytes(6)),
        local_auth_req=local_auth_req,
        peer_auth_req=peer_auth_req,
        received_identity_address=(0, bytes(6)),
        ltk_sc=b"\x11" * 16,
        received_irk=None,
        received_csrk=None,
        role=PairingRole.INITIATOR,
        connection_handle=1,
        _bond_storage=storage,
        pairing_complete=asyncio.get_event_loop().create_future(),
    )


@pytest.fixture(autouse=True)
def _sc_pairing(monkeypatch):
    monkeypatch.setattr(state_mod, "_sc_negotiated", lambda ctx: True)
    monkeypatch.setattr(state_mod, "_association_model", lambda ctx: "just_works")


async def test_bonding_negotiated_stores_the_bond():
    storage = _MemStorage()
    ctx = _ctx(storage, local_auth_req=0x0D, peer_auth_req=0x0D)

    await state_mod._persist_bond(ctx)

    assert len(storage.saved) == 1
    assert storage.saved[0].ltk == b"\x11" * 16


async def test_non_bonded_pairing_does_not_store_the_bond():
    storage = _MemStorage()
    ctx = _ctx(storage, local_auth_req=0x0C, peer_auth_req=0x0C)

    await state_mod._persist_bond(ctx)

    assert storage.saved == []
    # Pairing still completes; only the persistence step is skipped.
    assert ctx.pairing_complete.done()
    assert ctx.pairing_complete.result() is None


async def test_bonding_requested_by_one_side_stores_the_bond():
    storage = _MemStorage()
    ctx = _ctx(storage, local_auth_req=0x0D, peer_auth_req=0x0C)

    await state_mod._persist_bond(ctx)

    assert len(storage.saved) == 1
