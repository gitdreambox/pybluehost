"""IUT control hooks for autoptsclient.

autoptsclient calls ``iut_init`` at session start and ``iut_cleanup`` at end.
Between them, autoptsclient TCP-connects to the BTP tester port.

This module spawns ``pybluehost app pts-tester`` as a subprocess and waits
for the BTP READY event before returning from ``iut_init``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from typing import Any

logger = logging.getLogger(__name__)

# Module-level state — autoptsclient runs one IUT subprocess at a time.
_subprocess: subprocess.Popen | None = None


async def iut_init(ctx: dict[str, Any]) -> None:
    """Spawn ``pybluehost app pts-tester`` and wait until it's listening.

    ``ctx`` carries autoptsclient run-time options. We read:
      - ``ctx["listen"]``: ``host:port`` the tester should listen on
                           (default ``"127.0.0.1:65103"``)
      - ``ctx["transport"]``: PyBlueHost transport spec
                              (default ``"virtual"``; real PTS run uses ``"usb"``)
    """
    global _subprocess
    listen = ctx.get("listen", "127.0.0.1:65103")
    transport = ctx.get("transport", "virtual")

    cmd = [
        sys.executable, "-m", "pybluehost", "app", "pts-tester",
        "-t", transport,
        f"--listen={listen}",
    ]
    logger.info("iut_init: spawning %s", " ".join(cmd))
    _subprocess = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        cwd=os.getcwd(),
    )

    # Wait for the tester to accept a TCP connection AND emit the BTP READY event.
    host, port_str = listen.rsplit(":", 1)
    port = int(port_str)
    deadline = asyncio.get_event_loop().time() + 30.0
    while True:
        if asyncio.get_event_loop().time() > deadline:
            # Best-effort cleanup before raising.
            try:
                _subprocess.terminate()
            except Exception:
                pass
            raise RuntimeError(
                f"iut_init: pts-tester did not become ready on {listen} within 30 s"
            )
        try:
            reader, writer = await asyncio.open_connection(host, port)
        except OSError:
            await asyncio.sleep(0.2)
            continue
        try:
            header = await asyncio.wait_for(reader.readexactly(5), timeout=2.0)
            if header[0] == 0x00 and header[1] >= 0x80:
                logger.info("iut_init: tester ready, READY event received")
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
                return
        except (asyncio.TimeoutError, OSError, asyncio.IncompleteReadError):
            pass
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        await asyncio.sleep(0.2)


async def iut_cleanup(ctx: dict[str, Any]) -> None:
    """Tear down the IUT subprocess. Idempotent."""
    global _subprocess
    if _subprocess is None:
        return
    proc = _subprocess
    _subprocess = None
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                logger.warning("iut_cleanup: subprocess did not exit after kill")
    except Exception:
        logger.exception("iut_cleanup: subprocess teardown failed")


def iut_log(*args: Any, **kwargs: Any) -> None:
    """Logging integration hook called by autoptsclient at run-time."""
    msg = " ".join(str(a) for a in args)
    logger.info("autoptsclient: %s", msg)
