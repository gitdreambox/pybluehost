"""A2DP v1.4 Source and Sink profile classes."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from pybluehost.audio.codec import SBCDecoder, SBCEncoder
from pybluehost.avdtp.constants import (
    MediaType, PSM_AVDTP, ServiceCategory, TSEP,
)
from pybluehost.avdtp.media import AVDTPMediaPacket
from pybluehost.avdtp.sep import StreamEndpoint
from pybluehost.avdtp.session import AVDTPSession
from pybluehost.avdtp.signaling import (
    SBCCapability, encode_sbc_codec_capability,
)
from pybluehost.classic.sdp import DataElement, ServiceRecord
from pybluehost.profiles.classic._common import ClassicProfile


_AUDIO_SOURCE_UUID = 0x110A
_AUDIO_SINK_UUID = 0x110B
_ADV_AUDIO_DISTRIBUTION = 0x110D
_A2DP_PROFILE_VERSION = 0x0104
_AVDTP_UUID = 0x0019
_AVDTP_VERSION = 0x0103
_L2CAP_UUID = 0x0100


def _default_sbc_capability() -> SBCCapability:
    """A2DP v1.4 §4.3.2 mandatory SBC capability range."""
    return SBCCapability(
        sample_rates={16000, 32000, 44100, 48000},
        channel_modes={"mono", "dual", "stereo", "joint_stereo"},
        block_lengths={4, 8, 12, 16},
        subbands={4, 8},
        allocations={"loudness", "snr"},
        min_bitpool=2, max_bitpool=53,
    )


def _build_a2dp_sdp_record(*, service_class_uuid: int) -> ServiceRecord:
    """Standard A2DP service record — Source or Sink determined by UUID."""
    record = ServiceRecord()
    # 0x0001 ServiceClassIDList
    record.attributes[0x0001] = DataElement.sequence([
        DataElement.uuid16(service_class_uuid),
    ])
    # 0x0004 ProtocolDescriptorList: [[L2CAP, PSM], [AVDTP, version]]
    record.attributes[0x0004] = DataElement.sequence([
        DataElement.sequence([
            DataElement.uuid16(_L2CAP_UUID),
            DataElement.uint16(PSM_AVDTP),
        ]),
        DataElement.sequence([
            DataElement.uuid16(_AVDTP_UUID),
            DataElement.uint16(_AVDTP_VERSION),
        ]),
    ])
    # 0x0009 BluetoothProfileDescriptorList: [(0x110D, 0x0104)]
    record.attributes[0x0009] = DataElement.sequence([
        DataElement.sequence([
            DataElement.uuid16(_ADV_AUDIO_DISTRIBUTION),
            DataElement.uint16(_A2DP_PROFILE_VERSION),
        ]),
    ])
    return record


@dataclass
class A2DPSource(ClassicProfile):
    """A2DP Source — outgoing audio (e.g., phone pushing music)."""
    stack: Any
    supported_codecs: tuple[str, ...] = ("SBC",)

    def __post_init__(self) -> None:
        self._local_sep = StreamEndpoint(
            seid=1, media_type=MediaType.AUDIO, tsep=TSEP.SRC,
        )
        self._sessions: dict[int, "A2DPSession"] = {}

    def local_capabilities(self) -> list[tuple[ServiceCategory, bytes]]:
        return [
            (ServiceCategory.MEDIA_TRANSPORT, b""),
            (ServiceCategory.MEDIA_CODEC, encode_sbc_codec_capability(_default_sbc_capability())),
        ]

    def _psm(self) -> int:
        return PSM_AVDTP

    def _build_sdp_record(self) -> ServiceRecord:
        return _build_a2dp_sdp_record(service_class_uuid=_AUDIO_SOURCE_UUID)

    def _on_psm_connect(self, channel) -> None:
        # Peer-initiated channel on our signaling PSM. Source role typically
        # initiates; handle peer-driven path for completeness. First channel
        # for a given ACL handle is signaling; subsequent is media.
        handle = channel.connection_handle
        existing = self._sessions.get(handle)
        if existing is not None:
            existing.avdtp.attach_media_channel(channel)
            return
        avdtp = AVDTPSession(channel, local_seps=[self._local_sep])
        avdtp.set_capabilities(seid=self._local_sep.seid, capabilities=self.local_capabilities())
        session = A2DPSession(
            stack=self.stack, avdtp=avdtp, local_sep=self._local_sep,
            role="source", handle=handle,
        )
        self._sessions[handle] = session
        asyncio.create_task(avdtp.start())

    async def connect(self, *, handle: int) -> "A2DPSession":
        """Open signaling channel to `handle` and return an A2DPSession."""
        ch = await self.stack.l2cap.connect_classic_channel(handle, PSM_AVDTP)
        avdtp = AVDTPSession(ch, local_seps=[self._local_sep])
        avdtp.set_capabilities(seid=self._local_sep.seid, capabilities=self.local_capabilities())
        await avdtp.start()
        session = A2DPSession(
            stack=self.stack, avdtp=avdtp, local_sep=self._local_sep,
            role="source", handle=handle,
        )
        self._sessions[handle] = session
        return session


@dataclass
class A2DPSink(ClassicProfile):
    """A2DP Sink — incoming audio (e.g., speaker receiving phone's stream)."""
    stack: Any
    supported_codecs: tuple[str, ...] = ("SBC",)
    on_pcm: Optional[Callable[[bytes], Awaitable[None]]] = None

    def __post_init__(self) -> None:
        self._local_sep = StreamEndpoint(
            seid=1, media_type=MediaType.AUDIO, tsep=TSEP.SNK,
        )
        self._sessions: dict[int, "A2DPSession"] = {}

    def local_capabilities(self) -> list[tuple[ServiceCategory, bytes]]:
        return [
            (ServiceCategory.MEDIA_TRANSPORT, b""),
            (ServiceCategory.MEDIA_CODEC, encode_sbc_codec_capability(_default_sbc_capability())),
        ]

    def _psm(self) -> int:
        return PSM_AVDTP

    def _build_sdp_record(self) -> ServiceRecord:
        return _build_a2dp_sdp_record(service_class_uuid=_AUDIO_SINK_UUID)

    def _on_psm_connect(self, channel) -> None:
        # First channel for a given ACL handle is the AVDTP signaling channel;
        # a subsequent channel on the same handle is the media channel that
        # the source opened after we accepted OPEN.
        handle = channel.connection_handle
        existing = self._sessions.get(handle)
        if existing is not None:
            existing.avdtp.attach_media_channel(channel)
            return
        avdtp = AVDTPSession(channel, local_seps=[self._local_sep])
        avdtp.set_capabilities(seid=self._local_sep.seid, capabilities=self.local_capabilities())
        session = A2DPSession(
            stack=self.stack, avdtp=avdtp, local_sep=self._local_sep,
            role="sink", on_pcm=self.on_pcm, handle=handle,
        )
        self._sessions[handle] = session
        asyncio.create_task(avdtp.start())
        asyncio.create_task(session._sink_rx_loop())


@dataclass
class A2DPSession:
    """High-level A2DP session — wraps AVDTPSession with codec encode/decode.

    Source: `negotiate_codec()`, `start()`, `send_pcm()`, `suspend()`, `close()`.
    Sink: receives media packets via the underlying AVDTPSession and decodes to PCM.
    """
    stack: Any
    avdtp: AVDTPSession
    local_sep: StreamEndpoint
    role: str
    on_pcm: Optional[Callable[[bytes], Awaitable[None]]] = None
    handle: Optional[int] = None

    _encoder: Optional[SBCEncoder] = field(default=None, init=False)
    _decoder: Optional[SBCDecoder] = field(default=None, init=False)
    _seq: int = field(default=0, init=False)
    _ssrc: int = field(default=0xA2DA2D, init=False)
    _peer_seid: Optional[int] = field(default=None, init=False)

    async def negotiate_codec(self, *, prefer: tuple[str, ...] = ("SBC",)) -> dict:
        if self.role != "source":
            raise RuntimeError("negotiate_codec is source-side only")
        peer_seps = await self.avdtp.discover()
        for psep in peer_seps:
            if psep.tsep != TSEP.SNK:
                continue
            await self.avdtp.get_capabilities(peer_seid=psep.seid)
            config = SBCCapability(
                sample_rates={44100}, channel_modes={"joint_stereo"},
                block_lengths={16}, subbands={8}, allocations={"loudness"},
                min_bitpool=53, max_bitpool=53,
            )
            await self.avdtp.set_configuration(
                peer_seid=psep.seid, local_seid=self.local_sep.seid,
                capabilities=[
                    (ServiceCategory.MEDIA_TRANSPORT, b""),
                    (ServiceCategory.MEDIA_CODEC, encode_sbc_codec_capability(config)),
                ],
            )
            self._peer_seid = psep.seid
            self._encoder = SBCEncoder(
                sample_rate=44100, channels=2, channel_mode="joint_stereo",
                blocks=16, subbands=8, allocation="loudness", bitpool=53,
            )
            return {"codec": "SBC", "config": config, "peer_seid": psep.seid}
        raise RuntimeError("no compatible Sink SEP found on peer")

    async def start(self) -> None:
        if self._peer_seid is None:
            raise RuntimeError("call negotiate_codec() first")
        await self.avdtp.open(peer_seid=self._peer_seid)
        # Source side opens the L2CAP media channel after AVDTP OPEN — peer's
        # L2CAP listener at PSM 0x0019 routes the second channel to the same
        # A2DPSession (by ACL handle) and attaches it as media. Done before
        # START so the streaming path is fully wired.
        if self.role == "source" and self.handle is not None:
            media_ch = await self.stack.l2cap.connect_classic_channel(
                self.handle, PSM_AVDTP,
            )
            self.avdtp.attach_media_channel(media_ch)
            # Give peer a tick to receive its media channel via _on_psm_connect
            # and attach it to its own AVDTPSession before we start streaming.
            await asyncio.sleep(0.05)
        await self.avdtp.start_stream(peer_seids=[self._peer_seid])

    async def suspend(self) -> None:
        if self._peer_seid is not None:
            await self.avdtp.suspend(peer_seids=[self._peer_seid])

    async def close(self) -> None:
        if self._peer_seid is not None:
            await self.avdtp.close(peer_seid=self._peer_seid)
        await self.avdtp.stop()

    async def send_pcm(self, pcm_bytes: bytes) -> None:
        if self._encoder is None:
            raise RuntimeError("encoder not set — call negotiate_codec() first")
        sbc_frame = self._encoder.encode(pcm_bytes)
        packet = AVDTPMediaPacket(
            sequence_number=self._seq & 0xFFFF,
            timestamp=self._seq * 128,
            ssrc=self._ssrc,
            payload=sbc_frame,
            frame_count=1,
        )
        self._seq += 1
        await self.avdtp.send_media(packet)

    async def _sink_rx_loop(self) -> None:
        if self.role != "sink":
            return
        self._decoder = SBCDecoder()
        while True:
            try:
                packet = await self.avdtp.recv_media()
            except Exception:
                return
            try:
                pcm, _ = self._decoder.decode(packet.payload)
            except Exception:
                continue
            if self.on_pcm is not None:
                await self.on_pcm(pcm)
