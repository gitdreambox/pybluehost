"""HSP HS ↔ AG end-to-end via VirtualClassicLink — RFCOMM + SCO + WAV (CVSD)."""
from __future__ import annotations

import asyncio
import math
import os
import struct
import wave

import pytest
import pytest_asyncio

from pybluehost.hci.virtual_classic_link import VirtualClassicLink
from pybluehost.profiles.classic import HSPAudioGateway, HSPHeadset
from pybluehost.profiles.classic._hsp_constants import HSP_AG_RFCOMM_CHANNEL
from pybluehost.profiles.classic._sco_loopback import (
    ScoToWavReceiver, WavToScoSender,
)

from tests.e2e._helpers import (
    classic_discover_and_pair_jw, disconnect_classic_and_wait, e2e_timeout,
)


pytestmark = pytest.mark.asyncio


def _make_sine_wav(path: str, sample_rate: int, secs: float = 0.3) -> int:
    n = int(sample_rate * secs)
    samples = [int(6000 * math.sin(2 * math.pi * 400 * i / sample_rate))
               for i in range(n)]
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(struct.pack(f"<{n}h", *samples))
    return n


@pytest_asyncio.fixture
async def hsp_pair(stack, peer_stack, transport_mode):
    if transport_mode != "virtual":
        pytest.skip("HSP real-hardware loopback is A.6 runbook")
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


async def test_hsp_rfcomm_plus_sco_wav_round_trip(hsp_pair, transport_mode, tmp_path):
    """HS connects to AG on channel 12, requests audio via +CKPD, sets up CVSD
    SCO, sends a WAV; AG receives and writes a WAV. Both must match ±10%."""
    stack_hs, stack_ag, _link = hsp_pair
    timeout = e2e_timeout(transport_mode, virtual=10.0)

    src_wav = tmp_path / "src.wav"
    rx_wav = tmp_path / "rx.wav"
    _make_sine_wav(str(src_wav), sample_rate=8000)

    button_presses = []

    async def on_button() -> None:
        button_presses.append(True)

    ag = HSPAudioGateway(stack=stack_ag, on_button_press=on_button)
    ag.register()
    hs = HSPHeadset(stack=stack_hs)
    hs.register()

    handle = None
    try:
        handle = await classic_discover_and_pair_jw(
            stack_hs, stack_ag._local_address,
            scan_timeout=timeout, pair_timeout=timeout,
        )
        session = await hs.connect(handle=handle, channel=HSP_AG_RFCOMM_CHANNEL)
        await asyncio.sleep(0.1)

        await session.request_audio()
        await asyncio.sleep(0.1)
        assert len(button_presses) == 1

        sco_link = await session.setup_sco()
        assert sco_link.codec == "CVSD"

        ag_session = next(iter(ag._sessions.values()))
        for _ in range(20):
            if ag_session._sco_link is not None:
                break
            await asyncio.sleep(0.05)
        ag_sco_link = ag_session._sco_link
        assert ag_sco_link is not None, "AG-side SCO link never armed"

        receiver = ScoToWavReceiver(wav_path=str(rx_wav), sco_link=ag_sco_link)
        sender = WavToScoSender(wav_path=str(src_wav), sco_link=sco_link)

        await sender.run()
        await asyncio.sleep(0.2)
        receiver.close()
        await session.close()

        assert os.path.exists(rx_wav)
        with wave.open(str(rx_wav), "rb") as w:
            n_received = w.getnframes()
        with wave.open(str(src_wav), "rb") as w:
            n_sent = w.getnframes()
        assert 0.9 * n_sent <= n_received <= 1.1 * n_sent, (
            f"length mismatch: sent {n_sent}, received {n_received}"
        )
    finally:
        if handle is not None:
            try:
                await disconnect_classic_and_wait(stack_hs, handle, timeout=timeout)
            except Exception:
                pass
