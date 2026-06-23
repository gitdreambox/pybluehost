"""IUT control hooks — autoptsclient surface compliance + subprocess lifecycle."""
import asyncio
import socket

import pytest


def _alloc_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    _, port = s.getsockname()
    s.close()
    return port


def test_iutctl_module_has_required_surface():
    """autoptsclient discovery hook check."""
    from auto_pts_project.pybluehost import iutctl
    assert callable(getattr(iutctl, "iut_init", None))
    assert callable(getattr(iutctl, "iut_cleanup", None))
    assert callable(getattr(iutctl, "iut_log", None))


def test_iutctl_project_name_is_pybluehost():
    from auto_pts_project import pybluehost
    assert pybluehost.PROJECT_NAME == "pybluehost"


@pytest.mark.asyncio
async def test_iutctl_init_spawns_pts_tester_and_waits_ready():
    """iut_init blocks until the tester is listening and has emitted READY."""
    from auto_pts_project.pybluehost import iutctl

    port = _alloc_port()
    ctx = {"listen": f"127.0.0.1:{port}", "transport": "virtual"}
    try:
        await iutctl.iut_init(ctx)
        # After init returns, we should be able to TCP-connect.
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        header = await asyncio.wait_for(reader.readexactly(5), timeout=2.0)
        assert header[0] == 0x00          # Service ID = Core
        assert header[1] >= 0x80          # Event opcode range
        writer.close()
        await writer.wait_closed()
    finally:
        await iutctl.iut_cleanup(ctx)


@pytest.mark.asyncio
async def test_iutctl_cleanup_kills_subprocess():
    from auto_pts_project.pybluehost import iutctl

    port = _alloc_port()
    ctx = {"listen": f"127.0.0.1:{port}", "transport": "virtual"}
    await iutctl.iut_init(ctx)
    await iutctl.iut_cleanup(ctx)
    # Port should free up (give the OS a moment).
    await asyncio.sleep(0.5)
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.close()


@pytest.mark.asyncio
async def test_iutctl_cleanup_idempotent_without_init():
    """Calling cleanup before init shouldn't raise."""
    from auto_pts_project.pybluehost import iutctl
    await iutctl.iut_cleanup({})


def test_iutctl_log_doesnt_raise():
    from auto_pts_project.pybluehost import iutctl
    iutctl.iut_log("test", "message")
