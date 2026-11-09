"""iutctl — sync autoptsclient contract (init/cleanup/get_iut + PyBlueHostIutCtl).

autopts is not installed in PyBlueHost CI, so these tests stub the autopts
module tree in sys.modules and patch subprocess.Popen to avoid spawning a real
pts-tester.
"""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest


@pytest.fixture
def fake_autopts(monkeypatch):
    """Install a minimal fake autopts.* module tree."""
    stack_mod = types.ModuleType("autopts.ptsprojects.stack")
    iutctl_common = types.ModuleType("autopts.pybtp.iutctl_common")
    defs = types.ModuleType("autopts.pybtp.defs")
    types_mod = types.ModuleType("autopts.pybtp.types")

    class FakeStack:
        def __init__(self):
            self.synced = False

        def synch_init(self):
            self.synced = True

    stack_mod.Stack = FakeStack

    class BTPError(Exception):
        pass

    class BTPInitError(BTPError):
        pass

    types_mod.BTPError = BTPError
    types_mod.BTPInitError = BTPInitError

    defs.BTP_SERVICE_ID_CORE = 0x00
    defs.BTP_CORE_EV_IUT_READY = 0x80

    class _FakeSock:
        def getsockname(self):
            return ("127.0.0.1", 43210)

    class BTPSocketSrv:
        def __init__(self, log_dir=None):
            self.log_dir = log_dir
            self.sock = _FakeSock()
            self.opened = False

        def open(self, address, port=0):
            self.opened = True

    class BTPWorker:
        def __init__(self, sock):
            self._socket = sock
            self.closed = False

        def accept(self, timeout=10.0):
            pass

        def read(self, timeout=20.0):
            hdr = SimpleNamespace(
                svc_id=defs.BTP_SERVICE_ID_CORE, op=defs.BTP_CORE_EV_IUT_READY,
            )
            return hdr, None

        def close(self):
            self.closed = True

    iutctl_common.BTP_ADDRESS = "/tmp/bt-stack-tester"
    iutctl_common.BTPSocketSrv = BTPSocketSrv
    iutctl_common.BTPWorker = BTPWorker

    for name, mod in {
        "autopts": types.ModuleType("autopts"),
        "autopts.ptsprojects": types.ModuleType("autopts.ptsprojects"),
        "autopts.ptsprojects.stack": stack_mod,
        "autopts.pybtp": types.ModuleType("autopts.pybtp"),
        "autopts.pybtp.iutctl_common": iutctl_common,
        "autopts.pybtp.defs": defs,
        "autopts.pybtp.types": types_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    return SimpleNamespace(defs=defs, BTPSocketSrv=BTPSocketSrv, BTPWorker=BTPWorker)


@pytest.fixture
def popen_spy(monkeypatch):
    """Patch subprocess.Popen inside iutctl and record invocations."""
    from auto_pts_project.pybluehost_iut import iutctl

    calls = []

    class _FakeProc:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.kwargs = kwargs
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    def _popen(cmd, **kwargs):
        proc = _FakeProc(cmd, **kwargs)
        calls.append(proc)
        return proc

    monkeypatch.setattr(iutctl.subprocess, "Popen", _popen)
    return calls


def _args(**over):
    base = {"pybluehost_transport": "usb:0A12:0001#1"}
    base.update(over)
    return SimpleNamespace(**base)


def test_module_surface_is_sync_contract(fake_autopts):
    from auto_pts_project.pybluehost_iut import iutctl

    assert callable(iutctl.init)
    assert callable(iutctl.cleanup)
    assert callable(iutctl.get_iut)
    # The old async hooks must be gone.
    assert not hasattr(iutctl, "iut_init")
    assert not hasattr(iutctl, "iut_cleanup")


def test_init_builds_iut_with_synced_autopts_stack(fake_autopts, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # keep the iut-pybluehost.log out of the repo
    from auto_pts_project.pybluehost_iut import iutctl

    iutctl.init(_args())
    iut = iutctl.get_iut()
    assert iut is not None
    assert iut.stack.synced is True
    assert iut.get_stack() is iut.stack
    assert iut.transport == "usb:0A12:0001#1"
    iutctl.cleanup()
    assert iutctl.get_iut() is None


def test_transport_default_when_arg_missing(fake_autopts, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from auto_pts_project.pybluehost_iut import iutctl

    iutctl.init(SimpleNamespace())  # no pybluehost_transport attribute
    assert iutctl.get_iut().transport == iutctl.DEFAULT_TRANSPORT
    iutctl.cleanup()


def test_start_spawns_pts_tester_connecting_out(fake_autopts, popen_spy, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from auto_pts_project.pybluehost_iut import iutctl

    iutctl.init(_args())
    iut = iutctl.get_iut()
    test_case = SimpleNamespace(log_dir=str(tmp_path))
    iut.start(test_case)

    assert len(popen_spy) == 1
    cmd = popen_spy[0].cmd
    assert cmd[:5] == [sys.executable, "-m", "pybluehost", "app", "pts-tester"]
    assert "--connect=127.0.0.1:43210" in cmd
    iutctl.cleanup()


def test_wait_iut_ready_event_consumes_ready(fake_autopts, popen_spy, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from auto_pts_project.pybluehost_iut import iutctl

    iutctl.init(_args())
    iut = iutctl.get_iut()
    iut.start(SimpleNamespace(log_dir=str(tmp_path)))
    # Should not raise — the fake BTPWorker returns a Core READY event.
    iut.wait_iut_ready_event()
    iutctl.cleanup()


def test_stop_terminates_subprocess_and_closes_socket(fake_autopts, popen_spy, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from auto_pts_project.pybluehost_iut import iutctl

    iutctl.init(_args())
    iut = iutctl.get_iut()
    iut.start(SimpleNamespace(log_dir=str(tmp_path)))
    proc = popen_spy[0]
    worker = iut.btp_socket

    iut.stop()
    assert proc.terminated is True
    assert worker.closed is True
    assert iut.iut_process is None
    assert iut.btp_socket is None
    iutctl.cleanup()


def test_cleanup_idempotent(fake_autopts):
    from auto_pts_project.pybluehost_iut import iutctl

    iutctl.cleanup()  # before init — must not raise
    iutctl.cleanup()
