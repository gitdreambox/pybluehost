"""SMP WID handler adapter for PyBlueHost. Same shape as ``gap.py``."""
from __future__ import annotations

try:
    from wid.sm import sm_wid_hdl as _upstream_sm_wid_hdl
except ImportError:
    _upstream_sm_wid_hdl: dict[int, object] = {}

sm_wid_hdl: dict[int, object] = dict(_upstream_sm_wid_hdl)

PYBLUEHOST_OVERRIDES: list[int] = []
