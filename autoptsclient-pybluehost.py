#!/usr/bin/env python
"""PyBlueHost auto-PTS client entry point.

Drives PyBlueHost as a PTS IUT under the current auto-pts master contract.
Run from the repository root (or anywhere with the repo on PYTHONPATH) with
autoptsclient installed:

    python autoptsclient-pybluehost.py -i <pts-server-ip> -l <local-ip> \
        --pybluehost-transport usb:0A12:0001#1 -c GAP/CONN/UCON/BV-06-C

autoptsclient is the BTP *server*; this client spawns ``pybluehost app
pts-tester --connect <host>:<port>`` (via ``pybluehost_iut.iutctl``) which dials
OUT to the auto-pts BTPSocketSrv.
"""
import importlib
import os
import sys

# Make ``auto_pts_project`` importable when invoked from outside the repo root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# autopts.client does ``from cliparser import CliParser``; cliparser.py lives at the
# auto-pts repo ROOT, which a PEP 660 editable install does NOT expose. Add the
# repo root (parent of the autopts package) to sys.path so cliparser resolves.
import autopts  # noqa: E402

_AUTOPTS_FILE = getattr(autopts, "__file__", None)  # absent in stubbed unit tests
if _AUTOPTS_FILE:
    _AUTOPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(_AUTOPTS_FILE)))
    if _AUTOPTS_ROOT not in sys.path:
        sys.path.insert(0, _AUTOPTS_ROOT)

from autopts.client import Client, CliParser  # noqa: E402

from auto_pts_project.pybluehost_iut import PROJECT_NAME, iutctl  # noqa: E402


class PyBlueHostCliParser(CliParser):
    """CliParser with a PyBlueHost transport flag for the spawned pts-tester."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # PyBlueHost is a self-spawning BTP IUT (the bluez "btpclient_path" model):
        # our iutctl opens the BTPSocketSrv and spawns pts-tester itself, so we
        # select that IUT mode. btpclient_path is defaulted to the interpreter only
        # to satisfy the mode's existence check — our iutctl never executes it.
        self.set_defaults(btpclient_path=[sys.executable])
        self.add_argument(
            "--pybluehost-transport", "--pybluehost_transport", type=str, default=None,
            help="PyBlueHost transport for the spawned pts-tester, "
                 "e.g. 'usb:0A12:0001#1' (default: CSR8510 dongle).",
        )


class PyBlueHostClient(Client):
    def __init__(self):
        project = importlib.import_module("auto_pts_project.pybluehost_iut")
        super().__init__(
            iutctl.get_iut, project, PROJECT_NAME,
            parser_class=PyBlueHostCliParser,
        )


def main():
    # Resolve any relative .pqw6 workspace path to an absolute Windows path.
    # autoptsserver opens the workspace relative to its own CWD; when it is
    # launched from a WSL shell the relative path fails with HRESULT 0x849C0005.
    for i, arg in enumerate(sys.argv[1:], start=1):
        if not arg.startswith("-") and arg.lower().endswith(".pqw6"):
            abs_path = os.path.abspath(arg)
            if abs_path != arg:
                sys.argv[i] = abs_path
            break
    client = PyBlueHostClient()
    client.start()


if __name__ == "__main__":
    main()
