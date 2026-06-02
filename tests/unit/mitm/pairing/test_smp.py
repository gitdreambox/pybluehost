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
    # 拒绝 → 永不完成,_pump 会抛 AssertionError(预期)
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
    # 过短公钥:应 _fail 而非抛异常
    await resp.feed(P.encode(P.PAIRING_PUBLIC_KEY, b"\x01\x02\x03"))
    assert resp._failed is True
    assert not resp.is_complete()
