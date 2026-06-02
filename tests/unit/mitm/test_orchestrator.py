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


def _fake_side(name, handle, acl_max_payload=27):
    sent = []

    async def send_acl(h, pb, data):
        sent.append((h, pb, data))

    return RelaySide(name=name, handle=handle, acl_max_payload=acl_max_payload, send_acl=send_acl), sent


def _bare_relay():
    """构造一个不依赖真实 pair 的 MitmRelay,仅填好 _build_relay 需要的字段。"""
    relay = MitmRelay.__new__(MitmRelay)
    relay._delegate = AutoConfirmDelegate()
    relay._capture = NullTap()
    relay._pairings = {}
    relay._sides = {}
    relay._smp_queues = {}
    relay._drain_tasks = []
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
    # C1: drain task 需要多次 yield 才能跑完;轮询等待输出
    for _ in range(50):
        if phone_sent:
            break
        await asyncio.sleep(0)
    assert phone_sent, "no SMP response emitted on phone side"
    _, _, data = phone_sent[0]
    assert data[2:4] == bytes([0x06, 0x00])  # CID 0x06
    assert data[4] == P.PAIRING_RESPONSE
    # SMP PDU 本地终结,不应透传到 target 侧:
    assert not target_sent, "SMP PDU 不应被转发到 target 侧"

    # 清理 drain tasks 避免 "Task was destroyed but it is pending" 警告
    for t in relay._drain_tasks:
        t.cancel()


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

    for t in relay._drain_tasks:
        t.cancel()


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

    for t in relay._drain_tasks:
        t.cancel()


async def test_smp_emitter_preserves_pdu_order_across_fragments():
    """C1 回归:两个 PDU 按入队顺序发出,第一个 PDU 的所有分片先于第二个 PDU 的分片。

    使用 acl_max_payload=16 强制分片,确保跨分片边界的顺序不被 ensure_future 打乱。
    """
    relay = _bare_relay()

    # acl_max_payload=16:强制 64 字节 payload 的 PDU 被拆成多个分片
    phone_side, phone_sent = _fake_side("phone", 0x40, acl_max_payload=16)
    target_side, _ = _fake_side("target", 0x11)
    addr = bytes([0x00]) + bytes.fromhex("aabbccddeeff")
    addr2 = bytes([0x00]) + bytes.fromhex("112233445566")
    relay._build_relay(phone_side, target_side, addr, addr2, addr2, addr)

    emit = relay._make_smp_emitter("phone")

    # PDU1: PAIRING_PUBLIC_KEY —— opcode(1) + 64 bytes body = 65 bytes SMP PDU
    pk_body = bytes(range(64))
    pk = P.encode(P.PAIRING_PUBLIC_KEY, pk_body)  # 65 bytes
    # PDU2: PAIRING_CONFIRM —— opcode(1) + 16 bytes body = 17 bytes SMP PDU
    cf_body = bytes(range(16))
    cf = P.encode(P.PAIRING_CONFIRM, cf_body)  # 17 bytes

    # 同步入队两个 PDU(保序语义)
    emit(pk)
    emit(cf)

    # L2CAP frame size: 4 byte header + SMP PDU
    # PDU1 L2CAP = 4 + 65 = 69 bytes; PDU2 L2CAP = 4 + 17 = 21 bytes; total = 90
    total_bytes = (4 + len(pk)) + (4 + len(cf))

    for _ in range(200):
        joined = b"".join(d for _, _, d in phone_sent)
        if len(joined) >= total_bytes:
            break
        await asyncio.sleep(0)

    for t in relay._drain_tasks:
        t.cancel()

    joined = b"".join(d for _, _, d in phone_sent)
    assert len(joined) >= total_bytes, (
        f"Expected at least {total_bytes} bytes, got {len(joined)}"
    )

    # 第一个 L2CAP 帧: length=65(LE), cid=6, opcode=PAIRING_PUBLIC_KEY
    l2cap_len_0 = int.from_bytes(joined[0:2], "little")
    l2cap_cid_0 = int.from_bytes(joined[2:4], "little")
    assert l2cap_len_0 == len(pk), f"First L2CAP frame length wrong: {l2cap_len_0}"
    assert l2cap_cid_0 == CID_SMP, f"First L2CAP frame CID wrong: {l2cap_cid_0}"
    assert joined[4] == P.PAIRING_PUBLIC_KEY, (
        f"First frame opcode wrong: 0x{joined[4]:02x}"
    )

    # 第二个 L2CAP 帧紧随其后: offset = 4 + len(pk)
    offset = 4 + len(pk)
    l2cap_len_1 = int.from_bytes(joined[offset : offset + 2], "little")
    l2cap_cid_1 = int.from_bytes(joined[offset + 2 : offset + 4], "little")
    assert l2cap_len_1 == len(cf), f"Second L2CAP frame length wrong: {l2cap_len_1}"
    assert l2cap_cid_1 == CID_SMP, f"Second L2CAP frame CID wrong: {l2cap_cid_1}"
    assert joined[offset + 4] == P.PAIRING_CONFIRM, (
        f"Second frame opcode wrong: 0x{joined[offset + 4]:02x}"
    )


# ===========================================================================
# MITM-3 Task 5 — BR/EDR 分支(SSP 终结 + 模式分派)的 fake 单测
# ===========================================================================


class _FakeSspController:
    """记录 SSP 监听器注册的 fake 控制器(SspTermination.attach 需要这四个方法)。"""

    def __init__(self, label):
        self.label = label
        self.io_listeners = []
        self.uc_listeners = []
        self.lkn_listeners = []
        self.lkr_listeners = []
        self.sent_commands = []

    def on_io_capability_request(self, cb):
        self.io_listeners.append(cb)

    def on_user_confirmation_request(self, cb):
        self.uc_listeners.append(cb)

    def on_link_key_notification(self, cb):
        self.lkn_listeners.append(cb)

    def on_link_key_request(self, cb):
        self.lkr_listeners.append(cb)

    async def send_command(self, command):
        self.sent_commands.append(command)

    @property
    def attached(self):
        return bool(
            self.io_listeners
            and self.uc_listeners
            and self.lkn_listeners
            and self.lkr_listeners
        )


class _FakePair:
    """最小 ControllerPair:暴露 upstream/downstream + async close()。"""

    def __init__(self, upstream, downstream):
        self.upstream = upstream
        self.downstream = downstream
        self.closed = False

    async def close(self):
        self.closed = True


def _bare_bredr_relay(pair):
    """构造一个 bredr 模式的 MitmRelay,填好 _build_relay_bredr 需要的字段。"""
    relay = MitmRelay.__new__(MitmRelay)
    relay._pair = pair
    relay._delegate = AutoConfirmDelegate()
    relay._capture = NullTap()
    relay._mode = "bredr"
    relay._numeric = False
    relay._ssp = {}
    relay._pairings = {}
    relay._sides = {}
    relay._smp_queues = {}
    relay._drain_tasks = []
    return relay


async def test_bredr_relay_uses_ssp_no_smp_handler():
    upstream = _FakeSspController("target")
    downstream = _FakeSspController("phone")
    pair = _FakePair(upstream, downstream)
    relay = _bare_bredr_relay(pair)

    phone_side, phone_sent = _fake_side("phone", 0x40)
    target_side, target_sent = _fake_side("target", 0x11)

    acl_relay = relay._build_relay_bredr(phone_side, target_side)

    # 1. AclRelay 不应配置 smp_handler(BR 的 SSP 走 HCI 事件,不走 L2CAP SMP)
    assert acl_relay._smp_handler is None

    # 2. 两侧控制器都应挂上 SspTermination(四个监听器都注册了)
    assert downstream.attached, "phone 侧未挂 SspTermination"
    assert upstream.attached, "target 侧未挂 SspTermination"
    assert "phone" in relay._ssp and "target" in relay._ssp
    # phone 侧 SspTermination 挂在 downstream 控制器上,target 侧挂在 upstream 上
    assert relay._ssp["phone"]._controller is downstream
    assert relay._ssp["target"]._controller is upstream

    # 3. 非 SMP 的 L2CAP PDU(ATT)经 on_phone_acl 应透传到 target 侧
    att_payload = bytes([0x02, 0x17, 0x00])
    att = encode_l2cap_basic(CID_ATT, att_payload)
    await acl_relay.on_phone_acl(
        HCIACLData(handle=0x40, pb_flag=PB_FIRST_FLUSH, data=att)
    )
    await asyncio.sleep(0)

    assert target_sent, "L2CAP PDU 应透传到 target 侧"
    _, _, data = target_sent[0]
    assert data[4:] == att_payload
    # BR 路径不启动 drain task
    assert relay._drain_tasks == []


async def test_run_recon_dispatches_by_mode(monkeypatch):
    import pybluehost.cli.app.mitm.bredr_recon as bredr_recon
    import pybluehost.cli.app.mitm.recon as recon
    from pybluehost.cli.app.mitm.recon import ClonedIdentity

    calls = []
    bredr_id = ClonedIdentity("AA:BB:CC:DD:EE:FF", 0, b"", b"", "bredr")
    le_id = ClonedIdentity("11:22:33:44:55:66", 0, b"", b"", "le")

    async def fake_inquiry(controller, *, target_addr=None, target_name=None):
        calls.append("bredr")
        return bredr_id

    async def fake_scan(controller, *, target_addr=None, target_name=None):
        calls.append("le")
        return le_id

    monkeypatch.setattr(bredr_recon, "inquiry_for_target", fake_inquiry)
    monkeypatch.setattr(recon, "scan_for_target", fake_scan)

    pair = _FakePair(_FakeSspController("target"), _FakeSspController("phone"))

    relay = MitmRelay(pair, target_addr="AA:BB:CC:DD:EE:FF", mode="bredr")
    await relay.run_recon()
    assert calls == ["bredr"]
    assert relay._identity is bredr_id

    calls.clear()
    relay_le = MitmRelay(pair, target_addr="AA:BB:CC:DD:EE:FF", mode="le")
    await relay_le.run_recon()
    assert calls == ["le"]
    assert relay_le._identity is le_id


async def test_run_impersonate_dispatches_by_mode(monkeypatch):
    import pybluehost.cli.app.mitm.bredr_impersonate as bredr_impersonate
    import pybluehost.cli.app.mitm.impersonate as impersonate

    calls = []

    async def fake_bredr_imp(controller, identity, *, clone_address=False):
        calls.append("bredr")

    async def fake_le_imp(controller, identity, *, clone_address=False):
        calls.append("le")

    monkeypatch.setattr(bredr_impersonate, "start_bredr_impersonation", fake_bredr_imp)
    monkeypatch.setattr(impersonate, "start_impersonation", fake_le_imp)

    pair = _FakePair(_FakeSspController("target"), _FakeSspController("phone"))

    relay = MitmRelay(pair, target_addr="AA:BB:CC:DD:EE:FF", mode="bredr")
    relay._identity = object()
    await relay.run_impersonate()
    assert calls == ["bredr"]

    calls.clear()
    relay_le = MitmRelay(pair, target_addr="AA:BB:CC:DD:EE:FF", mode="le")
    relay_le._identity = object()
    await relay_le.run_impersonate()
    assert calls == ["le"]
