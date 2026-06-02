from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate


async def test_auto_confirm_yes():
    d = AutoConfirmDelegate()
    assert await d.confirm_numeric("phone", 123456) is True
    assert await d.confirm_numeric("target", 654321) is True


import asyncio

from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate
from pybluehost.cli.app.mitm.pairing.smp import ScPairing


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
