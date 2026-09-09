"""AclRelay — a B-style bidirectional HCI-ACL transparent relay.

One RelaySide per side (phone/target), holding the send callback, the peer's buffer
size, and the reassembler. on_*_acl receives HCIACLData → reassembles into PDUs →
routes by CID:
  TERMINATE_SMP → handed to smp_handler (MITM-2 termination);
  RELAY → capture → re-fragment to the peer's buffer size → peer send_acl.
"""
from __future__ import annotations

import asyncio
import logging
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
from pybluehost.cli.app.mitm.transform import PduTransform
from pybluehost.hci.packets import HCIACLData

logger = logging.getLogger(__name__)

SendAcl = Callable[[int, int, bytes], Awaitable[None]]
SmpHandler = Callable[[str, int, bytes], Awaitable[None]]
# Sync or async both fine; teardown awaits the coroutine return value.
TeardownHook = Callable[[], Awaitable[None] | None]


@dataclass
class RelaySide:
    # One RelaySide corresponds to one connection (one connection handle): the
    # reassembler accumulates the ACL stream of that handle. Multiple connections need
    # one RelaySide per handle, otherwise fragments from different handles would
    # interleave in the same buffer.
    name: str
    handle: int
    acl_max_payload: int
    send_acl: SendAcl
    reassembler: L2capReassembler = field(default_factory=L2capReassembler)


@dataclass
class _Egress:
    """Outbound decoupling for a single destination: bounded PDU queue + drain task.

    Queue items are **complete L2CAP PDUs** (not HCI fragments) — fragmentation happens
    on the drain side, so a drop discards a whole PDU atomically and never feeds the
    peer's reassembler half a PDU.
    """

    queue: asyncio.Queue
    task: asyncio.Task | None = None


class AclRelay:
    def __init__(
        self,
        *,
        phone_side: RelaySide,
        target_side: RelaySide,
        capture: CaptureTap | None = None,
        smp_handler: SmpHandler | None = None,
        on_teardown: TeardownHook | None = None,
        egress_max: int = 24,
        egress_low: int = 4,
        transform: PduTransform | None = None,
    ) -> None:
        self._phone = phone_side
        self._target = target_side
        self._capture = capture or NullTap()
        self._smp_handler = smp_handler
        self._on_teardown = on_teardown
        # Amplifier guard: outbound decoupling. dst.send_acl is no longer awaited inline
        # in src's read callback; PDUs are enqueued (put_nowait) and sent by each
        # destination's own background drain task. A wedged dongle TX on either side
        # (send_acl stuck in acl_flow.acquire) then only blocks its own drain task and
        # fills its own bounded queue — it **never back-pressures the peer's bulk read
        # loop**. Real-hardware lesson: an earbud-side wedge once stalled the phone-side
        # read loop and the phone's media was silently dropped at the USB layer
        # ("no audio").
        # Queue depth (the _latency budget_ of isochronous media): A2DP is isochronous,
        # in == out == 43/s, and the dst side is pinned to 43/s by NCP flow control.
        # **A backlog can never drain** (the earbud cannot play faster than real time),
        # so the queue must never be large — a large one only accumulates latency (measured
        # 512 → after a 5s pause the earbud kept playing and the phone judged the link
        # unusable and switched to speaker). The right approach: a small queue (high
        # watermark egress_max ≈ 0.5s) absorbs normal jitter; **on full, drop to the low
        # watermark egress_low in one shot**, pulling latency back immediately and freeing
        # headroom. Dropped old frames are already too late for the earbud (missed real
        # time), so dropping is the only way to not accumulate latency.
        self._egress_max = egress_max
        self._egress_low = egress_low
        self._egress: dict[str, _Egress] = {}
        self._stopped = False
        self._dropped = 0
        self._last_drop_log = 0.0
        # PDU-level regex replacement hook (optional). Default None = byte-identical to
        # having no such parameter. Exceptions fail open: log, forward the original frame,
        # never kill the media stream.
        self._transform = transform

    @property
    def dropped(self) -> int:
        """Total PDUs dropped because the egress queue was full (observes amplifier trips)."""
        return self._dropped

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
                else:
                    # Before MITM-2 there is no SMP terminator; relaying without a
                    # handler would leave the peer's pairing to time out (detectable),
                    # so warn explicitly rather than drop silently.
                    logger.warning(
                        "%s 侧收到 SMP PDU(CID 0x%04X)但未配置 smp_handler,已丢弃",
                        src.name, cid,
                    )
                continue
            pdu = encode_l2cap_basic(cid, self._apply_transform(direction, cid, payload))
            # Enqueue and return immediately: forwarding (fragment + send + capture) happens
            # in dst's drain task, off src's read loop. Capture therefore also rides along
            # with forwarding in the drain, still after the send.
            self._enqueue(dst, direction, pdu)

    def _apply_transform(
        self, direction: RelayDirection, cid: int, payload: bytes
    ) -> bytes:
        if self._transform is None:
            return payload
        try:
            return self._transform(direction, cid, payload)
        except Exception:
            logger.exception("transform 处理失败,fail-open 转发原帧")
            return payload

    # ------------------------------------------------------------------ egress
    def _enqueue(self, dst: RelaySide, direction: RelayDirection, pdu: bytes) -> None:
        if self._stopped:
            return
        eg = self._egress.get(dst.name)
        if eg is None:
            eg = _Egress(queue=asyncio.Queue(maxsize=self._egress_max))
            eg.task = asyncio.ensure_future(self._drain(dst, direction, eg))
            self._egress[dst.name] = eg
        try:
            eg.queue.put_nowait(pdu)
            return
        except asyncio.QueueFull:
            pass
        # Queue full: drop to the **low watermark** in one shot (not just 1 PDU). An
        # isochronous backlog never drains on its own; dropping only 1 would leave the
        # queue pinned at the cap with latency stuck high. Dropping to the low watermark
        # pulls latency back immediately and frees headroom for the next burst. Every
        # dropped PDU must task_done() to keep join() balanced.
        dropped_now = 0
        while eg.queue.qsize() > self._egress_low:
            try:
                eg.queue.get_nowait()
                eg.queue.task_done()
                dropped_now += 1
            except asyncio.QueueEmpty:
                break
        try:
            eg.queue.put_nowait(pdu)
        except asyncio.QueueFull:
            dropped_now += 1  # even the low watermark won't fit (extreme: drain fully wedged) — drop the new one
        self._dropped += dropped_now
        now = asyncio.get_running_loop().time()
        if now - self._last_drop_log >= 1.0:
            self._last_drop_log = now
            logger.warning(
                "%s→%s 出站积压超高水位(%d),丢 %d 条至低水位 %d(累计丢 %d)——对侧慢/楔死",
                direction.name, dst.name, self._egress_max, dropped_now,
                self._egress_low, self._dropped,
            )

    async def _drain(self, dst: RelaySide, direction: RelayDirection, eg: _Egress) -> None:
        while True:
            pdu = await eg.queue.get()
            try:
                # Forward first, then capture: capture is a side observation and must not
                # block forwarding; capture.on_pdu only enqueues.
                for frag in fragment(
                    handle=dst.handle, l2cap_pdu=pdu, max_payload=dst.acl_max_payload
                ):
                    await dst.send_acl(frag.handle, frag.pb_flag, frag.data)
                await self._capture.on_pdu(direction, dst.handle, pdu)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A single send failure (e.g. link already down) must not kill the drain
                # task; drop that PDU and continue.
                logger.exception("%s→%s 转发失败,丢弃该 PDU", direction.name, dst.name)
            finally:
                eg.queue.task_done()

    async def flush(self) -> None:
        """Wait for all egress queues to drain (for tests / graceful sync points)."""
        for eg in self._egress.values():
            await eg.queue.join()

    async def stop(self) -> None:
        """Stop all drain tasks (called on reconnect/teardown; does not close the shared capture). Idempotent."""
        if self._stopped:
            return
        self._stopped = True
        tasks = [eg.task for eg in self._egress.values() if eg.task is not None]
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass

    async def teardown(self) -> None:
        """Begin teardown: stop drains, fire the on_teardown hook (sync or async), then close capture."""
        await self.stop()
        if self._on_teardown is not None:
            result = self._on_teardown()
            if asyncio.iscoroutine(result):
                await result
        await self._capture.close()
