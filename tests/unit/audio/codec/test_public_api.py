def test_public_api_exports():
    import pybluehost.audio.codec as codec
    for name in ("SBCEncoder", "SBCDecoder", "CVSDEncoder", "CVSDDecoder",
                 "MSBCEncoder", "MSBCDecoder", "SBCHeader"):
        assert hasattr(codec, name), f"{name} missing from public API"


def test_quick_smoke_sbc_round_trip():
    """Quick smoke: encode + decode silence on the A2DP default config."""
    from pybluehost.audio.codec import SBCDecoder, SBCEncoder

    enc = SBCEncoder(
        sample_rate=44100, channels=2, channel_mode="joint_stereo",
        blocks=16, subbands=8, allocation="loudness", bitpool=53,
    )
    dec = SBCDecoder()
    pcm = bytes(2 * 16 * 8 * 2)
    frame = enc.encode(pcm)
    assert len(frame) == 119
    assert frame[0] == 0x9C
    decoded, consumed = dec.decode(frame)
    assert consumed == 119
    assert len(decoded) == 2 * 16 * 8 * 2
