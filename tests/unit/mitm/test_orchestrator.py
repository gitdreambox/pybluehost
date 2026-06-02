"""MitmRelay 编排器 + SMP↔ScPairing↔ACL 桥接的 fake 单测。

这里只验证 UNIT-TESTABLE 核心:_build_relay 装配出的 AclRelay,
其 SMP CID(0x06)PDU 能路由到正确的 ScPairing,响应能编回 ACL;
非 SMP PDU(ATT)按 AclRelay 既有行为透传到对侧。

不触碰真实 HCIController —— 用 fake RelaySide 记录 send_acl 调用。
"""
from __future__ import annotations

import asyncio

from pybluehost.cli.app.mitm.acl import (
    CID_ATT,
    CID_SMP,
    PB_FIRST_FLUSH,
    encode_l2cap_basic,
)
from pybluehost.cli.app.mitm.capture import NullTap
from pybluehost.cli.app.mitm.orchestrator import MitmRelay
from pybluehost.cli.app.mitm.pairing import smp_pdu as P
from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate
from pybluehost.cli.app.mitm.relay import RelaySide
from pybluehost.hci.packets import HCIACLData


def _fake_side(name, handle):
    sent = []

    async def send_acl(h, pb, data):
        sent.append((h, pb, data))

    return RelaySide(name=name, handle=handle, acl_max_payload=27, send_acl=send_acl), sent


def _bare_relay():
    """构造一个不依赖真实 pair 的 MitmRelay,仅填好 _build_relay 需要的字段。"""
    relay = MitmRelay.__new__(MitmRelay)
    relay._delegate = AutoConfirmDelegate()
    relay._capture = NullTap()
    relay._pairings = {}
    relay._sides = {}
    return relay


async def test_smp_request_routed_to_downstream_pairing_and_response_emitted():
    relay = _bare_relay()

    phone_side, phone_sent = _fake_side("phone", 0x40)
    target_side, target_sent = _fake_side("target", 0x11)
    addr = bytes([0x00]) + bytes.fromhex("aabbccddeeff")
    addr2 = bytes([0x00]) + bytes.fromhex("112233445566")
    acl_relay = relay._build_relay(phone_side, target_side, addr, addr2, addr2, addr)

    # 手机侧发来一个 PAIRING_REQUEST(作为 downstream/phone 侧的 ACL 帧):
    body = bytes([0x03, 0x00, 0x09, 16, 0, 0])
    req = encode_l2cap_basic(CID_SMP, P.encode(P.PAIRING_REQUEST, body))
    await acl_relay.on_phone_acl(
        HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=req)
    )
    # 让 ensure_future 的 SMP emit 跑起来:
    await asyncio.sleep(0)

    # downstream(responder)pairing 应在 phone 侧回出一个 PAIRING_RESPONSE 的 ACL:
    assert phone_sent, "no SMP response emitted on phone side"
    _, _, data = phone_sent[0]
    assert data[2:4] == bytes([0x06, 0x00])  # CID 0x06
    assert data[4] == P.PAIRING_RESPONSE
    # SMP PDU 本地终结,不应透传到 target 侧:
    assert not target_sent, "SMP PDU 不应被转发到 target 侧"


async def test_non_smp_att_pdu_relayed_to_target_side():
    relay = _bare_relay()

    phone_side, phone_sent = _fake_side("phone", 0x40)
    target_side, target_sent = _fake_side("target", 0x11)
    addr = bytes([0x00]) + bytes.fromhex("aabbccddeeff")
    addr2 = bytes([0x00]) + bytes.fromhex("112233445566")
    acl_relay = relay._build_relay(phone_side, target_side, addr, addr2, addr2, addr)

    # 一个 ATT PDU(CID 0x04)从 phone 侧进来,应透传到 target 侧:
    att_payload = bytes([0x02, 0x17, 0x00])  # 任意 ATT MTU exchange 风格 PDU
    att = encode_l2cap_basic(CID_ATT, att_payload)
    await acl_relay.on_phone_acl(
        HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=att)
    )
    await asyncio.sleep(0)

    assert target_sent, "ATT PDU 应被转发到 target 侧"
    _, _, data = target_sent[0]
    assert data[2:4] == bytes([0x04, 0x00])  # CID 0x04
    assert data[4:] == att_payload
    # ATT 不进 SMP,不应在 phone 侧产生任何 SMP 输出:
    assert not phone_sent


async def test_build_relay_creates_pairings_with_correct_roles():
    relay = _bare_relay()
    phone_side, _ = _fake_side("phone", 0x40)
    target_side, _ = _fake_side("target", 0x11)
    addr = bytes([0x00]) + bytes.fromhex("aabbccddeeff")
    addr2 = bytes([0x00]) + bytes.fromhex("112233445566")
    relay._build_relay(phone_side, target_side, addr, addr2, addr2, addr)

    assert relay._pairings["phone"].role == "responder"
    assert relay._pairings["target"].role == "initiator"
    assert relay._sides["phone"] is phone_side
    assert relay._sides["target"] is target_side
