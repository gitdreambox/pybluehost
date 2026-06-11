"""A2DP source→sink end-to-end loopback via VirtualClassicLink.

Two Stack.virtual() instances are paired; source registers A2DPSource, sink
registers A2DPSink. Source initiates inquiry+pair+AVDTP connect, negotiates
SBC codec, opens a media channel, and pushes encoded SBC frames. Sink decodes
back to PCM; we assert PSNR > 60 dB end-to-end (libsbc backend).
"""
from __future__ import annotations

import asyncio
import math
import struct

import pytest
import pytest_asyncio

from pybluehost.hci.virtual_classic_link import VirtualClassicLink
from pybluehost.profiles.classic import A2DPSink, A2DPSource

from tests.e2e._helpers import (
    classic_discover_and_pair_jw, disconnect_classic_and_wait, e2e_timeout,
)


pytestmark = pytest.mark.asyncio


def _sine_pcm_stereo(freq_hz: float, sample_rate: int, num_samples: int) -> bytes:
    mono = [int(8000 * math.sin(2 * math.pi * freq_hz * i / sample_rate))
            for i in range(num_samples)]
    interleaved = [s for s in mono for _ in range(2)]
    return struct.pack(f"<{len(interleaved)}h", *interleaved)


def _best_psnr(orig: list[int], rec: list[int], max_delay: int = 250) -> float:
    best = -math.inf
    for d in range(0, max_delay):
        if d + 200 >= len(rec):
            break
        n = min(len(orig) - d, len(rec) - d) - 100
        if n <= 0:
            continue
        err = [orig[i] - rec[i + d] for i in range(n)]
        mse = sum(e * e for e in err) / n
        if mse > 0:
            best = max(best, 10 * math.log10((32767 ** 2) / mse))
    return best


@pytest_asyncio.fixture
async def a2dp_pair(stack, peer_stack, transport_mode):
    """Pair two Classic stacks via VirtualClassicLink; register A2DPSink on peer."""
    if transport_mode == "virtual":
        # Make peer connectable + discoverable.
        await peer_stack.gap.classic_discoverability.set_connectable(True)
        await peer_stack.gap.classic_discoverability.set_discoverable(True)
        link = VirtualClassicLink(
            central=stack._virtual_controller,
            peripheral=peer_stack._virtual_controller,
            central_address=stack._local_address,
            peripheral_address=peer_stack._local_address,
            page_timeout_seconds=0.5,
        )
        link.attach()
        try:
            yield stack, peer_stack, link
        finally:
            try:
                await link.disconnect()
            except Exception:
                pass
    else:
        pytest.skip("real-hardware A2DP loopback is part of A.6 runbook, not e2e suite")


async def test_a2dp_source_to_sink_loopback_via_virtual(
    a2dp_pair, transport_mode,
):
    """End-to-end PCM loopback over AVDTP: pair → AVDTP signaling chain →
    open second L2CAP media channel → push 16 frames of 1 kHz sine →
    sink decodes back to PCM → assert PSNR > 60 dB."""
    stack_src, stack_snk, _link = a2dp_pair
    timeout = e2e_timeout(transport_mode, virtual=5.0)

    received_pcm: list[bytes] = []

    async def collect_pcm(pcm: bytes) -> None:
        received_pcm.append(pcm)

    sink = A2DPSink(stack=stack_snk, on_pcm=collect_pcm)
    sink.register()

    src = A2DPSource(stack=stack_src)
    src.register()

    handle = None
    try:
        handle = await classic_discover_and_pair_jw(
            stack_src, stack_snk._local_address,
            scan_timeout=timeout, pair_timeout=timeout,
        )
        session = await src.connect(handle=handle)

        # Let peer spin up its AVDTPSession before we issue signaling commands.
        await asyncio.sleep(0.1)

        await asyncio.wait_for(session.negotiate_codec(), timeout=timeout)
        await asyncio.wait_for(session.start(), timeout=timeout)

        # Push 16 frames of 1 kHz sine. Source-side SBCEncoder is joint-stereo,
        # 16 blocks × 8 subbands × 2 channels = 256 samples = 512 bytes per
        # encode call.
        n_frames = 16
        bytes_per_frame_in = 2 * 16 * 8 * 2
        pcm = _sine_pcm_stereo(1000, 44100, n_frames * 16 * 8)
        for f in range(n_frames):
            await session.send_pcm(
                pcm[f * bytes_per_frame_in:(f + 1) * bytes_per_frame_in]
            )

        # Drain sink — wait up to a few seconds for accumulated PCM.
        for _ in range(60):
            if sum(len(b) for b in received_pcm) >= bytes_per_frame_in * (n_frames - 2):
                break
            await asyncio.sleep(0.05)

        await session.close()

        rec_bytes = b"".join(received_pcm)
        assert rec_bytes, "sink received no PCM"
        orig_left = list(struct.unpack(f"<{len(pcm) // 2}h", pcm))[0::2]
        rec_left = list(struct.unpack(f"<{len(rec_bytes) // 2}h", rec_bytes))[0::2]
        psnr = _best_psnr(orig_left, rec_left)
        assert psnr > 60, f"PSNR {psnr:.2f} dB below 60 dB e2e threshold"
    finally:
        if handle is not None:
            try:
                await disconnect_classic_and_wait(stack_src, handle, timeout=timeout)
            except Exception:
                pass
