"""SDP profile wiring for autoptsclient (BR/EDR SDP/CL cases).

Mirrors zephyr's ptsprojects/zephyr/sdp.py: PIXIT defaults, per-case
pre-conditions (GAP bring-up + connectable/discoverable so the Lower Tester
can page us), and the WID adapter delegating to upstream autopts.wid.sdp.
"""
from __future__ import annotations

from auto_pts_project.pybluehost_iut.testcase import PyBlueHostTestCase
from auto_pts_project.pybluehost_iut.wid.sdp import sdp_wid_hdl


def set_pixits(ptses) -> None:
    """Setup SDP PIXITs + PICS. ptses -- list of PyPTS instances."""
    pts = ptses[0]

    # PICS: enable the full SDP test selection (roles + operations). The
    # PTS-created workspace starts from the PICSX defaults where both roles
    # are FALSE, which yields an empty test case list.
    for entry in ("TSPC_ALL", "TSPC_SDP_1b_1", "TSPC_SDP_1b_2",
                  "TSPC_SDP_2_1", "TSPC_SDP_2_2", "TSPC_SDP_2_3",
                  "TSPC_SDP_4_1", "TSPC_SDP_4_2", "TSPC_SDP_4_3",
                  "TSPC_SDP_6_1", "TSPC_SDP_6_2", "TSPC_SDP_6_3"):
        try:
            pts.set_pics("SDP", entry, True)
        except Exception:
            pass  # already set / not present in this PTS build

    pts.set_pixit("SDP", "TSPX_security_enabled", "FALSE")
    pts.set_pixit("SDP", "TSPX_delete_link_key", "TRUE")
    pts.set_pixit("SDP", "TSPX_class_of_device_pts", "200404")
    pts.set_pixit("SDP", "TSPX_pin_code", "0000")
    pts.set_pixit("SDP", "TSPX_time_guard", "200000")
    pts.set_pixit("SDP", "TSPX_use_implicit_send", "TRUE")
    pts.set_pixit("SDP", "TSPX_secure_simple_pairing_pass_key_confirmation", "FALSE")

    pts.set_pixit("SDP", "TSPX_sdp_service_search_pattern", "0100")
    pts.set_pixit("SDP", "TSPX_sdp_unsupported_service", "EEEE")
    pts.set_pixit("SDP", "TSPX_sdp_service_data_base_state", "0100")
    pts.set_pixit("SDP", "TSPX_sdp_version_number_list", "0100")
    pts.set_pixit("SDP", "TSPX_sdp_unsupported_attribute_id", "EEEE")


def test_cases(ptses):
    """Return a list of SDP test cases."""
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
        TestFunc(stack.gap_init, iut_device_name),
        TestFunc(btp.gap_read_controller_info),
        TestFunc(btp.core_reg_svc_sdp),
        TestFunc(stack.sdp_init),
        TestFunc(lambda: pts.update_pixit_param(
            "SDP", "TSPX_bd_addr_iut",
            stack.gap.iut_addr_get_str())),
        TestFunc(btp.set_pts_addr, pts_bd_addr, Addr.le_public),
        TestFunc(btp.gap_set_io_capability, IOCap.no_input_output),
        TestFunc(btp.gap_set_connectable),
        TestFunc(btp.gap_set_general_discoverable),
    ]

    tc_list = []
    for tc_name in pts.get_test_case_list('SDP'):
        tc_list.append(PyBlueHostTestCase(
            'SDP', tc_name, cmds=list(pre_conditions),
            generic_wid_hdl=sdp_wid_hdl))

    return tc_list
