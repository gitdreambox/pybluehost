"""PyBlueHost auto-pts project module.

When autoptsclient is configured for the ``pybluehost_iut`` project it imports
this package and drives it through the auto-pts master contract:

- ``iutctl.init(args)`` / ``iutctl.cleanup()`` / ``iutctl.get_iut()``
- ``getattr(pkg, '<profile>').set_pixits(ptses)`` / ``.test_cases(ptses)`` for
  each profile the PTS workspace enables (``gap``, ``gatt``, ``l2cap``, ``sm``).

The ``_iut`` suffix disambiguates this plugin folder from the protocol-stack
package (``pybluehost``) on sys.path — both directories sit on disk under the
same repo, and a bare ``import pybluehost`` from autoptsclient must always
resolve to the stack, not this plugin.

Profile submodules import autopts at load time, so they are resolved lazily via
module ``__getattr__`` (PEP 562): ``getattr(pkg, 'gap')`` imports
``pybluehost_iut.gap`` on demand. This keeps ``import pybluehost_iut`` cheap and
importable without autoptsclient installed (PyBlueHost CI), while still making
``getattr(autoprojects, profile)`` work for autoptsclient at run time.

See README.md for the operator runbook.
"""
from __future__ import annotations

import importlib

PROJECT_NAME = "pybluehost_iut"

# Profiles autoptsclient may look up via getattr(autoprojects, <name>).
# SM runs through the GAP BTP service (no dedicated SM service upstream), but
# still needs a profile module to register its test cases — see sm.py.
_PROFILE_MODULES = ("gap", "gatt", "l2cap", "sm", "sdp", "rfcomm")


def __getattr__(name: str):
    if name == "iutctl" or name in _PROFILE_MODULES:
        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
