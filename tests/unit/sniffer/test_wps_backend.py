import ctypes
from datetime import datetime, timezone

import pytest

from pybluehost.core.trace import Direction
from pybluehost.sniffer.wps import LiveImportLibrary, WpsBackend


class _FakeLib:
    """Stand-in for ctypes.CDLL(LiveImportAPI.dll) — records calls."""
    def __init__(self) -> None:
        self.initialize_calls = []
        self.send_frame_calls = []
        self.send_notification_calls = []
        self._initialize_hresult = 0   # 0 = success
        self._send_frame_hresult = 0
        self._is_app_ready = True

    def InitializeLiveImportEx(self, conn, cfg, success_ptr, mode):
        self.initialize_calls.append((conn, cfg, mode))
        success_ptr._obj.value = True
        return self._initialize_hresult

    def SendFrame3(self, length1, length2, buf, drf, stream, ts):
        payload = bytes(buf[:length1])
        self.send_frame_calls.append({
            "len": length1, "drf": drf, "stream": stream, "ts": ts, "payload": payload,
        })
        return self._send_frame_hresult

    def SendNotification(self, code):
        self.send_notification_calls.append(code)
        return 0

    def IsAppReady(self, ptr):
        ptr._obj.value = self._is_app_ready
        return 0


def test_live_import_library_accepts_injected_dll():
    fake = _FakeLib()
    lib = LiveImportLibrary(fake, connection_string="cs", config_string="cfg")
    assert lib.connection_string == "cs"
    assert lib.config_string == "cfg"


async def test_wps_backend_start_calls_initialize_and_start_capture():
    fake = _FakeLib()
    lib = LiveImportLibrary(fake, connection_string="cs", config_string="cfg")
    backend = WpsBackend(library=lib)
    await backend.start()
    assert len(fake.initialize_calls) == 1
    assert fake.initialize_calls[0][0] == b"cs"
    assert fake.initialize_calls[0][1] == b"cfg"
    # SendNotification(E_START_CAPTURE_TO_FILE=6) issued once
    assert 6 in fake.send_notification_calls


async def test_wps_backend_inject_command_uses_drf_1_stream_0():
    fake = _FakeLib()
    lib = LiveImportLibrary(fake, connection_string="cs", config_string="cfg")
    backend = WpsBackend(library=lib)
    await backend.start()
    wall = datetime(2026, 1, 15, 0, 0, 1, 0, tzinfo=timezone.utc)
    await backend.inject(
        h4_type=0x01, direction=Direction.DOWN,
        payload=bytes.fromhex("03 0C 00"), wall_clock=wall,
    )
    assert len(fake.send_frame_calls) == 1
    call = fake.send_frame_calls[0]
    assert call["drf"] == 1            # DRF_COMMAND
    assert call["stream"] == 0         # STREAM_HOST
    assert call["payload"] == bytes.fromhex("03 0C 00")
    assert call["ts"] == int(wall.timestamp() * 1e9)


async def test_wps_backend_skips_iso_and_warns_once(caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="pybluehost.sniffer.wps")
    fake = _FakeLib()
    lib = LiveImportLibrary(fake, connection_string="cs", config_string="cfg")
    backend = WpsBackend(library=lib)
    await backend.start()
    wall = datetime(2026, 1, 15, tzinfo=timezone.utc)
    await backend.inject(h4_type=0x05, direction=Direction.DOWN, payload=b"\x01", wall_clock=wall)
    await backend.inject(h4_type=0x05, direction=Direction.UP,   payload=b"\x02", wall_clock=wall)
    assert fake.send_frame_calls == []   # ISO skipped
    iso_warnings = [r for r in caplog.records if "ISO" in r.getMessage()]
    assert len(iso_warnings) == 1
