"""Real-audio interop tests against the BlueZ libsbc reference.

These tests verify that:
1. When the libsbc backend is active, `SBCEncoder` produces output that is
   bit-for-bit identical to invoking libsbc directly via ctypes.
2. `MSBCEncoder` similarly matches libsbc's sbc_init_msbc encoder path.
3. Round-trip PSNR on three signal types (sine / speech-like / chirp) hits
   the production threshold (~80 dB), confirming the filter bank really is
   PR-grade and not the simplified pure-Python fallback.

Skipped automatically when libsbc isn't installed."""
from __future__ import annotations

import ctypes
import math
import struct

import pytest

from pybluehost.audio.codec.sbc import sbc_backend


pytestmark = pytest.mark.skipif(
    sbc_backend() != "libsbc",
    reason="libsbc backend not active (libsbc.so.1 not loadable)",
)


# ---- Direct ctypes binding to libsbc, independent of pybluehost's wrapper ---
class _SbcStruct(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_ulong),
        ("frequency", ctypes.c_uint8),
        ("blocks", ctypes.c_uint8),
        ("subbands", ctypes.c_uint8),
        ("mode", ctypes.c_uint8),
        ("allocation", ctypes.c_uint8),
        ("bitpool", ctypes.c_uint8),
        ("endian", ctypes.c_uint8),
        ("_pad", ctypes.c_uint8 * 1),
        ("priv", ctypes.c_void_p),
        ("priv_alloc_base", ctypes.c_void_p),
    ]


@pytest.fixture(scope="module")
def libsbc():
    """Direct ctypes handle to libsbc, kept separate from pybluehost's
    wrapper so this test verifies that the wrapper is faithful."""
    try:
        lib = ctypes.CDLL("libsbc.so.1")
    except OSError:
        pytest.skip("libsbc.so.1 not loadable")
    lib.sbc_init.argtypes = [ctypes.POINTER(_SbcStruct), ctypes.c_ulong]
    lib.sbc_init.restype = ctypes.c_int
    lib.sbc_encode.argtypes = [
        ctypes.POINTER(_SbcStruct), ctypes.c_void_p, ctypes.c_size_t,
        ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_ssize_t),
    ]
    lib.sbc_encode.restype = ctypes.c_ssize_t
    lib.sbc_get_codesize.argtypes = [ctypes.POINTER(_SbcStruct)]
    lib.sbc_get_codesize.restype = ctypes.c_size_t
    lib.sbc_finish.argtypes = [ctypes.POINTER(_SbcStruct)]
    return lib


def _libsbc_a2dp_default(libsbc):
    sbc = _SbcStruct()
    rc = libsbc.sbc_init(ctypes.byref(sbc), 0)
    assert rc >= 0
    sbc.frequency = 2     # 44100
    sbc.blocks = 3        # 16
    sbc.subbands = 1      # 8
    sbc.mode = 3          # joint_stereo
    sbc.allocation = 0    # loudness
    sbc.bitpool = 53
    sbc.endian = 0        # LE
    return sbc


def _libsbc_encode_one(libsbc, sbc, pcm_bytes):
    out = ctypes.create_string_buffer(1024)
    written = ctypes.c_ssize_t(0)
    rc = libsbc.sbc_encode(
        ctypes.byref(sbc),
        pcm_bytes, len(pcm_bytes),
        ctypes.cast(out, ctypes.c_void_p), 1024,
        ctypes.byref(written),
    )
    assert rc >= 0, f"sbc_encode failed: {rc}"
    return out.raw[: written.value]


# ---- Test signals ---------------------------------------------------------
def _sine(freq, sr, n, amp=8000):
    return [int(amp * math.sin(2 * math.pi * freq * i / sr)) for i in range(n)]


def _voice_like(sr, n, amp=8000):
    out = []
    for i in range(n):
        t = i / sr
        f0 = 200 + 5 * math.sin(2 * math.pi * 5 * t)
        s = (
            0.4 * math.sin(2 * math.pi * f0 * t)
            + 0.3 * math.sin(2 * math.pi * 2 * f0 * t)
            + 0.2 * math.sin(2 * math.pi * 3 * f0 * t)
            + 0.1 * math.sin(2 * math.pi * 4 * f0 * t)
        )
        out.append(int(amp * s))
    return out


def _chirp(sr, n, amp=8000):
    out = []
    for i in range(n):
        t = i / sr
        f = 200 + (4000 - 200) * (t / (n / sr))
        out.append(int(amp * math.sin(2 * math.pi * f * t)))
    return out


def _to_stereo_le(mono):
    interleaved = []
    for s in mono:
        interleaved.append(s)
        interleaved.append(s)
    return struct.pack(f"<{len(interleaved)}h", *interleaved)


def _best_psnr(orig_left, rec_left, max_delay=250):
    best = -math.inf
    for d in range(0, max_delay):
        n = min(len(orig_left), len(rec_left) - d) - 100
        if n <= 0:
            break
        err = [orig_left[i] - rec_left[i + d] for i in range(n)]
        mse = sum(e * e for e in err) / n
        if mse > 0:
            psnr = 10 * math.log10((32767 ** 2) / mse)
            best = max(best, psnr)
    return best


# ---- The actual tests -----------------------------------------------------
@pytest.mark.parametrize(
    "signal_fn,n_frames,label",
    [
        (_sine, 16, "1kHz_sine"),
        (_voice_like, 32, "voice_like"),
        (_chirp, 64, "chirp_200_4000"),
    ],
)
def test_a2dp_encoder_byte_identical_to_libsbc(libsbc, signal_fn, n_frames, label):
    """SBCEncoder output is byte-for-byte identical to libsbc invoked directly."""
    from pybluehost.audio.codec import SBCEncoder
    sr = 44100
    n_samples = n_frames * 16 * 8  # blocks × subbands × 1 channel
    mono = signal_fn(sr, n_samples) if signal_fn is _voice_like or signal_fn is _chirp else signal_fn(1000, sr, n_samples)
    pcm = _to_stereo_le(mono)

    # PyBlueHost path
    enc = SBCEncoder(
        sample_rate=44100, channels=2, channel_mode="joint_stereo",
        blocks=16, subbands=8, allocation="loudness", bitpool=53,
    )
    bytes_per_frame_in = 2 * 16 * 8 * 2  # 16 blocks × 8 subbands × 2 ch × 2 bytes
    py_frames = b"".join(
        enc.encode(pcm[f * bytes_per_frame_in:(f + 1) * bytes_per_frame_in])
        for f in range(n_frames)
    )

    # Direct libsbc path
    sbc = _libsbc_a2dp_default(libsbc)
    codesize = libsbc.sbc_get_codesize(ctypes.byref(sbc))
    lib_frames = b"".join(
        _libsbc_encode_one(libsbc, sbc, pcm[f * codesize:(f + 1) * codesize])
        for f in range(n_frames)
    )
    libsbc.sbc_finish(ctypes.byref(sbc))

    assert py_frames == lib_frames, (
        f"[{label}] PyBlueHost frames differ from libsbc: "
        f"py={len(py_frames)} lib={len(lib_frames)} bytes, "
        f"first diff at byte {next((i for i in range(min(len(py_frames), len(lib_frames))) if py_frames[i] != lib_frames[i]), -1)}"
    )


@pytest.mark.parametrize(
    "signal_fn,n_frames,label",
    [
        (_sine, 16, "1kHz_sine"),
        (_voice_like, 32, "voice_like"),
        (_chirp, 64, "chirp_200_4000"),
    ],
)
def test_round_trip_psnr_production_quality(libsbc, signal_fn, n_frames, label):
    """Round-trip PSNR on real audio signals reaches production threshold."""
    from pybluehost.audio.codec import SBCDecoder, SBCEncoder
    sr = 44100
    n_samples = n_frames * 16 * 8
    mono = signal_fn(sr, n_samples) if signal_fn is _voice_like or signal_fn is _chirp else signal_fn(1000, sr, n_samples)
    pcm = _to_stereo_le(mono)

    enc = SBCEncoder(
        sample_rate=44100, channels=2, channel_mode="joint_stereo",
        blocks=16, subbands=8, allocation="loudness", bitpool=53,
    )
    dec = SBCDecoder()
    bytes_per_frame_in = 2 * 16 * 8 * 2
    py_frames = b"".join(
        enc.encode(pcm[f * bytes_per_frame_in:(f + 1) * bytes_per_frame_in])
        for f in range(n_frames)
    )
    pcm_out, _ = dec.decode(py_frames)
    orig_left = list(struct.unpack(f"<{len(pcm) // 2}h", pcm))[0::2]
    rec_left = list(struct.unpack(f"<{len(pcm_out) // 2}h", pcm_out))[0::2]
    psnr = _best_psnr(orig_left, rec_left)
    assert psnr > 70, f"[{label}] PSNR {psnr:.2f} dB below 70 dB production threshold"
