"""HFP HF ↔ AG end-to-end via VirtualClassicLink — SLC + SCO + WAV loopback."""
from __future__ import annotations

import asyncio
import math
import os
import struct
import wave

import pytest
import pytest_asyncio

from pybluehost.hci.virtual_classic_link import VirtualClassicLink
from pybluehost.profiles.classic import HFPAudioGateway, HFPHandsFree
from pybluehost.profiles.classic._sco_loopback import (
    ScoToWavReceiver, WavToScoSender,
)

from tests.e2e._helpers import (
    classic_discover_and_pair_jw, disconnect_classic_and_wait, e2e_timeout,
)


pytestmark = pytest.mark.asyncio


def _make_sine_wav(path: str, sample_rate: int, secs: float = 0.5) -> int:
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
async def hfp_pair(stack, peer_stack, transport_mode):
    if transport_mode != "virtual":
        pytest.skip("HFP real-hardware loopback is A.6 runbook")
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


async def test_hfp_slc_plus_sco_wav_round_trip(hfp_pair, transport_mode, tmp_path):
    """HF connects to AG, drives SLC, sets up SCO, sends 0.5 s of WAV; AG
    receives and writes WAV. Both files must exist and match in length."""
    stack_hf, stack_ag, _link = hfp_pair
    timeout = e2e_timeout(transport_mode, virtual=10.0)

    src_wav = tmp_path / "src.wav"
    rx_wav = tmp_path / "rx.wav"
    _make_sine_wav(str(src_wav), sample_rate=8000)

    ag = HFPAudioGateway(stack=stack_ag)
    ag.register()
    hf = HFPHandsFree(stack=stack_hf)
    hf.register()

    handle = None
    try:
        handle = await classic_discover_and_pair_jw(
            stack_hf, stack_ag._local_address,
            scan_timeout=timeout, pair_timeout=timeout,
        )
        session = await hf.connect(handle=handle)
        # SLC should be up: hf.connect() awaits _kick_off which waits for _slc_done.
        assert session.sm.state.name == "ESTABLISHED"

        # Give the AG side a moment to arm its SCO listener via _arm_sco_listener().
        await asyncio.sleep(0.1)

        # Setup SCO on the HF side; this also triggers Synchronous_Connection_Complete
        # on the AG side, which _arm_sco_listener() resolves.
        sco_link = await session.setup_sco()

        # Wait for the AG SCOLink to be populated.
        ag_session = next(iter(ag._sessions.values()))
        for _ in range(20):
            if ag_session._sco_link is not None:
                break
            await asyncio.sleep(0.05)
        assert ag_session._sco_link is not None, "AG never received Synchronous_Connection_Complete"

        ag_sco_link = ag_session._sco_link

        receiver = ScoToWavReceiver(wav_path=str(rx_wav), sco_link=ag_sco_link)
        sender = WavToScoSender(wav_path=str(src_wav), sco_link=sco_link)

        await sender.run()
        await asyncio.sleep(0.2)    # let the inbound SCO drain
        receiver.close()
        await session.close()

        # Validate received WAV is non-empty and roughly the right length.
        assert os.path.exists(rx_wav)
        with wave.open(str(rx_wav), "rb") as w:
            n_received = w.getnframes()
        with wave.open(str(src_wav), "rb") as w:
            n_sent = w.getnframes()
        # Codec frame loss tolerance: ±10%.
        assert n_received > 0, "AG received no PCM frames"
        assert 0.9 * n_sent <= n_received <= 1.1 * n_sent, (
            f"frame count mismatch: sent={n_sent}, received={n_received}"
        )
    finally:
        if handle is not None:
            try:
                await disconnect_classic_and_wait(stack_hf, handle, timeout=timeout)
            except Exception:
                pass
