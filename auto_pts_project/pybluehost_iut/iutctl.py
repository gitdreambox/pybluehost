"""IUT control for autoptsclient — synchronous contract matching auto-pts master.

Current upstream ``autoptsclient`` drives the IUT through three module-level
functions plus a control class:

- ``init(args)``      — build the IUT controller (called once at session start)
- ``get_iut()``       — return the controller instance
- ``cleanup()``       — tear down (called once at session end)

and, per test case, ``controller.start(test_case)`` /
``controller.wait_iut_ready_event()`` / ``controller.stop()``.

This replaces the earlier ``async iut_init/iut_cleanup`` design, which assumed
PyBlueHost pts-tester was the BTP *server*.  In the current auto-pts model the
client (autoptsclient, via ``BTPSocketSrv``) listens and the IUT connects OUT,
so we spawn ``pybluehost app pts-tester --connect host:port`` and accept its
connection here.

All ``autopts.*`` imports are deferred into the methods that need them so the
module imports cleanly on a host without autoptsclient installed (PyBlueHost
CI, ``--help`` sanity).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Any

log = logging.debug
logger = logging.getLogger(__name__)

# Module-level state — autoptsclient runs one IUT at a time.
IUT: "PyBlueHostIutCtl | None" = None
IUT_LOG_FO: Any = None

# Default PyBlueHost transport for the spawned pts-tester. Overridable via the
# ``--pybluehost-transport`` CLI flag. BE200 — see the IUT-address note in
# ixit.py: it is the only dongle with the subrate and ISO command families.
DEFAULT_TRANSPORT = "usb:8087:0036#1"


def get_iut() -> "PyBlueHostIutCtl | None":
    return IUT


def init(args: Any) -> None:
    """IUT init routine — called by ``Client.init_iutctl`` with parsed args."""
    global IUT, IUT_LOG_FO
    IUT_LOG_FO = open("iut-pybluehost.log", "w", encoding="utf-8")
    IUT = PyBlueHostIutCtl(args)


def cleanup() -> None:
    """IUT cleanup routine. Idempotent."""
    global IUT, IUT_LOG_FO
    if IUT is not None:
        IUT.stop()
        IUT = None
    if IUT_LOG_FO is not None:
        try:
            IUT_LOG_FO.close()
        except Exception:
            pass
        IUT_LOG_FO = None


class PyBlueHostIutCtl:
    """IUT Control: owns the autopts Stack model and the pts-tester subprocess."""

    def __init__(self, args: Any) -> None:
        from autopts.ptsprojects.stack import Stack

        self.transport = getattr(args, "pybluehost_transport", None) or DEFAULT_TRANSPORT
        self.btp_socket = None
        self.socket_srv = None
        self.iut_process: subprocess.Popen | None = None

        self.stack = Stack()
        self.stack.synch_init()

    def start(self, test_case: Any) -> None:
        """Open the BTP server socket, spawn pts-tester connecting OUT, accept it."""
        from autopts.pybtp.iutctl_common import BTP_ADDRESS, BTPSocketSrv, BTPWorker

        self.socket_srv = BTPSocketSrv(test_case.log_dir)
        # On win32 BTPSocketSrv.open binds an ephemeral TCP port on the hostname;
        # BTP_ADDRESS (a unix path) is ignored.
        self.socket_srv.open(BTP_ADDRESS)
        self.btp_socket = BTPWorker(self.socket_srv)

        host, port = self.socket_srv.sock.getsockname()[:2]

        # Optional diagnosis knob: PYBLUEHOST_IUT_LOG_LEVEL=DEBUG raises the
        # spawned pts-tester's log verbosity (top-level --log-level must precede
        # the `app` subcommand) so the SMP/HCI PDU exchange lands in
        # iut-pybluehost.log. PYBLUEHOST_TRACE=<layer>=debug also works.
        iut_log_level = os.environ.get("PYBLUEHOST_IUT_LOG_LEVEL")
        level_args = ["--log-level", iut_log_level] if iut_log_level else []
        # Optional HCI capture: PYBLUEHOST_IUT_BTSNOOP=path.cfa writes an IUT-side
        # btsnoop so the over-the-air pairing exchange + disconnect initiator can
        # be inspected in Wireshark.
        iut_btsnoop = os.environ.get("PYBLUEHOST_IUT_BTSNOOP")
        snoop_args = ["--btsnoop", iut_btsnoop] if iut_btsnoop else []
        cmd = [
            sys.executable, "-m", "pybluehost", *level_args,
            "app", "pts-tester",
            "-t", self.transport,
            f"--connect={host}:{port}",
            *snoop_args,
        ]
        logger.info("PyBlueHostIutCtl.start: spawning %s", " ".join(cmd))
        self.iut_process = subprocess.Popen(
            cmd, stdout=IUT_LOG_FO, stderr=subprocess.STDOUT,
        )

        try:
            self.btp_socket.accept()
        except TimeoutError:
            logger.error("IUT (pts-tester) did not connect to BTP socket")
            self.stop()

    def wait_iut_ready_event(self) -> None:
        """Block until the IUT sends the Core IUT_READY event after power-up.

        NOTE: must be called *before* any ``stack.core_init()``/BTP command so the
        READY event is still queued on the BTPWorker rx queue.
        """
        from autopts.pybtp import defs
        from autopts.pybtp.types import BTPError, BTPInitError

        tuple_hdr, _tuple_data = self.btp_socket.read()
        try:
            if (tuple_hdr.svc_id != defs.BTP_SERVICE_ID_CORE
                    or tuple_hdr.op != defs.BTP_CORE_EV_IUT_READY):
                raise BTPInitError("Failed to get ready event")
        except BTPError as err:
            logger.error("Unexpected event (%s), expected IUT ready!", err)
            self.stop()
        else:
            logger.info("IUT ready event received OK")

    def stop(self) -> None:
        """Tear down the BTP socket and the pts-tester subprocess."""
        if self.btp_socket is not None:
            try:
                self.btp_socket.close()
            except Exception:
                logger.exception("btp_socket close failed")
            self.btp_socket = None

        if self.iut_process is not None and self.iut_process.poll() is None:
            try:
                self.iut_process.terminate()
                self.iut_process.wait(timeout=5.0)
            except Exception:
                try:
                    self.iut_process.kill()
                except Exception:
                    pass
            self.iut_process = None

    def get_stack(self) -> Any:
        return self.stack
