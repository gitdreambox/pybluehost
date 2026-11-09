"""L2CAP WID handler adapter for PyBlueHost. Same shape as ``gap.py``."""
from __future__ import annotations

try:
    from autopts.wid import generic_wid_hdl
except ImportError:  # autoptsclient not installed (PyBlueHost CI)
    generic_wid_hdl = None

_UPSTREAM_MODULE = "autopts.wid.l2cap"


def l2cap_wid_hdl(wid, description, test_case_name):
    if generic_wid_hdl is None:
        raise RuntimeError("autoptsclient is not installed; cannot dispatch L2CAP WID")
    return generic_wid_hdl(wid, description, test_case_name,
                           [__name__, _UPSTREAM_MODULE])
