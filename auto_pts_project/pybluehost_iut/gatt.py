"""GATT profile wiring for autoptsclient (auto-pts master contract)."""
from __future__ import annotations

from auto_pts_project.pybluehost_iut.ixit import IXIT_GATT, apply_pixits, update_pixit
from auto_pts_project.pybluehost_iut.testcase import PyBlueHostTestCase
from auto_pts_project.pybluehost_iut.wid.gatt import gatt_wid_hdl


class Value:
    """Hex-string attribute values used by the GATT server init sequence.

    Mirrors ``autopts.ptsprojects.zephyr.gatt.Value`` so our GATT/SR database
    matches the reference IUT byte-for-byte.
    """

    one_byte_1 = '01'
    one_byte_2 = '02'
    eight_bytes_1 = '0123456789ABCDEF'
    eight_bytes_2 = 'FEDCBA9876543210'
    long_1 = eight_bytes_1 * 4
    long_2 = eight_bytes_2 * 4
    long_3 = eight_bytes_2 * 7
    long_4 = one_byte_1 * 64
    long_5 = eight_bytes_1 * 10
    long_6 = one_byte_2 * 512


def set_pixits(ptses) -> None:
    """Setup GATT PIXITs for the workspace. ptses -- list of PyPTS instances."""
    apply_pixits(ptses[0], "GATT", IXIT_GATT)


def _init_server():
    """Build the GATT *server* database pre-condition sequence.

    GATT/SR (server-role) cases need the IUT to host a populated GATT db so PTS
    can discover / read / write / subscribe against it. Upstream builds this db
    dynamically over BTP (``gatts_add_*``) before each SR case; without it the
    IUT exposes an empty db and every SR case fails. Ported 1:1 from
    ``autopts.ptsprojects.zephyr.gatt.test_cases_server`` ``init_server``.

    autopts symbols are imported lazily so this module imports cleanly on CI
    (no autoptsclient installed).
    """
    from autopts.ptsprojects.testcase import TestFunc
    from autopts.pybtp import btp
    from autopts.pybtp.types import UUID, Perm, Prop

    return [
        TestFunc(btp.gatts_add_svc, 1, UUID.SVND16_0),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write,
                 Perm.read | Perm.write,
                 UUID.VND16_0),
        TestFunc(btp.gatts_set_val, 0, Value.eight_bytes_1),

        # A write-only characteristic (no read bit at all) for the "Read Not
        # Permitted" cases (GAR/BI-01/06/18/36). It must sit BEFORE the
        # security-gated characteristics: hdl_wid_110/111 select the first
        # declaration whose permission lacks Perm.read, and read_enc/read_authn
        # also lack it, so this char must win the handle-order scan.
        TestFunc(btp.gatts_add_char, 0,
                 Prop.write,
                 Perm.write,
                 'AA70'),
        TestFunc(btp.gatts_set_val, 0, Value.eight_bytes_1),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write,
                 Perm.read_enc | Perm.write_enc,
                 UUID.VND16_1),
        TestFunc(btp.gatts_set_val, 0, Value.eight_bytes_1),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write,
                 Perm.read_authn | Perm.write_authn,
                 UUID.VND16_2),
        TestFunc(btp.gatts_set_val, 0, Value.eight_bytes_1),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write,
                 Perm.read_authz | Perm.write_authz,
                 UUID.VND16_3),
        TestFunc(btp.gatts_set_val, 0, Value.eight_bytes_1),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write | Prop.notify | Prop.indicate,
                 Perm.read | Perm.write,
                 UUID.VND16_4),
        TestFunc(btp.gatts_set_val, 0, Value.eight_bytes_1),
        TestFunc(btp.gatts_add_desc, 0,
                 Perm.read | Perm.write,
                 UUID.CCC),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write | Prop.notify | Prop.indicate,
                 Perm.read | Perm.write,
                 UUID.VND16_5),
        TestFunc(btp.gatts_set_val, 0, Value.eight_bytes_1),
        TestFunc(btp.gatts_add_desc, 0,
                 Perm.read | Perm.write,
                 UUID.CCC),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write_wo_resp,
                 Perm.read | Perm.write,
                 UUID.VND16_6),
        TestFunc(btp.gatts_set_val, 0, Value.eight_bytes_1),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write_wo_resp,
                 Perm.read_authn | Perm.write_authn,
                 UUID.VND16_7),
        TestFunc(btp.gatts_set_val, 0, Value.eight_bytes_1),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write | Prop.ext_prop,
                 Perm.read | Perm.write,
                 UUID.VND16_8),
        TestFunc(btp.gatts_set_val, 0, Value.eight_bytes_1),
        TestFunc(btp.gatts_add_desc, 0, Perm.read, UUID.CEP),
        TestFunc(btp.gatts_set_val, 0, '0100'),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write,
                 Perm.read_enc | Perm.write_enc,
                 UUID.VND16_9),
        TestFunc(btp.gatts_set_val, 0, Value.eight_bytes_1),
        TestFunc(btp.gatts_set_enc_key_size, 0, 0x0f),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write,
                 Perm.read_enc | Perm.write_enc,
                 UUID.VND16_10),
        TestFunc(btp.gatts_set_val, 0, Value.eight_bytes_1),
        TestFunc(btp.gatts_set_enc_key_size, 0, 0x0f),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write,
                 Perm.read | Perm.write,
                 UUID.VND128_1),
        TestFunc(btp.gatts_set_val, 0, Value.eight_bytes_1),

        TestFunc(btp.gatts_add_svc, 0, UUID.SVND16_1),
        TestFunc(btp.gatts_add_inc_svc, 1),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write,
                 Perm.read | Perm.write,
                 UUID.VND16_0),
        TestFunc(btp.gatts_set_val, 0, Value.long_1),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write,
                 Perm.read | Perm.write,
                 UUID.VND16_1),
        TestFunc(btp.gatts_set_val, 0, Value.long_2),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write,
                 Perm.read_enc | Perm.write_enc,
                 UUID.VND16_2),
        TestFunc(btp.gatts_set_val, 0, Value.long_3),
        TestFunc(btp.gatts_set_enc_key_size, 0, 0x0f),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read,
                 Perm.read,
                 UUID.VND16_3),
        TestFunc(btp.gatts_set_val, 0, Value.eight_bytes_1 * 10),
        TestFunc(btp.gatts_add_desc, 0,
                 Perm.read | Perm.write,
                 UUID.VND16_4),
        TestFunc(btp.gatts_set_val, 0, Value.long_4),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write,
                 Perm.read | Perm.write,
                 UUID.VND16_5),
        TestFunc(btp.gatts_set_val, 0, Value.long_5),

        TestFunc(btp.gatts_add_char, 0,
                 Prop.read | Prop.write,
                 Perm.read | Perm.write,
                 UUID.VND16_6),
        TestFunc(btp.gatts_set_val, 0, Value.long_6),

        TestFunc(btp.gatts_start_server),
    ]


def _update_service_gas_bv_01():
    """WID 96 post-action for GATT/SR/GAS/BV-01-C.

    The upstream default hdl_wid_96 is a no-op, but this case needs the Service
    Changed indication: after the Lower Tester disconnects, change the database
    so the IUT resends the indication on the reconnect. Mirrors upstream zephyr
    ``update_service_gatt_sr_gas_bv_01_c`` (post_wid=96)."""
    from autopts.pybtp import btp
    btp.gap_wait_for_disconnection(30)
    btp.gatts_change_database(0, 0, 0x02)


def test_cases(ptses):
    """Return a list of GATT test cases. ptses -- list of PyPTS instances."""
    from autopts.client import get_unique_name
    from autopts.ptsprojects.stack import get_stack
    from autopts.ptsprojects.testcase import TestFunc
    from autopts.pybtp import btp
    from autopts.pybtp.types import IOCap, Addr

    pts = ptses[0]
    pts_bd_addr = pts.q_bd_addr
    iut_device_name = get_unique_name(pts)
    stack = get_stack()

    pre_conditions = [
        TestFunc(btp.core_reg_svc_gap),
        TestFunc(stack.gap_init, iut_device_name),
        TestFunc(btp.core_reg_svc_gatt),
        TestFunc(btp.gap_read_controller_info),
        TestFunc(lambda: update_pixit(
            pts, "GATT", "TSPX_bd_addr_iut", stack.gap.iut_addr_get_str)),
        TestFunc(btp.gap_set_io_capability, IOCap.display_only),
        TestFunc(btp.set_pts_addr, pts_bd_addr, Addr.le_public),
        TestFunc(stack.gatt_init),
    ]

    tc_list = []
    for tc_name in pts.get_test_case_list('GATT'):
        # Server-role cases additionally need the populated GATT db; client
        # cases run with the bare pre-conditions (matches upstream routing).
        cmds = list(pre_conditions)
        if tc_name.startswith('GATT/SR'):
            cmds = cmds + _init_server()
        if tc_name == 'GATT/SR/GAS/BV-01-C':
            # The Service Changed indication is driven by a WID 96 db change
            # after the Lower Tester disconnects (upstream zephyr post_wid=96).
            cmds = cmds + [TestFunc(_update_service_gas_bv_01, post_wid=96)]
        tc_list.append(PyBlueHostTestCase(
            'GATT', tc_name, cmds=cmds,
            generic_wid_hdl=gatt_wid_hdl))

    return tc_list
