"""L2CAP (LE CoC) profile wiring for autoptsclient (auto-pts master contract)."""
from __future__ import annotations

from auto_pts_project.pybluehost_iut.ixit import IXIT_L2CAP, apply_pixits, update_pixit
from auto_pts_project.pybluehost_iut.testcase import PyBlueHostTestCase
from auto_pts_project.pybluehost_iut.wid.l2cap import l2cap_wid_hdl

# Default LE Credit-Based PSM / initial MTU used when building preconditions.
# Overridden at run time from IXIT via update_pixit_param.
LE_PSM = 0x0080
LE_INITIAL_MTU = 120
PSM_UNSUPPORTED = 0x00F1  # matches upstream zephyr psm_unsupported


def set_pixits(ptses) -> None:
    """Setup L2CAP PIXITs for the workspace. ptses -- list of PyPTS instances."""
    apply_pixits(ptses[0], "L2CAP", IXIT_L2CAP)


def test_cases(ptses):
    """Return a list of L2CAP test cases. ptses -- list of PyPTS instances."""
    from autopts.client import get_unique_name
    from autopts.ptsprojects.stack import get_stack
    from autopts.ptsprojects.testcase import TestFunc
    from autopts.pybtp import btp
    from autopts.pybtp.types import Addr, L2CAPConnectionResponse

    pts = ptses[0]
    pts_bd_addr = pts.q_bd_addr
    iut_device_name = get_unique_name(pts)
    stack = get_stack()

    pre_conditions = [
        TestFunc(btp.core_reg_svc_gap),
        TestFunc(btp.core_reg_svc_l2cap),
        TestFunc(stack.gap_init, iut_device_name),
        TestFunc(btp.gap_read_controller_info),
        TestFunc(lambda: update_pixit(
            pts, "L2CAP", "TSPX_bd_addr_iut", stack.gap.iut_addr_get_str())),
        TestFunc(stack.l2cap_init, LE_PSM, LE_INITIAL_MTU),
        TestFunc(btp.set_pts_addr, pts_bd_addr, Addr.le_public),
        # PTS picks the CoC PSM per test from these PIXITs. If they don't match
        # the PSM our listener is registered on, PTS's LE Credit Based Connection
        # Request lands on a PSM we aren't listening to and the case goes INCONC.
        # Mirror upstream zephyr: point them all at our single LE_PSM.
        TestFunc(lambda: update_pixit(pts, "L2CAP", "TSPX_spsm", format(LE_PSM, '04x'))),
        TestFunc(lambda: update_pixit(
            pts, "L2CAP", "TSPX_psm_authentication_required", format(LE_PSM, '04x'))),
        TestFunc(lambda: update_pixit(
            pts, "L2CAP", "TSPX_psm_authorization_required", format(LE_PSM, '04x'))),
        TestFunc(lambda: update_pixit(
            pts, "L2CAP", "TSPX_psm_encryption_key_size_required", format(LE_PSM, '04x'))),
        TestFunc(lambda: update_pixit(
            pts, "L2CAP", "TSPX_psm_encryption_required", format(LE_PSM, '04x'))),
        TestFunc(lambda: update_pixit(
            pts, "L2CAP", "TSPX_psm_unsupported", format(PSM_UNSUPPORTED, '04x'))),
    ]

    # Upstream zephyr uses pre_conditions_success (= common + l2cap_le_listen)
    # as the DEFAULT for every L2CAP case: the IUT listens on the PSM so it can
    # RESPOND to incoming credit-based connections, not just initiate them.
    # Without this, every "PTS connects a CoC channel to the IUT" case goes
    # INCONC (no listener → no response). Initiator cases are unaffected by the
    # extra listener, so it is safe as the universal default.
    pre_conditions_success = pre_conditions + [
        TestFunc(btp.l2cap_le_listen, LE_PSM, LE_INITIAL_MTU,
                 L2CAPConnectionResponse.success),
    ]
    # Security-responder variants: the LISTEN carries the security level the IUT
    # must demand before accepting an incoming CoC channel. The BTP listener
    # enforces it (rejects the connect with the mapped result code until the
    # link is paired/encrypted sufficiently), forcing PTS to upgrade security.
    pre_conditions_authen = pre_conditions + [
        TestFunc(btp.l2cap_le_listen, LE_PSM, LE_INITIAL_MTU,
                 L2CAPConnectionResponse.insufficient_authentication),
    ]
    pre_conditions_author = pre_conditions + [
        TestFunc(btp.l2cap_le_listen, LE_PSM, LE_INITIAL_MTU,
                 L2CAPConnectionResponse.insufficient_authorization),
    ]
    pre_conditions_keysize = pre_conditions + [
        TestFunc(btp.l2cap_le_listen, LE_PSM, LE_INITIAL_MTU,
                 L2CAPConnectionResponse.insufficient_encryption_key_size),
    ]
    pre_conditions_encryption = pre_conditions + [
        TestFunc(btp.l2cap_le_listen, LE_PSM, LE_INITIAL_MTU,
                 L2CAPConnectionResponse.insufficient_encryption),
    ]

    # K-frame "SDU length = MPS" behavior cases (L2CAP.TS 4.9.3.15, Tables
    # 4.69/4.71): the LT replays rounds with SDU Length in {MPS, MPS−1, MPS+1,
    # MPS×2, MPS×2+1, MTU} and passes only if the IUT never disconnects. All
    # rounds are legal only when the IUT's advertised MTU ≥ MPS−1 (ALT 4A);
    # with the model default MTU=120 < 247−1 the LT takes ALT 4B (no rounds)
    # and aborts ~64 ms after accepting the channel. 512 ≥ 247−1 with margin
    # for MPS×2+1=495 and round 6's SDU Length = 512 == our advertised MTU.
    # The request MTU must also stay inside the range the workspace declares
    # for the IUT (the LT aborts a 512 request against the default
    # cbmtu_max=0x0100 — the same range check that kills BV-22), so the max is
    # aligned per case.
    kframe_mtu_512 = [
        TestFunc(lambda: stack.l2cap.initial_mtu_set(512)),
        TestFunc(lambda: update_pixit(pts, "L2CAP", "TSPX_l2ca_cbmtu_max", "0200")),
    ]

    # Renegotiate MTU — Initiator (BV-22) / Reassembling with MTU = MPS
    # (COS/ECFC/BV-04). Our inbound accept advertises receive MTU 512; the
    # workspace default TSPX_l2ca_cbmtu_max = 0x0100 (256) contradicts it and
    # both Lower Testers abort right after reading our 0x18 ("current MTU
    # above the supported maximum" — on-air: 0x17 in, 0x18 out, 0x13 within
    # ~100 ms). Aligning the PIXIT with what we actually advertise fires
    # TS 4.9.1.15's step-1 short circuit for BV-22 (current MTU == max →
    # Pass) and gives BV-04's LT a legal X range for its MTU = MPS request.
    # Must stay defined in IXIT_L2CAP (update_pixit skips undefined names).
    cbmtu_512 = [
        TestFunc(lambda: update_pixit(pts, "L2CAP", "TSPX_l2ca_cbmtu_max", "0200")),
    ]

    # COS/CED/BI-29 runs 255 connect rounds answered with wrong / duplicate
    # identifiers; each round only completes once the IUT retransmits (Core
    # §4.1 RTX). The default time guard cuts the case off long before the
    # rounds finish — zephyr raises it to 6 minutes.
    bi29_time_guard = [
        TestFunc(lambda: pts.set_pixit("L2CAP", "TSPX_time_guard", "360000")),
    ]

    # Per-case overrides (mirror upstream zephyr custom_test_cases).
    custom = {
        # Connect on the UNSUPPORTED PSM so PTS refuses with 0x0002.
        "L2CAP/LE/CFC/BV-04-C": pre_conditions + [
            TestFunc(lambda: stack.l2cap.psm_set(PSM_UNSUPPORTED)),
        ],
        # Security — Responder cases: listener rejects until link security met.
        # Levels follow the BTP L2CAPConnectionResponse enum, and the expected
        # Result is the TS's, not a guess — see L2CAP.TS Tables 4.57-4.65.
        "L2CAP/LE/CFC/BV-11-C": pre_conditions_authen,
        "L2CAP/LE/CFC/BV-13-C": pre_conditions_author,
        "L2CAP/LE/CFC/BV-15-C": pre_conditions_keysize,
        # BV-25 sits in Table 4.65 (Insufficient *Encryption* -> 0x0008), not in
        # the authentication table: the link is paired but not encrypted, and
        # the PSM demands encryption. Mapping it to authen made us answer
        # 0x0005 while PTS waited for 0x0008.
        "L2CAP/LE/CFC/BV-25-C": pre_conditions_encryption,
        # ECFC twins. Without an explicit mapping these fall back to the plain
        # success listener, ACCEPT PTS's 0x17 request, and PTS waits forever for
        # the refusal it is testing for.
        "L2CAP/ECFC/BV-11-C": pre_conditions_authen,
        "L2CAP/ECFC/BV-13-C": pre_conditions_author,
        "L2CAP/ECFC/BV-15-C": pre_conditions_keysize,
        "L2CAP/ECFC/BV-32-C": pre_conditions_encryption,
        # Renegotiate MPS — Initiator. L2CAP.TS 4.9.1.18 step 1 ends this case
        # with a Pass verdict when TSPX_l2ca_cbmps_min == TSPX_l2ca_cbmps_max,
        # and that is the only reachable route: BTP L2CAP RECONFIGURE carries an
        # MTU only, so auto-pts has no way to ask for an MPS renegotiation at
        # all. Declare one supported MPS, as the reference IUT does.
        "L2CAP/ECFC/BV-24-C": pre_conditions_success + [
            TestFunc(lambda: update_pixit(pts, "L2CAP", "TSPX_l2ca_cbmps_min", "0040")),
            TestFunc(lambda: update_pixit(pts, "L2CAP", "TSPX_l2ca_cbmps_max", "0040")),
        ],
        # K-frame behaviour cases: the MTU must cover the whole round table.
        "L2CAP/ECFC/BV-80-C": pre_conditions_success + kframe_mtu_512,
        "L2CAP/LE/CFC/BV-32-C": pre_conditions_success + kframe_mtu_512,
        "L2CAP/ECFC/BV-22-C": pre_conditions_success + cbmtu_512,
        "L2CAP/COS/ECFC/BV-04-C": pre_conditions_success + cbmtu_512,
        "L2CAP/COS/CED/BI-29-C": pre_conditions_success + bi29_time_guard,
    }

    tc_list = []
    for tc_name in pts.get_test_case_list('L2CAP'):
        cmds = custom.get(tc_name, pre_conditions_success)
        tc_list.append(PyBlueHostTestCase(
            'L2CAP', tc_name, cmds=list(cmds),
            generic_wid_hdl=l2cap_wid_hdl))

    return tc_list
