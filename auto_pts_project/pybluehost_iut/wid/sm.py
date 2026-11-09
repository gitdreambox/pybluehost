"""SM WID handler adapter for PyBlueHost. Same shape as ``gap.py``.

NOTE: the dedicated SM BTP service is deprecated upstream — pairing/bonding is
driven through the GAP service and GAP WIDs. This adapter exists only so an
``hdl_wid_<N>`` override can be added if a stray SM MMI appears; ``sm.py`` is
not wired into the package ``__init__``.
"""
from __future__ import annotations

try:
    from autopts.wid import generic_wid_hdl
except ImportError:  # autoptsclient not installed (PyBlueHost CI)
    generic_wid_hdl = None

_UPSTREAM_MODULE = "autopts.wid.sm"


def hdl_wid_108(params):
    """Please start pairing process.

    Secure-Connections OOB (``/SCOB/``): the test procedure (SM/CEN/SCOB/BV-04-C
    step 1c) requires the IUT's Pairing Request to carry MITM=0 — OOB provides its
    own authentication, so the MITM bit must be clear. Our ``sm.py`` forces
    ``gap_set_mitm_on`` globally for the Passkey-Entry and Numeric-Comparison
    cases; that leaked into SCOB and made our Pairing Request deviate from the
    test's expected format (PTS aborted with INDCSV right after our Public Key).
    Clear MITM for SCOB only — matching the bluez reference, which never sets
    mitm_on — then pair. Legacy OOB (``/OOB/``) already passes with MITM on, so it
    is left untouched, as are all non-OOB cases (delegate to upstream).

    JW reflection (``JW/BI-06``): the test procedure (step 1c) requires the IUT
    Pairing Request to carry Bonding_Flags=00 and MITM=0. Our global mitm_on +
    bondable default sends auth=0x0d (bonding=01, MITM=1), and PTS disconnects
    (0x13) right after our Confirm — before it ever sends the reflected
    LP_CONFIRM_R the test is about. Other JW cases tolerate 0x0d, so scope this
    tightly to BI-06.
    """
    from autopts.pybtp import btp

    name = params.test_case_name or ""
    if "/SCOB/" in name:
        btp.gap_set_mitm_off()
        btp.gap_pair()
        return True
    if "JW/BI-06" in name:
        # SM/CEN/JW/BI-06-C (reflection): the test procedure (step 1c) requires the
        # IUT Pairing Request to carry Bonding_Flags=00 and MITM=0. Our global
        # mitm_on + bondable default sends auth=0x0d (bonding=01, MITM=1), and PTS
        # disconnects (0x13) right after our Confirm — before it ever sends the
        # reflected LP_CONFIRM_R the test is about. Other JW cases tolerate 0x0d,
        # so scope this tightly to BI-06.
        btp.gap_set_bondable_off()
        btp.gap_set_mitm_off()
        btp.gap_pair()
        return True
    # Delegate every other case to upstream's hdl_wid_108 — it special-cases
    # SM/CEN/JW/BV-01-C (bondable_off + mitm_off) and pairs. Shadowing it without
    # delegating silently dropped that and broke JW/BV-01 (regression).
    from autopts.wid import sm as _upstream_sm
    return _upstream_sm.hdl_wid_108(params)


def sm_wid_hdl(wid, description, test_case_name):
    if generic_wid_hdl is None:
        raise RuntimeError("autoptsclient is not installed; cannot dispatch SM WID")
    return generic_wid_hdl(wid, description, test_case_name,
                           [__name__, _UPSTREAM_MODULE])
