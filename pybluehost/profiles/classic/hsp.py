"""HSP v1.2 HeadSet + Audio-Gateway profile classes.

HSP is a stripped-down sibling of HFP:
- No SLC handshake (RFCOMM up = ready).
- CVSD only (no codec negotiation).
- Tiny AT command set: AT+VGS, AT+VGM, AT+CKPD, RING.

Reuses A.4 infrastructure: ATLineBuffer + parse_at_line + format_*,
HCIController.setup_synchronous_connection, SCOLink.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from pybluehost.classic.sdp import DataElement, ServiceRecord
from pybluehost.hci.sco import SCOLink
from pybluehost.hci.sco_constants import PRESET_CVSD_S1
from pybluehost.profiles.classic._at_parser import (
    ATCommand, ATLineBuffer, ATResponse, ATUnsolicited,
    format_at_command, format_at_response, format_unsolicited,
    parse_at_line,
)
from pybluehost.profiles.classic._hsp_at import (
    build_ckpd_command, build_ring_unsolicited,
    build_vgm_command, build_vgm_unsolicited,
    build_vgs_command, build_vgs_unsolicited,
    parse_ckpd_command, parse_vgm_command, parse_vgs_command,
)
from pybluehost.profiles.classic._hsp_constants import (
    HEADSET_UUID, HSP_AG_RFCOMM_CHANNEL, HSP_AG_UUID,
    HSP_DEFAULT_GAIN, HSP_HS_RFCOMM_CHANNEL, HSP_HS_UUID,
    HSP_PROFILE_VERSION,
)
from pybluehost.profiles.classic._common import ClassicProfile


_log = logging.getLogger(__name__)


GENERIC_AUDIO_UUID = 0x1203
_L2CAP_UUID = 0x0100
_RFCOMM_UUID = 0x0003


def _build_hsp_sdp_record(
    *, service_class_uuids: list[int], rfcomm_channel: int,
) -> ServiceRecord:
    record = ServiceRecord()
    record.attributes[0x0001] = DataElement.sequence([
        DataElement.uuid16(u) for u in service_class_uuids
    ])
    record.attributes[0x0004] = DataElement.sequence([
        DataElement.sequence([DataElement.uuid16(_L2CAP_UUID)]),
        DataElement.sequence([
            DataElement.uuid16(_RFCOMM_UUID),
            DataElement.uint8(rfcomm_channel),
        ]),
    ])
    record.attributes[0x0009] = DataElement.sequence([
        DataElement.sequence([
            DataElement.uuid16(HEADSET_UUID),
            DataElement.uint16(HSP_PROFILE_VERSION),
        ]),
    ])
    return record


@dataclass
class HSPHeadset(ClassicProfile):
    """HS (HeadSet) role — typically initiates the connection."""
    stack: Any

    def __post_init__(self) -> None:
        self._sessions: dict[int, "HSPSession"] = {}

    def _psm(self) -> int:
        raise NotImplementedError

    def _build_sdp_record(self) -> ServiceRecord:
        return _build_hsp_sdp_record(
            service_class_uuids=[HSP_HS_UUID, HEADSET_UUID, GENERIC_AUDIO_UUID],
            rfcomm_channel=HSP_HS_RFCOMM_CHANNEL,
        )

    def _on_psm_connect(self, channel) -> None:
        raise NotImplementedError

    def register(self) -> None:
        self.stack.sdp.register(self._build_sdp_record())
        self.stack.rfcomm.listen_channel(
            HSP_HS_RFCOMM_CHANNEL, self._on_rfcomm_connect,
        )

    def _on_rfcomm_connect(self, rfcomm_session) -> None:
        handle = getattr(rfcomm_session, "connection_handle", 0)
        session = HSPSession(
            stack=self.stack, rfcomm=rfcomm_session, handle=handle, role="hs",
        )
        self._sessions[handle] = session
        asyncio.create_task(session._run())

    async def connect(self, *, handle: int, channel: int = HSP_AG_RFCOMM_CHANNEL) -> "HSPSession":
        rfcomm_session = await self.stack.rfcomm.connect(handle=handle, channel=channel)
        session = HSPSession(
            stack=self.stack, rfcomm=rfcomm_session, handle=handle, role="hs",
        )
        self._sessions[handle] = session
        await session._kick_off()
        return session


@dataclass
class HSPAudioGateway(ClassicProfile):
    """AG (Audio Gateway) role — responds to HS connections."""
    stack: Any
    on_button_press: Optional[Callable[[], Awaitable[None]]] = None

    def __post_init__(self) -> None:
        self._sessions: dict[int, "HSPSession"] = {}

    def _psm(self) -> int:
        raise NotImplementedError

    def _build_sdp_record(self) -> ServiceRecord:
        return _build_hsp_sdp_record(
            service_class_uuids=[HSP_AG_UUID, GENERIC_AUDIO_UUID],
            rfcomm_channel=HSP_AG_RFCOMM_CHANNEL,
        )

    def _on_psm_connect(self, channel) -> None:
        raise NotImplementedError

    def register(self) -> None:
        self.stack.sdp.register(self._build_sdp_record())
        self.stack.rfcomm.listen_channel(
            HSP_AG_RFCOMM_CHANNEL, self._on_rfcomm_connect,
        )

    def _on_rfcomm_connect(self, rfcomm_session) -> None:
        handle = getattr(rfcomm_session, "connection_handle", 0)
        session = HSPSession(
            stack=self.stack, rfcomm=rfcomm_session, handle=handle, role="ag",
            on_button_press=self.on_button_press,
        )
        self._sessions[handle] = session
        asyncio.create_task(session._run())


@dataclass
class HSPSession:
    """High-level HSP session — wraps RFCOMM + line buffer + SCO link."""
    stack: Any
    rfcomm: Any
    handle: int
    role: str
    on_button_press: Optional[Callable[[], Awaitable[None]]] = None

    speaker_gain: int = HSP_DEFAULT_GAIN
    mic_gain: int = HSP_DEFAULT_GAIN

    _line_buf: ATLineBuffer = field(default_factory=ATLineBuffer, init=False)
    _ready: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _sco_link: Optional[SCOLink] = field(default=None, init=False)

    def _bind_on_data(self) -> None:
        cb = self._on_data
        on_data_attr = getattr(self.rfcomm, "on_data", None)
        if callable(on_data_attr):
            try:
                self.rfcomm.on_data(cb)
                return
            except TypeError:
                pass
        self.rfcomm.on_data = cb

    async def _kick_off(self) -> None:
        """HS-side: register on_data; HSP has no SLC, so we're immediately ready."""
        self._bind_on_data()
        self._ready.set()

    async def _run(self) -> None:
        self._bind_on_data()
        if self.role == "ag":
            self._arm_sco_listener()
        self._ready.set()

    def _arm_sco_listener(self) -> None:
        """AG-side: listen for Synchronous_Connection_Complete and auto-build SCOLink."""
        hci = getattr(self.stack, "hci", None)
        if hci is None or not hasattr(hci, "add_sco_complete_listener"):
            return

        async def _on_complete(acl_handle: int, sco_handle: int) -> None:
            if acl_handle != self.handle:
                return
            self._sco_link = SCOLink(
                handle=sco_handle, codec="CVSD", controller=hci,
            )
            if hasattr(hci, "set_on_sco_data"):
                hci.set_on_sco_data(self._sco_link._on_inbound)

        hci.add_sco_complete_listener(_on_complete)

    async def _on_data(self, data: bytes) -> None:
        self._line_buf.feed(data)
        for line in self._line_buf.drain():
            try:
                msg = parse_at_line(line)
            except ValueError:
                continue
            await self._dispatch(msg)

    async def _dispatch(self, msg) -> None:
        if isinstance(msg, ATCommand):
            await self._handle_command(msg)
        elif isinstance(msg, ATUnsolicited):
            await self._handle_unsolicited(msg)

    async def _handle_command(self, cmd: ATCommand) -> None:
        if self.role != "ag":
            return
        try:
            if cmd.name == "+CKPD":
                _ = parse_ckpd_command(cmd)
                if self.on_button_press is not None:
                    await self.on_button_press()
                await self._send_at(ATResponse(name="OK", is_terminator=True))
            elif cmd.name == "+VGS":
                self.speaker_gain = parse_vgs_command(cmd)
                await self._send_at(ATResponse(name="OK", is_terminator=True))
            elif cmd.name == "+VGM":
                self.mic_gain = parse_vgm_command(cmd)
                await self._send_at(ATResponse(name="OK", is_terminator=True))
            else:
                await self._send_at(ATResponse(name="ERROR", is_terminator=True))
        except ValueError:
            await self._send_at(ATResponse(name="ERROR", is_terminator=True))

    async def _handle_unsolicited(self, msg: ATUnsolicited) -> None:
        if self.role != "hs":
            return
        if msg.name == "+VGS" and msg.args:
            self.speaker_gain = int(msg.args[0])
        elif msg.name == "+VGM" and msg.args:
            self.mic_gain = int(msg.args[0])

    async def _send_at(self, msg) -> None:
        if isinstance(msg, ATCommand):
            text = format_at_command(msg)
        elif isinstance(msg, ATResponse):
            text = format_at_response(msg)
        else:
            text = format_unsolicited(msg)
        await self.rfcomm.send(text.encode("ascii"))

    async def request_audio(self) -> None:
        if self.role != "hs":
            raise RuntimeError("request_audio is HS-side only")
        await self._send_at(build_ckpd_command())

    async def set_speaker_gain(self, gain: int) -> None:
        if self.role != "hs":
            raise RuntimeError("set_speaker_gain is HS-side only")
        self.speaker_gain = gain
        await self._send_at(build_vgs_command(gain=gain))

    async def set_mic_gain(self, gain: int) -> None:
        if self.role != "hs":
            raise RuntimeError("set_mic_gain is HS-side only")
        self.mic_gain = gain
        await self._send_at(build_vgm_command(gain=gain))

    async def emit_ring(self) -> None:
        if self.role != "ag":
            raise RuntimeError("emit_ring is AG-side only")
        await self._send_at(build_ring_unsolicited())

    async def setup_sco(self) -> SCOLink:
        sco_handle = await self.stack.hci.setup_synchronous_connection(
            acl_handle=self.handle, preset=PRESET_CVSD_S1,
        )
        self._sco_link = SCOLink(
            handle=sco_handle, codec="CVSD", controller=self.stack.hci,
        )
        self.stack.hci.set_on_sco_data(self._sco_link._on_inbound)
        return self._sco_link

    async def disconnect_sco(self) -> None:
        if self._sco_link is not None:
            await self._sco_link.close()
            self._sco_link = None

    async def close(self) -> None:
        await self.disconnect_sco()
        if hasattr(self.rfcomm, "close"):
            await self.rfcomm.close()
