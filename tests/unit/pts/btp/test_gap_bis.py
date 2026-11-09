"""BTP GAP CREATE_BIG (0x2d) / BIS_BROADCAST (0x2e) — PTS GAP/BIS/BBM/BV-01-C.

auto-pts drives the broadcaster flow with ``gap_create_big`` (body
``<BBIHBBBB`` + encryption byte + optional 16-byte broadcast code) and
``gap_bis_broadcast`` (``bis_id(1) + len(1) + data``), then — once the IUT has
created the BIG and wired the HCI data paths — expects one
BIS_DATA_PATH_SETUP (ev 0x95) per BIS so ``hdl_wid_357``'s
``stack.gap.big_bis_data_path_setup`` fills. The 0x95 payload layout is
``<B6sB`` (addr_type + addr + bis_id); the model ignores the address fields
and only appends bis_id.
"""
from __future__ import annotations

import asyncio
import struct

import pytest

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import BtpFrame
from pybluehost.pts.btp.services.gap import GapService


class _FakeTester:
    def __init__(self) -> None:
        self.events: list[BtpFrame] = []

    async def emit_event(self, frame: BtpFrame) -> None:
        self.events.append(frame)


class _FakeActions:
    def __init__(self, handles: dict[int, int] | None = None,
                 error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.handles = handles if handles is not None else {0: 0x0E01}
        self.error = error

    async def create_big(self, **kwargs) -> dict[int, int]:
        self.calls.append(("create_big", kwargs))
        if self.error is not None:
            raise self.error
        return self.handles

    async def bis_broadcast(self, bis_id: int, data: bytes) -> None:
        self.calls.append(("bis_broadcast", {"bis_id": bis_id, "data": data}))


def _big_body(**over) -> bytes:
    body = struct.pack(
        "<BBIHBBBB",
        over.get("bis_id", 0),
        over.get("num_bis", 1),
        over.get("sdu_interval", 10000),
        over.get("latency", 20),
        over.get("rtn", 2),
        over.get("phy", 1),
        over.get("packing", 0),
        over.get("framing", 0),
    ) + bytes([over.get("encryption", 0)])
    if over.get("encryption"):
        body += over.get("broadcast_code", bytes(16))
    return body


async def _finish_big(svc: GapService) -> None:
    task = getattr(svc, "_big_task", None)
    if task is not None:
        await task


# ---------------------------------------------------------------------------
# CREATE_BIG (0x2d)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_big_responds_immediately_and_wires_data_paths():
    """The BIG takes seconds on air; the BTP response must not wait for it
    (the PAIR-op-0x11 deadlock family). Data-path events follow later, on the
    background task."""
    tester = _FakeTester()
    actions = _FakeActions(handles={0: 0x0E01})
    svc = GapService(actions=actions, tester=tester)

    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_CREATE_BIG, controller_index=0, data=_big_body(),
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert actions.calls == []  # nothing awaited the command handler

    await _finish_big(svc)
    kind, call = actions.calls[0]
    assert kind == "create_big"
    assert call["num_bis"] == 1
    assert call["sdu_interval_us"] == 10000
    assert call["max_transport_latency_ms"] == 20
    assert call["rtn"] == 2
    assert call["phy"] == 1
    assert call["packing"] == 0
    assert call["framing"] == 0
    assert call["encryption"] == 0


@pytest.mark.asyncio
async def test_create_big_emits_one_data_path_event_per_bis():
    tester = _FakeTester()
    actions = _FakeActions(handles={0: 0x0E01, 1: 0x0E02})
    svc = GapService(actions=actions, tester=tester)
    await svc.dispatch(
        opcode=op.OP_GAP_CREATE_BIG, controller_index=0,
        data=_big_body(num_bis=2),
    )
    await _finish_big(svc)

    assert [e.opcode for e in tester.events] == [
        op.OP_GAP_EVENT_BIS_DATA_PATH_SETUP,
        op.OP_GAP_EVENT_BIS_DATA_PATH_SETUP,
    ]
    for bis_id, frame in enumerate(tester.events):
        # <B6sB>: addr_type(1) + addr(6, ignored by the model) + bis_id(1).
        assert frame.data == bytes([0x00]) + bytes(6) + bytes([bis_id])


@pytest.mark.asyncio
async def test_create_big_encryption_form_carries_the_broadcast_code():
    tester = _FakeTester()
    code = bytes(range(16))
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_CREATE_BIG, controller_index=0,
        data=_big_body(encryption=1, broadcast_code=code),
    )
    assert status == op.BTP_STATUS_SUCCESS
    await _finish_big(svc)
    kind, call = actions.calls[0]
    assert kind == "create_big"
    assert call["encryption"] == 1
    assert call["broadcast_code"] == code


@pytest.mark.asyncio
async def test_create_big_short_body_fails():
    svc = GapService(actions=_FakeActions(), tester=_FakeTester())
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_CREATE_BIG, controller_index=0, data=b"\x00" * 12,
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_create_big_encryption_form_requires_the_full_code():
    svc = GapService(actions=_FakeActions(), tester=_FakeTester())
    # encryption=1 but only 5 code bytes — a truncated body (18 < 29).
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_CREATE_BIG, controller_index=0,
        data=_big_body(encryption=1, broadcast_code=b"\x01\x02\x03\x04\x05"),
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_create_big_background_failure_does_not_crash():
    """If LE_Create_BIG fails on air, the command response is already gone —
    the background task must swallow the error (log it), not take the
    pts-tester down."""
    tester = _FakeTester()
    actions = _FakeActions(error=RuntimeError("controller rejected 0x2068"))
    svc = GapService(actions=actions, tester=tester)
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_CREATE_BIG, controller_index=0, data=_big_body(),
    )
    assert status == op.BTP_STATUS_SUCCESS
    await _finish_big(svc)  # must not raise
    assert tester.events == []


# ---------------------------------------------------------------------------
# BIS_BROADCAST (0x2e)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bis_broadcast_forwards_bis_id_and_payload():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_BIS_BROADCAST, controller_index=0,
        data=bytes([0, 3]) + b"\x01\x02\x03",
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert actions.calls == [("bis_broadcast", {"bis_id": 0, "data": b"\x01\x02\x03"})]


@pytest.mark.asyncio
async def test_bis_broadcast_short_body_fails():
    svc = GapService(actions=_FakeActions(), tester=_FakeTester())
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_BIS_BROADCAST, controller_index=0, data=b"\x00",
    )
    assert status == op.BTP_STATUS_FAILED
