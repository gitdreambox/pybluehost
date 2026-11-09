"""IutActions.create_big / bis_broadcast — the BTP → IsoBroadcastManager bridge.

BTP phy values are the HCI bitmask values verbatim (``BTP_GAP_CMD_CREATE_BIG_
PHY_1M/2M/CODED`` = 0x01/0x02/0x04 — checked against autopts/pybtp/defs.py),
so they pass through untouched. Defaults mirror what upstream's ``hdl_wid_300``
passes to ``gap_create_big`` (interval 10000 µs, latency 20 ms, rtn 2,
PHY 2M), so a WID that omits them gets the reference-IUT shape.
"""
from __future__ import annotations

import pytest
from types import SimpleNamespace

from pybluehost.pts.actions import IutActions


class _FakeIsoBroadcast:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def create_big(self, **kwargs) -> dict[int, int]:
        self.calls.append(("create_big", kwargs))
        return {0: 0x0E01}

    async def bis_broadcast(self, bis_id: int, data: bytes) -> None:
        self.calls.append(("bis_broadcast", {"bis_id": bis_id, "data": data}))


def _make_actions() -> tuple[IutActions, _FakeIsoBroadcast]:
    iso = _FakeIsoBroadcast()
    stack = SimpleNamespace(
        config=SimpleNamespace(bond_storage=None),
        _smp=SimpleNamespace(_bond_storage=None),
        gap=SimpleNamespace(iso_broadcast=iso),
        on_connection_event=lambda cb: None,
        local_address=None,
    )
    return IutActions(stack), iso


@pytest.mark.asyncio
async def test_create_big_defaults_match_the_upstream_wid_shape():
    actions, iso = _make_actions()
    await actions.create_big()
    kwargs = iso.calls[0][1]
    # hdl_wid_300: create_big(0, 1, 10000, 20, code) + auto-pts defaults
    # rtn=2, phy=PHY_2M(0x02), sequential packing, unframed.
    assert kwargs["num_bis"] == 1
    assert kwargs["sdu_interval_us"] == 10000
    assert kwargs["max_transport_latency_ms"] == 20
    assert kwargs["rtn"] == 2
    assert kwargs["phy"] == 0x02
    assert kwargs["packing"] == 0
    assert kwargs["framing"] == 0
    assert kwargs["encryption"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("phy", [0x01, 0x02, 0x04])
async def test_create_big_passes_the_phy_through_verbatim(phy: int):
    actions, iso = _make_actions()
    await actions.create_big(phy=phy)
    assert iso.calls[0][1]["phy"] == phy


@pytest.mark.asyncio
async def test_create_big_only_carries_a_code_when_encrypted():
    actions, iso = _make_actions()
    await actions.create_big(num_bis=1, encryption=1,
                             broadcast_code=bytes(range(16)))
    assert iso.calls[0][1]["broadcast_code"] == bytes(range(16))

    await actions.create_big(num_bis=1, encryption=0, broadcast_code=None)
    assert iso.calls[1][1]["broadcast_code"] is None


@pytest.mark.asyncio
async def test_bis_broadcast_forwards_payload():
    actions, iso = _make_actions()
    await actions.bis_broadcast(0, b"\x00")
    assert iso.calls == [("bis_broadcast", {"bis_id": 0, "data": b"\x00"})]


@pytest.mark.asyncio
async def test_missing_iso_broadcast_manager_raises():
    stack = SimpleNamespace(
        config=SimpleNamespace(bond_storage=None),
        _smp=None,
        gap=SimpleNamespace(),  # no iso_broadcast manager
        on_connection_event=lambda cb: None,
        local_address=None,
    )
    actions = IutActions(stack)
    with pytest.raises(RuntimeError, match="isochronous broadcast"):
        await actions.create_big(num_bis=1)
