"""L2CAP WID handler adapter for PyBlueHost. Same shape as ``gap.py``."""
from __future__ import annotations

try:
    from wid.l2cap import l2cap_wid_hdl as _upstream_l2cap_wid_hdl
except ImportError:
    _upstream_l2cap_wid_hdl: dict[int, object] = {}

l2cap_wid_hdl: dict[int, object] = dict(_upstream_l2cap_wid_hdl)

PYBLUEHOST_OVERRIDES: list[int] = []
