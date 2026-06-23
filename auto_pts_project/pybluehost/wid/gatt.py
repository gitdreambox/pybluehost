"""GATT WID handler adapter for PyBlueHost. Same shape as ``gap.py``."""
from __future__ import annotations

try:
    from wid.gatt import gatt_wid_hdl as _upstream_gatt_wid_hdl
except ImportError:
    _upstream_gatt_wid_hdl: dict[int, object] = {}

gatt_wid_hdl: dict[int, object] = dict(_upstream_gatt_wid_hdl)

PYBLUEHOST_OVERRIDES: list[int] = []
