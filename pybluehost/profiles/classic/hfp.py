"""HFP v1.8 Hands-Free + Audio-Gateway profile classes."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from pybluehost.classic.sdp import DataElement, ServiceRecord
from pybluehost.profiles.classic._at_parser import (
    ATCommand, ATLineBuffer, ATResponse, ATUnsolicited,
    format_at_command, format_at_response, format_unsolicited,
    parse_at_line,
)
from pybluehost.profiles.classic._hfp_at import (
    build_bcs_command, build_bcs_unsolicited, build_ciev_unsolicited,
    parse_bcs_command, parse_bcs_unsolicited,
)
from pybluehost.profiles.classic._hfp_constants import (
    AGFeature, DEFAULT_AG_FEATURES, DEFAULT_HF_FEATURES,
    HANDSFREE_UUID, HFFeature, HFP_AG_UUID, HFP_HF_UUID, HFP_PROFILE_VERSION,
    HFPCodecID,
)
from pybluehost.profiles.classic._hfp_state import HFPStateMachine, SLCState
from pybluehost.profiles.classic._common import ClassicProfile


_log = logging.getLogger(__name__)


HFP_RFCOMM_CHANNEL = 13           # convention for Plan A.4
GENERIC_AUDIO_UUID = 0x1203
_L2CAP_UUID = 0x0100
_RFCOMM_UUID = 0x0003


def _build_hfp_sdp_record(
    *, service_class_uuids: list[int], features: int, ag_network: bool = False,
) -> ServiceRecord:
    record = ServiceRecord()
    record.attributes[0x0001] = DataElement.sequence([
        DataElement.uuid16(u) for u in service_class_uuids
    ])
    record.attributes[0x0004] = DataElement.sequence([
        DataElement.sequence([DataElement.uuid16(_L2CAP_UUID)]),
        DataElement.sequence([
            DataElement.uuid16(_RFCOMM_UUID),
            DataElement.uint8(HFP_RFCOMM_CHANNEL),
        ]),
    ])
    record.attributes[0x0009] = DataElement.sequence([
        DataElement.sequence([
            DataElement.uuid16(HANDSFREE_UUID),
            DataElement.uint16(HFP_PROFILE_VERSION),
        ]),
    ])
    record.attributes[0x0311] = DataElement.uint16(features & 0xFFFF)
    if ag_network:
        record.attributes[0x0301] = DataElement.uint8(1)   # AG can reject calls
    return record


@dataclass
class HFPHandsFree(ClassicProfile):
    """HF (Hands Free) role — connecting side."""
    stack: Any
    supported_codecs: tuple[str, ...] = ("CVSD", "mSBC")

    def __post_init__(self) -> None:
        self._sessions: dict[int, "HFPSession"] = {}

    def _psm(self) -> int:
        # HFP uses RFCOMM, not a direct L2CAP PSM. _psm() is unused by HFP;
        # the ClassicProfile base only calls it if listen_classic_channel is
        # used, but we override register() below to use RFCOMM instead.
        raise NotImplementedError

    def _build_sdp_record(self) -> ServiceRecord:
        return _build_hfp_sdp_record(
            service_class_uuids=[HFP_HF_UUID, GENERIC_AUDIO_UUID],
            features=int(DEFAULT_HF_FEATURES),
        )

    def _on_psm_connect(self, channel) -> None:  # unused
        raise NotImplementedError

    def register(self) -> None:
        self.stack.sdp.register(self._build_sdp_record())
        self.stack.rfcomm.listen_channel(HFP_RFCOMM_CHANNEL, self._on_rfcomm_connect)

    def _on_rfcomm_connect(self, rfcomm_session) -> None:
        # HF role usually initiates; the inverse direction is rare but supported.
        handle = getattr(rfcomm_session, "connection_handle", 0)
        sm = HFPStateMachine(
            role="hf",
            local_features=int(DEFAULT_HF_FEATURES),
            local_codecs=[HFPCodecID.CVSD, HFPCodecID.MSBC],
        )
        session = HFPSession(
            stack=self.stack, rfcomm=rfcomm_session, sm=sm, handle=handle, role="hf",
        )
        self._sessions[handle] = session
        asyncio.create_task(session._run())

    async def connect(self, *, handle: int, channel: int = HFP_RFCOMM_CHANNEL) -> "HFPSession":
        rfcomm_session = await self.stack.rfcomm.connect(handle=handle, channel=channel)
        sm = HFPStateMachine(
            role="hf",
            local_features=int(DEFAULT_HF_FEATURES),
            local_codecs=[HFPCodecID.CVSD, HFPCodecID.MSBC],
        )
        session = HFPSession(
            stack=self.stack, rfcomm=rfcomm_session, sm=sm, handle=handle, role="hf",
        )
        self._sessions[handle] = session
        await session._kick_off()
        return session


@dataclass
class HFPAudioGateway(ClassicProfile):
    """AG (Audio Gateway) role — responding side."""
    stack: Any
    supported_codecs: tuple[str, ...] = ("CVSD", "mSBC")
    on_call_event: Optional[Callable[[str], Awaitable[None]]] = None

    def __post_init__(self) -> None:
        self._sessions: dict[int, "HFPSession"] = {}

    def _psm(self) -> int:
        raise NotImplementedError

    def _build_sdp_record(self) -> ServiceRecord:
        return _build_hfp_sdp_record(
            service_class_uuids=[HFP_AG_UUID, GENERIC_AUDIO_UUID],
            features=int(DEFAULT_AG_FEATURES),
            ag_network=True,
        )

    def _on_psm_connect(self, channel) -> None:
        raise NotImplementedError

    def register(self) -> None:
        self.stack.sdp.register(self._build_sdp_record())
        self.stack.rfcomm.listen_channel(HFP_RFCOMM_CHANNEL, self._on_rfcomm_connect)

    def _on_rfcomm_connect(self, rfcomm_session) -> None:
        handle = getattr(rfcomm_session, "connection_handle", 0)
        sm = HFPStateMachine(
            role="ag",
            local_features=int(DEFAULT_AG_FEATURES),
            local_codecs=[HFPCodecID.CVSD, HFPCodecID.MSBC],
            indicators=[
                ("service", (0, 1)),
                ("call", (0, 1)),
                ("callsetup", (0, 3)),
            ],
            indicator_values={"service": 1, "call": 0, "callsetup": 0},
        )
        session = HFPSession(
            stack=self.stack, rfcomm=rfcomm_session, sm=sm, handle=handle, role="ag",
            on_call_event=self.on_call_event,
        )
        self._sessions[handle] = session
        asyncio.create_task(session._run())


@dataclass
class HFPSession:
    """High-level HFP session — wraps RFCOMM channel + state machine + line buffer."""
    stack: Any
    rfcomm: Any                     # RFCOMM session with async send(bytes) + on_data callback
    sm: HFPStateMachine
    handle: int
    role: str
    on_call_event: Optional[Callable[[str], Awaitable[None]]] = None

    _line_buf: ATLineBuffer = field(default_factory=ATLineBuffer, init=False)
    _slc_done: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _sco_link: Optional[Any] = field(default=None, init=False)

    @property
    def negotiated_codec(self) -> str:
        if self.sm.negotiated_codec is None:
            return ""
        return "mSBC" if self.sm.negotiated_codec == HFPCodecID.MSBC else "CVSD"

    async def _kick_off(self) -> None:
        """HF-side: register on_data and emit AT+BRSF."""
        self.rfcomm.on_data = self._on_data
        out = self.sm.begin()
        for m in out:
            await self._send_at(m)
        # Wait for SLC to come up.
        await asyncio.wait_for(self._slc_done.wait(), timeout=5.0)

    async def _run(self) -> None:
        """AG-side: drive the RFCOMM channel passively until SLC + beyond."""
        self.rfcomm.on_data = self._on_data
        await self._slc_done.wait()

    async def _on_data(self, data: bytes) -> None:
        self._line_buf.feed(data)
        for line in self._line_buf.drain():
            try:
                msg = parse_at_line(line)
            except ValueError:
                continue
            out = self.sm.feed(msg)
            for m in out:
                await self._send_at(m)
            if self.sm.state == SLCState.ESTABLISHED:
                self._slc_done.set()

    async def _send_at(self, msg) -> None:
        if isinstance(msg, ATCommand):
            text = format_at_command(msg)
        elif isinstance(msg, ATResponse):
            text = format_at_response(msg)
        else:
            text = format_unsolicited(msg)
        await self.rfcomm.send(text.encode("ascii"))

    async def close(self) -> None:
        if self._sco_link is not None:
            await self._sco_link.close()
        if hasattr(self.rfcomm, "close"):
            await self.rfcomm.close()
