"""ctypes binding to BlueZ libsbc (LGPL-2.1+).

When `libsbc.so.1` is loadable, this gives a byte-exact, production-quality
SBC encoder/decoder — same code that PulseAudio / PipeWire use for A2DP.

The pure-Python implementation in `sbc.py` (`_PurePythonSBCEncoder` etc.)
remains as a fallback when libsbc is unavailable and as a transparent
reference for the codec internals. Plan A.1 documented that fallback's
~60 dB PSNR gap vs reference — this module is how we close that gap.

Loading is lazy: importing this module doesn't open the library; the first
encoder/decoder construction does. ImportError surfaces if the library
isn't present so the caller can switch backends.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import struct


_lib = None


def _load() -> ctypes.CDLL:
    global _lib
    if _lib is not None:
        return _lib
    # Prefer the SONAME so we get a stable ABI; fall back to ctypes.util search.
    for candidate in ("libsbc.so.1", "libsbc.so"):
        try:
            _lib = ctypes.CDLL(candidate)
            break
        except OSError:
            continue
    if _lib is None:
        found = ctypes.util.find_library("sbc")
        if found:
            _lib = ctypes.CDLL(found)
    if _lib is None:
        raise ImportError("libsbc.so.1 not found — install libsbc1 / libsbc-dev")
    _bind(_lib)
    return _lib


class _SbcStruct(ctypes.Structure):
    """Mirror of struct sbc_struct from sbc.h.

    Layout matches BlueZ's exact field order; size matches ABI compiled with
    default packing (the trailing void* pointers are 8-byte aligned)."""
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


def _bind(lib: ctypes.CDLL) -> None:
    lib.sbc_init.argtypes = [ctypes.POINTER(_SbcStruct), ctypes.c_ulong]
    lib.sbc_init.restype = ctypes.c_int
    lib.sbc_init_msbc.argtypes = [ctypes.POINTER(_SbcStruct), ctypes.c_ulong]
    lib.sbc_init_msbc.restype = ctypes.c_int
    lib.sbc_encode.argtypes = [
        ctypes.POINTER(_SbcStruct),
        ctypes.c_void_p, ctypes.c_size_t,
        ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_ssize_t),
    ]
    lib.sbc_encode.restype = ctypes.c_ssize_t
    lib.sbc_decode.argtypes = [
        ctypes.POINTER(_SbcStruct),
        ctypes.c_void_p, ctypes.c_size_t,
        ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    lib.sbc_decode.restype = ctypes.c_ssize_t
    lib.sbc_get_codesize.argtypes = [ctypes.POINTER(_SbcStruct)]
    lib.sbc_get_codesize.restype = ctypes.c_size_t
    lib.sbc_get_frame_length.argtypes = [ctypes.POINTER(_SbcStruct)]
    lib.sbc_get_frame_length.restype = ctypes.c_size_t
    lib.sbc_finish.argtypes = [ctypes.POINTER(_SbcStruct)]


_FREQ_CODES = {16000: 0, 32000: 1, 44100: 2, 48000: 3}
_BLOCK_CODES = {4: 0, 8: 1, 12: 2, 16: 3, 15: 3}    # 15 = mSBC overload
_SUBBAND_CODES = {4: 0, 8: 1}
_MODE_CODES = {"mono": 0, "dual": 1, "stereo": 2, "joint_stereo": 3}
_ALLOC_CODES = {"loudness": 0, "snr": 1}


class LibsbcSBCEncoder:
    """libsbc-backed SBC encoder. Drop-in for the pure-Python SBCEncoder."""

    def __init__(
        self,
        *,
        sample_rate: int,
        channels: int,
        channel_mode: str,
        blocks: int,
        subbands: int,
        allocation: str,
        bitpool: int,
        syncword: int = 0x9C,
    ) -> None:
        # Same channel-count check as pure-Python path
        expected_ch = 1 if channel_mode == "mono" else 2
        if channels != expected_ch:
            raise ValueError(
                f"channel_mode={channel_mode!r} implies {expected_ch} channels, "
                f"got channels={channels}"
            )
        lib = _load()
        self._lib = lib
        self._sbc = _SbcStruct()
        if syncword == 0xAD:
            # mSBC preset: 16k mono blocks=15 subbands=8 loudness bitpool=26.
            # libsbc's sbc_init_msbc pins the right config and frame layout.
            if (sample_rate, channels, blocks, subbands, allocation, bitpool) != (
                16000, 1, 15, 8, "loudness", 26
            ):
                raise ValueError("mSBC syncword 0xAD requires the canonical mSBC config")
            rc = lib.sbc_init_msbc(ctypes.byref(self._sbc), 0)
        else:
            rc = lib.sbc_init(ctypes.byref(self._sbc), 0)
            if rc < 0:
                raise OSError(f"sbc_init failed: {rc}")
            self._sbc.frequency = _FREQ_CODES[sample_rate]
            self._sbc.blocks = _BLOCK_CODES[blocks]
            self._sbc.subbands = _SUBBAND_CODES[subbands]
            self._sbc.mode = _MODE_CODES[channel_mode]
            self._sbc.allocation = _ALLOC_CODES[allocation]
            self._sbc.bitpool = bitpool
            self._sbc.endian = 0   # LE
        if rc < 0:
            raise OSError(f"libsbc init failed: rc={rc}")
        self.sample_rate = sample_rate
        self.channels = channels
        self.channel_mode = channel_mode
        self.blocks = blocks
        self.subbands = subbands
        self.allocation = allocation
        self.bitpool = bitpool
        self._syncword = syncword
        self._codesize = lib.sbc_get_codesize(ctypes.byref(self._sbc))
        self._frame_size = lib.sbc_get_frame_length(ctypes.byref(self._sbc))

    @property
    def frame_size(self) -> int:
        return self._frame_size

    def encode(self, pcm_bytes: bytes) -> bytes:
        if len(pcm_bytes) != self._codesize:
            raise ValueError(
                f"pcm_bytes length {len(pcm_bytes)} doesn't match libsbc codesize "
                f"{self._codesize} (blocks={self.blocks}, subbands={self.subbands}, "
                f"channels={self.channels})"
            )
        out = ctypes.create_string_buffer(self._frame_size + 16)
        written = ctypes.c_ssize_t(0)
        rc = self._lib.sbc_encode(
            ctypes.byref(self._sbc),
            pcm_bytes, len(pcm_bytes),
            ctypes.cast(out, ctypes.c_void_p), len(out),
            ctypes.byref(written),
        )
        if rc < 0:
            raise OSError(f"sbc_encode failed: rc={rc}")
        frame = out.raw[:written.value]
        if self._syncword != 0x9C and len(frame) > 0:
            # libsbc emits 0xAD for mSBC, 0x9C for SBC; sync override is no-op
            # when init paths matched, but stays safe for custom future use.
            frame = bytes([self._syncword]) + frame[1:]
        return frame

    def __del__(self) -> None:
        try:
            if self._sbc.priv:
                self._lib.sbc_finish(ctypes.byref(self._sbc))
        except Exception:
            pass


class LibsbcSBCDecoder:
    """libsbc-backed SBC decoder. Drop-in for the pure-Python SBCDecoder.

    Pass `msbc=True` to initialize the decoder in mSBC mode (HFP wide-band
    speech). libsbc requires the msbc init path for 0xAD-syncword frames.
    """

    def __init__(self, *, msbc: bool = False) -> None:
        lib = _load()
        self._lib = lib
        self._sbc = _SbcStruct()
        if msbc:
            rc = lib.sbc_init_msbc(ctypes.byref(self._sbc), 0)
        else:
            rc = lib.sbc_init(ctypes.byref(self._sbc), 0)
        if rc < 0:
            raise OSError(f"sbc_init{'_msbc' if msbc else ''} failed: {rc}")
        self._msbc = msbc

    def decode(self, data: bytes) -> tuple[bytes, int]:
        if len(data) < 4 or data[0] not in (0x9C, 0xAD):
            raise ValueError(
                f"SBC syncword 0x9C / 0xAD not found at byte 0 (got {data[:1].hex()})"
            )
        # libsbc parses header on its own; just feed frames sequentially.
        pcm_chunks: list[bytes] = []
        consumed = 0
        out = ctypes.create_string_buffer(8192)
        written = ctypes.c_size_t(0)
        while consumed < len(data):
            remaining = len(data) - consumed
            if remaining < 4:
                break
            rc = self._lib.sbc_decode(
                ctypes.byref(self._sbc),
                ctypes.c_char_p(data[consumed:]), remaining,
                ctypes.cast(out, ctypes.c_void_p), len(out),
                ctypes.byref(written),
            )
            if rc <= 0:
                break
            pcm_chunks.append(out.raw[:written.value])
            consumed += rc
        if consumed == 0:
            raise ValueError("no complete SBC frame found in input")
        return b"".join(pcm_chunks), consumed

    def __del__(self) -> None:
        try:
            if self._sbc.priv:
                self._lib.sbc_finish(ctypes.byref(self._sbc))
        except Exception:
            pass


def is_available() -> bool:
    """Returns True if libsbc.so.1 can be loaded."""
    try:
        _load()
        return True
    except ImportError:
        return False
