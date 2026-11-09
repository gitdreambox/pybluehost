"""Bond-storage selection for the PTS IUT (`pybluehost app pts-tester`).

A fresh pts-tester process is spawned per PTS test case, so by default the IUT
starts each case with an empty bond store. ``PYBLUEHOST_PTS_BOND_STORE`` opts
into a file-backed store that survives the case boundary, for cases where the
IUT is required to already hold a bond when the case starts.

Note that this only covers the IUT's half. GAP/SEC/AUT/BV-13-C and BV-14-C also
need the *Lower Tester* to hold the bond, and it never does — PTS deletes its
host LTK at case start. Those two are blocked by the test case (SIG errata
ES-28650); see AGENTS.md.
"""
import pytest

from pybluehost.ble.smp import BDAddress, BondInfo, InMemoryBondStorage, JsonBondStorage
from pybluehost.cli.app.pts_tester import BOND_STORE_ENV, _make_bond_storage


def test_default_bond_storage_is_in_memory(monkeypatch):
    monkeypatch.delenv(BOND_STORE_ENV, raising=False)
    assert isinstance(_make_bond_storage(), InMemoryBondStorage)


def test_bond_store_env_selects_a_file_backed_store(monkeypatch, tmp_path):
    monkeypatch.setenv(BOND_STORE_ENV, str(tmp_path / "bonds.json"))
    assert isinstance(_make_bond_storage(), JsonBondStorage)


@pytest.mark.asyncio
async def test_bonds_survive_a_new_pts_tester_process(monkeypatch, tmp_path):
    monkeypatch.setenv(BOND_STORE_ENV, str(tmp_path / "bonds.json"))
    peer = BDAddress.from_string("5C:67:83:07:04:EE")

    first = _make_bond_storage()
    await first.save_bond(BondInfo(peer_address=peer, ltk=b"\x11" * 16, ediv=0x1234))

    # A second pts-tester reads the same file — a bond held across the case
    # boundary is the property any "previous bond exists" case would need.
    second = _make_bond_storage()
    bond = await second.load_bond(peer)
    assert bond is not None
    assert bond.ltk == b"\x11" * 16
    assert bond.ediv == 0x1234
