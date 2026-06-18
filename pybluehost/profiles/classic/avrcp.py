"""AVRCP v1.6 Controller and Target profile classes."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from pybluehost.classic.avctp.constants import (
    AVRCP_CONTROLLER_UUID, AVRCP_PROFILE_UUID, AVRCP_TARGET_UUID, PSM_AVCTP,
)
from pybluehost.classic.avctp.session import AVCTPSession
from pybluehost.avrcp.constants import (
    AVCCtype, AVCOpCode, AVCSubunitType,
    AVRCPEventID, AVRCPOperationID,
)
from pybluehost.avrcp.frame import AVCFrame
from pybluehost.avrcp.notification import (
    build_notification_interim_response,
    build_register_notification_command,
    parse_notification_response,
)
from pybluehost.avrcp.passthrough import PassThroughCommand, PassThroughResponse
from pybluehost.classic.sdp import DataElement, ServiceRecord
from pybluehost.profiles.classic._common import ClassicProfile


_log = logging.getLogger(__name__)


_AVCTP_UUID = 0x0017
_AVCTP_VERSION = 0x0104
_AVRCP_PROFILE_VERSION = 0x0106    # AVRCP v1.6
_L2CAP_UUID = 0x0100


def _build_avrcp_sdp_record(*, service_class_uuids: list[int]) -> ServiceRecord:
    """Common AVRCP SDP record builder; caller passes UUIDs for role.

    Per AVRCP v1.6 §6, the record carries the legacy AVRemoteControl UUID
    (0x110E) plus the role-specific UUID (0x110F for controller, 0x110C for
    target)."""
    record = ServiceRecord()
    record.attributes[0x0001] = DataElement.sequence([
        DataElement.uuid16(uuid) for uuid in service_class_uuids
    ])
    record.attributes[0x0004] = DataElement.sequence([
        DataElement.sequence([
            DataElement.uuid16(_L2CAP_UUID),
            DataElement.uint16(PSM_AVCTP),
        ]),
        DataElement.sequence([
            DataElement.uuid16(_AVCTP_UUID),
            DataElement.uint16(_AVCTP_VERSION),
        ]),
    ])
    record.attributes[0x0009] = DataElement.sequence([
        DataElement.sequence([
            DataElement.uuid16(AVRCP_PROFILE_UUID),
            DataElement.uint16(_AVRCP_PROFILE_VERSION),
        ]),
    ])
    # 0x0311 SupportedFeatures — minimal Category 1 (Player) bit.
    record.attributes[0x0311] = DataElement.uint16(0x0001)
    return record


@dataclass
class AVRCPController(ClassicProfile):
    """AVRCP Controller — issues PASS_THROUGH commands and notifications."""
    stack: Any

    def __post_init__(self) -> None:
        self._sessions: dict[int, "AVRCPSession"] = {}

    def _psm(self) -> int:
        return PSM_AVCTP

    def _build_sdp_record(self) -> ServiceRecord:
        return _build_avrcp_sdp_record(
            service_class_uuids=[AVRCP_PROFILE_UUID, AVRCP_CONTROLLER_UUID],
        )

    def _on_psm_connect(self, channel) -> None:
        # Peer connected to our PSM — rare for controller role, but support it.
        handle = channel.connection_handle
        if handle in self._sessions:
            return    # already have a session for this handle
        avctp = AVCTPSession(channel, profile_id=AVRCP_PROFILE_UUID)
        session = AVRCPSession(stack=self.stack, avctp=avctp, handle=handle, role="controller")
        self._sessions[handle] = session
        asyncio.create_task(avctp.start())

    async def connect(self, *, handle: int) -> "AVRCPSession":
        ch = await self.stack.l2cap.connect_classic_channel(handle, PSM_AVCTP)
        avctp = AVCTPSession(ch, profile_id=AVRCP_PROFILE_UUID)
        await avctp.start()
        session = AVRCPSession(
            stack=self.stack, avctp=avctp, handle=handle, role="controller",
        )
        self._sessions[handle] = session
        return session


@dataclass
class AVRCPTarget(ClassicProfile):
    """AVRCP Target — accepts PASS_THROUGH commands and notifications."""
    stack: Any
    on_pass_through: Optional[Callable[[PassThroughCommand], Awaitable[bool]]] = None
    on_notification_register: Optional[Callable[[int], Awaitable[bytes]]] = None

    def __post_init__(self) -> None:
        self._sessions: dict[int, "AVRCPSession"] = {}

    def _psm(self) -> int:
        return PSM_AVCTP

    def _build_sdp_record(self) -> ServiceRecord:
        return _build_avrcp_sdp_record(
            service_class_uuids=[AVRCP_PROFILE_UUID, AVRCP_TARGET_UUID],
        )

    def _on_psm_connect(self, channel) -> None:
        handle = channel.connection_handle
        if handle in self._sessions:
            return
        session = AVRCPSession(
            stack=self.stack, avctp=None, handle=handle, role="target",
            on_pass_through=self.on_pass_through,
            on_notification_register=self.on_notification_register,
        )
        avctp = AVCTPSession(
            channel, profile_id=AVRCP_PROFILE_UUID,
            on_command=session._handle_command,
        )
        session.avctp = avctp
        self._sessions[handle] = session
        asyncio.create_task(avctp.start())


@dataclass
class AVRCPSession:
    """High-level AVRCP session.

    Controller side: methods like `play()`, `pause()`, `register_notification()`.
    Target side: dispatches incoming AVCTP commands to the user's
    `on_pass_through` / `on_notification_register` callbacks.
    """
    stack: Any
    avctp: Optional[AVCTPSession]
    handle: int
    role: str
    on_pass_through: Optional[Callable[[PassThroughCommand], Awaitable[bool]]] = None
    on_notification_register: Optional[Callable[[int], Awaitable[bytes]]] = None

    _notification_callbacks: dict[int, Callable[[bytes], Awaitable[None]]] = field(
        default_factory=dict, init=False,
    )

    # Controller-side commands ---------------------------------------
    async def _send_passthrough(self, op_id: int) -> bool:
        """Press -> Release pair. Returns True if both got ACCEPTED."""
        if self.avctp is None:
            raise RuntimeError("session not connected")
        for pressed in (True, False):
            cmd = PassThroughCommand(operation_id=op_id, pressed=pressed)
            resp_bytes = await self.avctp.send_command(cmd.to_avcframe().to_bytes())
            resp = AVCFrame.from_bytes(resp_bytes)
            if resp.ctype != AVCCtype.ACCEPTED:
                return False
        return True

    async def play(self) -> bool:
        return await self._send_passthrough(AVRCPOperationID.PLAY)

    async def pause(self) -> bool:
        return await self._send_passthrough(AVRCPOperationID.PAUSE)

    async def stop(self) -> bool:
        return await self._send_passthrough(AVRCPOperationID.STOP)

    async def next_track(self) -> bool:
        return await self._send_passthrough(AVRCPOperationID.FORWARD)

    async def prev_track(self) -> bool:
        return await self._send_passthrough(AVRCPOperationID.BACKWARD)

    async def volume_up(self) -> bool:
        return await self._send_passthrough(AVRCPOperationID.VOLUME_UP)

    async def volume_down(self) -> bool:
        return await self._send_passthrough(AVRCPOperationID.VOLUME_DOWN)

    async def register_notification(self, event_id: int) -> bytes:
        """Send REGISTER_NOTIFICATION; return the INTERIM response payload
        (current event value). Returns event_payload (bytes after event_id)."""
        if self.avctp is None:
            raise RuntimeError("session not connected")
        cmd = build_register_notification_command(event_id=event_id)
        resp_bytes = await self.avctp.send_command(cmd.to_bytes())
        resp = AVCFrame.from_bytes(resp_bytes)
        ctype, returned_event_id, payload = parse_notification_response(resp)
        if returned_event_id != event_id:
            raise RuntimeError(
                f"unexpected event id in INTERIM response: {returned_event_id}"
            )
        return payload

    async def close(self) -> None:
        if self.avctp is not None:
            await self.avctp.stop()

    # Target-side dispatch -------------------------------------------
    async def _handle_command(self, payload: bytes) -> bytes:
        """AVCTP command handler. Dispatch on AV/C opcode."""
        try:
            frame = AVCFrame.from_bytes(payload)
        except ValueError:
            _log.warning("dropping malformed AV/C command")
            return AVCFrame(
                ctype=AVCCtype.REJECTED, subunit_type=AVCSubunitType.PANEL, subunit_id=0,
                opcode=AVCOpCode.PASS_THROUGH, operands=b"",
            ).to_bytes()

        if frame.opcode == AVCOpCode.PASS_THROUGH:
            try:
                cmd = PassThroughCommand.from_avcframe(frame)
            except ValueError:
                return PassThroughResponse.rejected(
                    operation_id=0, pressed=True,
                ).to_avcframe().to_bytes()
            accepted = False
            if self.on_pass_through is not None:
                try:
                    accepted = await self.on_pass_through(cmd)
                except Exception:
                    _log.exception("on_pass_through raised")
                    accepted = False
            resp = (
                PassThroughResponse.accepted(operation_id=cmd.operation_id, pressed=cmd.pressed)
                if accepted else
                PassThroughResponse.not_implemented(operation_id=cmd.operation_id, pressed=cmd.pressed)
            )
            return resp.to_avcframe().to_bytes()

        if frame.opcode == AVCOpCode.VENDOR_DEPENDENT and len(frame.operands) >= 8:
            # REGISTER_NOTIFICATION
            event_id = frame.operands[7]
            if self.on_notification_register is not None:
                try:
                    event_payload = await self.on_notification_register(event_id)
                except Exception:
                    _log.exception("on_notification_register raised")
                    event_payload = b"\x00"
            else:
                event_payload = b"\x00"
            return build_notification_interim_response(
                event_id=event_id, event_payload=event_payload,
            ).to_bytes()

        # Unknown opcode -> NOT_IMPLEMENTED.
        return AVCFrame(
            ctype=AVCCtype.NOT_IMPLEMENTED,
            subunit_type=frame.subunit_type, subunit_id=frame.subunit_id,
            opcode=frame.opcode, operands=frame.operands,
        ).to_bytes()
