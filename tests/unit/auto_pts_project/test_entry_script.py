"""autoptsclient-pybluehost.py — entry-script structure.

Full ``--help`` requires autoptsclient installed (a Phase B deployment step), so
these tests stub ``autopts.client`` to validate the wiring offline and skip the
real end-to-end parser run when autopts is absent.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ENTRY = Path(__file__).resolve().parents[3] / "autoptsclient-pybluehost.py"


def _load_entry(monkeypatch):
    """Import the entry script with a stubbed autopts.client."""
    client_mod = types.ModuleType("autopts.client")

    class CliParser:
        def __init__(self, *args, **kwargs):
            self._extra = []
            self._defaults = {}

        def add_argument(self, *args, **kwargs):
            self._extra.append((args, kwargs))

        def set_defaults(self, **kwargs):
            self._defaults.update(kwargs)

    class Client:
        def __init__(self, get_iut, project, name, parser_class=None):
            self.get_iut = get_iut
            self.project = project
            self.name = name
            self.parser_class = parser_class

    client_mod.CliParser = CliParser
    client_mod.Client = Client
    monkeypatch.setitem(sys.modules, "autopts", types.ModuleType("autopts"))
    monkeypatch.setitem(sys.modules, "autopts.client", client_mod)

    spec = importlib.util.spec_from_file_location("autoptsclient_pybluehost", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_entry_defines_client_and_parser(monkeypatch):
    module = _load_entry(monkeypatch)
    assert hasattr(module, "PyBlueHostClient")
    assert hasattr(module, "PyBlueHostCliParser")


def test_client_uses_pybluehost_project_and_parser(monkeypatch):
    module = _load_entry(monkeypatch)
    client = module.PyBlueHostClient()
    assert client.name == "pybluehost_iut"
    assert client.parser_class is module.PyBlueHostCliParser
    # get_iut is our iutctl's hook.
    from auto_pts_project.pybluehost_iut import iutctl
    assert client.get_iut is iutctl.get_iut


def test_parser_adds_transport_flag(monkeypatch):
    module = _load_entry(monkeypatch)
    parser = module.PyBlueHostCliParser()
    flags = [a for args, _ in parser._extra for a in args]
    assert "--pybluehost-transport" in flags


def test_entry_help_runs_when_autopts_installed():
    """End-to-end --help; only meaningful with autoptsclient installed."""
    pytest.importorskip("autopts.client", reason="autoptsclient not installed (Phase B)")
    import subprocess
    result = subprocess.run(
        [sys.executable, str(ENTRY), "--help"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    assert "--pybluehost-transport" in result.stdout
