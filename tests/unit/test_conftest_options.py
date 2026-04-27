"""pytest CLI options registered by tests/conftest.py."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_help_shows_transport_options() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.pop("PYBLUEHOST_TEST_TRANSPORT", None)
    env.pop("PYBLUEHOST_TEST_TRANSPORT_PEER", None)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--help"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "--transport" in result.stdout
    assert "--transport-peer" in result.stdout
    assert "--list-transports" in result.stdout
