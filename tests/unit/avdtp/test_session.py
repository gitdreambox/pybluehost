import asyncio

import pytest
import pytest_asyncio

from pybluehost.avdtp.constants import (
    AVDTPSignalID, MediaType, ServiceCategory, TSEP,
)
from pybluehost.avdtp.sep import StreamEndpoint
from pybluehost.avdtp.session import AVDTPSession
from pybluehost.avdtp.signaling import (
    SBCCapability, encode_sbc_codec_capability,
)


class _FakeChannel:
    """Bidirectional in-memory channel used to pair two AVDTPSession instances."""

    def __init__(self) -> None:
        self._inbound: asyncio.Queue[bytes] = asyncio.Queue()
        self._peer: "_FakeChannel | None" = None
        self.closed = False

    def pair(self, peer: "_FakeChannel") -> None:
        self._peer = peer
        peer._peer = self

    async def send(self, data: bytes) -> None:
        if self.closed or self._peer is None:
            raise RuntimeError("channel closed or unpaired")
        await self._peer._inbound.put(bytes(data))

    async def recv(self) -> bytes:
        return await self._inbound.get()

    def close(self) -> None:
        self.closed = True


@pytest_asyncio.fixture
async def paired_sessions():
    ch_a = _FakeChannel()
    ch_b = _FakeChannel()
    ch_a.pair(ch_b)

    sep_a = StreamEndpoint(seid=1, media_type=MediaType.AUDIO, tsep=TSEP.SRC)
    sep_b = StreamEndpoint(seid=2, media_type=MediaType.AUDIO, tsep=TSEP.SNK)

    sess_a = AVDTPSession(ch_a, local_seps=[sep_a])
    sess_b = AVDTPSession(ch_b, local_seps=[sep_b])

    await sess_a.start()
    await sess_b.start()
    yield sess_a, sess_b
    await sess_a.stop()
    await sess_b.stop()


async def test_discover_returns_remote_seps(paired_sessions):
    sess_a, _ = paired_sessions
    seps = await sess_a.discover()
    assert len(seps) == 1
    assert seps[0].seid == 2
    assert seps[0].tsep == TSEP.SNK


async def test_get_capabilities_returns_capability_list(paired_sessions):
    sess_a, sess_b = paired_sessions
    sess_b.set_capabilities(seid=2, capabilities=[
        (ServiceCategory.MEDIA_TRANSPORT, b""),
        (ServiceCategory.MEDIA_CODEC, encode_sbc_codec_capability(
            SBCCapability(
                sample_rates={44100}, channel_modes={"joint_stereo"},
                block_lengths={16}, subbands={8}, allocations={"loudness"},
                min_bitpool=2, max_bitpool=53,
            )
        )),
    ])
    caps = await sess_a.get_capabilities(peer_seid=2)
    categories = [c for c, _ in caps]
    assert ServiceCategory.MEDIA_TRANSPORT in categories
    assert ServiceCategory.MEDIA_CODEC in categories


async def test_set_configuration_transitions_remote_sep_to_configured(paired_sessions):
    sess_a, sess_b = paired_sessions
    sess_b.set_capabilities(seid=2, capabilities=[
        (ServiceCategory.MEDIA_TRANSPORT, b""),
        (ServiceCategory.MEDIA_CODEC, encode_sbc_codec_capability(
            SBCCapability(
                sample_rates={44100}, channel_modes={"joint_stereo"},
                block_lengths={16}, subbands={8}, allocations={"loudness"},
                min_bitpool=2, max_bitpool=53,
            )
        )),
    ])
    await sess_a.set_configuration(
        peer_seid=2, local_seid=1,
        capabilities=[
            (ServiceCategory.MEDIA_TRANSPORT, b""),
            (ServiceCategory.MEDIA_CODEC, encode_sbc_codec_capability(
                SBCCapability(
                    sample_rates={44100}, channel_modes={"joint_stereo"},
                    block_lengths={16}, subbands={8}, allocations={"loudness"},
                    min_bitpool=53, max_bitpool=53,
                )
            )),
        ],
    )
    assert sess_b.get_sep(2).state == "CONFIGURED"


async def test_transaction_id_wraps_around_after_15(paired_sessions):
    sess_a, _ = paired_sessions
    for _ in range(20):
        await sess_a.discover()
