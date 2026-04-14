import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pybluehost.core.trace import BtsnoopSink, Direction, TraceEvent
from pybluehost.transport.btsnoop import BtsnoopTransport


class _Collect:
    def __init__(self) -> None:
        self.received: list[bytes] = []

    async def on_data(self, data: bytes) -> None:
        self.received.append(data)


async def _write_btsnoop_async(path: Path, payloads: list[tuple[bytes, float]]) -> None:
    sink = BtsnoopSink(str(path))
    for payload, ts in payloads:
        wall = datetime.fromtimestamp(ts, tz=timezone.utc)
        await sink.on_trace(TraceEvent(
            timestamp=0.0,
            wall_clock=wall,
            source_layer="hci",
            direction=Direction.UP,
            raw_bytes=payload,
            decoded=None,
            connection_handle=None,
            metadata={},
        ))
    await sink.flush()
    await sink.close()


class TestBtsnoopTransport:
    @pytest.mark.asyncio
    async def test_replays_records_in_order(self, tmp_path: Path):
        path = tmp_path / "cap.cfa"
        p1 = bytes.fromhex("040e0401030c00")
        p2 = bytes.fromhex("01030c00")
        await _write_btsnoop_async(path, [(p1, 1700000000.0), (p2, 1700000000.1)])

        sink = _Collect()
        t = BtsnoopTransport(str(path))
        t.set_sink(sink)
        await t.open()
        # Wait for replay task to finish draining the file
        for _ in range(50):
            if len(sink.received) == 2:
                break
            await asyncio.sleep(0.01)
        await t.close()
        assert sink.received == [p1, p2]

    @pytest.mark.asyncio
    async def test_send_is_silently_dropped(self, tmp_path: Path):
        path = tmp_path / "empty.cfa"
        await _write_btsnoop_async(path, [])

        t = BtsnoopTransport(str(path))
        await t.open()
        await t.send(b"ignored")  # no error
        await t.close()

    @pytest.mark.asyncio
    async def test_rejects_invalid_magic(self, tmp_path: Path):
        path = tmp_path / "bad.cfa"
        path.write_bytes(b"NOTBTSNOOP" + b"\x00" * 10)
        t = BtsnoopTransport(str(path))
        await t.open()
        for _ in range(20):
            await asyncio.sleep(0.01)
            if t._replay_task is not None and t._replay_task.done():  # noqa: SLF001
                break
        # Replay task should have raised — confirm it's done and has an exception
        assert t._replay_task is not None  # noqa: SLF001
        assert t._replay_task.done()  # noqa: SLF001
        exc = t._replay_task.exception()  # noqa: SLF001
        assert isinstance(exc, ValueError) and "btsnoop" in str(exc)
        await t.close()

    @pytest.mark.asyncio
    async def test_realtime_sleeps_between_records(self, tmp_path: Path):
        path = tmp_path / "timed.cfa"
        p1 = bytes.fromhex("01030c00")
        p2 = bytes.fromhex("040e0401030c00")
        # 0.1s apart
        await _write_btsnoop_async(path, [(p1, 1700000000.0), (p2, 1700000000.1)])

        sink = _Collect()
        t = BtsnoopTransport(str(path), realtime=True)
        t.set_sink(sink)
        start = asyncio.get_running_loop().time()
        await t.open()
        for _ in range(50):
            if len(sink.received) == 2:
                break
            await asyncio.sleep(0.02)
        elapsed = asyncio.get_running_loop().time() - start
        await t.close()
        assert sink.received == [p1, p2]
        assert elapsed >= 0.08  # allow some scheduler slop under 0.1s target

    @pytest.mark.asyncio
    async def test_info(self, tmp_path: Path):
        path = tmp_path / "any.cfa"
        await _write_btsnoop_async(path, [])
        t = BtsnoopTransport(str(path))
        assert t.info.type == "btsnoop"
        assert t.info.details["path"] == str(path)
        assert t.info.details["realtime"] is False
