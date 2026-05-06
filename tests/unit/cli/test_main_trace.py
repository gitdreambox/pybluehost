"""Tests for top-level --trace CLI option."""
from __future__ import annotations

import pytest

from pybluehost.cli import main


def test_main_help_shows_trace_option(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "--trace" in out


def test_main_invalid_trace_spec_exits_nonzero(monkeypatch, capsys):
    monkeypatch.delenv("PYBLUEHOST_TRACE", raising=False)
    rc = main(["--trace=invalid_layer", "tools", "decode", "01030c00"])
    # Should fail before/at decode; CLI returns non-zero (exact code = 4 from
    # explicit InvalidTraceSpec handling).
    assert rc != 0


def test_main_trace_env_var_works(monkeypatch, capsys):
    monkeypatch.setenv("PYBLUEHOST_TRACE", "")
    rc = main(["tools", "decode", "01030c00"])
    assert rc == 0  # tools decode is offline, no trace impact
