"""PyBlueHost WID handler adapters — function-style, auto-pts master shape.

Each module exposes ``<profile>_wid_hdl(wid, description, test_case_name)`` and
routes through ``generic_wid_hdl`` with itself first in the search path, so a
locally-defined ``hdl_wid_<N>`` overrides the upstream ``autopts.wid.<profile>``
handler. Baseline: no overrides — upstream handlers cover everything.
"""
