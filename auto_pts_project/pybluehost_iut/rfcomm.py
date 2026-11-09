"""RFCOMM profile wiring for autoptsclient (BR/EDR RFCOMM cases).

Mirrors zephyr's ptsprojects/zephyr/rfcomm.py: PIXIT defaults, pre-conditions
(GAP bring-up + RFCOMM service registration), WID adapter delegating to
upstream autopts.wid.rfcomm.
"""
from __future__ import annotations

from auto_pts_project.pybluehost_iut.testcase import PyBlueHostTestCase
from auto_pts_project.pybluehost_iut.wid.rfcomm import rfcomm_wid_hdl


def set_pixits(ptses) -> None:
    """Setup RFCOMM PIXITs + PICS."""
    pts = ptses[0]

    for entry in ("TSPC_ALL",):
        try:
            pts.set_pics("RFCOMM", entry, True)
        except Exception:
            pass

    pts.set_pixit("RFCOMM", "TSPX_time_guard", "180000")
    pts.set_pixit("RFCOMM", "TSPX_use_implicit_send", "TRUE")
    pts.set_pixit("RFCOMM", "TSPX_server_channel_iut", "05")
    pts.set_pixit("RFCOMM", "TSPX_serviceclassid_uuid16", "1101")
    pts.set_pixit("RFCOMM", "TSPX_delete_link_key", "TRUE")


def test_cases(ptses):
    """Return a list of RFCOMM test cases."""
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
        TestFunc(lambda: pts.update_pixit_param(
            "RFCOMM", "TSPX_bd_addr_iut",
            stack.gap.iut_addr_get_str())),
        TestFunc(btp.set_pts_addr, pts_bd_addr, Addr.le_public),
        TestFunc(btp.core_reg_svc_rfcomm),
        TestFunc(stack.rfcomm_init),
        TestFunc(btp.gap_set_io_capability, IOCap.no_input_output),
        TestFunc(btp.gap_set_connectable),
        TestFunc(btp.gap_set_general_discoverable),
    ]

    tc_list = []
    for tc_name in pts.get_test_case_list('RFCOMM'):
        tc_list.append(PyBlueHostTestCase(
            'RFCOMM', tc_name, cmds=list(pre_conditions),
            generic_wid_hdl=rfcomm_wid_hdl))

    return tc_list
