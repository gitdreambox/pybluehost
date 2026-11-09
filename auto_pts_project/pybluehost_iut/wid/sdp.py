"""SDP WID handler adapter for PyBlueHost — same shape as ``gap.py``.

Routes through ``generic_wid_hdl`` with THIS module first in the search path
so any ``hdl_wid_<N>`` defined below overrides upstream, then falls back to
``autopts.wid.sdp`` (which carries the NXP-contributed SDP/CL handlers:
WID 102 BR-connect + search, 6007 attribute request, ...).
"""
from __future__ import annotations

try:
    from autopts.wid import generic_wid_hdl
except ImportError:  # autoptsclient not installed (PyBlueHost CI)
    generic_wid_hdl = None

_UPSTREAM_MODULE = "autopts.wid.sdp"


def sdp_wid_hdl(wid, description, test_case_name):
    if generic_wid_hdl is None:
        raise RuntimeError("autoptsclient is not installed; cannot dispatch SDP WID")
    return generic_wid_hdl(wid, description, test_case_name,
                           [__name__, _UPSTREAM_MODULE])
