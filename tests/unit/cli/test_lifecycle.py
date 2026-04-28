import asyncio
from datetime import datetime, timezone

import pytest
from pybluehost.cli._lifecycle import run_app_command
from pybluehost.core.trace import Direction, TraceEvent


async def test_run_app_command_completes_normally():
    async def main(stack, stop):
        return

    code = await run_app_command("virtual", main)
    assert code == 0


async def test_run_app_command_returns_when_main_finishes():
    """If main returns before stop_event fires, exit 0."""
    async def main(stack, stop):
        # Just returns immediately
        return

    code = await run_app_command("virtual", main)
    assert code == 0


async def test_run_app_command_propagates_error():
    async def main(stack, stop):
        raise RuntimeError("boom")

    code = await run_app_command("virtual", main)
    assert code == 1


async def test_run_app_command_invalid_transport():
    async def main(stack, stop):
        return

    code = await run_app_command("bogus", main)
    assert code == 1


async def test_run_app_command_hci_log_prints_trace_events(capsys):
    async def main(stack, stop):
        stack.trace.emit(
            TraceEvent(
                timestamp=0.0,
                wall_clock=datetime.now(timezone.utc),
                source_layer="hci",
                direction=Direction.DOWN,
                raw_bytes=b"\x01\x03\x0c\x00",
                decoded=None,
                connection_handle=None,
                metadata={},
            )
        )
        stack.trace.emit(
            TraceEvent(
                timestamp=0.0,
                wall_clock=datetime.now(timezone.utc),
                source_layer="hci",
                direction=Direction.UP,
                raw_bytes=b"\x04\x0e\x04\x01\x03\x0c\x00",
                decoded=None,
                connection_handle=None,
                metadata={},
            )
        )

    code = await run_app_command("virtual", main, hci_log=True)
    captured = capsys.readouterr()

    assert code == 0
    assert "[HCI TX] 01 03 0c 00" in captured.err
    assert "[HCI RX] 04 0e 04 01 03 0c 00" in captured.err


async def test_run_app_command_btsnoop_writes_hci_packets(tmp_path):
    path = tmp_path / "hci.cfa"

    async def main(stack, stop):
        stack.trace.emit(
            TraceEvent(
                timestamp=0.0,
                wall_clock=datetime.now(timezone.utc),
                source_layer="hci",
                direction=Direction.DOWN,
                raw_bytes=b"\x01\x03\x0c\x00",
                decoded=None,
                connection_handle=None,
                metadata={},
            )
        )

    code = await run_app_command("virtual", main, btsnoop=path)

    assert code == 0
    data = path.read_bytes()
    assert data[:16] == b"btsnoop\x00\x00\x00\x00\x01\x00\x00\x03\xea"
    assert b"\x01\x03\x0c\x00" in data
