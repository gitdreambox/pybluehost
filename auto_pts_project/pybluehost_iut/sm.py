"""SM profile wiring for autoptsclient (auto-pts master contract).

The dedicated SM BTP service is deprecated upstream — pairing/bonding runs
through the GAP service and GAP/SM WIDs. So this module needs no new BTP
opcodes; it only registers the SM test cases with GAP-service pre-conditions
(io-capability, bondable) so PTS can drive the pairing state machine.

Exposes the two hooks ``setup_project_pixits``/``setup_test_cases`` call via
``getattr(autoprojects, 'sm')``:

- ``set_pixits(ptses)`` — push our IXIT_SMP values into the PTS workspace.
- ``test_cases(ptses)`` — build one PyBlueHostTestCase per enabled SM case.

IO capability is fixed to DisplayOnly and MITM is enabled **per case** (CEN
initiator cases + SM/PER/PKE/BV-05), matching the bluez reference
``autopts/ptsprojects/bluez/sm.py`` behaviour without a global force. Just-Works cases explicitly turn
bondable/MITM off via their WID handlers (upstream ``autopts.wid.sm`` WID 108/110
call ``gap_set_bondable_off``/``gap_set_mitm_off``), so JW still negotiates Just
Works. Passkey-Entry (PKE) cases keep MITM on and, with DisplayOnly, run the
IUT-as-display passkey flow via ``_PtsSmpDelegate.display_passkey`` → BTP
PASSKEY_DISPLAY. OOB and Secure-Connections cases (OOB/SCJW/SCPK/SCOB) remain
out of reach — CSR8510 is BT4.0 (no SC) and OOB data plumbing is not wired.
"""
from __future__ import annotations

from auto_pts_project.pybluehost_iut.ixit import IXIT_SMP, apply_pixits, update_pixit
from auto_pts_project.pybluehost_iut.testcase import PyBlueHostTestCase
from auto_pts_project.pybluehost_iut.wid.sm import sm_wid_hdl

# Fixed IUT legacy-OOB TK, matching the bluez/zephyr reference TSPX_OOB_Data.
# Pre-provisioned for every legacy /OOB/ case so the IUT advertises
# oob_data_flag=1. The both-sides-have-OOB cases (BV-01/02/10/11) overwrite it
# with a fresh random via WID 147; the asymmetric cases (BV-03/04/09/10) never
# issue WID 147 yet require flag=1 (test step 1); BI-01/02 rely on the peer's
# OOB data differing from ours.
_LEGACY_OOB_DATA = "0000000000000000FE12036E5A889F4D"


def set_pixits(ptses) -> None:
    """Setup SM PIXITs for the workspace. ptses -- list of PyPTS instances."""
    apply_pixits(ptses[0], "SM", IXIT_SMP)


def test_cases(ptses):
    """Return a list of SM test cases. ptses -- list of PyPTS instances."""
    from autopts.client import get_unique_name
    from autopts.ptsprojects.stack import get_stack
    from autopts.ptsprojects.testcase import TestFunc
    from autopts.pybtp import btp
    from autopts.pybtp.types import Addr, IOCap

    pts = ptses[0]
    pts_bd_addr = pts.q_bd_addr
    iut_device_name = get_unique_name(pts)
    stack = get_stack()

    pre_conditions = [
        TestFunc(btp.core_reg_svc_gap),
        TestFunc(btp.gap_reset),
        TestFunc(stack.gap_init, iut_device_name),
        TestFunc(btp.gap_read_controller_info),
        TestFunc(btp.gap_set_bondable_on),
        TestFunc(btp.gap_set_io_capability, IOCap.display_only),
        TestFunc(lambda: update_pixit(
            pts, "SM", "TSPX_bd_addr_iut", stack.gap.iut_addr_get_str)),
        TestFunc(btp.set_pts_addr, pts_bd_addr, Addr.le_public),
    ]

    tc_list = []
    for tc_name in pts.get_test_case_list('SM'):
        cmds = list(pre_conditions)
        # MITM is per-case, never global: the responder honors the config, so a
        # shared gap_set_mitm_on leaks into the unauthenticated PER cases
        # (KDU/BV-08, PKE/BV-06 mirror the LT's 0). CEN cases need it for the
        # initiator's PKE/NC requests; SM/PER/PKE/BV-05 is the lone PER case
        # whose response must set MITM against the LT's 0 (SM.TS Table 4.3,
        # v6.1-or-earlier variant — its BV-06 twin requires 0).
        if "/CEN/" in tc_name or tc_name == "SM/PER/PKE/BV-05-C":
            cmds.append(TestFunc(btp.gap_set_mitm_on))
        if "/OOB/" in tc_name:  # legacy OOB only — /SCOB/ does not match "/OOB/"
            cmds.append(TestFunc(btp.gap_oob_legacy_set_data, _LEGACY_OOB_DATA))
        tc_list.append(PyBlueHostTestCase(
            'SM', tc_name, cmds=cmds,
            generic_wid_hdl=sm_wid_hdl))

    return tc_list
