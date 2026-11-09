"""GAP WID handler adapter for PyBlueHost — function-style, auto-pts master shape.

autoptsclient calls ``gap_wid_hdl(wid, description, test_case_name)``. We route
through ``generic_wid_hdl`` with THIS module first in the search path so any
``hdl_wid_<N>`` defined below overrides upstream, then fall back to
``autopts.wid.gap``. Baseline: no overrides.

To override a WID, define ``def hdl_wid_<N>(params): ...`` in this module
(``params`` is an ``autopts.pybtp.types.WIDParams``).
"""
from __future__ import annotations

try:
    from autopts.wid import generic_wid_hdl
except ImportError:  # autoptsclient not installed (PyBlueHost CI)
    generic_wid_hdl = None

_UPSTREAM_MODULE = "autopts.wid.gap"

# --- PyBlueHost-specific WID overrides (baseline: none) ---
# def hdl_wid_42(params):
#     ...


def hdl_wid_208(params):
    """Please configure the IUT into LE Security Mode 1 Level N and start pairing.

    The security LEVEL named in the description constrains the Pairing Request's
    AuthReq: Level 4 (SC + MITM) needs the MITM bit set — our initiator takes it
    from the global config, which the GAP profile (unlike SM) never enables, so
    the request went out as bonding+SC only and PTS (responding 0x0D with MITM)
    aborted the pairing — Mode 1 Level 4 can never be reached (GAP/SEC/SEM
    INDCSV/FATAL). Level 3 stays unauthenticated: no MITM.
    """
    from autopts.pybtp import btp
    if "Level 4" in params.description:
        btp.gap_set_mitm_on()
    btp.gap_pair()
    return True


def hdl_wid_241(params):
    """Please configures the IUT into LE Security Mode 1 Level 3.

    Level 3 is *authenticated* pairing, so the Pairing Request's AuthReq needs
    the MITM bit. Upstream only sets the io_capability, and the GAP profile
    never enables MITM (unlike SM's pre-conditions), so our Central-role cases
    went out with AuthReq 0x09 while PTS answered 0x0D — PTS then ran Numeric
    Comparison (both sides KeyboardDisplay) while we ran Just Works, and it
    aborted the pairing with "Numeric Comparison Failed" (0x0C).

    Only the initiator is affected: a responder mirrors the peer's AuthReq
    rather than the config, which is why the Peripheral-role twins
    (GAP/SEC/SEM/BV-57) already pass.
    """
    from autopts.pybtp import btp
    from autopts.pybtp.types import IOCap

    btp.gap_set_io_capability(IOCap.keyboard_display)
    btp.gap_set_mitm_on()
    return True


def hdl_wid_143(params):
    """Please confirm that the IUT reports the lost bond to the Upper Tester.

    Upstream waits only 5 s for the BTP BOND_LOST event. GAP/SEC/AUT/BV-22's
    sequence at this point is: LT reconnects to the advertising IUT, answers
    our Security Request with a Pairing Request, and only then does the IUT
    report the lost bond — the LT reconnect alone routinely takes longer than
    5 s on this rig (peripheral-connect flakiness), so the event never made it
    inside the window and the WID answered Cancel. 20 s keeps the semantics
    (wait for the event, pass if it arrives) while absorbing the reconnect
    latency. Client-side wait — no BTP opcode is involved.
    """
    from autopts.pybtp import btp
    from autopts.ptsprojects.stack import get_stack

    btp.gap_wait_for_lost_bond(20)
    return bool(get_stack().gap.bond_lost_ev_data.data)


def hdl_wid_503(params):
    """Please authorize that PTS to read Encrypted Data Key value.

    auto-pts master ships no handler for WID 503 (``No hdl_wid_503 found!``), so
    every GAP/ADV "Encrypted Data" case died with MISSING WID ERROR before the
    procedure ran. The MMI just asks the Upper Tester to let the Lower Tester
    read the Encrypted Data Key characteristic — authorize it.
    """
    return True


def gap_wid_hdl(wid, description, test_case_name):
    if generic_wid_hdl is None:
        raise RuntimeError("autoptsclient is not installed; cannot dispatch GAP WID")
    return generic_wid_hdl(wid, description, test_case_name,
                           [__name__, _UPSTREAM_MODULE])
