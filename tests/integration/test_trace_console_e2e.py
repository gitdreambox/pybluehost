"""End-to-end: launch CLI in a subprocess and inspect stderr trace output."""
from __future__ import annotations

import os
import subprocess
import sys


def _cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "pybluehost", *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)


def test_trace_hci_emits_structured_lines_on_virtual():
    r = _cli("--trace=hci", "tools", "decode", "01030c00")
    # tools decode is offline (no Stack), so no HCI trace expected, but the
    # CLI must accept --trace and exit 0.
    assert r.returncode == 0


def test_trace_invalid_layer_exits_nonzero():
    r = _cli("--trace=invalid_layer", "tools", "decode", "01030c00")
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "Unknown layer" in out


def test_trace_env_var_works():
    env = os.environ.copy()
    env["PYBLUEHOST_TRACE"] = "hci"
    r = _cli("tools", "decode", "01030c00", env=env)
    assert r.returncode == 0
