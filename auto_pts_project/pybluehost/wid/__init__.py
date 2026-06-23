"""PyBlueHost WID handler adapters.

Each module shadows upstream autoptsclient's per-profile WID dispatch dict
(``wid.gap.gap_wid_hdl``, ``wid.gatt.gatt_wid_hdl``, etc.) and overrides only
the WIDs that need PyBlueHost-specific BTP command sequences. Baseline
(P.9 v1): no overrides — upstream handlers cover everything.
"""
