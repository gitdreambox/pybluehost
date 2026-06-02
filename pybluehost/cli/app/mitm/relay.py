"""AclRelay —— B 式 HCI-ACL 双向透传的中继器。

每侧(phone/target)一个 RelaySide,持有 send 回调、对侧 buffer 大小、重组器。
on_*_acl 收到 HCIACLData → 重组成 PDU → 按 CID 分流:
  TERMINATE_SMP → 交 smp_handler(MITM-2 接管);
  RELAY → 抓包 → 按对侧 buffer 重分片 → 对侧 send_acl。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pybluehost.cli.app.mitm.acl import (
    CidAction,
    L2capReassembler,
    RelayDirection,
    classify,
    encode_l2cap_basic,
    fragment,
)
from pybluehost.cli.app.mitm.capture import CaptureTap, NullTap
from pybluehost.hci.packets import HCIACLData

SendAcl = Callable[[int, int, bytes], Awaitable[None]]
SmpHandler = Callable[[str, int, bytes], Awaitable[None]]


@dataclass
class RelaySide:
    name: str
    handle: int
    acl_max_payload: int
    send_acl: SendAcl
    reassembler: L2capReassembler = field(default_factory=L2capReassembler)


class AclRelay:
    def __init__(
        self,
        *,
        phone_side: RelaySide,
        target_side: RelaySide,
        capture: CaptureTap | None = None,
        smp_handler: SmpHandler | None = None,
        on_teardown: Callable[[], None] | None = None,
    ) -> None:
        self._phone = phone_side
        self._target = target_side
        self._capture = capture or NullTap()
        self._smp_handler = smp_handler
        self._on_teardown = on_teardown

    async def on_phone_acl(self, acl: HCIACLData) -> None:
        await self._handle(self._phone, self._target, RelayDirection.PHONE_TO_TARGET, acl)

    async def on_target_acl(self, acl: HCIACLData) -> None:
        await self._handle(self._target, self._phone, RelayDirection.TARGET_TO_PHONE, acl)

    async def _handle(
        self, src: RelaySide, dst: RelaySide, direction: RelayDirection, acl: HCIACLData
    ) -> None:
        for cid, payload in src.reassembler.feed(acl):
            if classify(cid) is CidAction.TERMINATE_SMP:
                if self._smp_handler is not None:
                    await self._smp_handler(src.name, cid, payload)
                continue
            pdu = encode_l2cap_basic(cid, payload)
            await self._capture.on_pdu(direction, dst.handle, pdu)
            for frag in fragment(
                handle=dst.handle, l2cap_pdu=pdu, max_payload=dst.acl_max_payload
            ):
                await dst.send_acl(frag.handle, frag.pb_flag, frag.data)

    async def teardown(self) -> None:
        if self._on_teardown is not None:
            self._on_teardown()
        await self._capture.close()
