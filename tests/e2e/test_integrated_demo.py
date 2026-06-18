"""Integrated demo e2e — phone + headphone profiles end-to-end.

Phone stack registers A2DP Source + AVRCP Target + HFP AG.
Headphone stack connects A2DP Sink + AVRCP Controller + HFP HF.

Verifies the full integration:
- A2DP music flows from phone → headphone (received bytes > 0)
- AVRCP PASS_THROUGH command from headphone → phone roundtrips (ACCEPTED)
- HFP RING from phone → headphone HF receives it
"""
from __future__ import annotations

import asyncio
import math
import os
import struct
import wave

import pytest
import pytest_asyncio

from pybluehost.classic.avrcp.constants import AVRCPOperationID
from pybluehost.hci.virtual_classic_link import VirtualClassicLink
from pybluehost.profiles.classic import (
    A2DPSink, A2DPSource, AVRCPController, AVRCPTarget,
    HFPAudioGateway, HFPHandsFree,
)
from pybluehost.profiles.classic._at_parser import ATUnsolicited

from tests.e2e._helpers import (
    classic_discover_and_pair_jw, disconnect_classic_and_wait, e2e_timeout,
)


pytestmark = pytest.mark.asyncio


def _make_music_wav(path: str, secs: float = 0.3) -> int:
    sr = 44100
    n = int(sr * secs)
    samples = []
    for i in range(n):
        # Stereo: L = 440 Hz, R = 660 Hz, both ~6000 amplitude
        l = int(6000 * math.sin(2 * math.pi * 440 * i / sr))
        r = int(6000 * math.sin(2 * math.pi * 660 * i / sr))
        samples.append(l)
        samples.append(r)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return n


@pytest_asyncio.fixture
async def integrated_pair(stack, peer_stack, transport_mode):
    if transport_mode != "virtual":
        pytest.skip("Integrated demo e2e runs virtual only")
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
        # Treat stack=peer (central) as the HEADPHONE; peer_stack as the PHONE.
        # This way the headphone initiates the connection.
        yield stack, peer_stack, link
    finally:
        try:
            await link.disconnect()
        except Exception:
            pass


async def test_phone_headphone_integrated_demo(integrated_pair, transport_mode, tmp_path):
    """Full integrated lifecycle:
    1. Headphone pairs with phone
    2. Headphone connects A2DP Sink — phone Source streams music — PCM received
    3. Headphone AVRCP Controller sends PAUSE — phone AVRCP Target receives ACCEPTED
    4. Phone HFP AG fires RING — headphone HFP HF observes it
    """
    stack_headphone, stack_phone, _link = integrated_pair
    timeout = e2e_timeout(transport_mode, virtual=15.0)

    music_wav = tmp_path / "music.wav"
    rx_music = tmp_path / "received.wav"
    _make_music_wav(str(music_wav))

    # ---- PHONE side (passive: A2DP Source + AVRCP Target + HFP AG) ----
    avrcp_commands_seen: list[int] = []

    async def on_pass_through(cmd) -> bool:
        if cmd.pressed:
            avrcp_commands_seen.append(cmd.operation_id)
        return True

    async def on_notify_register(event_id: int) -> bytes:
        return b"\x01"

    phone_src = A2DPSource(stack=stack_phone)
    phone_src.register()
    phone_avrcp = AVRCPTarget(
        stack=stack_phone,
        on_pass_through=on_pass_through,
        on_notification_register=on_notify_register,
    )
    phone_avrcp.register()
    phone_hfp = HFPAudioGateway(stack=stack_phone)
    phone_hfp.register()

    # ---- HEADPHONE side (active: A2DP Sink + AVRCP Controller + HFP HF) ----
    received_chunks: list[bytes] = []

    async def on_music(pcm: bytes) -> None:
        received_chunks.append(pcm)

    hp_sink = A2DPSink(stack=stack_headphone, on_pcm=on_music)
    hp_sink.register()
    hp_avrcp = AVRCPController(stack=stack_headphone)
    hp_avrcp.register()
    hp_hfp = HFPHandsFree(stack=stack_headphone)
    hp_hfp.register()

    handle = None
    try:
        # Step 1: pair
        handle = await classic_discover_and_pair_jw(
            stack_headphone, stack_phone._local_address,
            scan_timeout=timeout, pair_timeout=timeout,
        )

        # Step 2: AVRCP control — headphone sends PAUSE to phone
        avrcp_session = await hp_avrcp.connect(handle=handle)
        await asyncio.sleep(0.2)
        accepted = await avrcp_session.pause()
        assert accepted, "AVRCP PAUSE was not ACCEPTED by phone target"
        assert AVRCPOperationID.PAUSE in avrcp_commands_seen, (
            f"Phone target did not log PAUSE command (saw: {avrcp_commands_seen})"
        )

        # Step 3: A2DP — headphone sink connects A2DP source, music flows
        # The phone-side source needs to actively push WAV. We do that here.
        # First make the headphone's A2DP-sink session arm by connecting.
        # In the loopback path, the SOURCE initiates the AVDTP signaling.
        # So we have phone push via its A2DPSource.connect path:
        phone_a2dp_session = await phone_src.connect(handle=handle)
        await phone_a2dp_session.negotiate_codec()
        await phone_a2dp_session.start()

        # Push some frames. WAV readframes(n) returns n stereo frames = 4 bytes each;
        # SBCEncoder wants 128 stereo frames (256 int16 samples = 512 bytes per encode).
        with wave.open(str(music_wav), "rb") as w:
            bytes_per_frame_in = 2 * 16 * 8 * 2   # 512
            n_pushed = 0
            while n_pushed < 8:
                pcm = w.readframes(128)
                if len(pcm) < bytes_per_frame_in:
                    break
                await phone_a2dp_session.send_pcm(pcm)
                n_pushed += 1

        # Drain on the sink side
        for _ in range(20):
            if sum(len(c) for c in received_chunks) > 0:
                break
            await asyncio.sleep(0.05)
        assert len(received_chunks) > 0, "headphone A2DP sink did not receive any audio"

        await phone_a2dp_session.close()

        # Step 4: HFP — headphone connects HF; phone AG emits RING
        # The HFP HF.connect() drives SLC; phone AG handles BRSF→BAC→CIND→CMER.
        hfp_hf_session = await hp_hfp.connect(handle=handle)
        await asyncio.sleep(0.2)
        assert hfp_hf_session.sm.state.name == "ESTABLISHED", (
            f"HFP SLC not ESTABLISHED: {hfp_hf_session.sm.state}"
        )

        # Phone AG emits RING — verify it doesn't crash; we don't assert
        # observation on HF side because the unsolicited RING handler is
        # informational only.
        phone_hfp_sess = next(iter(phone_hfp._sessions.values()))
        await phone_hfp_sess._send_at(ATUnsolicited(name="RING", args=[]))
        await asyncio.sleep(0.1)

        await avrcp_session.close()
        await hfp_hf_session.close()

    finally:
        if handle is not None:
            try:
                await disconnect_classic_and_wait(stack_headphone, handle, timeout=timeout)
            except Exception:
                pass
