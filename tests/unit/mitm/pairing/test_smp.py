import asyncio

import pytest

from pybluehost.cli.app.mitm.pairing import smp_pdu as P
from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate
from pybluehost.cli.app.mitm.pairing.smp import ScPairing


async def test_auto_confirm_yes():
    d = AutoConfirmDelegate()
    assert await d.confirm_numeric("phone", 123456) is True
    assert await d.confirm_numeric("target", 654321) is True


async def _pump(a: ScPairing, b: ScPairing):
    a_out, b_out = asyncio.Queue(), asyncio.Queue()
    a.set_output(a_out.put_nowait)
    b.set_output(b_out.put_nowait)
    await a.start()
    for _ in range(60):
        if a.is_complete() and b.is_complete():
            return
        moved = False
        while not a_out.empty():
            await b.feed(a_out.get_nowait()); moved = True
        while not b_out.empty():
            await a.feed(b_out.get_nowait()); moved = True
        if not moved:
            break
    raise AssertionError("SC JW 未在限定轮数内完成")


async def test_sc_just_works_initiator_responder_agree_on_ltk():
    init_addr = bytes([0x00]) + bytes.fromhex("aabbccddeeff")
    resp_addr = bytes([0x00]) + bytes.fromhex("112233445566")
    a = ScPairing(role="initiator", local_addr=init_addr, peer_addr=resp_addr, delegate=AutoConfirmDelegate(), side_name="A")
    b = ScPairing(role="responder", local_addr=resp_addr, peer_addr=init_addr, delegate=AutoConfirmDelegate(), side_name="B")
    await _pump(a, b)
    assert a.is_complete() and b.is_complete()
    assert a.ltk is not None and a.ltk == b.ltk and len(a.ltk) == 16


class _RejectDelegate:
    async def confirm_numeric(self, side_name: str, value: int) -> bool:
        return False


async def test_sc_numeric_reject_no_ltk():
    init_addr = bytes([0x00]) + bytes.fromhex("aabbccddeeff")
    resp_addr = bytes([0x00]) + bytes.fromhex("112233445566")
    a = ScPairing(role="initiator", local_addr=init_addr, peer_addr=resp_addr,
                  delegate=_RejectDelegate(), side_name="A")
    b = ScPairing(role="responder", local_addr=resp_addr, peer_addr=init_addr,
                  delegate=_RejectDelegate(), side_name="B")
    # rejection → never completes; _pump raises AssertionError (expected)
    with pytest.raises(AssertionError):
        await _pump(a, b)
    assert not a.is_complete() and not b.is_complete()
    assert a.ltk is None and b.ltk is None


async def test_malformed_public_key_fails_gracefully():
    resp = ScPairing(
        role="responder",
        local_addr=bytes([0]) + bytes.fromhex("112233445566"),
        peer_addr=bytes([0]) + bytes.fromhex("aabbccddeeff"),
        delegate=AutoConfirmDelegate(), side_name="B",
    )
    sent: list[bytes] = []
    resp.set_output(sent.append)
    await resp.feed(P.encode(P.PAIRING_REQUEST, bytes([0x03, 0x00, 0x09, 16, 0, 0])))
    # public key too short: should _fail instead of raising
    await resp.feed(P.encode(P.PAIRING_PUBLIC_KEY, b"\x01\x02\x03"))
    assert resp._failed is True
    assert not resp.is_complete()


async def test_initiator_aborts_when_peer_refuses_sc():
    init = ScPairing(
        role="initiator",
        local_addr=bytes([0]) + bytes.fromhex("aabbccddeeff"),
        peer_addr=bytes([0]) + bytes.fromhex("112233445566"),
        delegate=AutoConfirmDelegate(), side_name="A",
    )
    sent: list[bytes] = []
    init.set_output(sent.append)
    # responder replies auth_req=0x01 (bonding only, SC bit not set) → must abort, must not send PUBLIC_KEY
    await init.feed(P.encode(P.PAIRING_RESPONSE, bytes([0x03, 0x00, 0x01, 16, 0, 0])))
    assert init._failed is True
    assert not init.is_complete()
    assert all(P.decode(p)[0] != P.PAIRING_PUBLIC_KEY for p in sent)


async def test_responder_aborts_when_initiator_requests_legacy():
    resp = ScPairing(
        role="responder",
        local_addr=bytes([0]) + bytes.fromhex("112233445566"),
        peer_addr=bytes([0]) + bytes.fromhex("aabbccddeeff"),
        delegate=AutoConfirmDelegate(), side_name="B",
    )
    sent: list[bytes] = []
    resp.set_output(sent.append)
    # initiator requests auth_req=0x01 (bonding only, SC bit not set) → must abort, must not send PAIRING_RESPONSE
    await resp.feed(P.encode(P.PAIRING_REQUEST, bytes([0x03, 0x00, 0x01, 16, 0, 0])))
    assert resp._failed is True
    assert not resp.is_complete()
    assert all(P.decode(p)[0] != P.PAIRING_RESPONSE for p in sent)
