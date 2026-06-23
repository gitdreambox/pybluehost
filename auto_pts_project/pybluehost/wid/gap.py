"""GAP WID handler adapter for PyBlueHost.

Strategy: import upstream's GAP WID dispatch dict and override only the WIDs
that need PyBlueHost-specific handling. Baseline P.9: no overrides — stock
BTP semantics cover all GAP WIDs.

When autoptsclient is not installed (e.g. during PyBlueHost's own unit tests),
the upstream import fails gracefully and ``gap_wid_hdl`` is empty.
"""
from __future__ import annotations

try:
    from wid.gap import gap_wid_hdl as _upstream_gap_wid_hdl
except ImportError:
    _upstream_gap_wid_hdl: dict[int, object] = {}

gap_wid_hdl: dict[int, object] = dict(_upstream_gap_wid_hdl)

PYBLUEHOST_OVERRIDES: list[int] = []
"""WID numbers PyBlueHost overrides locally. Empty in P.9 v1."""
